# Tests for the TASK-2402 outcome rules in llm_arm_means (the experiments
# TASK-2401 did not cover). Fixtures use the REAL records.jsonl schema:
# one JSON object per record with p_norm over answer letters and/or
# digit_items with p_norm over digit tokens.

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from twin2k10 import llm_arm_means  # noqa: E402

MODEL = "test-model"


def _choice_record(experiment: str, arm: str, p_norm: dict) -> dict:
    """A record shaped like the real letter-choice records."""
    return {
        "model_id": f"openai/{MODEL}",
        "model": MODEL,
        "experiment": experiment,
        "arm": arm,
        "blind": "blinded",
        "succeeded": True,
        "qid": "QID1",
        "qids": ["QID1"],
        "label_map": {},
        "p_norm": p_norm,
        "digit_items": [],
    }


def _digit_record(experiment: str, arm: str, items: list[dict]) -> dict:
    """A record shaped like the real digit_items records."""
    return {
        "model_id": f"openai/{MODEL}",
        "model": MODEL,
        "experiment": experiment,
        "arm": arm,
        "blind": "blinded",
        "succeeded": True,
        "qid": "QID1",
        "qids": ["QID1"],
        "label_map": {},
        "digit_items": items,
    }


def _digit_item(row: int | None, p_norm: dict) -> dict:
    return {"qid": "QID1", "row": row, "p_norm": p_norm, "succeeded": True}


def test_fire_extinguisher_mean_is_expected_letter_code_1_to_5():
    # Mass 0.5 on "D" (code 4) and 0.5 on "E" (code 5) -> mean 4.5.
    record = _choice_record(
        "fire_extinguisher", "high", {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.5, "E": 0.5}
    )
    assert llm_arm_means._record_outcome(record, "fire_extinguisher") == 4.5


def test_seatbelt_mean_is_expected_letter_code_1_to_6():
    # Half "A" (1) and half "F" (6) -> 3.5.
    record = _choice_record("seatbelt", "low", {"A": 0.5, "F": 0.5})
    assert llm_arm_means._record_outcome(record, "seatbelt") == 3.5


def test_sunk_cost_letters_map_to_0_to_20_purchases():
    # "A" is 0 purchases, "U" is 20; half each -> 10.
    record = _choice_record("sunk_cost", "sunk", {"A": 0.5, "U": 0.5})
    assert llm_arm_means._record_outcome(record, "sunk_cost") == 10.0


def test_wta_wtp_bracket_index_is_ordinal_1_to_10():
    # "C" is bracket 3; full mass -> 3.0 (dollar means are not implied).
    record = _choice_record("wta_wtp", "high", {"C": 1.0})
    assert llm_arm_means._record_outcome(record, "wta_wtp") == 3.0


def test_abs_relative_p_yes_is_mass_on_letter_a():
    record = _choice_record("abs_relative", "control", {"A": 0.25, "B": 0.75})
    assert llm_arm_means._record_outcome(record, "abs_relative") == 0.25


def test_anchoring_arm_statistic_is_anchor_choice_mass_on_a():
    record = _choice_record("anchoring_redwood", "high", {"A": 0.8, "B": 0.2})
    assert llm_arm_means._record_outcome(record, "anchoring_redwood") == 0.8
    assert llm_arm_means._record_outcome(record, "anchoring_african") == 0.8


def test_false_consensus_is_mean_over_items_restricted_to_1_to_5():
    # Item 1: E[digit|1-5] = 4.0; item 2: full mass on 2 -> 2.0; mean 3.0.
    # A "0" mass on item 2 is off-scale noise and must be dropped.
    items = [_digit_item(1, {"4": 0.9, "6": 0.1}), _digit_item(2, {"0": 0.5, "2": 0.5})]
    record = _digit_record("false_consensus", "own", items)
    assert llm_arm_means._record_outcome(record, "false_consensus") == 3.0


def test_outcome_bias_and_myside_use_their_own_letter_ranges():
    bias = _choice_record("outcome_bias", "outcome", {"A": 1.0})
    my = _choice_record("myside", "own", {"F": 1.0})
    assert llm_arm_means._record_outcome(bias, "outcome_bias") == 1.0
    assert llm_arm_means._record_outcome(my, "myside") == 6.0


def test_base_rate_estimate_stays_none_with_records_counted():
    # The 0-100 estimate is unrecoverable from first-digit mass; the arm
    # mean stays None (registry NEEDS-OWNER) but the record still counts.
    record = _digit_record(
        "base_rate", "30_engineers", [_digit_item(None, {"0": 0.5, "5": 0.5})]
    )
    assert llm_arm_means._record_outcome(record, "base_rate") is None


def test_new_rules_survive_a_build_roundtrip(tmp_path):
    """End-to-end: a registry subset with seatbelt only yields per-arm
    means through build_llm_arm_means (real directory layout)."""
    leg = tmp_path / MODEL / "seatbelt_blinded"
    leg.mkdir(parents=True)
    records = [
        _choice_record("seatbelt", "low", {"A": 1.0}),
        _choice_record("seatbelt", "high", {"F": 1.0}),
    ]
    with open(leg / "records.jsonl", "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    registry = {
        "experiments": {
            "seatbelt": {
                "run": "run6",
                "leg_path_pattern": str(tmp_path)
                + "/{model}/{seatbelt_blinded,unblinded}"
                "/records.jsonl",
                "arm_roles": {"low": "comparison", "high": "treatment"},
            }
        }
    }
    result = llm_arm_means.build_llm_arm_means(registry, {"run6": tmp_path})
    means = result[MODEL]["seatbelt"]["blinded"]["means"]
    assert means == {"low": 1.0, "high": 6.0}
