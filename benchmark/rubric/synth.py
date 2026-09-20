"""Synthetic fixtures: a structurally-correct, deliberately *well-behaved* world.

Used by ``--synthetic`` to exercise the whole pipeline without an LLM or a
simulation run, and as the positive half of the discrimination check: the rule
items should score this near the top, and score its ablated twin near the
bottom. If they don't, the harness itself is broken.
"""

import random

from . import loader

LOCATIONS = ["Building C-02", "Central Block", "South Block", "Willow Design Studio",
             "River Park", "Night Market"]
MODES = [("walk", 5.0), ("e-bike", 18.0), ("bus", 25.0), ("metro", 40.0)]
SKILLS = ["沟通表达", "数据分析", "烘焙"]


def build(n_agents: int = 8, n_days: int = 35, seed: int = 1) -> dict:
    rng = random.Random(seed)
    episodes, growth, diaries, series, ledger, conservation, profiles = {}, {}, {}, {}, {}, {}, {}

    shock_days = {12, 25}
    for aid in range(1, n_agents + 1):
        levels = {s: 0.10 + 0.05 * rng.random() for s in SKILLS}
        agent_eps, agent_diaries = [], {}
        emotion, econ = 0.55 + 0.1 * rng.random(), 0.5 + 0.2 * rng.random()
        metrics = {"emotion": [], "econ_security": [], "stress": [], "city_identity": []}
        balance = 20000 + 5000 * rng.random()

        for day in range(1, n_days + 1):
            clock = 8 * 60 + rng.randint(0, 30)
            loc = LOCATIONS[0]
            shocked = day in shock_days
            for slot in range(3):
                target = LOCATIONS[rng.randrange(len(LOCATIONS))]
                mode, speed = MODES[rng.randrange(len(MODES))]
                dist = round(1.0 + 6.0 * rng.random(), 3)
                minutes = max(4, int(dist / speed * 60))
                clock += minutes + rng.randint(40, 120)
                if clock >= 23 * 60:
                    break

                skill = SKILLS[(day + slot) % len(SKILLS)]
                # Growth: rising, but with plateaus and an occasional setback so
                # R2.6 has something real to find.
                if rng.random() < 0.65:
                    levels[skill] = min(1.0, levels[skill] + 0.004 + 0.004 * rng.random())
                elif rng.random() < 0.15:
                    levels[skill] = max(0.0, levels[skill] - 0.006)

                # Per-agent persistent drift, so the cohort fans out over time
                # (that is what R2.5 looks for).
                drift = (aid - n_agents / 2.0) * 0.0015
                d_emotion = (-0.18 if shocked else rng.uniform(-0.04, 0.05) + drift)
                d_econ = (-0.12 if shocked else rng.uniform(-0.02, 0.03) + drift)
                before = {"emotion": round(emotion, 4), "econ_security": round(econ, 4)}
                emotion = max(0.0, min(1.0, emotion + d_emotion))
                econ = max(0.0, min(1.0, econ + d_econ))

                partner = None
                if rng.random() < 0.4:
                    partner = rng.choice([a for a in range(1, n_agents + 1) if a != aid])

                agent_eps.append({
                    "episode_id": f"{aid}-{day}-{slot}",
                    "day": day, "time": f"{clock // 60:02d}:{clock % 60:02d}",
                    "location": target, "target_location": target,
                    "travel": {"mode": mode, "distance_km": dist, "minutes": minutes,
                               "status": "arrived", "cost": round(dist * 0.1, 2)},
                    "scheduled_activity": f"练习{skill}",
                    "final_activity": (f"改到室内练习{skill}" if shocked else f"练习{skill}"),
                    "action": f"在{target}练习{skill}",
                    "change_reason": ("受当日冲击影响，改为低强度的室内安排" if shocked else ""),
                    "decision_driver": "成长目标" if not shocked else "风险规避",
                    "need_snapshot": {"energy": round(rng.random(), 3),
                                      "social_need": round(rng.random(), 3)},
                    "recollections": ([f"上次在{loc}练习{skill}的感觉"] if day > 1 else []),
                    "growth_progress": {s: round(v, 4) for s, v in levels.items()},
                    "growth_matches": [skill] if rng.random() < 0.7 else [],
                    "social_partners": [partner] if partner else [],
                    "env_events": ([f"第{day}天的强降水"] if shocked else []),
                    "policy_event": ("临时交通管制" if shocked else ""),
                    "life_events": [],
                    "state_before": before,
                    "state_after": {"emotion": round(emotion, 4), "econ_security": round(econ, 4)},
                    "delta": {"emotion": round(emotion - before["emotion"], 4),
                              "econ_security": round(econ - before["econ_security"], 4)},
                    "plan_struct": {"goal": f"推进{skill}", "constraint": "时间有限"},
                    "reflection": f"第{day}天在{target}的{skill}练习{'被打断' if shocked else '还算顺利'}",
                    "perception": f"第{day}天{'路面湿滑' if shocked else '天气普通'}",
                })
                loc = target

            metrics["emotion"].append((day, round(emotion, 4)))
            metrics["econ_security"].append((day, round(econ, 4)))
            metrics["stress"].append((day, round(1 - emotion, 4)))
            metrics["city_identity"].append((day, round(0.5 + 0.004 * day * (aid % 3), 4)))

            income = round(200 + 100 * rng.random(), 2)
            expense = round(150 + 80 * rng.random(), 2)
            balance += income - expense
            ledger[(day, aid)] = {"day": float(day), "agent_id": float(aid),
                                  "income": income, "expense": expense,
                                  "net": round(income - expense, 2),
                                  "balance": round(balance, 2)}
            conservation[day] = 0.0
            agent_diaries[day] = (f"# 第{day}天\n今天主要在{loc}，"
                                  f"{'因为天气改了安排' if shocked else '按计划推进了练习'}。"
                                  f"{'不过效率不高，晚上有点懊恼。' if day % 4 == 0 else ''}")

        episodes[aid] = agent_eps
        diaries[aid] = agent_diaries
        series[aid] = metrics
        growth[aid] = {"agent_id": aid, "items": [
            {"name": s, "kind": "skill", "level": round(levels[s], 3),
             "total_minutes": round(600 + 400 * rng.random(), 1)} for s in SKILLS]}
        profiles[aid] = f"**基础信息**：受访者 {aid}，从事与{SKILLS[aid % len(SKILLS)]}相关的工作。"

    # Make social claims reciprocal, which is what R3.1 tests for.
    _make_reciprocal(episodes)

    data = {"output_dir": "<synthetic>", "run_mode": "full", "episodes": episodes,
            "growth": growth, "diaries": diaries, "series": series, "ledger": ledger,
            "conservation": conservation, "profiles": profiles}
    data["capabilities"] = loader.capabilities(data)
    return data


def build_fast_forward(n_agents: int = 8, n_days: int = 35, seed: int = 1) -> dict:
    """What a ``run --fast-forward`` leaves behind: state history, growth,
    ledger and template diaries, but no intra-day episodes.

    Used to test that the capability gate abstains on R1/R3/R4 instead of
    scoring them 0, and that R2 still finds trajectories without episodes.
    """
    data = build(n_agents=n_agents, n_days=n_days, seed=seed)
    data["run_mode"] = "fast_forward"
    data["episodes"] = {}
    # Fast-forward appends one state point per agent per day, not per tick.
    data["series"] = {a: {m: [(d, v) for d, v in pairs[:n_days]]
                          for m, pairs in metrics.items()}
                      for a, metrics in data["series"].items()}
    data["capabilities"] = loader.capabilities(data)
    return data


def _make_reciprocal(episodes: dict) -> None:
    for aid, eps in episodes.items():
        for ep in eps:
            for partner in ep.get("social_partners") or []:
                day = ep["day"]
                peer_eps = [p for p in episodes.get(partner, []) if p["day"] == day]
                if peer_eps and aid not in (peer_eps[0].get("social_partners") or []):
                    peer_eps[0].setdefault("social_partners", []).append(aid)
