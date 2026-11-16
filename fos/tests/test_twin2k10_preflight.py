# Locked tests for the twin2k10 study's preflight examiner (TASK-2139 RED
# phase; tests ONLY — no implementation lives yet, so every test here
# errors at collection until scripts/twin2k10/preflight.py exists).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The stop-or-proceed decision is one PURE function: it takes the
#     preflight records in memory and returns a verdict, touching no
#     files and no network.
#   - It says STOP exactly on technical failure criteria: a record whose
#     top-logprobs came back empty (the known GGUF failure signature), a
#     choice record where no answer letter could be read, and a digit
#     item where no answer digit could be read. TASK-2182: the sampling-
#     era truncation checks (expected_rows, unparseable numeric samples)
#     are GONE — records carry per-item first-token label distributions,
#     and leftover sampling fields are simply never inspected.
#   - Clean records mean PROCEED, and every stop verdict says why.
#
# All offline: pure functions over synthetic record dicts; no files.
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import preflight, scoring  # noqa: E402


def _entry(token: str, prob: float) -> dict:
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": math.log(prob)}


def _good_choice_record() -> dict:
    """A healthy choice preflight record: letters found, mass solid."""
    top_k = [_entry("A", 0.7), _entry("B", 0.2)]
    scored = scoring.score_labels(top_k, "allais", decision_position=1,
                                  skipped_prefix=[], skipped_len=0)
    return {"experiment": "allais", "arm": "form1", "model": "m",
            "persona_id": 0, "blind": "blinded",
            "top_logprobs": top_k, **scored}


def _digit_item(labels, top_k, p_raw=None, row=None, qid="QID287") -> dict:
    """One healthy digit-item entry as the executor stamps it (helper)."""
    return {
        "qid": qid, "row": row, "statement": None,
        "top_logprobs": list(top_k),
        "p_raw": p_raw if p_raw is not None
        else {label: 1.0 / len(labels) for label in labels},
    }


def _good_digit_record() -> dict:
    """A healthy digit preflight record: every item's digits readable."""
    labels = tuple("12345")
    top_k = [_entry("1", 0.6), _entry("2", 0.3)]
    item = _digit_item(labels, top_k, row=1)
    return {"experiment": "false_consensus", "arm": "all", "model": "m",
            "persona_id": 0, "blind": "blinded",
            "top_logprobs": top_k, "digit_items": [item]}


def test_clean_records_mean_proceed() -> None:
    """Healthy choice + digit records produce stop=False."""
    verdict = preflight.decide(
        [_good_choice_record(), _good_digit_record()]
    )
    assert verdict["stop"] is False
    assert verdict["reasons"] == []


def test_empty_top_logprobs_stops_the_model() -> None:
    """The known GGUF signature: no top-logprobs at the decision position."""
    broken = _good_choice_record()
    broken["top_logprobs"] = []
    verdict = preflight.decide([_good_choice_record(), broken])
    assert verdict["stop"] is True
    assert verdict["reasons"], "a stop verdict must say why"


def test_missing_labels_stop_the_run() -> None:
    """A choice record where no letter could be read is a failure."""
    letterless = _good_choice_record()
    letterless["p_raw"] = {"A": None, "B": None}
    verdict = preflight.decide([letterless])
    assert verdict["stop"] is True
    assert verdict["reasons"]


# ---------------------------------------------------------------------------
# TASK-2182 design pivot — digit-label checks replace the sampling-era
# numeric/truncation checks. A digit item fails technically exactly when
# a choice record fails: its top-logprobs came back empty (GGUF
# signature) or NO label digit could be read from its distribution.
# There is no truncation concept left: every item is one deterministic
# first-token call, and sampling-era record fields are never inspected.
# ---------------------------------------------------------------------------


