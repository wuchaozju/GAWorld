"""
Builds the deterministic FOS scene and SimTree for one experiment run.

Turns a run's placement (computed elsewhere from the matrix seed) into a
FOS council scene with relabeled edges, injects confederate prompts onto
deep copies of the agent configs, and wraps everything in a SimTree with a
network_replace branch, ready for round-by-round advance.

Functions:
    _fos_agent_config()     — convert a population agent into a FOS agent config
    _build_council_scene()  — build the FOS council scene for a run
    _build_tree()           — SimTree + network_replace branch
    _deserialize_tree()     — rebuild a SimTree from a checkpoint payload
    _placement_to_json()    — placement dict -> JSON-safe dict
    _placement_from_json()  — JSON-safe dict -> placement dict
"""

from __future__ import annotations

import copy
from typing import Any

from fos.experiment import network
from fos.experiment.results import DELIBERATION_ROUNDS
from fos.experiments import confederates as conf
from fos.i18n import T


def _fos_agent_config(agent: dict[str, Any], conf_prompt: str | None, provider_id: str = "") -> dict[str, Any]:
    """Convert a population agent into the agent dict the FOS scene expects."""
    archetype = agent.get("archetype_cell") or {}
    big_five = agent.get("big_five") or {}
    bio = agent.get("bio", "") or ""
    role_prompt = f"{conf_prompt}\n\n{bio}" if conf_prompt else bio
    # Resolve the correct port for this agent's model (dual-server routing)
    from fos.experiment.clients import MODEL_PORT_MAP

    _model = agent.get("voting_model", "openai/gpt-oss-20b")
    _port = MODEL_PORT_MAP.get(_model, 8080)
    return {
        "name": agent["agent_id"],
        "properties": {
            "archetype_age": archetype.get("age", ""),
            "archetype_political": archetype.get("political", ""),
            "archetype_sector": archetype.get("sector", ""),
            "Openness": big_five.get("o", 50),
            "Conscientiousness": big_five.get("c", 50),
            "Extraversion": big_five.get("e", 50),
            "Agreeableness": big_five.get("a", 50),
            "Neuroticism": big_five.get("n", 50),
        },
        "role_prompt": role_prompt,
        "llm_config": {
            "dialect": "openai",
            "model": _model,
            "base_url": f"http://localhost:{_port}/v1",
            "api_key": "not-needed",
            "temperature": 0.7,
        },
        "provider_id": provider_id,
    }


def _build_council_scene(
    run_agents: list[dict[str, Any]],
    proposal_statement: str,
    network_dict: dict[str, Any],
    confederates: list[Any] | None = None,
) -> Any:
    """Build the FOS council scene for a run (mirrors scripts/headless_council.py)."""
    from fos.core.experiment.config import ExperimentConfig
    from fos.core.experiment.scenes.council_experiment import CouncilExperimentScene

    fos_agents = [
        _fos_agent_config(
            agent,
            agent.get("confederate_prompt"),
            provider_id=agent.get("provider_id", ""),
        )
        for agent in run_agents
    ]
    return CouncilExperimentScene(
        ExperimentConfig(
            scenario_id="council_chamber",
            agents=fos_agents,
            actions=[],
            parameters={
                "proposal_text": proposal_statement,
                "deliberation_rounds": DELIBERATION_ROUNDS,
                "voting_threshold": 0.5,
                "confederates": [
                    {
                        "agent_id": s.agent_id,
                        "stance": s.stance,
                        "speech_mode": s.speech_mode,
                    }
                    for s in (confederates or [])
                ],
            },
            description=proposal_statement,
            social_network=network_dict,
            locale="en",
        )
    )


