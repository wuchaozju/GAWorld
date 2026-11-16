# Locked tests for the twin2k6 study's first-token label scoring (TASK-2060
# RED phase; tests ONLY — no implementation lives here yet).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - A label letter folds exactly four spellings: "A", " A", "a", " a"
#     (compare with whitespace stripped). Prose look-alikes like "A.",
#     "Answer", "=A", "(A" NEVER fold, and a letter never absorbs another
#     letter's probability.
#   - score_labels turns one decision-position top-logprob list into the
#     record's scoring fields: per-letter raw probability (missing labels
#     stay None, never 0), branch mass (the sum over found letters),
#     per-letter normalized probability (raw / mass), the expected value
#     on the experiment's scale under its pinned outcome-field name, the
#     0.80 low-branch-mass flag, disease's p_safe (raw and normalized,
#     normalized is primary), and the untouched audit fields (full top
#     logprobs, decision position, skipped prefix/length).
#   - Entries under the 1-in-a-million probability floor are noise and
#     are ignored.
#
# All offline: pure functions over synthetic top-k lists; no network.
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import experiments, scoring  # noqa: E402


def _lp(prob):
    """Turn a probability into a top-k logprob entry value (helper)."""
    return math.log(prob)


def _entry(token, prob):
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": _lp(prob)}


# The worked example: a disease answer whose top-k carries every fold form,
# one punctuation-glue impostor for the missing E, prose, and a sub-floor E.
DISEASE_TOP_K = [
    _entry("A", 0.40),
    _entry("B", 0.20),
    _entry("b", 0.05),
    _entry("C", 0.10),
    _entry("D", 0.05),
    _entry("(E", 0.05),   # punctuation glue — must NOT fold into E
    _entry("F", 0.05),
    _entry("Answer", 0.02),   # prose — must never fold
    _entry("E", 1e-9),   # below the 1e-6 floor — noise, E stays missing
]
DISEASE_BRANCH_MASS = 0.40 + 0.20 + 0.05 + 0.10 + 0.05 + 0.05  # = 0.85


def _score(top_k, experiment, **kwargs):
    """score_labels with the audit fields every record must carry (helper)."""
    return scoring.score_labels(
        top_k,
        experiment,
        decision_position=kwargs.get("decision_position", 1),
        skipped_prefix=kwargs.get("skipped_prefix", []),
        skipped_len=kwargs.get("skipped_len", 0),
    )


def test_fold_forms_are_exactly_the_four_spellings():
    """Each letter folds only 'X', ' X', 'x', ' x' — nothing else."""
    for letter in ("A", "F", "J", "U"):
        forms = set(scoring.fold_label_tokens(letter))
        assert forms == {letter, f" {letter}", letter.lower(), f" {letter.lower()}"}, letter
        assert len(forms) == 4, letter


def test_prose_and_glue_tokens_never_fold():
    """'A.', 'Answer', '=A', '(A', 'not' contribute to no label ever."""
    top_k = [
        {"token": "A.", "logprob": -0.1},
        {"token": "Answer", "logprob": -0.2},
        {"token": "=A", "logprob": -0.3},
        {"token": "(A", "logprob": -0.4},
        {"token": "not", "logprob": -0.5},
        {"token": " a", "logprob": -0.6},  # the one spelling that DOES fold
    ]
    record = _score(top_k, "disease")
    assert record["p_raw"]["A"] == pytest.approx(math.exp(-0.6))
    assert record["branch_mass"] == pytest.approx(math.exp(-0.6))


def test_space_glued_and_case_forms_all_fold_to_the_same_letter():
    """'A', ' a', 'a', ' a' all count toward A; B never absorbs A's mass."""
    top_k = [
        _entry("A", 0.30),
        _entry(" a", 0.10),
        _entry("a", 0.05),
        _entry(" A", 0.05),
        _entry("B", 0.50),
    ]
    record = _score(top_k, "disease")
    assert record["p_raw"]["A"] == pytest.approx(0.50)
    assert record["p_raw"]["B"] == pytest.approx(0.50)


def test_entries_below_the_probability_floor_are_ignored():
    """Top-k noise under 1e-6 is not an answer — E stays missing above."""
    record = _score(DISEASE_TOP_K, "disease")
    assert record["p_raw"]["E"] is None
    assert record["branch_mass"] == pytest.approx(DISEASE_BRANCH_MASS)


