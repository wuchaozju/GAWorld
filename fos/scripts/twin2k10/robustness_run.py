# This script runs the whole objective-equivalence robustness battery on
# the REAL study numbers and writes the outputs: the combined CSV table,
# four pictures, and the text report. It loads the completed error tables
# and the feature codebooks, reshapes them into the tidy form the
# battery expects, runs every check, and prints the headline table plus
# the final verdict. Run it as:
#   python scripts/twin2k10/robustness_run.py <run_dir> <codebook_dir>

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from twin2k10.robustness import (
    build_robustness_table,
    make_figures,
    permutation_calibration,
    shared_difficulty_robustness,
    validation_report,
    write_report,
    write_robustness_csv,
)

# Paradigm families for the real experiments, with the plain-language
# reason each group belongs together.
REAL_FAMILIES: dict[str, list[str]] = {
    "anchoring": ["anchoring_redwood", "anchoring_african"],
    "proportion_dominance": ["fire_extinguisher", "seatbelt"],
    "valuation_reference": ["wta_wtp", "sunk_cost"],
    "probability_risk": ["allais", "base_rate", "prob_matching"],
    "judgment_inference": ["linda", "myside", "outcome_bias"],
    "framing_reference": ["disease", "less_is_more", "abs_relative"],
    "social_consensus": ["false_consensus"],
}


def load_profile_errors(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split the completed profile table into model errors (the blinded
    arm-mean column) and the human test-retest rows."""
    raw = pd.read_csv(run_dir / "figures" / "profile_error_complete.csv")
    models = raw[
        (raw["method"] == "arm_mean") & raw["profile_error_blinded"].notna()
    ].copy()
    models["error"] = models["profile_error_blinded"]
    human = raw[raw["model"].str.upper() == "HUMAN"].copy()
    human["human_error"] = human["profile_error_unblinded"]
    human = human[["experiment", "human_error"]].dropna()
    return models[["model", "experiment", "error"]], human


def load_contrast_errors(run_dir: Path) -> pd.DataFrame:
    """The completed contrast table is already tidy; rename its error
    column so the battery can read it."""
    raw = pd.read_csv(run_dir / "figures" / "contrast_error_complete.csv")
    raw = raw[raw["model"].str.upper() != "HUMAN"]
    return raw[["model", "experiment", "contrast_error"]].rename(
        columns={"contrast_error": "error"}
    )


def load_codebooks(codebook_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the experiment and contrast feature codebooks."""
    experiment = pd.read_csv(codebook_dir / "experiment_feature_codebook.csv")
    contrast = pd.read_csv(codebook_dir / "contrast_feature_codebook.csv")
    return experiment, contrast


def main(run_dir: Path, codebook_dir: Path) -> int:
    """Run the full battery on the real data and write every output."""
    profile_errors, human_retest = load_profile_errors(run_dir)
    contrast_errors = load_contrast_errors(run_dir)
    experiment_codebook, contrast_codebook = load_codebooks(codebook_dir)
    out_dir = run_dir / "robustness"
    out_dir.mkdir(parents=True, exist_ok=True)

    report = validation_report(
        profile_errors,
        contrast_errors,
        human_retest,
        experiment_codebook=experiment_codebook,
    )
    if (report["status"] == "FAIL").any():
        print(report.to_string(index=False))
        raise SystemExit("bug audit failed — fix inputs before the battery")

    table = build_robustness_table(
        profile_errors,
        contrast_errors,
        experiment_codebook,
        contrast_codebook,
        human_retest,
        REAL_FAMILIES,
        n_boot=1000,
        seed=2426,
    )
    write_robustness_csv(table, out_dir / "objective_equivalence_robustness.csv")
    make_figures(table, profile_errors, REAL_FAMILIES, out_dir=out_dir)
    report_path = out_dir / "objective_equivalence_robustness_report.txt"
    write_report(table, report_path)

    extra = shared_difficulty_robustness(profile_errors, n_boot=1000, seed=2426)
    perm = permutation_calibration(
        profile_errors, experiment_codebook, n_draws=2000, seed=2426
    )
    profile = table[table["outcome"] == "profile"]
    print(
        profile[["specification", "estimate_pp", "ci_low", "ci_high"]].to_string(
            index=False
        )
    )
    print(
        f"\nKendall W = {extra['kendall_w']:.3f} "
        f"[{extra['kendall_w_ci_low']:.3f}, {extra['kendall_w_ci_high']:.3f}], "
        f"LOO range [{extra['kendall_w_loo_min']:.3f}, "
        f"{extra['kendall_w_loo_max']:.3f}]"
    )
    print(
        f"Permutation null: median |delta| = {perm['median_abs_null_pp']:.2f} pp, "
        f"95th pct = {perm['pct95_abs_null_pp']:.2f} pp, "
        f"observed = {perm['observed_abs_pp']:.2f} pp"
    )
    print("\n" + report_path.read_text().splitlines()[-1])
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: robustness_run.py <run_dir> <codebook_dir>")
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
