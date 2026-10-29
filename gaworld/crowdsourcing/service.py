"""Session lifecycle for crowdsourcing.

Mirrors :class:`gaworld.collaboration.service.CollaborationService`: the
dashboard creates a session, the service validates it, hands it to a worker
thread and keeps the events flowing. One difference is deliberate — a crowd
session can be *paused and resumed*, because a crowd that is half way
through its rounds is expensive to throw away.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gaworld.crowdsourcing.models import CrowdSession, CrowdStatus
from gaworld.crowdsourcing.runner import CrowdsourcingRunner
from gaworld.crowdsourcing.store import CrowdStore
from gaworld.crowdsourcing.strategies import DEFAULT_STRATEGY, get_strategy, strategy_catalog


def _missing_llm(*args: Any, **kwargs: Any) -> str:
    raise RuntimeError("crowdsourcing LLM is not configured")


class CrowdsourcingService:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        sessions_dir: str | Path,
        agent_loader: Callable[[int], dict[str, Any] | None],
        llm: Callable[..., str] | None,
        background: bool = True,
        episode_writer: Callable[[int, dict[str, Any]], None] | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = dict(config)
        self.store = CrowdStore(sessions_dir, event_sink=event_sink)
        self.agent_loader = agent_loader
        self.llm = llm
        self.background = bool(background)
        self.max_pool_size = max(2, int(self.config.get("max_pool_size", 200)))
        self.max_rounds = max(1, int(self.config.get("max_rounds", 8)))
        self.max_participants = max(1, int(self.config.get("max_participants_per_round", 32)))
        self.runner = CrowdsourcingRunner(
            store=self.store,
            agent_loader=agent_loader,
            llm=llm if llm is not None else _missing_llm,
            episode_writer=episode_writer,
            max_parallel_calls=max(1, int(self.config.get("max_parallel_calls", 6))),
            step_retries=max(0, int(self.config.get("step_retries", 1))),
            learning_rate=float(self.config.get("learning_rate", 0.35)),
        )
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[str, Future[None]] = {}
        self._guard = threading.RLock()
        self._started = False
        self._closing = False
        self._shutdown_complete = threading.Event()
        self._shutdown_complete.set()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._guard:
            if self._closing:
                raise RuntimeError("crowdsourcing service is shutting down")
            if self._started:
                return
            self.store.recover_interrupted()
            if self.background:
                self._executor = ThreadPoolExecutor(
                    max_workers=max(
                        1,
                        int(self.config.get("max_concurrent_sessions", 1)),
                    ),
                    thread_name_prefix="gaworld_crowdsourcing",
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
            for session_id, future in futures:
                if future.cancel():
                    try:
                        self._cancel_queued_session(session_id)
                    except Exception:
                        pass
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
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
                CrowdStatus.COMPLETED,
                CrowdStatus.CANCELLED,
            }:
                return
            session.transition(CrowdStatus.CANCELLED)
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
                CrowdStatus.COMPLETED,
                CrowdStatus.CANCELLED,
            }:
                return
            session.error = str(exc)[:500]
            if session.status is not CrowdStatus.FAILED:
                if session.status is not CrowdStatus.RUNNING:
                    session.transition(CrowdStatus.RUNNING)
                session.transition(CrowdStatus.FAILED)
            self.store.save(session)
            self.store.append_event(session_id, "error", session.error)

    def _submit(self, session_id: str) -> None:
        with self._guard:
            if self._closing:
                raise RuntimeError("crowdsourcing service is shutting down")
            if not self.background:
                return
            if not self._started:
                self.store.recover_interrupted()
                self._executor = ThreadPoolExecutor(
                    max_workers=max(
                        1,
                        int(self.config.get("max_concurrent_sessions", 1)),
                    ),
                    thread_name_prefix="gaworld_crowdsourcing",
                )
                self._started = True
            existing = self._futures.get(session_id)
            if existing is not None and not existing.done():
                return
            if self._executor is None:
                raise RuntimeError("crowdsourcing executor is not running")
            self._futures[session_id] = self._executor.submit(
                contextvars.copy_context().run,
                self.run_session,
                session_id,
            )

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

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
        if len(members) > self.max_pool_size:
            raise ValueError(f"pool is limited to {self.max_pool_size} agents")
        missing = [agent_id for agent_id in members if self.agent_loader(agent_id) is None]
        if missing:
            raise ValueError(f"agents not found: {missing}")
        return members

    def _prune_config(self, raw: Any) -> dict[str, Any]:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("prune must be an object")
        enabled = bool(raw.get("enabled", True))
        keep = int(raw.get("keep", 0) or 0)
        explore_ratio = float(raw.get("explore_ratio", 0.25) or 0.0)
        if keep < 0 or keep > self.max_pool_size:
            raise ValueError(f"keep must be between 0 and {self.max_pool_size}")
        if explore_ratio < 0.0 or explore_ratio > 1.0:
            raise ValueError("explore_ratio must be between 0 and 1")
        return {
            "enabled": enabled,
            "keep": keep,
            "explore_ratio": explore_ratio,
        }

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def strategies(self) -> dict[str, Any]:
        return {
            "strategies": strategy_catalog(),
            "defaults": {
                "strategy": str(self.config.get("default_strategy", DEFAULT_STRATEGY)),
                "rounds": 3,
                "participants_per_round": 5,
                "keep": 8,
                "explore_ratio": 0.25,
            },
            "limits": {
                "max_pool_size": self.max_pool_size,
                "max_rounds": self.max_rounds,
                "max_participants_per_round": self.max_participants,
                "max_keep": self.max_pool_size,
            },
        }

    def create_crowd(
        self,
        agent_ids: Iterable[int],
        *,
        task: str,
        strategy: str = DEFAULT_STRATEGY,
        rounds: int = 3,
        participants_per_round: int = 5,
        criteria: str = "",
        prune: dict[str, Any] | None = None,
    ) -> CrowdSession:
        members = self._members(agent_ids)
        clean_task = str(task).strip()
        if not clean_task:
            raise ValueError("task is required")
        spec = get_strategy(strategy)
        total_rounds = int(rounds)
        if total_rounds < 1 or total_rounds > self.max_rounds:
            raise ValueError(f"rounds must be between 1 and {self.max_rounds}")
        participants = int(participants_per_round)
        if participants < 1 or participants > self.max_participants:
            raise ValueError(f"participants_per_round must be between 1 and {self.max_participants}")
        participants = min(participants, len(members))
        prune_config = self._prune_config(prune)
        if prune_config["enabled"] and prune_config["keep"] == 0:
            prune_config["keep"] = min(len(members), 8)
        session = CrowdSession.new(
            task=clean_task,
            strategy=spec.id,
            agent_ids=members,
            rounds=total_rounds,
            participants_per_round=participants,
            criteria=str(criteria or "").strip(),
            title=clean_task[:80],
            prune=prune_config,
        )
        self.store.create(session)
        self.store.append_event(session.id, "created", session.title)
        self._submit(session.id)
        return session

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.store.get(session_id).to_dict()

    def list_sessions(self, *, status: str = "") -> list[dict[str, Any]]:
        return [session.to_dict() for session in self.store.list(status=status)]

    def rounds(self, session_id: str) -> list[dict[str, Any]]:
        return self.store.rounds(session_id)

    def health(self) -> dict[str, Any]:
        return self.store.health()

    def events(self, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        return [asdict(event) for event in self.store.events(session_id, after=after)]

    def pause(self, session_id: str) -> dict[str, Any]:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            session.transition(CrowdStatus.PAUSED)
            self.store.save(session)
            self.store.append_event(session_id, "paused", "众包已暂停")
            return session.to_dict()

    def resume(self, session_id: str) -> dict[str, Any]:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            session.transition(CrowdStatus.RUNNING)
            session.error = ""
            self.store.save(session)
            self.store.append_event(session_id, "resumed", "众包已恢复")
            payload = session.to_dict()
        self._submit(session_id)
        return payload

    def cancel(self, session_id: str) -> dict[str, Any]:
        with self.store.session_guard(session_id):
            session = self.store.get(session_id)
            session.transition(CrowdStatus.CANCELLED)
            self.store.save(session)
            self.store.append_event(session_id, "cancelled", "众包已终止")
            return session.to_dict()

    def run_session(self, session_id: str) -> None:
        try:
            self.runner.run(session_id)
        except Exception as exc:
            self._fail_session(session_id, exc)