def _build_tree(
    placement: dict[str, Any],
    proposal_statement: str,
    clients: dict[str, Any],
) -> tuple[Any, int]:
    """Create the SimTree, branch with the relabeled network, return (tree, branch_id)."""
    from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
    from fos.core.simtree import SimTree

    scene = _build_council_scene(
        placement["run_agents"],
        proposal_statement,
        {"edges": []},
        confederates=placement.get("confederates") or [],
    )
    adapter = ExperimentRunnerAdapter(scene, clients)
    tree = SimTree.new(adapter, adapter.clients)
    root_id = tree.root
    if root_id is None:
        raise RuntimeError(T("error.scene_builder.simtree_root_none"))
    branch_id = tree.branch(
        root_id,
        [{"op": "network_replace", "network": {"edges": placement["relabeled_edges"]}}],
    )
    return tree, branch_id


def _deserialize_tree(data: dict[str, Any], clients: dict[str, Any]) -> Any:
    """Rebuild a SimTree from a checkpoint payload."""
    from fos.core.simtree import SimTree

    return SimTree.deserialize(data, clients)


def derive_placement(
    matrix: dict[str, str],
    config: dict[str, Any],
    agents: list[dict[str, Any]],
    proposal_statement: str,
    edges: list[list[str]],
    n_yes: int = 3,
    n_no: int = 3,
) -> dict[str, Any]:
    """Compute the deterministic placement for a run.

    Placement uses branch 0 of the placement seed; confederate assignment
    uses branch 1, so the two randomisations never overlap. Seeds come from
    sha256 (never hash()) so they are identical across processes regardless
    of PYTHONHASHSEED. Returns the permuted node assignment, the relabeled
    edges, the confederate specs, and deep copies of the agent configs with
    confederate prompts injected on the copy.
    """
    import random

    from fos.experiment.results import network_label

    agent_names = [agent["agent_id"] for agent in agents]
    base = int(matrix["placement_seed"])
    label = network_label(config)
    proposal_id = matrix["proposal_id"]
    placement_seed = conf.derive_placement_seed(base, proposal_id, label, 0)
    confederate_seed = conf.derive_placement_seed(base, proposal_id, label, 1)
    placement_rng = random.Random(placement_seed)
    confederate_rng = random.Random(confederate_seed)

    permuted = conf.permute_node_assignment(agent_names, placement_rng)
    conf_specs = conf.assign_confederates(
        agent_names,
        n_yes=n_yes,
        n_no=n_no,
        rng=confederate_rng,
        speech_mode="llm",
    )
    lookup = conf.build_confederate_lookup(conf_specs)
    relabeled_edges = conf.relabel_edges(edges, network.AGENT_NAMES, permuted)

    run_agents: list[dict[str, Any]] = []
    for agent in agents:
        run_agent = copy.deepcopy(agent)
        spec = lookup.get(agent["agent_id"])
        run_agent["confederate_prompt"] = (
            conf.confederate_system_prompt(spec, proposal_statement) if spec is not None else None
        )
        run_agent["confederate_stance"] = spec.stance if spec is not None else ""
        run_agents.append(run_agent)

    return {
        "agent_names": agent_names,
        "permuted": permuted,
        "confederates": conf_specs,
        "placement_seed": placement_seed,
        "run_agents": run_agents,
        "relabeled_edges": relabeled_edges,
    }


def placement_to_json(placement: dict[str, Any]) -> dict[str, Any]:
    """Convert a placement dict into a JSON-safe dict (specs -> plain dicts)."""
    return {
        "agent_names": placement["agent_names"],
        "permuted": placement["permuted"],
        "confederates": [
            {"agent_id": s.agent_id, "stance": s.stance, "speech_mode": s.speech_mode}
            for s in placement["confederates"]
        ],
        "placement_seed": placement["placement_seed"],
        "run_agents": placement["run_agents"],
        "relabeled_edges": placement["relabeled_edges"],
    }


def placement_from_json(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON-safe placement dict back into a placement dict."""
    return {
        "agent_names": payload["agent_names"],
        "permuted": payload["permuted"],
        "confederates": [
            conf.ConfederateSpec(s["agent_id"], s["stance"], s["speech_mode"])
            for s in payload["confederates"]
        ],
        "placement_seed": payload["placement_seed"],
        "run_agents": payload["run_agents"],
        "relabeled_edges": payload["relabeled_edges"],
    }
