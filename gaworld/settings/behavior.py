"""Behavior, media exposure, and intervention defaults."""

from __future__ import annotations

from typing import Any


def news_settings() -> dict[str, Any]:
    return {
        # News / social media reading
        "news": {
            "enabled": True,
            "sources_path": "data/news_source.md",
            "cache_path": "data/news_cache.json",
            "use_cache_first": True,
            "daily_chance": 0.9,
            "max_reads_per_day": 5,
            "timeout": 8,
            "max_chars": 2000,
            "memory_excerpt_chars": 600,
            "user_agent": "GAWorld/1.0",
            "info_seek": {
                "enabled": True,
                "base_daily_chance": 0.55,
                "max_seeks_per_day": 3,
                "preferred_sites_per_agent": 6,
                "prefer_source_visit_ratio": 0.55,
                "engines": ["x", "baidu", "google", "bing"],
                "max_results": 4,
                "timeout": 8,
                "content_timeout": 8,
                "content_max_chars": 2000,
                "memory_excerpt_chars": 700,
                "user_agent": "GAWorld/1.0",
                # Hosted X API MCP server, App-only Bearer route (read-only;
                # see https://docs.x.com/tools/mcp). The "x" engine is skipped
                # silently when the token env var is unset, and falls through
                # to the web engines on throttle / rate limit.
                "x_mcp": {
                    "enabled": True,
                    "url": "https://api.x.com/mcp",
                    "bearer_token_env": "X_BEARER_TOKEN",
                    "max_results": 5,
                    "timeout": 8,
                    "min_interval_seconds": 5.0,
                    "cooldown_on_429_seconds": 900,
                    "cache_ttl_seconds": 900,
                },
                "contextual_keywords": True,
                "contextual_max_keywords": 3,
                "event_driven": {
                    "enabled": True,
                    "max_extra_seeks_per_day": 2,
                    "stress_threshold": 0.6,
                    "curiosity_threshold": 0.6,
                    "trigger_chance_on_event": 0.5,
                },
            },
        },
    }


def intervention_settings() -> dict[str, Any]:
    return {
        # PolicySim-inspired lightweight intervention evaluation.
        # This is deterministic and does not call external moderation or training APIs.
        "intervention": {
            "enabled": True,
            "output_dir": "output/intervention",
            "recommendation": {
                "max_items": 5,
                "source_weights": {
                    "relational": 1.0,
                    "personalized": 0.85,
                    "headline": 0.75,
                },
            },
            "exposure_control": {
                "enabled": True,
                "toxicity_threshold": 0.45,
                "misinformation_threshold": 0.35,
                "suppression_factor": 0.25,
            },
            "stance": {
                "alpha": 0.8,
                "positive_keywords": ["支持", "赞成", "改善", "安心", "信任", "机会", "合作", "透明", "保护"],
                "negative_keywords": ["反对", "担心", "不满", "风险", "冲突", "失望", "质疑", "压力", "限制"],
            },
            "toxicity_keywords": ["辱骂", "攻击", "仇恨", "歧视", "极端", "滚", "骗子", "垃圾"],
            "misinformation_keywords": ["谣言", "假消息", "未经证实", "阴谋", "伪造", "骗局", "造假", "不实"],
            "objectives": {
                "cross_viewpoint_weight": 0.55,
                "engagement_weight": 0.20,
                "toxicity_penalty_weight": 0.15,
                "misinformation_penalty_weight": 0.10,
            },
        },
    }


def human_realism_settings() -> dict[str, Any]:
    return {
        # Agent interests and skill-growth profiles.
        "interests": {
            "enabled": True,
            "max_items": 6,
            "daily_insert_chance": 0.55,
            "weekend_boost": 0.25,
            # Null means use the current timeline step length.
            "progress_minutes_per_step": None,
            "cache_path": "output/memory/growth_profiles.json",
            # Day-end forgetting: unpracticed items lose level after a
            # grace period; accumulated practice raises retention.
            "decay": {
                "enabled": True,
                "grace_days": 2,
                "daily_rate": 0.012,
                "floor": 0.05,
            },
            # Day-end interest-set turnover: retire stale triggered-phase
            # items, adopt new ones from social partners (contagion).
            "evolution": {
                "enabled": True,
                "retire_after_days": 14,
                "adopt_chance": 0.35,
                "max_new_per_day": 1,
            },
        },
        # Goal hierarchy (life / long-term / short-term) driving daily plans.
        # Design doc: docs/superpowers/specs/2026-07-18-long-term-goals-design.md
        "goals": {
            "enabled": True,
            "review_interval_days": 7,
            "event_review_severity": 0.7,
            "max_life_goals": 2,
            "max_long_term": 3,
            "max_short_term": 4,
            "max_daily_progress_delta": 0.34,
            "review_log_keep": 12,
            "relevance_floor": 0.2,
            "relevance_cap": 0.9,
            # Global throttle for weekly reviews per sim-day (event reviews
            # are exempt); deferred agents retry the next day.
            "max_reviews_per_day": 20,
        },
        # Human realism (experience accumulation + habit/need dynamics)
        "human_realism": {
            "enabled": True,
            "llm": {
                "max_extra_calls_per_agent_day": 2,
            },
            "memory": {
                "max_episodes_per_agent": 2000,
                "daily_consolidation_top_k": 12,
                "salience_threshold": 0.35,
                "decay_half_life_days": 14,
                "recall": {
                    "base_top_k": 2,
                    "max_top_k": 5,
                    "planning_top_k": 3,
                    "action_top_k": 3,
                    "reflection_top_k": 4,
                    "interview_top_k": 4,
                    "hint_chars": 240,
                    "surface_min_score": 0.08,
                    "effect_scale": 0.015,
                },
                "review": {
                    "interval_minutes": 240,
                    "max_per_day": 3,
                    "trigger_salience": 0.72,
                    "top_k": 4,
                },
            },
            "behavior": {
                "habit_learning_rate": 0.08,
                # A context must recur this many times before it counts as a
                # habit — keeps one-off interrupts out of the habit table.
                "habit_min_occurrences": 3,
                "inertia_weight": 0.25,
                "decision_noise": 0.18,
                "fatigue_work_gain": 0.035,
                "fatigue_sleep_recovery": 0.18,
                "self_control_recovery": 0.08,
                "time_pressure_decay": 0.06,
                "commitment_weights": {
                    "high": 1.2,
                    "medium": 0.6,
                    "low": 0.2,
                },
                "avoidance_bonus_scale": 1.1,
                "need_weights": {
                    "energy": 0.45,
                    "hunger": 0.30,
                    "social_need": 0.25,
                },
            },
        },
        # Dynamic behaviour system: spontaneous urges, social encounters,
        # need-based interrupts, and environment-triggered activity changes.
        # LLM-generated action spaces.
        "action_space": {
            # How many activities one generation call may ask for.
            #
            # Measured, not guessed. On 848 real ``actions`` completions the
            # per-activity block runs 193 characters at the median and 215 at
            # p75, while the provider's default 512-token cap lets through
            # about 916 characters. Four activities sit right on that edge --
            # 37.5% of the sample was truncated -- and six or more never fit at
            # all. A real day carries ten distinct activities, so the
            # un-chunked call could never have worked; it recovered the first
            # four and the retry then hit the same wall.
            #
            # Three leaves a block of headroom for a verbose agent. Chunking is
            # not more expensive than the old path: ten activities take four
            # calls that succeed, against two that fail plus a per-activity
            # top-up call for each one later.
            "activities_per_call": 3,
        },
        "dynamic_behavior": {
            "enabled": True,
        },
    }
