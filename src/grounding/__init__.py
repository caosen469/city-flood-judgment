"""Stage 2a — Road Grounding (ADR-0003).

Two independently-testable layers plus an orchestrator:

* :func:`locate` — ``LocationRef -> LocatedPoint | None`` (normalization; owns
  geocoding + error handling).
* :func:`match` — ``lat, lon -> GroundedEntity`` (pure geometry; no network).
* :func:`ground` — the pipeline-facing entry point. Runs ``locate`` then
  ``match`` and maps a ``None`` from ``locate`` to the correct
  ``unresolved_reason`` (``no_location`` vs ``geocode_failed``).

The matching substrate is :class:`RoadNetwork` (a scipy cKDTree over projected
OSM edges — osmnx 2.1.1 ``nearest_edges`` takes no ``k``; see
:mod:`src.grounding.graph`).
"""

from __future__ import annotations

from .graph import DEFAULT_ROADS_GPKG, NANSHA_UTM_CRS, RoadNetwork
from .locate import Geocoder, locate, osmnx_geocoder
from .match import (
    AMBIGUOUS_ABS_M,
    AMBIGUOUS_RATIO,
    HIGH_BAND_M,
    K_NEAREST,
    LOW_BAND_M,
    MEDIUM_BAND_M,
    ground,
    match,
)

__all__ = [
    "DEFAULT_ROADS_GPKG",
    "NANSHA_UTM_CRS",
    "RoadNetwork",
    "Geocoder",
    "locate",
    "osmnx_geocoder",
    "AMBIGUOUS_ABS_M",
    "AMBIGUOUS_RATIO",
    "HIGH_BAND_M",
    "MEDIUM_BAND_M",
    "LOW_BAND_M",
    "K_NEAREST",
    "ground",
    "match",
]
