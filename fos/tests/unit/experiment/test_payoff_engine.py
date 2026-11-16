"""
Tests for PayoffEngine - generic payoff calculation.

Tests all payoff types: matrix (pairwise/group), pool, feedback, none.
"""

import pytest
from fos.core.experiment.payoff.engine import PayoffEngine
from fos.core.experiment.controller import ActionResult


class TestPayoffEngine:
    """Test PayoffEngine class."""

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    @pytest.fixture
    def pd_actions(self):
        """Simple PD actions for two agents."""
        return [
            ActionResult(
                agent_name="Alice",
                action_name="cooperate",
                parameters={},
                summary="Alice chose cooperate",
                success=True,
                skipped=False,
                round_num=1,
            ),
            ActionResult(
                agent_name="Bob",
                action_name="defect",
                parameters={},
                summary="Bob chose defect",
                success=True,
                skipped=False,
                round_num=1,
            ),
        ]

    def test_payoff_engine_exists(self, engine):
        """PayoffEngine can be instantiated."""
        assert engine is not None

    def test_payoff_type_none_returns_empty(self, engine, pd_actions):
        """payoff_type 'none' returns empty dict."""
        result = engine.calculate_round_payoffs(
            payoff_type="none",
            actions=pd_actions,
            config={},
            grouping_mode="pairwise",
        )
        assert result == {}

    def test_payoff_type_feedback_returns_empty(self, engine, pd_actions):
        """payoff_type 'feedback' returns empty dict (no numerical payoffs)."""
        result = engine.calculate_round_payoffs(
            payoff_type="feedback",
            actions=pd_actions,
            config={},
            grouping_mode="neighbor",
        )
        assert result == {}


class TestGraphGrouping:
    """Test graph-based pair and group selection."""

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    def test_get_pairs_from_graph_basic(self, engine):
        """Pairs are selected from graph edges."""
        graph = {
            "edges": [("Alice", "Bob"), ("Charlie", "Diana")]
        }
        agent_names = ["Alice", "Bob", "Charlie", "Diana"]
        pairs = engine.get_pairs_from_graph(graph, agent_names)

        assert len(pairs) == 2
        assert ("Alice", "Bob") in pairs
        assert ("Charlie", "Diana") in pairs

    def test_get_pairs_each_agent_only_once(self, engine):
        """Each agent can only be in one pair per round."""
        graph = {
            "edges": [("Alice", "Bob"), ("Alice", "Charlie"), ("Bob", "Charlie")]
        }
        agent_names = ["Alice", "Bob", "Charlie"]
        pairs = engine.get_pairs_from_graph(graph, agent_names)

        # Only one pair should be formed (Alice with one of Bob/Charlie)
        assert len(pairs) == 1
        paired_agents = set()
        for a, b in pairs:
            paired_agents.add(a)
            paired_agents.add(b)
        assert len(paired_agents) == 2

    def test_get_pairs_disconnected_sits_out(self, engine):
        """Disconnected nodes don't get paired."""
        graph = {
            "edges": [("Alice", "Bob")]
        }
        agent_names = ["Alice", "Bob", "Charlie"]  # Charlie is disconnected
        pairs = engine.get_pairs_from_graph(graph, agent_names)

        assert len(pairs) == 1
        assert ("Alice", "Bob") in pairs
        # Charlie is not in any pair

    def test_get_groups_from_graph_fully_connected(self, engine):
        """Fully connected graph forms one group."""
        graph = {
            "edges": [("Alice", "Bob"), ("Bob", "Charlie"), ("Alice", "Charlie")]
        }
        agent_names = ["Alice", "Bob", "Charlie"]
        groups = engine.get_groups_from_graph(graph, agent_names)

        assert len(groups) == 1
        assert set(groups[0]) == {"Alice", "Bob", "Charlie"}

    def test_get_groups_disconnected_components(self, engine):
        """Disconnected components form separate groups."""
        graph = {
            "edges": [("Alice", "Bob"), ("Charlie", "Diana")]
        }
        agent_names = ["Alice", "Bob", "Charlie", "Diana"]
        groups = engine.get_groups_from_graph(graph, agent_names)

        assert len(groups) == 2
        group_sets = [set(g) for g in groups]
        assert {"Alice", "Bob"} in group_sets
        assert {"Charlie", "Diana"} in group_sets

    def test_get_groups_single_isolated_agent(self, engine):
        """Isolated agent forms their own group."""
        graph = {
            "edges": [("Alice", "Bob")]
        }
        agent_names = ["Alice", "Bob", "Charlie"]  # Charlie is isolated
        groups = engine.get_groups_from_graph(graph, agent_names)

        assert len(groups) == 2
        group_sets = [set(g) for g in groups]
        assert {"Alice", "Bob"} in group_sets
        assert {"Charlie"} in group_sets

    def test_get_groups_without_edges_returns_single_group(self, engine):
        """Group-mode games without a graph treat everyone as one group."""
        graph = {"edges": []}
        agent_names = ["Alice", "Bob", "Charlie"]

        groups = engine.get_groups_from_graph(graph, agent_names)

        assert groups == [["Alice", "Bob", "Charlie"]]


