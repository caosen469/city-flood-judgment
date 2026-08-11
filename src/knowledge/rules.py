"""Stage 3 rule engine (ADR-0004): deterministic FactBundle extraction +
TerrainRisk production.

Two responsibilities, both pure and unit-testable:

* :func:`extract_fact_bundle` — read the locked contracts
  (:class:`~schemas.observation.Observation`, :class:`~schemas.grounding.GroundedEntity`,
  :class:`~schemas.context.UrbanContext`) and distill them into the typed
  :class:`~schemas.knowledge.FactBundle` the LLM reasons over. Never re-judges
  the image — only extracts already-structured fields (PRD §7.2). The
  ``eligible_types`` list is the rule-layer eligibility gate output: the LLM may
  infer only inside it.
* :func:`produce_terrain_risk` — the **deterministic** TerrainRisk item. Case C
  (same image, different terrain ⇒ different knowledge, PRD §5.3/§7.4) *must*
  hold every run, so this item is always rule-produced (``mechanism=rule``,
  locked by the schema). Fires iff water is present and the terrain block
  resolved a trigger lowness class (``moderately_low``+, ADR-0004 Q12).

This module imports only the committed schemas — it does not depend on the
Stage 2 implementations (grounding/context), so it composes with whatever
produces the contracts.
"""

from __future__ import annotations

from typing import Optional

from schemas.context import (
    Availability,
    ContextBlock,
    LownessClass,
    UrbanContext,
)
from schemas.grounding import GroundedEntity, GroundingStatus
from schemas.knowledge import (
    Confidence,
    ContextRef,
    DerivedRef,
    EvidenceRef,
    FactBundle,
    GroundingFacts,
    InferenceMechanism,
    KnowledgeType,
    ObservationFacts,
    ObservationRef,
    RoadFacts,
    TerrainFacts,
    TerrainRiskKnowledge,
    WaterloggingStatus,  # re-exported for convenience
    terrain_risk_eligible,
)
from schemas.observation import Observation, WaterloggingLevel

# Rule id stamped on the TerrainRisk item (mechanism=rule ⇒ rule_id required).
TERRAIN_RISK_RULE_ID = "terrain_risk_low_lying"

# Confidence per trigger class: the deeper the composite low, the more certain
# the ponding-risk signal (ADR-0004 Q12 — moderately_low is the floor).
_TERRAIN_CONFIDENCE: dict[LownessClass, Confidence] = {
    LownessClass.MODERATELY_LOW: Confidence.MEDIUM,
    LownessClass.SIGNIFICANTLY_LOW: Confidence.HIGH,
}

# zh labels for the statement template (kept inline — only two classes trigger).
_LOWNESS_ZH: dict[LownessClass, str] = {
    LownessClass.MODERATELY_LOW: "中度",
    LownessClass.SIGNIFICANTLY_LOW: "显著",
}


# --------------------------------------------------------------------------- #
# Block accessors — tolerate missing/unavailable blocks (Case D/F).            #
# --------------------------------------------------------------------------- #


def _available_block(
    context: Optional[UrbanContext], block_type: str
) -> Optional[ContextBlock]:
    """Return the block if it exists and is ``available``; else ``None``.

    Per ADR-0002 a block always appears (status + reason say so when missing),
    so the knowledge layer treats anything not ``available`` as absent for
    inference purposes — eligibility gates close (Case D/F)."""
    if context is None:
        return None
    block = context.block(block_type)
    if block is None:
        return None
    return block if block.availability.status is Availability.AVAILABLE else None


def _terrain_class(context: Optional[UrbanContext]) -> Optional[LownessClass]:
    """The resolved lowness class, or ``None`` when the terrain block is
    unavailable / has insufficient data (closes the TerrainRisk gate)."""
    block = _available_block(context, "terrain")
    if block is None:
        return None
    klass = block.lowness.lowness_class  # type: ignore[attr-defined]
    if klass is LownessClass.INSUFFICIENT_DATA:
        return None
    return klass


def _terrain_composite(context: Optional[UrbanContext]) -> Optional[float]:
    block = _available_block(context, "terrain")
    if block is None:
        return None
    return block.lowness.composite  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# extract_fact_bundle                                                          #
# --------------------------------------------------------------------------- #


def _has_depth_estimate(obs: Observation) -> bool:
    d = obs.waterlogging.depth_estimate.depth_cm
    return d.min is not None or d.max is not None or d.most_likely is not None


