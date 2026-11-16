# Tests for the TASK-2436 fix: contrast feature effects must not come out
# all-NaN when the contrast error file is experiment-level (its "contrast"
# key is just the experiment name) while the contrast codebook uses real
# contrast-level keys. Each test has a plain-language name saying what it
# checks.

import pandas as pd
import pytest

from twin2k10.task_difficulty import feature_effects


def _experiment_level_contrast_errors() -> pd.DataFrame:
    """Error rows keyed by experiment only (no real contrast column)."""
    rows = []
    errors = {"disease": 10.0, "linda": 2.0, "myside": 8.0, "allais": 1.0}
    for experiment, error in errors.items():
        for model in ["m1", "m2"]:
            rows.append({"model": model, "experiment": experiment,
                         "error": error + 0.1 * (model == "m2")})
    return pd.DataFrame(rows).assign(
        contrast=lambda df: df["experiment"])


def _contrast_level_contrast_errors() -> pd.DataFrame:
    """Error rows keyed by real contrast names (the healthy path)."""
    rows = []
    errors = {"con_one": 10.0, "con_two": 2.0}
    for contrast, error in errors.items():
        for model in ["m1", "m2"]:
            rows.append({"model": model, "experiment": "exp",
                         "contrast": contrast, "error": error})
    return pd.DataFrame(rows)


def _contrast_codebook(experiment_level: bool) -> pd.DataFrame:
    """Codebook mapping contrasts (and their experiments) to codings."""
    if experiment_level:
        return pd.DataFrame({
            "contrast": ["con_disease", "con_linda", "con_myside",
                         "con_allais"],
            "experiment": ["disease", "linda", "myside", "allais"],
            "objective_equivalence": [1, 1, 0, 0],
        })
    return pd.DataFrame({
        "contrast": ["con_one", "con_two"],
        "experiment": ["exp", "exp"],
        "objective_equivalence": [1, 0],
    })


@pytest.mark.parametrize("experiment_level", [True, False])
def test_contrast_effects_are_numeric_when_error_keys_differ_from_codebook_keys(
    experiment_level: bool,
) -> None:
    """Feature effects on the contrast outcome must be real numbers, both
    when errors are experiment-level and when they are contrast-level."""
    if experiment_level:
        contrast = _experiment_level_contrast_errors()
    else:
        contrast = _contrast_level_contrast_errors()
    codebook = _contrast_codebook(experiment_level)
    profile = pd.DataFrame({
        "model": ["m1"], "experiment": ["disease"], "error": [5.0]})
    human = pd.DataFrame({"experiment": ["disease"], "human_error": [1.0]})
    result = feature_effects(
        profile_errors=profile, contrast_errors=contrast,
        experiment_codebook=codebook, contrast_codebook=codebook,
        human_retest=human, feature="objective_equivalence",
        outcome="contrast", n_boot=50, seed=1)
    assert result["delta"].notna().all(), result.to_dict("records")
    assert result["ci_low"].notna().all()
    assert result["ci_high"].notna().all()
