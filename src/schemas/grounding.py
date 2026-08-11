"""Canonical Grounding contract (Pydantic v2) + module interface for the demo.

This module is the contract between the location-acquisition / matching logic
and the Knowledge Engine. It encodes the decisions recorded in ADR-0003 and on
wayfinder ticket #5:

* Grounding binds an Observation's passthrough ``LocationRef`` to a real road
  entity in the Nansha OSM network. Per PRD §4.7 it must NOT use LLM world
  knowledge — identity comes from image-borne location / demo input + GIS
  spatial matching only. Failure is expressed by value (``unresolved``), never
  by an exception that aborts the pipeline (PRD Case F).
* Confidence reuses the Observation ``Confidence`` enum so the whole chain
  speaks one uncertainty vocabulary; geocoding accuracy is tracked separately
  via ``source == "geocoded_text"``, not folded into match confidence.

Module interface (two layers, independently testable — see ADR-0003)::

    locate(LocationRef) -> LocatedPoint | None
        Normalization front-step. Has lat/lon → pass through; only ``raw_text``
        → Nominatim geocode. Owns geocoding + error handling. Returns ``None``
        when nothing usable can be produced (geocode failure / empty input).

    match(lat, lon) -> GroundedEntity
        Pure geometry: project to a metric CRS (UTM 50N, ~EPSG:32650) then run
        ``ox.nearest_edges(G, lon, lat, k=5)``. No network, fully mockable.

Matching base = OSMnx graph edges (ticket #2 cache ``nansha_roads.gpkg``,
``edges`` layer). Hits are re-clustered to their parent OSM way via
``osm_way_id`` so a bidirectional road's two edges collapse to one identity;
direction / heading is deliberately NOT used in v1.

Match-distance → status / confidence table (see ADR-0003)::

    < 15 m                                  grounded   high
    15–35 m                                 grounded   medium
    35–100 m                                grounded   low
    > 100 m                                 unresolved (out_of_buffer)
    runner-up within 15 m OR within 1.5x    ambiguous  (overrides; confidence
    of nearest                                          from nearest distance band)
    query point outside Nansha R3287345     unresolved (outside_nansha)
    Nominatim could not resolve raw_text    unresolved (geocode_failed)
    LocationRef carries nothing usable      unresolved (no_location)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .observation import Confidence


# =========================================================================== #
# Coordinate system & provenance                                              #
# =========================================================================== #


class CRS(str, Enum):
    """Coordinate reference system of an ingested location.

    v1 ingests WGS-84 only. GCJ-02 (used by Chinese map apps) is ~300–500 m
    offset from WGS-84 in this region; converting it is deferred — see
    ADR-0002 and the map's "Not yet specified". ``crs`` exists so a future
    GCJ-02 path is a non-breaking addition.
    """

    WGS84 = "wgs84"


class LocationSource(str, Enum):
    """How the lat/lon fed to ``match()`` was obtained."""

    EXIF = "exif"  # lat/lon extracted from image EXIF
    USER_LATLON = "user_latlon"  # lat/lon entered manually in the demo UI
    GEOCODED_TEXT = "geocoded_text"  # raw_text → Nominatim → lat/lon
    NONE = "none"  # LocationRef carried nothing usable


# =========================================================================== #
# locate() output — the point handed to match()                              #
# =========================================================================== #


class LatLon(BaseModel):
    lat: float
    lon: float


class LocatedPoint(BaseModel):
    """Output of the ``locate()`` front-step and input to ``match()``.

    Carries provenance so downstream layers can tell a precise EXIF/manual
    fix apart from a fuzzy Nominatim centroid.
    """

    point: LatLon
    crs: CRS = CRS.WGS84
    source: LocationSource
    # Only meaningful when source == geocoded_text: how reliable Nominatim's
    # centroid was. Null for EXIF / user_latlon (treated as exact).
    geocode_confidence: Optional[Confidence] = None


# =========================================================================== #
# match() output — the Grounding stage result                                #
# =========================================================================== #


class GroundingStatus(str, Enum):
    """Three states, not two: ``ambiguous`` keeps the Knowledge Engine honest
    about a point whose road identity is genuinely not unique (junctions,
    dual carriageways) instead of silently picking one."""

    GROUNDED = "grounded"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class UnresolvedReason(str, Enum):
    """Why grounding could not bind a road. One required when status is
    ``unresolved``; populates the Evidence Chain's failure explanation."""

    OUT_OF_BUFFER = "out_of_buffer"  # nearest edge farther than 100 m
    OUTSIDE_NANSHA = "outside_nansha"  # query point outside Nansha R3287345
    GEOCODE_FAILED = "geocode_failed"  # Nominatim could not resolve raw_text
    NO_LOCATION = "no_location"  # LocationRef carried nothing usable


