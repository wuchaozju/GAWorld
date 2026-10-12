# This file compares the study's model answers with the human benchmark
# numbers and writes the result tables. It averages each arm's scored
# outcome over the 100 personas, takes the pinned contrasts between arms
# (same names and signs as the shipped human benchmarks), measures how far
# the model is from the human wave1_3 numbers (absolute, and normalized by
# each experiment's scale divisor), and reports the unblinding gain — how
# much less error the unblinded arm has than the blinded arm, where a
# positive number means seeing the randomization note helped. It also
# summarizes answer quality per model and experiment (mean branch mass and
# the share of diffuse answers) and writes tidy CSVs plus a summary.json.

import csv
import json
from pathlib import Path
from statistics import fmean

from twin2k6 import config, experiments

# Each experiment's error is normalized by the width of its scored scale,
# so a 4-point and a 21-point experiment contribute comparable errors.
NORMALIZATION = {
    "disease": 1.0,
    "less_is_more": 4.0,
    "fire_extinguisher": 4.0,
    "seatbelt": 5.0,
    "sunk_cost": 20.0,
    "wta_wtp": 9.0,
}

# The pinned contrasts: experiment -> contrast name -> (arm1, arm2), the
# value being arm2's mean minus arm1's mean. Names and signs match the
# shipped human benchmarks file exactly.
CONTRASTS = {
    "disease": {"p_safe_loss_minus_gain": ("gain", "loss")},
    "less_is_more": {"B_minus_A": ("A", "B"), "C_minus_A": ("A", "C")},
    "fire_extinguisher": {
        "98pct_minus_all": ("all", "98pct"),
        "95pct_minus_all": ("all", "95pct"),
    },
    "seatbelt": {
        "98pct_minus_all": ("all", "98pct"),
        "95pct_minus_all": ("all", "95pct"),
    },
    "sunk_cost": {"card_minus_no_card": ("no_card", "card")},
    "wta_wtp": {
        "wta_minus_wtp_certainty": ("wtp_certainty", "wta_certainty"),
        "wtp_noncertainty_minus_wtp_certainty": (
            "wtp_certainty", "wtp_noncertainty"),
    },
}


def _arm_statistic(record: dict, experiment: str) -> float | None:
    """The one number an arm's mean averages, from one record.

    Disease's arm statistic is the normalized safe-side probability
    (p_safe_norm — the primary measure, even when expected_1_6 disagrees);
    every other experiment uses its pinned expected-value outcome field.
    Records missing the statistic return None and never enter the mean.
    """
    if experiment == "disease":
        return record.get("p_safe_norm")
    field = experiments.EXPERIMENTS[experiment].outcome_field
    return record.get(field)


def arm_means(records: list[dict]) -> dict[tuple, float]:
    """Each arm's mean outcome, keyed (model, experiment, blind, arm).

    Averages the arm statistic over the records of each (model, experiment,
    blinding, arm) group; records without a scored outcome are excluded.
    """
    grouped: dict[tuple, list[float]] = {}
    for record in records:
        value = _arm_statistic(record, record["experiment"])
        if value is None:
            continue
        key = (record["model"], record["experiment"],
               record["blind"], record["arm"])
        grouped.setdefault(key, []).append(value)
    return {key: fmean(values) for key, values in grouped.items()}


def contrast_values(records: list[dict]) -> dict[tuple, dict[str, float]]:
    """The pinned contrasts per (model, experiment, blinding) group.

    Each contrast is arm2's mean minus arm1's mean with the pinned sign.
    A contrast is skipped when one of its arms has no data — a missing arm
    is never read as a zero.
    """
    means = arm_means(records)
    results: dict[tuple, dict[str, float]] = {}
    for (model, experiment, blinding, arm), mean in means.items():
        results.setdefault((model, experiment, blinding), {})[arm] = mean
    contrasts: dict[tuple, dict[str, float]] = {}
    for (model, experiment, blinding), by_arm in results.items():
        for name, (arm1, arm2) in CONTRASTS[experiment].items():
            if arm1 in by_arm and arm2 in by_arm:
                contrasts.setdefault((model, experiment, blinding), {})[name] = (
                    by_arm[arm2] - by_arm[arm1]
                )
    return contrasts


def absolute_contrast_errors(records: list[dict], benchmarks: dict) -> dict[tuple, dict[str, float]]:
    """|model contrast - human contrast| against the wave1_3 benchmarks.

    Keyed (model, experiment, blinding) -> contrast name -> absolute error.
    Contrasts absent from the human benchmarks are skipped.
    """
    humans = benchmarks["waves"]["wave1_3"]
    errors: dict[tuple, dict[str, float]] = {}
    for key, by_name in contrast_values(records).items():
        model, experiment, blinding = key
        human_contrasts = humans[experiment]["contrasts"]
        for name, value in by_name.items():
            if name not in human_contrasts:
                continue
            human_value = human_contrasts[name]["value"]
            errors.setdefault(key, {})[name] = abs(value - human_value)
    return errors


def normalized_contrast_errors(records: list[dict], benchmarks: dict) -> dict[tuple, dict[str, float]]:
    """Absolute contrast errors divided by each experiment's scale divisor."""
    errors = absolute_contrast_errors(records, benchmarks)
    return {
        key: {
            name: value / NORMALIZATION[key[1]]
            for name, value in by_name.items()
        }
        for key, by_name in errors.items()
    }


