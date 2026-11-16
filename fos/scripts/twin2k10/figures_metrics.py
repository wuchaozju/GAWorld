# This module holds the twin2k10 figures' NUMBERS side: the fixed model and
# experiment orders, the 0-1 normalization rule, the error formulas that
# compare model answers against the human benchmark, the result-table row,
# the table builder with its special cases (anchoring excluded, base_rate
# first-digit variant, false_consensus without a contrast), the human
# test-retest band, and the descriptive variance split and per-model
# correlation. The drawing code lives in figures.py, which re-exports
# everything from here.

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

MODEL_ORDER: list[str] = [
    "gpt-oss-20b",
    "gemma-4-26b-a4b",
    "gemma-4-31b-it-qat",
    "gemma-4-12b-it-qat",
    "qwen3.8-27b",
    "qwen3.6-27b-dense",
    "qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored",
    "qwen3-32b",
    "qwen3-4b",
    "granite-4.1-8b",
    "granite-4.1-30b",
    "nemotron-cascade-2-30b-a3b",
    "muse-glimmer",
    "glm-4.7-flash",
]

# The 16 registry experiments in registry order.
EXPERIMENT_ORDER: list[str] = [
    "disease",
    "less_is_more",
    "fire_extinguisher",
    "seatbelt",
    "sunk_cost",
    "wta_wtp",
    "allais",
    "linda",
    "base_rate",
    "anchoring_redwood",
    "anchoring_african",
    "outcome_bias",
    "myside",
    "prob_matching",
    "abs_relative",
    "false_consensus",
]

_TOL = 1e-3  # tolerance when matching a contrast value back to an arm pair


def _anchor_share(value: object) -> float | None:
    """Return the 'answered more' share (0-1) when an arm carries the
    bounded anchor-choice observable, else None."""
    if isinstance(value, Mapping):
        mc = value.get("anchor_mc")
        if isinstance(mc, Mapping) and "1" in mc:
            return float(mc["1"]) / 100.0
    return None


def _is_anchor_arms(arms: Mapping) -> bool:
    """True when at least one human arm carries an anchor-choice share
    (the anchoring experiments' bounded observable)."""
    return any(_anchor_share(v) is not None for v in arms.values())


