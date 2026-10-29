"""
This file runs a realistic council pilot with local Ollama models.

default_proposals gives the three proposal texts, build_network_variants makes
three network shapes, and build_mixed_model_agents creates and assigns agents.
run_full_council_pilot runs every combination, combine_branch_csv_exports joins
the results, and main lets people run the pilot from the command line.
"""

from __future__ import annotations

import csv
import io
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fos.backend.services.export_service import export_events
from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scenes.council_experiment import CouncilExperimentScene
from fos.core.llm.client import LLMClient
from fos.core.llm.generation import generate_agents_with_archetypes
from fos.core.llm_config import LLMConfig
from fos.core.simtree import SimTree
from fos.i18n import T


DEFAULT_COUNCIL_MODELS = [
    "ministral-3:3b",
    "granite4:3b",
    "phi4-mini:latest",
    "qwen3:4b-instruct-2507-q4_K_M",
]
DEFAULT_DEMOGRAPHICS = [
    {"name": "Age", "categories": ["18-29", "30-49", "50+"]},
    {"name": "Political View", "categories": ["progressive", "moderate"]},
    {"name": "Work Sector", "categories": ["public service", "private sector"]},
]
DEFAULT_TRAITS = [
    {"name": "Trust", "mean": 58, "std": 14},
    {"name": "Empathy", "mean": 64, "std": 12},
    {"name": "Openness", "mean": 61, "std": 11},
    {"name": "RiskTolerance", "mean": 54, "std": 13},
]


@dataclass(frozen=True)
class ProposalSpec:
    """Keep one proposal label and text together."""

    key: str
    label: str
    text: str


@dataclass(frozen=True)
class NetworkVariant:
    """Store one named network for a branch."""

    label: str
    network: dict[str, list[list[str]]]


@dataclass(frozen=True)
class BranchCsvExport:
    """Store one exported branch CSV with its labels."""

    proposal_key: str
    proposal_label: str
    network_label: str
    csv_text: str


def default_proposals() -> list[ProposalSpec]:
    """Return the three proposal texts from the experiment spec."""
    return [
        ProposalSpec(
            key="proposal_a",
            label="Proposal A - Solar geoengineering",
            text=(
                "Should the international community authorise the large-scale "
                "deployment of solar geoengineering (stratospheric aerosol "
                "injection) to reduce global temperatures, accepting the "
                "associated scientific uncertainties and governance risks?"
            ),
        ),
        ProposalSpec(
            key="proposal_b",
            label="Proposal B - Global wealth tax",
            text=(
                "Should a coordinated global wealth tax be levied on the "
                "world's largest fortunes, with the revenue redistributed to "
                "lower-income populations and climate adaptation programmes?"
            ),
        ),
        ProposalSpec(
            key="proposal_c",
            label="Proposal C - Lethal autonomous weapons (LAWS)",
            text=(
                "Should the development and deployment of lethal autonomous "
                "weapons systems - weapons that can select and engage targets "
                "without direct human control - be permitted under "
                "international law?"
            ),
        ),
    ]


