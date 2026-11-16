#!/usr/bin/env python3
"""
Search for a balanced Phase-3 population assignment.

This module contains the deterministic, seeded local search that decides
which of the six populations runs on each of the 126 Phase-3 runs (18
network configurations x 7 proposals). It is used by generate_run_matrix.py.

The search starts from a structured "transversal" design in which every
population gets exactly one configuration per generator per proposal, which
already satisfies Morgan-Rubin criteria 1, 2, 4 and 5. It then swaps
populations between runs to satisfy criterion 3 (secondary-level counts)
and criterion 6 (population statistic means within a tolerance of the grand
mean). Simulated annealing finds a good region and an exact local search
polishes it; the statistic tolerance is relaxed stepwise from 0.10 SD to
0.20 SD of the grand mean, while criteria 1-5 are never relaxed.

Functions:
- setup_search: give the module the statistics and config vectors it needs
- build_initial_assignment: deterministic transversal start (criteria 1,2,4,5)
- search_balanced_assignment: run the annealing + refinement search
- AssignmentState: one candidate assignment with validity and objective checks
"""

from __future__ import annotations

import math
import random
from typing import Any

STAT_KEYS = (
    "mean_degree",
    "degree_gini",
    "global_clustering",
    "mean_path_length",
    "modularity",
)
N_PROP = 7  # number of proposals
N_POP = 6  # number of populations
N_CONFIG = 18  # number of network configurations

# Diagonal structure for the transversal start: TYPE_PL[t][g] is the primary
# dial level at generator g (0=WS, 1=HK, 2=SBM) for type t. Over the seven
# proposals each population cycles through the types, so its generator and
# primary-level counts are exactly 7 and every (generator x primary level)
# cell is covered.
TYPE_PL = {0: [0, 1, 2], 1: [1, 2, 0], 2: [2, 0, 1]}
PROP_TYPES = [
    [0, 0, 1, 1, 2, 2],
    [2, 2, 0, 0, 1, 1],
    [1, 1, 2, 2, 0, 0],
    [0, 0, 1, 1, 2, 2],
    [2, 2, 0, 0, 1, 1],
    [1, 1, 2, 2, 0, 0],
    [0, 0, 1, 1, 2, 2],
]

ASSIGNMENT_SEED = 42

# Search data, installed by setup_search before the search runs.
_SEARCH: dict[str, Any] = {}


def setup_search(stats: list[list[list[float]]], cg: list[int], cpl: list[int],
                 csl: list[int], grand_mean: list[float], grand_sd: list[float]) -> None:
    """Give the module the per-cell statistics and the config index vectors.

    Args:
        stats: stats[config][proposal][stat] statistic values
        cg: generator index (0/1/2) per config
        cpl: primary level (0/1/2) per config
        csl: secondary level (0/1) per config
        grand_mean: mean of each statistic over all 126 runs
        grand_sd: population SD of each statistic over all 126 runs
    """
    _SEARCH["stats"] = stats
    _SEARCH["cg"] = cg
    _SEARCH["cpl"] = cpl
    _SEARCH["csl"] = csl
    _SEARCH["grand_mean"] = grand_mean
    _SEARCH["grand_sd"] = grand_sd


def cell_config(g: int, pl: int, sl: int) -> int:
    """Config id for generator g, primary level pl and secondary level sl."""
    return g * 6 + pl * 2 + sl