def _arm_mean(value: object) -> float | None:
    """The raw number carried by one arm value, in any accepted shape:
    a plain float, the builder's dict ({"mean": x} with an optional
    "n"), or one of the human stat cards handled by _stat_card_value
    (p_safe / p_yes / first-choice dist / per-statement / per-trial /
    per-item). A None value (missing model cell) carries no number."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        mean = value.get("mean")
        if mean is None:
            return _stat_card_value(value)
        return float(mean)
    return float(value)


def _stat_card_value(card: Mapping) -> float | None:
    """The raw number carried by one human stat card, keyed by the
    stat name registered in the experiment's contrasts / normalization
    rule (never invented): "p_safe" or "p_yes" proportions read
    directly; a "dist" card contributes the share choosing option 1
    (its "1" bucket pct / 100 = p_opt1); "per_statement" cards
    contribute statement 3's mean (mean_statement3); a
    "per_trial_pct_majority" card contributes the subject mean majority
    share (mean of the per-trial pcts / 100); a "per_item" card
    contributes the mean of the per-item means. None when the card
    matches none of these shapes."""
    for stat in ("p_safe", "p_yes"):
        if isinstance(card.get(stat), (int, float)):
            # The registry declares these proportions as "already 0-1";
            # the real survey cards store some of them as percents
            # (e.g. p_yes 73.7), so a value above 1 is a percent and is
            # brought back onto the registered 0-1 scale.
            value = float(card[stat])
            return value / 100.0 if value > 1.0 else value
    dist = card.get("dist")
    if isinstance(dist, Mapping) and "1" in dist:
        bucket = dist["1"]
        if isinstance(bucket, Mapping) and "pct" in bucket:
            return float(bucket["pct"]) / 100.0
    per_statement = card.get("per_statement")
    if isinstance(per_statement, Mapping):
        third = [
            v
            for k, v in per_statement.items()
            if k.endswith("_3") and isinstance(v, Mapping) and "mean" in v
        ]
        if third:
            return float(third[0]["mean"])
    per_trial = card.get("per_trial_pct_majority")
    if isinstance(per_trial, Mapping) and per_trial:
        return float(np.mean([float(v) for v in per_trial.values()])) / 100.0
    per_item = card.get("per_item")
    if isinstance(per_item, Mapping) and per_item:
        means = [
            float(v["mean"])
            for v in per_item.values()
            if isinstance(v, Mapping) and "mean" in v
        ]
        if means:
            return float(np.mean(means))
    return None


def _arm_observable(value: object, spec: Mapping, anchor_mode: bool) -> float | None:
    """The single 0-1 number compared for one arm: the anchor-choice
    share when the experiment is anchored (model arms are already 0-1
    shares), otherwise the registry-normalized raw value. Arm values may
    be floats or {"mean": x} dicts (with or without "n")."""
    mean = _arm_mean(value)
    if anchor_mode:
        share = _anchor_share(value)
        if share is not None:
            return share
        return mean
    if mean is None:
        return None
    return normalize(mean, spec)


def _observables(
    arms: Mapping, spec: Mapping, anchor_mode: bool
) -> dict[str, float] | None:
    """Map every arm of one experiment onto its comparable 0-1 number;
    None if any arm has no rule (or no share)."""
    out: dict[str, float] = {}
    for arm, value in arms.items():
        obs = _arm_observable(value, spec, anchor_mode)
        if obs is None:
            return None
        out[arm] = obs
    return out


def normalize(value: float, spec: Mapping) -> float | None:
    """Map one raw answer onto 0-1 with the experiment's registered
    min/max. Returns None when the registry has no rule (NEEDS-OWNER)."""
    lo = spec.get("min")
    hi = spec.get("max")
    if lo is None or hi is None:
        return None
    return (value - lo) / (hi - lo)


def profile_error(
    model_means: Mapping[str, float], human_means: Mapping[str, float]
) -> float:
    """Average distance between the model's and the humans' arm means on
    the 0-1 scale, times 100. Both inputs must already be normalized."""
    gaps = [
        abs(model_means[arm] - human_means[arm])
        for arm in model_means
        if arm in human_means
    ]
    if not gaps:
        raise ValueError("no shared arms between model and human means")
    return float(np.mean(gaps) * 100.0)


def contrast_error(
    model_contrasts: Mapping[str, float], human_contrasts: Mapping[str, float]
) -> float:
    """Average distance between the model's and the humans' pre-specified
    contrast values (0-1 scale), times 100."""
    names = [name for name in model_contrasts if name in human_contrasts]
    if not names:
        raise ValueError("no shared contrasts between model and human")
    gaps = [abs(model_contrasts[name] - human_contrasts[name]) for name in names]
    return float(np.mean(gaps) * 100.0)


def profile_error_first_digit(
    model_dist: Mapping[int, float], human_dist: Mapping[int, float]
) -> float:
    """Average distance between two digit distributions (0-9 buckets),
    times 100. Used where the model side is a first-digit distribution."""
    digits = range(10)
    gaps = [abs(model_dist.get(d, 0.0) - human_dist.get(d, 0.0)) for d in digits]
    return float(np.mean(gaps) * 100.0)


@dataclass
class ErrorRow:
    """One line of the result table: a model's error numbers on one
    experiment, plus which comparison method was used."""

    model: str
    experiment: str
    method: str  # "arm_mean" or "first_digit"
    profile_error_blinded: float | None
    profile_error_unblinded: float | None
    contrast_error: float | None


def _normalize_arms(
    arms: Mapping[str, object], spec: Mapping
) -> dict[str, float] | None:
    """Normalize every arm of one experiment; None if any arm has no
    rule. Arm values may be floats or {"mean": x} dicts."""
    out: dict[str, float] = {}
    for arm, value in arms.items():
        mean = _arm_mean(value)
        if mean is None:
            return None
        normed = normalize(mean, spec)
        if normed is None:
            return None
        out[arm] = normed
    return out


def _find_arm_pair(arms: Mapping[str, float], target: float) -> tuple[str, str] | None:
    """Find two arms whose RAW difference equals the target RAW contrast
    value. Matching happens on the RAW human arm means only, so the pair
    is identified once and then applied to both sides' 0-1 numbers — the
    value itself never gates computability (the TASK-2409 root cause)."""
    names = list(arms)
    for a in names:
        for b in names:
            if a != b and abs(arms[a] - arms[b] - target) < _TOL:
                return (a, b)
    return None


def _contrast_gap(
    human_wave: Mapping,
    human_raw: Mapping,
    human_obs: Mapping[str, float],
    blinding_arms: Mapping,
    spec: Mapping,
    anchor_mode: bool,
) -> float | None:
    """Mean |model effect - human effect| x100, both effects computed on
    the 0-1 scale. Anchored experiments use the high-low anchor-choice
    gap; others use each registered contrast's arm pair found on the RAW
    human arms."""
    if "blinded" not in blinding_arms:
        return None
    model_obs = _observables(blinding_arms["blinded"], spec, anchor_mode)
    if model_obs is None:
        return None
    if anchor_mode:
        if not {"low", "high"} <= set(human_obs):
            return None
        if not {"low", "high"} <= set(model_obs):
            return None
        human_delta = human_obs["high"] - human_obs["low"]
        model_delta = model_obs["high"] - model_obs["low"]
        return abs(model_delta - human_delta) * 100.0
    gaps: list[float] = []
    for name, info in human_wave.get("contrasts", {}).items():
        if not info.get("computable"):
            continue
        pair = _find_arm_pair(human_raw, info["value"])
        if pair is None or not all(arm in model_obs for arm in pair):
            continue
        a, b = pair
        model_delta = model_obs[a] - model_obs[b]
        human_delta = human_obs[a] - human_obs[b]
        gaps.append(abs(model_delta - human_delta))
    if not gaps:
        return None
    return float(np.mean(gaps) * 100.0)


def _unwrap_means(entry: Mapping) -> Mapping:
    """Return one blinding condition's arms. When the entry wraps its
    arms inside a "means" key (the production builder shape, with a
    sibling "n" of sample counts), unwrap it; otherwise the entry is
    already the arms mapping."""
    means = entry.get("means")
    if isinstance(means, Mapping):
        return means
    return entry


def _experiment_row(
    model: str,
    experiment: str,
    spec: Mapping,
    human_wave: Mapping,
    blinding_arms: Mapping[str, Mapping],
    first_digit: bool,
) -> ErrorRow:
    """Build one model-x-experiment row: put every arm (human and
    model) on its comparable 0-1 observable first, then compute both
    blinding conditions' profile errors and the contrast error."""
    method = "first_digit" if first_digit else "arm_mean"
    if first_digit:
        # base_rate: the model side is first-digit mass only, so neither
        # the Profile Error nor an effect error is computable; the method
        # label documents the excluded variant.
        return ErrorRow(model, experiment, method, None, None, None)
    human_cards: Mapping = human_wave.get("arms", {})
    anchor_mode = _is_anchor_arms(human_cards)
    human_obs = _observables(human_cards, spec, anchor_mode)
    if human_obs is None:
        # No registered rule for the human observable (NEEDS-OWNER).
        return ErrorRow(model, experiment, method, None, None, None)
    # The contrast pair search compares RAW numbers, so reduce the
    # human stat cards to their numbers first (never subtract dicts).
    human_raw = {
        arm: value
        for arm, value in ((a, _arm_mean(v)) for a, v in human_cards.items())
        if value is not None
    }
    profile: dict[str, float | None] = {}
    for label, arms in blinding_arms.items():
        model_obs = _observables(arms, spec, anchor_mode)
        profile[label] = (
            None if model_obs is None else profile_error(model_obs, human_obs)
        )
    contrast: float | None = None
    if all(v is not None for v in profile.values()):
        contrast = _contrast_gap(
            human_wave, human_raw, human_obs, blinding_arms, spec, anchor_mode
        )
    return ErrorRow(
        model=model,
        experiment=experiment,
        method=method,
        profile_error_blinded=profile.get("blinded"),
        profile_error_unblinded=profile.get("unblinded"),
        contrast_error=contrast,
    )


