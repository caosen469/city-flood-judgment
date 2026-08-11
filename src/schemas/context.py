"""Canonical Urban Context contract (Pydantic v2) for the city-waterlogging demo.

This module is the *contract* between the Grounding layer, the urban-data
providers, and the Knowledge Engine. It encodes the decisions recorded in
ADR-0002 and on wayfinder ticket #6:

* ``UrbanContext`` is a **composition of typed ContextBlocks** — one block per
  knowledge source (road, elevation, terrain, …). New sources extend as new
  block types; the root model never changes shape (mirrors the
  ``phenomenon_type`` discriminator pattern of ADR-0001).
* **Elevation and Terrain are separate blocks**: ElevationContext holds absolute
  height + surrounding stats ("how high is it"), TerrainContext holds the
  relative-lowness judgement ("is it low-lying vs. its surroundings"). The
  latter is what the Knowledge Engine turns into TerrainRisk knowledge.
* **Availability is per-block, three-state** (``available`` / ``unavailable`` /
  ``uncertain``) with a machine ``reason`` code. When Grounding is unresolved
  (PRD Case F), ``RoadContext`` is ``unavailable`` but elevation/terrain are
  still computed on the raw lat/lon — we never claim it is *a road's* elevation.
* **Provenance is per-block**: every block knows its ``source`` (which dataset /
  fallback tier), ``data_vintage`` and ``retrieved_at``. The Evidence Chain
  (PRD §4.14) requires this so a viewer can say how trustworthy a figure is.
* **"unknown" by value, not by missing key**: per ADR-0001, required keys always
  appear; missing data is expressed by ``status`` + ``reason`` and by nullable
  numbers.

The low-lying classifier tiers and the multi-scale TPI weighting live here as
module constants so the Knowledge Engine (#7) and any tests reference one
source of truth. Provider / assembler interfaces are specified in ADR-0002;
this file deliberately contains *only* the data contract, not query logic.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# =========================================================================== #
# Enums — canonical values are language-neutral codes.                         #
# zh-CN display labels will live in display_labels.py (see #4 convention).     #
# =========================================================================== #


class ContextSource(str, Enum):
    """Which dataset / fallback tier a block came from. Required on every block
    so the Evidence Chain can quote provenance and a viewer can gauge trust."""

    OSM = "osm"                        # OpenStreetMap road network (OSMnx / GeoPackage)
    SRTM_LOCAL = "srtm_local"          # local SRTM 30m GeoTIFF (primary, full-res)
    OPENTOPOGRAPHY = "opentopography"  # OpenTopography API (fallback tier 1)
    OPEN_METEO = "open_meteo"          # Open-Meteo elevation API (fallback tier 2)
    OPEN_ELEVATION = "open_elevation"  # Open-Elevation public instance (last resort)
    USER_PROVIDED = "user_provided"    # supplied by demo input, not retrieved


class Availability(str, Enum):
    """Per-block availability. Mirrors ADR-0001's "unknown by value" rule:
    a block is always present; its status says whether the data is real."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"  # source had nothing usable
    UNCERTAIN = "uncertain"      # got a value, but low confidence / degraded


class UnavailabilityReason(str, Enum):
    """Why a block is unavailable or uncertain. Extensible."""

    NO_DATA_IN_BOUNDS = "no_data_in_bounds"        # query point outside cached coverage
    GROUNDING_UNRESOLVED = "grounding_unresolved"  # no road matched (Case F) -> road only
    LOW_PIXEL_COUNT = "low_pixel_count"            # too few valid DEM pixels for stats
    FALLBACK_USED = "fallback_used"                # primary failed, a tier served it
    SOURCE_ERROR = "source_error"                  # provider raised / timed out
    NOT_APPLICABLE = "not_applicable"              # block type irrelevant for this input


