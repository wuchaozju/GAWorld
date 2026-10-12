# This file turns model answers into numbers, two ways. (1) Choice AND
# digit scoring is exactly twin2k6's folding machinery: an answer token
# folds only its four spellings ("A", " A", "a", " a" — a digit's
# lowercase forms equal its bare forms, so "1" folds "1" and " 1"),
# punctuation/prose look-alikes never fold, entries under the
# one-in-a-million floor are sampler noise, a missing label stays
# explicitly None (never a faked 0.0), the found labels' raw
# probabilities sum into the branch mass, and a mass under 0.80 is
# flagged. The label list to fold toward comes either from the
# experiment's choice letters or from the caller's explicit labels=
# (the digit labels of one first-token item). (2) parse_numeric pulls
# the number out of messy model prose ("about 15,000 feet" -> 15000,
# "$5,000,000" -> 5000000) and returns None — never an exception, never
# 0 — when there is no number.

import math
import re

from logprob_scoring import _logprob_from_entry, _token_from_entry

from twin2k10 import config, experiments

# One number with optional thousands commas and optional decimals. The
# match is searched anywhere in the text, so "about 15,000 feet" works.
NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def fold_label_tokens(letter: str) -> frozenset[str]:
    """The exact token spellings that count as one answer letter.

    Exactly four forms: bare, space-glued, lowercase, and space-glued
    lowercase ("A", " A", "a", " a"). Nothing else — not "A.", "(A",
    "Answer" — ever folds into a letter.
    """
    return frozenset(
        {
            letter,
            f" {letter}",
            letter.lower(),
            f" {letter.lower()}",
        }
    )


def _stripped_form_to_letter(letters) -> dict[str, str]:
    """Map each stripped fold spelling to its canonical uppercase letter.

    The fold forms compared after stripping are the bare letter and its
    lowercase twin, so the lookup has one entry per letter per case.
    """
    lookup: dict[str, str] = {}
    for letter in letters:
        lookup[letter] = letter
        lookup[letter.lower()] = letter
    return lookup


def _raw_letter_probabilities(top_logprobs, lookup: dict[str, str]) -> dict[str, float]:
    """Sum the raw probabilities each letter collects from one top-k list.

    Walks the entries with the proven R1 helpers (token text and logprob
    across the known key names), skips entries under the visibility floor,
    strips each token and adds its probability to the letter it folds to.
    Letters never seen stay absent from the returned dict.
    """
    raw: dict[str, float] = {}
    for entry in top_logprobs or []:
        token = _token_from_entry(entry)
        if token is None:
            continue
        logprob = _logprob_from_entry(entry, token)
        if logprob is None:
            continue
        probability = math.exp(logprob)
        if probability < config.PROBABILITY_FLOOR:
            continue  # numerically-zero top-k noise, never an answer form
        letter = lookup.get(token.strip())
        if letter is not None:
            raw[letter] = raw.get(letter, 0.0) + probability
    return raw


def _normalized(
    p_raw: dict[str, float | None], branch_mass: float, letters
) -> dict[str, float | None]:
    """Divide each found letter's raw probability by the branch mass.

    With zero mass (no letter appeared at all) every normalized probability
    stays None — there is no distribution to normalize.
    """
    if branch_mass == 0.0:
        return {letter: None for letter in letters}
    return {
        letter: (value / branch_mass if value is not None else None)
        for letter, value in p_raw.items()
    }


