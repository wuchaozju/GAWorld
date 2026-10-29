# Offline tests for the twin2k6 analysis OUTPUT files (TASK-2072 RED
# phase; tests ONLY — no implementation lives here).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - write_analysis_outputs must turn scored records into five tidy CSVs
#     (arm means, contrasts, errors, unblinding gain, branch-mass
#     diagnostics) plus a summary.json — WITHOUT crashing when
#     unblinding-gain rows exist (the locked 79 tests never exercised
#     that path; this file does).
#   - The unblinding_gain.csv numbers are checked against hand-computed
#     expectations, with both signs present: five experiments have their
#     blinded arms sitting exactly on the human wave1_3 numbers (error 0)
#     and simple shifted unblinded arms (error > 0), so their gains are
#     NEGATIVE; wta_wtp is mirrored, so its gains are POSITIVE.
#   - arm_means.csv and contrasts.csv are checked cell-by-cell for one
#     whole experiment (sunk cost), so a fix that silently writes empty
#     files cannot pass.
#
# All offline: pure synthetic records + the shipped benchmarks file; no
# network, no models.
import csv
import json
import sys
from pathlib import Path
from statistics import fmean

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import analyze, config, experiments  # noqa: E402

# Two real registry models; both get the identical synthetic answers so
# every expected number below holds for each of them.
MODELS = ("granite-4.1-8b", "qwen3-4b")

# Every (model, experiment, blinding, arm) group gets 3 personas — enough
# to be a real group, few enough to keep the files small.
PERSONAS_PER_ARM = 3

# (experiment, arm) -> outcome per blinding condition.
# Blinded outcomes sit EXACTLY on the human wave1_3 arm numbers for every
# experiment except wta_wtp, so their contrast errors are zero; unblinded
# outcomes sit on hand-picked simple numbers so each contrast misses its
# human contrast by an amount a person can check with a calculator.
# wta_wtp is the mirror image: blinded shifted, unblinded on the human
# numbers — which makes wta_wtp's gains positive while the rest are
# negative. Numbers are the shipped research-delivery benchmarks, which
# must never be edited.
ARM_OUTCOMES: dict[tuple[str, str], dict[str, float]] = {
    ("disease", "gain"): {"blinded": 0.718843, "unblinded": 0.7},
    ("disease", "loss"): {"blinded": 0.363033, "unblinded": 0.4},
    ("less_is_more", "A"): {"blinded": 2.061224, "unblinded": 2.0},
    ("less_is_more", "B"): {"blinded": 2.894345, "unblinded": 6.0},
    ("less_is_more", "C"): {"blinded": 2.863287, "unblinded": 3.0},
    ("fire_extinguisher", "all"): {"blinded": 4.028571, "unblinded": 2.0},
    ("fire_extinguisher", "98pct"): {"blinded": 4.285714, "unblinded": 2.25},
    ("fire_extinguisher", "95pct"): {"blinded": 4.296467, "unblinded": 2.5},
    ("seatbelt", "all"): {"blinded": 4.314286, "unblinded": 4.0},
    ("seatbelt", "98pct"): {"blinded": 4.668155, "unblinded": 4.35},
    ("seatbelt", "95pct"): {"blinded": 4.671275, "unblinded": 4.36},
    ("sunk_cost", "no_card"): {"blinded": 14.884058, "unblinded": 10.0},
    ("sunk_cost", "card"): {"blinded": 10.636364, "unblinded": 20.0},
    ("wta_wtp", "wtp_certainty"): {"blinded": 3.0, "unblinded": 3.265449},
    ("wta_wtp", "wta_certainty"): {"blinded": 7.0, "unblinded": 6.824666},
    ("wta_wtp", "wtp_noncertainty"): {"blinded": 2.0, "unblinded": 2.203566},
}