def extract_fact_bundle(
    observation: Observation,
    grounding: Optional[GroundedEntity],
    context: Optional[UrbanContext],
) -> FactBundle:
    """Distill (Observation, Grounding, UrbanContext) into a typed FactBundle.

    Pure function: no I/O, no LLM, fully deterministic. The eligibility gates
    populate ``eligible_types`` — the LLM may infer only within that set.
    """
    wl = observation.waterlogging

    observation_facts = ObservationFacts(
        status=wl.status,
        waterlogging_level=wl.waterlogging_level,
        presence_probability=observation.presence_probability,
        visual_impact_hint=wl.visual_impact_hint,
        has_depth_estimate=_has_depth_estimate(observation),
    )

    best = grounding.best_match if grounding is not None else None
    grounding_facts = GroundingFacts(
        status=grounding.status.value if grounding is not None else "unresolved",
        highway=best.highway if best is not None else None,
        is_bridge=best.bridge if best is not None else None,
        is_tunnel=best.tunnel if best is not None else None,
        offset_distance_m=best.match_distance_m if best is not None else None,
    )

    terrain_class = _terrain_class(context)
    terrain_facts = TerrainFacts(
        available=terrain_class is not None,
        lowness_class=terrain_class,
        composite_tpi_m=_terrain_composite(context),
    )

    road_block = _available_block(context, "road")
    road_facts = RoadFacts(
        available=road_block is not None,
        highway_class=road_block.highway_class if road_block is not None else None,  # type: ignore[union-attr]
        lanes=road_block.lanes if road_block is not None else None,  # type: ignore[union-attr]
        is_bridge=road_block.is_bridge if road_block is not None else None,  # type: ignore[union-attr]
        is_tunnel=road_block.is_tunnel if road_block is not None else None,  # type: ignore[union-attr]
    )

    # Eligibility gates (ADR-0004 rule table).
    eligible: list[KnowledgeType] = []
    if terrain_risk_eligible(observation_facts.status, terrain_class):
        eligible.append(KnowledgeType.TERRAIN_RISK)
    if (
        observation_facts.status is WaterloggingStatus.PRESENT
        and grounding is not None
        and grounding.status in {GroundingStatus.GROUNDED, GroundingStatus.AMBIGUOUS}
        and road_facts.available
    ):
        eligible.append(KnowledgeType.ROAD_IMPACT)

    return FactBundle(
        observation=observation_facts,
        grounding=grounding_facts,
        terrain=terrain_facts,
        road=road_facts,
        eligible_types=eligible,
    )


# --------------------------------------------------------------------------- #
# TerrainRisk — the deterministic rule product (Case C).                       #
# --------------------------------------------------------------------------- #


def produce_terrain_risk(bundle: FactBundle) -> Optional[TerrainRiskKnowledge]:
    """Emit the TerrainRisk item iff the gate is open (rule, deterministic).

    Returns ``None`` when ``terrain_risk`` is not eligible — Case D (missing /
    insufficient terrain) and "no water" both close the gate. ``mechanism`` is
    locked to ``rule`` by the schema; Case C determinism lives here.
    """
    if KnowledgeType.TERRAIN_RISK not in bundle.eligible_types:
        return None

    klass = bundle.terrain.lowness_class
    assert klass is not None  # eligible ⇒ trigger class present
    composite = bundle.terrain.composite_tpi_m

    composite_str = f"{composite:.2f}" if composite is not None else "未知"
    statement = (
        f"积水发生{_LOWNESS_ZH.get(klass, '')}低洼位置：多尺度 TPI composite "
        f"约 {composite_str} m（正值表示比周边明显偏低），符合易于积水/汇水的"
        "低洼地形特征。"
    )

    evidence: list[EvidenceRef] = [
        ContextRef(
            block_type="terrain",
            field_path="lowness.composite",
            note=f"terrain 块低洼分级 {klass.value}（composite {composite_str} m）。",
        ),
        ObservationRef(
            field_path="waterlogging.status",
            note="Observation 判定存在积水（status=present）。",
        ),
        DerivedRef(
            rule_id=TERRAIN_RISK_RULE_ID,
            value=f"eligible:class={klass.value}",
            inputs=[],
            note="规则：有水 且 terrain 低洼分级 ∈ {moderately_low, significantly_low}。",
        ),
    ]

    return TerrainRiskKnowledge(
        statement=statement,
        confidence=_TERRAIN_CONFIDENCE.get(klass, Confidence.MEDIUM),
        mechanism=InferenceMechanism.RULE,
        rule_id=TERRAIN_RISK_RULE_ID,
        evidence=evidence,
        lowness_class=klass,
        composite_tpi_m=composite,
    )