class TestMatrixPayoffPairwise:
    """Test matrix payoff calculation for pairwise mode."""

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    @pytest.fixture
    def pd_config(self):
        """Standard PD payoff matrix."""
        return {
            "matrix": {
                "cooperate_cooperate": {"value": 3},
                "cooperate_defect": {"row": 0, "col": 5},
                "defect_cooperate": {"row": 5, "col": 0},
                "defect_defect": {"value": 1},
            }
        }

    @pytest.fixture
    def pd_actions_both_cooperate(self):
        return [
            ActionResult(
                agent_name="Alice", action_name="cooperate",
                parameters={}, summary="", success=True, skipped=False, round_num=1,
            ),
            ActionResult(
                agent_name="Bob", action_name="cooperate",
                parameters={}, summary="", success=True, skipped=False, round_num=1,
            ),
        ]

    @pytest.fixture
    def pd_actions_mixed(self):
        """Alice cooperates, Bob defects."""
        return [
            ActionResult(
                agent_name="Alice", action_name="cooperate",
                parameters={}, summary="", success=True, skipped=False, round_num=1,
            ),
            ActionResult(
                agent_name="Bob", action_name="defect",
                parameters={}, summary="", success=True, skipped=False, round_num=1,
            ),
        ]

    def test_both_cooperate_symmetric_payoff(self, engine, pd_config, pd_actions_both_cooperate):
        """Both cooperate -> both get 3."""
        graph = {"edges": [("Alice", "Bob")]}
        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=pd_actions_both_cooperate,
            config=pd_config,
            grouping_mode="pairwise",
            graph=graph,
        )

        assert result["Alice"] == 3
        assert result["Bob"] == 3

    def test_mixed_choices_asymmetric_payoff(self, engine, pd_config, pd_actions_mixed):
        """Alice cooperates, Bob defects -> Alice gets 0, Bob gets 5."""
        graph = {"edges": [("Alice", "Bob")]}
        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=pd_actions_mixed,
            config=pd_config,
            grouping_mode="pairwise",
            graph=graph,
        )

        assert result["Alice"] == 0
        assert result["Bob"] == 5

    def test_both_defect_symmetric_payoff(self, engine, pd_config):
        """Both defect -> both get 1."""
        actions = [
            ActionResult(
                agent_name="Alice", action_name="defect",
                parameters={}, summary="", success=True, skipped=False, round_num=1,
            ),
            ActionResult(
                agent_name="Bob", action_name="defect",
                parameters={}, summary="", success=True, skipped=False, round_num=1,
            ),
        ]
        graph = {"edges": [("Alice", "Bob")]}

        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=actions,
            config=pd_config,
            grouping_mode="pairwise",
            graph=graph,
        )

        assert result["Alice"] == 1
        assert result["Bob"] == 1

    def test_four_agents_two_pairs(self, engine, pd_config):
        """Four agents form two pairs, each pair calculates independently."""
        actions = [
            ActionResult(agent_name="Alice", action_name="cooperate",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Bob", action_name="defect",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Charlie", action_name="cooperate",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Diana", action_name="cooperate",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
        ]
        # Alice-Bob pair, Charlie-Diana pair
        graph = {"edges": [("Alice", "Bob"), ("Charlie", "Diana")]}

        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=actions,
            config=pd_config,
            grouping_mode="pairwise",
            graph=graph,
        )

        # Alice cooperates, Bob defects -> Alice 0, Bob 5
        assert result["Alice"] == 0
        assert result["Bob"] == 5
        # Both cooperate -> both 3
        assert result["Charlie"] == 3
        assert result["Diana"] == 3


