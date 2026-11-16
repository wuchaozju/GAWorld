"""
Unit tests for InformationModel - declarative knowledge rules per scenario.
"""
import pytest
from fos.core.experiment.information_model import InformationModel


def test_invalid_scope_type_raises():
    with pytest.raises(ValueError, match="scope_type"):
        InformationModel(scope_type="invalid")


def test_get_observers_all_scope():
    m = InformationModel(scope_type="all")
    obs = m.get_observers("Alice", {}, ["Alice", "Bob", "Charlie"])
    assert set(obs) == {"Alice", "Bob", "Charlie"}


def test_get_observers_self_scope():
    m = InformationModel(scope_type="self")
    obs = m.get_observers("Alice", {}, ["Alice", "Bob"])
    assert obs == ["Alice"]


def test_get_observers_neighborhood_scope_via_state():
    m = InformationModel(scope_type="neighborhood")
    state = {"social_network": {"Alice": ["Bob"]}}
    obs = m.get_observers("Alice", state, ["Alice", "Bob", "Charlie"])
    assert set(obs) == {"Alice", "Bob"}
    assert "Charlie" not in obs


def test_get_observers_neighborhood_scope_via_fn():
    m = InformationModel(
        scope_type="neighborhood",
        scope_fn=lambda agent, state, all_agents: ["Bob"],
    )
    obs = m.get_observers("Alice", {}, ["Alice", "Bob", "Charlie"])
    assert set(obs) == {"Alice", "Bob"}


def test_get_observers_pair_scope_with_pairing_fn():
    fixed = [("Alice", "Bob"), ("Charlie", "David")]
    m = InformationModel(
        scope_type="pair",
        pairing_fn=lambda agents, rn: fixed,
    )
    obs = m.get_observers("Alice", {}, ["Alice", "Bob", "Charlie", "David"], round_num=1)
    assert set(obs) == {"Alice", "Bob"}
    obs2 = m.get_observers("Charlie", {}, ["Alice", "Bob", "Charlie", "David"], round_num=1)
    assert set(obs2) == {"Charlie", "David"}


def test_get_observers_pair_scope_no_pairing_fn():
    # Falls back to self-only when no pairing_fn
    m = InformationModel(scope_type="pair")
    obs = m.get_observers("Alice", {}, ["Alice", "Bob"], round_num=1)
    assert obs == ["Alice"]


def test_get_observers_role_based_scope():
    def mafia_sees_mafia(agent, state, all_agents):
        roles = state.get("roles", {})
        if roles.get(agent) == "mafia":
            return [a for a, r in roles.items() if r == "mafia"]
        return [agent]

    m = InformationModel(scope_type="role_based", scope_fn=mafia_sees_mafia)
    state = {"roles": {"Alice": "mafia", "Bob": "mafia", "Charlie": "villager"}}
    obs = m.get_observers("Alice", state, ["Alice", "Bob", "Charlie"])
    assert set(obs) == {"Alice", "Bob"}
    obs2 = m.get_observers("Charlie", state, ["Alice", "Bob", "Charlie"])
    assert obs2 == ["Charlie"]
