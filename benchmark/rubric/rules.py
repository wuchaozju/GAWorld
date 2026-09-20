"""Programmatic scoring (``checker: rule``) and fact extraction (``hybrid``).

Anything computable is computed here: it costs no tokens, never drifts between
runs, and gives the LLM judge a factual table instead of asking it to count.
Every function returns the common result shape::

    {"score": 0|1|2|None, "abstain": bool, "evidence": [...], "reasoning": str,
     "facts": {...}}

``score=None`` + ``abstain=True`` means "not enough data", which is excluded
from the denominator rather than scored as a failure.
"""

import json
import math
import re
import statistics
from collections import defaultdict

from .sampler import _partner_ids

# km/h ceilings per travel mode; unknown modes skip the speed check.
SPEED_LIMIT = {
    "walk": 7, "walking": 7, "步行": 7,
    "bike": 25, "bicycle": 25, "e-bike": 30, "ebike": 30, "自行车": 25, "电动车": 30,
    "bus": 45, "公交": 45, "metro": 80, "subway": 80, "地铁": 80,
    "car": 100, "drive": 100, "taxi": 100, "driving": 100, "ride-hailing": 100,
}
DRIFT_TOL = 1e-6


def _res(score, *, abstain=False, evidence=None, reasoning="", facts=None):
    return {"score": score, "abstain": abstain, "evidence": evidence or [],
            "reasoning": reasoning, "facts": facts or {}}


def _abstain(reason, facts=None):
    return _res(None, abstain=True, reasoning=reason, facts=facts)


def _minutes(ep: dict) -> int | None:
    parts = str(ep.get("time") or "").split(":")
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None


# ────────────────────────── R4: world coherence ──────────────────────────

def r4_1_time_budget(unit: dict) -> dict:
    """Travel time must fit in the wall-clock gap between consecutive episodes,
    and total travel must fit in a day. Also catches time going backwards."""
    eps = unit.get("episodes") or []
    if len(eps) < 2:
        return _abstain("当日 episode 少于 2 条，无法检验时间预算")

    total_travel = 0.0
    overflows, backwards = [], []
    prev_t = None
    for ep in eps:
        t = _minutes(ep)
        mins = float((ep.get("travel") or {}).get("minutes") or 0)
        total_travel += mins
        if t is None:
            continue
        if prev_t is not None:
            if t < prev_t:
                backwards.append(f"{ep.get('time')} 早于前一条 {prev_t // 60:02d}:{prev_t % 60:02d}")
            elif mins > (t - prev_t) + 1e-9:
                overflows.append(
                    f"{ep.get('time')} 通勤 {mins:.0f} 分钟 > 与上一事件间隔 {t - prev_t} 分钟")
        prev_t = t

    facts = {"total_travel_minutes": round(total_travel, 1),
             "n_overflow": len(overflows), "n_backwards": len(backwards)}
    if backwards or total_travel > 24 * 60:
        return _res(0, evidence=(backwards or [f"全天通勤 {total_travel:.0f} 分钟"]),
                    reasoning="时序倒流或全天通勤超 24 小时", facts=facts)
    if overflows:
        # ≤10% of transitions over budget counts as minor.
        ratio = len(overflows) / max(1, len(eps) - 1)
        return _res(1 if ratio <= 0.10 else 0, evidence=overflows[:3],
                    reasoning=f"{len(overflows)} 处通勤时长超出事件间隔", facts=facts)
    return _res(2, reasoning="无超支", facts=facts)


def r4_2_reachability(unit: dict) -> dict:
    """Location changes need a travel record; implied speed must be plausible."""
    eps = unit.get("episodes") or []
    if len(eps) < 2:
        return _abstain("当日 episode 少于 2 条，无法检验空间可达")

    teleports, speeding, hard_speeding = [], [], []
    prev_loc = None
    for ep in eps:
        loc = ep.get("location")
        travel = ep.get("travel") or {}
        if prev_loc is not None and loc and loc != prev_loc:
            if not travel or not travel.get("minutes"):
                teleports.append(f"{ep.get('time')} {prev_loc} → {loc} 无通勤记录")
            else:
                dist = float(travel.get("distance_km") or 0)
                mins = float(travel.get("minutes") or 0)
                limit = SPEED_LIMIT.get(str(travel.get("mode") or "").lower())
                if limit and mins > 0 and dist > 0:
                    speed = dist / (mins / 60.0)
                    if speed > limit * 2:
                        hard_speeding.append(
                            f"{ep.get('time')} {travel.get('mode')} {speed:.0f} km/h > 上限 {limit} 的 2 倍")
                    elif speed > limit:
                        speeding.append(
                            f"{ep.get('time')} {travel.get('mode')} {speed:.0f} km/h > 上限 {limit}")
        if loc:
            prev_loc = loc

    facts = {"n_teleport": len(teleports), "n_speeding": len(speeding),
             "n_hard_speeding": len(hard_speeding)}
    if teleports or hard_speeding:
        return _res(0, evidence=(teleports + hard_speeding)[:3],
                    reasoning="存在瞬移或严重超速", facts=facts)
    if speeding:
        return _res(1 if len(speeding) <= 1 else 0, evidence=speeding[:3],
                    reasoning=f"{len(speeding)} 处轻微超速", facts=facts)
    return _res(2, reasoning="全部地点变更均自洽", facts=facts)


