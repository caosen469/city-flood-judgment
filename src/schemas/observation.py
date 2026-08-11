"""Canonical Observation schema (Pydantic v2) for the city-waterlogging demo.

This module is the *contract* between the VLM (Qwen3-VL), the pipeline, and the
Knowledge Engine. It encodes the decisions recorded in ADR-0001 and on
wayfinder ticket #4:

* One ``Observation`` per image;积水区域 / 参照物 / 证据 are nested arrays.
* A ``phenomenon_type`` discriminator + a typed ``waterlogging`` sub-block, so
  future city-event types extend as sibling sub-blocks.
* Observation holds only what is *visible*; contextual impact (``traffic_risk``)
  belongs to the Knowledge Engine's Inference layer — not here.
* "unknown" is expressed by value, never by a missing key: enums carry an
  explicit sentinel, numbers go nullable, lists default to empty.
* Confidence: an observation-level roll-up + depth-estimate confidence +
  per-item ``reliability`` on reference objects / evidence.

The VLM fills ``phenomenon_type``, ``overall_confidence``, ``presence_probability``,
``waterlogging`` and ``observed_summary``. The ``meta`` block is stamped by the
pipeline (never produced by the model). See ``observation_schema.md`` for the
narrative spec and ``display_labels.py`` for the zh-CN display labels.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# =========================================================================== #
# Enums — canonical values are language-neutral codes.                         #
# zh-CN display labels live in display_labels.py.                             #
# =========================================================================== #


class PhenomenonType(str, Enum):
    """Top-level discriminator. v1 ships only road waterlogging; future city
    event types (icing, subsidence, …) extend here and gain a sibling sub-block."""

    ROAD_WATERLOGGING = "road_waterlogging"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Likelihood(str, Enum):
    """Used for per-item reliability and alternative-explanation likelihood."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WaterloggingStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNCERTAIN = "uncertain"  # unknown sentinel for status


class WaterloggingLevel(str, Enum):
    """Visual depth grade (visual estimate only, not a field measurement)."""

    L0 = "L0"  # no water / only slight dampness
    L1 = "L1"  # ~0–3 cm
    L2 = "L2"  # ~3–10 cm
    L3 = "L3"  # ~10–20 cm
    L4 = "L4"  # ~20–30 cm
    L5 = "L5"  # >30 cm
    LX = "LX"  # suspected water, depth not estimable (unknown sentinel)


class SurfaceCondition(str, Enum):
    DRY = "dry"
    WET = "wet"
    SUSPECTED_WATER = "suspected_water"
    CLEAR_WATER = "clear_water"
    UNKNOWN = "unknown"  # unknown sentinel


class ReflectionType(str, Enum):
    WATER_REFLECTION = "water_reflection"
    WET_ROAD_GLARE = "wet_road_glare"
    LIGHT_GLARE = "light_glare"
    SHADOW = "shadow"
    LENS_ARTIFACT = "lens_artifact"
    UNKNOWN = "unknown"


class PatchCoverage(str, Enum):
    LOCALIZED = "localized"
    MODERATE = "moderate"
    EXTENSIVE = "extensive"
    UNKNOWN = "unknown"


class VisualImpactHint(str, Enum):
    """Purely visual, descriptive impact hint — distinct from the Knowledge
    Engine's contextual ``traffic_risk`` Inference."""

    NONE = "none"  # no visible impact (dry / trivial)
    MINOR = "minor"  # e.g. a curb puddle
    OBSTRUCTING = "obstructing"  # water covers roadway features / markings
    SUBMERGING = "submerging"  # reaches vehicle / pedestrian undercarriage
    UNCLEAR = "unclear"  # cannot tell


# =========================================================================== #
# Meta block — pipeline-stamped, never produced by the VLM.                    #
# =========================================================================== #


