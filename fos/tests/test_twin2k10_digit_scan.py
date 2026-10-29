# Locked tests for the twin2k10 multi-position digit scan (TASK-2206 RED
# phase; tests ONLY — the scan itself does not exist yet, so every scan
# test here fails on current main for the right reason: the feature is
# missing, not a syntax error).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - Granite-style models write lead-in prose ("The", "To", "Given",
#     then digits at only ~4-5% probability mass) before answering a
#     digit item. The study must NOT read the digit from position 1: it
#     generates a deeper window (config.DIGIT_SCAN_TOKENS = 16 tokens
#     for digit-item calls; the choice window stays scan_tokens = 8),
#     computes each position's digit mass (the summed probability of
#     top-k tokens that START with a digit — "7", " 7", "30", " 15" all
#     count toward their LEADING digit), picks the position with the
#     MAXIMUM digit mass (ties go to the EARLIEST position), and reads
#     the digit distribution from THAT position.
#   - Preflight gate: a digit item passes only when the chosen
#     position's digit mass is at least 0.5 (dominant); otherwise the
#     existing STOP-with-reason path fires and the reason names the best
#     mass and its position ("digit mass 0.07 at best position 4").
#     Choice 1-5 items (false_consensus) use the same mechanism.
#   - skipped_prefix / skipped_len keep their current meaning (a
#     control-sequence prefix skip at position 1 only) and prompts are
#     UNCHANGED (owner decision) — the lock tests at the bottom pin that.
#
# All offline: pure functions over synthetic per-position top-k lists.

import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import config, legexec, preflight, prompts, scoring  # noqa: E402


def _entry(token: str, prob: float) -> dict:
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": math.log(prob)}


# ---------------------------------------------------------------------------
# TASK-2206 contract 1 — the config knob DIGIT_SCAN_TOKENS (default 16)
# ---------------------------------------------------------------------------


def test_digit_scan_tokens_knob_exists_and_defaults_to_16() -> None:
    """The digit-item generation window is a named config knob, 16."""
    assert config.DIGIT_SCAN_TOKENS == 16


def test_digit_mass_preflight_threshold_knob_is_05() -> None:
    """The preflight dominance gate is a named config knob, 0.5."""
    assert config.DIGIT_MASS_PREFLIGHT_THRESHOLD == 0.5


# ---------------------------------------------------------------------------
# TASK-2206 contract 2 — the multi-position scan in scoring
# ---------------------------------------------------------------------------


def _digit_scan(position_top_logprobs: list[list[dict]], labels) -> dict:
    """Call the scan with the contract's argument shape (helper).

    position_top_logprobs is ONE top-k list per generated position,
    index 0 = position 1. The implementer function name is part of this
    RED contract: scoring.scan_digit_positions.
    """
    return scoring.scan_digit_positions(position_top_logprobs,
                                        tuple(labels))


def test_scan_picks_the_max_digit_mass_position_not_position_one() -> None:
    """Digit mass peaking at position 4 wins over weak position-1 mass.

    Positions 1-3 carry Granite-style lead-in prose ("The", "to",
    "cost"); position 4 carries the real digit answer. The distribution
    must be read from position 4, never position 1.
    """
    positions = [
        [_entry("The", 0.9), _entry(" A", 0.05)],
        [_entry(" to", 0.8), _entry("the", 0.1)],
        [_entry(" cost", 0.7), _entry(" is", 0.2)],
        [_entry("7", 0.6), _entry(" 7", 0.2), _entry("3", 0.1)],
    ]
    result = _digit_scan(positions, "0123456789")
    assert result["decision_position"] == 4, (
        "the scan must read the digit from the max-mass position, not "
        "from position 1"
    )
    assert result["p_raw"]["7"] == pytest.approx(0.6 + 0.2)
    assert result["p_raw"]["3"] == pytest.approx(0.1)
    assert result["digit_mass"] == pytest.approx(0.9)


