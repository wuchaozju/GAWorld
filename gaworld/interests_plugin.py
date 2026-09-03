"""InterestsPlugin — interest/skill-growth lifecycle as a kernel plugin (K3d).

Owns the growth-profile *lifecycle* (bootstrap, per-episode progress,
day-end decay/evolution), which used to be three inline blocks in
``run_simulation``:

- ``agents.built`` (observe): bootstrap growth profiles (or seed ``{}``
  when disabled — schema parity with the old inline else-branch);
- ``episode.compose`` (observe): update growth from the just-built episode
  and fill ``episode["growth_matches"]`` / ``["growth_progress"]`` (the
  memorize stage pre-sets empty defaults, so the schema survives when this
  plugin is disabled or absent);
- ``on_day_end`` (observe, priority=10 so it runs before the economy's
  config-registered day-end settlement, matching the old inline order):
  forgetting decay + interest-set evolution + the 🌱 change line.

Interim coupling, by design: the profile stays at ``agent["growth_profile"]``
(not ``agent["ext"]["interests"]``) because two read-side consumers are
still inline — schedule/routine prompt context (``format_growth_context``)
and location/action matching (``match_growth_items``). Move the key when
those migrate.
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interests_plugin")


class InterestsPlugin(Plugin):
    id = "interests"

    def setup(self, ctx):
        # Domain imports stay out of kernel assembly; resolved once here.
        from gaworld import interests as impl
        from gaworld.memory.store import append_agent_log
        from gaworld.sim._utils import _parse_step_minutes

        self._impl = impl
        self._append_agent_log = append_agent_log
        self._parse_step_minutes = _parse_step_minutes
        cfg = ctx.config.get("interests", {}) or {}
        self._cfg = cfg
        self._enabled = bool(cfg.get("enabled", True))
        self._max_items = max(1, int(cfg.get("max_items", 6)))
        ctx.bus.on("agents.built", self._bootstrap)
        if not self._enabled:
            return
        ctx.bus.on("episode.compose", self._grow_from_episode)
        ctx.bus.on("growth.step", self._grow_from_step)
        ctx.bus.on("on_day_end", self._day_end_evolution, priority=10)

    # -- hooks ---------------------------------------------------------------

    def _bootstrap(self, hook_ctx):
        sim = hook_ctx["sim"]
        agents = hook_ctx.get("agents", [])
        if not self._enabled:
            for agent in agents:
                agent["growth_profile"] = {}
            return
        self._impl.bootstrap_growth_profiles(
            agents,
            cache_path=self._cfg.get(
                "cache_path", "output/memory/growth_profiles.json"
            ),
            memory_dir=sim.config.get("memory_dir", "output/memory"),
            llm=lambda prompt: sim.llm(prompt, task="growth_profile", agent_id=None),
            max_items=self._max_items,
            stateful=bool(sim.config.get("stateful", False)),
        )
        for agent in agents:
            context = self._impl.format_growth_context(
                agent.get("growth_profile"), max_items=self._max_items
            )
            growth_log = f"[GrowthProfile] {agent.get('name', agent['id'])}\n{context}\n"
            print(growth_log.strip())
            self._append_agent_log(agent, growth_log)

    def _grow_from_step(self, hook_ctx):
        """Grow skills over a fast-forward step.

        Practice normally accrues on ``episode.compose``, one tick at a time.
        Fast-forward builds no episodes, so only the day-end *decay* ran and
        skills could only fall — a simulated year took 阅读 from 0.30 to 0.10
        no matter how the resident spent it. That is the opposite of
        individual development, and it is worst exactly where development is
        the point.

        The period digest reports average weekly minutes per item; this
        replays the existing power-law curve once per elapsed week rather
        than inventing a second growth model, on consecutive days so the
        streak bonus behaves as it does in a fine-grained run.
        """
        sim = hook_ctx["sim"]
        day = int(hook_ctx.get("day") or 0)
        try:
            span_days = max(1, int(hook_ctx.get("period_days") or 1))
        except (TypeError, ValueError):
            span_days = 1
        weeks = max(1, round(span_days / 7))
        by_agent = hook_ctx.get("development_by_agent") or {}
        stateful = bool(sim.config.get("stateful", False))
        memory_dir = sim.config.get("memory_dir", "output/memory")
        for agent in hook_ctx.get("agents", []) or []:
            entries = by_agent.get(agent["id"]) or []
            if not entries:
                continue
            changed = {}
            for entry in entries:
                name = str(entry.get("item", "")).strip()
                minutes = entry.get("weekly_minutes")
                if not name or not minutes:
                    continue
                for week in range(weeks):
                    episode = {
                        "final_activity": name,
                        "action": str(entry.get("note", "") or name),
                        "reflection": "",
                        # Consecutive days keep the streak bonus meaningful.
                        "day": max(1, day - weeks + week + 1),
                    }
                    profile, progress = self._impl.update_growth_from_episode(
                        agent.get("growth_profile"), episode, step_minutes=int(minutes),
                    )
                    agent["growth_profile"] = profile
                    changed.update(progress.get("level_changes") or {})
            if not changed:
                continue
            if stateful:
                self._impl.save_agent_growth_profile(
                    agent["id"], agent.get("growth_profile"), memory_dir)
            line = "；".join(
                f"{name} {vals['before']:.2f}→{vals['after']:.2f}"
                for name, vals in changed.items()
            )
            text = f"[GrowthStep Day {day}] {agent.get('name', agent['id'])}: {line}\n"
            daily_logs = hook_ctx.get("daily_logs")
            if daily_logs is not None:
                daily_logs[agent["id"]] += text
            self._append_agent_log(agent, text)

    def _grow_from_episode(self, hook_ctx):
        sim = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        episode = hook_ctx["episode"]
        progress_minutes = hook_ctx.get("step_minutes")
        pm_cfg = self._cfg.get("progress_minutes_per_step")
        if pm_cfg is not None:
            parsed = self._parse_step_minutes(pm_cfg)
            if parsed is not None:
                progress_minutes = parsed
        updated_growth, growth_progress = self._impl.update_growth_from_episode(
            agent.get("growth_profile"),
            episode,
            step_minutes=progress_minutes,
        )
        agent["growth_profile"] = updated_growth
        episode["growth_matches"] = list(growth_progress.get("matches", []))
        episode["growth_progress"] = growth_progress
        if bool(sim.config.get("stateful", False)):
            self._impl.save_agent_growth_profile(
                agent["id"],
                agent.get("growth_profile", {}),
                sim.config.get("memory_dir", "output/memory"),
            )

    def _day_end_evolution(self, hook_ctx):
        sim = hook_ctx["sim"]
        day = hook_ctx.get("day")
        agents = hook_ctx.get("agents", [])
        agents_by_id = hook_ctx.get("agents_by_id", {})
        decay_cfg = dict(self._cfg.get("decay", {}) or {})
        evolution_cfg = dict(self._cfg.get("evolution", {}) or {})
        stateful = bool(sim.config.get("stateful", False))
        for agent in agents:
            profile = agent.get("growth_profile")
            if not profile:
                continue
            partner_ids = set()
            for ep in agent.get("episodes", []) or []:
                if int(ep.get("day", 0) or 0) != day:
                    continue
                partner_ids.update(ep.get("social_partners", []) or [])
            candidates: list[str] = []
            for pid in partner_ids:
                partner = agents_by_id.get(pid)
                if partner is None:
                    try:
                        partner = agents_by_id.get(int(pid))
                    except (TypeError, ValueError):
                        partner = None
                if partner is None or partner is agent:
                    continue
                candidates.extend(
                    self._impl.growth_focus(partner.get("growth_profile"), limit=1)
                )
            profile, decay_changes = self._impl.apply_daily_growth_decay(
                profile, day, config=decay_cfg
            )
            profile, evolution_changes = self._impl.evolve_growth_profile(
                profile,
                day,
                social_candidates=candidates,
                config=evolution_cfg,
                max_items=self._max_items,
            )
            agent["growth_profile"] = profile
            if stateful:
                self._impl.save_agent_growth_profile(
                    agent["id"], profile, sim.config.get("memory_dir", "output/memory")
                )
            growth_notes = []
            if decay_changes.get("level_changes"):
                growth_notes.append(
                    f"{len(decay_changes['level_changes'])}项兴趣/技能因久未练习而生疏"
                )
            if evolution_changes.get("retired"):
                growth_notes.append("放下了：" + "、".join(evolution_changes["retired"]))
            if evolution_changes.get("adopted"):
                growth_notes.append(
                    "受身边人影响开始尝试：" + "、".join(evolution_changes["adopted"])
                )
            if growth_notes:
                print(f"🌱 {agent['name']} 的成长变化：{'；'.join(growth_notes)}")
