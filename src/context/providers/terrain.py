"""Terrain context provider — relative-lowness judgement from multi-scale TPI
(ADR-0002 / PRD §4.6).

This is the block the Knowledge Engine turns into TerrainRisk knowledge (ADR-0004
Case C). The composite signal is::

    composite = meso + 0.3·micro + 0.2·macro   (meters; positive = lower)

with per-scale TPI = mean(neighbourhood disk) − z_point. Radii and weights are
the schema's single source of truth (``TPI_RADII_PX`` / ``TPI_WEIGHTS``). The
classifier tier (``classify_lowness``) is shared with the Knowledge Engine.

Like elevation, terrain computes on the **raw lat/lon** regardless of Grounding
(ADR-0002 §5). If the point pixel is nodata or too few valid neighbours exist,
the block is ``unavailable`` / ``uncertain`` with a reason — never an exception.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np

from schemas.context import (
    Availability,
    BlockAvailability,
    ContextSource,
    LownessScores,
    Provenance,
    TerrainContextBlock,
    UnavailabilityReason,
    TPI_RADII_PX,
    TPI_WEIGHTS,
    classify_lowness,
)
from schemas.grounding import GroundedEntity, LocatedPoint

from ..base import _now
from ..dem import SrtmReader, disk_mean

# Fewer valid pixels than this in the meso (primary) disk → insufficient data.
_MIN_VALID_PRIMARY = 50


class TerrainProvider:
    """Emits the ``terrain`` ContextBlock (multi-scale TPI → LownessScores)."""

    block_type = "terrain"

    def __init__(
        self,
        reader: SrtmReader,
        *,
        data_vintage: Optional[date] = None,
    ):
        self._reader = reader
        self._data_vintage = data_vintage

    # ------------------------------------------------------------------ #
    def query(self, point: LocatedPoint, grounding: GroundedEntity) -> TerrainContextBlock:
        lat, lon = point.point.lat, point.point.lon
        provenance = Provenance(
            source=ContextSource.SRTM_LOCAL,
            data_vintage=self._data_vintage,
            retrieved_at=_now(),
        )

        z_point = self._reader.sample_point(lon, lat)
        if z_point is None:
            return TerrainContextBlock(
                lowness=LownessScores(),
                provenance=provenance,
                availability=BlockAvailability(
                    status=Availability.UNAVAILABLE,
                    reason=UnavailabilityReason.NO_DATA_IN_BOUNDS
                    if not self._reader.in_bounds(lon, lat)
                    else UnavailabilityReason.SOURCE_ERROR,
                ),
            )

        scores = self._lowness_scores(lat, lon, z_point)

        # If the primary (meso) scale had too few valid pixels, the composite is
        # not trustworthy → uncertain with low_pixel_count.
        if scores.meso is None:
            return TerrainContextBlock(
                lowness=scores,
                provenance=provenance,
                availability=BlockAvailability(
                    status=Availability.UNCERTAIN,
                    reason=UnavailabilityReason.LOW_PIXEL_COUNT,
                ),
            )

        return TerrainContextBlock(
            lowness=scores,
            provenance=provenance,
            availability=BlockAvailability(status=Availability.AVAILABLE),
        )

    # ------------------------------------------------------------------ #
    def _lowness_scores(self, lat: float, lon: float, z_point: float) -> LownessScores:
        # Read the largest window once (macro radius) and compute every scale
        # against it — cheaper than three reads.
        macro_r = TPI_RADII_PX["macro"]
        arr, pr, pc = self._reader.read_window(lon, lat, macro_r)

        per_scale: dict[str, Optional[float]] = {}
        counts: dict[str, int] = {}
        for name, radius in TPI_RADII_PX.items():
            mean, count = disk_mean(arr, radius, pr, pc)
            counts[name] = count
            per_scale[name] = (mean - z_point) if mean is not None else None

        micro = per_scale["micro"]
        meso = per_scale["meso"]
        macro = per_scale["macro"]

        composite: Optional[float] = None
        # composite needs the primary (meso) scale; micro/macro are confirmatory
        # and may be None at tile edges without invalidating the composite.
        if meso is not None:
            parts = [meso * TPI_WEIGHTS["meso"]]
            if micro is not None:
                parts.append(micro * TPI_WEIGHTS["micro"])
            if macro is not None:
                parts.append(macro * TPI_WEIGHTS["macro"])
            composite = float(sum(parts))

        return LownessScores(
            micro=None if micro is None else float(micro),
            meso=None if meso is None else float(meso),
            macro=None if macro is None else float(macro),
            composite=composite,
            lowness_class=classify_lowness(composite),
        )
