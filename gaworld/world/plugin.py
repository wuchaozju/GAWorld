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

:class:`VenueCapacityPlugin` makes crowding bite: a ``move`` to a full venue
is rewritten to the nearest same-category venue with room, or refused — see
``gaworld/world/venue_capacity.py``.

:class:`RoomsPlugin` puts residents in rooms (``local_physical.rooms``,
default off): each household gets a flat in its building, each step places
the resident in the room that fits what they are doing, residents only run
into the people in their own room, and venue capacity is counted per room —
see ``gaworld/world/spatial_tree.py``.
"""

from __future__ import annotations

from gaworld.kernel import ActionRequest, Plugin, Verdict
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


class VenueCapacityPlugin(Plugin):
    """A full venue turns people away (``local_physical.capacity``, default off).

    Three pieces, all inert unless enabled:

    * ``on_time_tick``: start this tick's ledger from where everyone is (or is
      heading).
    * ``tick.agent_order`` filter: a seeded shuffle of who acts first, so the
      last seat is a fair draw rather than the lowest agent id's.
    * a ``move`` validator, registered last (priority -10) so its admission
      bookkeeping is never undone by a later deny: room → admit; full →
      rewrite to the nearest same-category venue that is open and has room;
      all full → deny (the resident stays put and perceives why).
    """

    id = "venue_capacity"

    def setup(self, ctx):
        from gaworld.world import city_map as cm_impl
        from gaworld.world import venue_capacity as vc_impl

        self._cm = cm_impl
        self._vc = vc_impl
        cfg = (ctx.config.get("local_physical", {}) or {}).get("capacity", {}) or {}
        if not bool(cfg.get("enabled", False)):
            return
        self._categories = tuple(cfg.get("categories") or vc_impl.DEFAULT_CATEGORIES)
        represent = cfg.get("agents_represent")
        if represent is None:
            # One sampled population, one answer to "how many people is a
            # resident": share the congestion layer's knob unless overridden.
            represent = (ctx.config.get("traffic", {}) or {}).get("agents_represent", 1.0)
        self._represent = max(0.0, float(represent))
        self._top_k = max(0, int(cfg.get("redirect_top_k", 4)))
        self._seed = ctx.config.get("random_seed")
        self._ledger = vc_impl.TickLedger()
        # With rooms on, a venue is full *for an activity* once every room
        # that hosts it is: the ledger then counts per (venue, room).
        rooms_cfg = (ctx.config.get("local_physical", {}) or {}).get("rooms", {}) or {}
        self._by_room = bool(rooms_cfg.get("enabled", False))
        if self._by_room:
            from gaworld.world import spatial_tree as st_impl

            self._st = st_impl
        ctx.bus.on("on_time_tick", self._start_tick)
        ctx.bus.on("tick.agent_order", self._order)
        ctx.controller.register_validator(self._validate, priority=-10)

    def _node(self, city_map, location):
        return self._cm.node_by_name(city_map, location) if city_map and location else None

    def _start_tick(self, hook_ctx):
        city_map = hook_ctx.get("city_map")
        if self._by_room:
            self._ledger.reset(self._room_start_counts(hook_ctx.get("agents", []), city_map))
            return

        def capped_id(location):
            node = self._node(city_map, location)
            return node["id"] if self._vc.is_capped(node, self._categories) else None

        self._ledger.reset(self._vc.start_counts(hook_ctx.get("agents", []), capped_id))

    @staticmethod
    def _room_slot(node_id, arena):
        return f"{node_id}\x1f{arena}"

    def _room_start_counts(self, agents, city_map):
        """Per (venue, room): who is in it, plus who is on the way to it.

        Someone travelling counts in the room they were admitted to; anyone
        without a room yet counts in the building's default room.
        """
        counts = {}
        for agent in agents or []:
            locations = agent.get("locations") if isinstance(agent, dict) else None
            if not isinstance(locations, dict):
                continue
            moving = bool(locations.get("in_transit"))
            node = self._node(city_map, locations.get("destination") if moving else locations.get("current"))
            if not self._vc.is_capped(node, self._categories):
                continue
            if moving:
                intent = locations.get("room_intent") or {}
                arena = intent.get("arena") if intent.get("node") == node["id"] else None
            else:
                room = locations.get("room") or {}
                arena = room.get("arena") if room.get("node") == locations.get("current") else None
            if not arena:
                arena = self._st.BLUEPRINTS[self._st.blueprint_key(node)]["default"]
            slot = self._room_slot(node["id"], arena)
            counts[slot] = counts.get(slot, 0) + 1
        return counts

    def _rooms_for(self, node, request, agent, city_map):
        """The rooms this trip's activity could use at *node*, best first."""
        locations = agent.get("locations") or {}

        def is_here(where):
            other = self._node(city_map, where)
            return bool(other) and other["id"] == node["id"]

        key = self._st.blueprint_key(node)
        slot = self._st.activity_slot(request.params.get("activity"))
        return key, self._st.rooms_for(
            key, slot, staff=is_here(locations.get("workplace")), resident=is_here(locations.get("home"))
        )

    def _free_room(self, node, request, agent, city_map):
        key, rooms = self._rooms_for(node, request, agent, city_map)
        try:
            capacity = float(node.get("capacity"))
        except (TypeError, ValueError):
            return rooms[0] if rooms else None  # no capacity, never full
        for arena in rooms:
            load = self._ledger.load(self._room_slot(node["id"], arena))
            if not self._vc.is_full(load, capacity * self._st.room_share(key, arena), self._represent):
                return arena
        return None

    def _admit(self, node, request, agent, city_map):
        """Count the visitor in (per room when rooms are on); False when full."""
        if not self._by_room:
            if not self._has_room(node):
                return False
            self._ledger.admit(node["id"], request.agent_id)
            return True
        arena = self._free_room(node, request, agent, city_map)
        if arena is None:
            return False
        self._ledger.admit(self._room_slot(node["id"], arena), request.agent_id)
        # RoomsPlugin seats them here on arrival; travellers count here meanwhile.
        agent.setdefault("locations", {})["room_intent"] = {"node": node["id"], "arena": arena}
        return True

    def _load(self, node):
        if not self._by_room:
            return self._ledger.load(node["id"])
        rooms = self._st.BLUEPRINTS[self._st.blueprint_key(node)]["rooms"]
        return sum(self._ledger.load(self._room_slot(node["id"], r["name"])) for r in rooms)

    def _full_reason(self, node, request, agent, city_map):
        if not self._by_room:
            return f"【{node['id']}】已经满了，附近同类的地方也都没有空位"
        key, rooms = self._rooms_for(node, request, agent, city_map)
        labels = "、".join(dict.fromkeys(self._st.room_label(key, arena) for arena in rooms))
        return f"【{node['id']}】的{labels}已经满了，附近同类的地方也都没有空位"

    def _order(self, agents, hook_ctx):
        return self._vc.shuffled(agents, self._seed, hook_ctx.get("day"), hook_ctx.get("time_str"))

    def _has_room(self, node):
        return not self._vc.is_full(self._ledger.load(node["id"]), node.get("capacity"), self._represent)

    def _validate(self, request, ctx):
        if request.name != "move":
            return None
        city_map = ctx.extras.get("city_map")
        node = self._node(city_map, str(request.params.get("to", "") or ""))
        if not self._vc.is_capped(node, self._categories):
            return None
        agent = ctx.agents_by_id.get(request.agent_id) or {}
        locations = agent.get("locations") or {}
        if locations.get("in_transit"):
            return None  # move_agent ignores the request until the trip ends
        here = self._node(city_map, locations.get("current"))
        if here and here["id"] == node["id"]:
            return None  # already inside, already counted
        if self._admit(node, request, agent, city_map):
            return None
        time_str = getattr(ctx.clock, "time_str", "")
        for alt_id, _distance in self._cm.nearest_by_category(
            city_map, node["id"], node.get("category", ""), top_k=self._top_k
        ) if self._top_k else []:
            alt = self._node(city_map, alt_id)
            if not alt or not self._cm.is_open(city_map, alt_id, time_str):
                continue
            if not self._admit(alt, request, agent, city_map):
                continue
            if ctx.recorder is not None:
                ctx.recorder.record("venue.redirect", {
                    "agent_id": request.agent_id,
                    "from": node["id"],
                    "to": alt["id"],
                    "load": self._load(node),
                    "capacity": node.get("capacity"),
                })
            return Verdict.rewrite(ActionRequest(
                agent_id=request.agent_id,
                name=request.name,
                params={**request.params, "to": alt["id"]},
                raw_text=request.raw_text,
            ))
        return Verdict.deny(self._full_reason(node, request, agent, city_map))