class AssignmentState:
    """One candidate population assignment plus the counters used to check it.

    assign[proposal][config] is the population index (0-5) at that cell. The
    counters track generator/level counts per population and per model so the
    Morgan-Rubin criteria can be verified incrementally and a swap can be
    rejected before it is applied.
    """

    def __init__(self, assign: list[list[int]]) -> None:
        self.assign = assign
        self.stats = _SEARCH["stats"]
        self.cg = _SEARCH["cg"]
        self.cpl = _SEARCH["cpl"]
        self.csl = _SEARCH["csl"]
        self.grand_mean = _SEARCH["grand_mean"]
        self.grand_sd = _SEARCH["grand_sd"]
        self.pop_sum = [[0.0] * len(STAT_KEYS) for _ in range(N_POP)]
        self.c_sl = [[0] * 2 for _ in range(N_POP)]
        self.c_gen = [[0] * 3 for _ in range(N_POP)]
        self.c_pl = [[0] * 3 for _ in range(N_POP)]
        self.c_gpl = [[[0] * 3 for _ in range(3)] for _ in range(N_POP)]
        self.c_mg = [[0] * 3 for _ in range(3)]
        self.c_mpl = [[0] * 3 for _ in range(3)]
        for p in range(N_PROP):
            row = assign[p]
            for c in range(N_CONFIG):
                pop = row[c]
                g, pl, sl = self.cg[c], self.cpl[c], self.csl[c]
                self.c_gen[pop][g] += 1
                self.c_pl[pop][pl] += 1
                self.c_sl[pop][sl] += 1
                self.c_gpl[pop][g][pl] += 1
                self.c_mg[pop // 2][g] += 1
                self.c_mpl[pop // 2][pl] += 1
                sv = self.stats[c][p]
                ps = self.pop_sum[pop]
                for s in range(len(STAT_KEYS)):
                    ps[s] += sv[s]

    def valid(self) -> bool:
        """True if Morgan-Rubin criteria 1-5 all hold for this assignment."""
        for pop in range(N_POP):
            for g in range(3):
                if not (6 <= self.c_gen[pop][g] <= 8):
                    return False
            for pl in range(3):
                if not (6 <= self.c_pl[pop][pl] <= 8):
                    return False
            for sl in range(2):
                if self.c_sl[pop][sl] not in (10, 11):
                    return False
            for g in range(3):
                for pl in range(3):
                    if self.c_gpl[pop][g][pl] < 1:
                        return False
        for m in range(3):
            for g in range(3):
                if not (13 <= self.c_mg[m][g] <= 15):
                    return False
            for pl in range(3):
                if not (13 <= self.c_mpl[m][pl] <= 15):
                    return False
        return True

    def pop_maxdev(self, pop: int) -> float:
        """Worst statistic deviation of one population, in units of grand SD."""
        worst = 0.0
        for s in range(len(STAT_KEYS)):
            dev = abs(self.pop_sum[pop][s] / 21 - self.grand_mean[s]) / self.grand_sd[s]
            worst = max(worst, dev)
        return worst

    def max_dev(self) -> float:
        """Worst deviation over all populations and statistics, in grand SD units."""
        return max(self.pop_maxdev(pop) for pop in range(N_POP))

    def sq(self) -> float:
        """Sum of squared per-population statistic deviations."""
        total = 0.0
        for pop in range(N_POP):
            for s in range(len(STAT_KEYS)):
                d = self.pop_sum[pop][s] / 21 - self.grand_mean[s]
                total += d * d
        return total

    def swap_delta(self, p1: int, c1: int, p2: int, c2: int, a: int, b: int,
                   kind: str, power: int = 8) -> float | None:
        """Objective change of swapping cells (p1,c1) and (p2,c2).

        Returns None if the swap would break Morgan-Rubin criteria 1-5,
        otherwise the change in the requested objective ('sq' = sum of
        squared deviations, 'p' = sum of absolute deviations to the 8th
        power). Does not mutate the state.
        """
        g1, pl1, sl1 = self.cg[c1], self.cpl[c1], self.csl[c1]
        g2, pl2, sl2 = self.cg[c2], self.cpl[c2], self.csl[c2]
        if self.c_gen[a][g1] - 1 < 6 or self.c_gen[b][g2] - 1 < 6:
            return None
        if self.c_gen[a][g2] + 1 > 8 or self.c_gen[b][g1] + 1 > 8:
            return None
        if self.c_pl[a][pl1] - 1 < 6 or self.c_pl[b][pl2] - 1 < 6:
            return None
        if self.c_pl[a][pl2] + 1 > 8 or self.c_pl[b][pl1] + 1 > 8:
            return None
        ma, mb = a // 2, b // 2
        if ma != mb:
            if self.c_mg[ma][g1] - 1 < 13 or self.c_mg[mb][g2] - 1 < 13:
                return None
            if self.c_mg[ma][g2] + 1 > 15 or self.c_mg[mb][g1] + 1 > 15:
                return None
            if self.c_mpl[ma][pl1] - 1 < 13 or self.c_mpl[mb][pl2] - 1 < 13:
                return None
            if self.c_mpl[ma][pl2] + 1 > 15 or self.c_mpl[mb][pl1] + 1 > 15:
                return None
        if self.c_gpl[a][g1][pl1] - 1 < 1:
            return None
        if self.c_gpl[b][g2][pl2] - 1 < 1:
            return None
        n_a0 = self.c_sl[a][0] - (1 if sl1 == 0 else 0) + (1 if sl2 == 0 else 0)
        n_a1 = self.c_sl[a][1] - (1 if sl1 == 1 else 0) + (1 if sl2 == 1 else 0)
        n_b0 = self.c_sl[b][0] - (1 if sl2 == 0 else 0) + (1 if sl1 == 0 else 0)
        n_b1 = self.c_sl[b][1] - (1 if sl2 == 1 else 0) + (1 if sl1 == 1 else 0)
        if (n_a0, n_a1) not in ((10, 11), (11, 10)):
            return None
        if (n_b0, n_b1) not in ((10, 11), (11, 10)):
            return None
        if kind == "sq":
            delta = 0.0
            for s in range(len(STAT_KEYS)):
                d = self.stats[c2][p2][s] - self.stats[c1][p1][s]
                da = self.pop_sum[a][s] / 21 - self.grand_mean[s]
                db = self.pop_sum[b][s] / 21 - self.grand_mean[s]
                na = da + d / 21
                nb = db - d / 21
                delta += na * na + nb * nb - da * da - db * db
            return delta
        delta = 0.0
        for s in range(len(STAT_KEYS)):
            d = self.stats[c2][p2][s] - self.stats[c1][p1][s]
            da = (self.pop_sum[a][s] / 21 - self.grand_mean[s]) / self.grand_sd[s]
            db = (self.pop_sum[b][s] / 21 - self.grand_mean[s]) / self.grand_sd[s]
            na = da + d / 21 / self.grand_sd[s]
            nb = db - d / 21 / self.grand_sd[s]
            delta += abs(na) ** power + abs(nb) ** power - abs(da) ** power - abs(db) ** power
        return delta

    def apply_swap(self, p1: int, c1: int, p2: int, c2: int, a: int, b: int) -> None:
        """Swap the populations of cells (p1,c1) and (p2,c2) in place."""
        g1, pl1, sl1 = self.cg[c1], self.cpl[c1], self.csl[c1]
        g2, pl2, sl2 = self.cg[c2], self.cpl[c2], self.csl[c2]
        ma, mb = a // 2, b // 2
        pa, pb = self.pop_sum[a][:], self.pop_sum[b][:]
        for s in range(len(STAT_KEYS)):
            pa[s] += self.stats[c2][p2][s] - self.stats[c1][p1][s]
            pb[s] += self.stats[c1][p1][s] - self.stats[c2][p2][s]
        self.pop_sum[a], self.pop_sum[b] = pa, pb
        self.c_gen[a][g1] -= 1
        self.c_gen[b][g2] -= 1
        self.c_gen[a][g2] += 1
        self.c_gen[b][g1] += 1
        self.c_pl[a][pl1] -= 1
        self.c_pl[b][pl2] -= 1
        self.c_pl[a][pl2] += 1
        self.c_pl[b][pl1] += 1
        self.c_sl[a][sl1] -= 1
        self.c_sl[a][sl2] += 1
        self.c_sl[b][sl2] -= 1
        self.c_sl[b][sl1] += 1
        self.c_gpl[a][g1][pl1] -= 1
        self.c_gpl[b][g2][pl2] -= 1
        self.c_gpl[a][g2][pl2] += 1
        self.c_gpl[b][g1][pl1] += 1
        if ma != mb:
            self.c_mg[ma][g1] -= 1
            self.c_mg[mb][g2] -= 1
            self.c_mg[ma][g2] += 1
            self.c_mg[mb][g1] += 1
            self.c_mpl[ma][pl1] -= 1
            self.c_mpl[mb][pl2] -= 1
            self.c_mpl[ma][pl2] += 1
            self.c_mpl[mb][pl1] += 1
        self.assign[p1][c1], self.assign[p2][c2] = b, a


def build_initial_assignment(rng: random.Random) -> AssignmentState:
    """Build a deterministic transversal start satisfying criteria 1, 2, 4, 5.

    Each population gets exactly one config per generator per proposal, so
    per-population generator and primary-level counts are exactly 7 and the
    (generator x primary level) cells are all covered. The secondary-level
    bits are drawn from the seeded RNG; the search fixes criterion 3 and
    criterion 6 afterwards.
    """
    while True:
        bits = [[rng.randint(0, 1) for _ in range(9)] for _ in range(N_PROP)]
        assign = [[0] * N_CONFIG for _ in range(N_PROP)]
        for p in range(N_PROP):
            types = PROP_TYPES[p]
            for t in range(3):
                pops = [i for i in range(N_POP) if types[i] == t]
                for g in range(3):
                    bit = bits[p][t * 3 + g]
                    pl = TYPE_PL[t][g]
                    assign[p][cell_config(g, pl, bit)] = pops[0]
                    assign[p][cell_config(g, pl, 1 - bit)] = pops[1]
        st = AssignmentState(assign)
        if st.valid():
            return st


def random_move(rng: random.Random) -> tuple[int, int, int, int]:
    """Pick a random swap proposal between two configurations of one proposal.

    Swaps stay inside a single proposal so every population keeps exactly
    three configurations per proposal, matching the task's shuffle semantics.
    """
    p = rng.randrange(N_PROP)
    c1 = rng.randrange(N_CONFIG)
    c2 = rng.randrange(N_CONFIG)
    return (p, c1, p, c2)


def sa_phase(st: AssignmentState, rng: random.Random, iters: int,
             t0: float, t1: float, kind: str) -> None:
    """Simulated annealing on the chosen objective ('sq' or 'p')."""
    anneal = math.exp(math.log(t1 / t0) / iters)
    temp = t0
    for _ in range(iters):
        p1, c1, p2, c2 = random_move(rng)
        a = st.assign[p1][c1]
        b = st.assign[p2][c2]
        if a == b:
            continue
        delta = st.swap_delta(p1, c1, p2, c2, a, b, kind)
        if delta is None:
            continue
        if delta < 0 or rng.random() < math.exp(-delta / temp):
            st.apply_swap(p1, c1, p2, c2, a, b)
        temp *= anneal


def refine_exact(st: AssignmentState, rng: random.Random, max_passes: int = 400) -> None:
    """Best-improvement local search on the worst statistic deviation.

    Only swaps inside a single proposal are considered, so every population
    keeps exactly three configurations per proposal.
    """
    for _ in range(max_passes):
        pop_maxes = [st.pop_maxdev(p) for p in range(N_POP)]
        cur_md = max(pop_maxes)
        best_gain = 1e-12
        best_move: tuple | None = None
        for p in range(N_PROP):
            for i in range(N_CONFIG):
                c1 = i
                a = st.assign[p][c1]
                for j in range(i + 1, N_CONFIG):
                    c2 = j
                    b = st.assign[p][c2]
                    if a == b:
                        continue
                    if st.swap_delta(p, c1, p, c2, a, b, "sq") is None:
                        continue
                    new_a = [st.pop_sum[a][s] + st.stats[c2][p][s] - st.stats[c1][p][s]
                             for s in range(len(STAT_KEYS))]
                    new_b = [st.pop_sum[b][s] + st.stats[c1][p][s] - st.stats[c2][p][s]
                             for s in range(len(STAT_KEYS))]
                    new_pair_md = max(
                        max(abs(new_a[s] / 21 - st.grand_mean[s]) / st.grand_sd[s]
                            for s in range(len(STAT_KEYS))),
                        max(abs(new_b[s] / 21 - st.grand_mean[s]) / st.grand_sd[s]
                            for s in range(len(STAT_KEYS))),
                    )
                    others_md = max(pop_maxes[x] for x in range(N_POP) if x != a and x != b)
                    gain = cur_md - max(others_md, new_pair_md)
                    if gain > best_gain:
                        best_gain = gain
                        best_move = (p, c1, p, c2, a, b)
        if best_move is None or best_gain <= 1e-12:
            break
        p1, c1, p2, c2, a, b = best_move
        st.apply_swap(p1, c1, p2, c2, a, b)


def perturb(st: AssignmentState, rng: random.Random, n: int) -> None:
    """Apply n random valid swaps to escape a local minimum."""
    for _ in range(n):
        p1, c1, p2, c2 = random_move(rng)
        a = st.assign[p1][c1]
        b = st.assign[p2][c2]
        if a == b:
            continue
        if st.swap_delta(p1, c1, p2, c2, a, b, "sq") is not None:
            st.apply_swap(p1, c1, p2, c2, a, b)


def search_balanced_assignment() -> tuple[AssignmentState, float, int]:
    """Search for an assignment meeting criteria 1-5 and criterion 6.

    Criterion 6 (statistic balance) is tried at 0.10 SD of the grand mean
    first and relaxed to 0.15 then 0.20 if no assignment is found. Criteria
    1-5 are never relaxed. Returns (assignment, threshold_used, attempts)
    where attempts is the number of search seeds used.
    """
    for threshold in (0.10, 0.15, 0.20):
        for seed in range(ASSIGNMENT_SEED, ASSIGNMENT_SEED + 8):
            rng = random.Random(seed)
            st = build_initial_assignment(rng)
            sa_phase(st, rng, 3_000_000, 0.05, 1e-6, "sq")
            sa_phase(st, rng, 1_500_000, 1e-3, 1e-7, "p")
            refine_exact(st, rng)
            if st.max_dev() <= threshold:
                return st, threshold, seed - ASSIGNMENT_SEED + 1
            best = st
            for _round in range(12):
                candidate = AssignmentState([row[:] for row in best.assign])
                perturb(candidate, rng, 300)
                refine_exact(candidate, rng)
                if candidate.max_dev() < best.max_dev():
                    best = candidate
                if best.max_dev() <= threshold:
                    return best, threshold, seed - ASSIGNMENT_SEED + 1
        print(f"  threshold {threshold:.2f}: not met with 8 seeds; relaxing", flush=True)
    raise RuntimeError("No assignment found even at 0.20 SD — this should not happen")
