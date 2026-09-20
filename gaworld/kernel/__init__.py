"""GAWorld microkernel (K1).

Six kernel services — and nothing else — live here:

- :class:`~gaworld.kernel.clock.Clock` — deterministic simulation time
- :class:`~gaworld.kernel.bus.EventBus` — observe/collect/filter hooks
  (drop-in superset of the legacy :class:`gaworld.hooks.HookBus`)
- :class:`~gaworld.kernel.registry.PluginRegistry` / ``Plugin`` — plugin assembly
- :class:`~gaworld.kernel.controller.Controller` — action validation + runtime intervention
- :class:`~gaworld.kernel.recorder.Recorder` — unified structured event recording
- :class:`~gaworld.kernel.context.SimContext` — the single runtime source of truth

Domain logic must never be imported here. Design doc:
``docs/proposals/2026-07-11-microkernel-plugin-architecture.md``.
"""

from gaworld.kernel.bus import EventBus
from gaworld.kernel.clock import Clock
from gaworld.kernel.context import SimContext, build_kernel
from gaworld.kernel.controller import ActionRequest, Controller, Verdict
from gaworld.kernel.recorder import Recorder
from gaworld.kernel.registry import Plugin, PluginRegistry

__all__ = [
    "ActionRequest",
    "Clock",
    "Controller",
    "EventBus",
    "Plugin",
    "PluginRegistry",
    "Recorder",
    "SimContext",
    "Verdict",
    "build_kernel",
]