class RoomsPlugin(Plugin):
    """Residents stand in rooms (``local_physical.rooms``, default off).

    * ``agents.built`` (priority -10, after the family plugin has formed the
      households): every household gets its own flat in its home building.
    * ``on_time_tick``: last tick's chairs and beds are free again.
    * ``agent.moved``: place the resident — flat at home, room, the object
      they use — from what they are doing. A resident keeps their room while
      it still fits; a trip admitted to a room by venue capacity lands there.

    Whom a resident runs into (``detect_co_located_agents``) then needs the
    same room, not just the same place, and :class:`VenueCapacityPlugin`
    counts per room. The room goes into the trace for the indoor views.
    """

    id = "rooms"

    def setup(self, ctx):
        from gaworld.world import city_map as cm_impl
        from gaworld.world import spatial_tree as st_impl

        self._cm = cm_impl
        self._st = st_impl
        cfg = (ctx.config.get("local_physical", {}) or {}).get("rooms", {}) or {}
        if not bool(cfg.get("enabled", False)):
            return
        self._flats = {}  # building id -> {household: flat}
        self._taken = {}  # (building id, flat) -> {room: objects in use this tick}
        ctx.bus.on("agents.built", self._seat_households, priority=-10)
        ctx.bus.on("on_time_tick", self._new_tick)
        ctx.bus.on("agent.moved", self._place)

    def _node(self, city_map, location):
        return self._cm.node_by_name(city_map, location) if city_map and location else None

    def _flat_for(self, agent, node, city_map):
        flats = self._flats.setdefault(node["id"], {})
        household = self._st.household_key(agent)
        if household not in flats:
            interior = (city_map.get("interiors") or {}).get(node["id"])
            flats.update(self._st.assign_units([household], interior, flats))
        return flats[household]

    def _seat_households(self, hook_ctx):
        sim = hook_ctx.get("sim")
        city_map = getattr(sim, "extras", {}).get("city_map") if sim is not None else None
        if not city_map:
            return
        by_building = {}
        for agent in hook_ctx.get("agents") or []:
            node = self._node(city_map, (agent.get("locations") or {}).get("home"))
            if node and self._st.is_residential(self._st.blueprint_key(node)):
                by_building.setdefault(node["id"], set()).add(self._st.household_key(agent))
        interiors = city_map.get("interiors") or {}
        for node_id, households in sorted(by_building.items()):
            self._flats[node_id] = self._st.assign_units(households, interiors.get(node_id), self._flats.get(node_id))
        if by_building:
            flats = sum(len(v) for v in self._flats.values())
            print(f"🚪 分户：{len(by_building)} 栋住宅楼 / {flats} 户（同屋才算碰面）")

    def _new_tick(self, hook_ctx):
        self._taken = {}

    def _place(self, hook_ctx):
        agent = hook_ctx.get("agent") or {}
        locations = agent.get("locations")
        if not isinstance(locations, dict):
            return
        if locations.get("in_transit"):
            locations.pop("room", None)
            return
        city_map = hook_ctx.get("city_map")
        current = locations.get("current")
        node = self._node(city_map, current)
        intent = locations.pop("room_intent", None) or {}
        if not node:
            locations.pop("room", None)
            return
        st = self._st
        key = st.blueprint_key(node)

        def is_here(where):
            other = self._node(city_map, where)
            return bool(other) and other["id"] == node["id"]

        resident, staff = is_here(locations.get("home")), is_here(locations.get("workplace"))
        flat = self._flat_for(agent, node, city_map) if resident and st.is_residential(key) else ""
        slot = st.activity_slot(hook_ctx.get("activity"))
        home_type = None
        observed = agent.get("_home_observation") or {}
        if resident and observed.get("is_at_home"):
            home_type = st.HOME_ROOM_TYPES.get((observed.get("current_room") or {}).get("key"))
        rooms = st.rooms_for(key, slot, staff=staff, resident=resident, home_type=home_type)
        previous = locations.get("room") or {}
        same_flat = previous.get("node") == current and (previous.get("unit") or "") == flat
        taken = self._taken.setdefault((node["id"], flat), {})
        if intent.get("node") == node["id"] and intent.get("arena") in rooms:
            arena = intent["arena"]
        elif same_flat and previous.get("arena") in rooms:
            arena = previous["arena"]  # still fits: stay put
        else:
            # the first fitting room with a free bed / chair / stove, if any
            arena = next((r for r in rooms if st.pick_object(key, r, slot, taken.get(r, ()))), rooms[0])
        used = taken.setdefault(arena, set())
        keep = previous.get("object") if same_flat and previous.get("arena") == arena else None
        if keep and keep not in used and keep in st.pick_objects(key, arena, slot):
            obj = keep
        else:
            obj = st.pick_object(key, arena, slot, used)
        if obj:
            used.add(obj)
        locations["room"] = {"node": current, "unit": flat, "arena": arena, "object": obj}
