"""
Tests for Public Goods neighbor-scoped average contribution behavior.

Verifies that build_structured_context uses graph neighbors (not all agents)
when a network graph is present, and global averaging only when no graph exists.

Covers: chain network, isolated agent, fully connected, global mode regression.

Contains: TestPGGNeighborAverageChain, TestPGGIsolatedAgent,
          TestPGGFullMesh, TestPGGGlobalModeRegression
"""

import pytest
from fos.core.context_builder import build_structured_context
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.state import ExperimentState, AgentState
from fos.core.experiment.round_context import RoundEvent


def _make_events_for_round(
    round_num: int,
    contributions: dict[str, int],
    observed_by_all: list[str] | None = None,
) -> list[RoundEvent]:
    """Create RoundEvents for a round with given agent contributions.

    Args:
        round_num: Round number
        contributions: Dict of agent_name -> contribution amount
        observed_by_all: If set, all events use this as observed_by.
                        If None, all agents observe each other (global visibility).

    Returns:
        List of RoundEvent objects
    """
    agents = list(contributions.keys())
    events = []
    for name, amount in contributions.items():
        obs = observed_by_all if observed_by_all else agents
        events.append(
            RoundEvent(
                agent_name=name,
                action_name="allocate",
                parameters={"amount": amount},
                round_num=round_num,
                summary=f"{name} allocated {amount}",
                observed_by=list(obs),
            )
        )
    return events


class TestPGGNeighborAverageChain:
    """Chain network A-B-C: verify each agent's average uses only graph neighbors."""

    @pytest.fixture
    def chain_state(self):
        """A-B-C chain: A←→B←→C. Contributions: A=2, B=5, C=8."""
        return ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 2}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 5}
                ),
                "C": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 8}
                ),
            }
        )

    @pytest.fixture
    def chain_graph(self):
        """A←→B←→C chain graph."""
        return {"edges": [("A", "B"), ("B", "C")]}

    @pytest.fixture
    def info_model(self):
        """InformationModel with show_average_contribution enabled."""
        return InformationModel(
            scope_type="all",  # PGG default
            show_average_contribution=True,
            recent_window=3,
        )

    def test_A_sees_only_B(self, chain_state, chain_graph, info_model):
        """A's neighbor average uses B only (not C)."""
        events = _make_events_for_round(1, {"A": 2, "B": 5, "C": 8})
        context = build_structured_context(
            for_agent="A",
            events=events,
            info_model=info_model,
            state=chain_state,
            graph=chain_graph,
        )
        # A's only neighbor is B with contribution 5
        assert "1 neighbor" in context, f"Expected '1 neighbor', got: {context}"
        assert "5.0" in context, f"Expected average 5.0, got: {context}"
        # A should NOT see C's contribution (8) in the average
        assert "8.0" not in context, f"A should not see C's contribution, got: {context}"

    def test_B_sees_A_and_C(self, chain_state, chain_graph, info_model):
        """B's neighbor average uses A and C (not all agents)."""
        events = _make_events_for_round(1, {"A": 2, "B": 5, "C": 8})
        context = build_structured_context(
            for_agent="B",
            events=events,
            info_model=info_model,
            state=chain_state,
            graph=chain_graph,
        )
        # B's neighbors: A(2) + C(8), average = 5.0
        assert "2 neighbor" in context, f"Expected '2 neighbors', got: {context}"
        assert "5.0" in context, f"Expected average 5.0, got: {context}"

    def test_C_sees_only_B(self, chain_state, chain_graph, info_model):
        """C's neighbor average uses B only (not A)."""
        events = _make_events_for_round(1, {"A": 2, "B": 5, "C": 8})
        context = build_structured_context(
            for_agent="C",
            events=events,
            info_model=info_model,
            state=chain_state,
            graph=chain_graph,
        )
        # C's only neighbor is B with contribution 5
        assert "1 neighbor" in context, f"Expected '1 neighbor', got: {context}"
        assert "5.0" in context, f"Expected average 5.0, got: {context}"
        # C should NOT see A's contribution (2) in the average
        assert "2.0" not in context, f"C should not see A's contribution, got: {context}"

    def test_no_agent_sees_global_average(self, chain_state, chain_graph, info_model):
        """No agent's average includes all agents."""
        # Global average would be (2+5+8)/3 = 5.0, but that's coincidental
        # with neighbor averages. Use a non-symmetric case to be sure.
        asymmetric_state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 10}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 0}
                ),
                "C": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 20}
                ),
            }
        )
        events2 = _make_events_for_round(1, {"A": 10, "B": 0, "C": 20})

        # A sees B(0): avg = 0.0
        ctx_a = build_structured_context(
            for_agent="A", events=events2, info_model=info_model,
            state=asymmetric_state, graph=chain_graph,
        )
        assert "0.0" in ctx_a, f"A should see avg 0.0 (neighbor B), got: {ctx_a}"

        # C sees B(0): avg = 0.0
        ctx_c = build_structured_context(
            for_agent="C", events=events2, info_model=info_model,
            state=asymmetric_state, graph=chain_graph,
        )
        assert "0.0" in ctx_c, f"C should see avg 0.0 (neighbor B), got: {ctx_c}"

        # B sees A(10)+C(20): avg = 15.0
        ctx_b = build_structured_context(
            for_agent="B", events=events2, info_model=info_model,
            state=asymmetric_state, graph=chain_graph,
        )
        assert "15.0" in ctx_b, f"B should see avg 15.0 (neighbors A+C), got: {ctx_b}"
        # Global avg would be (10+20)/2=15.0 — coincidental, so check labels
        assert "2 neighbor" in ctx_b, f"B should see '2 neighbors', got: {ctx_b}"


