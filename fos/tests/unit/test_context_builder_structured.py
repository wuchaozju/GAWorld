"""
Unit tests for build_structured_context() with tiered history and observation filtering.
"""
from fos.core.context_builder import build_structured_context
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.round_context import RoundEvent


def _evt(agent, action, round_num, observed_by=None, payoff=None):
    return RoundEvent(
        agent_name=agent, action_name=action, parameters={},
        round_num=round_num, summary=f"{agent} {action}",
        observed_by=observed_by or [agent],
        payoff=payoff,
    )


def test_empty_events_returns_first_round_message():
    info_model = InformationModel(scope_type="all")
    ctx = build_structured_context("Alice", [], info_model)
    assert ctx == "This is the first round."


def test_basic_events_appear_in_context():
    events = [
        _evt("Alice", "cooperate", 1, ["Alice", "Bob"]),
        _evt("Bob", "defect", 1, ["Alice", "Bob"]),
    ]
    info_model = InformationModel(scope_type="all", primacy_keep=False)
    ctx = build_structured_context("Alice", events, info_model)
    assert "cooperate" in ctx
    assert "defect" in ctx


def test_recent_window_excludes_old_rounds_when_primacy_false():
    events = [_evt("Alice", "cooperate", r, ["Alice"]) for r in range(1, 6)]
    info_model = InformationModel(scope_type="self", recent_window=2, primacy_keep=False)
    ctx = build_structured_context("Alice", events, info_model)
    assert "Round 1" not in ctx
    assert "Round 2" not in ctx
    assert "Round 3" not in ctx
    assert "Round 4" in ctx
    assert "Round 5" in ctx


def test_primacy_keep_always_includes_round_1():
    events = [_evt("Alice", "cooperate", r, ["Alice"]) for r in range(1, 7)]
    info_model = InformationModel(scope_type="self", recent_window=2, primacy_keep=True)
    ctx = build_structured_context("Alice", events, info_model)
    assert "Round 1" in ctx
    assert "Round 5" in ctx
    assert "Round 6" in ctx
    assert "Round 2" not in ctx
    assert "Round 3" not in ctx
    assert "Round 4" not in ctx


def test_observed_by_filtering_is_caller_responsibility():
    # build_structured_context trusts its input events list;
    # filtering by observed_by is done by get_context_for_agent before calling here.
    events = [_evt("Alice", "cooperate", 1, ["Alice"])]
    info_model = InformationModel(scope_type="self", primacy_keep=False)
    ctx = build_structured_context("Alice", events, info_model)
    assert "cooperate" in ctx


def test_payoff_template_replaces_default_line():
    events = [
        _evt("Alice", "cooperate", 1, ["Alice", "Bob"], payoff=0),
        _evt("Bob", "defect", 1, ["Alice", "Bob"]),
    ]
    info_model = InformationModel(
        scope_type="pair",
        payoff_template="Round {N}: {my_action} vs {partner_action} → {payoff} pts",
        primacy_keep=False,
    )
    ctx = build_structured_context("Alice", events, info_model)
    assert "cooperate vs defect" in ctx
    assert "0 pts" in ctx
    # Template IS the full line — no "Round 1: Round 1:" double prefix
    assert ctx.count("Round 1") == 1


def test_include_scores_shows_agent_score():
    events = [_evt("Alice", "cooperate", 1, ["Alice"])]
    info_model = InformationModel(scope_type="self", primacy_keep=False, include_scores=True)
    ctx = build_structured_context("Alice", events, info_model, agent_score=7)
    assert "7" in ctx


def test_include_scores_false_hides_score():
    events = [_evt("Alice", "cooperate", 1, ["Alice"])]
    info_model = InformationModel(scope_type="self", primacy_keep=False, include_scores=False)
    ctx = build_structured_context("Alice", events, info_model, agent_score=7)
    assert "My score" not in ctx
