#!/usr/bin/env python3
"""
Build the Phase-3 run matrix: assign the six populations to the 126 runs.

This script does three things:
1. Finds a balanced population assignment (the search itself lives in
   scripts/run_matrix_search.py). Each of the 126 runs (18 network
   configurations x 7 proposals) gets one of the six populations, balanced
   under the Morgan-Rubin criteria: criteria 1-5 are hard, criterion 6
   (population statistic means) is relaxed stepwise from 0.10 SD to 0.20 SD
   of the grand mean as needed.
2. Writes the assignment to data/configs/run_matrix.csv with every column
   the downstream experiment needs (run id, config, proposal, population,
   generating model, network seed, placement seed, execution order).
3. Writes the balance evidence to data/configs/balance_table.md and the
   search metadata to data/configs/assignment_meta.json.

The assignment RNG is seeded with 42 (assignment_seed) and the execution
order RNG with 12345 (execution_order_seed), so the whole pipeline is
reproducible.

Functions:
- load_phase_data: read configs, network stats and populations
- derive_config_vectors: turn configs into generator/level index lists
- build_stat_matrix: index the five statistics by (config, proposal)
- compute_balance_tables: aggregate every count and mean for the evidence
- write_run_matrix_csv: write the 126-row run matrix
- write_balance_table: write the cross-tab balance evidence as Markdown
- write_assignment_meta: write the JSON metadata file
- verify_run_matrix: re-check acceptance facts straight from the CSV
- main: run the whole pipeline
"""

from __future__ import annotations

