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
        state = sim.plugin_state(self.id)
        if "service" in state:
            return
        cfg = sim.config.get("collaboration", {})
        if not isinstance(cfg, dict):
            cfg = {}
        if not cfg.get("enabled", True):
            state["service"] = None
            return
        agents = {
            int(agent["id"]): agent
            for agent in hook_ctx.get("agents", sim.agents)
        }
        merge_persisted_agent_edges(list(agents.values()))
        service = CollaborationService(
            config=cfg,
            sessions_dir=Path(
                cfg.get(
                    "sessions_dir",
                    "output/collaboration/sessions",
                )
            ),
            memory_dir=Path(
                sim.config.get("memory_dir", "output/memory")
            ),
            agent_loader=lambda agent_id: agents.get(int(agent_id)),
            llm=sim.llm,
            episode_writer=lambda agent_id, episode: append_agent_episode(
                agent_id,
                episode,
                cfg=sim.config,
            ),
            event_sink=lambda event: sim.bus.emit(
                "collaboration.event",
                event=event,
            ),
        )
        service.start()
        state["service"] = service

    def teardown(self, ctx) -> None:
        service = ctx.plugin_state(self.id).pop("service", None)
        if service is not None:
            service.shutdown()
