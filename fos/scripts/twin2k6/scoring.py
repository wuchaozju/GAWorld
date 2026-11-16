# This file turns one decision-position top-logprob list into a record's
# scoring numbers. A letter answer folds exactly four spellings ("A", " A",
# "a", " a" — compared with whitespace stripped), so punctuation-glued
# look-alikes like "(A" or prose like "Answer" never count. Entries below
# the one-in-a-million floor are sampler noise and are ignored. A letter
# absent from the top-k stays explicitly missing (None, never a faked 0.0);
# the found letters' raw probabilities are summed into the branch mass,
# each letter is normalized by that mass, and the expected value is the
# mass-weighted average of the letters' worths on the experiment's scale.
# The disease experiment additionally reports the probability of the "safe"
# side (letters A, B, C = the Program-A options), raw and normalized.

import math

from logprob_scoring import _logprob_from_entry, _token_from_entry

from twin2k6 import config, experiments


def fold_label_tokens(letter: str) -> frozenset[str]:
    """The exact token spellings that count as one answer letter.

    Exactly four forms: bare, space-glued, lowercase, and space-glued
    lowercase ("A", " A", "a", " a"). Nothing else — not "A.", "(A",
    "Answer" — ever folds into a letter.
    """
    return frozenset({
        letter,
        f" {letter}",
        letter.lower(),
        f" {letter.lower()}",
    })


def _stripped_form_to_letter(spec) -> dict[str, str]:
    """Map each stripped fold spelling to its canonical uppercase letter.

    The fold forms compared after stripping are the bare letter and its
    lowercase twin, so the lookup has one entry per letter per case.
    """
    lookup: dict[str, str] = {}
    for letter in spec.label_letters:
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


def _p_raw_and_mass(raw: dict[str, float], letters) -> tuple[dict[str, float | None], float]:
    """Per-letter raw probabilities (None when absent) and the branch mass.

    The mass is the sum over found letters only; an absent letter is None
    in the mapping — a silent 0.0 would fake a measured answer.
    """
    p_raw: dict[str, float | None] = {
        letter: raw.get(letter) for letter in letters
    }
    branch_mass = float(sum(raw.values()))
    return p_raw, branch_mass


def _normalized(p_raw: dict[str, float | None], branch_mass: float, letters) -> dict[str, float | None]:
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


def _expected_value(spec, p_norm: dict[str, float | None]) -> float:
    """The expected score on the experiment's scale from normalized masses.

    Sum of each found letter's worth times its normalized probability.
    Zero mass gives 0.0 (nothing was measured).
    """
    return float(sum(
        spec.label_values[letter] * p_norm[letter]
        for letter in spec.label_letters
        if p_norm[letter] is not None
    ))


def _p_safe(raw: dict[str, float], p_norm: dict[str, float | None]) -> tuple[float, float]:
    """The disease "safe" side (letters A, B, C): raw and normalized share.

    Sums the safe letters' raw probabilities and their normalized shares;
    missing letters simply contribute nothing. Zero found letters gives 0.0.
    """
    safe_letters = ("A", "B", "C")
    raw_sum = float(sum(raw[letter] for letter in safe_letters if letter in raw))
    norm_sum = float(sum(
        p_norm[letter] for letter in safe_letters if p_norm[letter] is not None
    ))
    return raw_sum, norm_sum


def score_labels(
    top_logprobs: list[dict],
    experiment: str,
    decision_position: int | None = None,
    skipped_prefix: list | None = None,
    skipped_len: int | None = None,
) -> dict:
    """Score one decision-position top-logprob list for one experiment.

    Returns the record's scoring fields: p_raw / p_norm (every letter of
    the experiment, None when absent), branch_mass, the pinned outcome
    field (expected_1_6, expected_0_20, ...) holding the expected value,
    the low_branch_mass flag (mass strictly below 0.80), the disease-only
    p_safe_raw / p_safe_norm, and the untouched audit fields (the full
    top_logprobs array, decision_position, skipped_prefix, skipped_len).
    Raises KeyError for an unknown experiment.
    """
    spec = experiments.EXPERIMENTS[experiment]
    lookup = _stripped_form_to_letter(spec)
    raw = _raw_letter_probabilities(top_logprobs, lookup)
    p_raw, branch_mass = _p_raw_and_mass(raw, spec.label_letters)
    p_norm = _normalized(p_raw, branch_mass, spec.label_letters)

    record: dict = {
        "p_raw": p_raw,
        "p_norm": p_norm,
        "branch_mass": branch_mass,
        spec.outcome_field: _expected_value(spec, p_norm),
        "low_branch_mass": branch_mass < config.LOW_BRANCH_MASS_THRESHOLD,
    }
    if spec.safe_letters is not None:
        record["p_safe_raw"], record["p_safe_norm"] = _p_safe(raw, p_norm)
    record["top_logprobs"] = top_logprobs
    record["decision_position"] = decision_position
    record["skipped_prefix"] = skipped_prefix
    record["skipped_len"] = skipped_len
    return record
