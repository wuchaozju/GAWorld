# Compute per-arm mean LLM outcomes for the twin2k10 experiments.
#
# What this file does: for every experiment in the registry, it reads the
# run records (one JSON object per line in records.jsonl), turns each
# record into one raw-scale number using that experiment's outcome rule,
# and averages those numbers per arm, separately for the blinded and
# unblinded legs. It also counts how many records each average is based
# on.
#
# Functions:
#   build_llm_arm_means(registry, run_roots)
#       -> the full nested result:
#          {model: {experiment: {"blinded": {"means": {arm: number},
#                                            "n": {arm: count}},
#                                "unblinded": {...}}}}
#   _expand_leg_paths(pattern, run_root)
#       -> turns the registry's leg path pattern (which contains a
#          "{model}" placeholder and a brace list like
#          "{allais_blinded,unblinded}") into concrete file paths plus
#          the blinding label of each.
#   _read_records(path)
#       -> the successfully-parsed records from one records.jsonl file.
#   _record_outcome(record, experiment)
#       -> the one number this record contributes (None when the
#          experiment's rule cannot produce a number).
#   _expected_digit_restricted(masses)
#       -> mass-weighted mean digit over digits 1-6 only (digit 0 is
#          off-scale noise and is dropped, the rest renormalised).
#   _prob_match_share(items)
#       -> mean over trials of P(majority) = mass on "1" divided by the
#          trial's total digit mass.
#   _leg_summary(records, experiment)
#       -> {"means": {arm: float|None}, "n": {arm: int}} for one leg.

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import fmean
from string import ascii_uppercase

# Experiments whose registry rule is NEEDS-OWNER: records still count
# toward n, but the arm mean stays None (written as JSON null).
NEEDS_OWNER_EXPERIMENTS = frozenset({"base_rate"})

# Likert experiments: expected letter code on a 1..N scale (A=1).
_LIKERT_EXPERIMENTS = {
    "less_is_more": 5,
    "fire_extinguisher": 5,
    "seatbelt": 6,
    "myside": 6,
    "outcome_bias": 7,
}

# Ordinal experiments: expected letter code where the letters stand for
# ordered amounts (sunk_cost A-U = 0-20 purchases; wta_wtp A-J = money
# brackets 1-10; dollar means are NOT implied for the brackets).
_ORDINAL_EXPERIMENTS = {
    "sunk_cost": 21,
    "wta_wtp": 10,
}

# Anchoring experiments: the registry-defined arm statistic is the anchor
# choice itself, P(more) = p_norm["A"] (A=more, B=less/fewer). The numeric
# estimate is NOT derivable (records carry only first-token digit mass).
_ANCHOR_EXPERIMENTS = frozenset({"anchoring_redwood", "anchoring_african"})

# Digits that carry a real answer for false_consensus items (1-5 scale).
_CONSENSUS_DIGITS = ("1", "2", "3", "4", "5")

# Matches each brace group in a leg path pattern, e.g. "{model}" or
# "{allais_blinded,unblinded}".
_BRACE_GROUP = re.compile(r"\{([^{}]*)\}")

# Digits that carry a real answer for digit experiments. Digit "0" is
# off-scale noise (an artefact of single-token digit mass), not a choice.
_ANSWER_DIGITS = ("1", "2", "3", "4", "5", "6")


def _expand_leg_paths(pattern: str, run_root: Path) -> list[tuple[Path, str]]:
    """Turn a registry leg path pattern into (file path, blinding) pairs.

    The pattern holds one brace group per wildcard: "{model}" expands to
    every model directory found under the run root; any other brace group
    is a comma-separated list of directory-name options (e.g. the blinded
    and unblinded leg directory names).
    """
    candidates = [pattern]
    for match in _BRACE_GROUP.findall(pattern):
        if match == "model":
            options = sorted(
                child.name for child in run_root.iterdir() if child.is_dir()
            )
        else:
            options = [option.strip() for option in match.split(",")]
        candidates = [
            candidate.replace("{" + match + "}", option, 1)
            for candidate in candidates
            for option in options
        ]
    legs: list[tuple[Path, str]] = []
    for candidate in candidates:
        path = Path(candidate)
        parts = path.parts
        # The leg directory is either named "<experiment>_blinded" or
        # plainly "unblinded"; everything else counts as blinded.
        blinding = "unblinded" if "unblinded" in parts else "blinded"
        legs.append((path, blinding))
    return legs


