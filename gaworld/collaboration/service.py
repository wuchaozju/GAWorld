from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gaworld.collaboration.cooperation import CooperationRunner
from gaworld.collaboration.discussion import DiscussionRunner
from gaworld.collaboration.models import CollaborationSession, SessionStatus
from gaworld.collaboration.relationships import RelationshipService
from gaworld.collaboration.store import SessionStore


def _missing_llm(*args: Any, **kwargs: Any) -> str:
    raise RuntimeError("collaboration LLM is not configured")


class CollaborationService:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        sessions_dir: str | Path,
        memory_dir: str | Path,
        agent_loader: Callable[[int], dict[str, Any] | None],
        llm: Callable[..., str] | None,
        background: bool = True,
        episode_writer: Callable[[int, dict[str, Any]], None] | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = dict(config)
        self.store = SessionStore(sessions_dir, event_sink=event_sink)
        self.agent_loader = agent_loader
        self.llm = llm
        self.background = bool(background)
        self.relationships = RelationshipService(
            memory_dir=memory_dir,
            agent_loader=agent_loader,
        )
        runner_args: dict[str, Any] = {
            "store": self.store,
            "agent_loader": agent_loader,
            "llm": llm if llm is not None else _missing_llm,
            "episode_writer": episode_writer,
            "max_context_events": int(config.get("max_context_events", 24)),
            "step_retries": int(config.get("step_retries", 2)),
        }
        self.discussion = DiscussionRunner(
            **runner_args,
            interaction_writer=self.relationships.touch_interaction,
        )
        self.cooperation = CooperationRunner(**runner_args)
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[str, Future[None]] = {}
        self._guard = threading.RLock()
        self._started = False
        self._closing = False
        self._shutdown_complete = threading.Event()
        self._shutdown_complete.set()

    def start(self) -> None:
        with self._guard:
            if self._closing:
                raise RuntimeError("collaboration service is shutting down")
            if self._started:
                return
            self.store.recover_interrupted()
            if self.background:
                self._executor = ThreadPoolExecutor(
                    max_workers=max(
                        1,
                        int(self.config.get("max_concurrent_sessions", 2)),
                    ),
                    thread_name_prefix="gaworld_collaboration",
                )
            self._started = True

    def shutdown(self) -> None:
        with self._guard:
            if self._closing:
                shutdown_complete = self._shutdown_complete
                owns_shutdown = False
            else:
                self._closing = True
                self._shutdown_complete.clear()
                shutdown_complete = self._shutdown_complete
                owns_shutdown = True
            if not owns_shutdown:
                executor = None
                futures: list[tuple[str, Future[None]]] = []
            else:
                executor = self._executor
                futures = list(self._futures.items())
                self._executor = None
                self._started = False
        if not owns_shutdown:
            shutdown_complete.wait()
            return
        try:
            cancellation_errors: list[Exception] = []
            for session_id, future in futures:
                if future.cancel():
                    try:
                        self._cancel_queued_session(session_id)
                    except Exception as exc:
                        cancellation_errors.append(exc)
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            if cancellation_errors:
                raise RuntimeError(
                    "failed to persist queued session cancellation"
                ) from cancellation_errors[0]
        finally:
            with self._guard:
                self._closing = False
                self._shutdown_complete.set()

    def _cancel_queued_session(self, session_id: str) -> None:
        with self.store.session_guard(session_id):
            try:
                session = self.store.get(session_id)
            except KeyError:
                return
            if session.status in {
                SessionStatus.COMPLETED,
                SessionStatus.CANCELLED,
            }:
                return
            session.transition(SessionStatus.CANCELLED)
            self.store.save(session)
            self.store.append_event(
                session_id,
                "cancelled",
                "服务关闭，排队会话已终止",
            )

    def _fail_session(self, session_id: str, exc: Exception) -> None:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            if session.status in {
                SessionStatus.COMPLETED,
                SessionStatus.CANCELLED,
            }:
                return
            session.error = str(exc)[:500]
            if session.status is SessionStatus.FAILED:
                self.store.save(session)
                if not any(
                    event.type == "error"
                    and event.content == session.error
                    for event in self.store.events(session_id)
                ):
                    self.store.append_event(
                        session_id,
                        "error",
                        session.error,
                    )
                return
            if session.status is not SessionStatus.RUNNING:
                session.transition(SessionStatus.RUNNING)
            session.transition(SessionStatus.FAILED)
            self.store.save(session)
            self.store.append_event(session_id, "error", session.error)

    def _submit(self, session_id: str) -> None:
        with self._guard:
            if self._closing:
                raise RuntimeError("collaboration service is shutting down")
            if not self.background:
                return
            if not self._started:
                self.store.recover_interrupted()
                self._executor = ThreadPoolExecutor(
                    max_workers=max(
                        1,
                        int(self.config.get("max_concurrent_sessions", 2)),
                    ),
                    thread_name_prefix="gaworld_collaboration",
                )
                self._started = True
            existing = self._futures.get(session_id)
            if existing is not None and not existing.done():
                return
            if self._executor is None:
                raise RuntimeError("collaboration executor is not running")
            self._futures[session_id] = self._executor.submit(
                self.run_session,
                session_id,
            )

    def _members(self, agent_ids: Iterable[int]) -> list[int]:
        members: list[int] = []
        for raw in agent_ids:
            agent_id = int(raw)
            if agent_id <= 0:
                raise ValueError("agent ids must be positive")
            if agent_id not in members:
                members.append(agent_id)
        if len(members) < 2:
            raise ValueError("at least two agents are required")
        missing = [
            agent_id
            for agent_id in members
            if self.agent_loader(agent_id) is None
        ]
        if missing:
            raise ValueError(f"agents not found: {missing}")
        return members

    def make_friends(self, agent_ids: Iterable[int]) -> dict[str, Any]:
        return self.relationships.make_friends(agent_ids)

    def create_discussion(
        self,
        agent_ids: Iterable[int],
        *,
        topic: str,
        max_rounds: int,
    ) -> CollaborationSession:
        members = self._members(agent_ids)
        limits = self.config.get("discussion", {})
        if not isinstance(limits, dict):
            limits = {}
        minimum = int(limits.get("min_rounds", 3))
        maximum = int(limits.get("max_rounds", 20))
        rounds = int(max_rounds)
        if rounds < minimum or rounds > maximum:
            raise ValueError(
                f"max_rounds must be between {minimum} and {maximum}"
            )
        title = str(topic).strip()
        session = CollaborationSession.new(
            kind="discussion",
            member_ids=members,
            topic=title,
            title=title or "自由讨论",
            max_rounds=rounds,
        )
        self.store.create(session)
        self.store.append_event(session.id, "created", session.title)
        self._submit(session.id)
        return session

    def create_cooperation(
        self,
        agent_ids: Iterable[int],
        *,
        task: str,
        leader_id: int | None = None,
        role_overrides: dict[str, str] | None = None,
    ) -> CollaborationSession:
        members = self._members(agent_ids)
        clean_task = str(task).strip()
        if not clean_task:
            raise ValueError("task is required")
        clean_leader = int(leader_id) if leader_id is not None else None
        if clean_leader is not None and clean_leader not in members:
            raise ValueError("leader must be a selected member")
        clean_roles = {
            str(int(agent_id)): str(role).strip()
            for agent_id, role in (role_overrides or {}).items()
            if int(agent_id) in members and str(role).strip()
        }
        session = CollaborationSession.new(
            kind="cooperation",
            member_ids=members,
            task=clean_task,
            title=clean_task[:80],
            leader_id=clean_leader,
            role_overrides=clean_roles,
        )
        self.store.create(session)
        self.store.append_event(session.id, "created", session.title)
        self._submit(session.id)
        return session

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.store.get(session_id).to_dict()

    def list_sessions(
        self,
        *,
        kind: str = "",
        status: str = "",
    ) -> list[dict[str, Any]]:
        return [
            session.to_dict()
            for session in self.store.list(kind=kind, status=status)
        ]

    def health(self) -> dict[str, Any]:
        return self.store.health()

    def events(
        self,
        session_id: str,
        *,
        after: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            asdict(event)
            for event in self.store.events(session_id, after=after)
        ]

    def pause(self, session_id: str) -> dict[str, Any]:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            session.transition(SessionStatus.PAUSED)
            self.store.save(session)
            self.store.append_event(session_id, "paused", "会话已暂停")
            return session.to_dict()

    def resume(self, session_id: str) -> dict[str, Any]:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            session.transition(SessionStatus.RUNNING)
            session.error = ""
            self.store.save(session)
            self.store.append_event(session_id, "resumed", "会话已恢复")
            payload = session.to_dict()
        self._submit(session_id)
        return payload

    def cancel(self, session_id: str) -> dict[str, Any]:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            session.transition(SessionStatus.CANCELLED)
            self.store.save(session)
            self.store.append_event(session_id, "cancelled", "会话已终止")
            return session.to_dict()

    def run_session(self, session_id: str) -> None:
        try:
            session = self.store.get(session_id)
            if session.kind == "discussion":
                self.discussion.run(session_id)
            elif session.kind == "cooperation":
                self.cooperation.run(session_id)
            else:
                raise ValueError(
                    f"unsupported session kind: {session.kind}"
                )
        except Exception as exc:
            self._fail_session(session_id, exc)
