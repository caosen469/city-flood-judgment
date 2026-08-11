"""Canonical Knowledge Engine contract (Pydantic v2) for the city-waterlogging demo.

This module is the *contract* between the rule engine, the LLM-assisted inference
step, and the Pipeline. It encodes the decisions recorded in ADR-0004 and on
wayfinder ticket #7 (Knowledge Engine 推理解析设计):

* ``KnowledgeResult`` is a **composition** of typed ``KnowledgeItem``s plus a
  single composite ``EventAssessment`` — the same composition pattern ADR-0002
  chose for Urban Context (a ``blocks`` list + discriminated ``block_type``).
  New knowledge types extend as new item subclasses under a fresh
  ``knowledge_type`` literal; the root never changes shape. Every item carries
  its own ``evidence`` (PRD §3.6-34, Case H).

* **Hybrid inference, LLM-assisted** (PRD §7.2, ticket Q2): a deterministic
  **rule engine** extracts a typed ``FactBundle`` from (Observation, Grounding,
  UrbanContext) and produces the threshold-driven ``TerrainRiskKnowledge``
  (Case-C-critical, must be deterministic); an **LLM** infers
  ``RoadImpactKnowledge`` and the ``EventAssessment`` composite over that fact
  bundle, schema-whitelisted to the allowed ``knowledge_type`` literals. The LLM
  may join the inference step — but only over rule-extracted, grounded facts,
  never re-judging the visual Observation (ticket Q4 labor split).

* **Evidence is a typed discriminated union** (``EvidenceRef``): observation /
  grounding / context / derived. A ``context_ref`` inherits the block's existing
  ``Provenance`` rather than duplicating it. Each item's ``evidence`` is
  non-empty (validator) — PRD Case H traceability.

* **Forbidden knowledge is blocked three ways** (PRD §4.12/§4.13, Case G;
  ticket Q7): (1) structural — ``KnowledgeType`` is a closed whitelist, so
  "排水管网堵塞" / "暴雨导致" have no type to inhabit; (2) eligibility gate — a
  type is generable only when its required data is present (Case D: terrain
  unavailable → no TerrainRisk; Case F: grounding unresolved → no RoadImpact);
  (3) post-validation — every emitted item must carry valid evidence refs or it
  is dropped.

* **"unknown by value"** (ADR-0001 rule): required keys always appear; absence is
  expressed by ``severity = uncertain`` / nullable numbers / empty lists.

The rule-engine eligibility thresholds and the RoadImpact level scale live here
as module constants so the rule layer (future ``src/knowledge/``) and tests
reference one source of truth. This file contains *only* the data contract +
thresholds, not the inference implementation.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from .context import HighwayClass, LownessClass
from .observation import (
    Confidence,
    VisualImpactHint,
    WaterloggingLevel,
    WaterloggingStatus,
)


# =========================================================================== #
# Enums — canonical values are language-neutral codes.                         #
# zh-CN display labels live in display_labels.py (see ADR-0001 convention).    #
# =========================================================================== #


class KnowledgeType(str, Enum):
    """Closed whitelist of generable knowledge types — the first layer of the
    Case-G guardrail. A new knowledge assertion can only exist if its type is
    listed here. v1 ships terrain risk + road impact; future types (when more
    Context sources arrive, PRD §4.9) join as sibling items."""

    TERRAIN_RISK = "terrain_risk"
    ROAD_IMPACT = "road_impact"


class InferenceMechanism(str, Enum):
    """How a knowledge assertion was produced — recorded per item so the
    Evidence Chain can tell a hard rule product from an LLM judgement (PRD
    §4.16 traceability). TerrainRisk is always ``rule`` (Case C determinism);
    RoadImpact / EventAssessment are ``llm`` by default."""

    RULE = "rule"
    LLM = "llm"


class EvidenceRefType(str, Enum):
    """The four evidence provenances a KnowledgeItem can cite (PRD §4.6)."""

    OBSERVATION = "observation"  # a field of the visual Observation
    GROUNDING = "grounding"  # a field of the GroundedEntity
    CONTEXT = "context"  # a ContextBlock field (inherits block Provenance)
    DERIVED = "derived"  # a rule-computed intermediate value


class RoadActor(str, Enum):
    """The three road-user classes the legacy ``traffic_risk`` split impact over
    (ticket Q3 sub-question). Retained for output continuity."""

    PEDESTRIAN = "pedestrian"
    NON_MOTOR_VEHICLE = "non_motor_vehicle"
    MOTOR_VEHICLE = "motor_vehicle"


class RoadImpactLevel(str, Enum):
    """Per-actor impact grade. Matches the legacy ``waterlogging.py``
    ``traffic_risk`` 5-level scale (低/中/高/严重/无法判断) for output
    continuity (ticket Q9)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SEVERE = "severe"
    UNCERTAIN = "uncertain"  # unknown sentinel


