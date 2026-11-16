"""
CoordinationFeedbackBuilder - generates coordination feedback for neighbor-based games.

For games like Graph Coloring, provides human-readable feedback about which
neighbors coordinated (same choice) vs conflicted (different choice).

Contains: CoordinationFeedbackBuilder
"""


class CoordinationFeedbackBuilder:
    """Builds coordination feedback for agent context.

    Used in games where agents try to coordinate with neighbors (e.g., Graph Coloring).
    Generates natural language feedback like:
    "Coordinated with: Bob (both red). Conflicted with: Charlie (you red, they blue)."
    """

    def build_feedback(
        self,
        agent_name: str,
        agent_choice: str,
        neighbors: list[str],
        all_choices: dict[str, str],
        goal: str = "match",
    ) -> str:
        """Build coordination feedback for an agent.

        Args:
            agent_name: The agent receiving feedback
            agent_choice: What this agent chose
            neighbors: List of neighbor agent names
            all_choices: Dict mapping all agent names to their choices
            goal: Coordination objective - "match" or "differ"

        Returns:
            Human-readable feedback string
        """
        if not neighbors:
            return "No neighbors to compare with."

        coordinated = []
        conflicted = []

        agent_choice_lower = agent_choice.lower()

        for neighbor in neighbors:
            neighbor_choice = all_choices.get(neighbor)
            if not neighbor_choice:
                continue  # Skip neighbors without choices

            same_choice = neighbor_choice.lower() == agent_choice_lower
            coordinated_condition = same_choice if goal == "match" else not same_choice

            if coordinated_condition:
                coordinated.append((neighbor, neighbor_choice))
            else:
                conflicted.append((neighbor, neighbor_choice))

        parts = []

        if coordinated:
            if goal == "differ":
                coord_str = ", ".join([f"{n} (you {agent_choice}, they {c})" for n, c in coordinated])
            else:
                coord_str = ", ".join([f"{n} (both {c})" for n, c in coordinated])
            parts.append(f"Coordinated with: {coord_str}")

        if conflicted:
            conf_str = ", ".join([f"{n} (you {agent_choice}, they {c})" for n, c in conflicted])
            parts.append(f"Conflicted with: {conf_str}")

        return ". ".join(parts) if parts else "No neighbors to compare with."
