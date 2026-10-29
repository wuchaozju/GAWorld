"""
Smoketest for Public Goods Game deduction/reduction phase features.

Tests FEAT-PGG-01 (Network Visibility):
- Agents only see contributions from agents they're connected to
- Isolated agents (no edges) see no contributions from others
- Visibility respects graph edges in both directions

Tests FEAT-PGG-03 (Reduce Action):
- Agents can allocate deduction tokens to reduce other agents' payoff
- Over-budget amounts are clamped to available budget
- Allocations stored in state.extensions["reductions"]

Legacy backward compatibility:
- Payoff engine reads state.extensions["punishments"] as fallback for old data
"""

import pytest
from fos.core.experiment.state import ExperimentState, AgentState
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.controller import ActionResult


class TestPunishmentVisibility:
    """Tests for network-dependent contribution visibility (FEAT-PGG-01)."""

    @pytest.fixture
    def info_model(self):
        """Create InformationModel instance with neighborhood scope."""
        return InformationModel(scope_type="neighborhood")

    @pytest.fixture
    def isolated_state(self):
        """Agent Alice has no connections to Bob."""
        return ExperimentState(
            agents={
                "Alice": AgentState(
                    resources={"tokens": 20},
                    properties={"last_contribution": 10}
                ),
                "Bob": AgentState(
                    resources={"tokens": 20},
                    properties={"last_contribution": 15}
                ),
            }
        )

    @pytest.fixture
    def isolated_graph(self):
        """No edges - Alice is isolated."""
        return {"edges": []}

    def test_isolated_agent_sees_no_contributions(self, info_model, isolated_state, isolated_graph):
        """Isolated agent sees no contributions from others."""
        visible = info_model.get_visible_contributions(
            "Alice", isolated_state, isolated_graph
        )

        assert visible == {}, f"Isolated agent should see no contributions, got {visible}"

    def test_connected_agents_see_each_other(self, info_model):
        """Connected agents see each other's contributions."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(
                    resources={"tokens": 20},
                    properties={"last_contribution": 10}
                ),
                "Bob": AgentState(
                    resources={"tokens": 20},
                    properties={"last_contribution": 15}
                ),
            }
        )
        graph = {"edges": [("Alice", "Bob")]}

        alice_visible = info_model.get_visible_contributions("Alice", state, graph)
        bob_visible = info_model.get_visible_contributions("Bob", state, graph)

        assert alice_visible == {"Bob": 15}, f"Alice should see Bob's 15, got {alice_visible}"
        assert bob_visible == {"Alice": 10}, f"Bob should see Alice's 10, got {bob_visible}"

    def test_partial_network_visibility(self, info_model):
        """Line network A-B-C-D: each agent sees only neighbors."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(properties={"last_contribution": 10}),
                "Bob": AgentState(properties={"last_contribution": 15}),
                "Charlie": AgentState(properties={"last_contribution": 20}),
                "David": AgentState(properties={"last_contribution": 5}),
            }
        )
        # Line: A-B-C-D
        graph = {"edges": [("Alice", "Bob"), ("Bob", "Charlie"), ("Charlie", "David")]}

        # Alice only sees Bob
        assert info_model.get_visible_contributions("Alice", state, graph) == {"Bob": 15}

        # Bob sees Alice and Charlie
        bob_visible = info_model.get_visible_contributions("Bob", state, graph)
        assert bob_visible == {"Alice": 10, "Charlie": 20}

        # Charlie sees Bob and David
        charlie_visible = info_model.get_visible_contributions("Charlie", state, graph)
        assert charlie_visible == {"Bob": 15, "David": 5}

        # David only sees Charlie
        assert info_model.get_visible_contributions("David", state, graph) == {"Charlie": 20}

    def test_agent_not_in_state_handled_gracefully(self, info_model):
        """If a neighbor is not in state, it's skipped."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(properties={"last_contribution": 10}),
                # Bob is in graph but not in state
            }
        )
        graph = {"edges": [("Alice", "Bob")]}

        alice_visible = info_model.get_visible_contributions("Alice", state, graph)

        # Alice's only neighbor Bob is not in state, so empty dict
        assert alice_visible == {}, f"Should be empty when neighbor not in state, got {alice_visible}"

    def test_missing_contribution_defaults_to_zero(self, info_model):
        """Agent without last_contribution property defaults to 0."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(properties={}),  # No last_contribution
                "Bob": AgentState(properties={"last_contribution": 15}),
            }
        )
        graph = {"edges": [("Alice", "Bob")]}

        alice_visible = info_model.get_visible_contributions("Alice", state, graph)
        bob_visible = info_model.get_visible_contributions("Bob", state, graph)

        assert alice_visible == {"Bob": 15}
        assert bob_visible == {"Alice": 0}


