"""Tests for the dashboard home-mode HTTP handlers.

Mirrors the ``home_environment`` plugin's writer: the plugin writes
``output/home/agent_<id>.json`` + ``output/home/agent_<id>.jsonl``, and
``home_api.handle_get`` reads them. We don't run the simulation here — we
just stage the files and check what the endpoints return.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