class HighwayClass(str, Enum):
    """OSM ``highway`` values that matter for waterlogging context, collapsed to
    a closed set. Rare / non-drivable values fold into OTHER."""

    MOTORWAY = "motorway"
    TRUNK = "trunk"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    UNCLASSIFIED = "unclassified"
    RESIDENTIAL = "residential"
    LIVING_STREET = "living_street"
    SERVICE = "service"
    OTHER = "other"  # catch-all for pedestrian / track / footway / etc.


class LownessClass(str, Enum):
    """Relative-lowness tier from the multi-scale TPI composite (meters).

    Thresholds are fixed by ticket #6 / ADR-0002; see ``LOWNESS_THRESHOLDS``.
    """

    LEVEL_OR_HIGHER = "level_or_higher"      # composite < 0.3 m  — flat / raised
    SLIGHTLY_LOW = "slightly_low"            # 0.3 - 1.0 m
    MODERATELY_LOW = "moderately_low"        # 1.0 - 2.0 m
    SIGNIFICANTLY_LOW = "significantly_low"  # > 2.0 m  — strong ponding signal
    INSUFFICIENT_DATA = "insufficient_data"  # unknown sentinel


# =========================================================================== #
# Low-lying classifier — single source of truth for tiers & TPI weighting.     #
# =========================================================================== #

#: composite thresholds (meters), lower-bound exclusive. Order matters.
LOWNESS_THRESHOLDS: tuple[tuple[float, LownessClass], ...] = (
    (0.3, LownessClass.LEVEL_OR_HIGHER),
    (1.0, LownessClass.SLIGHTLY_LOW),
    (2.0, LownessClass.MODERATELY_LOW),
    # > 2.0 falls through to SIGNIFICANTLY_LOW
)

#: multi-scale TPI weighting: composite = meso + 0.3*micro + 0.2*macro.
#: meso (1 km) is the primary signal; micro (300 m) confirms local character;
#: macro (2 km) gives broad delta-plain context. Radii in SRTM pixels (~30 m).
TPI_WEIGHTS: dict[str, float] = {"meso": 1.0, "micro": 0.3, "macro": 0.2}
TPI_RADII_PX: dict[str, int] = {"micro": 10, "meso": 33, "macro": 66}  # ~300m/1km/2km


def classify_lowness(composite: Optional[float]) -> LownessClass:
    """Map a TPI composite (meters, positive = lower than surroundings) to a
    tier. ``None`` -> ``insufficient_data``."""
    if composite is None:
        return LownessClass.INSUFFICIENT_DATA
    for bound, cls in LOWNESS_THRESHOLDS:
        if composite < bound:
            return cls
    return LownessClass.SIGNIFICANTLY_LOW


# =========================================================================== #
# Shared mixins — provenance + availability live on every block.               #
# =========================================================================== #


class Provenance(BaseModel):
    """Where a block's data came from. Required on every block (PRD §4.14)."""

    source: ContextSource
    data_vintage: Optional[date] = None  # dataset currency, e.g. SRTMGL1 v003 date
    retrieved_at: datetime  # when this block was computed / fetched


class BlockAvailability(BaseModel):
    """Per-block availability + reason. ``reason`` is required when status !=
    available; useful too on ``uncertain`` (e.g. fallback_used)."""

    status: Availability = Availability.AVAILABLE
    reason: Optional[UnavailabilityReason] = None


# =========================================================================== #
# Block payloads                                                               #
# =========================================================================== #


class SurroundingStats(BaseModel):
    """Elevation statistics within the analysis radius around the query point."""

    radius_m: float = 1000.0
    valid_pixels: int = 0
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None


class LownessScores(BaseModel):
    """Multi-scale TPI scores (meters; positive = lower than neighbourhood).

    ``composite`` is the weighted sum consumed by the classifier; per-scale
    scores are kept for explainability in the Evidence Chain.
    """

    micro: Optional[float] = None   # ~300 m neighbourhood
    meso: Optional[float] = None    # ~1 km neighbourhood (primary)
    macro: Optional[float] = None   # ~2 km neighbourhood
    composite: Optional[float] = None
    lowness_class: LownessClass = LownessClass.INSUFFICIENT_DATA


