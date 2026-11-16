"""
This file checks the network configuration grid and the Phase-3 networks.

It makes sure the mean degree of a generated network stays the same no
matter how often triadic closure is used, and it checks both copies of the
generator (the plain runner and the preloaded runner) behave the same way.
It also checks the 18 configurations in network_configs.json form a complete
3x2 factorial grid per generator, that every one of the 126 measured network
instances is connected, that realised mean degrees sit near their targets,
and that global clustering moves monotonically with the primary dial.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from headless_council import _build_holme_kim_edges as build_holme_kim  # noqa: E402
from headless_council_preloaded import _build_holme_kim_edges as build_holme_kim_preloaded  # noqa: E402

_CONFIGS_FILE = _REPO_ROOT / "data" / "configs" / "network_configs.json"
_STATS_FILE = _REPO_ROOT / "data" / "networks" / "network_stats.csv"

_AGENT_NAMES = [f"agent_{index}" for index in range(100)]


def _mean_degree(edges: list[list[str]], n: int) -> float:
    """Mean degree of a network: twice the edge count divided by node count."""
    return 2.0 * len(edges) / n


@pytest.mark.parametrize(
    "build_edges",
    [build_holme_kim, build_holme_kim_preloaded],
    ids=["headless_council", "headless_council_preloaded"],
)
def test_mean_degree_does_not_depend_on_triad_probability(build_edges) -> None:
    """Mean degree must stay about 2*m whether triadic closure is rare or common."""
    degrees_rare: list[float] = []
    degrees_common: list[float] = []
    for seed in range(20):
        edges_rare, _ = build_edges(_AGENT_NAMES, seed=seed, m=3, p_triad=0.2)
        edges_common, _ = build_edges(_AGENT_NAMES, seed=seed, m=3, p_triad=0.8)
        degrees_rare.append(_mean_degree(edges_rare, len(_AGENT_NAMES)))
        degrees_common.append(_mean_degree(edges_common, len(_AGENT_NAMES)))

    mean_rare = sum(degrees_rare) / len(degrees_rare)
    mean_common = sum(degrees_common) / len(degrees_common)
    assert abs(mean_rare - mean_common) < 0.15


@pytest.fixture(scope="module")
def configs() -> list[dict]:
    """The 18 configurations from network_configs.json, sorted by config_id."""
    payload = json.loads(_CONFIGS_FILE.read_text(encoding="utf-8"))
    return sorted(payload["configs"], key=lambda c: c["config_id"])


@pytest.fixture(scope="module")
def stats_rows() -> list[dict]:
    """The 126 measured network rows from network_stats.csv."""
    with _STATS_FILE.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# ── Configuration grid ────────────────────────────────────────────────────────


def test_config_grid_has_18_configs_and_6_per_generator(configs: list[dict]) -> None:
    """There must be 18 configs total and exactly 6 per generator."""
    assert len(configs) == 18
    per_generator = defaultdict(int)
    for config in configs:
        per_generator[config["generator"]] += 1
    assert per_generator == {"watts_strogatz": 6, "holme_kim": 6, "sbm": 6}


def test_config_grid_is_a_complete_3_by_2_factorial_per_generator(configs: list[dict]) -> None:
    """Each generator must cover all 3 primary levels x 2 secondary levels."""
    per_generator: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for config in configs:
        per_generator[config["generator"]].add(
            (config["primary_level"], config["secondary_level"])
        )
    expected = {(level, sl) for level in range(3) for sl in range(2)}
    assert per_generator["watts_strogatz"] == expected
    assert per_generator["holme_kim"] == expected
    assert per_generator["sbm"] == expected


# ── Measured networks ─────────────────────────────────────────────────────────


def test_all_126_network_instances_are_connected(stats_rows: list[dict]) -> None:
    """Every config x proposal instance in network_stats.csv must be connected."""
    assert len(stats_rows) == 126
    assert all(row["is_connected"] == "True" for row in stats_rows)


def _target_mean_degree(config: dict) -> float:
    """The intended mean degree for a config: k for WS, 2m for HK, deg_target for SBM."""
    if config["generator"] == "watts_strogatz":
        return float(config["params"]["k"])
    if config["generator"] == "holme_kim":
        return 2.0 * float(config["params"]["m"])
    return float(config["params"]["deg_target"])


def test_realised_mean_degree_within_05_of_target_for_every_config(
    configs: list[dict], stats_rows: list[dict],
) -> None:
    """Each config's realised mean degree (over its 7 proposals) must be near its target."""
    means_by_config: dict[int, list[float]] = defaultdict(list)
    for row in stats_rows:
        means_by_config[int(row["config_id"])].append(float(row["mean_degree"]))
    for config in configs:
        realised = statistics.mean(means_by_config[config["config_id"]])
        target = _target_mean_degree(config)
        assert abs(realised - target) <= 0.5, (
            f"config {config['config_id']} ({config['generator']}): realised "
            f"mean degree {realised:.3f} is more than 0.5 away from target {target}"
        )


def test_clustering_is_monotonic_in_primary_dial_within_each_generator(
    configs: list[dict], stats_rows: list[dict],
) -> None:
    """Per-level mean clustering must move monotonically with the primary dial.

    Watts-Strogatz clustering falls as the rewiring probability rises; Holme-Kim
    and SBM clustering rise as their primary dials rise.
    """
    level_of: dict[int, tuple[str, int]] = {}
    for config in configs:
        level_of[config["config_id"]] = (config["generator"], config["primary_level"])
    means: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in stats_rows:
        generator, level = level_of[int(row["config_id"])]
        means[(generator, level)].append(float(row["global_clustering"]))
    per_level: dict[tuple[str, int], float] = {
        key: statistics.mean(values) for key, values in means.items()
    }
    expected_direction = {
        "watts_strogatz": -1,  # clustering decreases as rewiring increases
        "holme_kim": 1,
        "sbm": 1,
    }
    for generator, direction in expected_direction.items():
        sequence = [per_level[(generator, level)] for level in range(3)]
        for low, high in zip(sequence, sequence[1:]):
            assert direction * (high - low) > 0, (
                f"{generator} clustering not monotonic in primary dial: {sequence}"
            )

