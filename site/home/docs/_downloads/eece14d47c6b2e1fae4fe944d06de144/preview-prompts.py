"""Render documentation prompts offline using GAWorld's actual builders.

Run from an environment with GAWorld installed:
    python preview-prompts.py --out prompts-preview
The personas, events and replies below are teaching fixtures.
"""
import argparse
import json
import random
from pathlib import Path
from unittest.mock import patch

from gaworld.interview.prompt import build_turn_prompt, parse_answer
from gaworld.interview.schema import Question
from gaworld.research.policy_sim import reaction_prompt
from gaworld.sim._cognition import perception
from gaworld.sim._fastforward import simulate_agent_day


def render():
    prompts = {}
    persona = "你是林悦，住在城西，每天乘公交去社区服务中心工作。"
    context = "社区正在征求公交末班车时间的调整意见。"
    questions = [
        Question(id="q1", text="目前的末班车时间对你的生活有什么影响？"),
        Question(id="q2", text="你希望末班车如何调整？", kind="choice",
                 options=["保持现状", "延后半小时", "延后一小时"]),
        Question(id="q3", text="你会使用延后的末班车吗？", kind="boolean"),
    ]
    for question in questions:
        prompts[f"interview-{question.kind}.txt"] = build_turn_prompt(
            persona=persona, context=context, question=question,
        ).strip() + "\n"

    agent = {"id": 1, "name": "林悦", "state": {"emotion": .5, "stress": .4},
             "social_neighbors": [], "memory": []}

    def capture_perception(prompt, **kwargs):
        prompts["perception.txt"] = prompt.strip() + "\n"
        assert kwargs["task"] == "perception"
        return "社区的新通告让我想重新安排下班后的出行。"

    with patch("gaworld.sim._cognition._deterministic_cognition_enabled", return_value=False), \
            patch("gaworld.llm.providers.call_llm", side_effect=capture_perception):
        perception(agent, "18:00", "同事也在讨论末班车时间。",
                   "社区服务中心即将关门。", "公交末班车拟延后半小时。",
                   extra_sections=["你已经掌握的小技能：\n- 路线规划：比较通勤路线与耗时。"])

    def capture_digest(prompt, **kwargs):
        prompts["daily-brief.txt"] = prompt.strip() + "\n"
        assert kwargs["task"] == "fast_forward_day"
        return json.dumps({"brief": "今天在社区工作，下班后乘公交回家。",
                           "memory": "留意末班车时间。", "state_changes": {"stress": -.01}},
                          ensure_ascii=False)

    simulate_agent_day(agent, day=1, day_desc="工作日",
                       base_schedule=[("09:00", "社区工作"), ("18:00", "乘公交回家")],
                       env_context="公交末班车拟延后半小时。",
                       config={"long_run": {"randomness": 0, "brief_llm": True}},
                       llm_fn=capture_digest, rng=random.Random(42))
    prompts["policy-reaction.txt"] = reaction_prompt(
        persona, "将公交末班车延后半小时，票价保持不变。", "示例城市"
    ).strip() + "\n"

    # These fixture replies check the current parser without calling a model.
    choice = parse_answer('{"choice":["延后半小时"],"reason":"方便下班回家。"}', questions[1])
    assert choice.choice == ["延后半小时"] and not choice.unparsed
    boolean = parse_answer('{"yes":true,"reason":"有时会晚下班。"}', questions[2])
    assert boolean.boolean is True and not boolean.unparsed
    return prompts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("prompts-preview"))
    args = parser.parse_args()
    prompts = render()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in prompts.items():
        (args.out / name).write_text(content, encoding="utf-8")
    print(f"Rendered {len(prompts)} prompt files into {args.out}; model calls: 0")
