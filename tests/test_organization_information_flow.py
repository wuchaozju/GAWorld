"""The data has to reach the members, and the rules have to be what runs.

Three failures made an organization comparison measure nothing:

* a discussion that passed conclusions and small talk but never the task
  data, so a member could not integrate anything it did not already hold;
* a method whose material said "vote first, then discuss" that never voted
  before the discussion, so the comparison was not the comparison it was
  named after;
* a report that said "100% completed" next to a score of 0.5, because the
  two numbers were the same number under two names.
"""

import json

import pytest

from gaworld.collaboration import organization_engine as engine
from gaworld.collaboration.organization_methods import normalize_method
from gaworld.research.organization_intelligence.comparison import (
    analysis,
    benchmarks,
    protocol,
)


def members(count=4):
    return [{"id": i, "name": f"M{i}", "profile": ""} for i in range(1, count + 1)]


def task(count=4):
    return {
        "id": "q1",
        "prompt": "选择总收益最高的方案",
        "options": ["A", "B"],
        "observations": [json.dumps([{"方案": "A", "分项": i}], ensure_ascii=False) for i in range(count)],
    }


def method(**overrides):
    base = {
        "name": "m",
        "roles": ["r1", "r2", "r3", "r4"],
        "topology": {"kind": "full"},
        "rounds": 2,
        "review": False,
        "decision": "vote",
    }
    base.update(overrides)
    return normalize_method(base)


def record_prompts(answer="A"):
    seen = []

    def llm(prompt, agent_id=None):
        seen.append(json.loads(prompt))
        return json.dumps({"answer": answer, "message": "说明"})

    return seen, llm


def test_the_discussion_carries_the_task_data_along_the_communication_structure():
    seen, llm = record_prompts()
    engine.run_method(method(), members(), task(), llm, seed=3)
    discussion = [p for p in seen if p["phase"] == "communicate"]
    assert discussion
    # Every member of a fully connected team is handed the other three
    # pieces of the task. Before this, each member saw only the
    # conclusions and had to guess what the others knew.
    for prompt in discussion[:4]:
        owners = sorted(d["member"] for d in prompt["data"])
        assert owners == [m for m in (1, 2, 3, 4) if m != prompt["member"]["id"]]
        assert all("value" in d for d in prompt["data"])


def test_data_travels_one_hop_per_round_and_only_along_the_graph():
    seen, llm = record_prompts()
    path = method(
        topology={
            "kind": "custom",
            "edges": [[0, 1], [1, 0], [1, 2], [2, 1], [2, 3], [3, 2]],
        }
    )
    outcome = engine.run_method(path, members(), task(), llm, seed=3)
    discussion = [p for p in seen if p["phase"] == "communicate"]
    # Round one: a member sees its neighbour's piece and nothing further.
    first = {p["member"]["id"]: sorted(d["member"] for d in p["data"]) for p in discussion[:4]}
    assert first[1] == [2]
    assert first[4] == [3]
    # A member that is not connected to anybody receives nothing.
    assert outcome["reach"]["coverage"] < 1


def test_the_cross_review_ring_does_not_carry_raw_data():
    seen, llm = record_prompts()
    # Only members 1 and 2 are connected. The review ring still reaches
    # every member, so it could become a second way around the structure
    # being compared.
    sparse = method(
        topology={"kind": "custom", "edges": [[0, 1], [1, 0]]},
        review=True,
        revisions=1,
    )
    engine.run_method(sparse, members(), task(), llm, seed=3)
    # The reviewer of member 3 is member 4. They were never connected, so
    # member 4 may not hold member 3's piece of the task.
    review = [p for p in seen if p["phase"] == "review" and p["messages"][0]["sender"] == 3]
    assert review
    assert all(d["member"] != 3 for d in review[0]["data"])
    # A member works from what it holds itself, and its own piece is in
    # its observation rather than in the data channel.
    for prompt in seen:
        assert all(d["member"] != prompt["member"]["id"] for d in prompt["data"])


def test_a_method_that_votes_first_shows_the_vote_before_the_discussion():
    seen, llm = record_prompts()
    engine.run_method(method(prior_vote=True), members(), task(), llm, seed=3)
    discussion = [p for p in seen if p["phase"] == "communicate"]
    assert discussion[0]["prior_vote"]["tally"] == [{"answer": "A", "votes": 4}]
    assert discussion[0]["prior_vote"]["leading"] == "A"
    # The private round comes first and the tally is made from it.
    assert seen[0]["phase"] == "private"
    assert all("prior_vote" not in p for p in seen if p["phase"] == "private")


def test_without_the_prior_vote_no_tally_is_shown():
    seen, llm = record_prompts()
    engine.run_method(method(), members(), task(), llm, seed=3)
    assert all("prior_vote" not in p for p in seen)


def test_the_built_in_task_names_a_share_as_a_share():
    bank = benchmarks.builtin("information", count=3, slots=3, seed=7)
    task = bank["tasks"][0]
    share = json.loads(task["observations"][0])
    assert isinstance(share, list)
    assert all(set(piece) == {"方案", "分项"} for piece in share)
    # The question says what the pieces are; a member that mistakes its own
    # share for the total cannot solve it, and no arm can.
    assert "分项" in task["prompt"]
    assert "相加" in task["prompt"]


