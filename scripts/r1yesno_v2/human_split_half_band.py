"""Human split-half benchmark band (TASK-2124).

WHAT THIS FILE DOES: it measures how much human purchase-intent data
wobbles against ITSELF. We split the 2,058 Twin-2K-500 participants into
two random halves 1,000 times, draw the demand curve of each half, and
measure how far apart the two halves land. That gives an error
DISTRIBUTION (a band), which complements the wave3-vs-wave4 retest floor
of 0.0241 MAE from TASK-1536: if a model's error sits inside the human
band, the model is no worse than humans disagreeing with themselves.

A safety gate runs first: the extraction must rebuild the known human
p(buy) for all 440 product-and-price cells EXACTLY as archived in the
TASK-1592 cells file, with all 82,320 answers and zero off-grid prices,
or the script refuses to run.

Plain-language map of the functions:

    product_from_text / price_from_text
                         - The product name / shown dollar price in a question.
    grid_level           - Snap a shown price to a grid level k (0..10), or
                           None when the price is not really on the grid.
    extract_tidy_table(_with_skips)
                         - Turn persona_json blobs into one tidy row per
                           answer (pid, product, price, level, answer);
                           _with_skips also counts unreadable pricing
                           questions, never dropping them silently.
    split_pids           - Two random disjoint halves covering everyone;
                           same seed, same halves.
    cell_buy_share / cell_mae
                         - One half's "would buy" share per cell; then the
                           mean absolute gap between halves over cells.
    pooled_curve / curve_mae / level_maes
                         - One half's 11-point demand curve (average buy
                           share per level); then the gap between halves'
                           curves, overall and per level.
    percentiles / split_metrics / run_splits
                         - p5/p50/p95 of errors; all three error numbers
                           for one split; the repeat-many-splits table.
    load_personas        - Read every participant's persona_json blob
                           from the dataset (read-only).
    build_answer_matrix  - Lay answers out as a participants-by-cells grid
                           so 1,000 splits run fast.
    gate_report          - Safety checks against the archived cells file;
                           raise ValueError on any mismatch.
    _summary_lines / _caveat_lines / write_summary
                         - The markdown body, its caveats, and the writer
                           of the plain-language SUMMARY file.
    main                 - Command-line entry point; writes the CSV and
                           the summary next to it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

N_LEVELS = 11
LEVELS = tuple(range(N_LEVELS))
# Expected volume of wave-4 pricing answers: 2,058 x 40 = 82,320, i.e.
# ~93.5 answers per cell per half. The gate refuses any other count.
EXPECTED_ITEMS = 82_320
ANSWERS_PER_CELL_PER_HALF = EXPECTED_ITEMS / 440 / 2
# A shown price is the regular price times k/5, rounded to whole cents,
# so the raw level lands within ~0.025 of a whole number. Anything further
# away than this tolerance is treated as an off-grid price.
GRID_TOLERANCE = 0.05
# The wave3-vs-wave4 retest floor measured in TASK-1536.
RETEST_FLOOR_MAE = 0.0241

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TWIN_DIR = Path("/home/justin/work/datasets/Twin-2K-500")
DEFAULT_CELLS_CSV = Path("/home/justin/work/research/TASK-1592/csv/cells.csv")
DEFAULT_PRODUCTS_JSON = REPO_ROOT / "data" / "configs" / "unblinding_products.json"
DEFAULT_OUT_DIR = Path("/home/justin/Documents/output/R1-YESNO-analysis/csv")

_PRODUCT_MARKER = "following product in that category: "
_PRICE_MARKER = ". The product is priced at: $"
_PRICE_RE = re.compile(r"priced at: \$(\d+(?:\.\d+)?)")
_GRID_PRICE_TO_LEVEL = {level * 20: level for level in LEVELS}
CellShares = dict[tuple[str, int], float]  # one half's per-cell buy shares


def product_from_text(text: str) -> str | None:
    """The product name from a pricing question's text, or None."""
    if _PRODUCT_MARKER not in text:
        return None
    tail = text.split(_PRODUCT_MARKER, 1)[1]
    if _PRICE_MARKER not in tail:
        return None
    return tail.split(_PRICE_MARKER, 1)[0]


