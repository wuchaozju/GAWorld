import json

import pytest

from gaworld.research import replication as rp


def spec():
    return {
        "items": [
            {"id": "Q1", "kind": "number", "text": "评分", "min": 0, "max": 10, "sampling_margin": 0.5},
            {"id": "Q2", "kind": "choice", "text": "选择", "options": ["甲", "乙"]},
        ],
        "results": [{"item": "Q1", "mean": 5, "sd": 1, "n": 100}],
        "bias_checks": {"order": True},
        "sampling_probe": {"enabled": True, "repeats": 3},
    }


def run(s=None, answer=None):
    return rp.run_replication(
        spec=s or spec(),
        answer=answer or (lambda _: json.dumps({"Q1": 5, "Q2": 1})),
        population=[{"id": i, "age": 30} for i in range(8)],
        profile_fn=lambda *_: "固定档案",
        seed=123,
        sample_size=8,
        workers=1,
    )


def card(r, index=0):
    return next(
        c for c in r["comparison"]["cells"][index]["result_checks"]["checks"] if c["id"] == "sampling"
    )


def test_budget_records_and_default_off():
    calls = []
    r = run(answer=lambda p: calls.append(p) or '{"Q1":5,"Q2":1}')
    assert len(calls) == r["check_protocol"]["planned_calls"] == 64
    assert len(r["responses"][0]["sampling"]) == 6
    assert card(r)["status"] == "insufficient"
    assert card(r, 1)["status"] == "observed"
    s = spec()
    s["sampling_probe"]["enabled"] = False
    calls.clear()
    run(s, lambda p: calls.append(p) or '{"Q1":5}')
    assert len(calls) == 16


@pytest.mark.parametrize("repeats", [0, 1, 6, True, 2.5])
def test_invalid_repetitions_preflight(repeats):
    s = spec()
    s["sampling_probe"]["repeats"] = repeats
    with pytest.raises(ValueError, match="重复"):
        run(s)


def test_resident_means_not_draws_and_missing_blocks_stability():
    from gaworld.research import sampling_checks as sc

    r = run()
    for response in r["responses"]:
        for record in response["sampling"]:
            record["answers"]["Q1"] = 5 + (
                1 + response["agent_id"] * 0.05 if record["variant"] == "order" else 0
            )
    sc.attach(r["comparison"], r["spec"], r["responses"])
    c = card(r)["evidence"]["contrasts"]["order"]
    assert c["status"] == "detected"
    assert c["evidence"]["components"][0][1] == 8
    assert c["evidence"]["difference"] == pytest.approx(1.175)
    r["spec"]["items"][0]["sampling_margin"] = 3
    r["responses"][0]["sampling"][0]["answers"] = {}
    sc.attach(r["comparison"], r["spec"], r["responses"])
    assert card(r)["evidence"]["contrasts"]["order"]["status"] == "insufficient"
    assert card(r)["evidence"]["contrasts"]["order"]["evidence"]["missing"] == 1
    r["responses"][1]["sampling"].append(r["responses"][1]["sampling"][0])
    sc.attach(r["comparison"], r["spec"], r["responses"])
    assert card(r)["status"] == "insufficient"


def test_prompt_hashes_canonical_labels_and_shuffled_draw_order():
    r = run()
    orders = []
    for response in r["responses"]:
        draws = response["sampling"]
        orders.append([(v["variant"], v["repetition"]) for v in draws])
        assert len({v["prompt_hash"] for v in draws}) == 2
        assert all(v["answers"]["Q2"] == (0 if v["variant"] == "main" else 1) for v in draws)
    assert len({str(order) for order in orders}) > 1
    again = run()
    assert orders == [[(v["variant"], v["repetition"]) for v in x["sampling"]] for x in again["responses"]]


def test_failed_extra_draws_retained_and_no_change_to_original_answers():
    calls = [0]

    def answer(prompt):
        calls[0] += 1
        if calls[0] % 8 > 2 or calls[0] % 8 == 0:
            raise TimeoutError("fixture")
        return '{"Q1":5,"Q2":1}'

    r = run(answer=answer)
    assert calls[0] == 64
    assert all(v["answers"]["Q1"] == 5 for v in r["responses"])
    assert all("TimeoutError" in v["error"] for r in r["responses"] for v in r["sampling"])
    assert card(r)["evidence"]["contrasts"]["order"]["evidence"]["missing"] == 8


@pytest.mark.parametrize("damage", [None, "bad", True, float("nan"), 99])
def test_corrupt_record_cannot_crash_or_support_equivalence(damage):
    from gaworld.research import sampling_checks as sc

    r = run()
    r["spec"]["items"][0]["sampling_margin"] = 3
    if damage is None:
        r["responses"][0]["sampling"][0] = None
    else:
        r["responses"][0]["sampling"][0]["answers"]["Q1"] = damage
    sc.attach(r["comparison"], r["spec"], r["responses"])
    assert card(r)["status"] == "insufficient"
