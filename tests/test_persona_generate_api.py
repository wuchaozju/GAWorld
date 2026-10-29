"""RED tests for the LLM persona authoring/enrichment API (``persona-generate``).

Specifies the contract from ``SPEC-persona-generate.md`` (audit: research
RESULT-2799):

* A new delegate module ``gaworld/apps/persona_generate_api.py`` exposing
  ``handle_post("/api/persona-generate", body)`` → ``(job, 202)`` and
  ``handle_get("/api/persona-generate/jobs/<id>")``, following the
  ``persona_api`` job pattern (``_new_job/_run_in_background/job_status``,
  ownership stamping).
* The LLM is called through the router only: ``call_llm(prompt,
  task="persona_author", provider=…, agent_id=None)`` — never bypassed, no
  silent fallback. Every model call here runs against a fake (repo
  convention, ``tests/test_persona_api.py``).
* Structural facts (id, name, gender, age, hukou, residence, job, …) are
  immutable: the model is never asked for them and an output that
  contradicts them is rejected before any write. Agent ids never change.
* Provenance (persona_source, provider, model, task, timestamp) is recorded
  per enriched resident. Invalid JSON fails visibly — no templated fallback.

Every non-guard test must fail with a clear "module missing" assertion until
the implement phase lands the feature.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from gaworld.apps import residents, world_paths

REPO_ROOT = world_paths.REPO_ROOT
REAL_CSV = os.path.join(REPO_ROOT, "data", "hangzhou_agents_state_init.csv")
REAL_MD = os.path.join(REPO_ROOT, "data", "hangzhou_profiles_with_names.md")
REAL_BIG5 = os.path.join(REPO_ROOT, "data", "agents_big5.csv")

#: What a well-behaved enrichment answer looks like: only narrative fields,
#: never a structural fact.
ENRICHED = {
    "personality": "精打细算，遇事冷静，不爱出头",
    "daily_life": "清晨去菜市场挑新鲜菜，随后开门看店到傍晚",
    "values": "踏实过日子，信用比什么都重要",
    "motivations": "让家里人过得更稳当",
    "concerns": "店铺租金年年涨",
    "social_context": "老街坊都熟，谁家有事都搭把手",
    "behavioral_tendencies": "倾向规避风险，先攒后花",
    "voice": "短句，先讲价钱再讲人情",
}


def _api():
    """Fetch the not-yet-existing delegate module; fails naming the feature."""
    try:
        from gaworld.apps import persona_generate_api
    except ImportError as exc:  # pragma: no cover - the RED state itself
        raise AssertionError(
            f"feature missing: gaworld.apps.persona_generate_api is not implemented "
            f"(persona-generate RED): {exc}"
        ) from exc
    return persona_generate_api


def make_fake_llm(*, fail_on_call=(), broken_json_on_call=(), mutates_structural_on_call=()):
    """A call_llm fake that records every call and can misbehave on demand.

    ``call`` indexes are 1-based, in call order. A misbehaving call either
    raises (failure) or answers with output the structural gate must reject.
    """
    calls: list[dict] = []

    def fake(prompt, task=None, agent_id=None, provider=None, **kwargs):
        calls.append({"prompt": prompt, "task": task, "agent_id": agent_id, "provider": provider, **kwargs})
        index = len(calls)
        if index in fail_on_call:
            raise ConnectionError(f"simulated LLM failure on call {index}")
        if index in broken_json_on_call:
            return "模型这次没有答成 JSON：他就是个老实人。"
        if index in mutates_structural_on_call:
            mutated = dict(ENRICHED)
            mutated["age"] = 99  # the model invents a structural fact
            mutated["hukou"] = "北京"
            return json.dumps(mutated, ensure_ascii=False)
        return json.dumps(ENRICHED, ensure_ascii=False)

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


class BaseGenerateCase(unittest.TestCase):
    """Tmp copies of the seed files + the mocked router, per test_persona_api."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._paths = (
            world_paths.STATE_CSV_PATH,
            world_paths.PROFILE_PATH,
            world_paths.BIG5_CSV_PATH,
        )
        world_paths.STATE_CSV_PATH = os.path.join(self.tmp, "state.csv")
        world_paths.PROFILE_PATH = os.path.join(self.tmp, "profiles.md")
        world_paths.BIG5_CSV_PATH = os.path.join(self.tmp, "big5.csv")
        shutil.copy(REAL_CSV, world_paths.STATE_CSV_PATH)
        shutil.copy(REAL_MD, world_paths.PROFILE_PATH)
        shutil.copy(REAL_BIG5, world_paths.BIG5_CSV_PATH)
        self.fake_llm = make_fake_llm()
        self._patches = [
            mock.patch("gaworld.llm.providers.call_llm", self.fake_llm),
        ]
        try:
            import gaworld.apps.persona_generate_api as _mod  # noqa: F401

            self._patches.append(mock.patch("gaworld.apps.persona_generate_api.call_llm", self.fake_llm))
        except ImportError:
            pass
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        (
            world_paths.STATE_CSV_PATH,
            world_paths.PROFILE_PATH,
            world_paths.BIG5_CSV_PATH,
        ) = self._paths
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ----------------------------------------------------------

    def run_job(self, payload):
        """POST a generate/enrich job and poll it to a finished record."""
        api = _api()
        body, status = api.handle_post("/api/persona-generate", payload)
        self.assertEqual(202, status, f"expected a job, got {status}: {body}")
        self.assertIn("job_id", body)
        deadline = time.time() + 20
        job_id = body["job_id"]
        while time.time() < deadline:
            record, st = api.handle_get(f"/api/persona-generate/jobs/{job_id}")
            self.assertEqual(200, st)
            if record.get("status") in ("completed", "failed"):
                return record
            time.sleep(0.05)
        self.fail("job did not finish within 20s")


