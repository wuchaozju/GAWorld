"""Materialisation: which individuals get run at full fidelity today.

Cohorts are cheap and lossy; individuals are expensive and exact. Every day a
budget of individuals is promoted to the individual tier, and the choice of
*which* is what determines whether the approximation is defensible.

Four reasons to materialise someone, in priority order:

``focal``   the researcher named them. Non-negotiable — this is the whole
            reason to run a group simulation with a story in it.
``tail``    the cohort centroid demonstrably cannot represent them. Selected
            by Mahalanobis-style distance in the cohort's own dispersion
            metric, because "far from the mean" only means something relative
            to how spread out the group already is. This is the direct
            countermeasure to the known tail-collapse failure of aggregate
            LLM simulation (Bisbee et al. 2024).
``event``   they are a party to something that needs a real decision today.
``audit``   a random sample, held out to *measure* the approximation error
            rather than reduce it. Borrowed from the shadow-audit idea in the
            design doc's path D: without it, group mode reports no error at
            all, which is worse than reporting a large one.

The audit sample is the part most likely to be cut for cost and the part that
should not be: it is the only thing that makes group-mode output falsifiable
during a run rather than only in a post-hoc L0 double-run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaworld.group.cohort import Cohort, refresh_cohort_statistics
from gaworld.population.schema import STATE_VAR_KEYS

#: Floor on a cohort's per-key dispersion when computing distance. Without it,
#: a cohort whose members happen to agree on one variable would report an
#: infinite distance for any deviation on that variable, and tail selection
#: would be driven entirely by numerical noise.
_MIN_SD = 0.02


@dataclass
class MaterializationPlan:
    """Who runs at individual fidelity today, and why."""

    day: int
    focal: list[int] = field(default_factory=list)
    tail: list[int] = field(default_factory=list)
    event: list[int] = field(default_factory=list)
    audit: list[int] = field(default_factory=list)

    @property
    def all_ids(self) -> list[int]:
        seen: set[int] = set()
        ordered: list[int] = []
        for group in (self.focal, self.event, self.tail, self.audit):
            for member_id in group:
                if member_id not in seen:
                    seen.add(member_id)
                    ordered.append(member_id)
        return ordered

    def reason_for(self, member_id: int) -> str:
        for name, group in (
            ("focal", self.focal),
            ("event", self.event),
            ("tail", self.tail),
            ("audit", self.audit),
        ):
            if member_id in group:
                return name
        return "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "focal": list(self.focal),
            "event": list(self.event),
            "tail": list(self.tail),
            "audit": list(self.audit),
            "total": len(self.all_ids),
        }


def cohort_distance(cohort: Cohort, agent: dict[str, Any], *, min_sd: float = _MIN_SD) -> float:
    """How badly the cohort centroid fails to describe ``agent``.

    A diagonal Mahalanobis distance: per-key deviation divided by that key's
    within-cohort spread, then combined. Plain Euclidean distance would rank a
    0.2 deviation on a tightly-agreeing variable below a 0.2 deviation on an
    already-scattered one, which is backwards — the former is the member the
    cohort cannot speak for.
    """
    state = agent.get("state")
    if not isinstance(state, dict) or not cohort.centroid:
        return 0.0
    total = 0.0
    for key in STATE_VAR_KEYS:
        value = state.get(key)
        if not isinstance(value, (int, float)):
            continue
        sd = max(float(cohort.dispersion.get(key, 0.0)), float(min_sd))
        total += ((float(value) - float(cohort.centroid.get(key, 0.5))) / sd) ** 2
    return float(np.sqrt(total))


def select_materialized(
    cohorts: Sequence[Cohort],
    agents_by_id: dict[int, dict[str, Any]],
    *,
    day: int,
    budget: int,
    focal_ids: Sequence[int] = (),
    event_ids: Sequence[int] = (),
    audit_fraction: float = 0.03,
    rng: np.random.Generator | None = None,
) -> MaterializationPlan:
    """Pick today's individual-fidelity agents within ``budget``.

    Focal and event agents are always included even if that overruns the
    budget — silently dropping the agent a researcher is following would make
    the run useless in a way that is hard to notice. The audit sample is sized
    from ``audit_fraction`` of the population and takes priority over tail
    selection, because an unmeasured approximation is worse than a slightly
    less well-targeted one. Whatever budget remains goes to the tail.
    """
    generator = rng if rng is not None else np.random.default_rng(day)
    all_members = [m for cohort in cohorts for m in cohort.members]
    population = len(all_members)

    focal = [int(i) for i in focal_ids if int(i) in agents_by_id]
    event = [int(i) for i in event_ids if int(i) in agents_by_id and int(i) not in focal]
    reserved = set(focal) | set(event)

    audit_target = round(max(0.0, float(audit_fraction)) * population)
    audit: list[int] = []
    if audit_target > 0:
        # Stratify by cohort so the audit covers the whole population rather
        # than over-sampling whichever cohort happens to be largest.
        for cohort in cohorts:
            if not cohort.members:
                continue
            share = max(1, round(audit_target * cohort.size / max(population, 1)))
            candidates = [m for m in cohort.members if m not in reserved]
            if not candidates:
                continue
            take = min(share, len(candidates))
            picked = generator.choice(len(candidates), size=take, replace=False)
            audit.extend(int(candidates[int(i)]) for i in picked)
        audit = sorted(set(audit) - reserved)[:audit_target]
    reserved |= set(audit)

    remaining = max(0, int(budget) - len(focal) - len(event) - len(audit))
    tail: list[int] = []
    if remaining > 0:
        scored: list[tuple[float, int]] = []
        for cohort in cohorts:
            for member_id in cohort.members:
                if member_id in reserved:
                    continue
                agent = agents_by_id.get(member_id)
                if agent is None:
                    continue
                scored.append((cohort_distance(cohort, agent), member_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        tail = [member_id for _score, member_id in scored[:remaining]]

    return MaterializationPlan(day=day, focal=focal, event=event, tail=tail, audit=sorted(audit))


def apply_individual_deltas_to_cohort(
    cohort: Cohort,
    agents_by_id: dict[int, dict[str, Any]],
) -> dict[str, float]:
    """Fold materialised members' outcomes back into cohort statistics.

    This is the L0 → L1 feedback edge of the hybrid: individuals ran their own
    day, their state moved, and the cohort's centroid and dispersion must now
    reflect it or the two tiers desynchronise. Recomputing from members rather
    than accumulating deltas means the cohort statistics are always exactly the
    statistics of its current members — there is no separate cohort state that
    can drift.

    Returns the centroid shift, which the audit layer uses as its residual
    signal.
    """
    before = dict(cohort.centroid)
    refresh_cohort_statistics(cohort, agents_by_id)
    return {
        key: float(cohort.centroid.get(key, 0.5) - before.get(key, 0.5))
        for key in STATE_VAR_KEYS
        if abs(cohort.centroid.get(key, 0.5) - before.get(key, 0.5)) > 1e-9
    }


def audit_residual(
    cohort: Cohort,
    agents_by_id: dict[int, dict[str, Any]],
    audit_ids: Sequence[int],
    cohort_delta: dict[str, float],
    before_states: dict[int, dict[str, float]],
) -> dict[str, Any]:
    """Compare what the audit sample actually did against what the cohort predicted.

    The residual must be defined on **changes**, not on levels::

        residual = mean_over_audit(state_after − state_before) − cohort_delta

    Comparing the audit sample's *level* against the cohort centroid instead
    (an easy mistake, and the first version of this function's bug) measures
    the sampling gap between a handful of members and their cohort mean — which
    is large, non-zero even when nothing at all happened, and says nothing
    about approximation quality. Differencing each member against their own
    prior state cancels that offset, so a day in which the cohort's prediction
    was exactly right scores zero regardless of who was sampled.

    A large residual is a signal to materialise more of this cohort, not a
    reason to stop; the point is that it is *visible*.
    """
    members = [int(i) for i in audit_ids if int(i) in agents_by_id and int(i) in before_states]
    if not members:
        return {"cohort_id": cohort.id, "sample_size": 0, "residual": {}, "residual_l1": 0.0}

    residual: dict[str, float] = {}
    for key in STATE_VAR_KEYS:
        observed_deltas = []
        for member_id in members:
            after = agents_by_id[member_id].get("state", {}).get(key)
            before = before_states[member_id].get(key)
            if isinstance(after, (int, float)) and isinstance(before, (int, float)):
                observed_deltas.append(float(after) - float(before))
        if not observed_deltas:
            continue
        residual[key] = float(np.mean(observed_deltas) - float(cohort_delta.get(key, 0.0)))

    return {
        "cohort_id": cohort.id,
        "sample_size": len(members),
        "residual": residual,
        "residual_l1": float(sum(abs(v) for v in residual.values())),
    }


__all__ = [
    "MaterializationPlan",
    "apply_individual_deltas_to_cohort",
    "audit_residual",
    "cohort_distance",
    "select_materialized",
]
