# Locked tests for decision-position scoring (TASK-1565, RED phase).
#
# WHY THESE TESTS EXIST: some models (Gemma, observed on 8/8 probes in
# TASK-1564) open their reply with a control/channel token such as
# "<|channel>" before any real answer word. The yes/no probabilities
# measured at generated position 1 are then about the channel marker, not
# the answer. The scorer must therefore generate a SHORT window of tokens
# (max_tokens > 1), walk the CHOSEN tokens from position 1, SKIP
# control/channel tokens, and measure the yes/no mass at the FIRST
# substantive position's top-k. Control tokens still generate normally
# (no grammar, prompt unchanged) - they are skipped only when locating
# the decision position. Every skipped token is recorded, and the
# control-token definition is extendable per model WITHOUT code changes
# (a list of extra exact token strings beside the built-in markup shape).
#
# All offline: the fake HTTP poster IS the only transport; no network,
# no model loads. The 52 locked offline tests in the five existing files
# stay green.
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

CATEGORY, PRODUCT, PRICE = "Soft Drinks", "Cola 12 oz", 1.99
LEVELS = [0.0, 100.0]
BASE_URL, MODEL = "http://127.0.0.1:9", "vendor/model"
YES_NO = ("yes", "no")
PRODUCTS = [{"category": CATEGORY, "product": PRODUCT, "regular_price": PRICE}]
MARKER = "<|channel>"  # Gemma's observed opening control token
THREE_CONTROLS = [MARKER, "<|message>", "<|end|>"]

# The historical survey bytes exactly as R1-5MODEL rendered them (also
# locked verbatim in test_r1_yesno.py): a decision scan must NOT change
# the prompt template in any way.
HISTORICAL_PROMPT = (
    "Please consider the following product category: Soft Drinks.\n"
    "Suppose you are in a grocery store, and you see the following product in "
    "that category: Cola 12 oz.\n"
    "The product is currently priced at $1.99. Would you or would you not "
    'purchase the product? ["purchase" or "not purchase"]\n'
    "Return example: purchase"
)

# The substantive answer position's top-k: two yes forms, the exact "no"
# form, and three look-alikes the exact matcher must never fold into a
# branch.
DECISION_TOP_K = [
    {"token": " yes", "logprob": -0.30},
    {"token": " The", "logprob": -1.00},
    {"token": "no", "logprob": -2.20},
    {"token": "Yes", "logprob": -3.00},
    {"token": "not", "logprob": -4.00},
    {"token": "none", "logprob": -5.00},
]
P_YES = math.exp(-0.30) + math.exp(-3.00)  # both yes forms count
P_NO = math.exp(-2.20)  # "not" and "none" must NOT count

# Gemma's observed opening position (TASK-1564): the chosen token IS the
# channel marker at probability ~1, and the top-k carries a bait " yes"
# and "no" that must NEVER be counted (the marker position is skipped).
CHANNEL_TOP_K = [
    {"token": MARKER, "logprob": -0.01},
    {"token": " yes", "logprob": -4.50},
    {"token": "no", "logprob": -5.50},
]
CHANNEL_POSITION = (MARKER, -0.01, CHANNEL_TOP_K)

# An answer position whose top-k holds no yes/no branch at all.
NO_BRANCH_TOP_K = [
    {"token": " The", "logprob": -0.90},
    {"token": " maybe", "logprob": -1.40},
]


def _require_parameter(function, name: str, owner: str) -> None:
    """Fail in plain language on a missing parameter (RED = feature gone)."""
    assert name in inspect.signature(function).parameters, (
        f"{owner} must accept a {name!r} parameter - decision-position "
        f"scoring cannot be configured without it "
        f"(got: {inspect.signature(function)})"
    )


def _require_field(mapping, name: str, owner: str):
    """Return a NEW field's value, failing plainly when it is missing."""
    assert name in mapping, (
        f"{owner} must carry a {name!r} field - the decision-position "
        f"audit trail is incomplete without it "
        f"(got fields: {sorted(str(key) for key in mapping)})"
    )
    return mapping[name]


def _bare(token: str, logprob: float) -> tuple:
    """A position whose chosen token is its only top-k candidate."""
    return (token, logprob, [{"token": token, "logprob": logprob}])


