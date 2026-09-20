# Agent Collaboration Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Dashboard users create reciprocal friendships, run observable multi-agent discussions, and assemble teams that plan, execute, review, and deliver collaborative tasks.

**Architecture:** Add a file-backed `gaworld.collaboration` plugin and standalone service shared by the simulator and Dashboard. Sessions use atomic JSON snapshots plus append-only JSONL events, while independent background workers call the existing LLM router and write experience references back to member memory. The existing Dashboard receives a self-contained interaction panel, and the console shell receives a separate cooperation page.

**Tech Stack:** Python 3.11 dataclasses, `ThreadPoolExecutor`, JSON/JSONL persistence, GAWorld kernel plugins and LLM router, stdlib `ThreadingHTTPServer`, vanilla HTML/CSS/JavaScript, pytest, Node.js built-in test runner, Ruff, mypy.

---

## File Structure

### New backend files

- `gaworld/collaboration/__init__.py` — public collaboration service exports.
- `gaworld/collaboration/models.py` — session and event data models plus state transitions.
- `gaworld/collaboration/store.py` — atomic snapshots, append-only events, artifact confinement, and recovery.
- `gaworld/collaboration/relationships.py` — reciprocal all-pairs friendship writes.
- `gaworld/collaboration/discussion.py` — discussion prompt construction and bounded turn runner.
- `gaworld/collaboration/cooperation.py` — planning, execution, review, and synthesis runner.
- `gaworld/collaboration/service.py` — validation, worker lifecycle, session commands, and runner dispatch.
- `gaworld/collaboration/plugin.py` — kernel lifecycle integration.

### Modified backend files

- `gaworld/settings/integrations.py` — collaboration defaults.
- `gaworld/plugins/__init__.py` — built-in plugin registration.
- `gaworld/apps/dashboard_server.py` — thin API routing and standalone service lifecycle.

### New frontend files

- `site/dashboard/interaction.js` — Dashboard friendship/discussion controls and transcript polling.
- `site/dashboard/interaction.css` — scoped interaction panel styles.
- `site/dashboard/collaboration-core.js` — pure payload/status helpers shared with tests.
- `site/dashboard/collaboration.html` — cooperation task page.
- `site/dashboard/collaboration.js` — cooperation page controller and polling.
- `site/dashboard/collaboration.css` — cooperation workspace styles.
- `site/dashboard/collaboration-core.test.js` — Node unit tests for pure frontend behavior.

### Modified frontend files

- `site/dashboard/index.html` — mount the interaction panel and load its isolated assets.
- `site/console/index.html` — add the **合作任务** tab.
- `site/console/console.js` — register the collaboration iframe.
- `site/console/console.css` — keep the fourth tab usable at narrow widths.
- `site/dashboard/locales/zh-CN.json` — Chinese interaction strings.
- `site/dashboard/locales/en.json` — matching English strings.

### New tests

- `tests/test_collaboration_models_store.py`
- `tests/test_collaboration_relationships.py`
- `tests/test_collaboration_discussion.py`
- `tests/test_collaboration_cooperation.py`
- `tests/test_collaboration_service_plugin.py`
- `tests/test_dashboard_collaboration.py`
- `tests/test_collaboration_frontend.py`

## Working-Tree Safety

`site/dashboard/index.html` is already modified in the current worktree. Before editing it, inspect `git diff -- site/dashboard/index.html` and apply only a narrow additive patch around the selected insertion point and script/style tags. Do not rewrite or restore `site/dashboard/app.js`; the new interaction controller deliberately lives in `interaction.js`.

---

### Task 1: Configuration and Session Models

**Files:**
- Create: `gaworld/collaboration/__init__.py`
- Create: `gaworld/collaboration/models.py`
- Modify: `gaworld/settings/integrations.py`
- Test: `tests/test_collaboration_models_store.py`
- Test: `tests/test_gaworld_settings.py`

- [ ] **Step 1: Write failing model and configuration tests**

```python
# tests/test_collaboration_models_store.py
from gaworld.collaboration.models import CollaborationSession, SessionStatus


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
```

Add to `tests/test_gaworld_settings.py`:

```python
def test_collaboration_defaults_are_bounded():
    cfg = build_default_config()["collaboration"]
    assert cfg["enabled"] is True
    assert cfg["max_concurrent_sessions"] == 2
    assert cfg["discussion"]["min_rounds"] == 3
    assert cfg["discussion"]["max_rounds"] == 20
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_models_store.py tests/test_gaworld_settings.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'gaworld.collaboration'`.

- [ ] **Step 3: Add collaboration defaults**

Add this key to `integration_settings()`:

```python
"collaboration": {
    "enabled": True,
    "sessions_dir": "output/collaboration/sessions",
    "max_concurrent_sessions": 2,
    "max_context_events": 24,
    "step_retries": 2,
    "discussion": {
        "default_rounds": 6,
        "min_rounds": 3,
        "max_rounds": 20,
    },
},
```

- [ ] **Step 4: Implement the data model and transition table**

`gaworld/collaboration/models.py` must define:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