class TestPGGIsolatedAgent:
    """Isolated agent (no edges): should NOT receive a global fallback average."""

    def test_isolated_agent_no_global_fallback(self):
        """Isolated agent sees no average, no global fallback."""
        model = InformationModel(
            scope_type="all",
            show_average_contribution=True,
            recent_window=3,
        )
        state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 5}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 10}
                ),
                "C": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 15}
                ),
            }
        )
        # A has no edges (isolated)
        graph = {"edges": [("B", "C")]}
        events = _make_events_for_round(1, {"A": 5, "B": 10, "C": 15})

        context = build_structured_context(
            for_agent="A",
            events=events,
            info_model=model,
            state=state,
            graph=graph,
        )
        # A is isolated — should NOT see "Average contribution from X neighbors"
        assert "Average contribution" not in context, (
            f"Isolated agent should not see average. Got: {context}"
        )
        # Should NOT fall back to global average (which would be 12.5)
        assert "12.5" not in context, (
            f"Isolated agent should not get global fallback. Got: {context}"
        )

    def test_isolated_agent_via_get_visible_contributions(self):
        """Verify get_visible_contributions returns empty for isolated agent."""
        model = InformationModel(scope_type="all")
        state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 5}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 10}
                ),
            }
        )
        graph = {"edges": []}  # No edges at all
        visible = model.get_visible_contributions("A", state, graph)
        assert visible == {}, f"Isolated agent should have no visible contributions, got: {visible}"

    def test_isolated_agent_neighbor_average_is_none(self):
        """Verify get_neighbor_average returns None for isolated agent."""
        model = InformationModel(scope_type="all")
        state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 5}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 10}
                ),
            }
        )
        graph = {"edges": []}
        result = model.get_neighbor_average("A", state, graph)
        assert result is None, f"Isolated agent average should be None, got: {result}"


