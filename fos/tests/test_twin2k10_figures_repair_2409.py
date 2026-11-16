# Locked RED tests for the twin2k10 figures REPAIR (TASK-2409; tests ONLY
# — the repair in scripts/twin2k10/figures_metrics.py / figures.py does
# not exist yet, so every test below must fail on the missing repair,
# never on a typo here).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The contrast fix (the root-cause bug): the human's experimental
#     effect is first put on the 0-1 scale with the experiment's own
#     registry rule, and the model-vs-human effect error is the gap
#     between the two 0-1 differences, times 100. Before the repair the
#     code searched for the RAW human effect among normalized arm means
#     and silently dropped every experiment that was not already 0-1 —
#     only 4 of the contrast-bearing experiments survived.
#   - The two anchoring experiments get a Profile Error and an
#     experimental-effect error computed from the BOUNDED anchor choice
#     (did the answerer pick "more"?) — the share answering "more" is a
#     clean 0-1 number for both humans and models. The free numeric
#     estimate stays excluded and the repair report says so.
#   - base_rate stays excluded from the Profile/effect figures (its LLM
#     side is first-digit mass only), and the repair report documents it.
#   - Every output gains an explicit HUMAN row: how far the humans
#     themselves drift between wave1_3 and wave4, computed through the
#     SAME pipeline, one point per experiment, plus a median and an
#     interquartile range across experiments.
#   - New pinned outputs: two "complete" CSVs (every computable row),
#     four ..._FIXED.png figures, a diagnostic_summary.csv (variance
#     split plus per-model Profile-vs-effect correlations) and a
#     repair_report.txt that opens with the exact model count (15) and
#     experiment count (16).
#   - The FIXED figures' axis labels state the unit (percentage points)
#     and that zero means an exact match.
#
# Everything runs offline on small synthetic fixtures (a hand-written
# registry subset plus fake arm means). No real run directory is read.
import struct
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import figures  # noqa: E402


@pytest.fixture(autouse=True)
def _out_dir(tmp_path, monkeypatch):
    """Give every test its own empty output directory as pytest.out_dir."""
    monkeypatch.setattr(pytest, "out_dir", tmp_path)
    yield tmp_path


# ---------------------------------------------------------------- fixtures
# The new pinned output files the repair adds (on top of the TASK-2392 set).
REPAIR_OUTPUT_FILES = [
    "profile_error_complete.csv",
    "contrast_error_complete.csv",
    "figure2_profile_error_distribution_FIXED.png",
    "figure2_profile_error_heatmap_FIXED.png",
    "figure3_contrast_error_distribution_FIXED.png",
    "figure3_contrast_error_heatmap_FIXED.png",
    "diagnostic_summary.csv",
    "repair_report.txt",
]


def _repair_registry():
    """A tiny hand-written registry subset covering the shapes the repair
    must get right:
      - sunk_cost: a NON-0-1 experiment (raw 0-20 purchases) whose human
        effect is a raw-scale number — the root-cause regression case;
      - anchoring_redwood: no normalization rule for the numeric
        estimate, but each human arm carries the share answering "more"
        on the bounded anchor question (anchor_mc, in percent);
      - base_rate: stays excluded (first-digit mass only);
      - false_consensus: no human effect at all (single arm).
    """
    return {
        "sunk_cost": {
            "normalization_0_1": {"min": 0, "max": 20},
            "human": {
                "wave1_3": {
                    "arms": {"no_card": 10.636364, "card": 6.388889},
                    "contrasts": {
                        "card_minus_no_card": {"computable": True, "value": -4.247694},
                    },
                },
                "wave4": {
                    "arms": {"no_card": 10.0, "card": 7.0},
                    "contrasts": {
                        "card_minus_no_card": {"computable": True, "value": -3.0},
                    },
                },
            },
        },
        "anchoring_redwood": {
            "normalization_0_1": {"min": None, "max": None},
            "human": {
                "wave1_3": {
                    "arms": {
                        "low": {"anchor_mc": {"1": 93.7083, "2": 6.2917}},
                        "high": {"anchor_mc": {"1": 35.1833, "2": 64.8167}},
                    },
                    "contrasts": {},
                },
                "wave4": {
                    "arms": {
                        "low": {"anchor_mc": {"1": 94.3756, "2": 5.6244}},
                        "high": {"anchor_mc": {"1": 31.3181, "2": 68.6819}},
                    },
                    "contrasts": {},
                },
            },
        },
        "base_rate": {
            "normalization_0_1": {"min": 0, "max": 100},
            "first_digit_profile": True,
            "human": {
                "wave1_3": {
                    "arms": {"30_engineers": 52.1735, "70_engineers": 68.0128},
                    "contrasts": {
                        "mean_70_minus_30": {"computable": True, "value": 15.8393},
                    },
                },
                "wave4": {
                    "arms": {"30_engineers": 52.3873, "70_engineers": 70.7054},
                    "contrasts": {
                        "mean_70_minus_30": {"computable": True, "value": 18.3181},
                    },
                },
            },
        },
        "false_consensus": {
            "normalization_0_1": {"min": 1, "max": 5},
            "human": {
                "wave1_3": {"arms": {"all": 3.1}, "contrasts": {}},
                "wave4": {"arms": {"all": 3.2}, "contrasts": {}},
            },
        },
    }


