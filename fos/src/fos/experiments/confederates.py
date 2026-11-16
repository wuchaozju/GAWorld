"""
Confederate agent assignment and vote interception for headless council experiments.

Provides:
- Uniform-random confederate assignment with seed-controlled reproducibility
- Predetermined vote generation (no LLM call for confederate votes)
- LLM-mandated and scripted speech modes
- Neighbour-count helpers for downstream analysis
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fos.i18n import T


@dataclass(frozen=True)
class ConfederateSpec:
    """Specification for a single confederate agent.

    Attributes:
        agent_id: Agent name (e.g. "agent_37")
        stance: "yes" or "no" — exactly these strings
        speech_mode: "llm" or "scripted"
    """

    agent_id: str
    stance: str
    speech_mode: str


# ── Placement seed derivation ───────────────────────────────────────────────


def derive_placement_seed(
    base: int,
    proposal_key: str,
    network_label: str,
    branch: int,
) -> int:
    """Derive a deterministic, reproducible placement seed.

    Uses SHA-256 so the seed is identical across processes regardless
    of PYTHONHASHSEED. ``hash()`` is not reproducible across invocations
    when string keys are involved.

    Args:
        base: Base seed (e.g. placement_seed or seed + 1000)
        proposal_key: Proposal identifier
        network_label: Network topology label
        branch: Branch index within the invocation

    Returns:
        Integer seed in [0, 2³¹)
    """
    payload = f"{base}|{proposal_key}|{network_label}|{branch}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


# ── Persona permutation ──────────────────────────────────────────────────────


def permute_node_assignment(
    agent_names: list[str],
    rng: random.Random,
) -> list[str]:
    """Permute which agent occupies which network node. Returns a new list.

    Position ``i`` in the returned list holds the agent occupying that
    network node. The list is a permutation of ``agent_names``.

    Persona, model, and all other agent attributes are never touched —
    they stay bound to the canonical agent id. Only network position
    changes per run, enabling within-agent transition-pair fixed effects.

    Args:
        agent_names: Canonical agent ids in order
        rng: Seeded random instance

    Returns:
        Permuted list: ``result[i]`` = agent occupying node ``i``
    """
    permuted = list(agent_names)
    rng.shuffle(permuted)
    return permuted


def relabel_edges(
    edges: list[list[str]],
    agent_names: list[str],
    permuted: list[str],
) -> list[list[str]]:
    """Relabel network edges through a node-permutation.

    Given an edge list keyed by canonical agent ids and a permutation
    of which agent occupies which node, produce a new edge list where
    each endpoint is replaced by the agent at the corresponding position.

    The graph structure (degree sequence, clustering, etc.) is unchanged
    up to isomorphism.

    Args:
        edges: Original edges ``[[agent_a, agent_b], ...]``
        agent_names: Canonical agent ids in order
        permuted: ``permuted[i]`` = agent occupying node ``i``

    Returns:
        Relabeled edge list
    """
    # Map canonical agent name → its position index
    pos_of: dict[str, int] = {name: idx for idx, name in enumerate(agent_names)}

    relabeled: list[list[str]] = []
    for a, b in edges:
        pa = pos_of[a]
        pb = pos_of[b]
        relabeled.append([permuted[pa], permuted[pb]])

    return relabeled


# ── Assignment ────────────────────────────────────────────────────────────────


def assign_confederates(
    agent_ids: list[str],
    *,
    n_yes: int = 3,
    n_no: int = 3,
    rng: random.Random,
    speech_mode: str = "llm",
) -> list[ConfederateSpec]:
    """Sample confederate agents uniformly from the pool.

    Args:
        agent_ids: All agent IDs to sample from
        n_yes: Number of fixed-yes confederates
        n_no: Number of fixed-no confederates
        rng: Random instance (caller owns the seed)
        speech_mode: "llm" or "scripted"

    Returns:
        List of ConfederateSpec, first n_yes entries with stance "yes",
        the rest with stance "no"

    Raises:
        ValueError: if n_yes + n_no > len(agent_ids)
    """
    total = n_yes + n_no
    if total > len(agent_ids):
        raise ValueError(
            T("error.confederates.sample_too_large", total=total, count=len(agent_ids))
        )

    chosen = rng.sample(agent_ids, total)

    specs: list[ConfederateSpec] = []
    for i, agent_id in enumerate(chosen):
        stance = "yes" if i < n_yes else "no"
        specs.append(ConfederateSpec(agent_id=agent_id, stance=stance, speech_mode=speech_mode))

    return specs


# ── Vote interception ─────────────────────────────────────────────────────────


def confederate_vote_action(spec: ConfederateSpec) -> str:
    """Return the predetermined vote action name for a confederate.

    Args:
        spec: Confederate specification

    Returns:
        "vote_yes" or "vote_no" (never abstain)
    """
    if spec.stance == "yes":
        return "vote_yes"
    elif spec.stance == "no":
        return "vote_no"
    raise ValueError(T("error.confederates.unknown_stance", stance=repr(spec.stance)))


# ── Speech ────────────────────────────────────────────────────────────────────


def confederate_system_prompt(spec: ConfederateSpec, proposal_statement: str) -> str:
    """Build a system prompt instructing the confederate to argue for its stance.

    Writes as a sincerely held personal view — no reference to assignment,
    study design, or concealment. The agent believes its position and argues
    for it naturally.

    Args:
        spec: Confederate specification
        proposal_statement: The proposal text being debated

    Returns:
        System prompt string
    """
    if spec.stance == "yes":
        return (
            f'You are a participant in a deliberation about the following proposal:\n\n'
            f'"{proposal_statement}"\n\n'
            f'You have thought about this carefully and you genuinely support this proposal. '
            f'You believe it is the right course of action. In every round of discussion, '
            f'express your support clearly, give reasons that matter to you personally, '
            f'and respond to what other participants say. You are speaking as yourself, '
            f'not performing a role.'
        )
    else:
        return (
            f'You are a participant in a deliberation about the following proposal:\n\n'
            f'"{proposal_statement}"\n\n'
            f'You have thought about this carefully and you genuinely oppose this proposal. '
            f'You believe it is the wrong course of action. In every round of discussion, '
            f'express your opposition clearly, give reasons that matter to you personally, '
            f'and respond to what other participants say. You are speaking as yourself, '
            f'not performing a role.'
        )


def scripted_argument(spec: ConfederateSpec, proposal_id: str, round_index: int) -> str:
    """Load a pre-written scripted argument for a confederate.

    Reads from data/confederates/scripts.json, keyed
    {proposal_id}.{stance}.{round_index}.

    Falls back to a safe placeholder when the entry is still TODO_WRITE_SCRIPT.

    Args:
        spec: Confederate specification
        proposal_id: Proposal key (e.g. "proposal_a")
        round_index: 0-based round index

    Returns:
        Scripted argument text or fallback placeholder
    """
    scripts_path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "confederates" / "scripts.json"
    try:
        with open(scripts_path) as f:
            scripts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        scripts = {}

    key = f"{proposal_id}.{spec.stance}.{round_index}"
    text = scripts.get(key, "")

    if not text or text == "TODO_WRITE_SCRIPT":
        stance_text = "in favour of" if spec.stance == "yes" else "against"
        return (
            f"[Confederate {spec.agent_id} speaks {stance_text} "
            f"the proposal. (Script not yet written for {key}.)]"
        )

    return text


# ── Neighbour counts ──────────────────────────────────────────────────────────


def confederate_neighbour_counts(
    adjacency: dict[str, list[str]],
    specs: list[ConfederateSpec],
) -> dict[str, dict[str, int]]:
    """Count confederate neighbours for every agent.

    For each agent, returns counts of yes-confederate, no-confederate,
    and total confederate neighbours. Confederates themselves also get
    counts (for diagnostic purposes).

    Args:
        adjacency: Adjacency list mapping agent_id -> list of neighbour agent_ids
        specs: Confederate specifications

    Returns:
        Dict mapping agent_id -> {"conf_yes": int, "conf_no": int, "conf_total": int}
    """
    conf_ids = {spec.agent_id for spec in specs}
    stance_of: dict[str, str] = {spec.agent_id: spec.stance for spec in specs}

    result: dict[str, dict[str, int]] = {}
    for agent, neighbours in adjacency.items():
        conf_yes = 0
        conf_no = 0
        for nb in neighbours:
            if nb in conf_ids:
                if stance_of[nb] == "yes":
                    conf_yes += 1
                elif stance_of[nb] == "no":
                    conf_no += 1
        result[agent] = {
            "conf_yes": conf_yes,
            "conf_no": conf_no,
            "conf_total": conf_yes + conf_no,
        }

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────


def build_confederate_lookup(
    specs: list[ConfederateSpec],
) -> dict[str, ConfederateSpec]:
    """Build a fast agent_id → ConfederateSpec lookup.

    Args:
        specs: Confederate specifications

    Returns:
        Dict mapping agent_id to its ConfederateSpec
    """
    return {spec.agent_id: spec for spec in specs}


def record_confederate_vote(
    spec: ConfederateSpec,
    state_extensions: dict[str, Any],
) -> None:
    """Record a confederate's predetermined vote directly into state extensions.

    Makes no LLM call — writes the fixed vote immediately.

    Args:
        spec: Confederate specification
        state_extensions: The state.extensions dict (mutated in-place)
    """
    vote_value = spec.stance  # "yes" or "no"
    votes = state_extensions.get("votes", {})
    votes[spec.agent_id] = vote_value
    state_extensions["votes"] = votes


def assert_confederate_votes(
    specs: list[ConfederateSpec],
    state_extensions: dict[str, Any],
) -> None:
    """Raise RuntimeError if any confederate's recorded vote differs from its stance.

    A mismatch means vote interception failed and the run is invalid.

    Args:
        specs: Confederate specifications
        state_extensions: The state.extensions dict with recorded votes

    Raises:
        RuntimeError: if any confederate vote does not match
    """
    votes = state_extensions.get("votes", {})
    for spec in specs:
        recorded = votes.get(spec.agent_id)
        if recorded is None:
            raise RuntimeError(
                T(
                    "error.confederates.no_recorded_vote",
                    agent_id=spec.agent_id,
                    stance=spec.stance,
                )
            )
        if recorded != spec.stance:
            raise RuntimeError(
                T(
                    "error.confederates.vote_mismatch",
                    agent_id=spec.agent_id,
                    recorded=repr(recorded),
                    stance=repr(spec.stance),
                )
            )


def compute_k_yes(
    adjacency: dict[str, list[str]],
    final_votes: dict[str, str],
    conf_ids: set[str],
) -> dict[str, dict[str, int]]:
    """Compute k_yes_incl_conf and k_yes_excl_conf for every agent.

    Args:
        adjacency: Undirected adjacency dict
        final_votes: Agent ID -> vote ("yes", "no", or "abstain")
        conf_ids: Set of confederate agent IDs

    Returns:
        Dict mapping agent_id -> {"k_yes_incl_conf": int, "k_yes_excl_conf": int}
    """
    result: dict[str, dict[str, int]] = {}
    for agent, neighbours in adjacency.items():
        yes_incl = 0
        yes_excl = 0
        for nb in neighbours:
            if final_votes.get(nb) == "yes":
                yes_incl += 1
                if nb not in conf_ids:
                    yes_excl += 1
        result[agent] = {
            "k_yes_incl_conf": yes_incl,
            "k_yes_excl_conf": yes_excl,
        }
    return result


def build_adjacency_from_edges(
    edges: list[list[str]],
) -> dict[str, list[str]]:
    """Build an undirected adjacency list from an edge list.

    Args:
        edges: List of [node_a, node_b] edge pairs

    Returns:
        Adjacency dict mapping node -> list of neighbour nodes
    """
    adj: dict[str, list[str]] = {}
    for pair in edges:
        a, b = pair[0], pair[1]
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    return adj
