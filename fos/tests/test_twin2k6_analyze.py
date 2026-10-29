# Locked tests for the twin2k6 study's analysis module (TASK-2060 RED
# phase; tests ONLY — no implementation lives here yet).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - Arm means average each scored outcome over the 100 personas per
#     (model, experiment, blinding, arm). Disease uses p_safe_norm (the
#     normalized Program-A share) as its arm statistic — every other
#     experiment uses its expected-value outcome field.
#   - Contrasts subtract arm means with the study's PINNED signs and use
#     the same contrast names as the shipped human benchmarks file
#     (p_safe_loss_minus_gain, B_minus_A, 98pct_minus_all, ...).
#   - Errors are absolute differences against the wave1_3 human numbers;
#     each experiment's error is normalized by its pinned divisor
#     (disease 1, less-is-more 4, fire 4, seatbelt 5, sunk cost 20,
#     WTA/WTP 9).
#   - unblinding_gain = normalized error blinded MINUS unblinded, so a
#     POSITIVE number means unblinding helped (pinned with a worked
#     example).
#   - Branch-mass diagnostics summarize mean branch mass and the share of
#     low-branch-mass records per model x experiment.
#
# All offline: pure functions over synthetic records + the shipped
# benchmarks file; no network, no models.
import json
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import analyze, config, experiments  # noqa: E402


def _benchmarks():
    """Load the shipped human benchmarks file (helper)."""
    with open(config.BENCHMARKS_PATH) as f:
        return json.load(f)


def _outcome_field(exp_name):
    """The experiment's pinned outcome-field name (helper)."""
    return experiments.EXPERIMENTS[exp_name].outcome_field


def _make_record(model, persona_id, exp_name, arm, blind, outcome, branch_mass=1.0, low=False):
    """Build one synthetic analyzed record (identity + scoring fields)."""
    record = {
        "model": model, "persona_id": persona_id, "experiment": exp_name,
        "arm": arm, "blind": blind,
        _outcome_field(exp_name): outcome,
        "branch_mass": branch_mass, "low_branch_mass": low,
    }
    if exp_name == "disease":
        record["p_safe_norm"] = outcome  # disease's arm statistic is p_safe
        record["p_safe_raw"] = outcome
    return record


def _constant_arm(exp_name, model, blind, arm, value, n=100):
    """`n` synthetic personas all reporting the same outcome (helper)."""
    return [
        _make_record(model, pid, exp_name, arm, blind, value)
        for pid in range(n)
    ]


def test_normalization_divisors_are_pinned():
    """disease 1, less-is-more 4, fire 4, seatbelt 5, sunk cost 20, brackets 9."""
    assert analyze.NORMALIZATION == {
        "disease": 1.0,
        "less_is_more": 4.0,
        "fire_extinguisher": 4.0,
        "seatbelt": 5.0,
        "sunk_cost": 20.0,
        "wta_wtp": 9.0,
    }


def test_arm_means_average_over_the_100_personas():
    """An arm's mean is the average of its 100 persona outcomes."""
    records = (
        _constant_arm("sunk_cost", "qwen3-4b", "blinded", "no_card", 15.0, n=60)
        + _constant_arm("sunk_cost", "qwen3-4b", "blinded", "no_card", 10.0, n=40)
    )
    key = ("qwen3-4b", "sunk_cost", "blinded", "no_card")
    assert analyze.arm_means(records)[key] == pytest.approx(0.6 * 15.0 + 0.4 * 10.0)


def test_disease_arm_means_use_p_safe_norm_not_expected_1_6():
    """Disease's arm statistic is the normalized p_safe, even when the
    expected_1_6 field disagrees (primary = normalized-based p_safe)."""
    record = _make_record("qwen3-4b", 0, "disease", "gain", "blinded", 0.9)
    record["expected_1_6"] = 3.0  # decoy that must be ignored
    means = analyze.arm_means([record])
    assert means[("qwen3-4b", "disease", "blinded", "gain")] == pytest.approx(0.9)


