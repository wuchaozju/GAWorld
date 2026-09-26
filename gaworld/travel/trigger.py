"""Who leaves town, and why.

Three purposes, three different drivers. They are deliberately *not* collapsed
into one "trip probability" knob: a business trip, a duty visit to an ageing
parent and a holiday answer to different forces, and a single number would
stand for none of them.

Every driver is a quantity the simulation already maintains:

============ ==================================================== ============
purpose      driver                                               source
============ ==================================================== ============
business     job text, working day                                economy/job
family       relationship ``obligation`` + days since contact      social/network
leisure      weekend, liquid cash, openness, accumulated stress    economy/traits
============ ==================================================== ============

The family trigger is the load-bearing one. ``decay_relationships`` already
raises ``obligation`` on neglected kin ties every single day, and until now
that pressure had no outlet — it could only rise. Here it is spent: going
resets ``last_contact_day``, which lets obligation fall again. That closes a
loop the repo had left open, which is a stronger claim than "we added a
probability".

All decisions are pure and seeded (``rng_for``): the same seed puts the same
resident on the same train on the same day. No LLM call is involved — a
departure must be reproducible across seeds to be analysable.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.personality.traits import traits_of

#: Job keywords that make travel part of the work, in rough descending order
#: of how much. Matched against the agent's job / work-style text.
BUSINESS_JOB_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("销售", 3.0), ("市场", 2.2), ("商务", 2.6), ("采购", 2.4), ("外贸", 3.0),
    ("咨询", 2.6), ("审计", 2.4), ("记者", 2.2), ("工程", 1.6), ("项目", 1.8),
    ("研究", 1.4), ("教授", 1.4), ("博士", 1.2), ("经理", 1.6), ("总监", 2.0),
    ("创业", 2.0), ("投资", 2.2), ("物流", 2.0), ("培训", 1.8),
)

#: Roles whose ties can pull someone out of town to visit in person. Mirrors
#: the ``"visit"`` channel already declared in ``social/network.py``.
VISITABLE_ROLES: frozenset[str] = frozenset({
    "mother", "father", "parent", "grandparent", "sibling",
    "best_friend", "close_friend", "friend", "mentor",
})


def rng_for(seed: Any, agent_id: Any, day: Any, stream: str) -> random.Random:
    """A deterministic stream for one agent, one day, one decision."""
    return random.Random(f"{seed}::{agent_id}::{day}::travel::{stream}")


def _blob(agent: dict[str, Any], *keys: str) -> str:
    return " ".join(str(agent.get(k, "") or "") for k in keys)


def business_weight(agent: dict[str, Any]) -> float:
    """How travel-heavy this job is; ``1.0`` for an ordinary one."""
    blob = _blob(agent, "job", "work_style", "daily_life")
    weight = 1.0
    for keyword, w in BUSINESS_JOB_WEIGHTS:
        if keyword in blob:
            weight = max(weight, w)
    return weight


def _liquid_months(agent: dict[str, Any]) -> float:
    """Liquid savings measured in months of spending; ``0.0`` without economy."""
    econ = agent.get("economy")
    if not isinstance(econ, dict):
        return 0.0
    accounts = econ.get("accounts", {})
    if not isinstance(accounts, dict):
        return 0.0
    liquid = float(accounts.get("checking", 0) or 0) + float(accounts.get("savings", 0) or 0)
    monthly = float(econ.get("monthly_expense_estimate", 0) or 0)
    if monthly <= 0:
        return 0.0
    return liquid / monthly


def visitable_ties(agent: dict[str, Any], day: int) -> list[tuple[str, dict[str, Any], float]]:
    """Off-screen ties worth travelling for, as ``(key, record, pressure)``.

    Pressure combines standing obligation with how long the tie has been left
    alone — the two axes ``decay_relationships`` moves. In-sim agents are
    excluded: they live in this city, so seeing them is not a journey.
    """
    relationships = agent.get("relationships")
    if not isinstance(relationships, dict):
        return []
    out: list[tuple[str, dict[str, Any], float]] = []
    for key, rel in relationships.items():
        if not isinstance(rel, dict) or rel.get("kind") != "ghost":
            continue
        if str(rel.get("role", "")) not in VISITABLE_ROLES:
            continue
        obligation = float(rel.get("obligation", 0.0) or 0.0)
        silent_days = max(0, int(day) - int(rel.get("last_contact_day", 0) or 0))
        pressure = obligation + min(0.25, silent_days * 0.005)
        out.append((str(key), rel, pressure))
    out.sort(key=lambda e: (-e[2], e[0]))
    return out


def decide(
    agent: dict[str, Any],
    day: int,
    *,
    is_weekend: bool,
    cfg: dict[str, Any],
    seed: Any,
) -> dict[str, Any] | None:
    """Should this agent leave town today? Returns the intent, or ``None``.

    The intent names the purpose, how many days, and (for a family visit) the
    tie that pulled — the destination itself is resolved later, against the
    map, by :mod:`~gaworld.travel.destination`.
    """
    agent_id = agent.get("id")

    # -- family visit: spend the obligation the social layer has accumulated.
    fam_cfg = cfg.get("family", {}) or {}
    threshold = float(fam_cfg.get("obligation_threshold", 0.72))
    ties = visitable_ties(agent, day)
    if ties and ties[0][2] >= threshold:
        key, rel, pressure = ties[0]
        rng = rng_for(seed, agent_id, day, "family")
        # Above the threshold the pull is real but not instant: a duty visit
        # gets scheduled within a week or so, not on the day it crosses.
        if rng.random() < float(fam_cfg.get("daily_prob_over_threshold", 0.18)):
            lo, hi = _days_range(fam_cfg.get("days", [2, 5]))
            return {
                "purpose": "family",
                "days": rng.randint(lo, hi),
                "tie_key": key,
                "tie_city": str((rel.get("profile") or {}).get("city", "")),
                "tie_name": str((rel.get("profile") or {}).get("name", "")) or "家人",
                "pressure": round(pressure, 3),
            }

    # -- business trip: a property of the job, on working days.
    biz_cfg = cfg.get("business", {}) or {}
    if not is_weekend and agent.get("job"):
        rng = rng_for(seed, agent_id, day, "business")
        prob = float(biz_cfg.get("base_daily_prob", 0.004)) * business_weight(agent)
        if rng.random() < prob:
            lo, hi = _days_range(biz_cfg.get("days", [2, 4]))
            return {"purpose": "business", "days": rng.randint(lo, hi)}

    # -- holiday: affordable, wanted, and there is a weekend to hang it on.
    lei_cfg = cfg.get("leisure", {}) or {}
    if is_weekend:
        if _liquid_months(agent) < float(lei_cfg.get("min_cash_months", 1.5)):
            return None
        rng = rng_for(seed, agent_id, day, "leisure")
        openness = float(traits_of(agent, "rules").get("o", 0.0))
        stress = float((agent.get("state") or {}).get("stress", 0.5) or 0.5)
        prob = (
            float(lei_cfg.get("base_daily_prob", 0.02))
            * max(0.2, 1.0 + 0.35 * openness)
            * max(0.5, 0.7 + 0.6 * stress)
        )
        if rng.random() < prob:
            lo, hi = _days_range(lei_cfg.get("days", [3, 7]))
            return {"purpose": "leisure", "days": rng.randint(lo, hi)}

    return None


def _days_range(raw: Any) -> tuple[int, int]:
    try:
        lo, hi = int(raw[0]), int(raw[1])
    except (TypeError, ValueError, IndexError):
        return 2, 3
    lo = max(1, lo)
    return lo, max(lo, hi)
