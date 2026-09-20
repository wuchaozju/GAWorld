from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gaworld.collaboration.models import (
    CollaborationSession,
    SessionEvent,
    SessionStatus,
    utc_now,
)


class SessionStore:
    def __init__(
        self,
        root: str | Path,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.event_sink = event_sink
        self._load_errors: list[str] = []
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock(self, session_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, threading.RLock())

    @contextmanager
    def session_guard(self, session_id: str) -> Iterator[None]:
        self._dir(session_id)
        with self._lock(session_id):
            yield

    def _dir(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("invalid session id")
        return self.root / session_id

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    def create(self, session: CollaborationSession) -> CollaborationSession:
        directory = self._dir(session.id)
        with self.session_guard(session.id):
            if directory.exists():
                raise ValueError(f"session already exists: {session.id}")
            directory.mkdir(parents=True)
            self._atomic_json(directory / "session.json", session.to_dict())
        return session

    def save(self, session: CollaborationSession) -> CollaborationSession:
        with self.session_guard(session.id):
            if not self._dir(session.id).exists():
                raise KeyError(session.id)
            session.updated_at = utc_now()
            self._atomic_json(self._dir(session.id) / "session.json", session.to_dict())
        return session

    def get(self, session_id: str) -> CollaborationSession:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "session.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise KeyError(session_id) from exc
            return CollaborationSession.from_dict(payload)

    def list(self, *, kind: str = "", status: str = "") -> list[CollaborationSession]:
        sessions: list[CollaborationSession] = []
        self._load_errors = []
        directories = sorted(path for path in self.root.iterdir() if path.is_dir())
        for directory in directories:
            path = directory / "session.json"
            if not path.is_file():
                self._load_errors.append(directory.name)
                continue
            try:
                session = CollaborationSession.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self._load_errors.append(path.parent.name)
                continue
            if kind and session.kind != kind:
                continue
            if status and session.status.value != status:
                continue
            sessions.append(session)
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def health(self) -> dict[str, list[str]]:
        return {"malformed_sessions": list(self._load_errors)}

    def append_event(
        self,
        session_id: str,
        event_type: str,
        content: str = "",
        *,
        agent_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionEvent:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "events.jsonl"
            existing = self.events(session_id)
            event = SessionEvent(
                seq=existing[-1].seq + 1 if existing else 1,
                type=str(event_type),
                timestamp=utc_now(),
                content=str(content),
                agent_id=agent_id,
                metadata=dict(metadata or {}),
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if self.event_sink is not None:
                try:
                    self.event_sink(asdict(event))
                except Exception:
                    pass
            return event

    def events(self, session_id: str, *, after: int = 0) -> list[SessionEvent]:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "events.jsonl"
            if not (self._dir(session_id) / "session.json").exists():
                raise KeyError(session_id)
            if not path.exists():
                return []
            items: list[SessionEvent] = []
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                payload = json.loads(raw)
                event = SessionEvent(**payload)
                if event.seq > int(after):
                    items.append(event)
            return items

    def write_artifact(
        self,
        session_id: str,
        filename: str,
        content: str,
        *,
        agent_id: int | None,
        media_type: str = "text/markdown",
        summary: str = "",
    ) -> dict[str, Any]:
        if not filename or Path(filename).name != filename:
            raise ValueError("unsafe artifact filename")
        with self.session_guard(session_id):
            directory = self._dir(session_id) / "artifacts"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / filename
            temp = path.with_name(path.name + ".tmp")
            with temp.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            metadata = {
                "filename": filename,
                "path": f"artifacts/{filename}",
                "media_type": media_type,
                "agent_id": agent_id,
                "summary": str(summary).strip(),
                "size": path.stat().st_size,
                "created_at": utc_now(),
            }
            session = self.get(session_id)
            session.artifacts = [
                item for item in session.artifacts if item.get("filename") != filename
            ]
            session.artifacts.append(metadata)
            self.save(session)
            return metadata

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for session in self.list():
            if session.status is SessionStatus.RUNNING:
                session.transition(SessionStatus.INTERRUPTED)
                self.save(session)
                with suppress(OSError, TypeError, ValueError):
                    self.append_event(session.id, "interrupted", "服务重启，会话等待恢复")
                recovered.append(session.id)
        return recovered
