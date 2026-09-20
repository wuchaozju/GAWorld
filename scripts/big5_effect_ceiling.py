"""Analytic effect ceiling for the Big Five style-fit component — a merge gate.

Answers one question before any LLM is spent: *given this amplitude, how large
a trait/behaviour correlation can the decision loop produce at all?* If the
ceiling is below ~0.10 the feature is undetectable at n=51 and the amplitude is
wrong; if it is above ~0.45 personality is louder than the personality
literature supports and the amplitude is also wrong.

It is a ceiling, not a prediction. The run calls the real
``gaworld.sim._action.choose_action`` with synthetic agents and a fixed action
pool, so the weight arithmetic, the noise jitter and the impulse bypass are the
production ones — but there is no LLM, no memory, no location bias and no
schedule, all of which add between-agent variance and therefore *lower* the
observed correlation. Treat the printed numbers as the optimistic end.

Bands come from ``docs/proposals/2026-08-20-big-five-personality.md`` §7.3 and
depend on the observation window, because aggregating over occasions raises the
trait/behaviour correlation by construction (Epstein's aggregation principle) —
judging a 200-decision run against the day-level band would fail a system that
is behaving correctly:

===========  ==================  ==============  ================
tier         window              target mean|r|  fail above max|r|
===========  ==================  ==============  ================
S (daily)    <= 60 decisions     0.10-0.30       0.45
P (aggregate) > 60 decisions     0.20-0.45       0.60
===========  ==================  ==============  ================

Usage::

    python scripts/big5_effect_ceiling.py
    python scripts/big5_effect_ceiling.py --amplitudes 0.2,0.4,0.6,0.9 --decisions 200
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gaworld.personality.plugin import cholesky, correlation_matrix, sample_traits
from gaworld.personality.traits import DIMENSIONS
from gaworld.settings import CONFIG

#: One action per style tag plus two multi-tag ones, so every candidate list
#: offers the loop a real choice between styles rather than a single outlier.
ACTION_POOL = [
    "推进手头的任务",       # progress
    "整理一下资料",         # progress
    "继续按原计划做",       # maintain
    "照常处理例行事项",     # maintain
    "刷手机拖延一会",       # avoidant
    "发呆放空一下",         # avoidant
    "联系朋友聊天",         # social
    "回消息确认安排",       # social + progress
    "回家休息",             # restorative
    "出门散步",             # restorative
    "先简单处理一下",       # quick + progress
    "顺手把小事做掉",       # quick
]

#: ``(trait, style tag, expected sign)``. The first five are the predictions
#: the loading table makes; the last is a discriminant pair with no theoretical
#: link, which should come out near zero — if it does not, the estimate is
#: picking up shared variance rather than personality.
PREDICTIONS = [
    ("e", "social", +1),
    ("c", "progress", +1),
    ("n", "restorative", +1),
    ("c", "avoidant", -1),
    ("o", "maintain", -1),
    ("a", "restorative", 0),
]

#: ``tier -> (mean lo, mean hi, fail above max)``. See the module docstring
#: for why the window decides which one applies.
TIERS = {
    "S": (0.10, 0.30, 0.45),
    "P": (0.20, 0.45, 0.60),
}

#: A 5-day run is ~40 decisions per agent; past ~60 the score is an aggregate.
S_TIER_MAX_DECISIONS = 60


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 1e-12 and dy > 1e-12 else 0.0


def make_agents(count: int, seed: int, tuning: dict[str, float], channels: list[str]) -> list[dict]:
    """Synthetic residents: correlated OCEAN plus heterogeneous internal state.

    The state spread matters as much as the traits do — it is the stand-in for
    every between-agent difference (job, schedule, relationships) that competes
    with personality for control of the choice, and leaving it out would
    inflate the ceiling.
    """
    sampling = (CONFIG.get("personality", {}) or {}).get("sampling", {}) or {}
    factor = cholesky(correlation_matrix(sampling.get("correlations", {}) or {}))
    agents = []
    for i in range(count):
        rng = random.Random(seed * 7919 + i)
        traits = sample_traits(rng, factor)
        agents.append({
            "id": 10_000 + i,
            "name": f"sim{i}",
            "state": {
                "stress": rng.uniform(0.2, 0.8),
                "emotion": rng.uniform(0.3, 0.8),
                "econ_security": rng.uniform(0.2, 0.8),
                "energy": rng.uniform(0.4, 0.9),
                "hunger": rng.uniform(0.1, 0.5),
                "social_need": rng.uniform(0.2, 0.7),
                "fatigue_debt": rng.uniform(0.1, 0.6),
                "self_control": rng.uniform(0.3, 0.8),
                "time_pressure": rng.uniform(0.1, 0.6),
            },
            "ext": {"big_five": {
                "v": 1, "source": "ceiling_probe", "channels": list(channels),
                "tuning": dict(tuning), **{d: traits[d] for d in DIMENSIONS},
            }},
        })
    return agents


def run(amplitude: float, agents: list[dict], decisions: int, seed: int) -> dict[str, float]:
    from gaworld.sim._action import choose_action
    from gaworld.sim._schedule import _action_style_tags

    tags = ["social", "progress", "restorative", "avoidant", "maintain", "quick"]
    shares: dict[str, list[float]] = {tag: [] for tag in tags}
    for agent in agents:
        agent["ext"]["big_five"]["tuning"]["amplitude"] = amplitude
        counts = dict.fromkeys(tags, 0)
        random.seed(seed * 31 + int(agent["id"]))
        for _ in range(decisions):
            picked = choose_action(agent, "个人时间", {"个人时间": ACTION_POOL})
            for tag in _action_style_tags(picked):
                if tag in counts:
                    counts[tag] += 1
        for tag in tags:
            shares[tag].append(counts[tag] / decisions)

    out: dict[str, float] = {}
    for dim, tag, _sign in PREDICTIONS:
        zs = [a["ext"]["big_five"][dim] for a in agents]
        out[f"{dim}->{tag}"] = pearson(zs, shares[tag])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amplitudes", default="0.2,0.4,0.6,0.9")
    parser.add_argument("--agents", type=int, default=51)
    parser.add_argument("--decisions", type=int, default=200,
                        help="decisions per agent; ~40 matches a 5-day run, 200 approximates the asymptote")
    parser.add_argument("--residual-ratio", type=float, default=None,
                        help="override personality.residual_ratio; the knob that caps how far "
                             "|r| can climb as the observation window grows")
    parser.add_argument("--tier", choices=("auto", "S", "P"), default="auto",
                        help="which acceptance band to apply; auto picks S for short windows")
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()

    CONFIG.setdefault("human_realism", {})["enabled"] = True
    personality = CONFIG.get("personality", {}) or {}
    tuning = {
        "strength": float(personality.get("strength", 1.0)),
        "amplitude": 0.6,
        "band": float(personality.get("modifier_band", 0.25)),
        "residual_ratio": (
            args.residual_ratio
            if args.residual_ratio is not None
            else float(personality.get("residual_ratio", 0.6))
        ),
    }
    agents = make_agents(args.agents, args.seed, tuning, ["rules"])
    amplitudes = [float(x) for x in args.amplitudes.split(",") if x.strip()]

    tier = args.tier
    if tier == "auto":
        tier = "S" if args.decisions <= S_TIER_MAX_DECISIONS else "P"
    mean_lo, mean_hi, fail_above = TIERS[tier]

    labels = [f"{d}->{t}" for d, t, _ in PREDICTIONS]
    print(f"agents={args.agents}  decisions/agent={args.decisions}  "
          f"residual_ratio={tuning['residual_ratio']}  band={tuning['band']}")
    print(f"tier {tier}: target mean|r| {mean_lo}-{mean_hi}; fail when any single |r| > {fail_above}\n")
    header = "amplitude | " + " | ".join(f"{lab:>16}" for lab in labels) + " |  mean|r| | verdict"
    print(header)
    print("-" * len(header))

    ok = True
    for amplitude in amplitudes:
        results = run(amplitude, agents, args.decisions, args.seed)
        # The discriminant pair is excluded from the mean: it is a control, not
        # a prediction.
        predicted = [abs(results[f"{d}->{t}"]) for d, t, sign in PREDICTIONS if sign]
        mean_r = sum(predicted) / len(predicted)
        worst = max(predicted)
        verdict = "PASS"
        if worst > fail_above:
            verdict = "FAIL over-strong"
        elif mean_r < mean_lo:
            verdict = "FAIL undetectable"
        elif mean_r > mean_hi:
            verdict = "WARN above band"
        cells = " | ".join(f"{results[lab]:>16.3f}" for lab in labels)
        print(f"{amplitude:>9.2f} | {cells} | {mean_r:>8.3f} | {verdict}")
        if abs(amplitude - float(personality.get("style_fit_amplitude", 0.6))) < 1e-9:
            ok = verdict == "PASS"

    configured = float(personality.get("style_fit_amplitude", 0.6))
    print(f"\nconfigured style_fit_amplitude = {configured} -> {'PASS' if ok else 'FAIL'}")
    print(f"discriminant pair {labels[-1]} should sit near 0; a large value means the "
          "estimate is picking up shared variance, not personality.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