class RoadContextBlock(BaseModel):
    """Road attributes for the matched road entity. Populated only after
    Grounding (#5) resolves a road; geometry is deliberately NOT carried (too
    heavy, unused downstream) — only identity + attributes + spatial relation."""

    block_type: Literal["road"] = "road"
    # identity
    road_name: Optional[str] = None  # zh name preferred (name:zh)
    osm_way_id: Optional[int] = None
    highway_class: Optional[HighwayClass] = None
    # attributes relevant to waterlogging risk
    lanes: Optional[int] = None
    oneway: Optional[bool] = None
    is_bridge: Optional[bool] = None
    is_tunnel: Optional[bool] = None
    maxspeed: Optional[int] = None  # km/h, parsed where possible
    # spatial relation between query point and matched road
    offset_distance_m: Optional[float] = None
    grounding_confidence: Optional[float] = None  # from #5 GroundedEntity
    # shared
    provenance: Provenance
    availability: BlockAvailability = Field(default_factory=BlockAvailability)


class ElevationContextBlock(BaseModel):
    """Absolute elevation + surrounding stats. Computable on a raw lat/lon even
    when Grounding is unresolved (Case F) — it makes no claim about a road."""

    block_type: Literal["elevation"] = "elevation"
    elevation_pt: Optional[float] = None  # meters, at the query point
    stats: SurroundingStats = Field(default_factory=SurroundingStats)
    provenance: Provenance
    availability: BlockAvailability = Field(default_factory=BlockAvailability)


class TerrainContextBlock(BaseModel):
    """Relative-lowness judgement derived from multi-scale TPI. This is the
    block the Knowledge Engine turns into TerrainRisk knowledge (Case C)."""

    block_type: Literal["terrain"] = "terrain"
    lowness: LownessScores = Field(default_factory=LownessScores)
    provenance: Provenance
    availability: BlockAvailability = Field(default_factory=BlockAvailability)


#: Discriminated union — new context types join here as a new block class with a
#: fresh ``block_type`` literal. The Knowledge Engine and frontend dispatch on it.
ContextBlock = Annotated[
    Union[RoadContextBlock, ElevationContextBlock, TerrainContextBlock],
    Field(discriminator="block_type"),
]


# =========================================================================== #
# Root aggregate                                                               #
# =========================================================================== #


class QueryPoint(BaseModel):
    """The location an UrbanContext was assembled for. ``source_location`` is
    the free-text / structured input the point was geocoded from (#5)."""

    lat: float
    lon: float
    source_location: Optional[str] = None  # passthrough from Observation.meta


class UrbanContext(BaseModel):
    """The assembled background layer for one location (PRD §4.4 / §4.6).

    A list of typed blocks rather than fixed fields: road / elevation / terrain
    today, historical-flooding / drainage / POI tomorrow (PRD §4.9), each a new
    ``ContextBlock`` subclass with no change to this root. Blocks appear even
    when their data is unavailable — status + reason say so (Case D / F).
    """

    query_point: Optional[QueryPoint] = None  # None only when there was no
    # location at all (grounding no_location / geocode_failed) — honest
    # representation of "no point" rather than a fabricated coordinate. Relaxed
    # from required by #13 implementation (mirrors GroundedEntity.query_point).
    blocks: list[ContextBlock] = Field(default_factory=list)

    # ---- typed convenience accessors (derived, not stored) ----
    def block(self, block_type: str) -> Optional[ContextBlock]:
        """First block of a given type, or None."""
        return next((b for b in self.blocks if b.block_type == block_type), None)

    @property
    def road(self) -> Optional[RoadContextBlock]:
        return self.block("road")  # type: ignore[return-value]

    @property
    def elevation(self) -> Optional[ElevationContextBlock]:
        return self.block("elevation")  # type: ignore[return-value]

    @property
    def terrain(self) -> Optional[TerrainContextBlock]:
        return self.block("terrain")  # type: ignore[return-value]
