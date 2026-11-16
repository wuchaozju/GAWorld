"""EventImpactPlugin — events change the world, and each resident reads them
differently.

编排者，不是拥有者。它做四件事：

1. **收事件** —— 本 tick 落到这个居民身上的���人生事件与环境事件；
2. **评估** —— 规则层（零 token，永远跑）先给出预估；严重度够高时再问模型一次，
   把「思考-反应-行动」变成结构化数据；
3. **落地** —— 客观影响池经主体预估缩放筛选后，日程类影响就地改写当天的日程，
   其余领域发 ``event.impact.apply`` 由**拥有该领域的插件**执行
   （经济 → ``gaworld/economy/plugin.py``，家庭 → ``gaworld/family/plugin.py``）；
4. **留痕** —— 思考、预估、计划与实际落地写进 ``output/event_responses/``。

编排者不 import 领域逻辑：它描述"发生了什么、影响多大"，各领域自己决定
"怎么改"。这条信任边界与仓库里既有的 ``life.event.applied`` 一致。

配置：``CONFIG["event_impact"]``。
设计：``docs/proposals/2026-11-15-event-impact-cascade.md``。
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any

from gaworld.events.appraisal import rule_appraisal
from gaworld.events.appraisal_llm import llm_appraisal, merge_with_rule
from gaworld.events.cascade import (
    ImpactLedger,
    apply_schedule_impacts,
    appraisal_key,
    ledger_key,
    plan_actions_to_impacts,
    select_impacts,
)
from gaworld.events.impact import impact_pool_for_event
from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.events.impact_plugin")

_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "appraisal": {
        "enabled": True,
        "llm_enabled": True,
        "llm_min_severity": 0.55,
        "max_events_per_step": 2,
    },
    "cascade": {
        "enabled": True,
        "max_impacts_per_event": 4,
    },
    "output_dir": "",
}

_CSV_FIELDS = [
    "day",
    "time",
    "agent_id",
    "agent_name",
    "event_id",
    "event_title",
    "event_kind",
    "objective_severity",
    "perceived_severity",
    "sensitivity",
    "primary_concern",
    "coping_style",
    "resilience",
    "duration_days",
    "source",
    "applied_domains",
    "applied_count",
    "thought",
]


def event_impact_config(config: Any = None) -> dict[str, Any]:
    """``CONFIG["event_impact"]`` merged over the packaged defaults."""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _DEFAULT_CONFIG.items()}
    raw = (config or {}).get("event_impact") if isinstance(config, dict) else None
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                merged = dict(cfg[key])
                merged.update(value)
                cfg[key] = merged
            else:
                cfg[key] = value
    return cfg


def _signature(row: dict[str, Any]) -> str:
    """What makes two impacts of the same domain and kind *different*.

    Two schedule changes are different when they change the day differently
    ("go to the hospital" vs "go to the clinic"); everything else of the same
    domain and kind is the same change.
    """
    impact = row.get("impact")
    params = getattr(impact, "params", None) or {}
    if row.get("domain") == "schedule":
        return str(params.get("replacement") or params.get("activity") or "")
    return ""


class EventImpactPlugin(Plugin):
    id = "event_impact"

    def setup(self, ctx):
        self._cfg = event_impact_config(getattr(ctx, "config", None))
        self._bus = ctx.bus
        if not self._cfg.get("enabled", True):
            return
        appraisal_cfg = self._cfg.get("appraisal") or {}
        cascade_cfg = self._cfg.get("cascade") or {}
        self._appraisal_enabled = bool(appraisal_cfg.get("enabled", True))
        self._llm_enabled = bool(appraisal_cfg.get("llm_enabled", True))
        self._llm_min_severity = float(appraisal_cfg.get("llm_min_severity", 0.55))
        self._max_events = max(1, int(appraisal_cfg.get("max_events_per_step", 2)))
        self._cascade_enabled = bool(cascade_cfg.get("enabled", True))
        self._max_impacts = max(1, int(cascade_cfg.get("max_impacts_per_event", 4)))
        # Empty means "this plugin's own directory" (Database-per-Plugin).
        self._output_dir = str(self._cfg.get("output_dir") or "").strip() or str(self.output_dir(ctx))

        ctx.bus.on("appraisal.compose", self._appraise)
        # Fast-forward runs no ticks, so the appraisal never happens there
        # unless the plugin asks for it explicitly. Priority -1 puts it after
        # the life-events plugin, which publishes what it consumed.
        ctx.bus.on("life.step", self._fastforward, priority=-1)
        ctx.bus.on("perception.compose", self._perception, priority=25)

    # -- the appraisal ------------------------------------------------------

    def _appraise(self, value, hook_ctx):
        """``appraisal.compose`` filter: assess this resident's events."""
        if value is not None:
            return None  # an upstream producer already appraised
        if not self._appraisal_enabled:
            return None
        sim = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        step = hook_ctx.get("step") or {}
        day = hook_ctx.get("day")
        time_str = hook_ctx.get("time_str")
        schedule_map = hook_ctx.get("schedule_map") or {}

        results = []
        for event in self._collect_events(step)[: self._max_events]:
            outcome = self._process(
                sim,
                agent,
                event,
                day=day,
                time_str=time_str,
                schedule_map=schedule_map,
                step=step,
                daily_logs=hook_ctx.get("daily_logs"),
            )
            if outcome:
                results.append(outcome)

        summary = self._summarize(agent, results, day=day, time_str=time_str)
        sim.agent_ext(agent, self.id)["appraisal"] = summary
        return summary or None

    def _fastforward(self, hook_ctx):
        """Fast-forward: assess life events, but without a schedule to bend.

        Runs *after* the life-events plugin (priority -1 against its 0), so
        the events this step consumed are already published in the plugin
        state — draining the queue again here would find them consumed and
        silently apply them to nobody.
        """
        if not self._appraisal_enabled:
            return
        sim = hook_ctx["sim"]
        day = hook_ctx.get("day")
        time_str = hook_ctx.get("time_str") or "fast_forward"
        agents = hook_ctx.get("agents") or []
        step_events = sim.plugin_state("life_events").get("step_events") or {}
        if not step_events:
            return
        for agent in agents:
            events = list(step_events.get(int(agent["id"])) or [])
            if not events:
                continue
            for event in events[: self._max_events]:
                self._process(
                    sim,
                    agent,
                    event,
                    day=day,
                    time_str=time_str,
                    schedule_map=None,
                    step=None,
                )

    def _collect_events(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        """The events that landed on this resident this tick."""
        out: list[dict[str, Any]] = []
        for event in step.get("life_events") or []:
            if isinstance(event, dict):
                out.append(event)
        for event in step.get("_env_events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("life_event"):
                continue  # already covered above, in its full form
            out.append(event)
        return out

    def _process(
        self,
        sim,
        agent: dict[str, Any],
        event: dict[str, Any],
        *,
        day: Any,
        time_str: Any,
        schedule_map: Any,
        step: Any,
        daily_logs: Any = None,
    ) -> dict[str, Any] | None:
        """Assess one event and land its impacts. ``None`` when nothing lands."""
        impacts = impact_pool_for_event(event)
        if not impacts:
            return None

        # One assessment per event: an event's consequences must not depend on
        # how many times the tick loop looks at it.
        ledger = ImpactLedger(agent)
        assessed = appraisal_key(event, day)
        if ledger.already_applied(assessed):
            return None

        schedule = None
        if isinstance(schedule_map, dict) and agent.get("id") in schedule_map:
            schedule = schedule_map.get(agent["id"])

        rule = rule_appraisal(agent, event, impacts, schedule=schedule, config=self._cfg)
        severity = float(rule.get("objective_severity", 0.5))

        llm: dict[str, Any] = {}
        if self._llm_enabled and severity >= self._llm_min_severity:
            llm = llm_appraisal(agent, event, rule, impacts, config=self._cfg)
        appraisal = merge_with_rule(rule, llm)

        selected = select_impacts(impacts, appraisal, max_impacts=self._max_impacts)
        if not selected:
            return None

        # The model's own plan enters the same channel as the template's.
        plan_impacts = plan_actions_to_impacts(appraisal.get("actions"), time_str=str(time_str or ""))
        if plan_impacts:
            plan_selected = select_impacts(plan_impacts, appraisal, max_impacts=self._max_impacts)
            # The resident's own plan gets the room it needs; the template's
            # impacts fill what is left. The cap still holds on the total.
            selected = sorted(plan_selected + selected, key=lambda row: -row["scale"])
            selected = selected[: self._max_impacts]

        applied: list[dict[str, Any]] = []
        schedule_rows: list[dict[str, Any]] = []
        for row in selected:
            key = ledger_key(event, row["domain"], row["kind"], day, _signature(row))
            if ledger.already_applied(key):
                continue
            if row["domain"] == "schedule":
                if schedule_map is None:
                    continue
                schedule_rows.append(row)
                applied.append(row)
                continue
            if not self._cascade_enabled:
                continue
            self._bus.emit(
                "event.impact.apply",
                sim=sim,
                agent=agent,
                impact=row["impact"],
                scale=row["scale"],
                objective_severity=row["objective_severity"],
                # NB: the payload key cannot be ``event`` — ``EventBus.emit``
                # names its first parameter ``event``, so ``event=`` collides
                # with it and the bus swallows the TypeError as a handler
                # failure. Same trap the life-events plugin documents.
                source_event=event,
                day=day,
                time_str=time_str,
            )
            ledger.mark(key, {"scale": row["scale"], "domain": row["domain"]})
            applied.append(row)

        schedule_changes: list[dict[str, Any]] = []
        if schedule_rows and isinstance(schedule_map, dict):
            agent_id = agent.get("id")
            current = schedule_map.get(agent_id)
            if current:
                new_schedule, schedule_changes = apply_schedule_impacts(
                    current, schedule_rows, time_str=str(time_str or "")
                )
                if schedule_changes:
                    schedule_map[agent_id] = new_schedule
                    for row in schedule_rows:
                        key = ledger_key(event, row["domain"], row["kind"], day, _signature(row))
                        ledger.mark(key, {"scale": row["scale"], "domain": row["domain"]})

        ledger.mark(assessed, {"day": day, "title": str(event.get("title", ""))})
        if not applied:
            return None

        self._apply_emotion(agent, appraisal)
        self._apply_environment(sim, agent, applied, event=event, day=day)
        summary = {
            "day": day,
            "time": time_str,
            "agent_id": agent.get("id"),
            "agent_name": agent.get("name", ""),
            "event_id": event.get("id", ""),
            "event_title": str(event.get("title", event.get("name", "")) or ""),
            "event_kind": str(event.get("template_key", event.get("topic", "event")) or "event"),
            "objective_severity": rule.get("objective_severity", severity),
            "perceived_severity": appraisal.get("perceived_severity", severity),
            "sensitivity": appraisal.get("sensitivity", 1.0),
            "concerns": appraisal.get("concerns", {}),
            "primary_concern": appraisal.get("primary_concern", ""),
            "coping_style": appraisal.get("coping_style", ""),
            "resilience": appraisal.get("resilience", 1.0),
            "duration_days": appraisal.get("duration_days", 1),
            "source": appraisal.get("source", "rules"),
            "thought": appraisal.get("thought", ""),
            "emotion": appraisal.get("emotion", {}),
            "expected_consequences": appraisal.get("expected_consequences", []),
            "seek_help_from": appraisal.get("seek_help_from", []),
            "info_needed": appraisal.get("info_needed", []),
            "rationale": appraisal.get("rationale", []),
            "applied": [
                {
                    "domain": row["domain"],
                    "kind": row["kind"],
                    "scale": row["scale"],
                    "note": getattr(row["impact"], "note", ""),
                }
                for row in applied
            ],
            "schedule_changes": schedule_changes,
        }
        self._record(summary)
        self._note(agent, summary, daily_logs)
        return summary

    def _note(self, agent: dict[str, Any], summary: dict[str, Any], daily_logs: Any) -> None:
        """The event response, written where a resident can read it back.

        The daily log is what an operator reads; the memory entry is what the
        resident's own recall sees next time something similar happens — which
        is how "他上次是怎么处理的" becomes part of the behaviour.
        """
        title = summary.get("event_title", "") or "这件事"
        applied = summary.get("applied") or []
        domains = "、".join(sorted({str(a.get("domain")) for a in applied})) or "无明显变化"
        text = (
            f"[EventResponse Day {summary.get('day')} {summary.get('time')}] "
            f"{agent.get('name', agent.get('id', 'agent'))} 对「{title}」的判断："
            f"严重度 {summary.get('perceived_severity', 0)}，"
            f"最在意 {summary.get('primary_concern', '—')}；"
            f"实际影响：{domains}"
        )
        thought = str(summary.get("thought", "") or "").strip()
        if thought:
            text += f"；{thought}"
        if daily_logs is not None:
            try:
                daily_logs[agent["id"]] += text + "\n"
            except (KeyError, TypeError):
                pass
        try:
            from gaworld.sim._diary import _append_memory_record

            _append_memory_record(
                agent,
                text,
                entry_type="event_response",
                day=summary.get("day"),
                time_str=str(summary.get("time") or ""),
            )
        except Exception as exc:  # a memory write must not break the step
            _LOG.warning("event response memory write failed: %s", exc)

    # -- emotion ------------------------------------------------------------

    def _apply_emotion(self, agent: dict[str, Any], appraisal: dict[str, Any]) -> None:
        """The model's emotional reaction, on top of the template's deltas.

        Scaled by the perceived severity: a resident who reads the event as
        minor does not swing as hard as one who reads it as major.
        """
        emotion = appraisal.get("emotion")
        if not isinstance(emotion, dict):
            return
        state = agent.get("state")
        if not isinstance(state, dict):
            return
        severity = float(appraisal.get("perceived_severity", 0.5))
        factor = max(0.0, min(1.6, severity))
        for key, target in (("delta_emotion", "emotion"), ("delta_stress", "stress")):
            raw = emotion.get(key)
            if raw is None:
                continue
            try:
                delta = float(raw) * factor
            except (TypeError, ValueError):
                continue
            current = float(state.get(target, 0.5))
            state[target] = max(0.0, min(1.0, current + delta))

    # -- environment --------------------------------------------------------

    def _apply_environment(
        self,
        sim,
        agent: dict[str, Any],
        applied: list[dict[str, Any]],
        *,
        event: dict[str, Any],
        day: Any,
    ) -> None:
        """Environment conditions: city-wide ones are shared, personal ones local."""
        conditions = sim.plugin_state(self.id).setdefault("conditions", {})
        for row in applied:
            impact = row.get("impact")
            domain = row.get("domain")
            if domain != "environment" or impact is None:
                continue
            params = impact.params or {}
            key = str(params.get("key") or "condition")
            label = str(params.get("label") or impact.note or key)
            scope = str(params.get("scope") or ("city" if event.get("scope") == "city" else "agent"))
            try:
                day_int = int(day)
            except (TypeError, ValueError):
                day_int = 0
            if scope == "city":
                conditions[key] = {
                    "key": key,
                    "label": label,
                    "scope": scope,
                    "day": day_int,
                    "severity": row.get("objective_severity", 0.5),
                    "scale": row.get("scale", 1.0),
                }
            else:
                store = sim.agent_ext(agent, self.id).setdefault("environment", {})
                entries = store.setdefault("conditions", {})
                entries[key] = {
                    "key": key,
                    "label": label,
                    "scope": scope,
                    "day": day_int,
                    "severity": row.get("objective_severity", 0.5),
                    "scale": row.get("scale", 1.0),
                }

    # -- perception ---------------------------------------------------------

    def _perception(self, hook_ctx):
        """The resident's own reading of the event, plus the environment."""
        sim = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        store = sim.agent_ext(agent, self.id)
        appraisal = store.get("appraisal") or {}
        lines: list[str] = []

        for event in appraisal.get("events") or []:
            line = self._appraisal_line(event)
            if line:
                lines.append(line)

        conditions = sim.plugin_state(self.id).get("conditions") or {}
        day = hook_ctx.get("day")
        for condition in conditions.values():
            try:
                if int(condition.get("day", -1)) != int(day):
                    continue
            except (TypeError, ValueError):
                continue
            lines.append(f"环境状况：{condition.get('label', '')}")
        for condition in (store.get("environment") or {}).get("conditions", {}).values():
            lines.append(f"身边的环境：{condition.get('label', '')}")

        lines = [line for line in lines if line and str(line).strip()]
        if not lines:
            return None
        return "\n".join(lines)

    def _appraisal_line(self, event: dict[str, Any]) -> str:
        title = event.get("event_title", "") or "这件事"
        severity = event.get("perceived_severity", 0.0)
        try:
            severity = float(severity)
        except (TypeError, ValueError):
            severity = 0.0
        concern = str(event.get("primary_concern", "") or "")
        concern_zh = {
            "economy": "经济",
            "family": "家庭",
            "schedule": "日程",
            "environment": "环境",
        }.get(concern, concern)
        thought = str(event.get("thought", "") or "").strip()
        line = f"我对「{title}」的判断：严重程度 {severity:.2f}"
        if concern_zh:
            line += f"，最在意的是{concern_zh}"
        tone = str((event.get("emotion") or {}).get("tone", "") or "").strip()
        if tone:
            line += f"，{tone}"
        if thought:
            line += f"。{thought}"
        return line

    # -- records ------------------------------------------------------------

    def _summarize(
        self,
        agent: dict[str, Any],
        results: list[dict[str, Any]],
        *,
        day: Any,
        time_str: Any,
    ) -> dict[str, Any]:
        return {
            "agent_id": agent.get("id"),
            "day": day,
            "time": time_str,
            "events": results,
        }

    def _record(self, summary: dict[str, Any]) -> None:
        """Write the event-response record (JSONL + CSV)."""
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            jsonl_path = os.path.join(self._output_dir, "event_responses.jsonl")
            with open(jsonl_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(summary, ensure_ascii=False, default=str) + "\n")
            csv_path = os.path.join(self._output_dir, "event_responses.csv")
            applied = summary.get("applied") or []
            row = {
                "day": summary.get("day", ""),
                "time": summary.get("time", ""),
                "agent_id": summary.get("agent_id", ""),
                "agent_name": summary.get("agent_name", ""),
                "event_id": summary.get("event_id", ""),
                "event_title": summary.get("event_title", ""),
                "event_kind": summary.get("event_kind", ""),
                "objective_severity": summary.get("objective_severity", ""),
                "perceived_severity": summary.get("perceived_severity", ""),
                "sensitivity": summary.get("sensitivity", ""),
                "primary_concern": summary.get("primary_concern", ""),
                "coping_style": summary.get("coping_style", ""),
                "resilience": summary.get("resilience", ""),
                "duration_days": summary.get("duration_days", ""),
                "source": summary.get("source", ""),
                "applied_domains": "|".join(sorted({str(a.get("domain")) for a in applied})),
                "applied_count": len(applied),
                "thought": str(summary.get("thought", "") or "")[:300],
            }
            write_header = not os.path.exists(csv_path)
            with open(csv_path, "a", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
                if write_header:
                    writer.writeheader()
                writer.writerow({key: row.get(key, "") for key in _CSV_FIELDS})
        except OSError as exc:
            _LOG.warning("event response record failed: %s", exc)


__all__ = ["EventImpactPlugin", "event_impact_config"]
