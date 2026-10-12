# Tests for the twin2k10 figures HUMAN arm-stat extraction (TASK-2419;
# tests ONLY — the fix in scripts/twin2k10/figures_metrics.py does not
# exist yet, so every test below must fail on the missing fix).
#
# WHAT THIS FILE CHECKS, in plain words:
#   In the real production data the HUMAN arm values are not plain
#   numbers — they are little stat cards whose number lives under a
#   different key per experiment. This file pins each real shape and
#   the number that must be pulled out of it:
#     - {"n": ..., "p_safe": 0.72}          -> 0.72   (disease)
#     - {"n": ..., "mean": 52.2}            -> 52.2   (base_rate, myside, ...)
#     - {"n": ..., "dist": {"1": {"pct": 69.1}}} -> 0.691 (allais: share
#       choosing option 1 = pct / 100)
#     - {"per_statement": {..., "_3": {"mean": 3.378}}} -> 3.378 (linda:
#       statement 3's mean)
#     - {"per_trial_pct_majority": {trial: pct}}  -> mean(pcts)/100
#       (prob_matching)
#     - {"per_item": {item: {"mean": m}}}   -> mean of the item means
#       (false_consensus)
#   Also: the arm-pair search for contrasts must compare NUMBERS, not
#   dicts (the production crash), and a model arm value of None (the
#   real base_rate cells are null) must give a missing row, not a crash.
#
# Everything runs offline on a small synthetic registry subset plus fake
# arm means. No real run directory is read.
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import figures_metrics as fm  # noqa: E402


def _spec(lo: float, hi: float) -> dict:
    return {"min": lo, "max": hi}


def test_p_safe_card_gives_its_number() -> None:
    assert fm._arm_mean({"qid": "Q1", "n": 1003, "p_safe": 0.7188}) == pytest.approx(
        0.7188
    )


def test_p_yes_card_gives_its_number() -> None:
    assert fm._arm_mean({"qid": "Q1", "n": 100, "p_yes": 0.41}) == pytest.approx(0.41)


def test_p_yes_percent_card_is_brought_back_to_0_1() -> None:
    # Real abs_relative data stores p_yes as a percent (73.7) even
    # though the registry rule says "p_yes already 0-1"; a percent
    # larger than 1 must be divided by 100 to restore the registered
    # 0-1 scale, never compared raw against model proportions.
    assert fm._arm_mean({"qid": "Q1", "n": 100, "p_yes": 73.7148}) == pytest.approx(
        0.737148
    )


def test_p_safe_percent_card_is_brought_back_to_0_1() -> None:
    assert fm._arm_mean({"qid": "Q1", "n": 100, "p_safe": 72.0}) == pytest.approx(0.72)


def test_dist_card_gives_share_choosing_option_1() -> None:
    value = {"n": 1051, "dist": {"1": {"pct": 69.1722}, "2": {"pct": 30.8278}}}
    assert fm._arm_mean(value) == pytest.approx(0.691722)


def test_per_statement_card_gives_statement_3_mean() -> None:
    value = {
        "per_statement": {
            "QID160_1": {"mean": 3.2303},
            "QID160_2": {"mean": 3.2634},
            "QID160_3": {"mean": 3.378},
        }
    }
    assert fm._arm_mean(value) == pytest.approx(3.378)


def test_per_trial_card_gives_mean_majority_share_0_1() -> None:
    value = {"per_trial_pct_majority": {"a": 90.0, "b": 70.0}}
    assert fm._arm_mean(value) == pytest.approx(0.80)


def test_per_item_card_gives_mean_of_item_means() -> None:
    value = {"per_item": {"i1": {"mean": 3.0}, "i2": {"mean": 4.0}}}
    assert fm._arm_mean(value) == pytest.approx(3.5)


def test_none_arm_value_gives_no_number() -> None:
    assert fm._arm_mean(None) is None


def _registry_with(name: str, arms: dict, contrasts: dict) -> dict:
    return {
        name: {
            "normalization_0_1": _spec(0, 1),
            "human": {
                "wave1_3": {"arms": arms, "contrasts": contrasts},
                "wave4": {"arms": arms, "contrasts": contrasts},
            },
        }
    }


