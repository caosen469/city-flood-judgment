# -*- coding: utf-8 -*-
"""Stage 2a Grounding tests (``src/grounding/``).

Hermetic: no network, no dependency on the gitignored GeoPackage. A small
synthetic road network is built via :meth:`RoadNetwork.from_edges` so the
distance bands, ambiguity override, way-clustering and unresolved reasons are
asserted against known metric offsets.

Run: ``python -m unittest tests.test_grounding -v``
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grounding import RoadNetwork, ground, locate  # noqa: E402
from grounding.match import (  # noqa: E402
    _distance_band,
    _first_str,
    _highway_of,
    _truthy_tag,
    _way_id_of,
    match,
)
from schemas.grounding import (  # noqa: E402
    Confidence,
    GroundingStatus,
    LocationSource,
    UnresolvedReason,
)
from schemas.observation import LocationRef  # noqa: E402

# 1 m of latitude at ~22.8°N, in degrees (UTM confirms the band either way).
M_LAT_DEG = 1.0 / 110_574.0
ROAD_LAT = 22.7700
ROAD_LON_MID = 113.505


def _edges(*specs: tuple[int, float, float, float, float, dict]) -> gpd.GeoDataFrame:
    """Build a WGS-84 edges frame. Each spec = (osmid, lon0, lat0, lon1, lat1, tags)."""
    rows = []
    for i, (osmid, lon0, lat0, lon1, lat1, tags) in enumerate(specs):
        row = {"u": i * 2, "v": i * 2 + 1, "key": 0, "osmid": osmid,
               "geometry": LineString([(lon0, lat0), (lon1, lat1)])}
        row.update(tags)
        rows.append(row)
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return gdf.set_index(["u", "v", "key"])


def _nodes_frame() -> gpd.GeoDataFrame:
    """Nodes spanning a wide bbox so the road-free north/south stays *inside*
    the coverage gate (lets us test out_of_buffer distinctly from outside_nansha)."""
    pts = [Point(lo, la) for lo, la in [
        (113.45, 22.60), (113.55, 22.60), (113.45, 22.90), (113.55, 22.90)
    ]]
    return gpd.GeoDataFrame({"osmid": [1, 2, 3, 4], "geometry": pts}, crs="EPSG:4326")


def _single_road_network() -> RoadNetwork:
    """One isolated primary road at ROAD_LAT — no runner-up, so never ambiguous."""
    edges = _edges(
        (100, 113.500, ROAD_LAT, 113.510, ROAD_LAT,
         {"highway": "primary", "name:zh": "测试路A", "bridge": "no"}),
    )
    return RoadNetwork.from_edges(_nodes_frame(), edges)


class TestLocate(unittest.TestCase):
    def test_latlon_passthrough_default_user_latlon(self):
        lp = locate(LocationRef(lat=1.0, lon=2.0))
        self.assertAlmostEqual(lp.point.lat, 1.0)
        self.assertAlmostEqual(lp.point.lon, 2.0)
        self.assertEqual(lp.source, LocationSource.USER_LATLON)
        self.assertIsNone(lp.geocode_confidence)

    def test_latlon_passthrough_exif_source(self):
        lp = locate(LocationRef(lat=1.0, lon=2.0), source=LocationSource.EXIF)
        self.assertEqual(lp.source, LocationSource.EXIF)

    def test_text_geocode_success(self):
        geocoder = lambda q: (10.0, 20.0, Confidence.MEDIUM)  # noqa: E731
        lp = locate(LocationRef(raw_text="某地"), geocoder=geocoder)
        self.assertEqual(lp.source, LocationSource.GEOCODED_TEXT)
        self.assertAlmostEqual(lp.point.lat, 10.0)
        self.assertEqual(lp.geocode_confidence, Confidence.MEDIUM)

    def test_text_geocode_failure_returns_none(self):
        self.assertIsNone(locate(LocationRef(raw_text="x"), geocoder=lambda q: None))

    def test_empty_ref_returns_none(self):
        self.assertIsNone(locate(LocationRef()))
        self.assertIsNone(locate(None))

    def test_latlon_takes_precedence_over_text(self):
        # If both are present, the precise coordinate wins — no geocode call.
        called = []
        geocoder = lambda q: called.append(q) or (9.0, 9.0, Confidence.LOW)  # noqa: E731
        lp = locate(LocationRef(lat=1.0, lon=2.0, raw_text="ignored"), geocoder=geocoder)
        self.assertEqual(lp.source, LocationSource.USER_LATLON)
        self.assertEqual(called, [])


class TestMatchBands(unittest.TestCase):
    def setUp(self):
        self.net = _single_road_network()

    def test_on_road_is_grounded_high(self):
        ent = match(ROAD_LAT, ROAD_LON_MID, network=self.net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.GROUNDED)
        self.assertEqual(ent.best_match.confidence, Confidence.HIGH)
        self.assertLess(ent.best_match.match_distance_m, 1.0)
        self.assertEqual(ent.best_match.road_name, "测试路A")
        self.assertEqual(ent.best_match.osm_way_id, "100")
        self.assertIn(ent.best_match, ent.candidates)

    def test_band_medium_20m(self):
        ent = match(ROAD_LAT + 20 * M_LAT_DEG, ROAD_LON_MID,
                    network=self.net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.GROUNDED)
        self.assertEqual(ent.best_match.confidence, Confidence.MEDIUM)

    def test_band_low_50m(self):
        ent = match(ROAD_LAT + 50 * M_LAT_DEG, ROAD_LON_MID,
                    network=self.net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.GROUNDED)
        self.assertEqual(ent.best_match.confidence, Confidence.LOW)

    def test_out_of_buffer_inside_bbox(self):
        # 150 m north of the road — still inside the coverage bbox (>100 m) →
        # unresolved(out_of_buffer), NOT outside_nansha.
        ent = match(ROAD_LAT + 150 * M_LAT_DEG, ROAD_LON_MID,
                    network=self.net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.UNRESOLVED)
        self.assertEqual(ent.unresolved_reason, UnresolvedReason.OUT_OF_BUFFER)
        self.assertIsNotNone(ent.query_point)

    def test_outside_nansha(self):
        ent = match(23.5, 116.0, network=self.net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.UNRESOLVED)
        self.assertEqual(ent.unresolved_reason, UnresolvedReason.OUTSIDE_NANSHA)


class TestAmbiguityAndClustering(unittest.TestCase):
    def test_two_close_roads_are_ambiguous(self):
        # Two parallel roads 10 m apart → a point between them is genuinely not
        # unique: runner-up within 15 m ⇒ ambiguous.
        edges = _edges(
            (100, 113.500, ROAD_LAT, 113.510, ROAD_LAT, {"highway": "primary"}),
            (200, 113.500, ROAD_LAT + 10 * M_LAT_DEG, 113.510, ROAD_LAT + 10 * M_LAT_DEG,
             {"highway": "residential"}),
        )
        net = RoadNetwork.from_edges(_nodes_frame(), edges)
        ent = match(ROAD_LAT + 5 * M_LAT_DEG, ROAD_LON_MID,
                    network=net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.AMBIGUOUS)
        self.assertGreaterEqual(len(ent.candidates), 2)

    def test_dual_carriageway_collapses_to_one_candidate(self):
        # Two edges sharing one osmid (both directions of one road) 6 m apart →
        # re-clustered to a single candidate, so NOT ambiguous.
        edges = _edges(
            (100, 113.500, ROAD_LAT, 113.510, ROAD_LAT, {"highway": "primary"}),
            (100, 113.500, ROAD_LAT + 6 * M_LAT_DEG, 113.510, ROAD_LAT + 6 * M_LAT_DEG,
             {"highway": "primary"}),
        )
        net = RoadNetwork.from_edges(_nodes_frame(), edges)
        ent = match(ROAD_LAT + 3 * M_LAT_DEG, ROAD_LON_MID,
                    network=net, source=LocationSource.USER_LATLON)
        self.assertEqual(ent.status, GroundingStatus.GROUNDED)
        self.assertEqual(len(ent.candidates), 1)


class TestGroundOrchestrator(unittest.TestCase):
    def test_no_location(self):
        ent = ground(LocationRef(), network=_single_road_network())
        self.assertEqual(ent.status, GroundingStatus.UNRESOLVED)
        self.assertEqual(ent.unresolved_reason, UnresolvedReason.NO_LOCATION)
        self.assertIsNone(ent.query_point)
        self.assertEqual(ent.source, LocationSource.NONE)

    def test_geocode_failed(self):
        ent = ground(LocationRef(raw_text="不存在"),
                     network=_single_road_network(), geocoder=lambda q: None)
        self.assertEqual(ent.status, GroundingStatus.UNRESOLVED)
        self.assertEqual(ent.unresolved_reason, UnresolvedReason.GEOCODE_FAILED)
        self.assertIsNone(ent.query_point)

    def test_latlon_passthrough_matches(self):
        ent = ground(LocationRef(lat=ROAD_LAT, lon=ROAD_LON_MID),
                     network=_single_road_network())
        self.assertEqual(ent.status, GroundingStatus.GROUNDED)
        self.assertEqual(ent.source, LocationSource.USER_LATLON)


class TestCoercionHelpers(unittest.TestCase):
    def test_distance_bands(self):
        self.assertEqual(_distance_band(0.0), Confidence.HIGH)
        self.assertEqual(_distance_band(14.9), Confidence.HIGH)
        self.assertEqual(_distance_band(15.0), Confidence.MEDIUM)
        self.assertEqual(_distance_band(34.9), Confidence.MEDIUM)
        self.assertEqual(_distance_band(35.0), Confidence.LOW)
        self.assertEqual(_distance_band(99.9), Confidence.LOW)

    def test_way_id_of_handles_list(self):
        self.assertEqual(_way_id_of({"osmid": [7, 8, 9]}), "7")
        self.assertEqual(_way_id_of({"osmid": 7}), "7")

    def test_truthy_tag(self):
        self.assertTrue(_truthy_tag("yes"))
        self.assertTrue(_truthy_tag("viaduct"))
        self.assertTrue(_truthy_tag(True))
        self.assertFalse(_truthy_tag("no"))
        self.assertFalse(_truthy_tag(""))
        self.assertFalse(_truthy_tag(None))

    def test_first_str_and_highway(self):
        self.assertIsNone(_first_str(None))
        self.assertEqual(_first_str(["a", "b"]), "a")
        self.assertEqual(_highway_of({"highway": "primary"}), "primary")
        self.assertEqual(_highway_of({}), "unclassified")


if __name__ == "__main__":
    unittest.main()
