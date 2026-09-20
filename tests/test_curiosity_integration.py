import unittest
from unittest.mock import patch

import generative_city_sim as sim


def _agent():
    return {
        "id": 3,
        "name": "测试居民",
        "age": 31,
        "job": "外卖骑手",
        "personality": "务实，关注收入",
        "daily_life": "每天跑单",
        "values": "重视收入稳定",
        "state": {"stress": 0.8, "econ_security": 0.4,
                  "platform_dependence": 0.6, "risk_preference": 0.5},
        "growth_profile": {"items": []},
        "memory": [],
    }


class TestCuriosityTickTrigger(unittest.TestCase):
    def test_fresh_event_triggers_seek_and_writes_rag(self):
        agent = _agent()
        cfg = {
            "contextual_keywords": True,
            "contextual_max_keywords": 2,
            "memory_excerpt_chars": 200,
            "event_driven": {
                "enabled": True,
                "max_extra_seeks_per_day": 2,
                "stress_threshold": 0.6,
                "curiosity_threshold": 0.6,
                "trigger_chance_on_event": 1.0,
            },
        }

        # The seek itself returns a fake memory + log so we only assert wiring.
        def fake_seek(agent, **kw):
            self.assertEqual(kw["keywords"], ["配送费规则 最新", "骑手收入 政策"])
            return "MEM", "LOGLINE\n", "https://ex.com/a", "配送费规则 最新"

        budget = {3: 2}
        with patch.object(sim, "propose_contextual_keywords",
                          return_value=["配送费规则 最新", "骑手收入 政策"]), \
             patch.object(sim, "info_seek_and_store", side_effect=fake_seek):
            triggered = sim._maybe_curiosity_seek(
                agent,
                day=1,
                time_str="12:30",
                scheduled_activity="跑单途中",
                recent_events=["平台调整了配送费规则"],
                news_cache=[],
                news_sources=[],
                preferred_sites=[],
                seen_urls=set(),
                used_queries=set(),
                curiosity_budget=budget,
                config=cfg,
            )

        self.assertTrue(triggered)
        self.assertEqual(budget[3], 1)  # budget decremented


if __name__ == "__main__":
    unittest.main()
