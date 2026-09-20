"""Does OCEAN add anything the state variables did not already carry? — a merge gate.

The residents already have five person-level dials in
``data/hangzhou_agents_state_init.csv``: ``policy_sensitivity``,
``platform_dependence``, ``risk_preference``, ``voice_propensity`` and
``mobility_intent``. If a calibrated trait turns out to be a linear combination
of those, the Big Five is a rename rather than a new construct — every
"personality effect" the simulation then reports is an effect the model could
already produce, and the honest move is to drop that dimension rather than to
ship it.

So this script regresses each OCEAN dimension on all five existing variables
and reports the **adjusted** multiple R^2. Reading:

* ``< 0.30`` — the trait carries mostly new information. Fine.
* ``0.30-0.50`` — substantial overlap. Usable, but any finding about that
  dimension has to be reported alongside the overlapping variable.
* ``> 0.50`` — the dimension is largely predictable from what was already
  there. This is the gate: it fails.

Two details that decide whether the number means anything:

**Only residents the profiles actually describe are included.** A dimension the
source text never mentions is written as exactly 0 by
``scripts/calibrate_big5.py``, and a column of identical zeros has no variance
to explain — including those rows drags the estimate towards zero and hides the
overlap. On this corpus that is not a rounding difference: Openness scores 0.52
over all 51 residents and 0.84 over the 17 the profiles describe.

**Adjusted, not raw, R^2.** Five predictors against 11-35 evidenced residents
overfits badly enough that raw R^2 is not interpretable; the adjustment charges
for the degrees of freedom actually spent.

It also prints the pairwise correlations, because *which* variable a trait
overlaps with is more actionable than the aggregate (N vs stress is expected
and benign; O vs mobility_intent means the profile sentence that produced one
also produced the other).

Requires ``data/agents_big5.csv`` — run ``scripts/calibrate_big5.py`` first.

Usage::

    python scripts/big5_collinearity.py
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gaworld.personality.traits import DIMENSION_NAMES_ZH, DIMENSIONS

#: The person-level dials that already existed. Emotion/stress/econ_security
#: are excluded on purpose: those are *states* that move during a run, so an
#: overlap with them is a dynamic question, not a redundancy one.
STATE_VARS = [
    "policy_sensitivity",
    "platform_dependence",
    "risk_preference",
    "voice_propensity",
    "mobility_intent",
]

WARN_R2, FAIL_R2 = 0.30, 0.50


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 1e-12 and dy > 1e-12 else 0.0


#: Below this the regression has too few residents per predictor to read.
MIN_N = 10


def adjust(r2: float, n: int, predictors: int) -> float:
    """Shrink R^2 for the degrees of freedom spent. Never returns below 0."""
    if n - predictors - 1 <= 0:
        return r2
    return max(0.0, 1.0 - (1.0 - r2) * (n - 1) / (n - predictors - 1))


def multiple_r2(y: list[float], columns: list[list[float]]) -> float:
    """OLS R^2 of ``y`` on ``columns`` (plus intercept), via normal equations.

    Hand-rolled Gaussian elimination rather than numpy so the gate has no
    dependency beyond the standard library; at 6x6 the difference is noise.
    """
    n = len(y)
    design = [[1.0] + [col[i] for col in columns] for i in range(n)]
    width = len(design[0])
    normal = [[sum(design[i][a] * design[i][b] for i in range(n)) for b in range(width)]
              + [sum(design[i][a] * y[i] for i in range(n))] for a in range(width)]
    for col in range(width):
        pivot = max(range(col, width), key=lambda r: abs(normal[r][col]))
        if abs(normal[pivot][col]) < 1e-10:
            continue
        normal[col], normal[pivot] = normal[pivot], normal[col]
        scale = normal[col][col]
        normal[col] = [v / scale for v in normal[col]]
        for row in range(width):
            if row == col:
                continue
            factor = normal[row][col]
            if factor:
                normal[row] = [v - factor * c for v, c in zip(normal[row], normal[col], strict=True)]
    beta = [row[-1] for row in normal]
    mean = sum(y) / n
    ss_tot = sum((v - mean) ** 2 for v in y)
    ss_res = sum((y[i] - sum(b * x for b, x in zip(beta, design[i], strict=True))) ** 2 for i in range(n))
    return 0.0 if ss_tot < 1e-12 else max(0.0, 1.0 - ss_res / ss_tot)


def load(traits_path: str, state_path: str):
    with open(traits_path, newline="", encoding="utf-8-sig") as handle:
        traits = {int(r["id"]): r for r in csv.DictReader(handle)}
    with open(state_path, newline="", encoding="utf-8-sig") as handle:
        states = {int(r["id"]): r for r in csv.DictReader(handle)}
    ids = sorted(set(traits) & set(states))
    # Per dimension, keep only the residents whose profile actually evidenced
    # it — see the module docstring for why this is not optional.
    evidenced = {
        d: [i for i in ids if d not in str(traits[i].get("unstated", "") or "").split("|")]
        for d in DIMENSIONS
    }
    return ids, traits, states, evidenced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traits", default="data/agents_big5.csv")
    parser.add_argument("--states", default="data/hangzhou_agents_state_init.csv")
    parser.add_argument("--annotate", action="store_true",
                        help="write the failing dimensions back into the traits CSV's "
                             "`redundant` column, so every run carries the flag")
    args = parser.parse_args()

    if not os.path.exists(args.traits):
        print(f"{args.traits} not found — run scripts/calibrate_big5.py first.", file=sys.stderr)
        return 2
    ids, traits, states, evidenced = load(args.traits, args.states)
    if len(ids) < 20:
        print(f"only {len(ids)} matched agents; R^2 on this few is not interpretable",
              file=sys.stderr)
        return 2

    print(f"{len(ids)} residents matched; existing person-level variables: "
          f"{', '.join(STATE_VARS)}")
    print("each row uses only the residents whose profile evidenced that dimension\n")
    header = ("dim         n  " + "".join(f"{v[:12]:>14}" for v in STATE_VARS)
              + "   adjR^2  verdict")
    print(header)
    print("-" * len(header))

    worst = 0.0
    skipped: list[str] = []
    redundant: list[str] = []
    for dim in DIMENSIONS:
        subset = evidenced[dim]
        y = [float(traits[i][dim]) for i in subset]
        cols = [[float(states[i][v]) for i in subset] for v in STATE_VARS]
        if len(subset) < MIN_N:
            skipped.append(dim.upper())
            cells = "".join(f"{'-':>14}" for _ in STATE_VARS)
            print(f"{dim.upper()} {DIMENSION_NAMES_ZH[dim]:<5}{len(subset):>3}  {cells}"
                  f"       -  too few residents")
            continue
        cells = "".join(
            f"{pearson(y, [float(states[i][v]) for i in subset]):>14.2f}" for v in STATE_VARS
        )
        r2 = adjust(multiple_r2(y, cols), len(subset), len(STATE_VARS))
        worst = max(worst, r2)
        verdict = "ok" if r2 < WARN_R2 else ("OVERLAP" if r2 < FAIL_R2 else "FAIL redundant")
        if r2 >= FAIL_R2:
            redundant.append(dim)
        print(f"{dim.upper()} {DIMENSION_NAMES_ZH[dim]:<5}{len(subset):>3}  {cells}  "
              f"{r2:>7.2f}  {verdict}")

    if args.annotate:
        annotate(args.traits, redundant)

    print(f"\nworst adjusted R^2 = {worst:.2f} (warn at {WARN_R2}, fail at {FAIL_R2})")
    if skipped:
        print(f"{', '.join(skipped)}: fewer than {MIN_N} evidenced residents — not judged, "
              "which is itself a finding about the source profiles.")
    if worst >= FAIL_R2:
        print("A dimension above the fail line is a rename of variables the model already had:\n"
              "the profile sentences that produced it are the same ones the state variables\n"
              "were authored from. Drop it, orthogonalise it, or state plainly in any write-up\n"
              "that it is not independent.")
        return 1
    print("Every judged dimension carries information the existing state variables did not.")
    return 0


def annotate(path: str, redundant: list[str]) -> None:
    """Stamp the failing dimensions into the traits CSV's ``redundant`` column.

    The flag has to live in the frozen artefact rather than in a report,
    because the report is read once and the CSV is read by every run. The
    plugin carries it into ``output/traits/agent_traits.csv`` and prints it at
    startup, so a run cannot quietly present these dimensions as independent.
    """
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if "redundant" not in fields:
        fields.append("redundant")
    flag = "|".join(redundant)
    for row in rows:
        row["redundant"] = flag
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    if redundant:
        print(f"\nstamped redundant={flag} into {path}")
    else:
        print(f"\ncleared the redundant flag in {path}")


if __name__ == "__main__":
    raise SystemExit(main())
