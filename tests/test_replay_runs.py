"""Discovery of replayable traces for the simulation replay page.

The replay page must list every run on disk — the live one, the per-run
archives, and the traces scenario runs leave in their own output trees — and it
must do that without parsing multi-megabyte traces in full.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gaworld.apps import replay_runs

ROOT = Path(__file__).resolve().parents[1]


def _write_trace(path, meta, frames=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "meta": meta,
        "map": {"nodes": [], "tile_map": {"width": 160, "height": 112}},
        "agents": [],
        "frames": [{"index": i} for i in range(frames)],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


class ReadTraceMetaTests(unittest.TestCase):
    def test_meta_is_read_from_the_head_of_a_huge_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "simulation_trace.json")
            meta = {
                "generated_at": "2026-07-31T10:00:00Z",
                "finished": True,
                "frame_count": 5000,
                "sim_meta": {"sim_days": 30, "agent_ids": [1, 2, 3]},
            }
            # Bigger than the full-parse fallback allows, so a hit here proves
            # the prefix scan did the work.
            _write_trace(path, meta, frames=200000)
            self.assertGreater(os.path.getsize(path), replay_runs.FULL_PARSE_MAX_BYTES)
            read = replay_runs.read_trace_meta(path)
            self.assertEqual(5000, read["frame_count"])
            self.assertEqual(30, read["sim_meta"]["sim_days"])

    def test_unreadable_or_broken_trace_yields_empty_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "simulation_trace.json")
            with open(broken, "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual({}, replay_runs.read_trace_meta(broken))
            self.assertEqual({}, replay_runs.read_trace_meta(os.path.join(tmp, "missing.json")))


class ListRunsTests(unittest.TestCase):
    def _seed(self, root):
        _write_trace(
            os.path.join(root, "output", "visualization", "simulation_trace.json"),
            {"generated_at": "2026-07-31T12:00:00Z", "finished": False, "frame_count": 12},
            frames=12,
        )
        _write_trace(
            os.path.join(root, "output", "visualization", "runs", "20260730-090000", "simulation_trace.json"),
            {"generated_at": "2026-07-30T09:00:00Z", "finished": True, "frame_count": 480,
             "sim_meta": {"sim_days": 20, "agent_ids": [1, 2]}},
            frames=3,
        )
        _write_trace(
            os.path.join(root, "output", "comparisons", "20260711_临时交通限行", "with_event",
                         "visualization", "simulation_trace.json"),
            {"generated_at": "2026-07-11T08:00:00Z", "finished": True, "frame_count": 264},
            frames=2,
        )

    def test_lists_live_archived_and_scenario_runs(self):
        with tempfile.TemporaryDirectory() as root:
            self._seed(root)
            runs = replay_runs.list_runs(root)
            by_kind = {run["kind"]: run for run in runs}
            self.assertEqual({"live", "archive", "scenario"}, set(by_kind))
            self.assertEqual("live", runs[0]["kind"])   # live run always first

            live = by_kind["live"]
            self.assertEqual("/output/visualization/simulation_trace.json", live["trace_url"])
            self.assertEqual("/output/visualization/latest_frame.json", live["latest_url"])
            self.assertEqual(12, live["frame_count"])

            archive = by_kind["archive"]
            self.assertEqual("output/visualization/runs/20260730-090000", archive["id"])
            self.assertIn("20260730-090000", archive["label"])
            self.assertEqual(480, archive["frame_count"])
            self.assertTrue(archive["finished"])
            self.assertEqual(20, archive["sim_days"])
            self.assertEqual(2, archive["agent_count"])
            # Archived runs reuse the avatars of the visualization dir above them.
            self.assertEqual("/output/visualization/", archive["avatar_base"])
            self.assertEqual("", archive["latest_url"])

            scenario = by_kind["scenario"]
            self.assertEqual("comparisons/20260711_临时交通限行/with_event", scenario["label"])
            self.assertEqual(264, scenario["frame_count"])

    def test_empty_output_tree_lists_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual([], replay_runs.list_runs(root))

    def test_scenario_runs_are_found_under_a_custom_live_dir(self):
        with tempfile.TemporaryDirectory() as root:
            self._seed(root)
            runs = replay_runs.list_runs(root, live_dir="output/comparisons/20260711_临时交通限行/with_event/visualization")
            self.assertEqual("live", runs[0]["kind"])
            self.assertEqual(264, runs[0]["frame_count"])
            # The default visualization dir is still listed, just not as live.
            ids = {run["id"] for run in runs}
            self.assertIn("output/visualization", ids)


class ReplayPageTests(unittest.TestCase):
    def test_replay_page_node_suite(self):
        """The page's run switching is only covered on the JS side."""
        result = subprocess.run(
            ["node", "--test", str(ROOT / "site" / "simviz" / "replay.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
