"""Stratified sampling of evaluation units (U1-U4) + coverage accounting.

Sampling seed is separate from the simulation seed and is recorded in the
manifest so a scoring run is reproducible independently of the run it scores.
"""

import random
from collections import defaultdict

# Target sample sizes from the design doc §2.2.
TARGETS = {"agent_day": 40, "trajectory": 12, "dyad": 15, "world_slice": 5}


def _terciles(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    s = sorted(values)
    return (s[len(s) // 3], s[(2 * len(s)) // 3])


def _stratify(agent_ids: list[int], episodes: dict) -> dict[str, list[int]]:
    """Strata = activity tercile (episode count). Cheap, data-driven, and does
    not depend on persona metadata that may be absent."""
    counts = {a: len(episodes.get(a, [])) for a in agent_ids}
    lo, hi = _terciles([float(c) for c in counts.values()])
    strata: dict[str, list[int]] = defaultdict(list)
    for a in agent_ids:
        c = counts[a]
        key = "low" if c <= lo else ("mid" if c <= hi else "high")
        strata[key].append(a)
    return strata


def _draw(strata: dict[str, list[int]], n: int, rng: random.Random) -> list[int]:
    """Round-robin across strata so no stratum dominates."""
    pools = {k: rng.sample(v, len(v)) for k, v in strata.items() if v}
    picked: list[int] = []
    while pools and len(picked) < n:
        for key in sorted(pools):
            if not pools[key]:
                continue
            picked.append(pools[key].pop())
            if len(picked) >= n:
                break
        pools = {k: v for k, v in pools.items() if v}
    return picked


def build_units(data: dict, *, seed: int = 42, min_days: int = 30,
                targets: dict | None = None) -> dict:
    """Return {"units": [...], "coverage": {kind: ratio}, "manifest": {...}}."""
    rng = random.Random(seed)
    targets = dict(TARGETS if targets is None else targets)
    episodes = data["episodes"]
    agent_ids = sorted(episodes)
    strata = _stratify(agent_ids, episodes)

    units: list[dict] = []

    # ---- U1 agent_day -----------------------------------------------------
    pairs = [(a, d) for a in agent_ids
             for d in sorted({int(e.get("day") or 0) for e in episodes[a]})]
    rng.shuffle(pairs)
    for aid, day in pairs[: targets["agent_day"]]:
        eps = [e for e in episodes[aid] if int(e.get("day") or 0) == day]
        units.append({
            "unit_id": f"AD:{aid}:{day}", "kind": "agent_day",
            "agent_id": aid, "day": day, "episodes": eps,
            "diary": data["diaries"].get(aid, {}).get(day),
            "profile": data["profiles"].get(aid),
            "ledger": data["ledger"].get((day, aid)),
            "conservation_drift": data["conservation"].get(day),
        })
    n_agent_day = len(pairs)

    # ---- U2 trajectory ----------------------------------------------------
    # Fast-forward runs write no episodes but still write state history, growth
    # and diaries, so trajectories are built from whatever spans enough days.
    traj_agents = sorted(set(agent_ids) | set(data["series"]) | set(data["growth"]))
    long_enough = [a for a in traj_agents if _n_days(data, a) >= min_days]
    for aid in _draw(_stratify(long_enough, episodes), targets["trajectory"], rng):
        units.append({
            "unit_id": f"TR:{aid}", "kind": "trajectory", "agent_id": aid,
            "episodes": episodes.get(aid, []), "growth": data["growth"].get(aid),
            "series": data["series"].get(aid, {}),
            "diaries": data["diaries"].get(aid, {}),
            "profile": data["profiles"].get(aid),
            "n_days": _n_days(data, aid),
        })
    n_trajectory = len(long_enough)

    # ---- U3 dyad ----------------------------------------------------------
    dyads: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for aid, eps in episodes.items():
        for ep in eps:
            for partner in _partner_ids(ep.get("social_partners")):
                if partner in episodes:
                    dyads[tuple(sorted((aid, partner)))].append(ep)
    dyad_keys = sorted(dyads)
    rng.shuffle(dyad_keys)
    for key in dyad_keys[: targets["dyad"]]:
        a, b = key
        units.append({
            "unit_id": f"DY:{a}-{b}", "kind": "dyad", "pair": [a, b],
            "episodes_a": [e for e in episodes[a] if _mentions(e, b)],
            "episodes_b": [e for e in episodes[b] if _mentions(e, a)],
        })
    n_dyad = len(dyad_keys)

    # ---- U4 world_slice ---------------------------------------------------
    days = sorted({int(e.get("day") or 0) for eps in episodes.values() for e in eps})
    rng.shuffle(days)
    for day in days[: targets["world_slice"]]:
        by_agent = {a: [e for e in eps if int(e.get("day") or 0) == day]
                    for a, eps in episodes.items()}
        units.append({
            "unit_id": f"WS:{day}", "kind": "world_slice", "day": day,
            "by_agent": {a: v for a, v in by_agent.items() if v},
        })
    n_world = len(days)

    # ---- U5 cohort (single synthetic unit spanning everyone) --------------
    units.append({
        "unit_id": "CH:all", "kind": "cohort",
        "episodes": episodes, "series": data["series"],
        "profiles": data["profiles"],
    })

    available = {"agent_day": n_agent_day, "trajectory": n_trajectory,
                 "dyad": n_dyad, "world_slice": n_world}
    coverage = {k: (min(1.0, available[k] / targets[k]) if targets[k] else 0.0)
                for k in targets}
    # The cohort unit spans everyone the run produced anything for, which in a
    # fast-forward run is the state-history agents rather than episode agents.
    coverage["cohort"] = 1.0 if traj_agents else 0.0

    return {
        "units": units,
        "coverage": coverage,
        "manifest": {
            "sample_seed": seed, "min_days": min_days, "targets": targets,
            "available": available, "n_agents": len(agent_ids),
            "strata_sizes": {k: len(v) for k, v in strata.items()},
        },
    }


def _n_days(data: dict, agent_id: int) -> int:
    """Span of an agent's record in days.

    Episodes carry an explicit ``day``. Without them (fast-forward), fall back
    to the state history, which appends one point per agent per day in that
    mode; diaries are the last resort.
    """
    eps = (data.get("episodes") or {}).get(agent_id) or []
    if eps:
        return len({int(e.get("day") or 0) for e in eps})
    series = (data.get("series") or {}).get(agent_id) or {}
    if series:
        return max((len(v) for v in series.values()), default=0)
    return len((data.get("diaries") or {}).get(agent_id) or {})


def _partner_ids(raw) -> list[int]:
    """social_partners may hold ints, {"agent_id": n} dicts, or names."""
    out = []
    for p in raw or []:
        if isinstance(p, int):
            out.append(p)
        elif isinstance(p, dict):
            for key in ("agent_id", "id", "partner_id"):
                if isinstance(p.get(key), int):
                    out.append(p[key])
                    break
        elif isinstance(p, str) and p.strip().lstrip("-").isdigit():
            out.append(int(p.strip()))
    return out


def _mentions(ep: dict, agent_id: int) -> bool:
    return agent_id in _partner_ids(ep.get("social_partners"))
