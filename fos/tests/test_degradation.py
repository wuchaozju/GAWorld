"""
Tests for the 3-tier overflow degradation cascade in runner._prompt_agent.

Covers four scenarios:
- Clean prompt that fits within the context limit (no degradation)
- Prompt slightly over limit, recap at 400 tokens fits (recap_400)
- Prompt far over limit, dropping old rounds works (rounds_dropped)
- Prompt impossibly large, nothing fits (failed)
"""

import asyncio
import threading
from unittest.mock import Mock, AsyncMock, patch

import pytest

from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.controller import ActionResult
from fos.core.experiment.round_context import RoundEvent
from fos.core.experiment.information_model import InformationModel
from fos.core.llm_config import LLMConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(name: str) -> ExperimentAgent:
    """Create a minimal ExperimentAgent for testing."""
    return ExperimentAgent(
        name=name,
        properties={"age_group": "adult"},
        llm_config=LLMConfig(dialect="mock"),
        score=0,
    )


def _make_round_events() -> list[RoundEvent]:
    """Create 6 events across 3 rounds (2 per round), visible to all agents."""
    agents = ["Alice", "Bob"]
    events = []
    for rnd in range(1, 4):
        for agent in agents:
            events.append(RoundEvent(
                agent_name=agent,
                action_name="cooperate",
                parameters={},
                round_num=rnd,
                summary=f"{agent} cooperated in round {rnd}",
                observed_by=list(agents),  # everyone sees everything
            ))
    return events


def _make_game_config_mock():
    """Return a Mock with the attributes _prompt_agent accesses on self.game_config."""
    gc = Mock()
    gc.description = "test scenario"
    gc.actions = ["cooperate", "defect"]
    gc.action_schemas = {}
    gc.action_followup_modes = None
    gc.action_type = "discrete"
    gc.output_field = "action"
    gc.action_descriptions = {}
    return gc


def _make_llm_client(server_ctx_size: int) -> Mock:
    """Return a mock LLM client configured for Path 2 (no model lock)."""
    client = Mock()
    client.server_ctx_size = server_ctx_size
    client.provider = Mock()
    client.provider.model = ""       # empty → Path 2 (no lock)
    client.provider.max_tokens = 0   # int → _limit = server_ctx_size - 0 - 100
    client.chat = Mock(return_value='{"action": "cooperate"}')
    return client


def _make_minimal_runner(agents: list, mock_client: Mock) -> ExperimentRunner:
    """Build an ExperimentRunner with minimal dependencies for _prompt_agent tests.

    Most functionality (controller, kernel, context manager) is kept real but
    populated with mocks so _prompt_agent can execute without an LLM server.
    """
    info_model = InformationModel(
        scope_type="all",
        recap_tokens=400,
        include_scores=False,
    )
    runner = ExperimentRunner(
        agents=agents,
        game_config=_make_game_config_mock(),
        llm_client=mock_client,
        round_visibility="simultaneous",
        information_model=info_model,
    )
    # Populate _round_events so the degradation tiers have data to filter
    runner.context_manager._round_events = _make_round_events()
    return runner


# ---------------------------------------------------------------------------
# Patches shared across tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_async_debug_write():
    """Prevent _write_debug_atomically from actually writing files."""
    with patch.object(ExperimentRunner, "_write_debug_atomically", AsyncMock()):
        yield