def compute_error_rows(registry_subset: Mapping, llm_means: Mapping) -> list[ErrorRow]:
    """Build the error table for every model and experiment present in the
    caller's data, in the pinned MODEL_ORDER / EXPERIMENT_ORDER."""
    rows: list[ErrorRow] = []
    for model in MODEL_ORDER:
        if model not in llm_means:
            continue
        for experiment in EXPERIMENT_ORDER:
            if experiment not in llm_means[model]:
                continue
            spec = registry_subset[experiment]["normalization_0_1"]
            human_wave = registry_subset[experiment]["human"]["wave1_3"]
            blinding = {
                label: _unwrap_means(entry)
                for label, entry in llm_means[model][experiment].items()
            }
            first_digit = bool(registry_subset[experiment].get("first_digit_profile"))
            rows.append(
                _experiment_row(
                    model, experiment, spec, human_wave, blinding, first_digit
                )
            )
    return rows


def human_test_retest_errors(registry_subset: Mapping) -> dict:
    """Run the SAME profile and contrast formulas between the humans'
    wave1_3 and wave4 answers. This is the test-retest band: how far the
    same humans drift between the two waves. Split-half is never used."""
    band: dict[str, dict] = {}
    for experiment, config in registry_subset.items():
        band[experiment] = _retest_experiment(config)
    return band