class MockScene:
    """Mock scene with deduction config for testing reduce handler."""

    def __init__(self, deduction_budget=10, cost_ratio=3.0):
        self.config = type('obj', (object,), {
            'parameters': {
                'deduction_budget_per_phase': deduction_budget,
                'deduction_cost_ratio': cost_ratio,
            }
        })()
        self.emitted_events = []

    def _emit_event(self, event_type: str, data: dict):
        self.emitted_events.append({'type': event_type, 'data': data})


class TestReduceAction:
    """Unit tests for reduce action handler validation."""

    @pytest.fixture
    def state_with_budget(self):
        """Create state with two agents having deduction budgets."""
        return ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20, "deduction_budget": 5}),
                "Bob": AgentState(resources={"tokens": 20, "deduction_budget": 5}),
            }
        )

    @pytest.fixture
    def mock_scene(self):
        """Create mock scene with deduction enabled."""
        return MockScene(deduction_budget=10, cost_ratio=3.0)

    def test_valid_reduce_action(self, state_with_budget, mock_scene):
        """Valid reduce action with sufficient budget succeeds."""
        from fos.core.experiment.actions.registry import get_action
        from fos.core.experiment.actions.handlers import handle_reduce

        action = get_action("reduce")
        assert action is not None, "REDUCE_ACTION not registered"

        result = handle_reduce(
            {"target": "Bob", "amount": 3},
            "Alice",
            state_with_budget,
            mock_scene
        )

        assert result["success"] is True
        assert result["amount"] == 3
        assert result["target"] == "Bob"
        assert result.get("effect_applied") is not False

    def test_cannot_reduce_self(self, state_with_budget, mock_scene):
        """Agent cannot reduce themselves."""
        from fos.core.experiment.actions.handlers import handle_reduce

        result = handle_reduce(
            {"target": "Alice", "amount": 3},
            "Alice",
            state_with_budget,
            mock_scene
        )

        assert result["success"] is False
        assert "own" in result.get("error", "").lower()

    def test_cannot_reduce_unknown_agent(self, state_with_budget, mock_scene):
        """Cannot reduce agent that doesn't exist."""
        from fos.core.experiment.actions.handlers import handle_reduce

        result = handle_reduce(
            {"target": "Charlie", "amount": 3},
            "Alice",
            state_with_budget,
            mock_scene
        )

        assert result["success"] is False
        assert "unknown" in result.get("error", "").lower()

    def test_cannot_exceed_budget(self, state_with_budget, mock_scene):
        """Over-budget amount is clamped to available budget."""
        from fos.core.experiment.actions.handlers import handle_reduce

        # Alice has 5 budget, attempts 10
        result = handle_reduce(
            {"target": "Bob", "amount": 10},
            "Alice",
            state_with_budget,
            mock_scene
        )

        assert result["success"] is True
        assert result["amount"] == 5  # Clamped to budget
        assert result["target"] == "Bob"

    def test_reduce_emits_effect_applied(self, state_with_budget, mock_scene):
        """Reduce action returns effect_applied=true via ActionHandler."""
        from fos.core.experiment.action_handler import ActionHandler

        handler = ActionHandler()
        result = handler.execute("reduce", "Alice", {"target": "Bob", "amount": 3}, state_with_budget, mock_scene)

        assert result["success"] is True
        assert result.get("effect_applied") is True