ALLOWED_TRANSITIONS = {
    SessionStatus.QUEUED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.RUNNING: {
        SessionStatus.PAUSED,
        SessionStatus.COMPLETED,
        SessionStatus.CANCELLED,
        SessionStatus.FAILED,
        SessionStatus.INTERRUPTED,
    },
    SessionStatus.PAUSED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.FAILED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.INTERRUPTED: {SessionStatus.RUNNING, SessionStatus.CANCELLED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.CANCELLED: set(),
}


@dataclass(slots=True)
class CollaborationSession:
    id: str
    kind: str
    member_ids: list[int]
    status: SessionStatus = SessionStatus.QUEUED
    title: str = ""
    topic: str = ""
    task: str = ""
    leader_id: int | None = None
    role_overrides: dict[str, str] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    max_rounds: int = 6
    current_round: int = 0
    current_step: int = 0
    plan: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def new(cls, *, kind: str, member_ids: list[int], **values: Any) -> "CollaborationSession":
        return cls(
            id=f"cs_{datetime.now(UTC):%Y%m%d}_{uuid4().hex[:10]}",
            kind=kind,
            member_ids=list(member_ids),
            **values,
        )

    def transition(self, target: SessionStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid session transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CollaborationSession":
        values = dict(payload)
        values["status"] = SessionStatus(values["status"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class SessionEvent:
    seq: int
    type: str
    timestamp: str
    content: str = ""
    agent_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

`gaworld/collaboration/__init__.py` initially exports `CollaborationSession`, `SessionEvent`, and `SessionStatus`.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
pytest tests/test_collaboration_models_store.py tests/test_gaworld_settings.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add gaworld/collaboration/__init__.py gaworld/collaboration/models.py \
  gaworld/settings/integrations.py tests/test_collaboration_models_store.py \
  tests/test_gaworld_settings.py
git commit -m "add collaboration session models"
```

---

### Task 2: File-Backed Session Store

**Files:**
- Create: `gaworld/collaboration/store.py`
- Modify: `tests/test_collaboration_models_store.py`

- [ ] **Step 1: Add failing store tests**

```python
import json

from gaworld.collaboration.store import SessionStore


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


def test_recovery_marks_running_sessions_interrupted(tmp_path):
    store = SessionStore(tmp_path)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    session.transition(SessionStatus.RUNNING)
    store.create(session)

    recovered = SessionStore(tmp_path).recover_interrupted()

    assert recovered == [session.id]
    assert store.get(session.id).status is SessionStatus.INTERRUPTED


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
    store = SessionStore(tmp_path, event_sink=seen.append)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2])
    store.create(session)
    store.append_event(session.id, "created", "讨论")
    assert seen == [{
        "seq": 1,
        "type": "created",
        "timestamp": seen[0]["timestamp"],
        "content": "讨论",
        "agent_id": None,
        "metadata": {},
    }]


def test_malformed_session_is_skipped_and_reported(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "session.json").write_text("{bad json", encoding="utf-8")
    store = SessionStore(tmp_path)
    assert store.list() == []
    assert store.health()["malformed_sessions"] == ["broken"]
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_models_store.py -v
```

Expected: fails because `gaworld.collaboration.store` does not exist.

- [ ] **Step 3: Implement `SessionStore`**

Implement `gaworld/collaboration/store.py` with the following complete store:

```python
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
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
        with self._lock(session.id):
            if directory.exists():
                raise ValueError(f"session already exists: {session.id}")
            directory.mkdir(parents=True)
            self._atomic_json(directory / "session.json", session.to_dict())
        return session

    def save(self, session: CollaborationSession) -> CollaborationSession:
        with self._lock(session.id):
            if not self._dir(session.id).exists():
                raise KeyError(session.id)
            session.updated_at = utc_now()
            self._atomic_json(self._dir(session.id) / "session.json", session.to_dict())
        return session

    def get(self, session_id: str) -> CollaborationSession:
        path = self._dir(session_id) / "session.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(session_id) from exc
        return CollaborationSession.from_dict(payload)

    def list(self, *, kind: str = "", status: str = "") -> list[CollaborationSession]:
        sessions: list[CollaborationSession] = []
        self._load_errors = []
        for path in sorted(self.root.glob("*/session.json")):
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
        with self._lock(session_id):
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
        with self._lock(session_id):
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
                self.append_event(session.id, "interrupted", "服务重启，会话等待恢复")
                recovered.append(session.id)
        return recovered
```

The reentrant lock is required because `append_event()` calls `events()` and `write_artifact()` calls `get()` and `save()` while holding the same session lock.

- [ ] **Step 4: Run store tests and verify GREEN**

Run:

```bash
pytest tests/test_collaboration_models_store.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add gaworld/collaboration/store.py tests/test_collaboration_models_store.py
git commit -m "add collaboration session store"
```

---

### Task 3: Reciprocal Friendship Service

**Files:**
- Create: `gaworld/collaboration/relationships.py`
- Create: `tests/test_collaboration_relationships.py`

- [ ] **Step 1: Write failing relationship tests**

```python
import json

from gaworld.collaboration.relationships import (
    RelationshipService,
    merge_persisted_agent_edges,
)


def _agent(agent_id):
    return {"identity": {"id": agent_id, "name": f"居民{agent_id}"}}


def test_make_friends_creates_every_reciprocal_pair(tmp_path):
    service = RelationshipService(
        memory_dir=tmp_path,
        agent_loader=lambda agent_id: _agent(agent_id),
    )
    result = service.make_friends([1, 2, 3])

    assert result["created_pairs"] == [[1, 2], [1, 3], [2, 3]]
    for left, right in result["created_pairs"]:
        left_rels = json.loads((tmp_path / f"agent_{left}_relationships.json").read_text())
        right_rels = json.loads((tmp_path / f"agent_{right}_relationships.json").read_text())
        assert left_rels[str(right)]["role"] == "friend"
        assert right_rels[str(left)]["role"] == "friend"
        assert left_rels[str(right)]["closeness"] == 0.65


def test_make_friends_is_idempotent_and_preserves_stronger_role(tmp_path):
    (tmp_path / "agent_1_relationships.json").write_text(
        json.dumps({"2": {"role": "mentor", "closeness": 0.9, "trust": 0.8, "friction": 0.0}}),
        encoding="utf-8",
    )
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))
    service.make_friends([1, 2])
    second = service.make_friends([1, 2])
    rel = json.loads((tmp_path / "agent_1_relationships.json").read_text())["2"]

    assert rel["role"] == "mentor"
    assert rel["closeness"] == 0.9
    assert second["existing_pairs"] == [[1, 2]]


def test_make_friends_rejects_missing_agent_without_writes(tmp_path):
    service = RelationshipService(
        memory_dir=tmp_path,
        agent_loader=lambda agent_id: _agent(agent_id) if agent_id != 9 else None,
    )
    try:
        service.make_friends([1, 9])
    except ValueError as exc:
        assert "9" in str(exc)
    else:
        raise AssertionError("missing agent was accepted")
    assert list(tmp_path.iterdir()) == []


def test_merge_persisted_edges_updates_runtime_neighbors():
    agents = [
        {
            "id": 1,
            "social_neighbors": [],
            "relationships": {"2": {"kind": "agent", "role": "friend"}},
        },
        {"id": 2, "social_neighbors": [], "relationships": {}},
    ]
    merge_persisted_agent_edges(agents)
    assert agents[0]["social_neighbors"] == [2]
    assert agents[1]["social_neighbors"] == [1]


def test_touch_interaction_updates_existing_edges_without_creating_new_ones(tmp_path):
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))
    service.make_friends([1, 2])
    service.touch_interaction([1, 2, 3])
    rels_1 = json.loads((tmp_path / "agent_1_relationships.json").read_text())
    assert rels_1["2"]["last_dashboard_interaction_at"]
    assert "3" not in rels_1
```

- [ ] **Step 2: Run relationship tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_relationships.py -v
```

Expected: fails because `gaworld.collaboration.relationships` does not exist.

- [ ] **Step 3: Implement reciprocal all-pairs writes**

Implement `gaworld/collaboration/relationships.py` with this all-pairs service:

