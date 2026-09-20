import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import twin_calibrate
from gaworld.twin import store


def _report(report_id, ts, node_id, tag, hour):
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": 30.27, "lng": 120.15, "acc_m": 10, "source": "gps"},
        "grid": {"x": 1.0, "y": 0.0},
        "node_id": node_id,
        "out_of_map": False,
        "action_tag": tag,
        "note": "",
        "hour": hour,
    }


class TestTwinCalibrate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "twin")
        # Three mornings at the office, one evening at the gym.
        store.append_reports(
            7,
            [
                _report("a", 1000, "office", "work", 9),
                _report("b", 2000, "office", "work", 9),
                _report("c", 3000, "office", "work", 9),
                _report("d", 4000, "gym", "exercise", 19),
            ],
            root=self.root,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_aggregate_counts_locations(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        self.assertEqual(summary["frequent_locations"]["office"], 3)
        self.assertEqual(summary["frequent_locations"]["gym"], 1)

    def test_aggregate_counts_activity_tags(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        self.assertEqual(summary["action_tags"]["work"], 3)
        self.assertEqual(summary["action_tags"]["exercise"], 1)

    def test_aggregate_reports_total_and_span(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        self.assertEqual(summary["total_reports"], 4)
        self.assertEqual(summary["first_ts"], 1000)
        self.assertEqual(summary["last_ts"], 4000)

    def test_aggregate_on_an_agent_with_no_reports(self):
        summary = twin_calibrate.aggregate(99, root=self.root)
        self.assertEqual(summary["total_reports"], 0)
        self.assertEqual(summary["frequent_locations"], {})

    def test_build_patch_only_includes_locations_above_the_threshold(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        patch = twin_calibrate.build_patch(summary, min_occurrences=3)
        self.assertIn("office", patch["frequent_locations"])
        self.assertNotIn("gym", patch["frequent_locations"])

    def test_render_diff_is_human_readable(self):
        summary = twin_calibrate.aggregate(7, root=self.root)
        diff = twin_calibrate.render_diff(7, twin_calibrate.build_patch(summary, 3))
        self.assertIn("office", diff)
        self.assertIn("7", diff)

    def test_apply_refuses_without_approval(self):
        out = os.path.join(self._tmp.name, "patch.json")
        written = twin_calibrate.apply_patch(7, {"frequent_locations": {"office": 3}},
                                             out_path=out, approved=False)
        self.assertFalse(written)
        self.assertFalse(os.path.exists(out))

    def test_apply_writes_only_when_approved(self):
        out = os.path.join(self._tmp.name, "patch.json")
        written = twin_calibrate.apply_patch(7, {"frequent_locations": {"office": 3}},
                                             out_path=out, approved=True)
        self.assertTrue(written)
        with open(out, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["agent_id"], 7)


if __name__ == "__main__":
    unittest.main()