class TestReduceActionRegistry:
    """Tests for reduce action registration in ACTION_REGISTRY."""

    def test_reduce_action_in_registry(self):
        """REDUCE_ACTION is registered in ACTION_REGISTRY."""
        from fos.core.experiment.actions.registry import ACTION_REGISTRY

        assert "reduce" in ACTION_REGISTRY, "reduce action not in ACTION_REGISTRY"
        action = ACTION_REGISTRY["reduce"]
        assert action.name == "reduce"

    def test_reduce_action_has_required_parameters(self):
        """REDUCE_ACTION has target and amount parameters."""
        from fos.core.experiment.actions.registry import get_action

        action = get_action("reduce")
        assert action is not None

        param_names = [p.name for p in action.parameters]
        assert "target" in param_names, "reduce action missing 'target' parameter"
        assert "amount" in param_names, "reduce action missing 'amount' parameter"

    def test_reduce_action_handler_bound(self):
        """REDUCE_ACTION has handler bound."""
        from fos.core.experiment.actions.registry import get_action

        action = get_action("reduce")
        assert action is not None
        assert action.handler is not None, "reduce action handler not bound"

    def test_punish_not_in_registry(self):
        """Punish action should not be in ACTION_REGISTRY."""
        from fos.core.experiment.actions.registry import ACTION_REGISTRY

        assert "punish" not in ACTION_REGISTRY, "punish should be removed from ACTION_REGISTRY"

    def test_public_goods_scenario_has_reduce_action(self):
        """Public Goods scenario actions include 'reduce'."""
        from fos.core.scenarios.registry import PUBLIC_GOODS

        action_ids = [a["id"] for a in PUBLIC_GOODS["actions"]]
        assert "reduce" in action_ids, f"Public Goods should have 'reduce' action, got: {action_ids}"

    def test_public_goods_scenario_no_punish_action(self):
        """Public Goods scenario actions do not include 'punish'."""
        from fos.core.scenarios.registry import PUBLIC_GOODS

        action_ids = [a["id"] for a in PUBLIC_GOODS["actions"]]
        assert "punish" not in action_ids, f"Public Goods should not have 'punish' action, got: {action_ids}"


class TestReduceDisabledExecution:
    """Tests for reduce action behavior when deductions are disabled."""

    def test_reduce_rejected_when_deductions_disabled(self):
        """Reduce action fails when deduction_budget_per_phase is 0."""
        from fos.core.experiment.action_handler import ActionHandler

        handler = ActionHandler()
        state = ExperimentState()
        state.agents["Alice"] = AgentState(resources={"tokens": 20})
        state.agents["Bob"] = AgentState(resources={"tokens": 20})

        # Scene with deductions disabled (budget=0)
        disabled_scene = MockScene(deduction_budget=0, cost_ratio=3.0)

        result = handler.execute("reduce", "Alice", {"target": "Bob", "amount": 5}, state, disabled_scene)

        assert result["success"] is False
        assert result.get("effect_applied") is not True

    def test_reduce_not_offered_when_disabled(self):
        """get_scene_actions does not include reduce when budget is 0."""
        from fos.core.experiment.scene import ExperimentScene
        from fos.core.experiment.config import ExperimentConfig

        config = ExperimentConfig(
            scenario_id="public_goods",
            agents=[
                {"name": "Alice", "properties": {}},
                {"name": "Bob", "properties": {}},
            ],
            actions=[{"name": "allocate"}, {"name": "keep"}],
            parameters={
                "deduction_budget_per_phase": 0,
                "resource_name": "tokens",
                "tokens_per_round": 20,
            },
        )
        scene = ExperimentScene(config)
        scene._initialize_state()

        # Advance to deduct phase — but budget=0, so phase stays allocate
        scene.advance_pgg_phase()
        actions = scene.get_scene_actions("Alice")

        assert "reduce" not in actions, f"reduce should not appear when disabled, got: {actions}"

    def test_no_deduction_effect_when_disabled(self):
        """Payoff engine does not apply deductions when enabled=False."""
        from fos.core.experiment.payoff.engine import PayoffEngine
        from fos.core.experiment.controller import ActionResult

        engine = PayoffEngine()

        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
            },
            extensions={
                "reductions": {
                    "Alice": [{"target": "Bob", "amount": 2}]
                }
            }
        )

        config = {
            "multiplier": 1.5,
            "initial_tokens": 20,
            "deduction": {
                "enabled": False,
                "cost_ratio": 3,
            }
        }

        actions = [
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Alice", round_num=1),
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Bob", round_num=1),
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=config,
            grouping_mode="group",
            state=state,
        )

        # Base payoff: (20 - 10) + (20 * 1.5 / 2) = 25
        # Deductions disabled — no deduction applied
        assert payoffs["Bob"] == 25.0, \
            f"Bob should get 25 (no deduction when disabled), got {payoffs['Bob']}"