class LocationRef(BaseModel):
    """Passthrough location attached to an image. Populated from image EXIF /
    demo input — **never** from VLM world knowledge. Resolving it to a real
    road is the job of the Grounding step (ticket #5), not the model."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    road_name: Optional[str] = None
    raw_text: Optional[str] = None


class ObservationMeta(BaseModel):
    observation_id: str
    source_image: str  # path / url / ref
    observed_at: datetime
    source_location: Optional[LocationRef] = None  # passthrough; may be unresolved


# =========================================================================== #
# Waterlogging sub-block — typed under the phenomenon discriminator.           #
# =========================================================================== #


class DepthCm(BaseModel):
    """All fields nullable: unknown depth is expressed as ``None``, never by
    omitting the object. Fill only when a reliable size reference exists."""

    min: Optional[float] = Field(default=None, ge=0)
    max: Optional[float] = Field(default=None, ge=0)
    most_likely: Optional[float] = Field(default=None, ge=0)


class DepthEstimate(BaseModel):
    depth_cm: DepthCm = Field(default_factory=DepthCm)
    confidence: Confidence = Confidence.LOW


class WaterPatch(BaseModel):
    """One distinct积水区域 in the frame. An image may contain several."""

    patch_id: str
    location_in_frame: str = Field(description="画面位置/范围的自然语言描述")
    coverage: PatchCoverage = PatchCoverage.UNKNOWN
    waterlogging_level: WaterloggingLevel = WaterloggingLevel.LX
    depth_cm: DepthCm = Field(default_factory=DepthCm)


class VisualCues(BaseModel):
    """Low-level visual signals from the current ``scene_observations`` block."""

    reflection_present: bool = False
    reflection_type: ReflectionType = ReflectionType.UNKNOWN
    visible_water_boundary: bool = False
    visible_waterline: bool = False
    visible_ripple_or_wave: bool = False


class ReferenceObject(BaseModel):
    object: str
    known_size: str = "unknown"
    relation_to_water: str = ""
    reliability: Likelihood = Likelihood.LOW


class VisualEvidence(BaseModel):
    evidence: str
    supports: str = Field(description="支持存在/不存在积水，或某一深度等级")
    reliability: Likelihood = Likelihood.LOW


class AlternativeExplanation(BaseModel):
    possibility: str
    likelihood: Likelihood = Likelihood.LOW
    reason: str = ""


class WaterloggingAttributes(BaseModel):
    """Waterlogging-specific visual attributes. Sits under ``Observation.waterlogging``
    keyed to ``phenomenon_type == road_waterlogging``."""

    status: WaterloggingStatus = WaterloggingStatus.UNCERTAIN
    waterlogging_level: WaterloggingLevel = WaterloggingLevel.LX
    depth_estimate: DepthEstimate = Field(default_factory=DepthEstimate)
    water_patches: list[WaterPatch] = Field(default_factory=list)
    surface_condition: SurfaceCondition = SurfaceCondition.UNKNOWN
    visual_cues: VisualCues = Field(default_factory=VisualCues)
    reference_objects: list[ReferenceObject] = Field(default_factory=list)
    visual_impact_hint: VisualImpactHint = VisualImpactHint.UNCLEAR
    visual_evidence: list[VisualEvidence] = Field(default_factory=list)
    alternative_explanations: list[AlternativeExplanation] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _absent_implies_l0(self) -> "WaterloggingAttributes":
        """If no water is present, the depth grade must be L0."""
        if self.status is WaterloggingStatus.ABSENT and self.waterlogging_level is not WaterloggingLevel.L0:
            raise ValueError(
                "waterlogging_level must be L0 when status is 'absent'."
            )
        return self


# =========================================================================== #
# Observation — one per image.                                                 #
# =========================================================================== #


class Observation(BaseModel):
    """Structured visual observation for one image. See ADR-0001."""

    meta: Optional[ObservationMeta] = None  # pipeline-stamped; absent in raw VLM output
    phenomenon_type: Literal[PhenomenonType.ROAD_WATERLOGGING] = (
        PhenomenonType.ROAD_WATERLOGGING
    )
    overall_confidence: Confidence = Confidence.LOW
    presence_probability: float = Field(ge=0.0, le=1.0, default=0.0)
    waterlogging: WaterloggingAttributes = Field(default_factory=WaterloggingAttributes)
    visible_location_text: Optional[str] = Field(
        default=None,
        description=(
            "画面中 OSD/水印/招牌等地名的原文抄录（VLM 仅照抄可见文字，看不到则留空 "
            "null）。这是 Grounding（ADR-0003）的一个候选位置线索——pipeline 负责把它"
            "搬进 meta.source_location.raw_text；本字段本身不做任何地理推断，也不来自"
            "模型世界知识。"
        ),
    )
    observed_summary: str = Field(
        default="",
        description="仅基于可见内容的自然语言概述；禁止包含风险/事件/因果推论。",
    )
