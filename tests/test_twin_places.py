import json
import os
import tempfile
import unittest

from gaworld.twin import places


class TestTwinPlaces(unittest.TestCase):
    def test_names_a_province_level_city(self):
        self.assertEqual(places.describe(39.90, 116.41), "北京")

    def test_names_a_province_from_a_point_inside_it(self):
        # Ningbo is nowhere near a centre entry of its own; it should resolve
        # to Zhejiang rather than to a neighbouring province.
        self.assertEqual(places.describe(29.87, 121.55), "浙江")

    def test_a_city_bundle_beats_the_province_table(self):
        bundle = [{"name": "乌镇镇", "lat": 30.7465, "lng": 120.4819,
                   "bbox": [30.7114, 120.4469, 30.7814, 120.5169]}]
        self.assertEqual(
            places.describe(30.7465, 120.4819, city_places=bundle), "乌镇镇"
        )

    def test_a_point_outside_the_bundle_bbox_falls_through_to_province(self):
        bundle = [{"name": "乌镇镇", "lat": 30.7465, "lng": 120.4819,
                   "bbox": [30.7114, 120.4469, 30.7814, 120.5169]}]
        self.assertEqual(places.describe(39.90, 116.41, city_places=bundle), "北京")

    def test_far_from_any_centre_returns_coordinates_not_a_wrong_guess(self):
        # London. Naming this "新疆" because it is the least-distant entry
        # would be a confidently wrong label; coordinates are honest.
        result = places.describe(51.50, -0.12)
        self.assertIn("51.50°N", result)
        self.assertIn("0.12°W", result)

    def test_missing_or_invalid_coordinates_return_empty(self):
        self.assertEqual(places.describe(None, None), "")
        self.assertEqual(places.describe("nonsense", 1), "")

    def test_format_coords_marks_hemispheres(self):
        self.assertEqual(places.format_coords(-33.87, 151.21), "33.87°S 151.21°E")

    def test_load_city_places_reads_bundles_on_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            slug_dir = os.path.join(tmpdir, "wuzhen")
            os.makedirs(slug_dir)
            with open(os.path.join(slug_dir, "city.json"), "w", encoding="utf-8") as fh:
                json.dump({"slug": "wuzhen", "name": "乌镇镇",
                           "place": {"name": "乌镇镇", "lat": 30.7465, "lng": 120.4819,
                                     "bbox": [30.71, 120.44, 30.78, 120.51]}}, fh)
            loaded = places.load_city_places(city_dir=tmpdir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "乌镇镇")

    def test_load_city_places_skips_a_broken_bundle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for slug, payload in (("good", '{"place":{"name":"A","lat":1,"lng":2}}'),
                                  ("bad", "{not json")):
                os.makedirs(os.path.join(tmpdir, slug))
                with open(os.path.join(tmpdir, slug, "city.json"), "w",
                          encoding="utf-8") as fh:
                    fh.write(payload)
            self.assertEqual(len(places.load_city_places(city_dir=tmpdir)), 1)

    def test_load_city_places_on_a_missing_directory(self):
        self.assertEqual(places.load_city_places(city_dir="/nope/does/not/exist"), [])


if __name__ == "__main__":
    unittest.main()