def price_from_text(text: str) -> float | None:
    """The shown dollar price from a pricing question's text, or None."""
    match = _PRICE_RE.search(text)
    return float(match.group(1)) if match else None


def grid_level(price: float, regular: float) -> int | None:
    """Snap a shown price to a grid level k in 0..10, or None if off-grid.

    The grid is the shown price as a fraction of the regular price, times
    five (k=0 free, k=5 regular, k=10 double). Stores round to cents, so
    accept the nearest level only within GRID_TOLERANCE of it.
    """
    if regular <= 0:
        return None
    raw = price / regular * 5.0
    level = int(math.floor(raw + 0.5))
    if abs(raw - level) > GRID_TOLERANCE or level not in LEVELS:
        return None
    return level


def extract_tidy_table_with_skips(
    personas: list[tuple[int, str]], products: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Turn persona_json blobs into tidy rows, counting unreadable pricing
    questions.

    `personas` holds (pid, persona_json_text) pairs. Only pricing questions
    (QuestionID starting "QID9") are extracted; each returned row has pid,
    product, price, level, answer (True = buy). A pricing question whose
    product, price, or answer cannot be read is counted in the returned
    skip count, never dropped silently.
    """
    regular = {p["product"]: float(p["regular_price"]) for p in products}
    rows: list[dict[str, Any]] = []
    skipped = 0
    for pid, blob in personas:
        for block in json.loads(blob):
            for question in block.get("Questions") or []:
                if not str(question.get("QuestionID", "")).startswith("QID9"):
                    continue
                text = str(question.get("QuestionText", ""))
                product = product_from_text(text)
                price = price_from_text(text)
                answer = (question.get("Answers") or {}).get("SelectedByPosition")
                if product is None or price is None or answer not in (1, 2):
                    skipped += 1
                    continue
                level = grid_level(price, regular.get(product, -1.0))
                if level is None:
                    skipped += 1
                    continue
                rows.append(
                    {
                        "pid": int(pid),
                        "product": product,
                        "price": price,
                        "level": level,
                        "answer": answer == 1,
                    }
                )
    return rows, skipped


def extract_tidy_table(
    personas: list[tuple[int, str]], products: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Just the tidy rows (see extract_tidy_table_with_skips)."""
    return extract_tidy_table_with_skips(personas, products)[0]


def split_pids(pids: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Two random disjoint halves of the pids that together cover everyone.

    Same seed gives the same halves; sizes differ by at most one when the
    count is odd.
    """
    rng = np.random.default_rng(seed)
    shuffled = np.asarray(pids)[rng.permutation(len(pids))]
    half = len(shuffled) // 2
    return shuffled[:half], shuffled[half:]


def cell_buy_share(rows: list[dict[str, Any]], pids: np.ndarray) -> CellShares:
    """Share of "would buy" answers per (product, level) cell for a half."""
    wanted = set(np.asarray(pids).tolist())
    buys: dict[tuple[str, int], list[int]] = {}
    for row in rows:
        if row["pid"] not in wanted:
            continue
        buys.setdefault((row["product"], row["level"]), []).append(
            1 if row["answer"] else 0
        )
    return {cell: float(np.mean(answers)) for cell, answers in buys.items()}


def cell_mae(cells_a: CellShares, cells_b: CellShares) -> float:
    """Mean absolute gap between two halves over the cells they share.

    Cells in only one half are left out with a warning (real data always
    covers every cell).
    """
    shared = set(cells_a) & set(cells_b)
    if not shared:
        raise ValueError("cell_mae: the two halves share no (product, level) cell")
    if set(cells_a) != set(cells_b):
        warnings.warn(
            f"cell_mae: {len(set(cells_a) ^ set(cells_b))} unshared cells left out"
        )
    return float(np.mean([abs(cells_a[c] - cells_b[c]) for c in shared]))


def pooled_curve(
    rows: list[dict[str, Any]], pids: np.ndarray, n_levels: int = N_LEVELS
) -> np.ndarray:
    """The 11-point demand curve of one half (buy share per price level).

    Levels with no answers at all come back as NaN rather than a fake 0.
    """
    wanted = set(np.asarray(pids).tolist())
    per_level: dict[int, list[int]] = {level: [] for level in range(n_levels)}
    for row in rows:
        if row["pid"] in wanted:
            per_level[row["level"]].append(1 if row["answer"] else 0)
    return np.array(
        [
            float(np.mean(per_level[level])) if per_level[level] else np.nan
            for level in range(n_levels)
        ]
    )


def curve_mae(curve_a: np.ndarray, curve_b: np.ndarray) -> float:
    """Mean absolute gap between two halves' curves over comparable levels."""
    gaps = np.abs(np.asarray(curve_a, dtype=float) - np.asarray(curve_b, dtype=float))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return float(np.nanmean(gaps))


def level_maes(
    cells_a: CellShares, cells_b: CellShares, levels: tuple[int, ...] = LEVELS
) -> list[float]:
    """Per price level: mean absolute gap across that level's products.

    A level with no comparable products scores 0.0 (no disagreement seen).
    """
    result = []
    for level in levels:
        cells = [c for c in set(cells_a) & set(cells_b) if c[1] == level]
        result.append(
            float(np.mean([abs(cells_a[c] - cells_b[c]) for c in cells]))
            if cells
            else 0.0
        )
    return result


def percentiles(values: np.ndarray) -> tuple[float, float, float]:
    """The p5, p50, and p95 of a list of error numbers."""
    p5, p50, p95 = np.percentile(np.asarray(values, dtype=float), [5, 50, 95])
    return float(p5), float(p50), float(p95)


def split_metrics(
    rows: list[dict[str, Any]], pids: np.ndarray, seed: int
) -> dict[str, Any]:
    """The three error numbers for one random half-vs-half split."""
    half_a, half_b = split_pids(pids, seed)
    cells_a = cell_buy_share(rows, half_a)
    cells_b = cell_buy_share(rows, half_b)
    curve_a = pooled_curve(rows, half_a)
    curve_b = pooled_curve(rows, half_b)
    return {
        "cell_mae": cell_mae(cells_a, cells_b),
        "curve_mae": curve_mae(curve_a, curve_b),
        "level_mae": level_maes(cells_a, cells_b),
    }


def run_splits(rows: list[dict[str, Any]], n_splits: int, seed: int) -> pd.DataFrame:
    """Repeat the split n_splits times; one row per split, matrix-backed.

    Columns: split_id, cell_mae, curve_mae, one level_k_mae per level.
    """
    pids, matrix, cells = build_answer_matrix(rows)
    records = []
    for split_id in range(n_splits):
        half_a, half_b = split_pids(pids, seed + split_id)
        share_a = np.nanmean(matrix[np.isin(pids, half_a)], axis=0)
        share_b = np.nanmean(matrix[np.isin(pids, half_b)], axis=0)
        gap = np.abs(share_a - share_b)
        per_level_gap = _level_pool(gap, cells)
        record: dict[str, Any] = {
            "split_id": split_id,
            "cell_mae": float(np.nanmean(gap)),
            "curve_mae": curve_mae(
                _level_pool(share_a, cells), _level_pool(share_b, cells)
            ),
        }
        record.update({f"level_{lv}_mae": float(per_level_gap[lv]) for lv in LEVELS})
        records.append(record)
    return pd.DataFrame(records)


def _level_pool(share: np.ndarray, cells: list[tuple[str, int]]) -> np.ndarray:
    """Per-level average of one half's per-cell shares (the pooled curve)."""
    pooled = np.full(N_LEVELS, np.nan)
    for level in LEVELS:
        values = [share[i] for i, cell in enumerate(cells) if cell[1] == level]
        if values:
            pooled[level] = float(np.nanmean(values))
    return pooled


def load_personas(twin_dir: Path) -> list[tuple[int, str]]:
    """Read every participant's persona_json blob (read-only, no writes)."""
    chunks = sorted(
        (twin_dir / "full_persona" / "chunks").glob("persona_chunk_*.parquet")
    )
    if not chunks:
        raise FileNotFoundError(f"no persona_chunk_*.parquet under {twin_dir}")
    personas: list[tuple[int, str]] = []
    for chunk in chunks:
        frame = pd.read_parquet(chunk, columns=["pid", "persona_json"])
        personas.extend(zip(frame["pid"].astype(int), frame["persona_json"]))
    return personas


def build_answer_matrix(
    rows: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, list[tuple[str, int]]]:
    """Lay answers out as a participants-by-cells grid for fast splitting.

    Returns (pids in order, matrix of 1.0 buy / 0.0 no / NaN unanswered,
    and the sorted (product, level) key for each matrix column).
    """
    pids = np.array(sorted({row["pid"] for row in rows}), dtype=int)
    cells = sorted({(row["product"], row["level"]) for row in rows})
    pid_index = {pid: i for i, pid in enumerate(pids)}
    cell_index = {cell: j for j, cell in enumerate(cells)}
    matrix = np.full((len(pids), len(cells)), np.nan)
    for row in rows:
        matrix[pid_index[row["pid"]], cell_index[(row["product"], row["level"])]] = (
            1.0 if row["answer"] else 0.0
        )
    return pids, matrix, cells


def gate_report(tidy: pd.DataFrame, cells_csv: Path) -> str:
    """Check the extraction against the archived cells file before use.

    Raises ValueError unless every row sits on the price grid, the answer
    count matches EXPECTED_ITEMS, and the rebuilt p(buy) matches the
    archived human_p to float precision on all 440 cells.
    """
    n_items = len(tidy)
    violations = int((tidy["level"].isna()).sum())
    if n_items != EXPECTED_ITEMS:
        raise ValueError(f"gate: expected {EXPECTED_ITEMS} answers, got {n_items}")
    if violations:
        raise ValueError(f"gate: {violations} answers fell off the price grid")
    rebuilt = tidy.groupby(["product", "level"], sort=True)["answer"].mean()
    archived = pd.read_csv(cells_csv).drop_duplicates(["product", "price"])
    archived = archived.set_index(["product", "price"])["human_p"]
    archived.index = pd.MultiIndex.from_tuples(
        [(prod, _GRID_PRICE_TO_LEVEL[int(price)]) for prod, price in archived.index],
        names=["product", "level"],
    )
    joined = pd.concat([rebuilt.rename("rebuilt"), archived.rename("archived")], axis=1)
    if len(joined) != len(rebuilt) or joined.isna().any().any():
        raise ValueError(
            f"gate: cell sets disagree ({len(rebuilt)} rebuilt vs {len(joined)} joined)"
        )
    max_diff = float((joined["rebuilt"] - joined["archived"]).abs().max())
    if max_diff > 1e-12:
        raise ValueError(f"gate: human_p mismatch, max |diff| = {max_diff:.3e}")
    n_pids = tidy["pid"].nunique()
    return (
        f"gate PASS: {n_items:,} answers, {n_pids:,} participants, "
        f"{len(rebuilt)} cells, 0 grid violations, "
        f"human_p max |diff| = {max_diff:.1e} vs {cells_csv.name}"
    )


def _caveat_lines(seed: int) -> list[str]:
    """The caveats bullet list: wave-3, cent rounding, Monte-Carlo, read-only."""
    return [
        "- Wave-3 answers are NOT used: the dataset does not ship wave-3 shown "
        "prices, so a wave3-vs-wave4 per-cell pairing is impossible here; the "
        "0.0241 floor from TASK-1536 used wave-4 slot pairing for the same reason.",
        "- Shown prices are cent-rounded, so grid levels are snapped with a "
        f"+/-{GRID_TOLERANCE}-level tolerance (max observed offset ~0.025 levels).",
        f"- Monte-Carlo band, not a closed-form interval; seed {seed} makes it "
        "reproducible.",
        "- The dataset was read read-only; no existing file was modified.",
        "",
    ]


def _summary_lines(
    frame: pd.DataFrame, gate_line: str, n_splits: int, seed: int
) -> list[str]:
    """The markdown body: method, results table, comparison, caveats."""
    table = ["| metric | p5 | p50 | p95 |", "|---|---|---|---|"]
    for column, label in SUMMARY_COLUMNS:
        p5, p50, p95 = percentiles(frame[column].to_numpy())
        table.append(f"| {label} | {p5:.4f} | {p50:.4f} | {p95:.4f} |")
    p5, _p50, _p95 = percentiles(frame["cell_mae"].to_numpy())
    above = float((frame["cell_mae"] > RETEST_FLOOR_MAE).mean()) * 100
    return [
        "# Human split-half benchmark band (TASK-2124)",
        "",
        "## Method",
        "",
        f"Each of {n_splits} splits (numpy default_rng, base seed {seed}) cuts the "
        "2,058 Twin-2K-500 wave-4 participants into two random halves. Each half's "
        "p(buy) is computed for all 440 product-price cells (40 products x 11 price "
        "levels k=0..10, level = price/regular*5). Metrics per split: cell_mae "
        "(mean |pA-pB| over cells), curve_mae (mean |pA-pB| over the 11 pooled "
        "levels), and one mean |pA-pB| per level.",
        "",
        f"{gate_line}.",
        "",
        f"A half holds 1,029 participants; with {EXPECTED_ITEMS:,} answers over 440 "
        f"cells that is ~{ANSWERS_PER_CELL_PER_HALF:.0f} answers per cell per half, "
        "so each cell's p(buy) still carries binomial noise of roughly 0.05 - that "
        "sampling noise IS the band.",
        "",
        "## Results (p5 / p50 / p95 per metric)",
        "",
        *table,
        "",
        "## Comparison vs the retest floor (0.0241)",
        "",
        f"Of {n_splits} splits, {above:.1f}% land above the wave3-vs-wave4 retest "
        f"floor of {RETEST_FLOOR_MAE} MAE; the p5 cell-MAE ({p5:.4f}) is the honest "
        "lower bound of human-vs-human error. The floor is lower because the SAME "
        "people retest (correlated answers); random halves are independent samples, "
        "so this band is the right yardstick for comparing one model against "
        "another, while the floor bounds how stable one person's curve stays.",
        "",
        "## Caveats",
        "",
        *_caveat_lines(seed),
    ]


def write_summary(
    frame: pd.DataFrame, gate_line: str, out_path: Path, n_splits: int, seed: int
) -> None:
    """Write the plain-language SUMMARY markdown next to the CSV."""
    body = _summary_lines(frame, gate_line, n_splits, seed)
    out_path.write_text("\n".join(body), encoding="utf-8")


# The CSV columns to summarise in the markdown, with readable labels.
SUMMARY_COLUMNS = [
    ("cell_mae", "cell-MAE (440 cells)"),
    ("curve_mae", "curve-MAE (11 pooled levels)"),
] + [(f"level_{lv}_mae", f"level-{lv} MAE") for lv in LEVELS]


def main() -> None:
    """Run the gate, then the 1,000 splits, then write CSV + summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--twin-dir", type=Path, default=DEFAULT_TWIN_DIR)
    parser.add_argument("--cells-csv", type=Path, default=DEFAULT_CELLS_CSV)
    parser.add_argument("--products-json", type=Path, default=DEFAULT_PRODUCTS_JSON)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--n-splits", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    products = json.loads(args.products_json.read_text(encoding="utf-8"))["products"]
    print(f"reading personas from {args.twin_dir} ...")
    personas = load_personas(args.twin_dir)
    rows, skipped = extract_tidy_table_with_skips(personas, products)
    if skipped:
        raise ValueError(f"extraction skipped {skipped} unreadable questions")
    tidy = pd.DataFrame(rows)
    gate_line = gate_report(tidy, args.cells_csv)
    print(gate_line)

    print(f"running {args.n_splits} half-vs-half splits (seed {args.seed}) ...")
    frame = run_splits(rows, n_splits=args.n_splits, seed=args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "human_split_half_band.csv"
    frame.to_csv(csv_path, index=False)
    summary_path = args.out_dir / "human_split_half_band_SUMMARY.md"
    write_summary(frame, gate_line, summary_path, args.n_splits, args.seed)
    p5, p50, p95 = percentiles(frame["cell_mae"].to_numpy())
    print(f"wrote {csv_path}\nwrote {summary_path}")
    print(f"cell-MAE p5/p50/p95 = {p5:.4f} / {p50:.4f} / {p95:.4f}")


if __name__ == "__main__":
    main()