class TestMatrixPayoffGroupThreshold:
    """Test matrix payoff for group mode with threshold (Stag Hunt)."""

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    @pytest.fixture
    def stag_hunt_config(self):
        """Stag Hunt threshold configuration."""
        return {
            "group_payoff_mode": "threshold",
            "threshold_action": "stag",
            "threshold_reward": 5,
            "threshold_failure": 0,
            "safe_reward": 1,
        }

    @pytest.fixture
    def all_stag_actions(self):
        return [
            ActionResult(agent_name="Alice", action_name="stag",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Bob", action_name="stag",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Charlie", action_name="stag",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
        ]

    @pytest.fixture
    def mixed_actions(self):
        """Two stag, one hare."""
        return [
            ActionResult(agent_name="Alice", action_name="stag",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Bob", action_name="stag",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Charlie", action_name="hare",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
        ]

    @pytest.fixture
    def all_hare_actions(self):
        return [
            ActionResult(agent_name="Alice", action_name="hare",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Bob", action_name="hare",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
            ActionResult(agent_name="Charlie", action_name="hare",
                        parameters={}, summary="", success=True, skipped=False, round_num=1),
        ]

    def test_all_stag_gets_threshold_reward(self, engine, stag_hunt_config, all_stag_actions):
        """All choose stag -> everyone gets threshold_reward (5)."""
        graph = {"edges": [
            ("Alice", "Bob"), ("Bob", "Charlie"), ("Alice", "Charlie")
        ]}

        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=all_stag_actions,
            config=stag_hunt_config,
            grouping_mode="group",
            graph=graph,
        )

        assert result["Alice"] == 5
        assert result["Bob"] == 5
        assert result["Charlie"] == 5

    def test_mixed_choices_stag_gets_failure(self, engine, stag_hunt_config, mixed_actions):
        """Not all stag -> stag choosers get threshold_failure (0), hare gets safe (1)."""
        graph = {"edges": [
            ("Alice", "Bob"), ("Bob", "Charlie"), ("Alice", "Charlie")
        ]}

        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=mixed_actions,
            config=stag_hunt_config,
            grouping_mode="group",
            graph=graph,
        )

        # Alice and Bob chose stag but Charlie chose hare
        assert result["Alice"] == 0  # threshold_failure
        assert result["Bob"] == 0    # threshold_failure
        assert result["Charlie"] == 1  # safe_reward

    def test_all_hare_gets_safe_reward(self, engine, stag_hunt_config, all_hare_actions):
        """All choose hare -> everyone gets safe_reward (1)."""
        graph = {"edges": [
            ("Alice", "Bob"), ("Bob", "Charlie"), ("Alice", "Charlie")
        ]}

        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=all_hare_actions,
            config=stag_hunt_config,
            grouping_mode="group",
            graph=graph,
        )

        assert result["Alice"] == 1
        assert result["Bob"] == 1
        assert result["Charlie"] == 1

    def test_mixed_choices_without_graph_still_use_single_group(self, engine, stag_hunt_config, mixed_actions):
        """Group threshold games without a graph still evaluate the whole group together."""
        result = engine.calculate_round_payoffs(
            payoff_type="matrix",
            actions=mixed_actions,
            config=stag_hunt_config,
            grouping_mode="group",
            graph={"edges": []},
        )

        assert result["Alice"] == 0
        assert result["Bob"] == 0
        assert result["Charlie"] == 1


class TestPoolPayoff:
    """Test pool payoff calculation (Public Goods Game)."""

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    @pytest.fixture
    def pool_config(self):
        return {
            "multiplier": 1.5,
            "initial_tokens": 20,
        }

    def contribute_action(self, agent_name, amount):
        return ActionResult(
            agent_name=agent_name,
            action_name="contribute",
            parameters={"amount": amount},
            summary=f"{agent_name} contributed {amount}",
            success=True,
            skipped=False,
            round_num=1,
        )

    def test_pool_calculation_basic(self, engine, pool_config):
        """3 agents: contribute 0, 10, 20 -> verify correct payoffs.

        Formula: payoff = (initial_tokens - contribution) + (total * multiplier / n)

        Total = 0 + 10 + 20 = 30
        Pool return = 30 * 1.5 / 3 = 15

        Agent A (0): 20 + 15 = 35
        Agent B (10): 10 + 15 = 25
        Agent C (20): 0 + 15 = 15
        """
        actions = [
            self.contribute_action("Alice", 0),
            self.contribute_action("Bob", 10),
            self.contribute_action("Charlie", 20),
        ]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
        )

        assert result["Alice"] == 35.0
        assert result["Bob"] == 25.0
        assert result["Charlie"] == 15.0

    def test_pool_all_contribute_same(self, engine, pool_config):
        """All contribute 10 -> all get same payoff.

        Total = 30
        Pool return = 30 * 1.5 / 3 = 15
        Each: (20 - 10) + 15 = 25
        """
        actions = [
            self.contribute_action("Alice", 10),
            self.contribute_action("Bob", 10),
            self.contribute_action("Charlie", 10),
        ]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
        )

        assert result["Alice"] == 25.0
        assert result["Bob"] == 25.0
        assert result["Charlie"] == 25.0

    def test_pool_free_rider_advantage(self, engine, pool_config):
        """Free rider (contribute 0) gets higher payoff than contributor.

        This is the dilemma of public goods games.
        """
        actions = [
            self.contribute_action("FreeRider", 0),
            self.contribute_action("Contributor", 20),
        ]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
        )

        # Free rider should get more
        assert result["FreeRider"] > result["Contributor"]