def _write_text(path: Path, text: str) -> None:
    """Write text without Windows adding extra blank CSV rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        file_obj.write(text)


def _make_edge(left: str, right: str) -> tuple[str, str]:
    """Store an undirected edge in a stable sorted shape."""
    return tuple(sorted((left, right)))


def _json_get(base_url: str, route: str) -> dict[str, Any]:
    """Read one JSON response from Ollama."""
    request = Request(
        base_url.rstrip("/") + route, headers={"Accept": "application/json"}
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_ollama_models_available(base_url: str, model_names: list[str]) -> None:
    """Raise a clear error when a requested local model is missing."""
    try:
        payload = _json_get(base_url, "/api/tags")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            T("api.errors.ollama_unreachable", base_url=base_url, detail=str(exc))
        ) from exc

    installed = {str(model["name"]) for model in payload.get("models", [])}
    missing = [name for name in model_names if name not in installed]
    if missing:
        raise RuntimeError(
            T("api.errors.ollama_models_missing", models=", ".join(missing))
        )


def make_ollama_client(model_name: str, base_url: str, temperature: float) -> LLMClient:
    """Build one local Ollama client for a named model."""
    return LLMClient(
        LLMConfig(
            dialect="ollama",
            model=model_name,
            base_url=base_url,
            temperature=temperature,
            max_tokens=256,
        )
    )


def _build_small_world_edges(agent_names: list[str], seed: int) -> list[list[str]]:
    """Make a ring with a few random shortcut links."""
    rng = random.Random(seed)
    edges: set[tuple[str, str]] = set()
    count = len(agent_names)
    for index, name in enumerate(agent_names):
        for step in (1, 2):
            neighbor = agent_names[(index + step) % count]
            edges.add(_make_edge(name, neighbor))
    for _ in range(max(1, count // 2)):
        left, right = rng.sample(agent_names, 2)
        edges.add(_make_edge(left, right))
    return [list(edge) for edge in sorted(edges)]


def _pick_weighted_name(
    rng: random.Random,
    agent_names: list[str],
    degree_map: dict[str, int],
    blocked: set[str],
) -> str:
    """Pick one name with a mild preference for already popular nodes."""
    choices = [name for name in agent_names if name not in blocked]
    weights = [degree_map.get(name, 0) + 1 for name in choices]
    return rng.choices(choices, weights=weights, k=1)[0]


def _build_holme_kim_edges(agent_names: list[str], seed: int) -> list[list[str]]:
    """Make a scale-free graph with a few triangle-closing links."""
    rng = random.Random(seed)
    edges: set[tuple[str, str]] = {
        _make_edge(agent_names[0], agent_names[1]),
        _make_edge(agent_names[1], agent_names[2]),
        _make_edge(agent_names[0], agent_names[2]),
    }
    degree_map = {name: 0 for name in agent_names}
    for left, right in edges:
        degree_map[left] += 1
        degree_map[right] += 1

    for index in range(3, len(agent_names)):
        new_name = agent_names[index]
        chosen: set[str] = set()
        while len(chosen) < 2:
            chosen.add(
                _pick_weighted_name(rng, agent_names[:index], degree_map, chosen)
            )
        chosen_names = list(chosen)
        for chosen_name in chosen_names:
            edge = _make_edge(new_name, chosen_name)
            edges.add(edge)
            degree_map[new_name] += 1
            degree_map[chosen_name] += 1
        if rng.random() < 0.35:
            friend = chosen_names[0]
            others = [
                name
                for name in agent_names[:index]
                if name not in {friend, chosen_names[1]}
            ]
            if others:
                triangle_name = rng.choice(others)
                edge = _make_edge(friend, triangle_name)
                if edge not in edges:
                    edges.add(edge)
                    degree_map[friend] += 1
                    degree_map[triangle_name] += 1
    return [list(edge) for edge in sorted(edges)]


def _build_sbm_edges(agent_names: list[str], seed: int) -> list[list[str]]:
    """Make two dense communities with lighter cross-block links."""
    rng = random.Random(seed)
    midpoint = len(agent_names) // 2
    left_block = agent_names[:midpoint]
    right_block = agent_names[midpoint:]
    edges: set[tuple[str, str]] = set()

    def add_block_edges(block: list[str], probability: float) -> None:
        for left_index, left_name in enumerate(block):
            for right_name in block[left_index + 1 :]:
                if rng.random() <= probability:
                    edges.add(_make_edge(left_name, right_name))

    add_block_edges(left_block, 0.75)
    add_block_edges(right_block, 0.75)
    for left_name in left_block:
        for right_name in right_block:
            if rng.random() <= 0.08:
                edges.add(_make_edge(left_name, right_name))

    if left_block and right_block:
        edges.add(_make_edge(left_block[0], right_block[0]))
    return [list(edge) for edge in sorted(edges)]


def build_network_variants(agent_names: list[str], seed: int) -> list[NetworkVariant]:
    """Build the three network variants used in the pilot."""
    return [
        NetworkVariant(
            "small_world", {"edges": _build_small_world_edges(agent_names, seed)}
        ),
        NetworkVariant(
            "holme_kim", {"edges": _build_holme_kim_edges(agent_names, seed + 1)}
        ),
        NetworkVariant("sbm", {"edges": _build_sbm_edges(agent_names, seed + 2)}),
    ]


def _generated_agent_to_config(agent: dict[str, Any]) -> dict[str, Any]:
    """Turn one generated agent into scene config data."""
    return {
        "name": str(agent["name"]),
        "role_prompt": str(agent.get("profile") or ""),
        "properties": dict(agent.get("properties") or {}),
    }


def build_mixed_model_agents(
    generator_client: LLMClient,
    model_names: list[str],
    base_url: str,
    temperature: float,
    total_agents: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Generate demographic agents and spread the requested models across them."""
    random_state = random.getstate()
    random.seed(seed)
    try:
        generated = generate_agents_with_archetypes(
            total_agents=total_agents,
            demographics=DEFAULT_DEMOGRAPHICS,
            archetype_probabilities={},
            traits=DEFAULT_TRAITS,
            llm_client=generator_client,
            language="en",
            timeout=120,
        )
    finally:
        random.setstate(random_state)

    assigned_agents: list[dict[str, Any]] = []
    for index, agent in enumerate(generated):
        config_agent = _generated_agent_to_config(agent)
        model_name = model_names[index % len(model_names)]
        config_agent["provider_id"] = f"provider_{index % len(model_names)}"
        config_agent["llm_config"] = {
            "dialect": "ollama",
            "model": model_name,
            "base_url": base_url,
            "temperature": temperature,
            "max_tokens": 500,
        }
        assigned_agents.append(config_agent)
    return assigned_agents