def _scan_body(positions: list[tuple[str, float, list[dict]]]) -> str:
    """One OpenAI-style reply with several generated token positions.

    Each position is (chosen token, chosen logprob, top-k candidate list)
    - the shape a multi-token reply carries when per-position logprobs
    are requested. The message content is the chosen tokens joined.
    """
    blocks = [
        {"token": token, "logprob": logprob, "top_logprobs": top_k}
        for token, logprob, top_k in positions
    ]
    content = "".join(token for token, _, _ in positions)
    choice = {
        "message": {"content": content},
        "logprobs": {"content": blocks},
    }
    return json.dumps({"choices": [choice]})


def _parse(positions: list, control_tokens: tuple = ()):
    """Parse a multi-position reply with the given control-token list."""
    from logprob_scoring import parse_first_token_response

    _require_parameter(
        parse_first_token_response, "control_tokens", "first-token parser"
    )
    return parse_first_token_response(
        _scan_body(positions), labels=YES_NO, control_tokens=control_tokens
    )


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple[int, str]:
        self.calls.append((url, payload))
        return 200, self.body


def _yes_no_scorer(post: _FakePost, **kwargs):
    """The production first_token scorer over the injected fake transport."""
    from logprob_scoring import make_scorer

    _require_parameter(make_scorer, "scan_tokens", "make_scorer")
    _require_parameter(make_scorer, "control_tokens", "make_scorer")
    return make_scorer(
        "first_token", BASE_URL, MODEL, post=post, labels=YES_NO, **kwargs
    )


# --- (Task items 1+5) One control token, then the answer ----------------


def test_channel_marker_is_skipped_and_mass_is_measured_at_the_first_real_answer():
    """A "<|channel>" chosen at position 1 is skipped: the decision
    position becomes 2, the yes/no mass comes from position 2's top-k
    ONLY, and the skipped prefix is recorded."""
    parsed = _parse([CHANNEL_POSITION, (" yes", -0.30, DECISION_TOP_K)])

    assert _require_field(parsed, "decision_position", "parse") == 2, (
        "the channel marker at position 1 must be skipped; the decision "
        "position is the first substantive answer token (position 2)"
    )
    assert _require_field(parsed, "skipped_prefix", "parse") == [MARKER], (
        "the skipped control tokens must be recorded in order"
    )
    assert _require_field(parsed, "skipped_len", "parse") == 1
    assert parsed["p_yes"] == pytest.approx(P_YES), (
        f"the yes mass must come from position 2's top-k only; got "
        f"{parsed['p_yes']} - the bait ' yes' in the SKIPPED position's "
        "top-k leaked in"
    )
    assert parsed["p_no"] == pytest.approx(P_NO)
    assert parsed["matched_yes_tokens"] == [" yes", "Yes"]
    assert parsed["matched_no_tokens"] == ["no"]
    assert parsed["top_logprobs"] == DECISION_TOP_K, (
        "top_logprobs stays the DECISION position's raw top-k, exactly as "
        "the server returned it"
    )
    expected_tops = [CHANNEL_TOP_K, DECISION_TOP_K]
    assert _require_field(parsed, "per_position_top_k", "parse") == expected_tops, (
        "every position's raw top-k must be retained, not just the decision's"
    )
    assert parsed["succeeded"] is True


def test_several_control_tokens_are_skipped_in_order_until_the_answer():
    """Three control chosen tokens ("<|channel>", "<|message>", "<|end|>")
    are skipped in order; the decision position is 4."""
    positions = [
        _bare(THREE_CONTROLS[0], -0.01),
        _bare(THREE_CONTROLS[1], -0.02),
        _bare(THREE_CONTROLS[2], -0.03),
        (" yes", -0.30, DECISION_TOP_K),
    ]
    parsed = _parse(positions)

    assert _require_field(parsed, "decision_position", "parse") == 4
    assert _require_field(parsed, "skipped_prefix", "parse") == THREE_CONTROLS, (
        "the whole control prefix must be recorded, in generation order"
    )
    assert _require_field(parsed, "skipped_len", "parse") == 3
    assert parsed["p_yes"] == pytest.approx(P_YES)
    assert parsed["p_no"] == pytest.approx(P_NO)
    assert len(_require_field(parsed, "per_position_top_k", "parse")) == 4