def test_scan_p_norm_is_the_chosen_position_digit_distribution() -> None:
    """p_norm divides the chosen position's digit probabilities by mass."""
    positions = [
        [_entry("To", 0.9)],
        [_entry(" 15", 0.4), _entry(" 30", 0.2), _entry("Given", 0.2)],
    ]
    result = _digit_scan(positions, "0123456789")
    assert result["decision_position"] == 2
    assert result["p_raw"]["1"] == pytest.approx(0.4)
    assert result["p_raw"]["3"] == pytest.approx(0.2)
    assert result["p_norm"]["1"] == pytest.approx(0.4 / 0.6)
    assert result["p_norm"]["3"] == pytest.approx(0.2 / 0.6)


def test_scan_tie_between_positions_takes_the_earliest() -> None:
    """Two positions with the same digit mass resolve to the earlier one."""
    top_k = [_entry("5", 0.5), _entry("2", 0.2)]
    result = _digit_scan([top_k, top_k], "0123456789")
    assert result["decision_position"] == 1


def test_scan_counts_multi_digit_number_tokens_by_leading_digit() -> None:
    """A "30" token counts toward digit "3", a "15" token toward "1"."""
    positions = [
        [_entry("The", 0.5)],
        [_entry("30", 0.3), _entry(" 15", 0.25), _entry("7", 0.2)],
    ]
    result = _digit_scan(positions, "0123456789")
    assert result["decision_position"] == 2
    assert result["p_raw"]["3"] == pytest.approx(0.3)
    assert result["p_raw"]["1"] == pytest.approx(0.25)
    assert result["p_raw"]["7"] == pytest.approx(0.2)


def test_scan_prose_only_positions_have_zero_digit_mass() -> None:
    """Positions with no digit-starting top-k token contribute nothing."""
    positions = [
        [_entry("The", 0.9), _entry("Given", 0.05)],
        [_entry("7", 0.5)],
    ]
    result = _digit_scan(positions, "0123456789")
    assert result["decision_position"] == 2
    assert result["digit_mass"] == pytest.approx(0.5)


def test_scan_returns_the_full_record_payload_shape() -> None:
    """The scan result carries the same audit keys a record stamps."""
    positions = [[_entry("7", 0.6)]]
    result = _digit_scan(positions, "0123456789")
    for key in ("decision_position", "p_raw", "p_norm", "digit_mass"):
        assert key in result, f"scan result must stamp {key}"
    assert result["decision_position"] == 1


# ---------------------------------------------------------------------------
# TASK-2206 contract 3 — the preflight digit-mass gate
# ---------------------------------------------------------------------------


def _digit_item_with_mass(labels, digit_mass: float, position: int = 4,
                          qid="QID287", row=1) -> dict:
    """One digit item whose scan found `digit_mass` at `position` (helper)."""
    weak = digit_mass < config.DIGIT_MASS_PREFLIGHT_THRESHOLD
    top_k = ([_entry("The", 0.9)] if weak
             else [_entry("7", digit_mass)])
    p_raw = {label: None for label in labels}
    if not weak:
        p_raw["7"] = digit_mass
    return {
        "qid": qid, "row": row, "statement": None,
        "top_logprobs": top_k,
        "decision_position": position,
        "p_raw": p_raw,
        "digit_mass": digit_mass,
    }


def _digit_record(item: dict) -> dict:
    """A record carrying one digit item (helper)."""
    return {"experiment": "false_consensus", "arm": "all", "model": "m",
            "persona_id": 0, "blind": "blinded",
            "digit_items": [item]}


def test_digit_item_below_half_mass_stops_with_mass_named() -> None:
    """digit mass < 0.5 at the best position is a technical failure."""
    item = _digit_item_with_mass("12345", 0.07, position=4)
    verdict = preflight.decide([_digit_record(item)])
    assert verdict["stop"] is True, (
        "a digit item whose best-position digit mass is below 0.5 must "
        "stop the run"
    )
    reason = verdict["reasons"][0]
    assert "0.07" in reason and "4" in reason, (
        f"the stop reason must name the best mass and its position; "
        f"got: {reason}"
    )


