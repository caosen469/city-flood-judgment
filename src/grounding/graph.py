"""OSM road-network loader for Stage 2 Grounding (ADR-0003).

Loads the cached GeoPackage produced by ``scripts/download_osm_roads.py``
(ticket #11) into a :class:`RoadNetwork` — the matching substrate for
:mod:`src.grounding.match`.

Why not ``ox.nearest_edges(G, …, k=5)``?
    osmnx 2.1.1's ``nearest_edges`` takes **no** ``k`` argument — it returns the
    single nearest edge only (``return_dist`` gives its distance). ADR-0003 needs
    the *k* nearest so the dual-carriageway / junction ambiguity logic has a
    runner-up to compare against. We therefore build the same structure osmnx
    builds internally — a scipy cKDTree over the edges' coordinate points — and
    own the k-nearest retrieval ourselves. The ADR's ``ox.nearest_edges(..., k=5)``
    is the *intent*; this is its faithful implementation against the installed
    osmnx. (See the resolution note on ticket #13.)

Everything here is read from the local cache — no network access.

GeoPackage round-trip caveat (ticket #11 downstream note): writing to GPKG
flattens the OSMnx MultiIndex (``osmid`` on nodes, ``(u, v, key)`` on edges) into
plain columns. We restore the edge index ``(u, v, key)`` so each edge keeps its
OSMnx identity for ``MatchedRoad.edge_ref``; the node index is not needed for
matching (we work off the projected edges GeoDataFrame, not the MultiDiGraph).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

DEFAULT_ROADS_GPKG = Path("data/urban/nansha_roads.gpkg")

# Metric CRS for all distance / buffer work (ADR-0003). Nansha sits at ~113.5°E,
# which is UTM zone **49N** (EPSG:32649, central meridian 111°E) — not 50N as the
# ADR's "~EPSG:32650" approximation had. Both are metric and give identical
# <100 m band results, but 32649 is the true zone for the longitude, so we use
# it. See ticket #13 resolution note.
NANSHA_UTM_CRS = "EPSG:32649"
WGS84_CRS = "EPSG:4326"

# Columns the matcher / RoadProvider read off an edge. We keep the OSMnx
# identity + the waterlogging-relevant attributes, drop the rest to keep the
# projected frame small.
_EDGE_COLUMNS: tuple[str, ...] = (
    "osmid", "name", "name:zh", "highway", "bridge", "tunnel",
    "lanes", "oneway", "maxspeed", "surface", "geometry",
)


@dataclass
class RoadNetwork:
    """Projected road edges + a spatial index for k-nearest matching.

    Built once at startup (FastAPI lifespan) and shared across requests.
    """

    edges_proj: gpd.GeoDataFrame  # UTM, index = (u, v, key)
    proj_crs: str
    bbox_wgs84: tuple[float, float, float, float]  # (west, south, east, north)
    _tree: cKDTree = field(repr=False)
    _point_to_edge: np.ndarray = field(repr=False)  # tree-point i -> edge row pos
    _to_proj: Transformer = field(repr=False)
    _to_wgs84: Transformer = field(repr=False)
    _edge_index: np.ndarray = field(repr=False)  # row pos -> (u, v, key)

    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #
    @classmethod
    def from_gpkg(cls, path: str | Path = DEFAULT_ROADS_GPKG) -> "RoadNetwork":
        """Load ``edges`` (and ``nodes`` for bounds) from the cached GeoPackage.

        Raises
        ------
        FileNotFoundError
            If the cache is absent (the download script has not been run).
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"路网缓存不存在：{path}。请先运行 scripts/download_osm_roads.py（#11）。"
            )
        edges = gpd.read_file(path, layer="edges")
        nodes = gpd.read_file(path, layer="nodes")
        return cls.from_edges(nodes, edges)

    @classmethod
    def from_edges(
        cls,
        nodes: gpd.GeoDataFrame,
        edges: gpd.GeoDataFrame,
        *,
        utm_crs: str = NANSHA_UTM_CRS,
    ) -> "RoadNetwork":
        """Build a RoadNetwork from already-loaded WGS-84 ``nodes`` / ``edges``
        GeoDataFrames (the same shape ``download_osm_roads.py`` writes). Used by
        :meth:`from_gpkg` and by tests with a small synthetic network."""
        # GPKG flattened the (u, v, key) MultiIndex into columns — restore it so
        # each edge keeps a stable OSMnx identity for MatchedRoad.edge_ref.
        edge_index_cols = [c for c in ("u", "v", "key") if c in edges.columns]
        if edge_index_cols:
            edges = edges.set_index(edge_index_cols)

        keep = [c for c in _EDGE_COLUMNS if c in edges.columns]
        edges = edges[keep]

        # Coarse coverage gate (outside_nansha): the geographic bbox of the road
        # nodes. A point outside this rectangle is not ours (ADR-0003).
        bbox = tuple(float(v) for v in nodes.total_bounds)  # (w, s, e, n)

        edges_proj = edges.to_crs(utm_crs)

        # Build a cKDTree over every edge coordinate point, remembering which
        # edge row each point came from. k-nearest retrieval then dedups back to
        # edges keeping the nearest point per edge.
        pts_list: list[np.ndarray] = []
        src_list: list[np.ndarray] = []
        for row_pos, geom in enumerate(edges_proj.geometry):
            if geom is None or getattr(geom, "is_empty", False):
                continue
            coords = np.asarray(geom.coords, dtype=float)
            pts_list.append(coords)
            src_list.append(np.full(len(coords), row_pos, dtype=np.int64))
        if not pts_list:
            raise ValueError("edges GeoDataFrame 没有任何可用几何。")

        points = np.concatenate(pts_list, axis=0)
        point_to_edge = np.concatenate(src_list, axis=0)
        tree = cKDTree(points)

        to_proj = Transformer.from_crs(WGS84_CRS, utm_crs, always_xy=True)
        to_wgs84 = Transformer.from_crs(utm_crs, WGS84_CRS, always_xy=True)

        edge_index = np.asarray(edges_proj.index.tolist())  # (u,v,key) per row

        return cls(
            edges_proj=edges_proj,
            proj_crs=utm_crs,
            bbox_wgs84=bbox,
            _tree=tree,
            _point_to_edge=point_to_edge,
            _to_proj=to_proj,
            _to_wgs84=to_wgs84,
            _edge_index=edge_index,
        )

    # ------------------------------------------------------------------ #
    # Matching primitives (used by src.grounding.match)                  #
    # ------------------------------------------------------------------ #
    def contains_wgs84(self, lon: float, lat: float, *, margin_deg: float = 0.0) -> bool:
        """Coarse coverage gate. ``True`` if the point is within the network's
        geographic bbox (optionally expanded by ``margin_deg``)."""
        west, south, east, north = self.bbox_wgs84
        m = margin_deg
        return (west - m) <= lon <= (east + m) and (south - m) <= lat <= (north + m)

    def project_point(self, lon: float, lat: float) -> tuple[float, float]:
        """WGS-84 (lon, lat) → projected metric (x, y)."""
        x, y = self._to_proj.transform(lon, lat)
        return float(x), float(y)

    def unproject_point(self, x: float, y: float) -> tuple[float, float]:
        """Projected metric (x, y) → WGS-84 (lon, lat)."""
        lon, lat = self._to_wgs84.transform(x, y)
        return float(lon), float(lat)

    def nearest_edge_rows(
        self, lon: float, lat: float, *, k: int, oversample: int = 6
    ) -> list[int]:
        """Return up to ``k`` distinct edge **row positions**, nearest-first.

        Queries the point tree for ``k * Oversample`` nearest points (several
        points map to the same edge — dual carriageways, long edges), then dedups
        keeping each edge's nearest point. The result is ordered by that nearest
        point distance, which is a tight upper bound on the true perpendicular
        distance (the matcher recomputes the exact foot/distance afterwards).
        """
        x, y = self.project_point(lon, lat)
        # Query more points than edges requested, then dedup.
        n_points = max(k * oversample, k + 5)
        n_points = min(n_points, len(self._tree.data))
        dists, idxs = self._tree.query([x, y], k=n_points)
        if np.isscalar(idxs):
            dists, idxs = np.array([dists]), np.array([idxs])

        seen: set[int] = set()
        ordered: list[int] = []
        for idx in idxs:
            row = int(self._point_to_edge[int(idx)])
            if row in seen:
                continue
            seen.add(row)
            ordered.append(row)
            if len(ordered) >= k:
                break
        return ordered

    def edge_ref(self, row_pos: int) -> tuple[int, int, int]:
        """OSMnx ``(u, v, key)`` identity for an edge row position."""
        u, v, key = self._edge_index[row_pos]
        return int(u), int(v), int(key)
