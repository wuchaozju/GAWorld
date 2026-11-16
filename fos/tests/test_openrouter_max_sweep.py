# Locked tests for the OPENROUTER QWEN3.8-MAX GRAMMAR SWEEP (TASK-1653,
# RED phase; tests ONLY - no implementation lives here): the SPEC half.
# This file pins the pure specification of scripts/openrouter_max_sweep.py:
# the profile stamp, the pinned model id, the local-R1-5MODEL temperatures,
# the cost table, the exact response_format JSON schema, the reused persona
# pool source, the 7,040-call plan geometry with the four spread personas
# of the shared [40, 60) slice, decision parsing, cost math, and the
# politeness rules (429/5xx retry with backoff, loud abort on a rejected
# model id). The RUN half (prompt parity, records, durability, resume,
# cost guard, offline CLI) lives in tests/test_openrouter_max_sweep_run.py.
#
# Everything here is OFFLINE: no network, no API key, no GPU. The harness
# module does not exist yet, so every test below must fail with its
# missing-feature error - never a syntax error.
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import launch_queue  # noqa: E402
from fos.experiments import sweep_kit  # noqa: E402
from tests.openrouter_max_sweep_spec import EXACT_RESPONSE_FORMAT, fake_pool  # noqa: E402

import openrouter_max_sweep as harness  # noqa: E402


# ---------------------------------------------------------------------------
# (1) Spec constants: profile, model, temperatures, prices, schema, pools
# ---------------------------------------------------------------------------


def test_profile_model_temperatures_and_prices_are_pinned():
    """The harness stamps R1-API-QWEN38MAX, pins qwen/qwen3.8-max-0902 (never
    the bare qwen3.8-max alias), reuses the local R1-5MODEL temperatures, and
    carries the pinned cost table and politeness knobs."""
    assert harness.SWEEP_PROFILE == "R1-API-QWEN38MAX"
    assert harness.DEFAULT_MODEL == "qwen/qwen3.8-max-0902"
    assert "qwen3.8-max-0902" in harness.DEFAULT_MODEL
    assert harness.NONE_LEG_TEMPERATURE == sweep_kit._TEMPERATURE == 1.0
    assert harness.PERSONA_LEG_TEMPERATURE == sweep_kit._PERSONA_TEMPERATURE == 0.0
    assert harness.DEFAULT_DRAWS == 4
    assert harness.PROMPT_USD_PER_M == 2.0
    assert harness.COMPLETION_USD_PER_M == 6.0
    assert harness.DEFAULT_MAX_COST_USD == 15.0
    assert harness.DEFAULT_CONCURRENCY == 4
    assert harness.MAX_TRIES == 5
    assert harness.DEFAULT_TIMEOUT_SECONDS > 0


def test_response_format_is_the_exact_pinned_json_schema():
    """Every request must force the decision with exactly this strict JSON
    schema - the API stand-in for the local one-token GBNF grammar."""
    assert harness.build_response_format() == EXACT_RESPONSE_FORMAT


def test_persona_pool_source_is_the_shared_reused_pools_dir():
    """The harness reuses the same archived persona pools the other R1 runs
    reused (launch_queue.DEFAULT_POOLS_FROM), not a freshly drawn pool."""
    assert harness.DEFAULT_POOLS_FROM == launch_queue.DEFAULT_POOLS_FROM
    assert "R1-nemotron-cascade-2-30b-a3b-20260909T004614" in harness.DEFAULT_POOLS_FROM


# ---------------------------------------------------------------------------
# (2) Plan geometry: 7,040 calls across 4 legs; the 4 spread personas
# ---------------------------------------------------------------------------


def test_full_plan_is_7040_calls_across_four_legs():
    """40 products x 11 levels x 2 blindings x (4 draws none + 4 personas)
    = 7,040 calls; the plan records the four legs with their call counts."""
    plan = harness.build_max_sweep_plan(40, 11, levels=[float(x) for x in range(0, 220, 20)])
    assert plan["profile"] == "R1-API-QWEN38MAX"
    assert plan["model"] == harness.DEFAULT_MODEL
    assert plan["seed"] == 42
    assert plan["draws"] == 4
    assert plan["persona_indices"] == (40, 46, 52, 58)
    assert plan["sweep_calls"] == 7040
    legs = {(leg["depth"], leg["blinding"]): leg["calls"] for leg in plan["legs"]}
    assert set(legs) == {
        ("none", "blinded"),
        ("none", "unblinded"),
        ("demographics", "blinded"),
        ("demographics", "unblinded"),
    }
    for (_depth, _blinding), calls in legs.items():
        assert calls == 40 * 11 * 4, "every leg plans 4 cells per (product x level)"


