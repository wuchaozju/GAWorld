"""
Context builder utilities for experiment history.

Provides functions to build context summaries from round history,
with support for visibility filtering and structured output.

Contains: build_context_summary, build_structured_context
"""

import json
import os
import urllib.request
from typing import TYPE_CHECKING, Any, Dict, List


# Module-level cache for real token counts from llama-server /tokenize endpoint
# Key: text string, Value: token count
_token_cache: Dict[str, int] = {}

if TYPE_CHECKING:
    from fos.core.experiment.information_model import InformationModel
    from fos.core.experiment.state import ExperimentState


def _format_action_with_parameters(agent_label: str, action_name: str, parameters: Dict[str, Any]) -> str:
    """Render an action with its numeric parameters for prompt context."""
    if "amount" in parameters:
        return f"{agent_label} {action_name} {parameters['amount']}"
    if not parameters:
        return f"{agent_label} {action_name}"
    param_str = ", ".join(f"{key}={value}" for key, value in parameters.items())
    return f"{agent_label} {action_name} ({param_str})"


def build_context_summary(
    round_history: List[Dict[str, Any]],
    max_rounds: int = 5,
    state_snapshot: Dict[str, Any] | None = None,
    for_agent: str | None = None,
    visibility_mode: str = "all"  # "all", "sequential", or custom
) -> str:
    """Build brief summary of recent rounds.

    Args:
        round_history: List of dicts with "round" and "actions" keys.
                      Each action has "agent" and "action" keys.
        max_rounds: Number of recent rounds to include (default: 5).
        state_snapshot: Optional scenario-specific state to append.
        for_agent: Optional agent name to filter visible actions for.
        visibility_mode: How to filter visible actions:
            - "all": Show all actions (default, for backward compatibility)
            - "sequential": In sequential mode, agents see earlier agents' actions
            - "previous_rounds": Show only previous rounds, not current round actions

    Returns:
        Summary string, or "This is the first round." if history is empty.
    """
    if not round_history:
        return "This is the first round."

    # Filter round history based on visibility rules
    filtered_history = _filter_round_history(
        round_history,
        for_agent,
        visibility_mode
    )

    if not filtered_history:
        return "This is the first round."

    lines = []
    recent = filtered_history[-max_rounds:]

    # Summarize each round
    for round_data in recent:
        round_num = round_data["round"]
        actions = round_data["actions"]

        action_strs = [f"{a['agent']} chose {a['action']}" for a in actions]
        actions_desc = ", ".join(action_strs)

        lines.append(f"Round {round_num}: {actions_desc}.")

    # Detect dominant action patterns (3+ occurrences in 3+ rounds)
    agent_actions: Dict[str, Dict[str, int]] = {}

    for round_data in recent:
        for action_data in round_data["actions"]:
            agent = action_data["agent"]
            action = action_data["action"]

            if agent not in agent_actions:
                agent_actions[agent] = {}
            agent_actions[agent][action] = agent_actions[agent].get(action, 0) + 1

    for agent, counts in agent_actions.items():
        total = sum(counts.values())
        if total >= 3:
            dominant_action = max(counts, key=counts.get)
            dominant_count = counts[dominant_action]
            if dominant_count >= 3:
                lines.append(
                    f"{agent} has chosen {dominant_action} in "
                    f"{dominant_count} of the last {total} rounds."
                )

    # Append state snapshot if provided
    if state_snapshot:
        lines.append("\nState:")
        for key, value in state_snapshot.items():
            lines.append(f"- {key}: {value}")

    return "\n".join(lines)


def _filter_round_history(
    round_history: List[Dict[str, Any]],
    for_agent: str | None,
    visibility_mode: str
) -> List[Dict[str, Any]]:
    """Filter round history based on visibility rules for an agent.

    Args:
        round_history: Full round history
        for_agent: Agent name to filter for (None = show all)
        visibility_mode: How to determine visibility

    Returns:
        Filtered round history
    """
    if not for_agent or visibility_mode == "all":
        # No filtering - show all history
        return round_history.copy()

    filtered = []

    for round_data in round_history:
        round_num = round_data["round"]
        actions = round_data["actions"]

        if visibility_mode == "previous_rounds":
            # Show all actions from previous rounds
            # round_history contains only completed rounds, so current round = max + 1
            # This is used when agents in simultaneous/paired mode shouldn't see current round
            current_round = max(r["round"] for r in round_history) + 1
            if round_num < current_round:
                filtered.append(round_data)
        elif visibility_mode == "sequential":
            # In sequential mode, agents see:
            # 1. All previous rounds (full history)
            # 2. Current round: only actions from agents before them in sequence
            current_round_num = max(r["round"] for r in round_history)
            if round_num < current_round_num:
                # Previous rounds - show all
                filtered.append(round_data)
            else:
                # Current round - filter to show only earlier agents' actions
                earlier_actions = []
                for action in actions:
                    # Agent can see actions from agents that went before them
                    # This is a simplified version - assumes sequential order is alphabetical
                    if action["agent"] < for_agent:
                        earlier_actions.append(action)
                if earlier_actions:
                    filtered.append({
                        "round": round_num,
                        "actions": earlier_actions
                    })
        else:
            # Default - no filtering
            filtered.append(round_data)

    return filtered