def _human_arm_statistic(benchmarks: dict, experiment: str, arm: str) -> float | None:
    """The human benchmark number for one arm (p_safe for disease, else mean)."""
    arm_entry = benchmarks["waves"]["wave1_3"][experiment]["arms"].get(arm)
    if arm_entry is None:
        return None
    if experiment == "disease":
        return arm_entry.get("p_safe")
    return arm_entry.get("mean")


def absolute_arm_errors(records: list[dict], benchmarks: dict) -> dict[tuple, float]:
    """|model arm mean - human arm number| per (model, experiment, blind, arm)."""
    means = arm_means(records)
    errors: dict[tuple, float] = {}
    for (model, experiment, blinding, arm), mean in means.items():
        human = _human_arm_statistic(benchmarks, experiment, arm)
        if human is None:
            continue
        errors[(model, experiment, blinding, arm)] = abs(mean - human)
    return errors


def unblinding_gain(blinded_error: float, unblinded_error: float) -> float:
    """How much unblinding changed the error: blinded minus unblinded.

    Positive means the unblinded arm has LESS error — unblinding helped.
    """
    return blinded_error - unblinded_error


def branch_mass_diagnostics(records: list[dict]) -> dict[tuple, dict[str, float]]:
    """Answer-quality numbers per (model, experiment): mean branch mass and
    the share of records flagged low-branch-mass (diffuse answers)."""
    grouped: dict[tuple, list[dict]] = {}
    for record in records:
        key = (record["model"], record["experiment"])
        grouped.setdefault(key, []).append(record)
    diagnostics: dict[tuple, dict[str, float]] = {}
    for key, group in grouped.items():
        diagnostics[key] = {
            "mean_branch_mass": fmean(r["branch_mass"] for r in group),
            "low_branch_mass_share": (
                sum(1 for r in group if r["low_branch_mass"]) / len(group)
            ),
        }
    return diagnostics


def unblinding_gains_by_contrast(records: list[dict], benchmarks: dict) -> dict[tuple, float]:
    """Per (model, experiment, contrast): the unblinding gain on the
    normalized error, for groups where both blinding arms have data."""
    normalized = normalized_contrast_errors(records, benchmarks)
    gains: dict[tuple, float] = {}
    for model, experiment in {
        (key[0], key[1]) for key in normalized
    }:
        blinded = normalized.get((model, experiment, "blinded"), {})
        unblinded = normalized.get((model, experiment, "unblinded"), {})
        for name in set(blinded) & set(unblinded):
            gains[(model, experiment, name)] = unblinding_gain(
                blinded[name], unblinded[name]
            )
    return gains


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Write one tidy CSV with a header row (small shared writer)."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _contrast_rows(records: list[dict], benchmarks: dict) -> tuple[list[list], list[list], list[list]]:
    """The rows of the contrasts, errors and unblinding-gain CSVs."""
    contrast_rows, error_rows, gain_rows = [], [], []
    for (model, experiment, blinding), by_name in sorted(
            contrast_values(records).items()):
        for name, value in by_name.items():
            contrast_rows.append([model, experiment, blinding, name, value])
    for (model, experiment, blinding), by_name in sorted(
            normalized_contrast_errors(records, benchmarks).items()):
        for name, value in by_name.items():
            error_rows.append([model, experiment, blinding, name, value])
    for (model, experiment, name), gain in sorted(
            unblinding_gains_by_contrast(records, benchmarks).items()):
        gain_rows.append([model, experiment, name, gain])
    return contrast_rows, error_rows, gain_rows


def write_analysis_outputs(records: list[dict], benchmarks: dict, out_dir: Path) -> dict:
    """Write the study's tidy CSVs and summary.json into a folder.

    Produces arm_means.csv, contrasts.csv, errors.csv (absolute and
    normalized), unblinding_gain.csv, branch_mass_diagnostics.csv, and a
    summary.json with record counts and overall mean gains. Returns the
    summary dict it wrote.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    arm_rows = [
        [model, experiment, blinding, arm, mean]
        for (model, experiment, blinding, arm), mean in sorted(
            arm_means(records).items())
    ]
    _write_csv(out_dir / "arm_means.csv",
               ["model", "experiment", "blinding", "arm", "mean"], arm_rows)

    contrast_rows, error_rows, gain_rows = _contrast_rows(records, benchmarks)
    _write_csv(out_dir / "contrasts.csv",
               ["model", "experiment", "blinding", "contrast", "value"],
               contrast_rows)
    _write_csv(out_dir / "errors.csv",
               ["model", "experiment", "blinding", "contrast",
                "normalized_error"], error_rows)
    _write_csv(out_dir / "unblinding_gain.csv",
               ["model", "experiment", "contrast", "gain"], gain_rows)

    diagnostic_rows = [
        [model, experiment, stats["mean_branch_mass"],
         stats["low_branch_mass_share"]]
        for (model, experiment), stats in sorted(
            branch_mass_diagnostics(records).items())
    ]
    _write_csv(out_dir / "branch_mass_diagnostics.csv",
               ["model", "experiment", "mean_branch_mass",
                "low_branch_mass_share"], diagnostic_rows)

    gains = [gain for _model, _experiment, _name, gain in gain_rows]
    summary = {
        "study": config.STUDY_NAME,
        "records": len(records),
        "contrasts": len(contrast_rows),
        "unblinding_gain_rows": len(gain_rows),
        "mean_unblinding_gain": fmean(gains) if gains else None,
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    return summary
