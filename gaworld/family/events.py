"""Family events, and the emotional weather inside a household.

Two distinct mechanisms, often confused:

* **Events** are discrete and *shared*. A child's fever is one event that
  lands on both parents in the same tick — which is precisely what the
  existing per-agent ghost events cannot express, and the reason family is
  worth modelling as a household rather than as decoration on a profile.
  They are emitted into the ordinary life-event queue, so they inherit
  memory writing, aftermath decay and the dashboard timeline for free.
* **Contagion** is continuous and *asymmetric*. Living with someone anxious
  makes you more anxious, at a rate set by how close you are and whether
  you share a roof.

Templates gate on household composition: an agent with no children cannot
draw "孩子发烧". The gating is a predicate over the family record, so
adding a template never requires touching the sampling logic.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.family.schema import family_config


def _children(record, max_age=None, min_age=None):
    out = []
    for member in (record or {}).get("members", []) or []:
        if member.get("role") != "child" or not member.get("coresident"):
            continue
        age = int(member.get("age", 0) or 0)
        if max_age is not None and age > max_age:
            continue
        if min_age is not None and age < min_age:
            continue
        out.append(member)
    return out


def _partner(record):
    for member in (record or {}).get("members", []) or []:
        if member.get("role") in ("spouse", "partner") and member.get("coresident"):
            return member
    return None


def _elders(record, min_age=0):
    return [
        m
        for m in (record or {}).get("members", []) or []
        if m.get("role") in ("father", "mother", "parent")
        and m.get("coresident")
        and int(m.get("age", 0) or 0) >= min_age
    ]


def _remote_parents(record):
    return [
        m
        for m in (record or {}).get("members", []) or []
        if m.get("role") in ("father", "mother", "parent") and not m.get("coresident")
    ]


#: ``when`` receives the family record and returns a bool; ``title`` and
#: ``description`` receive it too so the text can name the actual child.
FAMILY_EVENT_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "child_sick",
        "weight": 1.4,
        "when": lambda r: bool(_children(r, max_age=15)),
        "title": lambda r: f"{_children(r, max_age=15)[0]['name']}发烧了",
        "description": lambda r: (
            f"{_children(r, max_age=15)[0]['name']}半夜发烧，白天得有人请假带去医院、在家看着。"
        ),
        "severity": 0.68,
        "impact_tags": ["family", "health", "childcare"],
        "state_effects": {"emotion": -0.07, "stress": 0.13, "fatigue_debt": 0.10, "time_pressure": 0.10},
        "time": "07:30",
    },
    {
        "key": "child_school",
        "weight": 1.0,
        "when": lambda r: bool(_children(r, min_age=6, max_age=18)),
        "title": lambda r: f"{_children(r, min_age=6, max_age=18)[0]['name']}的学业问题",
        "description": lambda r: (
            f"老师来消息说{_children(r, min_age=6, max_age=18)[0]['name']}最近状态不好，"
            "晚上要腾出时间谈一次。"
        ),
        "severity": 0.52,
        "impact_tags": ["family", "education"],
        "state_effects": {"emotion": -0.04, "stress": 0.08, "time_pressure": 0.06},
        "time": "18:30",
    },
    {
        "key": "child_good_news",
        "weight": 0.9,
        "when": lambda r: bool(_children(r, min_age=5)),
        "title": lambda r: f"{_children(r, min_age=5)[0]['name']}带回好消息",
        "description": lambda r: (
            f"{_children(r, min_age=5)[0]['name']}这次表现得很好，一家人晚上难得都高兴。"
        ),
        "severity": 0.40,
        "impact_tags": ["family", "positive"],
        "state_effects": {"emotion": 0.10, "stress": -0.05},
        "time": "19:30",
    },
    {
        "key": "couple_argument",
        "weight": 1.2,
        "when": lambda r: _partner(r) is not None,
        "title": lambda r: f"和{_partner(r)['name']}吵了一架",
        "description": lambda r: (
            f"为家务、开销或长辈的事和{_partner(r)['name']}起了争执，一晚上没说几句话。"
        ),
        "severity": 0.60,
        "impact_tags": ["family", "conflict"],
        "state_effects": {"emotion": -0.11, "stress": 0.10, "self_control": -0.05},
        "time": "21:00",
    },
    {
        "key": "family_warmth",
        "weight": 1.1,
        "when": lambda r: _partner(r) is not None or bool(_children(r)) or bool(_elders(r)),
        "title": lambda r: "一顿像样的家庭晚饭",
        "description": lambda r: "一家人难得凑齐吃了顿饭，聊了些平时顾不上说的事。",
        "severity": 0.35,
        "impact_tags": ["family", "positive"],
        "state_effects": {"emotion": 0.09, "stress": -0.07, "social_need": -0.12},
        "time": "19:00",
    },
    {
        "key": "money_argument",
        "weight": 0.8,
        "when": lambda r: _partner(r) is not None and bool(_children(r)),
        "title": lambda r: "为孩子的开销起了分歧",
        "description": lambda r: "补习班、学区、要不要换房——账算下来谁都不轻松。",
        "severity": 0.58,
        "impact_tags": ["family", "money", "conflict"],
        "state_effects": {"emotion": -0.07, "stress": 0.09, "econ_security": -0.06},
        "time": "21:30",
    },
    {
        "key": "elder_health",
        "weight": 1.2,
        "when": lambda r: bool(_elders(r, min_age=70)) or bool(_remote_parents(r)),
        "title": lambda r: "长辈身体出状况",
        "description": lambda r: "家里老人身体不舒服，得陪着去医院，接下来几天都要安排人照看。",
        "severity": 0.72,
        "impact_tags": ["family", "health", "eldercare"],
        "state_effects": {"emotion": -0.08, "stress": 0.14, "time_pressure": 0.12},
        "time": "09:00",
    },
    {
        "key": "elder_visit",
        "weight": 0.7,
        "when": lambda r: bool(_remote_parents(r)),
        "title": lambda r: "老家来电话",
        "description": lambda r: "父母打电话来问近况，顺便催了几句一直没解决的事。",
        "severity": 0.38,
        "impact_tags": ["family", "obligation"],
        "state_effects": {"emotion": 0.02, "stress": 0.04, "obligation": 0.0},
        "time": "20:00",
    },
]


def sample_family_event(
    record: dict[str, Any] | None,
    *,
    day: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Draw at most one family event for this household today."""
    if not record:
        return None
    cfg = family_config(config)
    ev_cfg = cfg.get("events", {})
    if not ev_cfg.get("enabled", True):
        return None
    rng = random.Random(f"{cfg.get('seed')}::{record.get('household_id')}::{day}::event")
    if rng.random() >= float(ev_cfg.get("daily_probability", 0.14)):
        return None
    eligible = [t for t in FAMILY_EVENT_TEMPLATES if t["when"](record)]
    if not eligible:
        return None
    total = sum(float(t.get("weight", 1.0)) for t in eligible)
    roll = rng.random() * total
    acc = 0.0
    chosen = eligible[-1]
    for template in eligible:
        acc += float(template.get("weight", 1.0))
        if roll <= acc:
            chosen = template
            break
    return {
        "template_key": f"family_{chosen['key']}",
        "title": chosen["title"](record),
        "description": chosen["description"](record),
        "severity": float(chosen["severity"]),
        "impact_tags": list(chosen["impact_tags"]),
        "state_effects": {k: v for k, v in chosen["state_effects"].items() if v},
        "time": chosen["time"],
        "day": int(day),
    }


