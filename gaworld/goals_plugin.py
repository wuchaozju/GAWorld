"""GoalsPlugin — goal-hierarchy lifecycle as a kernel plugin.

Owns bootstrap (``agents.built``) and the day-end review cadence
(``on_day_end``): weekly reviews every ``review_interval_days`` days plus
event-triggered reviews after severe life events. Daily goal-progress
application stays inline next to ``consolidate_day`` in the run loop —
the same interim coupling the interests read-side consumers use.

Interim coupling, by design: goals live at ``agent["goals"]`` (not
``agent["ext"]``) because the read-side consumers (intention/routine/
diary/interview prompts, episode salience) are still inline.
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.goals_plugin")


class GoalsPlugin(Plugin):
    id = "goals"

    def setup(self, ctx):
        from gaworld import goals as impl
        from gaworld.memory.store import append_agent_log

        self._impl = impl
        self._append_agent_log = append_agent_log
        self._cfg = impl.goals_config(ctx.config.get("goals", {}) or {})
        self._enabled = bool(self._cfg.get("enabled", True))
        ctx.bus.on("agents.built", self._bootstrap)
        if not self._enabled:
            return
        # priority=5: after the interests day-end pass (10), before the
        # economy's config-registered settlement (0).
        ctx.bus.on("on_day_end", self._day_end_reviews, priority=5)

    # -- hooks ---------------------------------------------------------------

    def _bootstrap(self, hook_ctx):
        sim = hook_ctx["sim"]
        agents = hook_ctx.get("agents", [])
        if not self._enabled:
            for agent in agents:
                agent["goals"] = {}
            return
        self._impl.bootstrap_goals(
            agents,
            llm=lambda prompt: sim.llm(prompt, task="goals_bootstrap", agent_id=None),
            memory_dir=sim.config.get("memory_dir", "output/memory"),
            stateful=bool(sim.config.get("stateful", False)),
            config=self._cfg,
            day=0,
        )
        for agent in agents:
            context = self._impl.format_goals_context(agent.get("goals"))
            line = f"[Goals] {agent.get('name', agent['id'])}\n{context}\n"
            print(line.strip())
            self._append_agent_log(agent, line)

    def _day_end_reviews(self, hook_ctx):
        # Long-horizon fast-forward replays the day-boundary hooks in chunks
        # (a year = 12 emissions), but a goal review is a *cognitive* beat, not
        # a bookkeeping one: run it once per simulation step, on the final
        # chunk. Day and month steps are a single chunk, so this is a no-op
        # there; a year step reviews once instead of twelve times.
        if hook_ctx.get("coarse") and not hook_ctx.get("period_end", True):
            return
        sim = hook_ctx["sim"]
        day = int(hook_ctx.get("day", 0) or 0)
        agents = hook_ctx.get("agents", [])
        stateful = bool(sim.config.get("stateful", False))
        memory_dir = sim.config.get("memory_dir", "output/memory")
        interval = int(self._cfg.get("review_interval_days", 7))
        weekly_budget = int(self._cfg.get("max_reviews_per_day", 20))
        for agent in agents:
            goals = agent.get("goals")
            if not isinstance(goals, dict) or not goals:
                continue
            trigger = None
            trigger_event = self._severe_event_today(agent, day)
            if trigger_event is not None or goals.get("needs_review"):
                trigger = "event"
                # Mark before the LLM call: a failed review keeps the flag
                # set, so the event review retries tomorrow.
                goals["needs_review"] = True
            elif day - int(goals.get("last_review_day", 0) or 0) >= interval:
                if weekly_budget <= 0:
                    continue  # deferred: last_review_day untouched, retries tomorrow
                trigger = "weekly"
                weekly_budget -= 1
            if trigger is None:
                continue
            _goals, summary = self._impl.run_goal_review(
                agent,
                llm=lambda prompt: sim.llm(
                    prompt, task="goals_review", agent_id=agent["id"]),
                day=day,
                trigger=trigger,
                trigger_event=trigger_event,
                config=self._cfg,
            )
            if stateful:
                self._impl.save_agent_goals(agent["id"], agent.get("goals", {}), memory_dir)
            if summary:
                label = "目标周回顾" if trigger == "weekly" else "目标重估"
                line = f"🎯 {agent.get('name', agent['id'])} 的{label}：{summary}\n"
                print(line.strip())
                self._append_agent_log(agent, line)

    # -- helpers -------------------------------------------------------------

    def _severe_event_today(self, agent, day):
        """Highest-severity consumed life event for this agent today at or
        above ``event_review_severity``, else None."""
        from gaworld.events.life import list_life_events

        threshold = float(self._cfg.get("event_review_severity", 0.7))
        try:
            events = list_life_events(include_consumed=True)
        except (OSError, TypeError, ValueError):
            return None
        try:
            agent_id = int(agent.get("id", 0) or 0)
        except (TypeError, ValueError):
            return None
        best, best_sev = None, -1.0
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            try:
                if int(ev.get("triggered_day", -1) or -1) != day:
                    continue
                sev = float(ev.get("severity", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if sev < threshold:
                continue
            ids = ev.get("agent_ids") or []
            if ids:
                try:
                    if agent_id not in [int(x) for x in ids]:
                        continue
                except (TypeError, ValueError):
                    continue
            if sev > best_sev:
                best, best_sev = ev, sev
        return best
