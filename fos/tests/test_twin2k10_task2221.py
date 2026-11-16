# TASK-2221 RED tests for the RATE-BASED preflight launch gate (tests
# ONLY — the rate gate does not exist yet, so the rate tests here fail
# on the current branch for the right reason: the feature is missing).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - A model PROCEEDs when at least 90% of its digit items pass the
#     0.5 digit-mass dominance gate (config.DIGIT_PASS_RATE_GATE).
#     Sub-threshold items no longer STOP the model by themselves: they
#     are recorded as WARN-flagged rows (item id + mass) so the
#     analysis can drop them.
#   - If a model's digit pass rate falls below 0.90, the model STOPs,
#     and the stop reason names the rate and the worst items.
#   - The absolute STOPs are untouched and never rate-tolerated: an
#     all-None digit p_raw, an empty top_logprobs at the decision
#     token, and a choice record with no readable answer letter each
#     stop the model at ANY pass rate (data integrity, not quality).
#   - The verdict carries per-model digit_pass_rate and a flagged-rows
#     list, machine-readable, and write_outputs stamps both into
#     preflight_verdict.json in the run directory.
#
# All offline: pure functions over synthetic record dicts; no network.

import json
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import config, preflight  # noqa: E402


def _entry(token: str, prob: float) -> dict:
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": math.log(prob)}


def _digit_item(qid: str, digit_mass: float, row: int = 1) -> dict:
    """One digit item that passes/fails the 0.5 dominance gate (helper)."""
    strong = digit_mass >= config.DIGIT_MASS_PREFLIGHT_THRESHOLD
    top_k = ([_entry("7", digit_mass)] if strong
             else [_entry("The", 0.9)])
    p_raw = {digit: None for digit in "0123456789"}
    if strong:
        p_raw["7"] = digit_mass
    return {
        "qid": qid, "row": row, "statement": None,
        "top_logprobs": top_k,
        "decision_position": 4,
        "p_raw": p_raw,
        "digit_mass": digit_mass,
    }


def _digit_record(items: list, model: str = "m") -> dict:
    """A preflight record for one model carrying these digit items."""
    return {"experiment": "false_consensus", "arm": "all", "model": model,
            "persona_id": 0, "blind": "blinded",
            "digit_items": items}


def _rate_record(n_strong: int, n_weak: int, model: str = "m") -> dict:
    """One model's record with n_strong dominant + n_weak sub-gate items."""
    items = [_digit_item(f"QID{100 + i}", 0.9, row=i + 1)
             for i in range(n_strong)]
    items += [_digit_item(f"QID{900 + i}", 0.07, row=50 + i)
              for i in range(n_weak)]
    return _digit_record(items, model=model)


# ---------------------------------------------------------------------------
# Contract 1 — the config knob DIGIT_PASS_RATE_GATE = 0.90
# ---------------------------------------------------------------------------


def test_digit_pass_rate_gate_knob_is_090() -> None:
    """The rate gate is a named config knob, 0.90."""
    assert config.DIGIT_PASS_RATE_GATE == 0.90


# ---------------------------------------------------------------------------
# Contract 2 — rate >= gate: PROCEED, sub-gate items become flagged rows
# ---------------------------------------------------------------------------


def test_two_failed_digit_items_out_of_ninety_proceed_with_flags() -> None:
    """88 of 90 digit items dominant: the model PROCEEDs but is flagged.

    The two sub-gate items must NOT stop the model; they must be
    recorded as flagged rows naming the item id and its mass so the
    analysis can drop them.
    """
    record = _rate_record(n_strong=88, n_weak=2)
    verdict = preflight.decide([record])
    assert verdict["stop"] is False, verdict["reasons"]
    flagged = verdict["per_model"]["m"]["flagged"]
    assert len(flagged) == 2, flagged
    assert all(row["digit_mass"] == pytest.approx(0.07) for row in flagged)
    assert all(str(row["qid"]).startswith("QID9") for row in flagged), (
        "each flagged row must name its digit item's id"
    )


def test_eight_failed_digit_items_out_of_ninety_proceed_with_flags() -> None:
    """82 of 90 dominant is a 0.911 rate — above the 0.90 gate: PROCEED.

    (The task example calls this case a STOP, but 82/90 = 0.911 >= 0.90,
    so the contract formula makes it a PROCEED with flags; this test
    pins the formula, not the example.)
    """
    record = _rate_record(n_strong=82, n_weak=8)
    verdict = preflight.decide([record])
    assert verdict["stop"] is False, verdict["reasons"]
    assert len(verdict["per_model"]["m"]["flagged"]) == 8


