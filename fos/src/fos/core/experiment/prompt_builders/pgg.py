"""
PGG-specific prompt builder for allocate/deduct phases.

Generates phase-appropriate prompts with neutral language
matching canonical experimental instructions.

Contains: build_pgg_allocate_prompt, build_pgg_deduct_prompt,
          build_pgg_allocate_followup, build_pgg_deduct_followup
"""

from typing import Any


def build_pgg_allocate_prompt(
    agent_name: str,
    agent_personality: str,
    resource_name: str,
    tokens_per_round: int,
    multiplier: float,
    num_members: int,
    agent_total_resources: float,
    context_history: str,
) -> str:
    """Build allocate phase prompt.

    Args:
        agent_name: Agent's name
        agent_personality: Agent's personality/role description
        resource_name: Name of resource (e.g., "tokens")
        tokens_per_round: Amount received per round
        multiplier: Pool multiplier
        num_members: Number of group members
        agent_total_resources: Agent's current total balance
        context_history: Formatted context from previous rounds

    Returns:
        Complete prompt string
    """
    return f"""You are {agent_name}. {agent_personality}

In this experiment, you receive {tokens_per_round} {resource_name} each round. You may allocate any amount to a group account. The total group account is multiplied by {multiplier} and split equally among all {num_members} members. You keep any {resource_name} you do not allocate.

You currently have {agent_total_resources} {resource_name}.

Your available actions:
- allocate: Add {resource_name} to the group account
- keep: Keep all your {resource_name} this round

{context_history}

Respond with JSON: {{"action": "allocate" or "keep"}}"""


def build_pgg_deduct_prompt(
    agent_name: str,
    agent_personality: str,
    resource_name: str,
    deduction_budget: int,
    cost_ratio: float,
    anonymous: bool,
    round_num: int,
    observed_allocations: list[dict[str, Any]],
    context_history: str,
) -> str:
    """Build deduct phase prompt.

    Args:
        agent_name: Agent's name
        agent_personality: Agent's personality/role description
        resource_name: Name of resource
        deduction_budget: Fixed deduction budget for this phase
        cost_ratio: Deduction cost ratio (1:N)
        anonymous: Whether deductions are anonymous
        round_num: Current round number
        observed_allocations: List of {agent, amount} allocations observed
        context_history: Formatted context from previous rounds

    Returns:
        Complete prompt string
    """
    visibility = "Deductions are anonymous." if anonymous else "Deductions are visible to others."

    # Format observed allocations
    allocation_lines = [
        f"- {a['agent']}: allocated {a['amount']} {resource_name}"
        for a in observed_allocations
    ]
    allocations_str = "\n".join(allocation_lines) if allocation_lines else "No allocations observed."

    return f"""You are {agent_name}. {agent_personality}

You now have the opportunity to reduce the {resource_name} of other members. Reducing another member's {resource_name} by {cost_ratio} costs you 1 {resource_name} from your deduction budget. {visibility}

Your deduction budget this phase: {deduction_budget} {resource_name} (separate from your main balance).

Round {round_num} allocations you observed:
{allocations_str}

Your available actions:
- reduce: Deduct {resource_name} from another member
- skip: Do nothing this phase

{context_history}

Respond with JSON: {{"action": "reduce" or "skip"}}"""


def build_pgg_allocate_followup(
    resource_name: str,
    agent_total_resources: float,
) -> str:
    """Build allocate follow-up prompt.

    Args:
        resource_name: Name of resource
        agent_total_resources: Agent's current total balance

    Returns:
        Follow-up prompt string
    """
    return f"""How many {resource_name} do you allocate to the group account? (0 to {agent_total_resources})

Respond with JSON: {{"amount": <number>}}"""


def build_pgg_deduct_followup(
    resource_name: str,
    deduction_budget: int,
    available_targets: list[str],
) -> str:
    """Build deduct follow-up prompt.

    Args:
        resource_name: Name of resource
        deduction_budget: Remaining deduction budget
        available_targets: List of target agent names

    Returns:
        Follow-up prompt string
    """
    targets_str = ", ".join(available_targets)
    return f"""Who do you reduce and by how much? Available targets: [{targets_str}]
You have {deduction_budget} deduction budget remaining.

Respond with JSON: {{"target": "<name>", "amount": <number>}}"""
