"""Cohorts: groups of residents that act as first-class simulation entities.

A cohort is a cell in attribute space plus the statistics of the people in it.
The statistics are the whole point, and specifically the fact that there are
*two* of them:

``centroid``     the group mean of each state variable
``dispersion``   the standard deviation of each state variable

Carrying only the centroid is what Kirman's 1992 critique of the
representative agent is about: the aggregate of heterogeneous individuals is
generally not the behaviour of any single individual, so a cohort that has
forgotten its own spread will make decisions no member would make. Keeping
dispersion lets the cohort prompt say "roughly a third of this group is under
real financial stress while the rest are comfortable" — which is a group a
model can reason about — rather than "this group's econ_security is 0.5".

Cohort membership is deliberately *coarse*: the default partition is
``(age band × industry × hukou)``, which puts a 500-person town in the
20-40 cohort range. Granularity is the main fidelity/cost dial in the whole
group tier — finer cohorts cost more LLM calls and represent their members
better — so it is configurable rather than baked in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaworld.population.schema import AGE_BAND_RANGES, AGE_BANDS, STATE_VAR_KEYS

#: Attribute axes available for partitioning. Values are functions of an agent
#: dict, so the partition works on both generated ``Person`` payloads and the
#: agent dicts the individual tier uses.
COHORT_AXES: dict[str, Any] = {
    "age_band": lambda agent: _age_band_of(agent.get("age", 0)),
    "industry": lambda agent: str(agent.get("industry") or "none"),
    "hukou": lambda agent: str(agent.get("hukou") or "未知"),
    "employment": lambda agent: str(agent.get("employment") or "unknown"),
    "gender": lambda agent: str(agent.get("gender") or "未知"),
    "district": lambda agent: str(agent.get("district") or _district_of(agent)),
}

#: Default partition. Age drives daily rhythm, industry drives economic
#: exposure, hukou drives entitlement and belonging — the three axes the
#: existing state variables are most sensitive to.
DEFAULT_COHORT_AXES: tuple[str, ...] = ("age_band", "industry", "hukou")

#: A cohort smaller than this is merged into its nearest neighbour: a
#: "cohort" of one person is just an individual paying cohort overhead, and
#: its dispersion is meaningless.
MIN_COHORT_SIZE = 4

CohortKey = tuple[str, ...]


def _age_band_of(age: Any) -> str:
    try:
        value = int(age)
    except (TypeError, ValueError):
        return AGE_BANDS[0]
    for band, (low, high) in AGE_BAND_RANGES.items():
        if low <= value <= high:
            return band
    return AGE_BANDS[-1]


def _district_of(agent: dict[str, Any]) -> str:
    residence = str(agent.get("residence") or "")
    return residence.split("·")[0] if "·" in residence else residence or "未知"


@dataclass
class Cohort:
    """One cohort: its members, its statistics, its memory and its history.

    ``members`` holds ids only. The individual records stay in one place
    (the population), so a materialised agent and its cohort can never drift
    into two disagreeing copies of the same person.
    """

    id: str
    key: CohortKey
    axes: tuple[str, ...]
    members: list[int] = field(default_factory=list)
    centroid: dict[str, float] = field(default_factory=dict)
    dispersion: dict[str, float] = field(default_factory=dict)
    #: Cohort-level shared memory — things "everyone around here" knows.
    memory: list[str] = field(default_factory=list)
    #: Member ids currently running at individual fidelity.
    materialized: set[int] = field(default_factory=set)
    #: Per-day digests, newest last.
    history: list[dict[str, Any]] = field(default_factory=list)
    #: Per-member deltas from the most recent ``apply_cohort_state_changes``.
    #: Feeds the next day's :class:`NetworkCoupling`; without it the graph term
    #: would have nothing to propagate.
    last_member_deltas: dict[int, dict[str, float]] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.members)

    def label(self) -> str:
        """Human-readable cohort description, used in prompts and logs."""
        parts = [f"{axis}={value}" for axis, value in zip(self.axes, self.key, strict=True)]
        return f"{self.id}（{self.size}人｜{'，'.join(parts)}）"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": list(self.key),
            "axes": list(self.axes),
            "size": self.size,
            "members": list(self.members),
            "centroid": dict(self.centroid),
            "dispersion": dict(self.dispersion),
            "materialized": sorted(self.materialized),
            "memory": list(self.memory),
        }


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------


def _agent_state(agent: dict[str, Any]) -> dict[str, Any]:
    state = agent.get("state")
    return state if isinstance(state, dict) else {}


def refresh_cohort_statistics(cohort: Cohort, agents_by_id: dict[int, dict[str, Any]]) -> None:
    """Recompute centroid and dispersion from current member state, in place."""
    rows = []
    for member_id in cohort.members:
        state = _agent_state(agents_by_id.get(member_id, {}))
        rows.append([float(state.get(key, 0.5)) for key in STATE_VAR_KEYS])
    if not rows:
        cohort.centroid = dict.fromkeys(STATE_VAR_KEYS, 0.5)
        cohort.dispersion = dict.fromkeys(STATE_VAR_KEYS, 0.0)
        return
    matrix = np.asarray(rows, dtype=float)
    means = matrix.mean(axis=0)
    # ddof=0: this is the dispersion of *this* cohort's members, a population
    # statistic over a fully observed group, not an estimate of a wider one.
    sds = matrix.std(axis=0, ddof=0)
    cohort.centroid = {key: float(means[i]) for i, key in enumerate(STATE_VAR_KEYS)}
    cohort.dispersion = {key: float(sds[i]) for i, key in enumerate(STATE_VAR_KEYS)}


def partition_cohorts(
    agents: Sequence[dict[str, Any]],
    *,
    axes: Sequence[str] | None = None,
    min_size: int = MIN_COHORT_SIZE,
) -> list[Cohort]:
    """Partition ``agents`` into cohorts along ``axes``.

    Every agent lands in exactly one cohort — the partition is a cover, so no
    member is simulated twice or dropped. Cells below ``min_size`` are merged
    into the nearest surviving cohort by centroid distance, falling back to the
    largest cohort when no cohort survives the threshold on its own.

    Raises ``ValueError`` on an unknown axis rather than silently ignoring it;
    a typo'd axis would otherwise produce a coarser partition than requested
    and quietly cost fidelity.
    """
    # ``None`` means "use the default"; an *empty* sequence is a caller bug
    # (typically ``"".split(",")``) and must not silently become the default —
    # that would hand back a coarser partition than asked for and quietly cost
    # fidelity.
    chosen = DEFAULT_COHORT_AXES if axes is None else tuple(axes)
    if not chosen:
        raise ValueError("at least one cohort axis is required (got an empty sequence)")
    unknown = [axis for axis in chosen if axis not in COHORT_AXES]
    if unknown:
        raise ValueError(f"unknown cohort axes: {unknown}; available: {sorted(COHORT_AXES)}")

    agents_by_id = {int(a["id"]): a for a in agents}
    buckets: dict[CohortKey, list[int]] = {}
    for agent in agents:
        key = tuple(str(COHORT_AXES[axis](agent)) for axis in chosen)
        buckets.setdefault(key, []).append(int(agent["id"]))

    cohorts: list[Cohort] = []
    for index, (key, members) in enumerate(sorted(buckets.items()), start=1):
        cohort = Cohort(
            id=f"c{index:03d}",
            key=key,
            axes=chosen,
            members=sorted(members),
        )
        refresh_cohort_statistics(cohort, agents_by_id)
        cohorts.append(cohort)

    cohorts = _merge_small_cohorts(cohorts, agents_by_id, min_size=min_size)
    for index, cohort in enumerate(cohorts, start=1):
        cohort.id = f"c{index:03d}"
    return cohorts


def _centroid_vector(cohort: Cohort) -> np.ndarray:
    return np.array([cohort.centroid.get(key, 0.5) for key in STATE_VAR_KEYS], dtype=float)


def _merge_small_cohorts(
    cohorts: list[Cohort], agents_by_id: dict[int, dict[str, Any]], *, min_size: int
) -> list[Cohort]:
    if min_size <= 1 or not cohorts:
        return cohorts
    keepers = [c for c in cohorts if c.size >= min_size]
    strays = [c for c in cohorts if c.size < min_size]
    if not strays:
        return cohorts
    if not keepers:
        # Everything is small (tiny population): merge into the largest cell
        # rather than returning a partition of singletons.
        keepers = [max(cohorts, key=lambda c: c.size)]
        strays = [c for c in cohorts if c is not keepers[0]]

    for stray in strays:
        target = min(
            keepers,
            key=lambda k: float(np.linalg.norm(_centroid_vector(k) - _centroid_vector(stray))),
        )
        target.members.extend(stray.members)
        # A merged cohort no longer matches its own key on every axis; mark it
        # so prompts and reports do not overstate how homogeneous it is.
        target.key = tuple(
            existing if existing == other else f"{existing}/…"
            for existing, other in zip(target.key, stray.key, strict=True)
        )
    for keeper in keepers:
        keeper.members = sorted(set(keeper.members))
        refresh_cohort_statistics(keeper, agents_by_id)
    return keepers


# ---------------------------------------------------------------------------
# Prompt-facing summary
# ---------------------------------------------------------------------------


def cohort_summary(cohort: Cohort, *, top_n: int = 4) -> str:
    """Describe a cohort's state as mean **and spread**, for the LLM prompt.

    Reporting "econ_security 0.50" invites the model to reason about a single
    average person. Reporting "econ_security 平均0.50，约34%低于0.4" keeps the
    heterogeneity in view, which is the difference between a group decision and
    a representative-agent decision.
    """
    if not cohort.centroid:
        return "（无统计）"
    ordered = sorted(
        STATE_VAR_KEYS,
        key=lambda key: -abs(cohort.centroid.get(key, 0.5) - 0.5),
    )[:top_n]
    parts = []
    for key in ordered:
        mean = cohort.centroid.get(key, 0.5)
        sd = cohort.dispersion.get(key, 0.0)
        low_share = _share_below(cohort, key, 0.4)
        high_share = _share_above(cohort, key, 0.6)
        detail = f"{key} 平均{mean:.2f}（离散{sd:.2f}"
        if low_share >= 0.15:
            detail += f"，约{low_share:.0%}低于0.4"
        if high_share >= 0.15:
            detail += f"，约{high_share:.0%}高于0.6"
        detail += "）"
        parts.append(detail)
    return "；".join(parts)


def _normal_cdf(x: float) -> float:
    """Standard normal CDF via ``erf`` — avoids a scipy dependency."""
    import math

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _share_below(cohort: Cohort, key: str, threshold: float) -> float:
    mean = cohort.centroid.get(key, 0.5)
    sd = cohort.dispersion.get(key, 0.0)
    if sd <= 1e-9:
        return 1.0 if mean < threshold else 0.0
    return _normal_cdf((threshold - mean) / sd)


def _share_above(cohort: Cohort, key: str, threshold: float) -> float:
    return 1.0 - _share_below(cohort, key, threshold)


# ---------------------------------------------------------------------------
# Network coupling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NetworkCoupling:
    """Graph-mediated redistribution *within* a cohort day.

    Why this exists: without it, a cohort day gives every member an identical
    shift, so neighbour-mediated co-movement is inexpressible at the group tier.
    The Phase 3 gate measured exactly that — reference Moran's I on state
    changes came out at +0.05…+0.10 while the cohort tier produced −0.02, and no
    materialisation budget below 80% of the population closed the gap
    (see ``docs/GROUP_AGENT_DESIGN.md`` §8.5).

    The mechanism is a clean split of ownership:

    * the **cohort layer owns the mean** — whatever the group digest predicted
      for the aggregate is exactly what the aggregate does;
    * the **graph owns the within-cohort spread** — each member is additionally
      nudged by how their own neighbours moved yesterday, relative to how the
      cohort as a whole moved.

    That relative-to-cohort framing is what makes it safe. The coupling term is
    *centred within the cohort*, so it sums to zero and cannot shift the group
    mean. Adding a raw neighbour term instead would let the graph silently
    override the cohort's prediction, which would put the layers that already
    pass (L1 distributional, L4 causal) at risk to fix the one that fails.

    Costs nothing: it is arithmetic over an existing graph, with no extra LLM
    calls.
    """

    #: agent id → neighbour ids (the population's social graph).
    neighbours: Mapping[int, Sequence[int]]
    #: agent id → yesterday's per-key deltas.
    previous_deltas: Mapping[int, Mapping[str, float]]
    #: Strength of the graph term. 0 reproduces the pre-coupling behaviour
    #: exactly, which is what makes this safe to land as an opt-in.
    weight: float = 0.6
    #: Cap on the coupling term as a multiple of ``max_delta``, so a
    #: pathological neighbourhood cannot dominate the cohort's own prediction.
    max_multiple: float = 1.0


def _centred_network_terms(
    cohort: Cohort, key: str, coupling: NetworkCoupling, *, cap: float
) -> dict[int, float]:
    """Per-member graph nudge for ``key``, centred to sum to zero.

    Members with no neighbours in ``previous_deltas`` get a raw signal of zero;
    they still receive the centring offset, which is correct — "your
    neighbourhood did nothing while the cohort moved" is itself information.
    """
    raw: dict[int, float] = {}
    for member_id in cohort.members:
        peers = coupling.neighbours.get(member_id) or ()
        moves = [
            float(coupling.previous_deltas[p][key])
            for p in peers
            if p in coupling.previous_deltas and key in coupling.previous_deltas[p]
        ]
        raw[member_id] = float(np.mean(moves)) if moves else 0.0
    if not raw:
        return {}
    offset = float(np.mean(list(raw.values())))
    limit = max(0.0, cap * float(coupling.max_multiple))
    return {
        member_id: float(np.clip(coupling.weight * (value - offset), -limit, limit))
        for member_id, value in raw.items()
    }


# ---------------------------------------------------------------------------
# Applying a cohort's day to its members
# ---------------------------------------------------------------------------


def apply_cohort_state_changes(
    cohort: Cohort,
    state_changes: dict[str, float],
    agents_by_id: dict[int, dict[str, Any]],
    *,
    max_delta: float = 0.15,
    skip: Iterable[int] = (),
    dispersion_retention: float = 1.0,
    coupling: NetworkCoupling | None = None,
) -> dict[str, float]:
    """Push a cohort-level delta onto its members, preserving spread.

    Every member gets the same base shift, which is what keeps within-cohort
    dispersion intact: adding a constant to a distribution moves its mean and
    leaves its standard deviation alone. Assigning the cohort mean to each
    member instead would collapse the cohort to a point after one day, and the
    simulation would lose exactly the heterogeneity it exists to study.

    With ``coupling`` supplied, each member additionally receives a mean-zero
    graph term (see :class:`NetworkCoupling`) so social structure survives the
    aggregation. ``coupling=None`` reproduces the uniform-shift behaviour
    exactly.

    ``skip`` excludes materialised members — they ran their own day at
    individual fidelity and applying the cohort delta on top would
    double-count it. ``dispersion_retention`` below 1.0 deliberately contracts
    spread (for ablation experiments); the default leaves it untouched.

    Returns the group-level shift per key. The per-member deltas actually
    applied are recorded on ``cohort.last_member_deltas`` so the next day's
    coupling has something to read.
    """
    if not isinstance(state_changes, dict):
        cohort.last_member_deltas = {}
        return {}
    cap = max(0.0, float(max_delta))
    skipped = {int(i) for i in skip}
    applied: dict[str, float] = {}
    member_deltas: dict[int, dict[str, float]] = {m: {} for m in cohort.members}

    for key, raw in state_changes.items():
        if key not in STATE_VAR_KEYS:
            continue
        try:
            step = max(-cap, min(cap, float(raw)))
        except (TypeError, ValueError):
            continue
        network = _centred_network_terms(cohort, key, coupling, cap=cap) if coupling is not None else {}
        if step == 0.0 and not any(abs(v) > 1e-12 for v in network.values()):
            continue
        applied[key] = step
        for member_id in cohort.members:
            if member_id in skipped:
                continue
            state = _agent_state(agents_by_id.get(member_id, {}))
            if not isinstance(state.get(key), (int, float)):
                continue
            before = float(state[key])
            total = step + network.get(member_id, 0.0)
            state[key] = float(np.clip(before + total, 0.0, 1.0))
            member_deltas[member_id][key] = state[key] - before

    if dispersion_retention < 1.0:
        _contract_dispersion(cohort, agents_by_id, retention=dispersion_retention, skip=skipped)

    cohort.last_member_deltas = {m: d for m, d in member_deltas.items() if d}
    refresh_cohort_statistics(cohort, agents_by_id)
    return applied


def _contract_dispersion(
    cohort: Cohort,
    agents_by_id: dict[int, dict[str, Any]],
    *,
    retention: float,
    skip: set[int],
) -> None:
    """Shrink members toward the cohort mean by ``1 - retention``."""
    factor = max(0.0, min(1.0, float(retention)))
    for key in STATE_VAR_KEYS:
        mean = cohort.centroid.get(key, 0.5)
        for member_id in cohort.members:
            if member_id in skip:
                continue
            state = _agent_state(agents_by_id.get(member_id, {}))
            if not isinstance(state.get(key), (int, float)):
                continue
            value = float(state[key])
            state[key] = float(np.clip(mean + (value - mean) * factor, 0.0, 1.0))


__all__ = [
    "COHORT_AXES",
    "DEFAULT_COHORT_AXES",
    "MIN_COHORT_SIZE",
    "Cohort",
    "CohortKey",
    "NetworkCoupling",
    "apply_cohort_state_changes",
    "cohort_summary",
    "partition_cohorts",
    "refresh_cohort_statistics",
]