def contagion_effects(
    agent: dict[str, Any],
    peers: list[dict[str, Any]],
    *,
    coresident_ids: set[int] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Emotion / stress pull towards the household's in-sim members.

    Applied as a *convergence* term (``w * (peer - self)``), so it moves an
    agent towards the people they live with without inventing feeling: a
    household where everyone is calm produces no drift at all. Co-residents
    pull an order of magnitude harder than family living elsewhere.
    """
    cfg = family_config(config).get("events", {})
    if not cfg.get("contagion_enabled", True) or not peers:
        return {}
    near = float(cfg.get("contagion_weight", 0.035))
    far = float(cfg.get("remote_contagion_weight", 0.008))
    coresident_ids = coresident_ids or set()
    state = agent.get("state") or {}
    deltas: dict[str, float] = {}
    for key in ("emotion", "stress"):
        try:
            mine = float(state.get(key, 0.5) or 0.5)
        except (TypeError, ValueError):
            continue
        total = 0.0
        for peer in peers:
            peer_state = peer.get("state") or {}
            try:
                theirs = float(peer_state.get(key, 0.5) or 0.5)
            except (TypeError, ValueError):
                continue
            weight = near if int(peer.get("id", -1)) in coresident_ids else far
            total += weight * (theirs - mine)
        if abs(total) > 1e-6:
            deltas[key] = round(total, 5)
    return deltas
