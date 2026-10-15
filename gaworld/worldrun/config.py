"""Authoritative output-isolation definitions for world runs.

ONE implementation of the reserved-key set and the run-root override key
table. The parallel-worlds runner (``gaworld.parallel.spec``) and the SimTree
branch launcher (``fos.backend.services.simtree_gaworld``) both import from
here — a per-world patch may never move a run's output back into the shared
tree, and that invariant is enforced from a single definition.
"""

from __future__ import annotations

from typing import Any

from gaworld.city.config import RUN_PATHS, run_root_overrides

#: Config keys a world patch may never set. These are the knobs that make a
#: comparison valid (seed, horizon, cohort) or that isolate worlds on disk.
#: The flat leaves of :data:`gaworld.city.config.RUN_PATHS` are all reserved:
#: each one names a top-level config key a run redirects under its own root.
RESERVED_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        # comparison knobs
        "random_seed",
        "sim_days",
        "agent_ids",
        "policy_events",
        "stateful",
        # flat RUN_PATHS leaves (output isolation)
        "run_output_dir",
        "memory_dir",
        "vector_db_path",
        "log_dir",
        "state_output_dir",
        "network_output_dir",
        "environment_output_dir",
        "diary_output_dir",
        "agent_import_output_dir",
        # namespaced RUN_PATHS handled per-key, reserved as whole sections
        "visualization",
        "distributed",
    }
)

#: ``output_root`` is the root itself but is excluded from the reserved set:
#: historical configs carry it and :func:`run_root_overrides` re-pins it.
_RESERVED_EXCLUDED = {"output_root"}

#: Every dotted RUN_PATHS key (``economy.output_dir`` …) that a nested patch
#: also may not set. Re-pinning after the patch catches drift, but a loud
#: rejection is the honest answer.
RESERVED_DOTTED_KEYS: frozenset[str] = frozenset(RUN_PATHS) - _RESERVED_EXCLUDED


class ReservedOverrideError(ValueError):
    """A world patch tried to set a reserved / output-isolation key."""


def _dotted_path(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else str(key)


def validate_world_overrides(config: Any, *, where: str = "world") -> None:
    """Reject — loudly — a world patch that touches reserved keys.

    Two rules, both enforced from this one module:

    - a top-level key in :data:`RESERVED_CONFIG_KEYS` is rejected by name;
    - any nested leaf whose dotted path is in :data:`RESERVED_DOTTED_KEYS`
      (the RUN_PATHS table) is rejected, because it would move part of the
      run's output back into the shared tree.
    """
    if not isinstance(config, dict):
        return
    conflicts = sorted(set(config) & RESERVED_CONFIG_KEYS)
    if conflicts:
        raise ReservedOverrideError(
            f"{where}: config 不能覆盖实验级设置 {', '.join(conflicts)}"
            f"（它们是各世界之间的对照基准）"
        )
    for key, value in config.items():
        path = _dotted_path("", key)
        if isinstance(value, dict):
            _validate_nested(value, path, where=where)


def _validate_nested(node: dict, prefix: str, *, where: str) -> None:
    if prefix in RESERVED_DOTTED_KEYS:
        raise ReservedOverrideError(
            f"{where}: config 不能覆盖输出路径 {prefix}"
            f"（它会把这个世界的产物写回共享目录）"
        )
    for key, value in node.items():
        path = _dotted_path(prefix, key)
        if path in RESERVED_DOTTED_KEYS:
            raise ReservedOverrideError(
                f"{where}: config 不能覆盖输出路径 {path}"
                f"（它会把这个世界的产物写回共享目录）"
            )
        if isinstance(value, dict):
            _validate_nested(value, path, where=where)


__all__ = [
    "RESERVED_CONFIG_KEYS",
    "RESERVED_DOTTED_KEYS",
    "ReservedOverrideError",
    "RUN_PATHS",
    "run_root_overrides",
    "validate_world_overrides",
]
