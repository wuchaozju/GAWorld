# Locked tests for the R1-YESNO profile (TASK-1562, RED phase).
#
# WHY THESE TESTS EXIST: R1-YESNO asks the five models the same purchase
# question as R1-5MODEL, but the model answers "yes" or "no" in its own
# words and we read its honest first-token probabilities instead of
# forcing the answer with a grammar. Locked here, all offline (the fake
# HTTP poster IS the only transport; no network, no model loads):
#   (1) PROMPT: response_format="yes/no" changes ONLY the bracket hint and
#       the return example; the question keeps "not purchase"; None keeps
#       today's bytes.
#   (2) PROFILE: --profile R1-YESNO resolves: first_token, NO grammar, the
#       R1LP call geometry, a response_format manifest stamp.
#   (3) SCORER: p_yes/p_no/p_yes_binary from the raw top-k, EXACT token
#       forms ("not"/"none" never count as "no"); absent branches = None.
#   (4) RECORDS: raw top-k, yes/no fields, matched forms, stamps.
#   (5) ONE SOURCE: response_format feeds prompt wording AND scorer labels.
#
# The 39 locked offline tests in the four existing R1LP files stay green.
import inspect
import json
import math
import sys
from dataclasses import fields, replace
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

CATEGORY, PRODUCT, PRICE = "Soft Drinks", "Cola 12 oz", 1.99
LEVELS = [0.0, 100.0]

# The historical survey exactly as R1-5MODEL rendered it (YESNO-PROMPT-DIFF §1).
HISTORICAL_PROMPT = (
    "Please consider the following product category: Soft Drinks.\n"
    "Suppose you are in a grocery store, and you see the following product in "
    "that category: Cola 12 oz.\n"
    "The product is currently priced at $1.99. Would you or would you not "
    'purchase the product? ["purchase" or "not purchase"]\n'
    "Return example: purchase"
)
QUESTION_SENTENCE = "Would you or would you not purchase the product?"

# One synthetic first-position top-k: the two yes forms (leading-space and
# capitalised), the "no" form, three distractors the old prefix matcher
# would have folded into a branch, and one neutral token.
TOP_K = [
    {"token": " yes", "logprob": -0.10},
    {"token": " The", "logprob": -0.80},
    {"token": "no", "logprob": -2.30},
    {"token": "Yes", "logprob": -3.50},
    {"token": "not", "logprob": -4.20},
    {"token": " Yesterday", "logprob": -5.00},
    {"token": "none", "logprob": -6.00},
]
P_YES = math.exp(-0.10) + math.exp(-3.50)  # both yes forms count
P_NO = math.exp(-2.30)  # "not" and "none" must NOT count


def _require_parameter(function, name: str, owner: str) -> None:
    """Fail in plain language on a missing parameter (RED = feature gone)."""
    assert name in inspect.signature(function).parameters, (
        f"{owner} must accept a {name!r} parameter - the R1-YESNO profile "
        f"cannot be configured without it (got: {inspect.signature(function)})"
    )


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple[int, str]:
        self.calls.append((url, payload))
        return 200, self.body


def _first_token_body(entries: list[dict], content: str = " yes") -> str:
    """One OpenAI-style first-token reply carrying the given top-k."""
    first = {"token": content, "logprob": entries[0]["logprob"], "top_logprobs": entries}
    return json.dumps(
        {"choices": [{"message": {"content": content},
                      "logprobs": {"content": [first]}}]}
    )


def _yes_no_scorer_result() -> dict:
    """A synthetic first_token scorer result in the yes/no record shape."""
    return {
        "logprob_mode": "first_token",
        "p_buy_logprob": P_YES,  # legacy keys kept for schema continuity
        "p_nobuy_logprob": P_NO,
        "branch_mass": P_YES + P_NO,
        "p_yes": P_YES,
        "p_no": P_NO,
        "p_yes_binary": P_YES / (P_YES + P_NO),
        "top_logprobs": [dict(entry) for entry in TOP_K],
        "matched_yes_tokens": [" yes", "Yes"],
        "matched_no_tokens": ["no"],
        "neither_branch_in_top_k": False,
        "raw_logprob_response": "{}",
        "raw_content": " yes",
        "succeeded": True,
    }


# --- (1) Prompt: response_format="yes/no" changes exactly two slots -----