class TestEnrichmentPersistence(BaseGenerateCase):
    def test_valid_enrichment_persists_through_residents(self):
        record = self.run_job({"scope": "selected", "ids": [1]})
        self.assertEqual("completed", record["status"], record.get("error"))
        text = residents.agent_profile(1)["text"]
        self.assertIn(ENRICHED["personality"], text)
        self.assertIn(ENRICHED["daily_life"], text)

    def test_gate_rejects_mutated_structural_facts(self):
        self.fake_llm = make_fake_llm(mutates_structural_on_call={1})
        for patch in self._patches:
            patch.stop()
        self._patches = [mock.patch("gaworld.llm.providers.call_llm", self.fake_llm)]
        try:
            import gaworld.apps.persona_generate_api as _mod  # noqa: F401 - import availability is the point

            self._patches.append(mock.patch("gaworld.apps.persona_generate_api.call_llm", self.fake_llm))
        except ImportError:
            pass
        for patch in self._patches:
            patch.start()

        before = residents.agent_profile(1)["text"]
        record = self.run_job({"scope": "selected", "ids": [1]})
        # The output contradicted the CSV's age/hukou, so nothing was written
        # and the failure is visible — not papered over with template prose.
        self.assertEqual(before, residents.agent_profile(1)["text"])
        result = record.get("result") or {}
        failures = result.get("failed") or result.get("failures") or []
        self.assertTrue(
            failures or record.get("status") == "failed",
            f"a structural mutation must fail visibly: {record}",
        )

    def test_agent_id_never_changes(self):
        rows_before = residents.read_state_rows()[1]
        ids_before = [row["id"] for row in rows_before]
        record = self.run_job({"scope": "selected", "ids": [1]})
        self.assertEqual("completed", record["status"], record.get("error"))
        rows_after = residents.read_state_rows()[1]
        self.assertEqual(ids_before, [row["id"] for row in rows_after])
        state = residents.agent_state(1)
        self.assertEqual("1", str(state["id"]))

    def test_invalid_json_fails_visibly_with_no_fallback(self):
        self.fake_llm = make_fake_llm(broken_json_on_call={1})
        for patch in self._patches:
            patch.stop()
        self._patches = [mock.patch("gaworld.llm.providers.call_llm", self.fake_llm)]
        try:
            import gaworld.apps.persona_generate_api as _mod  # noqa: F401 - import availability is the point

            self._patches.append(mock.patch("gaworld.apps.persona_generate_api.call_llm", self.fake_llm))
        except ImportError:
            pass
        for patch in self._patches:
            patch.start()

        before = residents.agent_profile(1)["text"]
        record = self.run_job({"scope": "selected", "ids": [1]})
        self.assertEqual(before, residents.agent_profile(1)["text"])
        result = record.get("result") or {}
        failures = result.get("failed") or result.get("failures") or []
        self.assertTrue(
            failures or record.get("status") == "failed",
            f"unparseable output must fail visibly: {record}",
        )

    def test_provenance_recorded(self):
        record = self.run_job({"scope": "selected", "ids": [1], "provider": "ui-provider"})
        self.assertEqual("completed", record["status"], record.get("error"))
        result = record.get("result") or {}
        entries = result.get("provenance") or result.get("enriched") or []
        if not entries:
            # provenance may live in a sidecar instead of the job record
            sidecar = os.path.join(self.tmp, "personas", "derived", "1.json")
            self.assertTrue(os.path.exists(sidecar), "provenance must be recorded somewhere")
            entries = [json.load(open(sidecar, encoding="utf-8"))]  # noqa: SIM115 - read-only probe
        entry = entries[0]
        self.assertEqual("llm_enriched", entry.get("persona_source"))
        self.assertEqual("persona_author", entry.get("task"))
        self.assertEqual("ui-provider", entry.get("provider"))
        self.assertTrue(entry.get("timestamp") or entry.get("created_at"))

    def test_job_polling_contract(self):
        api = _api()
        body, status = api.handle_post("/api/persona-generate", {"scope": "selected", "ids": [1]})
        self.assertEqual(202, status)
        self.assertEqual("running", body.get("status"))
        _payload, st = api.handle_get("/api/persona-generate/jobs/does-not-exist")
        self.assertEqual(404, st)


if __name__ == "__main__":
    unittest.main()