def _read_records(path: Path) -> list[dict]:
    """Read one records.jsonl file; skip blank lines.

    A malformed line is a data error, not something to hide, so it raises.
    """
    if not path.is_file():
        return []
    records: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path}:{line_number}: malformed record line"
                ) from error
    return records


def _expected_digit_restricted(
    masses: dict[str, float],
    digits: tuple[str, ...] = _ANSWER_DIGITS,
) -> float | None:
    """Mass-weighted mean digit over the in-scale digits, renormalised.

    Off-scale mass (e.g. digit "0" noise) is dropped before averaging.
    Returns None when no in-scale mass remains.
    """
    in_scale = {
        digit: mass
        for digit, mass in masses.items()
        if digit in digits and mass is not None and mass > 0.0
    }
    total = sum(in_scale.values())
    if total <= 0.0:
        return None
    return sum(int(digit) * mass for digit, mass in in_scale.items()) / total


def _prob_match_share(items: list[dict]) -> float | None:
    """Mean over trials of P(majority) = mass on "1" / trial digit mass.

    Trials with no digit mass at all are skipped. Returns None when no
    usable trial remains.
    """
    shares: list[float] = []
    for item in items:
        masses = item.get("p_norm") or {}
        total = sum(mass for mass in masses.values() if mass is not None)
        if total <= 0.0:
            continue
        share = masses.get("1")
        if share is None:
            share = 0.0
        shares.append(share / total)
    if not shares:
        return None
    return fmean(shares)


def _expected_letter_code(p_norm: dict, n_letters: int) -> float | None:
    """Expected letter code on a 1..N scale (A=1, B=2, ...), mass-weighted.

    Letters with no (or None) mass are skipped; returns None when no
    in-range mass remains.
    """
    letters = ascii_uppercase[:n_letters]
    total = sum(p_norm[letter] for letter in letters if p_norm.get(letter) is not None)
    if total <= 0.0:
        return None
    return (
        sum(
            (position + 1) * p_norm[letter]
            for position, letter in enumerate(letters)
            if p_norm.get(letter) is not None
        )
        / total
    )


def _false_consensus_mean(items: list[dict]) -> float | None:
    """Mean over the digit items of E[digit | 1-5] (the registry's rule:
    per item 1-5, leg value = mean over the 10 items). Off-scale digit
    mass is dropped per item; items with no in-scale mass are skipped.
    Returns None when no item yields a number."""
    item_means = [
        mean
        for item in items
        if (
            mean := _expected_digit_restricted(
                item.get("p_norm") or {}, _CONSENSUS_DIGITS
            )
        )
        is not None
    ]
    if not item_means:
        return None
    return fmean(item_means)


