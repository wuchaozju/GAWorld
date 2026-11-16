# Tests for the TASK-2478 FORENSIC orientation repair.
#
# WHAT THIS FILE CHECKS, in plain words:
#   The saved FINAL table may have a bug: when the humans moved in the
#   NEGATIVE direction (human_effect_pp < 0), the stored "oriented" model
#   effect might have been left UN-flipped. This file specifies a fresh
#   forensic module that recomputes everything from only the two raw
#   effects (dh, dm), writes a new CSV, reads it back from disk, checks
#   every recomputed number independently, and re-derives the
#   model-x-experiment mean absolute error that must match the standalone
#   contrast-error table exactly.
#
#   Every test uses small synthetic numbers made up on the spot.
#   No real results file is ever read.
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import forensic as foren  # noqa: E402

# The recomputed columns the forensic table must add.
RECOMPUTED_COLUMNS = [
    "H_recomputed",
    "M_recomputed",
    "R_recomputed",
    "A_recomputed",
    "absR_recomputed",
]

# The ten FORENSIC-named outputs (locked by the tests).
FORENSIC_OUTPUTS = [
    "signed_contrast_effects_FORENSIC.csv",
    "signed_orientation_forensic_check.txt",
    "attenuation_by_task_type_FORENSIC.png",
    "human_effect_recovery_slopes_FORENSIC.png",
    "attenuation_by_model_FORENSIC.png",
    "absolute_error_by_model_FORENSIC.png",
    "response_regime_FORENSIC.png",
    "profile_vs_contrast_FORENSIC.png",
    "taxonomy_comparison_FORENSIC.png",
    "invariance_gap_FORENSIC_REPORT.txt",
]

# The forensic report must end with exactly one of these verdicts.
FORENSIC_VERDICTS = [
    "Robust attenuation mechanism",
    "Suggestive attenuation mechanism",
    "Absolute-error difference only",
    "No reproducible task-type difference",
]


def _raw_effects():
    """A small synthetic table with the two raw effects only.

    Rows deliberately mix positive and negative human effects:
      r1: dh=+40, dm=+30  -> H=40, M=+30, R=-10, A=+10, |R|=10
      r2: dh=-20, dm=+15  -> H=20, M=-15, R=+5,  A=+5,  |R|=5
      r3: dh=-20, dm=-15  -> H=20, M=-15, R=-35, A=+35, |R|=35
      r4: dh=+10, dm=-25  -> H=10, M=-25, R=-35, A=+35, |R|=35
    """
    return pd.DataFrame({
        "model": ["m1", "m1", "m2", "m2"],
        "experiment": ["disease", "linda", "disease", "linda"],
        "contrast": ["c1", "c2", "c1", "c2"],
        "human_effect_pp": [40.0, -20.0, -20.0, 10.0],
        "model_effect_pp": [30.0, 15.0, -15.0, -25.0],
    })


# ---------------------------------------------------------------- contract 1
# Orientation recomputation from the raw effects only.


def test_recompute_adds_all_five_columns():
    """The recompute step must add exactly the five fresh columns."""
    out = foren.recompute_orientation(_raw_effects())
    missing = [c for c in RECOMPUTED_COLUMNS if c not in out.columns]
    assert not missing, f"missing recomputed columns: {missing}"


def test_human_recomputed_is_absolute_human_effect():
    """H = |dh|: negative human effects must come out positive."""
    out = foren.recompute_orientation(_raw_effects())
    lhs = out["H_recomputed"]
    rhs = out["human_effect_pp"].abs()
    assert (lhs - rhs).abs().max() < 1e-10, "H must be exactly |dh|"


def test_model_recomputed_carries_human_sign():
    """M = sign(dh) x dm: a model moving +15 where humans moved -20 must
    be reported as -15, and a model moving -15 where humans moved -20
    stays -15."""
    out = foren.recompute_orientation(_raw_effects())
    assert out.loc[1, "M_recomputed"] == pytest.approx(-15.0, abs=1e-10)
    assert out.loc[2, "M_recomputed"] == pytest.approx(-15.0, abs=1e-10)
    assert out.loc[0, "M_recomputed"] == pytest.approx(30.0, abs=1e-10)


def test_signed_error_is_model_minus_human():
    """R = M - H on the recomputed values."""
    out = foren.recompute_orientation(_raw_effects())
    lhs = out["R_recomputed"]
    rhs = out["M_recomputed"] - out["H_recomputed"]
    assert (lhs - rhs).abs().max() < 1e-10


def test_attenuation_is_human_minus_model():
    """A = H - M, so A = -R exactly."""
    out = foren.recompute_orientation(_raw_effects())
    lhs = out["A_recomputed"]
    rhs = out["H_recomputed"] - out["M_recomputed"]
    assert (lhs - rhs).abs().max() < 1e-10
    assert (out["absR_recomputed"] - out["R_recomputed"].abs()).abs().max() < 1e-10


