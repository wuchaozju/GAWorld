"""Tests for the four context aggregators feeding ``generate_daily_routine``.

The aggregators (state / yesterday / life events / social pulse) are pure
functions, so we exercise them directly with hand-crafted agent dicts.
The integrated prompt is then checked by patching ``call_llm`` and
capturing the prompt text actually passed to the LLM.
"""

import unittest
from unittest.mock import patch

import generative_city_sim as sim


def _make_agent(**overrides):
    base = {
        "id": 1,
        "name": "张三",
        "age": 32,
        "job": "项目经理",
        "personality": "稳重",
        "daily_life": "工作日朝九晚六",
        "values": "重视家庭",
        "state": {
            "emotion": 0.5,
            "stress": 0.5,
            "energy": 0.6,
            "hunger": 0.3,
            "fatigue_debt": 0.3,
            "time_pressure": 0.3,
            "self_control": 0.6,
            "social_need": 0.5,
        },
        "episodes": [],
        "relationships": {},
        "intentions": {
            "priorities": ["专注工作"],
            "avoidances": ["拖延"],
            "target_social": "回复消息",
            "target_recovery": "早睡",
            "growth_focus": ["阅读"],
        },
    }
    base.update(overrides)
    return base


class TestStateBrief(unittest.TestCase):
    def test_high_emotion_produces_positive_band(self):
        agent = _make_agent()
        agent["state"]["emotion"] = 0.85
        agent["state"]["stress"] = 0.2
        text = sim._state_brief_for_prompt(agent)
        self.assertIn("偏积极", text)
        self.assertIn("较低", text)  # stress 较低
        self.assertIn("emotion=0.85", text)

    def test_low_emotion_produces_low_band(self):
        agent = _make_agent()
        agent["state"]["emotion"] = 0.2
        agent["state"]["fatigue_debt"] = 0.8
        agent["state"]["hunger"] = 0.75
        text = sim._state_brief_for_prompt(agent)
        self.assertIn("偏低落", text)
        self.assertIn("较重", text)
        self.assertIn("明显", text)

    def test_missing_state_uses_neutral_defaults(self):
        agent = {"id": 7}
        text = sim._state_brief_for_prompt(agent)
        # No crash, and the section header is always present.
        self.assertIn("当前身心状态", text)


class TestYesterdayRecap(unittest.TestCase):
    def test_first_day_returns_fallback(self):
        agent = _make_agent()
        text = sim._yesterday_recap_for_prompt(agent, day=1)
        self.assertIn("模拟首日", text)

    def test_picks_highest_salience_from_prev_day(self):
        agent = _make_agent()
        agent["episodes"] = [
            {
                "day": 2, "time": "09:00", "final_activity": "工作",
                "action": "推进项目", "salience": 0.4,
                "reflection": "节奏不错",
            },
            {
                "day": 2, "time": "20:00", "final_activity": "晚餐",
                "action": "和家人聊天", "salience": 0.8,
                "reflection": "情绪修复明显",
            },
            {
                "day": 1, "time": "10:00", "final_activity": "会议",
                "action": "汇报", "salience": 0.9,
            },
        ]
        text = sim._yesterday_recap_for_prompt(agent, day=3)
        self.assertIn("Day 2", text)
        self.assertIn("和家人聊天", text)  # high-salience day-2 episode
        self.assertNotIn("汇报", text)      # day-1 must be excluded

    def test_no_prev_day_episodes_yields_calm_message(self):
        agent = _make_agent()
        agent["episodes"] = [
            {"day": 5, "time": "09:00", "final_activity": "工作", "salience": 0.5}
        ]
        text = sim._yesterday_recap_for_prompt(agent, day=3)
        self.assertIn("整体平稳", text)


class TestRecentLifeEvents(unittest.TestCase):
    def test_returns_empty_when_no_events(self):
        agent = _make_agent()
        with patch("gaworld.sim._prompt.list_life_events", return_value=[]):
            text = sim._recent_life_events_for_prompt(agent, day=5)
        self.assertIn("近期突发事件：无", text)

    def test_filters_pending_and_old_events(self):
        agent = _make_agent()
        events = [
            {
                "title": "突然生病", "description": "发烧需要休养",
                "severity": 0.7, "status": "consumed",
                "triggered_day": 4, "triggered_time": "10:00",
                "agent_ids": [1],
            },
            {
                "title": "未触发事件", "description": "...",
                "status": "pending", "triggered_day": 0,
                "agent_ids": [1],
            },
            {
                "title": "陈年事件", "description": "...",
                "status": "consumed", "triggered_day": 1,
                "agent_ids": [1],
            },
            {
                "title": "别人的事件", "description": "...",
                "status": "consumed", "triggered_day": 4,
                "agent_ids": [99],
            },
        ]
        with patch("gaworld.sim._prompt.list_life_events", return_value=events):
            text = sim._recent_life_events_for_prompt(agent, day=5, max_age_days=2)
        self.assertIn("突然生病", text)
        self.assertNotIn("未触发事件", text)
        self.assertNotIn("陈年事件", text)
        self.assertNotIn("别人的事件", text)

    def test_unscoped_event_reaches_every_agent(self):
        agent = _make_agent()
        events = [
            {
                "title": "城市公告", "description": "全市断电",
                "severity": 0.5, "status": "consumed",
                "triggered_day": 5, "triggered_time": "08:00",
                "agent_ids": [],
            }
        ]
        with patch("gaworld.sim._prompt.list_life_events", return_value=events):
            text = sim._recent_life_events_for_prompt(agent, day=5)
        self.assertIn("城市公告", text)


