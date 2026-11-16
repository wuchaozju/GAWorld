"""
Stratified distribution utilities for balanced provider assignment.

Ensures providers are distributed evenly across demographic groups
to avoid confounding variables in experiments.
"""

from typing import List, Dict, Any
import random
from collections import defaultdict


def stratified_provider_assignment(
    agents: List[Dict[str, Any]],
    provider_ids: List[int],
    demographic_keys: List[str] = ["Age", "Income"]
) -> Dict[str, int]:
    """
    Assign providers to agents with stratification across demographic groups.

    This ensures each provider gets a balanced mix of all demographic groups,
    preventing confounds between provider/model and demographics.

    Args:
        agents: List of agent dicts with 'name' and 'properties' containing demographics
        provider_ids: List of provider IDs to distribute (e.g., [1, 2, 3])
        demographic_keys: Keys in agent properties to stratify by (e.g., ["Age", "Income"])

    Returns:
        Dict mapping agent name -> provider_id with stratified assignment

    Example:
        >>> agents = [
        ...     {"name": "Agent 1", "properties": {"Age": "18-30", "Income": "Lower"}},
        ...     {"name": "Agent 2", "properties": {"Age": "31-50", "Income": "Middle"}},
        ... ]
        >>> provider_ids = [1, 2, 3]
        >>> assignment = stratified_provider_assignment(agents, provider_ids)
        >>> # Each demographic group gets ~1/3 of each provider
    """
    if not agents or not provider_ids:
        return {}

    # Group agents by demographic combination
    demographic_groups = defaultdict(list)
    for agent in agents:
        name = agent.get("name")
        props = agent.get("properties", {})

        # Create demographic signature (e.g., "Age:18-30|Income:Lower")
        demo_sig = "|".join(
            f"{key}:{props.get(key, 'unknown')}"
            for key in demographic_keys
            if key in props
        )

        demographic_groups[demo_sig].append(name)

    # Assign providers within each demographic group
    assignment = {}
    num_providers = len(provider_ids)

    for demo_sig, agent_names in demographic_groups.items():
        # Shuffle within group to randomize
        shuffled_names = list(agent_names)
        random.shuffle(shuffled_names)

        # Distribute providers evenly within this demographic group
        for i, agent_name in enumerate(shuffled_names):
            provider_id = provider_ids[i % num_providers]
            assignment[agent_name] = provider_id

    return assignment


def validate_distribution(
    agents: List[Dict[str, Any]],
    assignment: Dict[str, int],
    provider_models: Dict[int, str],
    demographic_keys: List[str] = ["Age", "Income"]
) -> Dict[str, Any]:
    """
    Validate that provider distribution is balanced across demographics.

    Returns a report showing the distribution for debugging/validation.

    Args:
        agents: List of agent dicts
        assignment: Agent name -> provider_id mapping
        provider_models: provider_id -> model name mapping (e.g., {1: "gemma3-4b"})
        demographic_keys: Keys to check balance for

    Returns:
        Distribution report dict with counts per provider per demographic group
    """
    # Count agents per provider per demographic group
    provider_demo_counts = defaultdict(lambda: defaultdict(int))

    for agent in agents:
        name = agent.get("name")
        if name not in assignment:
            continue

        provider_id = assignment[name]
        props = agent.get("properties", {})

        for demo_key in demographic_keys:
            if demo_key in props:
                demo_value = props[demo_key]
                provider_demo_counts[provider_id][f"{demo_key}:{demo_value}"] += 1

    # Convert to regular dict for readability
    report = {
        "provider_distribution": {
            provider_models.get(pid, f"provider_{pid}"): dict(demo_counts)
            for pid, demo_counts in provider_demo_counts.items()
        },
        "total_agents": len(agents),
        "providers_used": list(assignment.values())
    }

    return report


# Example usage for your case:
if __name__ == "__main__":
    # Simulated example based on your 99-agent run

    # After generating agents, use stratified assignment:
    # agents = generate_agents_with_archetypes(...)
    # provider_ids = [1, 2, 3]  # Your 3 providers
    # assignment = stratified_provider_assignment(agents, provider_ids, ["Age", "Income"])

    # Then update each agent:
    # for agent_name, provider_id in assignment.items():
    #     # Call update_agent_llm_config for each agent
    #     pass

    # Validate the distribution:
    # report = validate_distribution(agents, assignment, {1: "gemma3-4b", 2: "phi4-mini", 3: "qwen3-4b"})
    # print(report)
    pass
