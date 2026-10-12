"""
Network generation and verification for the checkpointed runner.

Rebuilds a network for a config from data/configs/network_configs.json using
the same generators as scripts/headless_council.py, then verifies it against
the expected statistics in data/networks/network_stats.csv. A mismatch raises
NetworkMismatchError, which aborts the whole batch.

Functions:
    _network_label()        — stable label for a config (e.g. holme_kim_p2s1)
    _load_network_config()  — network config dict for a config_id
    _load_expected_stats()  — expected statistics row for a run
    _build_network()        — generate edges with the configured generator
    _gini_degree()          — Gini coefficient of a degree sequence
    _verify_network()       — compare generated edges against expected stats
"""

from __future__ import annotations

import csv
import json
import math
from typing import Any

import networkx as nx

from fos.experiment import store

NETWORK_CONFIGS_PATH = store.NETWORK_CONFIGS_PATH
NETWORK_STATS_PATH = store.REPO_ROOT / "data" / "networks" / "network_stats.csv"
AGENT_NAMES = [f"agent_{i}" for i in range(100)]


class NetworkMismatchError(RuntimeError):
    """Raised when a regenerated network does not match the expected statistics."""


def _network_label(config: dict[str, Any]) -> str:
    """Stable label for a config, e.g. holme_kim_p2s1."""
    return (
        f"{config['generator']}_p{config['primary_level']}s{config['secondary_level']}"
    )


def _load_network_config(config_id: int) -> dict[str, Any]:
    """Return the network config dict for a config_id."""
    payload = json.loads(NETWORK_CONFIGS_PATH.read_text(encoding="utf-8"))
    for config in payload["configs"]:
        if int(config["config_id"]) == config_id:
            return config
    raise NetworkMismatchError(f"no network config for config_id {config_id}")


def _load_expected_stats(
    config_id: int, proposal_id: str, network_seed: int
) -> dict[str, str]:
    """Return the expected network statistics row for a run."""
    with NETWORK_STATS_PATH.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                int(row["config_id"]) == config_id
                and row["proposal_id"] == proposal_id
                and int(row["seed"]) == network_seed
            ):
                return row
    raise NetworkMismatchError(
        f"no stats row for config {config_id} proposal {proposal_id} seed {network_seed}"
    )


def _build_network(config: dict[str, Any], network_seed: int) -> list[list[str]]:
    """Generate the network edges for a config using its configured generator."""
    from scripts.headless_council import (
        _build_holme_kim_edges,
        _build_sbm_edges,
        _build_watts_strogatz_edges,
    )

    generator = config["generator"]
    params = config["params"]
    if generator == "watts_strogatz":
        edges, _ = _build_watts_strogatz_edges(
            AGENT_NAMES, network_seed, k=params["k"], p=params["p"]
        )
    elif generator == "holme_kim":
        edges, _ = _build_holme_kim_edges(
            AGENT_NAMES, network_seed, m=params["m"], p_triad=params["p_triad"]
        )
    elif generator == "sbm":
        edges, _ = _build_sbm_edges(
            AGENT_NAMES,
            network_seed,
            n_blocks=params["n_blocks"],
            block_sizes=params["block_sizes"],
            p_in=params["p_in"],
            p_out=params["p_out"],
        )
    else:
        raise NetworkMismatchError(f"unknown generator {generator!r}")
    return edges


def _gini_degree(degrees: list[int]) -> float:
    """Gini coefficient of a degree sequence (0 = equal, 1 = most unequal)."""
    sorted_degrees = sorted(degrees)
    n = len(sorted_degrees)
    total = sum(sorted_degrees)
    if n == 0 or total == 0:
        return 0.0
    numerator = 2 * sum((i + 1) * d for i, d in enumerate(sorted_degrees))
    return numerator / (n * total) - (n + 1) / n


def _verify_network(edges: list[list[str]], expected: dict[str, str]) -> dict[str, Any]:
    """Compute the network statistics and compare them against the expected ones.

    Raises NetworkMismatchError when any statistic differs beyond the float
    tolerance or when connectivity differs.
    """
    graph = nx.Graph()
    graph.add_nodes_from(AGENT_NAMES)
    graph.add_edges_from(edges)
    degrees = [degree for _, degree in graph.degree()]
    actual = {
        "n_edges": graph.number_of_edges(),
        "mean_degree": sum(degrees) / len(degrees),
        "degree_gini": _gini_degree(degrees),
        "mean_local_clustering": nx.average_clustering(graph),
        "is_connected": nx.is_connected(graph),
    }
    checks = (
        ("n_edges", actual["n_edges"], float(expected["n_edges"]), 1e-9),
        ("mean_degree", actual["mean_degree"], float(expected["mean_degree"]), 1e-9),
        ("degree_gini", actual["degree_gini"], float(expected["degree_gini"]), 1e-6),
        (
            "mean_local_clustering",
            actual["mean_local_clustering"],
            float(expected["global_clustering"]),
            1e-6,
        ),
    )
    for name, got, want, tol in checks:
        if not math.isclose(got, want, rel_tol=tol):
            raise NetworkMismatchError(
                f"{name}: got {got}, expected {want} (rel_tol {tol})"
            )
    connected = str(expected["is_connected"]).lower() == "true"
    if actual["is_connected"] != connected:
        raise NetworkMismatchError(
            f"is_connected: got {actual['is_connected']}, expected {expected['is_connected']}"
        )
    return actual