def test_digit_item_at_or_above_half_mass_proceeds() -> None:
    """digit mass >= 0.5 at the chosen position passes the gate."""
    item = _digit_item_with_mass("12345", 0.5, position=1)
    verdict = preflight.decide([_digit_record(item)])
    assert verdict["stop"] is False, verdict["reasons"]


def test_anchoring_estimate_item_same_mass_mechanism() -> None:
    """The 0-100 estimate item is gated by the same digit-mass rule."""
    weak = _digit_item_with_mass("0123456789", 0.05, position=2,
                                 qid="QID168")
    verdict = preflight.decide([_digit_record(weak)])
    assert verdict["stop"] is True
    assert "0.05" in verdict["reasons"][0]


def test_record_without_digit_mass_field_keeps_the_old_checks() -> None:
    """An item with no digit_mass field (legacy shape) is not gated."""
    labels = "12345"
    legacy = {
        "qid": "QID287", "row": 1, "statement": None,
        "top_logprobs": [_entry("1", 0.6), _entry("2", 0.3)],
        "p_raw": {label: 0.6 if label == "1" else None
                  for label in labels},
    }
    verdict = preflight.decide([_digit_record(legacy)])
    assert verdict["stop"] is False, verdict["reasons"]


# ---------------------------------------------------------------------------
# TASK-2206 contract 1 (executor side) — digit calls use the 16 window
# ---------------------------------------------------------------------------


def test_executor_builds_the_digit_scorer_with_the_16_window(monkeypatch
                                                             ) -> None:
    """Digit-item calls generate DIGIT_SCAN_TOKENS; choice stays 8.

    legexec must build the digit-item scorer with
    scan_tokens=config.DIGIT_SCAN_TOKENS while the choice scorer keeps
    scan_tokens=config.SCAN_TOKENS (8). The implementer function name is
    part of this RED contract: legexec.make_digit_scorer.
    """
    captured: list[dict] = []

    def fake_make_scorer(base_url, model_id, **kwargs):
        captured.append(kwargs)
        return lambda messages: {"succeeded": True}

    import twin2k10.legexec as legexec_module

    monkeypatch.setattr(legexec_module, "make_first_token_scorer",
                        fake_make_scorer)
    context = legexec.make_leg_context(
        "gpt-oss-20b", "http://127.0.0.1:8080", [])
    legexec.make_scorer(context)
    assert captured[-1]["scan_tokens"] == config.SCAN_TOKENS == 8
    legexec.make_digit_scorer(context)
    assert captured[-1]["scan_tokens"] == config.DIGIT_SCAN_TOKENS
    assert captured[-1]["top_k"] == config.TOP_K


# ---------------------------------------------------------------------------
# TASK-2206 contract 4+5 — locks: prefix skip meaning and prompts
# ---------------------------------------------------------------------------


def test_prompts_are_unchanged_by_the_digit_scan() -> None:
    """Lock: the pinned prompt texts survive the digit scan pivot."""
    assert prompts.BLINDED_SYSTEM_LINE == "You are a survey respondent."
    assert prompts.FINAL_INSTRUCTION == (
        "Answer with only the corresponding uppercase letter."
    )
    assert prompts.NUMERIC_INSTRUCTION == "Answer with a single number."
    assert "uniform" not in prompts.UNBLINDING_PARAGRAPH
    assert "equal probability" not in prompts.UNBLINDING_PARAGRAPH


def test_skipped_prefix_len_fields_keep_their_meaning() -> None:
    """Lock: score_labels still stamps skipped_prefix / skipped_len."""
    scored = scoring.score_labels([_entry("A", 0.9)], "allais",
                                  decision_position=1,
                                  skipped_prefix=["<|channel>"],
                                  skipped_len=1)
    assert scored["skipped_prefix"] == ["<|channel>"]
    assert scored["skipped_len"] == 1
