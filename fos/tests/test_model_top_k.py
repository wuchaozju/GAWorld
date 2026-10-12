# Locked tests for the per-model top_k override in the queue plan layer
# (TASK-1578, RED phase; tests ONLY - no implementation lives here).
#
# WHY THESE TESTS EXIST: the muse model's useful yes/no candidates only
# show up in a top-100 candidate list (user launch order 2026-09-11:
# k=100 pins the free-cell no-branch, rank 44-50 at k=50), while every
# other model keeps the historical top-20. The override must therefore
# live in the queue
# PROFILE CONFIG (never a hardcoded model-name branch in scoring code):
# a plan-layer resolver answers "what k does this model use?", the
# first_token REQUEST carries the resolved k (payload top_logprobs), and
# a completed leg's MANIFEST stamps the k that was in force - so a
# reader of the records always knows how much coverage the top-k lists
# of a leg have.
#
# All offline: the fake HTTP poster IS the only transport; no network,
# no model loads, and NEVER the full test suite (live-API tests are out
# of budget). The 62 locked offline tests in the existing files stay
# green.
import inspect
import json
import math
import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

BASE_URL, MODEL = "http://127.0.0.1:9", "vendor/model"
YES_NO = ("yes", "no")
LEVELS = [0.0, 100.0]
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


def _scan_body() -> str:
    """One ordinary single-position first_token reply (answer at pos 1)."""
    top_k = [
        {"token": "yes", "logprob": math.log(0.90)},
        {"token": "no", "logprob": math.log(0.08)},
    ]
    block = {"token": "yes", "logprob": math.log(0.90), "top_logprobs": top_k}
    choice = {
        "message": {"content": "yes"},
        "logprobs": {"content": [block]},
    }
    return json.dumps({"choices": [choice]})


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
                    "treatment_value": LEVELS[index % len(LEVELS)],
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
    from dataclasses import replace

    from launch_grid import _parse_args, _settings_from
    from launch_queue import build_logprob_plan
    from launch_queue_leg import run_queue_leg
    from launch_support import _safe_model_name

    args = _parse_args(["--profile", "R1-YESNO", "--run-name", "k-stamp"])
    settings = replace(_settings_from(args, "k-stamp"), out=tmp_path, model=model)
    target = {
        "model": model,
        "model_index": 4 if "muse" in model else 0,
        "safe_model": _safe_model_name(model),
        "depth": "none",
        "blinding": "blinded",
        "calls": 2,
    }
    run_dir = settings.out / settings.run_name
    _write_durable_none_leg(run_dir, target)
    plan = build_logprob_plan(1, len(LEVELS), levels=LEVELS)
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


def test_request_top_k_is_configurable_and_defaults_to_twenty():
    """The first_token request's top-k (payload top_logprobs) defaults to
    the historical 20 and is configurable per call - never hardcoded."""
    from logprob_scoring import make_first_token_scorer, make_scorer

    _require_parameter(make_first_token_scorer, "top_k", "make_first_token_scorer")
    _require_parameter(make_scorer, "top_k", "make_scorer")

    default_post = _FakePost(_scan_body())
    _first_token_scorer(default_post)([{"role": "user", "content": "buy?"}])
    assert default_post.calls[0][1]["top_logprobs"] == 20, (
        "without an override the request must keep the historical top_logprobs=20"
    )

    muse_post = _FakePost(_scan_body())
    _first_token_scorer(muse_post, top_k=100)([{"role": "user", "content": "buy?"}])
    assert muse_post.calls[0][1]["top_logprobs"] == 100, (
        "the request must use the configured top_k (the muse-style "
        "top-100 sweep) instead of the hardcoded 20"
    )

    dispatch_post = _FakePost(_scan_body())
    make_scorer(
        "first_token", BASE_URL, MODEL, post=dispatch_post, labels=YES_NO, top_k=100
    )([{"role": "user", "content": "buy?"}])
    assert dispatch_post.calls[0][1]["top_logprobs"] == 100


def test_muse_profile_overrides_top_k_to_one_hundred_others_keep_twenty():
    """The queue plan layer resolves the per-model top_k from config:
    muse-glimmer -> 100, every other queue model (and any unknown model)
    -> 20."""
    import launch_queue

    _require_function(launch_queue, "model_top_k", "queue plan layer")
    from launch_queue import MODEL_QUEUE, model_top_k

    # user launch order 2026-09-11: k=100 pins the free-cell no-branch (rank 44-50 at k=50)
    assert model_top_k("meta/muse-glimmer") == 100, (
        "the muse profile override must resolve to top_k 100"
    )
    for model in MODEL_QUEUE:
        if model == "meta/muse-glimmer":
            continue
        assert model_top_k(model) == 20, f"{model} must keep the historical top_k 20"
    assert model_top_k("vendor/unknown-model") == 20, (
        "a model with no override keeps the historical 20"
    )


def test_the_muse_leg_manifest_stamps_the_overridden_top_k(tmp_path):
    """A completed leg's manifest records the per-leg k that was in force:
    100 for the muse leg, 20 for another model's leg."""
    muse_manifest, muse_results = _finalize_durable_leg(tmp_path, "meta/muse-glimmer")
    assert muse_manifest.exists(), "a completed leg must write its manifest.json"
    assert muse_results and muse_results[0]["ok"], (
        f"the durable muse leg must finalize cleanly; got {muse_results}"
    )
    payload = json.loads(muse_manifest.read_text(encoding="utf-8"))
    assert "top_k" in payload and payload["top_k"] == 100, (
        f"the muse leg's manifest must stamp the overridden top_k 100 - "
        f"without the stamp a reader cannot know which coverage the "
        f"top-k lists of this leg have (got: {payload.get('top_k')!r})"
    )

    other_manifest, _ = _finalize_durable_leg(tmp_path / "other", "openai/gpt-oss-20b")
    other = json.loads(other_manifest.read_text(encoding="utf-8"))
    assert "top_k" in other and other["top_k"] == 20, (
        "a leg of a model without an override stamps the historical 20"
    )


def test_scoring_code_never_hardcodes_a_model_name():
    """The scoring module stays model-agnostic: per-model tuning lives in
    the queue profile config, never in a hardcoded model-name branch."""
    import logprob_scoring

    source = Path(logprob_scoring.__file__).read_text(encoding="utf-8")
    assert "muse" not in source.lower(), (
        "logprob_scoring.py must not name any model: the per-model "
        "top_k override is queue-profile config, not a scoring-code "
        "conditional"
    )