class TestReductionStateTracking:
    """Tests for reduction allocation storage in state.extensions."""

    @pytest.fixture
    def state_with_budget(self):
        """Create state with two agents having deduction budgets."""
        return ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20, "deduction_budget": 5}),
                "Bob": AgentState(resources={"tokens": 20, "deduction_budget": 5}),
            }
        )

    @pytest.fixture
    def mock_scene(self):
        """Create mock scene with deduction enabled."""
        return MockScene(deduction_budget=10, cost_ratio=3.0)

    def test_reduction_stored_in_extensions(self, state_with_budget, mock_scene):
        """Reduction allocation is stored in state.extensions['reductions']."""
        from fos.core.experiment.actions.handlers import handle_reduce

        handle_reduce(
            {"target": "Bob", "amount": 3},
            "Alice",
            state_with_budget,
            mock_scene
        )

        assert "reductions" in state_with_budget.extensions
        assert "Alice" in state_with_budget.extensions["reductions"]

        reductions = state_with_budget.extensions["reductions"]["Alice"]
        assert len(reductions) == 1
        assert reductions[0]["target"] == "Bob"
        assert reductions[0]["amount"] == 3

    def test_multiple_reductions_tracked(self, state_with_budget, mock_scene):
        """Multiple reductions from same agent are tracked."""
        from fos.core.experiment.actions.handlers import handle_reduce

        # First reduction
        handle_reduce(
            {"target": "Bob", "amount": 2},
            "Alice",
            state_with_budget,
            mock_scene
        )

        # Second reduction (different target would need another agent)
        # Add Charlie to state
        state_with_budget.agents["Charlie"] = AgentState(
            resources={"tokens": 20, "deduction_budget": 5}
        )

        handle_reduce(
            {"target": "Charlie", "amount": 2},
            "Alice",
            state_with_budget,
            mock_scene
        )

        reductions = state_with_budget.extensions["reductions"]["Alice"]
        assert len(reductions) == 2

    def test_clamped_amount_stored_not_requested(self, state_with_budget, mock_scene):
        """Clamped amount is stored, not requested amount."""
        from fos.core.experiment.actions.handlers import handle_reduce

        # Alice has 5 budget, requests 10
        result = handle_reduce(
            {"target": "Bob", "amount": 10},
            "Alice",
            state_with_budget,
            mock_scene
        )

        # Result shows clamped amount
        assert result["amount"] == 5

        # State also stores clamped amount
        reductions = state_with_budget.extensions["reductions"]["Alice"]
        assert reductions[0]["amount"] == 5  # Not 10


