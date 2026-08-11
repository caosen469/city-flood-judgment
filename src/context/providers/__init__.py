"""Urban-context providers (ADR-0002).

Each provider emits one typed ``ContextBlock``:

* :class:`RoadProvider`      — road identity + attributes (from Grounding)
* :class:`ElevationProvider` — absolute height + surrounding stats (SRTM + fallbacks)
* :class:`TerrainProvider`   — multi-scale TPI relative-lowness (SRTM)
"""

from __future__ import annotations

from .elevation import ElevationProvider, open_meteo_elevation
from .road import RoadProvider
from .terrain import TerrainProvider

__all__ = [
    "RoadProvider",
    "ElevationProvider",
    "TerrainProvider",
    "open_meteo_elevation",
]