def r4_3_affordability(unit: dict) -> dict:
    """Negative balances and conservation drift are hard failures."""
    ledger = unit.get("ledger")
    if not ledger:
        return _abstain("缺 daily_ledger 记录")

    balance = float(ledger.get("balance") or 0)
    expense = float(ledger.get("expense") or 0)
    income = float(ledger.get("income") or 0)
    drift = unit.get("conservation_drift")
    facts = {"balance": balance, "expense": expense, "income": income, "drift": drift}

    negative = [k for k in ("balance", "checking", "savings", "investment")
                if isinstance(ledger.get(k), float) and ledger[k] < -1e-9]
    if negative:
        return _res(0, evidence=[f"{k}={ledger[k]}" for k in negative],
                    reasoning="出现负余额", facts=facts)
    if drift is not None and abs(drift) > DRIFT_TOL:
        return _res(0, evidence=[f"当日守恒 drift={drift}"],
                    reasoning="货币守恒审计漂移超容差", facts=facts)
    if drift is None:
        return _res(1, reasoning="余额为正，但缺守恒审计数据", facts=facts)
    return _res(2, reasoning="余额为正且守恒 drift = 0", facts=facts)


def r4_6_facts(unit: dict) -> dict:
    """Hybrid: detect hard same-timestamp-two-places conflicts for the judge."""
    eps = unit.get("episodes") or []
    seen: dict[int, set] = defaultdict(set)
    for ep in eps:
        t = _minutes(ep)
        if t is not None and ep.get("location"):
            seen[t].add(ep["location"])
    conflicts = [f"{t // 60:02d}:{t % 60:02d} 同时出现在 {sorted(locs)}"
                 for t, locs in sorted(seen.items()) if len(locs) > 1]
    return _res(None, evidence=conflicts[:3], facts={"n_conflicts": len(conflicts)})


# ────────────────────────── R2: evolution ──────────────────────────

def _mann_kendall(values: list[float]) -> tuple[float, float]:
    """Return (tau, two-sided p) using the normal approximation. n<4 -> (0,1)."""
    n = len(values)
    if n < 4:
        return 0.0, 1.0
    s = sum(1 if values[j] > values[i] else (-1 if values[j] < values[i] else 0)
            for i in range(n - 1) for j in range(i + 1, n))
    var = n * (n - 1) * (2 * n + 5) / 18.0
    if var <= 0:
        return 0.0, 1.0
    z = (s - math.copysign(1, s)) / math.sqrt(var) if s != 0 else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    tau = 2.0 * s / (n * (n - 1))
    return tau, p


def _amplitude_ratio(values: list[float]) -> float:
    """|net change| / step-noise. >1 means the trend beats the jitter."""
    if len(values) < 3:
        return 0.0
    diffs = [abs(b - a) for a, b in zip(values, values[1:])]
    noise = statistics.mean(diffs) if diffs else 0.0
    return abs(values[-1] - values[0]) / noise if noise > 1e-12 else 0.0


def _trajectory_series(unit: dict) -> dict[str, list[float]]:
    """Daily series worth trend-testing: growth levels + core state metrics."""
    out: dict[str, list[float]] = {}
    for metric, pairs in (unit.get("series") or {}).items():
        if metric in ("emotion", "econ_security", "stress", "city_identity"):
            out[f"state:{metric}"] = [v for _, v in pairs]
    # Growth exposes only the final level, so reconstruct a proxy series from
    # per-day growth_progress in episodes when present.
    per_day: dict[str, dict[int, float]] = defaultdict(dict)
    for ep in unit.get("episodes") or []:
        day = int(ep.get("day") or 0)
        prog = ep.get("growth_progress")
        if isinstance(prog, dict):
            for name, val in prog.items():
                try:
                    per_day[name][day] = float(val)
                except (TypeError, ValueError):
                    continue
    for name, days in per_day.items():
        if len(days) >= 4:
            out[f"growth:{name}"] = [days[d] for d in sorted(days)]
    return out


