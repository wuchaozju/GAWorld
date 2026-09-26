"""Environment, distributed simulation, and external-agent defaults."""

from __future__ import annotations

from typing import Any


def environment_settings() -> dict[str, Any]:
    return {
        # Local physical perception (P0): wires the city map's per-node
        # occupancy / opening-hours state — previously dead code — into the
        # cognition loop so agents perceive their *current* surroundings.
        # Endogenous road congestion (P1): the city map's per-edge travel-time
        # multiplier — read by ``travel_plan`` since day one, never written —
        # is now recomputed each tick from the trips agents actually made.
        # Off by default: it changes every trip's duration and cost, so runs
        # from before it was switched on are not comparable.
        # How a resident picks a way to travel. "scored" weighs every feasible
        # mode against the others by travel time plus fare converted to time at
        # the traveller's own value of time — the standard discrete-choice
        # form, and the only version in which a car owner can drive a short
        # trip. Off because it is not calibrated: its comfort parameters
        # outnumber the published shares available to fit them against.
        "mode_choice": {
            "scored": False,
        },
        # Who has a bike or an e-bike. Cars were modelled; the thing most
        # people actually ride was not, so every resident was treated as
        # having one and the cheapest, quickest option was always available.
        # Anchor: China's e-bike stock passed 400 million in 2024 against
        # ~1.41 billion people (~0.28 each, all ages); ownership among
        # working-age commuters runs higher than that.
        "two_wheeler_ownership": {
            "enabled": True,
            "pivot_income_multiple": 0.35,
            "spread": 1.1,
            "riding_age": 16,
        },
        # Who can choose to drive. Mode choice had no ownership test at all,
        # so a 6-10km trip without metro access simply became a car trip.
        # Ownership rises with income on a logistic in log-income, with the
        # 50% point at a multiple of *this* population's median so the same
        # numbers carry over to a richer or poorer town.
        "car_ownership": {
            "enabled": True,
            "pivot_income_multiple": 1.2,
            "spread": 0.55,
            "driving_age": 18,
        },
        "traffic": {
            "enabled": False,
            # BPR link performance function: t = t0 * (1 + alpha*(v/c)^beta).
            # The standard parameterisation; beta=4 gives "free until ~80% of
            # capacity, then a cliff" without any extra thresholding.
            "alpha": 0.15,
            "beta": 4.0,
            # How many real travellers one simulated agent stands for. The
            # population is a *sample*, so at 1.0 the volume/capacity ratio is
            # ~0 and congestion never happens. This is a MODELLING KNOB, not a
            # demographic fact — results that depend on the absolute level of
            # congestion must be argued across a range of values, not at one.
            "agents_represent": 1.0,
            # Ceiling on the multiplier, so beta=4 cannot produce absurd trips.
            "max_congestion": 3.0,
            # Weight of the previous tick's congestion when blending in this
            # tick's. Keeps jams easing off instead of snapping to free flow.
            "decay": 0.5,
            # Passenger-car equivalents per transport mode. Walking and metro
            # are off-road; a bus takes more road space than a car.
            "mode_pcu": {
                "car": 1.0, "taxi": 1.0, "bus": 2.0,
                "e-bike": 0.2, "bike": 0.2, "walk": 0.0, "metro": 0.0,
            },
            # One-direction capacity in PCU per hour, by road class.
            "road_capacity": {
                "arterial": 1800.0, "collector": 900.0, "local": 400.0, "road": 900.0,
            },
            # RUSH_HOUR_TIME_MULT is a static stand-in for peak-hour slowdown
            # — the very thing modelled here. Leaving both on counts it twice,
            # so the time-side multiplier steps aside while this layer is on.
            # (The taxi rush-hour surcharge is a fare rule and is unaffected.)
            "suppress_rush_hour_mult": True,
        },
        "local_physical": {
            "enabled": True,
            # Crowding labels are derived from occupancy / capacity.
            "crowd_busy_ratio": 0.6,
            "crowd_packed_ratio": 0.9,
            # Inject the local snapshot text into per-step perception context.
            "inject_into_perception": True,
            # P2 emergent anomaly: flag a location as anomalous when it is
            # packed *and* occupancy jumped sharply versus the previous tick.
            "crowd_anomaly_ratio": 0.9,
            "crowd_anomaly_jump": 0.25,
            # Write the per-tick occupancy the perception loop already computes
            # to the recorder. Off by default: it is one row per tick and only
            # the Track B redistribution analysis reads it.
            "record_occupancy": False,
        },
        # P5: per-agent home design + at-home perception. Default-on so a
        # fresh checkout ships with every resident having a home; turn it
        # off (or set ``enabled=False``) if a run is comparing apples to
        # apples against the pre-P5 baseline.
        "home": {
            "enabled": True,
            # Seed for the procedural home generator. Deterministic per agent
            # id, so two runs with the same seed produce the same homes.
            "seed": 42,
            # When on, the procedural home gets passed through an LLM that
            # polishes furniture names and writes a one-line ``vibe``.
            "llm_enrich": False,
            # Inject the at-home room/ambiance line into perception prompts.
            "inject_into_perception": True,
            # Append one observation row per tick to ``output/home/agent_<id>.jsonl``.
            "record_observations": True,
        },
        # Anomaly modelling (P2): promotes "异常" to a first-class signal on
        # top of the continuous ``severity``. Routine fluctuations (ordinary
        # weather, small market moves) are not anomalies; extreme/shock/
        # emergency events and high-severity events are.
        # NB: the *reaction-side* escalation magnitudes (priority boost,
        # non-resumable score) are fixed constants in ``behavior/dynamic.py``,
        # which is intentionally decoupled from CONFIG; only the *detection*
        # thresholds below are configurable here.
        "anomaly": {
            "enabled": True,
            "severity_threshold": 0.65,
            "intraday_threshold": 0.45,
        },
        # Same-day replanning (P3): when a *persistent* anomaly makes the
        # current activity unworkable (venue closed, crowd surge, emergency),
        # defer the disrupted slots in the affected window instead of only
        # patching the single current step.
        "replan": {
            "enabled": True,
            # How far ahead the disruption is assumed to persist (minutes).
            "window_minutes": 120,
            # Spacing used when re-placing deferred activities after the window.
            "defer_gap_minutes": 30,
        },
        # Structured spatial learning (P4): sediment location-bound anomaly
        # experiences into a reusable avoidance preference that later biases
        # location choice. In-memory across a run; decays by recency.
        "spatial_preferences": {
            "enabled": True,
            "anomaly_weight": 1.0,
            "avoid_threshold": 1.5,
            "half_life_days": 7.0,
        },
        # Distributed multi-machine simulation.
        # Run a relay server and let each node process its own local agent subset.
        "distributed": {
            "enabled": True,
            "cluster": "default",
            # Leave empty to auto-generate using hostname + pid.
            "node_id": "",
            # Optional local subset override for this machine.
            # If enabled and non-empty, this list overrides CONFIG["agent_ids"].
            "local_agent_ids": [],
            # Optional explicit cross-machine peers.
            # If empty, peers are discovered from relay directory.
            "peer_agent_ids": [],
            "send_probability": 0.18,
            "max_outbound_per_step": 1,
            "max_inbound_per_step": 3,
            "message_max_chars": 160,
            "fail_fast": False,
            "relay": {
                "base_url": "http://127.0.0.1:8877",
                "timeout": 3,
            },
            "server": {
                "host": "0.0.0.0",
                "port": 8877,
                "state_path": "output/distributed/relay_state.json",
                "max_messages": 20000,
            },
        },
        # OpenClaw external agent integration.
        # Allows users to connect their personal OpenClaw agents to the simulation.
        "openclaw": {
            "enabled": False,
            # ID range for auto-assigned OpenClaw agents (avoid collision with native IDs).
            "id_range_start": 1001,
            # Auth tokens that OpenClaw bridges must present to register.
            # Empty list = open (no auth required). Set via POST /auth/token or here.
            "auth_tokens": [],
            # Whether the sim engine should push tick state to the relay server
            # so that bridges can synchronise with the simulation clock.
            "push_tick_to_relay": True,
            # Default bridge settings (informational; the bridge reads its own CLI args).
            "bridge_defaults": {
                "poll_interval_seconds": 5.0,
                "openclaw_gateway_url": "http://127.0.0.1:18789",
                "openclaw_timeout": 30,
                "max_inbound_per_cycle": 5,
                "message_max_chars": 300,
            },
        },
        "environment_server": {
            "host": "0.0.0.0",
            "port": 8765,
            "state_path": "output/environment/server_state.json",
            "use_llm": True,
        },
    }
