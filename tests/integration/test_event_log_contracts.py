"""
Event log contract tests for the Results Tab data pipeline.

Pins the shape and content of the RoundContextManager event log so that the
Results Tab feature has a stable foundation for charts, CSV, and Markdown
export. All tests use dialect="mock" with no real LLM calls.

Contains: test_one_event_per_agent_per_round, test_event_fields_complete_and_typed,
    test_events_queryable_by_round, test_event_agent_names_match_config,
    test_event_action_names_from_configured_set, test_event_log_append_only
"""

import pytest

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agents(names: list[str]) -> list[ExperimentAgent]:
    """Create mock-dialect agents with the given names."""
    return [
        ExperimentAgent(
            name=name,
            properties={},
            llm_config=LLMConfig(dialect="mock"),
        )
        for name in names
    ]


def _make_runner(
    agents: list[ExperimentAgent],
    actions: list[str] | None = None,
    action_descriptions: dict[str, str] | None = None,
) -> ExperimentRunner:
    """Create an ExperimentRunner with a mock LLM client."""
    llm_client = LLMClient(LLMConfig(dialect="mock"))
    game_config = GameConfig(
        name="test_event_log",
        description="Event log contract test scenario",
        action_type="discrete",
        actions=actions or ["cooperate", "defect"],
        action_descriptions=action_descriptions or {
            a: a.capitalize() for a in (actions or ["cooperate", "defect"])
        },
        payoff_type="none",
    )
    return ExperimentRunner(
        agents=agents,
        game_config=game_config,
        llm_client=llm_client,
        round_visibility="simultaneous",
    )


# ---------------------------------------------------------------------------
# Contract 1
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_event_per_agent_per_round():
    """Every agent must produce exactly one event per round — no duplicates, no gaps.

    If this fails, the Results Tab action breakdown chart will show wrong agent
    counts per round. A duplicate means the chart double-counts an action; a
    missing entry means an agent disappears from the chart entirely.

    Depends on: action breakdown chart.
    """
    agent_names = ["Alice", "Bob", "Carol"]
    agents = _make_agents(agent_names)
    runner = _make_runner(agents)

    # Round 1
    await runner._run_simultaneous_round(1)
    events_r1 = runner.context_manager.get_round_events(1)
    assert len(events_r1) == 3, (
        f"Round 1 expected 3 events (one per agent), got {len(events_r1)}. "
        "The event log must contain exactly one entry per agent per round."
    )
    # No duplicate agent names
    r1_names = [e.agent_name for e in events_r1]
    assert len(set(r1_names)) == 3, (
        f"Duplicate agent names in round 1 events: {r1_names}. "
        "Each agent must appear exactly once."
    )

    # Round 2
    await runner._run_simultaneous_round(2)
    events_r2 = runner.context_manager.get_round_events(2)
    assert len(events_r2) == 3, (
        f"Round 2 expected 3 events, got {len(events_r2)}. "
        "Event count must be consistent across rounds."
    )
    r2_names = [e.agent_name for e in events_r2]
    assert set(r2_names) == set(agent_names), (
        f"Round 2 agent names {r2_names} don't match configured {agent_names}."
    )


# ---------------------------------------------------------------------------
# Contract 2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_fields_complete_and_typed():
    """Every event field must be present, correctly typed, and non-trivial.

    If this fails, the CSV export will crash (missing columns) or the Markdown
    report will render blank rows. A None parameter dict causes KeyError when
    the pipeline tries to read action details.

    Depends on: CSV export, Markdown report.
    """
    agents = _make_agents(["Alice", "Bob", "Carol"])
    runner = _make_runner(agents)

    await runner._run_simultaneous_round(1)

    events = runner.context_manager.get_round_events(1)
    assert len(events) == 3

    for event in events:
        # agent_name: non-empty string
        assert isinstance(event.agent_name, str) and event.agent_name, (
            f"agent_name must be non-empty str, got: {event.agent_name!r}"
        )

        # action_name: non-empty string
        assert isinstance(event.action_name, str) and event.action_name, (
            f"action_name must be non-empty str, got: {event.action_name!r}"
        )

        # round_num: positive integer matching the round
        assert isinstance(event.round_num, int) and event.round_num > 0, (
            f"round_num must be positive int, got: {event.round_num!r}"
        )
        assert event.round_num == 1, (
            f"round_num is {event.round_num}, expected 1"
        )

        # summary: non-empty string
        assert isinstance(event.summary, str) and event.summary.strip(), (
            f"summary must be non-empty str, got: {event.summary!r}"
        )

        # parameters: dict — may be empty but must not be None
        assert isinstance(event.parameters, dict), (
            f"parameters must be dict, got: {type(event.parameters).__name__} "
            f"({event.parameters!r}). None would crash CSV/Markdown export."
        )