def r2_1_nontrivial_trajectory(unit: dict, *, min_days: int = 30) -> dict:
    n_days = unit.get("n_days")
    if n_days is None:
        n_days = len({int(e.get("day") or 0) for e in unit.get("episodes") or []})
    if n_days < min_days:
        return _abstain(f"轨迹仅 {n_days} 天 < 要求的 {min_days} 天")
    series = _trajectory_series(unit)
    if not series:
        return _abstain("无可做趋势检验的序列")

    detail, n_sig = {}, 0
    for name, values in series.items():
        tau, p = _mann_kendall(values)
        amp = _amplitude_ratio(values)
        sig = bool(p < 0.05 and amp > 1.0)
        n_sig += sig
        detail[name] = {"tau": round(tau, 3), "p": round(p, 4),
                        "amplitude_ratio": round(amp, 2), "significant": sig}
    ratio = n_sig / len(series)
    facts = {"n_series": len(series), "n_significant": n_sig, "detail": detail}
    evidence = [f"{k}: tau={v['tau']} p={v['p']} 幅噪比={v['amplitude_ratio']}"
                for k, v in list(detail.items())[:3]]
    score = 2 if ratio >= 0.5 else (1 if n_sig > 0 else 0)
    return _res(score, evidence=evidence,
                reasoning=f"{n_sig}/{len(series)} 条序列存在显著且超噪声的趋势", facts=facts)


def r2_5_divergence(unit: dict) -> dict:
    """Cross-agent variance should grow, not shrink, over time."""
    series = unit.get("series") or {}
    metrics = ("emotion", "econ_security", "stress", "city_identity")
    rising, falling, detail = 0, 0, {}
    for metric in metrics:
        early, late = [], []
        for _, per_metric in series.items():
            pairs = per_metric.get(metric) or []
            if len(pairs) < 6:
                continue
            cut = len(pairs) // 3
            early.append(statistics.mean(v for _, v in pairs[:cut]))
            late.append(statistics.mean(v for _, v in pairs[-cut:]))
        if len(early) < 3:
            continue
        v0, v1 = statistics.pvariance(early), statistics.pvariance(late)
        detail[metric] = {"var_early": round(v0, 5), "var_late": round(v1, 5)}
        if v1 > v0 * 1.1:
            rising += 1
        elif v1 < v0 * 0.9:
            falling += 1
    if not detail:
        return _abstain("参与比较的 agent 或时间点不足")
    facts = {"detail": detail, "n_rising": rising, "n_falling": falling}
    evidence = [f"{k}: var {v['var_early']} → {v['var_late']}" for k, v in detail.items()]
    score = 2 if rising > falling else (0 if falling > rising else 1)
    return _res(score, evidence=evidence,
                reasoning=f"{rising} 个指标方差上升，{falling} 个下降", facts=facts)


def r2_2_facts(unit: dict) -> dict:
    """Hybrid: locate jump points and whether an episode/event sits nearby."""
    series = _trajectory_series(unit)
    jumps = []
    for name, values in series.items():
        if len(values) < 4:
            continue
        diffs = [b - a for a, b in zip(values, values[1:])]
        sd = statistics.pstdev(diffs) or 0.0
        for i, d in enumerate(diffs):
            if sd > 1e-12 and abs(d) > 3 * sd:
                jumps.append({"series": name, "day_index": i + 1, "delta": round(d, 4)})
    days_with_event = sorted({int(e.get("day") or 0) for e in unit.get("episodes") or []
                              if e.get("policy_event") or e.get("life_events") or e.get("env_events")})
    days_with_practice = sorted({int(e.get("day") or 0) for e in unit.get("episodes") or []
                                 if e.get("growth_matches")})
    return _res(None, facts={"jumps": jumps[:10], "n_jumps": len(jumps),
                             "days_with_event": days_with_event[:20],
                             "days_with_growth_practice": days_with_practice[:20]})