class MatchedRoad(BaseModel):
    """One candidate road. ``best_match`` is the top entry of ``candidates``;
    both are populated together so the UI can show alternatives on demand."""

    osm_way_id: str  # re-clustered parent way (collapses dual-carriageway edges)
    edge_ref: tuple[int, int, int]  # OSMnx edge identity (u, v, key)
    road_name: Optional[str] = None
    highway: str = Field(description="OSM highway tag: motorway / primary / …")
    bridge: bool = False
    tunnel: bool = False
    match_point: LatLon  # where on the edge the perpendicular foot lands
    match_distance_m: float = Field(ge=0)
    confidence: Confidence = Confidence.LOW


class GroundedEntity(BaseModel):
    """Grounding stage output. Consumed by the Urban Context layer (ticket #6),
    which joins road/elevation context onto the matched road. An unresolved
    entity still flows downstream — Context is then marked unavailable and the
    pipeline returns image-only analysis (PRD Case F)."""

    status: GroundingStatus
    # None only for the no-point unresolved reasons (no_location / geocode_failed)
    # — there is genuinely no coordinate to carry. Resolved/grounded/ambiguous and
    # the point-bearing unresolved reasons (out_of_buffer / outside_nansha) always
    # set it. Relaxed from required to keep degradation honest (PRD "unknown by
    # value", surfaced by #13 implementation).
    query_point: Optional[LatLon] = None
    source: LocationSource
    crs: CRS = CRS.WGS84
    best_match: Optional[MatchedRoad] = None
    candidates: list[MatchedRoad] = Field(
        default_factory=list,
        description="Ranked candidates, at most 5 (k from ox.nearest_edges).",
    )
    unresolved_reason: Optional[UnresolvedReason] = None

    @model_validator(mode="after")
    def _status_consistency(self) -> "GroundedEntity":
        point_bearing_reasons = {
            UnresolvedReason.OUT_OF_BUFFER,
            UnresolvedReason.OUTSIDE_NANSHA,
        }
        if self.status is GroundingStatus.UNRESOLVED:
            if self.unresolved_reason is None:
                raise ValueError(
                    "unresolved_reason is required when status is 'unresolved'."
                )
            if self.best_match is not None or self.candidates:
                raise ValueError(
                    "best_match / candidates must be empty when unresolved."
                )
            # out_of_buffer / outside_nansha carry the queried point; the other
            # two reasons (no_location / geocode_failed) have no point at all.
            if self.unresolved_reason in point_bearing_reasons:
                if self.query_point is None:
                    raise ValueError(
                        "query_point is required for unresolved reason "
                        f"{self.unresolved_reason.value}."
                    )
            elif self.query_point is not None:
                raise ValueError(
                    "query_point must be None for unresolved reason "
                    f"{self.unresolved_reason.value}."
                )
        else:
            if self.query_point is None:
                raise ValueError(
                    "query_point is required when status is 'grounded' or "
                    "'ambiguous'."
                )
            if self.best_match is None:
                raise ValueError(
                    "best_match is required when status is 'grounded' or "
                    "'ambiguous'."
                )
            if self.unresolved_reason is not None:
                raise ValueError(
                    "unresolved_reason must be None unless status is "
                    "'unresolved'."
                )
            if self.best_match not in self.candidates:
                raise ValueError("best_match must be one of candidates.")
            if self.status is GroundingStatus.AMBIGUOUS and len(self.candidates) < 2:
                raise ValueError("'ambiguous' requires at least 2 candidates.")
        return self
