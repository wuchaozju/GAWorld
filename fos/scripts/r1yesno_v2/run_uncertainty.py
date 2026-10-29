# This file runs the full uncertainty analysis for the price study: for every
# model and both main conditions it re-computes the price-slope ratio G on
# 5,000 resampled datasets (whole product-and-persona curves resampled, two
# ways: bundles in-or-out, and bundles randomly weighted), writes the
# interval tables as CSV files, and appends a short numbers-only section to
# the study summary. Run it as:
#   python -m scripts.r1yesno_v2.run_uncertainty --results-root <results dir>
#     --outdir <output dir> [--copy-to <mirror dir>] [--n-draws 5000]

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.r1yesno_v2 import load, uncertainty
from scripts.r1yesno_v2.figures_style import BLINDED, CONDITIONS, UNBLINDED
from scripts.r1yesno_v2.registry import MODELS, verify_registry_paths
from scripts.r1yesno_v2.run_analysis import _records_path
from scripts.r1yesno_v2.uncertainty_report import (
    DELTAS,
    METHODS,
    PARTIAL_MODELS,
    append_summary,
    mirror_outputs,
    summary_section,
)

CLASSICAL_SEED = 42
BAYESIAN_SEED = 43
METRICS = ("beta_human", "beta_model", "G", "delta_G")
G_TOLERANCE = 0.05


def parse_args() -> argparse.Namespace:
    """Read the runner's command-line arguments."""
    parser = argparse.ArgumentParser(description="R1-YESNO V2 uncertainty analysis")
    parser.add_argument(
        "--results-root",
        type=Path,
        required=True,
        help="the results/unblinding directory of the fos repo",
    )
    parser.add_argument(
        "--cells-ref",
        type=Path,
        default=load.PRIMARY_HUMAN_CELLS,
        help="validated human reference cells file",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        required=True,
        help="output directory (csv/ written inside, SUMMARY-V2.md appended)",
    )
    parser.add_argument(
        "--copy-to",
        type=Path,
        default=None,
        help="optional mirror directory to copy outputs into",
    )
    parser.add_argument(
        "--n-draws", type=int, default=5000, help="number of bootstrap draws per method"
    )
    return parser.parse_args()


def load_condition_records(
    results_root: Path, model_id: str, condition: str
) -> pd.DataFrame:
    """Read one model-condition answer file as rows of product/persona/price/p.

    Uses the registry's reader for the model (logprob vs forced choice) and
    its sidecar override when one is registered. Only the primary price
    range (20-200%) is kept, with price scaled to price/100.
    """
    info = MODELS[model_id]
    reader = (
        load.load_logprob_records
        if info["method"] == "logprob_p_yes_binary"
        else load.load_forced_choice_records
    )
    leg_dir = results_root / info["run_dir"] / info["safe_dir"] / condition
    records = reader(_records_path(results_root, model_id, info, condition, leg_dir))
    primary = records.loc[
        records["price"].between(load.PRIMARY_PRICE_MIN, load.PRIMARY_PRICE_MAX)
    ]
    return primary.assign(price_scaled=primary["price"] / 100.0)


def model_clusters(
    records: pd.DataFrame, model_id: str, condition: str
) -> dict[tuple, np.ndarray]:
    """Bundle one model-condition's rows into (product, persona) curves.

    Bundles with fewer than two distinct prices cannot shape a slope and are
    dropped (count reported loudly, never silently).
    """
    clusters = uncertainty.collect_clusters(records)
    kept = {k: v for k, v in clusters.items() if np.unique(v[:, 0]).size >= 2}
    dropped = len(clusters) - len(kept)
    if dropped:
        print(
            f"  {model_id} {condition}: dropped {dropped} clusters with <2 distinct prices"
        )
    if len(kept) < 2:
        raise ValueError(f"{model_id} {condition}: only {len(kept)} usable clusters")
    return kept


def human_price_table(
    human_cells: pd.DataFrame, condition: str
) -> dict[str, np.ndarray]:
    """Collect the human (price_scaled, p) rows per product for one condition."""
    frame = human_cells.loc[
        (human_cells["condition"] == condition)
        & human_cells["price"].between(load.PRIMARY_PRICE_MIN, load.PRIMARY_PRICE_MAX)
    ].sort_values(["product", "price"])
    return {
        product: np.column_stack(
            [
                group["price"].to_numpy(float) / 100.0,
                group["p_human"].to_numpy(float),
            ]
        )
        for product, group in frame.groupby("product", sort=True)
    }


def build_human_clusters(
    model_cluster_keys: list[tuple],
    human_prices: dict[str, np.ndarray],
    model_id: str,
    condition: str,
) -> dict[tuple, np.ndarray]:
    """Give every model bundle a human twin carrying the product's human rows.

    The human has no personas: each (product, persona) bundle's twin holds
    the human price-response rows of the same product, so a resampled
    product-persona contributes the same human curve (with multiplicity).
    Products with fewer than two human price rows are dropped loudly.
    """
    human_clusters: dict[tuple, np.ndarray] = {}
    for key in model_cluster_keys:
        rows = human_prices.get(key[0])
        if rows is None or np.unique(rows[:, 0]).size < 2:
            raise ValueError(
                f"{model_id} {condition}: product {key[0]!r} has fewer than 2 human price rows"
            )
        human_clusters[key] = rows
    return human_clusters