class TestSocialPulse(unittest.TestCase):
    def test_empty_relationships_returns_none_text(self):
        agent = _make_agent()
        text = sim._social_pulse_for_prompt(agent, day=3)
        self.assertIn("近期社交脉动：无", text)

    def test_picks_recent_top_relationships(self):
        agent = _make_agent()
        agent["current_day"] = 5
        agent["relationships"] = {
            "7": {
                "closeness": 0.8, "trust": 0.7, "obligation": 0.5,
                "friction": 0.2, "last_interaction_day": 4,
            },
            "12": {
                "closeness": 0.2, "trust": 0.2, "obligation": 0.3,
                "friction": 0.6, "last_interaction_day": 4,
            },
            "20": {
                "closeness": 0.9, "trust": 0.9, "obligation": 0.8,
                "friction": 0.1, "last_interaction_day": 1,  # too old
            },
        }
        text = sim._social_pulse_for_prompt(agent, day=5, max_age_days=2, top_k=2)
        self.assertIn("邻居 #7", text)
        self.assertNotIn("邻居 #20", text)  # outside max_age_days

    def test_uses_agents_by_id_for_names(self):
        agent = _make_agent()
        agent["current_day"] = 3
        agent["relationships"] = {
            "5": {"closeness": 0.6, "trust": 0.6, "friction": 0.2,
                  "last_interaction_day": 3}
        }
        agents_by_id = {5: {"name": "李四"}}
        text = sim._social_pulse_for_prompt(
            agent, day=3, agents_by_id=agents_by_id
        )
        self.assertIn("李四", text)


class TestGenerateDailyRoutinePromptComposition(unittest.TestCase):
    """End-to-end check that the new sections actually make it into the prompt."""

    def _capture_prompt_for_agent(self, agent):
        base_schedule = [
            ("07:00", "起床"),
            ("09:00", "工作"),
            ("12:00", "午餐"),
            ("14:00", "工作"),
            ("19:00", "晚餐"),
            ("23:00", "睡觉"),
        ]
        captured = {}

        def fake_llm(prompt, task=None, agent_id=None):
            # setdefault, not assignment: ``generate_daily_routine`` makes a
            # *second* call to the weekend rewriter when the simulated Day 3
            # happens to fall on a Saturday or Sunday, and overwriting here
            # handed the assertions that prompt instead of the one under test.
            #
            # The sim calendar starts from the real date by default, so Day 3
            # is a weekend on two days out of every seven — which is exactly
            # how often this pair went red. It read as flakiness and was twice
            # misdiagnosed (as RNG order, then as leftover state under
            # output/); it is neither, it is the calendar.
            captured.setdefault("prompt", prompt)
            return '[{"time":"07:00","activity":"起床"},{"time":"23:00","activity":"睡觉"}]'

        with patch.object(sim, "call_llm", side_effect=fake_llm), \
             patch("gaworld.sim._prompt.list_life_events", return_value=[]):
            sim.generate_daily_routine(agent, base_schedule, day=3)
        return captured.get("prompt", "")

    def test_capture_is_the_routine_prompt_on_every_weekday(self):
        """The prompt under test must not depend on what day it is run.

        Both a weekday Day 3 and a weekend Day 3 have to yield the daily-routine
        prompt, not the weekend rewriter's.
        """
        import datetime

        for start in (datetime.date(2026, 9, 7), datetime.date(2026, 9, 10)):
            with self.subTest(start=start.strftime("%a")):
                with patch.object(sim, "SIM_START_DATE", start):
                    prompt = self._capture_prompt_for_agent(_make_agent())
                self.assertNotIn("周末个性化日程改写器", prompt)
                self.assertIn("当前身心状态", prompt)

    def test_prompt_contains_all_new_sections(self):
        agent = _make_agent()
        agent["episodes"] = [
            {"day": 2, "time": "20:00", "final_activity": "晚餐",
             "action": "陪家人", "salience": 0.7},
        ]
        agent["relationships"] = {
            "9": {"closeness": 0.7, "trust": 0.6, "friction": 0.2,
                  "last_interaction_day": 2}
        }
        prompt = self._capture_prompt_for_agent(agent)
        self.assertIn("当前身心状态", prompt)
        self.assertIn("昨日关键回顾", prompt)
        self.assertIn("近期突发事件", prompt)
        self.assertIn("事件余波", prompt)
        self.assertIn("近期社交脉动", prompt)
        self.assertIn("基础日程", prompt)  # original section preserved

    def test_high_vs_low_stress_prompt_differs(self):
        agent_high = _make_agent()
        agent_high["state"]["emotion"] = 0.2
        agent_high["state"]["stress"] = 0.85
        agent_high["state"]["fatigue_debt"] = 0.8

        agent_low = _make_agent()
        agent_low["state"]["emotion"] = 0.85
        agent_low["state"]["stress"] = 0.2
        agent_low["state"]["fatigue_debt"] = 0.2

        prompt_high = self._capture_prompt_for_agent(agent_high)
        prompt_low = self._capture_prompt_for_agent(agent_low)
        self.assertIn("偏低落", prompt_high)
        self.assertIn("偏积极", prompt_low)
        self.assertNotEqual(prompt_high, prompt_low)


if __name__ == "__main__":
    unittest.main()
