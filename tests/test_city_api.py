"""Dashboard ``/api/city/*`` routing, validation and status codes."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gaworld.apps import city_api
from gaworld.city.bundle import city_root
from gaworld.city.create import create_city


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
        self.assertEqual([c["slug"] for c in payload["cities"]], ["测试城"])
        self.assertIn("small", payload["scales"])
        self.assertIn("cn_county_town", payload["presets"])

    def test_detail_requires_a_city_and_404s_on_a_miss(self):
        payload, status = city_api.handle_get("/api/city/detail", {})
        self.assertEqual(status, 400)

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


if __name__ == "__main__":
    unittest.main()
