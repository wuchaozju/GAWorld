# Locked tests for pre-launch control_sequences hardening (TASK-1585, RED
# phase; tests ONLY - no implementation lives in this file).
#
# WHY THESE TESTS EXIST: two things block a gemma-enabled production
# launch. (1) A configured EMPTY control sequence matches vacuously
# today, which would make the decision walk advance by zero tokens
# forever - a silent hang with no error. The scorer builder must refuse
# such config loudly, at construction, BEFORE any call is made. (2) The
# queue threads per-model top_k into the scorer but NOT
# control_sequences, so a real gemma leg could never receive its
# channel-header config: the header sequence must ride the exact proven
# top_k path - profile config in launch_queue, a plan-layer resolver,
# a leg-manifest stamp, and launch_sweep passing it into the scorer -
# with every model WITHOUT an override keeping the default-off empty
# tuple and byte-identical behavior.
#
# All offline: the fake HTTP poster IS the only transport; no network,
# no model loads, and NEVER the full test suite (live-API tests are out
# of budget). The 79 locked offline tests in the existing files stay
# green.
import inspect
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

BASE_URL, MODEL = "http://127.0.0.1:9", "vendor/model"
YES_NO = ("yes", "no")

# Gemma's observed fixed channel header (RESULT-1576/1583): four chosen
# tokens in exactly this order, then the sharp answer at position 5.
GEMMA_HEADER = ["<|channel>", "thought", "\n", "<channel|>"]
GEMMA_QUEUE_MODEL = "google/gemma-4-26b-a4b"
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

YES_NO_LEVELS = [0.0, 100.0]
PRODUCT, PRICE, CATEGORY = "Cola 12 oz", 1.99, "Soft Drinks"
PRODUCTS = [{"category": CATEGORY, "product": PRODUCT, "regular_price": PRICE}]


def _require_parameter(function, name: str, owner: str) -> None:
    """Fail in plain language on a missing parameter (RED = feature gone)."""
    assert name in inspect.signature(function).parameters, (
        f"{owner} must accept a {name!r} parameter - this behaviour cannot "
        f"be configured without it (got: {inspect.signature(function)})"
    )


def _require_function(module, name: str, owner: str) -> None:
    """Fail in plain language when a module lacks a needed helper."""
    assert hasattr(module, name), (
        f"the {owner} must expose a {name!r} helper - per-model "
        "configuration cannot be resolved without it"
    )


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


def _gemma_reply_positions() -> list:
    """The full observed Gemma reply: the 4-token header, then the answer."""
    return [
        _bare(GEMMA_HEADER[0], -0.00001),
        _bare(GEMMA_HEADER[1], -0.00015),
        _bare(GEMMA_HEADER[2], -0.0),
        _bare(GEMMA_HEADER[3], -0.00001),
        ("yes", -0.000005, GEMMA_ANSWER_TOP_K),
    ]


