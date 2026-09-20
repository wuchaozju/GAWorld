"""Environment, distributed simulation, and external-agent defaults."""

from __future__ import annotations

from typing import Any


def environment_settings() -> dict[str, Any]:
    return {
        # Local physical perception (P0): wires the city map's per-node
        # occupancy / opening-hours state — previously dead code — into the
        # cognition loop so agents perceive their *current* surroundings.
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