# The hand-computed unblinding gain per (experiment, contrast name):
# gain = normalized_error(blinded) - normalized_error(unblinded), where a
# POSITIVE number means unblinding helped. Worked example (disease): the
# blinded arms match the human contrast -0.35581 exactly (error 0); the
# unblinded contrast is 0.4 - 0.7 = -0.3, missing the human number by
# 0.05581, so the gain is 0 - 0.05581 = -0.05581. wta_wtp's first
# contrast: blinded 7.0 - 3.0 = 4.0 misses the human 3.559216 by
# 0.440784; its unblinded arms ARE the human arms, so the gain is
# +0.440784 / 9. (Written as formulas over the shipped human contrast
# numbers where the shipped file rounds its own arm means, so the
# expectation cannot drift from the data file.)
_WTA_HUMAN_WTA_MINUS_WTP = 3.559216
_WTA_HUMAN_NONCERT_MINUS_CERT = -1.061883
EXPECTED_GAINS: dict[tuple[str, str], float] = {
    ("disease", "p_safe_loss_minus_gain"): -0.05581,
    ("less_is_more", "B_minus_A"): -(4.0 - 0.833121) / 4.0,
    ("less_is_more", "C_minus_A"): -(1.0 - 0.802063) / 4.0,
    ("fire_extinguisher", "98pct_minus_all"): -(0.257143 - 0.25) / 4.0,
    ("fire_extinguisher", "95pct_minus_all"): -(0.5 - 0.267896) / 4.0,
    ("seatbelt", "98pct_minus_all"): -(0.353869 - 0.35) / 5.0,
    ("seatbelt", "95pct_minus_all"): -(0.36 - 0.356989) / 5.0,
    ("sunk_cost", "card_minus_no_card"): -(10.0 - -4.247694) / 20.0,
    ("wta_wtp", "wta_minus_wtp_certainty"):
        (4.0 - _WTA_HUMAN_WTA_MINUS_WTP
         - abs((6.824666 - 3.265449) - _WTA_HUMAN_WTA_MINUS_WTP)) / 9.0,
    ("wta_wtp", "wtp_noncertainty_minus_wtp_certainty"):
        (-1.0 - _WTA_HUMAN_NONCERT_MINUS_CERT
         - abs((2.203566 - 3.265449) - _WTA_HUMAN_NONCERT_MINUS_CERT)) / 9.0,
}


def _benchmarks() -> dict:
    """Load the shipped human benchmarks file (helper)."""
    with open(config.BENCHMARKS_PATH) as f:
        return json.load(f)


def _outcome_field(exp_name: str) -> str:
    """The experiment's pinned outcome-field name (helper)."""
    return experiments.EXPERIMENTS[exp_name].outcome_field


def _make_record(model: str, persona_id: int, exp_name: str, arm: str,
                 blind: str, outcome: float, branch_mass: float,
                 low: bool) -> dict:
    """Build one synthetic analyzed record (identity + scoring fields),
    mirroring the schema the analysis module's inputs carry."""
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


def _synthetic_records() -> list[dict]:
    """The full offline mini-study: 2 models x 6 experiments x every arm x
    both blinding conditions x 3 personas (192 records). Persona ids do
    not collide inside a (model, experiment, blinding) group — each arm
    gets its own block of the persona pool, like the real run. Blinded
    records carry branch mass 0.9 flagged low; unblinded 0.7 not flagged,
    so the diagnostics file has hand-checkable numbers too."""
    records: list[dict] = []
    arms_by_experiment: dict[str, list[str]] = {}
    for (exp_name, arm), outcomes in ARM_OUTCOMES.items():
        arms_by_experiment.setdefault(exp_name, []).append(arm)
    for model in MODELS:
        for exp_name, arms in arms_by_experiment.items():
            for arm_index, arm in enumerate(arms):
                for blind in ("blinded", "unblinded"):
                    outcome = ARM_OUTCOMES[(exp_name, arm)][blind]
                    low = blind == "blinded"
                    mass = 0.9 if low else 0.7
                    for persona in range(PERSONAS_PER_ARM):
                        records.append(_make_record(
                            model,
                            persona_id=100 * arm_index + persona,
                            exp_name=exp_name, arm=arm, blind=blind,
                            outcome=outcome, branch_mass=mass, low=low,
                        ))
    return records