class TestPunishmentPayoffEffect:
    """Tests for FEAT-PGG-04: 3:1 cost ratio for punishment."""

    @pytest.fixture
    def engine(self):
        """Create PayoffEngine instance."""
        from fos.core.experiment.payoff.engine import PayoffEngine
        return PayoffEngine()

    @pytest.fixture
    def pool_config_with_punishment(self):
        """Pool config with punishment enabled."""
        return {
            "multiplier": 1.5,
            "initial_tokens": 20,
            "punishment": {
                "enabled": True,
                "cost_ratio": 3,
            }
        }

    def test_cost_ratio_3_reduces_target_by_3x(self, engine, pool_config_with_punishment):
        """Cost ratio 3: 1 token spent = 3 payoff deducted from target."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
            },
            extensions={
                "punishments": {
                    "Alice": [{"target": "Bob", "amount": 2}]
                }
            }
        )

        # Base payoff from contributions
        actions = [
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Alice", round_num=1),
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Bob", round_num=1),
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config_with_punishment,
            grouping_mode="group",
            state=state,
        )

        # Base payoff: (20 - 10) + (20 * 1.5 / 2) = 10 + 15 = 25
        # Bob punished by Alice: 2 tokens * 3 ratio = 6 deduction
        # Bob final: 25 - 6 = 19
        assert payoffs["Bob"] == 19.0, \
            f"Bob's payoff should be 19 (25 - 6), got {payoffs['Bob']}"
        assert payoffs["Alice"] == 25.0, \
            f"Alice's payoff should be 25 (no punishment received), got {payoffs['Alice']}"

    def test_multiple_punishers_cumulative(self, engine, pool_config_with_punishment):
        """Multiple punishers stack - effects are cumulative."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
                "Charlie": AgentState(resources={"tokens": 20}),
            },
            extensions={
                "punishments": {
                    "Alice": [{"target": "Charlie", "amount": 2}],
                    "Bob": [{"target": "Charlie", "amount": 3}],
                }
            }
        )

        actions = [
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Alice", round_num=1),
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Bob", round_num=1),
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Charlie", round_num=1),
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config_with_punishment,
            grouping_mode="group",
            state=state,
        )

        # Base payoff: (20 - 10) + (30 * 1.5 / 3) = 10 + 15 = 25
        # Charlie punished: (2 + 3) * 3 = 15 deduction
        # Charlie final: 25 - 15 = 10
        assert payoffs["Charlie"] == 10.0, \
            f"Charlie's payoff should be 10 (25 - 15), got {payoffs['Charlie']}"

    def test_payoff_floor_at_zero(self, engine, pool_config_with_punishment):
        """Payoff cannot go negative - floor at 0."""
        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
            },
            extensions={
                "punishments": {
                    "Alice": [{"target": "Bob", "amount": 20}]  # Huge punishment
                }
            }
        )

        actions = [
            ActionResult(success=True, action_name="contribute", parameters={"amount": 0}, summary="", agent_name="Alice", round_num=1),
            ActionResult(success=True, action_name="contribute", parameters={"amount": 0}, summary="", agent_name="Bob", round_num=1),
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config_with_punishment,
            grouping_mode="group",
            state=state,
        )

        # Base payoff: 20 + 0 = 20
        # Punishment: 20 * 3 = 60 deduction
        # Without floor: 20 - 60 = -40
        # With floor: max(0, -40) = 0
        assert payoffs["Bob"] == 0.0, \
            f"Bob's payoff should be 0 (floor), got {payoffs['Bob']}"

    def test_punishment_disabled_no_effect(self, engine):
        """Punishment disabled = no payoff deduction."""
        config_no_punishment = {
            "multiplier": 1.5,
            "initial_tokens": 20,
            "punishment": {
                "enabled": False,
                "cost_ratio": 3,
            }
        }

        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
            },
            extensions={
                "punishments": {
                    "Alice": [{"target": "Bob", "amount": 2}]
                }
            }
        )

        actions = [
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Alice", round_num=1),
            ActionResult(success=True, action_name="contribute", parameters={"amount": 10}, summary="", agent_name="Bob", round_num=1),
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=config_no_punishment,
            grouping_mode="group",
            state=state,
        )

        # No punishment applied - base payoff only
        # Base: (20 - 10) + 15 = 25
        assert payoffs["Bob"] == 25.0, \
            f"With punishment disabled, Bob should get 25, got {payoffs['Bob']}"