def test_contrast_names_match_the_human_benchmarks_file():
    """Every pinned contrast name exists in the shipped wave1_3 benchmarks."""
    benchmarks = _benchmarks()
    for exp_name, spec in experiments.EXPERIMENTS.items():
        human_names = set(benchmarks["waves"]["wave1_3"][exp_name]["contrasts"].keys())
        assert analyze.CONTRASTS[exp_name].keys() == human_names, exp_name


def test_all_contrast_signs_are_pinned():
    """Each contrast is (later-listed arm) minus (earlier-listed arm)."""
    model = "granite-4.1-8b"
    arms = {
        "disease": {"gain": 0.7, "loss": 0.4},
        "less_is_more": {"A": 2.0, "B": 3.0, "C": 4.0},
        "fire_extinguisher": {"all": 4.0, "98pct": 4.25, "95pct": 4.5},
        "seatbelt": {"all": 4.0, "98pct": 4.35, "95pct": 4.36},
        "sunk_cost": {"no_card": 15.0, "card": 10.0},
        "wta_wtp": {"wtp_certainty": 3.0, "wta_certainty": 7.0, "wtp_noncertainty": 2.0},
    }
    expected = {
        "disease": {"p_safe_loss_minus_gain": -0.3},
        "less_is_more": {"B_minus_A": 1.0, "C_minus_A": 2.0},
        "fire_extinguisher": {"98pct_minus_all": 0.25, "95pct_minus_all": 0.5},
        "seatbelt": {"98pct_minus_all": 0.35, "95pct_minus_all": 0.36},
        "sunk_cost": {"card_minus_no_card": -5.0},
        "wta_wtp": {
            "wta_minus_wtp_certainty": 4.0,
            "wtp_noncertainty_minus_wtp_certainty": -1.0,
        },
    }
    records = []
    for exp_name, arm_values in arms.items():
        for arm, value in arm_values.items():
            records += _constant_arm(exp_name, model, "blinded", arm, value, n=2)
    contrasts = analyze.contrast_values(records)
    for exp_name, by_name in expected.items():
        got = contrasts[(model, exp_name, "blinded")]
        for name, value in by_name.items():
            assert got[name] == pytest.approx(value), f"{exp_name}/{name} sign pinned"


def test_absolute_contrast_error_against_wave1_3_human_numbers():
    """Blinded disease example: contrast -0.8 misses the human -0.35581."""
    model = "granite-4.1-8b"
    records = (
        _constant_arm("disease", model, "blinded", "gain", 0.9)
        + _constant_arm("disease", model, "blinded", "loss", 0.1)
    )
    errors = analyze.absolute_contrast_errors(records, _benchmarks())
    assert errors[(model, "disease", "blinded")]["p_safe_loss_minus_gain"] == (
        pytest.approx(0.44419)
    )


def test_absolute_contrast_error_uses_wave1_3_not_wave4():
    """A model matching the wave4 number (not wave1_3) must show error > 0."""
    model = "granite-4.1-8b"
    wave4 = _benchmarks()["waves"]["wave4"]["disease"]["contrasts"]["p_safe_loss_minus_gain"]["value"]
    gain, loss = 0.9, 0.9 + wave4  # model contrast == wave4 contrast exactly
    records = (
        _constant_arm("disease", model, "unblinded", "gain", gain)
        + _constant_arm("disease", model, "unblinded", "loss", loss)
    )
    errors = analyze.absolute_contrast_errors(records, _benchmarks())
    assert errors[(model, "disease", "unblinded")]["p_safe_loss_minus_gain"] > 0


def test_absolute_arm_error_against_wave1_3_human_arms():
    """Arm-level error: |model arm mean - human arm statistic|."""
    model = "granite-4.1-8b"
    records = _constant_arm("disease", model, "blinded", "gain", 0.9)
    errors = analyze.absolute_arm_errors(records, _benchmarks())
    human_gain = _benchmarks()["waves"]["wave1_3"]["disease"]["arms"]["gain"]["p_safe"]
    assert errors[(model, "disease", "blinded", "gain")] == pytest.approx(abs(0.9 - human_gain))