def _run_write(tmp_path: Path) -> tuple[dict, Path]:
    """Build the synthetic records, run write_analysis_outputs into a
    fresh folder, and return (summary dict, output folder)."""
    out_dir = tmp_path / "analysis_out"
    summary = analyze.write_analysis_outputs(
        _synthetic_records(), _benchmarks(), out_dir)
    return summary, out_dir


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Read one tidy CSV into (header, rows-as-dicts) (helper)."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        return header, [dict(zip(header, row)) for row in reader]


def test_write_outputs_produces_all_files_without_crashing_when_gain_rows_exist(
        tmp_path: Path):
    """The writer must emit all 5 tidy CSVs + summary.json and not crash
    when unblinding-gain rows exist (it used to unpack 2 of 4 columns)."""
    summary, out_dir = _run_write(tmp_path)
    for name in ("arm_means.csv", "contrasts.csv", "errors.csv",
                 "unblinding_gain.csv", "branch_mass_diagnostics.csv",
                 "summary.json"):
        assert (out_dir / name).exists(), f"missing output file {name}"
    assert summary["unblinding_gain_rows"] > 0, (
        "this scenario must actually produce unblinding-gain rows")


def test_unblinding_gain_file_has_exact_signed_hand_computed_values(
        tmp_path: Path):
    """Every gain cell equals the hand-computed value, with both signs
    present (negative when unblinding hurt, positive when it helped)."""
    _summary, out_dir = _run_write(tmp_path)
    header, rows = _read_csv(out_dir / "unblinding_gain.csv")
    assert header == ["model", "experiment", "contrast", "gain"], header
    assert len(rows) == 2 * len(EXPECTED_GAINS), (
        f"expected one gain row per model per contrast, got {len(rows)}")
    gains = {
        (row["model"], row["experiment"], row["contrast"]): float(row["gain"])
        for row in rows
    }
    expected = {
        (model, experiment, contrast): value
        for model in MODELS
        for (experiment, contrast), value in EXPECTED_GAINS.items()
    }
    assert gains.keys() == expected.keys()
    for key, want in expected.items():
        assert gains[key] == pytest.approx(want), f"gain {key}"
    assert any(value > 0 for value in gains.values()), (
        "wta_wtp's blinded arms miss the human numbers, so at least one "
        "gain must be positive")
    assert any(value < 0 for value in gains.values()), (
        "the five benchmark-matching experiments must show negative gains")


def test_errors_file_holds_the_worked_example_disease_numbers(tmp_path: Path):
    """The errors.csv disease rows: blinded error 0 (arms match the human
    numbers), unblinded error 0.05581 (contrast -0.3 vs human -0.35581)."""
    _summary, out_dir = _run_write(tmp_path)
    _header, rows = _read_csv(out_dir / "errors.csv")
    assert len(rows) == len(MODELS) * 2 * len(EXPECTED_GAINS), (
        "one normalized-error row per model per blinding per contrast")
    disease = {
        (row["model"], row["blinding"]): float(row["normalized_error"])
        for row in rows if row["experiment"] == "disease"
    }
    assert len(disease) == 2 * len(MODELS)
    for model in MODELS:
        assert disease[(model, "blinded")] == pytest.approx(0.0), (
            "blinded disease arms sit exactly on the human numbers")
        assert disease[(model, "unblinded")] == pytest.approx(0.05581), (
            "unblinded disease contrast -0.3 misses the human -0.35581")


