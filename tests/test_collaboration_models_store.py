import json
import threading

from gaworld.collaboration.models import CollaborationSession, SessionStatus
from gaworld.collaboration.store import SessionStore


def test_session_round_trip_preserves_public_fields():
    session = CollaborationSession.new(
        kind="discussion",
        member_ids=[3, 1],
        topic="城市公共空间",
        max_rounds=6,
    )
    restored = CollaborationSession.from_dict(session.to_dict())
    assert restored.id == session.id
    assert restored.kind == "discussion"
    assert restored.member_ids == [3, 1]
    assert restored.status is SessionStatus.QUEUED
    assert restored.max_rounds == 6


def test_transition_table_rejects_completed_to_running():
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    session.transition(SessionStatus.RUNNING)
    session.transition(SessionStatus.COMPLETED)
    try:
        session.transition(SessionStatus.RUNNING)
    except ValueError as exc:
        assert "completed" in str(exc)
    else:
        raise AssertionError("terminal session accepted an invalid transition")


def test_store_persists_snapshot_and_incremental_events(tmp_path):
    store = SessionStore(tmp_path)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    store.create(session)
    first = store.append_event(session.id, "message", "你好", agent_id=1)
    second = store.append_event(session.id, "message", "你好呀", agent_id=2)

    assert SessionStore(tmp_path).get(session.id).member_ids == [1, 2]
    assert first.seq == 1
    assert second.seq == 2
    assert [event.seq for event in store.events(session.id, after=1)] == [2]


def test_session_guard_serializes_status_check_and_event_append(tmp_path):
    store = SessionStore(tmp_path)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    session.transition(SessionStatus.RUNNING)
    store.create(session)
    paused = store.get(session.id)
    paused.transition(SessionStatus.PAUSED)
    guard_entered = threading.Event()
    save_started = threading.Event()
    save_finished = threading.Event()

    def guarded_append():
        with store.session_guard(session.id):
            assert store.get(session.id).status is SessionStatus.RUNNING
            guard_entered.set()
            assert save_started.wait(1)
            assert not save_finished.wait(0.05)
            store.append_event(session.id, "message", "guarded")

    def save_pause():
        assert guard_entered.wait(1)
        save_started.set()
        store.save(paused)
        save_finished.set()

    guarded_thread = threading.Thread(target=guarded_append)
    pause_thread = threading.Thread(target=save_pause)
    guarded_thread.start()
    pause_thread.start()
    guarded_thread.join(timeout=2)
    pause_thread.join(timeout=2)

    assert not guarded_thread.is_alive()
    assert not pause_thread.is_alive()
    assert save_finished.is_set()
    assert [event.content for event in store.events(session.id)] == ["guarded"]
    assert store.get(session.id).status is SessionStatus.PAUSED


def test_recovery_marks_running_sessions_interrupted(tmp_path):
    store = SessionStore(tmp_path)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    session.transition(SessionStatus.RUNNING)
    store.create(session)

    recovered = SessionStore(tmp_path).recover_interrupted()

    assert recovered == [session.id]
    assert store.get(session.id).status is SessionStatus.INTERRUPTED


def test_recovery_continues_after_malformed_event_log(tmp_path):
    store = SessionStore(tmp_path)
    healthy = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    store.create(healthy)
    healthy.transition(SessionStatus.RUNNING)
    store.save(healthy)
    broken = CollaborationSession.new(kind="discussion", member_ids=[3, 4])
    store.create(broken)
    broken.transition(SessionStatus.RUNNING)
    store.save(broken)
    (tmp_path / broken.id / "events.jsonl").write_text("{bad json\n", encoding="utf-8")

    recovered = store.recover_interrupted()

    assert recovered == [broken.id, healthy.id]
    assert store.get(broken.id).status is SessionStatus.INTERRUPTED
    assert store.get(healthy.id).status is SessionStatus.INTERRUPTED


def test_artifact_path_rejects_traversal(tmp_path):
    store = SessionStore(tmp_path)
    session = CollaborationSession.new(kind="cooperation", member_ids=[1, 2])
    store.create(session)
    try:
        store.write_artifact(session.id, "../secret.txt", "bad", agent_id=1)
    except ValueError as exc:
        assert "artifact" in str(exc)
    else:
        raise AssertionError("unsafe artifact path was accepted")


def test_event_sink_receives_persisted_event(tmp_path):
    seen = []
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])

    def sink(event):
        persisted = [
            json.loads(line)
            for line in (tmp_path / session.id / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert persisted[-1] == event
        seen.append(event)

    store = SessionStore(tmp_path, event_sink=sink)
    store.create(session)
    store.append_event(session.id, "created", "讨论")
    assert seen == [
        {
            "seq": 1,
            "type": "created",
            "timestamp": seen[0]["timestamp"],
            "content": "讨论",
            "agent_id": None,
            "metadata": {},
        }
    ]


def test_malformed_session_is_skipped_and_reported(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "session.json").write_text("{bad json", encoding="utf-8")
    store = SessionStore(tmp_path)
    assert store.list() == []
    assert store.health()["malformed_sessions"] == ["broken"]


def test_orphan_session_directory_is_reported_as_malformed(tmp_path):
    (tmp_path / "orphan").mkdir()

    store = SessionStore(tmp_path)

    assert store.list() == []
    assert store.health()["malformed_sessions"] == ["orphan"]
