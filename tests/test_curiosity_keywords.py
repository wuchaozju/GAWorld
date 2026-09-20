import random
import unittest

from gaworld.sim import _curiosity


def _agent():
    return {
        "id": 7,
        "name": "测试居民",
        "age": 31,
        "job": "外卖骑手",
        "personality": "务实，关注收入",
        "daily_life": "每天跑单，晚上看手机资讯",
        "values": "重视收入稳定",
        "state": {
            "stress": 0.7,
            "econ_security": 0.4,
            "platform_dependence": 0.6,
            "risk_preference": 0.5,
        },
        "growth_profile": {"items": [{"name": "理财", "kind": "skill", "priority": 1, "level": 0.2}]},
        "memory": [],
    }


class TestAssembleContext(unittest.TestCase):
    def test_assembles_four_signal_groups(self):
        ctx = _curiosity.assemble_curiosity_context(
            _agent(),
            scheduled_activity="跑单途中",
            recent_events=["平台调整了配送费规则"],
            day=2,
            time_str="12:30",
        )
        self.assertEqual(ctx["activity"], "跑单途中")
        self.assertIn("平台调整了配送费规则", ctx["recent_events"])
        self.assertAlmostEqual(ctx["state"]["stress"], 0.7)
        self.assertIn("理财", ctx["growth_focus"])
        self.assertEqual(ctx["day"], 2)
        self.assertEqual(ctx["time_str"], "12:30")


class TestShouldSeekKnowledge(unittest.TestCase):
    CONFIG = {
        "event_driven": {
            "enabled": True,
            "stress_threshold": 0.6,
            "curiosity_threshold": 0.6,
            "trigger_chance_on_event": 0.5,
        }
    }

    def _ctx(self, **over):
        base = {
            "activity": "跑单途中",
            "recent_events": [],
            "state": {"stress": 0.3, "econ_security": 0.5},
            "growth_focus": [],
            "day": 1,
            "time_str": "10:00",
        }
        base.update(over)
        return base

    def test_no_trigger_when_disabled(self):
        cfg = {"event_driven": {"enabled": False}}
        ok, reason = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(recent_events=["x"]), budget_left=5, config=cfg
        )
        self.assertFalse(ok)

    def test_no_trigger_when_budget_exhausted(self):
        ok, _ = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(recent_events=["x"]), budget_left=0, config=self.CONFIG
        )
        self.assertFalse(ok)

    def test_no_trigger_when_no_hard_condition(self):
        # stress low, no events, no growth focus, low curiosity -> no hard condition
        agent = _agent()
        agent["state"]["platform_dependence"] = 0.1
        agent["state"]["risk_preference"] = 0.1
        ok, _ = _curiosity.should_seek_knowledge(
            agent, self._ctx(state={"stress": 0.1, "econ_security": 0.5}, growth_focus=[]),
            budget_left=5, config=self.CONFIG,
        )
        self.assertFalse(ok)

    def test_event_triggers_when_dice_low(self):
        random.seed(0)
        # With trigger_chance 1.0 a hard condition (fresh event) always fires.
        cfg = {"event_driven": {"enabled": True, "stress_threshold": 0.6,
                                "curiosity_threshold": 0.6, "trigger_chance_on_event": 1.0}}
        ok, reason = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(recent_events=["平台调整配送费"]), budget_left=5, config=cfg
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "event")

    def test_high_stress_is_hard_condition(self):
        cfg = {"event_driven": {"enabled": True, "stress_threshold": 0.6,
                                "curiosity_threshold": 0.6, "trigger_chance_on_event": 1.0}}
        ok, reason = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(state={"stress": 0.8, "econ_security": 0.4}),
            budget_left=5, config=cfg,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "stress")


from unittest.mock import patch
from gaworld.llm import providers as _providers


class TestProposeKeywords(unittest.TestCase):
    def _ctx(self):
        return {
            "activity": "跑单途中",
            "recent_events": ["平台调整了配送费规则"],
            "state": {"stress": 0.7, "econ_security": 0.4},
            "growth_focus": ["理财"],
            "day": 2,
            "time_str": "12:30",
        }

    def test_parses_json_array(self):
        with patch.object(_providers, "call_llm",
                          return_value='["配送费规则 最新", "骑手收入 政策"]'):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config={})
        self.assertEqual(kws, ["配送费规则 最新", "骑手收入 政策"])

    def test_respects_max(self):
        cfg = {"contextual_max_keywords": 1}
        with patch.object(_providers, "call_llm",
                          return_value='["a 最新", "b 政策", "c 趋势"]'):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config=cfg)
        self.assertEqual(len(kws), 1)

    def test_garbage_falls_back_to_template(self):
        with patch.object(_providers, "call_llm", return_value="抱歉我不知道"):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config={})
        # Fallback returns a non-empty template query string list.
        self.assertTrue(kws)
        self.assertIsInstance(kws[0], str)

    def test_llm_exception_falls_back(self):
        with patch.object(_providers, "call_llm", side_effect=RuntimeError("boom")):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config={})
        self.assertTrue(kws)


from gaworld.sim import _news


class TestNewsKeywordsParam(unittest.TestCase):
    def test_choose_info_target_uses_keywords_for_web_search(self):
        captured = {}

        def fake_web_search(query, config=None):
            captured["query"] = query
            return "google", [{"url": "https://ex.com/a", "title": "标题", "snippet": "片段内容"}]

        def fake_excerpt(url, **kw):
            return "这是抓取到的正文内容，足够长用于记忆。"

        with patch.object(_news, "web_search", side_effect=fake_web_search), \
             patch.object(_news, "fetch_news_excerpt", side_effect=fake_excerpt):
            target = _news._choose_info_target(
                agent=_agent(),
                news_cache=[],
                news_sources=[],
                preferred_sites=[],
                keywords=["配送费规则 最新", "骑手收入 政策"],
            )
        self.assertEqual(target["mode"], "web_search")
        self.assertEqual(captured["query"], "配送费规则 最新 骑手收入 政策")
        self.assertEqual(target["url"], "https://ex.com/a")


from gaworld.settings import behavior as _behavior_settings


class TestConfigDefaults(unittest.TestCase):
    def test_info_seek_has_curiosity_keys(self):
        cfg = _behavior_settings.news_settings()["news"]["info_seek"]
        self.assertTrue(cfg["contextual_keywords"])
        self.assertEqual(cfg["contextual_max_keywords"], 3)
        ev = cfg["event_driven"]
        self.assertTrue(ev["enabled"])
        self.assertEqual(ev["max_extra_seeks_per_day"], 2)
        self.assertAlmostEqual(ev["stress_threshold"], 0.6)
        self.assertAlmostEqual(ev["curiosity_threshold"], 0.6)
        self.assertAlmostEqual(ev["trigger_chance_on_event"], 0.5)


if __name__ == "__main__":
    unittest.main()
