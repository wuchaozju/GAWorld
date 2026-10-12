"""
PayoffEngine - generic payoff calculation for all game types.

Handles matrix (pairwise/group), pool, feedback, and none payoff types.
Validates contribution amounts against agent token balances for PGG.
"""

import logging
import random
from typing import Dict, List, Any, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from fos.core.experiment.state import ExperimentState

from fos.core.experiment.controller import ActionResult
from fos.i18n import T

logger = logging.getLogger(__name__)


class PayoffEngine:
    """Calculates payoffs based on payoff_type and configuration.

    Supported payoff types:
    - matrix: NxN payoff matrix lookup (pairwise or group)
    - pool: Contribution to shared pool with multiplier
    - feedback: No numerical payoffs, coordination feedback only
    - none: No scoring
    """

    def calculate_round_payoffs(
        self,
        payoff_type: str,
        actions: List[ActionResult],
        config: Dict[str, Any],
        grouping_mode: str,
        graph: Dict[str, Any] | None = None,
        state: "ExperimentState | None" = None,
    ) -> Dict[str, int | float]:
        """Calculate payoffs for all agents in a round.

        Args:
            payoff_type: "matrix" | "pool" | "feedback" | "none"
            actions: List of action results from the round
            config: Scenario-specific configuration
            grouping_mode: How agents are grouped
            graph: Network graph for neighbor-based calculations
            state: Current experiment state (for contribution validation)

        Returns:
            Dict mapping agent_name to payoff earned this round
        """
        if payoff_type == "matrix":
            return self._calculate_matrix_payoffs(actions, config, grouping_mode, graph)
        elif payoff_type == "pool":
            return self._calculate_pool_payoffs(actions, config, state)
        elif payoff_type == "feedback":
            return {}  # No numerical payoffs
        else:  # "none"
            return {}

    def get_pairs_from_graph(
        self,
        graph: Dict[str, Any],
        agent_names: List[str],
    ) -> List[Tuple[str, str]]:
        """Select pairs from graph edges for pairwise mode.

        Rules:
            1. Each agent can only be in ONE pair per round
            2. Randomly select from available edges
            3. Disconnected nodes sit out

        Args:
            graph: {"edges": [(A, B), (A, C), ...]}
            agent_names: List of all agent names

        Returns:
            List of (agent1, agent2) tuples
        """
        edges = graph.get("edges", [])
        available_edges = [
            (a, b) for a, b in edges
            if a in agent_names and b in agent_names
        ]
        random.shuffle(available_edges)

        paired = set()
        pairs = []

        for agent1, agent2 in available_edges:
            if agent1 not in paired and agent2 not in paired:
                pairs.append((agent1, agent2))
                paired.add(agent1)
                paired.add(agent2)

        return pairs

    def get_groups_from_graph(
        self,
        graph: Dict[str, Any],
        agent_names: List[str],
    ) -> List[List[str]]:
        """Find connected components for group mode.

        If graph is fully connected -> one big group
        If graph has disconnected components -> separate groups

        Args:
            graph: {"edges": [(A, B), ...]}
            agent_names: List of all agent names

        Returns:
            List of groups, each group is a list of agent names
        """
        edges = graph.get("edges", [])
        if not edges:
            return [agent_names] if agent_names else []

        # Build adjacency list
        adjacency = {name: set() for name in agent_names}
        for a, b in edges:
            if a in agent_names and b in agent_names:
                adjacency[a].add(b)
                adjacency[b].add(a)

        # BFS to find connected components
        visited = set()
        groups = []

        for agent in agent_names:
            if agent not in visited:
                group = []
                queue = [agent]
                while queue:
                    current = queue.pop(0)
                    if current not in visited:
                        visited.add(current)
                        group.append(current)
                        queue.extend(adjacency[current] - visited)
                groups.append(group)

        return groups

    def _calculate_matrix_payoffs(
        self,
        actions: List[ActionResult],
        config: Dict[str, Any],
        grouping_mode: str,
        graph: Dict[str, Any] | None,
    ) -> Dict[str, int]:
        """Calculate payoffs using matrix lookup.

        Handles both pairwise and group modes.
        """
        if graph is None:
            graph = {"edges": []}

        payoffs = {}
        action_map = {
            a.agent_name: str(a.action_name).lower()
            for a in actions if not a.skipped
        }
        agent_names = list(action_map.keys())

        if grouping_mode == "pairwise":
            pairs = self.get_pairs_from_graph(graph, agent_names)
            payoffs = self._calculate_matrix_payoffs_pairwise(
                actions, config, pairs, action_map
            )
        elif grouping_mode == "group":
            groups = self.get_groups_from_graph(graph, agent_names)
            payoffs = self._calculate_matrix_payoffs_group(
                actions, config, groups, action_map
            )

        return payoffs

    def _calculate_matrix_payoffs_pairwise(
        self,
        actions: List[ActionResult],
        config: Dict[str, Any],
        pairs: List[Tuple[str, str]],
        action_map: Dict[str, str],
    ) -> Dict[str, int]:
        """Calculate payoffs for pairwise matrix games."""
        payoffs = {}
        matrix = config.get("matrix", {})

        for agent1, agent2 in pairs:
            choice1 = action_map.get(agent1)
            choice2 = action_map.get(agent2)

            if not choice1 or not choice2:
                continue

            key = f"{choice1}_{choice2}"
            cell = matrix.get(key, {"value": 0})

            if "value" in cell:
                # Symmetric: both get same
                payoffs[agent1] = cell["value"]
                payoffs[agent2] = cell["value"]
            else:
                # Asymmetric: row/col payoffs
                payoffs[agent1] = cell.get("row", 0)
                payoffs[agent2] = cell.get("col", 0)

        return payoffs

    def _calculate_matrix_payoffs_group(
        self,
        actions: List[ActionResult],
        config: Dict[str, Any],
        groups: List[List[str]],
        action_map: Dict[str, str],
    ) -> Dict[str, int]:
        """Calculate payoffs for group matrix games.

        Supports threshold mode for games like Stag Hunt.
        """
        payoffs = {}

        if config.get("group_payoff_mode") != "threshold":
            return payoffs

        threshold_action = config.get("threshold_action", "cooperate")
        threshold_reward = config.get("threshold_reward", 5)
        threshold_failure = config.get("threshold_failure", 0)
        safe_reward = config.get("safe_reward", 1)

        for group in groups:
            choices = [action_map.get(a) for a in group if a in action_map]
            all_chose_target = all(c == threshold_action for c in choices)

            for agent in group:
                choice = action_map.get(agent)
                if choice == threshold_action:
                    payoffs[agent] = threshold_reward if all_chose_target else threshold_failure
                else:
                    payoffs[agent] = safe_reward

        return payoffs

    def _calculate_pool_payoffs(
        self,
        actions: List[ActionResult],
        config: Dict[str, Any],
        state: "ExperimentState | None" = None,
    ) -> Dict[str, int | float]:
        """Calculate payoffs for contribution games.

        Formula: payoff = (initial_tokens - contribution) + (total_contributions * multiplier / n)

        This equals: tokens_kept + share_of_pool

        Contribution validation (BUG-PGG-01, BUG-PGG-02):
            - Contributions are capped at agent's current token balance
            - Payoff calculations use constrained contribution values

        Config:
            multiplier: float (e.g., 1.5)
            initial_tokens: int (starting tokens per agent)
        """
        payoffs = {}
        total_contribution = 0
        contributions = {}

        logger.debug(f"Calculating pool payoffs: multiplier={config.get('multiplier')}, state={'provided' if state else 'none'}")

        for action in actions:
            if not action.skipped:
                if action.action_name in ("contribute", "allocate"):
                    attempted_amount = action.parameters.get("amount", 0)
                    if not isinstance(attempted_amount, (int, float)):
                        raise TypeError(
                            T(
                                "api.errors.contribution_amount_not_numeric",
                                type_name=type(attempted_amount).__name__,
                                value=repr(attempted_amount),
                            )
                        )

                    # Validate contribution against agent's token balance
                    if state is not None:
                        agent = state.agents.get(action.agent_name)
                        if agent:
                            current_tokens = agent.resources.get("tokens", 0)
                            # Cap contribution at current balance (minimum 0)
                            actual_amount = max(0, min(attempted_amount, current_tokens))

                            # Log when contribution is clamped
                            if attempted_amount != actual_amount:
                                logger.debug(
                                    f"Contribution clamped: {action.agent_name} attempted "
                                    f"{attempted_amount}, but only has {current_tokens} tokens. "
                                    f"Using {actual_amount}."
                                )
                        else:
                            # Agent not in state, use attempted amount (backward compat)
                            actual_amount = attempted_amount
                    else:
                        # No state provided, use attempted amount (backward compat)
                        actual_amount = attempted_amount

                    amount = actual_amount
                else:
                    amount = 0  # Non-contribute actions contribute 0

                contributions[action.agent_name] = amount
                total_contribution += amount

        num_agents = len([a for a in actions if not a.skipped])
        if num_agents == 0:
            return payoffs

        multiplier = config.get("multiplier", 1.5)
        initial_tokens = config.get("initial_tokens", 20)

        pool_return = (total_contribution * multiplier) / num_agents

        logger.debug(f"Pool: total_contribution={total_contribution}, pool_return={pool_return:.2f}")

        for agent_name, contribution in contributions.items():
            tokens_kept = initial_tokens - contribution
            payoffs[agent_name] = round(tokens_kept + pool_return, 2)
            logger.debug(f"{agent_name}: tokens_kept={tokens_kept}, payoff={payoffs[agent_name]}")

        # Apply deduction effects if enabled
        # Support both new deduction_* and legacy punishment_* config keys
        deduction_config = config.get("deduction", {})
        if not deduction_config:
            deduction_config = config.get("punishment", {})

        # Check if enabled: explicit flag takes priority.
        # enabled=True  → always apply deductions
        # enabled=False → never apply deductions (even if stale data exists)
        # no enabled key → infer from data presence (backward compat)
        is_enabled = deduction_config.get("enabled")
        if is_enabled is None and state is not None:
            # No explicit flag — infer from whether agents recorded deductions
            has_reductions = bool(
                state.extensions.get("reductions") or
                state.extensions.get("punishments")
            )
            is_enabled = has_reductions

        if is_enabled and state is not None:
            payoffs = self._apply_punishment_effects(payoffs, state, deduction_config)
            logger.info(
                f"Applied deduction effects (cost_ratio={deduction_config.get('cost_ratio', 3)})"
            )

        return payoffs

    def _apply_punishment_effects(
        self,
        payoffs: Dict[str, int | float],
        state: "ExperimentState",
        config: Dict[str, Any],
    ) -> Dict[str, int | float]:
        """Apply deduction effects to calculated payoffs.

        Deduction effects are applied at end of round after all
        deduction decisions are collected. This prevents strategic
        ordering effects where later agents see earlier deductions.

        Args:
            payoffs: Base payoffs from pool calculation
            state: Experiment state with deduction allocations
            config: Deduction config with cost_ratio

        Returns:
            Updated payoffs with deduction deductions applied

        Config:
            cost_ratio: Multiplier for deduction effect (e.g., 3 means
                        1 budget point spent = 3 payoff deducted from target)
        """
        cost_ratio = config.get("cost_ratio", 3)

        # Get deduction allocations from state
        # Support both new "reductions" key and legacy "punishments" key
        reductions = state.extensions.get("reductions", {})
        if not reductions:
            reductions = state.extensions.get("punishments", {})

        # Apply each deduction
        for reducer, allocations in reductions.items():
            for allocation in allocations:
                target = allocation.get("target")
                amount = allocation.get("amount", 0)

                if target in payoffs:
                    deduction = amount * cost_ratio
                    # Floor at 0 - payoffs cannot go negative
                    payoffs[target] = max(0, payoffs[target] - deduction)
                    logger.debug(
                        f"Deduction: {reducer} -> {target}, "
                        f"amount={amount}, deduction={deduction}, "
                        f"new_payoff={payoffs[target]}"
                    )

        return payoffs
