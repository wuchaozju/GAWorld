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

:class:`TrafficPlugin` is the P1 layer: endogenous road congestion. It
collects each trip's road load on ``on_agent_post_step`` and commits the
tick's flows as per-edge travel-time multipliers on the *next*
``on_time_tick`` — see ``gaworld/world/traffic.py`` for why the lag matters.
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
        mode_cfg = ctx.config.get("mode_choice", {}) or {}
        self._scored_modes = bool(mode_cfg.get("scored", False))
        # Off by default: one row per tick is cheap, but no run should grow an
        # extra artifact it did not ask for. Track B's spatial experiment
        # turns it on (see benchmark/trackb_spatial.py).
        self._record_occupancy = bool(cfg.get("record_occupancy", False))
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
        # Map-level runtime flags travel with the map, so they are refreshed
        # here alongside the clock rather than being read on every trip.
        self._cm.set_mode_choice(city_map, self._scored_modes)
        self._cm.set_sim_time(city_map, hook_ctx.get("time_str"))
        counts = self._lp.update_occupancy_from_agents(city_map, hook_ctx.get("agents", []))
        if self._record_occupancy:
            self._record_where_everyone_is(hook_ctx, counts)

    def _record_where_everyone_is(self, hook_ctx, counts):
        """One row per tick: who is where, as a distribution.

        This is what Track B needs and nothing else writes: the per-node
        occupancy the loop already computes was used for perception and then
        dropped. Stored as the counts themselves so the analyser can pick its
        own concentration measure later.
        """
        sim = hook_ctx.get("sim")
        recorder = getattr(sim, "recorder", None)
        if recorder is None or not counts:
            return
        total = sum(counts.values())
        recorder.record("spatial.occupancy", {
            "nodes": len(counts),
            "people": total,
            "counts": counts,
        })

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


class VehicleOwnershipPlugin(Plugin):
    """Who owns a car and who owns a two-wheeler (see ``world/traffic.py``).

    On by default and independent of the congestion layer: mode choice needs
    an ownership condition whether or not the roads are modelled as busy.
    """

    id = "vehicle_ownership"

    def setup(self, ctx):
        from gaworld.world import traffic as tf_impl

        self._tf = tf_impl
        cfg = ctx.config.get("car_ownership", {}) or {}
        if not bool(cfg.get("enabled", True)):
            return
        self._pivot = float(cfg.get("pivot_income_multiple", tf_impl.DEFAULT_CAR_PIVOT_MULTIPLE))
        self._spread = float(cfg.get("spread", tf_impl.DEFAULT_CAR_SPREAD))
        self._driving_age = int(cfg.get("driving_age", tf_impl.DEFAULT_DRIVING_AGE))
        two = ctx.config.get("two_wheeler_ownership", {}) or {}
        self._two_enabled = bool(two.get("enabled", True))
        self._two_pivot = float(two.get("pivot_income_multiple",
                                        tf_impl.DEFAULT_TWO_WHEELER_PIVOT_MULTIPLE))
        self._two_spread = float(two.get("spread", tf_impl.DEFAULT_TWO_WHEELER_SPREAD))
        self._riding_age = int(two.get("riding_age", 16))
        ctx.bus.on("agents.built", self._assign)

    def _assign(self, hook_ctx):
        import random

        sim = hook_ctx["sim"]
        seed = sim.config.get("random_seed")
        rate = self._tf.assign_car_ownership(
            hook_ctx.get("agents", []),
            pivot_multiple=self._pivot,
            spread=self._spread,
            driving_age=self._driving_age,
            rng=random.Random(f"car_ownership:{seed}"),
        )
        state = sim.plugin_state(self.id)
        state["car_ownership_rate"] = rate
        _LOG.info("car ownership assigned: %.1f%% of residents", rate * 100)
        if self._two_enabled:
            two_rate = self._tf.assign_two_wheeler_ownership(
                hook_ctx.get("agents", []),
                pivot_multiple=self._two_pivot, spread=self._two_spread,
                riding_age=self._riding_age,
                rng=random.Random(f"two_wheeler_ownership:{seed}"),
            )
            state["two_wheeler_ownership_rate"] = two_rate
            _LOG.info("two-wheeler ownership assigned: %.1f%% of residents", two_rate * 100)


