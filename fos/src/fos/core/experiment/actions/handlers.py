"""
This file holds the small pieces of action logic used during experiments.

Each function handles one kind of move, like speaking, voting, or moving
around a map, and returns a clear result that the rest of the system can log.
"""
import logging
from typing import Any
from fos.core.experiment.state import ExperimentState

logger = logging.getLogger(__name__)


def _get_council_observers(
    agent_name: str,
    state: ExperimentState,
    scene: Any,
) -> list[str]:
    """Pick who can see a council action based on the scene network."""
    if hasattr(scene, "get_visible_observers"):
        return list(scene.get_visible_observers(agent_name))

    config = getattr(scene, "config", None)
    social_network = getattr(config, "social_network", {}) or {}
    edges = social_network.get("edges", [])
    if not edges:
        return list(state.agents.keys())

    neighbors = [b for a, b in edges if a == agent_name]
    neighbors.extend(a for a, b in edges if b == agent_name)
    return sorted(set([agent_name, *neighbors]))

    return list(state.agents.keys())


def handle_move(agent_name: str, params: dict, state: ExperimentState) -> dict[str, Any]:
    """Handle move action - update agent position on grid.

    Args:
        agent_name: Agent moving
        params: {"direction": "north"|"south"|"east"|"west"}
        state: Current experiment state

    Returns:
        Result dict with success status and new position
    """
    direction = params.get("direction", "")
    current_pos = state.get_agent_position(agent_name)

    if current_pos is None:
        return {"success": False, "error": "Agent has no position"}

    x, y = current_pos
    dx, dy = {
        "north": (0, -1),
        "south": (0, 1),
        "east": (1, 0),
        "west": (-1, 0),
    }.get(direction, (0, 0))

    new_pos = (x + dx, y + dy)

    # TODO: Add boundary checking when we have grid dimensions

    state.update_agent_position(agent_name, new_pos)

    return {
        "success": True,
        "old_position": current_pos,
        "new_position": new_pos,
    }


def handle_talk(agent_name: str, params: dict, state: ExperimentState) -> dict[str, Any]:
    """Handle talk action - record message for context.

    Args:
        agent_name: Agent sending message
        params: {"target": "AgentName", "message": "text"}
        state: Current experiment state (unused, but required for handler signature)

    Returns:
        Result dict with success status
    """
    _ = state  # State not needed for talk action
    target = params.get("target", "")
    message = params.get("message", "")

    if not target or not message:
        return {"success": False, "error": "Missing target or message"}

    # Messages are added to context, not state
    # The runner will add this to the event history
    return {
        "success": True,
        "from": agent_name,
        "to": target,
        "message": message,
    }


# === Council Action Handlers ===

