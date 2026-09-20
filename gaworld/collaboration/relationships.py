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
from gaworld.social.network import ensure_relationship_schema, role_config


class RelationshipService:
    def __init__(
        self,
        *,
        memory_dir: str | Path,
        agent_loader: Callable[[int], dict[str, Any] | None],
    ) -> None:
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
            loaded: dict[int, dict[str, Any]] = {}
            stamp = utc_now()
            for left, right in combinations(ids, 2):
                for source, target in ((left, right), (right, left)):
                    relationships = loaded.setdefault(
                        source,
                        self._load(self._path(source)),
                    )
                    record = relationships.get(str(target))
                    if isinstance(record, dict):
                        record["last_dashboard_interaction_at"] = stamp
                        changed[source] = relationships
            for agent_id, relationships in changed.items():
                self._atomic_write(self._path(agent_id), relationships)

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid relationship file: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"relationship file must contain a JSON object: {path}")
        return payload

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
            str(record.get("role") or "") not in {"", "acquaintance"}
            and float(record.get("closeness", 0.0)) >= 0.65
            and float(record.get("trust", 0.0)) >= 0.60
            and float(record.get("obligation", 0.0)) >= 0.40
            and float(record.get("friction", 1.0)) <= 0.10
        )

    def _promote(self, record: dict[str, Any], peer: dict[str, Any]) -> dict[str, Any]:
        if not record:
            record.update(
                {
                    "closeness": 0.65,
                    "trust": 0.60,
                    "obligation": 0.40,
                    "friction": 0.10,
                }
            )
        existing_role = str(record.get("role") or "")
        role = "friend" if existing_role in {"", "acquaintance"} else existing_role
        ensure_relationship_schema(record, role=role, kind="agent", tie_origin="dashboard")
        record["kind"] = "agent"
        record["role"] = role
        if existing_role in {"", "acquaintance"}:
            defaults = role_config(role)
            record["channels"] = list(defaults["channels"])
            record["decay_rate"] = float(defaults["decay_rate"])
            record["obligation_base"] = float(defaults["obligation_base"])
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
        result: dict[str, list[list[int]]] = {
            "created_pairs": [],
            "updated_pairs": [],
            "existing_pairs": [],
        }
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

        attempted: list[int] = []
        try:
            for agent_id in ids:
                attempted.append(agent_id)
                self._atomic_write(paths[agent_id], relationships[agent_id])
        except Exception:
            for agent_id in reversed(attempted):
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
    for agent in agents:
        if not isinstance(agent.get("social_neighbors"), list):
            agent["social_neighbors"] = []
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
