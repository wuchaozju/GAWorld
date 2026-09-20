"""The group-mode day loop.

One simulated day, in order:

1. partition (day 1) or refresh cohort statistics;
2. pick today's materialised individuals (focal / event / tail / audit);
3. run one cohort-day per cohort — this is the only LLM cost that scales with
   the population, and it scales with *cohort count*, not headcount;
4. apply each cohort's delta to its non-materialised members;
5. run the materialised individuals at individual fidelity;
6. fold their outcomes back into cohort statistics;
7. compute the audit residual and record everything.

Step 7 is what makes group mode answerable. The residual compares what the
cohort predicted for its audit sample against what those agents actually did,
so a run reports its own approximation error as it goes instead of only after
a separate full-individual double-run.

Note on step 5: the individual tier here is pluggable
(``individual_day_fn``). The real integration point is the existing
fast-forward digest or the 12-stage tick pipeline, but neither is imported
from this module — the tick stages are closures over ``run_simulation``'s
locals and unreachable from outside, and hard-wiring the fast-forward path
would make this loop untestable without a full simulator boot. The default is
a deterministic no-op so the loop is exercisable on its own; Phase 3 wires the
real thing in behind the same signature.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaworld.group.cohort import (
    Cohort,
    NetworkCoupling,
    apply_cohort_state_changes,
    partition_cohorts,
    refresh_cohort_statistics,
)
from gaworld.group.cohort_day import (
    effective_state_changes,
    render_cohort_brief_block,
    simulate_cohort_day,
)
from gaworld.group.materialize import (
    MaterializationPlan,
    apply_individual_deltas_to_cohort,
    audit_residual,
    select_materialized,
)
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.group.driver")


@dataclass
class GroupRunConfig:
    """Knobs for a group-mode run."""

    days: int = 7
    #: Attribute axes to partition on; ``None`` uses the default triple.
    cohort_axes: Sequence[str] | None = None
    min_cohort_size: int = 4
    #: How many individuals run at full fidelity per day.
    materialization_budget: int = 20
    #: Held-out share of the population used to measure approximation error.
    audit_fraction: float = 0.03
    focal_ids: Sequence[int] = ()
    max_state_delta: float = 0.12
    use_llm: bool = True
    seed: int = 0
    #: Residual L1 above which the run flags a cohort as under-materialised.
    residual_alarm: float = 0.08
    #: Strength of the graph-mediated within-cohort term (see
    #: ``gaworld.group.cohort.NetworkCoupling``). 0 disables it and reproduces
    #: the pre-Phase-4 uniform-shift behaviour exactly. Needs ``neighbours``.
    network_coupling: float = 0.0


@dataclass
class DayRecord:
    """Everything one simulated day produced."""

    day: int
    plan: MaterializationPlan
    cohort_digests: dict[str, dict[str, Any]] = field(default_factory=dict)
    cohort_deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    residuals: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    individual_days: int = 0

    @property
    def max_residual_l1(self) -> float:
        return max((r["residual_l1"] for r in self.residuals), default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "plan": self.plan.to_dict(),
            "cohort_digests": self.cohort_digests,
            "cohort_deltas": self.cohort_deltas,
            "residuals": self.residuals,
            "llm_calls": self.llm_calls,
            "individual_days": self.individual_days,
            "max_residual_l1": self.max_residual_l1,
        }


@dataclass
class GroupRunResult:
    cohorts: list[Cohort]
    agents_by_id: dict[int, dict[str, Any]]
    days: list[DayRecord] = field(default_factory=list)

    @property
    def total_llm_calls(self) -> int:
        return sum(d.llm_calls for d in self.days)

    @property
    def total_individual_days(self) -> int:
        return sum(d.individual_days for d in self.days)

    def cost_summary(self, individual_calls_per_agent_day: int = 198) -> dict[str, Any]:
        """Measured group cost vs the full-individual counterfactual.

        ``individual_calls_per_agent_day`` defaults to 198 = 48 ticks × 4 calls
        + 6 day-boundary calls, the figure derived in the design doc for a
        30-minute grid. It is a *parameter* rather than a constant because that
        number is itself an estimate from reading the code, not a measurement.
        """
        population = len(self.agents_by_id)
        days = max(1, len(self.days))
        full = population * days * individual_calls_per_agent_day
        return {
            "population": population,
            "days": len(self.days),
            "cohorts": len(self.cohorts),
            "group_llm_calls": self.total_llm_calls,
            "individual_agent_days": self.total_individual_days,
            "full_individual_llm_calls_estimate": full,
            "savings_factor": (full / self.total_llm_calls) if self.total_llm_calls else None,
            "assumed_calls_per_agent_day": individual_calls_per_agent_day,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohorts": [c.to_dict() for c in self.cohorts],
            "days": [d.to_dict() for d in self.days],
            "cost": self.cost_summary(),
        }


def _noop_individual_day(agent: dict[str, Any], *, day: int) -> dict[str, Any]:
    """Placeholder individual tier: consumes a day, changes nothing.

    Returning zero deltas is the honest placeholder. Inventing plausible
    movement here would make the audit residual look healthy while measuring
    nothing at all.
    """
    del agent, day
    return {"state_changes": {}, "llm_calls": 0}


def run_group_simulation(
    agents: Sequence[dict[str, Any]],
    config: GroupRunConfig | None = None,
    *,
    llm_fn: Callable[..., str] | None = None,
    individual_day_fn: Callable[..., dict[str, Any]] | None = None,
    env_context_for_day: Callable[[int], str] | None = None,
    event_ids_for_day: Callable[[int], Sequence[int]] | None = None,
    neighbours: Mapping[int, Sequence[int]] | None = None,
) -> GroupRunResult:
    """Run ``config.days`` days of group-mode simulation.

    ``agents`` are mutated in place (their ``state`` dicts evolve), matching how
    the individual tier treats agent dicts.

    ``neighbours`` enables the graph coupling term when
    ``config.network_coupling > 0``. Passing a positive coupling without a graph
    is a configuration error rather than a silent no-op: it would look like the
    fix for the Phase 3 L2 failure was active when it was not.
    """
    cfg = config or GroupRunConfig()
    if cfg.network_coupling > 0 and not neighbours:
        raise ValueError("network_coupling > 0 requires `neighbours` (the population's social graph)")
    individual_day = individual_day_fn or _noop_individual_day
    agents_by_id: dict[int, dict[str, Any]] = {int(a["id"]): a for a in agents}

    cohorts = partition_cohorts(agents, axes=cfg.cohort_axes, min_size=cfg.min_cohort_size)
    _LOG.info(
        "group mode: %d agents → %d cohorts (sizes %d-%d)",
        len(agents_by_id),
        len(cohorts),
        min((c.size for c in cohorts), default=0),
        max((c.size for c in cohorts), default=0),
    )
    result = GroupRunResult(cohorts=cohorts, agents_by_id=agents_by_id)

    for day in range(1, int(cfg.days) + 1):
        rng = np.random.default_rng(cfg.seed * 10_000 + day)
        for cohort in cohorts:
            refresh_cohort_statistics(cohort, agents_by_id)

        plan = select_materialized(
            cohorts,
            agents_by_id,
            day=day,
            budget=cfg.materialization_budget,
            focal_ids=cfg.focal_ids,
            event_ids=(event_ids_for_day(day) if event_ids_for_day else ()),
            audit_fraction=cfg.audit_fraction,
            rng=rng,
        )
        materialized = set(plan.all_ids)
        for cohort in cohorts:
            cohort.materialized = materialized & set(cohort.members)

        record = DayRecord(day=day, plan=plan)
        env_context = env_context_for_day(day) if env_context_for_day else ""

        # Snapshot the audit sample's state *before* anything moves. The
        # residual is defined on changes, so it needs each member's own prior
        # value — a cohort-level snapshot would not be enough.
        audit_before: dict[int, dict[str, float]] = {
            member_id: {
                key: float(value)
                for key, value in (agents_by_id[member_id].get("state") or {}).items()
                if isinstance(value, (int, float))
            }
            for member_id in plan.audit
            if member_id in agents_by_id
        }

        # Yesterday's per-member deltas, frozen. Reading today's as they are
        # produced would make propagation order-dependent and let a signal cross
        # the whole graph in a single day.
        previous_deltas: dict[int, dict[str, float]] = {}
        if cfg.network_coupling > 0:
            for cohort in cohorts:
                previous_deltas.update({m: dict(d) for m, d in cohort.last_member_deltas.items()})

        # --- cohort tier: one LLM call each ---
        for cohort in cohorts:
            digest = simulate_cohort_day(
                cohort,
                day=day,
                env_context=env_context,
                max_delta=cfg.max_state_delta,
                use_llm=cfg.use_llm,
                llm_fn=llm_fn,
            )
            if cfg.use_llm and llm_fn is not None:
                record.llm_calls += 1
            record.cohort_digests[cohort.id] = digest
            if digest.get("memory"):
                cohort.memory.append(str(digest["memory"]))
                del cohort.memory[:-10]  # keep the tail bounded
            cohort.history.append({"day": day, **digest})

            applied = apply_cohort_state_changes(
                cohort,
                effective_state_changes(digest),
                agents_by_id,
                max_delta=cfg.max_state_delta,
                skip=cohort.materialized,
                coupling=(
                    NetworkCoupling(
                        neighbours=neighbours or {},
                        previous_deltas=previous_deltas,
                        weight=cfg.network_coupling,
                    )
                    if cfg.network_coupling > 0
                    else None
                ),
            )
            record.cohort_deltas[cohort.id] = applied

        # --- individual tier: the materialised few ---
        for member_id in plan.all_ids:
            agent = agents_by_id.get(member_id)
            if agent is None:
                continue
            outcome = individual_day(agent, day=day) or {}
            record.individual_days += 1
            record.llm_calls += int(outcome.get("llm_calls", 0))

        # --- fold back + measure ---
        for cohort in cohorts:
            apply_individual_deltas_to_cohort(cohort, agents_by_id)
            audit_here = [m for m in plan.audit if m in set(cohort.members)]
            if not audit_here:
                continue
            residual = audit_residual(
                cohort,
                agents_by_id,
                audit_here,
                record.cohort_deltas.get(cohort.id, {}),
                audit_before,
            )
            record.residuals.append(residual)
            if residual["residual_l1"] > cfg.residual_alarm:
                _LOG.warning(
                    "day %d cohort %s residual L1 %.3f exceeds %.3f — "
                    "consider raising the materialization budget",
                    day,
                    cohort.id,
                    residual["residual_l1"],
                    cfg.residual_alarm,
                )

        result.days.append(record)

    return result


def render_day_block(result: GroupRunResult, day: int) -> str:
    """Console block for a whole group-mode day."""
    record = next((d for d in result.days if d.day == day), None)
    if record is None:
        return ""
    cohorts_by_id = {c.id: c for c in result.cohorts}
    lines = [f"═══ Day {day}｜{len(result.cohorts)} 个群体｜实体化 {record.individual_days} 人 ═══"]
    for cohort_id, digest in record.cohort_digests.items():
        cohort = cohorts_by_id.get(cohort_id)
        if cohort is not None:
            lines.append(render_cohort_brief_block(cohort, day, digest))
    if record.residuals:
        lines.append(f"   审计残差 L1 最大：{record.max_residual_l1:.4f}")
    return "\n".join(lines)


__all__ = [
    "DayRecord",
    "GroupRunConfig",
    "GroupRunResult",
    "render_day_block",
    "run_group_simulation",
]
