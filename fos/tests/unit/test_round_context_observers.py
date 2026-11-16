"""
Unit tests for RoundEvent observed_by/payoff and RoundContextManager observer methods.
"""
from fos.core.experiment.round_context import RoundContextManager, RoundEvent
from fos.core.experiment.information_model import InformationModel


def test_round_event_default_observed_by_is_self():
    e = RoundEvent(
        agent_name="Alice", action_name="cooperate",
        parameters={}, round_num=1, summary="Alice cooperated",
    )
    assert e.observed_by == ["Alice"]


def test_round_event_explicit_observed_by_preserved():
    e = RoundEvent(
        agent_name="Alice", action_name="cooperate",
        parameters={}, round_num=1, summary="",
        observed_by=["Alice", "Bob"],
    )
    assert e.observed_by == ["Alice", "Bob"]


def test_round_event_payoff_defaults_none():
    e = RoundEvent(
        agent_name="Alice", action_name="cooperate",
        parameters={}, round_num=1, summary="",
    )
    assert e.payoff is None


def test_record_action_with_observers_all_scope():
    info_model = InformationModel(scope_type="all")
    cm = RoundContextManager(
        information_model=info_model,
        all_agent_names=["Alice", "Bob", "Charlie"],
    )
    cm.record_action_with_observers("Alice", "cooperate", {}, 1, "Alice cooperated")
    assert len(cm._round_events) == 1
    assert set(cm._round_events[0].observed_by) == {"Alice", "Bob", "Charlie"}


def test_record_action_with_observers_self_scope():
    info_model = InformationModel(scope_type="self")
    cm = RoundContextManager(
        information_model=info_model,
        all_agent_names=["Alice", "Bob"],
    )
    cm.record_action_with_observers("Alice", "cooperate", {}, 1, "")
    assert cm._round_events[0].observed_by == ["Alice"]


def test_record_action_with_observers_no_info_model_defaults_to_self():
    cm = RoundContextManager()
    cm.record_action_with_observers("Alice", "cooperate", {}, 1, "")
    assert cm._round_events[0].observed_by == ["Alice"]


def test_get_context_for_agent_filters_by_observed_by():
    info_model = InformationModel(scope_type="self", primacy_keep=False)
    cm = RoundContextManager(
        information_model=info_model,
        all_agent_names=["Alice", "Bob"],
    )
    cm.record_action_with_observers("Alice", "cooperate", {}, 1, "Alice cooperated")
    cm.record_action_with_observers("Bob", "defect", {}, 1, "Bob defected")

    alice_ctx = cm.get_context_for_agent("Alice")
    assert "cooperate" in alice_ctx
    assert "defect" not in alice_ctx

    bob_ctx = cm.get_context_for_agent("Bob")
    assert "defect" in bob_ctx
    assert "cooperate" not in bob_ctx


def test_get_context_for_agent_no_info_model_falls_back():
    cm = RoundContextManager()
    cm._summaries["Alice"] = "existing summary"
    ctx = cm.get_context_for_agent("Alice")
    assert ctx == "existing summary"
