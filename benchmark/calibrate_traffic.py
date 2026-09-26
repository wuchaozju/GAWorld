"""Calibrate ``traffic.agents_represent`` against the commute-time anchor.

The simulated population is a *sample* of a real town, so the raw number of
simulated vehicles is far below what a real road carries: at
``agents_represent = 1`` the volume/capacity ratio is ~0 and no road ever
congests. This sweep answers "what value puts commute times in the right
range on this map", which is the one number the traffic layer cannot pick
for itself.

What this is and is not
-----------------------
This is a **mechanism harness, not a simulation**. It runs the real map, the
real home/workplace inference, the real mode choice and the real
``travel_plan`` — but it *imposes* a departure-time distribution instead of
reading one out of LLM-generated schedules, so it is deliberately usable
without an LLM budget.

That has a consequence worth being blunt about: because departure times are
an input here, **the double peak in the trip-time profile is an input too**.
This harness can calibrate Track A's commute-time anchor. It cannot be used
to claim Track B's bimodality has emerged — that needs a real run.

Usage
-----
    python -m benchmark.calibrate_traffic --profiles <profiles.md>
    python -m benchmark.calibrate_traffic --profiles ... --represent 1,25,50,100
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gaworld.sim._location import assign_agent_locations  # noqa: E402
from gaworld.sim.agents_loader import parse_profile  # noqa: E402
from gaworld.world import city_map as cm  # noqa: E402
from gaworld.world import traffic as tf  # noqa: E402

# 中国县城家庭拥车率约 45-50%；按人计的口径低于按户，这里只作量级参照。
CAR_OWNERSHIP_REFERENCE = 0.35

# ⚠️ 口径不符：下面三个数都是**全杭州**口径，而这张图是滨江一带约 19×15 km 的
# **一个片区**。实测片区能复现「5 公里以内通勤比重」52%，但通勤距离均值最多 5.94 km，
# 够不着全市的 8.1 km——19 公里的图上没有那条尾巴。所以它们在这里只作**参照量级**，
# 不是判据；Bench 里已标为 scope=city_wide、只报告不打分（提案 §15）。
COMMUTE_ANCHOR_MINUTES = 34.5      # 全市，仅参照
COMMUTE_ANCHOR_KM = 8.1            # 全市，仅参照
WITHIN_5KM_REFERENCE = 0.52        # 全市；片区实测可复现到 52.3%

# Job text that means this resident does not make a daily commute.
NON_COMMUTING = ("退休", "无业", "失业", "待业", "自由职业", "全职妈妈", "家庭主妇")


def load_agents(profiles_path: Path) -> list[dict]:
    text = profiles_path.read_text(encoding="utf-8")
    agents = []
    for index, block in enumerate(text.split("## Profile ")[1:], start=1):
        try:
            profile = parse_profile("## Profile " + block)
        except (AttributeError, ValueError):
            continue  # a malformed block is not worth failing the sweep over
        profile["id"] = index
        agents.append(profile)
    return agents


def commuters(agents: list[dict], city_map, seed: int) -> list[dict]:
    """Agents with a home and a distinct workplace, with locations assigned."""
    random.seed(seed)  # _infer_home picks randomly among central blocks
    # Mode choice needs to know who can drive; in a real run the
    # CarOwnershipPlugin does this on agents.built.
    tf.assign_car_ownership(agents, rng=random.Random(f"car_ownership:{seed}"))
    tf.assign_two_wheeler_ownership(
        agents, rng=random.Random(f"two_wheeler_ownership:{seed}"))
    out = []
    for agent in agents:
        if any(token in agent.get("job", "") for token in NON_COMMUTING):
            continue
        agent["locations"] = assign_agent_locations(agent, city_map)
        if agent["locations"]["workplace"] != agent["locations"]["home"]:
            out.append(agent)
    return out


def departure_minutes(count: int, peak_min: int, spread_min: float, rng: random.Random) -> list[int]:
    """IMPOSED departure times — see the module docstring. Normal around the
    peak, clipped to a four-hour window so nobody leaves at 3am."""
    lo, hi = peak_min - 120, peak_min + 120
    return [int(min(hi, max(lo, rng.gauss(peak_min, spread_min)))) for _ in range(count)]


def run_wave(city_map, agents, *, represent, step_minutes, peak_min, spread_min, seed, reverse):
    """One commute wave over a tick grid, with congestion fed back a tick late."""
    cm.clear_congestion(city_map)
    rng = random.Random(seed)
    schedule: dict[int, list[dict]] = {}
    for agent, depart in zip(agents, departure_minutes(len(agents), peak_min, spread_min, rng)):
        tick = (depart // step_minutes) * step_minutes
        schedule.setdefault(tick, []).append(agent)

    minutes: list[float] = []
    peak_ratio = 0.0
    for tick in range(min(schedule, default=0), max(schedule, default=0) + step_minutes, step_minutes):
        flows: dict[str, float] = {}
        time_str = f"{tick // 60:02d}:{tick % 60:02d}"
        for agent in schedule.get(tick, []):
            home = agent["locations"]["home"]
            work = agent["locations"]["workplace"]
            origin, target = (work, home) if reverse else (home, work)
            plan = cm.travel_plan(agent, city_map, origin, target, activity="通勤", time_str=time_str)
            minutes.append(plan["travel_minutes"])
            tf.accumulate_travel(
                flows,
                {"mode": plan["mode"], "status": "arrived", "route": plan["route"]},
                agents_represent=represent,
            )
        for key, flow in flows.items():
            a, b = key.split("||") if "||" in key else ("", "")
            capacity = tf.edge_capacity_pcu(city_map, a, b, step_minutes=step_minutes)
            peak_ratio = max(peak_ratio, flow / capacity)
        tf.apply_flows(city_map, flows, step_minutes=step_minutes, decay=0.5)
    return minutes, peak_ratio


def sweep(city_map, agents, values, **kwargs):
    rows = []
    for represent in values:
        morning, ratio_am = run_wave(city_map, agents, represent=represent, reverse=False, **kwargs)
        evening, ratio_pm = run_wave(
            city_map, agents, represent=represent, reverse=True,
            **{**kwargs, "peak_min": kwargs["peak_min"] + 10 * 60},
        )
        trips = morning + evening
        rows.append({
            "agents_represent": represent,
            "trips": len(trips),
            "mean_minutes": round(statistics.mean(trips), 2),
            "median_minutes": round(statistics.median(trips), 2),
            "p90_minutes": round(sorted(trips)[int(0.9 * len(trips))], 2),
            "peak_volume_capacity": round(max(ratio_am, ratio_pm), 3),
        })
    return rows


# 公交机动化分担率 47.6%（杭州口径），Track A 的另一个锚点。
TRANSIT_SHARE_ANCHOR = 0.476
# Motorised modes, for the transit-share anchor: a bicycle is not a car.
MOTORISED = ("bus", "metro", "car", "taxi")
TRANSIT = ("bus", "metro")


def diagnose(city_map, agents, *, represent, step_minutes, peak_min, spread_min, seed):
    """Report what the map and the assignment produce *before* congestion.

    Congestion can only ever make trips slower than free flow, so if the
    free-flow commute is already far off the anchor, no value of
    ``agents_represent`` can rescue it and the gap is somewhere upstream.
    """
    nodes = city_map.get("nodes", {})
    edge_count = sum(len(v) for v in city_map.get("adjacency", {}).values()) // 2

    distances, hops = [], []
    modes: dict[str, int] = {}
    homes: dict[str, int] = {}
    works: dict[str, int] = {}
    for agent in agents:
        home = agent["locations"]["home"]
        work = agent["locations"]["workplace"]
        homes[home] = homes.get(home, 0) + 1
        works[work] = works.get(work, 0) + 1
        plan = cm.travel_plan(agent, city_map, home, work, activity="通勤", time_str="08:00")
        distances.append(plan["distance_km"])
        hops.append(len(plan["route"]))
        modes[plan["mode"]] = modes.get(plan["mode"], 0) + 1

    total = max(1, len(agents))
    motorised = sum(count for mode, count in modes.items() if mode in MOTORISED)
    transit = sum(count for mode, count in modes.items() if mode in TRANSIT)

    # Peak-tick volume/capacity across edges, at the given represent.
    rng = random.Random(seed)
    busiest: dict[str, float] = {}
    schedule: dict[int, list] = {}
    for agent, depart in zip(agents, departure_minutes(len(agents), peak_min, spread_min, rng)):
        schedule.setdefault((depart // step_minutes) * step_minutes, []).append(agent)
    cm.clear_congestion(city_map)
    for tick, riders in sorted(schedule.items()):
        time_str = f"{tick // 60:02d}:{tick % 60:02d}"
        flows: dict[str, float] = {}
        for agent in riders:
            plan = cm.travel_plan(
                agent, city_map, agent["locations"]["home"],
                agent["locations"]["workplace"], activity="通勤", time_str=time_str,
            )
            tf.accumulate_travel(
                flows, {"mode": plan["mode"], "status": "arrived", "route": plan["route"]},
                agents_represent=represent,
            )
        for key, flow in flows.items():
            a, b = key.split("||") if "||" in key else ("", "")
            ratio = flow / tf.edge_capacity_pcu(city_map, a, b, step_minutes=step_minutes)
            busiest[key] = max(busiest.get(key, 0.0), ratio)
        tf.apply_flows(city_map, flows, step_minutes=step_minutes, decay=0.5)

    ratios = sorted(busiest.values(), reverse=True)
    return {
        "nodes": len(nodes), "edges": edge_count, "commuters": len(agents),
        "distance_mean": round(statistics.mean(distances), 2),
        "distance_median": round(statistics.median(distances), 2),
        "distance_p90": round(sorted(distances)[int(0.9 * len(distances))], 2),
        "distance_max": round(max(distances), 2),
        "within_5km": round(sum(1 for x in distances if x <= 5.0) / len(distances), 3),
        "hops_mean": round(statistics.mean(hops), 1),
        "modes": dict(sorted(modes.items(), key=lambda kv: -kv[1])),
        "car_ownership": round(sum(1 for a in agents if a.get("has_car")) / total, 3),
        "motorised_share": round(motorised / total, 3),
        "transit_share_of_motorised": round(transit / motorised, 3) if motorised else 0.0,
        "top_home_share": round(max(homes.values()) / total, 3),
        "top_work_share": round(max(works.values()) / total, 3),
        "edges_used": len(ratios),
        "vc_max": round(ratios[0], 2) if ratios else 0.0,
        "vc_p50": round(statistics.median(ratios), 2) if ratios else 0.0,
        "vc_over_08": sum(1 for r in ratios if r >= 0.8),
    }


def print_diagnosis(d, represent):
    print(f"地图：{d['nodes']} 节点 / {d['edges']} 边；通勤者 {d['commuters']} 人\n")
    print("— 自由流通勤（拥堵只能让它更慢，不能更快）—")
    print(f"  距离 km：均值 {d['distance_mean']} 中位 {d['distance_median']} "
          f"p90 {d['distance_p90']} max {d['distance_max']}；路线平均 {d['hops_mean']} 跳")
    print(f"  5 公里以内 {d['within_5km']:.1%}（全市参照 {WITHIN_5KM_REFERENCE:.0%}）")
    print(f"  出行方式：{d['modes']}")
    print(f"  机动化占比 {d['motorised_share']:.1%}；其中公交/地铁 "
          f"{d['transit_share_of_motorised']:.1%}（锚点 {TRANSIT_SHARE_ANCHOR:.1%}）")
    print(f"  通勤者拥车率 {d['car_ownership']:.1%}（参照量级 {CAR_OWNERSHIP_REFERENCE:.0%}，按人计）")
    print("\n— 分配集中度（小图效应）—")
    print(f"  最大居住地占 {d['top_home_share']:.1%}，最大工作地占 {d['top_work_share']:.1%}")
    print(f"\n— 峰值路段负荷 @ agents_represent={represent:g} —")
    print(f"  被用到的边 {d['edges_used']}/{d['edges']}；v/c 中位 {d['vc_p50']} "
          f"最大 {d['vc_max']}；v/c≥0.8 的边 {d['vc_over_08']} 条")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profiles", required=True, help="Population profiles Markdown")
    parser.add_argument("--map", default="data/citymap.md", help="City map path")
    parser.add_argument("--represent", default="1,10,25,50,100,200",
                        help="Comma-separated agents_represent values to sweep")
    parser.add_argument("--step-minutes", type=int, default=30)
    parser.add_argument("--peak", default="08:00", help="Morning peak, HH:MM")
    parser.add_argument("--spread", type=float, default=45.0,
                        help="Std-dev of the imposed departure times, minutes")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--diagnose", action="store_true",
                        help="Report the free-flow baseline and load spread instead of sweeping")
    parser.add_argument("--diagnose-represent", type=float, default=100.0)
    args = parser.parse_args(argv)

    city_map = cm.load_city_map(args.map)
    agents = commuters(load_agents(Path(args.profiles)), city_map, args.seed)
    if not agents:
        parser.error("no commuting agents parsed from the profiles file")

    hour, minute = (int(part) for part in args.peak.split(":"))

    if args.diagnose:
        report = diagnose(
            city_map, agents,
            represent=args.diagnose_represent, step_minutes=args.step_minutes,
            peak_min=hour * 60 + minute, spread_min=args.spread, seed=args.seed,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_diagnosis(report, args.diagnose_represent)
        return 0

    rows = sweep(
        city_map, agents,
        [float(v) for v in args.represent.split(",")],
        step_minutes=args.step_minutes,
        peak_min=hour * 60 + minute,
        spread_min=args.spread,
        seed=args.seed,
    )

    if args.json:
        print(json.dumps({"anchor_minutes": COMMUTE_ANCHOR_MINUTES, "rows": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"通勤者 {len(agents)} 人 / 地图 {args.map} / 步长 {args.step_minutes} 分钟")
    print(f"参照（全市口径，非判据）：单程通勤 {COMMUTE_ANCHOR_MINUTES} 分钟 / "
          f"{COMMUTE_ANCHOR_KM} km，5km 以内 {WITHIN_5KM_REFERENCE:.0%}\n")
    print(f"{'represent':>10} {'趟数':>6} {'均值':>8} {'中位':>8} {'p90':>8} {'峰值 v/c':>9}  {'与参照':>8}")
    for row in rows:
        delta = row["mean_minutes"] - COMMUTE_ANCHOR_MINUTES
        print(f"{row['agents_represent']:>10.0f} {row['trips']:>6} {row['mean_minutes']:>8.1f} "
              f"{row['median_minutes']:>8.1f} {row['p90_minutes']:>8.1f} "
              f"{row['peak_volume_capacity']:>9.2f}  {delta:>+8.1f}")
    print("\n注意两点：出发时刻是本脚本强加的，不是涌现的，所以不能用来主张 Track B 的双峰；"
          "\n而通勤时长/距离的参照是全市口径，片区跟它对不齐是口径差，不是模型误差（提案 §15）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
