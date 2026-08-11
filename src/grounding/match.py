"""``match(lat, lon) -> GroundedEntity`` — pure-geometry road matching
(ADR-0003).

No network, fully deterministic: given a :class:`RoadNetwork` and a WGS-84
point, bind it to the nearest road entity. (osmnx 2.1.1 dropped k-nearest from
``nearest_edges``; see :mod:`src.grounding.graph` for the cKDTree substrate.)

Pipeline:

1. **Coarse gate** — if the query point lies outside the cached network's
   geographic bbox, return ``unresolved(outside_nansha)`` without running a
   search (ADR-0003: "不加载全城路网").
2. **Candidate retrieval** — :meth:`RoadNetwork.nearest_edge_rows` returns the
   ``k`` nearest edges via the projected cKDTree (metric ranking).
3. **Exact foot + distance** — for each candidate edge, project the query point
   onto its geometry (UTM) and take the perpendicular foot. ``match_distance_m``
   is the true point-to-line distance, not the tree's point-approximation.
4. **Re-cluster by way** — a bidirectional road's two directions show up as two
   edges sharing an ``osmid``; collapse them to one candidate (min-distance edge
   wins) so the road identity is unique.
5. **Three-state decision** — distance band → ``grounded`` (high/medium/low) or
   ``unresolved(out_of_buffer)``; a runner-up within 15 m or 1.5× of the nearest
   promotes the result to ``ambiguous`` (confidence from the nearest band).

Heading / direction is deliberately unused in v1 (ADR-0003).

:func:`ground` is the Stage-2a entry point the pipeline (#15) calls: it runs
:func:`locate` then :func:`match`, mapping a failed locate to the right
unresolved reason (``no_location`` vs ``geocode_failed``).
"""

from __future__ import annotations

from typing import Optional

from shapely.geometry import Point

from schemas.grounding import (
    Confidence,
    GroundedEntity,
    GroundingStatus,
    LatLon,
    LocationSource,
    MatchedRoad,
    UnresolvedReason,
)
from schemas.observation import LocationRef

from .graph import RoadNetwork
from .locate import Geocoder, locate

# Distance → status / confidence bands (ADR-0003). Lower-bound exclusive on each
# higher band: <15 high, 15–35 medium, 35–100 low, >100 unresolved.
HIGH_BAND_M = 15.0
MEDIUM_BAND_M = 35.0
LOW_BAND_M = 100.0

# Ambiguous override: a runner-up this close (m) or this fraction of the nearest
# distance means the road identity is genuinely not unique (ADR-0003).
AMBIGUOUS_ABS_M = 15.0
AMBIGUOUS_RATIO = 1.5

# How many nearest edges to retrieve before re-clustering by way.
K_NEAREST = 5


# --------------------------------------------------------------------------- #
# Tag coercion — OSM values are heterogeneous (lists, "yes"/"True", None).     #
# --------------------------------------------------------------------------- #


def _distance_band(distance_m: float) -> Confidence:
    if distance_m < HIGH_BAND_M:
        return Confidence.HIGH
    if distance_m < MEDIUM_BAND_M:
        return Confidence.MEDIUM
    return Confidence.LOW


def _way_id_of(row) -> str:
    """A single parent-way id from an edge's ``osmid`` (may be a list when OSM
    merged ways during simplification). Always a string — MatchedRoad.osm_way_id
    is typed ``str``."""
    osmid = row.get("osmid")
    if isinstance(osmid, list):
        return str(osmid[0])
    return str(osmid)


def _first_str(value) -> Optional[str]:
    """OSM tags can be a list (rare); take the first element. None stays None."""
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value)


def _truthy_tag(value) -> bool:
    """OSM boolean-ish tags: ``"yes"`` / ``True`` / ``"true"`` → True. Values
    like ``"viaduct"`` count as a bridge too (a bridge structure, not just the
    bare ``yes`` tag)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        return any(_truthy_tag(v) for v in value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"", "no", "false", "0", "none"}:
            return False
        return True  # "yes", "viaduct", "true", …
    return False


def _road_name_of(row) -> Optional[str]:
    """Prefer the Chinese name (``name:zh``), fall back to the latin ``name``."""
    return _first_str(row.get("name:zh")) or _first_str(row.get("name"))


def _highway_of(row) -> str:
    s = _first_str(row.get("highway"))
    return s if s else "unclassified"


def _foot_and_distance(
    geom, x: float, y: float, network: RoadNetwork
) -> tuple[float, LatLon]:
    """Perpendicular foot of projected ``(x, y)`` on ``geom`` and the metric
    distance. ``geom`` is already in the network's projected CRS."""
    pt = Point(x, y)
    # project + interpolate gives the true closest point on the line.
    projected = geom.interpolate(geom.project(pt))
    distance_m = float(pt.distance(geom))
    foot_lon, foot_lat = network.unproject_point(projected.x, projected.y)
    return distance_m, LatLon(lat=foot_lat, lon=foot_lon)


def _build_candidate(
    row, edge_ref: tuple[int, int, int], x: float, y: float, network: RoadNetwork
) -> MatchedRoad:
    geom = row.geometry
    distance_m, foot = _foot_and_distance(geom, x, y, network)
    return MatchedRoad(
        osm_way_id=_way_id_of(row),
        edge_ref=edge_ref,
        road_name=_road_name_of(row),
        highway=_highway_of(row),
        bridge=_truthy_tag(row.get("bridge")),
        tunnel=_truthy_tag(row.get("tunnel")),
        match_point=foot,
        match_distance_m=distance_m,
    )


