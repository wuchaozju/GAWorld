"""
This file checks the Phase-3 run matrix (data/configs/run_matrix.csv).

The run matrix assigns each of the 126 runs (18 network configurations times
7 proposals) to one of the six populations. The tests re-derive the Morgan-
Rubin balance criteria 1-5 straight from the CSV, so they check the final
artifact rather than the code that produced it. Criterion 6 (statistic
means) is documented in data/configs/balance_table.md and assignment_meta.json
rather than re-checked here.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from fos.proposals import PROPOSAL_IDS  # noqa: E402

RUN_MATRIX = _REPO_ROOT / "data" / "configs" / "run_matrix.csv"
CONFIGS_FILE = _REPO_ROOT / "data" / "configs" / "network_configs.json"

POPULATION_IDS = ("pop_a1", "pop_a2", "pop_b1", "pop_b2", "pop_c1", "pop_c2")
GENERATOR_INDEX = {"watts_strogatz": 0, "holme_kim": 1, "sbm": 2}
MODEL_INDEX = {"deepseek-v4-flash": 0, "glm-5.2": 1, "gpt-oss-20b": 2}
NUM_RUNS = 18 * 7  # 126


@pytest.fixture(scope="module")
def run_matrix() -> list[dict[str, str]]:
    """The rows of data/configs/run_matrix.csv."""
    with RUN_MATRIX.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def config_levels() -> dict[int, tuple[int, int]]:
    """Map each config_id to (generator_index, primary_level, secondary_level)."""
    payload = json.loads(CONFIGS_FILE.read_text(encoding="utf-8"))
    levels = {}
    for config in payload["configs"]:
        levels[int(config["config_id"])] = (
            GENERATOR_INDEX[config["generator"]],
            config["primary_level"],
            config["secondary_level"],
        )
    return levels


# ── Basic shape ───────────────────────────────────────────────────────────────


def test_run_matrix_has_126_rows_and_unique_run_ids(run_matrix: list[dict[str, str]]) -> None:
    """There must be 126 runs and each run_id must be unique."""
    assert len(run_matrix) == NUM_RUNS
    run_ids = [row["run_id"] for row in run_matrix]
    assert len(set(run_ids)) == NUM_RUNS
    assert sorted(run_ids) == [f"run_{i:03d}" for i in range(NUM_RUNS)]


def test_each_population_has_exactly_21_runs(run_matrix: list[dict[str, str]]) -> None:
    """Six populations of 21 runs each must add up to all 126 runs."""
    counts = Counter(row["population_id"] for row in run_matrix)
    assert set(counts) == set(POPULATION_IDS)
    assert all(count == 21 for count in counts.values())


def test_each_proposal_has_exactly_18_runs(run_matrix: list[dict[str, str]]) -> None:
    """Every proposal must appear once per configuration, 18 times total."""
    counts = Counter(row["proposal_id"] for row in run_matrix)
    assert set(counts) == set(PROPOSAL_IDS)
    assert all(count == 18 for count in counts.values())


def test_each_config_has_exactly_7_runs(run_matrix: list[dict[str, str]]) -> None:
    """Every configuration must be run once per proposal, 7 times total."""
    counts = Counter(int(row["config_id"]) for row in run_matrix)
    assert set(counts) == set(range(18))
    assert all(count == 7 for count in counts.values())


def test_execution_order_is_a_permutation_of_0_to_125(run_matrix: list[dict[str, str]]) -> None:
    """The execution_order column must hold every number from 0 to 125 once."""
    orders = sorted(int(row["execution_order"]) for row in run_matrix)
    assert orders == list(range(NUM_RUNS))


def test_every_config_id_exists_in_network_configs(run_matrix: list[dict[str, str]]) -> None:
    """Each run must reference a configuration that exists in network_configs.json."""
    payload = json.loads(CONFIGS_FILE.read_text(encoding="utf-8"))
    valid_ids = {int(config["config_id"]) for config in payload["configs"]}
    used_ids = {int(row["config_id"]) for row in run_matrix}
    assert used_ids <= valid_ids


def test_every_proposal_id_is_in_proposal_ids(run_matrix: list[dict[str, str]]) -> None:
    """Each run must reference one of the canonical proposal ids."""
    used = {row["proposal_id"] for row in run_matrix}
    assert used <= set(PROPOSAL_IDS)


# ── Morgan-Rubin balance criteria 1-5, re-derived from the CSV ───────────────


def test_population_appears_7_plus_or_minus_1_times_per_generator(
    run_matrix: list[dict[str, str]], config_levels: dict[int, tuple[int, int]],
) -> None:
    """Criterion 1: each population 7 +/- 1 times with each generator."""
    counts = Counter(
        (row["population_id"], config_levels[int(row["config_id"])][0])
        for row in run_matrix
    )
    assert all(6 <= count <= 8 for count in counts.values())


def test_population_appears_7_plus_or_minus_1_times_per_primary_level(
    run_matrix: list[dict[str, str]], config_levels: dict[int, tuple[int, int]],
) -> None:
    """Criterion 2: each population 7 +/- 1 times at each primary level."""
    counts = Counter(
        (row["population_id"], config_levels[int(row["config_id"])][1])
        for row in run_matrix
    )
    assert all(6 <= count <= 8 for count in counts.values())


def test_population_appears_10_or_11_times_per_secondary_level(
    run_matrix: list[dict[str, str]], config_levels: dict[int, tuple[int, int]],
) -> None:
    """Criterion 3: each population 10 or 11 times at each secondary level."""
    counts = Counter(
        (row["population_id"], config_levels[int(row["config_id"])][2])
        for row in run_matrix
    )
    assert all(count in (10, 11) for count in counts.values())


def test_no_empty_population_generator_primary_level_cell(
    run_matrix: list[dict[str, str]], config_levels: dict[int, tuple[int, int]],
) -> None:
    """Criterion 4: all 54 population x (generator x primary level) cells >= 1."""
    counts = Counter(
        (row["population_id"],
         config_levels[int(row["config_id"])][0],
         config_levels[int(row["config_id"])][1])
        for row in run_matrix
    )
    assert len(counts) == 54
    assert all(count >= 1 for count in counts.values())


def test_generating_model_appears_14_plus_or_minus_1_times_per_generator(
    run_matrix: list[dict[str, str]], config_levels: dict[int, tuple[int, int]],
) -> None:
    """Criterion 5: each generating model 14 +/- 1 times per generator."""
    counts = Counter(
        (MODEL_INDEX[row["generating_model"]], config_levels[int(row["config_id"])][0])
        for row in run_matrix
    )
    assert all(13 <= count <= 15 for count in counts.values())


def test_generating_model_appears_14_plus_or_minus_1_times_per_primary_level(
    run_matrix: list[dict[str, str]], config_levels: dict[int, tuple[int, int]],
) -> None:
    """Criterion 5: each generating model 14 +/- 1 times per primary level."""
    counts = Counter(
        (MODEL_INDEX[row["generating_model"]], config_levels[int(row["config_id"])][1])
        for row in run_matrix
    )
    assert all(13 <= count <= 15 for count in counts.values())