class EventSeverity(str, Enum):
    """Composite event tier (PRD §4.11). Uses Observation + Context, not image
    alone — this is where city knowledge truly participates in event
    understanding. ``uncertain`` is the unknown sentinel."""

    ORDINARY_PUDDLE = "ordinary_puddle"
    SUSPECTED_FLOOD_SIGNIFICANT = "suspected_flood_significant"
    UNCERTAIN = "uncertain"


# =========================================================================== #
# Rule-engine constants — single source of truth for thresholds.               #
# =========================================================================== #


#: Lowness tiers that trigger TerrainRisk (ticket Q12). ``moderately_low`` and
#: above only (composite TPI >= 1.0 m): at 30 m SRTM resolution the sub-metre
#: ``slightly_low`` band (0.3–1.0 m) is too noisy to call a ponding-risk signal,
#: so it is recorded in evidence but does not raise a risk item.
TERRAIN_RISK_CLASSES: frozenset[LownessClass] = frozenset(
    {
        LownessClass.MODERATELY_LOW,
        LownessClass.SIGNIFICANTLY_LOW,
    }
)


def terrain_risk_eligible(
    obs_status: WaterloggingStatus, terrain_class: Optional[LownessClass]
) -> bool:
    """Rule-engine eligibility gate for ``TerrainRiskKnowledge`` (Case D, Q12).

    Fires only when water is present AND the terrain block resolved a low-lying
    class in the trigger set. A ``None`` class (terrain block
    ``insufficient_data`` / unavailable) closes the gate — no TerrainRisk is
    generated, satisfying PRD Case D ("do not generate knowledge that depends on
    missing context").
    """
    return obs_status is WaterloggingStatus.PRESENT and terrain_class in TERRAIN_RISK_CLASSES


# =========================================================================== #
# Evidence references — discriminated union by ref_type.                       #
# =========================================================================== #


class _EvidenceRefBase(BaseModel):
    """Common field for every evidence reference. ``note`` is the human-readable
    basis string shown in the Evidence Chain (PRD §4.14)."""

    note: str = Field(default="", description="该依据的人类可读说明，供 Evidence Chain 展示。")


class ObservationRef(_EvidenceRefBase):
    """Points at a field of the visual ``Observation`` (e.g. the depth grade)."""

    ref_type: Literal[EvidenceRefType.OBSERVATION] = EvidenceRefType.OBSERVATION
    field_path: str = Field(
        description="Observation 内字段路径，如 waterlogging.waterlogging_level"
    )


class GroundingRef(_EvidenceRefBase):
    """Points at a field of the ``GroundedEntity`` (e.g. matched highway)."""

    ref_type: Literal[EvidenceRefType.GROUNDING] = EvidenceRefType.GROUNDING
    field_path: str = Field(
        description="GroundedEntity 内字段路径，如 best_match.highway / status"
    )


class ContextRef(_EvidenceRefBase):
    """Points at a ``ContextBlock`` field. The block's own ``Provenance``
    (``source`` / ``data_vintage`` / ``retrieved_at``) is inherited transitively
    — it is NOT duplicated here, so provenance has one source of truth."""

    ref_type: Literal[EvidenceRefType.CONTEXT] = EvidenceRefType.CONTEXT
    block_type: str = Field(description="ContextBlock 的 block_type，如 road / elevation / terrain")
    field_path: str = Field(description="该 block 内字段路径，如 lowness.composite")


