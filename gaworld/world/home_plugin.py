"""HomeEnvironmentPlugin — at-home perception & activity detail (P5).

Four jobs:

1. **Seed (``agents.built``)** — design each agent's home once. Procedural
   by default (deterministic off agent id + config seed), optional LLM polish
   when ``home.llm_enrich=True``. Re-loaded from disk on stateful runs so the
   same home comes back next time the simulation boots.
2. **Observe (``perception.compose``)** — when the agent's ``locations.current``
   equals their home node, contribute one or two prompt lines about the home
   (current room, ambiance, vibe). Priority 25 keeps the snippet ahead of the
   physical-environment (30 → 20 transition reads more naturally than the
   inverse).
3. **Arrive / leave (``agent.moved``)** — perception runs before the move,
   so its snapshot still says where the agent *was*. The moment a move lands
   at the home node the agent enters home mode (snapshot marked
   ``just_arrived``, ``home.entered`` recorded); the moment it leaves, home
   mode ends (``home.left``). Priority 10 runs ahead of the room placement,
   which reads the snapshot to pick the room inside the flat.
4. **Tick (``on_agent_post_step``)** — refresh the ambient state from the
   current activity, and append a per-tick observation row to
   ``output/home/agent_<id>.jsonl`` so downstream tooling can analyse home
   life independently of the Recorder.

Like every P5 plugin, this is OFF by default until ``home.enabled=True`` and
``CONFIG["plugins"]`` opts the plugin in. The default config turns it on, so
a fresh checkout gets a home for every resident.
"""

from __future__ import annotations

from gaworld.kernel import Plugin


