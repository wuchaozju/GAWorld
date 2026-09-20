"""Cognition pipeline (K2): the agent step as a configurable stage sequence.

``run_simulation``'s per-agent step body is carved into named stages. Each
stage is a callable ``fn(agent, step, ctx)`` where ``step`` is the per-step
data bus (a plain dict — hook consumers already read it via ``step=...`` in
the pre/post-step events, so we keep dict semantics for compatibility) and
``ctx`` is the kernel :class:`~gaworld.kernel.context.SimContext`.

Key conventions on the step dict:

- **hook-visible keys** keep their legacy names (``scheduled_activity``,
  ``activity``, ``action``, ``outcome``, ``reflection``, ...);
- **working keys** that only stages exchange are underscore-prefixed
  (``_env_context``, ``_act``, ``_travel``, ...), so the hook payload stays
  recognisable.

The stage order is configuration::

    CONFIG["pipeline"]["agent_step"] = [
        "prepare", "perceive", "interrupts", "plan", "adjust_activity",
        "move", "select_action", "reflect", "update_state",
        "broadcast", "memorize", "record",
    ]

Entries may be a builtin stage name, an importable ``"module:function"``
path (custom stage), or ``{"name": ..., "call": "module:function"}`` to give
a custom stage a display name. Omitting a builtin name ablates that stage;
downstream stages read missing data defensively (``step.get(..., default)``).
``prepare`` and ``record`` are structural (pre-step hooks / logging live
there) — ablation targets are the cognitive stages in between.

Stage errors propagate: unlike bus observers, stages ARE the simulation's
control flow, and swallowing a failure would silently corrupt agent state.
"""

from __future__ import annotations

from typing import Any, Callable

from gaworld.hooks import HookBus
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.sim.pipeline")

DEFAULT_AGENT_STEP_ORDER: tuple[str, ...] = (
    "prepare",
    "perceive",
    "interrupts",
    "plan",
    "adjust_activity",
    "move",
    "select_action",
    "reflect",
    "update_state",
    "broadcast",
    "memorize",
    "record",
)


class StagePipeline:
    """Ordered stage sequence for one agent step."""

    def __init__(self, stages: list[tuple[str, Callable]]):
        self.stages = list(stages)

    @property
    def stage_names(self) -> list[str]:
        return [name for name, _ in self.stages]

    @classmethod
    def from_config(
        cls,
        pipeline_cfg: dict | None,
        builtin: dict[str, Callable],
        default_order: tuple[str, ...] = DEFAULT_AGENT_STEP_ORDER,
    ) -> "StagePipeline":
        """Build the pipeline from ``CONFIG["pipeline"]`` (or the default).

        Unknown builtin names and unloadable custom paths are skipped with a
        warning rather than aborting the run — a typo in config should not
        take the whole simulation down, and the skip is visible in logs.
        """
        cfg = pipeline_cfg or {}
        order = cfg.get("agent_step") or list(default_order)
        stages: list[tuple[str, Callable]] = []
        for entry in order:
            name, fn = cls._resolve_entry(entry, builtin)
            if fn is None:
                _LOG.warning("pipeline stage %r not resolvable; skipped", entry)
                continue
            stages.append((name, fn))
        if not stages:
            raise ValueError("agent-step pipeline resolved to zero stages")
        return cls(stages)

    @staticmethod
    def _resolve_entry(
        entry: Any, builtin: dict[str, Callable]
    ) -> tuple[str, Callable | None]:
        if isinstance(entry, dict):
            call = str(entry.get("call", "")).strip()
            name = str(entry.get("name", "") or call)
            if call in builtin:
                return name, builtin[call]
            return name, HookBus._load_callable(call)
        text = str(entry).strip()
        if text in builtin:
            return text, builtin[text]
        if ":" in text:
            return text, HookBus._load_callable(text)
        return text, None

    def run_step(self, agent, step: dict, ctx) -> dict:
        """Run every stage over the shared step dict. Errors propagate."""
        for _name, fn in self.stages:
            fn(agent, step, ctx)
        return step
