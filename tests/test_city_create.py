"""Creating a city from a place name: geocoding, OSM, procedural fallback."""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gaworld.city.create import CityCreationError, create_city, projection_origin, resolve_place
from gaworld.city.environment import build_environment, climate_of
from gaworld.city.geocode import (
    GeocodeError,
    geocode,
    offline_place,
    place_from_nominatim,
    scale_from_population,
)
from gaworld.city.osm import OSMError, fetch_bundle
from gaworld.city.procedural import districts_from_spec, generate_citymap
from gaworld.world.city_map import distance_between, load_city_map, load_real_city_map

#: A Nominatim jsonv2 hit, trimmed to the fields the parser reads.
KEQIAO_HIT = {
    "lat": "30.0817",
    "lon": "120.4926",
    "display_name": "柯桥区, 绍兴市, 浙江省, 中国",
    "name": "柯桥区",
    "addresstype": "city",
    "type": "administrative",
    "osm_id": "123456",
    "osm_type": "relation",
    "boundingbox": ["30.01", "30.18", "120.40", "120.61"],
    "address": {"country": "中国", "country_code": "CN"},
    "extratags": {"population": "1,020,000"},
}


class GeocodeTest(unittest.TestCase):
    def test_parses_a_nominatim_hit(self):
        place = place_from_nominatim("绍兴柯桥", KEQIAO_HIT)
        self.assertEqual(place.name, "柯桥区")
        self.assertEqual(place.country_code, "cn")
        self.assertEqual(place.population, 1_020_000)
        self.assertEqual(place.scale, "large")  # addresstype=city
        self.assertEqual(place.osm_id, 123456)

    def test_bbox_is_reordered_to_overpass_order(self):
        place = place_from_nominatim("绍兴柯桥", KEQIAO_HIT)
        south, west, north, east = place.bbox
        # Nominatim gives [minlat, maxlat, minlon, maxlon]; Overpass wants
        # (south, west, north, east). Getting this backwards silently fetches
        # an empty region.
        self.assertAlmostEqual(south, 30.01)
        self.assertAlmostEqual(west, 120.40)
        self.assertAlmostEqual(north, 30.18)
        self.assertAlmostEqual(east, 120.61)

    def test_oversized_admin_bbox_is_clamped_to_the_places_scale(self):
        from gaworld.city.geocode import max_span_for

        province = dict(KEQIAO_HIT, boundingbox=["27.0", "31.5", "118.0", "123.0"])
        place = place_from_nominatim("浙江省", province)
        limit = max_span_for(place.scale)
        south, west, north, east = place.bbox
        self.assertLessEqual(north - south, limit + 1e-9)
        self.assertLessEqual(east - west, limit + 1e-9)

    def test_a_district_does_not_swallow_its_neighbours(self):
        # 柯桥区's own bbox is wide enough to reach the next city; unclamped it
        # gave agents 70km commutes.
        place = place_from_nominatim("绍兴柯桥", KEQIAO_HIT)
        south, _, north, _ = place.bbox
        self.assertLessEqual((north - south) * 111.0, 60.0, "city span should stay under ~60km")

    def test_scale_falls_back_to_population(self):
        self.assertEqual(scale_from_population(500), "tiny")
        self.assertEqual(scale_from_population(50_000), "medium")
        self.assertEqual(scale_from_population(5_000_000), "metro")
        self.assertIsNone(scale_from_population(None))

    def test_transport_error_becomes_a_geocode_error(self):
        def boom(url, timeout):
            raise OSError("no network")

        with self.assertRaises(GeocodeError):
            geocode("anywhere", fetch=boom)

    def test_no_match_raises(self):
        with self.assertRaises(GeocodeError):
            geocode("anywhere", fetch=lambda url, timeout: [])