def r2_4_facts(unit: dict) -> dict:
    """Hybrid: for each shock day, did activities change and did it persist?"""
    eps = unit.get("episodes") or []
    by_day: dict[int, list[dict]] = defaultdict(list)
    for ep in eps:
        by_day[int(ep.get("day") or 0)].append(ep)
    shock_days = [d for d, v in by_day.items()
                  if any(e.get("policy_event") or e.get("life_events") for e in v)]
    report = []
    for d in sorted(shock_days):
        before = {e.get("final_activity") for e in by_day.get(d - 1, [])}
        during = {e.get("final_activity") for e in by_day.get(d, [])}
        after = {e.get("final_activity") for e in by_day.get(d + 1, [])}
        after2 = {e.get("final_activity") for e in by_day.get(d + 2, [])}
        report.append({
            "day": d,
            "changed_on_day": bool(during - before),
            "persisted_next_day": bool((during - before) & after),
            "persisted_2_days": bool((during - before) & after2),
        })
    return _res(None, facts={"shock_days": sorted(shock_days)[:20], "response": report[:10]})


def r2_6_facts(unit: dict) -> dict:
    """Hybrid: monotone-only growth curves are the failure mode; find plateaus
    and declines."""
    detail = {}
    for name, values in _trajectory_series(unit).items():
        if not name.startswith("growth:") or len(values) < 4:
            continue
        diffs = [b - a for a, b in zip(values, values[1:])]
        detail[name] = {
            "monotone_nondecreasing": all(d >= -1e-12 for d in diffs),
            "n_plateau": sum(1 for d in diffs if abs(d) < 1e-9),
            "n_decline": sum(1 for d in diffs if d < -1e-9),
        }
    return _res(None, facts={"growth_curves": detail})


def r2_7_facts(unit: dict) -> dict:
    """Hybrid: level gained per practice hour, for the judge to sanity-check."""
    growth = unit.get("growth") or {}
    rows = []
    for item in growth.get("items", []) or []:
        minutes = float(item.get("total_minutes") or 0)
        level = float(item.get("level") or 0)
        rows.append({
            "name": item.get("name"), "kind": item.get("kind"),
            "level": round(level, 3), "total_minutes": minutes,
            "level_per_hour": round(level / (minutes / 60.0), 4) if minutes > 0 else None,
        })
    return _res(None, facts={"skills": rows[:15]})


# ────────────────────────── R3: social ──────────────────────────

def r3_1_reciprocity(unit: dict) -> dict:
    """A claims an interaction with B on day d; does B's log agree?"""
    episodes = unit.get("episodes") or {}
    claims, matched = 0, 0
    misses = []
    for aid, eps in episodes.items():
        for ep in eps:
            day = int(ep.get("day") or 0)
            for partner in _partner_ids(ep.get("social_partners")):
                if partner not in episodes:
                    continue  # partner not simulated/exported -> not a claim we can test
                claims += 1
                back = any(int(pe.get("day") or 0) == day and aid in _partner_ids(pe.get("social_partners"))
                           for pe in episodes[partner])
                if back:
                    matched += 1
                elif len(misses) < 3:
                    misses.append(f"day {day}: agent {aid} 记录了与 {partner} 的互动，对方无对应记录")
    if claims == 0:
        return _abstain("样本中没有可双向核对的社交记录（social_partners 全为空）",
                        facts={"claims": 0})
    rate = matched / claims
    facts = {"claims": claims, "matched": matched, "reciprocity_rate": round(rate, 3)}
    score = 2 if rate >= 0.6 else (1 if rate >= 0.3 else 0)
    return _res(score, evidence=misses, reasoning=f"双向匹配率 {rate:.2f}", facts=facts)


def r3_2_facts(unit: dict) -> dict:
    """Hybrid: repeat-interaction counts, so the judge can tell whether the
    text treats a 10th meeting like a first."""
    a_eps, b_eps = unit.get("episodes_a") or [], unit.get("episodes_b") or []
    days = sorted({int(e.get("day") or 0) for e in a_eps + b_eps})
    return _res(None, facts={"n_interactions": len(a_eps) + len(b_eps),
                             "distinct_days": len(days), "days": days[:20]})


