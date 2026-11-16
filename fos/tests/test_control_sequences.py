# Locked tests for the Gemma channel-header SEQUENCE detector (TASK-1578,
# RED phase; tests ONLY - no implementation lives in this file).
#
# WHY THESE TESTS EXIST: Gemma opens every reply with a FIXED FOUR-token
# header "<|channel>" -> "thought" -> "\n" -> "<channel|>" (observed 6/6
# in RESULT-1576) before the sharp yes/no answer at position 5. Skipping
# those tokens one at a time as generic "model-format metadata" is not
# the same thing: the whole header must be recognized as ONE exact
# control SEQUENCE (exact strings, exact order), recorded as the skipped
# prefix, with the answer mass read at position 5. A header that
# deviates at ANY position must consume NOTHING - the walk behaves
# exactly as today. Sequences are per-model config (a list of token
# lists beside the existing control_tokens), exact-string only, addable
# WITHOUT code surgery.
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

# Gemma's observed fixed channel header (RESULT-1576 section 1): four
# chosen tokens in exactly this order, then the sharp answer token.
GEMMA_HEADER = ["<|channel>", "thought", "\n", "<channel|>"]
# Position 5's real top-k shape (probe01): a sharp bare "yes" and tiny
# no forms - the forms the answer mass must be read from.
GEMMA_ANSWER_TOP_K = [
    {"token": "yes", "logprob": -0.000005},
    {"token": "no", "logprob": -12.43},
    {"token": "Yes", "logprob": -13.82},
    {"token": " no", "logprob": -13.12},
]
P_YES_GEMMA = math.exp(-0.000005) + math.exp(-13.82)
P_NO_GEMMA = math.exp(-12.43) + math.exp(-13.12)


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


def _parse_with_sequences(positions: list, sequences: list) -> dict:
    """Parse a multi-position reply with per-model control sequences."""
    from logprob_scoring import parse_first_token_response

    _require_parameter(
        parse_first_token_response, "control_sequences", "first-token parser"
    )
    return parse_first_token_response(
        _scan_body(positions), labels=YES_NO, control_sequences=sequences
    )


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple:
        self.calls.append((url, payload))
        return 200, self.body


def _gemma_reply_positions() -> list:
    """The full observed Gemma reply: the 4-token header, then the answer."""
    return [
        _bare(GEMMA_HEADER[0], -0.00001),
        _bare(GEMMA_HEADER[1], -0.00015),
        _bare(GEMMA_HEADER[2], -0.0),
        _bare(GEMMA_HEADER[3], -0.00001),
        ("yes", -0.000005, GEMMA_ANSWER_TOP_K),
    ]


def test_full_gemma_channel_header_is_consumed_as_one_control_sequence():
    """The exact 4-token header is consumed as one block: the decision
    position is 5, the skipped prefix is the whole header in order, and
    the yes/no mass comes from position 5's sharp top-k."""
    parsed = _parse_with_sequences(_gemma_reply_positions(), [GEMMA_HEADER])

    assert _require_field(parsed, "decision_position", "parse") == 5, (
        "the whole 4-token header must be consumed; the answer sits at "
        "position 5 (one block, not one-token-at-a-time skips)"
    )
    assert _require_field(parsed, "skipped_prefix", "parse") == GEMMA_HEADER, (
        "the skipped prefix must be exactly the four header tokens in generation order"
    )
    assert _require_field(parsed, "skipped_len", "parse") == 4
    assert parsed["p_yes"] == pytest.approx(P_YES_GEMMA), (
        f"the yes mass must come from position 5's top-k; got {parsed['p_yes']}"
    )
    assert parsed["p_no"] == pytest.approx(P_NO_GEMMA)
    assert parsed["matched_yes_tokens"] == ["yes"]
    assert parsed["matched_no_tokens"] == ["no", " no"]
    assert parsed["top_logprobs"] == GEMMA_ANSWER_TOP_K
    assert len(_require_field(parsed, "per_position_top_k", "parse")) == 5