class TestPoolPayoffContributionValidation:
    """Test contribution enforcement and payoff calculation accuracy.

    Tests BUG-PGG-01 and BUG-PGG-02: Agents cannot contribute more tokens
    than their current balance, and payoff calculations use the constrained
    contribution value, not the attempted amount.
    """

    @pytest.fixture
    def engine(self):
        return PayoffEngine()

    @pytest.fixture
    def pool_config(self):
        return {
            "multiplier": 1.5,
            "initial_tokens": 20,
        }

    def contribute_action(self, agent_name, amount):
        return ActionResult(
            agent_name=agent_name,
            action_name="contribute",
            parameters={"amount": amount},
            summary=f"{agent_name} contributed {amount}",
            success=True,
            skipped=False,
            round_num=1,
        )

    def test_over_contribution_clamped_to_balance(self, engine, pool_config):
        """When agent attempts to contribute 25 tokens but only has 20,
        contribution is capped at 20."""
        from fos.core.experiment.state import ExperimentState, AgentState

        # Agent has 20 tokens, attempts 25
        state = ExperimentState(
            agents={"Alice": AgentState(resources={"tokens": 20})}
        )
        actions = [self.contribute_action("Alice", 25)]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Total contribution should be 20 (capped), not 25
        # Pool return = 20 * 1.5 / 1 = 30
        # Payoff = (20 - 20) + 30 = 30
        assert result["Alice"] == 30.0

    def test_payoff_uses_constrained_not_attempted_amount(self, engine, pool_config):
        """Payoff calculation uses capped amount (15), not attempted amount (20).

        Agent has 15 tokens, attempts 20.
        Total contribution should be 15 (capped).
        Payoff: (20 - 15) + pool_return, not (20 - 20) + pool_return
        """
        from fos.core.experiment.state import ExperimentState, AgentState

        # Agent has 15 tokens, attempts 20
        state = ExperimentState(
            agents={"Bob": AgentState(resources={"tokens": 15})}
        )
        actions = [self.contribute_action("Bob", 20)]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Contribution capped at 15
        # Pool return = 15 * 1.5 / 1 = 22.5
        # Payoff = (20 - 15) + 22.5 = 27.5
        assert result["Bob"] == 27.5

    def test_multiple_agents_mixed_over_under_contributions(self, engine, pool_config):
        """Multiple agents with mixed valid and over-contributions.

        Alice has 20, contributes 10 (valid)
        Bob has 20, attempts 30 (capped to 20)
        Charlie has 20, contributes 5 (valid)

        All payoffs calculated correctly using constrained amounts.
        """
        from fos.core.experiment.state import ExperimentState, AgentState

        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
                "Charlie": AgentState(resources={"tokens": 20}),
            }
        )
        actions = [
            self.contribute_action("Alice", 10),
            self.contribute_action("Bob", 30),  # Over-contribution
            self.contribute_action("Charlie", 5),
        ]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Total contribution = 10 + 20 (capped) + 5 = 35
        # Pool return = 35 * 1.5 / 3 = 17.5
        # Alice: (20 - 10) + 17.5 = 27.5
        # Bob: (20 - 20) + 17.5 = 17.5
        # Charlie: (20 - 5) + 17.5 = 32.5
        assert result["Alice"] == 27.5
        assert result["Bob"] == 17.5
        assert result["Charlie"] == 32.5

    def test_agent_with_zero_tokens_cannot_contribute(self, engine, pool_config):
        """Agent with 0 tokens cannot contribute (contribution capped at 0)."""
        from fos.core.experiment.state import ExperimentState, AgentState

        state = ExperimentState(
            agents={"Poor": AgentState(resources={"tokens": 0})}
        )
        actions = [self.contribute_action("Poor", 10)]

        result = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Contribution capped at 0
        # Pool return = 0 * 1.5 / 1 = 0
        # Payoff = (20 - 0) + 0 = 20
        assert result["Poor"] == 20.0
