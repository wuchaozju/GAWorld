# Locked tests for the twin2k10 study's FIGURES module (TASK-2392 RED
# phase; tests ONLY — the implementation in scripts/twin2k10/figures.py
# does not exist yet, so every test below must fail on the missing
# feature, never on a typo here).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - There is a fixed row order for the figures: the 15 registry models
#     in family/generation order and the 16 registry experiments in
#     registry order. Figures are horizontal (one row per model) and
#     every experiment is a point.
#   - Normalization takes each experiment's raw outcome to 0-1 using the
#     registry's own min/max rule (e.g. sunk_cost (x-0)/20). Direction is
#     preserved and there is NO z-scoring. Experiments whose registry
#     rule is "NEEDS-OWNER" (the two anchoring estimates) have no rule,
#     so normalization returns None.
#   - Profile Error(model, experiment) = the average, over arms, of
#     |model arm mean - human arm mean| on the 0-1 scale, times 100.
#     Human arm means come from the wave1_3 benchmark; the wave4
#     (unblinded-primary) values are also accepted so the blinded /
#     unblinded splits can both be computed.
#   - Contrast Error(model, experiment) = the average, over the
#     pre-specified contrasts, of |model difference - human difference|
#     times 100. false_consensus has NO human contrast, so it gets a
#     Profile Error only and its Contrast Error stays None.
#   - base_rate's model side is a first-digit distribution (the records
#     only store digit 0-9 mass), so it uses a first-digit-distribution
#     variant of the Profile Error; the row is labelled with that method
#     so the report can document it.
#   - The human-vs-human reference band is test-retest: the SAME two
#     metrics computed between wave1_3 and wave4 human arm means.
#     Split-half is NOT available anywhere and must never be claimed.
#   - A descriptive variance decomposition of the model x experiment
#     Profile-Error matrix into model / experiment / residual shares,
#     plus a per-model correlation between Profile and Contrast errors.
#   - write_outputs creates EXACTLY these files: four PNGs
#     (figure2_profile_error_distribution, figure2_profile_error_heatmap,
#     figure3_contrast_error_distribution, figure3_contrast_error_heatmap),
#     three CSVs (profile_error, contrast_error, error_summary) and
#     report.txt, all at 300 dpi. Heatmaps are dark = closer to humans
#     (smaller error). There is no ranking column anywhere.
#
# Everything runs offline on small synthetic fixtures (a hand-written
# registry subset plus fake arm means). No real run directory is ever
# read; the module only ever writes inside the caller's out_dir.
import math
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
# The 15 registry models, pinned in family/generation order (the order the
# registry lists them: gpt-oss, gemma-4 family, qwen3.8/3.6/3 family,
# granite family, then the small/other models).
EXPECTED_MODEL_ORDER = [
    "gpt-oss-20b",
    "gemma-4-26b-a4b",
    "gemma-4-31b-it-qat",
    "gemma-4-12b-it-qat",
    "qwen3.8-27b",
    "qwen3.6-27b-dense",
    "qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored",
    "qwen3-32b",
    "qwen3-4b",
    "granite-4.1-8b",
    "granite-4.1-30b",
    "nemotron-cascade-2-30b-a3b",
    "muse-glimmer",
    "glm-4.7-flash",
]

# The 16 registry experiments in registry order.
EXPECTED_EXPERIMENT_ORDER = [
    "disease", "less_is_more", "fire_extinguisher", "seatbelt",
    "sunk_cost", "wta_wtp", "allais", "linda", "base_rate",
    "anchoring_redwood", "anchoring_african", "outcome_bias",
    "myside", "prob_matching", "abs_relative", "false_consensus",
]

# The exact output filenames the task pins. TASK-2410 (owner-approved
# amendment) adds the eight REPAIR outputs alongside the base eight.
EXPECTED_OUTPUT_FILES = [
    "figure2_profile_error_distribution.png",
    "figure2_profile_error_heatmap.png",
    "figure3_contrast_error_distribution.png",
    "figure3_contrast_error_heatmap.png",
    "profile_error.csv",
    "contrast_error.csv",
    "error_summary.csv",
    "report.txt",
    "profile_error_complete.csv",
    "contrast_error_complete.csv",
    "figure2_profile_error_distribution_FIXED.png",
    "figure2_profile_error_heatmap_FIXED.png",
    "figure3_contrast_error_distribution_FIXED.png",
    "figure3_contrast_error_heatmap_FIXED.png",
    "diagnostic_summary.csv",
    "repair_report.txt",
]


