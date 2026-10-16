"""HolidayPlugin — the kernel surface for the holiday feature.

Subscribes to the existing ``on_agent_pre_step`` hook (the one that
runs after ``_stage_prepare`` seeds ``scheduled_activity`` but before
the rest of the per-agent pipeline reads it) and rewrites that field
when the sim day sits inside an active holiday window.

Three Controller interventions are registered alongside the hooks so
the dashboard can drive the feature through the existing
``/api/interventions/{name}`` channel without a new HTTP route:

- ``start_holiday(agents, day, days, plan_key=None, seed=None)`` —
  arms a window. Implemented in service.start_holiday.
- ``end_holiday(agents, day)`` — closes the window early.
- ``cancel_holiday(agents)`` — strips every active window.

The plugin honors ``CONFIG["holiday"]["enabled"]``; when False, the
hooks are not registered and the registered interventions still answer
at the HTTP layer but never fire — that is the document the
``gaworld.policy`` plugin ships with.
"""

from __future__ import annotations

import os

from gaworld.holiday import service
from gaworld.kernel import Plugin


class HolidayPlugin(Plugin):
    id = "holiday"

    def setup(self, ctx):
        from gaworld.holiday import normalize_config

        self._cfg = normalize_config(ctx.config.get("holiday") if isinstance(ctx.config, dict) else None)
        self._enabled = bool(self._cfg.get("enabled", True))
        self._output_dir = self._cfg.get("output_dir", "output/holiday")
        if self._enabled:
            os.makedirs(self._output_dir, exist_ok=True)
            ctx.bus.on("on_agent_pre_step", self._rewrite_scheduled, priority=50)
            ctx.bus.on("on_agent_post_step", self._record_tick, priority=20)
        # Standard interventions are present regardless of the enabled
        # flag: a teacher turning the feature off shouldn't be unable to
        # cancel an existing window. ``start_holiday`` short-circuits on
        # ``enabled`` so the rule is enforced without disabling the hook.
        ctx.controller.register_intervention("start_holiday", self._intervene_start)
        ctx.controller.register_intervention("end_holiday", self._intervene_end)
        ctx.controller.register_intervention("cancel_holiday", self._intervene_cancel)

    # -- hooks ---------------------------------------------------------------

    def _rewrite_scheduled(self, hook_ctx):
        step = hook_ctx.get("step") or {}
        if not isinstance(step, dict):
            return
        agent = hook_ctx.get("agent")
        if not isinstance(agent, dict):
            return
        # day / time_str are the only two fields the rewriting rule needs.
        day = hook_ctx.get("day")
        time_str = hook_ctx.get("time_str") or step.get("time_str") or ""
        original = step.get("scheduled_activity")
        if not original:
            return
        replacement = service.pick_replacement_activity(
            agent, time_str=time_str, original_activity=original
        )
        if not replacement:
            return
        # Mark the original for the adjust-activity stage's later log.
        step["_holiday_original_activity"] = original
        step["scheduled_activity"] = replacement["activity"]
        step["activity"] = replacement["activity"]
        step["_holiday_replacement"] = replacement
        step["_holiday_day"] = int(day) if day is not None else None

    def _record_tick(self, hook_ctx):
        step = hook_ctx.get("step") or {}
        if not isinstance(step, dict):
            return
        replacement = step.pop("_holiday_replacement", None)
        if not replacement:
            return
        agent = hook_ctx.get("agent")
        if not isinstance(agent, dict):
            return
        daily_logs = hook_ctx.get("daily_logs")
        line = service.summarize_replacement_log(replacement)
        if not line:
            return
        if isinstance(daily_logs, dict):
            agent_id = agent.get("id")
            if agent_id is not None:
                daily_logs.setdefault(agent_id, "")
                if isinstance(daily_logs[agent_id], str):
                    if line not in daily_logs[agent_id]:
                        daily_logs[agent_id] = f"{daily_logs[agent_id]}\n{line}".strip()
        # Audit row: every agent on holiday leaves one record per tick
        # the replacement fires, so the dashboard can plot a coverage
        # timeline. Recorder.flush is per-row so a future replay sees
        # the same audit shape we record now.
        recorder = hook_ctx.get("recorder")
        if recorder is not None:
            recorder.record(
                "holiday.tick",
                {
                    "agent_id": agent.get("id"),
                    "day": hook_ctx.get("day"),
                    "time": hook_ctx.get("time_str"),
                    "plan_key": replacement.get("plan_key"),
                    "activity": replacement.get("activity"),
                    "reason": replacement.get("reason"),
                },
            )

    # -- interventions -------------------------------------------------------

    def _intervene_start(self, ctx, *, days=None, day=None, plan_key=None, seed=None):
        if not self._enabled:
            raise RuntimeError(
                "holiday feature is disabled (`holiday.enabled=false`); "
                "enable it in config and restart, then start a holiday."
            )
        cfg = self._cfg
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError("start_holiday requires integer `days`") from None
        if not (cfg["min_days"] <= days <= cfg["max_days"]):
            raise ValueError(
                f"start_holiday: `days` must be between "
                f"{cfg['min_days']} and {cfg['max_days']}; got {days}"
            )
        if day is None:
            clock = getattr(ctx, "clock", None)
            day = int(getattr(clock, "day", 1) or 1)
        agents = list(getattr(ctx, "agents", []) or [])
        result = service.start_holiday(
            agents, day=int(day), days=days, plan_key=plan_key, seed=seed
        )
        result["min_days"] = cfg["min_days"]
        result["max_days"] = cfg["max_days"]
        if ctx.recorder is not None:
            ctx.recorder.record(
                "holiday.intervention",
                {
                    "name": "start_holiday",
                    "day": int(day),
                    "days": days,
                    "plan_key": plan_key,
                    "armed": result["armed"],
                    "blocked": result["blocked"],
                },
            )
        return result

    def _intervene_end(self, ctx, *, day=None):
        agents = list(getattr(ctx, "agents", []) or [])
        if day is None:
            clock = getattr(ctx, "clock", None)
            day = int(getattr(clock, "day", 1) or 1)
        result = service.end_holiday(agents, day=int(day))
        if ctx.recorder is not None:
            ctx.recorder.record(
                "holiday.intervention",
                {
                    "name": "end_holiday",
                    "day": int(day),
                    "ended": result["ended"],
                },
            )
        return result

    def _intervene_cancel(self, ctx):
        agents = list(getattr(ctx, "agents", []) or [])
        result = service.cancel_holiday(agents)
        if ctx.recorder is not None:
            ctx.recorder.record(
                "holiday.intervention",
                {"name": "cancel_holiday", "cancelled": result["cancelled"]},
            )
        return result