class HomeEnvironmentPlugin(Plugin):
    id = "home_environment"

    def setup(self, ctx):
        # Domain imports stay out of kernel assembly; resolved once here so
        # tests can patch the module attributes cheaply.
        from gaworld.llm import providers as _llm_providers
        from gaworld.world import home_environment as he_impl

        self._he = he_impl
        self._llm_providers = _llm_providers
        cfg = ctx.config.get("home", {}) or {}
        self._enabled = bool(cfg.get("enabled", True))
        if not self._enabled:
            # Still register an empty ``perception.compose`` so the agent key
            # resets are skipped when callers look it up — mirrors the P0
            # plugin's disabled path.
            ctx.bus.on("perception.compose", self._disabled_snapshot)
            return
        self._seed = cfg.get("seed")
        self._llm_enrich = bool(cfg.get("llm_enrich", False))
        self._inject = bool(cfg.get("inject_into_perception", True))
        self._record = bool(cfg.get("record_observations", True))
        self._output_dir = ctx.config.get("output_root", "output")
        self._stateful = bool(ctx.config.get("stateful", False))
        # Store the per-plugin state on the sim so it can be persisted.
        self._state = ctx.plugin_state(self.id)

        ctx.bus.on("agents.built", self._seed_homes, priority=10)
        ctx.bus.on("perception.compose", self._compose, priority=25)
        ctx.bus.on("agent.moved", self._moved, priority=10)
        ctx.bus.on("on_agent_post_step", self._tick, priority=5)

    # -- helpers ------------------------------------------------------------

    def _home_id_for(self, agent: dict) -> str:
        return self._he._home_id(agent)

    def _output_path(self) -> str:
        from pathlib import Path

        return str(Path(self._output_dir) / "home")

    @staticmethod
    def _is_at_home(agent: dict, home: dict) -> bool:
        locations = agent.get("locations") or {}
        if locations.get("in_transit"):
            return False
        current = locations.get("current") or locations.get("home")
        home_node = locations.get("home") or home.get("home_node")
        return bool(current and home_node and current == home_node)

    @staticmethod
    def _weather(hook_ctx) -> str:
        sim = hook_ctx.get("sim")
        env_system = getattr(sim, "extras", {}).get("env_system") if sim is not None else None
        try:
            if env_system is not None and hasattr(env_system, "export_runtime_state"):
                return str((env_system.export_runtime_state() or {}).get("weather_state", "") or "")
        except Exception:
            pass
        return ""

    def _observe(self, agent: dict, home: dict, hook_ctx, activity: str) -> dict:
        """Refresh the ambiance for this tick and return the home snapshot."""
        time_str = hook_ctx.get("time_str") or ""
        self._he.update_ambiance(
            home, time_str=time_str, weather_state=self._weather(hook_ctx), activity=activity
        )
        return self._he.home_observation(agent, home, activity=activity, time_str=time_str)

    @staticmethod
    def _record_event(hook_ctx, name: str, payload: dict) -> None:
        recorder = getattr(hook_ctx.get("sim"), "recorder", None)
        if recorder is not None:
            recorder.record(name, payload)

    # -- hooks ---------------------------------------------------------------

    def _disabled_snapshot(self, hook_ctx):
        """When the plugin is off, never contribute and never store."""
        agent = hook_ctx["agent"]
        agent.pop("_home_observation", None)
        return None

    def _seed_homes(self, hook_ctx):
        """Build (or reload) the home for every agent. Idempotent on rerun."""
        sim = hook_ctx["sim"]
        agents = hook_ctx.get("agents") or []
        homes: dict[str, dict] = {}
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            home_id = self._home_id_for(agent)
            cached = self._he.load_home(home_id, self._output_path()) if self._stateful else None
            if cached:
                home = cached
            else:
                home = self._he.design_home(agent, seed=self._seed)
                if self._llm_enrich:
                    home = self._he.polish_home_with_llm(
                        home,
                        call_llm=self._llm_providers.call_llm,
                        agent=agent,
                    )
                self._he.save_home(home_id, home, self._output_path())
            agent["_home"] = home
            homes[home_id] = home
        self._state["count"] = len(homes)
        # Record one row per agent so a researcher can see the population at a
        # glance without scraping agent JSONs.
        recorder = getattr(sim, "recorder", None)
        if recorder is not None and homes:
            recorder.record(
                "home.seeded",
                {
                    "count": len(homes),
                    "sample": [
                        {
                            "home_id": home.get("home_id"),
                            "rooms": list((home.get("rooms") or {}).keys()),
                            "ambiance_quality": home.get("ambiance_quality"),
                        }
                        for home in list(homes.values())[:5]
                    ],
                },
            )

    def _compose(self, hook_ctx):
        """Contribute a one- or two-line home snippet to perception."""
        agent = hook_ctx["agent"]
        home = agent.get("_home")
        if not home:
            agent["_home_observation"] = {}
            return None
        if (agent.get("locations") or {}).get("in_transit"):
            agent["_home_observation"] = {"is_at_home": False, "reason": "in_transit"}
            return None
        if not self._is_at_home(agent, home):
            agent["_home_observation"] = {"is_at_home": False}
            return None
        step = hook_ctx.get("step") or {}
        activity = step.get("scheduled_activity") or step.get("activity") or ""
        # Refresh ambiance for the *current* tick so the prompt reflects the
        # new tick's lighting/sound even before ``on_agent_post_step`` runs.
        obs = self._observe(agent, home, hook_ctx, activity)
        agent["_home_observation"] = obs
        if not self._inject:
            return None
        lines = self._he.home_prompt_lines(obs)
        if not lines:
            return None
        # Return the room + ambiance block as one string the perception stage
        # can split on its own. Two short sentences read better than three.
        return "".join(lines)

    def _moved(self, hook_ctx):
        """Enter home mode as soon as the agent gets home; leave it as soon as
        they go out. Staying put keeps the perception snapshot."""
        agent = hook_ctx["agent"]
        home = agent.get("_home")
        if not home:
            return
        was_home = bool((agent.get("_home_observation") or {}).get("is_at_home"))
        now_home = self._is_at_home(agent, home)
        if now_home == was_home:
            return
        locations = agent.get("locations") or {}
        event = {
            "agent_id": agent.get("id"),
            "day": hook_ctx.get("day"),
            "time": hook_ctx.get("time_str", ""),
            "home_node": locations.get("home") or home.get("home_node"),
        }
        if not now_home:
            agent["_home_observation"] = (
                {"is_at_home": False, "reason": "in_transit"}
                if locations.get("in_transit")
                else {"is_at_home": False}
            )
            if self._record:
                self._record_event(hook_ctx, "home.left", event)
            return
        obs = self._observe(agent, home, hook_ctx, hook_ctx.get("activity") or "")
        obs["just_arrived"] = True
        agent["_home_observation"] = obs
        if self._record:
            self._record_event(hook_ctx, "home.entered", {**event, "room": obs["current_room"]["key"]})

    def _tick(self, hook_ctx):
        """Refresh ambiance, persist a per-tick observation row, and post the
        snapshot through the recorder."""
        if not self._record:
            return
        agent = hook_ctx["agent"]
        home = agent.get("_home")
        obs = agent.get("_home_observation") or {}
        if not home or not obs.get("is_at_home"):
            return
        # Append a per-tick row for downstream analyses (the dashboard reads
        # the same file via the ``/api/home`` endpoint).
        self._he.append_observation(
            self._output_path(),
            agent_id=agent.get("id"),
            day=hook_ctx.get("day"),
            time_str=hook_ctx.get("time_str", ""),
            obs=obs,
        )
        sim = hook_ctx.get("sim")
        recorder = getattr(sim, "recorder", None)
        if recorder is not None:
            recorder.record(
                "home.observation",
                {
                    "agent_id": agent.get("id"),
                    "day": hook_ctx.get("day"),
                    "time": hook_ctx.get("time_str", ""),
                    "home_node": obs.get("home_node"),
                    "room": (obs.get("current_room") or {}).get("key"),
                    "ambiance": obs.get("ambiance"),
                },
            )