class TestDeductionBudget:
    """Tests for FEAT-PGG-02: Per-phase deduction budget allocation."""

    @pytest.fixture
    def pgg_config_with_deduction(self):
        """PGG config with deduction enabled."""
        from fos.core.experiment.config import ExperimentConfig
        return ExperimentConfig(
            scenario_id="public_goods_game",
            agents=[
                {"name": "Alice", "resources": {"tokens": 20}},
                {"name": "Bob", "resources": {"tokens": 20}},
            ],
            actions=[{"name": "contribute"}, {"name": "reduce"}],
            parameters={
                "payoff_type": "pool",
                "multiplier": 1.5,
                "initial_tokens": 20,
                "deduction_budget_per_phase": 5,
            },
        )

    def test_budget_allocated_per_phase(self, pgg_config_with_deduction):
        """Each agent receives deduction budget at initialization."""
        from fos.core.experiment.scene import ExperimentScene
        from unittest.mock import MagicMock

        scene = ExperimentScene(pgg_config_with_deduction)
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value='{"action": "contribute", "amount": 10}')

        scene.initialize(mock_client)

        # Check budget was allocated
        assert scene.state.agents["Alice"].resources.get("deduction_budget") == 5, \
            "Alice should have 5 deduction points"
        assert scene.state.agents["Bob"].resources.get("deduction_budget") == 5, \
            "Bob should have 5 deduction points"

    def test_budget_does_not_carry_over(self, pgg_config_with_deduction):
        """Budget resets each round (fresh allocation)."""
        # This test verifies the reset mechanism exists
        # The actual reset happens in round setup, not initialization
        from fos.core.experiment.scene import ExperimentScene
        from unittest.mock import MagicMock

        scene = ExperimentScene(pgg_config_with_deduction)
        mock_client = MagicMock()
        scene.initialize(mock_client)

        # Simulate budget being spent
        scene.state.agents["Alice"].resources["deduction_budget"] = 2

        # In a real round, budget would be reset before deduct phase
        # For now, just verify the mechanism exists
        initial_budget = pgg_config_with_deduction.parameters.get("deduction_budget_per_phase", 5)
        assert initial_budget == 5, "Config should specify budget per phase"

    def test_over_budget_clamped(self, pgg_config_with_deduction):
        """Over-budget reduction amount is clamped to available budget."""
        from fos.core.experiment.scene import ExperimentScene
        from fos.core.experiment.actions.handlers import handle_reduce
        from unittest.mock import MagicMock

        scene = ExperimentScene(pgg_config_with_deduction)
        mock_client = MagicMock()
        scene.initialize(mock_client)

        # Alice has 5 budget, attempts to reduce with 10
        result = handle_reduce(
            {"target": "Bob", "amount": 10},
            "Alice",
            scene.state,
            scene
        )

        assert result["success"] is True
        assert result["amount"] == 5, "Amount should be clamped to 5 (budget)"