```python
from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from itertools import combinations
from pathlib import Path
from typing import Any

from gaworld.collaboration.models import utc_now
from gaworld.social.network import ensure_relationship_schema


class RelationshipService:
    def __init__(self, *, memory_dir: str | Path, agent_loader: Callable[[int], dict[str, Any] | None]) -> None:
        self.memory_dir = Path(memory_dir)
        self.agent_loader = agent_loader
        self._guard = threading.Lock()
        self._locks: dict[int, threading.RLock] = {}

    def make_friends(self, agent_ids: Iterable[int]) -> dict[str, list[list[int]]]:
        ids: list[int] = []
        for raw in agent_ids:
            value = int(raw)
            if value <= 0:
                raise ValueError("agent ids must be positive")
            if value not in ids:
                ids.append(value)
        if len(ids) < 2:
            raise ValueError("at least two agents are required")
        agents = {agent_id: self.agent_loader(agent_id) for agent_id in ids}
        missing = [agent_id for agent_id, agent in agents.items() if agent is None]
        if missing:
            raise ValueError(f"agents not found: {missing}")

        ordered = sorted(ids)
        with ExitStack() as stack:
            for agent_id in ordered:
                with self._guard:
                    lock = self._locks.setdefault(agent_id, threading.RLock())
                stack.enter_context(lock)
            return self._write_group(ordered, agents)

    def _path(self, agent_id: int) -> Path:
        return self.memory_dir / f"agent_{agent_id}_relationships.json"

    def touch_interaction(self, agent_ids: Iterable[int]) -> None:
        ids = sorted({int(agent_id) for agent_id in agent_ids})
        if len(ids) < 2:
            return
        with ExitStack() as stack:
            for agent_id in ids:
                with self._guard:
                    lock = self._locks.setdefault(agent_id, threading.RLock())
                stack.enter_context(lock)
            changed: dict[int, dict[str, Any]] = {}
            stamp = utc_now()
            for left, right in combinations(ids, 2):
                for source, target in ((left, right), (right, left)):
                    relationships = changed.setdefault(
                        source,
                        self._load(self._path(source)),
                    )
                    record = relationships.get(str(target))
                    if isinstance(record, dict):
                        record["last_dashboard_interaction_at"] = stamp
            for agent_id, relationships in changed.items():
                self._atomic_write(self._path(agent_id), relationships)

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    @staticmethod
    def _identity(agent: dict[str, Any]) -> dict[str, Any]:
        identity = agent.get("identity")
        return identity if isinstance(identity, dict) else agent

    @staticmethod
    def _already_promoted(record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        return (
            float(record.get("closeness", 0.0)) >= 0.65
            and float(record.get("trust", 0.0)) >= 0.60
            and float(record.get("obligation", 0.0)) >= 0.40
            and float(record.get("friction", 1.0)) <= 0.10
        )

    def _promote(self, record: dict[str, Any], peer: dict[str, Any]) -> dict[str, Any]:
        if not record:
            record.update({
                "closeness": 0.65,
                "trust": 0.60,
                "obligation": 0.40,
                "friction": 0.10,
            })
        existing_role = str(record.get("role") or "")
        role = "friend" if existing_role in {"", "acquaintance"} else existing_role
        ensure_relationship_schema(record, role=role, kind="agent", tie_origin="dashboard")
        record["kind"] = "agent"
        record["role"] = role
        record.setdefault("tie_origin", "dashboard")
        profile = record.setdefault("profile", {})
        if not isinstance(profile, dict):
            profile = {}
            record["profile"] = profile
        profile["name"] = str(self._identity(peer).get("name") or "")
        record["closeness"] = max(float(record.get("closeness", 0.0)), 0.65)
        record["trust"] = max(float(record.get("trust", 0.0)), 0.60)
        record["obligation"] = max(float(record.get("obligation", 0.0)), 0.40)
        record["friction"] = min(float(record.get("friction", 1.0)), 0.10)
        record["last_interaction_day"] = int(record.get("last_interaction_day", 0) or 0)
        record["last_contact_day"] = int(record.get("last_contact_day", 0) or 0)
        return record

    def _write_group(
        self,
        ids: list[int],
        agents: dict[int, dict[str, Any] | None],
    ) -> dict[str, list[list[int]]]:
        paths = {agent_id: self._path(agent_id) for agent_id in ids}
        originals = {
            agent_id: path.read_bytes() if path.exists() else None
            for agent_id, path in paths.items()
        }
        relationships = {agent_id: self._load(path) for agent_id, path in paths.items()}
        result = {"created_pairs": [], "updated_pairs": [], "existing_pairs": []}
        for left, right in combinations(ids, 2):
            left_record = relationships[left].get(str(right))
            right_record = relationships[right].get(str(left))
            pair = [left, right]
            if self._already_promoted(left_record) and self._already_promoted(right_record):
                result["existing_pairs"].append(pair)
            elif left_record is None and right_record is None:
                result["created_pairs"].append(pair)
            else:
                result["updated_pairs"].append(pair)
            relationships[left][str(right)] = self._promote(
                dict(left_record or {}), agents[right] or {}
            )
            relationships[right][str(left)] = self._promote(
                dict(right_record or {}), agents[left] or {}
            )

        replaced: list[int] = []
        try:
            for agent_id in ids:
                self._atomic_write(paths[agent_id], relationships[agent_id])
                replaced.append(agent_id)
        except Exception:
            for agent_id in reversed(replaced):
                original = originals[agent_id]
                if original is None:
                    paths[agent_id].unlink(missing_ok=True)
                else:
                    restore = paths[agent_id].with_name(paths[agent_id].name + ".restore")
                    restore.write_bytes(original)
                    os.replace(restore, paths[agent_id])
            raise
        return result


def merge_persisted_agent_edges(agents: list[dict[str, Any]]) -> None:
    by_id = {int(agent["id"]): agent for agent in agents}
    edges: set[tuple[int, int]] = set()
    for agent in agents:
        left = int(agent["id"])
        relationships = agent.get("relationships", {})
        if not isinstance(relationships, dict):
            continue
        for raw_peer, record in relationships.items():
            if not isinstance(record, dict) or record.get("kind", "agent") != "agent":
                continue
            try:
                right = int(raw_peer)
            except (TypeError, ValueError):
                continue
            if right in by_id and right != left:
                edges.add(tuple(sorted((left, right))))
    for left, right in sorted(edges):
        left_neighbors = by_id[left].setdefault("social_neighbors", [])
        right_neighbors = by_id[right].setdefault("social_neighbors", [])
        if right not in left_neighbors:
            left_neighbors.append(right)
        if left not in right_neighbors:
            right_neighbors.append(left)
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
pytest tests/test_collaboration_relationships.py tests/test_social_network_schema.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add gaworld/collaboration/relationships.py tests/test_collaboration_relationships.py
git commit -m "add dashboard friendship service"
```

---

### Task 4: Observable Discussion Runner

**Files:**
- Create: `gaworld/collaboration/discussion.py`
- Create: `tests/test_collaboration_discussion.py`

- [ ] **Step 1: Write failing discussion tests**

```python
import json

from gaworld.collaboration.discussion import DiscussionRunner
from gaworld.collaboration.models import CollaborationSession, SessionStatus
from gaworld.collaboration.store import SessionStore


def test_discussion_runs_round_robin_and_writes_summary(tmp_path):
    calls = []

    def llm(prompt, task=None, agent_id=None):
        calls.append((task, agent_id))
        if task == "collaboration_discussion_summary":
            return "双方同意先做社区试点。"
        return json.dumps({"content": f"居民{agent_id}的观点", "converged": False}, ensure_ascii=False)

    store = SessionStore(tmp_path)
    session = CollaborationSession.new(
        kind="discussion",
        member_ids=[2, 1],
        topic="公共空间",
        max_rounds=3,
    )
    store.create(session)
    runner = DiscussionRunner(store=store, agent_loader=lambda agent_id: {"identity": {"id": agent_id}}, llm=llm)
    runner.run(session.id)

    messages = [event for event in store.events(session.id) if event.type == "message"]
    assert [event.agent_id for event in messages] == [2, 1, 2]
    assert store.get(session.id).status is SessionStatus.COMPLETED
    assert store.events(session.id)[-1].type == "completed"
    assert calls[-1][0] == "collaboration_discussion_summary"


def test_discussion_honors_pause_before_next_turn(tmp_path):
    store = SessionStore(tmp_path)
    session = CollaborationSession.new(kind="discussion", member_ids=[1, 2], max_rounds=4)
    store.create(session)
    session.transition(SessionStatus.RUNNING)
    session.transition(SessionStatus.PAUSED)
    store.save(session)
    runner = DiscussionRunner(store=store, agent_loader=lambda agent_id: {"identity": {"id": agent_id}}, llm=lambda *a, **k: "")

    runner.run(session.id)

    assert not [event for event in store.events(session.id) if event.type == "message"]
    assert store.get(session.id).status is SessionStatus.PAUSED
```

- [ ] **Step 2: Run discussion tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_discussion.py -v
```

Expected: fails because `gaworld.collaboration.discussion` does not exist.

- [ ] **Step 3: Implement discussion prompting and runner**

Implement `gaworld/collaboration/discussion.py`:

```python
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from gaworld.collaboration.models import SessionStatus
from gaworld.collaboration.store import SessionStore