def test_yes_no_response_format_changes_exactly_the_two_response_words():
    """With response_format="yes/no" only the bracket hint and the return
    example change; the question sentence keeps its own "not purchase"."""
    from fos.experiments.sweep_kit import build_purchase_user_prompt

    _require_parameter(build_purchase_user_prompt, "response_format", "prompt builder")
    historical = build_purchase_user_prompt(CATEGORY, PRODUCT, PRICE)
    yes_no = build_purchase_user_prompt(
        CATEGORY, PRODUCT, PRICE, response_format="yes/no"
    )

    expected = historical.replace(
        '["purchase" or "not purchase"]', '["yes" or "no"]'
    ).replace("Return example: purchase", "Return example: yes")
    assert yes_no == expected, (
        "response_format='yes/no' must change ONLY the two response-word "
        f"slots.\nExpected:\n{expected!r}\nGot:\n{yes_no!r}"
    )
    assert '["yes" or "no"]' in yes_no
    assert "Return example: yes" in yes_no
    assert QUESTION_SENTENCE in yes_no, (
        "the question sentence must keep its 'not purchase' wording - it "
        "is the question, not a response word"
    )
    assert yes_no.count("purchase") == 1, (
        "outside the question sentence the word 'purchase' must be gone"
    )
    assert QUESTION_SENTENCE in historical  # same question in both


def test_none_response_format_keeps_the_historical_prompt_bytes():
    """Leaving response_format out (or passing None) renders exactly
    today's prompt bytes, so every stored prompt_sha256 stays stable."""
    from fos.experiments.sweep_kit import build_purchase_user_prompt

    assert build_purchase_user_prompt(CATEGORY, PRODUCT, PRICE) == HISTORICAL_PROMPT
    _require_parameter(build_purchase_user_prompt, "response_format", "prompt builder")
    assert (
        build_purchase_user_prompt(CATEGORY, PRODUCT, PRICE, response_format=None)
        == HISTORICAL_PROMPT
    ), "response_format=None must keep the historical prompt byte-identical"


# --- (2) Profile: R1-YESNO resolves, grammar-free, first_token ----------

def test_r1_yesno_is_a_registered_profile_choice():
    """R1-YESNO is registered in the launcher's profile table and accepted
    as a --profile choice (never an argparse refusal)."""
    import launch_support

    assert "R1-YESNO" in launch_support.PROFILES, (
        "launch_support.PROFILES must register R1-YESNO (the yes/no first-"
        f"token twin of the queue); got {sorted(launch_support.PROFILES)}"
    )
    from launch_grid import _parse_args

    try:
        args = _parse_args(["--profile", "R1-YESNO"])
    except SystemExit as exc:
        pytest.fail(
            "launch_grid refused --profile R1-YESNO (exit "
            f"{exc.code}): the profile is not a registered choice yet"
        )
    assert args.profile == "R1-YESNO"


def test_r1_yesno_settings_are_first_token_grammar_free_yes_no():
    """The settings a real R1-YESNO run would use ask for first-token
    logprobs, carry NO grammar, and stamp response_format='yes/no'."""
    from launch_grid import _parse_args, _settings_from

    settings = _settings_from(_parse_args(["--profile", "R1-YESNO"]), "probe")
    assert hasattr(settings, "response_format"), (
        "Settings must grow a response_format field - the response wording "
        "is pure config on this profile"
    )
    assert settings.response_format == "yes/no", (
        f"the R1-YESNO profile must stamp response_format='yes/no'; "
        f"got {settings.response_format!r}"
    )
    assert settings.logprob_mode == "first_token", (
        f"R1-YESNO reads honest first-token logprobs; got {settings.logprob_mode!r}"
    )
    assert settings.grammar is None, (
        "R1-YESNO must never constrain decoding: the purchase GBNF grammar "
        f"must be absent; got {settings.grammar!r}"
    )


def test_r1_yesno_plan_carries_its_own_profile_id_with_r1lp_geometry():
    """The R1-YESNO plan keeps the R1LP geometry (one scoring pass per
    prompt, 18,480 calls per model, 92,400 total) under its OWN profile id,
    and building it never disturbs the plain R1LP plan."""
    from launch_queue import build_logprob_plan

    _require_parameter(build_logprob_plan, "profile", "build_logprob_plan")
    plan = build_logprob_plan(
        40, 11, levels=[float(x) for x in range(0, 220, 20)], profile="R1-YESNO"
    )
    assert plan["profile"] == "R1-YESNO", (
        f"the yes/no plan must be stamped R1-YESNO, not a borrowed "
        f"{plan['profile']!r}"
    )
    assert plan["draws"] == 1
    assert len(plan["legs"]) == 20
    assert plan["sweep_calls"] == 92_400
    for meta in plan["models"]:
        assert meta["total_calls"] == 18_480
    assert not plan.get("ab_orders"), "R1-YESNO has no A/B form"

    default = build_logprob_plan(40, 11, levels=[float(x) for x in range(0, 220, 20)])
    assert default["profile"] == "R1LP", "no profile argument stays the R1LP plan"


