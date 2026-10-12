"""
Result extraction, gates, and result-file assembly for the checkpointed runner.

Reads the finished FOS node's logs and the tracked LLM calls, attributes
calls to agents and rounds, extracts deliberation messages and votes, counts
empty/failed calls for the empty-response gate, runs the validation gates,
and builds the result dict that is written to runs/results/{run_id}.json.

Functions:
    _extract_results()       — logs, deliberation messages, and votes
    _attribute_calls()       — match tracked LLM calls to log events
    _token_estimate()        — usage tokens, or approximate from text length
    _empty_stats()           — count empty/failed LLM calls and totals
    _call_is_empty()         — True when a tracked call produced no text
    _agent_degree_records()  — per-agent degree from the relabeled edges
    _validate_gates()        — neighbour-context and confederate-vote gates
    _build_result()          — assemble the full result dict
    _write_result_atomically() — fsync then os.replace the result file
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fos.experiment import store
from fos.experiments import confederates as conf
from fos.i18n import T

SCHEMA_VERSION = "2.0"
DELIBERATION_ROUNDS = 3          # rounds 1-3 debate; round 4 votes
TOTAL_ROUNDS = DELIBERATION_ROUNDS + 1
VOTING_ROUND = TOTAL_ROUNDS
EMPTY_RATE_LIMIT = 0.05          # runs with more than 5% empty calls fail


def _extract_results(
    tree: Any,
    current_node: int,
    placement: dict[str, Any],
    tracker,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Extract node logs, deliberation messages, and votes from the finished node."""
    node = tree.nodes[current_node]
    node_logs = list(node.get("logs") or [])
    events_by_round: dict[int, list[dict[str, Any]]] = {}
    for log in node_logs:
        data = log.get("data") or {}
        if log.get("type") == "experiment_action" and isinstance(data, dict) and data.get("round") is not None:
            events_by_round.setdefault(int(data["round"]), []).append(data)

    round_calls = tracker.round_calls if tracker is not None else {}
    attributed = _attribute_calls(round_calls, events_by_round)

    deliberation: list[dict[str, Any]] = []
    for round_idx in range(1, VOTING_ROUND):
        for event in events_by_round.get(round_idx, []):
            agent_uid = str(event.get("agent", ""))
            call_entries = attributed.get((round_idx, agent_uid), [])
            main = call_entries[0] if call_entries else {}
            message = str((event.get("parameters") or {}).get("message", "") or "")
            deliberation.append(
                {
                    "round": round_idx,
                    "agent_uid": agent_uid,
                    "action": str(event.get("action", "")),
                    "text": message,
                    "prompt": str(main.get("prompt", "")),
                    "prompt_tokens": _token_estimate(main, "prompt_tokens", "prompt"),
                    "completion_tokens": _token_estimate(
                        call_entries[-1] if call_entries else {}, "completion_tokens", "response"
                    ),
                }
            )

    votes = {agent["agent_id"]: "abstain" for agent in placement["run_agents"]}
    vote_map = {"vote_yes": "yes", "vote_no": "no", "abstain": "abstain"}
    for event in events_by_round.get(VOTING_ROUND, []):
        action = str(event.get("action", ""))
        agent_uid = str(event.get("agent", ""))
        if action in vote_map:
            votes[agent_uid] = vote_map[action]
    return node_logs, deliberation, votes