# --- (Task item 3) No-control regression: today's behaviour exactly -----


def test_plain_answers_without_control_tokens_reproduce_todays_result_exactly():
    """With no control tokens anywhere, the decision position is 1, the
    skipped prefix is empty, and every measured value equals today's
    first-token behaviour (later positions never leak in)."""
    later_top_k = [
        {"token": "yes", "logprob": -0.10},  # bait at a later position
        {"token": "No", "logprob": -0.20},
    ]
    parsed = _parse(
        [
            (" yes", -0.30, DECISION_TOP_K),
            (" The", -0.90, later_top_k),
            (" definitely", -0.60, later_top_k),
        ]
    )

    assert _require_field(parsed, "decision_position", "parse") == 1
    assert _require_field(parsed, "skipped_prefix", "parse") == []
    assert _require_field(parsed, "skipped_len", "parse") == 0
    assert parsed["p_yes"] == pytest.approx(P_YES), (
        "without control tokens the measurement must be exactly today's "
        "position-1 result; a later position's yes leaked in"
    )
    assert parsed["p_no"] == pytest.approx(P_NO)
    assert parsed["p_yes_binary"] == pytest.approx(P_YES / (P_YES + P_NO))
    assert parsed["top_logprobs"] == DECISION_TOP_K

    # Today's exact single-position reply shape regresses identically.
    single = _parse([(" yes", -0.30, DECISION_TOP_K)])
    assert _require_field(single, "decision_position", "parse") == 1
    assert _require_field(single, "skipped_prefix", "parse") == []
    assert _require_field(single, "skipped_len", "parse") == 0
    assert single["p_yes"] == pytest.approx(P_YES)
    assert single["p_no"] == pytest.approx(P_NO)


# --- (Task item 4) Runaway: every position is a control token -----------


def test_reply_of_only_control_tokens_reports_no_decision_position_and_none_fields():
    """When ALL chosen tokens are control tokens there is no decision
    position: it is reported as None with an explicit flag, p_yes/p_no/
    p_yes_binary are None (never a silent 0), the skipped prefix records
    every token, and nothing crashes."""
    positions = [
        _bare(THREE_CONTROLS[0], -0.01),
        _bare(THREE_CONTROLS[1], -0.02),
        _bare(THREE_CONTROLS[2], -0.03),
    ]
    parsed = _parse(positions)

    assert _require_field(parsed, "decision_position", "parse") is None, (
        "a reply of only control tokens has NO decision position - it must "
        "be None, never 1 (that would measure the channel marker)"
    )
    assert _require_field(parsed, "no_substantive_position", "parse") is True, (
        "the runaway case needs an explicit flag - a silent empty result "
        "would hide the failure"
    )
    assert _require_field(parsed, "skipped_prefix", "parse") == THREE_CONTROLS
    assert _require_field(parsed, "skipped_len", "parse") == 3
    assert parsed["p_yes"] is None
    assert parsed["p_no"] is None
    assert parsed["p_yes_binary"] is None
    assert _require_field(parsed, "per_position_top_k", "parse") == [
        position[2] for position in positions
    ], "even a runaway reply keeps every position's raw top-k"


# --- (Task item 5) Leakage from skipped positions ------------------------


def test_yes_no_hiding_in_a_skipped_position_is_never_counted():
    """A skipped position's top-k may contain strong yes/no candidates;
    they must never reach the measurement (here the decision position has
    no branches at all, so the honest result is None/None)."""
    bait_top_k = [
        {"token": " yes", "logprob": -0.10},
        {"token": "no", "logprob": -0.20},
    ]
    parsed = _parse(
        [
            (MARKER, -0.01, bait_top_k),
            (" The", -0.90, NO_BRANCH_TOP_K),
        ]
    )

    assert _require_field(parsed, "decision_position", "parse") == 2
    assert parsed["p_yes"] is None, (
        f"p_yes must be None; got {parsed['p_yes']} - yes mass in the "
        "SKIPPED position's top-k leaked into the measurement"
    )
    assert parsed["p_no"] is None, (
        f"p_no must be None; got {parsed['p_no']} - no mass in the "
        "SKIPPED position's top-k leaked into the measurement"
    )
    assert parsed["matched_yes_tokens"] == []
    assert parsed["matched_no_tokens"] == []