def test_the_prior_vote_is_a_factor_a_comparison_can_hold_equal_or_let_differ():
    assert "prior_vote" in protocol.FACTORS
    candidate = method(prior_vote=True, topology={"kind": "random", "probability": 0.5})
    control = method(prior_vote=False, topology={"kind": "full"})
    same = protocol.apply_factors(candidate, control, dict(protocol.DEFAULT_FACTORS))
    assert same["prior_vote"] is True
    assert protocol.differing_factors(candidate, same) == ["topology"]
    apart = protocol.apply_factors(
        candidate, control, {**protocol.DEFAULT_FACTORS, "prior_vote": "candidate"}
    )
    assert apart["prior_vote"] is False
    assert set(protocol.differing_factors(candidate, apart)) == {"topology", "prior_vote"}


def test_a_rule_the_engine_does_not_run_is_reported_not_swallowed():
    says_vote_first = method(
        prior_vote=False,
        rules=[{"text": "先各自解决并表决，再进行讨论。", "quote": "", "origin": "source"}],
    )
    assert protocol.fidelity(says_vote_first)["issues"]
    says_discussion_first = method(
        prior_vote=True,
        rules=[{"text": "成员进行讨论之后再进行决策和表决。", "quote": "", "origin": "source"}],
    )
    assert protocol.fidelity(says_discussion_first)["issues"]
    # A method whose rules say nothing about the order is not flagged.
    assert not protocol.fidelity(method())["issues"]


def test_the_plan_warns_before_the_run_when_an_arm_does_not_do_what_it_says():
    payload = {
        "candidate": {
            "name": "先独立表决后讨论",
            "roles": ["r1", "r2", "r3", "r4"],
            "topology": {"kind": "random", "probability": 0.5},
            "rounds": 2,
            "review": True,
            "revisions": 1,
            "decision": "vote",
            "prior_vote": True,
            "rules": [
                {"text": "独立解决后进行表决。", "quote": "先进行各自解决并表决", "origin": "source"},
                {"text": "表决后进行讨论。", "quote": "再进行讨论", "origin": "source"},
            ],
        },
        "baseline_method": {
            "name": "讨论后决策表决",
            "roles": ["r1", "r2", "r3", "r4"],
            "topology": {"kind": "full"},
            "rounds": 2,
            "review": True,
            "revisions": 1,
            "decision": "vote",
            "prior_vote": False,
            "rules": [
                {
                    "text": "成员进行讨论之后再进行决策和表决。",
                    "quote": "成员进行讨论之后 再进行决策和表决",
                    "origin": "source",
                }
            ],
        },
        "baseline": "custom",
        "count": 2,
        "repeats": 1,
    }
    prepared = protocol.prepare(payload, members())
    warnings = " ".join(prepared["plan"]["warnings"])
    # The control's own rule says the discussion comes first, and the
    # default table aligns the vote before the discussion onto it.
    assert "前置表决" in warnings
    assert prepared["control"]["prior_vote"] is True


def test_the_report_separates_a_well_formed_answer_from_a_correct_one():
    rows = [
        {
            "cell": "0:0:candidate",
            "task_id": "info-0",
            "category": "c",
            "repeat": 0,
            "arm": "candidate",
            "measured": True,
            "invalid_reason": "",
            "score": 0.0,
            "valid": True,
            "answer": {"answer": "A"},
            "metrics": {"calls": 1, "input_chars": 1, "output_chars": 1, "elapsed": 0.1},
            "reach": None,
        },
        {
            "cell": "0:0:baseline",
            "task_id": "info-0",
            "category": "c",
            "repeat": 0,
            "arm": "baseline",
            "measured": True,
            "invalid_reason": "",
            "score": 1.0,
            "valid": True,
            "answer": {"answer": "B"},
            "metrics": {"calls": 1, "input_chars": 1, "output_chars": 1, "elapsed": 0.1},
            "reach": None,
        },
    ]
    spec = {
        "title": "t",
        "candidate": {"name": "候选", "roles": ["r"], "topology": {"kind": "full"}, "rounds": 2},
        "baseline": {"name": "对照", "roles": ["r"], "topology": {"kind": "full"}, "rounds": 2},
        "arms": [
            {
                "id": "candidate",
                "label": "候选",
                "method": {"name": "候选", "roles": ["r"], "topology": {"kind": "full"}, "rounds": 2},
            },
            {
                "id": "baseline",
                "label": "对照",
                "method": {"name": "对照", "roles": ["r"], "topology": {"kind": "full"}, "rounds": 2},
            },
        ],
        "instructions": {"candidate": [], "baseline": []},
        "benchmark": {"name": "b"},
        "model": {"model": "m"},
        "engine_version": "organization-engine-3",
        "delta": 0,
        "limits": {},
        "expected": 2,
    }
    result = analysis.analyze(rows, expected=2, delta=0, seed=1, arms=["candidate", "baseline"])
    text = analysis.report(
        {
            "protocol": spec,
            "rows": rows,
            "analysis": result,
            "status": "completed",
            "protocol_hash": "hash",
        }
    )
    assert "格式合规率" in text
    assert "完成率 |" not in text
    # The failure list says how many there are instead of quietly showing
    # the first ten of them.
    assert "共 1 个实验单元没有得到满分" in text
    assert "每一臂实际执行的机制" in text


@pytest.mark.parametrize("kind", ["information", "allocation"])
def test_both_built_in_banks_stay_scorable(kind):
    bank = benchmarks.builtin(kind, count=4, slots=3, seed=11)
    for q in bank["tasks"]:
        assert benchmarks.score(q, {"answer": q["reference"]})["score"] == 1
        assert len(q["observations"]) == 3
