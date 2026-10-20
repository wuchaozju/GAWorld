import copy
import importlib.util
import json

import pytest


def module():
    name = "gaworld.research.organization_intelligence"
    assert importlib.util.find_spec(name) is not None, "organization intelligence template is missing"
    from gaworld.research.organization_intelligence import experiment, protocol

    return experiment, protocol


def residents():
    return [{"id": i, "name": f"person-{i}", "age": 30, "job": "居民"} for i in range(1, 10)]


def fake(prompt):
    return json.dumps({"choice": 0, "message": "记录收到的观察；核对后选择。"}, ensure_ascii=False)


def test_template_budget_and_frozen_inputs():
    _, p = module()
    source = residents()
    spec = p.freeze({"repeats": 3, "seed": 42}, source, {"name": "test", "model": "fixture"})
    assert spec["budget"]["requests"] == 327
    assert len(spec["blocks"]) == 3
    assert spec == p.freeze({"repeats": 3, "seed": 42}, source, {"name": "test", "model": "fixture"})
    source[0]["name"] = "changed"
    assert "changed" not in json.dumps(spec)
    for block in spec["blocks"]:
        assert len({r["id"] for r in block["incumbents"] + block["replacements"]}) == 6
        assert len({t["id"] for t in block["tasks"]}) == 6


@pytest.mark.parametrize("payload", [{"repeats": 0}, {"repeats": True}, {"seed": -1}, {"repeats": 101}])
def test_invalid_protocol_rejected(payload):
    _, p = module()
    with pytest.raises(ValueError):
        p.freeze(payload, residents(), {"name": "test"})


def test_too_few_people_rejected_without_silent_resampling():
    _, p = module()
    with pytest.raises(ValueError):
        p.freeze({}, residents()[:5], {"name": "test"})


def test_visible_task_never_exposes_weights_or_other_roles():
    e, p = module()
    spec = p.freeze({}, residents(), {"name": "test"})
    task = spec["blocks"][0]["tasks"][0]
    view = e.observation(task, 1)
    assert set(view) == {"task_id", "role", "attribute", "plans"}
    assert view["attribute"] == "道路"
    assert view["plans"] == [
        {"plan_id": i, "attributes": {"道路": row[1]}} for i, row in enumerate(task["options"])
    ]
    assert "weights" not in json.dumps(view)


def test_every_plan_and_feedback_value_is_explicitly_identified():
    e, p = module()
    spec = p.freeze({"repeats": 1}, residents(), {"name": "test"})
    events = []
    e.run(spec, fake, events.append)
    for event in events:
        context = event["request"]["context"]
        if event["request"]["phase"] != "archive":
            assert [row["plan_id"] for row in context["observation"]["plans"]] == [0, 1, 2, 3]
            expected = (
                set(e.ATTRIBUTES)
                if event["request"]["arm"] == "pooled"
                else {context["observation"]["attribute"]}
            )
            assert all(set(row["attributes"]) == expected for row in context["observation"]["plans"])
        for experience in context["personal_history"]:
            assert [row["plan_id"] for row in experience["feedback"]["plan_utilities"]] == [0, 1, 2, 3]
        for message in context.get("received_messages", []):
            assert set(message) == {"task_id", "sender_role", "source", "answer"}
            assert message["task_id"] == context["observation"]["task_id"]


def test_choice_is_plan_identifier_without_ordinal_conversion():
    e, p = module()
    spec = p.freeze({"repeats": 1}, residents(), {"name": "test"})
    result = e.run(spec, lambda prompt: '{"choice":2,"message":"编号2"}', lambda event: None)
    for row in result["rows"]:
        assert row["choice"] == 2
        assert row["utility"] == spec["blocks"][row["block"]]["tasks"][row["task_index"]]["utilities"][2]


def test_complete_run_exact_calls_and_turnover_boundaries():
    e, p = module()
    spec = p.freeze({"repeats": 1}, residents(), {"name": "test"})
    calls = []
    result = e.run(spec, fake, lambda event: calls.append(copy.deepcopy(event)))
    assert len(calls) == spec["budget"]["requests"] == 109
    assert len(result["rows"]) == 27
    assert result["analysis"]["complete"]
    requests = [c["request"] for c in calls]
    fresh = [r for r in requests if r["arm"] == "replacement_no_archive"]
    assert fresh and all(r["context"]["personal_history"] == [] for r in fresh)
    assert all(r["context"]["archive"] == "" for r in fresh)
    old = [r for r in requests if r["arm"] == "incumbent_no_archive"]
    assert all(r["context"]["archive"] == "" for r in old)
    assert any(r["context"]["personal_history"] for r in old)
    for r in requests:
        if r["phase"] == "test":
            assert "feedback" not in r["context"]["observation"]


def test_parse_failure_is_preserved_and_never_scored_as_zero():
    e, p = module()
    spec = p.freeze({"repeats": 1}, residents(), {"name": "test"})
    calls = []
    with pytest.raises(ValueError):
        e.run(spec, lambda prompt: '{"choice":99}', calls.append)
    assert calls[0]["status"] == "parse_error"
    assert calls[0]["raw"] == '{"choice":99}'


def test_incomplete_results_do_not_support_comparison():
    module()
    from gaworld.research.organization_intelligence.analysis import evaluate

    assert evaluate([], 3)["contrasts"] == []
    assert not evaluate([], 3)["complete"]


def test_maximum_valid_messages_fit_registered_prompt_budget():
    e, p = module()
    people = residents()
    for person in people:
        person["job"] = "职" * 500
    spec = p.freeze({"repeats": 1}, people, {"name": "test"})
    answer = json.dumps({"choice": 0, "message": "字" * 1800}, ensure_ascii=False)
    result = e.run(spec, lambda prompt: answer, lambda event: None)
    assert result["analysis"]["complete"]
