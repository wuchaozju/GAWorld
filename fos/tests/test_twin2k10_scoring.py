# Locked tests for the twin2k10 study's scoring module (TASK-2139 RED
# phase; digit contract amended by the TASK-2182 design pivot).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - Choice scoring is exactly twin2k6's: a letter folds only its four
#     spellings ("A", " A", "a", " a"), punctuation/prose look-alikes
#     never fold, entries under the 1-in-a-million floor are noise, a
#     missing letter stays None (never a faked 0.0), the branch mass is
#     the sum over found letters, and the 0.80 low-mass flag matches.
#   - Free-text numeric answers are still read out of messy prose for
#     anchoring-style single numbers: "about 15,000 feet" -> 15000,
#     "$5,000,000" -> 5000000, "3.5" -> 3.5; text with no number parses
#     to None.
#   - TASK-2182 pivot: EVERY numeric answer is now scored from ONE
#     deterministic first-token call — digit labels fold with exactly the
#     same machinery as choice letters (a 1–5 rating folds "1"/" 1" the
#     way "A" folds "A"/" A"/"a"/" a"), and a digit record carries the
#     exact same payload shape a choice record carries. The K=20
#     temperature-sampling era and its multi-row free-text parser are
#     gone (their deletion is pinned in test_twin2k10_config.py).
#
# All offline: pure functions over synthetic strings and top-k lists.
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import config, experiments, scoring  # noqa: E402


def _entry(token: str, prob: float) -> dict:
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": math.log(prob)}


def test_letter_folding_is_identical_to_twin2k6() -> None:
    """Every letter A-G folds exactly twin2k6's four spellings."""
    from twin2k6 import scoring as k6_scoring

    for letter in "ABCDEFG":
        assert scoring.fold_label_tokens(letter) \
            == k6_scoring.fold_label_tokens(letter)
    assert scoring.fold_label_tokens("A") == frozenset(
        {"A", " A", "a", " a"}
    )


def test_lookalike_tokens_never_fold_into_a_letter() -> None:
    """Punctuation glue and prose must never count as an answer letter."""
    for impostor in ("(A", "A.", "Answer", "=A", "A)"):
        for letter in "ABCDEFG":
            assert impostor not in scoring.fold_label_tokens(letter)


def test_floor_and_threshold_equal_twin2k6s_choice_scoring() -> None:
    """The visibility floor (1e-6) and the 0.80 low-mass flag are shared."""
    from twin2k6 import config as k6_config

    assert config.PROBABILITY_FLOOR == k6_config.PROBABILITY_FLOOR == 1e-6
    assert config.LOW_BRANCH_MASS_THRESHOLD \
        == k6_config.LOW_BRANCH_MASS_THRESHOLD == 0.80


def test_allais_scoring_keeps_missing_letters_none_and_sums_the_mass() -> None:
    """A two-letter choice: found letter scored, missing letter None."""
    top_k = [
        _entry("A", 0.55),
        _entry(" a", 0.30),      # second spelling folds into A (mass 0.85)
        _entry("(B", 0.10),      # impostor — must NOT fold into B
        _entry("Answer", 0.05),  # prose — never folds
        _entry("B", 1e-9),       # below the floor — B stays missing
    ]
    record = scoring.score_labels(top_k, "allais", decision_position=1,
                                  skipped_prefix=[], skipped_len=0)
    assert record["p_raw"]["A"] == pytest.approx(0.85)
    assert record["p_raw"]["B"] is None
    assert record["branch_mass"] == pytest.approx(0.85)
    assert record["p_norm"]["A"] == pytest.approx(1.0)
    assert record["p_norm"]["B"] is None
    assert record["low_branch_mass"] is False
    assert record["top_logprobs"] == top_k
    assert record["decision_position"] == 1


def test_low_branch_mass_flags_below_080() -> None:
    """A combined letter mass under 0.80 is flagged, at 0.80 it is not."""
    at_threshold = scoring.score_labels(
        [_entry("A", 0.80)], "allais", decision_position=0,
        skipped_prefix=[], skipped_len=0,
    )
    below = scoring.score_labels(
        [_entry("A", 0.79)], "allais", decision_position=0,
        skipped_prefix=[], skipped_len=0,
    )
    assert at_threshold["low_branch_mass"] is False
    assert below["low_branch_mass"] is True


def test_parse_numeric_reads_numbers_out_of_messy_prose() -> None:
    """The three pinned formats: comma thousands, currency, decimal."""
    assert scoring.parse_numeric("about 15,000 feet") == 15000
    assert scoring.parse_numeric("$5,000,000") == 5000000
    assert scoring.parse_numeric("3.5") == 3.5