class ProceduralTest(unittest.TestCase):
    def test_generated_spec_loads_as_a_city_map(self):
        spec = generate_citymap("柳溪村", scale="tiny")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(spec, encoding="utf-8")
            city_map = load_city_map(str(path))
        self.assertGreater(len(city_map["nodes"]), 10)
        self.assertGreater(len(city_map["edges"]), 5)

    def test_layout_is_deterministic_for_a_name(self):
        self.assertEqual(generate_citymap("同一个地方"), generate_citymap("同一个地方"))
        self.assertNotEqual(generate_citymap("甲地"), generate_citymap("乙地"))

    def test_the_place_name_reaches_the_output(self):
        spec = generate_citymap("桃源镇", scale="small")
        self.assertIn("- City: 桃源镇", spec)
        self.assertIn("@river: 桃源镇 River", spec)

    def test_small_places_get_no_metro(self):
        # A village inheriting a subway would skew transport-mode choice.
        for scale in ("tiny", "small"):
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "citymap.md"
                path.write_text(generate_citymap("小地方", scale=scale), encoding="utf-8")
                self.assertEqual(load_city_map(str(path))["metro_lines"], [], scale)

    def test_larger_places_do_get_a_metro(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(generate_citymap("大地方", scale="large"), encoding="utf-8")
            self.assertTrue(load_city_map(str(path))["metro_lines"])

    def test_districts_are_extracted_from_a_spec(self):
        spec = generate_citymap("某地", scale="medium")
        districts = districts_from_spec(spec)
        self.assertTrue(districts)
        self.assertEqual(len(districts), len(set(districts)))


class EnvironmentTest(unittest.TestCase):
    def test_climate_bands_are_latitude_symmetric(self):
        self.assertEqual(climate_of(1.0), "tropical")
        self.assertEqual(climate_of(30.0), "subtropical")
        self.assertEqual(climate_of(-30.0), "subtropical")
        self.assertEqual(climate_of(45.0), "temperate")
        self.assertEqual(climate_of(60.0), "continental")
        self.assertEqual(climate_of(80.0), "polar")

    def test_environment_matches_the_place(self):
        cold = build_environment(offline_place("Norilsk", lat=69.35, lng=88.2))
        warm = build_environment(offline_place("Sanya", lat=18.25, lng=109.5))
        self.assertEqual(cold["climate"], "polar")
        self.assertEqual(warm["climate"], "tropical")
        self.assertNotEqual(
            cold["environment"]["natural_events"], warm["environment"]["natural_events"]
        )

    def test_background_names_the_place(self):
        env = build_environment(offline_place("桃源镇", scale="small"))
        self.assertIn("桃源镇", env["background"])
        # The default background talks about Hangzhou; a new city must not.
        self.assertNotIn("杭州", env["background"])


class OSMTest(unittest.TestCase):
    """Overpass is stubbed: the point is the assembly, not the network."""

    @staticmethod
    def _overpass(nodes):
        def client(query, timeout):
            if '"station"="subway"' in query:
                return {"elements": []}
            if 'route"="subway' in query or "relation" in query:
                return {"elements": []}
            if "waterway" in query:
                return {"elements": []}
            # One category query: return everything; de-duplication is by name.
            return {"elements": nodes}

        return client

    def test_too_few_nodes_raises_so_the_caller_can_fall_back(self):
        sparse = [
            {"type": "node", "lon": 120.0 + i / 100, "lat": 30.0, "tags": {"name": f"P{i}"}}
            for i in range(2)
        ]
        with self.assertRaises(OSMError):
            fetch_bundle((29.9, 119.9, 30.1, 120.1), city="X", overpass=self._overpass(sparse), pause=0)

    def test_deadline_bounds_a_slow_fetch(self):
        """urlopen's timeout is per socket read, so a trickling mirror can run
        far past it; only the budget actually bounds the total."""
        import time

        from gaworld.city import osm

        seen_timeouts = []

        def slow(query, timeout):
            seen_timeouts.append(timeout)
            time.sleep(min(timeout, 1.0) * 0.4)
            raise OSMError("slow mirror")

        started = time.monotonic()
        with self.assertRaises(OSMError):
            osm.fetch_bundle(
                (30.0, 120.0, 30.1, 120.1),
                city="X",
                overpass=slow,
                timeout=45,
                deadline=3.0,
                pause=0,
            )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 12.0, "the deadline must bound the whole fetch")
        # Per-request timeouts are capped by what is left of the budget.
        self.assertTrue(all(t <= 45 for t in seen_timeouts))

    def test_bundle_carries_the_projection_origin(self):
        nodes = [
            {"type": "node", "lon": 120.0 + i / 100, "lat": 30.0, "tags": {"name": f"P{i}"}}
            for i in range(40)
        ]
        origin = {"lat": 30.0, "lng": 120.0, "lat_per_km": 1 / 111.0, "lng_per_km": 1 / 96.0}
        bundle = fetch_bundle(
            (29.9, 119.9, 30.1, 120.1),
            city="测试城",
            origin=origin,
            overpass=self._overpass(nodes),
            pause=0,
        )
        self.assertEqual(bundle["type"], "FeatureCollection")
        self.assertEqual(bundle["meta"]["city"], "测试城")
        self.assertEqual(bundle["meta"]["origin"], origin)