def test_digit_item_with_no_readable_digit_is_a_rate_failure_not_a_stop() -> None:
    """An all-None digit p_raw with REAL top_logprobs text is a MODEL

    failure: flagged and counted in the pass rate — not an absolute
    STOP. AMENDED per owner policy (2026-09-22, "90% rate gate,
    all 15"); the pre-amendment version of this test forced a STOP.
    The blank item is the 11th digit item, all-None with readable text
    top-k ("Support"), so the model's rate is 10/11 ≈ 0.909 >= 0.90:
    PROCEED with QID287 flagged and counted as a failure.
    """
    labels = tuple("12345")
    blank = _digit_item(labels, [_entry("Support", 0.9)],
                        p_raw={label: None for label in labels}, row=7)
    record = _good_digit_record()
    record["digit_items"].extend(
        _digit_item(labels, [_entry("1", 0.6), _entry("2", 0.3)],
                    row=row) for row in range(2, 11)
    )
    record["digit_items"].append(blank)
    verdict = preflight.decide([record])
    assert verdict["stop"] is False, (
        "an all-None digit p_raw with real top_logprobs text is a "
        "model-behavior failure: rate-gated and flagged, never a STOP"
    )
    per_model = verdict["per_model"]["m"]
    assert per_model["digit_pass_rate"] == pytest.approx(10 / 11), (
        "the all-None item must be COUNTED as a failing digit item"
    )
    assert any(row["qid"] == "QID287" for row in per_model["flagged"]), (
        "the all-None item must appear among the flagged rows"
    )


def test_digit_item_with_empty_top_logprobs_stops_the_run() -> None:
    """Empty top_logprobs at the decision token is a TRANSPORT failure:

    an absolute STOP regardless of the pass rate (owner policy
    2026-09-22); the all-None p_raw next to it is a model failure and
    only rides along in the rate."""
    labels = tuple("12345")
    empty = _digit_item(labels, [], p_raw={label: None for label in labels},
                        row=3)
    record = _good_digit_record()
    record["digit_items"][0] = empty
    verdict = preflight.decide([record])
    assert verdict["stop"] is True
    assert verdict["reasons"]


def test_record_with_every_digit_item_readable_proceeds() -> None:
    """A full false_consensus record (10 healthy rating items) passes."""
    labels = tuple("12345")
    items = [_digit_item(labels, [_entry("1", 0.5), _entry("2", 0.4)],
                         row=row) for row in range(1, 11)]
    record = _good_digit_record()
    record["digit_items"] = items
    verdict = preflight.decide([record])
    assert verdict["stop"] is False
    assert verdict["reasons"] == []


def test_anchoring_record_with_healthy_mc_and_digit_proceeds() -> None:
    """An anchoring record: one choice distribution + one digit item."""
    record = _good_choice_record()
    record["experiment"] = "anchoring_redwood"
    record["arm"] = "low"
    record["digit_items"] = [_digit_item(
        tuple("0123456789"), [_entry("7", 0.5)],
        p_raw={digit: 0.1 for digit in "0123456789"}, qid="QID168",
    )]
    verdict = preflight.decide([record])
    assert verdict["stop"] is False
    assert verdict["reasons"] == []


def test_leftover_sampling_fields_are_never_inspected() -> None:
    """Sampling-era fields on a record can no longer stop anything.

    The truncation/unparseable-sample checks are deleted with the
    sampling machinery: a record that still carries old sampling fields
    is judged only on its first-token label distributions.
    """
    record = _good_choice_record()
    record.update({
        "numeric_samples": ["I refuse to answer"],
        "multi_numeric_values": [[None, None, None]],
        "expected_rows": 10,
        "numeric_parse_failures": 99,
    })
    verdict = preflight.decide([record])
    assert verdict["stop"] is False, verdict["reasons"]


def test_a_record_without_digit_items_has_no_digit_reasons() -> None:
    """A pure-choice record simply has no digit items to check."""
    verdict = preflight.decide([_good_choice_record()])
    assert verdict["stop"] is False
    assert verdict["reasons"] == []


def test_the_decision_is_pure_and_stable() -> None:
    """Same records in, same verdict out; calling it changes nothing."""
    records = [_good_choice_record(), _good_digit_record()]
    first = preflight.decide([dict(r) for r in records])
    second = preflight.decide([dict(r) for r in records])
    assert first == second
    assert preflight.decide([])["stop"] is False


# ---------------------------------------------------------------------------
# TASK-2150 RED tests — review blocker B1 (RESULT-2146) — REMOVED by the
# TASK-2182 design pivot (owner decision): with sampling deleted there
# is no generation window, no truncation signature and no expected_rows
# field to check. Their digit-era replacements are the digit-label
# checks above (test_digit_item_with_no_readable_digit_stops_the_run and
# friends).
# ---------------------------------------------------------------------------
