"""
Tests for the provider-failure guard in the experiment runner.

These tests specify that an LLM provider outage (connection refused, timeout,
auth failure, HTTP 5xx, ...) must be treated as an EXECUTION failure that
aborts the round and stops the experiment — never silently converted into
per-agent "skips" that look like legitimate agent decisions.

They also pin the behaviours that must NOT change:
- a legitimate skip (LLM answered, agent chose "skip") stays skipped=True,
  success=True, error empty, and the experiment continues
- an all-agents-skipped round with zero execution errors stays a valid round
- a healthy run is unchanged
- no silent fallback: when the selected provider fails, no other LLM client
  is constructed or called

All tests use a fake in-process LLM client — no network, no real server.
"""

import asyncio

import pytest
from unittest.mock import Mock, patch

from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig, PRISONERS_DILEMMA
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.llm_config import LLMConfig

COOPERATE_JSON = '{"reasoning": "I choose to cooperate", "action": "cooperate"}'
SKIP_JSON = '{"reasoning": "I sit this one out", "action": "skip"}'

# A group-mode public-goods-style config: every agent plays every round and
# an explicit "skip" is an allowed (legitimate) action.
GROUP_GAME = GameConfig(
    name="Public Goods Test Game",
    description="Everyone decides independently; skip is allowed.",
    action_type="discrete",
    actions=["cooperate", "defect", "skip"],
    action_descriptions={
        "cooperate": "Contribute",
        "defect": "Keep everything",
        "skip": "Sit this round out",
    },
    grouping_mode="group",
    payoff_type="none",
)


class DeadProviderClient:
    """Fake LLM client whose provider is unreachable — every call raises."""

    def __init__(self, lm_studio=False):
        self.calls = 0
        self.provider = Mock()
        # Only the preflight test points at an LM Studio endpoint, so that
        # _preload_model's warm-up path is exercised there. Run-level tests
        # use a plain provider so no model preload interferes with the script.
        self.provider.base_url = "http://localhost:1234/v1" if lm_studio else ""
        self.provider.model = "qwen/qwen3-4b-2507" if lm_studio else ""

    def chat(self, messages, json_mode=False, max_tokens=None):
        self.calls += 1
        raise ConnectionError("Connection error.")


