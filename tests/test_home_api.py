"""Tests for the dashboard home-mode HTTP handlers.

Mirrors the ``home_environment`` plugin's writer: the plugin writes
``output/home/agent_<id>.json`` + ``output/home/agent_<id>.jsonl``, and
``home_api.handle_get`` reads them. We don't run the simulation here — we
just stage the files and check what the endpoints return.

A resident the last run never touched has no file to read. The endpoint
rebuilds their flat from the roster instead (a home is a procedural design),
and says so with ``source="preview"``.
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gaworld.apps import home_api


def _write_home(
    root: Path, agent_id: int, design: dict | None = None, observations: list[dict] | None = None
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    design = design or {
        "home_id": f"agent_{agent_id}",
        "home_node": "Lakeview Tower",
        "rooms": {
            "living_room": {"name": "客厅", "size_sqm": 16, "furniture": ["沙发", "茶几"]},
            "kitchen": {"name": "厨房", "size_sqm": 8, "furniture": ["灶台"]},
        },
        "ambiance_quality": "comfortable",
        "vibe": "warm minimal",
        "ambient_state": {"lighting": "自然光"},
        "at_home_activities": {"living_room": ["看电视"], "kitchen": ["做饭"]},
    }
    (root / f"agent_{agent_id}.json").write_text(
        json.dumps(design, ensure_ascii=False),
        encoding="utf-8",
    )
    if observations:
        with (root / f"agent_{agent_id}.jsonl").open("w", encoding="utf-8") as f:
            for obs in observations:
                f.write(json.dumps(obs, ensure_ascii=False) + "\n")


class TestHomeList(unittest.TestCase):
    def test_list_returns_empty_when_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_api._output_root = lambda: Path(tmp) / "home"
            payload, status = home_api.handle_get("/api/home", {})
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"homes": [], "count": 0})

    def test_list_summarizes_each_designed_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            _write_home(root, 1)
            _write_home(root, 2)
            home_api._output_root = lambda: root
            payload, status = home_api.handle_get("/api/home", {})
            self.assertEqual(status, 200)
            self.assertEqual(payload["count"], 2)
            ids = sorted(h["agent_id"] for h in payload["homes"])
            self.assertEqual(ids, [1, 2])
            # Summary picks the rooms list + count + vibe.
            h1 = next(h for h in payload["homes"] if h["agent_id"] == 1)
            self.assertEqual(h1["room_count"], 2)
            self.assertEqual(h1["rooms"], ["living_room", "kitchen"])
            self.assertEqual(h1["vibe"], "warm minimal")

    def test_list_skips_malformed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            _write_home(root, 1)
            (root / "agent_broken.json").write_text("{not valid json", encoding="utf-8")
            home_api._output_root = lambda: root
            payload, status = home_api.handle_get("/api/home", {})
            self.assertEqual(status, 200)
            self.assertEqual(payload["count"], 1)


class TestHomeGet(unittest.TestCase):
    def test_returns_full_design_and_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            _write_home(
                root,
                42,
                observations=[
                    {
                        "day": 1,
                        "time": "08:00",
                        "current_room": {"key": "kitchen", "name": "厨房"},
                        "ambiance": {"lighting": "晨光初起", "sound": "很安静"},
                    },
                    {
                        "day": 1,
                        "time": "12:00",
                        "current_room": {"key": "living_room", "name": "客厅"},
                        "ambiance": {"lighting": "自然光", "sound": "电视/手机的低语"},
                    },
                ],
            )
            home_api._output_root = lambda: root
            payload, status = home_api.handle_get("/api/home/42", {})
            self.assertEqual(status, 200)
            self.assertEqual(payload["agent_id"], 42)
            self.assertEqual(payload["design"]["home_node"], "Lakeview Tower")
            self.assertEqual(len(payload["observations"]), 2)
            self.assertEqual(payload["observation_count"], 2)
            self.assertEqual(payload["summary"]["vibe"], "warm minimal")

    def test_returns_404_when_no_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_api._output_root = lambda: Path(tmp) / "home"
            payload, status = home_api.handle_get("/api/home/999", {})
            self.assertEqual(status, 404)
            self.assertIn("error", payload)

    def test_returns_400_on_non_integer_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_api._output_root = lambda: Path(tmp) / "home"
            _payload, status = home_api.handle_get("/api/home/abc", {})
            self.assertEqual(status, 400)

    def test_tail_query_param_caps_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            _write_home(root, 7, observations=[{"day": i, "time": f"{i:02d}:00"} for i in range(50)])
            home_api._output_root = lambda: root
            payload, _ = home_api.handle_get("/api/home/7", {"tail": ["5"]})
            self.assertEqual(len(payload["observations"]), 5)
            self.assertEqual(payload["observation_count"], 50)
            # Returns the *last* 5 rows, not the first.
            self.assertEqual(payload["observations"][-1]["day"], 49)

    def test_returns_404_on_unknown_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            home_api._output_root = lambda: Path(tmp) / "home"
            _payload, status = home_api.handle_get("/api/foo", {})
            self.assertEqual(status, 404)


class TestHomePreview(unittest.TestCase):
    """A resident the last run never touched still has a home."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roster = self.root / "agents.csv"
        with self.roster.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["id", "name", "monthly_income", "residence"],
            )
            writer.writeheader()
            writer.writerow({"id": "3", "name": "阿三", "monthly_income": "8000", "residence": "西湖·文新"})
        self.patchers = [
            patch.object(home_api, "_output_root", lambda: self.root / "home"),
            patch.object(home_api.world_paths, "state_csv_path", lambda: str(self.roster)),
            patch.object(
                home_api.world_paths,
                "effective_config",
                lambda: {"home": {"enabled": True, "seed": 42}},
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.addCleanup(self.tmp.cleanup)
        for patcher in self.patchers:
            self.addCleanup(patcher.stop)

    def test_rebuilds_the_flat_of_a_resident_who_never_ran(self):
        payload, status = home_api.handle_get("/api/home/3", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["has_home"])
        self.assertEqual(payload["source"], "preview")
        rooms = payload["design"]["rooms"]
        self.assertTrue(rooms)
        # The flat is the one the resident has: same rules the plugin uses.
        self.assertEqual(payload["design"]["home_id"], "agent_3")
        self.assertIn("living_room", rooms)
        self.assertEqual(payload["observation_count"], 0)

    def test_the_preview_is_deterministic(self):
        first, _ = home_api.handle_get("/api/home/3", {})
        second, _ = home_api.handle_get("/api/home/3", {})
        self.assertEqual(first["design"], second["design"])

    def test_the_income_tier_decides_the_rooms(self):
        payload, _ = home_api.handle_get("/api/home/3", {})
        # 8000 a month → the middle tier: a dining room and a study, no balcony.
        rooms = payload["design"]["rooms"]
        self.assertEqual(payload["design"]["ambiance_quality"], "comfortable")
        self.assertIn("dining_room", rooms)
        self.assertIn("study", rooms)
        self.assertNotIn("balcony", rooms)

    def test_a_resident_outside_the_roster_has_no_home(self):
        payload, status = home_api.handle_get("/api/home/404", {})
        self.assertEqual(status, 404)
        self.assertFalse(payload["has_home"])
        self.assertEqual(payload["reason"], "no_home_design")

    def test_no_home_when_the_plugin_is_off(self):
        with patch.object(
            home_api.world_paths,
            "effective_config",
            lambda: {"home": {"enabled": False, "seed": 42}},
        ):
            payload, status = home_api.handle_get("/api/home/3", {})
        self.assertEqual(status, 404)
        self.assertEqual(payload["reason"], "no_home_design")

    def test_a_run_design_wins_over_the_preview(self):
        root = self.root / "home"
        _write_home(root, 3)
        payload, _ = home_api.handle_get("/api/home/3", {})
        self.assertEqual(payload["source"], "run")
        self.assertEqual(payload["design"]["home_node"], "Lakeview Tower")


class TestHomeResilience(unittest.TestCase):
    def test_handles_missing_jsonl_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            _write_home(root, 5, observations=None)  # no jsonl file
            home_api._output_root = lambda: root
            payload, status = home_api.handle_get("/api/home/5", {})
            self.assertEqual(status, 200)
            self.assertEqual(payload["observations"], [])
            self.assertEqual(payload["observation_count"], 0)

    def test_skips_malformed_observation_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "home"
            _write_home(root, 5, observations=[{"day": 1, "time": "01:00"}])
            with (root / "agent_5.jsonl").open("a", encoding="utf-8") as f:
                f.write("not json\n")
                f.write("{another broken\n")
                f.write(json.dumps({"day": 2, "time": "02:00"}, ensure_ascii=False) + "\n")
            home_api._output_root = lambda: root
            payload, status = home_api.handle_get("/api/home/5", {})
            self.assertEqual(status, 200)
            # Two valid rows survive the malformed lines.
            self.assertEqual(len(payload["observations"]), 2)


if __name__ == "__main__":
    unittest.main()