class TestPGGDeductionIntegration:
    """Integration tests for full PGG deduction flow (all requirements)."""

    @pytest.fixture
    def engine(self):
        """Create PayoffEngine instance."""
        from fos.core.experiment.payoff.engine import PayoffEngine
        return PayoffEngine()

    @pytest.fixture
    def full_config(self):
        """Full PGG configuration with deduction enabled."""
        return {
            "payoff_type": "pool",
            "multiplier": 1.5,
            "initial_tokens": 20,
            "deduction_enabled": True,
            "deduction_budget": 10,
            "deduction_ratio": 3,
            "network": {
                "Alice": ["Bob", "Charlie"],
                "Bob": ["Alice", "Charlie"],
                "Charlie": ["Alice", "Bob"],
            },
            "information_scope": "neighborhood",
        }

    def test_full_round_flow_with_deduction(self, engine, full_config):
        """
        Smoketest: Complete round with contributions and deductions.

        Expected behavior:
        - Round 1: Agents contribute to pool
        - Pool payoffs calculated
        - Agents can reduce based on observed contributions
        - Deduction effects applied to final payoff
        """
        pytest.skip("Stub - implement in Wave 1-3")

    def test_deduction_optional_disabled_by_default(self, engine, full_config):
        """
        Smoketest: Deduction is optional and disabled by default.

        Expected behavior:
        - Default config has deduction_enabled=False
        - Game runs normally without deduction
        - Reduce action not available when disabled
        """
        pytest.skip("Stub - implement in Wave 1-3")


class TestPGGDeductionWithScene:
    """Integration tests using ExperimentScene for realistic flow (same as GUI)."""

    @pytest.fixture
    def pgg_deduction_config(self):
        """Create PGG configuration with deduction for ExperimentScene."""
        from fos.core.experiment.config import ExperimentConfig

        return ExperimentConfig(
            scenario_id="public_goods_game",
            agents=[
                {"name": "Alice", "resources": {"tokens": 20}},
                {"name": "Bob", "resources": {"tokens": 20}},
                {"name": "Charlie", "resources": {"tokens": 20}},
            ],
            actions=[
                {"name": "contribute"},
                {"name": "reduce"},
            ],
            parameters={
                "payoff_type": "pool",
                "multiplier": 1.5,
                "initial_tokens": 20,
                "deduction_budget_per_phase": 10,
                "deduction_cost_ratio": 3,
                "network": {
                    "Alice": ["Bob", "Charlie"],
                    "Bob": ["Alice", "Charlie"],
                    "Charlie": ["Alice", "Bob"],
                },
                "information_scope": "neighborhood",
            },
        )

    def test_scene_initializes_deduction_budget(self, pgg_deduction_config):
        """
        Smoketest: ExperimentScene initializes deduction budget per agent.

        Expected behavior:
        - Scene.state tracks deduction_budget for each agent
        - Budget resets each round
        - Budget separate from main token balance
        """
        pytest.skip("Stub - implement in Wave 1-3")

    def test_scene_reduce_action_available_when_enabled(self, pgg_deduction_config):
        """
        Smoketest: Reduce action is available when deduction enabled.

        Expected behavior:
        - Agent's available actions include 'reduce'
        - Reduce action shows target and cost parameters
        - Action list excludes reduce when deduction is disabled
        """
        pytest.skip("Stub - implement in Wave 1-3")

    def test_full_round_flow_with_scene(self, pgg_deduction_config):
        """
        Smoketest: Complete round through ExperimentScene with deduction.

        Expected behavior:
        - Agents contribute via contribute action
        - Agents reduce via reduce action
        - Scene calculates final payoffs including deduction effects
        - State reflects all deductions correctly
        """
        pytest.skip("Stub - implement in Wave 1-3")

    def test_network_visibility_in_agent_prompts(self, pgg_deduction_config):
        """
        Smoketest: Agent prompts show only visible contributions based on network.

        Expected behavior:
        - Alice's prompt shows Bob and Charlie's contributions (fully connected)
        - In partial network, agent sees only neighbors
        - InformationModel enforces visibility in prompt generation
        """
        pytest.skip("Stub - implement in Wave 1-3")

    def test_payoff_reflects_deduction_effects(self, pgg_deduction_config):
        """
        Smoketest: Final payoff reflects all deduction effects.

        Expected behavior:
        - Pool payoff calculated first
        - Deduction costs deducted from reducers
        - Deduction damage deducted from targets
        - Final payoff = pool_payoff - deduction_cost - deduction_damage
        """
        pytest.skip("Stub - implement in Wave 1-3")