def score_labels(
    top_logprobs: list[dict],
    experiment: str,
    decision_position: int | None = None,
    skipped_prefix: list | None = None,
    skipped_len: int | None = None,
    labels: tuple[str, ...] | None = None,
) -> dict:
    """Score one decision-position top-logprob list into a distribution.

    Folds the top-k entries toward the given label list: the caller's
    explicit labels (a first-token item's own choice letters or digit
    labels) when supplied, otherwise the experiment's choice letters.
    Returns the record's scoring fields: p_raw / p_norm (every label,
    None when it never appeared), branch_mass (the found labels' summed
    raw probability), the low_branch_mass flag (mass strictly below
    0.80), and the untouched audit fields (the full top_logprobs array,
    decision_position, skipped_prefix, skipped_len). A digit item scores
    through exactly this path — its record payload is byte-for-byte the
    choice shape. Raises KeyError for an unknown experiment and
    ValueError when no labels are given and the experiment has no choice
    question.
    """
    fold_targets = (
        tuple(labels) if labels is not None else experiments.label_letters(experiment)
    )
    lookup = _stripped_form_to_letter(fold_targets)
    raw = _raw_letter_probabilities(top_logprobs, lookup)
    p_raw: dict[str, float | None] = {label: raw.get(label) for label in fold_targets}
    branch_mass = float(sum(raw.values()))
    return {
        "p_raw": p_raw,
        "p_norm": _normalized(p_raw, branch_mass, fold_targets),
        "branch_mass": branch_mass,
        "low_branch_mass": branch_mass < config.LOW_BRANCH_MASS_THRESHOLD,
        "top_logprobs": top_logprobs,
        "decision_position": decision_position,
        "skipped_prefix": skipped_prefix,
        "skipped_len": skipped_len,
    }


def _leading_digit_mass(top_logprobs: list[dict]) -> dict[str, float]:
    """One position's per-digit probabilities, keyed by leading digit.

    A token counts toward a digit when its text (stripped) STARTS with
    that digit — "7" and " 7" count toward "7", and multi-digit number
    tokens like "30" or " 15" count toward their LEADING digit ("3",
    "1"). Prose tokens ("The", " to") contribute nothing. Entries under
    the visibility floor are top-k noise and never count.
    """
    raw: dict[str, float] = {}
    for entry in top_logprobs or []:
        token = _token_from_entry(entry)
        if token is None:
            continue
        logprob = _logprob_from_entry(entry, token)
        if logprob is None:
            continue
        probability = math.exp(logprob)
        if probability < config.PROBABILITY_FLOOR:
            continue  # numerically-zero top-k noise, never an answer form
        stripped = token.strip()
        if stripped and stripped[0].isdigit():
            raw[stripped[0]] = raw.get(stripped[0], 0.0) + probability
    return raw


def scan_digit_positions(
    position_top_logprobs: list[list[dict]], labels: tuple[str, ...]
) -> dict:
    """Scan every generated position and read the digit from the best one.

    position_top_logprobs is ONE top-k list per generated position
    (index 0 = position 1). Each position's digit mass is the summed
    probability of its digit-starting tokens; the position with the
    MAXIMUM mass wins (a tie goes to the EARLIEST position). Returns the
    digit item's scan fields: decision_position (1-based), p_raw / p_norm
    from THAT position (every label, None when it never appeared), and
    digit_mass (the chosen position's total digit mass).
    """
    best_mass = -1.0
    best_raw: dict[str, float] = {}
    best_position: int | None = None
    for index, top_logprobs in enumerate(position_top_logprobs or []):
        raw = _leading_digit_mass(top_logprobs)
        mass = float(sum(raw.values()))
        if mass > best_mass:
            best_mass, best_raw, best_position = mass, raw, index + 1
    p_raw: dict[str, float | None] = {label: best_raw.get(label) for label in labels}
    return {
        "decision_position": best_position,
        "p_raw": p_raw,
        "p_norm": _normalized(p_raw, max(best_mass, 0.0), labels),
        "digit_mass": max(best_mass, 0.0),
    }


def parse_numeric(text: str | None) -> float | int | None:
    """The first number in a model's prose, or None when there is none.

    Understands thousands commas ("15,000"), currency ("$5,000,000") and
    decimals ("3.5"); whole numbers come back as int. Unparseable text
    ("I cannot say", "") returns None — never an exception, never 0, so
    a missing number is always distinguishable from the answer zero.
    """
    if not text:
        return None
    match = NUMBER_PATTERN.search(text.replace("$", ""))
    if match is None:
        return None
    value = float(match.group().replace(",", ""))
    return int(value) if value.is_integer() else value