def _record_outcome(record: dict, experiment: str) -> float | None:
    """The one raw-scale number this record contributes to its arm mean.

    Each experiment has its own rule (matching the registry's
    record_to_outcome_map):
      disease       -> the record's ready-made p_safe_norm field.
      allais        -> p_norm mass on letter "A" (A is always option 1).
      linda         -> expected digit of the critical (row 3) statement's
                       first-token digit mass, restricted to digits 1-6.
      prob_matching -> mean over trials of the majority-deck share.
      less_is_more, fire_extinguisher, seatbelt, outcome_bias, myside
                    -> expected letter code on the experiment's Likert
                       range (A=1).
      sunk_cost     -> expected letter code, letters A-U = 0-20 purchases.
      wta_wtp       -> expected letter code, letters A-J = bracket 1-10
                       (ordinal; dollar means are not implied).
      anchoring_*   -> anchor choice P(more) = p_norm["A"] (the estimate
                       is not derivable from first-digit mass).
      abs_relative  -> P(Yes) = p_norm["A"] (A=Yes, B=No).
      false_consensus -> mean over the 10 items of E[digit | 1-5].
      base_rate     -> NEEDS-OWNER: no derivable number, always None.
    Returns None when the rule cannot produce a number for this record.
    """
    if experiment in NEEDS_OWNER_EXPERIMENTS:
        return None
    if experiment in _LIKERT_EXPERIMENTS:
        return _expected_letter_code(
            record.get("p_norm") or {}, _LIKERT_EXPERIMENTS[experiment]
        )
    if experiment in _ORDINAL_EXPERIMENTS:
        code = _expected_letter_code(
            record.get("p_norm") or {}, _ORDINAL_EXPERIMENTS[experiment]
        )
        if code is None:
            return None
        # sunk_cost letters A-U carry codes 1-21 but stand for 0-20
        # purchases; wta_wtp letters A-J already stand for brackets 1-10.
        return code - 1 if experiment == "sunk_cost" else code
    if experiment in _ANCHOR_EXPERIMENTS:
        p_norm = record.get("p_norm") or {}
        value = p_norm.get("A")
        return float(value) if value is not None else None
    if experiment == "disease":
        value = record.get("p_safe_norm")
        return float(value) if value is not None else None
    if experiment in ("allais", "abs_relative"):
        p_norm = record.get("p_norm") or {}
        value = p_norm.get("A")
        return float(value) if value is not None else None
    if experiment == "false_consensus":
        items = record.get("digit_items") or []
        if not items:
            return None
        return _false_consensus_mean(items)
    if experiment == "linda":
        items = record.get("digit_items") or []
        critical = [item for item in items if item.get("row") == 3]
        if not critical:
            return None
        return _expected_digit_restricted(critical[0].get("p_norm") or {})
    if experiment == "prob_matching":
        items = record.get("digit_items") or []
        if not items:
            return None
        return _prob_match_share(items)
    # Unknown experiment: no rule, no number.
    return None


def _leg_summary(records: list[dict], experiment: str) -> dict:
    """Mean outcome and record count per arm for one leg.

    Records that did not succeed are excluded from both the means and the
    counts. An arm whose records all lack a derivable outcome gets a None
    mean (its records still count in n).
    """
    values_by_arm: dict[str, list[float]] = {}
    n_by_arm: dict[str, int] = {}
    for record in records:
        if not record.get("succeeded", False):
            continue
        arm = record.get("arm")
        if arm is None:
            continue
        n_by_arm[arm] = n_by_arm.get(arm, 0) + 1
        outcome = _record_outcome(record, experiment)
        if outcome is not None:
            values_by_arm.setdefault(arm, []).append(outcome)
    means = {
        arm: (fmean(values_by_arm[arm]) if values_by_arm.get(arm) else None)
        for arm in n_by_arm
    }
    return {"means": means, "n": n_by_arm}


def build_llm_arm_means(registry: dict, run_roots: dict[str, Path]) -> dict:
    """Per-arm LLM mean outcomes for every experiment named in the registry.

    Only the registry's "experiments" section is read; each experiment
    must carry "run", "leg_path_pattern" and "arm_roles". run_roots maps
    each run name to its root directory on disk. The result is nested
    model -> experiment -> blinding -> {"means", "n"}.
    """
    result: dict[str, dict[str, dict[str, dict]]] = {}
    for experiment, spec in registry.get("experiments", {}).items():
        run_name = spec["run"]
        run_root = Path(run_roots[run_name])
        for leg_path, blinding in _expand_leg_paths(spec["leg_path_pattern"], run_root):
            records = _read_records(leg_path)
            models_on_leg = sorted(
                {
                    record.get("model")
                    for record in records
                    if record.get("model") is not None
                }
            )
            for model in models_on_leg:
                model_records = [
                    record for record in records if record.get("model") == model
                ]
                model_summary = _leg_summary(model_records, experiment)
                result.setdefault(model, {}).setdefault(experiment, {}).setdefault(
                    blinding, model_summary
                )
    return result