def _mini_registry():
    """A tiny hand-written stand-in for experiment_registry.json: three
    experiments covering the three shapes we must handle — a 0-1 choice
    experiment with a contrast, a raw-scale experiment needing min/max
    normalization, and false_consensus which has NO human contrast."""
    return {
        "disease": {
            "normalization_0_1": {"min": 0, "max": 1},
            "human": {
                "wave1_3": {
                    "arms": {"gain": 0.718843, "loss": 0.363033},
                    "contrasts": {
                        "p_safe_loss_minus_gain": {"computable": True, "value": -0.35581},
                    },
                },
                "wave4": {
                    "arms": {"gain": 0.729811, "loss": 0.375355},
                    "contrasts": {
                        "p_safe_loss_minus_gain": {"computable": True, "value": -0.354455},
                    },
                },
            },
        },
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
        "false_consensus": {
            "normalization_0_1": {"min": 1, "max": 5},
            "human": {
                "wave1_3": {"arms": {"all": 3.1}, "contrasts": {}},
                "wave4": {"arms": {"all": 3.2}, "contrasts": {}},
            },
        },
        "anchoring_redwood": {
            # No pre-specified normalization rule (NEEDS-OWNER).
            "normalization_0_1": {"min": None, "max": None},
            "human": {
                "wave1_3": {"arms": {"low": 200.0, "high": 800.0}, "contrasts": {}},
                "wave4": {"arms": {"low": 210.0, "high": 810.0}, "contrasts": {}},
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
    }


def _fake_llm_means():
    """Fake raw-scale model arm means:
    {model: {experiment: {blinding: {arm: raw value}}}}.
    Chosen so hand arithmetic below is easy."""
    return {
        "gpt-oss-20b": {
            "disease": {
                "blinded": {"gain": 0.668843, "loss": 0.313033},
                "unblinded": {"gain": 0.768843, "loss": 0.413033},
            },
            "sunk_cost": {
                "blinded": {"no_card": 12.636364, "card": 8.388889},
                "unblinded": {"no_card": 10.636364, "card": 6.388889},
            },
            "false_consensus": {
                "blinded": {"all": 3.6},
                "unblinded": {"all": 3.6},
            },
        },
        "qwen3-32b": {
            "disease": {
                "blinded": {"gain": 0.918843, "loss": 0.563033},
                "unblinded": {"gain": 0.918843, "loss": 0.563033},
            },
            "sunk_cost": {
                "blinded": {"no_card": 4.636364, "card": 2.388889},
                "unblinded": {"no_card": 4.636364, "card": 2.388889},
            },
            "false_consensus": {
                "blinded": {"all": 2.1},
                "unblinded": {"all": 2.1},
            },
        },
    }


# ------------------------------------------------------------------ tests
def test_model_and_experiment_orders_are_fixed():
    """Rows in every figure/CSV follow the registry's model and experiment
    order, never alphabetical and never data-driven."""
    assert figures.MODEL_ORDER == EXPECTED_MODEL_ORDER
    assert figures.EXPERIMENT_ORDER == EXPECTED_EXPERIMENT_ORDER


def test_normalization_maps_raw_scale_to_0_1_by_registry_min_max():
    """A raw outcome on a k-point scale lands in 0-1 exactly as the
    registry rule says (e.g. sunk_cost code 10 on a 0-20 scale -> 0.5)."""
    assert figures.normalize(10.0, {"min": 0, "max": 20}) == pytest.approx(0.5)
    assert figures.normalize(0.718843, {"min": 0, "max": 1}) == pytest.approx(0.718843)
    assert figures.normalize(3.1, {"min": 1, "max": 5}) == pytest.approx(0.525)


def test_normalization_preserves_direction_and_is_not_z_scoring():
    """A bigger raw value must stay bigger after normalization, and the
    result must depend only on the registry min/max — not on the spread of
    the data (which is what a z-score would do)."""
    low = figures.normalize(2.0, {"min": 1, "max": 5})
    high = figures.normalize(4.0, {"min": 1, "max": 5})
    assert high > low
    # Same value, different data spread -> identical result (no z-scoring).
    assert figures.normalize(3.0, {"min": 1, "max": 5}) == figures.normalize(
        3.0, {"min": 1, "max": 5}
    )


def test_normalization_returns_none_when_registry_has_no_rule():
    """The anchoring estimates carry min=None/max=None (NEEDS-OWNER), so
    there is nothing defensible to normalize with."""
    assert figures.normalize(800.0, {"min": None, "max": None}) is None


def test_profile_error_is_mean_absolute_arm_gap_times_100():
    """Two arms each off by 0.20 on the 0-1 scale -> Profile Error 20."""
    model = {"gain": 0.668843, "loss": 0.313033}
    human = {"gain": 0.718843, "loss": 0.363033}
    # (0.05 + 0.05) / 2 * 100 = 5.0
    assert figures.profile_error(model, human) == pytest.approx(5.0)


def test_profile_error_works_for_blinded_and_unblinded():
    """The same metric must be computable for both blind conditions; the
    fake data above gives blinded 5.0 and unblinded 5.0 for gpt-oss-20b."""
    arms = _fake_llm_means()["gpt-oss-20b"]["disease"]
    human = {"gain": 0.718843, "loss": 0.363033}
    assert figures.profile_error(arms["blinded"], human) == pytest.approx(5.0)
    assert figures.profile_error(arms["unblinded"], human) == pytest.approx(5.0)


def test_contrast_error_is_mean_absolute_contrast_gap_times_100():
    """One pre-specified contrast off by 0.05 on the 0-1 scale -> 5."""
    # Model contrast -0.30581 vs human -0.35581 -> |0.05| * 100 = 5.
    assert figures.contrast_error(
        {"p_safe_loss_minus_gain": -0.30581},
        {"p_safe_loss_minus_gain": -0.35581},
    ) == pytest.approx(5.0)


def test_false_consensus_gets_profile_error_only():
    """false_consensus has no pre-specified human contrast, so its
    Contrast Error is None while its Profile Error is a number."""
    rows = figures.compute_error_rows(_mini_registry(), _fake_llm_means())
    fc = [r for r in rows if r.experiment == "false_consensus"]
    assert fc, "false_consensus rows must exist"
    assert all(r.contrast_error is None for r in fc)
    assert all(r.profile_error_blinded is not None for r in fc)


def test_anchoring_estimate_rows_are_excluded_with_a_report_note():
    """No normalization rule -> no computable Profile Error for the
    anchoring estimates, and report.txt must say so instead of failing
    silently."""
    rows = figures.compute_error_rows(_mini_registry(), _fake_llm_means())
    anch = [r for r in rows if r.experiment == "anchoring_redwood"]
    assert all(r.profile_error_blinded is None for r in anch)
    out = Path(pytest.out_dir)
    figures.write_outputs(rows, out, test_retest=None)
    report = (out / "report.txt").read_text()
    assert "anchoring" in report.lower()


def test_base_rate_uses_first_digit_profile_variant_and_documents_it():
    """base_rate's model side is a first-digit distribution, so its row is
    labelled method='first_digit' and the distribution-variant metric
    compares the two 10-bucket distributions (mean |gap| x 100)."""
    model_dist = {d: 0.1 for d in range(10)}
    human_dist = {d: 0.1 for d in range(10)}
    assert figures.profile_error_first_digit(model_dist, human_dist) == pytest.approx(0.0)
    model_dist[3] = 0.2
    model_dist[4] = 0.0
    # Two buckets moved by 0.1 -> mean |gap| = 0.02 -> 2.0.
    assert figures.profile_error_first_digit(model_dist, human_dist) == pytest.approx(2.0)
    rows = figures.compute_error_rows(_mini_registry(), _fake_llm_means())
    br = [r for r in rows if r.experiment == "base_rate"]
    # No human first-digit distribution was supplied -> metrics stay None
    # but the method label still documents the variant.
    assert all(r.method == "first_digit" for r in br)


def test_test_retest_band_uses_wave1_3_vs_wave4_same_metrics():
    """The human-vs-human reference band is test-retest: the SAME profile
    and contrast formulas applied between the two waves' human arms."""
    band = figures.human_test_retest_errors(_mini_registry())
    disease = band["disease"]
    # wave1_3 vs wave4 gaps: |0.729811-0.718843| = 0.010968 and
    # |0.375355-0.363033| = 0.012322 -> mean 0.011645 x100 = 1.1645.
    assert disease["profile_error"] == pytest.approx(1.1645, abs=1e-3)
    assert disease["contrast_error"] == pytest.approx(0.1355, abs=1e-3)


def test_report_never_claims_split_half():
    """Split-half is NOT available (verified); the report may mention
    test-retest but must never present a split-half band."""
    out = Path(pytest.out_dir)
    figures.write_outputs(
        figures.compute_error_rows(_mini_registry(), _fake_llm_means()),
        out,
        test_retest=figures.human_test_retest_errors(_mini_registry()),
    )
    report = (out / "report.txt").read_text().lower()
    assert "test-retest" in report or "test_retest" in report
    assert "split-half" not in report and "split_half" not in report


def test_variance_components_are_descriptive_and_sum_to_one():
    """The model/experiment/residual split of the Profile-Error matrix is
    descriptive only and its shares sum to 1."""
    rows = figures.compute_error_rows(_mini_registry(), _fake_llm_means())
    comp = figures.variance_components(rows)
    assert set(comp) == {"model", "experiment", "residual"}
    assert all(v >= 0 for v in comp.values())
    assert sum(comp.values()) == pytest.approx(1.0, abs=1e-6)


def test_profile_contrast_correlation_is_per_model():
    """Each model gets its own Profile-vs-Contrast correlation across
    experiments; a model with too few comparable experiments gets None
    rather than a meaningless number."""
    rows = figures.compute_error_rows(_mini_registry(), _fake_llm_means())
    corr = figures.profile_contrast_correlation(rows)
    # Only models present in the fixture data, per the contract.
    assert set(corr) == {"gpt-oss-20b", "qwen3-32b"}
    for value in corr.values():
        assert value is None or -1.0 <= value <= 1.0


def test_write_outputs_creates_exactly_the_pinned_files():
    """The four PNGs, three CSVs and report.txt — exact names, nothing
    else — inside out_dir only."""
    out = Path(pytest.out_dir)
    figures.write_outputs(
        figures.compute_error_rows(_mini_registry(), _fake_llm_means()),
        out,
        test_retest=figures.human_test_retest_errors(_mini_registry()),
    )
    assert sorted(p.name for p in out.iterdir()) == sorted(EXPECTED_OUTPUT_FILES)


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


def test_figures_are_written_at_300dpi():
    """Publication quality: every PNG carries a 300 dpi density tag."""
    out = Path(pytest.out_dir)
    figures.write_outputs(
        figures.compute_error_rows(_mini_registry(), _fake_llm_means()),
        out,
        test_retest=None,
    )
    for name in EXPECTED_OUTPUT_FILES:
        if name.endswith(".png"):
            dpi = _png_dpi(out / name)
            assert dpi is not None, f"{name} has no dpi information"
            assert dpi == pytest.approx(300, abs=1)


def test_distribution_points_cover_every_model_experiment_pair():
    """Every experiment is a point: the distribution figures show one dot
    per (model, experiment) pair with data — the CSV backing them has
    exactly that many data rows, in fixed model order. (TASK-2410
    owner-approved amendment: the complete CSVs legitimately gain one
    HUMAN test-retest row per experiment on top of the model rows; the
    pinned profile_error.csv keeps its model-rows-only contract.)"""
    out = Path(pytest.out_dir)
    rows = figures.compute_error_rows(_mini_registry(), _fake_llm_means())
    figures.write_outputs(
        rows,
        out,
        test_retest=figures.human_test_retest_errors(_mini_registry()),
    )
    lines = (out / "profile_error.csv").read_text().strip().splitlines()
    data_rows = [line.split(",") for line in lines[1:]]
    models_in_order = [r[0] for r in data_rows]
    # Rows grouped by model, models appearing in the pinned order.
    seen = list(dict.fromkeys(models_in_order))
    assert seen == ["gpt-oss-20b", "qwen3-32b"]
    # gpt-oss-20b has 3 experiments with profile errors; qwen3-32b also 3.
    assert models_in_order.count("gpt-oss-20b") == 3
    assert models_in_order.count("qwen3-32b") == 3
    # Complete CSV: same model rows, plus one HUMAN row per experiment
    # where the humans' own drift is computable (here: disease and
    # sunk_cost; base_rate is excluded, false_consensus has one arm).
    complete = (out / "profile_error_complete.csv").read_text().strip().splitlines()
    complete_rows = [line.split(",") for line in complete[1:]]
    assert [r[0] for r in complete_rows].count("gpt-oss-20b") == 3
    assert [r[0] for r in complete_rows].count("qwen3-32b") == 3
    assert [r[0] for r in complete_rows].count("HUMAN") == 2


def test_no_ranking_column_in_any_csv():
    """The figures must not rank models: no 'rank'/'score' ordering column
    appears in any output CSV."""
    out = Path(pytest.out_dir)
    figures.write_outputs(
        figures.compute_error_rows(_mini_registry(), _fake_llm_means()),
        out,
        test_retest=None,
    )
    for name in EXPECTED_OUTPUT_FILES:
        if name.endswith(".csv"):
            header = (out / name).read_text().splitlines()[0].lower()
            assert "rank" not in header, f"{name} has a ranking column"


def test_heatmap_dark_means_closer_to_humans():
    """In the error heatmaps the colormap must map SMALL error (close to
    humans) to DARK — check luminance at the low end vs the high end."""
    cmap = figures.HEATMAP_CMAP
    low = cmap(0.05)[:3]
    high = cmap(0.95)[:3]
    lum_low = 0.2126 * low[0] + 0.7152 * low[1] + 0.0722 * low[2]
    lum_high = 0.2126 * high[0] + 0.7152 * high[1] + 0.0722 * high[2]
    assert lum_low < lum_high


def test_write_outputs_touches_nothing_outside_out_dir():
    """The module works purely on in-memory data: no run directory is
    read, and with an empty out_dir only the pinned files appear there."""
    out = Path(pytest.out_dir)
    figures.write_outputs([], out, test_retest=None)
    assert sorted(p.name for p in out.iterdir()) == sorted(EXPECTED_OUTPUT_FILES)