def r3_6_facts(unit: dict) -> dict:
    """Hybrid: connected components of the interaction graph + shared locations,
    so the judge can rule on whether each cluster has a plausible cause."""
    episodes = unit.get("episodes") or {}
    adj: dict[int, set] = defaultdict(set)
    locs: dict[int, set] = defaultdict(set)
    for aid, eps in episodes.items():
        for ep in eps:
            if ep.get("location"):
                locs[aid].add(ep["location"])
            for p in _partner_ids(ep.get("social_partners")):
                if p in episodes:
                    adj[aid].add(p)
                    adj[p].add(aid)
    seen, clusters = set(), []
    for aid in sorted(episodes):
        if aid in seen:
            continue
        stack, comp = [aid], []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj[cur] - seen)
        if len(comp) > 1:
            shared = set.intersection(*[locs[m] for m in comp]) if comp else set()
            clusters.append({"members": sorted(comp), "shared_locations": sorted(shared)[:5]})
    return _res(None, facts={"n_clusters": len(clusters), "clusters": clusters[:8]})


# ────────────────────────── R1: believability ──────────────────────────

_TOKEN_RE = re.compile(r"[一-鿿]{2,}|[A-Za-z]{3,}")


def _tokens(text: str) -> set:
    return set(_TOKEN_RE.findall(text or ""))


def r1_1_facts(unit: dict, prior_episodes: list[dict] | None = None) -> dict:
    """Hybrid: try to ground each recollection in an earlier episode via token
    overlap. The judge then rules on whether the usage is faithful; this only
    supplies "does a matching past event exist at all"."""
    eps = unit.get("episodes") or []
    prior = prior_episodes or []
    prior_text = [(int(p.get("day") or 0),
                   " ".join(str(p.get(k) or "") for k in
                            ("final_activity", "scheduled_activity", "location", "outcome", "reflection")))
                  for p in prior]
    day = unit.get("day")
    prior_text = [(d, t) for d, t in prior_text if day is None or d < day]

    checks = []
    for ep in eps:
        for rec in ep.get("recollections") or []:
            if isinstance(rec, str):
                text = rec
            elif isinstance(rec, dict):
                text = " ".join(str(v) for v in rec.values())
            else:
                text = json.dumps(rec, ensure_ascii=False)
            rt = _tokens(text)
            best, best_day = 0.0, None
            for d, ptext in prior_text:
                pt = _tokens(ptext)
                if not rt or not pt:
                    continue
                jac = len(rt & pt) / len(rt | pt)
                if jac > best:
                    best, best_day = jac, d
            checks.append({"recollection": text[:80], "best_overlap": round(best, 3),
                           "matched_day": best_day, "grounded": best >= 0.10})
    grounded = sum(1 for c in checks if c["grounded"])
    return _res(None, facts={"n_recollections": len(checks),
                             "n_grounded": grounded,
                             "grounded_ratio": round(grounded / len(checks), 3) if checks else None,
                             "checks": checks[:10]})


def r1_4_facts(unit: dict) -> dict:
    """Hybrid: state deltas alongside whether anything happened that day."""
    rows = []
    for ep in unit.get("episodes") or []:
        delta = ep.get("delta") or {}
        big = {k: round(float(v), 3) for k, v in delta.items()
               if isinstance(v, (int, float)) and abs(v) >= 0.10}
        rows.append({
            "time": ep.get("time"),
            "n_events": len(ep.get("env_events") or []) + len(ep.get("life_events") or [])
                        + (1 if ep.get("policy_event") else 0),
            "large_deltas": big,
            "max_abs_delta": round(max((abs(float(v)) for v in delta.values()
                                        if isinstance(v, (int, float))), default=0.0), 3),
        })
    flat = all(r["max_abs_delta"] < 1e-6 for r in rows) if rows else False
    return _res(None, facts={"steps": rows[:12], "all_flat": flat})


# Registry consumed by the runner: item id -> (callable, unit kind).
RULE_ITEMS = {
    "R4.1": (r4_1_time_budget, "agent_day"),
    "R4.2": (r4_2_reachability, "agent_day"),
    "R4.3": (r4_3_affordability, "agent_day"),
    "R2.1": (r2_1_nontrivial_trajectory, "trajectory"),
    "R2.5": (r2_5_divergence, "cohort"),
    "R3.1": (r3_1_reciprocity, "cohort"),
}

FACT_ITEMS = {
    "R1.1": (r1_1_facts, "agent_day"),
    "R1.4": (r1_4_facts, "agent_day"),
    "R2.2": (r2_2_facts, "trajectory"),
    "R2.4": (r2_4_facts, "trajectory"),
    "R2.6": (r2_6_facts, "trajectory"),
    "R2.7": (r2_7_facts, "trajectory"),
    "R3.2": (r3_2_facts, "dyad"),
    "R3.6": (r3_6_facts, "cohort"),
    "R4.6": (r4_6_facts, "agent_day"),
}