def test_a_broken_header_sequence_is_not_consumed_and_the_walk_is_unchanged():
    """A header that deviates at any position consumes NOTHING: the walk
    behaves exactly as today (the "<|channel>" markup token alone is
    skipped, the deviating position is the decision position)."""
    broken = [
        _bare(GEMMA_HEADER[0], -0.01),
        _bare("Thought", -0.02),  # deviates: the sequence must not match
        (" yes", -0.30, [{"token": " yes", "logprob": -0.30}]),
    ]
    parsed = _parse_with_sequences(broken, [GEMMA_HEADER])

    assert _require_field(parsed, "decision_position", "parse") == 2, (
        "a broken header must not be consumed at all; the walk stops at "
        "the first non-control token exactly as today (position 2)"
    )
    assert _require_field(parsed, "skipped_prefix", "parse") == ["<|channel>"], (
        "only today's single markup token is skipped - the broken header "
        "must contribute none of its tokens"
    )
    assert _require_field(parsed, "skipped_len", "parse") == 1
    assert parsed["p_yes"] == pytest.approx(math.exp(-0.30))

    # A header cut short by the end of the reply is also unconsumed.
    partial = _parse_with_sequences(
        [_bare(GEMMA_HEADER[0], -0.01), _bare(GEMMA_HEADER[1], -0.02)],
        [GEMMA_HEADER],
    )
    assert _require_field(partial, "decision_position", "parse") == 2
    assert _require_field(partial, "skipped_len", "parse") == 1
    assert partial["p_yes"] is None


def test_control_sequences_match_exact_strings_only_and_are_addable_per_model():
    """Sequences are plain config: any list of exact token strings is
    addable per model, matches exact strings only, and wins as a WHOLE
    even when its first token is also a single control token."""
    other = ["<start>", "plan"]
    answer = (" yes", -0.30, [{"token": " yes", "logprob": -0.30}])
    matching = [_bare("<start>", -0.02), _bare("plan", -0.03), answer]
    parsed = _parse_with_sequences(matching, [other])
    assert _require_field(parsed, "decision_position", "parse") == 3
    assert _require_field(parsed, "skipped_prefix", "parse") == other

    # Exact-string matching only: a case deviation breaks the sequence.
    deviated = _parse_with_sequences(
        [_bare("<start>", -0.02), _bare("Plan", -0.03), answer], [other]
    )
    assert _require_field(deviated, "decision_position", "parse") == 1, (
        "sequences match exact strings only; a deviating token must "
        "consume nothing (an ordinary word opens the decision position)"
    )

    # The whole sequence wins BEFORE the single-token control rule.
    from logprob_scoring import parse_first_token_response

    _require_parameter(
        parse_first_token_response, "control_sequences", "first-token parser"
    )
    both = parse_first_token_response(
        _scan_body(matching),
        labels=YES_NO,
        control_tokens=("<start>",),
        control_sequences=[other],
    )
    assert both["decision_position"] == 3, (
        "when a sequence matches, it must be consumed as a whole before "
        "the single-token rule can stop after its first token"
    )
    assert both["skipped_prefix"] == ["<start>", "plan"]


def test_production_scorer_threads_control_sequences_end_to_end():
    """make_scorer accepts the per-model control_sequences config and the
    production scorer walks the Gemma header to the position-5 answer."""
    from logprob_scoring import make_scorer

    _require_parameter(make_scorer, "control_sequences", "make_scorer")
    post = _FakePost(_scan_body(_gemma_reply_positions()))
    scorer = make_scorer(
        "first_token",
        BASE_URL,
        MODEL,
        post=post,
        labels=YES_NO,
        control_sequences=[GEMMA_HEADER],
    )
    result = scorer([{"role": "user", "content": "buy?"}])

    assert post.calls[0][0].endswith("/v1/chat/completions")
    assert "grammar" not in post.calls[0][1], (
        "sequence skipping happens when locating the decision position; "
        "the request itself stays grammar-free"
    )
    assert _require_field(result, "decision_position", "scorer result") == 5
    assert _require_field(result, "skipped_prefix", "scorer result") == GEMMA_HEADER
    assert _require_field(result, "skipped_len", "scorer result") == 4
    assert result["p_yes"] == pytest.approx(P_YES_GEMMA)