def test_parse_numeric_returns_none_when_there_is_no_number() -> None:
    """Text without any number parses to None — never an exception, never 0."""
    assert scoring.parse_numeric("I cannot say") is None
    assert scoring.parse_numeric("") is None


# ---------------------------------------------------------------------------
# TASK-2182 design pivot — digit labels fold exactly like choice letters.
# There is no separate digit rule: fold_label_tokens builds the same
# four-form set for a digit as for a letter (a digit's lowercase forms
# equal its bare forms, so the set has the two spellings "1" and " 1"),
# and score_labels accepts the record's own label list so a digit item's
# distribution is stored exactly like a choice letter distribution.
# ---------------------------------------------------------------------------


def test_digit_labels_fold_with_the_same_machinery_as_choice_letters() -> None:
    """A digit folds the same spellings the choice folder builds."""
    for digit in "0123456789":
        assert scoring.fold_label_tokens(digit) \
            == frozenset({digit, f" {digit}"}), digit
    # Same function, not a digit-specific twin.
    assert scoring.fold_label_tokens("1") == frozenset({"1", " 1"})


def test_digit_lookalike_tokens_never_fold_into_a_digit() -> None:
    """Punctuation glue and spelled-out words never count as a digit."""
    for impostor in ("1.", "(1", "1)", "=1", "one", "Support"):
        assert impostor not in scoring.fold_label_tokens("1"), impostor


def test_score_labels_scores_digit_labels_exactly_like_choice_letters() -> None:
    """A 1–5 rating folds from one top-k list exactly like a letter does.

    Space-glued spellings fold, look-alikes never fold, entries under the
    floor stay None, the branch mass sums only found digits, and the
    normalized probabilities divide by that mass.
    """
    top_k = [
        _entry("1", 0.55),
        _entry(" 3", 0.30),      # space-glued spelling folds into "3"
        _entry("(2", 0.10),      # impostor — must NOT fold into "2"
        _entry("Support", 0.05), # prose — never folds
        _entry("5", 1e-9),       # below the floor — "5" stays missing
    ]
    record = scoring.score_labels(
        top_k, "false_consensus", labels=("1", "2", "3", "4", "5"),
        decision_position=1, skipped_prefix=[], skipped_len=0,
    )
    assert record["p_raw"] == {
        "1": pytest.approx(0.55), "2": None, "3": pytest.approx(0.30),
        "4": None, "5": None,
    }
    assert record["branch_mass"] == pytest.approx(0.85)
    assert record["p_norm"]["1"] == pytest.approx(0.55 / 0.85)
    assert record["p_norm"]["3"] == pytest.approx(0.30 / 0.85)
    assert record["p_norm"]["2"] is None
    assert record["low_branch_mass"] is False
    assert record["decision_position"] == 1


def test_first_significant_digit_labels_span_zero_to_nine_in_order() -> None:
    """An anchoring-style estimate folds over the ten digit tokens 0-9."""
    top_k = [_entry("7", 0.9), _entry("8", 0.05), _entry("the", 0.05)]
    record = scoring.score_labels(
        top_k, "anchoring_redwood", labels=tuple("0123456789"),
        decision_position=0, skipped_prefix=[], skipped_len=0,
    )
    assert list(record["p_raw"]) == list("0123456789")
    assert record["p_raw"]["7"] == pytest.approx(0.9)
    assert record["p_raw"]["0"] is None
    assert record["branch_mass"] == pytest.approx(0.95)


def test_digit_record_payload_shape_is_exactly_the_choice_shape() -> None:
    """A digit record stores the same fields a choice record stores."""
    digit = scoring.score_labels(
        [_entry("3", 0.9)], "false_consensus",
        labels=("1", "2", "3", "4", "5"),
    )
    letter = scoring.score_labels([_entry("A", 0.9)], "allais")
    assert set(digit) == set(letter), (
        "digit records must store label/digit logprob distributions "
        "exactly like choice records — no extra, no missing fields"
    )


def test_explicit_labels_never_touch_the_choice_letter_table() -> None:
    """Scoring with labels= must work even with no choice question.

    false_consensus has no choice question at all, so the letter lookup
    raises — the labels= path must never read that table.
    """
    with pytest.raises(ValueError):
        experiments.label_letters("false_consensus")
    record = scoring.score_labels(
        [_entry("3", 0.9)], "false_consensus",
        labels=("1", "2", "3", "4", "5"),
    )
    assert record["p_raw"]["3"] == pytest.approx(0.9)
    assert record["low_branch_mass"] is False