def _retest_contrast(
    wave13: Mapping, wave4: Mapping, spec: Mapping, anchor_mode: bool
) -> float | None:
    """The humans' wave1_3-vs-wave4 effect drift on the 0-1 scale:
    registered raw contrasts are divided by the registry range; anchored
    experiments use the high-low anchor-choice gap."""
    if anchor_mode:
        lo13, hi13 = wave13["arms"].get("low"), wave13["arms"].get("high")
        lo4, hi4 = wave4["arms"].get("low"), wave4["arms"].get("high")
        shares = [_anchor_share(v) for v in (lo13, hi13, lo4, hi4)]
        if any(s is None for s in shares):
            return None
        delta13, delta4 = shares[1] - shares[0], shares[3] - shares[2]
        return abs(delta4 - delta13) * 100.0
    lo, hi = spec.get("min"), spec.get("max")
    if lo is None or hi is None or hi == lo:
        return None
    c13 = {
        n: i["value"]
        for n, i in wave13.get("contrasts", {}).items()
        if i.get("computable")
    }
    c4 = {
        n: i["value"]
        for n, i in wave4.get("contrasts", {}).items()
        if i.get("computable")
    }
    shared = [n for n in c13 if n in c4]
    if not shared:
        return None
    gaps = [abs(c4[n] / (hi - lo) - c13[n] / (hi - lo)) for n in shared]
    return float(np.mean(gaps) * 100.0)


def _retest_experiment(config: Mapping) -> dict:
    """Test-retest numbers for one experiment: the profile drift (only
    when at least two arms form a pattern) and the effect drift."""
    spec = config["normalization_0_1"]
    first_digit = bool(config.get("first_digit_profile"))
    wave13 = config["human"]["wave1_3"]
    wave4 = config["human"]["wave4"]
    raw13: Mapping = wave13.get("arms", {})
    raw4: Mapping = wave4.get("arms", {})
    anchor_mode = _is_anchor_arms(raw13) or _is_anchor_arms(raw4)
    obs13 = _observables(raw13, spec, anchor_mode)
    obs4 = _observables(raw4, spec, anchor_mode)
    profile: float | None = None
    if not first_digit and obs13 is not None and obs4 is not None and len(obs13) >= 2:
        profile = profile_error(obs4, obs13)
    contrast: float | None = None
    if not first_digit and obs13 is not None and obs4 is not None:
        contrast = _retest_contrast(wave13, wave4, spec, anchor_mode)
    return {
        "profile_error": profile,
        "contrast_error": contrast,
        "n_arms": 0 if obs13 is None else len(obs13),
        "anchor_choice": anchor_mode,
    }


def variance_components(rows: list[ErrorRow]) -> dict:
    """Split the model-x-experiment profile-error table into three
    descriptive shares (model, experiment, leftover) that add up to 1."""
    cells: list[tuple[str, str, float]] = []
    for row in rows:
        value = row.profile_error_blinded
        if value is not None:
            cells.append((row.model, row.experiment, value))
    if not cells:
        return {"model": 0.0, "experiment": 0.0, "residual": 1.0}
    grand = float(np.mean([v for _, _, v in cells]))
    model_effects = []
    experiment_effects = []
    residuals = []
    for m, e, v in cells:
        m_mean = float(np.mean([x for mm, _, x in cells if mm == m]))
        e_mean = float(np.mean([x for _, ee, x in cells if ee == e]))
        model_effects.append(m_mean - grand)
        experiment_effects.append(e_mean - grand)
        residuals.append(v - m_mean - e_mean + grand)
    total = (
        float(np.mean(np.square(model_effects)))
        + float(np.mean(np.square(experiment_effects)))
        + float(np.mean(np.square(residuals)))
    )
    if total <= 0:
        return {"model": 0.0, "experiment": 0.0, "residual": 1.0}
    return {
        "model": float(np.mean(np.square(model_effects)) / total),
        "experiment": float(np.mean(np.square(experiment_effects)) / total),
        "residual": float(np.mean(np.square(residuals)) / total),
    }


def profile_contrast_correlation(rows: list[ErrorRow]) -> dict:
    """For each model, how its profile error moves with its contrast
    error across experiments. None when fewer than 3 points line up."""
    by_model: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        if row.profile_error_blinded is None or row.contrast_error is None:
            continue
        by_model.setdefault(row.model, []).append(
            (row.profile_error_blinded, row.contrast_error)
        )
    corr: dict[str, float | None] = {}
    for model in MODEL_ORDER:
        if model not in by_model:
            continue
        pairs = by_model[model]
        if len(pairs) < 3:
            corr[model] = None
            continue
        xs = np.array([p for p, _ in pairs])
        ys = np.array([c for _, c in pairs])
        if np.std(xs) == 0 or np.std(ys) == 0:
            corr[model] = None
            continue
        corr[model] = float(np.corrcoef(xs, ys)[0, 1])
    return corr
