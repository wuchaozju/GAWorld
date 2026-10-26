from __future__ import annotations

from pathlib import Path

from gaworld.crowdsourcing.service import CrowdsourcingService
from gaworld.kernel import Plugin
from gaworld.memory.experience import append_agent_episode


class CrowdsourcingPlugin(Plugin):
    """Runs crowdsourcing sessions inside a simulation.

    The dashboard starts its own service; this one is for a headless run
    (``python generative_city_sim.py run``) that wants crowd sessions driven
    from inside the simulation loop, and it publishes the session feed on the
    bus like the collaboration plugin does.
    """

    id = "crowdsourcing"

    def setup(self, ctx) -> None:
        ctx.bus.on("on_simulation_start", self._start_service)

    def _start_service(self, hook_ctx) -> None:
        sim = hook_ctx["sim"]
        state = sim.plugin_state(self.id)
        if "service" in state:
            return
        cfg = sim.config.get("crowdsourcing", {})
        if not isinstance(cfg, dict):
            cfg = {}
        if not cfg.get("enabled", True):
            state["service"] = None
            return
        agents = {int(agent["id"]): agent for agent in hook_ctx.get("agents", sim.agents)}
        service = CrowdsourcingService(
            config=cfg,
            sessions_dir=Path(
                cfg.get(
                    "sessions_dir",
                    "output/crowdsourcing/sessions",
                )
            ),
            agent_loader=lambda agent_id: agents.get(int(agent_id)),
            llm=sim.llm,
            episode_writer=lambda agent_id, episode: append_agent_episode(
                agent_id,
                episode,
                cfg=sim.config,
            ),
            event_sink=lambda event: sim.bus.emit(
                "crowdsourcing.event",
                event=event,
            ),
        )
        service.start()
        state["service"] = service

    def teardown(self, ctx) -> None:
        service = ctx.plugin_state(self.id).pop("service", None)
        if service is not None:
            service.shutdown()