def test_disease_worked_example_raw_normalized_and_expected():
    """The pinned 6-letter worked example, value by value."""
    record = _score(DISEASE_TOP_K, "disease")
    assert record["p_raw"] == {
        "A": pytest.approx(0.40), "B": pytest.approx(0.25),
        "C": pytest.approx(0.10), "D": pytest.approx(0.05),
        "E": None, "F": pytest.approx(0.05),
    }
    assert record["branch_mass"] == pytest.approx(0.85)
    assert record["p_norm"]["A"] == pytest.approx(0.40 / 0.85)
    assert record["p_norm"]["B"] == pytest.approx(0.25 / 0.85)
    assert record["p_norm"]["E"] is None
    assert record["expected_1_6"] == pytest.approx(2.0)


def test_disease_p_safe_raw_and_normalized_with_normalized_primary():
    """p_safe_raw = raw(A)+raw(B)+raw(C); p_safe_norm divides by the mass."""
    record = _score(DISEASE_TOP_K, "disease")
    assert record["p_safe_raw"] == pytest.approx(0.75)
    assert record["p_safe_norm"] == pytest.approx(0.75 / 0.85)
    # Primary = normalized-based p_safe: it must equal the normalized sum.
    assert record["p_safe_norm"] == pytest.approx(
        record["p_norm"]["A"] + record["p_norm"]["B"] + record["p_norm"]["C"]
    )


def test_every_experiment_writes_its_pinned_outcome_field():
    """expected_1_6 / expected_1_5 / expected_0_20 / expected_bracket_1_10."""
    cases = [
        ("less_is_more", [_entry("C", 0.4), _entry("D", 0.1)], "expected_1_5", 3.2),
        ("fire_extinguisher", [_entry("A", 0.25), _entry("E", 0.25)], "expected_1_5", 3.0),
        ("seatbelt", [_entry("F", 1.0)], "expected_1_6", 6.0),
        ("sunk_cost", [_entry("B", 0.6), _entry("C", 0.4)], "expected_0_20", 1.4),
        ("wta_wtp", [_entry("A", 0.5), _entry("C", 0.5)], "expected_bracket_1_10", 2.0),
    ]
    for exp_name, top_k, field, expected_value in cases:
        record = _score(top_k, exp_name)
        assert record[field] == pytest.approx(expected_value), exp_name


def test_sunk_cost_letter_values_start_at_zero():
    """Sunk cost A is worth 0 (not 1): all-A mass gives expected 0.0."""
    record = _score([_entry("A", 1.0)], "sunk_cost")
    assert record["expected_0_20"] == pytest.approx(0.0)


def test_probability_keys_cover_exactly_the_experiment_letters():
    """p_raw/p_norm carry every letter of the experiment — and only those."""
    record = _score(DISEASE_TOP_K, "disease")
    letters = set(experiments.EXPERIMENTS["disease"].label_letters)
    assert set(record["p_raw"].keys()) == letters
    assert set(record["p_norm"].keys()) == letters


def test_missing_labels_stay_none_and_never_become_zero():
    """A label absent from top-k is None in p_raw and p_norm — never 0.0."""
    record = _score([_entry("A", 1.0)], "seatbelt")
    assert record["p_raw"]["B"] is None
    assert record["p_norm"]["B"] is None
    assert record["p_raw"]["A"] == pytest.approx(1.0)
    assert record["p_norm"]["A"] == pytest.approx(1.0)


def test_zero_branch_mass_gives_none_probabilities_and_zero_expected():
    """When no letter appears: mass 0, every normalized p None, expected 0.0."""
    record = _score([_entry("Answer", 1.0)], "disease")
    assert record["branch_mass"] == 0.0
    assert all(value is None for value in record["p_norm"].values())
    assert record["expected_1_6"] == 0.0


def test_low_branch_mass_flag_uses_the_0_80_threshold():
    """Mass below 0.80 flags low; exactly 0.80 counts as covered (not low)."""
    low = _score([_entry("A", 0.5), _entry("B", 0.2)], "disease")
    assert low["branch_mass"] == pytest.approx(0.70)
    assert low["low_branch_mass"] is True
    exact = _score([_entry("A", 0.80)], "disease")
    assert exact["branch_mass"] == pytest.approx(0.80)
    assert exact["low_branch_mass"] is False
    covered = _score(DISEASE_TOP_K, "disease")
    assert covered["low_branch_mass"] is False


def test_audit_fields_pass_through_untouched():
    """The record keeps the full top-k array and the decision-position audit."""
    top_k = [{"token": "A", "logprob": -0.1}]
    record = scoring.score_labels(
        top_k, "disease",
        decision_position=5,
        skipped_prefix=["<|channel>", "thought"],
        skipped_len=2,
    )
    assert record["top_logprobs"] == top_k
    assert record["decision_position"] == 5
    assert record["skipped_prefix"] == ["<|channel>", "thought"]
    assert record["skipped_len"] == 2
