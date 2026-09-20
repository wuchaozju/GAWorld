import unittest

from gaworld.twin import geo
from gaworld.world.city_map import BASE_LAT, BASE_LNG, LAT_PER_KM, LNG_PER_KM


def _fake_map():
    """Two nodes 5 km apart on the x axis, built the way city_map builds them."""
    return {
        "nodes": {
            "home": {"id": "home", "name": "home", "x_km": 0.0, "y_km": 0.0},
            "office": {"id": "office", "name": "office", "x_km": 5.0, "y_km": 0.0},
        }
    }


def _lnglat_at_km(x_km, y_km):
    """Inverse of the projection, so tests can name a point in kilometres."""
    return (BASE_LNG + x_km * LNG_PER_KM, BASE_LAT + y_km * LAT_PER_KM)


class TestTwinGeo(unittest.TestCase):
    def test_project_round_trips_kilometres(self):
        lng, lat = _lnglat_at_km(3.0, -2.0)
        projected = geo.project(lng, lat)
        self.assertAlmostEqual(projected["x_km"], 3.0, places=2)
        self.assertAlmostEqual(projected["y_km"], -2.0, places=2)

    def test_locate_snaps_to_the_closest_node(self):
        lng, lat = _lnglat_at_km(4.6, 0.0)
        result = geo.locate(lng, lat, city_map=_fake_map(), max_snap_km=3.0)
        self.assertEqual(result["node_id"], "office")
        self.assertFalse(result["out_of_map"])
        self.assertAlmostEqual(result["snap_km"], 0.4, places=1)

    def test_locate_reports_out_of_map_instead_of_clamping(self):
        # 40 km away: far outside Hangzhou coverage. The nearest node must NOT
        # be returned, because a fabricated position would corrupt the mirror
        # channel and the calibration data downstream.
        lng, lat = _lnglat_at_km(40.0, 0.0)
        result = geo.locate(lng, lat, city_map=_fake_map(), max_snap_km=3.0)
        self.assertTrue(result["out_of_map"])
        self.assertIsNone(result["node_id"])

    def test_locate_handles_an_empty_map(self):
        result = geo.locate(120.15, 30.27, city_map={"nodes": {}}, max_snap_km=3.0)
        self.assertTrue(result["out_of_map"])
        self.assertIsNone(result["node_id"])


if __name__ == "__main__":
    unittest.main()