# -- Transmit cap helpers --

def _get_tokenize_url() -> str:
    """Resolve the /tokenize endpoint URL from environment or default."""
    url = os.environ.get("FOS_TOKENIZE_URL")
    if url:
        return url
    base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080")
    return base.rstrip("/") + "/tokenize"


def _tokenize_remote(text: str) -> int:
    """Call llama-server /tokenize endpoint. Returns token count.
    Falls back to chars//4 on any network error."""
    if not text:
        return 0
    url = _get_tokenize_url()
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"content": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return len(data.get("tokens", []))
    except Exception:
        return len(text) // 4  # emergency fallback only


def _count_tokens(text: str | None) -> int:
    """Count tokens using the real llama-server tokenizer with caching.
    Falls back to chars//4 on network error."""
    if not text:
        return 0
    if text in _token_cache:
        return _token_cache[text]
    count = _tokenize_remote(text)
    _token_cache[text] = count
    return max(1, count)

def _truncate_at_sentence(text: str, max_tokens: int) -> str:
    """Truncate text at the last complete sentence boundary under max_tokens.
    Uses real tokenizer via binary search on character cut point.
    Falls back to chars//4 heuristic if tokenizer is unavailable."""
    if not text:
        return text
    # Quick check: tokenize the full text
    if _count_tokens(text) <= max_tokens:
        return text
    # Binary search on character position to find the longest prefix within budget
    lo, hi = 0, len(text)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        tok = _count_tokens(text[:mid])
        if tok <= max_tokens:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    # Find the last sentence boundary before the best cutoff
    chunk = text[:best]
    last_boundary = -1
    for punct in [". ", "! ", "? "]:
        pos = chunk.rfind(punct)
        if pos >= 0:
            last_boundary = max(last_boundary, pos + 1)
    if last_boundary >= 0:
        return text[:last_boundary]
    # No sentence boundary found — hard cut at the token budget
    return chunk

def _truncate_speech_events(events, cap_tokens):
    """Mutate events in-place: truncate speech messages at cap_tokens."""
    if not cap_tokens or cap_tokens <= 0:
        return events
    for e in events:
        params = getattr(e, 'parameters', None) or {}
        msg = params.get('message', '')
        if not msg:
            continue
        full_tok = _count_tokens(msg)
        e.full_tokens = full_tok
        if full_tok <= cap_tokens:
            e.transmitted_message = msg
            e.truncated = False
            e.transmitted_tokens = full_tok
        else:
            tm = _truncate_at_sentence(msg, cap_tokens)
            e.transmitted_message = tm
            e.truncated = True
            e.transmitted_tokens = _count_tokens(tm)
    return events
# -- end transmit cap --