def test_ten_failed_digit_items_out_of_ninety_stop_naming_the_rate() -> None:
    """80 of 90 dominant is a 0.889 rate — below the gate: STOP.

    The stop reason must name the failing rate (0.889 or 80/90) and the
    worst items (their ids and masses).
    """
    record = _rate_record(n_strong=80, n_weak=10)
    verdict = preflight.decide([record])
    assert verdict["stop"] is True
    reason = "\n".join(verdict["reasons"])
    assert "0.89" in reason or "0.889" in reason or "80/90" in reason, (
        f"the stop reason must name the pass rate; got: {reason}"
    )
    assert "QID900" in reason, (
        "the stop reason must name the worst failing items"
    )


def test_perfect_rate_with_no_failures_proceeds_cleanly() -> None:
    """All digit items dominant: PROCEED, no flags, no reasons."""
    verdict = preflight.decide([_rate_record(n_strong=10, n_weak=0)])
    assert verdict["stop"] is False
    assert verdict["reasons"] == []
    assert verdict["per_model"]["m"]["flagged"] == []
    assert verdict["per_model"]["m"]["digit_pass_rate"] == pytest.approx(1.0)


def test_rates_are_computed_per_model_not_per_batch() -> None:
    """One weak model must not stop a healthy model (and vice versa).

    Model "weak" fails 20 of 100 items (rate 0.80 < 0.90 → STOP);
    model "healthy" fails 2 of 100 (rate 0.98 → PROCEED with flags).
    The batch verdict stops because of the weak model only.
    """
    records = [_rate_record(98, 2, model="healthy"),
               _rate_record(80, 20, model="weak")]
    verdict = preflight.decide(records)
    assert verdict["stop"] is True
    assert any("weak" in reason for reason in verdict["reasons"])
    assert not any("healthy" in reason for reason in verdict["reasons"]), (
        "a model above the rate gate must not be stop-flagged"
    )
    assert verdict["per_model"]["healthy"]["digit_pass_rate"] == (
        pytest.approx(0.98)
    )
    assert verdict["per_model"]["weak"]["digit_pass_rate"] == (
        pytest.approx(0.80)
    )


# ---------------------------------------------------------------------------
# Contract 3 — absolute STOPs never rate-tolerate
# ---------------------------------------------------------------------------


def test_all_none_digit_distribution_with_real_text_is_a_rate_failure() -> None:
    """An all-None digit p_raw with REAL top_logprobs text is a MODEL

    failure, not a transport failure: it is flagged and counted as a
    FAILING digit item in the pass rate. AMENDED per owner policy
    (2026-09-22, "90% rate gate, all 15"): the pre-2026-09-22 version
    of this test wrongly forced an absolute STOP. Here the degenerate
    item (digit_mass 1.0, top_logprobs text present) makes 99 pass + 1
    fail out of 100 — rate 0.99 >= the 0.90 gate — so the model must
    PROCEED with QID168 flagged.
    """
    degenerate = {
        "qid": "QID168", "row": 1, "statement": None,
        "top_logprobs": [_entry("379", 0.6)],
        "decision_position": 1,
        "p_raw": {digit: None for digit in "0123456789"},
        "digit_mass": 1.0,
    }
    record = _rate_record(n_strong=99, n_weak=0)
    record["digit_items"].append(degenerate)
    verdict = preflight.decide([record])
    assert verdict["stop"] is False, (
        "an all-None digit p_raw with real top_logprobs text is a "
        "model-behavior failure: rate-gated and flagged, never a STOP"
    )
    per_model = verdict["per_model"]["m"]
    assert per_model["digit_pass_rate"] == pytest.approx(99 / 100), (
        "the all-None item must be COUNTED as a failing digit item"
    )
    flagged_qids = [row["qid"] for row in per_model["flagged"]]
    assert "QID168" in flagged_qids, (
        "the all-None item must appear among the flagged rows"
    )


def test_enough_all_none_rows_drop_the_rate_below_the_gate_and_stop() -> None:
    """All-None model failures CAN still stop the model — via the rate.

    Fifteen all-None digit items (real top_logprobs text each) among
    85 healthy items give a rate of 85/100 = 0.85 < 0.90: the model
    STOPs because of the RATE, and the reason names it.
    """
    record = _rate_record(n_strong=85, n_weak=0)
    for i in range(15):
        record["digit_items"].append({
            "qid": f"QID{500 + i}", "row": 200 + i, "statement": None,
            "top_logprobs": [_entry("379", 0.6)],
            "decision_position": 1,
            "p_raw": {digit: None for digit in "0123456789"},
            "digit_mass": 1.0,
        })
    verdict = preflight.decide([record])
    assert verdict["stop"] is True, (
        "a 0.85 rate driven by all-None model failures is below the gate"
    )
    reason = "\n".join(verdict["reasons"])
    assert "0.85" in reason or "85/100" in reason, (
        f"the stop reason must name the failing rate; got: {reason}"
    )
    assert "QID500" in reason, (
        "the stop reason must name the failing all-None items"
    )