def _repair_llm_means():
    """Fake raw-scale model arm means:
    {model: {experiment: {blinding: {arm: value}}}}.
      - sunk_cost arms are raw 0-20 purchases;
      - anchoring arms are the model's share answering "more" (already 0-1);
      - base_rate and false_consensus present so their exclusion is testable.
    Chosen so hand arithmetic below is easy."""
    return {
        "gpt-oss-20b": {
            # Normalized effect (8.388889-12.636364)/20 = -0.212374 —
            # exactly the humans' normalized effect -> effect error 0.0.
            "sunk_cost": {
                "blinded": {"no_card": 12.636364, "card": 8.388889},
                "unblinded": {"no_card": 10.636364, "card": 6.388889},
            },
            # Matches the humans' anchor-choice shares exactly -> 0.0.
            "anchoring_redwood": {
                "blinded": {"low": 0.937083, "high": 0.351833},
                "unblinded": {"low": 0.943756, "high": 0.313181},
            },
            "base_rate": {
                "blinded": {"30_engineers": 30.0, "70_engineers": 70.0},
                "unblinded": {"30_engineers": 30.0, "70_engineers": 70.0},
            },
            "false_consensus": {
                "blinded": {"all": 3.6},
                "unblinded": {"all": 3.6},
            },
        },
        "qwen3-32b": {
            # Card arm 1 raw point HIGHER than the matching case:
            # normalized effect (7.388889-12.636364)/20 = -0.262374 vs the
            # humans' -0.212374 -> effect error exactly 5.0.
            "sunk_cost": {
                "blinded": {"no_card": 12.636364, "card": 7.388889},
                "unblinded": {"no_card": 12.636364, "card": 7.388889},
            },
            "anchoring_redwood": {
                "blinded": {"low": 0.90, "high": 0.40},
                "unblinded": {"low": 0.90, "high": 0.40},
            },
            "base_rate": {
                "blinded": {"30_engineers": 25.0, "70_engineers": 75.0},
                "unblinded": {"30_engineers": 25.0, "70_engineers": 75.0},
            },
            "false_consensus": {
                "blinded": {"all": 2.1},
                "unblinded": {"all": 2.1},
            },
        },
    }


def _rows():
    return figures.compute_error_rows(_repair_registry(), _repair_llm_means())


# ------------------------------------------------------- contrast fix (1)
def test_raw_scale_contrast_is_compared_on_the_0_1_scale_not_raw():
    """ROOT-CAUSE REGRESSION: an experiment whose human effect is a
    raw-scale number (sunk_cost, 0-20 purchases) must still get an
    experimental-effect error. The model above matches the humans exactly
    once both effects are put on the 0-1 scale, so the error is 0.0 —
    before the repair this cell came back empty (None)."""
    row = next(r for r in _rows() if r.model == "gpt-oss-20b" and r.experiment == "sunk_cost")
    assert row.contrast_error is not None, (
        "raw-scale experiment silently dropped its effect error (the bug)"
    )
    assert row.contrast_error == pytest.approx(0.0)


def test_raw_scale_contrast_error_value_is_hand_computable():
    """A model whose 0-1-scale effect is off by exactly 0.05 from the
    humans' 0-1-scale effect gets an error of 5.0 percentage points —
    proving the comparison happens on the normalized scale (comparing
    raw numbers would give a value near 424, not 5)."""
    row = next(r for r in _rows() if r.model == "qwen3-32b" and r.experiment == "sunk_cost")
    assert row.contrast_error == pytest.approx(5.0)