def summarize_draws(draws: np.ndarray, center: float) -> tuple[float, float, float]:
    """Return (center, 2.5th, 97.5th percentile) with NaN draws excluded."""
    return uncertainty.summarize(draws, point_estimate=center)


def full_sample_values(
    model_cl: dict[tuple, np.ndarray],
    human_cl: dict[tuple, np.ndarray],
) -> dict[str, float]:
    """Point estimates from all rows pooled: both slopes, G and G-1."""
    beta_human = uncertainty.full_sample_slope(human_cl)
    if beta_human == 0.0:
        raise ValueError("human price slope is 0 on the full sample; G undefined")
    beta_model = uncertainty.full_sample_slope(model_cl)
    g_full = beta_model / beta_human
    return {
        "beta_human": beta_human,
        "beta_model": beta_model,
        "G": g_full,
        "delta_G": g_full - 1.0,
    }


def bootstrap_rows(
    model_id: str,
    display_name: str,
    condition: str,
    model_cl: dict[tuple, np.ndarray],
    human_cl: dict[tuple, np.ndarray],
    n_draws: int,
    n_observations: int,
) -> list[dict]:
    """Run both bootstrap methods for one model-condition; return table rows."""
    points = full_sample_values(model_cl, human_cl)
    draw_sets = {
        "classical": uncertainty.cluster_bootstrap(
            model_cl, human_cl, n_draws, CLASSICAL_SEED
        ),
        "bayesian": uncertainty.bayesian_bootstrap(
            model_cl, human_cl, n_draws, BAYESIAN_SEED
        ),
    }
    rows = []
    for method, draws in draw_sets.items():
        for metric in METRICS:
            if metric == "delta_G":
                values = np.asarray(draws["G"], dtype=float) - 1.0
            else:
                values = np.asarray(draws[metric], dtype=float)
            center = (
                points[metric] if method == "classical" else float(np.nanmedian(values))
            )
            center, lo, hi = summarize_draws(values, center)
            rows.append(
                {
                    "model_id": model_id,
                    "display_name": display_name,
                    "condition": condition,
                    "metric": metric,
                    "method": method,
                    "center": center,
                    "lo": lo,
                    "hi": hi,
                    "n_clusters": len(model_cl),
                    "n_observations": n_observations,
                }
            )
    return rows


def check_point_estimate(
    model_id: str,
    condition: str,
    g_full: float,
    metrics_csv: pd.DataFrame | None,
) -> float | None:
    """Compare the pooled full-sample G with the published G_lin.

    Full-coverage 400-cell models must agree within 0.05 (asserted); the two
    partial models get their delta recorded and returned instead.
    """
    if metrics_csv is None:
        return None
    hit = metrics_csv.loc[
        (metrics_csv["model_id"] == model_id) & (metrics_csv["condition"] == condition)
    ]
    if hit.empty:
        print(f"  {model_id} {condition}: no metrics row; skipping G_lin comparison")
        return None
    g_lin = float(hit["G_lin"].iloc[0])
    delta = g_full - g_lin
    if model_id in PARTIAL_MODELS:
        print(
            f"  {model_id} {condition}: partial coverage, G_full-G_lin = {delta:+.4f} (recorded)"
        )
        return delta
    if abs(delta) > G_TOLERANCE:
        raise AssertionError(
            f"{model_id} {condition}: full-sample G {g_full:.4f} vs G_lin {g_lin:.4f} "
            f"(delta {delta:+.4f} exceeds {G_TOLERANCE})"
        )
    return delta


def analyze_model_condition(
    results_root: Path,
    model_id: str,
    condition: str,
    human_cells: pd.DataFrame,
    n_draws: int,
    metrics_csv: pd.DataFrame | None,
) -> tuple[list[dict], dict[tuple, np.ndarray], dict[str, float]]:
    """Load, bundle and bootstrap one model-condition end to end.

    Returns the interval rows, the model bundles (reused for the paired
    blinded-vs-unblinded deltas) and the full-sample point estimates.
    """
    display_name = MODELS[model_id]["short_name"]
    records = load_condition_records(results_root, model_id, condition)
    model_cl = model_clusters(records, model_id, condition)
    human_cl = build_human_clusters(
        list(model_cl.keys()),
        human_price_table(human_cells, condition),
        model_id,
        condition,
    )
    points = full_sample_values(model_cl, human_cl)
    check_point_estimate(model_id, condition, points["G"], metrics_csv)
    n_observations = int(sum(cluster.shape[0] for cluster in model_cl.values()))
    print(
        f"  {model_id} {condition}: {len(model_cl)} clusters, {n_observations} observations, "
        f"G={points['G']:.4f}"
    )
    rows = bootstrap_rows(
        model_id,
        display_name,
        condition,
        model_cl,
        human_cl,
        n_draws,
        n_observations,
    )
    return rows, model_cl, points


