"""Core simulation, memory, behavior, and policy defaults."""

from __future__ import annotations

from typing import Any


def simulation_settings() -> dict[str, Any]:
    return {
        # Simulation
        "agent_ids": [1, 2, 3, 4, 5],
        "sim_days": 2,
        "seconds_per_day": 10,
        # When False, simulation runs as fast as the CPU/LLM backend allows.
        "simulate_realtime": False,
        "print_agent_profile": False,
        # Time step for simulation timeline (minutes). None/0 uses schedule times only.
        # "time_step_minutes": "2 hours",
        "time_step_minutes": None,
        # Snap every agent's daily schedule onto the ``time_step_minutes`` grid.
        # Without this, the master timeline is the *union* of the grid and every
        # agent's LLM-authored times, so tick count — and therefore total LLM
        # cost — grows super-linearly with the agent count. Snapping pins the
        # tick count at ``1440 / time_step_minutes`` regardless of population
        # size, which is what makes 100+ agent runs affordable.
        # OFF by default: it changes intra-day timing, so existing runs and
        # same-seed traces stay bit-comparable until you opt in. Requires
        # ``time_step_minutes`` to be set; ignored otherwise.
        "time_grid_snap": False,
        # Long-horizon fast-forward mode. When enabled, each *step* is
        # compressed into a single per-agent brief (one LLM call/agent/step)
        # instead of the intra-day tick megaloop, so 60/600-day — and, at
        # month/year granularity, decade-scale — horizons stay tractable.
        # State / goals / relationships still evolve, but approximately. OFF by
        # default so the normal fine-grained loop is unchanged.
        "long_run": {
            "enabled": False,
            # Step unit: "day" | "month" | "year". A coarser unit compresses a
            # whole month/year into one brief per agent, which is what makes
            # multi-year runs affordable (10 years x 50 residents = 500 calls
            # at "year" vs 182,500 at "day"). Sim days still advance normally
            # underneath; only the cognition granularity changes.
            "unit": "day",
            # Use one LLM call per agent per step to author the brief + deltas.
            # When False, the brief is produced deterministically (zero LLM).
            "brief_llm": True,
            # Clamp for the magnitude of any single per-day approximate state
            # delta the digest may apply. Month/year steps scale this up (x2 /
            # x3) since the delta is cumulative over a wider window.
            "max_state_delta": 0.15,
            # Randomness of the long run, 0..1. Higher → more frequent sudden
            # ("burst") events and larger state swings. 0 = fully deterministic
            # (no bursts, no jitter). At month/year granularity the expected
            # burst count scales with the number of days the step covers.
            "randomness": 0.3,
            # Soft length cap (characters) for each agent's daily brief.
            "brief_max_chars": 240,
            # Same, for a month brief; a year brief gets 1.5x this.
            "period_brief_max_chars": 480,
            # A month/year step replays the day-boundary hooks (economy
            # settlement, interest decay, household duties) in chunks of at
            # most this many days, so a year does not book a single day of
            # rent. Capped at 30 so a chunk crosses at most one monthly
            # settlement boundary.
            "hook_chunk_days": 30,
        },
        # Calendar settings for weekday/weekend simulation.
        "calendar": {
            "start_date": "today",
            "start_weekday": "monday",
            "weekend_days": ["saturday", "sunday"],
        },
        # External RAG information (added via CLI/file import).
        "external_rag": {
            "top_k": 2,
            "bootstrap": {
                "enabled": True,
                "use_seed_script": True,
                "only_when_empty": True,
                "profile_items": 3,
                "web_items": 1,
                "use_web_search": True,
                "prefer_cached_news": True,
                "max_chars_per_item": 280,
            },
            # Runtime absorption: at each sim-day boundary, pull a small
            # number of fresh external snippets aimed at the agent's
            # current growth focus / values. Default OFF; opt in with
            # `external_rag.runtime_absorb=true`. Wired by
            # gaworld/memory/ingest.py and the day-tick hook in
            # generative_city_sim.py.
            "runtime_absorb": False,
            "daily_quota_per_agent": 1,
        },
        # Simulation background (time/city/societal status prompt)
        "background": "2025年冬季，中国·杭州。经济发展中等偏稳，青年就业压力上升，生活成本偏高；社会秩序稳定但政策与舆论压力较高。",
        # Data sources
        "csv_path": "data/hangzhou_agents_state_init.csv",
        "md_path": "data/hangzhou_profiles_with_names.md",
        "map_path": "data/citymap.md",
        # Map mode: "virtual" = procedural grid map from `map_path`;
        # "real" = real Hangzhou geography from the OSM bundle at `real_map_path`
        # (generate it with `python3 scripts/dev/fetch_hangzhou_osm.py`).
        #"map_mode": "virtual",
        "map_mode": "real",
        "real_map_path": "data/hangzhou_real.geojson",
        # Mobile digital twin. The twin server is a SEPARATE process from the
        # dashboard (see gaworld/apps/twin_server.py) because the dashboard
        # accepts unauthenticated config-write and process-spawn POSTs and
        # must never be exposed publicly.
        "twin": {
            "enabled": False,
            "root": "output/twin",
            "bindings_path": "data/twin_bindings.json",
            # How stale a snapshot may be before the mirror channel stops
            # applying it and the phone shows "not synced".
            "snapshot_ttl_minutes": 30,
            # A GPS fix farther than this from every map node is reported as
            # out of map rather than snapped to the nearest edge node.
            "max_snap_km": 3.0,
        },
        # Memory / logs
        "stateful": True,
        "memory_dir": "output/memory",
        "log_dir": "output/logs",
        "diary_output_dir": "output/diaries",
        "environment_output_dir": "output/environment",
        "visualization": {
            "enabled": True,
            "output_dir": "output/visualization",
            "site_path": "site/simviz/index.html",
            # Avoid rewriting the full trace file on every tick.
            "flush_every_frames": 24,
        },
        "environment_config_path": "data/environment_config.json",
        # Memory model compatibility gate.
        # When version changes and stateful mode is enabled, run `reset` once.
        "memory_model_version": 3,
        "require_clean_reset_on_memory_model_change": True,
        # Vector DB (memory + logs)
        "vector_db_path": "output/memory/vector_db.sqlite",
        "vector_db_dim": 256,
        "vector_db_top_k": 3,
        "vector_db_max_chars": 2000,
        # Embedding source for `_embed_text`:
        #   "hash" — CRC32 hashed bag-of-words (default; zero-dep, weak).
        #   "llm"  — Call provider's /embeddings endpoint with hash
        #            fallback. Set up via llm.embedding_* settings below.
        "vector_db_embedding_provider": "hash",
        # Memory model knobs. All default to behavior-preserving values so
        # the existing test suite is not affected unless flags flip ON.
        "memory": {
            # Recall-time scoring: weight cos_sim by salience and apply
            # exponential decay on age in days. When False, scoring stays
            # at pure cos_sim (legacy behavior).
            "salience_weight": True,
            "decay_halflife_days": 14,
            # Multiply hit score by (1 + growth_boost_strength * priority)
            # when the hit text matches a GrowthItem template/name. Light
            # touch, default ON because it can only re-rank existing hits.
            "growth_boost": True,
            "growth_boost_strength": 0.15,
            # Periodic consolidation: every N sim-days, summarize recent
            # episodic entries into one or more `semantic` memories.
            "consolidation": {
                "enabled": True,
                "every_days": 3,
                "lookback_days": 3,
                "max_outputs": 3,
            },
            # Periodic decay/forgetting: drop low-salience entries that
            # haven't been recalled in a long time.
            "decay": {
                "enabled": True,
                "every_days": 7,
                "min_age_days": 30,
                "salience_floor": 0.20,
            },
            # Periodic experience → private Skill distillation. Runs on
            # its own cadence inside ``run_daily_memory_lifecycle``.
            "skill_consolidation": {
                "enabled": True,
                "every_days": 3,
                "lookback_days": 3,
                "min_episodes": 2,
            },
        },
        # Skill subsystem (file-backed; library at ``global_dir``, private
        # per-agent skills under the memory dir).
        "skills": {
            "global_dir": "data/skills",
            "inject_into_cognition": True,
            "inject_into_work_brief": True,
            "max_per_prompt": 4,
        },
        # Policy events (description only; effect inferred by LLM)
        "policy_events": [
            {
                "day": 2,
                "time": "10:00",
                "name": "Platform worker protection policy",
                "description": (
                    "Increase social security coverage and wage transparency, "
                    "strengthen platform labor oversight."
                ),
            }
        ],
        # Manual "life events" queue. The dashboard can add targeted events while
        # a simulation is running; the simulator consumes due events on each tick.
        "life_events": {
            "enabled": True,
            "event_dir": "output/life_events",
            "events_file": "events.json",
            # Scale a life event's ``state_effects`` deltas by its severity so a
            # serious event moves the agent's state more than a mild one. The
            # multiplier is ``clip(1 + amplify * (severity - 0.5), 0.5, 1.8)``;
            # an event without a severity falls back to factor 1.0 (unchanged).
            "severity_state_amplify": 0.8,
            # Deterministic same-day reshaping (Part B): a serious,
            # routine-impacting event bends the rest of the day around it
            # instead of only rolling the probabilistic routine-change dice
            # (which a high-commitment activity would usually win).
            "reshape": {
                "enabled": True,
                "severity_threshold": 0.7,
                "window_minutes": 240,
            },
            # Cross-day aftermath (Part C): a serious event leaves a residual
            # that decays over days, is fed to the next days' planning as a
            # "still affecting you" constraint, and applies a small lingering
            # state pressure. Extends impact beyond the single firing tick and
            # the 2-day recency window of ``_recent_life_events_for_prompt``.
            "aftermath": {
                "enabled": True,
                "min_severity": 0.55,
                "decay_per_day": 0.5,
                "min_residual": 0.15,
                "max_age_days": 6,
                "max_items": 4,
                "state_pressure_scale": 0.5,
            },
        },
        # Routine change (chance to deviate from schedule during the day)
        "routine_change": {
            "enabled": True,
            "base_chance": 0.08,
            "event_boost": 0.08,
            "policy_boost": 0.05,
            "max_chance": 0.45,
            # Global "how loosely agents follow their daily routine" knob, 0..1
            # (dashboard-settable). Higher → committed activities resist less,
            # agents feel more free-floating restlessness, and the deviation
            # probability is lifted, so they break from the schedule more often.
            # 0 = strictly follow the tuned defaults (behavior-preserving).
            # Does not apply to sleep slots.
            "randomness": 0.0,
            # Severity-weighting of env/life events on the routine-change
            # decision. Previously events were counted (each +0.10 trigger,
            # +event_boost prob) regardless of how serious they were, so a
            # 0.86 "framed" life event moved the schedule no more than a
            # trivial one. Now each event contributes in proportion to
            # ``max(0, severity - severity_pivot)``. Defaults are tuned so a
            # plain event with the fallback severity (0.5) reproduces the old
            # magnitude, while a high-severity life event nearly guarantees a
            # re-plan.
            "severity_pivot": 0.4,
            "event_trigger_scale": 1.0,
            "event_trigger_cap": 0.6,
        },
        "daily_planning": {
            "anchor_minutes": 30,
            "random_delay_max_minutes": 10,
            # Use yesterday's plan (not a fixed per-archetype template) as
            # today's base schedule, so day-to-day changes accumulate instead
            # of resetting each morning.
            "autoregressive": True,
            "flexible": {
                "enabled": True,
                "min_items": 6,
                "max_items": 12,
                "max_time_shift_minutes": 120,
                "min_gap_minutes": 15,
                "allow_insertions": True,
                # Fraction of base-schedule anchors a candidate must stay near to
                # be accepted (else it's rejected back to the base). Lowered from
                # the former hard-coded 0.45 so the day is less template-locked.
                "min_anchor_match": 0.30,
            },
        },
        "spontaneity": {
            "enabled": True,
            "base_thought_chance": 0.18,
            "max_thought_chance": 0.68,
            "event_boost": 0.10,
            "policy_boost": 0.08,
            "social_boost": 0.08,
            "low_self_control_boost": 0.22,
            "stress_boost": 0.18,
            "fatigue_boost": 0.14,
            "hunger_boost": 0.12,
            "impulse_activity_chance": 0.10,
            "random_action_chance": 0.05,
            "max_override_bonus": 0.35,
        },
        # Concurrency (S3): each *_workers knob caps the parallelism for one
        # stage of the main loop. Default is serial for legacy compatibility.
        "concurrency": {
            "enabled": False,
            "day_routine_workers": 1,
        },
    }