# --------------------------------------------------------------------------- #
# match()                                                                      #
# --------------------------------------------------------------------------- #


def match(
    lat: float,
    lon: float,
    *,
    network: RoadNetwork,
    source: LocationSource,
    geocode_confidence: Optional[Confidence] = None,
    outside_gate_margin_deg: float = 0.0,
) -> GroundedEntity:
    """Bind a WGS-84 point to the nearest road entity in ``network``.

    Parameters
    ----------
    lat, lon : float
        Query point (WGS-84).
    network : RoadNetwork
        Loaded OSM road network (from :meth:`RoadNetwork.from_gpkg`).
    source : LocationSource
        Provenance of the point (carried onto the entity for downstream context).
    geocode_confidence : Confidence, optional
        Nominatim precision (only meaningful when ``source == geocoded_text``).
        Not folded into match confidence — ADR-0003 keeps geocode accuracy on
        ``source``; this param is accepted for signature symmetry with locate().
    outside_gate_margin_deg : float
        Expand the network bbox by this many degrees before the coarse gate, so
        a point just inside the real administrative boundary but outside the
        road coverage is not wrongly classed ``outside_nansha``. 0 by default.

    Returns
    -------
    GroundedEntity
        ``grounded`` / ``ambiguous`` / ``unresolved`` per ADR-0003.
    """
    _ = geocode_confidence  # not folded into match confidence (ADR-0003)

    query_point = LatLon(lat=lat, lon=lon)

    # 1. Coarse outside-Nansha gate.
    if not network.contains_wgs84(lon, lat, margin_deg=outside_gate_margin_deg):
        return GroundedEntity(
            status=GroundingStatus.UNRESOLVED,
            query_point=query_point,
            source=source,
            unresolved_reason=UnresolvedReason.OUTSIDE_NANSHA,
        )

    # 2. Candidate retrieval (projected cKDTree → metric ranking).
    edge_rows = network.nearest_edge_rows(lon, lat, k=K_NEAREST)
    edges = network.edges_proj

    # 3 + 4. Exact distance per edge, then re-cluster by parent way.
    x, y = network.project_point(lon, lat)
    per_way: dict[str, MatchedRoad] = {}
    for row_pos in edge_rows:
        row = edges.iloc[row_pos]
        edge_ref = network.edge_ref(row_pos)
        candidate = _build_candidate(row, edge_ref, x, y, network)
        existing = per_way.get(candidate.osm_way_id)
        if existing is None or candidate.match_distance_m < existing.match_distance_m:
            per_way[candidate.osm_way_id] = candidate

    candidates = sorted(per_way.values(), key=lambda c: c.match_distance_m)
    if not candidates:
        return GroundedEntity(
            status=GroundingStatus.UNRESOLVED,
            query_point=query_point,
            source=source,
            unresolved_reason=UnresolvedReason.OUT_OF_BUFFER,
        )

    nearest_road = candidates[0]
    nearest_dist = nearest_road.match_distance_m

    # 5a. Out of buffer — nearest road farther than 100 m.
    if nearest_dist > LOW_BAND_M:
        return GroundedEntity(
            status=GroundingStatus.UNRESOLVED,
            query_point=query_point,
            source=source,
            unresolved_reason=UnresolvedReason.OUT_OF_BUFFER,
        )

    confidence = _distance_band(nearest_dist)

    # 5b. Ambiguous override — runner-up within 15 m or 1.5× of nearest.
    if len(candidates) >= 2:
        runner_up = candidates[1]
        rd = runner_up.match_distance_m
        if rd <= AMBIGUOUS_ABS_M or rd <= AMBIGUOUS_RATIO * nearest_dist:
            for c in candidates:
                c.confidence = confidence
            return GroundedEntity(
                status=GroundingStatus.AMBIGUOUS,
                query_point=query_point,
                source=source,
                best_match=nearest_road,
                candidates=candidates,
            )

    nearest_road.confidence = confidence
    return GroundedEntity(
        status=GroundingStatus.GROUNDED,
        query_point=query_point,
        source=source,
        best_match=nearest_road,
        candidates=candidates,
    )


# --------------------------------------------------------------------------- #
# ground() — the Stage-2a orchestrator (locate → match).                       #
# --------------------------------------------------------------------------- #


def ground(
    ref: Optional[LocationRef],
    *,
    network: RoadNetwork,
    source: Optional[LocationSource] = None,
    geocoder: Optional[Geocoder] = None,
) -> GroundedEntity:
    """Resolve a :class:`LocationRef` to a :class:`GroundedEntity` (Stage 2a).

    Runs :func:`locate` then :func:`match`. When ``locate`` returns ``None`` the
    entity is ``unresolved`` with the honest reason: ``no_location`` if the input
    carried nothing usable, ``geocode_failed`` if text was supplied but could not
    be geocoded (ADR-0003 failure-by-value, never an exception).
    """
    located = locate(ref, source=source, geocoder=geocoder)
    if located is None:
        had_text = ref is not None and bool(
            (ref.raw_text or "").strip() or (ref.road_name or "").strip()
        )
        reason = (
            UnresolvedReason.GEOCODE_FAILED
            if had_text
            else UnresolvedReason.NO_LOCATION
        )
        return GroundedEntity(
            status=GroundingStatus.UNRESOLVED,
            query_point=None,  # no point — validator requires None here
            source=LocationSource.NONE,
            unresolved_reason=reason,
        )

    return match(
        located.point.lat,
        located.point.lon,
        network=network,
        source=located.source,
        geocode_confidence=located.geocode_confidence,
    )