def test_empty_top_logprobs_on_digit_item_stops_even_at_a_high_rate() -> None:
    """Empty top_logprobs at the decision token is a TRANSPORT failure:

    an absolute STOP regardless of the pass rate (owner policy
    2026-09-22). Unlike the all-None model failure, this is never
    rate-tolerated.
    """
    broken = {
        "qid": "QID170", "row": 2, "statement": None,
        "top_logprobs": [],
        "p_raw": {digit: None for digit in "0123456789"},
        "digit_mass": 0.0, "decision_position": 1,
    }
    record = _rate_record(n_strong=99, n_weak=0)
    record["digit_items"].append(broken)
    verdict = preflight.decide([record])
    assert verdict["stop"] is True
    assert any("QID170" in reason for reason in verdict["reasons"])


def test_missing_choice_letter_stops_even_at_a_high_rate() -> None:
    """A choice record with no readable answer letter is an absolute STOP.

    The rate gate only softens the digit-mass DOMINANCE check; the
    choice-path letter check never rate-tolerates.
    """
    letterless = {
        "experiment": "allais", "arm": "form1", "model": "m",
        "persona_id": 0, "blind": "blinded",
        "top_logprobs": [_entry("A", 0.7), _entry("B", 0.2)],
        "p_raw": {"A": None, "B": None},
    }
    record = _rate_record(n_strong=99, n_weak=0, model="m")
    verdict = preflight.decide([record, letterless])
    assert verdict["stop"] is True
    assert any("letter" in reason for reason in verdict["reasons"])


def test_empty_top_logprobs_on_choice_record_stops_at_a_high_rate() -> None:
    """The GGUF signature on a choice record is an absolute STOP too."""
    broken = {
        "experiment": "allais", "arm": "form1", "model": "m",
        "persona_id": 0, "blind": "blinded", "top_logprobs": [],
    }
    verdict = preflight.decide([_rate_record(99, 0, model="m"), broken])
    assert verdict["stop"] is True


# ---------------------------------------------------------------------------
# Contract 4 — verdict schema carries rate + flagged rows, machine-
# readable, and preflight_verdict.json is written
# ---------------------------------------------------------------------------


def test_verdict_carries_per_model_rate_and_flagged_rows() -> None:
    """decide() stamps machine-readable per-model rate + flagged rows."""
    verdict = preflight.decide([_rate_record(88, 2)])
    per_model = verdict["per_model"]["m"]
    assert per_model["digit_pass_rate"] == pytest.approx(88 / 90)
    assert len(per_model["flagged"]) == 2
    for row in per_model["flagged"]:
        assert "qid" in row and "digit_mass" in row


def test_write_outputs_writes_preflight_verdict_json(tmp_path) -> None:
    """write_outputs stamps per-model rate + flagged rows to a JSON file.

    The machine-readable verdict lands in preflight_verdict.json in the
    run directory, carrying each model's digit_pass_rate and flagged
    rows.
    """
    per_model = {"m": [_rate_record(88, 2)]}
    verdict = preflight.decide([_rate_record(88, 2)])
    preflight.write_outputs(tmp_path, per_model,
                            {"m": verdict["reasons"]})
    payload = json.loads(
        (tmp_path / "preflight_verdict.json").read_text(encoding="utf-8")
    )
    entry = payload["per_model"]["m"]
    assert entry["digit_pass_rate"] == pytest.approx(88 / 90)
    assert len(entry["flagged"]) == 2


def test_report_records_warn_flagged_rows_for_a_proceeding_model(tmp_path
                                                                ) -> None:
    """A PROCEEDing model with sub-gate items shows its flags in the md.

    The report line for the model names its digit pass rate, and the
    flagged rows (item id + mass) are listed so the analysis can drop
    them.
    """
    record = _rate_record(88, 2)
    per_model = {"m": [record]}
    verdict = preflight.decide([record])
    report = preflight.build_report(tmp_path, per_model, {})
    assert "0.978" in report, "the report must name the model's pass rate"
    assert "QID900" in report, "flagged rows must appear in the report"
    assert "WARN" in report or "flagged" in report
