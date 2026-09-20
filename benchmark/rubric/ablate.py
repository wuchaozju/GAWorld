"""Negative controls N1-N8: deliberately corrupt a unit so that a working
rubric item *must* score it lower.

This is the load-bearing part of the method. A rubric item that scores the
corrupted unit as highly as the real one is measuring nothing, and gets dropped
in aggregate.py rather than quietly inflating a dimension.

Every operator takes a unit and returns a deep-copied, corrupted unit with the
same ``unit_id`` (so real/ablated pairs line up).
"""

import copy
import random


def _copy(unit: dict) -> dict:
    return copy.deepcopy(unit)


def _episode_lists(unit: dict) -> list[list[dict]]:
    """All episode lists in a unit, whatever its kind.

    agent_day/trajectory hold a list; cohort holds {agent_id: [...]};
    world_slice holds by_agent; dyad holds two lists.
    """
    out = []
    eps = unit.get("episodes")
    if isinstance(eps, list):
        out.append(eps)
    elif isinstance(eps, dict):
        out.extend(v for v in eps.values() if isinstance(v, list))
    for key in ("episodes_a", "episodes_b"):
        if isinstance(unit.get(key), list):
            out.append(unit[key])
    if isinstance(unit.get("by_agent"), dict):
        out.extend(v for v in unit["by_agent"].values() if isinstance(v, list))
    return out


def n1_shuffle_recollections(unit: dict, rng: random.Random, pool: list | None = None) -> dict:
    """Replace recollections with other agents' memories -> R1.1 must drop."""
    out = _copy(unit)
    donors = list(pool or [])
    for eps in _episode_lists(out):
        for ep in eps:
            if ep.get("recollections"):
                ep["recollections"] = (
                    rng.sample(donors, min(len(ep["recollections"]), len(donors)))
                    if donors else ["（记不清了，大概是上个月的事）"])
    return out


def n2_swap_persona(unit: dict, rng: random.Random, pool: list | None = None) -> dict:
    """Attach someone else's profile to this behaviour -> R1.2/R1.3 must drop."""
    out = _copy(unit)
    others = [p for p in (pool or []) if p and p != unit.get("profile")]
    out["profile"] = rng.choice(others) if others else None
    return out


def n3_shuffle_days(unit: dict, rng: random.Random, pool=None) -> dict:
    """Permute day order while keeping day labels -> R2.1/2.2/2.3 must drop."""
    out = _copy(unit)
    # Series are shuffled unconditionally: on a fast-forward trajectory they are
    # the only signal there is, so skipping them would make N3 a no-op.
    out["series"] = _map_series(out.get("series") or {}, lambda s: _shuffle_series(s, rng))
    eps = out.get("episodes")
    if not isinstance(eps, list):
        return out
    days = sorted({int(e.get("day") or 0) for e in eps})
    if len(days) < 3:
        return out
    shuffled = days[:]
    rng.shuffle(shuffled)
    mapping = dict(zip(days, shuffled))
    by_day: dict[int, list] = {}
    for ep in eps:
        by_day.setdefault(int(ep.get("day") or 0), []).append(ep)
    new_eps = []
    for old_day, target in mapping.items():
        for ep in by_day[old_day]:
            clone = copy.deepcopy(ep)
            clone["day"] = target
            new_eps.append(clone)
    out["episodes"] = sorted(new_eps, key=lambda e: (e.get("day", 0), str(e.get("time"))))
    return out


def _map_series(series: dict, fn) -> dict:
    """Apply ``fn`` to a ``{metric: [(step, value)]}`` map.

    Trajectory units hold that shape directly; cohort units nest it one level
    deeper under agent_id.
    """
    if series and all(isinstance(v, dict) for v in series.values()):
        return {a: fn(m) for a, m in series.items()}
    return fn(series)


def _shuffle_series(series: dict, rng: random.Random) -> dict:
    out = {}
    for metric, pairs in series.items():
        values = [v for _, v in pairs]
        rng.shuffle(values)
        out[metric] = [(step, v) for (step, _), v in zip(pairs, values)]
    return out


def n4_duplicate_first_day(unit: dict, rng: random.Random, pool=None) -> dict:
    """Copy day 1 across the whole window -> anything about change must drop."""
    out = _copy(unit)
    eps = out.get("episodes")
    series = out.get("series") or {}
    if isinstance(eps, dict):  # cohort
        out["episodes"] = {a: _replicate_first_day(v) for a, v in eps.items() if v}
    elif isinstance(eps, list) and eps:
        out["episodes"] = _replicate_first_day(eps)
    # Flatten regardless of episodes: a fast-forward trajectory has none.
    out["series"] = _map_series(series, _flatten_series)
    if out.get("diaries"):
        first_day = min(out["diaries"])
        out["diaries"] = {d: out["diaries"][first_day] for d in out["diaries"]}
    return out


