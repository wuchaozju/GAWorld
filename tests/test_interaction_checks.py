"""Synchronous feedback uses independent groups and explicit factorial controls."""

import copy
import json

import pytest

from gaworld.research import replication as rp


def spec(enabled=True, rounds=2, size=4):
    return {
        "items": [
            {"id": "Q1", "text": "评分", "kind": "number", "min": 0, "max": 10, "interaction_margin": 0.3}
        ],
        "results": [{"item": "Q1", "mean": 5, "sd": 1, "n": 100}],
        "interaction_probe": {"enabled": enabled, "rounds": rounds, "group_size": size},
    }


def run(s, answer=None, n=16, **kwargs):
    return rp.run_replication(
        spec=s,
        answer=answer or (lambda _: '{"Q1":5}'),
        seed=321,
        sample_size=n,
        population=[{"id": i, "age": 30, "name": f"居民{i}"} for i in range(n)],
        profile_fn=lambda *_: "固定档案",
        workers=2,
        **kwargs,
    )


def check(result):
    return next(
        c for c in result["comparison"]["cells"][0]["result_checks"]["checks"] if c["id"] == "interaction"
    )


def test_normalization_preserves_explicit_controls_and_separate_margin():
    s = rp.normalize_spec(spec())
    assert s.get("interaction_probe") == spec()["interaction_probe"]
    assert s["items"][0].get("interaction_margin") == 0.3


@pytest.mark.parametrize(
    "field,value",
    [("rounds", 0), ("rounds", 4), ("rounds", True), ("rounds", 1.5), ("group_size", 1), ("group_size", 9)],
)
def test_invalid_settings_fail_before_model_calls(field, value):
    s = spec()
    s["interaction_probe"][field] = value
    calls = []
    with pytest.raises(ValueError, match="互动"):
        run(s, lambda p: calls.append(p) or '{"Q1":5}')
    assert not calls


def test_default_off_makes_no_extra_calls():
    calls = []
    r = run(spec(False), lambda p: calls.append(p) or '{"Q1":5}')
    assert len(calls) == 16
    assert check(r)["status"] == "untested"


def test_singleton_condition_rejected_before_main_calls():
    s = spec()
    s["conditions"] = [{"id": f"C{i}"} for i in range(6)]
    s["results"][0]["condition"] = "C0"
    calls = []
    with pytest.raises(ValueError, match="至少两位"):
        run(s, lambda p: calls.append(p) or '{"Q1":5}', n=6)
    assert not calls


def test_budget_group_partition_and_synchronous_branch_isolation():
    calls = []

    def answer(prompt):
        calls.append(prompt)
        if "【本轮可见的过往回答】" not in prompt:
            return '{"Q1":2}'
        visible = json.loads(prompt.split("【本轮可见的过往回答】\n")[1].split("\n【作答要求】")[0])
        return json.dumps({"Q1": 3 + bool(visible["own"]) + 2 * bool(visible["peers"])})

    r = run(spec(), answer)
    assert len(calls) == 16 * (1 + 4 * 2) == r["check_protocol"]["planned_calls"]
    assert all(row["answers"]["Q1"] == 2 for row in r["responses"])
    ir = r["interaction_run"]
    assert len(ir["groups"]) == 4
    assert sorted(a for g in ir["groups"] for a in g["members"]) == list(range(16))
    assert len(ir["rounds"]) == 2
    for row in ir["rounds"][0]["responses"]:
        for record in row["arms"].values():
            assert record["source_round"] == 0
            assert record["prompt_hash"]
            assert all(p["agent_id"] != row["agent_id"] for p in record["exposure"]["peers"])
    for row in ir["rounds"][1]["responses"]:
        for arm, record in row["arms"].items():
            expected = {"fresh": 3, "self": 4, "peers": 5, "both": 6}[arm]
            exposure = record["exposure"]
            if exposure["own"] is not None:
                assert exposure["own"]["Q1"] == expected
            assert all(p["answers"]["Q1"] == expected for p in exposure["peers"])
    again = run(spec(), answer)
    assert ir["groups"] == again["interaction_run"]["groups"]
    assert [r["arm_order"] for r in ir["rounds"][0]["responses"]] == [
        r["arm_order"] for r in again["interaction_run"]["rounds"][0]["responses"]
    ]


def measured(n=16, margin=0.3):
    r = run(spec(rounds=1), n=n)
    r["spec"]["items"][0]["interaction_margin"] = margin
    for row in r["interaction_run"]["rounds"][0]["responses"]:
        g = next(i for i, x in enumerate(r["interaction_run"]["groups"]) if x["id"] == row["group"])
        for arm, value in {"fresh": 3, "self": 4, "peers": 5, "both": 7 + g * 0.1}.items():
            row["arms"][arm]["answers"]["Q1"] = value
    from gaworld.research.interaction_checks import attach

    attach(r["comparison"], r["spec"], r["responses"], r["interaction_run"])
    return r