def test_r1_yesno_dry_run_resolves_offline_without_the_grammar(capsys):
    """launch_grid --profile R1-YESNO --dry-run is accepted offline: it
    prints the yes/no plan with the R1LP call counts and the first_token
    mode, and never shows the purchase grammar."""
    from launch_grid import main

    try:
        code = main(["--profile", "R1-YESNO", "--dry-run"])
    except SystemExit as exc:
        pytest.fail(
            "launch_grid refused --profile R1-YESNO --dry-run (exit "
            f"{exc.code}): the profile does not resolve yet"
        )
    assert code == 0
    out = capsys.readouterr().out
    assert "R1-YESNO launch plan (dry run)" in out
    assert "18,480" in out and "92,400" in out
    assert "first_token" in out, "the dry run must report the real mode (first_token)"
    assert "root ::=" not in out, (
        "the purchase GBNF grammar must never appear in an R1-YESNO plan"
    )


def test_r1_yesno_run_manifest_stamps_response_format_and_no_grammar(tmp_path):
    """The run manifest of an R1-YESNO run is self-describing: profile
    R1-YESNO, logprob_mode first_token, grammar None, response_format
    'yes/no' - so a later audit can never mistake it for an R1 rerun."""
    from launch_5model import write_queue_manifest
    from launch_grid import _parse_args, _settings_from
    from launch_queue import build_logprob_plan
    from launch_support import _now

    args = _parse_args(["--profile", "R1-YESNO", "--run-name", "yesno-probe"])
    settings = replace(_settings_from(args, "yesno-probe"), out=tmp_path)
    plan = build_logprob_plan(
        40, 11, levels=[float(x) for x in range(0, 220, 20)], profile="R1-YESNO"
    )
    run_dir = tmp_path / "yesno-probe"
    run_dir.mkdir(parents=True)

    manifest_path = write_queue_manifest(
        settings=settings, plan=plan, products_path=Path("products.json"),
        run_dir=run_dir, started=_now(), finished=_now(), leg_results=[],
        pools=None, prior=None, resume_invocation=False, state="running",
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["profile"] == "R1-YESNO"
    assert payload["logprob_mode"] == "first_token"
    assert payload["grammar"] is None, (
        "the manifest must record that this run used NO grammar"
    )
    assert payload.get("response_format") == "yes/no", (
        f"the manifest must stamp response_format; got "
        f"{payload.get('response_format')!r} - without the stamp a future "
        "audit could mistake the run for an R1 rerun"
    )


def test_r1_yesno_scorer_payload_never_carries_a_grammar_key():
    """The scorer the R1-YESNO profile resolves to (first_token, yes/no
    labels) posts a completely unconstrained request: no grammar field,
    logprobs requested - and its result carries the yes/no fields."""
    from logprob_scoring import make_scorer

    _require_parameter(make_scorer, "labels", "make_scorer")
    post = _FakePost(_first_token_body(TOP_K))
    scorer = make_scorer(
        "first_token", "http://127.0.0.1:9", "vendor/model",
        post=post, labels=("yes", "no"),
    )
    result = scorer([{"role": "user", "content": "buy?"}])

    assert len(post.calls) == 1  # the injected fake IS the transport
    url, payload = post.calls[0]
    assert url.endswith("/v1/chat/completions")
    assert "grammar" not in payload, (
        "the R1-YESNO request must be unconstrained - no grammar key, "
        "the model answers in its own words"
    )
    assert payload["max_tokens"] == 8  # superseded by decision-position directive (TASK-1565): scan window, see test_decision_position.py
    assert payload["logprobs"] is True and payload["top_logprobs"] == 20
    assert result["p_yes"] == pytest.approx(P_YES)
    assert result["p_no"] == pytest.approx(P_NO)
    assert result["p_yes_binary"] == pytest.approx(P_YES / (P_YES + P_NO))
    assert result["neither_branch_in_top_k"] is False
    assert result["succeeded"] is True


# --- (3) Scorer: yes/no math, exact token forms, None when absent -------

def test_yes_no_branch_math_from_synthetic_top_logprobs():
    """p_yes sums the yes forms, p_no sums the no form, and the parse adds
    p_yes_binary = p_yes/(p_yes+p_no); the raw top-k is kept as returned."""
    from logprob_scoring import parse_first_token_response, purchase_branch_mass

    _require_parameter(purchase_branch_mass, "labels", "purchase_branch_mass")
    mass = purchase_branch_mass(TOP_K, labels=("yes", "no"))
    assert mass["p_yes"] == pytest.approx(P_YES), (
        f"p_yes must sum BOTH yes token forms (leading-space and "
        f"capitalised); got {mass['p_yes']}"
    )
    assert mass["p_no"] == pytest.approx(P_NO)
    assert mass["branch_mass"] == pytest.approx(P_YES + P_NO)
    assert mass["neither_branch"] is False
    assert mass["matched_yes_tokens"] == [" yes", "Yes"], (
        "matched token forms must be recorded so per-model tokenisation "
        "quirks stay visible"
    )
    assert mass["matched_no_tokens"] == ["no"]

    _require_parameter(parse_first_token_response, "labels", "first-token parser")
    parsed = parse_first_token_response(_first_token_body(TOP_K), labels=("yes", "no"))
    assert parsed["p_yes"] == pytest.approx(P_YES)
    assert parsed["p_no"] == pytest.approx(P_NO)
    assert parsed["p_yes_binary"] == pytest.approx(P_YES / (P_YES + P_NO)), (
        "p_yes_binary is the yes share of the two-branch mass, "
        "p_yes/(p_yes+p_no)"
    )
    assert parsed["top_logprobs"] == TOP_K, (
        "the RAW top-k must be stored exactly as the server returned it"
    )
    assert parsed["succeeded"] is True


def test_not_and_none_tokens_do_not_count_as_no():
    """EXACT token-form matching: 'not', 'none' and 'nobody' share a prefix
    with 'no' but are different words - they must never be folded into
    p_no (the old code matched by prefix and would have swallowed them)."""
    from logprob_scoring import purchase_branch_mass

    _require_parameter(purchase_branch_mass, "labels", "purchase_branch_mass")
    top_k = [
        {"token": " yes", "logprob": -0.70},
        {"token": "no", "logprob": -1.60},
        {"token": "not", "logprob": -2.00},
        {"token": "none", "logprob": -3.00},
        {"token": "nobody", "logprob": -4.00},
    ]
    mass = purchase_branch_mass(top_k, labels=("yes", "no"))
    assert mass["p_no"] == pytest.approx(math.exp(-1.60)), (
        f"only the exact 'no' token form may count toward p_no; got "
        f"{mass['p_no']} - prefix look-alikes (not/none/nobody) leaked in"
    )
    assert mass["p_yes"] == pytest.approx(math.exp(-0.70))
    assert mass["matched_no_tokens"] == ["no"]
    assert mass["matched_yes_tokens"] == [" yes"]


def test_yes_no_absent_from_top_k_gives_none_fields_not_zero():
    """When neither yes nor no appears in the top-k the probabilities are
    None (with the visibility flag set) - never a silent 0.0 that would
    look like a measured 'certainly not'."""
    from logprob_scoring import parse_first_token_response, purchase_branch_mass

    _require_parameter(purchase_branch_mass, "labels", "purchase_branch_mass")
    top_k = [
        {"token": " The", "logprob": -0.90},
        {"token": " maybe", "logprob": -2.30},
    ]
    mass = purchase_branch_mass(top_k, labels=("yes", "no"))
    assert mass["p_yes"] is None, f"absent yes branch: None, not {mass['p_yes']!r}"
    assert mass["p_no"] is None, f"absent no branch: None, not {mass['p_no']!r}"
    assert mass["neither_branch"] is True

    _require_parameter(parse_first_token_response, "labels", "first-token parser")
    parsed = parse_first_token_response(
        _first_token_body(top_k, content=" The"), labels=("yes", "no")
    )
    assert parsed["p_yes_binary"] is None, (
        "p_yes_binary is None when neither branch is in the top-k - a 0.0 "
        "here would fake a measured answer"
    )
    assert parsed["neither_branch_in_top_k"] is True


# --- (4) Records: raw top-k, yes/no fields, matched forms, stamps -------

def test_yes_no_records_carry_raw_top_k_yes_no_fields_and_stamps():
    """run_logprob_sweep(response_format='yes/no') records carry the RAW
    top-k, the yes/no probabilities, the matched forms, response_format +
    parse_mode stamps - and the record's prompt uses the yes/no wording."""
    from fos.experiments.sweep_kit import run_logprob_sweep
    from unblinding_sweep import _build_design

    _require_parameter(run_logprob_sweep, "response_format", "run_logprob_sweep")
    design = _build_design(LEVELS, ["blinded"], 7, [], "none")
    records = run_logprob_sweep(
        design,
        [{"category": CATEGORY, "product": PRODUCT, "regular_price": PRICE}],
        "vendor/model",
        lambda _messages: _yes_no_scorer_result(),
        draws=1, blinding="blinded", seed=7, persona_depth="none",
        response_format="yes/no",
    )
    assert len(records) == len(LEVELS)
    for record in records:
        assert record["top_logprobs"] == [dict(entry) for entry in TOP_K], (
            "the record must keep the RAW top-k list exactly as returned"
        )
        assert record["p_yes"] == pytest.approx(P_YES)
        assert record["p_no"] == pytest.approx(P_NO)
        assert record["p_yes_binary"] == pytest.approx(P_YES / (P_YES + P_NO))
        assert record["matched_yes_tokens"] == [" yes", "Yes"]
        assert record["matched_no_tokens"] == ["no"]
        assert record["parsed_purchase"] is None  # no constrained parse here
        assert record["response_format"] == "yes/no", (
            f"every record must stamp response_format; got {record.get('response_format')!r}"
        )
        assert record["parse_mode"] == "first_token_logprob", (
            f"every record must name its parse mode; got {record.get('parse_mode')!r}"
        )
        assert '["yes" or "no"]' in record["user_prompt"], (
            "the record's stored prompt must use the yes/no wording - the "
            "runner threads response_format into the prompt builder"
        )
        json.dumps(record)  # must stay JSON-serialisable


# --- (5) One source of truth: response_format feeds prompt AND scorer ---

def test_one_response_format_setting_feeds_both_prompt_and_scorer():
    """The single response_format string is split once into the label pair
    and that SAME pair fills the prompt slots AND the scorer's branch
    matcher - changing the value changes both together, never drifting."""
    import launch_support
    from fos.experiments.sweep_kit import build_purchase_user_prompt
    from logprob_scoring import purchase_branch_mass

    names = [field.name for field in fields(launch_support.Settings)]
    assert "response_format" in names, (
        f"Settings must carry the response_format field (the one source of "
        f"truth for prompt wording and scorer labels); got {names}"
    )
    from launch_grid import _parse_args, _settings_from

    settings = _settings_from(_parse_args(["--profile", "R1-YESNO"]), "probe")
    fmt = settings.response_format  # the ONE source string

    # The prompt wording derives from it...
    prompt = build_purchase_user_prompt(CATEGORY, PRODUCT, PRICE, response_format=fmt)
    assert '["yes" or "no"]' in prompt and "Return example: yes" in prompt

    # ...and so do the scorer's branch labels, via the same split.
    from fos.experiments.sweep_kit import split_response_format

    mass = purchase_branch_mass(TOP_K, labels=split_response_format(fmt))
    assert mass["p_yes"] == pytest.approx(P_YES)
    assert mass["p_no"] == pytest.approx(P_NO)

    # Changing the one value moves BOTH together (any "<pos>/<neg>" pair).
    other_prompt = build_purchase_user_prompt(
        CATEGORY, PRODUCT, PRICE, response_format="maybe/not"
    )
    assert '["maybe" or "not"]' in other_prompt
    assert "Return example: maybe" in other_prompt
    other_mass = purchase_branch_mass(
        [
            {"token": " maybe", "logprob": -0.50},
            {"token": " The", "logprob": -1.00},
            {"token": "not", "logprob": -1.50},
        ],
        labels=split_response_format("maybe/not"),
    )
    assert other_mass["p_yes"] == pytest.approx(math.exp(-0.50))
    assert other_mass["p_no"] == pytest.approx(math.exp(-1.50))

    # The split itself: None keeps the historical words; a value without
    # the "/" separator is refused loudly, never silently mis-split.
    assert split_response_format(None) == ("purchase", "not purchase")
    with pytest.raises(ValueError):
        split_response_format("yesno")