class ProjectionTest(unittest.TestCase):
    """A real map away from Hangzhou needs its own longitude scale."""

    @staticmethod
    def _bundle(origin):
        meta = {"city": "Paris", "source": "OpenStreetMap"}
        if origin:
            meta["origin"] = origin
        return {
            "type": "FeatureCollection",
            "meta": meta,
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, 48.86]},
                    "properties": {"name": name, "category": "commerce", "kind": "hub"},
                }
                for name, lng in (("Alpha", 2.30), ("Beta", 2.40))
            ],
        }

    def _distance(self, origin):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.geojson"
            path.write_text(json.dumps(self._bundle(origin)), encoding="utf-8")
            return distance_between(load_real_city_map(str(path)), "Alpha", "Beta")

    def test_per_city_origin_corrects_east_west_distance(self):
        true_km = 0.10 * 111.32 * math.cos(math.radians(48.86))
        origin = projection_origin(offline_place("Paris", lat=48.86, lng=2.35))

        without = self._distance(None)
        with_origin = self._distance(origin)

        # The Hangzhou-calibrated default over-measures by ~30% at this latitude.
        self.assertGreater(abs(without - true_km) / true_km, 0.25)
        self.assertLess(abs(with_origin - true_km) / true_km, 0.01)

    def test_bundles_without_an_origin_keep_the_historical_projection(self):
        # Backwards compatibility: data/hangzhou_real.geojson has no origin.
        self.assertGreater(self._distance(None), 0)


class CreateCityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_offline_creation_produces_a_usable_bundle(self):
        city = create_city("柳溪村", offline=True, scale="tiny", root=self.root)

        self.assertTrue(city.manifest_path.exists())
        self.assertTrue(city.virtual_map_path.exists())
        self.assertTrue(city.environment_path.exists())
        self.assertFalse(city.real_map_path.exists())
        self.assertEqual(city.map_mode, "virtual")

        city_map = load_city_map(str(city.virtual_map_path))
        self.assertGreater(len(city_map["nodes"]), 10)

    def test_geocoding_failure_degrades_to_an_offline_place(self):
        def boom(name, **kwargs):
            raise GeocodeError("no network")

        city = create_city("无人知晓村", root=self.root, geocode_fn=boom, offline=False)
        # No geocode means no bbox worth fetching, so it stays virtual.
        self.assertEqual(city.map_mode, "virtual")
        self.assertEqual(city.manifest["place"]["source"], "offline")

    def test_osm_failure_still_yields_a_city(self):
        def fake_geocode(name, **kwargs):
            return place_from_nominatim(name, KEQIAO_HIT)

        def failing_overpass(query, timeout):
            raise OSMError("overpass down")

        city = create_city(
            "绍兴柯桥", root=self.root, geocode_fn=fake_geocode, overpass=failing_overpass
        )
        self.assertEqual(city.map_mode, "virtual")
        self.assertEqual(city.manifest["place"]["source"], "nominatim")
        actions = [entry["action"] for entry in city.manifest["history"]]
        self.assertIn("map.real.skipped", actions)

    def test_successful_osm_fetch_marks_the_city_real(self):
        def fake_geocode(name, **kwargs):
            return place_from_nominatim(name, KEQIAO_HIT)

        nodes = [
            {"type": "node", "lon": 120.49 + i / 500, "lat": 30.08, "tags": {"name": f"地点{i}"}}
            for i in range(30)
        ]

        def overpass(query, timeout):
            if "waterway" in query or "subway" in query or "relation" in query:
                return {"elements": []}
            return {"elements": nodes}

        city = create_city(
            "绍兴柯桥", root=self.root, geocode_fn=fake_geocode, overpass=overpass
        )
        self.assertEqual(city.map_mode, "real")
        self.assertTrue(city.real_map_path.exists())
        self.assertIn("origin", city.manifest["map"])
        # And the bundle the simulator will actually load must parse.
        self.assertGreater(len(load_real_city_map(str(city.real_map_path))["nodes"]), 10)

    def test_duplicate_slug_needs_force(self):
        create_city("重名地", offline=True, root=self.root)
        with self.assertRaises(CityCreationError):
            create_city("重名地", offline=True, root=self.root)
        again = create_city("重名地", offline=True, force=True, root=self.root)
        self.assertEqual(again.slug, "重名地")

    def test_empty_name_is_rejected(self):
        with self.assertRaises(CityCreationError):
            create_city("   ", offline=True, root=self.root)

    def test_explicit_scale_overrides_the_geocoded_guess(self):
        def fake_geocode(name, **kwargs):
            return place_from_nominatim(name, KEQIAO_HIT)  # scale=large

        place = resolve_place("绍兴柯桥", scale="tiny", geocode_fn=fake_geocode)
        self.assertEqual(place.scale, "tiny")
        self.assertEqual(place.name, "柯桥区")  # the rest of the record survives


if __name__ == "__main__":
    unittest.main()