class DerivedRef(_EvidenceRefBase):
    """A rule-computed intermediate value, pointing back at its inputs. Used when
    a rule combines inputs into a derived figure not already stored on a block."""

    ref_type: Literal[EvidenceRefType.DERIVED] = EvidenceRefType.DERIVED
    rule_id: str
    value: str
    inputs: list[EvidenceRef] = Field(
        default_factory=list, description="该派生值的输入依据（递归 EvidenceRef）"
    )


#: Discriminated union — the only way to cite evidence. New provenances join as
#: a new ref subclass with a fresh ``ref_type`` literal.
EvidenceRef = Annotated[
    Union[ObservationRef, GroundingRef, ContextRef, DerivedRef],
    Field(discriminator="ref_type"),
]


# =========================================================================== #
# Knowledge items — discriminated union by knowledge_type.                     #
# =========================================================================== #


class _KnowledgeItemCommon(BaseModel):
    """Fields shared by every KnowledgeItem. Sub-types add a ``knowledge_type``
    literal + a type-specific payload."""

    statement: str = Field(
        description="该断言的自然语言陈述。规则项为模板化输出，LLM 项为生成文本。"
    )
    confidence: Confidence
    mechanism: InferenceMechanism
    rule_id: Optional[str] = Field(
        default=None, description="当 mechanism=rule 时必填，标识产出该 item 的规则。"
    )
    evidence: list[EvidenceRef] = Field(
        min_length=1, description="≥1 条依据（PRD Case H）；后校验会丢弃无有效依据的 item。"
    )

    @model_validator(mode="after")
    def _mechanism_consistency(self) -> "_KnowledgeItemCommon":
        if self.mechanism is InferenceMechanism.RULE and not self.rule_id:
            raise ValueError("rule_id is required when mechanism is 'rule'.")
        return self


class TerrainRiskKnowledge(_KnowledgeItemCommon):
    """"积水发生在低洼位置" — Observation(有水) × TerrainContextBlock(低洼).

    THE Case-C knowledge item: the same image at a low-lying point vs a flat
    point must produce a TerrainRisk here vs not — so this item is **always
    rule-produced** (mechanism locked to ``rule``). An LLM may never override
    whether this fires; that determinism is what proves the Knowledge Engine did
    real work rather than rephrasing the VLM (PRD §5.3 Case C, §7.4).
    """

    knowledge_type: Literal[KnowledgeType.TERRAIN_RISK] = KnowledgeType.TERRAIN_RISK
    mechanism: InferenceMechanism = InferenceMechanism.RULE  # locked (Case C)
    lowness_class: LownessClass = Field(description="触发本项的低洼分级（来自 TerrainContextBlock）")
    composite_tpi_m: Optional[float] = Field(
        default=None, description="触发时的多尺度 TPI composite（米，正值=比周边低）。"
    )

    @model_validator(mode="after")
    def _must_be_rule(self) -> "TerrainRiskKnowledge":
        if self.mechanism is not InferenceMechanism.RULE:
            raise ValueError(
                "TerrainRiskKnowledge must be rule-produced (mechanism='rule') — "
                "Case C determinism depends on it."
            )
        if self.lowness_class not in TERRAIN_RISK_CLASSES:
            raise ValueError(
                f"lowness_class {self.lowness_class.value} is below the "
                "TerrainRisk trigger threshold (moderately_low+)."
            )
        return self


class RoadActorImpact(BaseModel):
    """One road-user class × its impact grade (legacy traffic_risk shape)."""

    actor: RoadActor
    level: RoadImpactLevel = RoadImpactLevel.UNCERTAIN


class RoadImpactKnowledge(_KnowledgeItemCommon):
    """"对该道路通行有 [N] 影响" — Observation(深度/影响提示) × RoadContextBlock.

    Replaces the legacy ``traffic_risk`` (moved out of Observation by ADR-0001),
    now grounded in real road attributes rather than free judgement. Produced by
    the LLM over the rule-extracted ``FactBundle`` (mechanism ``llm`` by
    default). Eligibility gate requires a grounded road (Case F: unresolved
    grounding → not generated).
    """

    knowledge_type: Literal[KnowledgeType.ROAD_IMPACT] = KnowledgeType.ROAD_IMPACT
    impacts: list[RoadActorImpact] = Field(
        min_length=1, description="≥1 个 road-user class 的影响等级。"
    )


