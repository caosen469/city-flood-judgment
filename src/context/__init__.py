"""Stage 2b — Urban Context (ADR-0002).

Composition of typed ``ContextBlock``s assembled by :class:`ContextAssembler`.
The default factory wires the three v1 providers (road / elevation / terrain)
around one shared :class:`SrtmReader`; the pipeline (#15) calls
:meth:`ContextAssembler.assemble` with a located point + the Grounding result.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from .base import ContextAssembler, ContextProvider, _now
from .dem import DEFAULT_SRTM_TIF, SrtmReader
from .providers import (
    ElevationProvider,
    RoadProvider,
    TerrainProvider,
    open_meteo_elevation,
)
from .providers.elevation import FallbackFetcher  # noqa: F401 — re-exported type


def make_default_assembler(
    *,
    srtm_path: str | Path = DEFAULT_SRTM_TIF,
    road_data_vintage: Optional[date] = None,
    srtm_data_vintage: Optional[date] = None,
    elevation_fallbacks: Optional[list] = None,
) -> ContextAssembler:
    """Wire the three v1 providers around one shared SRTM reader.

    The SRTM reader is shared by the elevation and terrain providers so the
    GeoTIFF is opened once (FastAPI lifespan constructs this; the assembler is
    then reused per request).
    """
    reader = SrtmReader.open(srtm_path)
    providers: list[ContextProvider] = [
        RoadProvider(data_vintage=road_data_vintage),
        ElevationProvider(
            reader,
            fallbacks=elevation_fallbacks,
            data_vintage=srtm_data_vintage,
        ),
        TerrainProvider(reader, data_vintage=srtm_data_vintage),
    ]
    return ContextAssembler(providers)


__all__ = [
    "ContextAssembler",
    "ContextProvider",
    "SrtmReader",
    "DEFAULT_SRTM_TIF",
    "RoadProvider",
    "ElevationProvider",
    "TerrainProvider",
    "open_meteo_elevation",
    "FallbackFetcher",
    "make_default_assembler",
]