def test_profile_row_computes_against_p_safe_cards() -> None:
    reg = _registry_with(
        "disease",
        {"gain": {"n": 10, "p_safe": 0.7}, "loss": {"n": 10, "p_safe": 0.3}},
        {},
    )
    llm = {
        "gpt-oss-20b": {"disease": {"blinded": {"means": {"gain": 0.7, "loss": 0.3}}}}
    }
    rows = fm.compute_error_rows(reg, llm)
    assert rows[0].profile_error_blinded == pytest.approx(0.0)


def test_contrast_pair_search_uses_numbers_not_dicts() -> None:
    # The production crash: _find_arm_pair subtracted two stat cards.
    pair = fm._find_arm_pair({"gain": 0.7, "loss": 0.3}, 0.4)
    assert pair is not None
    assert set(pair) == {"loss", "gain"}


def test_none_model_mean_gives_missing_row_not_crash() -> None:
    reg = _registry_with(
        "base_rate",
        {
            "30_engineers": {"n": 10, "mean": 52.2},
            "70_engineers": {"n": 10, "mean": 68.0},
        },
        {},
    )
    llm = {
        "gpt-oss-20b": {
            "base_rate": {
                "blinded": {"means": {"30_engineers": None, "70_engineers": None}}
            }
        }
    }
    rows = fm.compute_error_rows(reg, llm)
    assert rows[0].profile_error_blinded is None


def test_full_row_against_allais_dist_cards() -> None:
    arms = {
        "form1": {"n": 10, "dist": {"1": {"pct": 60.0}, "2": {"pct": 40.0}}},
        "form2": {"n": 10, "dist": {"1": {"pct": 40.0}, "2": {"pct": 60.0}}},
    }
    reg = _registry_with("allais", arms, {})
    llm = {
        "gpt-oss-20b": {"allais": {"blinded": {"means": {"form1": 0.6, "form2": 0.4}}}}
    }
    rows = fm.compute_error_rows(reg, llm)
    assert rows[0].profile_error_blinded == pytest.approx(0.0)


def test_full_row_against_prob_matching_cards() -> None:
    arms = {
        "problem1": {"per_trial_pct_majority": {"a": 80.0, "b": 60.0}},
        "problem2": {"per_trial_pct_majority": {"a": 60.0, "b": 40.0}},
    }
    reg = _registry_with("prob_matching", arms, {})
    llm = {
        "gpt-oss-20b": {
            "prob_matching": {
                "blinded": {"means": {"problem1": 0.70, "problem2": 0.50}}
            }
        }
    }
    rows = fm.compute_error_rows(reg, llm)
    assert rows[0].profile_error_blinded == pytest.approx(0.0)


def test_full_row_against_false_consensus_item_cards() -> None:
    arms = {"all": {"per_item": {"i1": {"mean": 3.0}, "i2": {"mean": 3.0}}}}
    reg = _registry_with("false_consensus", arms, {})
    llm = {"gpt-oss-20b": {"false_consensus": {"blinded": {"means": {"all": 3.0}}}}}
    rows = fm.compute_error_rows(reg, llm)
    assert rows[0].profile_error_blinded == pytest.approx(0.0)


def test_retest_band_survives_stat_cards() -> None:
    arms13 = {
        "gain": {"n": 10, "p_safe": 0.7},
        "loss": {"n": 10, "p_safe": 0.3},
    }
    arms4 = {"gain": {"n": 10, "p_safe": 0.6}, "loss": {"n": 10, "p_safe": 0.4}}
    reg = {
        "disease": {
            "normalization_0_1": _spec(0, 1),
            "human": {
                "wave1_3": {"arms": arms13, "contrasts": {}},
                "wave4": {"arms": arms4, "contrasts": {}},
            },
        }
    }
    band = fm.human_test_retest_errors(reg)
    assert band["disease"]["profile_error"] == pytest.approx(10.0)