def _attribute_calls(
    round_calls: dict[int, list[dict[str, Any]]],
    events_by_round: dict[int, list[dict[str, Any]]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """Match tracked LLM calls to log events, per round and agent.

    The runner forces FOS_LLM_CONCURRENCY=1 so calls happen strictly in agent
    order. A successful speak action takes two calls (main + follow-up);
    every other action takes one. Every event consumes at least one call.
    """
    result: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for round_idx, events in events_by_round.items():
        calls = list(round_calls.get(round_idx, []))
        ci = 0
        for event in events:
            agent_uid = str(event.get("agent", ""))
            action = str(event.get("action", ""))
            n = 2 if round_idx < VOTING_ROUND and event.get("success") and action == "speak" else 1
            n = min(n, len(calls) - ci)
            result[(round_idx, agent_uid)] = calls[ci : ci + n]
            ci += n
    return result


def _token_estimate(entry: dict[str, Any], usage_key: str, text_key: str) -> int:
    """Return a token count from usage metadata, or approximate from text length."""
    usage = entry.get("usage")
    if isinstance(usage, dict):
        value = usage.get(usage_key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return len(str(entry.get(text_key, ""))) // 4


def _empty_stats(tracker) -> tuple[int, int]:
    """Count empty/failed LLM calls and the total number of calls.

    A call counts as empty when its response text is empty/whitespace or its
    usage reports completion_tokens <= 1. Because the FOS LLMClient retries
    inside itself, this count already reflects post-retry failures.
    """
    entries: list[dict[str, Any]] = []
    if tracker is not None:
        for round_idx in range(1, TOTAL_ROUNDS + 1):
            entries.extend(tracker.round_calls.get(round_idx, []))
    empty = sum(1 for entry in entries if _call_is_empty(entry))
    return empty, len(entries)


def _call_is_empty(entry: dict[str, Any]) -> bool:
    """Return True when a tracked call produced no usable text."""
    response = str(entry.get("response") or "")
    if not response.strip():
        return True
    usage = entry.get("usage")
    if isinstance(usage, dict):
        completion = usage.get("completion_tokens")
        if completion is not None:
            try:
                if int(completion) <= 1:
                    return True
            except (TypeError, ValueError):
                pass
    return False


def _agent_degree_records(placement: dict[str, Any]) -> dict[str, int]:
    """Map each agent to its network degree, from the relabeled edges."""
    degree_counts = Counter(node for pair in placement["relabeled_edges"] for node in pair)
    return {agent["agent_id"]: degree_counts.get(agent["agent_id"], 0) for agent in placement["run_agents"]}


def _validate_gates(
    deliberation: list[dict[str, Any]],
    agent_records: dict[str, int],
    votes: dict[str, str],
    conf_specs: list[conf.ConfederateSpec],
    bios: dict[str, str] | None = None,
) -> None:
    """Run the validation gates; raise with a specific message when one fails."""
    prompts: dict[tuple[str, int], int] = {
        (entry["agent_uid"], entry["round"]): len(entry["prompt"]) for entry in deliberation
    }
    problems = [
        uid
        for uid, degree in agent_records.items()
        if degree > 2
        and (uid, 1) in prompts
        and (uid, 3) in prompts
        and prompts[(uid, 3)] <= prompts[(uid, 1)]
    ]
    # ── attribution self-check ──
    # Verify positional attribution for SPEAK actions only (skip actions
    # may produce entries with no prompt, which is fine).
    # We compare a collapsed 60-char slice from the MIDDLE of the bio
    # (bio[20:80]) against the collapsed prompt to avoid prefix collisions
    # between agents in the same archetype cell.
    mismatches = 0
    for entry in deliberation:
        if entry.get("action") != "speak":
            continue
        uid = entry["agent_uid"]
        prompt = entry.get("prompt", "")
        if not prompt.strip():
            mismatches += 1
            continue
        expected_bio = bios.get(uid) if bios else None
        if expected_bio and expected_bio.strip():
            bio_slice = " ".join(expected_bio[20:80].split())
            prompt_collapsed = " ".join(prompt.split())
            if bio_slice not in prompt_collapsed:
                mismatches += 1
    if mismatches:
        raise RuntimeError(
            T("error.results.attribution_gate_failed", mismatches=mismatches)
        )

    if problems:
        raise RuntimeError(
            T("error.results.neighbour_context_gate_failed", problems=problems[:10])
        )
    conf.assert_confederate_votes(conf_specs, {"votes": votes})


def _build_result(
    run_id: str,
    run_row: dict[str, Any],
    matrix: dict[str, str],
    config: dict[str, Any],
    placement: dict[str, Any],
    network_stats: dict[str, Any],
    votes: dict[str, str],
    deliberation: list[dict[str, Any]],
    empty_count: int,
    total_calls: int,
) -> dict[str, Any]:
    """Assemble the full result dict: run-level, per-agent, and deliberation."""
    degree_counts = Counter(node for pair in placement["relabeled_edges"] for node in pair)
    node_of = {name: idx for idx, name in enumerate(placement["permuted"])}
    lookup = conf.build_confederate_lookup(placement["confederates"])

    agents_out: list[dict[str, Any]] = []
    for agent in placement["run_agents"]:
        uid = agent["agent_id"]
        spec = lookup.get(uid)
        agents_out.append(
            {
                "agent_uid": uid,
                "big_five": agent["big_five"],
                "voting_model": agent["voting_model"],
                "is_confederate": spec is not None,
                "confederate_stance": spec.stance if spec is not None else "",
                "degree": degree_counts.get(uid, 0),
                "node_label": node_of.get(uid, -1),
                "vote": votes.get(uid, "abstain"),
            }
        )

    return {
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "config_id": int(run_row["config_id"]),
        "proposal_id": run_row["proposal_id"],
        "population_id": run_row["population_id"],
        "generator": config["generator"],
        "network_condition": "none" if config["generator"] == "none" else "networked",
        "network_label": network_label(config),
        "network_seed": int(matrix["network_seed"]),
        "placement_seed": placement["placement_seed"],
        "network_stats": network_stats,
        "confederates": [
            {"agent_id": s.agent_id, "stance": s.stance, "speech_mode": s.speech_mode}
            for s in placement["confederates"]
        ],
        "node_permutation": placement["permuted"],
        "agents": agents_out,
        "deliberation": deliberation,
        "empty_response_count": empty_count,
        "total_llm_calls": total_calls,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def network_label(config: dict[str, Any]) -> str:
    """Stable label for a config, e.g. holme_kim_p2s1."""
    return f"{config['generator']}_p{config['primary_level']}s{config['secondary_level']}"


def _write_result_atomically(run_id: str, payload: dict[str, Any]) -> str:
    """Write the result file via temp file + fsync + atomic rename."""
    store.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = store.RESULTS_DIR / f"{run_id}.json.tmp"
    final_path = store.RESULTS_DIR / f"{run_id}.json"
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, final_path)
    return f"runs/results/{run_id}.json"