# ---------------------------------------------------------------------------
# Contract 3
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_events_queryable_by_round():
    """get_round_events(N) must return only events from round N, with no overlap.

    If this fails, the score trajectory chart will mix data from different
    rounds, producing garbled trend lines. The CSV export will show wrong
    round-grouped rows.

    Depends on: score trajectory chart, CSV export.
    """
    agents = _make_agents(["Alice", "Bob", "Carol"])
    runner = _make_runner(agents)

    await runner._run_simultaneous_round(1)
    await runner._run_simultaneous_round(2)
    await runner._run_simultaneous_round(3)

    r1 = runner.context_manager.get_round_events(1)
    r2 = runner.context_manager.get_round_events(2)
    r3 = runner.context_manager.get_round_events(3)

    # Each round must have exactly 3 events
    assert len(r1) == 3, f"Round 1: expected 3 events, got {len(r1)}"
    assert len(r2) == 3, f"Round 2: expected 3 events, got {len(r2)}"
    assert len(r3) == 3, f"Round 3: expected 3 events, got {len(r3)}"

    # Every event in r1 has round_num == 1 (and similarly for 2, 3)
    for e in r1:
        assert e.round_num == 1, (
            f"Round 1 query returned event with round_num={e.round_num}"
        )
    for e in r2:
        assert e.round_num == 2, (
            f"Round 2 query returned event with round_num={e.round_num}"
        )
    for e in r3:
        assert e.round_num == 3, (
            f"Round 3 query returned event with round_num={e.round_num}"
        )

    # No event appears in two rounds — compare by identity (object id)
    all_ids = (
        [id(e) for e in r1]
        + [id(e) for e in r2]
        + [id(e) for e in r3]
    )
    assert len(all_ids) == len(set(all_ids)), (
        "An event object appears in more than one round's results. "
        "get_round_events() must not return overlapping events."
    )


# ---------------------------------------------------------------------------
# Contract 4
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_agent_names_match_config():
    """Event agent_name must exactly match a name from ExperimentConfig — no typos
    or case changes.

    If this fails, the Results Tab per-agent filter will silently drop agents,
    and the action breakdown chart will show "unknown" agents alongside the
    real ones.

    Depends on: action breakdown chart, CSV export.
    """
    configured_names = {"Researcher_A", "Researcher_B", "Researcher_C"}
    agents = _make_agents(list(configured_names))
    runner = _make_runner(agents)

    await runner._run_simultaneous_round(1)

    events = runner.context_manager.get_round_events(1)
    assert len(events) == 3

    event_names = {e.agent_name for e in events}
    assert event_names == configured_names, (
        f"Event agent names {event_names} don't match configured names "
        f"{configured_names}. Every event must reference an exact config name."
    )

    # Also verify no extra or misspelled names
    for e in events:
        assert e.agent_name in configured_names, (
            f"Event agent_name '{e.agent_name}' is not in configured set "
            f"{configured_names}. This is a typo, truncation, or case error."
        )


# ---------------------------------------------------------------------------
# Contract 5
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_action_names_from_configured_set():
    """Every event action_name must come from the configured action set.

    If this fails, the action breakdown chart will show unexpected action
    categories, and the CSV export will have action values that don't match
    any column header.

    Depends on: action breakdown chart, CSV export, Markdown report.
    """
    custom_actions = ["publish", "replicate", "reject"]
    action_descriptions = {
        "publish": "Publish your findings to the group",
        "replicate": "Attempt to replicate another's findings",
        "reject": "Reject a submitted finding as unreliable",
    }
    agents = _make_agents(["Reviewer_1", "Reviewer_2", "Reviewer_3"])
    runner = _make_runner(agents, actions=custom_actions, action_descriptions=action_descriptions)

    await runner._run_simultaneous_round(1)

    events = runner.context_manager.get_round_events(1)
    assert len(events) == 3

    for event in events:
        assert event.action_name in custom_actions, (
            f"Event action_name '{event.action_name}' is not in the configured "
            f"set {custom_actions}. The event log recorded an action outside "
            "the allowed choices."
        )


# ---------------------------------------------------------------------------
# Contract 6
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_log_append_only():
    """Round-1 events must be identical before and after round 2 runs.

    If this fails, the Results Tab's historical trend data is corrupted —
    viewing round-1 data after round 3 would show different values than
    viewing it right after round 1. This makes the score trajectory chart
    and CSV export unreliable.

    Depends on: score trajectory chart, CSV export.
    """
    agents = _make_agents(["Alice", "Bob", "Carol"])
    runner = _make_runner(agents)

    await runner._run_simultaneous_round(1)

    # Snapshot round-1 events immediately after round 1
    r1_snapshot = runner.context_manager.get_round_events(1)
    assert len(r1_snapshot) == 3

    snapshot_data = [
        (e.agent_name, e.action_name, e.round_num, e.summary, dict(e.parameters))
        for e in r1_snapshot
    ]

    # Run round 2 — this must not mutate round-1 events
    await runner._run_simultaneous_round(2)

    r1_after = runner.context_manager.get_round_events(1)
    assert len(r1_after) == 3

    after_data = [
        (e.agent_name, e.action_name, e.round_num, e.summary, dict(e.parameters))
        for e in r1_after
    ]

    assert snapshot_data == after_data, (
        "Round-1 events changed after round 2 executed. "
        "The event log must be append-only — new rounds must not mutate "
        "existing records."
    )