class DiscussionRunner:
    def __init__(
        self,
        *,
        store: SessionStore,
        agent_loader: Callable[[int], dict[str, Any] | None],
        llm: Callable[..., str],
        episode_writer: Callable[[int, dict[str, Any]], None] | None = None,
        interaction_writer: Callable[[list[int]], None] | None = None,
        max_context_events: int = 24,
        step_retries: int = 2,
    ) -> None:
        self.store = store
        self.agent_loader = agent_loader
        self.llm = llm
        self.episode_writer = episode_writer or (lambda agent_id, episode: None)
        self.interaction_writer = interaction_writer or (lambda agent_ids: None)
        self.max_context_events = max(1, int(max_context_events))
        self.step_retries = max(0, int(step_retries))

    def _call(self, prompt: str, *, task: str, agent_id: int | None = None) -> str:
        last_error: Exception | None = None
        for _attempt in range(self.step_retries + 1):
            try:
                return str(self.llm(prompt, task=task, agent_id=agent_id)).strip()
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    @staticmethod
    def _response(raw: str) -> tuple[str, bool]:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            content = str(payload.get("content") or "").strip()
            converged = bool(payload.get("converged", False))
            if content:
                return content, converged
        if raw.strip():
            return raw.strip(), False
        raise ValueError("discussion model returned empty content")

    def _prompt(self, session_id: str, speaker_id: int) -> str:
        session = self.store.get(session_id)
        detail = self.agent_loader(speaker_id) or {}
        recent = [
            {
                "agent_id": event.agent_id,
                "content": event.content,
            }
            for event in self.store.events(session_id)
            if event.type == "message"
        ][-self.max_context_events:]
        context = {
            "speaker": {
                "identity": detail.get("identity", detail),
                "profile_text": detail.get("profile_text", ""),
                "capabilities": detail.get("capabilities", {}),
            },
            "topic": session.topic or "自由选择一个成员们自然感兴趣的话题",
            "recent_messages": recent,
            "instruction": (
                "以该居民自身视角自然回应。输出 JSON，字段 content 为本轮发言，"
                "converged 表示讨论是否已形成足够明确的结论。"
            ),
        }
        return json.dumps(context, ensure_ascii=False)

    def _fail(self, session_id: str, exc: Exception) -> None:
        session = self.store.get(session_id)
        session.error = str(exc)[:500]
        if session.status is SessionStatus.RUNNING:
            session.transition(SessionStatus.FAILED)
        self.store.save(session)
        self.store.append_event(session_id, "error", session.error)

    def run(self, session_id: str) -> None:
        session = self.store.get(session_id)
        if session.status in {
            SessionStatus.QUEUED,
            SessionStatus.FAILED,
            SessionStatus.INTERRUPTED,
        }:
            session.transition(SessionStatus.RUNNING)
            session.error = ""
            self.store.save(session)
            self.store.append_event(session_id, "started", "讨论开始")
        elif session.status is not SessionStatus.RUNNING:
            return

        converged = False
        try:
            while True:
                session = self.store.get(session_id)
                if session.status is not SessionStatus.RUNNING:
                    return
                if session.current_round >= session.max_rounds:
                    break
                speaker_id = session.member_ids[
                    session.current_round % len(session.member_ids)
                ]
                raw = self._call(
                    self._prompt(session_id, speaker_id),
                    task="collaboration_discussion",
                    agent_id=speaker_id,
                )
                content, convergence_signal = self._response(raw)
                self.store.append_event(
                    session_id,
                    "message",
                    content,
                    agent_id=speaker_id,
                    metadata={"round": session.current_round + 1},
                )
                latest = self.store.get(session_id)
                latest.current_round += 1
                self.store.save(latest)
                converged = (
                    convergence_signal
                    and latest.current_round >= len(latest.member_ids)
                )
                if latest.status is not SessionStatus.RUNNING:
                    return
                if converged:
                    break

            transcript = [
                {
                    "agent_id": event.agent_id,
                    "content": event.content,
                }
                for event in self.store.events(session_id)
                if event.type == "message"
            ]
            summary = self._call(
                json.dumps(
                    {"topic": session.topic, "transcript": transcript},
                    ensure_ascii=False,
                ),
                task="collaboration_discussion_summary",
            )
            self.store.append_event(session_id, "summary", summary)
            latest = self.store.get(session_id)
            if latest.status is not SessionStatus.RUNNING:
                return
            latest.transition(SessionStatus.COMPLETED)
            self.store.save(latest)
            self.store.append_event(
                session_id,
                "completed",
                summary,
                metadata={"converged": converged},
            )
            for agent_id in latest.member_ids:
                self.episode_writer(agent_id, {
                    "source": "collaboration",
                    "session_id": session_id,
                    "kind": "discussion",
                    "summary": summary,
                    "salience": 0.65,
                })
            self.interaction_writer(latest.member_ids)
        except Exception as exc:
            self._fail(session_id, exc)
```

- [ ] **Step 4: Run discussion tests and verify GREEN**

Run:

```bash
pytest tests/test_collaboration_discussion.py tests/test_mock_llm_fixture.py -v
```

Expected: all tests pass without network calls.

- [ ] **Step 5: Commit**

```bash
git add gaworld/collaboration/discussion.py tests/test_collaboration_discussion.py
git commit -m "add observable agent discussions"
```

---

### Task 5: Collaborative Task Runner

**Files:**
- Create: `gaworld/collaboration/cooperation.py`
- Create: `tests/test_collaboration_cooperation.py`

- [ ] **Step 1: Write failing cooperation test**

```python
import json

from gaworld.collaboration.cooperation import CooperationRunner
from gaworld.collaboration.models import CollaborationSession, SessionStatus
from gaworld.collaboration.store import SessionStore