def handle_council_speak(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for council speak action.

    Records speech to round context manager for multi-round deliberation.
    Agents can reference previous speeches in follow-up turns.

    Args:
        action_data: Action parameters with 'message' field
        agent_name: Name of agent speaking
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status and summary
    """
    message = action_data.get("message", "")

    # Create summary (truncate long messages)
    summary = f"{agent_name} spoke: {message[:100]}{'...' if len(message) > 100 else ''}"

    # Record to round context manager if available
    if hasattr(scene, 'round_context_manager'):
        scene.round_context_manager.record_action(
            agent_name=agent_name,
            action_name="speak",
            parameters={"message": message},
            round_num=getattr(scene, 'round_num', 1),
            summary=summary,
            observed_by=_get_council_observers(agent_name, state, scene),
        )

    return {"success": True, "summary": summary}


def handle_start_voting(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for start_voting action.

    Transitions scene to voting phase. Only allowed if voting not already started.

    Args:
        action_data: Action parameters with 'title' field
        agent_name: Name of agent initiating vote (unused, any agent can start)
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status and summary
    """
    _ = agent_name  # Any agent can start voting
    # State guard: voting not already started
    if state.extensions.get("voting_started", False):
        return {"success": False, "message": "Voting has already started"}

    title = action_data.get("title", "the proposal")

    # Update state
    state.extensions["voting_started"] = True
    state.extensions["vote_title"] = title
    state.extensions["votes"] = {}

    # Transition facilitator if available
    if hasattr(scene, 'facilitator'):
        scene.facilitator.transition_to_voting(title)

    summary = f"Voting started on: {title}"
    return {"success": True, "summary": summary}


def handle_vote(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for vote action.

    Records vote choice to state.extensions['votes'] dict.
    Only allowed if voting phase has started.

    Args:
        action_data: Action parameters with 'choice' field (yes/no/abstain)
        agent_name: Name of agent voting
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status and summary
    """
    # State guard: voting must be started
    if not state.extensions.get("voting_started", False):
        return {"success": False, "message": "Voting has not started yet"}

    choice = action_data.get("choice", "abstain")
    if choice not in ["yes", "no", "abstain"]:
        return {"success": False, "message": f"Invalid vote choice: {choice}"}

    # Record vote
    votes = state.extensions.get("votes", {})
    votes[agent_name] = choice
    state.extensions["votes"] = votes

    summary = f"{agent_name} voted {choice}"

    # Record to context manager
    if hasattr(scene, 'round_context_manager'):
        scene.round_context_manager.record_action(
            agent_name=agent_name,
            action_name="vote",
            parameters={"choice": choice},
            round_num=getattr(scene, 'round_num', 1),
            summary=summary,
            observed_by=_get_council_observers(agent_name, state, scene),
        )

    return {"success": True, "summary": summary}


def handle_vote_yes(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for vote_yes action.

    Records 'yes' vote to state.extensions['votes'] dict.
    Only allowed if voting phase has started.

    Args:
        action_data: Empty dict (no parameters)
        agent_name: Name of agent voting
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status and summary
    """
    # Delegate to handle_vote with choice='yes'
    return handle_vote({"choice": "yes"}, agent_name, state, scene)


def handle_vote_no(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for vote_no action.

    Records 'no' vote to state.extensions['votes'] dict.
    Only allowed if voting phase has started.

    Args:
        action_data: Empty dict (no parameters)
        agent_name: Name of agent voting
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status and summary
    """
    # Delegate to handle_vote with choice='no'
    return handle_vote({"choice": "no"}, agent_name, state, scene)


def handle_abstain(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for abstain action.

    Records 'abstain' vote to state.extensions['votes'] dict.
    Only allowed if voting phase has started.

    Args:
        action_data: Empty dict (no parameters)
        agent_name: Name of agent voting
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status and summary
    """
    # Delegate to handle_vote with choice='abstain'
    return handle_vote({"choice": "abstain"}, agent_name, state, scene)


def handle_conclude(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handler for conclude action.

    Marks experiment as complete after voting. Checks threshold
    to determine if proposal passed.

    Args:
        action_data: Action parameters (unused for conclude)
        agent_name: Name of agent concluding (unused, any agent can conclude)
        state: Current experiment state
        scene: CouncilExperimentScene instance

    Returns:
        Result dict with success status, summary, and threshold check result
    """
    _ = action_data, agent_name  # Conclude doesn't need parameters
    # State guard: voting must be complete
    if not state.extensions.get("voting_started", False):
        return {"success": False, "message": "Cannot conclude before voting"}

    votes = state.extensions.get("votes", {})
    total_votes = len(votes)
    yes_votes = sum(1 for v in votes.values() if v == "yes")

    # Check threshold (from config or default 0.5)
    threshold = 0.5
    if hasattr(scene, 'game_config') and hasattr(scene.game_config, 'voting_threshold'):
        threshold = scene.game_config.voting_threshold
    elif hasattr(scene, 'voting_threshold'):
        threshold = scene.voting_threshold

    passed = (yes_votes / total_votes >= threshold) if total_votes > 0 else False

    # Update state
    state.extensions["concluded"] = True
    state.extensions["proposal_passed"] = passed

    result = "passed" if passed else "rejected"
    summary = f"Meeting concluded. Proposal {result} ({yes_votes}/{total_votes} yes votes)"

    return {"success": True, "summary": summary, "passed": passed}


# === PGG Reduction Action Handler ===

def handle_reduce(action_data: dict, agent_name: str, state: ExperimentState, scene) -> dict[str, Any]:
    """Handle reduce action with validation and budget enforcement.

    Cost semantics (per Fehr & Gächter 2002):
    - actual_amount: deduction budget points spent by reducer
    - cost_ratio: how much target loses per budget point spent (e.g., 3.0)
    - deduction: actual loss to target = actual_amount * cost_ratio

    Example: cost_ratio=3.0 means reducer spends 1 budget point → target loses 3 resources

    Validates:
    - Deductions must be enabled (budget > 0 in config)
    - Agent cannot reduce themselves
    - Target must exist in state.agents
    - Amount is clamped to available deduction budget

    Stores reduction in state.extensions["reductions"] for end-of-round
    payoff calculation. Payoff engine applies deductions at round end
    to prevent ordering effects.

    Emits reduction_action event for experiment logging.

    Args:
        action_data: {"target": agent_name, "amount": int}
        agent_name: Name of reducing agent
        state: Current experiment state
        scene: Scene reference for event emission and config access

    Returns:
        {"success": bool, "amount": int, "target": str, "deduction": float} or
        {"success": False, "error": str}
    """
    # Guard: Early return if deductions are disabled
    params = {}
    if scene is not None:
        if hasattr(scene, 'config') and hasattr(scene.config, 'parameters'):
            params = scene.config.parameters or {}
        elif hasattr(scene, 'game_config') and hasattr(scene.game_config, 'parameters'):
            params = scene.game_config.parameters or {}

    if int(params.get("deduction_budget_per_phase", 0) or 0) <= 0:
        return {"success": False, "error": "Deductions are disabled (budget=0)"}

    target = action_data.get("target")
    amount = action_data.get("amount", 0)

    # Validation 1: No self-reduction
    if target == agent_name:
        return {"success": False, "error": "Cannot reduce your own resources"}

    # Validation 2: Target exists
    if target not in state.agents:
        return {"success": False, "error": f"Unknown target: {target}"}

    # Validation 3: Clamp to budget
    agent = state.agents.get(agent_name)
    if not agent:
        return {"success": False, "error": "Agent not found in state"}

    current_budget = agent.resources.get("deduction_budget", 0)
    actual_amount = max(0, min(amount, current_budget))

    if actual_amount < amount:
        logger.debug(f"Reduction clamped: {agent_name} attempted {amount}, has {current_budget}")

    if actual_amount == 0:
        return {"success": False, "error": "No deduction budget remaining"}

    # Store reduction allocation for end-of-round processing
    # Payoff engine reads this at round end and applies deductions
    if "reductions" not in state.extensions:
        state.extensions["reductions"] = {}
    if agent_name not in state.extensions["reductions"]:
        state.extensions["reductions"][agent_name] = []

    state.extensions["reductions"][agent_name].append({
        "target": target,
        "amount": actual_amount,
    })

    # Deduct from budget (1 budget point per reduction attempt)
    agent.resources["deduction_budget"] = current_budget - actual_amount

    # Calculate target's loss using cost_ratio
    # cost_ratio = how much target loses per budget point spent
    # Default 3.0 per Fehr & Gächter 2002 canonical design
    cost_ratio = float(params.get('deduction_cost_ratio', 3.0) or 3.0)
    deduction = actual_amount * cost_ratio

    # Emit event for experiment logging
    if scene is not None and hasattr(scene, '_emit_event'):
        scene._emit_event("reduction_action", {
            "reducer": agent_name,
            "target": target,
            "amount": actual_amount,
            "deduction": deduction,
            "cost_ratio": cost_ratio,
            "round": getattr(scene, 'current_round', 1),
        })

    return {
        "success": True,
        "amount": actual_amount,
        "target": target,
        "deduction": deduction,
    }