def test_absolute_arm_error_uses_mean_for_non_disease_arms():
    """Sunk cost arms compare the expected_0_20 mean to the human mean."""
    model = "qwen3-4b"
    records = _constant_arm("sunk_cost", model, "unblinded", "card", 12.0)
    errors = analyze.absolute_arm_errors(records, _benchmarks())
    human = _benchmarks()["waves"]["wave1_3"]["sunk_cost"]["arms"]["card"]["mean"]
    assert errors[(model, "sunk_cost", "unblinded", "card")] == pytest.approx(abs(12.0 - human))


def test_sunk_cost_error_is_normalized_by_20():
    """Sunk cost model contrast 10 vs human -4.247694 -> |14.247694| / 20."""
    model = "qwen3-4b"
    records = (
        _constant_arm("sunk_cost", model, "blinded", "no_card", 10.0)
        + _constant_arm("sunk_cost", model, "blinded", "card", 20.0)
    )
    normalized = analyze.normalized_contrast_errors(records, _benchmarks())
    human = _benchmarks()["waves"]["wave1_3"]["sunk_cost"]["contrasts"]["card_minus_no_card"]["value"]
    raw_error = abs(10.0 - human)  # model contrast = 20 - 10 = 10
    assert normalized[(model, "sunk_cost", "blinded")]["card_minus_no_card"] == (
        pytest.approx(raw_error / 20.0)
    )


def test_less_is_more_error_is_normalized_by_4():
    """A B_minus_A contrast of 4.0 vs human 0.833121 -> 0.79171975 normalized."""
    model = "qwen3-4b"
    records = (
        _constant_arm("less_is_more", model, "blinded", "A", 2.0)
        + _constant_arm("less_is_more", model, "blinded", "B", 6.0)
    )
    normalized = analyze.normalized_contrast_errors(records, _benchmarks())
    assert normalized[(model, "less_is_more", "blinded")]["B_minus_A"] == (
        pytest.approx(0.79171975)
    )


def test_unblinding_gain_sign_positive_means_unblinding_helped():
    """Worked example: blinded error 0.5, unblinded 0.2 -> gain +0.3."""
    gain = analyze.unblinding_gain(0.5, 0.2)
    assert gain == pytest.approx(0.3)
    assert gain > 0
    assert analyze.unblinding_gain(0.2, 0.5) == pytest.approx(-0.3)


def test_unblinding_gain_worked_example_on_real_benchmarks():
    """Blinded 0.44419 vs unblinded 0.05581 on the disease contrast."""
    model = "granite-4.1-8b"
    records = (
        _constant_arm("disease", model, "blinded", "gain", 0.9)
        + _constant_arm("disease", model, "blinded", "loss", 0.1)
        + _constant_arm("disease", model, "unblinded", "gain", 0.7)
        + _constant_arm("disease", model, "unblinded", "loss", 0.4)
    )
    normalized = analyze.normalized_contrast_errors(records, _benchmarks())
    blinded = normalized[(model, "disease", "blinded")]["p_safe_loss_minus_gain"]
    unblinded = normalized[(model, "disease", "unblinded")]["p_safe_loss_minus_gain"]
    assert blinded == pytest.approx(0.44419)
    assert unblinded == pytest.approx(0.05581)
    assert analyze.unblinding_gain(blinded, unblinded) == pytest.approx(0.38838)


def test_branch_mass_diagnostics_mean_and_low_share():
    """Diagnostics: mean branch mass and the share flagged low, per pair."""
    records = (
        _constant_arm("disease", "qwen3-4b", "blinded", "gain", 0.9, n=50)
        + _constant_arm("disease", "qwen3-4b", "unblinded", "loss", 0.1, n=50)
    )
    for i, record in enumerate(records):
        record["branch_mass"] = 0.9 if i < 50 else 0.7
        record["low_branch_mass"] = i >= 50
    stats = analyze.branch_mass_diagnostics(records)
    got = stats[("qwen3-4b", "disease")]
    assert got["mean_branch_mass"] == pytest.approx(0.8)
    assert got["low_branch_mass_share"] == pytest.approx(0.5)
