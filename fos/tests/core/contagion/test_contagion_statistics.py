"""
Tests for ContagionStatistics state counting and event tracking.

Verifies that update() correctly counts agents per SEIR state,
handles empty agent lists, and handles all-susceptible populations.

Contains: test_compute_statistics_counts_each_state_correctly,
          test_compute_statistics_handles_empty_agent_list,
          test_compute_statistics_handles_all_susceptible
"""
from fos.core.contagion.statistics import ContagionStatistics


class _FakeAgent:
    """Minimal agent stub with a properties dict."""

    def __init__(self, name, state):
        self.name = name
        self.properties = {"contagion_state": state}


def test_compute_statistics_counts_each_state_correctly():
    """S=3, E=1, I=2, R=1 — verify each count matches."""
    stats = ContagionStatistics()
    agents = {
        "a1": _FakeAgent("a1", "susceptible"),
        "a2": _FakeAgent("a2", "susceptible"),
        "a3": _FakeAgent("a3", "susceptible"),
        "a4": _FakeAgent("a4", "exposed"),
        "a5": _FakeAgent("a5", "infected"),
        "a6": _FakeAgent("a6", "infected"),
        "a7": _FakeAgent("a7", "recovered"),
    }
    stats.update(agents)
    assert stats.counts["susceptible"] == 3
    assert stats.counts["exposed"] == 1
    assert stats.counts["infected"] == 2
    assert stats.counts["recovered"] == 1


def test_compute_statistics_handles_empty_agent_list():
    """With no agents, all counts are absent (empty dict)."""
    stats = ContagionStatistics()
    stats.update({})
    assert stats.counts == {}


def test_compute_statistics_handles_all_susceptible():
    """When every agent is susceptible, only that key appears."""
    stats = ContagionStatistics()
    agents = {
        "a1": _FakeAgent("a1", "susceptible"),
        "a2": _FakeAgent("a2", "susceptible"),
        "a3": _FakeAgent("a3", "susceptible"),
    }
    stats.update(agents)
    assert stats.counts == {"susceptible": 3}
