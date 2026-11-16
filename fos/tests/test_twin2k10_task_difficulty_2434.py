# Test for the EMPTY-GROUP fix in task_difficulty.py (TASK-2434).
#
# WHAT THIS FILE CHECKS, in plain words:
#   When a feature group has no "on" or no "off" experiments left after
#   excluding mixed / ambiguous codings, the analysis must NOT crash.
#   Instead it must return one row that says "no data" with blank
#   statistics, so the rest of the pipeline can keep going.
#
# Everything runs offline on small fake numbers written here in the test
# file. No real run directory or real codebook is read.
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import task_difficulty as td  # noqa: E402

MODELS = ["m1", "m2", "m3", "m4", "m5", "m6"]
EXPERIMENTS = ["disease", "seatbelt", "sunk_cost", "myside"]


def _error_frame(seed: int = 0) -> pd.DataFrame:
    """A tidy model/experiment/error table of fake numbers."""
    rng = np.random.default_rng(seed)
    base = {"disease": 20.0, "seatbelt": 10.0, "sunk_cost": 5.0, "myside": 1.0}
    rows = []
    for m_i, model in enumerate(MODELS):
        for exp in EXPERIMENTS:
            err = base[exp] + 0.5 * m_i + rng.normal(0, 0.1)
            rows.append({"model": model, "experiment": exp, "error": err})
    return pd.DataFrame(rows)


def _human_retest() -> pd.DataFrame:
    """Per-experiment human test-retest errors (the noise floor)."""
    return pd.DataFrame(
        {"experiment": EXPERIMENTS, "human_error": [0.5, 0.4, 0.3, 0.2]}
    )


def _codebook_empty_on_group() -> pd.DataFrame:
    """A codebook where 'objective_equivalence' is 'mixed' for every
    experiment that would be "on" — so after exclusions the "on" group
    is empty and nothing is estimable."""
    return pd.DataFrame(
        {
            "experiment": EXPERIMENTS,
            "objective_equivalence": ["mixed", 0, 0, 0],
            "reference_context": [1, 1, 0, 0],
        }
    )


def test_empty_feature_group_returns_no_data_row_instead_of_crashing():
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=_codebook_empty_on_group(),
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=1,
    )
    assert len(out) == 1
    row = out.iloc[0]
    assert row["estimate_status"] == "no_data"
    assert pd.isna(row["delta"])
    assert pd.isna(row["ci_low"])
    assert pd.isna(row["ci_high"])


def test_empty_group_row_keeps_output_columns():
    out = td.feature_effects(
        profile_errors=_error_frame(),
        contrast_errors=None,
        experiment_codebook=_codebook_empty_on_group(),
        contrast_codebook=None,
        human_retest=_human_retest(),
        feature="objective_equivalence",
        outcome="profile",
        n_boot=200,
        seed=1,
    )
    assert list(out.columns) == [
        "feature", "outcome", "d_e", "delta", "ci_low", "ci_high",
        "ci_method", "loo_min_delta", "loo_max_delta", "sign_stable",
        "estimate_status",
    ]
