"""Disk-backed registry for Skill files (global + per-agent private).

The registry is lazy: it scans directories the first time it's asked
for a slice, then re-scans on demand via :meth:`reload`. Lookups
prefer private skills over global ones when ids collide, mirroring
how a real person trusts their own learnt habit over a textbook.

Both directories are resolved through :data:`gaworld.settings.CONFIG`
so tests can point at a tmp_path. Defaults:

* global  → ``data/skills``
* private → ``{memory_dir}/agent_{id}_skills``
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG
from gaworld.skills.schemas import (
    Skill,
    dump_skill_markdown,
    parse_skill_markdown,
    slugify_skill_id,
)

_LOG = get_logger("gaworld.skills.registry")

_DEFAULT_GLOBAL_DIR = "data/skills"


def _skills_config() -> dict[str, Any]:
    return (CONFIG.get("skills", {}) or {}) if isinstance(CONFIG, dict) else {}


def _memory_dir() -> str:
    return str(CONFIG.get("memory_dir", "output/memory"))


class SkillRegistry:
    """Read/write surface over the global library + per-agent skills."""

    def __init__(
        self,
        *,
        global_dir: str | None = None,
        memory_dir: str | None = None,
    ) -> None:
        cfg = _skills_config()
        self.global_dir: str = global_dir or str(cfg.get("global_dir") or _DEFAULT_GLOBAL_DIR)
        self.memory_dir: str = memory_dir or _memory_dir()
        self._global: dict[str, Skill] = {}
        self._private: dict[int, dict[str, Skill]] = {}
        self._loaded_global = False
        self._loaded_private: set[int] = set()

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------
    def _load_dir(self, directory: str, *, source: str, owner: int | None) -> dict[str, Skill]:
        out: dict[str, Skill] = {}
        if not directory or not os.path.isdir(directory):
            return out
        try:
            entries = sorted(os.listdir(directory))
        except OSError as exc:
            _LOG.warning("skill dir unreadable %s: %s", directory, exc)
            return out
        for name in entries:
            if not name.endswith(".md") or name.startswith("."):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
            except OSError as exc:
                _LOG.warning("skill unreadable %s: %s", path, exc)
                continue
            skill_id = name[:-3]
            try:
                skill = parse_skill_markdown(skill_id, raw)
            except Exception as exc:
                _LOG.warning("skill parse failed %s: %s", path, exc)
                continue
            # Frontmatter source/owner override what the directory implies,
            # but we backfill from context when the file is silent.
            skill.source = skill.source or source  # type: ignore[assignment]
            if owner is not None and skill.owner_agent_id is None:
                skill.owner_agent_id = owner
            out[skill.skill_id] = skill
        return out

    def _ensure_global(self) -> None:
        if self._loaded_global:
            return
        self._global = self._load_dir(self.global_dir, source="global", owner=None)
        self._loaded_global = True

    def _ensure_private(self, agent_id: int) -> None:
        if agent_id in self._loaded_private:
            return
        directory = self._private_dir(agent_id)
        self._private[agent_id] = self._load_dir(directory, source="private", owner=agent_id)
        self._loaded_private.add(agent_id)

    def _private_dir(self, agent_id: int) -> str:
        return os.path.join(self.memory_dir, f"agent_{int(agent_id)}_skills")

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """Drop caches so the next access re-reads disk."""
        self._global = {}
        self._private = {}
        self._loaded_global = False
        self._loaded_private = set()

    def list_global(self) -> list[Skill]:
        self._ensure_global()
        return list(self._global.values())

    def list_private(self, agent_id: int) -> list[Skill]:
        self._ensure_private(int(agent_id))
        return list(self._private.get(int(agent_id), {}).values())

    def list_for_agent(self, agent: dict[str, Any] | int) -> list[Skill]:
        """All skills available to one agent: attached global + private.

        ``agent`` may be either an Agent dict (we read ``skill_ids``)
        or a bare agent_id (we return *all* private skills they own
        but no global skills, since attachment is unknown).
        """
        if isinstance(agent, int):
            return self.list_private(agent)
        agent_id = int(agent.get("id", 0) or 0)
        if not agent_id:
            return []
        attached_ids = [str(s) for s in (agent.get("skill_ids") or []) if str(s).strip()]
        out: list[Skill] = []
        seen: set[str] = set()
        # Private first — they outrank a global with the same id.
        for skill in self.list_private(agent_id):
            if skill.skill_id in seen:
                continue
            out.append(skill)
            seen.add(skill.skill_id)
        if attached_ids:
            self._ensure_global()
            for skill_id in attached_ids:
                if skill_id in seen:
                    continue
                skill = self._global.get(skill_id)
                if skill is not None:
                    out.append(skill)
                    seen.add(skill_id)
        return out

    def get(self, skill_id: str, *, agent_id: int | None = None) -> Skill | None:
        """Look up by id. If ``agent_id`` is given, private wins."""
        if agent_id is not None:
            self._ensure_private(int(agent_id))
            cached = self._private.get(int(agent_id), {}).get(skill_id)
            if cached is not None:
                return cached
        self._ensure_global()
        return self._global.get(skill_id)

    # ------------------------------------------------------------------
    # Public write API (private only — we never overwrite curated globals).
    # ------------------------------------------------------------------
    def save_private(self, agent_id: int, skill: Skill) -> Skill:
        """Persist a private skill and return the stored copy.

        The id is normalised through :func:`slugify_skill_id`; if a
        skill with that id already exists for this agent, the body and
        metadata are overwritten in place.
        """
        agent_id = int(agent_id)
        if not skill.skill_id:
            skill.skill_id = slugify_skill_id(skill.name, fallback=f"agent{agent_id}-skill")
        skill.source = "private"
        skill.owner_agent_id = agent_id

        directory = self._private_dir(agent_id)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{skill.skill_id}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump_skill_markdown(skill))

        self._ensure_private(agent_id)
        self._private.setdefault(agent_id, {})[skill.skill_id] = skill
        return skill

    def attach_to_agent(self, agent: dict[str, Any], skill_id: str) -> bool:
        """Add a global skill to the agent's ``skill_ids`` list."""
        if not isinstance(agent, dict):
            return False
        skill_id = str(skill_id).strip()
        if not skill_id:
            return False
        ids = list(agent.setdefault("skill_ids", []))
        if skill_id in ids:
            return False
        # Verify the skill exists in the global library — silent attach
        # of an unknown id would just create a dangling reference.
        self._ensure_global()
        if skill_id not in self._global:
            return False
        ids.append(skill_id)
        agent["skill_ids"] = ids
        return True

    def detach_from_agent(self, agent: dict[str, Any], skill_id: str) -> bool:
        if not isinstance(agent, dict):
            return False
        ids = list(agent.get("skill_ids") or [])
        if skill_id not in ids:
            return False
        ids.remove(skill_id)
        agent["skill_ids"] = ids
        return True


# Module-level default — created lazily so importing this file does not
# walk the disk. Tests can pass their own registry.
_DEFAULT_REGISTRY: SkillRegistry | None = None


def get_default_registry() -> SkillRegistry:
    """Return a process-wide registry instance, creating it on first use."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = SkillRegistry()
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Drop the module-level cache (mainly for tests)."""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None


def iter_global_skill_ids(registry: SkillRegistry | None = None) -> Iterable[str]:
    reg = registry or get_default_registry()
    for skill in reg.list_global():
        yield skill.skill_id


__all__ = [
    "SkillRegistry",
    "get_default_registry",
    "iter_global_skill_ids",
    "reset_default_registry",
]