# ---------------------------------------------------------------------------
# Test 1 — Clean prompt, no degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_prompt_no_degradation():
    """Prompt fits within the context limit — no degradation applied.

    Expected:
        - result.degraded == False
        - result.degrade_reason == ""
        - LLM chat was called
    """
    alice = _make_agent("Alice")
    bob = _make_agent("Bob")
    agents = [alice, bob]

    # server_ctx_size=10000 → _limit = 10000-0-100 = 9900, short prompt fits
    llm_client = _make_llm_client(server_ctx_size=10_000)

    runner = _make_minimal_runner(agents, llm_client)

    with patch("fos.core.experiment.runner._count_tokens", side_effect=lambda text: len(text)):
        with patch("fos.core.experiment.runner.build_prompt", return_value="short_prompt"):
            with patch("fos.core.experiment.runner.build_structured_context", return_value="ctx"):
                with patch("fos.core.experiment.runner._truncate_speech_events", side_effect=lambda evts, cap: evts):
                    controller_result = ActionResult(
                        success=True,
                        action_name="cooperate",
                        parameters={},
                        summary="Alice cooperated",
                        agent_name="Alice",
                        round_num=1,
                    )
                    runner.controller.process_response_with_followup = AsyncMock(
                        return_value=controller_result
                    )
                    result = await runner._prompt_agent(alice, 1)

    assert result.degraded == False, "Prompt fit — should not be marked degraded"
    assert result.degrade_reason == "", "No degradation reason expected"
    assert result.tokens_before == len("short_prompt")
    assert result.tokens_after == 0  # not set when not degraded
    assert llm_client.chat.called, "LLM chat should have been called"


# ---------------------------------------------------------------------------
# Test 2 — Recap at 400 tokens fits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recap_400_degradation():
    """Prompt is slightly over the limit, but recap at 400 tokens fits.

    Expected:
        - result.degraded == True
        - result.degrade_reason == "recap_400"
        - result.tokens_before > result.tokens_after
        - LLM chat was called (not skipped)
    """
    alice = _make_agent("Alice")
    bob = _make_agent("Bob")
    agents = [alice, bob]

    # server_ctx_size=500 → _limit = 500-0-100 = 400
    # original prompt ~1011 chars > 400 → triggers degradation
    # recap prompt ~312 chars ≤ 400 → recap_400 fits
    llm_client = _make_llm_client(server_ctx_size=500)

    runner = _make_minimal_runner(agents, llm_client)

    prompt_returns = [
        "BIG_PROMPT" + "x" * 1000,   # original: ~1011 chars > 400
        "RECAP_PROMPT" + "x" * 300,  # recap: ~312 chars ≤ 400
    ]

    with patch("fos.core.experiment.runner._count_tokens", side_effect=lambda text: len(text)):
        with patch("fos.core.experiment.runner.build_prompt", side_effect=prompt_returns):
            with patch("fos.core.experiment.runner.build_structured_context", return_value="ctx"):
                with patch("fos.core.experiment.runner._truncate_speech_events", side_effect=lambda evts, cap: evts):
                    controller_result = ActionResult(
                        success=True,
                        action_name="cooperate",
                        parameters={},
                        summary="Alice cooperated",
                        agent_name="Alice",
                        round_num=1,
                    )
                    runner.controller.process_response_with_followup = AsyncMock(
                        return_value=controller_result
                    )
                    result = await runner._prompt_agent(alice, 1)

    assert result.degraded == True, "Prompt exceeded limit — should be degraded"
    assert result.degrade_reason == "recap_400", (
        f"Expected recap_400, got {result.degrade_reason!r}"
    )
    assert result.tokens_before > result.tokens_after, (
        f"tokens_before ({result.tokens_before}) should be > tokens_after ({result.tokens_after})"
    )
    assert llm_client.chat.called, "LLM chat should have been called after recap"