# --- (Task item 6) Exact token-form matching at the decision position ---


def test_not_and_none_still_never_count_as_no_after_a_skip():
    """Exact token-form matching is unchanged at the decision position:
    after skipping a control prefix, 'not'/'none'/'nobody' still never
    fold into p_no."""
    lookalikes_top_k = [
        {"token": " no", "logprob": -0.50},
        {"token": " yes", "logprob": -0.80},
        {"token": "not", "logprob": -1.00},
        {"token": "none", "logprob": -2.00},
        {"token": "nobody", "logprob": -3.00},
    ]
    parsed = _parse([CHANNEL_POSITION, (" no", -0.50, lookalikes_top_k)])

    assert _require_field(parsed, "decision_position", "parse") == 2
    assert parsed["p_no"] == pytest.approx(math.exp(-0.50)), (
        f"only the exact ' no' token form may count toward p_no; got "
        f"{parsed['p_no']} - prefix look-alikes (not/none/nobody) leaked in"
    )
    assert parsed["p_yes"] == pytest.approx(math.exp(-0.80))
    assert parsed["matched_no_tokens"] == [" no"]
    assert parsed["matched_yes_tokens"] == [" yes"]


# --- (Task item 7) Request shape: short scan window, still grammar-free --


def test_production_request_asks_for_a_short_configurable_scan_window_without_grammar():
    """The R1-YESNO production request now generates a short token window
    (max_tokens = the decision-scan window, default 8, configurable) with
    per-position logprobs requested - still no grammar, and the prompt
    template is byte-unchanged."""
    from fos.experiments.sweep_kit import build_purchase_user_prompt

    body = _scan_body([CHANNEL_POSITION, (" yes", -0.30, DECISION_TOP_K)])
    post = _FakePost(body)
    result = _yes_no_scorer(post)([{"role": "user", "content": "buy?"}])
    url, payload = post.calls[0]

    assert url.endswith("/v1/chat/completions")
    assert "grammar" not in payload, (
        "control tokens must generate normally: no grammar key, the "
        "prompt unchanged - skipping happens only when locating the "
        "decision position"
    )
    assert payload["max_tokens"] == 8, (
        f"the default decision-scan window must be 8 (> 1) so a control "
        f"prefix can be walked past; got max_tokens={payload['max_tokens']}"
    )
    assert payload["logprobs"] is True and payload["top_logprobs"] == 20, (
        "the scan window needs per-position top-k logprobs"
    )
    assert _require_field(result, "decision_position", "scorer result") == 2
    assert _require_field(result, "skipped_prefix", "scorer result") == [MARKER]
    assert _require_field(result, "skipped_len", "scorer result") == 1
    assert result["p_yes"] == pytest.approx(P_YES)

    configured_post = _FakePost(body)
    configured = _yes_no_scorer(configured_post, scan_tokens=4)
    configured([{"role": "user", "content": "buy?"}])
    assert configured_post.calls[0][1]["max_tokens"] == 4, (
        "scan_tokens must be configurable - the window is production "
        "config, not a hard-coded constant"
    )

    prompt = build_purchase_user_prompt(
        CATEGORY, PRODUCT, PRICE, response_format="yes/no"
    )
    assert prompt == HISTORICAL_PROMPT.replace(
        '["purchase" or "not purchase"]', '["yes" or "no"]'
    ).replace("Return example: purchase", "Return example: yes"), (
        "the decision scan must not change the prompt template by one byte"
    )


# --- (Task items 8+9) Records and the p_yes_binary formula --------------


