import json

import pytest

from gaworld.collaboration.organization_methods import baseline, method_hash
from gaworld.collaboration.service import CollaborationService


def service(tmp_path, llm):
    return CollaborationService(
        config={},
        sessions_dir=tmp_path / "sessions",
        memory_dir=tmp_path / "memory",
        agent_loader=lambda i: {"id": i, "name": f"m{i}"},
        llm=llm,
        background=False,
    )


def snapshot():
    method = baseline("independent", 2)
    return {"id": "M" + "a" * 24, "version": 1, "method": method, "method_hash": method_hash(method)}


def test_cooperation_uses_same_method_and_keeps_immutable_snapshot(tmp_path):
    calls = []

    def llm(prompt, **kwargs):
        calls.append(json.loads(prompt))
        return '{"answer":"a complete deliverable"}'

    svc = service(tmp_path, llm)
    chosen = snapshot()
    session = svc.create_cooperation([1, 2], task="prepare report", organization_method=chosen)
    chosen["method"]["name"] = "changed outside"
    svc.run_session(session.id)
    result = svc.get_session(session.id)
    assert result["status"] == "completed"
    assert result["organization_method"]["method"]["name"] == "独立作答后汇总"
    assert result["organization_method"]["method_hash"] == snapshot()["method_hash"]
    assert all(not c["messages"] for c in calls if c["phase"] == "private")
    assert result["artifacts"][0]["filename"] == "final.md"


def test_incompatible_member_slots_rejected_before_start(tmp_path):
    svc = service(tmp_path, lambda *a, **k: "{}")
    with pytest.raises(ValueError, match="人数"):
        svc.create_cooperation([1, 2, 3], task="report", organization_method=snapshot())


def test_pause_resume_does_not_duplicate_method_calls(tmp_path):
    calls = []

    def llm(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            svc.pause(session.id)
        return '{"answer":"done"}'

    svc = service(tmp_path, llm)
    session = svc.create_cooperation([1, 2], task="report", organization_method=snapshot())
    svc.run_session(session.id)
    assert svc.get_session(session.id)["status"] == "paused"
    svc.resume(session.id)
    svc.run_session(session.id)
    assert svc.get_session(session.id)["status"] == "completed"
    assert len(calls) == 3


def test_dashboard_services_are_scoped_by_user_and_world(tmp_path, monkeypatch):
    from gaworld.accounts.context import USER, WORLD
    from gaworld.apps import dashboard_server as ds

    monkeypatch.setattr(ds, "_COLLABORATION_SERVICE", None)
    monkeypatch.setattr(
        ds.paths,
        "effective_config",
        lambda: {
            "collaboration": {"sessions_dir": str(tmp_path / "sessions")},
            "memory_dir": str(tmp_path / "memory"),
        },
    )
    monkeypatch.setattr(ds.paths, "world_file", lambda *p: str(tmp_path / WORLD.get()["id"] / "/".join(p)))
    u, w = USER.set({"id": "alice"}), WORLD.set({"id": "world-a"})
    try:
        a = ds._get_collaboration_service()
        t = WORLD.set({"id": "world-b"})
        try:
            b = ds._get_collaboration_service()
            assert a is not b
            assert a.store.root != b.store.root
        finally:
            WORLD.reset(t)
        assert ds._get_collaboration_service() is a
    finally:
        ds._reset_collaboration_service_for_tests()
        WORLD.reset(w)
        USER.reset(u)


def test_organized_artifact_download_is_authorized_and_cannot_escape(tmp_path, monkeypatch):
    from gaworld.apps import dashboard_server as ds
    from gaworld.apps import organization_artifacts_api as api

    svc = service(tmp_path, lambda *a, **k: '{"answer":"deliverable"}')
    session = svc.create_cooperation([1, 2], task="report", organization_method=snapshot())
    svc.run_session(session.id)
    monkeypatch.setattr(ds, "_get_collaboration_service", lambda: svc)
    result, status = api.handle_get(api.PREFIX + session.id + "/artifacts/final.md")
    assert status == 200 and result.content == b"deliverable"
    assert api.handle_get(api.PREFIX + session.id + "/artifacts/../session.json")[1] == 404
    assert api.handle_get(api.PREFIX + session.id + "/artifacts/not-listed.md")[1] == 404
    outside = tmp_path / "outside.md"
    outside.write_text("private")
    artifact = svc.store.root / session.id / "artifacts" / "final.md"
    artifact.unlink()
    artifact.symlink_to(outside)
    assert api.handle_get(api.PREFIX + session.id + "/artifacts/final.md")[1] == 404
