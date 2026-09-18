"""Tests for the 真人蒸馏 dashboard delegate.

The distillation job itself is covered in ``test_persona_distill``; what
matters here is the part that writes into a world: deploy has to land a
resident in the state CSV, the framework in the profile Markdown, and the
OCEAN seeds in the Big Five CSV — or say which of those it skipped.

All writes target temp copies of the seed files, following the
``test_dashboard_studio`` convention.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

import gaworld.apps.dashboard_server as ds
from gaworld.apps import persona_api
from gaworld.persona import store as store_mod
from gaworld.persona.distill import PersonaProfile

REPO_ROOT = ds.REPO_ROOT
REAL_CSV = os.path.join(REPO_ROOT, "data", "hangzhou_agents_state_init.csv")
REAL_MD = os.path.join(REPO_ROOT, "data", "hangzhou_profiles_with_names.md")
REAL_BIG5 = os.path.join(REPO_ROOT, "data", "agents_big5.csv")

PERSONA = {
    "name": "李某",
    "slug": "li-mou",
    "subject": "李某",
    "mode": "name",
    "summary": "一位做纺织外贸的经营者",
    "gender": "男",
    "age": 47,
    "hukou": "绍兴",
    "residence": "柯桥",
    "job": "经营一家面料出口公司",
    "personality": "谨慎，话少",
    "daily_life": "早七点到厂",
    "values": "务实",
    "education_income": "本科，收入中上",
    "social_network": "同业商会",
    "mental_models": [{"name": "订单即信号", "gist": "从订单结构反推行业周期", "evidence": ["2023年提前减产"]}],
    "heuristics": [{"rule": "如果账期超过90天，则不接单"}],
    "voice": {"sentences": "短句", "phrases": ["先看单子"]},
    "boundaries": ["只覆盖公开报道"],
    "state": {"emotion": 0.6, "stress": 0.7, "risk_preference": 0.2},
    "big5": {"o": 0.3, "c": 1.2, "e": -0.4, "a": 0.1, "n": -0.8},
    "sources": [{"title": "某篇报道", "url": "https://example.com/a", "kind": "page"}],
    "confidence": "medium",
    "built_at": "2026-09-18T00:00:00+00:00",
}


class PersonaApiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._paths = (ds.STATE_CSV_PATH, ds.PROFILE_PATH, ds.BIG5_CSV_PATH)
        ds.STATE_CSV_PATH = os.path.join(self.tmp, "state.csv")
        ds.PROFILE_PATH = os.path.join(self.tmp, "profiles.md")
        ds.BIG5_CSV_PATH = os.path.join(self.tmp, "big5.csv")
        shutil.copy(REAL_CSV, ds.STATE_CSV_PATH)
        shutil.copy(REAL_MD, ds.PROFILE_PATH)
        shutil.copy(REAL_BIG5, ds.BIG5_CSV_PATH)
        self._persona_dir = os.environ.get("GAWORLD_PERSONA_DIR")
        os.environ["GAWORLD_PERSONA_DIR"] = os.path.join(self.tmp, "personas")
        store_mod.save(PersonaProfile.from_dict(PERSONA))

    def tearDown(self):
        ds.STATE_CSV_PATH, ds.PROFILE_PATH, ds.BIG5_CSV_PATH = self._paths
        if self._persona_dir is None:
            os.environ.pop("GAWORLD_PERSONA_DIR", None)
        else:
            os.environ["GAWORLD_PERSONA_DIR"] = self._persona_dir
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestReads(PersonaApiCase):
    def test_list_returns_the_archive(self):
        payload, status = persona_api.handle_get("/api/persona/list")
        self.assertEqual(200, status)
        self.assertEqual(["li-mou"], [row["slug"] for row in payload["personas"]])

    def test_detail_carries_rendered_artefacts(self):
        payload, status = persona_api.handle_get("/api/persona/detail/li-mou")
        self.assertEqual(200, status)
        self.assertEqual("李某", payload["persona"]["name"])
        self.assertIn("订单即信号", payload["profile_block"])
        self.assertIn("## 心智模型", payload["skill_markdown"])

    def test_unknown_persona_is_404(self):
        _payload, status = persona_api.handle_get("/api/persona/detail/nobody")
        self.assertEqual(404, status)

    def test_unknown_route_is_404(self):
        _payload, status = persona_api.handle_get("/api/persona/whatever")
        self.assertEqual(404, status)


class TestDistillJob(PersonaApiCase):
    def test_a_blank_subject_is_rejected(self):
        payload, status = persona_api.handle_post("/api/persona/distill", {"subject": "   "})
        self.assertEqual(400, status)
        self.assertIn("姓名", payload["error"])

    def test_unknown_job_is_404(self):
        _payload, status = persona_api.handle_get("/api/persona/jobs/does-not-exist")
        self.assertEqual(404, status)


class TestDeploy(PersonaApiCase):
    def test_deploy_creates_a_resident_with_the_distilled_seeds(self):
        result, status = persona_api.handle_post("/api/persona/deploy", {"slug": "li-mou"})
        self.assertEqual(200, status)
        agent_id = result["agent_id"]

        state = ds._agent_state(agent_id)
        self.assertEqual("李某", state["name"])
        self.assertEqual(47, state["age"])
        self.assertAlmostEqual(0.6, state["state"]["emotion"], places=2)
        self.assertAlmostEqual(0.2, state["state"]["risk_preference"], places=2)

    def test_deploy_appends_the_framework_to_the_profile(self):
        result, _status = persona_api.handle_post("/api/persona/deploy", {"slug": "li-mou"})
        text = ds._agent_profile(result["agent_id"])["text"]
        self.assertIn("经营一家面料出口公司", text)   # the standard block
        self.assertIn("订单即信号", text)             # the distilled framework
        self.assertIn("如果账期超过90天", text)
        self.assertIn("只覆盖公开报道", text)          # the honest boundary
        self.assertTrue(result["framework_written"])
        # The framework goes inside the block, ahead of the rule that separates
        # this resident from the next one.
        self.assertLess(text.index("订单即信号"), text.rindex("---"))

    def test_deploy_seeds_the_big_five_row(self):
        result, _status = persona_api.handle_post("/api/persona/deploy", {"slug": "li-mou"})
        self.assertTrue(result["big5_written"])
        payload = ds._agent_big5(result["agent_id"])
        self.assertAlmostEqual(1.2, payload["values"]["c"], places=2)
        self.assertAlmostEqual(-0.8, payload["values"]["n"], places=2)

    def test_deploy_without_a_big_five_file_still_creates_the_resident(self):
        os.remove(ds.BIG5_CSV_PATH)
        result, status = persona_api.handle_post("/api/persona/deploy", {"slug": "li-mou"})
        self.assertEqual(200, status)
        self.assertFalse(result["big5_written"])
        self.assertIsNotNone(ds._agent_state(result["agent_id"]))

    def test_operator_overrides_win_over_the_distilled_values(self):
        result, _status = persona_api.handle_post(
            "/api/persona/deploy",
            {"slug": "li-mou", "identity": {"name": "李某（化名）", "residence": "杭州"},
             "state": {"stress": 0.1}},
        )
        state = ds._agent_state(result["agent_id"])
        self.assertEqual("李某（化名）", state["name"])
        self.assertEqual("杭州", state["residence"])
        self.assertAlmostEqual(0.1, state["state"]["stress"], places=2)

    def test_deploy_records_the_agent_id_on_the_persona(self):
        result, _status = persona_api.handle_post("/api/persona/deploy", {"slug": "li-mou"})
        again = store_mod.load("li-mou")
        self.assertEqual(result["agent_id"], again.agent_id)
        rows = json.loads(json.dumps(store_mod.list_personas()))
        self.assertEqual(result["agent_id"], rows[0]["agent_id"])

    def test_deploying_an_unknown_persona_is_a_400(self):
        payload, status = persona_api.handle_post("/api/persona/deploy", {"slug": "nobody"})
        self.assertEqual(400, status)
        self.assertIn("找不到", payload["error"])

    def test_delete_removes_the_archive(self):
        payload, status = persona_api.handle_post("/api/persona/delete", {"slug": "li-mou"})
        self.assertEqual(200, status)
        self.assertTrue(payload["deleted"])
        self.assertIsNone(store_mod.load("li-mou"))


if __name__ == "__main__":
    unittest.main()