class TrafficPlugin(Plugin):
    """P1: endogenous road congestion (see ``gaworld/world/traffic.py``).

    Off by default: switching it on changes every trip's duration and cost,
    so runs from before it was enabled are not comparable.
    """

    id = "traffic"

    # Only used before the first pair of ticks has been seen; by then there
    # are no flows to commit, so the exact value never reaches a result.
    _FALLBACK_STEP_MINUTES = 30.0

    def setup(self, ctx):
        from gaworld.world import city_map as cm_impl
        from gaworld.world import traffic as tf_impl

        self._cm = cm_impl
        self._tf = tf_impl
        cfg = ctx.config.get("traffic", {}) or {}
        self._enabled = bool(cfg.get("enabled", False))
        if not self._enabled:
            return
        self._alpha = float(cfg.get("alpha", tf_impl.DEFAULT_ALPHA))
        self._beta = float(cfg.get("beta", tf_impl.DEFAULT_BETA))
        self._decay = float(cfg.get("decay", tf_impl.DEFAULT_DECAY))
        self._max_congestion = float(cfg.get("max_congestion", tf_impl.DEFAULT_MAX_CONGESTION))
        self._agents_represent = float(cfg.get("agents_represent", 1.0))
        self._mode_pcu = cfg.get("mode_pcu") or None
        self._road_capacity = cfg.get("road_capacity") or None
        self._suppress_rush = bool(cfg.get("suppress_rush_hour_mult", True))
        ctx.bus.on("on_day_start", self._reset)
        ctx.bus.on("on_time_tick", self._commit)
        ctx.bus.on("on_agent_post_step", self._collect)

    # -- hooks ---------------------------------------------------------------

    def _state(self, sim):
        return sim.plugin_state(self.id)

    def _reset(self, hook_ctx):
        """Start each day from free flow, so a day's dynamics never inherit
        the previous evening's jam across the day-boundary phases."""
        sim = hook_ctx["sim"]
        state = self._state(sim)
        state["flows"] = {}
        state["last_time_min"] = None
        city_map = hook_ctx.get("city_map")
        if city_map:
            self._cm.clear_congestion(city_map)

    def _collect(self, hook_ctx):
        """Accumulate this agent's road load for the tick now in progress."""
        travel = (hook_ctx.get("step") or {}).get("_travel")
        if not travel:
            return
        flows = self._state(hook_ctx["sim"]).setdefault("flows", {})
        self._tf.accumulate_travel(
            flows,
            travel,
            mode_pcu=self._mode_pcu,
            agents_represent=self._agents_represent,
        )

    def _commit(self, hook_ctx):
        """Turn the *previous* tick's flows into this tick's congestion.

        Running here — before any agent steps — is what keeps the result
        independent of the order agents are iterated in.
        """
        city_map = hook_ctx.get("city_map")
        if not city_map:
            return
        if self._suppress_rush:
            # The static rush-hour multiplier is a proxy for exactly what we
            # now model from flow; leaving both on double-counts it.
            self._cm.set_rush_hour_time_mult(city_map, 1.0)
        state = self._state(hook_ctx["sim"])
        now_min = self._cm._time_to_min(hook_ctx.get("time_str"))
        step_minutes = self._elapsed_minutes(state.get("last_time_min"), now_min)
        state["last_time_min"] = now_min
        flows = state.get("flows") or {}
        state["flows"] = {}
        congestion = self._tf.apply_flows(
            city_map,
            flows,
            step_minutes=step_minutes,
            alpha=self._alpha,
            beta=self._beta,
            decay=self._decay,
            max_congestion=self._max_congestion,
            road_capacity=self._road_capacity,
        )
        self._record(hook_ctx["sim"], flows, congestion, step_minutes)

    def _record(self, sim, flows, congestion, step_minutes):
        """One row per tick, congested or not.

        A flat line of 1.0 is a finding, not noise: it is what says the
        population is too small a sample for the roads to ever fill up.
        """
        recorder = getattr(sim, "recorder", None)
        if recorder is None:
            return
        factors = sorted(congestion.items(), key=lambda kv: -kv[1])
        recorder.record("traffic.tick", {
            "step_minutes": round(float(step_minutes), 1),
            "edges_loaded": len(flows),
            "edges_congested": len(factors),
            "flow_pcu": round(sum(flows.values()), 1),
            "congestion_max": round(factors[0][1], 3) if factors else 1.0,
            "congestion_mean": (
                round(sum(v for _, v in factors) / len(factors), 3) if factors else 1.0
            ),
            "busiest": [{"edge": key, "factor": round(value, 3)}
                        for key, value in factors[:3]],
        })

    def _elapsed_minutes(self, previous_min, now_min):
        """Length of the tick whose flows we are about to commit.

        Measured from the timeline itself rather than read from config: the
        master timeline merges the grid with LLM-generated schedule times, so
        steps are not uniform and ``time_step_minutes`` would be a guess.
        """
        if previous_min is None or now_min is None:
            return self._FALLBACK_STEP_MINUTES
        delta = (now_min - previous_min) % (24 * 60)
        return float(delta) if delta > 0 else self._FALLBACK_STEP_MINUTES
