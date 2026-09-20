"""Experiment and world specifications, plus the per-world config overrides.

An *experiment* is a set of worlds that share everything except what happens
in them. Sharing is the point: the seed, the cohort, the horizon and the model
are fixed across worlds so any divergence at the end is attributable to the
events, not to sampling noise. What a world is free to change is its event
list and — for policy-shaped questions rather than incident-shaped ones — a
patch on the simulation config.

The override builder is deliberately the *only* place that knows how a world
is isolated on disk. Every path a run writes to (memory, logs, state, vector
db, visualization) is redirected under the world's own directory, because two
worlds sharing a memory dir would silently contaminate each other's history —
the failure mode looks like "the intervention had no effect", which is exactly
the answer the experiment is supposed to produce honestly.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

#: Config keys a world patch may never set. These are the knobs that make the
#: comparison valid (seed, horizon, cohort) or that isolate worlds on disk;
#: letting a per-world patch touch them would produce a diff nobody can read.
RESERVED_CONFIG_KEYS: frozenset[str] = frozenset({
    "random_seed",
    "sim_days",
    "agent_ids",
    "memory_dir",
    "log_dir",
    "vector_db_path",
    "state_output_dir",
    "network_output_dir",
    "environment_output_dir",
    "diary_output_dir",
    "policy_events",
    "visualization",
    "distributed",
    "stateful",
})

_SLUG_RE = re.compile(r"[^0-9A-Za-z一-鿿]+")
_ID_RE = re.compile(r"[^0-9A-Za-z_-]+")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def slugify(text: str, *, fallback: str = "experiment", limit: int = 40) -> str:
    cleaned = _SLUG_RE.sub("_", str(text or "").strip()).strip("_")
    return cleaned[:limit] if cleaned else fallback


def _world_id(text: str, index: int) -> str:
    cleaned = _ID_RE.sub("-", str(text or "").strip()).strip("-").lower()
    return cleaned[:32] if cleaned else f"w{index + 1}"


@dataclass
class WorldSpec:
    """One branch of an experiment: a label, its events, its config patch."""

    id: str
    label: str
    events: list[dict[str, Any]] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "events": [dict(item) for item in self.events],
            "config": dict(self.config),
            "note": self.note,
        }


@dataclass
class ExperimentSpec:
    """A set of worlds plus the settings every world shares."""

    name: str
    worlds: list[WorldSpec]
    baseline_id: str
    sim_days: int | None = None
    agent_ids: list[int] = field(default_factory=list)
    seed: int = 42
    llm_provider: str | None = None
    fast: bool = False
    max_parallel: int = 2
    note: str = ""

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def world(self, world_id: str) -> WorldSpec | None:
        for item in self.worlds:
            if item.id == world_id:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "note": self.note,
            "sim_days": self.sim_days,
            "agent_ids": list(self.agent_ids),
            "seed": self.seed,
            "llm_provider": self.llm_provider,
            "fast": self.fast,
            "max_parallel": self.max_parallel,
            "baseline_id": self.baseline_id,
            "worlds": [item.to_dict() for item in self.worlds],
        }


def _int_or_none(value: Any, label: str, *, minimum: int | None = None) -> int | None:
    if value in ("", None):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须是整数")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} 不能小于 {minimum}")
    return number


def normalize_event(raw: Any, *, where: str) -> dict[str, Any]:
    """Coerce one event into the ``policy_events`` shape the simulator reads."""
    if not isinstance(raw, dict):
        raise ValueError(f"{where}：事件必须是对象")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ValueError(f"{where}：事件缺少名称")
    day = _int_or_none(raw.get("day"), f"{where}·{name} 的 day", minimum=1)
    if day is None:
        raise ValueError(f"{where}·{name}：缺少事件日 day")
    time_value = str(raw.get("time", "10:00")).strip() or "10:00"
    if not _TIME_RE.match(time_value):
        raise ValueError(f"{where}·{name}：时间需要形如 09:30")
    return {
        "day": day,
        "time": time_value,
        "name": name,
        "description": str(raw.get("description", "")).strip(),
    }


def sanitize_world_config(raw: Any, *, where: str) -> dict[str, Any]:
    """Drop reserved keys from a per-world config patch.

    Rejecting rather than silently dropping: a user who typed ``random_seed``
    into a world patch is trying to do something the experiment design cannot
    honour, and a quiet drop would hand them a report that looks fine.
    """
    if raw in (None, "", {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{where}：config 必须是对象")
    conflicts = sorted(set(raw) & RESERVED_CONFIG_KEYS)
    if conflicts:
        raise ValueError(
            f"{where}：config 不能覆盖实验级设置 {', '.join(conflicts)}（它们是各世界之间的对照基准）"
        )
    return dict(raw)


def normalize_experiment(payload: Any) -> ExperimentSpec:
    """Validate a browser/CLI payload into an :class:`ExperimentSpec`."""
    if not isinstance(payload, dict):
        raise ValueError("实验定义必须是对象")

    raw_worlds = payload.get("worlds")
    if not isinstance(raw_worlds, list) or len(raw_worlds) < 2:
        raise ValueError("至少需要 2 个平行世界才能比较")
    if len(raw_worlds) > 8:
        raise ValueError("一次最多比较 8 个平行世界")

    worlds: list[WorldSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_worlds):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index + 1} 个世界必须是对象")
        label = str(raw.get("label", "")).strip() or f"世界 {index + 1}"
        world_id = _world_id(raw.get("id") or label, index)
        if world_id in seen:
            world_id = f"{world_id}-{index + 1}"
        seen.add(world_id)
        where = f"世界「{label}」"
        events = [
            normalize_event(item, where=where)
            for item in (raw.get("events") or [])
        ]
        events.sort(key=lambda item: (item["day"], item["time"]))
        worlds.append(
            WorldSpec(
                id=world_id,
                label=label,
                events=events,
                config=sanitize_world_config(raw.get("config"), where=where),
                note=str(raw.get("note", "")).strip(),
            )
        )

    baseline_id = str(payload.get("baseline_id", "")).strip()
    if baseline_id and baseline_id not in seen:
        raise ValueError(f"基准世界 {baseline_id} 不在世界列表中")
    if not baseline_id:
        # Default to the first world with no events — that is what "baseline"
        # means here — and fall back to the first world when every world has
        # events (a design where all branches are interventions is legitimate).
        empty = [item.id for item in worlds if not item.events]
        baseline_id = empty[0] if empty else worlds[0].id

    agent_ids: list[int] = []
    for value in payload.get("agent_ids") or []:
        number = _int_or_none(value, "agent_ids 中的元素")
        if number is not None:
            agent_ids.append(number)

    return ExperimentSpec(
        name=str(payload.get("name", "")).strip() or "平行世界实验",
        note=str(payload.get("note", "")).strip(),
        worlds=worlds,
        baseline_id=baseline_id,
        sim_days=_int_or_none(payload.get("sim_days"), "sim_days", minimum=1),
        agent_ids=agent_ids,
        seed=_int_or_none(payload.get("seed"), "seed") or 42,
        llm_provider=(str(payload.get("llm_provider")).strip() or None)
        if payload.get("llm_provider")
        else None,
        fast=bool(payload.get("fast")),
        max_parallel=max(1, min(4, _int_or_none(payload.get("max_parallel"), "max_parallel") or 2)),
    )


def world_overrides(
    spec: ExperimentSpec,
    world: WorldSpec,
    world_dir: str,
    *,
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Config overrides that isolate ``world`` on disk and inject its events.

    ``base_config`` supplies the ambient ``policy_events`` (events already
    configured for every run) and the LLM routing table used when the
    experiment forces one provider. It is optional so tests and the CLI can
    build overrides without importing the simulator.
    """
    base_config = base_config or {}
    ambient = [
        dict(item)
        for item in base_config.get("policy_events", [])
        if isinstance(item, dict)
    ]
    overrides: dict[str, Any] = {
        "memory_dir": os.path.join(world_dir, "memory"),
        "log_dir": os.path.join(world_dir, "logs"),
        "vector_db_path": os.path.join(world_dir, "memory", "vector_db.sqlite"),
        "state_output_dir": os.path.join(world_dir, "state"),
        "network_output_dir": os.path.join(world_dir, "network"),
        "environment_output_dir": os.path.join(world_dir, "environment"),
        # `reset` clears the diary and life-event directories too. Left at
        # their defaults they point at the shared `output/` tree, so forking a
        # world would wipe the operator's live diaries and queued life events.
        "diary_output_dir": os.path.join(world_dir, "diaries"),
        "life_events": {"event_dir": os.path.join(world_dir, "life_events")},
        "intervention": {"output_dir": os.path.join(world_dir, "intervention")},
        "visualization": {
            "enabled": True,
            "output_dir": os.path.join(world_dir, "visualization"),
            "site_path": base_config.get("visualization", {}).get(
                "site_path", "site/simviz/index.html"
            ),
        },
        "policy_events": ambient + [dict(item) for item in world.events],
        "stateful": True,
        "random_seed": int(spec.seed),
        "distributed": {"enabled": False},
    }

    if spec.sim_days is not None:
        overrides["sim_days"] = int(spec.sim_days)
    if spec.agent_ids:
        overrides["agent_ids"] = list(spec.agent_ids)

    if spec.fast:
        # Same trade as ``compare-event --fast``: fewer LLM calls per agent-day
        # so a local model can cover a longer horizon, at the cost of fidelity.
        overrides["fos_fast_mode"] = {
            "deterministic_cognition": True,
            "skip_daily_summary": True,
            "skip_daily_diary": True,
        }
        overrides.setdefault("agent_ids", [1, 2, 3])

    if spec.llm_provider:
        routing = base_config.get("llm", {}).get("routing", {})
        task_map = routing.get("tasks", {})
        forced = (
            {str(key): str(spec.llm_provider) for key in task_map}
            if isinstance(task_map, dict)
            else {}
        )
        overrides["llm"] = {
            "routing": {"default": str(spec.llm_provider), "tasks": forced}
        }

    # World-level patch last: it is the thing the experiment is varying, so it
    # wins over the shared defaults above (minus the reserved keys, which
    # `sanitize_world_config` already rejected).
    for key, value in world.config.items():
        if isinstance(value, dict) and isinstance(overrides.get(key), dict):
            merged = dict(overrides[key])
            merged.update(value)
            overrides[key] = merged
        else:
            overrides[key] = value
    return overrides


__all__ = [
    "RESERVED_CONFIG_KEYS",
    "ExperimentSpec",
    "WorldSpec",
    "normalize_event",
    "normalize_experiment",
    "sanitize_world_config",
    "slugify",
    "world_overrides",
]
