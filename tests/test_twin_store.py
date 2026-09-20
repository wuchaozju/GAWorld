import os
import tempfile
import unittest

from gaworld.twin import store


def _report(report_id, ts, action_tag="commute"):
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": 30.27, "lng": 120.15, "acc_m": 12, "source": "gps"},
        "grid": {"x": 0.0, "y": 0.0},
        "node_id": "home",
        "out_of_map": False,
        "action_tag": action_tag,
        "note": "",
    }


class TestTwinStore(unittest.TestCase):
    def test_append_then_load_returns_the_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["duplicates"], 0)
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["report_id"], "a")

    def test_duplicate_report_id_appends_only_once(self):
        # The phone resubmits its offline queue after a flaky upload; the same
        # report_id must not produce a second line.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            result = store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(result["accepted"], 0)
            self.assertEqual(result["duplicates"], 1)
            self.assertEqual(len(store.load_reports(7, root=tmpdir)), 1)

    def test_batch_dedupes_within_itself(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            batch = [_report("a", 1000), _report("a", 1000), _report("b", 1001)]
            result = store.append_reports(7, batch, root=tmpdir)
            self.assertEqual(result["accepted"], 2)
            self.assertEqual(result["duplicates"], 1)

    def test_snapshot_holds_the_latest_report_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Deliberately out of order: an offline flush can arrive late.
            store.append_reports(7, [_report("b", 2000, "work")], root=tmpdir)
            store.append_reports(7, [_report("a", 1000, "sleep")], root=tmpdir)
            snapshot = store.read_snapshot(7, root=tmpdir)
            self.assertEqual(snapshot["action_tag"], "work")
            self.assertEqual(snapshot["ts"], 2000)

    def test_agents_are_isolated_from_each_other(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(len(store.load_reports(8, root=tmpdir)), 0)
            self.assertIsNone(store.read_snapshot(8, root=tmpdir))

    def test_load_reports_can_filter_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(
                7, [_report("a", 1000), _report("b", 2000)], root=tmpdir
            )
            recent = store.load_reports(7, root=tmpdir, since_ts=1500)
            self.assertEqual([r["report_id"] for r in recent], ["b"])

    def test_is_fresh_uses_the_ttl(self):
        snapshot = _report("a", 1000)
        self.assertTrue(store.is_fresh(snapshot, now_ts=1000 + 29 * 60, ttl_minutes=30))
        self.assertFalse(store.is_fresh(snapshot, now_ts=1000 + 31 * 60, ttl_minutes=30))
        self.assertFalse(store.is_fresh(None, now_ts=1000, ttl_minutes=30))

    def test_delete_amendment_hides_the_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            self.assertEqual(store.load_reports(7, root=tmpdir), [])

    def test_update_amendment_patches_whitelisted_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000, "work")], root=tmpdir)
            store.append_amendment(
                7, "amend-1", "a", "update",
                patch={"action_tag": "meal", "note": "改了"}, root=tmpdir,
            )
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(loaded[0]["action_tag"], "meal")
            self.assertEqual(loaded[0]["note"], "改了")

    def test_update_amendment_cannot_rewrite_location(self):
        # Location is measured, not asserted. A wrong fix must be deleted,
        # not edited, or the calibration corpus stops being a record of where
        # anyone actually was.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(
                7, "amend-1", "a", "update",
                patch={"node_id": "somewhere-else", "loc": {"lat": 1, "lng": 2}},
                root=tmpdir,
            )
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(loaded[0]["node_id"], "home")
            self.assertEqual(loaded[0]["loc"]["lat"], 30.27)

    def test_amendments_are_not_returned_as_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "update",
                                   patch={"note": "x"}, root=tmpdir)
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["report_id"], "a")

    def test_deleting_the_newest_report_promotes_the_previous_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(
                7, [_report("a", 1000, "sleep"), _report("b", 2000, "work")],
                root=tmpdir,
            )
            store.append_amendment(7, "amend-1", "b", "delete", root=tmpdir)
            snapshot = store.read_snapshot(7, root=tmpdir)
            self.assertEqual(snapshot["report_id"], "a")

    def test_deleting_every_report_clears_the_snapshot(self):
        # Otherwise the phone keeps showing a position the user just erased.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            self.assertIsNone(store.read_snapshot(7, root=tmpdir))

    def test_amendment_is_idempotent_on_its_own_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            raw = store.load_raw(7, root=tmpdir)
            self.assertEqual(len([r for r in raw if r.get("kind") == "amend"]), 1)

    def test_last_amendment_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "m1", "a", "update",
                                   patch={"note": "first"}, root=tmpdir)
            store.append_amendment(7, "m2", "a", "update",
                                   patch={"note": "second"}, root=tmpdir)
            self.assertEqual(store.load_reports(7, root=tmpdir)[0]["note"], "second")

    def test_a_deleted_report_id_is_still_deduped(self):
        # Dedup must run against the raw log, not the folded view. A deleted
        # report drops out of load_reports(), so deduping against that would
        # let the offline queue re-append an id the server already saw.
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            store.append_amendment(7, "amend-1", "a", "delete", root=tmpdir)
            result = store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            self.assertEqual(result["accepted"], 0)
            self.assertEqual(result["duplicates"], 1)

    def test_corrupt_line_does_not_break_loading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store.append_reports(7, [_report("a", 1000)], root=tmpdir)
            path = os.path.join(store.agent_dir(7, root=tmpdir), "reports.jsonl")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write("{not json\n")
            loaded = store.load_reports(7, root=tmpdir)
            self.assertEqual(len(loaded), 1)


if __name__ == "__main__":
    unittest.main()
