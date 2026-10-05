"""GroupPlugin — the cohort tier inside a normal run.

Per ``AGENTS.md`` a new subsystem is a ``gaworld.kernel.Plugin``, not inline
logic in ``generative_city_sim.py``. Two jobs, both off by default:

**Group mode** (``simulation_mode: "group"``, day-step fast-forward only).
Each simulated day:

1. ``on_day_start`` — pick today's materialised residents (focal, the audit
   sample, then the cohorts' tails), give every cohort one model call and move
   its *other* members by the cohort's change as a common shift;
2. ``fast_forward.digest_agents`` — narrow the fast-forward brief to the
   materialised few, who run the ordinary individual tier;
3. ``on_day_end`` (early, before the day-boundary subsystems) — fold their
   outcomes back into cohort statistics, compare the audit sample's own
   changes with what its cohort predicted, and raise the audit share of any
   cohort whose residual crossed the alarm (``adapt_audit_boost``).

Everything else about the run is ordinary: every resident's state history,
the ``group.*`` records, the manifest — so the console, parallel worlds and
the research workbench read a group run like any other. Cohort changes are
limited to the state variables the fast-forward brief can move, so the two
tiers describe the same quantities and the audit compares like with like.

Not for network-diffusion questions: a cohort moves its members together and
never consults the social graph, which is exactly the validation gate's L2
failure (design doc §8.5); the coupling term that fixes it needs the
synthesiser's graph and is not wired here.

**Telemetry** (``group.enabled`` in an individual run): partition the
population and record cohort statistics daily, changing nothing.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from gaworld.kernel import Plugin

MODES: tuple[str, ...] = ("individual", "group")


def group_config(config: dict[str, Any]) -> dict[str, Any]:
    """The ``group`` block over its shipped defaults."""
    from gaworld.settings.runtime import simulation_settings

    merged = dict(simulation_settings()["group"])
    block = config.get("group") if isinstance(config, dict) else None
    if isinstance(block, dict):
        merged.update(block)
    return merged


def validate_config(config: dict[str, Any]) -> None:
    """Refuse a group run that cannot work, before the run starts."""
    mode = str(config.get("simulation_mode") or "individual")
    if mode not in MODES:
        raise ValueError(f"simulation_mode 只能是 {' / '.join(MODES)}，收到 {mode!r}")
    if mode != "group":
        return
    long_run = config.get("long_run") if isinstance(config.get("long_run"), dict) else {}
    unit = str(long_run.get("unit") or "day").strip().lower()
    if not long_run.get("enabled") or unit != "day":
        raise ValueError(
            "群体模式只能在按天快进下运行：加 --fast-forward（long_run.enabled = true，long_run.unit = day）。"
            "逐 tick 循环没法只让一部分居民走完整管线。"
        )
    cfg = group_config(config)
    if int(cfg["materialization_budget"]) < 0 or not 0 <= float(cfg["audit_fraction"]) <= 1:
        raise ValueError("group.materialization_budget 不能为负，group.audit_fraction 要在 0–1 之间")


def _axis_view(agent: dict[str, Any]) -> dict[str, Any]:
    """The agent as the partition sees it: industry inferred from the job when
    the corpus has no column for it (every hand-written city), or every
    resident would land in industry "none"."""
    if agent.get("industry"):
        return agent
    from gaworld.economy.finance import _infer_industry

    return {**agent, "industry": _infer_industry(agent)}


class GroupPlugin(Plugin):
    """Group mode, or cohort telemetry for an individual run."""

    id = "group"

    def setup(self, ctx: Any) -> None:
        config = ctx.config if isinstance(ctx.config, dict) else {}
        self._config = config
        self._cfg = group_config(config)
        self._recorder = ctx.recorder
        self._llm = getattr(ctx, "llm", None)
        self._cohorts: list[Any] | None = None
        self._today: dict[str, Any] | None = None
        self._boost: dict[str, int] = {}
        self._quiet: dict[str, int] = {}
        self._totals = {"days": 0, "cohort_calls": 0, "individual_calls": 0, "full_calls": 0, "alarms": 0}
        self._boosted: set[str] = set()
        if str(config.get("simulation_mode") or "individual") == "group":
            ctx.bus.on("on_day_start", self._group_day_start)
            ctx.bus.on("fast_forward.digest_agents", self._digest_agents)
            # Before the day-boundary subsystems (economy, family …): the audit
            # compares the tiers' day, not the ledger's settlement on top of it.
            ctx.bus.on("on_day_end", self._group_day_end, priority=100)
            ctx.bus.on("on_simulation_end", self._group_summary)
        elif self._cfg.get("enabled"):
            ctx.bus.on("on_simulation_start", self._telemetry_start)
            ctx.bus.on("on_day_end", self._telemetry_day)

    # -- shared ------------------------------------------------------------

    def _partition(self, agents: list[dict[str, Any]]) -> list[Any]:
        from gaworld.group.cohort import partition_cohorts

        axes = self._cfg.get("cohort_axes") or None
        return partition_cohorts(
            [_axis_view(a) for a in agents],
            axes=axes,
            min_size=int(self._cfg.get("min_cohort_size", 4)),
        )

    # -- group mode --------------------------------------------------------

    def _group_day_start(self, hook_ctx: dict[str, Any]) -> None:
        from gaworld.group.cohort import apply_cohort_state_changes, refresh_cohort_statistics
        from gaworld.group.cohort_day import effective_state_changes, simulate_cohort_day
        from gaworld.group.materialize import select_materialized
        from gaworld.sim._fastforward import LONG_RUN_STATE_KEYS

        agents = list(hook_ctx.get("agents") or [])
        if not agents:
            return
        day = int(hook_ctx.get("day") or 0)
        by_id = {int(a["id"]): a for a in agents}
        if self._cohorts is None:
            self._cohorts = self._partition(agents)
            sizes = [c.size for c in self._cohorts]
            self._recorder.record(
                "group.partition",
                {"population": len(agents), "cohorts": [c.to_dict() for c in self._cohorts]},
            )
            print(
                f"👥 群体模式：{len(agents)} 人 → {len(self._cohorts)} 个群体"
                f"（{min(sizes)}–{max(sizes)} 人），每天实体化 {self._cfg['materialization_budget']} 人"
            )
        for cohort in self._cohorts:
            refresh_cohort_statistics(cohort, by_id)

        seed = int(self._config.get("random_seed") or 0)
        plan = select_materialized(
            self._cohorts,
            by_id,
            day=day,
            budget=int(self._cfg["materialization_budget"]),
            focal_ids=[int(i) for i in self._cfg.get("focal_ids") or []],
            audit_fraction=float(self._cfg["audit_fraction"]),
            rng=np.random.default_rng(seed * 10_000 + day),
            audit_boost=self._boost,
        )
        materialized = set(plan.all_ids)
        audit_before = {
            member_id: {
                k: float(v) for k, v in by_id[member_id]["state"].items() if isinstance(v, (int, float))
            }
            for member_id in plan.audit
        }
        long_run = self._config.get("long_run") if isinstance(self._config.get("long_run"), dict) else {}
        use_llm = bool(long_run.get("brief_llm", True)) and self._llm is not None
        max_delta = float(self._cfg["max_state_delta"])
        digests: dict[str, dict[str, Any]] = {}
        deltas: dict[str, dict[str, float]] = {}
        for cohort in self._cohorts:
            cohort.materialized = materialized & set(cohort.members)
            digest = simulate_cohort_day(
                cohort,
                day=day,
                env_context=str(hook_ctx.get("env_context") or ""),
                max_delta=max_delta,
                use_llm=use_llm,
                llm_fn=self._llm,
            )
            changes = {k: v for k, v in effective_state_changes(digest).items() if k in LONG_RUN_STATE_KEYS}
            deltas[cohort.id] = apply_cohort_state_changes(
                cohort, changes, by_id, max_delta=max_delta, skip=cohort.materialized
            )
            if digest.get("memory"):
                cohort.memory.append(str(digest["memory"]))
                del cohort.memory[:-10]
            digests[cohort.id] = {
                "brief": digest.get("brief", ""),
                "divergence": digest.get("divergence", ""),
                "fallback": bool(digest.get("fallback")),
            }
        self._today = {
            "day": day,
            "plan": plan,
            "materialized": materialized,
            "audit_before": audit_before,
            "digests": digests,
            "deltas": deltas,
            "cohort_calls": len(self._cohorts) if use_llm else 0,
            "individual_calls": len(materialized) if use_llm else 0,
        }

    def _digest_agents(
        self, agents: list[dict[str, Any]], hook_ctx: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        if self._today is None:
            return None
        return [agent for agent in agents if int(agent["id"]) in self._today["materialized"]]

    def _group_day_end(self, hook_ctx: dict[str, Any]) -> None:
        from gaworld.group.materialize import (
            adapt_audit_boost,
            apply_individual_deltas_to_cohort,
            audit_residual,
        )

        today = self._today
        if today is None or self._cohorts is None:
            return
        agents = list(hook_ctx.get("agents") or [])
        by_id = {int(a["id"]): a for a in agents}
        plan = today["plan"]
        residuals = []
        for cohort in self._cohorts:
            apply_individual_deltas_to_cohort(cohort, by_id)
            audit_here = [m for m in plan.audit if m in set(cohort.members)]
            if audit_here:
                residuals.append(
                    audit_residual(
                        cohort, by_id, audit_here, today["deltas"].get(cohort.id, {}), today["audit_before"]
                    )
                )
        alarm = float(self._cfg["residual_alarm"])
        alarms = [r for r in residuals if r["residual_l1"] > alarm]
        changes = adapt_audit_boost(
            self._boost,
            self._quiet,
            residuals,
            alarm=alarm,
            factor=int(self._cfg["audit_boost_factor"]),
            max_multiplier=int(self._cfg["audit_boost_max"]),
            cooldown_days=int(self._cfg["audit_cooldown_days"]),
        )
        self._boosted.update(c["cohort_id"] for c in changes if c["to"] > c["from"])
        worst = max(residuals, key=lambda r: r["residual_l1"], default=None)
        calls = today["cohort_calls"] + today["individual_calls"]
        self._totals["days"] += 1
        self._totals["cohort_calls"] += today["cohort_calls"]
        self._totals["individual_calls"] += today["individual_calls"]
        self._totals["full_calls"] += len(agents)
        self._totals["alarms"] += len(alarms)
        self._recorder.record(
            "group.day",
            {
                "day": today["day"],
                "population": len(agents),
                "cohorts": len(self._cohorts),
                "plan": plan.to_dict(),
                "cohort_calls": today["cohort_calls"],
                "individual_calls": today["individual_calls"],
                "full_individual_calls": len(agents),
                "residuals": [
                    {
                        "cohort_id": r["cohort_id"],
                        "sample_size": r["sample_size"],
                        "residual_l1": round(r["residual_l1"], 4),
                    }
                    for r in residuals
                ],
                "max_residual_l1": round(worst["residual_l1"], 4) if worst else 0.0,
                "alarms": [r["cohort_id"] for r in alarms],
                "boost_changes": changes,
                "audit_boost": dict(self._boost),
                "cohort_deltas": today["deltas"],
                "digests": today["digests"],
            },
        )
        line = (
            f"👥 Day {today['day']}：{len(self._cohorts)} 个群体 · 实体化 {len(today['materialized'])} 人"
            f"（审计 {len(plan.audit)}）· 本天调用 {calls} 次（全个体快进约 {len(agents)} 次）"
        )
        if worst:
            line += f" · 审计残差 L1 最大 {worst['residual_l1']:.3f}（{worst['cohort_id']}）"
        print(line)
        for change in changes:
            arrow = "加大" if change["to"] > change["from"] else "回落"
            print(
                f"   ↳ {change['cohort_id']} 审计样本{arrow}到 ×{change['to']}（残差 {change['residual_l1']:.3f}）"
            )
        self._today = None

    def _group_summary(self, hook_ctx: dict[str, Any]) -> None:
        totals = dict(self._totals)
        used = totals["cohort_calls"] + totals["individual_calls"]
        totals["savings_factor"] = round(totals["full_calls"] / used, 2) if used else None
        totals["cohorts_boosted"] = sorted(self._boosted)
        self._recorder.record("group.summary", totals)
        if totals["days"]:
            print(
                f"👥 群体模式小结：{totals['days']} 天，调用 {used} 次"
                f"（全个体快进约 {totals['full_calls']} 次），审计告警 {totals['alarms']} 次"
                + (f"，加大过审计的群体：{'、'.join(totals['cohorts_boosted'])}" if self._boosted else "")
            )

    # -- telemetry ---------------------------------------------------------

    def _telemetry_start(self, hook_ctx: dict[str, Any]) -> None:
        agents = list(hook_ctx.get("agents") or [])
        if not agents:
            return
        self._cohorts = self._partition(agents)
        self._recorder.record(
            "group.partition",
            {"population": len(agents), "cohorts": [c.to_dict() for c in self._cohorts]},
        )

    def _telemetry_day(self, hook_ctx: dict[str, Any]) -> None:
        from gaworld.group.cohort import refresh_cohort_statistics

        if not self._cohorts:
            return
        by_id = {int(a["id"]): a for a in (hook_ctx.get("agents") or [])}
        for cohort in self._cohorts:
            refresh_cohort_statistics(cohort, by_id)
        self._recorder.record(
            "group.cohort_stats",
            {
                "cohorts": [
                    {"id": c.id, "size": c.size, "centroid": c.centroid, "dispersion": c.dispersion}
                    for c in self._cohorts
                ]
            },
        )


__all__ = ["MODES", "GroupPlugin", "group_config", "validate_config"]