def test_arm_means_file_matches_hand_computed_sunk_cost_means(tmp_path: Path):
    """All 8 sunk-cost cells (2 models x 2 blindings x 2 arms) equal the
    exact numbers the synthetic records were built from — and there are
    no extra sunk-cost rows, so the writer cannot pad or drop arms."""
    _summary, out_dir = _run_write(tmp_path)
    _header, rows = _read_csv(out_dir / "arm_means.csv")
    assert rows[0].keys() == {
        "model", "experiment", "blinding", "arm", "mean"}
    got = {
        (row["model"], row["experiment"], row["blinding"],
         row["arm"]): float(row["mean"])
        for row in rows if row["experiment"] == "sunk_cost"
    }
    expected = {
        (model, "sunk_cost", "blinded", "no_card"): 14.884058
        for model in MODELS
    } | {
        (model, "sunk_cost", "blinded", "card"): 10.636364
        for model in MODELS
    } | {
        (model, "sunk_cost", "unblinded", "no_card"): 10.0
        for model in MODELS
    } | {
        (model, "sunk_cost", "unblinded", "card"): 20.0
        for model in MODELS
    }
    assert got.keys() == expected.keys()
    for key, want in expected.items():
        assert got[key] == pytest.approx(want), f"arm mean {key}"


def test_contrasts_file_matches_hand_computed_sunk_cost_contrasts(
        tmp_path: Path):
    """Sunk-cost contrasts with the pinned sign: blinded
    10.636364 - 14.884058 = -4.247694 (the human number, error 0) and
    unblinded 20.0 - 10.0 = +10.0."""
    _summary, out_dir = _run_write(tmp_path)
    _header, rows = _read_csv(out_dir / "contrasts.csv")
    got = {
        (row["model"], row["blinding"]): float(row["value"])
        for row in rows if row["experiment"] == "sunk_cost"
    }
    assert got.keys() == {
        (model, blinding) for model in MODELS
        for blinding in ("blinded", "unblinded")}
    for model in MODELS:
        assert got[(model, "blinded")] == pytest.approx(-4.247694), (
            "blinded sunk-cost contrast equals the shipped human number")
        assert got[(model, "unblinded")] == pytest.approx(10.0), (
            "unblinded sunk-cost contrast is card 20.0 minus no_card 10.0")


def test_summary_json_counts_and_mean_gain_match_the_synthetic_study(
        tmp_path: Path):
    """summary.json counts every row correctly and averages the 20 gains
    (2 models x 10 contrasts)."""
    summary, out_dir = _run_write(tmp_path)
    with open(out_dir / "summary.json", encoding="utf-8") as handle:
        written = json.load(handle)
    assert written == summary, "returned summary matches the written file"
    assert written["study"] == config.STUDY_NAME
    assert written["records"] == 2 * 2 * 3 * 16, (
        "2 models x 2 blindings x 3 personas x 16 arms across the 6 "
        "experiments = 192 records")
    assert written["contrasts"] == 40
    assert written["unblinding_gain_rows"] == 20
    expected_mean = fmean(list(EXPECTED_GAINS.values()) * len(MODELS))
    assert written["mean_unblinding_gain"] == pytest.approx(expected_mean)


def test_branch_mass_diagnostics_file_has_one_hand_checked_row_per_pair(
        tmp_path: Path):
    """Every (model, experiment) pair gets one diagnostics row; blinded
    records carry mass 0.9 flagged low and unblinded 0.7 not flagged, so
    each row's mean is 0.8 and its low share is 0.5."""
    _summary, out_dir = _run_write(tmp_path)
    _header, rows = _read_csv(out_dir / "branch_mass_diagnostics.csv")
    assert len(rows) == 2 * 6, "one row per model x experiment pair"
    got = {
        (row["model"], row["experiment"]):
            (float(row["mean_branch_mass"]),
             float(row["low_branch_mass_share"]))
        for row in rows
    }
    expected = {
        (model, exp_name): (0.8, 0.5)
        for model in MODELS for exp_name in experiments.EXPERIMENTS
    }
    assert got.keys() == expected.keys()
    for key, want in expected.items():
        assert got[key] == pytest.approx(want), f"diagnostics {key}"