import csv
import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _root in (str(_REPO_ROOT / "src"), str(_REPO_ROOT / "scripts")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from fos.experiments.confederates import derive_placement_seed  # noqa: E402
from fos.proposals import PROPOSAL_IDS  # noqa: E402
from run_matrix_search import (  # noqa: E402
    N_CONFIG,
    N_POP,
    N_PROP,
    STAT_KEYS,
    search_balanced_assignment,
    setup_search,
)

# ── Paths and fixed parameters ────────────────────────────────────────────────

CONFIGS_PATH = _REPO_ROOT / "data" / "configs" / "network_configs.json"
STATS_PATH = _REPO_ROOT / "data" / "networks" / "network_stats.csv"
OUT_RUN_MATRIX = _REPO_ROOT / "data" / "configs" / "run_matrix.csv"
OUT_BALANCE = _REPO_ROOT / "data" / "configs" / "balance_table.md"
OUT_META = _REPO_ROOT / "data" / "configs" / "assignment_meta.json"

ASSIGNMENT_SEED = 42
EXECUTION_ORDER_SEED = 12345

POPULATION_IDS = ("pop_a1", "pop_a2", "pop_b1", "pop_b2", "pop_c1", "pop_c2")
GENERATING_MODEL = {
    "pop_a1": "deepseek-v4-flash",
    "pop_a2": "deepseek-v4-flash",
    "pop_b1": "glm-5.2",
    "pop_b2": "glm-5.2",
    "pop_c1": "gpt-oss-20b",
    "pop_c2": "gpt-oss-20b",
}


# ── Data loading ──────────────────────────────────────────────────────────────


def load_phase_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read configs and per-network stats.

    Returns:
        (configs, stats_rows): the 18 network configs sorted by config_id and
        the 126 rows of network_stats.csv.
    """
    payload = json.loads(CONFIGS_PATH.read_text(encoding="utf-8"))
    configs = payload["configs"]
    if len(configs) != N_CONFIG:
        raise ValueError(f"Expected {N_CONFIG} configs, got {len(configs)}")
    configs = sorted(configs, key=lambda c: c["config_id"])

    with STATS_PATH.open(encoding="utf-8") as handle:
        stats_rows = list(csv.DictReader(handle))
    if len(stats_rows) != N_CONFIG * N_PROP:
        raise ValueError(f"Expected {N_CONFIG * N_PROP} network stats rows, got {len(stats_rows)}")
    return configs, stats_rows


def derive_config_vectors(configs: list[dict[str, Any]]) -> tuple[list[int], list[int], list[int]]:
    """Turn configs into (generator, primary_level, secondary_level) index lists.

    generator: 0 = watts_strogatz, 1 = holme_kim, 2 = sbm.
    """
    gen_map = {"watts_strogatz": 0, "holme_kim": 1, "sbm": 2}
    cg = [gen_map[c["generator"]] for c in configs]
    cpl = [c["primary_level"] for c in configs]
    csl = [c["secondary_level"] for c in configs]
    return cg, cpl, csl


def build_stat_matrix(stats_rows: list[dict[str, Any]]) -> list[list[list[float]]]:
    """Index the five statistics by (config_id, proposal_index).

    Returns stats[config][proposal][stat]. The proposal index comes from the
    proposal_id column (seeds in the CSV include retry offsets, so they cannot
    be used to recover the proposal index).
    """
    proposal_index = {pid: i for i, pid in enumerate(PROPOSAL_IDS)}
    stats = [[[0.0] * len(STAT_KEYS) for _ in range(N_PROP)] for _ in range(N_CONFIG)]
    for row in stats_rows:
        c = int(row["config_id"])
        p = proposal_index[row["proposal_id"]]
        for s, key in enumerate(STAT_KEYS):
            stats[c][p][s] = float(row[key])
    return stats


# ── Outputs ───────────────────────────────────────────────────────────────────


def compute_balance_tables(assign: list[list[int]]) -> dict[str, Any]:
    """Aggregate every count and mean the balance table needs.

    Args:
        assign: assign[proposal][config] population index, from the search

    Returns:
        Dict with the population/model count matrices and the per-population
        statistic means plus the grand means and SDs.
    """
    configs = json.loads(CONFIGS_PATH.read_text(encoding="utf-8"))["configs"]
    configs = sorted(configs, key=lambda c: c["config_id"])
    cg, cpl, csl = derive_config_vectors(configs)
    stats_rows = list(csv.DictReader(STATS_PATH.open(encoding="utf-8")))
    stats = build_stat_matrix(stats_rows)
    grand_mean = [statistics.mean(stats[c][p][s] for c in range(N_CONFIG)
                                  for p in range(N_PROP)) for s in range(len(STAT_KEYS))]
    grand_sd = [statistics.pstdev(stats[c][p][s] for c in range(N_CONFIG)
                                  for p in range(N_PROP)) for s in range(len(STAT_KEYS))]
    pop_sum = [[0.0] * len(STAT_KEYS) for _ in range(N_POP)]
    counts = {
        "pop_gen": [[0] * 3 for _ in range(N_POP)],
        "pop_pl": [[0] * 3 for _ in range(N_POP)],
        "pop_sl": [[0] * 2 for _ in range(N_POP)],
        "pop_gpl": [[[0] * 3 for _ in range(3)] for _ in range(N_POP)],
        "model_gen": [[0] * 3 for _ in range(3)],
        "model_pl": [[0] * 3 for _ in range(3)],
    }
    for p in range(N_PROP):
        for c in range(N_CONFIG):
            pop = assign[p][c]
            g, pl, sl = cg[c], cpl[c], csl[c]
            counts["pop_gen"][pop][g] += 1
            counts["pop_pl"][pop][pl] += 1
            counts["pop_sl"][pop][sl] += 1
            counts["pop_gpl"][pop][g][pl] += 1
            counts["model_gen"][pop // 2][g] += 1
            counts["model_pl"][pop // 2][pl] += 1
            for s in range(len(STAT_KEYS)):
                pop_sum[pop][s] += stats[c][p][s]
    pop_means = {
        pop: {key: pop_sum[pop][s] / 21 for s, key in enumerate(STAT_KEYS)}
        for pop in range(N_POP)
    }
    return {
        "counts": counts,
        "pop_means": pop_means,
        "grand": {key: grand_mean[s] for s, key in enumerate(STAT_KEYS)},
        "sd": {key: grand_sd[s] for s, key in enumerate(STAT_KEYS)},
    }


def write_run_matrix_csv(assign: list[list[int]], configs: list[dict[str, Any]],
                         stats_rows: list[dict[str, Any]]) -> None:
    """Write the 126-row run matrix sorted by execution order."""
    # network_seed per (config, proposal): read from network_stats.csv
    network_seed = {}
    for row in stats_rows:
        c = int(row["config_id"])
        network_seed[(c, row["proposal_id"])] = int(row["seed"])

    rows: list[dict[str, Any]] = []
    run_index = 0
    for c, config in enumerate(configs):
        generator = config["generator"]
        for p, proposal_id in enumerate(PROPOSAL_IDS):
            pop = assign[p][c]
            pop_id = POPULATION_IDS[pop]
            network_label = f"{generator}_p{config['primary_level']}s{config['secondary_level']}"
            placement_seed = derive_placement_seed(
                ASSIGNMENT_SEED, proposal_key=proposal_id,
                network_label=network_label, branch=0,
            )
            rows.append({
                "run_id": f"run_{run_index:03d}",
                "config_id": c,
                "generator": generator,
                "primary_dial_value": config["primary_dial_value"],
                "primary_level": config["primary_level"],
                "secondary_dial_value": config["secondary_dial_value"],
                "secondary_level": config["secondary_level"],
                "proposal_id": proposal_id,
                "population_id": pop_id,
                "generating_model": GENERATING_MODEL[pop_id],
                "network_seed": network_seed[(c, proposal_id)],
                "placement_seed": placement_seed,
                "execution_order": 0,
            })
            run_index += 1

    order = list(range(len(rows)))
    rng = random.Random(EXECUTION_ORDER_SEED)
    rng.shuffle(order)
    for row, o in zip(rows, order):
        row["execution_order"] = o
    rows.sort(key=lambda r: r["execution_order"])

    columns = [
        "run_id", "config_id", "generator", "primary_dial_value", "primary_level",
        "secondary_dial_value", "secondary_level", "proposal_id", "population_id",
        "generating_model", "network_seed", "placement_seed", "execution_order",
    ]
    OUT_RUN_MATRIX.parent.mkdir(parents=True, exist_ok=True)
    with OUT_RUN_MATRIX.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_balance_table(tables: dict[str, Any]) -> None:
    """Write the cross-tab balance evidence as Markdown."""
    counts = tables["counts"]
    gen_labels = ("watts_strogatz", "holme_kim", "sbm")
    model_labels = ("deepseek-v4-flash", "glm-5.2", "gpt-oss-20b")
    lines: list[str] = []
    add = lines.append

    add("# Phase 3 Run-Matrix Balance Table")
    add("")
    add("Morgan-Rubin balance evidence for the 126-run assignment. Criteria 1-5 are")
    add("hard constraints; criterion 6 (statistic means) holds at the threshold recorded")
    add("in assignment_meta.json.")
    add("")

    def matrix_table(title: str, header: list[str], body: list[list[Any]]) -> None:
        add(f"## {title}")
        add("")
        add("| " + " | ".join(header) + " |")
        add("|" + "|".join(["---"] * len(header)) + "|")
        for row in body:
            add("| " + " | ".join(str(x) for x in row) + " |")
        add("")

    matrix_table("Population x generator (criterion 1, target 7 +/- 1)",
                 [""] + list(gen_labels),
                 [[POPULATION_IDS[i]] + counts["pop_gen"][i] for i in range(N_POP)])
    matrix_table("Population x primary level (criterion 2, target 7 +/- 1)",
                 [""] + ["level 0", "level 1", "level 2"],
                 [[POPULATION_IDS[i]] + counts["pop_pl"][i] for i in range(N_POP)])
    matrix_table("Population x secondary level (criterion 3, target 10 or 11)",
                 [""] + ["level 0", "level 1"],
                 [[POPULATION_IDS[i]] + counts["pop_sl"][i] for i in range(N_POP)])
    gpl_header = [""] + [f"{g} p{pl}" for g in ("WS", "HK", "SBM") for pl in range(3)]
    gpl_body = [
        [POPULATION_IDS[i]] +
        [counts["pop_gpl"][i][g][pl] for g in range(3) for pl in range(3)]
        for i in range(N_POP)
    ]
    matrix_table("Population x (generator x primary level) (criterion 4, all cells >= 1)",
                 gpl_header, gpl_body)
    matrix_table("Generating model x generator (criterion 5, target 14 +/- 1)",
                 [""] + list(gen_labels),
                 [[model_labels[m]] + counts["model_gen"][m] for m in range(3)])
    matrix_table("Generating model x primary level (criterion 5, target 14 +/- 1)",
                 [""] + ["level 0", "level 1", "level 2"],
                 [[model_labels[m]] + counts["model_pl"][m] for m in range(3)])

    add("## Population statistic means vs grand mean (criterion 6)")
    add("")
    add("| population | " + " | ".join(STAT_KEYS) + " |")
    add("|" + "|".join(["---"] * (len(STAT_KEYS) + 1)) + "|")
    for i in range(N_POP):
        add("| " + POPULATION_IDS[i] + " | "
            + " | ".join(f"{tables['pop_means'][i][k]:.4f}" for k in STAT_KEYS) + " |")
    add("| grand mean | "
        + " | ".join(f"{tables['grand'][k]:.4f}" for k in STAT_KEYS) + " |")
    add("| grand SD | "
        + " | ".join(f"{tables['sd'][k]:.4f}" for k in STAT_KEYS) + " |")
    add("")

    OUT_BALANCE.parent.mkdir(parents=True, exist_ok=True)
    OUT_BALANCE.write_text("\n".join(lines), encoding="utf-8")


def write_assignment_meta(threshold: float, attempts: int, generated_at: str) -> None:
    """Write the assignment metadata JSON file."""
    meta = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "assignment_seed": ASSIGNMENT_SEED,
        "execution_order_seed": EXECUTION_ORDER_SEED,
        "attempts": attempts,
        "threshold_used": f"{threshold:.2f} SD",
        "num_runs": N_CONFIG * N_PROP,
        "num_configs": N_CONFIG,
        "num_proposals": N_PROP,
        "num_populations": N_POP,
    }
    OUT_META.parent.mkdir(parents=True, exist_ok=True)
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def verify_run_matrix() -> None:
    """Re-check the acceptance facts directly from the written run_matrix.csv."""
    rows = list(csv.DictReader(OUT_RUN_MATRIX.open(encoding="utf-8")))
    if len(rows) != N_CONFIG * N_PROP:
        raise RuntimeError(f"run matrix has {len(rows)} rows, expected 126")
    if len({r["run_id"] for r in rows}) != len(rows):
        raise RuntimeError("run_id values are not unique")
    if sorted(int(r["execution_order"]) for r in rows) != list(range(len(rows))):
        raise RuntimeError("execution_order is not a permutation of 0..125")
    from collections import Counter
    pop_counts = Counter(r["population_id"] for r in rows)
    if any(v != 21 for v in pop_counts.values()):
        raise RuntimeError(f"population counts wrong: {pop_counts}")
    prop_counts = Counter(r["proposal_id"] for r in rows)
    if any(v != 18 for v in prop_counts.values()):
        raise RuntimeError(f"proposal counts wrong: {prop_counts}")
    cfg_counts = Counter(int(r["config_id"]) for r in rows)
    if any(v != 7 for v in cfg_counts.values()):
        raise RuntimeError(f"config counts wrong: {cfg_counts}")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Generate the run matrix, balance table and metadata, then verify."""
    configs, stats_rows = load_phase_data()
    cg, cpl, csl = derive_config_vectors(configs)
    stats = build_stat_matrix(stats_rows)
    grand_mean = [statistics.mean(stats[c][p][s] for c in range(N_CONFIG)
                                  for p in range(N_PROP)) for s in range(len(STAT_KEYS))]
    grand_sd = [statistics.pstdev(stats[c][p][s] for c in range(N_CONFIG)
                                  for p in range(N_PROP)) for s in range(len(STAT_KEYS))]
    setup_search(stats, cg, cpl, csl, grand_mean, grand_sd)

    print("Searching for a balanced population assignment (seed 42)...", flush=True)
    st, threshold, attempts = search_balanced_assignment()
    assert st.valid(), "Criteria 1-5 must hold"
    max_dev = st.max_dev()
    assert max_dev <= threshold + 1e-9, f"max deviation {max_dev} exceeds {threshold}"
    print(f"Found assignment: threshold {threshold:.2f} SD, max deviation "
          f"{max_dev:.4f} SD, seeds/attempts {attempts}", flush=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    write_run_matrix_csv(st.assign, configs, stats_rows)
    tables = compute_balance_tables(st.assign)
    write_balance_table(tables)
    write_assignment_meta(threshold, attempts, generated_at)

    verify_run_matrix()
    print("All acceptance checks passed. Outputs written to data/configs/")


if __name__ == "__main__":
    main()
