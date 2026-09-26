"""Track B: does avoidance behaviour redistribute where people go?

Track B asks for a regularity produced by the agent → environment → agent
loop rather than written into a prompt. Exactly one such loop is closed today:

    node occupancy → crowding perception → interrupt / redirect
                  → learned location aversion (P0–P4)

Nothing in that chain tells an agent to avoid busy places. The aversion score
accumulates only from anomalies the agent personally ran into, decays day by
day, and persists across runs. Whatever redistribution it produces is earned.

**Why not the commuting double peak.** It was the obvious candidate and it is
not admissible: ``generate_daily_routine`` never reads travel time or
congestion, so a peak can only come from what the profile prose and the
weekday/weekend rule already say. There is no mechanism by which it could
emerge, and running longer cannot change that (congestion proposal §16).

Method — a controlled pair, not a single number:

1. Reference run with ``spatial_preferences.enabled = false``.
2. Treatment run with it on, same seed, same everything else.
3. Per day, measure how concentrated visits are across locations.
4. The claim is the **separation of the two curves**, judged against
   cross-seed noise — the L1/L4 logic from the group-agent work, where a
   single seed was shown to be noise and absolute thresholds were shown to be
   the thing the module's own docstring warned about.

Both runs need ``local_physical.record_occupancy = true``; nothing else
writes where everyone was.

Both runs also need ``stateful = false``. Learned aversions are saved to
``memory_dir/agent_<id>_env_preferences.json`` and reloaded on ``agents.built``
(``world/plugin.py``), so with the default ``stateful = true`` seed 2 of the
treatment arm starts from seed 1's sediment. The cross-seed spread below is
then not a noise estimate of anything. ``stateful = false`` is what the config
docs already recommend for a clean control.

Do not use ``--fast-forward`` / ``--sim-months`` / ``--sim-years``: those
replace the intra-day tick loop with one brief per agent per step, and
occupancy is recorded per tick.

Usage
-----
    # one seed, one side
    GAWORLD_CONFIG_OVERRIDES='{"random_seed":1,"stateful":false,
        "local_physical":{"record_occupancy":true},
        "spatial_preferences":{"enabled":false},
        "records":{"output_dir":"output/trackb/ref-s1"}}' \\
      python generative_city_sim.py run --sim-days 30

    # …repeat with "enabled":true → output/trackb/trt-s1, and for seeds 2, 3
    # smoke-test the plumbing first for near-zero LLM cost:
    #   add "fos_fast_mode":{"deterministic_cognition":true} and --sim-days 2,
    #   then check output/trackb/<dir>/spatial.occupancy.jsonl is non-empty.

    python benchmark/trackb_spatial.py \\
        --reference output/trackb/ref-s1 output/trackb/ref-s2 output/trackb/ref-s3 \\
        --treatment output/trackb/trt-s1 output/trackb/trt-s2 output/trackb/trt-s3

    python benchmark/trackb_spatial.py --self-check   # no simulation needed
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TABLE = "spatial.occupancy.jsonl"
#: Cross-seed standard deviations of separation the effect must clear. Two is
#: the same bar the group-agent gates settled on after an absolute band was
#: found to be measuring estimator noise at small N.
NOISE_MULTIPLE = 2.0


def herfindahl(counts: dict[str, float]) -> float:
    """Concentration of people across locations: 1/n (even) … 1 (all in one)."""
    total = sum(max(0.0, float(v)) for v in counts.values())
    if total <= 0:
        return 0.0
    return sum((float(v) / total) ** 2 for v in counts.values() if float(v) > 0)


def daily_concentration(run_dir: Path) -> dict[int, float]:
    """Mean per-tick concentration for each day of one run."""
    path = Path(run_dir) / TABLE
    per_day: dict[int, list[float]] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                counts = row.get("counts")
                if not isinstance(counts, dict) or not counts:
                    continue
                per_day.setdefault(int(row.get("_day", 0)), []).append(herfindahl(counts))
    except OSError:
        return {}
    return {day: statistics.fmean(values) for day, values in sorted(per_day.items()) if values}


def _curve(run_dirs) -> tuple[dict[int, list[float]], list[str]]:
    curves: dict[int, list[float]] = {}
    missing = []
    for run_dir in run_dirs:
        daily = daily_concentration(Path(run_dir))
        if not daily:
            missing.append(str(run_dir))
            continue
        for day, value in daily.items():
            curves.setdefault(day, []).append(value)
    return curves, missing


def compare(reference_dirs, treatment_dirs) -> dict:
    """Separation of the two curves, against cross-seed spread."""
    ref, ref_missing = _curve(reference_dirs)
    trt, trt_missing = _curve(treatment_dirs)
    days = sorted(set(ref) & set(trt))
    if not days:
        return {"status": "no_data",
                "note": "no overlapping days; did both sides record occupancy?",
                "missing": ref_missing + trt_missing}

    rows = []
    for day in days:
        r, t = ref[day], trt[day]
        spread = max(
            statistics.pstdev(r) if len(r) > 1 else 0.0,
            statistics.pstdev(t) if len(t) > 1 else 0.0,
        )
        separation = statistics.fmean(t) - statistics.fmean(r)
        rows.append({
            "day": day,
            "reference": round(statistics.fmean(r), 6),
            "treatment": round(statistics.fmean(t), 6),
            "separation": round(separation, 6),
            "cross_seed_sd": round(spread, 6),
            "clears_noise": bool(spread > 0 and abs(separation) >= NOISE_MULTIPLE * spread),
        })

    seeds = min(len(reference_dirs), len(treatment_dirs))
    later = rows[len(rows) // 2:]  # aversion needs days to accumulate
    verdict = "inconclusive"
    if seeds < 3:
        note = f"only {seeds} seed(s) per side; a single seed is noise, use >=3"
    elif not any(row["cross_seed_sd"] > 0 for row in rows):
        note = "no cross-seed spread to judge against"
    elif all(row["clears_noise"] for row in later) and later:
        direction = "less" if later[-1]["separation"] < 0 else "more"
        verdict = "separated"
        note = (f"treatment stays {NOISE_MULTIPLE}x cross-seed sd from reference over the "
                f"second half of the run; avoidance leaves people {direction} concentrated")
    else:
        note = "separation does not clear cross-seed noise in the second half"

    return {"status": "ok", "verdict": verdict, "note": note,
            "seeds_per_side": seeds, "days": rows,
            "missing_runs": ref_missing + trt_missing}


def _self_check() -> dict:
    """Exercise the metric on synthetic occupancy — no simulator needed."""
    even = {f"n{i}": 10 for i in range(10)}
    lumpy = {"n0": 91, **{f"n{i}": 1 for i in range(1, 10)}}
    assert herfindahl(even) < herfindahl(lumpy)
    assert abs(herfindahl(even) - 0.1) < 1e-9
    assert herfindahl({}) == 0.0
    assert herfindahl({"a": 0}) == 0.0
    return {"herfindahl_even": herfindahl(even), "herfindahl_lumpy": herfindahl(lumpy)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reference", nargs="*", default=[],
                        help="run directories with spatial_preferences OFF")
    parser.add_argument("--treatment", nargs="*", default=[],
                        help="run directories with spatial_preferences ON")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.self_check:
        print(json.dumps(_self_check(), indent=2))
        return 0
    if not args.reference or not args.treatment:
        parser.error("need --reference and --treatment run directories")

    result = compare(args.reference, args.treatment)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if result["status"] != "ok":
        print(f"无法判定：{result['note']}")
        return 1
    print(f"每侧 {result['seeds_per_side']} 个种子\n")
    print(f"{'天':>4} {'参照':>10} {'处理':>10} {'分离':>10} {'跨种子sd':>10}  过噪声")
    for row in result["days"]:
        print(f"{row['day']:>4} {row['reference']:>10.5f} {row['treatment']:>10.5f} "
              f"{row['separation']:>+10.5f} {row['cross_seed_sd']:>10.5f}  "
              f"{'✓' if row['clears_noise'] else '·'}")
    print(f"\n判定：{result['verdict']} —— {result['note']}")
    print("提醒：判的是两条曲线的分离，不是某个绝对值；单种子结果一律不算数。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