def test_every_contrast_bearing_experiment_has_a_contrast_error():
    """All contrast-bearing experiments in the fixture (sunk_cost and the
    anchoring experiment via its anchor choice) must produce a number;
    base_rate (not computable) and false_consensus (no effect) stay None.
    Before the repair only the already-0-1 experiments survived."""
    by_experiment = {}
    for r in _rows():
        if r.model == "gpt-oss-20b":
            by_experiment[r.experiment] = r.contrast_error
    assert by_experiment["sunk_cost"] is not None
    assert by_experiment["anchoring_redwood"] is not None
    assert by_experiment["base_rate"] is None
    assert by_experiment["false_consensus"] is None


# ------------------------------------------- anchoring via anchor choice (2)
def test_anchoring_profile_and_effect_come_from_the_anchor_choice():
    """The anchoring experiment's Profile Error and effect error use the
    bounded 'more/less' choice share (0-1), which exists for both humans
    and models. With model shares equal to the humans', both errors are
    exactly 0.0 — the unbounded numeric estimate is never touched."""
    row = next(
        r for r in _rows() if r.model == "gpt-oss-20b" and r.experiment == "anchoring_redwood"
    )
    assert row.profile_error_blinded == pytest.approx(0.0)
    assert row.contrast_error == pytest.approx(0.0)
    # Unblinded shifts both arms: |0.943756-0.937083| = 0.006673 and
    # |0.313181-0.351833| = 0.038652 -> mean x100 = 2.26625.
    assert row.profile_error_unblinded == pytest.approx(2.26625, abs=1e-3)
    # Effect gap: (0.313181-0.943756) - (0.351833-0.937083) = -0.045325.
    assert row.contrast_error is not None


def test_anchoring_numeric_estimate_stays_excluded_and_documented():
    """The unbounded numeric estimate is still NOT used anywhere, and the
    repair report says so in plain words instead of failing silently."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    report = (out / "repair_report.txt").read_text().lower()
    assert "estimate" in report and "exclud" in report


# ------------------------------------------------- base_rate exclusion (3)
def test_base_rate_stays_excluded_and_documented():
    """base_rate keeps no Profile Error and no effect error in the
    figures/CSVs (its LLM side is first-digit mass only), and the repair
    report documents that it is not computable."""
    br = [r for r in _rows() if r.experiment == "base_rate"]
    assert all(r.profile_error_blinded is None for r in br)
    assert all(r.contrast_error is None for r in br)
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    report = (out / "repair_report.txt").read_text().lower()
    assert "base_rate" in report and ("not computable" in report or "excluded" in report)


# ------------------------------------------------------- new outputs (4+5)
def test_repair_outputs_are_written():
    """The repair's pinned new files all appear in out_dir: two complete
    CSVs, four ..._FIXED.png figures, diagnostic_summary.csv and
    repair_report.txt."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    for name in REPAIR_OUTPUT_FILES:
        assert (out / name).exists(), f"{name} was not written"


def test_complete_csvs_contain_every_computable_row():
    """profile_error_complete.csv holds a row for every model x experiment
    with a computable Profile Error (including the anchoring experiments
    via their anchor choice); contrast_error_complete.csv does the same
    for effect errors. Nothing computable may be silently missing."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    prof = (out / "profile_error_complete.csv").read_text().strip().splitlines()[1:]
    cont = (out / "contrast_error_complete.csv").read_text().strip().splitlines()[1:]
    # model rows only — the HUMAN rows are verified by their own test below
    prof_models = {line.split(",")[0] for line in prof if line.split(",")[0].upper() != "HUMAN"}
    prof_exps = {line.split(",")[1] for line in prof}
    assert prof_models == {"gpt-oss-20b", "qwen3-32b"}
    assert "anchoring_redwood" in prof_exps, "anchoring missing from complete Profile CSV"
    assert "base_rate" not in prof_exps, "base_rate must stay out of the Profile figure"
    cont_exps = {line.split(",")[1] for line in cont}
    assert "sunk_cost" in cont_exps
    assert "anchoring_redwood" in cont_exps
    assert "false_consensus" not in cont_exps


def _png_dpi(path):
    """Read a PNG's pHYs chunk: dots per meter -> dpi (None if absent)."""
    data = path.read_bytes()
    pos = 8
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        if ctype == b"pHYs":
            xppm = struct.unpack(">I", data[pos + 8:pos + 12])[0]
            return xppm * 0.0254
        pos += 8 + length + 4
    return None


