# Locked tests for the low-branch-mass coverage marker (TASK-1578, RED
# phase; tests ONLY - no implementation lives here).
#
# WHY THESE TESTS EXIST: a decision position whose combined yes/no mass
# is small (muse style: the two answer branches together hold only a
# fraction of the top-k probability) must be FLAGGED in the records
# (`low_branch_mass`) instead of being silently read like the sharp
# qwen/gpt-oss measurements. The flag's threshold is config
# (`branch_mass_threshold`, default 0.6, strictly lower-than); the raw
# probabilities and the combined mass keep their exact semantics - the
# marker only ADDS information, it never changes a measurement.
#
# All offline: the fake HTTP poster IS the only transport; no network,
# no model loads. The 62 locked offline tests in the existing files stay
# green.
import inspect
import json
import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

BASE_URL, MODEL = "http://127.0.0.1:9", "vendor/model"
YES_NO = ("yes", "no")
LEVELS = [0.0, 100.0]
PRODUCT, PRICE, CATEGORY = "Cola 12 oz", 1.99, "Soft Drinks"
PRODUCTS = [{"category": CATEGORY, "product": PRODUCT, "regular_price": PRICE}]
MARKER = "<|channel>"

# A 0.30 combined mass must be flagged, a 0.98 must not, and 0.60 sits
# exactly ON the default threshold (strictly lower-than: not low).
LOW_MASS_TOP_K = [
    {"token": "yes", "logprob": math.log(0.20)},
    {"token": "no", "logprob": math.log(0.10)},
]
HIGH_MASS_TOP_K = [
    {"token": "yes", "logprob": math.log(0.90)},
    {"token": "no", "logprob": math.log(0.08)},
]
BOUNDARY_TOP_K = [
    {"token": "yes", "logprob": math.log(0.30)},
    {"token": "no", "logprob": math.log(0.30)},
]
NO_BRANCH_TOP_K = [
    {"token": " The", "logprob": -0.90},
    {"token": " maybe", "logprob": -1.40},
]


def _require_parameter(function, name: str, owner: str) -> None:
    """Fail in plain language on a missing parameter (RED = feature gone)."""
    assert name in inspect.signature(function).parameters, (
        f"{owner} must accept a {name!r} parameter - this behaviour cannot "
        f"be configured without it (got: {inspect.signature(function)})"
    )


def _require_field(mapping, name: str, owner: str):
    """Return a NEW field's value, failing plainly when it is missing."""
    assert name in mapping, (
        f"the {owner} must carry a {name!r} field - the audit trail is "
        f"incomplete without it (got fields: {sorted(str(key) for key in mapping)})"
    )
    return mapping[name]


def _bare(token: str, logprob: float) -> tuple:
    """A position whose chosen token is its only top-k candidate."""
    return (token, logprob, [{"token": token, "logprob": logprob}])


def _scan_body(positions: list) -> str:
    """One OpenAI-style reply of (chosen token, logprob, top-k) positions."""
    blocks = [
        {"token": token, "logprob": logprob, "top_logprobs": top_k}
        for token, logprob, top_k in positions
    ]
    content = "".join(token for token, _, _ in positions)
    choice = {"message": {"content": content}, "logprobs": {"content": blocks}}
    return json.dumps({"choices": [choice]})


def _parse(positions: list) -> dict:
    """Parse a decision-scan reply with the yes/no labels."""
    from logprob_scoring import parse_first_token_response

    return parse_first_token_response(_scan_body(positions), labels=YES_NO)


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple:
        self.calls.append((url, payload))
        return 200, self.body


def _first_token_scorer(post: _FakePost, **kwargs):
    """The production first_token scorer over the injected fake transport."""
    from logprob_scoring import make_first_token_scorer

    return make_first_token_scorer(BASE_URL, MODEL, post=post, labels=YES_NO, **kwargs)


def test_low_branch_mass_flags_a_yes_no_mass_below_the_default_threshold():
    """A decision position whose combined yes/no mass is small is flagged
    low_branch_mass; raw probabilities and the mass keep their values."""
    low = _parse([_bare(MARKER, -0.01), ("yes", math.log(0.20), LOW_MASS_TOP_K)])
    assert _require_field(low, "low_branch_mass", "parse") is True, (
        "a 0.30 combined yes/no mass is a low-coverage measurement "
        "(muse style) and must be flagged, not read like a sharp answer"
    )
    assert low["p_yes"] == pytest.approx(0.20), "raw probabilities stay as-is"
    assert low["p_no"] == pytest.approx(0.10)
    assert low["branch_mass"] == pytest.approx(0.30)

    high = _parse([_bare(MARKER, -0.01), ("yes", math.log(0.90), HIGH_MASS_TOP_K)])
    assert _require_field(high, "low_branch_mass", "parse") is False, (
        "a 0.98 combined mass is well covered and must not be flagged"
    )


def test_branch_mass_threshold_is_configurable_with_a_six_tenths_default():
    """The default threshold is 0.6 and strictly lower-than (mass exactly
    0.6 is NOT low); a configured threshold changes the flag."""
    from logprob_scoring import make_first_token_scorer

    boundary = _parse([_bare(MARKER, -0.01), ("yes", math.log(0.30), BOUNDARY_TOP_K)])
    assert _require_field(boundary, "low_branch_mass", "parse") is False, (
        "mass exactly at the 0.6 default threshold is not BELOW it, so "
        "the record must not be flagged low"
    )

    _require_parameter(
        make_first_token_scorer, "branch_mass_threshold", "make_first_token_scorer"
    )
    body = _scan_body([_bare(MARKER, -0.01), ("yes", math.log(0.20), LOW_MASS_TOP_K)])
    result = _first_token_scorer(_FakePost(body), branch_mass_threshold=0.25)(
        [{"role": "user", "content": "buy?"}]
    )
    assert _require_field(result, "low_branch_mass", "scorer result") is False, (
        "with the threshold configured to 0.25 the same 0.30 mass is "
        "adequate coverage - the threshold must be honoured, not ignored"
    )


def test_low_branch_mass_is_present_when_nothing_was_measured_and_reaches_records():
    """The marker exists on every record shape - even a runaway reply with
    no decision position at all - and travels into the durable records."""
    from fos.experiments.sweep_kit import run_logprob_sweep
    from unblinding_sweep import _build_design

    runaway = _parse([_bare(MARKER, -0.01), _bare("<|message>", -0.02)])
    assert "low_branch_mass" in runaway, (
        "even a runaway reply (no decision position, p_yes/p_no None) "
        "must carry the low_branch_mass field"
    )
    absent = _parse([_bare(MARKER, -0.01), (" The", -0.90, NO_BRANCH_TOP_K)])
    assert "low_branch_mass" in absent, (
        "a decision position with no yes/no branch at all still carries "
        "the field (its value is the implementation's honest choice)"
    )

    design = _build_design(LEVELS, ["blinded"], 7, [], "none")
    body = _scan_body([_bare(MARKER, -0.01), ("yes", math.log(0.20), LOW_MASS_TOP_K)])
    records = run_logprob_sweep(
        design,
        PRODUCTS,
        MODEL,
        _first_token_scorer(_FakePost(body)),
        draws=1,
        blinding="blinded",
        seed=7,
        persona_depth="none",
        response_format="yes/no",
    )
    for record in records:
        assert _require_field(record, "low_branch_mass", "record") is True, (
            "the durable record must flag the muse-style low coverage "
            "(0.30 combined mass) so it is never read like a sharp answer"
        )
        assert record["branch_mass"] == pytest.approx(0.30)
