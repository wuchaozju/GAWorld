from __future__ import annotations

import threading
import time

import pytest

from gaworld.collaboration.models import CollaborationSession, SessionStatus
from gaworld.collaboration.plugin import CollaborationPlugin
from gaworld.collaboration.service import CollaborationService
from gaworld.kernel import build_kernel
from gaworld.plugins import builtin_plugins


def _agents() -> dict[int, dict]:
    return {
        1: {"id": 1, "name": "甲", "identity": {"id": 1, "name": "甲"}},
        2: {"id": 2, "name": "乙", "identity": {"id": 2, "name": "乙"}},
    }


def _service(tmp_path, **overrides) -> CollaborationService:
    agents = _agents()
    values = {
        "config": {
            "discussion": {"min_rounds": 3, "max_rounds": 20},
            "step_retries": 0,
        },
        "sessions_dir": tmp_path / "sessions",
        "memory_dir": tmp_path / "memory",
        "agent_loader": agents.get,
        "llm": lambda *args, **kwargs: '{"content":"同意","converged":true}',
        "background": False,
    }
    values.update(overrides)
    return CollaborationService(**values)


def test_service_validates_and_creates_non_background_discussion(tmp_path):
    service = _service(tmp_path)

    created = service.create_discussion([1, 2], topic="", max_rounds=6)

    assert created.kind == "discussion"
    assert created.status is SessionStatus.QUEUED
    assert service.get_session(created.id)["member_ids"] == [1, 2]
    assert service._executor is None
    assert service._futures == {}


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ([1], "at least two"),
        ([1, 0], "positive"),
        ([1, 3], "not found"),
    ],
)
def test_service_rejects_invalid_members(tmp_path, members, message):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match=message):
        service.create_discussion(members, topic="", max_rounds=6)

    assert service.list_sessions() == []


def test_service_rejects_invalid_session_options(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="between 3 and 20"):
        service.create_discussion([1, 2], topic="", max_rounds=2)
    with pytest.raises(ValueError, match="task is required"):
        service.create_cooperation([1, 2], task=" ")
    with pytest.raises(ValueError, match="leader"):
        service.create_cooperation([1, 2], task="研究", leader_id=3)


def test_start_recovers_running_session_without_automatically_resuming(tmp_path):
    service = _service(tmp_path, background=True)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2], max_rounds=3)
    session.transition(SessionStatus.RUNNING)
    service.store.create(session)

    service.start()

    assert service.store.get(session.id).status is SessionStatus.INTERRUPTED
    assert service._futures == {}
    assert [event.type for event in service.store.events(session.id)] == ["interrupted"]
    service.shutdown()


def test_submit_does_not_create_duplicate_live_future(tmp_path):
    service = _service(tmp_path, background=True)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2], max_rounds=3)
    service.store.create(session)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def blocking_run(session_id):
        calls.append(session_id)
        entered.set()
        assert release.wait(timeout=5)

    service.run_session = blocking_run
    service.start()
    service._submit(session.id)
    assert entered.wait(timeout=5)

    service._submit(session.id)

    assert calls == [session.id]
    assert list(service._futures) == [session.id]
    release.set()
    service._futures[session.id].result(timeout=5)
    service.shutdown()


def test_pause_holds_session_guard_across_read_transition_and_write(tmp_path):
    service = _service(tmp_path)
    session = service.create_discussion([1, 2], topic="", max_rounds=3)
    session.transition(SessionStatus.RUNNING)
    service.store.save(session)
    original_get = service.store.get
    pause_read = threading.Event()
    allow_pause = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    pause_thread_id = None

    def gated_get(session_id):
        loaded = original_get(session_id)
        if threading.get_ident() == pause_thread_id and not pause_read.is_set():
            pause_read.set()
            assert allow_pause.wait(timeout=5)
        return loaded

    service.store.get = gated_get
    pause_errors = []

    def pause():
        nonlocal pause_thread_id
        pause_thread_id = threading.get_ident()
        try:
            service.pause(session.id)
        except Exception as exc:  # pragma: no cover - assertion reports the exception
            pause_errors.append(exc)

    def competing_writer():
        writer_started.set()
        with service.store.session_guard(session.id):
            writer_done.set()

    pause_thread = threading.Thread(target=pause)
    pause_thread.start()
    assert pause_read.wait(timeout=5)
    writer_thread = threading.Thread(target=competing_writer)
    writer_thread.start()

    assert writer_started.wait(timeout=5)
    assert not writer_done.wait(timeout=0.1)
    allow_pause.set()
    pause_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    assert not pause_thread.is_alive()
    assert not writer_thread.is_alive()
    assert pause_errors == []
    assert original_get(session.id).status is SessionStatus.PAUSED
    assert [event.type for event in service.store.events(session.id)][-1] == "paused"