class ScriptedClient:
    """Fake LLM client returning scripted responses, then raising."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.provider = Mock()
        self.provider.base_url = ""
        self.provider.model = ""

    def chat(self, messages, json_mode=False, max_tokens=None):
        self.calls += 1
        if not self.script:
            raise ConnectionError("Connection error.")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_agents(n):
    return [
        ExperimentAgent(
            name=f"Agent {i + 1}",
            properties={"age_group": "adult"},
            llm_config=LLMConfig(dialect="mock"),
        )
        for i in range(n)
    ]


def make_runner(n_agents, client, round_visibility="simultaneous"):
    return ExperimentRunner(
        agents=make_agents(n_agents),
        game_config=GROUP_GAME,
        llm_client=client,
        kernel=ExperimentKernel(),
        round_visibility=round_visibility,
    )


async def run_stopping_at_failure(runner, max_rounds):
    """Run the experiment; if the runner raises, treat it as a loud abort."""
    try:
        return await runner.run(max_rounds=max_rounds), None
    except Exception as exc:  # a loud abort is an acceptable contract
        return [], exc


def failure_text(round_or_exc):
    """The failure reason carried by an aborted round or raised exception."""
    if round_or_exc is None:
        return ""
    return str(
        getattr(round_or_exc, "failure_reason", "")
        or getattr(round_or_exc, "error", "")
        or round_or_exc
    )


def is_provider_failure(text):
    lowered = text.lower()
    return "provider" in lowered or "connection" in lowered


def no_failure_disguised_as_skip(rounds):
    """Provider failures must never share the skip semantic state."""
    disguised = [
        action
        for round_result in rounds
        for action in round_result.actions
        if action.skipped and not action.success
    ]
    assert not disguised, (
        "provider/execution failures must not be recorded as skips; got: "
        f"{[(a.agent_name, a.error) for a in disguised]}"
    )


# ---------------------------------------------------------------------------
# 1. Provider unavailable before the run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_provider_stops_experiment_with_no_legitimate_skips():
    """Provider down from the start: the run fails loudly, nobody 'skips'."""
    client = DeadProviderClient()
    runner = make_runner(2, client)
    results, exc = await run_stopping_at_failure(runner, max_rounds=2)

    # The experiment must not complete normally.
    assert exc is not None or not results or not all(
        r.completed for r in results
    ), "experiment reported normal completion while the provider was down"

    # No agent may be counted as a legitimate skip.
    no_failure_disguised_as_skip(results)

    # The failure must be surfaced with provider/model information.
    text = failure_text(exc if exc is not None else (results[-1] if results else None))
    assert is_provider_failure(text), (
        f"expected a provider/connection failure reason, got: {text!r}"
    )


@pytest.mark.asyncio
async def test_dead_provider_does_not_record_completed_rounds():
    """A round where the provider was down is not recorded as completed."""
    client = DeadProviderClient()
    runner = make_runner(2, client)
    results, exc = await run_stopping_at_failure(runner, max_rounds=1)

    if exc is None and results:
        assert results[0].completed is False, (
            "round recorded as completed although every provider call failed"
        )
        assert results[0].payoffs is None, (
            "payoffs were computed for a round whose provider was down"
        )


# ---------------------------------------------------------------------------
# 2. Provider dies mid-round (agent 1 ok, agent 2 provider error)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_dying_mid_round_fails_the_round_and_stops():
    """One agent answered, then the provider died: partial round must fail."""
    client = ScriptedClient([COOPERATE_JSON])  # first call ok, then dead
    runner = make_runner(2, client)
    results, exc = await run_stopping_at_failure(runner, max_rounds=2)

    # The experiment must stop — it may not march on to round 2.
    assert exc is not None or len(results) < 2, (
        "experiment continued past a round in which the provider died"
    )

    if exc is None and results:
        round_result = results[0]
        # The round is incomplete — a partial round is never "completed".
        assert round_result.completed is False
        # Never compute game results from a partial round.
        assert round_result.payoffs is None
        # The one successful answer is preserved for diagnostics.
        ok = [a for a in round_result.actions if a.success]
        assert len(ok) == 1, "the agent that answered before the outage was lost"
        # The provider failure is not disguised as a skip.
        no_failure_disguised_as_skip(results)
        assert is_provider_failure(failure_text(round_result))


# ---------------------------------------------------------------------------
# 3. Provider dies in a later round
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_dying_in_later_round_keeps_earlier_rounds_valid():
    """Round 1 succeeded, round 2's provider died: history stays intact."""
    client = ScriptedClient([COOPERATE_JSON, COOPERATE_JSON])  # round 1 ok
    runner = make_runner(2, client)
    results, exc = await run_stopping_at_failure(runner, max_rounds=2)

    assert len(results) >= 1, "even round 1 is missing"
    first = results[0]
    assert first.completed is True, "round 1 was valid but is not marked completed"
    assert all(a.success for a in first.actions), "round 1 actions were corrupted"
    assert len(first.actions) == 2

    assert exc is not None or len(results) < 2 or results[1].completed is False, (
        "round 2 was recorded as completed although the provider was dead"
    )
    if len(results) >= 2:
        no_failure_disguised_as_skip([results[1]])
        assert is_provider_failure(failure_text(results[1]))


# ---------------------------------------------------------------------------
# 4. Legitimate skip stays a skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legitimate_skip_is_preserved_and_experiment_continues():
    """LLM answers and the agent explicitly skips: a genuine skip, no error."""
    client = ScriptedClient([SKIP_JSON, SKIP_JSON, SKIP_JSON, SKIP_JSON])
    runner = make_runner(2, client)
    results = await runner.run(max_rounds=2)

    assert len(results) == 2, "the experiment must continue after a legitimate skip"
    for round_result in results:
        assert round_result.completed is True
        for action in round_result.actions:
            assert action.skipped is True
            assert action.success is True
            assert not action.error, f"legitimate skip carries an error: {action.error!r}"


