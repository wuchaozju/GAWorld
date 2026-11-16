"""Build and measure the 126 Phase-3 council networks.

Reads the 18 network configurations from data/configs/network_configs.json
and the 7 proposal ids from fos.proposals.PROPOSAL_IDS, builds one network
per config x proposal using the generators in scripts/headless_council.py,
and writes one row per network to data/networks/network_stats.csv. A summary
table of mean clustering, degree Gini, modularity and mean degree per
generator x primary dial level is printed to stdout.

Functions:
    load_configs: read and validate the network configurations.
    build_network: generate the edges for one config x proposal pair,
        retrying with increasing seeds until the graph is connected.
    gini_degree: Gini coefficient of a degree sequence.
    measure_network: compute every network statistic from an edge list.
    write_stats_csv: write all measured networks to the CSV file.
    print_summary: print the per-generator x level means table.
    main: run the whole pipeline and report the acceptance checks.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import networkx as nx

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _root in (str(_REPO_ROOT / "src"), str(_REPO_ROOT / "scripts")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from headless_council import (  # noqa: E402
    _build_holme_kim_edges,
    _build_sbm_edges,
    _build_watts_strogatz_edges,
)
from fos.proposals import PROPOSAL_IDS  # noqa: E402

_CONFIGS_PATH = _REPO_ROOT / "data" / "configs" / "network_configs.json"
_OUTPUT_PATH = _REPO_ROOT / "data" / "networks" / "network_stats.csv"

_N_AGENTS = 100
_MAX_ATTEMPTS = 20

_COLUMNS = [
    "config_id",
    "proposal_id",
    "seed",
    "n_nodes",
    "n_edges",
    "mean_degree",
    "max_degree",
    "min_degree",
    "degree_gini",
    "global_clustering",
    "mean_path_length",
    "modularity",
    "n_components",
    "largest_component_size",
    "is_connected",
    "attempts",
]


def load_configs() -> list[dict[str, Any]]:
    """Read the 18 network configurations from the JSON file."""
    payload = json.loads(_CONFIGS_PATH.read_text(encoding="utf-8"))
    configs = payload["configs"]
    if len(configs) != 18:
        raise ValueError(f"Expected 18 configs, got {len(configs)}")
    return configs


def _generator_for(config: dict[str, Any], agent_names: list[str], seed: int):
    """Pick the generator that matches the config's generator name."""
    generator = config["generator"]
    params = config["params"]
    if generator == "watts_strogatz":
        return _build_watts_strogatz_edges(
            agent_names, seed, k=params["k"], p=params["p"]
        )
    if generator == "holme_kim":
        return _build_holme_kim_edges(
            agent_names, seed, m=params["m"], p_triad=params["p_triad"]
        )
    if generator == "sbm":
        return _build_sbm_edges(
            agent_names,
            seed,
            n_blocks=params["n_blocks"],
            block_sizes=params["block_sizes"],
            p_in=params["p_in"],
            p_out=params["p_out"],
        )
    raise ValueError(f"Unknown generator '{generator}'")


def build_network(
    config: dict[str, Any], agent_names: list[str], base_seed: int
) -> tuple[list[list[str]], int, int]:
    """Generate edges for one config, retrying until the graph is connected.

    Tries base_seed, base_seed+1, ... up to _MAX_ATTEMPTS attempts. Returns
    (edges, final_seed, attempts).
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        seed = base_seed + attempt - 1
        edges, _ = _generator_for(config, agent_names, seed)
        graph = nx.Graph()
        graph.add_nodes_from(agent_names)
        graph.add_edges_from(edges)
        if nx.is_connected(graph):
            return edges, seed, attempt
    raise RuntimeError(
        f"config {config['config_id']} ({config['generator']}) not connected "
        f"after {_MAX_ATTEMPTS} attempts"
    )


def gini_degree(degrees: list[int]) -> float:
    """Gini coefficient of a degree sequence (0 = equal, 1 = most unequal)."""
    sorted_degrees = sorted(degrees)
    n = len(sorted_degrees)
    total = sum(sorted_degrees)
    if n == 0 or total == 0:
        return 0.0
    numerator = 2 * sum((i + 1) * d for i, d in enumerate(sorted_degrees))
    return numerator / (n * total) - (n + 1) / n


def measure_network(
    edges: list[list[str]], agent_names: list[str]
) -> dict[str, float | int | bool]:
    """Compute every network statistic from an edge list."""
    graph = nx.Graph()
    graph.add_nodes_from(agent_names)
    graph.add_edges_from(edges)

    degree_values = [degree for _, degree in graph.degree()]
    components = list(nx.connected_components(graph))
    largest = max(components, key=len)
    largest_graph = graph.subgraph(largest)

    communities = nx.community.greedy_modularity_communities(graph)
    modularity = nx.community.modularity(graph, communities)

    return {
        "n_nodes": graph.number_of_nodes(),
        "n_edges": graph.number_of_edges(),
        "mean_degree": sum(degree_values) / len(degree_values),
        "max_degree": max(degree_values),
        "min_degree": min(degree_values),
        "degree_gini": gini_degree(degree_values),
        "global_clustering": nx.average_clustering(graph),
        "mean_path_length": nx.average_shortest_path_length(largest_graph),
        "modularity": modularity,
        "n_components": len(components),
        "largest_component_size": len(largest),
        "is_connected": nx.is_connected(graph),
    }


def write_stats_csv(rows: list[dict[str, Any]]) -> None:
    """Write every measured network to the CSV file."""
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]], configs: list[dict[str, Any]]) -> None:
    """Print mean clustering, degree Gini, modularity and mean degree per
    generator x primary dial level, averaged over proposals and secondary
    dial settings."""
    level_of: dict[int, tuple[str, int]] = {}
    for config in configs:
        level_of[config["config_id"]] = (
            config["generator"],
            config["primary_level"],
        )
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(level_of[row["config_id"]], []).append(row)

    print(f"{'generator':<14} {'primary_level':<14} {'clustering':>11} "
          f"{'degree_gini':>11} {'modularity':>11} {'mean_degree':>11}")
    for (generator, level), group in sorted(groups.items()):
        count = len(group)
        means = {key: sum(r[key] for r in group) / count for key in
                 ("global_clustering", "degree_gini", "modularity", "mean_degree")}
        print(f"{generator:<14} {level:<14} {means['global_clustering']:>11.4f} "
              f"{means['degree_gini']:>11.4f} {means['modularity']:>11.4f} "
              f"{means['mean_degree']:>11.4f}")


def main() -> None:
    """Build all 126 networks, measure them, save the CSV and print the table."""
    configs = load_configs()
    agent_names = [f"agent_{i}" for i in range(_N_AGENTS)]
    rows: list[dict[str, Any]] = []
    for config in configs:
        for proposal_index, proposal_id in enumerate(PROPOSAL_IDS):
            base_seed = config["config_id"] * 1000 + proposal_index
            edges, final_seed, attempts = build_network(config, agent_names, base_seed)
            stats = measure_network(edges, agent_names)
            rows.append(
                {
                    "config_id": config["config_id"],
                    "proposal_id": proposal_id,
                    "seed": final_seed,
                    **stats,
                    "attempts": attempts,
                }
            )
    write_stats_csv(rows)
    print_summary(rows, configs)

    expected = len(configs) * len(PROPOSAL_IDS)
    connected = sum(1 for row in rows if row["is_connected"])
    print(f"\nWrote {len(rows)} rows to {_OUTPUT_PATH}")
    print(f"Expected {expected} rows, connected {connected}/{expected}")


if __name__ == "__main__":
    main()
