import importlib.util
import json

import pytest


def modules():
    assert importlib.util.find_spec("gaworld.collaboration.organization_methods"), (
        "organization rules missing"
    )
    from gaworld.collaboration import organization_engine, organization_methods

    return organization_methods, organization_engine


def members(n=3):
    return [{"id": i + 11, "name": f"m{i}"} for i in range(n)]


def test_rules_reject_unsupported_and_hash_is_stable():
    methods, _ = modules()
    a = methods.baseline("random", 3)
    assert methods.method_hash(a) == methods.method_hash(methods.normalize_method(a))
    with pytest.raises(ValueError, match="支持"):
        methods.normalize_method({**a, "unsupported": ["telepathy"]})
    with pytest.raises(ValueError):
        methods.normalize_method({**a, "rounds": 100000})


def test_random_graph_reproducible_and_no_self_edges():
    methods, engine = modules()
    m = methods.baseline("random", 5)
    assert engine.edges(m, 29) == engine.edges(m, 29)
    assert all(a != b for a, b in engine.edges(m, 29))
    assert engine.edges(methods.baseline("independent", 3), 29) == []


def test_independent_messages_never_enter_other_member_context():
    methods, engine = modules()
    prompts = []

    def llm(prompt, **kw):
        prompts.append(json.loads(prompt))
        return json.dumps({"answer": "A", "message": f"SECRET-{kw['agent_id']}"})

    result = engine.run_method(
        methods.baseline("independent", 3),
        members(),
        {"id": "q", "prompt": "choose", "options": ["A", "B"]},
        llm,
    )
    assert result["answer"]["answer"] == "A"
    assert all(not p["messages"] for p in prompts)
    assert result["metrics"]["calls"] == len(prompts)


def test_custom_graph_only_previous_round_sender_is_visible():
    methods, engine = modules()
    m = methods.normalize_method(
        {**methods.baseline("full", 3), "topology": {"kind": "custom", "edges": [[0, 1]]}, "rounds": 1}
    )
    prompts = []

    def llm(prompt, **kw):
        p = json.loads(prompt)
        prompts.append(p)
        return json.dumps({"answer": "B", "message": f"FROM-{kw['agent_id']}"})

    engine.run_method(m, members(), {"id": "q", "prompt": "choose"}, llm)
    turns = [p for p in prompts if p["phase"] == "communicate"]
    assert turns[0]["messages"] == []
    assert [x["sender"] for x in turns[1]["messages"]] == [11]
    assert turns[2]["messages"] == []


def test_resume_reuses_completed_calls_without_replaying_llm():
    methods, engine = modules()
    state = {}
    count = []

    def llm(prompt, **kw):
        count.append(kw)
        return '{"answer":"A"}'

    m = methods.baseline("full", 3)
    a = engine.run_method(m, members(), {"prompt": "choose"}, llm, state=state)
    b = engine.run_method(m, members(), {"prompt": "choose"}, llm, state=state)
    assert a["answer"] == b["answer"]
    assert len(count) == a["metrics"]["calls"]
    with pytest.raises(ValueError, match="恢复"):
        engine.run_method(m, members(), {"prompt": "different"}, llm, state=state)


def test_limits_checked_before_calls_and_hidden_data_rejected():
    methods, engine = modules()
    count = []

    def llm(prompt, **kw):
        count.append(prompt)
        return '{"answer":"A"}'

    m = methods.baseline("full", 3)
    with pytest.raises(engine.BudgetExceeded):
        engine.run_method(m, members(), {"prompt": "q"}, llm, limits={"calls": 1})
    assert len(count) == 1
    with pytest.raises(ValueError, match="评分"):
        engine.run_method(m, members(), {"prompt": "q", "reference": "HIDDEN"}, llm)


def test_failed_attempts_consume_budget_and_remain_durable():
    methods, engine = modules()
    state = {}

    def broken(prompt, **kwargs):
        raise ConnectionError("network down")

    m = methods.baseline("full", 3)
    with pytest.raises(ConnectionError):
        engine.run_method(m, members(), {"prompt": "q"}, broken, limits={"calls": 1}, state=state)
    assert state["attempts"][0]["status"] == "failed"
    with pytest.raises(engine.BudgetExceeded):
        engine.run_method(m, members(), {"prompt": "q"}, broken, limits={"calls": 1}, state=state)


def test_rule_versions_booleans_and_limit_names_are_strict():
    methods, engine = modules()
    m = methods.baseline("full", 3)
    for change in ({"version": "future"}, {"review": "false"}, {"review": False, "revisions": 1}):
        with pytest.raises(ValueError):
            methods.normalize_method({**m, **change})
    with pytest.raises(ValueError):
        engine.run_method(m, members(), {"prompt": "q"}, lambda *a, **k: "{}", limits={"unknown": 1})