class _FakePost:
    """A fake HTTP poster: records every (url, payload) and returns a body."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list = []

    def __call__(self, url: str, payload: dict, timeout: float) -> tuple:
        self.calls.append((url, payload))
        return 200, self.body


# ---------------------------------------------------------------------------
# (1) The empty-sequence guard: bad config is refused at construction
# ---------------------------------------------------------------------------


def test_an_empty_sequence_in_config_is_rejected_at_scorer_construction():
    """A configured control sequence that is an EMPTY list must raise a
    clear ValueError naming control_sequences the moment the scorer is
    built - never a silent zero-token walk (which would loop forever)."""
    from logprob_scoring import make_first_token_scorer

    post = _FakePost(_scan_body(_gemma_reply_positions()))
    with pytest.raises(ValueError, match="control_sequences"):
        make_first_token_scorer(
            BASE_URL,
            MODEL,
            post=post,
            labels=YES_NO,
            control_sequences=[[]],
        )
    assert post.calls == [], (
        "a rejected configuration must never reach the server: no call "
        "may be made when scorer construction refuses the config"
    )


def test_non_string_entries_in_a_sequence_are_rejected_at_scorer_construction():
    """A control sequence containing a NON-STRING entry (e.g. a number)
    can never match a token exactly; the scorer builder must refuse it
    with the same clear ValueError naming control_sequences."""
    from logprob_scoring import make_first_token_scorer

    post = _FakePost(_scan_body(_gemma_reply_positions()))
    with pytest.raises(ValueError, match="control_sequences"):
        make_first_token_scorer(
            BASE_URL,
            MODEL,
            post=post,
            labels=YES_NO,
            control_sequences=[["<|channel>", 4]],
        )
    assert post.calls == [], (
        "a rejected configuration must never reach the server: no call "
        "may be made when scorer construction refuses the config"
    )


def test_the_dispatch_scorer_builder_rejects_an_empty_sequence_too():
    """make_scorer (the mode dispatcher production launches go through)
    must refuse an empty sequence exactly like the first_token builder:
    the guard must sit on the path launch_sweep actually calls."""
    from logprob_scoring import make_scorer

    with pytest.raises(ValueError, match="control_sequences"):
        make_scorer(
            "first_token",
            BASE_URL,
            MODEL,
            post=_FakePost(_scan_body(_gemma_reply_positions())),
            labels=YES_NO,
            control_sequences=[[]],
        )


def test_a_valid_gemma_header_still_builds_a_scorer_that_consumes_it():
    """Regression lock: the guard must not over-reject. The REAL gemma
    header (four exact strings) still builds a scorer, and that scorer
    walks the header to the sharp position-5 answer as today."""
    from logprob_scoring import make_first_token_scorer

    post = _FakePost(_scan_body(_gemma_reply_positions()))
    scorer = make_first_token_scorer(
        BASE_URL, MODEL, post=post, labels=YES_NO, control_sequences=[GEMMA_HEADER]
    )
    result = scorer([{"role": "user", "content": "buy?"}])
    assert result["decision_position"] == 5, (
        "the valid 4-token header must still be consumed as one block; "
        "the answer sits at position 5"
    )
    assert result["skipped_prefix"] == GEMMA_HEADER
    assert result["p_yes"] == pytest.approx(P_YES_GEMMA)
    assert result["p_no"] == pytest.approx(P_NO_GEMMA)


# ---------------------------------------------------------------------------
# (2) Threading: profile config -> resolver -> manifest -> launch_sweep
# ---------------------------------------------------------------------------


def test_the_queue_plan_layer_resolves_the_gemma_header_and_leaves_everyone_else_off():
    """The queue plan layer resolves per-model control_sequences from
    profile config, mirroring model_top_k exactly: the gemma queue model
    resolves to its channel header (a tuple of token tuples), every other
    queue model and any unknown model resolve to the empty tuple
    (default-off)."""
    import launch_queue

    _require_function(launch_queue, "model_control_sequences", "queue plan layer")
    assert GEMMA_QUEUE_MODEL in launch_queue.MODEL_QUEUE, (
        f"precondition: {GEMMA_QUEUE_MODEL} must still be a queue model "
        "(the gemma override is keyed by its queue model id)"
    )
    resolved = launch_queue.model_control_sequences(GEMMA_QUEUE_MODEL)
    assert resolved == (tuple(GEMMA_HEADER),), (
        f"the gemma profile override must resolve to its 4-token channel "
        f"header as a tuple of token tuples (got: {resolved!r})"
    )
    for model in launch_queue.MODEL_QUEUE:
        if model == GEMMA_QUEUE_MODEL:
            continue
        assert launch_queue.model_control_sequences(model) == (), (
            f"{model} has no header override and must resolve to the "
            "empty tuple (default-off)"
        )
    assert launch_queue.model_control_sequences("vendor/unknown-model") == (), (
        "a model with no override must resolve to the empty tuple "
        "(default-off identity for every unlisted model)"
    )


def _write_durable_none_leg(run_dir: Path, target: dict) -> Path:
    """Pre-write one none leg's full durable records.jsonl (2 cells)."""
    from launch_queue import queue_leg_dir, queue_leg_jsonl

    leg_dir = queue_leg_dir(run_dir, target)
    leg_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in range(int(target["calls"])):
        lines.append(
            json.dumps(
                {
                    "model": target["model"],
                    "product": PRODUCT,
                    "treatment_value": YES_NO_LEVELS[index % len(YES_NO_LEVELS)],
                    "blinding": target["blinding"],
                    "persona_depth": "none",
                    "succeeded": True,
                    "parsed_purchase": True,
                    "elapsed_seconds": 0.1,
                }
            )
        )
    queue_leg_jsonl(leg_dir).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return leg_dir


def _finalize_durable_leg(tmp_path: Path, model: str) -> tuple[Path, list]:
    """Finalize a fully durable none leg through the public leg runner.

    Every cell is already durable, so the leg finalizes without any chat
    or scoring call - the manifest it writes is the artifact under test.
    """
    from launch_grid import _parse_args, _settings_from
    from launch_queue import MODEL_QUEUE, build_logprob_plan
    from launch_queue_leg import run_queue_leg
    from launch_support import _safe_model_name

    args = _parse_args(["--profile", "R1-YESNO", "--run-name", "seq-stamp"])
    settings = replace(_settings_from(args, "seq-stamp"), out=tmp_path, model=model)
    target = {
        "model": model,
        "model_index": MODEL_QUEUE.index(model),
        "safe_model": _safe_model_name(model),
        "depth": "none",
        "blinding": "blinded",
        "calls": 2,
    }
    run_dir = settings.out / settings.run_name
    _write_durable_none_leg(run_dir, target)
    plan = build_logprob_plan(1, len(YES_NO_LEVELS), levels=YES_NO_LEVELS)
    results: list = []
    run_queue_leg(
        settings,
        plan,
        PRODUCTS,
        None,
        run_dir,
        None,
        target,
        results,
        lambda _message: None,
        None,
        None,
    )
    leg_manifest = run_dir / target["safe_model"] / "none_blinded" / "manifest.json"
    return leg_manifest, results