def test_resume_and_cancel_are_persisted_transitions(tmp_path):
    service = _service(tmp_path)
    session = service.create_discussion([1, 2], topic="", max_rounds=3)
    session.transition(SessionStatus.RUNNING)
    service.store.save(session)

    service.pause(session.id)
    resumed = service.resume(session.id)
    cancelled = service.cancel(session.id)

    assert resumed["status"] == "running"
    assert cancelled["status"] == "cancelled"
    assert service.store.get(session.id).status is SessionStatus.CANCELLED
    assert [event.type for event in service.store.events(session.id)][-3:] == [
        "paused",
        "resumed",
        "cancelled",
    ]
    assert service._futures == {}


def test_non_background_session_runs_only_when_called_explicitly(tmp_path):
    service = _service(tmp_path)
    session = service.create_discussion([1, 2], topic="测试", max_rounds=3)
    assert service.store.get(session.id).status is SessionStatus.QUEUED

    service.run_session(session.id)

    assert service.store.get(session.id).status is SessionStatus.COMPLETED
    assert service._executor is None


def test_event_sink_receives_persisted_events(tmp_path):
    emitted = []
    service = _service(tmp_path, event_sink=emitted.append)

    session = service.create_discussion([1, 2], topic="事件", max_rounds=3)

    assert emitted == [
        {
            "seq": 1,
            "type": "created",
            "timestamp": emitted[0]["timestamp"],
            "content": "事件",
            "agent_id": None,
            "metadata": {},
        }
    ]
    assert service.events(session.id)[0]["type"] == "created"


def test_missing_llm_marks_explicit_run_failed(tmp_path):
    service = _service(tmp_path, llm=None)
    session = service.create_discussion([1, 2], topic="", max_rounds=3)

    service.run_session(session.id)

    persisted = service.store.get(session.id)
    assert persisted.status is SessionStatus.FAILED
    assert "LLM" in persisted.error
    assert service.events(session.id)[-1]["type"] == "error"


def test_shutdown_is_idempotent_and_releases_executor(tmp_path):
    service = _service(tmp_path, background=True)
    service.start()
    executor = service._executor

    service.shutdown()
    service.shutdown()

    assert executor is not None
    assert service._executor is None
    assert service._started is False


def test_shutdown_waits_for_running_work_and_cancels_queued_dispatches(tmp_path):
    service = _service(
        tmp_path,
        background=True,
        config={
            "discussion": {"min_rounds": 3, "max_rounds": 20},
            "max_concurrent_sessions": 1,
        },
    )
    sessions = [
        CollaborationSession.new(
            kind="discussion",
            member_ids=[1, 2],
            max_rounds=3,
        )
        for _ in range(3)
    ]
    for session in sessions:
        service.store.create(session)
    entered = threading.Event()
    release = threading.Event()
    shutdown_returned = threading.Event()
    calls = []

    def blocking_run(session_id):
        calls.append(session_id)
        entered.set()
        assert release.wait(timeout=5)

    service.run_session = blocking_run
    service.start()
    service._submit(sessions[0].id)
    service._submit(sessions[1].id)
    assert entered.wait(timeout=5)
    queued_future = service._futures[sessions[1].id]

    shutdown_thread = threading.Thread(
        target=lambda: (service.shutdown(), shutdown_returned.set())
    )
    shutdown_thread.start()
    deadline = time.monotonic() + 5
    while service._executor is not None and time.monotonic() < deadline:
        time.sleep(0.001)

    try:
        assert service._executor is None
        assert not shutdown_returned.wait(timeout=0.1)
        with pytest.raises(RuntimeError, match="shutting down"):
            service._submit(sessions[2].id)
        assert queued_future.cancelled()
    finally:
        release.set()
        shutdown_thread.join(timeout=5)

    assert not shutdown_thread.is_alive()
    assert shutdown_returned.is_set()
    assert calls == [sessions[0].id]
    assert service.store.get(sessions[1].id).status is SessionStatus.CANCELLED
    assert service.store.events(sessions[1].id)[-1].type == "cancelled"