class TestPGGFullMesh:
    """Fully connected network: each agent's average uses all other agents."""

    @pytest.fixture
    def full_mesh_state(self):
        """4 agents in fully connected network."""
        return ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 2}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 4}
                ),
                "C": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 6}
                ),
                "D": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 8}
                ),
            }
        )

    @pytest.fixture
    def full_mesh_graph(self):
        """Complete graph on A, B, C, D."""
        return {
            "edges": [
                ("A", "B"), ("A", "C"), ("A", "D"),
                ("B", "C"), ("B", "D"),
                ("C", "D"),
            ]
        }

    @pytest.fixture
    def info_model(self):
        return InformationModel(
            scope_type="all",
            show_average_contribution=True,
            recent_window=3,
        )

    def test_each_agent_sees_all_others_as_neighbors(
        self, full_mesh_state, full_mesh_graph, info_model
    ):
        """Each agent's neighbor average uses all other agents (self excluded)."""
        contributions = {"A": 2, "B": 4, "C": 6, "D": 8}
        events = _make_events_for_round(1, contributions)

        expected = {
            "A": (4 + 6 + 8) / 3,   # B+C+D = 6.0
            "B": (2 + 6 + 8) / 3,   # A+C+D = 5.33...
            "C": (2 + 4 + 8) / 3,   # A+B+D = 4.67...
            "D": (2 + 4 + 6) / 3,   # A+B+C = 4.0
        }

        for agent, avg in expected.items():
            ctx = build_structured_context(
                for_agent=agent,
                events=events,
                info_model=info_model,
                state=full_mesh_state,
                graph=full_mesh_graph,
            )
            assert f"{avg:.1f}" in ctx, (
                f"{agent} expected avg {avg:.1f}, got: {ctx}"
            )
            assert "3 neighbor" in ctx, (
                f"{agent} should see 3 neighbors, got: {ctx}"
            )

    def test_self_excluded_from_neighbor_average(
        self, full_mesh_state, full_mesh_graph, info_model
    ):
        """Agent's own contribution is NOT included in their average."""
        # A contributes 100, all others contribute 0
        skewed_state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 100}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 0}
                ),
                "C": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 0}
                ),
                "D": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 0}
                ),
            }
        )
        events = _make_events_for_round(1, {"A": 100, "B": 0, "C": 0, "D": 0})
        ctx = build_structured_context(
            for_agent="A",
            events=events,
            info_model=info_model,
            state=skewed_state,
            graph=full_mesh_graph,
        )
        # A's own contribution (100) should NOT be averaged
        # Neighbors B+C+D all contributed 0, so avg = 0.0
        assert "0.0" in ctx, (
            f"A's avg should exclude own 100. Got: {ctx}"
        )
        assert "3 neighbor" in ctx


class TestPGGGlobalModeRegression:
    """Verify global (no-graph) mode still uses all agents."""

    def test_no_graph_uses_all_agents(self):
        """Without a graph, average includes ALL other agents."""
        model = InformationModel(
            scope_type="all",
            show_average_contribution=True,
            recent_window=3,
        )
        state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 2}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 4}
                ),
                "C": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 6}
                ),
            }
        )
        events = _make_events_for_round(1, {"A": 2, "B": 4, "C": 6})

        # No graph passed — should use all agents
        context = build_structured_context(
            for_agent="A",
            events=events,
            info_model=model,
            state=state,
            graph=None,
        )
        # All other agents: B(4) + C(6) = avg 5.0
        assert "5.0" in context, f"Expected global avg 5.0, got: {context}"
        assert "2 other agents" in context, f"Expected '2 other agents', got: {context}"

    def test_no_graph_self_excluded(self):
        """Without a graph, own contribution is excluded from average."""
        model = InformationModel(
            scope_type="all",
            show_average_contribution=True,
            recent_window=3,
        )
        state = ExperimentState(
            agents={
                "A": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 100}
                ),
                "B": AgentState(
                    resources={"tokens": 20}, properties={"last_contribution": 4}
                ),
            }
        )
        events = _make_events_for_round(1, {"A": 100, "B": 4})

        context = build_structured_context(
            for_agent="A",
            events=events,
            info_model=model,
            state=state,
            graph=None,
        )
        # Only B(4) — A's own 100 excluded
        assert "4.0" in context, f"Expected avg 4.0 (B only), got: {context}"
        assert "1 other agent" in context
