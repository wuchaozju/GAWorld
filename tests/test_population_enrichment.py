"""RED tests — population enrichment scopes and failure isolation.

From ``SPEC-persona-generate.md``:

* ``scope="fast"`` (default) makes ZERO ``call_llm`` calls;
* ``scope="selected"`` enriches exactly the given ids and nothing else;
* ``scope="focal_n"`` enriches exactly ``n`` residents;
* ``scope="all"`` enriches every resident;
* one failed agent never corrupts the successes, and a retry reruns only
  what failed;
* the state CSV's structural facts are untouched, and the enriched text
  lands in the profile Markdown where ``parse_profile`` can read it.
"""

from __future__ import annotations

import unittest

from gaworld.apps import residents, world_paths

from tests.test_persona_generate_api import BaseGenerateCase, ENRICHED, _api, make_fake_llm


def csv_snapshot():
    fieldnames, rows = residents.read_state_rows()
    return fieldnames, [dict(row) for row in rows]


class TestScopes(BaseGenerateCase):
    def test_selected_enriches_only_the_given_ids(self):
        record = self.run_job({"scope": "selected", "ids": [3, 7]})
        self.assertEqual("completed", record["status"], record.get("error"))
        self.assertEqual(2, len(self.fake_llm.calls))
        self.assertIn(ENRICHED["personality"], residents.agent_profile(3)["text"])
        self.assertIn(ENRICHED["personality"], residents.agent_profile(7)["text"])
        _fn, rows = csv_snapshot()
        untouched = next(row for row in rows if row["id"] == "5")
        self.assertNotIn("99", str(untouched))

    def test_focal_n_enriches_exactly_n(self):
        record = self.run_job({"scope": "focal_n", "n": 3})
        self.assertEqual("completed", record["status"], record.get("error"))
        self.assertEqual(3, len(self.fake_llm.calls))

    def test_all_enriches_every_resident(self):
        _fn, rows_before = csv_snapshot()
        record = self.run_job({"scope": "all"})
        self.assertEqual("completed", record["status"], record.get("error"))
        self.assertEqual(len(rows_before), len(self.fake_llm.calls))
        for row in rows_before:
            text = residents.agent_profile(int(row["id"]))["text"]
            self.assertIn(ENRICHED["personality"], text)

    def test_fast_makes_zero_llm_calls(self):
        record = self.run_job({"scope": "fast", "seed": {"name": "测试者", "age": 42, "gender": "男"}})
        self.assertEqual("completed", record["status"], record.get("error"))
        self.assertEqual([], self.fake_llm.calls)


class TestFailureIsolation(BaseGenerateCase):
    def test_failed_agent_does_not_corrupt_successes(self):
        _swap(self, make_fake_llm(fail_on_call={2}))
        _fn, rows = csv_snapshot()
        other_id = next(row["id"] for row in rows if row["id"] not in ("1", "2"))
        record = self.run_job({"scope": "selected", "ids": [1, int(other_id)]})
        # agent 1's call succeeded, the second call failed — visibly.
        result = record.get("result") or {}
        failures = result.get("failed") or result.get("failures") or []
        self.assertTrue(
            failures or record.get("status") == "failed",
            f"the failed agent must be reported: {record}",
        )
        self.assertIn(ENRICHED["personality"], residents.agent_profile(1)["text"])

    def test_retry_reruns_only_the_failed(self):
        _swap(self, make_fake_llm(fail_on_call={2}))
        _fn, rows = csv_snapshot()
        other_id = int(next(row["id"] for row in rows if row["id"] not in ("1", "2")))
        self.run_job({"scope": "selected", "ids": [1, other_id]})
        calls_after_first = len(self.fake_llm.calls)
        # Retry: only what failed should be re-run.
        _swap(self, make_fake_llm())
        record = self.run_job({"scope": "selected", "ids": [other_id]})
        self.assertEqual("completed", record["status"], record.get("error"))
        self.assertEqual(1, len(self.fake_llm.calls))
        self.assertIn(ENRICHED["personality"], residents.agent_profile(other_id)["text"])


class TestStructuralFactsUntouched(BaseGenerateCase):
    def test_csv_structural_facts_are_unchanged(self):
        fieldnames_before, rows_before = csv_snapshot()
        record = self.run_job({"scope": "all"})
        self.assertEqual("completed", record["status"], record.get("error"))
        fieldnames_after, rows_after = csv_snapshot()
        self.assertEqual(fieldnames_before, fieldnames_after)
        self.assertEqual(rows_before, rows_after)

    def test_enriched_text_lands_in_the_profile_md(self):
        record = self.run_job({"scope": "selected", "ids": [1]})
        self.assertEqual("completed", record["status"], record.get("error"))
        with open(world_paths.PROFILE_PATH, encoding="utf-8") as handle:
            full = handle.read()
        self.assertIn(ENRICHED["personality"], full)
        self.assertIn(ENRICHED["daily_life"], full)


def _swap(case, fake):
    """Replace the setUp fake with a behaviour-specific one."""
    for patch in case._patches:
        patch.stop()
    case.fake_llm = fake
    case._patches = [unittest.mock.patch("gaworld.llm.providers.call_llm", fake)]
    try:
        import gaworld.apps.persona_generate_api as _mod  # noqa: F401

        case._patches.append(unittest.mock.patch("gaworld.apps.persona_generate_api.call_llm", fake))
    except ImportError:
        pass
    for patch in case._patches:
        patch.start()


if __name__ == "__main__":
    unittest.main()
