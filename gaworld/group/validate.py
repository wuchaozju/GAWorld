"""The L0–L4 validation gate for group mode.

This is the go/no-go decision from ``docs/GROUP_AGENT_DESIGN.md`` §5: does the
cohort approximation preserve enough of what the individual tier produces to be
usable, and *for which research questions*?

**What this validates, and what it does not.** The reference tier is the
per-agent path, run on the same initial population with the same seed. It is
pluggable (``reference_day_fn``) and defaults to a per-agent day whose social
influence is explicit, so the comparison isolates exactly one thing: the error
introduced by *aggregating agents into cohorts*. It does **not** compare group
mode against the 12-stage tick pipeline — those stages are closures over
``run_simulation``'s locals and are not callable from here, and a comparison
that required a full simulator boot with live LLM access could not run in CI or
be tested. So a pass here means "cohorting costs little relative to per-agent
simulation of the same process", not "group mode reproduces the full
simulator". That second claim needs a separate, manual experiment and is out of
scope for this module.

**The baseline that makes the numbers mean anything.** An approximation error
of 0.03 is meaningless in isolation. The gate first runs the *reference tier
against itself* across several seeds and measures its own run-to-run spread;
the approximation is judged acceptable when its deviation is of the same order
as the noise the reference already has. Without that baseline, every threshold
here would be an arbitrary number.

The gate is expected to fail some layers. A validation suite that passes
everything on the first attempt is not measuring anything.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

from gaworld.group.cohort import NetworkCoupling
from gaworld.group.driver import GroupRunConfig
from gaworld.group.metrics import (
    average_treatment_effect,
    distribution_gap,
    effect_heterogeneity_spread,
    first_passage_days,
    heterogeneous_effects,
    morans_i,
    sign_agreement,
    state_columns,
    tail_shares,
)
from gaworld.logging_setup import get_logger
from gaworld.population.schema import STATE_VAR_KEYS

_LOG = get_logger("gaworld.group.validate")

Layer = Literal["L1", "L2", "L3", "L4"]

#: Variables the gate reports on. A subset keeps the output readable; these are
#: the four the existing corpus documents as "core internal states".
FOCUS_KEYS: tuple[str, ...] = ("emotion", "stress", "econ_security", "city_identity")


# ---------------------------------------------------------------------------
# Reference (per-agent) tier
# ---------------------------------------------------------------------------


def make_reference_day(
    neighbours: Mapping[int, Sequence[int]],
    *,
    seed: int = 0,
    social_weight: float = 0.6,
    shock_sensitivity: float = 1.0,
) -> Callable[..., dict[str, Any]]:
    """Build a per-agent day function with explicit social **contagion**.

    Deliberately a simple, transparent process rather than an LLM call: the
    gate needs a reference that is deterministic, free, and whose mechanism is
    known, so that when L2 reports a gap we can say what generated it.

    The social term is contagion on *changes* — an agent's move today is partly
    the average of its neighbours' moves yesterday — not mean-reversion toward
    the neighbourhood level. That distinction is load-bearing and was wrong in
    the first version of this function: with a ``(peer_mean − own_value)`` pull,
    agents above the local mean move down while agents below move up, so
    neighbouring *changes* end up anti-correlated and Moran's I on changes sits
    at zero. L2 then divides two near-zero numbers and reports a confident
    ratio like −75, which is noise wearing a decimal point. Contagion on
    changes produces the positive autocorrelation that real social influence
    produces, giving L2 an actual signal to look for.

    This is what a cohort tier structurally cannot reproduce: cohort deltas are
    uniform within a cohort, and the cohort partition is not the social graph.
    """
    rng = np.random.default_rng(seed)

    def reference_day(
        agent: dict[str, Any],
        *,
        day: int,
        agents_by_id: Mapping[int, dict[str, Any]] | None = None,
        shock: Mapping[str, float] | None = None,
        previous_deltas: Mapping[int, Mapping[str, float]] | None = None,
    ) -> dict[str, Any]:
        del day, agents_by_id
        state = agent.get("state") or {}
        peers = list(neighbours.get(int(agent["id"]), ()))
        applied: dict[str, float] = {}
        for key in STATE_VAR_KEYS:
            value = state.get(key)
            if not isinstance(value, (int, float)):
                continue
            delta = float(rng.normal(0.0, 0.02))
            if peers and previous_deltas:
                peer_moves = [
                    float(previous_deltas[p][key])
                    for p in peers
                    if p in previous_deltas and key in previous_deltas[p]
                ]
                if peer_moves:
                    delta += social_weight * float(np.mean(peer_moves))
            if shock:
                delta += shock_sensitivity * float(shock.get(key, 0.0))
            new_value = float(np.clip(float(value) + delta, 0.0, 1.0))
            applied[key] = new_value - float(value)
            state[key] = new_value
        return {"state_changes": applied, "llm_calls": 0}

    return reference_day


def run_reference_tier(
    agents: Sequence[dict[str, Any]],
    neighbours: Mapping[int, Sequence[int]],
    *,
    days: int,
    seed: int = 0,
    shock_from_day: int | None = None,
    shock: Mapping[str, float] | None = None,
    track_keys: Sequence[str] = FOCUS_KEYS,
) -> dict[str, Any]:
    """Run every agent individually for ``days``; return final state + trajectories.

    Contagion reads *yesterday's* deltas, held in a frozen snapshot. Reading
    deltas produced earlier in the same day would make the outcome depend on
    iteration order and turn simultaneous influence into a sequential chain
    that propagates across the whole graph in one step.
    """
    working = {int(a["id"]): a for a in agents}
    day_fn = make_reference_day(neighbours, seed=seed)
    trajectories: dict[str, dict[int, list[float]]] = {key: {i: [] for i in working} for key in track_keys}
    previous_deltas: dict[int, dict[str, float]] = {}

    for day in range(1, int(days) + 1):
        active_shock = shock if (shock_from_day is not None and day >= shock_from_day) else None
        frozen = {i: dict(d) for i, d in previous_deltas.items()}
        today: dict[int, dict[str, float]] = {}
        for agent_id, agent in working.items():
            outcome = day_fn(agent, day=day, shock=active_shock, previous_deltas=frozen)
            today[agent_id] = dict(outcome["state_changes"])
            for key in track_keys:
                trajectories[key][agent_id].append(float(agent["state"][key]))
        previous_deltas = today
    return {"agents": list(working.values()), "trajectories": trajectories}


def run_group_tier(
    agents: Sequence[dict[str, Any]],
    neighbours: Mapping[int, Sequence[int]],
    *,
    days: int,
    seed: int = 0,
    materialization_budget: int = 20,
    audit_fraction: float = 0.03,
    cohort_delta_fn: Callable[[Any, int], dict[str, float]] | None = None,
    shock_from_day: int | None = None,
    shock: Mapping[str, float] | None = None,
    network_coupling: float = 0.0,
    track_keys: Sequence[str] = FOCUS_KEYS,
) -> dict[str, Any]:
    """Run the cohort tier over the same population, with a stubbed cohort day.

    ``cohort_delta_fn`` stands in for the LLM's group digest so the comparison
    is deterministic and free. It defaults to the *cohort mean of what the
    reference process would do*, which is the most generous possible cohort
    prediction — if group mode fails a layer even with a perfectly-calibrated
    group delta, the failure is structural rather than a prompt-quality
    problem, which is exactly what a gate should isolate.
    """
    working = {int(a["id"]): a for a in agents}
    trajectories: dict[str, dict[int, list[float]]] = {key: {i: [] for i in working} for key in track_keys}
    reference_day = make_reference_day(neighbours, seed=seed)

    cfg = GroupRunConfig(
        days=days,
        materialization_budget=materialization_budget,
        audit_fraction=audit_fraction,
        seed=seed,
        use_llm=False,
    )

    # The cohort day is stubbed (see ``cohort_delta_fn``), so the loop is driven
    # here rather than through ``run_group_simulation`` — that keeps the shock
    # schedule and trajectory recording under this function's control while
    # reusing the real partition / selection / delta-application code.
    from gaworld.group.cohort import (
        apply_cohort_state_changes,
        partition_cohorts,
        refresh_cohort_statistics,
    )
    from gaworld.group.materialize import select_materialized

    cohorts = partition_cohorts(list(working.values()), min_size=cfg.min_cohort_size)
    previous_deltas: dict[int, dict[str, float]] = {}

    for day in range(1, int(days) + 1):
        rng = np.random.default_rng(seed * 10_000 + day)
        for cohort in cohorts:
            refresh_cohort_statistics(cohort, working)
        plan = select_materialized(
            cohorts,
            working,
            day=day,
            budget=materialization_budget,
            audit_fraction=audit_fraction,
            rng=rng,
        )
        materialized = set(plan.all_ids)
        active_shock = shock if (shock_from_day is not None and day >= shock_from_day) else None
        frozen = {i: dict(d) for i, d in previous_deltas.items()}
        today: dict[int, dict[str, float]] = {}

        for cohort in cohorts:
            cohort.materialized = materialized & set(cohort.members)
            delta = (
                cohort_delta_fn(cohort, day)
                if cohort_delta_fn
                else _oracle_cohort_delta(cohort, neighbours, frozen, active_shock)
            )
            applied = apply_cohort_state_changes(
                cohort,
                delta,
                working,
                max_delta=cfg.max_state_delta,
                skip=cohort.materialized,
                coupling=(
                    NetworkCoupling(
                        neighbours=neighbours,
                        previous_deltas=frozen,
                        weight=network_coupling,
                    )
                    if network_coupling > 0
                    else None
                ),
            )
            # With coupling off every non-materialised member got the same
            # shift; with it on they each got their own. Read the per-member
            # record either way so tomorrow's propagation sees what actually
            # happened rather than the group average.
            for member_id, member_delta in cohort.last_member_deltas.items():
                if member_id not in cohort.materialized:
                    today[member_id] = dict(member_delta)
            for member_id in cohort.members:
                if member_id not in cohort.materialized and member_id not in today:
                    today[member_id] = dict(applied)

        for member_id in plan.all_ids:
            agent = working.get(member_id)
            if agent is not None:
                outcome = reference_day(agent, day=day, shock=active_shock, previous_deltas=frozen)
                today[member_id] = dict(outcome["state_changes"])

        for agent_id, agent in working.items():
            for key in track_keys:
                trajectories[key][agent_id].append(float(agent["state"][key]))
        previous_deltas = today

    return {"agents": list(working.values()), "trajectories": trajectories, "cohorts": cohorts}


def _oracle_cohort_delta(
    cohort: Any,
    neighbours: Mapping[int, Sequence[int]],
    previous_deltas: Mapping[int, Mapping[str, float]],
    shock: Mapping[str, float] | None,
    *,
    social_weight: float = 0.6,
) -> dict[str, float]:
    """The best a cohort delta could possibly be: the true within-cohort mean.

    Computed by evaluating the reference process's *expected* move for each
    member (contagion from their own neighbours, plus any shock; the noise term
    has mean zero) and averaging over the cohort. This is an **oracle** — no
    LLM prompt could beat it — which is what makes the gate diagnostic: if a
    layer fails here, the cause is aggregation itself, not prediction quality.
    """
    totals: dict[str, float] = dict.fromkeys(STATE_VAR_KEYS, 0.0)
    count = max(1, len(cohort.members))
    for member_id in cohort.members:
        peers = list(neighbours.get(member_id, ()))
        for key in STATE_VAR_KEYS:
            delta = 0.0
            if peers and previous_deltas:
                peer_moves = [
                    float(previous_deltas[p][key])
                    for p in peers
                    if p in previous_deltas and key in previous_deltas[p]
                ]
                if peer_moves:
                    delta += social_weight * float(np.mean(peer_moves))
            if shock:
                delta += float(shock.get(key, 0.0))
            totals[key] += delta
    return {key: total / count for key, total in totals.items() if abs(total) > 1e-12}


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass
class LayerResult:
    layer: Layer
    name: str
    passed: bool
    detail: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    #: True when the experiment could not discriminate — the reference signal
    #: was below the noise floor, so neither pass nor fail is warranted. Kept
    #: distinct from ``passed=False`` on purpose: "the approximation broke this"
    #: and "this experiment cannot tell" are different findings, and collapsing
    #: them is how a validation suite starts producing confident nonsense.
    inconclusive: bool = False

    @property
    def status(self) -> str:
        if self.inconclusive:
            return "inconclusive"
        return "pass" if self.passed else "fail"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "status": self.status}


@dataclass
class ValidationVerdict:
    population: int
    days: int
    layers: list[LayerResult] = field(default_factory=list)
    baseline: dict[str, Any] = field(default_factory=dict)

    @property
    def gate_passed(self) -> bool:
        """L2 and L4 are the design doc's declared dividing lines.

        An inconclusive dividing-line layer does **not** count as a pass. The
        gate exists to withhold approval until the evidence exists.
        """
        required = {"L2", "L4"}
        relevant = [r for r in self.layers if r.layer in required]
        return bool(relevant) and all(r.passed and not r.inconclusive for r in relevant)

    @property
    def all_passed(self) -> bool:
        return all(r.passed and not r.inconclusive for r in self.layers)

    @property
    def inconclusive_layers(self) -> list[str]:
        return [r.layer for r in self.layers if r.inconclusive]

    def to_dict(self) -> dict[str, Any]:
        return {
            "population": self.population,
            "days": self.days,
            "baseline": self.baseline,
            "layers": [r.to_dict() for r in self.layers],
            "gate_passed": self.gate_passed,
            "all_passed": self.all_passed,
        }


# ---------------------------------------------------------------------------
# Baseline: the reference tier's own run-to-run spread
# ---------------------------------------------------------------------------


def cross_seed_baseline(
    agents: Sequence[dict[str, Any]],
    neighbours: Mapping[int, Sequence[int]],
    *,
    days: int,
    seeds: Sequence[int] = (1, 2, 3),
) -> dict[str, Any]:
    """How much the reference tier disagrees with *itself* across seeds.

    This is the yardstick. An approximation whose distributional deviation sits
    inside the reference's own seed-to-seed band is, for distributional
    purposes, indistinguishable from another valid run of the reference.
    """
    runs = []
    moran_by_key: dict[str, list[float]] = {key: [] for key in FOCUS_KEYS}
    for seed in seeds:
        result = run_reference_tier([copy.deepcopy(a) for a in agents], neighbours, days=days, seed=seed)
        runs.append(state_columns(result["agents"], FOCUS_KEYS))
        for key in FOCUS_KEYS:
            traj = result["trajectories"][key]
            change = {i: series[-1] - series[0] for i, series in traj.items() if series}
            moran_by_key[key].append(morans_i(change, neighbours))

    gaps: dict[str, list[float]] = {key: [] for key in FOCUS_KEYS}
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            for key, stats in distribution_gap(runs[i], runs[j]).items():
                gaps[key].append(stats["wasserstein1"])
    return {
        "seeds": list(seeds),
        "wasserstein1_by_key": {k: float(np.mean(v)) if v else 0.0 for k, v in gaps.items()},
        "wasserstein1_max": float(max((max(v) for v in gaps.values() if v), default=0.0)),
        # The reference tier's own Moran's I level and run-to-run spread. L2
        # thresholds against this spread rather than against a fixed ratio band:
        # bounds like [0.5, 2.0] are precisely the arbitrary constants this
        # module refuses to use elsewhere, and at these population sizes the
        # ratio estimator's noise is comparable to the band width, so a band
        # verdict flips depending on which seeds were drawn.
        "morans_i_by_key": {k: float(np.mean(v)) if v else 0.0 for k, v in moran_by_key.items()},
        "morans_i_sd_by_key": {k: (float(np.std(v)) if len(v) > 1 else 0.0) for k, v in moran_by_key.items()},
    }


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def run_validation(
    agents: Sequence[dict[str, Any]],
    neighbours: Mapping[int, Sequence[int]],
    *,
    days: int = 14,
    seed: int = 1,
    seeds: Sequence[int] | None = None,
    materialization_budget: int = 20,
    audit_fraction: float = 0.03,
    baseline_seeds: Sequence[int] = (1, 2, 3),
    network_coupling: float = 0.0,
    shock: Mapping[str, float] | None = None,
    shock_from_day: int = 7,
    l1_tolerance_multiple: float = 2.0,
    l2_tolerance_multiple: float = 2.0,
    l3_tail_tolerance: float = 0.10,
    l4_magnitude_tolerance: float = 0.20,
) -> ValidationVerdict:
    """Run the paired experiment across ``seeds`` and evaluate all four layers.

    **Every layer is evaluated over multiple seeds**, not one. A single paired
    run is not enough to judge any of this: measured on one seed, the L2 ratio
    swings between 0.32 and 2.66 for the *same* configuration, so a single-seed
    verdict reports whichever draw it happened to get. That is the same failure
    mode as thresholding a ratio of two near-zero numbers — a precise-looking
    number standing in for evidence that was never collected.

    Thresholds are expressed *relative to the measured baseline* wherever
    possible (L1, L2) rather than as absolute constants, because an absolute
    threshold on a quantity whose natural scale we have not measured is just a
    guess wearing a number.
    """
    shock = shock or {"econ_security": -0.03, "stress": 0.02}
    run_seeds = tuple(seeds) if seeds else (seed, seed + 1, seed + 2)
    baseline = cross_seed_baseline(agents, neighbours, days=days, seeds=baseline_seeds)

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for run_seed in run_seeds:
        reference = run_reference_tier(
            [copy.deepcopy(a) for a in agents], neighbours, days=days, seed=run_seed
        )
        group = run_group_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=days,
            seed=run_seed,
            materialization_budget=materialization_budget,
            audit_fraction=audit_fraction,
            network_coupling=network_coupling,
        )
        pairs.append((reference, group))

    layers: list[LayerResult] = []
    layers.append(_evaluate_l1(pairs, baseline, l1_tolerance_multiple))
    layers.append(_evaluate_l2(pairs, neighbours, baseline, l2_tolerance_multiple))
    layers.append(_evaluate_l3(pairs, l3_tail_tolerance))
    layers.append(
        _evaluate_l4(
            agents,
            neighbours,
            days=days,
            seeds=run_seeds,
            materialization_budget=materialization_budget,
            audit_fraction=audit_fraction,
            shock=shock,
            shock_from_day=shock_from_day,
            network_coupling=network_coupling,
            magnitude_tolerance=l4_magnitude_tolerance,
        )
    )

    return ValidationVerdict(
        population=len(agents),
        days=days,
        layers=layers,
        baseline={**baseline, "run_seeds": list(run_seeds)},
    )


Pair = tuple[dict[str, Any], dict[str, Any]]


def _mean(values: Sequence[float]) -> float:
    return float(np.mean(list(values))) if values else 0.0


def _evaluate_l1(pairs: Sequence[Pair], baseline: dict[str, Any], tolerance_multiple: float) -> LayerResult:
    per_seed: list[dict[str, dict[str, float]]] = []
    for reference, group in pairs:
        per_seed.append(
            distribution_gap(
                state_columns(reference["agents"], FOCUS_KEYS),
                state_columns(group["agents"], FOCUS_KEYS),
            )
        )
    gaps = {
        key: {
            "wasserstein1": _mean([s[key]["wasserstein1"] for s in per_seed if key in s]),
            "ks": _mean([s[key]["ks"] for s in per_seed if key in s]),
            "mean_gap": _mean([s[key]["mean_gap"] for s in per_seed if key in s]),
            "sd_ratio": _mean([s[key]["sd_ratio"] for s in per_seed if key in s]),
        }
        for key in FOCUS_KEYS
    }
    budget = {
        key: max(baseline["wasserstein1_by_key"].get(key, 0.0) * tolerance_multiple, 0.005) for key in gaps
    }
    failures = {k: v["wasserstein1"] for k, v in gaps.items() if v["wasserstein1"] > budget[k]}
    return LayerResult(
        layer="L1",
        name="分布级：边缘分布距离是否落在参照层自身的种子间噪声量级内",
        passed=not failures,
        detail={
            "gaps": gaps,
            "budget": budget,
            "failures": failures,
            "seeds": len(pairs),
        },
        note=(
            f"阈值 = 参照层跨种子 Wasserstein 均值 × {tolerance_multiple:.1f}"
            f"（不是拍脑袋的绝对值）；跨 {len(pairs)} 个种子取均值"
        ),
    )


#: Below this, the reference tier's own social autocorrelation is too weak for
#: a ratio against it to mean anything. Ratios of two near-zero numbers are how
#: a validation suite produces a confident-looking -75.9 out of pure noise.
_MORAN_NOISE_FLOOR = 0.05


def _evaluate_l2(
    pairs: Sequence[Pair],
    neighbours: Mapping[int, Sequence[int]],
    baseline: dict[str, Any],
    tolerance_multiple: float = 2.0,
) -> LayerResult:
    """Does neighbour-mediated co-movement survive cohorting?

    The criterion is **baseline-relative**, matching L1: the group tier's social
    autocorrelation must land within ``tolerance_multiple`` × the reference
    tier's own cross-seed standard deviation of the same quantity. Two earlier
    attempts were worse:

    * a *floor* on the ratio (``group_I / reference_I >= 0.5``) accepted
      arbitrarily strong over-propagation, which misleads in the opposite
      direction just as badly;
    * a *band* (``0.5 <= ratio <= 2.0``) pulled two arbitrary constants out of
      the air, and at N=100 the ratio estimator's own noise turned out to be
      comparable to the band width — the verdict flipped across seed sets
      (3 of 5 passing at a fixed coupling), which makes it a coin toss dressed
      as a measurement.

    Standardising by the reference's own spread fixes both: the tolerance
    widens exactly when the quantity is hard to measure, and shrinks when it is
    not. The ratio is still reported, as a readable diagnostic rather than the
    decision rule.
    """
    per_key_ratios: dict[str, list[float]] = {key: [] for key in FOCUS_KEYS}
    per_key_ref: dict[str, list[float]] = {key: [] for key in FOCUS_KEYS}
    per_key_grp: dict[str, list[float]] = {key: [] for key in FOCUS_KEYS}

    for reference, group in pairs:
        for key in FOCUS_KEYS:
            ref_traj = reference["trajectories"][key]
            grp_traj = group["trajectories"][key]
            ref_change = {i: s[-1] - s[0] for i, s in ref_traj.items() if s}
            grp_change = {i: s[-1] - s[0] for i, s in grp_traj.items() if s}
            ref_i = morans_i(ref_change, neighbours)
            grp_i = morans_i(grp_change, neighbours)
            per_key_ref[key].append(ref_i)
            per_key_grp[key].append(grp_i)
            if abs(ref_i) >= _MORAN_NOISE_FLOOR:
                per_key_ratios[key].append(grp_i / ref_i)

    baseline_sd = baseline.get("morans_i_sd_by_key", {})
    detail: dict[str, Any] = {}
    failures: list[str] = []
    discriminating: list[str] = []
    worst_z = 0.0

    for key in FOCUS_KEYS:
        ref_mean = _mean(per_key_ref[key])
        grp_mean = _mean(per_key_grp[key])
        usable = abs(ref_mean) >= _MORAN_NOISE_FLOOR
        # Floor the tolerance so a freak run of near-identical baseline seeds
        # cannot make the test impossibly strict.
        sd = max(float(baseline_sd.get(key, 0.0)), _MORAN_NOISE_FLOOR / 2.0)
        z = abs(grp_mean - ref_mean) / sd
        detail[key] = {
            "reference_morans_i": ref_mean,
            "group_morans_i": grp_mean,
            "ratio": _mean(per_key_ratios[key]) if per_key_ratios[key] else float("nan"),
            "ratio_spread": (float(np.std(per_key_ratios[key])) if len(per_key_ratios[key]) > 1 else 0.0),
            "baseline_sd": sd,
            "z": z,
            "tolerance_z": tolerance_multiple,
            "usable": usable,
            "usable_seeds": len(per_key_ratios[key]),
        }
        if not usable:
            continue
        discriminating.append(key)
        worst_z = max(worst_z, z)
        if z > tolerance_multiple:
            failures.append(key)

    if not discriminating:
        return LayerResult(
            layer="L2",
            name="网络级：邻居间的状态共变（Moran's I）是否落在参照层自身噪声量级内",
            passed=False,
            inconclusive=True,
            detail={
                "by_key": detail,
                "noise_floor": _MORAN_NOISE_FLOOR,
                "seeds": len(pairs),
                "reason": "参照层自身的 Moran's I 低于噪声地板，无法判别",
            },
            note="参照过程没有产生足够强的社会传染信号，本次实验无法判别（不是通过，也不是失败）",
        )

    return LayerResult(
        layer="L2",
        name="网络级：邻居间的状态共变（Moran's I）是否落在参照层自身噪声量级内",
        passed=not failures,
        detail={
            "by_key": detail,
            "failures": failures,
            "worst_z": worst_z,
            "tolerance_z": tolerance_multiple,
            "discriminating_keys": discriminating,
            "noise_floor": _MORAN_NOISE_FLOOR,
            "seeds": len(pairs),
        },
        note=(
            f"判定 = |群体 I − 参照 I| ≤ {tolerance_multiple:.1f} × 参照层跨种子标准差"
            f"（与 L1 同一逻辑：阈值来自实测噪声，不是拍脑袋的比值上下界）；"
            f"跨 {len(pairs)} 个种子取均值"
        ),
    )


def _evaluate_l3(pairs: Sequence[Pair], tolerance: float) -> LayerResult:
    detail: dict[str, Any] = {}
    failures: list[str] = []
    for key in FOCUS_KEYS:
        ref_low, ref_high, ref_spread = [], [], []
        grp_low, grp_high, grp_spread = [], [], []
        for reference, group in pairs:
            r = tail_shares([a["state"][key] for a in reference["agents"]])
            g = tail_shares([a["state"][key] for a in group["agents"]])
            ref_low.append(r["low_share"])
            ref_high.append(r["high_share"])
            ref_spread.append(r["p10_p90_spread"])
            grp_low.append(g["low_share"])
            grp_high.append(g["high_share"])
            grp_spread.append(g["p10_p90_spread"])
        ref_stats = {
            "low_share": _mean(ref_low),
            "high_share": _mean(ref_high),
            "p10_p90_spread": _mean(ref_spread),
        }
        grp_stats = {
            "low_share": _mean(grp_low),
            "high_share": _mean(grp_high),
            "p10_p90_spread": _mean(grp_spread),
        }
        spread_ratio = (
            grp_stats["p10_p90_spread"] / ref_stats["p10_p90_spread"]
            if ref_stats["p10_p90_spread"] > 1e-9
            else 1.0
        )
        detail[key] = {
            "reference": ref_stats,
            "group": grp_stats,
            "spread_ratio": spread_ratio,
        }
        if abs(grp_stats["low_share"] - ref_stats["low_share"]) > tolerance:
            failures.append(f"{key}.low_share")
        if abs(grp_stats["high_share"] - ref_stats["high_share"]) > tolerance:
            failures.append(f"{key}.high_share")

    reference, group = pairs[0]
    detail["first_passage_stress_0.8"] = {
        "reference": first_passage_days(reference["trajectories"]["stress"], 0.8),
        "group": first_passage_days(group["trajectories"]["stress"], 0.8),
    }
    return LayerResult(
        layer="L3",
        name="尾部与稀有事件：极端个体占比、分位区间宽度、首次越阈时间",
        passed=not failures,
        detail={
            "by_key": detail,
            "failures": failures,
            "tolerance": tolerance,
            "seeds": len(pairs),
        },
        note="单列而非并入 L1：聚合近似的已知失效模式正是保住主体分布、压扁尾部",
    )


def _evaluate_l4(
    agents: Sequence[dict[str, Any]],
    neighbours: Mapping[int, Sequence[int]],
    *,
    days: int,
    seeds: Sequence[int],
    materialization_budget: int,
    audit_fraction: float,
    shock: Mapping[str, float],
    shock_from_day: int,
    network_coupling: float,
    magnitude_tolerance: float,
) -> LayerResult:
    """Same shock, both tiers, averaged over seeds: do the effects agree?"""
    subgroups = {
        int(a["id"]): f"{a.get('hukou', '未知')}|"
        f"{'employed' if a.get('employment') == 'employed' else 'other'}"
        for a in agents
    }
    outcome_key = "econ_security"

    def final(result: dict[str, Any]) -> dict[int, float]:
        return {int(a["id"]): float(a["state"][outcome_key]) for a in result["agents"]}

    ref_ates, grp_ates = [], []
    ref_heteros: list[dict[str, float]] = []
    grp_heteros: list[dict[str, float]] = []

    for run_seed in seeds:
        ref_control = run_reference_tier(
            [copy.deepcopy(a) for a in agents], neighbours, days=days, seed=run_seed
        )
        ref_treated = run_reference_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=days,
            seed=run_seed,
            shock=shock,
            shock_from_day=shock_from_day,
        )
        grp_control = run_group_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=days,
            seed=run_seed,
            materialization_budget=materialization_budget,
            audit_fraction=audit_fraction,
            network_coupling=network_coupling,
        )
        grp_treated = run_group_tier(
            [copy.deepcopy(a) for a in agents],
            neighbours,
            days=days,
            seed=run_seed,
            materialization_budget=materialization_budget,
            audit_fraction=audit_fraction,
            network_coupling=network_coupling,
            shock=shock,
            shock_from_day=shock_from_day,
        )
        ref_ates.append(average_treatment_effect(final(ref_control), final(ref_treated)))
        grp_ates.append(average_treatment_effect(final(grp_control), final(grp_treated)))
        ref_heteros.append(heterogeneous_effects(final(ref_control), final(ref_treated), subgroups))
        grp_heteros.append(heterogeneous_effects(final(grp_control), final(grp_treated), subgroups))

    ref_ate = _mean(ref_ates)
    grp_ate = _mean(grp_ates)
    groups = sorted({g for h in ref_heteros for g in h})
    ref_hetero = {g: _mean([h[g] for h in ref_heteros if g in h]) for g in groups}
    grp_hetero = {g: _mean([h[g] for h in grp_heteros if g in h]) for g in groups}

    same_sign = (ref_ate >= 0) == (grp_ate >= 0)
    magnitude_error = abs(grp_ate - ref_ate) / abs(ref_ate) if abs(ref_ate) > 1e-9 else 0.0
    ref_spread = effect_heterogeneity_spread(ref_hetero)
    grp_spread = effect_heterogeneity_spread(grp_hetero)
    hetero_retained = (grp_spread / ref_spread) if ref_spread > 1e-9 else 1.0
    agreement = sign_agreement(ref_hetero, grp_hetero)

    failures = []
    if not same_sign:
        failures.append("ate_sign_flip")
    if magnitude_error > magnitude_tolerance:
        failures.append("ate_magnitude")
    if hetero_retained < 0.5:
        failures.append("heterogeneity_collapsed")
    if agreement < 0.8:
        failures.append("subgroup_sign_disagreement")

    return LayerResult(
        layer="L4",
        name="因果响应：同一政策冲击下的 ATE 方向、量级与子群异质性",
        passed=not failures,
        detail={
            "outcome": outcome_key,
            "reference_ate": ref_ate,
            "group_ate": grp_ate,
            "same_sign": same_sign,
            "magnitude_relative_error": magnitude_error,
            "reference_subgroup_effects": ref_hetero,
            "group_subgroup_effects": grp_hetero,
            "heterogeneity_retained_ratio": hetero_retained,
            "subgroup_sign_agreement": agreement,
            "failures": failures,
            "seeds": len(seeds),
        },
        note="最关键的一层：基线分布对齐但 ATE 反号的近似，用于政策研究会得出相反结论",
    )


def render_verdict(verdict: ValidationVerdict) -> str:
    """Human-readable gate report."""
    lines = [
        f"═══ Group 模式验证门 ═══  人口 {verdict.population}｜{verdict.days} 天",
        f"参照层跨种子基线（Wasserstein-1 最大）：{verdict.baseline['wasserstein1_max']:.4f}"
        f"｜配对实验种子：{verdict.baseline.get('run_seeds', [])}",
        "",
    ]
    for result in verdict.layers:
        mark = {"pass": "✅ 通过", "fail": "❌ 未通过", "inconclusive": "⚠️ 无法判别"}[result.status]
        lines.append(f"{mark}  {result.layer}  {result.name}")
        if result.note:
            lines.append(f"        注：{result.note}")
        if result.layer == "L1":
            for key, stats in result.detail["gaps"].items():
                budget = result.detail["budget"][key]
                flag = "✗" if stats["wasserstein1"] > budget else "✓"
                lines.append(
                    f"        {flag} {key:16s} W1={stats['wasserstein1']:.4f}"
                    f"（预算 {budget:.4f}）sd比={stats['sd_ratio']:.2f}"
                )
        elif result.layer == "L2":
            for key, stats in result.detail["by_key"].items():
                ratio = (
                    f"比={stats['ratio']:.2f} z={stats['z']:.2f}"
                    f"（容差 {stats['tolerance_z']:.1f}σ，σ={stats['baseline_sd']:.3f}）"
                    if stats.get("usable")
                    else "（参照信号低于噪声地板，不参与判定）"
                )
                lines.append(
                    f"          {key:16s} 参照 I={stats['reference_morans_i']:+.3f}"
                    f"  群体 I={stats['group_morans_i']:+.3f}  {ratio}"
                    + (
                        f"（跨种子波动 ±{stats['ratio_spread']:.2f}）"
                        if stats.get("usable") and stats.get("ratio_spread")
                        else ""
                    )
                )
        elif result.layer == "L3":
            for key, stats in result.detail["by_key"].items():
                if not isinstance(stats, dict) or "spread_ratio" not in stats:
                    continue
                lines.append(
                    f"          {key:16s} 分位宽度比={stats['spread_ratio']:.2f}"
                    f"  低尾 {stats['reference']['low_share']:.3f}→{stats['group']['low_share']:.3f}"
                    f"  高尾 {stats['reference']['high_share']:.3f}→{stats['group']['high_share']:.3f}"
                )
        elif result.layer == "L4":
            d = result.detail
            lines.append(
                f"          ATE 参照={d['reference_ate']:+.4f}  群体={d['group_ate']:+.4f}"
                f"  同号={d['same_sign']}  相对误差={d['magnitude_relative_error']:.1%}"
            )
            lines.append(
                f"          子群异质性保留={d['heterogeneity_retained_ratio']:.2f}"
                f"  子群符号一致率={d['subgroup_sign_agreement']:.0%}"
            )
        if result.detail.get("failures"):
            lines.append(f"        失败项：{result.detail['failures']}")
        lines.append("")

    lines.append("关口结论（L2 + L4 为分水岭）：" + ("✅ 通过" if verdict.gate_passed else "❌ 未通过"))
    lines.append("全部四层：" + ("✅ 通过" if verdict.all_passed else "❌ 有未通过项"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: python -m gaworld.group.validate
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the gate and exit non-zero when the dividing lines are not passed.

    The non-zero exit is deliberate: this is a *gate*, so it should be usable
    directly in CI to stop group mode from being wired into the default path
    while it still fails a dividing-line layer.
    """
    import argparse
    import json

    from gaworld.population.generate import generate_population
    from gaworld.population.schema import PRESETS, normalize_spec

    parser = argparse.ArgumentParser(
        prog="python -m gaworld.group.validate",
        description="Run the L1-L4 validation gate comparing group mode against the per-agent tier.",
    )
    parser.add_argument("--size", type=int, default=100, help="Population size (design doc: 100)")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="cn_county_town")
    parser.add_argument("--population-seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=1, help="Simulation seed for the paired run")
    parser.add_argument("--budget", type=int, default=20, help="Materialisation budget per day")
    parser.add_argument("--audit-fraction", type=float, default=0.03)
    parser.add_argument(
        "--network-coupling",
        type=float,
        default=0.0,
        help="Graph coupling strength for the cohort tier (0 = pre-Phase-4 uniform shift)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    population = generate_population(
        normalize_spec({"size": args.size, "seed": args.population_seed, "preset": args.preset})
    )
    agents = [
        {
            "id": person.id,
            "name": person.name,
            "age": person.age,
            "gender": person.gender,
            "hukou": person.hukou,
            "industry": person.industry,
            "employment": person.employment,
            "residence": person.residence,
            "district": person.district,
            "state": dict(person.state),
        }
        for person in population.people
    ]

    verdict = run_validation(
        agents,
        population.neighbours,
        days=args.days,
        seed=args.seed,
        materialization_budget=args.budget,
        audit_fraction=args.audit_fraction,
        network_coupling=args.network_coupling,
    )

    if args.json:
        print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_verdict(verdict))

    return 0 if verdict.gate_passed else 1


__all__ = [
    "FOCUS_KEYS",
    "LayerResult",
    "ValidationVerdict",
    "cross_seed_baseline",
    "main",
    "make_reference_day",
    "render_verdict",
    "run_group_tier",
    "run_reference_tier",
    "run_validation",
]


if __name__ == "__main__":
    raise SystemExit(main())