def test_persona_subsample_picks_the_four_spread_indices_deterministically():
    """The demographics draws are pool personas 40, 46, 52 and 58, in that
    order, always the same; a pool too short to hold them is refused, never
    silently subsampled from fewer."""
    pool = fake_pool(100)
    picked = harness.subsample_personas(pool)
    assert picked == [pool[40], pool[46], pool[52], pool[58]]
    assert harness.subsample_personas(pool) == picked
    with pytest.raises(RuntimeError):
        harness.subsample_personas(pool[:41])


# ---------------------------------------------------------------------------
# (4a) Parsing and cost math (pure functions)
# ---------------------------------------------------------------------------


def test_decision_is_parsed_from_the_content_json_object():
    """choices[0].message.content is a JSON object; only its decision field
    counts: purchase -> True, not purchase -> False, anything else -> None."""
    assert harness.parse_decision('{"decision": "purchase"}') is True
    assert harness.parse_decision('{"decision": "not purchase"}') is False
    assert harness.parse_decision('  {"decision":"purchase"}\n') is True
    assert harness.parse_decision('{"decision": "maybe"}') is None
    assert harness.parse_decision('{"other": "purchase"}') is None
    assert harness.parse_decision("garbage not json") is None
    assert harness.parse_decision("") is None


def test_call_cost_comes_from_usage_at_the_pinned_prices():
    """$2.00 per million prompt tokens + $6.00 per million completion tokens,
    computed straight from a response usage block."""
    assert harness.call_cost_usd(
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    ) == pytest.approx(8.0)
    assert harness.call_cost_usd({"prompt_tokens": 500_000}) == pytest.approx(1.0)
    assert harness.call_cost_usd({}) == 0.0


# ---------------------------------------------------------------------------
# (7) Politeness: retries with backoff; model-id rejection aborts loudly
# ---------------------------------------------------------------------------


class FlakyTransport:
    """A transport whose responses are a scripted list: raise the scripted
    exception or return the scripted body, one entry per call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, _payload):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok_response() -> dict:
    """One successful OpenRouter-shaped response body."""
    return {
        "choices": [{"message": {"content": '{"decision": "purchase"}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }


def test_rate_limits_and_server_errors_are_retried_with_backoff():
    """A 429 then a 503 are retried with growing sleeps and the call still
    succeeds; a call that never succeeds gives up after exactly MAX_TRIES."""
    sleeps: list[float] = []
    flaky = FlakyTransport(
        [
            harness.OpenRouterError(429, "rate limited"),
            harness.OpenRouterError(503, "upstream busy"),
            _ok_response(),
        ]
    )
    chat_fn = harness.make_openrouter_chat_fn(
        flaky, model=harness.DEFAULT_MODEL, sleep=sleeps.append
    )
    answer = chat_fn([{"role": "user", "content": "hi"}], 1.0)
    assert answer == '{"decision": "purchase"}'
    assert flaky.calls == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]

    always_429 = FlakyTransport([harness.OpenRouterError(429, "slow down")])
    chat_fn = harness.make_openrouter_chat_fn(
        always_429, model=harness.DEFAULT_MODEL, sleep=sleeps.append
    )
    with pytest.raises(harness.OpenRouterError):
        chat_fn([{"role": "user", "content": "hi"}], 1.0)
    assert always_429.calls == harness.MAX_TRIES == 5


def test_model_id_rejection_aborts_naming_the_model_without_substitution():
    """When OpenRouter rejects the pinned model id the harness aborts at once
    with a clear error naming it - it never retries into another model."""
    from tests.openrouter_max_sweep_spec import FakeTransport

    class RejectingTransport(FakeTransport):
        def __call__(self, payload):
            self.payloads.append(payload)
            raise harness.OpenRouterError(404, "no endpoint found for that model")

    rejecting = RejectingTransport()
    chat_fn = harness.make_openrouter_chat_fn(
        rejecting, model=harness.DEFAULT_MODEL, sleep=lambda _s: None
    )
    with pytest.raises(RuntimeError) as excinfo:
        chat_fn([{"role": "user", "content": "hi"}], 1.0)
    assert harness.DEFAULT_MODEL in str(excinfo.value)
    assert len(rejecting.payloads) == 1, "a rejected model id must abort at once"
