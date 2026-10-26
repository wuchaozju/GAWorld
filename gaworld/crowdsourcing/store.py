"""On-disk storage for crowdsourcing sessions.

Layout per session (``output/crowdsourcing/sessions/<id>/``):

``session.json``    the session itself, rewritten atomically on every change
``events.jsonl``    the live feed, appended one JSON object per line
``rounds.jsonl``    the full trajectory (bids, attempts, scores, survivors)
``artifacts/``      the final deliverable and anything else worth keeping

The split matters: ``session.json`` is what the dashboard polls and it stays
small, while the attempts — which are the bulk — live in their own file so
polling does not drag every answer of every round over the wire.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gaworld.crowdsourcing.models import (
    CrowdEvent,
    CrowdSession,
    CrowdStatus,
    utc_now,
)


class CrowdStore:
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

    def create(self, session: CrowdSession) -> CrowdSession:
        directory = self._dir(session.id)
        with self.session_guard(session.id):
            if directory.exists():
                raise ValueError(f"session already exists: {session.id}")
            directory.mkdir(parents=True)
            self._atomic_json(directory / "session.json", session.to_dict())
        return session

    def save(self, session: CrowdSession) -> CrowdSession:
        with self.session_guard(session.id):
            if not self._dir(session.id).exists():
                raise KeyError(session.id)
            session.updated_at = utc_now()
            self._atomic_json(self._dir(session.id) / "session.json", session.to_dict())
        return session

    def get(self, session_id: str) -> CrowdSession:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "session.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise KeyError(session_id) from exc
            return CrowdSession.from_dict(payload)

    def list(self, *, status: str = "") -> list[CrowdSession]:
        sessions: list[CrowdSession] = []
        self._load_errors = []
        directories = sorted(path for path in self.root.iterdir() if path.is_dir())
        for directory in directories:
            path = directory / "session.json"
            if not path.is_file():
                self._load_errors.append(directory.name)
                continue
            try:
                session = CrowdSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self._load_errors.append(path.parent.name)
                continue
            if status and session.status.value != status:
                continue
            sessions.append(session)
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def health(self) -> dict[str, list[str]]:
        # Re-scan rather than report whatever the last ``list()`` happened to
        # see: a session that went bad since then would otherwise be reported
        # as healthy.
        self.list()
        return {"malformed_sessions": list(self._load_errors)}

    def append_event(
        self,
        session_id: str,
        event_type: str,
        content: str = "",
        *,
        agent_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CrowdEvent:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "events.jsonl"
            existing = self.events(session_id)
            event = CrowdEvent(
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

    def events(self, session_id: str, *, after: int = 0) -> list[CrowdEvent]:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "events.jsonl"
            if not (self._dir(session_id) / "session.json").exists():
                raise KeyError(session_id)
            if not path.exists():
                return []
            items: list[CrowdEvent] = []
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                payload = json.loads(raw)
                event = CrowdEvent(**payload)
                if event.seq > int(after):
                    items.append(event)
            return items

    def append_round(self, session_id: str, record: dict[str, Any]) -> None:
        """Append one round's full detail to the trajectory file."""
        with self.session_guard(session_id):
            path = self._dir(session_id) / "rounds.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def rounds(self, session_id: str) -> list[dict[str, Any]]:
        with self.session_guard(session_id):
            path = self._dir(session_id) / "rounds.jsonl"
            if not (self._dir(session_id) / "session.json").exists():
                raise KeyError(session_id)
            if not path.exists():
                return []
            records: list[dict[str, Any]] = []
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                records.append(json.loads(raw))
            return records

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
            session.artifacts = [item for item in session.artifacts if item.get("filename") != filename]
            session.artifacts.append(metadata)
            self.save(session)
            return metadata

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for session in self.list():
            if session.status is CrowdStatus.RUNNING:
                session.transition(CrowdStatus.INTERRUPTED)
                self.save(session)
                with suppress(OSError, TypeError, ValueError):
                    self.append_event(session.id, "interrupted", "服务重启，众包等待恢复")
                recovered.append(session.id)
        return recovered