def paired_difference_rows(
    model_id: str,
    display_name: str,
    blinded: dict,
    unblinded: dict,
    human_prices: dict[str, dict[str, np.ndarray]],
    n_draws: int,
) -> list[dict]:
    """Unblinding effect per model: same-draw deltas of beta and G.

    Both conditions are resampled on the INTERSECTION of their clusters, in
    the same key order with the same seeds, so draw d of the unblinded run
    and draw d of the blinded run sample the same bundles.
    """
    shared = sorted(set(blinded) & set(unblinded))
    if len(shared) < 2:
        raise ValueError(
            f"{model_id}: intersection of conditions has {len(shared)} clusters"
        )
    restricted = {
        short: {key: clusters[key] for key in shared}
        for short, clusters in (("b", blinded), ("u", unblinded))
    }
    condition_of = {"b": BLINDED, "u": UNBLINDED}
    human_restricted = {
        short: {key: human_prices[condition_of[short]][key[0]] for key in shared}
        for short in ("b", "u")
    }
    draw_sets = {
        "classical": {
            cond: uncertainty.cluster_bootstrap(
                restricted[cond],
                human_restricted[cond],
                n_draws,
                CLASSICAL_SEED,
            )
            for cond in ("b", "u")
        },
        "bayesian": {
            cond: uncertainty.bayesian_bootstrap(
                restricted[cond],
                human_restricted[cond],
                n_draws,
                BAYESIAN_SEED,
            )
            for cond in ("b", "u")
        },
    }
    full = {
        method: (
            full_sample_values(restricted["u"], human_restricted["u"]),
            full_sample_values(restricted["b"], human_restricted["b"]),
        )
        for method in METHODS
    }
    rows = []
    for method in METHODS:
        for metric in DELTAS:
            source = "beta_model" if metric == "delta_beta" else "G"
            diff = uncertainty.paired_difference(
                np.asarray(draw_sets[method]["u"][source], dtype=float),
                np.asarray(draw_sets[method]["b"][source], dtype=float),
            )
            center = (
                full[method][0][source] - full[method][1][source]
                if method == "classical"
                else float(np.nanmedian(diff))
            )
            center, lo, hi = summarize_draws(diff, center)
            rows.append(
                {
                    "model_id": model_id,
                    "display_name": display_name,
                    "metric": metric,
                    "method": method,
                    "center": center,
                    "lo": lo,
                    "hi": hi,
                    "n_clusters": len(shared),
                }
            )
    return rows


def run_all(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run every model-condition and the paired deltas; return both tables."""
    verify_registry_paths(args.results_root)
    human_cells, human_source = load.load_human_cells(args.cells_ref)
    print(f"  human reference: {human_source}")
    metrics_csv_path = args.outdir / "csv" / "model_price_response_metrics.csv"
    metrics_csv = pd.read_csv(metrics_csv_path) if metrics_csv_path.exists() else None
    uncertainty_rows: list[dict] = []
    delta_rows: list[dict] = []
    cluster_log: dict[tuple[str, str, str], int] = {}
    for model_id in MODELS:
        bundles: dict[str, dict] = {}
        human_prices: dict[str, dict] = {}
        for condition in CONDITIONS:
            rows, model_cl, _ = analyze_model_condition(
                args.results_root,
                model_id,
                condition,
                human_cells,
                args.n_draws,
                metrics_csv,
            )
            uncertainty_rows.extend(rows)
            bundles[condition] = model_cl
            human_prices[condition] = human_price_table(human_cells, condition)
        delta_rows.extend(
            paired_difference_rows(
                model_id,
                MODELS[model_id]["short_name"],
                bundles[BLINDED],
                bundles[UNBLINDED],
                human_prices,
                args.n_draws,
            )
        )
        for condition in CONDITIONS:
            cluster_log[(model_id, condition, "clusters")] = len(bundles[condition])
    return pd.DataFrame(uncertainty_rows), pd.DataFrame(delta_rows), cluster_log


def main() -> None:
    """Run the whole uncertainty analysis and write CSV + summary outputs."""
    args = parse_args()
    print(
        f"[1/4] uncertainty analysis over {args.results_root} ({args.n_draws} draws/method)"
    )
    uncertainty_df, delta_df, cluster_log = run_all(args)
    csv_dir = args.outdir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    uncertainty_path = csv_dir / "model_price_response_uncertainty.csv"
    delta_path = csv_dir / "unblinding_effect_uncertainty.csv"
    uncertainty_df.to_csv(uncertainty_path, index=False)
    delta_df.to_csv(delta_path, index=False)
    print(f"[2/4] wrote {uncertainty_path} ({len(uncertainty_df)} rows)")
    print(f"[3/4] wrote {delta_path} ({len(delta_df)} rows)")
    summary_path = append_summary(
        args.outdir, summary_section(uncertainty_df, delta_df, cluster_log)
    )
    print(f"  appended uncertainty section to {summary_path}")
    if args.copy_to is not None:
        print("[4/4] mirroring outputs")
        mirror_outputs(args.outdir, args.copy_to)
    else:
        print("[4/4] no mirror requested")


if __name__ == "__main__":
    main()