def test_recompute_ignores_stored_oriented_columns():
    """The recomputation must NOT reuse any existing 'oriented',
    'recovery', or 'attenuation' column. We poison those columns with
    deliberately wrong numbers; the results must not change."""
    df = _raw_effects()
    df["model_effect_oriented_pp"] = [999.0] * len(df)
    df["signed_recovery_error_pp"] = [-888.0] * len(df)
    df["attenuation_pp"] = [777.0] * len(df)
    clean = foren.recompute_orientation(_raw_effects())
    dirty = foren.recompute_orientation(df)
    for col in RECOMPUTED_COLUMNS:
        assert np.allclose(clean[col], dirty[col]), (
            f"{col} was influenced by a stored column it must ignore"
        )


# ---------------------------------------------------------------- contract 2
# Write-then-reload with independent verification.


def test_write_then_reload_roundtrip(tmp_path):
    """Write the forensic CSV, read it back, and get identical numbers."""
    df = foren.recompute_orientation(_raw_effects())
    path = tmp_path / "signed_contrast_effects_FORENSIC.csv"
    foren.write_forensic_csv(df, path)
    assert path.exists(), "the forensic CSV must be written to disk"
    back = foren.load_forensic_csv(path)
    for col in ["human_effect_pp", "model_effect_pp"] + RECOMPUTED_COLUMNS:
        assert np.allclose(df[col], back[col]), f"{col} changed on disk"


def test_verify_passes_on_consistent_table():
    """A table whose stored oriented values match the bug-free rule must
    verify clean (empty failure list)."""
    df = foren.recompute_orientation(_raw_effects())
    df["model_effect_oriented_pp"] = df["M_recomputed"]
    df["human_effect_oriented_pp"] = df["H_recomputed"]
    df["attenuation_pp"] = df["A_recomputed"]
    assert foren.verify_forensic_columns(df) == []


def test_verify_catches_the_unflipped_negative_bug():
    """THE bug: when dh < 0 the stored oriented model effect equals the
    RAW model effect. Verification must flag every such row."""
    df = foren.recompute_orientation(_raw_effects())
    df["model_effect_oriented_pp"] = df["model_effect_pp"]  # the bug
    failures = foren.verify_forensic_columns(df)
    assert failures, "the unflipped negative-dh bug must be caught"
    # the two healthy rows must not be blamed
    assert len(failures) >= 1


def test_verify_respects_tolerance():
    """Differences below 1e-10 must not be flagged."""
    df = foren.recompute_orientation(_raw_effects())
    df["model_effect_oriented_pp"] = df["M_recomputed"] + 1e-12
    assert foren.verify_forensic_columns(df, tol=1e-10) == []


def test_orientation_audit_lists_negative_human_rows():
    """The audit must list every row where the human effect is negative
    (including disease framing) with the raw effect, the expected
    oriented value, the stored value, and the attenuation — so the sign
    flip is visible at a glance."""
    df = foren.recompute_orientation(_raw_effects())
    df["model_effect_oriented_pp"] = df["model_effect_pp"]  # the bug
    rows = foren.orientation_audit_rows(df)
    assert len(rows) == 2, (
        "exactly the two negative-human rows must appear in the audit"
    )
    assert set(rows["experiment"]) == {"disease", "linda"}
    for col in ["human_effect_pp", "model_effect_pp",
                "expected_oriented_pp", "stored_oriented_pp",
                "attenuation_pp"]:
        assert col in rows.columns, f"audit row missing {col}"
    # the sign flip must be visible: expected is negative where stored is not
    assert (rows["expected_oriented_pp"] < 0).all()
    assert (rows["stored_oriented_pp"] > 0).all()


# ---------------------------------------------------------------- contract 3
# Reproduce the standalone contrast-error aggregation.


def _contrast_error_table(df):
    """A standalone table of per model-x-experiment mean |R|."""
    agg = (
        df.groupby(["model", "experiment"], as_index=False)["absR_recomputed"]
        .mean()
        .rename(columns={"absR_recomputed": "contrast_error"})
    )
    return agg


def test_reproduction_matches_within_tolerance():
    """The forensic aggregation must reproduce the standalone table to
    better than 1e-8 with zero mismatched cells."""
    df = foren.recompute_orientation(_raw_effects())
    table = _contrast_error_table(df)
    mismatched, worst = foren.reproduce_contrast_error(df, table)
    assert mismatched == 0, "no cell may mismatch"
    assert worst < 1e-8, f"max discrepancy {worst} exceeds 1e-8"


def test_reproduction_flags_a_perturbed_table():
    """If the standalone table disagrees, the mismatch must be reported,
    not swallowed."""
    df = foren.recompute_orientation(_raw_effects())
    table = _contrast_error_table(df)
    table.loc[0, "contrast_error"] += 1.0
    mismatched, worst = foren.reproduce_contrast_error(df, table)
    assert mismatched >= 1, "a perturbed cell must be counted as mismatched"
    assert worst >= 1.0


# ---------------------------------------------------------------- contract 4
# Output names, report verdicts, CLI entry point.


def test_forensic_output_names_are_locked():
    """The module must declare exactly the ten FORENSIC-named outputs."""
    assert foren.FORENSIC_OUTPUTS == FORENSIC_OUTPUTS


def test_report_verdicts_are_exactly_four():
    """The report must end with exactly one of four fixed verdicts."""
    assert foren.FORENSIC_VERDICTS == FORENSIC_VERDICTS


def test_module_has_cli_entry_point():
    """The module must expose a CLI entry (main) so it can run stand-alone."""
    assert callable(foren.main), "forensic.py must expose a callable main()"
