"""LocalPhysicalPlugin — local physical perception as a kernel plugin (K3g).

P0 of the physical-environment stack: refresh the city map's per-node state
each tick and give every agent a snapshot of its *current* surroundings
(crowding / open-closed / local weather) before it perceives.

- ``on_time_tick`` (observe): write the sim time into the map and recompute
  node occupancy from where agents actually are.
- ``perception.compose`` (collect, priority=30): build the snapshot, store
  it at ``agent["_local_physical"]`` (the dynamic-behavior interrupt engine
  reads it in the next stage), and — when ``inject_into_perception`` is on —
  contribute the "身边的物理环境：…" line. Priority 30 keeps the line ahead
  of the life-event (20) and intervention (10) contributions, preserving the
  pre-migration text order exactly.

:class:`SpatialPreferencesPlugin` (K3i) is the P4 layer of the same stack:
learned location-aversion — stateful load on ``agents.built``, recency decay
on ``on_day_start``, aversion-aware redirection on the ``location.resolve``
filter, and anomaly-experience recording on ``interrupt.applied``.
"""

from __future__ import annotations

from gaworld.kernel import Plugin, Verdict
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.world.plugin")


def _weather_state(env_system) -> str:
    """Best-effort read of the environment's current weather label."""
    try:
        state = env_system.export_runtime_state()
        if isinstance(state, dict):
            return str(state.get("weather_state", "") or "")
    except Exception:  # noqa: BLE001 — remote client may lack this method
        pass
    return str(getattr(env_system, "_weather_state", "") or "")


class LocalPhysicalPlugin(Plugin):
    id = "local_physical"

    def setup(self, ctx):
        # Domain imports stay out of kernel assembly; module refs kept so
        # tests can patch the module attributes.
        from gaworld.world import city_map as cm_impl
        from gaworld.world import local_physical as lp_impl

        self._cm = cm_impl
        self._lp = lp_impl
        cfg = ctx.config.get("local_physical", {}) or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._inject = bool(cfg.get("inject_into_perception", True))
        self._busy_ratio = float(cfg.get("crowd_busy_ratio", 0.6))
        self._packed_ratio = float(cfg.get("crowd_packed_ratio", 0.9))
        self._anomaly_ratio = float(cfg.get("crowd_anomaly_ratio", 0.9))
        self._anomaly_jump = float(cfg.get("crowd_anomaly_jump", 0.25))
        ctx.bus.on("on_time_tick", self._refresh_map)
        ctx.bus.on("perception.compose", self._snapshot, priority=30)
        # K4 validators. location_exists is on by default — resolve_location
        # only yields map nodes, so in normal operation it never fires; it
        # catches rogue rewrites from plugins/hooks. venue_open is OFF by
        # default: hard-blocking closed venues would change dynamics (the
        # P0/P2 layers handle closures reactively) — opt in via
        # CONFIG["controller"]["validators"]["venue_open"] = True.
        vcfg = ctx.config.get("controller", {}) or {}
        vcfg = vcfg.get("validators", {}) if isinstance(vcfg, dict) else {}
        if vcfg.get("location_exists", True):
            ctx.controller.register_validator(self._validate_location_exists, priority=10)
        if vcfg.get("venue_open", False):
            ctx.controller.register_validator(self._validate_venue_open)

    # -- hooks ---------------------------------------------------------------

    def _validate_location_exists(self, request, ctx):
        if request.name != "move":
            return None
        to = str(request.params.get("to", "") or "")
        if not to:
            return None
        city_map = ctx.extras.get("city_map")
        if not city_map:
            return None
        if self._cm.node_by_name(city_map, to) is None:
            return Verdict.deny(f"目的地【{to}】在这座城市里并不存在")
        return None

    def _validate_venue_open(self, request, ctx):
        if request.name != "move":
            return None
        to = str(request.params.get("to", "") or "")
        city_map = ctx.extras.get("city_map")
        if not to or not city_map:
            return None
        if not self._cm.is_open(city_map, to, ctx.clock.time_str):
            return Verdict.deny(f"【{to}】目前不在营业时间")
        return None

    def _refresh_map(self, hook_ctx):
        if not self._enabled:
            return
        city_map = hook_ctx.get("city_map")
        if not city_map:
            return
        self._cm.set_sim_time(city_map, hook_ctx.get("time_str"))
        self._lp.update_occupancy_from_agents(city_map, hook_ctx.get("agents", []))

    def _snapshot(self, hook_ctx):
        agent = hook_ctx["agent"]
        if not self._enabled:
            agent["_local_physical"] = {}
            return None
        sim = hook_ctx["sim"]
        local_physical = self._lp.local_physical_state(
            sim.extras.get("city_map"),
            agent,
            time_str=hook_ctx.get("time_str"),
            weather_state=_weather_state(sim.extras.get("env_system")),
            busy_ratio=self._busy_ratio,
            packed_ratio=self._packed_ratio,
            anomaly_ratio=self._anomaly_ratio,
            anomaly_jump=self._anomaly_jump,
        )
        agent["_local_physical"] = local_physical
        if not self._inject:
            return None
        text = self._lp.physical_state_text(local_physical)
        if text:
            return f"身边的物理环境：{text}"
        return None