def test_records_carry_decision_position_fields_alongside_the_old_ones():
    """A real scorer (fake transport) threaded through run_logprob_sweep
    records the new decision-position fields beside every existing field,
    keeps the raw per-position top-k, and stays JSON-serialisable. The
    control token here is an EXTENSION-list token, proving the spec used
    travels end to end into the record."""
    from fos.experiments.sweep_kit import run_logprob_sweep
    from unblinding_sweep import _build_design

    positions = [_bare("<start>", -0.05), (" yes", -0.30, DECISION_TOP_K)]
    design = _build_design(LEVELS, ["blinded"], 7, [], "none")
    scorer = _yes_no_scorer(
        _FakePost(_scan_body(positions)), control_tokens=("<start>",)
    )
    records = run_logprob_sweep(
        design,
        PRODUCTS,
        MODEL,
        scorer,
        draws=1,
        blinding="blinded",
        seed=7,
        persona_depth="none",
        response_format="yes/no",
    )
    assert len(records) == len(LEVELS)
    for record in records:
        assert _require_field(record, "decision_position", "record") == 2
        assert _require_field(record, "skipped_prefix", "record") == ["<start>"]
        assert _require_field(record, "skipped_len", "record") == 1
        assert _require_field(record, "control_tokens", "record") == ["<start>"], (
            "the record must stamp the control spec that was actually used"
        )
        expected_tops = [position[2] for position in positions]
        assert (
            _require_field(record, "per_position_top_k", "record") == expected_tops
        ), "records must retain the raw per-position top-k"
        assert record["top_logprobs"] == DECISION_TOP_K
        assert record["p_yes"] == pytest.approx(P_YES)
        assert record["p_no"] == pytest.approx(P_NO)
        assert record["matched_yes_tokens"] == [" yes", "Yes"]
        assert record["matched_no_tokens"] == ["no"]
        assert record["response_format"] == "yes/no"
        assert record["parse_mode"] == "first_token_logprob"
        json.dumps(record)  # must stay JSON-serialisable


def test_p_yes_binary_stays_yes_share_of_the_two_branch_mass():
    """The p_yes_binary formula is unchanged after the move: the yes share
    of the two-branch mass measured at the decision position (and None
    when neither branch is there)."""
    parsed = _parse([CHANNEL_POSITION, (" yes", -0.30, DECISION_TOP_K)])

    assert parsed["p_yes_binary"] == pytest.approx(
        parsed["p_yes"] / (parsed["p_yes"] + parsed["p_no"])
    ), "p_yes_binary must stay p_yes/(p_yes+p_no) of the decision position"
    assert parsed["p_yes_binary"] == pytest.approx(P_YES / (P_YES + P_NO))

    absent = _parse([CHANNEL_POSITION, (" The", -0.90, NO_BRANCH_TOP_K)])
    assert absent["p_yes_binary"] is None, (
        "no branch at the decision position: p_yes_binary is None, never 0"
    )


# --- (Control spec) Extensible without code changes ----------------------


def test_new_control_tokens_are_addable_without_code_changes():
    """The built-in spec is the special markup shape (<|...|> style); a
    per-model list of extra exact token strings must extend it through
    the plain control_tokens parameter - no code surgery."""
    # The markup shape is control BY DEFAULT (Gemma's observed marker).
    marked = _parse([CHANNEL_POSITION, (" yes", -0.30, DECISION_TOP_K)])
    assert _require_field(marked, "decision_position", "parse") == 2, (
        "'<|channel>' must be a control token under the default spec"
    )

    # A token with no markup shape is NOT control by default: it is the
    # answer position (even though its top-k has no yes/no branch).
    plain_body = [_bare("<start>", -0.05), (" yes", -0.30, DECISION_TOP_K)]
    plain = _parse(plain_body)
    assert _require_field(plain, "decision_position", "parse") == 1, (
        "without an extension list, an ordinary word opens the decision "
        "position like any other answer token"
    )

    # The SAME token becomes control via the extension list alone.
    extended = _parse(plain_body, control_tokens=("<start>",))
    assert _require_field(extended, "decision_position", "parse") == 2
    assert _require_field(extended, "skipped_prefix", "parse") == ["<start>"]
    assert extended["p_yes"] == pytest.approx(P_YES)

    # Ordinary answer words are never control under the default spec.
    ordinary = _parse(
        [(" The", -0.90, NO_BRANCH_TOP_K), (" yes", -0.30, DECISION_TOP_K)]
    )
    assert _require_field(ordinary, "decision_position", "parse") == 1
