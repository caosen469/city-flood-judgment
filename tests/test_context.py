# -*- coding: utf-8 -*-
"""Stage 2b Urban Context tests (``src/context/``).

Hermetic: the Elevation/Terrain providers are exercised against a FakeReader
(duck-typed to the few methods they call), so no GeoTIFF is needed. The Road
provider is driven by a hand-built GroundedEntity. The assembler is checked for
block ordering and query_point wiring.

Run: ``python -m unittest tests.test_context -v``
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from context import ContextAssembler, ElevationProvider, RoadProvider, TerrainProvider  # noqa: E402
from schemas.context import (  # noqa: E402
    Availability,
    ContextSource,
    HighwayClass,
    LownessClass,
    UnavailabilityReason,
    classify_lowness,
)
from schemas.grounding import (  # noqa: E402
    Confidence,
    GroundedEntity,
    GroundingStatus,
    LatLon,
    LocatedPoint,
    LocationSource,
    MatchedRoad,
    UnresolvedReason,
)


# --------------------------------------------------------------------------- #
# Fake DEM reader — duck-typed to src.context.dem.SrtmReader's public surface. #
# --------------------------------------------------------------------------- #


class FakeReader:
    """Returns a constant window value and a configured point elevation."""

    def __init__(
        self,
        *,
        point_value: Optional[float] = 5.0,
        window_value: float = 8.0,
        in_bounds: bool = True,
    ):
        self._point = point_value
        self._window = window_value
        self._in_bounds = in_bounds

    def sample_point(self, lon: float, lat: float) -> Optional[float]:
        return self._point

    def in_bounds(self, lon: float, lat: float) -> bool:
        return self._in_bounds

    def pixel_size_m(self, lat: float) -> float:
        return 30.0

    def read_window(self, lon: float, lat: float, radius_px: int):
        size = int(radius_px) * 2 + 1
        arr = np.ma.array(np.full((size, size), self._window, dtype=float))
        return arr, int(radius_px), int(radius_px)


def _located(lat: float = 22.77, lon: float = 113.505) -> LocatedPoint:
    return LocatedPoint(point=LatLon(lat=lat, lon=lon), source=LocationSource.USER_LATLON)


def _grounded_entity(confidence: Confidence = Confidence.HIGH) -> GroundedEntity:
    bm = MatchedRoad(
        osm_way_id="100",
        edge_ref=(1, 2, 0),
        road_name="测试路",
        highway="primary",
        bridge=True,
        tunnel=False,
        match_point=LatLon(lat=22.77, lon=113.505),
        match_distance_m=8.0,
        confidence=confidence,
    )
    return GroundedEntity(
        status=GroundingStatus.GROUNDED,
        query_point=LatLon(lat=22.77, lon=113.505),
        source=LocationSource.USER_LATLON,
        best_match=bm,
        candidates=[bm],
    )


def _unresolved_entity() -> GroundedEntity:
    return GroundedEntity(
        status=GroundingStatus.UNRESOLVED,
        query_point=LatLon(lat=22.77, lon=113.505),
        source=LocationSource.USER_LATLON,
        unresolved_reason=UnresolvedReason.OUT_OF_BUFFER,
    )


# --------------------------------------------------------------------------- #
# Road provider                                                                #
# --------------------------------------------------------------------------- #


class TestRoadProvider(unittest.TestCase):
    def test_grounded_emits_available_block(self):
        block = RoadProvider().query(_located(), _grounded_entity())
        self.assertEqual(block.block_type, "road")
        self.assertEqual(block.availability.status, Availability.AVAILABLE)
        self.assertEqual(block.road_name, "测试路")
        self.assertEqual(block.osm_way_id, 100)
        self.assertEqual(block.highway_class, HighwayClass.PRIMARY)
        self.assertTrue(block.is_bridge)
        self.assertFalse(block.is_tunnel)
        self.assertAlmostEqual(block.offset_distance_m, 8.0)
        self.assertEqual(block.grounding_confidence, 0.9)
        self.assertEqual(block.provenance.source, ContextSource.OSM)

    def test_unresolved_emits_unavailable_grounding_unresolved(self):
        block = RoadProvider().query(_located(), _unresolved_entity())
        self.assertEqual(block.availability.status, Availability.UNAVAILABLE)
        self.assertEqual(block.availability.reason, UnavailabilityReason.GROUNDING_UNRESOLVED)
        self.assertIsNone(block.road_name)
        self.assertIsNone(block.osm_way_id)

    def test_highway_link_folds_to_base_class(self):
        bm = MatchedRoad(
            osm_way_id="1", edge_ref=(1, 2, 0), highway="trunk_link",
            match_point=LatLon(lat=1, lon=2), match_distance_m=0.0, confidence=Confidence.HIGH,
        )
        ent = GroundedEntity(
            status=GroundingStatus.GROUNDED, query_point=LatLon(lat=1, lon=2),
            source=LocationSource.USER_LATLON, best_match=bm, candidates=[bm],
        )
        block = RoadProvider().query(_located(), ent)
        self.assertEqual(block.highway_class, HighwayClass.TRUNK)

    def test_non_numeric_way_id_is_none(self):
        bm = MatchedRoad(
            osm_way_id="way-x", edge_ref=(1, 2, 0), highway="service",
            match_point=LatLon(lat=1, lon=2), match_distance_m=0.0, confidence=Confidence.LOW,
        )
        ent = GroundedEntity(
            status=GroundingStatus.GROUNDED, query_point=LatLon(lat=1, lon=2),
            source=LocationSource.USER_LATLON, best_match=bm, candidates=[bm],
        )
        self.assertIsNone(RoadProvider().query(_located(), ent).osm_way_id)


# --------------------------------------------------------------------------- #
# Elevation provider                                                           #
# --------------------------------------------------------------------------- #


class TestElevationProvider(unittest.TestCase):
    def test_local_srtm_available_with_stats(self):
        prov = ElevationProvider(FakeReader(point_value=5.0, window_value=8.0))
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.availability.status, Availability.AVAILABLE)
        self.assertAlmostEqual(block.elevation_pt, 5.0)
        self.assertEqual(block.provenance.source, ContextSource.SRTM_LOCAL)
        self.assertGreater(block.stats.valid_pixels, 3000)
        self.assertAlmostEqual(block.stats.mean, 8.0)
        self.assertAlmostEqual(block.stats.std, 0.0)

    def test_fallback_served_is_uncertain(self):
        # Local nodata, point out of tile, one fallback answers.
        prov = ElevationProvider(
            FakeReader(point_value=None, in_bounds=False),
            fallbacks=[(ContextSource.OPEN_METEO, lambda la, lo: 12.0)],
        )
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.availability.status, Availability.UNCERTAIN)
        self.assertEqual(block.availability.reason, UnavailabilityReason.FALLBACK_USED)
        self.assertAlmostEqual(block.elevation_pt, 12.0)
        self.assertEqual(block.provenance.source, ContextSource.OPEN_METEO)
        self.assertEqual(block.stats.valid_pixels, 0)

    def test_all_tiers_exhausted_in_bounds_is_source_error(self):
        prov = ElevationProvider(
            FakeReader(point_value=None, in_bounds=True),
            fallbacks=[(ContextSource.OPEN_METEO, lambda la, lo: None)],
        )
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.availability.status, Availability.UNAVAILABLE)
        self.assertEqual(block.availability.reason, UnavailabilityReason.SOURCE_ERROR)

    def test_out_of_tile_no_fallback_is_no_data_in_bounds(self):
        prov = ElevationProvider(
            FakeReader(point_value=None, in_bounds=False), fallbacks=[],
        )
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.availability.status, Availability.UNAVAILABLE)
        self.assertEqual(block.availability.reason, UnavailabilityReason.NO_DATA_IN_BOUNDS)


# --------------------------------------------------------------------------- #
# Terrain provider                                                             #
# --------------------------------------------------------------------------- #


class TestTerrainProvider(unittest.TestCase):
    def test_depression_is_significantly_low(self):
        # Point 5 m, surroundings 8 m → TPI = +3 at every scale → composite 4.5.
        prov = TerrainProvider(FakeReader(point_value=5.0, window_value=8.0))
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.availability.status, Availability.AVAILABLE)
        self.assertEqual(block.lowness.lowness_class, LownessClass.SIGNIFICANTLY_LOW)
        self.assertAlmostEqual(block.lowness.meso, 3.0)
        self.assertAlmostEqual(block.lowness.composite, 4.5)

    def test_flat_is_level_or_higher(self):
        prov = TerrainProvider(FakeReader(point_value=5.0, window_value=5.0))
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.lowness.lowness_class, LownessClass.LEVEL_OR_HIGHER)
        self.assertAlmostEqual(block.lowness.composite, 0.0)

    def test_nodata_point_is_unavailable(self):
        prov = TerrainProvider(FakeReader(point_value=None, in_bounds=False))
        block = prov.query(_located(), _grounded_entity())
        self.assertEqual(block.availability.status, Availability.UNAVAILABLE)
        self.assertEqual(block.lowness.lowness_class, LownessClass.INSUFFICIENT_DATA)


# --------------------------------------------------------------------------- #
# Assembler                                                                    #
# --------------------------------------------------------------------------- #


class TestAssembler(unittest.TestCase):
    def test_assemble_orders_blocks_and_sets_query_point(self):
        provs = [
            RoadProvider(),
            ElevationProvider(FakeReader(point_value=5.0, window_value=8.0)),
            TerrainProvider(FakeReader(point_value=5.0, window_value=8.0)),
        ]
        ctx = ContextAssembler(provs).assemble(
            _located(), _grounded_entity(), source_location="南沙某路口"
        )
        self.assertEqual([b.block_type for b in ctx.blocks], ["road", "elevation", "terrain"])
        self.assertAlmostEqual(ctx.query_point.lat, 22.77)
        self.assertEqual(ctx.query_point.source_location, "南沙某路口")
        # typed accessors
        self.assertIsNotNone(ctx.road)
        self.assertIsNotNone(ctx.elevation)
        self.assertIsNotNone(ctx.terrain)

    def test_case_f_road_down_elevation_terrain_up(self):
        # Grounding unresolved(out_of_buffer): road unavailable, but elevation
        # and terrain still compute on the raw point (ADR-0002 §5 key behavior).
        provs = [
            RoadProvider(),
            ElevationProvider(FakeReader(point_value=5.0, window_value=8.0)),
            TerrainProvider(FakeReader(point_value=5.0, window_value=8.0)),
        ]
        ctx = ContextAssembler(provs).assemble(_located(), _unresolved_entity())
        self.assertEqual(ctx.road.availability.status, Availability.UNAVAILABLE)
        self.assertEqual(ctx.road.availability.reason, UnavailabilityReason.GROUNDING_UNRESOLVED)
        self.assertEqual(ctx.elevation.availability.status, Availability.AVAILABLE)
        self.assertEqual(ctx.terrain.availability.status, Availability.AVAILABLE)


class TestClassifyLowness(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(classify_lowness(None), LownessClass.INSUFFICIENT_DATA)
        self.assertEqual(classify_lowness(0.0), LownessClass.LEVEL_OR_HIGHER)
        self.assertEqual(classify_lowness(0.3), LownessClass.SLIGHTLY_LOW)
        self.assertEqual(classify_lowness(1.0), LownessClass.MODERATELY_LOW)
        self.assertEqual(classify_lowness(2.0), LownessClass.SIGNIFICANTLY_LOW)


if __name__ == "__main__":
    unittest.main()