class SpatialPreferencesPlugin(Plugin):
    """P4: learned location-avoidance preferences (see module docstring)."""

    id = "spatial_preferences"

    def setup(self, ctx):
        from gaworld.memory import experience as exp_impl
        from gaworld.memory import spatial_preferences as sp_impl

        self._sp = sp_impl
        self._exp = exp_impl
        cfg = ctx.config.get("spatial_preferences", {}) or {}
        self._enabled = bool(cfg.get("enabled", True))
        self._weight = float(cfg.get("anomaly_weight", 1.0))
        self._threshold = float(cfg.get("avoid_threshold", 1.5))
        self._half_life = float(cfg.get("half_life_days", 7.0))
        if not self._enabled:
            return
        ctx.bus.on("agents.built", self._load_preferences)
        ctx.bus.on("on_day_start", self._decay_preferences)
        ctx.bus.on("location.resolve", self._redirect)
        ctx.bus.on("interrupt.applied", self._record_anomaly)

    def _stateful(self, sim) -> bool:
        return bool(sim.config.get("stateful", False))

    def _save(self, agent):
        self._exp.save_agent_env_preferences(
            agent["id"], agent.get("env_preferences", {})
        )

    def _load_preferences(self, hook_ctx):
        sim = hook_ctx["sim"]
        if not self._stateful(sim):
            return
        for agent in hook_ctx.get("agents", []):
            agent["env_preferences"] = self._exp.load_agent_env_preferences(agent["id"])

    def _decay_preferences(self, hook_ctx):
        sim = hook_ctx["sim"]
        day = hook_ctx.get("day")
        for agent in hook_ctx.get("agents", []):
            self._sp.decay_preferences(agent, day, half_life_days=self._half_life)
            if self._stateful(sim):
                self._save(agent)

    def _redirect(self, desired_location, hook_ctx):
        if not desired_location:
            return None
        sim = hook_ctx["sim"]
        new_location, _redirected = self._sp.redirect_for_aversion(
            hook_ctx["agent"],
            sim.extras.get("city_map"),
            desired_location,
            hook_ctx.get("time_str"),
            threshold=self._threshold,
        )
        return new_location

    def _record_anomaly(self, hook_ctx):
        sim = hook_ctx["sim"]
        # Parity with the pre-K3i nesting: recording lived inside the
        # replan block, so it inherits the replan enable gate.
        if not bool((sim.config.get("replan", {}) or {}).get("enabled", True)):
            return
        dyn = hook_ctx.get("dyn_result")
        if not (hook_ctx.get("changed") and isinstance(dyn, dict)):
            return
        itr = dyn.get("interrupt") or {}
        extra = itr.get("extra", {}) if isinstance(itr, dict) else {}
        persistent_anomaly = (
            isinstance(itr, dict)
            and not itr.get("resumable", True)
            and (bool(extra.get("anomaly"))
                 or extra.get("event_type") in ("emergency", "local_physical"))
        )
        # Learn to avoid a *place* only for location-bound anomalies —
        # never for city-wide macro anomalies, which aren't a place's fault.
        if not (persistent_anomaly
                and extra.get("event_type") == "local_physical"
                and extra.get("location")):
            return
        agent = hook_ctx["agent"]
        self._sp.record_anomaly_experience(
            agent,
            location=str(extra.get("location")),
            day=hook_ctx.get("day"),
            weight=self._weight,
            reason=str(itr.get("kind", "")),
            time_str=hook_ctx.get("time_str"),
        )
        if self._stateful(sim):
            self._save(agent)