def test_fixed_figures_are_written_at_300dpi():
    """Publication quality carries over: every ..._FIXED.png carries a
    300 dpi density tag."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    for name in REPAIR_OUTPUT_FILES:
        if name.endswith(".png"):
            dpi = _png_dpi(out / name)
            assert dpi is not None, f"{name} has no dpi information"
            assert dpi == pytest.approx(300, abs=1)


# ------------------------------------------------------------ HUMAN row (4)
def test_complete_csvs_gain_an_explicit_human_row():
    """The complete CSVs carry a HUMAN row per experiment: how far the
    humans themselves drift between wave1_3 and wave4, through the SAME
    pipeline. For sunk_cost the drift is: arms (10.0 vs 10.636364) and
    (7.0 vs 6.388889) on the 0-1 scale -> profile drift
    (0.0318182 + 0.0305556)/2 x100 = 3.11869."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    prof = (out / "profile_error_complete.csv").read_text().strip().splitlines()[1:]
    human_rows = [line.split(",") for line in prof if line.split(",")[0].upper() == "HUMAN"]
    assert human_rows, "no HUMAN row in profile_error_complete.csv"
    by_exp = {r[1]: float(r[2]) for r in human_rows}
    assert by_exp["sunk_cost"] == pytest.approx(3.11869, abs=1e-3)
    cont = (out / "contrast_error_complete.csv").read_text().strip().splitlines()[1:]
    human_cont = [line.split(",") for line in cont if line.split(",")[0].upper() == "HUMAN"]
    assert human_cont, "no HUMAN row in contrast_error_complete.csv"


def test_human_row_summary_reports_median_and_iqr():
    """The HUMAN summary gives a median and an interquartile range across
    experiments (one point per experiment), written into the diagnostic
    summary. Fixture human profile drifts: anchoring 2.26625, sunk_cost
    3.11869 -> median 2.69247 and the IQR must bracket the median."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    text = (out / "diagnostic_summary.csv").read_text().lower()
    assert "median" in text and ("iqr" in text or "interquartile" in text)
    for token in ("2.69",):
        assert token in text, f"expected human median {token}... in diagnostic_summary.csv"


# -------------------------------------------------- repair_report counts (5)
def test_repair_report_opens_with_exact_counts():
    """repair_report.txt starts by stating the exact model count (15) and
    experiment count (16) so the reader immediately knows the scope."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    first_line = (out / "repair_report.txt").read_text().splitlines()[0]
    assert "15" in first_line and "model" in first_line.lower()
    assert "16" in first_line and "experiment" in first_line.lower()


# ------------------------------------------------- diagnostic summary (5)
def test_diagnostic_summary_has_variance_split_and_per_model_correlations():
    """diagnostic_summary.csv carries the model/experiment/residual
    variance split (shares that add up to 1) and one Profile-vs-effect
    correlation per model."""
    out = Path(pytest.out_dir)
    figures.write_outputs(_rows(), out, test_retest=figures.human_test_retest_errors(_repair_registry()))
    lines = (out / "diagnostic_summary.csv").read_text().strip().splitlines()
    text = "\n".join(lines).lower()
    for key in ("model", "experiment", "residual"):
        assert key in text, f"variance share '{key}' missing"
    assert "gpt-oss-20b" in text and "qwen3-32b" in text, "per-model correlations missing"
    # Variance shares must appear somewhere as three numbers summing to 1:
    comp = figures.variance_components(_rows())
    assert sum(comp.values()) == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------- axis labels (6)
def test_axis_labels_name_the_unit_and_zero_meaning():
    """The FIXED figures' axis labels state the unit (percentage points)
    and that 0 means an exact match — exactly the owner-pinned wording."""
    assert figures.PROFILE_ERROR_AXIS_LABEL == (
        "Profile error vs. human reference (percentage points; 0 = exact match)"
    )
    assert figures.CONTRAST_ERROR_AXIS_LABEL == (
        "Experimental-effect error (percentage points; 0 = exact human effect)"
    )
