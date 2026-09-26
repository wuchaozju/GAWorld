"""Dashboard ``/api/city/*`` routing, validation and status codes."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gaworld.apps import city_api
from gaworld.city.bundle import city_root
from gaworld.city.create import CityCreationError, create_city


class CityApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.config_path = self.root / "dashboard_config.json"
        patches = [
            mock.patch.object(city_api, "DASHBOARD_CONFIG", self.config_path),
            # The API resolves bundles through the registry's default root, so
            # point that at the temp dir for the duration of the test.
            mock.patch("gaworld.city.bundle.PROJECT_ROOT", self.root),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

        self.city = create_city("测试城", offline=True, scale="small", root=self.root)

    def test_overview_lists_cities_and_the_selection(self):
        payload, statusd = city_api.handle_get("/api/city", {})
        self.assertEqual(statusd, 200)
        self.assertEqual(payload["selected"], "")
        # The default world (data/'s original dataset) is not a bundle under
        # the temp root, but it is always listed first, ahead of bundles.
        slugs = [c["slug"] for c in payload["cities"]]
        self.assertEqual(slugs[0], "")
        self.assertIn("测试城", slugs)
        self.assertIn("small", payload["scales"])
        self.assertIn("cn_county_town", payload["presets"])

    def test_detail_defaults_to_the_default_world_and_404s_on_a_miss(self):
        payload, status = city_api.handle_get("/api/city/detail", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["slug"], "")

        payload, status = city_api.handle_get("/api/city/detail", {"city": ["nope"]})
        self.assertEqual(status, 404)

        payload, status = city_api.handle_get("/api/city/detail", {"city": ["测试城"]})
        self.assertEqual(status, 200)
        self.assertTrue(payload["districts"])

    def test_unknown_endpoints_404(self):
        self.assertEqual(city_api.handle_get("/api/city/nope", {})[1], 404)
        self.assertEqual(city_api.handle_post("/api/city/nope", {})[1], 404)

    def test_create_validates_and_creates(self):
        payload, status = city_api.handle_post("/api/city/create", {"name": "  "})
        self.assertEqual(status, 400)

        payload, status = city_api.handle_post(
            "/api/city/create", {"name": "新镇", "offline": True, "scale": "tiny"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["city"]["slug"], "新镇")
        self.assertTrue((city_root(self.root) / "新镇").is_dir())

    def test_create_rejects_an_oversized_population(self):
        payload, status = city_api.handle_post(
            "/api/city/create", {"name": "巨城", "offline": True, "size": 999999}
        )
        self.assertEqual(status, 400)

    def test_population_validates_size(self):
        for size in (0, -5, 999999):
            payload, status = city_api.handle_post(
                "/api/city/population", {"city": "测试城", "size": size}
            )
            self.assertEqual(status, 400, size)

    def test_add_agent_validates_name_and_age(self):
        payload, status = city_api.handle_post(
            "/api/city/agent", {"city": "测试城", "name": "", "age": 30}
        )
        self.assertEqual(status, 400)

        payload, status = city_api.handle_post(
            "/api/city/agent", {"city": "测试城", "name": "甲", "age": "abc"}
        )
        self.assertEqual(status, 400)

        payload, status = city_api.handle_post(
            "/api/city/agent", {"city": "测试城", "name": "甲", "age": 30}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["agent"]["id"], 1)

    def test_select_round_trips_through_the_config_file(self):
        payload, status = city_api.handle_post("/api/city/select", {"city": "测试城"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["selected"], "测试城")
        self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8"))["city"], "测试城")

        payload, _ = city_api.handle_post("/api/city/select", {"clear": True})
        self.assertEqual(payload["selected"], "")
        self.assertNotIn("city", json.loads(self.config_path.read_text(encoding="utf-8")))

    def test_select_preserves_other_config_keys(self):
        self.config_path.write_text(json.dumps({"sim_days": 365}), encoding="utf-8")
        city_api.handle_post("/api/city/select", {"city": "测试城"})
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["sim_days"], 365)
        self.assertEqual(config["city"], "测试城")

    def test_deleting_the_selected_city_clears_the_selection(self):
        city_api.handle_post("/api/city/select", {"city": "测试城"})
        payload, status = city_api.handle_post("/api/city/delete", {"city": "测试城"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["cleared_selection"])
        # Never leave the config pointing at a directory that no longer exists.
        self.assertNotIn("city", json.loads(self.config_path.read_text(encoding="utf-8")))


class CityResidentsTest(unittest.TestCase):
    """``/api/city/catalogue``, ``/api/city/agents`` and ``/api/city/agent``.

    These are the reads behind "list this city's residents" and "look at
    another city's residents from Agent Studio". They go to the *bundle*, not
    through the simulator's globals, so they must work for a city that is not
    the selected one — that is the whole point of them.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.config_path = self.root / "dashboard_config.json"
        for patch in (
            mock.patch.object(city_api, "DASHBOARD_CONFIG", self.config_path),
            mock.patch("gaworld.city.bundle.PROJECT_ROOT", self.root),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        create_city("测试城", offline=True, scale="small", root=self.root)
        for name, age, job in (("阿甲", 31, "社区医生"), ("阿乙", 46, "货车司机"), ("阿丙", 27, "面点师")):
            payload, status = city_api.handle_post(
                "/api/city/agent", {"city": "测试城", "name": name, "age": age, "job": job}
            )
            self.assertEqual(status, 200, payload)

    def test_catalogue_lists_the_default_world_first(self):
        payload, status = city_api.handle_get("/api/city/catalogue", {})
        self.assertEqual(status, 200)
        self.assertEqual("", payload["cities"][0]["slug"])
        self.assertIn("测试城", [c["slug"] for c in payload["cities"]])

    def test_agents_lists_residents_of_a_city_that_is_not_selected(self):
        payload, status = city_api.handle_get("/api/city/agents", {"city": ["测试城"]})
        self.assertEqual(status, 200)
        self.assertFalse(payload["city"]["selected"], "the test city is not the running one")
        self.assertEqual("测试城", payload["city"]["slug"])
        self.assertEqual(3, payload["matched"])
        self.assertEqual(["阿甲", "阿乙", "阿丙"], [a["name"] for a in payload["agents"]])

    def test_每个居民都带九个状态变量(self):
        payload, _ = city_api.handle_get("/api/city/agents", {"city": ["测试城"]})
        for person in payload["agents"]:
            self.assertEqual(9, len(person["state"]))
            self.assertTrue(all(0.0 <= v <= 1.0 for v in person["state"].values()))

    def test_the_stamp_reports_the_running_city(self):
        city_api.handle_post("/api/city/select", {"city": "测试城"})
        payload, _ = city_api.handle_get("/api/city/agents", {"city": ["测试城"]})
        self.assertTrue(payload["city"]["selected"])

    def test_search_matches_name_job_and_id(self):
        for needle, expected in (("阿乙", ["阿乙"]), ("面点", ["阿丙"]), ("2", ["阿乙"])):
            payload, _ = city_api.handle_get(
                "/api/city/agents", {"city": ["测试城"], "q": [needle]}
            )
            self.assertEqual(expected, [a["name"] for a in payload["agents"]], needle)

    def test_search_that_matches_nobody_is_an_empty_list_not_an_error(self):
        payload, status = city_api.handle_get(
            "/api/city/agents", {"city": ["测试城"], "q": ["没有这个人"]}
        )
        self.assertEqual(200, status)
        self.assertEqual(0, payload["matched"])
        self.assertEqual([], payload["agents"])

    def test_paging_reports_the_full_count(self):
        payload, _ = city_api.handle_get(
            "/api/city/agents", {"city": ["测试城"], "limit": ["2"], "offset": ["1"]}
        )
        self.assertEqual(3, payload["matched"], "matched counts the whole population, not the page")
        self.assertEqual(["阿乙", "阿丙"], [a["name"] for a in payload["agents"]])

    def test_a_broken_page_window_falls_back_instead_of_failing(self):
        payload, status = city_api.handle_get(
            "/api/city/agents", {"city": ["测试城"], "limit": ["abc"], "offset": ["-9"]}
        )
        self.assertEqual(200, status)
        self.assertEqual(0, payload["offset"])
        self.assertEqual(3, len(payload["agents"]))

    def test_agents_of_an_unknown_city_404(self):
        _payload, status = city_api.handle_get("/api/city/agents", {"city": ["nope"]})
        self.assertEqual(404, status)

    def test_agent_detail_carries_state_and_profile_text(self):
        payload, status = city_api.handle_get(
            "/api/city/agent", {"city": ["测试城"], "id": ["1"]}
        )
        self.assertEqual(200, status)
        self.assertEqual("阿甲", payload["agent"]["name"])
        self.assertEqual(31, payload["agent"]["age"])
        self.assertEqual(9, len(payload["agent"]["state"]))
        self.assertIn("阿甲", payload["agent"]["profile_text"])
        self.assertIn("社区医生", payload["agent"]["profile_text"])

    def test_agent_detail_validates_the_id(self):
        _payload, status = city_api.handle_get("/api/city/agent", {"city": ["测试城"]})
        self.assertEqual(400, status, "a missing id is a bad request")

        _payload, status = city_api.handle_get(
            "/api/city/agent", {"city": ["测试城"], "id": ["abc"]}
        )
        self.assertEqual(400, status, "an unparseable id is a bad request")

        _payload, status = city_api.handle_get(
            "/api/city/agent", {"city": ["测试城"], "id": ["999"]}
        )
        self.assertEqual(404, status, "a resident who does not exist is a miss")


class SketchUploadTest(unittest.TestCase):
    """Decoding the sketch a browser posts for an imagined city."""

    def test_a_data_url_is_split_into_media_type_and_payload(self):
        images = city_api._sketch_images({"image": "data:image/jpeg;base64,QUJD"})
        self.assertEqual([{"media_type": "image/jpeg", "data": "QUJD"}], images)

    def test_bare_base64_is_assumed_to_be_png(self):
        self.assertEqual("image/png", city_api._sketch_images({"image": "QUJD"})[0]["media_type"])

    def test_no_image_is_not_an_error(self):
        self.assertEqual([], city_api._sketch_images({}))
        self.assertEqual([], city_api._sketch_images({"image": "  "}))

    def test_a_non_image_data_url_is_rejected(self):
        with self.assertRaises(CityCreationError):
            city_api._sketch_images({"image": "data:application/pdf;base64,QUJD"})

    def test_a_truncated_data_url_is_rejected(self):
        with self.assertRaises(CityCreationError):
            city_api._sketch_images({"image": "data:image/png;base64"})

    def test_an_oversized_sketch_is_rejected(self):
        oversized = "data:image/png;base64," + "A" * (city_api.MAX_SKETCH_B64 + 1)
        with self.assertRaises(CityCreationError):
            city_api._sketch_images({"image": oversized})


if __name__ == "__main__":
    unittest.main()
