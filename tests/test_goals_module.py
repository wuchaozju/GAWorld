"""Tests for gaworld.goals — persistence, normalization, fallback."""

import json
import os
import tempfile
import unittest

from gaworld import goals as goals_mod


def _agent(job="产品经理", econ=0.6):
    return {
        "id": 3,
        "name": "测试者",
        "age": 32,
        "job": job,
        "personality": "稳重务实",
        "daily_life": "作息规律",
        "values": "重视家庭",
        "state": {"econ_security": econ},
    }


def _sample_goals():
    return {
        "life_goals": [
            {"id": "lg1", "title": "在杭州安家", "domain": "family",
             "description": "", "status": "active"},
        ],
        "long_term_goals": [
            {"id": "ltg1", "parent": "lg1", "title": "两年内攒够首付",
             "horizon_days": 700, "progress": 0.15, "status": "active",
             "created_day": 1, "updated_day": 1},
        ],
        "short_term_goals": [
            {"id": "stg1", "parent": "ltg1", "title": "这两周完成基金调仓",
             "target_day": 14, "progress": 0.4, "status": "active",
             "created_day": 1, "updated_day": 1, "recent_note": ""},
        ],
        "last_review_day": 0,
        "needs_review": False,
        "review_log": [],
    }


class TestPersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals_mod.save_agent_goals(3, _sample_goals(), tmp)
            loaded = goals_mod.load_agent_goals(3, tmp)
        self.assertEqual(loaded["short_term_goals"][0]["title"], "这两周完成基金调仓")

    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(goals_mod.load_agent_goals(99, tmp), {})

    def test_load_corrupt_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = goals_mod.agent_goals_path(3, tmp)
            os.makedirs(tmp, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json {{{")
            self.assertEqual(goals_mod.load_agent_goals(3, tmp), {})


class TestNormalize(unittest.TestCase):
    def test_truncates_active_to_limits(self):
        payload = _sample_goals()
        payload["short_term_goals"] = [
            {"id": f"stg{i}", "parent": "ltg1", "title": f"目标{i}",
             "progress": 0.0, "status": "active"}
            for i in range(1, 8)
        ]
        out = goals_mod.normalize_goals(payload, day=1)
        active = [g for g in out["short_term_goals"] if g["status"] == "active"]
        self.assertLessEqual(len(active), 4)

    def test_reparents_orphans(self):
        payload = _sample_goals()
        payload["short_term_goals"][0]["parent"] = "ltg_missing"
        out = goals_mod.normalize_goals(payload, day=1)
        self.assertEqual(out["short_term_goals"][0]["parent"], "ltg1")

    def test_clamps_progress_and_status(self):
        payload = _sample_goals()
        payload["long_term_goals"][0]["progress"] = 4.2
        payload["long_term_goals"][0]["status"] = "bogus"
        out = goals_mod.normalize_goals(payload, day=1)
        self.assertEqual(out["long_term_goals"][0]["progress"], 1.0)
        self.assertEqual(out["long_term_goals"][0]["status"], "active")

    def test_drops_untitled_and_empty_payload(self):
        self.assertEqual(goals_mod.normalize_goals({"life_goals": [{"title": ""}]}, day=1), {})
        self.assertEqual(goals_mod.normalize_goals("nope", day=1), {})


class TestFallbackGoals(unittest.TestCase):
    def test_worker_gets_three_tiers(self):
        goals = goals_mod._fallback_goals(_agent(), day=1)
        for tier in ("life_goals", "long_term_goals", "short_term_goals"):
            self.assertTrue(goals[tier], tier)
        self.assertEqual(goals["short_term_goals"][0]["parent"],
                         goals["long_term_goals"][0]["id"])

    def test_retiree_has_no_work_goal(self):
        goals = goals_mod._fallback_goals(_agent(job="已退休"), day=1)
        blob = json.dumps(goals, ensure_ascii=False)
        for word in ("工作", "上班", "加班"):
            self.assertNotIn(word, blob)

    def test_low_econ_prioritizes_income(self):
        goals = goals_mod._fallback_goals(_agent(econ=0.2), day=1)
        self.assertIn("收入", json.dumps(goals, ensure_ascii=False))


class TestBootstrap(unittest.TestCase):
    def _llm_ok(self, prompt):
        self.last_prompt = prompt
        return json.dumps({
            "life_goals": [{"title": "成为行业专家", "domain": "career", "description": "深耕产品"}],
            "long_term_goals": [{"title": "一年内主导一个大项目", "parent_index": 1, "horizon_days": 365}],
            "short_term_goals": [
                {"title": "这两周完成竞品分析", "parent_index": 1, "target_day_offset": 14},
                {"title": "本周约谈三位用户", "parent_index": 1, "target_day_offset": 7},
            ],
        }, ensure_ascii=False)

    def test_derive_goals_maps_parent_index_and_offsets(self):
        goals = goals_mod.derive_goals(_agent(), llm=self._llm_ok, day=10)
        self.assertEqual(goals["long_term_goals"][0]["parent"], "lg1")
        self.assertEqual(goals["short_term_goals"][0]["parent"], "ltg1")
        self.assertEqual(goals["short_term_goals"][0]["target_day"], 24)
        self.assertIn("产品经理", self.last_prompt)

    def test_derive_goals_llm_failure_falls_back(self):
        def boom(prompt):
            raise RuntimeError("llm down")
        goals = goals_mod.derive_goals(_agent(), llm=boom, day=1)
        self.assertTrue(goals["short_term_goals"])  # heuristic fallback

    def test_derive_goals_garbage_falls_back(self):
        goals = goals_mod.derive_goals(_agent(), llm=lambda p: "不是JSON", day=1)
        self.assertTrue(goals["life_goals"])

    def test_bootstrap_skips_existing_file_when_stateful(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            goals_mod.save_agent_goals(3, _sample_goals(), tmp)
            agent = _agent()
            goals_mod.bootstrap_goals(
                [agent], llm=lambda p: calls.append(p) or "{}",
                memory_dir=tmp, stateful=True,
            )
        self.assertEqual(calls, [])
        self.assertEqual(agent["goals"]["short_term_goals"][0]["id"], "stg1")

    def test_bootstrap_derives_and_saves_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent()
            goals_mod.bootstrap_goals(
                [agent], llm=self._llm_ok, memory_dir=tmp, stateful=True,
            )
            self.assertTrue(os.path.exists(goals_mod.agent_goals_path(3, tmp)))
        self.assertEqual(agent["goals"]["life_goals"][0]["title"], "成为行业专家")


class TestFormatAndRelevance(unittest.TestCase):
    def test_format_goals_context_lists_three_tiers_with_ids(self):
        text = goals_mod.format_goals_context(_sample_goals())
        self.assertIn("人生方向", text)
        self.assertIn("[ltg1]", text)
        self.assertIn("[stg1]", text)
        self.assertIn("40%", text)

    def test_format_goals_context_empty(self):
        self.assertEqual(goals_mod.format_goals_context({}), "无")
        self.assertEqual(goals_mod.format_goals_context(None), "无")

    def test_format_skips_inactive(self):
        goals = _sample_goals()
        goals["short_term_goals"][0]["status"] = "completed"
        self.assertNotIn("[stg1]", goals_mod.format_goals_context(goals))

    def test_relevance_floor_when_unrelated_or_empty(self):
        self.assertEqual(goals_mod.match_goal_relevance({}, "跑步"), 0.2)
        self.assertEqual(
            goals_mod.match_goal_relevance(_sample_goals(), "下午在西湖边散步"), 0.2)

    def test_relevance_high_on_short_term_match(self):
        score = goals_mod.match_goal_relevance(
            _sample_goals(), "上午研究基金调仓方案", "认真比较了收益")
        self.assertGreater(score, 0.5)
        self.assertLessEqual(score, 0.9)

    def test_relevance_ignores_inactive_goals(self):
        goals = _sample_goals()
        goals["short_term_goals"][0]["status"] = "abandoned"
        goals["long_term_goals"][0]["status"] = "abandoned"
        score = goals_mod.match_goal_relevance(goals, "基金调仓 攒首付")
        self.assertEqual(score, 0.2)


class TestApplyGoalProgress(unittest.TestCase):
    def test_applies_progress_and_note(self):
        goals, notes = goals_mod.apply_goal_progress(
            _sample_goals(),
            [{"id": "stg1", "progress": 0.6, "note": "完成了方案比较"}],
            day=5,
        )
        g = goals["short_term_goals"][0]
        self.assertEqual(g["progress"], 0.6)
        self.assertEqual(g["recent_note"], "完成了方案比较")
        self.assertEqual(g["updated_day"], 5)
        self.assertTrue(notes)

    def test_caps_daily_delta(self):
        goals, _ = goals_mod.apply_goal_progress(
            _sample_goals(), [{"id": "stg1", "progress": 1.0}], day=5,
            config={"max_daily_progress_delta": 0.1},
        )
        self.assertAlmostEqual(goals["short_term_goals"][0]["progress"], 0.5)

    def test_daily_pass_never_regresses(self):
        goals, _ = goals_mod.apply_goal_progress(
            _sample_goals(), [{"id": "stg1", "progress": 0.1}], day=5)
        self.assertEqual(goals["short_term_goals"][0]["progress"], 0.4)

    def test_full_progress_completes_short_term(self):
        base = _sample_goals()
        base["short_term_goals"][0]["progress"] = 0.9
        goals, notes = goals_mod.apply_goal_progress(
            base, [{"id": "stg1", "progress": 1.0}], day=5)
        self.assertEqual(goals["short_term_goals"][0]["status"], "completed")
        self.assertIn("完成", "".join(notes))

    def test_unknown_id_and_bad_items_skipped(self):
        goals, notes = goals_mod.apply_goal_progress(
            _sample_goals(),
            [{"id": "nope", "progress": 0.9}, "garbage", {"progress": 0.5}],
            day=5,
        )
        self.assertEqual(goals["short_term_goals"][0]["progress"], 0.4)
        self.assertEqual(notes, [])


def _review_agent():
    agent = _agent()
    agent["goals"] = _sample_goals()
    agent["episodes"] = [
        {"day": 3, "time": "10:00", "final_activity": "研究基金", "action": "比较收益",
         "reflection": "有进展", "salience": 0.8},
    ]
    return agent


class TestGoalReview(unittest.TestCase):
    def _llm(self, payload):
        return lambda prompt: json.dumps(payload, ensure_ascii=False)

    def test_weekly_review_applies_actions_and_logs(self):
        agent = _review_agent()
        goals, summary = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly",
            llm=self._llm({
                "short_term_updates": [{"id": "stg1", "action": "complete"}],
                "new_short_term_goals": [
                    {"title": "下两周研究学区政策", "parent": "ltg1", "target_day_offset": 14}
                ],
                "long_term_updates": [{"id": "ltg1", "action": "keep", "progress": 0.2}],
                "new_long_term_goals": [],
                "life_goal_change": None,
                "summary": "这周把调仓做完了",
            }),
        )
        self.assertEqual(summary, "这周把调仓做完了")
        by_id = {g["id"]: g for g in goals["short_term_goals"]}
        self.assertEqual(by_id["stg1"]["status"], "completed")
        titles = [g["title"] for g in goals["short_term_goals"] if g["status"] == "active"]
        self.assertIn("下两周研究学区政策", titles)
        self.assertEqual(goals["long_term_goals"][0]["progress"], 0.2)
        self.assertEqual(goals["last_review_day"], 7)
        self.assertEqual(goals["review_log"][-1]["type"], "weekly")

    def test_weekly_review_cannot_touch_life_goals(self):
        agent = _review_agent()
        goals, _ = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly",
            llm=self._llm({
                "short_term_updates": [], "new_short_term_goals": [],
                "long_term_updates": [], "new_long_term_goals": [],
                "life_goal_change": {"id": "lg1", "title": "环游世界"},
                "summary": "想换个活法",
            }),
        )
        self.assertEqual(goals["life_goals"][0]["title"], "在杭州安家")

    def test_event_review_may_change_one_life_goal(self):
        agent = _review_agent()
        goals, _ = goals_mod.run_goal_review(
            agent, day=9, trigger="event",
            trigger_event={"title": "突发失业", "severity": 0.9, "description": "被裁员"},
            llm=self._llm({
                "short_term_updates": [{"id": "stg1", "action": "abandon"}],
                "new_short_term_goals": [
                    {"title": "这两周整理简历投递", "parent": "ltg1", "target_day_offset": 10}
                ],
                "long_term_updates": [], "new_long_term_goals": [],
                "life_goal_change": {"id": "lg1", "title": "先稳住生活再谈安家"},
                "summary": "失业了，先求稳",
            }),
        )
        self.assertEqual(goals["life_goals"][0]["title"], "先稳住生活再谈安家")
        self.assertFalse(goals["needs_review"])
        self.assertEqual(goals["review_log"][-1]["type"], "event")

    def test_unparseable_review_keeps_goals_and_review_day(self):
        agent = _review_agent()
        goals, summary = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly", llm=lambda p: "上周还行",
        )
        self.assertEqual(summary, "")
        self.assertEqual(goals["last_review_day"], 0)

    def test_new_goals_respect_active_caps(self):
        agent = _review_agent()
        goals, _ = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly",
            llm=self._llm({
                "short_term_updates": [],
                "new_short_term_goals": [
                    {"title": f"新目标{i}", "parent": "ltg1", "target_day_offset": 14}
                    for i in range(8)
                ],
                "long_term_updates": [], "new_long_term_goals": [],
                "life_goal_change": None, "summary": "加了一堆",
            }),
        )
        active = [g for g in goals["short_term_goals"] if g["status"] == "active"]
        self.assertLessEqual(len(active), 4)


if __name__ == "__main__":
    unittest.main()