# ---------------------------------------------------------------------------
# 5. All agents legitimately skipping is a valid round
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_agents_skipping_is_still_a_valid_round():
    """Everyone chooses skip with a healthy provider: the round is valid."""
    client = ScriptedClient([SKIP_JSON, SKIP_JSON])
    runner = make_runner(2, client)
    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    round_result = results[0]
    assert round_result.completed is True, "an all-skip round must remain valid"
    assert all(a.skipped and a.success for a in round_result.actions)
    assert not any(a.error for a in round_result.actions)


# ---------------------------------------------------------------------------
# 6. All skipped AND at least one execution error → round rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_skipped_with_an_execution_error_rejects_the_round():
    """One agent errored, the rest skipped: the round must fail, not complete."""
    client = ScriptedClient([SKIP_JSON])  # agent 1 skips, agent 2 hits dead provider
    runner = make_runner(2, client)
    results, exc = await run_stopping_at_failure(runner, max_rounds=1)

    assert exc is not None or (results and results[0].completed is False), (
        "a round with an execution error was accepted as completed"
    )
    if results:
        no_failure_disguised_as_skip(results)
        assert is_provider_failure(failure_text(results[0]))


# ---------------------------------------------------------------------------
# 7. No silent provider fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_silent_fallback_to_another_provider():
    """When the selected provider fails, no other LLM client is used."""
    client = DeadProviderClient()
    runner = make_runner(2, client)

    with patch("fos.core.experiment.runner.LLMClient") as fallback_client_cls:
        fallback_client_cls.return_value.chat = Mock(return_value=COOPERATE_JSON)
        results, exc = await run_stopping_at_failure(runner, max_rounds=1)

    # No fallback client was ever constructed or spoken to.
    assert fallback_client_cls.call_count == 0, (
        "a fallback LLM client was constructed after the provider failure"
    )

    # And the failure itself is loud, not hidden behind skips or fallback.
    assert exc is not None or (results and results[0].completed is False)
    no_failure_disguised_as_skip(results)


# ---------------------------------------------------------------------------
# 6b. Parse failures stay distinct from provider outages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_output_is_not_misclassified_as_provider_failure():
    """A bad JSON answer is a parse failure — it must not abort as an outage."""
    client = ScriptedClient([COOPERATE_JSON, "this is not json at all"])
    runner = make_runner(2, client)
    results = await runner.run(max_rounds=1)

    assert len(results) == 1
    text = failure_text(results[0])
    if text:
        assert not is_provider_failure(text), (
            "a malformed model answer was misclassified as a provider outage"
        )


# ---------------------------------------------------------------------------
# 8. Healthy Public Goods-style regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthy_run_five_agents_three_rounds_is_unchanged():
    """Provider healthy: 5 agents × 3 rounds, everyone acts, nothing changes."""
    client = ScriptedClient([COOPERATE_JSON] * 15)
    runner = make_runner(5, client)
    results = await runner.run(max_rounds=3)

    assert len(results) == 3
    for round_result in results:
        assert round_result.completed is True
        assert len(round_result.actions) == 5
        assert all(a.success for a in round_result.actions)
        assert not any(a.skipped for a in round_result.actions)


# ---------------------------------------------------------------------------
# Preflight: a failed warm-up must prevent the experiment from starting
# ---------------------------------------------------------------------------


def test_preflight_warmup_failure_prevents_experiment_start(monkeypatch):
    """Warm-up pings a dead provider: preflight must fail, not continue anyway."""
    monkeypatch.delenv("FOS_MODEL_MANAGER_URL", raising=False)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    client = DeadProviderClient(lm_studio=True)
    runner = make_runner(2, client)

    # Keep the LM Studio admin endpoints offline (no network in tests).
    monkeypatch.setattr(runner, "_trigger_model_load", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_unload_stale_lm_studio_models", lambda *a, **k: None)

    ready = runner._preload_model("qwen/qwen3-4b-2507", client)

    assert ready is False, (
        "preflight reported the provider as ready although every warm-up "
        "ping failed with a connection error"
    )
    assert client.calls > 0, "preflight never contacted the provider"
