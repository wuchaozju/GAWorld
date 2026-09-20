"""SimContext — the runtime's single source of truth.

Plugins and cognition stages access the world through this object instead of
importing module-level globals. ``build_kernel`` assembles the six kernel
services from CONFIG and is the one bootstrap entry point for the simulator,
tests, and future tools.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from gaworld.kernel.bus import EventBus
from gaworld.kernel.clock import Clock
from gaworld.kernel.controller import Controller
from gaworld.kernel.recorder import Recorder
from gaworld.kernel.registry import PluginRegistry


@dataclass
class SimContext:
    """Everything a plugin may legitimately touch at runtime."""

    config: dict
    clock: Clock
    bus: EventBus
    registry: PluginRegistry
    controller: Controller
    recorder: Recorder
    agents: list = field(default_factory=list)
    agents_by_id: dict = field(default_factory=dict)
    llm: Callable | None = None
    rng: random.Random = field(default_factory=random.Random)
    # Escape hatch for not-yet-formalised shared objects (city_map, ...).
    extras: dict = field(default_factory=dict)
    _plugin_state: dict = field(default_factory=dict, repr=False)

    def plugin_state(self, plugin_id: str) -> dict:
        """Shared (simulation-level) mutable state owned by one plugin.

        Other plugins may read it via the same call, but must not import the
        owning plugin's internals.
        """
        return self._plugin_state.setdefault(str(plugin_id), {})

    def agent_ext(self, agent, plugin_id: str) -> dict:
        """Per-agent state namespace owned by one plugin.

        Replaces sprinkling bare keys on the agent dict: all plugin state
        lives under ``agent["ext"][plugin_id]``.
        """
        return agent.setdefault("ext", {}).setdefault(str(plugin_id), {})

    def set_agents(self, agents: list) -> None:
        """Refresh the live agent list (supports runtime add/remove)."""
        self.agents = agents
        self.agents_by_id = {a["id"]: a for a in agents}


def build_kernel(
    config: dict,
    *,
    llm: Callable | None = None,
    load_entry_points: bool = True,
) -> SimContext:
    """Assemble the six kernel services from CONFIG.

    Behavior-compatible with the legacy bootstrap: the EventBus loads the
    same ``CONFIG["extensions"]`` hook declarations HookBus did, and plugin
    sources (``CONFIG["plugins"]`` + entry points) default to empty/no-op
    until plugins land in K3.
    """
    clock = Clock()
    bus = EventBus(config.get("extensions", {}))
    recorder = Recorder(
        base_dir=config.get("records", {}).get("output_dir", "output/records"),
        clock=clock,
    )
    registry = PluginRegistry()
    registry.load_config_plugins(config.get("plugins", []))
    if load_entry_points:
        registry.load_entry_points()

    seed = config.get("random_seed")
    try:
        rng = random.Random(int(seed)) if seed is not None else random.Random()
    except (TypeError, ValueError):
        rng = random.Random()

    ctx = SimContext(
        config=config,
        clock=clock,
        bus=bus,
        registry=registry,
        controller=Controller(),
        recorder=recorder,
        llm=llm,
        rng=rng,
    )
    # Every hook/collect/filter context carries the SimContext.
    bus.base_context["sim"] = ctx
    # K5: domain-free standard interventions ship with every kernel.
    from gaworld.kernel.interventions import register_standard_interventions

    register_standard_interventions(ctx)
    return ctx
