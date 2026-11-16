# Tests for the TASK-2452 NaN fixes in the invariance-gap analysis.
#
# WHAT THIS FILE CHECKS, in plain words:
#   The real-data run produced "nan" penalties because (a) a codebook row
#   whose task-type label is the text "ambiguous/NA" turned the whole
#   label column into text, so every comparison against 0 or 1 found
#   nothing; (b) the human benchmark table left out the anchoring
#   experiments (their rows are flagged ambiguous), so all anchoring
#   model rows were silently dropped by the join; (c) the codebook join
#   used the contrast name alone, which is ambiguous when two experiments
#   reuse the same contrast name (duplicate rows).
#
#   Each test reproduces one of those failures on small fake data.
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import invariance_gap as ig  # noqa: E402
from twin2k10 import invariance_gap_run as run  # noqa: E402


def test_ambiguous_text_label_does_not_poison_objective_equivalence():
    """A codebook row with the text 'ambiguous/NA' as its task-type label
    must not stop the numeric rows from being grouped."""
    contrasts = pd.DataFrame(
        {
            "model": ["m1", "m1"],
            "experiment": ["base_rate", "outcome_bias"],
            "contrast": ["mean_70_minus_30", "mean_success_minus_failure"],
            "blinding": ["blinded", "blinded"],
            "value": [10.0, 0.4],
        }
    )
    codebook = pd.DataFrame(
        {
            "contrast": ["mean_70_minus_30", "mean_success_minus_failure"],
            "experiment": ["base_rate", "outcome_bias"],
            "objective_equivalence": ["0", "ambiguous/NA"],
            "reference_context": [0, 0],
        }
    )
    humans = {"base_rate": 15.0, "outcome_bias": 0.5}
    effects = ig.build_signed_effects(contrasts, codebook, humans)
    assert effects["objective_equivalence"].dtype.kind in "if", (
        "objective_equivalence must be numeric even when one codebook row "
        "says 'ambiguous/NA'"
    )
    non_oe = effects[effects["objective_equivalence"] == 0]
    assert len(non_oe) == 1, "the numeric 0 row must still be findable after the join"
    oe = effects[effects["objective_equivalence"] == 1]
    assert oe.empty, "the ambiguous row must sit outside both groups"


def test_ambiguous_labelled_cell_stays_explicitly_missing_not_zero():
    """The row whose task-type label is unavailable keeps a real missing
    marker (not a 0 that would silently join the framing-only group)."""
    contrasts = pd.DataFrame(
        {
            "model": ["m1"],
            "experiment": ["outcome_bias"],
            "contrast": ["mean_success_minus_failure"],
            "blinding": ["blinded"],
            "value": [0.4],
        }
    )
    codebook = pd.DataFrame(
        {
            "contrast": ["mean_success_minus_failure"],
            "experiment": ["outcome_bias"],
            "objective_equivalence": ["ambiguous/NA"],
            "reference_context": [0],
        }
    )
    effects = ig.build_signed_effects(contrasts, codebook, {"outcome_bias": 0.5})
    cell = effects["objective_equivalence"].iloc[0]
    assert pd.isna(cell), "the ambiguous label must become an explicit NA"


def test_anchoring_rows_survive_the_human_benchmark_join():
    """Anchoring experiments are flagged ambiguous in the codebook but do
    have human magnitudes; their model rows must not be dropped."""
    codebook = pd.DataFrame(
        {
            "contrast": [
                "mean_high_minus_low",
                "mean_high_minus_low",
                "mean_70_minus_30",
            ],
            "experiment": ["anchoring_redwood", "anchoring_african", "base_rate"],
            "ambiguous_flag": [1, 1, 0],
            "wave1_3_magnitude": [592.9, 21.8, 15.8],
            "objective_equivalence": [1, 1, 0],
            "reference_context": [1, 1, 0],
        }
    )
    humans = run.load_humans(codebook)
    for experiment in ("anchoring_redwood", "anchoring_african", "base_rate"):
        assert experiment in humans, (
            f"{experiment} has a human magnitude in the codebook; the "
            "humans join must not lose it"
        )
    assert humans["anchoring_redwood"] == 592.9


def test_codebook_join_uses_experiment_and_contrast_together():
    """Two experiments reusing one contrast name must not cross-match:
    the join key is (experiment, contrast), so no duplicate rows appear."""
    contrasts = pd.DataFrame(
        {
            "model": ["m1", "m1"],
            "experiment": ["fire_extinguisher", "seatbelt"],
            "contrast": ["98pct_minus_all", "98pct_minus_all"],
            "blinding": ["blinded", "blinded"],
            "value": [0.2, 0.3],
        }
    )
    codebook = pd.DataFrame(
        {
            "contrast": ["98pct_minus_all", "98pct_minus_all"],
            "experiment": ["fire_extinguisher", "seatbelt"],
            "objective_equivalence": [0, 0],
            "reference_context": [1, 1],
        }
    )
    humans = {"fire_extinguisher": 0.25, "seatbelt": 0.35}
    effects = ig.build_signed_effects(contrasts, codebook, humans)
    assert len(effects) == 2, (
        "one row per (model, experiment, contrast); a shared contrast "
        "name must not duplicate rows"
    )


def test_strata_penalties_compute_with_mixed_label_column():
    """End-to-end: strata penalties must be real numbers, not nan, when
    one experiment's label is 'ambiguous/NA' and anchoring rows exist."""
    rng = np.random.default_rng(0)
    rows = []
    codebook_rows = []
    humans = {}
    for experiment, oe, magnitude in [
        ("anchoring_redwood", 1, 592.9),
        ("anchoring_african", 1, 21.8),
        ("base_rate", 0, 15.8),
        ("prob_matching", 0, 0.01),
        ("outcome_bias", "ambiguous/NA", 0.78),
    ]:
        humans[experiment] = magnitude
        codebook_rows.append(
            {
                "contrast": f"c_{experiment}",
                "experiment": experiment,
                "objective_equivalence": (str(oe) if not isinstance(oe, str) else oe),
                "reference_context": 0,
            }
        )
        for model in ("m1", "m2", "m3"):
            value = magnitude * (0.6 if oe == 0 else 1.0)
            rows.append(
                {
                    "model": model,
                    "experiment": experiment,
                    "contrast": f"c_{experiment}",
                    "blinding": "blinded",
                    "value": value,
                }
            )
    effects = ig.build_signed_effects(
        pd.DataFrame(rows), pd.DataFrame(codebook_rows), humans
    )
    strata = {
        "half": pd.DataFrame(
            {
                "model": ["m1", "m2", "m3"],
                "stratum": ["a", "a", "b"],
            }
        )
    }
    penalties = ig.strata_penalties(effects, strata, rng, n_boot=5)
    assert penalties["penalty"].notna().all(), (
        "every estimable stratum penalty must be a number, not nan"
    )


def test_every_stratum_group_has_a_comparison_half():
    """Each predefined model group must split the models into two
    non-empty strata, so a penalty versus the other half can be computed
    (a single all-model stratum has no 'outside' and turns into nan)."""
    models = pd.DataFrame(
        {
            "model": [f"m{i}" for i in range(6)],
        }
    )
    strata = run.build_strata(models)
    assert set(strata) >= {
        "qwen3_vs_36_38",
        "granite_8b_vs_30b",
        "gemma_variants",
        "older_vs_newer",
    }
    for label, mapping in strata.items():
        sizes = mapping["stratum"].value_counts()
        assert len(sizes) >= 2, f"{label} must have at least two strata to compare"
        assert sizes.min() > 0, f"{label} has an empty stratum"