def _build_council_scene(
    agents: list[dict[str, Any]],
    proposal: ProposalSpec,
    network: dict[str, list[list[str]]],
) -> CouncilExperimentScene:
    """Build one council scene from the generated agents and branch network."""
    return CouncilExperimentScene(
        ExperimentConfig(
            scenario_id="council_chamber",
            agents=agents,
            actions=[],
            parameters={
                "proposal_text": proposal.text,
                "deliberation_rounds": 3,
                "voting_threshold": 0.5,
            },
            description=proposal.label,
            social_network=network,
            locale="en",
        )
    )


def _node_logs_to_export_events(
    node_id: int, node_logs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert branch node logs into the export service event shape."""
    events: list[dict[str, Any]] = []
    for sequence, log in enumerate(node_logs):
        log_data = dict(log.get("data") or {})
        events.append(
            {
                "sequence": sequence,
                "tree_node_id": node_id,
                "event_type": log.get("type"),
                "payload": log_data,
                "created_at": log.get("timestamp") or log_data.get("created_at") or "",
            }
        )
    return events


def combine_branch_csv_exports(exports: list[BranchCsvExport]) -> str:
    """Stack many branch CSV files into one CSV with branch labels."""
    combined_rows: list[dict[str, str]] = []
    base_fieldnames: list[str] = []
    for export_item in exports:
        reader = csv.DictReader(io.StringIO(export_item.csv_text))
        if reader.fieldnames and not base_fieldnames:
            base_fieldnames = list(reader.fieldnames)
        for row in reader:
            combined_rows.append(
                {
                    "proposal_key": export_item.proposal_key,
                    "proposal_label": export_item.proposal_label,
                    "network_label": export_item.network_label,
                    **{key: str(value or "") for key, value in row.items()},
                }
            )

    fieldnames = ["proposal_key", "proposal_label", "network_label", *base_fieldnames]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(combined_rows)
    return output.getvalue()


def run_full_council_pilot(
    output_dir: Path,
    model_names: list[str] | None = None,
    total_agents: int = 12,
    seed: int = 7,
    temperature: float = 0.7,
    base_url: str = "http://localhost:11434",
) -> dict[str, Any]:
    """Run all three proposals against all three network variants."""
    selected_models = model_names or DEFAULT_COUNCIL_MODELS
    ensure_ollama_models_available(base_url, selected_models)

    generator_client = make_ollama_client(selected_models[0], base_url, temperature)
    agents = build_mixed_model_agents(
        generator_client=generator_client,
        model_names=selected_models,
        base_url=base_url,
        temperature=temperature,
        total_agents=total_agents,
        seed=seed,
    )
    agent_names = [str(agent["name"]) for agent in agents]
    networks = build_network_variants(agent_names, seed)

    combined_exports: list[BranchCsvExport] = []
    summary: dict[str, Any] = {
        "seed": seed,
        "temperature": temperature,
        "agent_count": total_agents,
        "models": selected_models,
        "agents": agents,
        "runs": [],
    }

    for proposal in default_proposals():
        scene = _build_council_scene(agents, proposal, {"edges": []})
        adapter = ExperimentRunnerAdapter(
            scene, {"chat": generator_client, "default": generator_client}
        )
        tree = SimTree.new(adapter, adapter.clients)
        root_id = tree.root
        if root_id is None:
            raise RuntimeError(T("api.errors.simtree_root_missing"))

        for network in networks:
            branch_id = tree.branch(
                root_id, [{"op": "network_replace", "network": network.network}]
            )
            finished_id = tree.advance(branch_id, turns=4)
            node = tree.nodes[finished_id]
            node_logs = list(node.get("logs") or [])
            scenario_params = {
                "scenario_id": "council_chamber",
                "proposal_text": proposal.text,
                "deliberation_rounds": 3,
                "voting_threshold": 0.5,
            }
            csv_text = export_events(
                _node_logs_to_export_events(finished_id, node_logs),
                scenario_params,
                "csv",
            )
            branch_export = BranchCsvExport(
                proposal_key=proposal.key,
                proposal_label=proposal.label,
                network_label=network.label,
                csv_text=csv_text,
            )
            combined_exports.append(branch_export)
            summary["runs"].append(
                {
                    "proposal_key": proposal.key,
                    "proposal_label": proposal.label,
                    "network_label": network.label,
                    "node_id": finished_id,
                    "log_count": len(node_logs),
                }
            )

    combined_csv = combine_branch_csv_exports(combined_exports)
    _write_text(output_dir / "combined_results.csv", combined_csv)
    _write_text(output_dir / "summary.json", json.dumps(summary, indent=2))
    return summary


def main() -> None:
    """Run the full council pilot from the command line."""
    from fos.experiments.council_pilot_cli import run_council_pilot_cli

    run_council_pilot_cli()


if __name__ == "__main__":
    main()
