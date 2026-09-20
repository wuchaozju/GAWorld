"""Print the actual prompt that ``generate_daily_routine`` sends to the LLM
for two contrasting agents (high-emotion / low-emotion).

This is a sanity-check tool for the new context aggregators (state,
yesterday recap, recent life events, social pulse).  No real LLM call
is made — we patch ``call_llm`` so the script terminates immediately
and prints the captured prompt.

Run from the repo root:
    python scripts/dev/show_daily_routine_prompt.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

# Make the repo root importable when invoked as a script.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import generative_city_sim as sim  # noqa: E402  (sys.path tweak above)


def _common_agent(agent_id: int, name: str) -> dict:
    return {
        "id": agent_id,
        "name": name,
        "age": 33,
        "job": "产品经理",
        "personality": "敏感细腻，注重节奏",
        "daily_life": "工作日朝九晚六，周末偏静态",
        "values": "重视健康与家庭，关心社区议题",
        "intentions": {
            "priorities": ["跟进项目", "晚上恢复体力"],
            "avoidances": ["拖延", "情绪化决策"],
            "target_social": "回复一两条朋友消息",
            "target_recovery": "晚饭后散步",
            "growth_focus": ["阅读"],
        },
    }


def _build_low_mood_agent() -> dict:
    agent = _common_agent(101, "低情绪示范")
    agent["state"] = {
        "emotion": 0.25,
        "stress": 0.82,
        "energy": 0.35,
        "hunger": 0.7,
        "fatigue_debt": 0.78,
        "time_pressure": 0.7,
        "self_control": 0.35,
        "social_need": 0.62,
    }
    agent["episodes"] = [
        {
            "day": 2, "time": "10:00", "final_activity": "上午工作",
            "action": "加班赶进度", "salience": 0.82,
            "reflection": "压力很大，被催了一上午",
        },
        {
            "day": 2, "time": "21:30", "final_activity": "睡前",
            "action": "失眠刷手机", "salience": 0.74,
            "reflection": "睡前焦虑，越想越睡不着",
        },
    ]
    agent["relationships"] = {
        "7": {
            "closeness": 0.62, "trust": 0.55, "obligation": 0.5,
            "friction": 0.45, "last_interaction_day": 2,
        }
    }
    return agent


def _build_high_mood_agent() -> dict:
    agent = _common_agent(202, "高情绪示范")
    agent["state"] = {
        "emotion": 0.82,
        "stress": 0.25,
        "energy": 0.78,
        "hunger": 0.3,
        "fatigue_debt": 0.22,
        "time_pressure": 0.3,
        "self_control": 0.7,
        "social_need": 0.55,
    }
    agent["episodes"] = [
        {
            "day": 2, "time": "11:00", "final_activity": "上午工作",
            "action": "完成关键交付", "salience": 0.78,
            "reflection": "推进顺利，被认可",
        },
        {
            "day": 2, "time": "19:30", "final_activity": "晚餐",
            "action": "和朋友聚餐", "salience": 0.7,
            "reflection": "聊得开心",
        },
    ]
    agent["relationships"] = {
        "12": {
            "closeness": 0.82, "trust": 0.78, "obligation": 0.6,
            "friction": 0.15, "last_interaction_day": 2,
        }
    }
    return agent


# A consumed life event scoped to the low-mood agent and a city-wide one.
FAKE_LIFE_EVENTS = [
    {
        "title": "突然生病",
        "description": "昨晚开始发烧、乏力，今天需要重新安排。",
        "severity": 0.7,
        "status": "consumed",
        "triggered_day": 2,
        "triggered_time": "21:00",
        "agent_ids": [101],
        "impact_tags": ["health", "stress"],
    },
    {
        "title": "片区临时停水",
        "description": "今天上午所在片区停水，需要重新安排洗漱与做饭。",
        "severity": 0.4,
        "status": "consumed",
        "triggered_day": 3,
        "triggered_time": "07:00",
        "agent_ids": [],
    },
]


BASE_SCHEDULE = [
    ("07:00", "起床洗漱"),
    ("08:30", "通勤"),
    ("09:30", "上午工作"),
    ("12:30", "午餐"),
    ("14:00", "下午工作"),
    ("18:30", "晚餐"),
    ("20:00", "个人时间"),
    ("23:00", "睡觉"),
]


def _capture_prompt(agent: dict, day: int) -> str:
    captured: dict[str, str] = {}

    def fake_llm(prompt, task=None, agent_id=None):
        captured["prompt"] = prompt
        # Return something the schedule parser will accept so
        # generate_daily_routine completes normally.
        return json.dumps(
            [{"time": t, "activity": a} for t, a in BASE_SCHEDULE],
            ensure_ascii=False,
        )

    with patch.object(sim, "call_llm", side_effect=fake_llm), \
         patch.object(sim, "list_life_events", return_value=FAKE_LIFE_EVENTS):
        sim.generate_daily_routine(agent, BASE_SCHEDULE, day=day)
    return captured.get("prompt", "<prompt was not captured>")


def main() -> int:
    for label, agent_builder in [
        ("LOW-MOOD AGENT", _build_low_mood_agent),
        ("HIGH-MOOD AGENT", _build_high_mood_agent),
    ]:
        agent = agent_builder()
        prompt = _capture_prompt(agent, day=3)
        print("=" * 80)
        print(f"  {label}  (id={agent['id']}, name={agent['name']})")
        print("=" * 80)
        print(prompt)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
