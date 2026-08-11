"""Elevation context provider — absolute height + surrounding stats
(ADR-0002 / PRD §4.6).

Computes on the **raw lat/lon** whether or not Grounding resolved a road: it
never claims to be a particular road's elevation, so a Case-F (grounding
unresolved) point still gets an elevation block (ADR-0002 §5 key behavior).

Fallback chain (ADR-0002): local SRTM GeoTIFF (full elevation + surrounding
stats) → remote point-only tiers. The first tier that answers wins, and its
tier name is written to ``Provenance.source`` so the Evidence Chain can quote
how trustworthy the figure is.

The local tier is the only one that returns surrounding stats; remote tiers
serve a point elevation only (their stats window is empty). Remote tiers are
injectable callables so tests run hermetically. The default remote tier is
Open-Meteo (free, no API key); OpenTopography (needs a key) and Open-Elevation
(public instance, often down) are pluggable but not in the default chain.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Optional

import numpy as np

from schemas.context import (
    Availability,
    BlockAvailability,
    ContextSource,
    ElevationContextBlock,
    Provenance,
    SurroundingStats,
    UnavailabilityReason,
)
from schemas.grounding import GroundedEntity, LocatedPoint

from ..base import _now
from ..dem import SrtmReader

#: surrounding-stats window radius (px). meso TPI radius = 33 px ≈ 1 km.
_STATS_RADIUS_PX = 33

#: A remote fallback tier: (lat, lon) -> elevation_m or None. Tagged with the
#: ContextSource it counts as when it answers.
FallbackFetcher = Callable[[float, float], Optional[float]]


def open_meteo_elevation(lat: float, lon: float) -> Optional[float]:
    """Free, no-key elevation API (fallback tier). Returns meters or None.

    Only used when the local SRTM tile does not cover the point. Network errors
    any kind → None (the chain moves on / marks unavailable).
    """
    import urllib.request  # noqa: PLC0415 — lazy, only hit on fallback
    import json  # noqa: PLC0415

    url = f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — public API
            payload = json.loads(resp.read().decode("utf-8"))
        elev = payload.get("elevation")
        if isinstance(elev, list) and elev:
            return float(elev[0])
        return None
    except Exception:  # noqa: BLE001 — any failure ⇒ chain moves on
        return None


class ElevationProvider:
    """Emits the ``elevation`` ContextBlock (absolute height + surrounding stats)."""

    block_type = "elevation"

    def __init__(
        self,
        reader: SrtmReader,
        *,
        fallbacks: Optional[list[tuple[ContextSource, FallbackFetcher]]] = None,
        data_vintage: Optional[date] = None,
    ):
        self._reader = reader
        self._fallbacks = fallbacks if fallbacks is not None else [
            (ContextSource.OPEN_METEO, open_meteo_elevation)
        ]
        self._data_vintage = data_vintage

    # ------------------------------------------------------------------ #
    def query(self, point: LocatedPoint, grounding: GroundedEntity) -> ElevationContextBlock:
        lat, lon = point.point.lat, point.point.lon

        # Tier 0 — local SRTM (full elevation + surrounding stats).
        elevation_pt = self._reader.sample_point(lon, lat)
        if elevation_pt is not None:
            stats = self._surrounding_stats(lat, lon)
            return ElevationContextBlock(
                elevation_pt=elevation_pt,
                stats=stats,
                provenance=Provenance(
                    source=ContextSource.SRTM_LOCAL,
                    data_vintage=self._data_vintage,
                    retrieved_at=_now(),
                ),
                availability=BlockAvailability(status=Availability.AVAILABLE),
            )

        # Tier 1..n — remote point-only fallbacks. A fallback-served value is
        # real but less granular (no stats), so UNCERTAIN + FALLBACK_USED.
        for source, fetch in self._fallbacks:
            val = fetch(lat, lon)
            if val is not None:
                return ElevationContextBlock(
                    elevation_pt=float(val),
                    stats=SurroundingStats(),  # remote tiers carry no stats
                    provenance=Provenance(
                        source=source,
                        data_vintage=self._data_vintage,
                        retrieved_at=_now(),
                    ),
                    availability=BlockAvailability(
                        status=Availability.UNCERTAIN,
                        reason=UnavailabilityReason.FALLBACK_USED,
                    ),
                )

        # All tiers exhausted. Distinguish "outside cached coverage" from
        # "in tile but unusable pixel + fallbacks failed".
        in_bounds = self._reader.in_bounds(lon, lat)
        reason = (
            UnavailabilityReason.NO_DATA_IN_BOUNDS
            if not in_bounds
            else UnavailabilityReason.SOURCE_ERROR
        )
        return ElevationContextBlock(
            elevation_pt=None,
            stats=SurroundingStats(),
            provenance=Provenance(
                source=ContextSource.SRTM_LOCAL,
                data_vintage=self._data_vintage,
                retrieved_at=_now(),
            ),
            availability=BlockAvailability(
                status=Availability.UNAVAILABLE, reason=reason
            ),
        )

    # ------------------------------------------------------------------ #
    def _surrounding_stats(self, lat: float, lon: float) -> SurroundingStats:
        """min/max/mean/std of valid pixels within the ~1 km disk around point."""
        arr, pr, pc = self._reader.read_window(lon, lat, _STATS_RADIUS_PX)
        yy, xx = np.ogrid[: arr.shape[0], : arr.shape[1]]
        disk = (yy - pr) ** 2 + (xx - pc) ** 2 <= _STATS_RADIUS_PX**2
        disk_vals = arr[disk].compressed()
        radius_m = self._reader.pixel_size_m(lat) * _STATS_RADIUS_PX
        if disk_vals.size == 0:
            return SurroundingStats(radius_m=radius_m, valid_pixels=0)
        return SurroundingStats(
            radius_m=radius_m,
            valid_pixels=int(disk_vals.size),
            min=float(np.min(disk_vals)),
            max=float(np.max(disk_vals)),
            mean=float(np.mean(disk_vals)),
            std=float(np.std(disk_vals)),
        )