def _replicate_first_day(eps: list[dict]) -> list[dict]:
    days = sorted({int(e.get("day") or 0) for e in eps})
    first = [e for e in eps if int(e.get("day") or 0) == days[0]]
    out = []
    for day in days:
        for ep in first:
            clone = copy.deepcopy(ep)
            clone["day"] = day
            out.append(clone)
    return out


def _flatten_series(series: dict) -> dict:
    return {m: [(step, pairs[0][1]) for step, _ in pairs]
            for m, pairs in series.items() if pairs}


def n5_random_walk_growth(unit: dict, rng: random.Random, pool=None) -> dict:
    """Detach growth from anything that happened -> R2.2/2.6/2.7 must drop."""
    out = _copy(unit)
    for eps in _episode_lists(out):
        for ep in eps:
            if isinstance(ep.get("growth_progress"), dict):
                ep["growth_progress"] = {k: max(0.0, min(1.0, rng.random()))
                                         for k in ep["growth_progress"]}
            ep["growth_matches"] = []
    growth = out.get("growth")
    if isinstance(growth, dict):
        for item in growth.get("items", []) or []:
            item["level"] = round(rng.random(), 3)
            item["total_minutes"] = round(rng.random() * 30, 1)
    return out


def n6_rewire_social(unit: dict, rng: random.Random, pool: list | None = None) -> dict:
    """Point interactions at the wrong counterpart -> R3.* must drop."""
    out = _copy(unit)
    candidates = list(pool or [])
    for eps in _episode_lists(out):
        for ep in eps:
            if ep.get("social_partners") and candidates:
                ep["social_partners"] = [rng.choice(candidates)
                                         for _ in ep["social_partners"]]
    return out


def n7_break_budget(unit: dict, rng: random.Random, pool=None) -> dict:
    """Inject teleports, impossible travel times and negative balances."""
    out = _copy(unit)
    for eps in _episode_lists(out):
        for i, ep in enumerate(eps):
            if isinstance(ep.get("delta"), dict):
                ep["delta"] = {k: 0.0 for k in ep["delta"]}   # flat-line affect
            if i == 0 or not ep.get("location"):
                continue
            if i % 2 == 1:
                # impossible travel: blows both the wall-clock gap and the speed
                # limit, whether or not the episode originally had a trip
                ep["travel"] = {"mode": "walk", "minutes": 600, "distance_km": 400.0,
                                "status": "arrived"}
            else:
                # location change with no trip at all -> teleport
                ep["location"] = f"{ep['location']}-远郊分部"
                ep["target_location"] = ep["location"]
                ep["travel"] = {}
    if out.get("ledger"):
        out["ledger"] = dict(out["ledger"])
        out["ledger"]["balance"] = -abs(float(out["ledger"].get("balance") or 1)) - 1
    out["conservation_drift"] = 12345.0
    return out


def n8_strip_events(unit: dict, rng: random.Random, pool=None) -> dict:
    """Remove the shocks while keeping the behaviour -> R2.4/R3.5/R4.4 must drop."""
    out = _copy(unit)
    for eps in _episode_lists(out):
        for ep in eps:
            ep["policy_event"] = ""
            ep["life_events"] = []
            ep["env_events"] = []
    return out


OPERATORS = {
    "N1": n1_shuffle_recollections,
    "N2": n2_swap_persona,
    "N3": n3_shuffle_days,
    "N4": n4_duplicate_first_day,
    "N5": n5_random_walk_growth,
    "N6": n6_rewire_social,
    "N7": n7_break_budget,
    "N8": n8_strip_events,
}


def donor_pool(name: str, data: dict) -> list:
    """Material an operator needs from *other* agents."""
    if name == "N1":
        return [r for eps in data["episodes"].values() for e in eps
                for r in (e.get("recollections") or [])][:200]
    if name == "N2":
        return list(data["profiles"].values())
    if name == "N6":
        return sorted(data["episodes"])
    return []


def apply(name: str, unit: dict, data: dict, *, seed: int = 7) -> dict:
    return OPERATORS[name](unit, random.Random(seed), donor_pool(name, data))