def build_structured_context(
    for_agent: str,
    events: list,
    info_model: "InformationModel",
    agent_score: "int | None" = None,
    state: "ExperimentState | None" = None,
    graph: dict | None = None,
) -> str:
    """Build deterministic, budget-bounded structured context for an agent.

    Tiered history: recent_window rounds of full detail, optionally with
    round 1 always kept (primacy_keep=True). Applies payoff_template when set.

    Args:
        for_agent: Agent receiving the context (used to identify "my" action)
        events: Pre-filtered RoundEvent list (caller must filter by observed_by)
        info_model: InformationModel controlling window/primacy/template
        agent_score: Agent's cumulative score (shown if info_model.include_scores)
        state: Current experiment state (required for average contribution mode)
        graph: Network graph (required for average contribution mode)

    Returns:
        Formatted context string
    """
    # Apply transmit cap to speech events before rendering
    cap = getattr(info_model, "transmit_cap_tokens", 0)
    if cap and cap > 0:
        events = _truncate_speech_events(list(events), cap)

    if not events:
        return "This is the first round."

    # Group events by round
    rounds_seen = sorted(set(e.round_num for e in events))
    events_by_round: Dict[int, list] = {r: [] for r in rounds_seen}
    for e in events:
        events_by_round[e.round_num].append(e)

    # Determine which rounds to show (recent window + optional primacy)
    max_round = max(rounds_seen)
    cutoff = max_round - info_model.recent_window + 1
    included = [r for r in rounds_seen if r >= cutoff]
    if info_model.primacy_keep and rounds_seen and rounds_seen[0] < cutoff:
        included = [rounds_seen[0]] + included

    lines = []
    for r in sorted(set(included)):
        round_events = events_by_round.get(r, [])
        if not round_events:
            continue

        my_event = next((e for e in round_events if e.agent_name == for_agent), None)
        # FIX: Filter other_events by visibility (observed_by)
        other_events = [e for e in round_events if e.agent_name != for_agent and for_agent in e.observed_by]

        if info_model.payoff_template and my_event is not None:
            # Template IS the complete line — no round prefix added separately
            partner_action = other_events[0].action_name if other_events else "unknown"
            payoff_val = my_event.payoff if my_event.payoff is not None else "?"
            line = info_model.payoff_template.format(
                N=r,
                my_action=my_event.action_name,
                partner_action=partner_action,
                payoff=payoff_val,
            )
        elif my_event is not None and my_event.feedback is not None:
            # Feedback-type games: show action + coordination feedback
            parts = [f"Round {r}: I chose {my_event.action_name}."]
            # Show what neighbors chose
            for e in other_events:
                parts.append(f"{e.agent_name} chose {e.action_name}")
            # Add coordination feedback
            parts.append(f"→ {my_event.feedback}")
            line = " ".join(parts)
        else:
            # CRITICAL: Only apply during allocate phase, not deduct
            if info_model.show_average_contribution and other_events and state:
                # CRITICAL: Check graph FIRST — when a network graph is present,
                # neighbor-scoped averaging must be used regardless of scope_type.
                # The scope_type=="all" path is only for experiments without a graph.
                if graph:
                    # Graph present: use neighbor-scoped average from visible connections
                    visible = info_model.get_visible_contributions(for_agent, state, graph)
                    if visible:
                        # CRITICAL: Use len(visible) for neighbor count, NOT len(other_events)
                        # This ensures count matches average source
                        neighbor_count = len(visible)
                        avg = sum(visible.values()) / neighbor_count
                        # Keep own action, show average for neighbors
                        parts = []
                        if my_event:
                            parts.append(_format_action_with_parameters("I", my_event.action_name, my_event.parameters))
                        parts.append(f"Average contribution from {neighbor_count} neighbors: {avg:.1f}")
                    else:
                        # No visible neighbors — show only own action (no global fallback)
                        parts = []
                        if my_event:
                            parts.append(_format_action_with_parameters("I", my_event.action_name, my_event.parameters))
                elif info_model.scope_type == "all":
                    # No graph: calculate average from ALL other agents' contributions
                    all_contributions = {}
                    for agent_name, agent_state in state.agents.items():
                        if agent_name != for_agent:
                            contribution = agent_state.properties.get("last_contribution", 0)
                            all_contributions[agent_name] = contribution

                    if all_contributions:
                        neighbor_count = len(all_contributions)
                        avg = sum(all_contributions.values()) / neighbor_count
                        # Keep own action, show average for all others
                        parts = []
                        if my_event:
                            parts.append(_format_action_with_parameters("I", my_event.action_name, my_event.parameters))
                        parts.append(f"Average contribution from {neighbor_count} other agents: {avg:.1f}")
                    else:
                        # No other contributions - show just own action
                        parts = []
                        if my_event:
                            parts.append(_format_action_with_parameters("I", my_event.action_name, my_event.parameters))
                else:
                    # No graph available - fall back to showing individuals
                    parts = []
                    if my_event:
                        parts.append(_format_action_with_parameters("I", my_event.action_name, my_event.parameters))
                    for e in other_events:
                        parts.append(_format_action_with_parameters(e.agent_name, e.action_name, e.parameters))
            else:
                # Average not enabled or missing data - show individual contributions
                parts = []
                if my_event:
                    parts.append(_format_action_with_parameters("I", my_event.action_name, my_event.parameters))
                for e in other_events:
                    parts.append(_format_action_with_parameters(e.agent_name, e.action_name, e.parameters))
            line = f"Round {r}: {', '.join(parts)}." if parts else f"Round {r}: (no actions)"
            if any("amount" in e.parameters for e in round_events):
                total_contribution = sum(e.parameters.get("amount", 0) for e in round_events)
                line += f" Total contribution: {total_contribution}."
            if my_event and my_event.payoff is not None:
                line += f" My payoff: {my_event.payoff}."

        lines.append(line)

    if agent_score is not None and info_model.include_scores:
        lines.append(f"My score: {agent_score}")

    return "\n".join(lines)
