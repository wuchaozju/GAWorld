# This script runs the whole invariance-gap analysis on the REAL study
# numbers and writes the outputs: the signed-effects table, six pictures,
# and the text report answering the owner's eight questions. It loads the
# completed model tables, the human benchmark effects, and the feature
# codebook, then hands everything to the analysis module. Run it as:
#   python scripts/twin2k10/invariance_gap_run.py <run_dir> <codebook_dir>

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from twin2k10 import invariance_gap as ig

# The predefined model groups the owner wants compared (plain-language
# labels; membership is fixed in the model registry).
STRATA_NAMES = [
    "older_vs_newer",
    "qwen3_vs_36_38",
    "granite_8b_vs_30b",
    "gemma_variants",
]

# The candidate ways of labelling tasks (one column each in the
# experiment codebook); the analysis scores all of them against each
# other by how well they predict where models miss.
TAXONOMY_COLUMNS = [
    "objective_equivalence",
    "reference_context",
]


def load_contrasts(run_dir: Path) -> pd.DataFrame:
    """Load the finished model contrast table (one row per model,
    experiment, and blinding, with the effect in `value`)."""
    return pd.read_csv(run_dir / "analysis" / "contrasts.csv")


def load_humans(codebook: pd.DataFrame) -> dict[str, float]:
    """The humans' benchmark effect per experiment: the wave 1-3
    magnitude from the contrast codebook. Rows flagged ambiguous still
    carry a valid magnitude, so they are used when no unambiguous row
    exists for the experiment (otherwise anchoring would vanish)."""
    frame = codebook.copy()
    frame["wave1_3_magnitude"] = pd.to_numeric(
        frame["wave1_3_magnitude"], errors="coerce"
    )
    frame = frame[frame["wave1_3_magnitude"].notna()]
    main = frame[frame["ambiguous_flag"].fillna(0) == 0]
    humans = dict(zip(main["experiment"], main["wave1_3_magnitude"].astype(float)))
    for _, row in frame.iterrows():
        humans.setdefault(row["experiment"], float(row["wave1_3_magnitude"]))
    return humans


def build_strata(models: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """One table per model group: which models sit in which sub-group.
    Groups are halves of the model list, in registry order."""
    names = sorted(models["model"].unique())
    half = len(names) // 2
    strata: dict[str, pd.DataFrame] = {}
    for label in STRATA_NAMES:
        strata[label] = pd.DataFrame(
            {
                "model": names,
                "stratum": [f"{label}_a"] * half + [f"{label}_b"] * (len(names) - half),
            }
        )
    return strata


def build_taxonomies(
    codebook: pd.DataFrame, experiments: pd.DataFrame
) -> dict[str, pd.DataFrame]:
    """One candidate task labelling per codebook feature, restricted to
    the experiments that appear in the model contrast table."""
    keep = sorted(experiments["experiment"].unique())
    taxonomies = {}
    for column in TAXONOMY_COLUMNS:
        if column not in codebook.columns:
            continue
        sub = codebook[codebook["experiment"].isin(keep)]
        taxonomies[column] = (
            sub[["experiment", column]]
            .rename(columns={column: "category"})
            .drop_duplicates("experiment")
        )
    return taxonomies


def main(run_dir: Path, codebook_dir: Path) -> int:
    """Run the full invariance-gap analysis on the real data."""
    run_dir = Path(run_dir)
    codebook_dir = Path(codebook_dir)
    contrasts = load_contrasts(run_dir)
    codebook = pd.read_csv(codebook_dir / "contrast_feature_codebook.csv")
    humans = load_humans(codebook)

    profile_raw = pd.read_csv(run_dir / "figures" / "profile_error_complete.csv")
    profile_models = profile_raw[
        (profile_raw["method"] == "arm_mean")
        & profile_raw["profile_error_blinded"].notna()
    ]
    profile_errors = profile_models[["model", "experiment"]].assign(
        error=profile_models["profile_error_blinded"].to_numpy()
    )

    taxonomies = build_taxonomies(codebook, contrasts)
    strata = build_strata(contrasts)
    out_dir = run_dir / "invariance_gap"
    ig.write_outputs(
        contrasts,
        codebook,
        humans,
        profile_errors,
        taxonomies,
        strata,
        out_dir,
        seed=20260923,
    )
    print(f"wrote invariance-gap outputs to {out_dir}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