def test_the_gemma_leg_manifest_stamps_the_header_and_other_legs_stamp_an_empty_list(tmp_path):
    """A completed leg's manifest records the control_sequences that were
    in force: the gemma leg stamps its channel header, a leg of any other
    model stamps the empty list - a reader of the records always knows
    which header config a leg ran with."""
    gemma_manifest, gemma_results = _finalize_durable_leg(
        tmp_path, GEMMA_QUEUE_MODEL
    )
    assert gemma_manifest.exists(), "a completed leg must write its manifest.json"
    assert gemma_results and gemma_results[0]["ok"], (
        f"the durable gemma leg must finalize cleanly; got {gemma_results}"
    )
    payload = json.loads(gemma_manifest.read_text(encoding="utf-8"))
    assert payload.get("control_sequences") == [GEMMA_HEADER], (
        f"the gemma leg's manifest must stamp the channel header that was "
        f"in force - without the stamp a reader cannot know which control "
        f"sequences this leg consumed (got: "
        f"{payload.get('control_sequences')!r})"
    )

    other_manifest, _ = _finalize_durable_leg(tmp_path / "other", "openai/gpt-oss-20b")
    other = json.loads(other_manifest.read_text(encoding="utf-8"))
    assert other.get("control_sequences") == [], (
        "a leg of a model without an override stamps the empty list "
        "(default-off is still an explicit, readable stamp)"
    )


def _first_token_settings(tmp_path: Path, model: str):
    """Offline first_token Settings for one launch_sweep leg seam probe."""
    from launch_support import Settings

    return Settings(
        model=model,
        port=8080,
        manager_url=BASE_URL,
        base_url=BASE_URL,
        out=tmp_path,
        run_name="seq-threading-probe",
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="data/configs/unblinding_products.json",
        grammar=None,
        logprob_mode="first_token",
        response_format="yes/no",
    )


def test_launch_sweep_hands_the_gemma_header_to_the_scorer_through_the_post_seam(tmp_path):
    """launch_sweep._make_logprob_scorer must thread the per-model
    control_sequences into the scorer exactly like top_k: a gemma leg's
    scorer consumes the channel header on a synthetic gemma-shaped reply
    THROUGH the threaded path (audit field, decision position and answer
    mass all prove the scorer received the sequence)."""
    from launch_sweep import _make_logprob_scorer

    post = _FakePost(_scan_body(_gemma_reply_positions()))
    scorer_fn, _state, _abort = _make_logprob_scorer(
        _first_token_settings(tmp_path, GEMMA_QUEUE_MODEL),
        1,
        lambda *args: None,
        post=post,
    )
    result = scorer_fn([{"role": "user", "content": "buy?"}])

    assert result.get("control_sequences") == [GEMMA_HEADER], (
        f"the leg scorer must receive the gemma profile's control_sequences "
        f"- launch_sweep must thread the resolver's value into make_scorer "
        f"(got: {result.get('control_sequences')!r})"
    )
    assert result.get("decision_position") == 5, (
        "the threaded header must be consumed as one block: the answer "
        "sits at position 5 (a scorer that never received the sequence "
        "stops at position 2 and misreads the reply)"
    )
    assert result.get("skipped_prefix") == GEMMA_HEADER
    assert result.get("p_yes") == pytest.approx(P_YES_GEMMA), (
        "the yes mass must be read from position 5's sharp top-k through "
        "the threaded path"
    )
    assert result.get("p_no") == pytest.approx(P_NO_GEMMA)
    # Threading is parser-side only: the request payload stays untouched.
    assert post.calls and post.calls[0][0].endswith("/v1/chat/completions")
    assert "control_sequences" not in post.calls[0][1], (
        "control_sequences is walk config, not a request field: the "
        "payload must stay byte-identical apart from the resolved top_k"
    )


def test_a_model_without_overrides_scores_default_off_through_the_leg_seam(tmp_path):
    """Default-off identity through the launch_sweep seam: a model with
    no control_sequences override scores an ordinary single-position
    reply exactly as today - empty audit list, decision at position 1,
    unchanged answer mass."""
    from launch_sweep import _make_logprob_scorer

    plain = [
        ("yes", math.log(0.90), [
            {"token": "yes", "logprob": math.log(0.90)},
            {"token": "no", "logprob": math.log(0.08)},
        ]),
    ]
    post = _FakePost(_scan_body(plain))
    scorer_fn, _state, _abort = _make_logprob_scorer(
        _first_token_settings(tmp_path, "openai/gpt-oss-20b"),
        1,
        lambda *args: None,
        post=post,
    )
    result = scorer_fn([{"role": "user", "content": "buy?"}])

    assert result.get("control_sequences") == [], (
        "a model without an override must run with NO control sequences "
        "(the empty default, not a stray header)"
    )
    assert result.get("decision_position") == 1, (
        "with no sequences configured the walk must stay the historical "
        "single-position behavior (answer at position 1)"
    )
    assert result.get("p_yes") == pytest.approx(0.90), (
        "the answer mass must be unchanged by the threading work for "
        "models without overrides"
    )