# ---------------------------------------------------------------------------
# Test 3 — Dropping old rounds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rounds_dropped_degradation():
    """Prompt is far over the limit — recap_400 still too big, but dropping rounds helps.

    Expected:
        - result.degraded == True
        - result.degrade_reason == "rounds_dropped"
        - result.rounds_dropped > 0
        - tokens_before > tokens_after
        - Round 1 events retained in the rebuilt context
        - LLM chat was called
    """
    alice = _make_agent("Alice")
    bob = _make_agent("Bob")
    agents = [alice, bob]

    # server_ctx_size=300 → _limit = 300-0-100 = 200
    # original ~2011 > 200, recap ~516 > 200, dropped ~113 ≤ 200 → rounds_dropped
    llm_client = _make_llm_client(server_ctx_size=300)

    runner = _make_minimal_runner(agents, llm_client)

    prompt_returns = [
        "HUGE_PROMPT" + "x" * 2000,       # ~2011 chars > 200
        "STILL_BIG_RECAP" + "x" * 500,    # ~516 chars > 200
        "SMALL_DROPPED" + "x" * 100,      # ~113 chars ≤ 200 — fits!
    ]

    with patch("fos.core.experiment.runner._count_tokens", side_effect=lambda text: len(text)):
        with patch("fos.core.experiment.runner.build_prompt", side_effect=prompt_returns):
            with patch("fos.core.experiment.runner.build_structured_context", return_value="ctx"):
                with patch("fos.core.experiment.runner._truncate_speech_events", side_effect=lambda evts, cap: evts):
                    controller_result = ActionResult(
                        success=True,
                        action_name="cooperate",
                        parameters={},
                        summary="Alice cooperated",
                        agent_name="Alice",
                        round_num=1,
                    )
                    runner.controller.process_response_with_followup = AsyncMock(
                        return_value=controller_result
                    )
                    result = await runner._prompt_agent(alice, 1)

    assert result.degraded == True, "Prompt exceeded limit — should be degraded"
    assert result.degrade_reason == "rounds_dropped", (
        f"Expected rounds_dropped, got {result.degrade_reason!r}"
    )
    assert result.rounds_dropped > 0, "At least one round should have been dropped"
    assert result.tokens_before > result.tokens_after, (
        f"tokens_before ({result.tokens_before}) should be > "
        f"tokens_after ({result.tokens_after})"
    )
    assert llm_client.chat.called, "LLM chat should have been called after dropping rounds"


# ---------------------------------------------------------------------------
# Test 4 — Nothing fits → failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_failed_degradation():
    """Prompt is impossibly large — none of the three tiers can fit it in the limit.

    Expected:
        - result.degraded == True
        - result.degrade_reason == "failed"
        - result.skipped == True
        - result.error contains "overflow" or "degradation"
        - LLM chat was NOT called
    """
    alice = _make_agent("Alice")
    bob = _make_agent("Bob")
    agents = [alice, bob]

    # server_ctx_size=50 → _limit = 50-0-100 = -50, nothing will fit
    llm_client = _make_llm_client(server_ctx_size=50)

    runner = _make_minimal_runner(agents, llm_client)

    prompt_returns = [
        "HUGE" + "x" * 10000,  # ~10004 chars > -50
        "HUGE" + "x" * 5000,   # ~5004 chars > -50
        "HUGE" + "x" * 3000,   # ~3004 chars > -50
        "HUGE" + "x" * 1000,   # ~1004 chars > -50  (all rounds dropped)
    ]

    with patch("fos.core.experiment.runner._count_tokens", side_effect=lambda text: len(text)):
        with patch("fos.core.experiment.runner.build_prompt", side_effect=prompt_returns):
            with patch("fos.core.experiment.runner.build_structured_context", return_value="ctx"):
                with patch("fos.core.experiment.runner._truncate_speech_events", side_effect=lambda evts, cap: evts):
                    result = await runner._prompt_agent(alice, 1)

    assert result.degraded == True, "Should be marked as degraded"
    assert result.degrade_reason == "failed", (
        f"Expected 'failed', got {result.degrade_reason!r}"
    )
    assert result.skipped == True, "Failed degradation should result in skipped turn"
    assert "overflow" in result.error or "degradation" in result.error, (
        f"Error message should mention overflow or degradation, got: {result.error!r}"
    )
    assert not llm_client.chat.called, (
        "LLM chat should NOT have been called when all tiers fail"
    )
