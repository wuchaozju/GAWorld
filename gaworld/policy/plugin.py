"""InterventionPlugin — PolicySim-style feed/metrics as a kernel plugin (K3a).

First built-in subsystem migrated onto the plugin surface. Replaces the
inline calls that lived in ``generative_city_sim.run_simulation``:

- ``agents.built`` (observe): seed the five intervention metric keys into
  ``agent["state"]``. Runs unconditionally (like the old inline init) so the
  initial state snapshot keeps the same schema whether or not the feature
  is enabled.
- ``perception.compose`` (collect, enabled only): build the deterministic
  recommendation feed and contribute it as a perception snippet. The feed
  is stashed in this plugin's ``agent_ext`` namespace for the metrics pass.

  Note two deliberate behavior changes vs. the inline code, documented in
  the CHANGELOG: the snippet now *appends* to the step context (the inline
  version rebuilt it from ``env_context`` and silently dropped the life-event
  context), and it is ordered after the local-physical snippet instead of
  before it.
- ``on_agent_post_step`` (observe, enabled only): update per-agent metrics
  and append the ``intervention_metrics.csv`` row; expose ``intervention_feed``
  / ``intervention_metrics`` on the step dict for lower-priority observers.
"""

from __future__ import annotations

from gaworld.kernel import Plugin


class InterventionPlugin(Plugin):
    id = "intervention"

    def setup(self, ctx):
        # Domain import stays out of kernel assembly; resolved once here.
        from gaworld.policy import intervention as impl

        self._impl = impl
        self._cfg = ctx.config.get("intervention", {}) or {}
        self._enabled = bool(self._cfg.get("enabled", False))
        self._output_dir = self._cfg.get("output_dir", "output/intervention")
        ctx.bus.on("agents.built", self._seed_agent_state)
        if not self._enabled:
            return
        ctx.bus.on("perception.compose", self._inject_feed, priority=10)
        ctx.bus.on("on_agent_post_step", self._record_metrics, priority=10)

    # -- hooks ---------------------------------------------------------------

    def _seed_agent_state(self, hook_ctx):
        for agent in hook_ctx.get("agents", []):
            self._impl.initialize_agent_intervention_state(agent, self._cfg)

    def _inject_feed(self, hook_ctx):
        sim = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        feed = self._impl.build_intervention_feed(
            agent,
            agents_by_id=sim.agents_by_id,
            day=hook_ctx.get("day"),
            time_str=hook_ctx.get("time_str"),
            env_events=hook_ctx.get("env_events") or [],
            policy_event=hook_ctx.get("policy") or hook_ctx.get("policy_desc"),
            news_items=hook_ctx.get("news") or [],
            config=self._cfg,
        )
        sim.agent_ext(agent, self.id)["feed"] = feed
        feed_context = feed.get("context_text", "")
        if feed_context:
            return [f"平台干预推荐：{feed_context}"]
        return None

    def _record_metrics(self, hook_ctx):
        sim = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        step = hook_ctx.get("step") or {}
        feed = sim.agent_ext(agent, self.id).pop("feed", {})
        metrics = self._impl.update_agent_intervention_metrics(
            agent,
            feed=feed,
            action=step.get("action", ""),
            outcome=step.get("outcome", ""),
            reflection=step.get("reflection", ""),
            agents_by_id=sim.agents_by_id,
            config=self._cfg,
        )
        source_counts = feed.get("source_counts", {}) if isinstance(feed, dict) else {}
        self._impl.append_intervention_metrics(
            self._output_dir,
            {
                "day": hook_ctx.get("day"),
                "time": hook_ctx.get("time_str"),
                "agent_id": agent.get("id"),
                "feed_items": len(feed.get("items", [])) if isinstance(feed, dict) else 0,
                "relational_items": source_counts.get("relational", 0),
                "personalized_items": source_counts.get("personalized", 0),
                "headline_items": source_counts.get("headline", 0),
                **metrics,
            },
        )
        # Lower-priority post_step observers keep seeing the same keys the
        # inline code used to put on the step dict.
        step["intervention_feed"] = feed
        step["intervention_metrics"] = metrics
