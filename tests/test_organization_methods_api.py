"""The cooperation picker lists built-in structures and the saved ones."""

import importlib.util

import pytest

from gaworld.collaboration.organization_methods import (
    KINDS,
    baseline,
    builtin_id,
    builtin_method,
    method_hash,
    parse_builtin,
    topology_text,
)
from gaworld.collaboration.service import CollaborationService


@pytest.fixture
def env(tmp_path, monkeypatch):
    assert importlib.util.find_spec("gaworld.apps.organization_methods_api"), "methods API missing"
    from gaworld.apps import organization_methods_api as methods
    from gaworld.research.organization_intelligence.comparison.store import Store

    monkeypatch.setattr(methods, "database", lambda: Store(tmp_path / "methods"))
    return methods


def save(env, kind="full", slots=3):
    method = baseline(kind, slots)
    record, status = env.handle_post(env.PREFIX, {"method": method})
    assert status == 201, record
    return record


def test_saved_methods_are_listed_without_the_builtins(env):
    save(env)
    methods, status = env.handle_get(env.PREFIX)
    assert status == 200
    assert [m["builtin"] for m in methods["methods"]] == [False]


def test_builtins_are_listed_when_the_caller_asks_for_them(env):
    saved = save(env)
    methods, status = env.handle_get(env.PREFIX, {"include": "builtin"})
    assert status == 200
    listed = methods["methods"]
    builtins = [m for m in listed if m["builtin"]]
    assert [m["id"] for m in builtins] == [builtin_id(kind) for kind in KINDS]
    assert [m["name"] for m in builtins] == list(KINDS.values())
    assert [m["id"] for m in listed if not m["builtin"]] == [saved["id"]]


def test_a_builtin_is_sized_by_the_team_that_runs_it(env):
    record = env.resolve(builtin_id("hierarchy"), 1, slots=3)
    assert record["method"]["roles"] == ["成员 1", "成员 2", "成员 3"]
    assert record["method"]["topology"]["kind"] == "hierarchy"
    assert record["method_hash"] == method_hash(record["method"])
    assert record["description"] == topology_text("hierarchy")
    assert record["evidence"]["verdict"] == "builtin"


def test_a_builtin_needs_a_version_and_a_team(env):
    with pytest.raises(ValueError, match="版本"):
        env.resolve(builtin_id("full"), 2, slots=3)
    with pytest.raises(ValueError, match="成员"):
        env.resolve(builtin_id("full"), 1, slots=1)
    with pytest.raises(ValueError, match="成员"):
        env.resolve(builtin_id("full"), 1, slots=None)


def test_builtin_ids_are_recognised_and_saved_ids_are_not():
    assert parse_builtin("builtin:hierarchy") == "hierarchy"
    assert parse_builtin("builtin:nope") is None
    assert parse_builtin("M" + "a" * 24) is None


def test_the_dashboard_resolves_a_builtin_with_the_team_size():
    from gaworld.apps import dashboard_server

    record = dashboard_server._organization_method(builtin_id("full"), 1, slots=4)
    assert len(record["method"]["roles"]) == 4
    assert record["method"]["topology"]["kind"] == "full"


def test_a_cooperation_task_runs_a_builtin_structure(tmp_path):
    method = builtin_method("independent", 2)
    svc = CollaborationService(
        config={},
        sessions_dir=tmp_path / "sessions",
        memory_dir=tmp_path / "memory",
        agent_loader=lambda i: {"id": i, "name": f"m{i}"},
        llm=lambda *a, **k: '{"answer":"done"}',
        background=False,
    )
    session = svc.create_cooperation(
        [1, 2],
        task="prepare report",
        organization_method={
            "id": builtin_id("independent"),
            "version": 1,
            "method": method,
            "method_hash": method_hash(method),
        },
    )
    svc.run_session(session.id)
    result = svc.get_session(session.id)
    assert result["status"] == "completed"
    assert result["organization_method"]["method"]["roles"] == ["成员 1", "成员 2"]
    assert result["organization_method"]["method"]["topology"]["kind"] == "independent"