def test_unsupported_persisted_kind_is_durably_failed(tmp_path):
    service = _service(tmp_path, background=True)
    session = CollaborationSession.new(
        kind="unsupported",
        member_ids=[1, 2],
    )
    service.store.create(session)

    service.start()
    service._submit(session.id)
    service._futures[session.id].result(timeout=5)

    persisted = service.store.get(session.id)
    assert persisted.status is SessionStatus.FAILED
    assert "unsupported session kind" in persisted.error
    error = service.store.events(session.id)[-1]
    assert error.type == "error"
    assert "unsupported session kind" in error.content
    service.shutdown()


def test_unsupported_kind_preserves_an_already_failed_session(tmp_path):
    service = _service(tmp_path)
    session = CollaborationSession.new(
        kind="unsupported",
        member_ids=[1, 2],
    )
    session.transition(SessionStatus.RUNNING)
    session.transition(SessionStatus.FAILED)
    session.error = "unsupported session kind: unsupported"
    service.store.create(session)
    service.store.append_event(session.id, "error", session.error)

    service.run_session(session.id)

    persisted = service.store.get(session.id)
    assert persisted.status is SessionStatus.FAILED
    assert persisted.error == "unsupported session kind: unsupported"
    assert [
        event.type
        for event in service.store.events(session.id)
        if event.type == "error"
    ] == ["error"]


def test_plugin_starts_and_stops_runtime(tmp_path):
    ctx = build_kernel(
        {
            "collaboration": {
                "enabled": True,
                "sessions_dir": str(tmp_path / "sessions"),
            },
            "memory_dir": str(tmp_path / "memory"),
        },
        llm=lambda *args, **kwargs: "",
        load_entry_points=False,
    )
    ctx.set_agents([{"id": 1, "name": "甲"}, {"id": 2, "name": "乙"}])
    plugin = CollaborationPlugin()
    plugin.setup(ctx)

    ctx.bus.emit("on_simulation_start", agents=ctx.agents)

    assert ctx.plugin_state("collaboration")["service"] is not None
    plugin.teardown(ctx)
    assert "service" not in ctx.plugin_state("collaboration")


def test_plugin_merges_persisted_friend_edges_into_runtime_neighbors(tmp_path):
    ctx = build_kernel(
        {
            "collaboration": {
                "enabled": True,
                "sessions_dir": str(tmp_path / "sessions"),
            },
            "memory_dir": str(tmp_path / "memory"),
        },
        llm=lambda *args, **kwargs: "",
        load_entry_points=False,
    )
    agents = [
        {
            "id": 1,
            "name": "甲",
            "social_neighbors": [],
            "relationships": {"2": {"kind": "agent", "role": "friend"}},
        },
        {"id": 2, "name": "乙", "social_neighbors": [], "relationships": {}},
    ]
    ctx.set_agents(agents)
    plugin = CollaborationPlugin()
    plugin.setup(ctx)

    ctx.bus.emit("on_simulation_start", agents=agents)

    assert agents[0]["social_neighbors"] == [2]
    assert agents[1]["social_neighbors"] == [1]
    plugin.teardown(ctx)


def test_disabled_plugin_does_not_start_or_merge_edges(tmp_path):
    ctx = build_kernel(
        {
            "collaboration": {
                "enabled": False,
                "sessions_dir": str(tmp_path / "sessions"),
            },
            "memory_dir": str(tmp_path / "memory"),
        },
        load_entry_points=False,
    )
    agents = [
        {
            "id": 1,
            "social_neighbors": [],
            "relationships": {"2": {"kind": "agent", "role": "friend"}},
        },
        {"id": 2, "social_neighbors": [], "relationships": {}},
    ]
    ctx.set_agents(agents)
    plugin = CollaborationPlugin()
    plugin.setup(ctx)

    ctx.bus.emit("on_simulation_start", agents=agents)

    assert ctx.plugin_state("collaboration")["service"] is None
    assert agents[0]["social_neighbors"] == []
    assert agents[1]["social_neighbors"] == []
    assert not (tmp_path / "sessions").exists()
    plugin.teardown(ctx)
    assert "service" not in ctx.plugin_state("collaboration")


def test_collaboration_is_registered_as_builtin():
    assert "collaboration" in [plugin.id for plugin in builtin_plugins()]
