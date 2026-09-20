"""Extension hooks and real-work execution defaults."""

from __future__ import annotations

from typing import Any


def integration_settings() -> dict[str, Any]:
    return {
        # Optional extension hooks for custom functions.
        # Each item uses "module:function" import path.
        # NOTE: built-in subsystems no longer register here — the economy's
        # handlers moved to gaworld.economy.plugin.EconomyPlugin (K3f), and
        # built-in assembly lives in gaworld.plugins.builtin_plugins(). This
        # map is for user extensions.
        "extensions": {
            "strict": False,
            "hooks": {},
        },
        "collaboration": {
            "enabled": True,
            "sessions_dir": "output/collaboration/sessions",
            "max_concurrent_sessions": 2,
            "max_context_events": 24,
            "step_retries": 2,
            "discussion": {
                "default_rounds": 6,
                "min_rounds": 3,
                "max_rounds": 20,
            },
        },
        # Real Work Execution (gaworld/work/*).
        # When enabled, "工作"-class activities can be dispatched to local adapters
        # that produce real artifacts under artifacts_dir, and agents can browse a
        # mock job market.
        "real_work": {
            "enabled": True,
            "queue_path": "output/work/queue.jsonl",
            "artifacts_dir": "output/work",
            "capabilities_cache": "output/work/capabilities.json",
            "max_concurrent_tasks": 2,
            "task_timeout_seconds": 600,
            "tick_ingest_limit": 5,
            "adapters": {
                "web_design": {"enabled": True},
                "code": {"enabled": True, "write_pytest": True},
                "content": {"enabled": True},
                "teaching": {"enabled": True},
            },
            "market": {
                "enabled": True,
                "seed_path": "gaworld/work/market_seed.json",
                "store_path": "output/work/market.jsonl",
                "browse_top_k": 5,
                "max_taken_per_agent_per_day": 2,
                "browse_probability_base": 0.15,
                "expire_after_sim_days": 5,
                "auto_replenish": True,
                "replenish_threshold": 5,
            },
            "external_hooks": {
                "webhook_url": "",
                "mcp_server": "",
            },
        },
    }
