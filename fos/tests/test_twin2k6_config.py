# Locked tests for the twin2k6 study's configuration module (TASK-2060 RED
# phase; tests ONLY — no implementation lives here yet, so every test in
# this file errors at collection until scripts/twin2k6/config.py exists).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The study runs exactly the 15 local models (the API model is excluded).
#   - The two data files shipped with the study (stimuli + human benchmarks)
#     exist in the repo, parse, carry a provenance note, and hold the pinned
#     questions/benchmarks the whole study is built on.
#   - The inference knobs copy the proven R1 pipeline (8-token scan window,
#     temperature 1.0, at least 100 top logprobs, the 1-in-a-million
#     probability floor) plus the study's own thresholds (0.80 branch-mass
#     floor, fsync at least every 50 records) and the two blinding arms.
#
# All offline: file reads and pure asserts; no network, no model loads.
import json
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import config  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent

# The fixed 15-model list, in the study's pinned order (from
# scripts/r1yesno_v2/registry.py entries with local_or_api="local";
# the API model qwen3.8-max-0902 is EXCLUDED).
EXPECTED_MODELS = [
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

# The 16 stimulus QIDs the study ships (pinned so a silent re-export of the
# question catalogue cannot shrink or swap the study's questions).
EXPECTED_QIDS = [
    "QID157", "QID158",
    "QID171", "QID172", "QID173",
    "QID174", "QID175", "QID176",
    "QID177", "QID178", "QID179",
    "QID181", "QID182",
    "QID189", "QID190", "QID191",
]


def test_model_list_is_exactly_the_15_pinned_local_models_in_order():
    """config.MODELS lists exactly the 15 study models, in the pinned order."""
    assert list(config.MODELS) == EXPECTED_MODELS


def test_model_list_has_no_duplicates_and_no_api_model():
    """Every model id is distinct and the API model never sneaks in."""
    assert len(set(config.MODELS)) == 15
    assert "qwen3.8-max-0902" not in config.MODELS


def test_model_list_matches_the_local_models_in_r1yesno_registry():
    """The study list equals the local half of the R1 registry (provenance)."""
    from r1yesno_v2 import registry

    local = sorted(
        mid for mid, info in registry.MODELS.items()
        if info["local_or_api"] == "local"
    )
    assert sorted(config.MODELS) == local


def test_data_file_paths_point_at_the_shipped_repo_copies():
    """Config names the repo data files; both exist on disk."""
    assert config.STIMULI_PATH == _REPO / "data" / "configs" / "twin2k6_stimuli.json"
    assert config.BENCHMARKS_PATH == _REPO / "data" / "configs" / "twin2k6_benchmarks.json"
    assert config.STIMULI_PATH.is_file(), f"missing {config.STIMULI_PATH}"
    assert config.BENCHMARKS_PATH.is_file(), f"missing {config.BENCHMARKS_PATH}"


def _load(path):
    """Read one of the shipped JSON data files (helper for the checks below)."""
    with open(path) as f:
        return json.load(f)


def test_stimuli_copy_holds_all_16_pinned_questions():
    """The shipped stimuli file has the provenance note and all 16 QIDs."""
    data = _load(config.STIMULI_PATH)
    assert "_provenance" in data, "shipped copy must carry a _provenance key"
    assert "TASK-2058" in json.dumps(data["_provenance"])
    qids = [s["qid"] for s in data["stimuli"]]
    assert qids == EXPECTED_QIDS


def test_stimuli_copy_preserves_verbatim_question_text_and_options():
    """Spot-check that question text and options survived the copy untouched."""
    data = _load(config.STIMULI_PATH)
    by_qid = {s["qid"]: s for s in data["stimuli"]}
    gain = by_qid["QID157"]
    assert gain["experiment"] == "disease"
    assert gain["arm"] == "gain"
    assert gain["question_text"].startswith(
        "Imagine that the U.S. is preparing for the outbreak of an unusual disease"
    )
    assert gain["options"][0] == "I strongly favor program A"
    sunk = by_qid["QID181"]
    assert sunk["experiment"] == "sunk_cost"
    assert sunk["arm"] == "no_card"
    assert sunk["options"] is None  # sunk cost has no lettered options in the catalogue
    wtp = by_qid["QID189"]
    assert wtp["options"][0] == "$10"
    assert wtp["options"][-1] == "$5,000,000 or more"


def test_benchmarks_copy_holds_both_waves_and_provenance():
    """The shipped benchmarks file has wave1_3 + wave4 for all 6 experiments."""
    data = _load(config.BENCHMARKS_PATH)
    assert "_provenance" in data, "shipped copy must carry a _provenance key"
    assert "TASK-2058" in json.dumps(data["_provenance"])
    for wave in ("wave1_3", "wave4"):
        assert wave in data["waves"]
        assert set(data["waves"][wave].keys()) == {
            "disease", "less_is_more", "fire_extinguisher",
            "seatbelt", "sunk_cost", "wta_wtp",
        }


def test_benchmarks_copy_preserves_pinned_human_numbers():
    """Spot-check human contrast values the analysis is graded against."""
    data = _load(config.BENCHMARKS_PATH)
    w13 = data["waves"]["wave1_3"]
    disease = w13["disease"]["contrasts"]["p_safe_loss_minus_gain"]
    assert disease["value"] == pytest.approx(-0.35581)
    assert w13["disease"]["arms"]["gain"]["p_safe"] == pytest.approx(0.718843)
    assert w13["disease"]["arms"]["loss"]["p_safe"] == pytest.approx(0.363033)
    sunk = w13["sunk_cost"]["contrasts"]["card_minus_no_card"]
    assert sunk["value"] == pytest.approx(-4.247694)
    wta = w13["wta_wtp"]["contrasts"]["wta_minus_wtp_certainty"]
    assert wta["value"] == pytest.approx(3.559216)


def test_blinding_arms_are_blinded_and_unblinded():
    """The study compares exactly the two blinding arms, in that order."""
    assert tuple(config.BLINDINGS) == ("blinded", "unblinded")


def test_persona_pool_is_100_shared_personas():
    """Every model answers the same single pool of 100 personas (ids 0-99)."""
    assert config.PERSONA_COUNT == 100


def test_inference_knobs_copy_the_proven_r1_pipeline():
    """Scan window, temperature and probability floor match the R1 runs."""
    assert config.SCAN_TOKENS == 8
    assert config.TEMPERATURE == 1.0
    assert config.PROBABILITY_FLOOR == 1e-6


def test_top_k_is_at_least_100_for_every_label_set():
    """10-21 label spellings must fit in the top-k window, so k >= 100."""
    assert config.TOP_K >= 100


def test_low_branch_mass_threshold_is_0_80_not_the_r1_0_60():
    """This study flags diffuse answers at 0.80 (R1 used 0.60)."""
    assert config.LOW_BRANCH_MASS_THRESHOLD == 0.80


def test_fsync_constant_loses_at_most_50_records_on_crash():
    """Durability spec: fsync at least every 50 records (crash loses <= 50)."""
    assert config.FSYNC_EVERY <= 50