def test_cooperation_plans_executes_reviews_and_synthesizes(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "collaboration_plan":
            return json.dumps({
                "leader_id": 1,
                "roles": {"1": "研究负责人", "2": "分析员"},
                "steps": [
                    {"title": "需求研究", "agent_id": 1, "artifact": "research.md"},
                    {"title": "数据归纳", "agent_id": 2, "artifact": "analysis.md"},
                ],
            }, ensure_ascii=False)
        if task == "collaboration_review":
            return json.dumps({"approved": True, "feedback": "证据充分"}, ensure_ascii=False)
        if task == "collaboration_synthesis":
            return "# 最终建议\n先开展社区试点。"
        return f"# {agent_id} 的交付\n已完成"

    store = SessionStore(tmp_path)
    session = CollaborationSession.new(
        kind="cooperation",
        member_ids=[1, 2],
        task="形成社区服务行动建议",
    )
    store.create(session)
    runner = CooperationRunner(
        store=store,
        agent_loader=lambda agent_id: {
            "identity": {"id": agent_id, "name": f"居民{agent_id}"},
            "capabilities": {"skills": ["研究"] if agent_id == 1 else ["数据分析"]},
        },
        llm=llm,
    )
    runner.run(session.id)

    saved = store.get(session.id)
    event_types = [event.type for event in store.events(session.id)]
    assert saved.status is SessionStatus.COMPLETED
    assert saved.roles == {"1": "研究负责人", "2": "分析员"}
    assert event_types.count("artifact") == 3
    assert "review" in event_types
    assert any(item["filename"] == "final.md" for item in saved.artifacts)
```

- [ ] **Step 2: Run cooperation tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_cooperation.py -v
```

Expected: fails because `gaworld.collaboration.cooperation` does not exist.

- [ ] **Step 3: Implement plan, execution, review, and synthesis**

Implement `gaworld/collaboration/cooperation.py`:

```python
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gaworld.collaboration.models import SessionStatus
from gaworld.collaboration.store import SessionStore


class CooperationRunner:
    def __init__(
        self,
        *,
        store: SessionStore,
        agent_loader: Callable[[int], dict[str, Any] | None],
        llm: Callable[..., str],
        episode_writer: Callable[[int, dict[str, Any]], None] | None = None,
        max_context_events: int = 24,
        step_retries: int = 2,
    ) -> None:
        self.store = store
        self.agent_loader = agent_loader
        self.llm = llm
        self.episode_writer = episode_writer or (lambda agent_id, episode: None)
        self.max_context_events = max(1, int(max_context_events))
        self.step_retries = max(0, int(step_retries))

    def _call(self, prompt: str, *, task: str, agent_id: int | None = None) -> str:
        last_error: Exception | None = None
        for _attempt in range(self.step_retries + 1):
            try:
                return str(self.llm(prompt, task=task, agent_id=agent_id)).strip()
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    @staticmethod
    def _json(raw: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _safe_filename(value: Any, fallback: str) -> str:
        filename = str(value or fallback).strip()
        return filename if filename and Path(filename).name == filename else fallback

    def _capabilities(self, member_ids: list[int]) -> list[dict[str, Any]]:
        table = []
        for agent_id in member_ids:
            detail = self.agent_loader(agent_id) or {}
            table.append({
                "agent_id": agent_id,
                "identity": detail.get("identity", detail),
                "capabilities": detail.get("capabilities", {}),
                "private_skills": detail.get("private_skills", []),
                "growth": detail.get("growth", {}),
                "cognition": detail.get("cognition", {}),
            })
        return table

    def _fallback_plan(self, member_ids: list[int]) -> dict[str, Any]:
        return {
            "leader_id": member_ids[0],
            "roles": {
                str(agent_id): f"成员{index}"
                for index, agent_id in enumerate(member_ids, start=1)
            },
            "steps": [
                {
                    "title": f"完成成员 {agent_id} 的子任务",
                    "agent_id": agent_id,
                    "artifact": f"member_{agent_id}.md",
                }
                for agent_id in member_ids
            ],
        }

    def _normalized_plan(self, raw: str, member_ids: list[int]) -> dict[str, Any]:
        payload = self._json(raw)
        fallback = self._fallback_plan(member_ids)
        leader_id = int(payload.get("leader_id", fallback["leader_id"]))
        if leader_id not in member_ids:
            leader_id = fallback["leader_id"]
        incoming_roles = payload.get("roles")
        roles = dict(fallback["roles"])
        if isinstance(incoming_roles, dict):
            for agent_id in member_ids:
                value = str(incoming_roles.get(str(agent_id), "")).strip()
                if value:
                    roles[str(agent_id)] = value
        steps = []
        incoming_steps = payload.get("steps")
        if isinstance(incoming_steps, list):
            for index, item in enumerate(incoming_steps, start=1):
                if not isinstance(item, dict):
                    continue
                agent_id = int(item.get("agent_id", 0) or 0)
                if agent_id not in member_ids:
                    continue
                steps.append({
                    "title": str(item.get("title") or f"子任务 {index}").strip(),
                    "agent_id": agent_id,
                    "artifact": self._safe_filename(
                        item.get("artifact"),
                        f"member_{agent_id}_{index}.md",
                    ),
                    "status": "pending",
                })
        if not steps:
            steps = [dict(item, status="pending") for item in fallback["steps"]]
        return {"leader_id": leader_id, "roles": roles, "steps": steps}

    def _fail(self, session_id: str, exc: Exception) -> None:
        session = self.store.get(session_id)
        session.error = str(exc)[:500]
        if session.status is SessionStatus.RUNNING:
            session.transition(SessionStatus.FAILED)
        self.store.save(session)
        self.store.append_event(session_id, "error", session.error)

    def run(self, session_id: str) -> None:
        session = self.store.get(session_id)
        if session.status in {
            SessionStatus.QUEUED,
            SessionStatus.FAILED,
            SessionStatus.INTERRUPTED,
        }:
            session.transition(SessionStatus.RUNNING)
            session.error = ""
            self.store.save(session)
            self.store.append_event(session_id, "started", "合作任务开始")
        elif session.status is not SessionStatus.RUNNING:
            return

        try:
            session = self.store.get(session_id)
            if not session.plan:
                plan_raw = self._call(
                    json.dumps({
                        "task": session.task,
                        "members": self._capabilities(session.member_ids),
                        "instruction": (
                            "输出 JSON：leader_id、roles 对象、steps 数组。"
                            "每个 step 包含 title、agent_id、artifact。"
                        ),
                    }, ensure_ascii=False),
                    task="collaboration_plan",
                )
                plan = self._normalized_plan(plan_raw, session.member_ids)
                session.leader_id = (
                    session.leader_id
                    if session.leader_id in session.member_ids
                    else plan["leader_id"]
                )
                session.roles = plan["roles"]
                session.roles.update(session.role_overrides)
                session.plan = plan["steps"]
                self.store.save(session)
                self.store.append_event(
                    session_id,
                    "role_assigned",
                    "团队角色已确定",
                    metadata={"leader_id": session.leader_id, "roles": session.roles},
                )
                self.store.append_event(
                    session_id,
                    "plan_created",
                    "团队计划已生成",
                    metadata={"plan": session.plan},
                )

            while True:
                session = self.store.get(session_id)
                if session.status is not SessionStatus.RUNNING:
                    return
                if session.current_step >= len(session.plan):
                    break
                step = session.plan[session.current_step]
                author_id = int(step["agent_id"])
                delivery = self._call(
                    json.dumps({
                        "task": session.task,
                        "role": session.roles.get(str(author_id), ""),
                        "step": step,
                        "instruction": "完成该子任务并输出可直接保存的 Markdown。",
                    }, ensure_ascii=False),
                    task="collaboration_execute",
                    agent_id=author_id,
                )
                artifact = self.store.write_artifact(
                    session_id,
                    str(step["artifact"]),
                    delivery,
                    agent_id=author_id,
                )
                self.store.append_event(
                    session_id,
                    "artifact",
                    artifact["filename"],
                    agent_id=author_id,
                    metadata=artifact,
                )
                reviewer_id = next(
                    member_id
                    for member_id in session.member_ids
                    if member_id != author_id
                )
                review_raw = self._call(
                    json.dumps({
                        "task": session.task,
                        "artifact": delivery,
                        "instruction": "输出 JSON：approved 布尔值与 feedback 字符串。",
                    }, ensure_ascii=False),
                    task="collaboration_review",
                    agent_id=reviewer_id,
                )
                review = self._json(review_raw)
                approved = bool(review.get("approved", False))
                feedback = str(review.get("feedback") or review_raw).strip()
                self.store.append_event(
                    session_id,
                    "review",
                    feedback,
                    agent_id=reviewer_id,
                    metadata={"approved": approved, "artifact": artifact["filename"]},
                )
                if not approved:
                    delivery = self._call(
                        json.dumps({
                            "task": session.task,
                            "artifact": delivery,
                            "feedback": feedback,
                            "instruction": "根据审阅意见修订并输出完整 Markdown。",
                        }, ensure_ascii=False),
                        task="collaboration_revision",
                        agent_id=author_id,
                    )
                    self.store.write_artifact(
                        session_id,
                        artifact["filename"],
                        delivery,
                        agent_id=author_id,
                    )
                    self.store.append_event(
                        session_id,
                        "revision",
                        artifact["filename"],
                        agent_id=author_id,
                    )
                latest = self.store.get(session_id)
                latest.plan[latest.current_step]["status"] = "completed"
                latest.current_step += 1
                self.store.save(latest)

            session = self.store.get(session_id)
            if session.status is not SessionStatus.RUNNING:
                return
            final_text = self._call(
                json.dumps({
                    "task": session.task,
                    "plan": session.plan,
                    "artifacts": session.artifacts,
                    "instruction": "汇总团队成果，输出完整最终 Markdown。",
                }, ensure_ascii=False),
                task="collaboration_synthesis",
                agent_id=session.leader_id,
            )
            final = self.store.write_artifact(
                session_id,
                "final.md",
                final_text,
                agent_id=session.leader_id,
            )
            self.store.append_event(
                session_id,
                "artifact",
                final["filename"],
                agent_id=session.leader_id,
                metadata=final,
            )
            session = self.store.get(session_id)
            session.transition(SessionStatus.COMPLETED)
            self.store.save(session)
            self.store.append_event(session_id, "completed", "合作任务已完成")
            for agent_id in session.member_ids:
                self.episode_writer(agent_id, {
                    "source": "collaboration",
                    "session_id": session_id,
                    "kind": "cooperation",
                    "summary": session.task,
                    "artifact": "final.md",
                    "salience": 0.75,
                })
        except Exception as exc:
            self._fail(session_id, exc)
```

- [ ] **Step 4: Run cooperation tests and verify GREEN**

Run:

```bash
pytest tests/test_collaboration_cooperation.py tests/test_collaboration_models_store.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add gaworld/collaboration/cooperation.py tests/test_collaboration_cooperation.py
git commit -m "add collaborative task runner"
```

---

### Task 6: Orchestration Service and Kernel Plugin

**Files:**
- Create: `gaworld/collaboration/service.py`
- Create: `gaworld/collaboration/plugin.py`
- Modify: `gaworld/collaboration/__init__.py`
- Modify: `gaworld/plugins/__init__.py`
- Create: `tests/test_collaboration_service_plugin.py`

- [ ] **Step 1: Write failing service and plugin tests**

```python
from gaworld.collaboration.plugin import CollaborationPlugin
from gaworld.collaboration.service import CollaborationService
from gaworld.kernel import build_kernel
from gaworld.plugins import builtin_plugins


def test_service_validates_and_creates_non_background_discussion(tmp_path):
    service = CollaborationService(
        config={"discussion": {"min_rounds": 3, "max_rounds": 20}},
        sessions_dir=tmp_path / "sessions",
        memory_dir=tmp_path / "memory",
        agent_loader=lambda agent_id: {"identity": {"id": agent_id}},
        llm=lambda *a, **k: "",
        background=False,
    )
    created = service.create_discussion([1, 2], topic="", max_rounds=6)
    assert created.kind == "discussion"
    assert created.status.value == "queued"
    assert service.get_session(created.id)["member_ids"] == [1, 2]


def test_plugin_starts_and_stops_runtime(tmp_path):
    ctx = build_kernel(
        {"collaboration": {"enabled": True, "sessions_dir": str(tmp_path / "sessions")}, "memory_dir": str(tmp_path / "memory")},
        llm=lambda *a, **k: "",
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
        llm=lambda *a, **k: "",
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


def test_collaboration_is_registered_as_builtin():
    assert "collaboration" in [plugin.id for plugin in builtin_plugins()]
```

- [ ] **Step 2: Run service/plugin tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_service_plugin.py -v
```

Expected: fails because service and plugin modules do not exist.

- [ ] **Step 3: Implement `CollaborationService`**

Implement `gaworld/collaboration/service.py` with this orchestration service:

```python
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


class CollaborationService:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        sessions_dir: str | Path,
        memory_dir: str | Path,
        agent_loader: Callable[[int], dict[str, Any] | None],
        llm: Callable[..., str],
        background: bool = True,
        episode_writer: Callable[[int, dict[str, Any]], None] | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = dict(config)
        self.store = SessionStore(sessions_dir, event_sink=event_sink)
        self.agent_loader = agent_loader
        self.llm = llm
        self.background = background
        self.relationships = RelationshipService(
            memory_dir=memory_dir,
            agent_loader=agent_loader,
        )
        runner_args = {
            "store": self.store,
            "agent_loader": agent_loader,
            "llm": llm,
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
        self._guard = threading.Lock()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.store.recover_interrupted()
        if self.background:
            self._executor = ThreadPoolExecutor(
                max_workers=max(1, int(self.config.get("max_concurrent_sessions", 2))),
                thread_name_prefix="gaworld_collaboration",
            )
        self._started = True

    def shutdown(self) -> None:
        executor = self._executor
        self._executor = None
        self._started = False
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

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
        missing = [agent_id for agent_id in members if self.agent_loader(agent_id) is None]
        if missing:
            raise ValueError(f"agents not found: {missing}")
        return members

    def _submit(self, session_id: str) -> None:
        if not self.background:
            return
        if not self._started:
            self.start()
        with self._guard:
            existing = self._futures.get(session_id)
            if existing is not None and not existing.done():
                return
            if self._executor is None:
                raise RuntimeError("collaboration executor is not running")
            self._futures[session_id] = self._executor.submit(self.run_session, session_id)

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
        minimum = int(limits.get("min_rounds", 3))
        maximum = int(limits.get("max_rounds", 20))
        rounds = int(max_rounds)
        if rounds < minimum or rounds > maximum:
            raise ValueError(f"max_rounds must be between {minimum} and {maximum}")
        session = CollaborationSession.new(
            kind="discussion",
            member_ids=members,
            topic=str(topic).strip(),
            title=str(topic).strip() or "自由讨论",
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
        if leader_id is not None and int(leader_id) not in members:
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
            leader_id=int(leader_id) if leader_id is not None else None,
            role_overrides=clean_roles,
        )
        self.store.create(session)
        self.store.append_event(session.id, "created", session.title)
        self._submit(session.id)
        return session

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.store.get(session_id).to_dict()

    def list_sessions(self, *, kind: str = "", status: str = "") -> list[dict[str, Any]]:
        return [session.to_dict() for session in self.store.list(kind=kind, status=status)]

    def health(self) -> dict[str, Any]:
        return self.store.health()

    def events(self, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        return [asdict(event) for event in self.store.events(session_id, after=after)]

    def pause(self, session_id: str) -> dict[str, Any]:
        session = self.store.get(session_id)
        session.transition(SessionStatus.PAUSED)
        self.store.save(session)
        self.store.append_event(session_id, "paused", "会话已暂停")
        return session.to_dict()

    def resume(self, session_id: str) -> dict[str, Any]:
        session = self.store.get(session_id)
        session.transition(SessionStatus.RUNNING)
        session.error = ""
        self.store.save(session)
        self.store.append_event(session_id, "resumed", "会话已恢复")
        self._submit(session_id)
        return session.to_dict()

    def cancel(self, session_id: str) -> dict[str, Any]:
        session = self.store.get(session_id)
        session.transition(SessionStatus.CANCELLED)
        self.store.save(session)
        self.store.append_event(session_id, "cancelled", "会话已终止")
        return session.to_dict()

    def run_session(self, session_id: str) -> None:
        session = self.store.get(session_id)
        if session.kind == "discussion":
            self.discussion.run(session_id)
        elif session.kind == "cooperation":
            self.cooperation.run(session_id)
        else:
            raise ValueError(f"unsupported session kind: {session.kind}")
```

- [ ] **Step 4: Implement plugin lifecycle and built-in registration**

Create `gaworld/collaboration/plugin.py`:

```python
from __future__ import annotations

from pathlib import Path

from gaworld.collaboration.relationships import merge_persisted_agent_edges
from gaworld.collaboration.service import CollaborationService
from gaworld.kernel import Plugin
from gaworld.memory.experience import append_agent_episode


class CollaborationPlugin(Plugin):
    id = "collaboration"

    def setup(self, ctx) -> None:
        ctx.bus.on("on_simulation_start", self._start_service)

    def _start_service(self, hook_ctx) -> None:
        sim = hook_ctx["sim"]
        cfg = sim.config.get("collaboration", {})
        if not cfg.get("enabled", True):
            sim.plugin_state(self.id)["service"] = None
            return
        agents = {
            int(agent["id"]): agent
            for agent in hook_ctx.get("agents", sim.agents)
        }
        merge_persisted_agent_edges(list(agents.values()))
        service = CollaborationService(
            config=cfg,
            sessions_dir=Path(cfg.get("sessions_dir", "output/collaboration/sessions")),
            memory_dir=Path(sim.config.get("memory_dir", "output/memory")),
            agent_loader=lambda agent_id: agents.get(int(agent_id)),
            llm=sim.llm,
            episode_writer=lambda agent_id, episode: append_agent_episode(
                agent_id, episode, cfg=sim.config
            ),
            event_sink=lambda event: sim.bus.emit(
                "collaboration.event",
                event=event,
            ),
        )
        service.start()
        sim.plugin_state(self.id)["service"] = service

    def teardown(self, ctx) -> None:
        service = ctx.plugin_state(self.id).pop("service", None)
        if service is not None:
            service.shutdown()
```

Import `CollaborationPlugin` inside `builtin_plugins()` and add `CollaborationPlugin()` to the returned list.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
pytest tests/test_collaboration_service_plugin.py tests/test_kernel_plugin_e2e.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add gaworld/collaboration gaworld/plugins/__init__.py \
  tests/test_collaboration_service_plugin.py
git commit -m "wire collaboration service plugin"
```

---

### Task 7: Dashboard Collaboration API

**Files:**
- Modify: `gaworld/apps/dashboard_server.py`
- Create: `tests/test_dashboard_collaboration.py`

- [ ] **Step 1: Write failing API integration tests**

Use a real `ThreadingHTTPServer` bound to port zero with a temporary repository root and a fake `CollaborationService`. The tests must issue HTTP requests with `urllib.request` and assert:

```python
def test_friendship_endpoint_returns_service_result(api_server):
    payload = post_json(api_server, "/api/relationships/friends", {"agent_ids": [1, 2]})
    assert payload["created_pairs"] == [[1, 2]]


def test_discussion_create_and_incremental_events(api_server):
    created = post_json(api_server, "/api/collaboration/sessions", {
        "kind": "discussion",
        "agent_ids": [1, 2],
        "topic": "公共空间",
        "max_rounds": 6,
    })
    detail = get_json(api_server, f"/api/collaboration/sessions/{created['id']}")
    events = get_json(api_server, f"/api/collaboration/sessions/{created['id']}/events?after=1")
    assert detail["kind"] == "discussion"
    assert all(event["seq"] > 1 for event in events["events"])


def test_invalid_session_command_returns_400(api_server):
    status, payload = post_json_with_status(
        api_server,
        "/api/collaboration/sessions/missing/pause",
        {},
    )
    assert status == 400
    assert payload["error"]
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
pytest tests/test_dashboard_collaboration.py -v
```

Expected: friendship and collaboration endpoints return HTTP 404.

- [ ] **Step 3: Add a lazily created standalone service**

Add `atexit` and `threading` imports, then add:

```python
_COLLABORATION_SERVICE = None
_COLLABORATION_LOCK = threading.Lock()


def _repo_path(value):
    path = Path(str(value))
    return path if path.is_absolute() else Path(REPO_ROOT) / path


def _get_collaboration_service():
    global _COLLABORATION_SERVICE
    with _COLLABORATION_LOCK:
        if _COLLABORATION_SERVICE is not None:
            return _COLLABORATION_SERVICE
        from gaworld.collaboration.service import CollaborationService
        from gaworld.llm.providers import call_llm
        from gaworld.memory.experience import append_agent_episode

        config = _effective_config()
        collaboration = config.get("collaboration", {})
        service = CollaborationService(
            config=collaboration,
            sessions_dir=_repo_path(
                collaboration.get(
                    "sessions_dir",
                    "output/collaboration/sessions",
                )
            ),
            memory_dir=_repo_path(config.get("memory_dir", "output/memory")),
            agent_loader=lambda agent_id: _agent_detail(int(agent_id)),
            llm=call_llm,
            episode_writer=lambda agent_id, episode: append_agent_episode(
                agent_id,
                episode,
                cfg=config,
            ),
        )
        service.start()
        _COLLABORATION_SERVICE = service
        return service


def _reset_collaboration_service_for_tests():
    global _COLLABORATION_SERVICE
    with _COLLABORATION_LOCK:
        service = _COLLABORATION_SERVICE
        _COLLABORATION_SERVICE = None
    if service is not None:
        service.shutdown()


atexit.register(_reset_collaboration_service_for_tests)


def _public_collaboration_session(payload):
    result = deepcopy(payload)
    config = _effective_config().get("collaboration", {})
    sessions_dir = _repo_path(
        config.get("sessions_dir", "output/collaboration/sessions")
    ).resolve()
    try:
        public_root = "/" + sessions_dir.relative_to(Path(REPO_ROOT).resolve()).as_posix()
    except ValueError:
        public_root = ""
    for artifact in result.get("artifacts", []):
        rel_path = str(artifact.get("path") or "")
        if public_root and rel_path and ".." not in Path(rel_path).parts:
            artifact["url"] = f"{public_root}/{result['id']}/{rel_path}"
    return result
```

- [ ] **Step 4: Add thin routes**

Add before the unknown-endpoint return in `_handle_api_get()`:

```python
        if path == "/api/collaboration/sessions":
            service = _get_collaboration_service()
            kind = (query.get("kind") or [""])[0]
            status = (query.get("status") or [""])[0]
            sessions = service.list_sessions(kind=kind, status=status)
            return self._json_response({
                "sessions": [_public_collaboration_session(item) for item in sessions],
                "health": service.health(),
            })
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:3] == ["api", "collaboration", "sessions"]:
            session = _get_collaboration_service().get_session(parts[3])
            return self._json_response(_public_collaboration_session(session))
        if (
            len(parts) == 5
            and parts[:3] == ["api", "collaboration", "sessions"]
            and parts[4] == "events"
        ):
            after = int((query.get("after") or [0])[0])
            events = _get_collaboration_service().events(parts[3], after=after)
            return self._json_response({"events": events})
```

Add before the unknown-endpoint return in `_handle_api_post()`:

```python
        if path == "/api/relationships/friends":
            return self._json_response(
                _get_collaboration_service().make_friends(payload.get("agent_ids", []))
            )
        if path == "/api/collaboration/sessions":
            service = _get_collaboration_service()
            kind = str(payload.get("kind") or "")
            if kind == "discussion":
                session = service.create_discussion(
                    payload.get("agent_ids", []),
                    topic=str(payload.get("topic") or ""),
                    max_rounds=int(payload.get("max_rounds", 6)),
                )
            elif kind == "cooperation":
                session = service.create_cooperation(
                    payload.get("agent_ids", []),
                    task=str(payload.get("task") or ""),
                    leader_id=payload.get("leader_id"),
                    role_overrides=payload.get("role_overrides"),
                )
            else:
                raise ValueError("kind must be discussion or cooperation")
            return self._json_response(_public_collaboration_session(session.to_dict()))
        parts = path.strip("/").split("/")
        if (
            len(parts) == 5
            and parts[:3] == ["api", "collaboration", "sessions"]
            and parts[4] in {"pause", "resume", "cancel"}
        ):
            service = _get_collaboration_service()
            result = getattr(service, parts[4])(parts[3])
            return self._json_response(_public_collaboration_session(result))
```

In both `do_GET()` and `do_POST()`, add this exception branch before the existing generic branch:

```python
        except (ValueError, KeyError) as exc:
            return self._json_response({"error": str(exc)}, status=400)
```

Keep all domain work in `CollaborationService`.

- [ ] **Step 5: Run API tests and verify GREEN**

Run:

```bash
pytest tests/test_dashboard_collaboration.py tests/test_dashboard_studio.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add gaworld/apps/dashboard_server.py tests/test_dashboard_collaboration.py
git commit -m "expose collaboration dashboard api"
```

---

### Task 8: Dashboard Friendship and Discussion Panel

**Files:**
- Create: `site/dashboard/collaboration-core.js`
- Create: `site/dashboard/interaction.js`
- Create: `site/dashboard/interaction.css`
- Create: `site/dashboard/collaboration-core.test.js`
- Modify: `site/dashboard/index.html`
- Modify: `site/dashboard/locales/zh-CN.json`
- Modify: `site/dashboard/locales/en.json`
- Create: `tests/test_collaboration_frontend.py`

- [ ] **Step 1: Inspect the existing Dashboard diff**

Run:

```bash
git diff -- site/dashboard/index.html site/dashboard/app.js
```

Expected: user-owned changes are visible. Record the exact insertion point and do not alter `site/dashboard/app.js`.

- [ ] **Step 2: Write failing pure-JavaScript tests**

`site/dashboard/collaboration-core.test.js`:

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("./collaboration-core.js");

test("discussion payload normalizes unique numeric members", () => {
  assert.deepEqual(
    core.discussionPayload(["2", 1, "2"], "议题", 6),
    { kind: "discussion", agent_ids: [2, 1], topic: "议题", max_rounds: 6 },
  );
});

test("terminal sessions stop polling", () => {
  assert.equal(core.shouldPoll({ status: "running" }), true);
  assert.equal(core.shouldPoll({ status: "completed" }), false);
  assert.equal(core.shouldPoll({ status: "cancelled" }), false);
});
```

`tests/test_collaboration_frontend.py` must run `node --test site/dashboard/collaboration-core.test.js` and assert exit code zero. It must also assert that `interaction.js` uses `textContent` for event content and does not interpolate event content into `innerHTML`.

- [ ] **Step 3: Run frontend tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_frontend.py -v
```

Expected: fails because the frontend collaboration files do not exist.

- [ ] **Step 4: Implement pure helpers and interaction controller**

`collaboration-core.js` uses this UMD implementation:

```javascript
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.GAWorldCollaborationCore = api;
}(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  function normalizeAgentIds(values) {
    const result = [];
    (values || []).forEach(function (raw) {
      const value = Number(raw);
      if (Number.isInteger(value) && value > 0 && !result.includes(value)) result.push(value);
    });
    return result;
  }

  function discussionPayload(values, topic, maxRounds) {
    return {
      kind: "discussion",
      agent_ids: normalizeAgentIds(values),
      topic: String(topic || "").trim(),
      max_rounds: Number(maxRounds),
    };
  }

  function cooperationPayload(values, task, leaderId, roles) {
    const payload = {
      kind: "cooperation",
      agent_ids: normalizeAgentIds(values),
      task: String(task || "").trim(),
      role_overrides: Object.assign({}, roles || {}),
    };
    const leader = Number(leaderId);
    if (Number.isInteger(leader) && leader > 0) payload.leader_id = leader;
    return payload;
  }

  function shouldPoll(session) {
    return Boolean(
      session &&
      ["queued", "running", "paused", "failed", "interrupted"].includes(session.status)
    );
  }

  return {
    normalizeAgentIds,
    discussionPayload,
    cooperationPayload,
    shouldPoll,
  };
}));
```

`interaction.js` must independently load `/api/agents`, render keyboard-focusable member chips, require at least two selected members, call the friendship endpoint, create discussion sessions, poll events once per second using the last sequence number, and render speaker/content with DOM nodes and `textContent`. It must stop polling in terminal states or when `document.hidden`, resume on `visibilitychange`, and expose pause/resume/cancel controls based on current status.

- [ ] **Step 5: Mount and style the panel**

Add `interaction.css` after `styles.css`, add an **智能体互动** panel near the existing interview panel, and load scripts in this order:

```html
<script src="/site/dashboard/i18n.js"></script>
<script src="/site/dashboard/collaboration-core.js"></script>
<script src="/site/dashboard/citymap-view.js?v=1"></script>
<script src="/site/dashboard/app.js?v=4"></script>
<script src="/site/dashboard/interaction.js"></script>
```

Add matching, identically ordered Chinese and English locale keys for member selection, friendship, topic, rounds, start, pause, resume, cancel, discussion status, and empty transcript.

- [ ] **Step 6: Run frontend and i18n tests**

Run:

```bash
pytest tests/test_collaboration_frontend.py tests/test_i18n.py tests/test_i18n_js.py -v
node --check site/dashboard/interaction.js
```

Expected: all tests and syntax checks pass.

- [ ] **Step 7: Commit only the additive Dashboard files and hunks**

```bash
git add -p site/dashboard/index.html
git add site/dashboard/collaboration-core.js site/dashboard/interaction.js \
  site/dashboard/interaction.css site/dashboard/collaboration-core.test.js \
  site/dashboard/locales/zh-CN.json site/dashboard/locales/en.json \
  tests/test_collaboration_frontend.py
git diff --cached --check
git commit -m "add dashboard agent interactions"
```

Confirm the staged hunk in `index.html` contains only the interaction panel and asset tags.

---

### Task 9: Cooperation Task Tab

**Files:**
- Create: `site/dashboard/collaboration.html`
- Create: `site/dashboard/collaboration.js`
- Create: `site/dashboard/collaboration.css`
- Modify: `site/console/index.html`
- Modify: `site/console/console.js`
- Modify: `site/console/console.css`
- Modify: `tests/test_collaboration_frontend.py`

- [ ] **Step 1: Add failing shell and page tests**

Add assertions that:

```python
def test_console_registers_cooperation_tab():
    html = read("site/console/index.html")
    js = read("site/console/console.js")
    assert 'data-tab="collaboration"' in html
    assert '{ id: "collaboration", src: "/site/dashboard/collaboration.html" }' in js


def test_cooperation_page_has_required_controls():
    html = read("site/dashboard/collaboration.html")
    for element_id in (
        "taskInput",
        "memberPicker",
        "leaderSelect",
        "startTaskBtn",
        "sessionList",
        "taskPlan",
        "activityFeed",
        "artifactList",
    ):
        assert f'id="{element_id}"' in html
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest tests/test_collaboration_frontend.py -v
```

Expected: fails because the tab and page are missing.

- [ ] **Step 3: Build the cooperation page**

`collaboration.html` must include:

- a task textarea;
- multi-select member cards with capability hints;
- leader select and optional role inputs;
- session-history list;
- plan/progress area;
- member-role cards;
- activity feed with `aria-live="polite"`;
- artifact list;
- pause, resume, and cancel buttons.

`collaboration.js` must use `GAWorldCollaborationCore.cooperationPayload`, load agents and sessions, create cooperation sessions, reopen history entries, incrementally poll events, update plan/progress from the session snapshot, render all external text through `textContent`, and link artifacts only to server-returned session-scoped paths.

`collaboration.css` must use the current green/paper/steel variables, a three-column desktop grid, visible focus states, status text in addition to color, and a single-column layout below 900px.

- [ ] **Step 4: Register the tab**

Add:

```html
<button class="tab" role="tab" data-tab="collaboration">
  合作任务<span class="en">Collaboration</span>
</button>
```

Add to `TABS`:

```javascript
{ id: "collaboration", src: "/site/dashboard/collaboration.html" },
```

At widths below 860px, allow `.console-bar` horizontal scrolling and keep `.tabs` from shrinking so all four tabs remain reachable.

- [ ] **Step 5: Run tests and syntax checks**

Run:

```bash
pytest tests/test_collaboration_frontend.py -v
node --check site/dashboard/collaboration-core.js
node --check site/dashboard/collaboration.js
node --check site/console/console.js
```

Expected: all tests and checks pass.

- [ ] **Step 6: Commit**

```bash
git add site/dashboard/collaboration.html site/dashboard/collaboration.js \
  site/dashboard/collaboration.css site/console/index.html \
  site/console/console.js site/console/console.css \
  tests/test_collaboration_frontend.py
git commit -m "add cooperation task console tab"
```

---

### Task 10: End-to-End Verification and Documentation

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `docs/PROJECT_STRUCTURE.md`
- Modify: `tests/test_dashboard_collaboration.py`

- [ ] **Step 1: Add a failing independent-mode smoke test**

Add a test that creates a standalone `CollaborationService(background=False)` without a kernel context, uses a deterministic fake LLM, creates friendship, completes a three-turn discussion, completes a two-member cooperation task, reopens a fresh service against the same directory, and asserts that relationships, transcripts, final artifacts, and completed session status remain readable.

- [ ] **Step 2: Run the smoke test and verify RED or existing GREEN**

Run:

```bash
pytest tests/test_dashboard_collaboration.py::test_standalone_service_persists_all_three_user_flows -v
```

Expected: if any integration seam is incomplete, the test fails at that seam; otherwise it passes and proves the already test-driven parts compose correctly.

- [ ] **Step 3: Fix only the failing integration seam**

Keep fixes within `gaworld/collaboration/` or the thin Dashboard service factory. Do not add new behavior beyond the approved design. Re-run the single smoke test after each fix until it passes.

- [ ] **Step 4: Document the feature**

Add to `docs/FEATURES.md`:

- Dashboard reciprocal friendship;
- independent observable discussion sessions;
- the cooperation task lifecycle and artifact directory;
- pause, resume, cancel, and interrupted-session recovery.

Add `gaworld/collaboration/` and the **合作任务** page to `docs/PROJECT_STRUCTURE.md`.

- [ ] **Step 5: Run focused backend and frontend suites**

```bash
pytest \
  tests/test_collaboration_models_store.py \
  tests/test_collaboration_relationships.py \
  tests/test_collaboration_discussion.py \
  tests/test_collaboration_cooperation.py \
  tests/test_collaboration_service_plugin.py \
  tests/test_dashboard_collaboration.py \
  tests/test_collaboration_frontend.py -v
```

Expected: all collaboration tests pass.

- [ ] **Step 6: Run complete verification**

```bash
pytest tests
ruff check .
ruff format --check gaworld tests
mypy gaworld
node --check site/dashboard/interaction.js
node --check site/dashboard/collaboration.js
```

Expected: all commands pass. If pre-existing failures occur, record the exact command and distinguish them from collaboration regressions.

- [ ] **Step 7: Perform local browser acceptance**

Start:

```bash
python -m gaworld.apps.dashboard_server --port 8766
```

Verify at `http://127.0.0.1:8766/`:

1. select three agents and establish all reciprocal friendship pairs;
2. start a free discussion, observe messages, pause, resume, and finish;
3. start a topic discussion and confirm the topic remains visible;
4. open **合作任务**, select members, create a task, and observe roles, plan, progress, review, and `final.md`;
5. refresh both pages and confirm the histories remain visible;
6. stop the server during a running test session, restart it, and confirm the session appears interrupted and can resume.

Use a test-only fake LLM injection or locally configured non-network provider for acceptance; do not consume remote API quota.

- [ ] **Step 8: Inspect the final diff and commit**

```bash
git diff --check
git status --short
git diff --stat
git add docs/FEATURES.md docs/PROJECT_STRUCTURE.md \
  tests/test_dashboard_collaboration.py gaworld/collaboration
git diff --cached --check
git commit -m "document agent collaboration workflows"
```

Before committing, confirm no `output/`, `.superpowers/`, `dashboard_config.json`, `data/news_cache.json`, `website/`, or unrelated user-owned changes are staged.
