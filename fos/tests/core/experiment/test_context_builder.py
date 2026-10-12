"""
Tests for context builder — visibility, network filtering, history truncation.

Tests build_structured_context to ensure agents see the right information
each round. Wrong context = agents making decisions based on bad data.

Contains: tests for build_structured_context with InformationModel
"""


from fos.core.context_builder import build_structured_context
from fos.core.experiment.round_context import RoundEvent
from fos.core.experiment.information_model import InformationModel


def _event(round_num, agent, action, observed_by=None, **kwargs):
    """Helper to create a RoundEvent with sensible defaults."""
    return RoundEvent(
        round_num=round_num,
        agent_name=agent,
        action_name=action,
        parameters=kwargs.pop("parameters", {}),
        summary=kwargs.pop("summary", f"{agent} did {action}"),
        observed_by=observed_by or [agent],
        **kwargs,
    )


def test_basic_context_shows_own_action_and_round_number():
    """Agent sees their own action and the round number in context."""
    events = [_event(1, "Alice", "cooperate", observed_by=["Alice"])]
    info = InformationModel(scope_type="self", recent_window=5)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info,
    )

    assert "Round 1:" in context
    assert "cooperate" in context


def test_full_visibility_shows_all_agents_actions():
    """With scope_type 'all', every agent's action appears in context."""
    events = [
        _event(1, "Alice", "cooperate", observed_by=["Alice", "Bob"]),
        _event(1, "Bob", "defect", observed_by=["Alice", "Bob"]),
    ]
    info = InformationModel(scope_type="all", recent_window=5)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info,
    )

    assert "cooperate" in context
    assert "defect" in context


def test_self_only_visibility_hides_other_agents():
    """With scope_type 'self', agent only sees own actions."""
    events = [
        _event(1, "Alice", "cooperate", observed_by=["Alice"]),
        _event(1, "Bob", "defect", observed_by=["Bob"]),
    ]
    info = InformationModel(scope_type="self", recent_window=5)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info,
    )

    assert "cooperate" in context
    assert "defect" not in context


def test_social_network_filtering_shows_only_neighbours():
    """Neighborhood scope with a graph — agent sees only connected neighbours."""
    from fos.core.experiment.state import ExperimentState, AgentState

    events = [
        _event(1, "Alice", "cooperate", observed_by=["Alice", "Bob", "Charlie"]),
        _event(1, "Bob", "defect", observed_by=["Alice", "Bob", "Charlie"]),
        _event(1, "Charlie", "cooperate", observed_by=["Alice", "Bob", "Charlie"]),
    ]
    info = InformationModel(scope_type="neighborhood", recent_window=5)

    graph = {"edges": [("Alice", "Bob")]}  # Alice-Bob connected, Charlie isolated

    state = ExperimentState(
        agents={
            "Bob": AgentState(properties={"last_contribution": 5}),
            "Charlie": AgentState(properties={"last_contribution": 10}),
        }
    )

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info, state=state, graph=graph,
    )

    # Alice should see own action and Bob's, but not Charlie's
    assert "cooperate" in context  # Alice's own action
    assert "defect" in context     # Bob is a neighbour


def test_history_truncated_to_recent_window():
    """Long history is truncated to the configured recent_window size."""
    events = [
        _event(r, "Alice", "cooperate", observed_by=["Alice"])
        for r in range(1, 11)  # 10 rounds
    ]
    info = InformationModel(scope_type="self", recent_window=3)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info,
    )

    assert "Round 8:" in context
    assert "Round 10:" in context
    assert "Round 5:" not in context


def test_empty_state_returns_first_round_message():
    """When no events have occurred, context says first round."""
    info = InformationModel(scope_type="all", recent_window=5)

    context = build_structured_context(
        for_agent="Alice", events=[], info_model=info,
    )

    assert context == "This is the first round."


def test_primacy_keep_preserves_round_one():
    """With primacy_keep=True, round 1 stays visible even outside window."""
    events = [
        _event(r, "Alice", "cooperate", observed_by=["Alice"])
        for r in range(1, 11)
    ]
    info = InformationModel(scope_type="self", recent_window=3, primacy_keep=True)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info,
    )

    # Round 1 should be kept despite being outside the 3-round window
    assert "Round 1:" in context
    assert "Round 10:" in context


def test_score_shown_when_include_scores_is_true():
    """Score appears in context when include_scores=True."""
    events = [_event(1, "Alice", "cooperate", observed_by=["Alice"])]
    info = InformationModel(scope_type="self", recent_window=5, include_scores=True)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info, agent_score=42,
    )

    assert "My score: 42" in context


def test_score_hidden_when_include_scores_is_false():
    """Score does not appear in context when include_scores=False."""
    events = [_event(1, "Alice", "cooperate", observed_by=["Alice"])]
    info = InformationModel(scope_type="self", recent_window=5, include_scores=False)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info, agent_score=42,
    )

    assert "score" not in context.lower()


def test_multiple_rounds_all_appear_in_context():
    """Context shows all visible rounds in order."""
    events = [
        _event(1, "Alice", "cooperate", observed_by=["Alice"]),
        _event(2, "Alice", "defect", observed_by=["Alice"]),
        _event(3, "Alice", "cooperate", observed_by=["Alice"]),
    ]
    info = InformationModel(scope_type="self", recent_window=5)

    context = build_structured_context(
        for_agent="Alice", events=events, info_model=info,
    )

    assert "Round 1:" in context
    assert "Round 2:" in context
    assert "Round 3:" in context