#: Discriminated union — the closed whitelist of generable items (Case G guard).
KnowledgeItem = Annotated[
    Union[TerrainRiskKnowledge, RoadImpactKnowledge],
    Field(discriminator="knowledge_type"),
]


# =========================================================================== #
# Event Assessment — the single composite roll-up (PRD §4.11).                 #
# =========================================================================== #


class EventAssessment(BaseModel):
    """The composite event tier — higher-order than any single KnowledgeItem.
    Stored apart from the raw Observation (PRD §3.5-27) so inference logic can
    be adjusted without regenerating Observation. Produced by the LLM over the
    full FactBundle + already-generated items; always eligible (may be
    ``uncertain``)."""

    severity: EventSeverity
    confidence: Confidence
    mechanism: InferenceMechanism = InferenceMechanism.LLM
    reasoning: str = Field(
        description="为何定到该 tier 的自然语言说明，须基于已生成 items + fact bundle。"
    )
    evidence: list[EvidenceRef] = Field(min_length=1)


# =========================================================================== #
# Fact bundle — the rule-engine extraction handed to the LLM.                  #
# =========================================================================== #


class ObservationFacts(BaseModel):
    """The visual facts the LLM may reason over — extracted, never re-judged."""

    status: WaterloggingStatus
    waterlogging_level: WaterloggingLevel
    presence_probability: float = Field(ge=0.0, le=1.0)
    visual_impact_hint: VisualImpactHint
    has_depth_estimate: bool = Field(
        description="是否存在可靠尺寸参照下的深度估算（非 null depth）。"
    )


class GroundingFacts(BaseModel):
    """Grounding outcome relevant to inference. ``status`` drives the RoadImpact
    eligibility gate (Case F)."""

    status: str = Field(description="GroundingStatus 值：grounded / ambiguous / unresolved")
    highway: Optional[str] = Field(default=None, description="匹配路段的 OSM highway tag")
    is_bridge: Optional[bool] = None
    is_tunnel: Optional[bool] = None
    offset_distance_m: Optional[float] = None


class TerrainFacts(BaseModel):
    """Terrain block summary. ``available=False`` or a non-trigger class closes
    the TerrainRisk gate (Case D)."""

    available: bool
    lowness_class: Optional[LownessClass] = None
    composite_tpi_m: Optional[float] = None


class RoadFacts(BaseModel):
    """Road block summary. ``available=False`` (Case F) closes the RoadImpact
    gate."""

    available: bool
    highway_class: Optional[HighwayClass] = None
    lanes: Optional[int] = None
    is_bridge: Optional[bool] = None
    is_tunnel: Optional[bool] = None


class FactBundle(BaseModel):
    """The deterministic, typed extraction the rule engine builds from
    (Observation, Grounding, UrbanContext) and hands to the LLM. The LLM reasons
    ONLY over these grounded fields, never re-judging the image (PRD §7.2).
    ``eligible_types`` is the gate output: the LLM may infer only within the
    types the rules have opened."""

    observation: ObservationFacts
    grounding: GroundingFacts
    terrain: TerrainFacts
    road: RoadFacts
    eligible_types: list[KnowledgeType] = Field(
        default_factory=list,
        description="资格门输出。LLM 只能在这些类型内推断；不在此列的类型不得生成。",
    )


# =========================================================================== #
# Root result                                                                 #
# =========================================================================== #


class KnowledgeResult(BaseModel):
    """The Knowledge Engine's output for one image (PRD §4.10/§4.12).

    A list of typed items + one composite Event Assessment + one LLM-rendered
    explanation. The explanation is generated FROM the structured chain, never
    reverse-fabricated from the conclusion (PRD §4.14). Items appear even when
    their underlying context was unavailable — they are simply absent from the
    list, and the Event Assessment / explanation say so (Case D/F).
    """

    knowledge_items: list[KnowledgeItem] = Field(default_factory=list)
    event_assessment: EventAssessment
    explanation: str = Field(
        description="LLM 渲染的整条 Evidence Chain 自然语言叙述（基于 chain 生成，不得反向编造）。"
    )


# Resolve the recursive ``DerivedRef.inputs -> EvidenceRef`` forward reference
# now that ``EvidenceRef`` is defined at module scope.
DerivedRef.model_rebuild()