def test_inference_uses_group_count_not_residents_or_rounds():
    c = check(measured())
    assert c["status"] == "detected"
    assert c["evidence"]["unit"] == "group"
    assert c["evidence"]["complete_groups"] == 4
    peer = c["evidence"]["contrasts"]["peer"]
    assert peer["evidence"]["components"][0][1] == 4
    assert peer["evidence"]["difference"] == pytest.approx(3.15)
    assert c["evidence"]["contrasts"]["memory"]["evidence"]["difference"] == pytest.approx(2.15)
    assert c["evidence"]["contrasts"]["interaction"]["evidence"]["difference"] == pytest.approx(1.15)


def test_one_group_and_zero_group_variance_cannot_support_inference():
    assert check(measured(n=4))["status"] == "insufficient"
    assert check(run(spec(rounds=1)))["status"] == "insufficient"


def test_missing_member_excludes_whole_group_and_prevents_equivalence():
    from gaworld.research.interaction_checks import attach

    r = measured(margin=9)
    assert check(r)["status"] == "stable"
    r["interaction_run"]["rounds"][0]["responses"][0]["arms"]["self"] = {"answers": {}, "error": "timeout"}
    attach(r["comparison"], r["spec"], r["responses"], r["interaction_run"])
    c = check(r)
    assert c["status"] == "insufficient"
    assert c["evidence"]["complete_groups"] == 3
    assert c["evidence"]["missing_groups"] == 1


def test_duplicate_and_overlapping_group_records_cannot_infer():
    from gaworld.research.interaction_checks import attach

    r = measured()
    r["interaction_run"]["rounds"][0]["responses"].append(
        copy.deepcopy(r["interaction_run"]["rounds"][0]["responses"][0])
    )
    attach(r["comparison"], r["spec"], r["responses"], r["interaction_run"])
    assert check(r)["status"] == "insufficient"
    assert not check(r)["evidence"].get("contrasts")


def test_nominal_choices_report_shifts_and_disagreement_without_code_means():
    s = spec(rounds=1)
    s["items"] = [{"id": "Q1", "text": "选择", "kind": "choice", "options": ["甲", "乙"]}]
    s["results"] = [{"item": "Q1", "distribution": {"甲": 0.5, "乙": 0.5}}]
    r = run(s, lambda p: '{"Q1":2}' if "【本轮可见的过往回答】" in p else '{"Q1":1}')
    c = check(r)
    assert c["status"] == "observed"
    assert c["evidence"]["option_shifts"]["peer"] == {"甲": 0, "乙": 0}
    assert "contrasts" not in c["evidence"]
    assert "disagreement" in c["evidence"]
    assert "短期" in rp.export_markdown(r)


def test_odd_pairs_with_two_person_limit_rejected_before_calls():
    calls = []
    with pytest.raises(ValueError, match="至少两位"):
        run(spec(size=2), lambda p: calls.append(p), n=7)
    assert not calls


def test_round_workers_keep_owner_context_and_failures_do_not_change_budget():
    import contextvars

    owner = contextvars.ContextVar("interaction_test_owner", default="lost")
    token = owner.set("requester")
    seen = []

    def answer(prompt):
        seen.append(owner.get())
        if "【本轮可见的过往回答】" in prompt:
            raise TimeoutError("fixture")
        return '{"Q1":5}'

    try:
        r = run(spec(rounds=1), answer)
    finally:
        owner.reset(token)
    assert seen == ["requester"] * 80
    assert check(r)["evidence"]["missing_groups"] == 4
    assert check(r)["status"] == "insufficient"
    for row in r["interaction_run"]["rounds"][0]["responses"]:
        assert all("TimeoutError" in record["error"] for record in row["arms"].values())


def test_missing_earlier_round_excludes_group_even_when_final_round_complete():
    from gaworld.research.interaction_checks import attach

    r = run(spec())
    r["interaction_run"]["rounds"][0]["responses"][0]["arms"]["peers"]["answers"] = {}
    attach(r["comparison"], r["spec"], r["responses"], r["interaction_run"])
    assert check(r)["evidence"]["complete_groups"] == 3
    assert check(r)["evidence"]["missing_groups"] == 1
    before = r["comparison"]["cells"][0]["result_checks"]["source_hash"]
    attach(r["comparison"], r["spec"], r["responses"], r["interaction_run"])
    assert r["comparison"]["cells"][0]["result_checks"]["source_hash"] == before


@pytest.mark.parametrize("damage", ["missing_run", "overlap", "missing_key"])
def test_malformed_structure_is_insufficient_without_crashing(damage):
    from gaworld.research.interaction_checks import attach

    r = measured()
    if damage == "missing_run":
        r["interaction_run"] = None
    elif damage == "overlap":
        r["interaction_run"]["groups"][1]["members"].append(r["interaction_run"]["groups"][0]["members"][0])
    else:
        del r["interaction_run"]["rounds"][0]["responses"][0]["agent_id"]
    attach(r["comparison"], r["spec"], r["responses"], r["interaction_run"])
    assert check(r)["status"] == "insufficient"
