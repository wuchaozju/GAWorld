"""Social network extensions: off-screen ghosts, role-aware decay, Dunbar tiers.

The existing `human_realism.relationship_update / relationship_weight` keeps
relationships as a flat dict keyed by in-sim agent id, with four scalar
axes. This module adds three things on top, without disturbing that schema:

1. **Schema migration.** ``ensure_relationship_schema`` fills the new fields
   (``kind``, ``role``, ``tie_origin``, ``profile``, ``last_contact_day``,
   ``channels``, ``decay_rate``, ``obligation_base``) with role-driven
   defaults. Old records keep working.

2. **Off-screen ghosts.** ``bootstrap_social_roster`` asks the LLM for a
   plausible family / friend / coworker network for the agent and stores
   each as a record with ``kind="ghost"``. Ghosts never participate in
   the in-sim co-location loop; they only interact via remote channels
   (call / chat / visit) and via ``generate_ghost_event``.

3. **Maintenance.** ``decay_relationships`` decays closeness by role,
   bumps obligation (the "guilt" signal) for long-neglected ties, and
   ``enforce_dunbar`` caps total ties to ~150 while protecting kin.

The module avoids touching the in-sim co-location pipeline; callers
should still drive `relationship_update` for in-sim positive/negative
signals after a reflection.
"""

from __future__ import annotations

import json
import math
import random
import re
import unicodedata
from typing import Any, Callable, Iterable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.social")


# ---------------------------------------------------------------------------
# Role config
# ---------------------------------------------------------------------------

# Per-role tuning. ``decay_rate`` is daily closeness loss when no contact;
# ``obligation_base`` is the baseline obligation pull; ``protected`` keeps
# the tie out of Dunbar pruning (kin always survives); ``channels`` lists
# allowed remote channels for ghost events.
ROLE_CONFIG: dict[str, dict[str, Any]] = {
    # --- kin (very slow decay, high obligation, protected) ---
    "mother":          {"decay_rate": 0.001, "obligation_base": 0.80, "protected": True,  "channels": ["call", "visit"], "category": "kin"},
    "father":          {"decay_rate": 0.001, "obligation_base": 0.80, "protected": True,  "channels": ["call", "visit"], "category": "kin"},
    "parent":          {"decay_rate": 0.001, "obligation_base": 0.78, "protected": True,  "channels": ["call", "visit"], "category": "kin"},
    "sibling":         {"decay_rate": 0.002, "obligation_base": 0.62, "protected": True,  "channels": ["call", "chat"],  "category": "kin"},
    "grandparent":     {"decay_rate": 0.001, "obligation_base": 0.70, "protected": True,  "channels": ["call", "visit"], "category": "kin"},
    "relative":        {"decay_rate": 0.004, "obligation_base": 0.40, "protected": True,  "channels": ["chat"],           "category": "kin"},
    "spouse":          {"decay_rate": 0.0,   "obligation_base": 0.85, "protected": True,  "channels": ["face", "call"],  "category": "kin"},
    "partner":         {"decay_rate": 0.0,   "obligation_base": 0.82, "protected": True,  "channels": ["face", "call"],  "category": "kin"},
    "child":           {"decay_rate": 0.0,   "obligation_base": 0.90, "protected": True,  "channels": ["face", "call"],  "category": "kin"},

    # --- close friends ---
    "best_friend":     {"decay_rate": 0.004, "obligation_base": 0.55, "protected": False, "channels": ["call", "chat", "visit"], "category": "friend"},
    "close_friend":    {"decay_rate": 0.005, "obligation_base": 0.50, "protected": False, "channels": ["call", "chat", "visit"], "category": "friend"},
    "friend":          {"decay_rate": 0.008, "obligation_base": 0.40, "protected": False, "channels": ["chat", "visit"],         "category": "friend"},

    # --- past ties ---
    "classmate":       {"decay_rate": 0.012, "obligation_base": 0.28, "protected": False, "channels": ["chat"], "category": "past"},
    "ex":              {"decay_rate": 0.010, "obligation_base": 0.20, "protected": False, "channels": ["chat"], "category": "past"},
    "former_coworker": {"decay_rate": 0.015, "obligation_base": 0.20, "protected": False, "channels": ["chat"], "category": "past"},
    "old_friend":      {"decay_rate": 0.006, "obligation_base": 0.35, "protected": False, "channels": ["chat", "call"], "category": "past"},

    # --- current work ---
    "coworker":        {"decay_rate": 0.006, "obligation_base": 0.42, "protected": False, "channels": ["face", "chat"], "category": "work"},
    "boss":            {"decay_rate": 0.005, "obligation_base": 0.55, "protected": False, "channels": ["face", "chat"], "category": "work"},
    "subordinate":     {"decay_rate": 0.006, "obligation_base": 0.40, "protected": False, "channels": ["face", "chat"], "category": "work"},
    "mentor":          {"decay_rate": 0.005, "obligation_base": 0.45, "protected": False, "channels": ["chat", "visit"], "category": "work"},
    "client":          {"decay_rate": 0.009, "obligation_base": 0.40, "protected": False, "channels": ["face", "chat"], "category": "work"},

    # --- community ---
    # A flatmate is the one person a single agent sees at home every day, so
    # the tie decays slowly and runs face-to-face — closer to kin than to a
    # neighbour, without the obligation.
    "roommate":        {"decay_rate": 0.004, "obligation_base": 0.30, "protected": False, "channels": ["face", "chat"], "category": "community"},
    "neighbor":        {"decay_rate": 0.010, "obligation_base": 0.28, "protected": False, "channels": ["face"], "category": "community"},
    "online_friend":   {"decay_rate": 0.020, "obligation_base": 0.15, "protected": False, "channels": ["chat"], "category": "community"},
    "acquaintance":    {"decay_rate": 0.018, "obligation_base": 0.18, "protected": False, "channels": ["chat", "face"], "category": "community"},
}

# Used when ``role`` is unset or unknown — preserves prior behaviour
# (an in-sim agent neighbour with no explicit role).
DEFAULT_ROLE_CONFIG: dict[str, Any] = {
    "decay_rate": 0.008,
    "obligation_base": 0.40,
    "protected": False,
    "channels": ["face"],
    "category": "other",
}

# Dunbar tiers used by enforce_dunbar. Outer cap (150) is the hard prune.
DUNBAR_TIERS: dict[str, int] = {"inner": 5, "close": 15, "acquaintance": 50, "weak": 150}


def role_config(role: str | None) -> dict[str, Any]:
    """Return the merged role config for ``role`` (lookup, then default)."""
    key = (str(role or "")).strip().lower()
    if not key:
        return dict(DEFAULT_ROLE_CONFIG)
    cfg = ROLE_CONFIG.get(key)
    if cfg is None:
        merged = dict(DEFAULT_ROLE_CONFIG)
        merged["role_unknown"] = key
        return merged
    return dict(cfg)


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

_REL_DEFAULTS = {
    "closeness": 0.5,
    "trust": 0.5,
    "obligation": 0.5,
    "friction": 0.5,
    "last_interaction_day": 0,
}


def ensure_relationship_schema(
    item: dict[str, Any] | None,
    *,
    role: str = "",
    kind: str = "agent",
    tie_origin: str = "",
    profile: dict[str, Any] | None = None,
    current_day: int = 0,
) -> dict[str, Any]:
    """Fill the extended schema in-place and return ``item``.

    Old records (the flat dict from ``relationship_update``) keep their
    scalar values; we only add new keys with role-driven defaults.
    """
    if not isinstance(item, dict):
        item = {}
    for key, default in _REL_DEFAULTS.items():
        item.setdefault(key, default)
    # New fields. We only set if missing — preserves any caller overrides.
    item.setdefault("kind", kind)
    if role and not item.get("role"):
        item["role"] = role
    item.setdefault("role", "")
    item.setdefault("tie_origin", tie_origin)
    if profile:
        existing = item.setdefault("profile", {})
        if isinstance(existing, dict):
            for k, v in profile.items():
                existing.setdefault(k, v)
        else:
            item["profile"] = dict(profile)
    else:
        item.setdefault("profile", {})
    item.setdefault("channels", list(role_config(item["role"])["channels"]))
    item.setdefault("decay_rate", float(role_config(item["role"])["decay_rate"]))
    item.setdefault("obligation_base", float(role_config(item["role"])["obligation_base"]))
    # Use explicit None-check: ``0`` is a valid day value but falsy.
    if "last_contact_day" not in item:
        raw_last = item.get("last_interaction_day")
        item["last_contact_day"] = int(raw_last) if raw_last is not None else int(current_day)
    return item


#: Current-work roles that stop being current when the job ends.
WORK_TIE_ROLES: tuple[str, ...] = ("coworker", "boss", "subordinate")
RETIRED_WORK_ROLE = "former_coworker"


def retire_work_ties(
    agent: dict[str, Any],
    *,
    current_day: int = 0,
    roles: tuple[str, ...] = WORK_TIE_ROLES,
    new_role: str = RETIRED_WORK_ROLE,
) -> list[str]:
    """Move current-work ties to past ties when the agent's job ends.

    The role table already encodes what that means — ``coworker`` decays at
    0.006/day and owes 0.42, ``former_coworker`` at 0.015 and owes 0.20 — but
    nothing ever performed the switch, so someone who changed jobs kept
    colleagues from a company they had left, decaying as if they still saw
    them daily. ``SOCIAL_NETWORK_DESIGN.md`` §6 lists this as needing "an
    external trigger"; the employment life event is that trigger.

    ``role`` alone is not enough: ``ensure_relationship_schema`` fills the
    role-driven fields with ``setdefault``, so the rate has to be rewritten
    explicitly or the tie would keep the old one forever. Returns the keys
    that changed.
    """
    relationships = agent.get("relationships") if isinstance(agent, dict) else None
    if not isinstance(relationships, dict):
        return []
    target = role_config(new_role)
    changed: list[str] = []
    for key, item in relationships.items():
        if not isinstance(item, dict) or str(item.get("role", "")) not in roles:
            continue
        item["role"] = new_role
        item["decay_rate"] = float(target["decay_rate"])
        item["obligation_base"] = float(target["obligation_base"])
        item["channels"] = list(target["channels"])
        # Leaving a workplace is itself the last easy contact.
        item.setdefault("last_contact_day", int(current_day))
        changed.append(str(key))
    return changed


def apply_closeness_delta(
    agent: dict[str, Any],
    neighbor_key: Any,
    delta: float,
    *,
    current_day: int = 0,
    max_delta: float = 0.25,
) -> dict[str, Any] | None:
    """Move one tie along its trajectory over a long step.

    ``relationship_update`` books a single interaction (±0.03 closeness),
    which is the right unit for a tick and noise over a year. A coarse step
    reports where the relationship *went* instead, and this applies it.

    Trust follows closeness at half rate — slower to build, slower to lose.
    A positive delta counts as contact and resets the decay clock; a negative
    one deliberately does not, because drifting apart is precisely the
    absence of contact, and letting decay keep running is what makes it go on
    drifting.
    """
    if not isinstance(agent, dict):
        return None
    try:
        step = float(delta)
    except (TypeError, ValueError):
        return None
    cap = max(0.0, float(max_delta))
    step = max(-cap, min(cap, step))
    if step == 0.0:
        return None
    relationships = agent.setdefault("relationships", {})
    if not isinstance(relationships, dict):
        return None
    key = str(neighbor_key)
    item = relationships.get(key)
    if not isinstance(item, dict):
        return None
    ensure_relationship_schema(item, current_day=current_day)
    before = float(item.get("closeness", 0.5))
    item["closeness"] = max(_MIN_CLOSENESS_FLOOR, min(1.0, before + step))
    trust = float(item.get("trust", 0.5))
    item["trust"] = max(_MIN_CLOSENESS_FLOOR, min(1.0, trust + step * 0.5))
    if step > 0:
        item["last_contact_day"] = int(current_day)
        item["last_interaction_day"] = int(current_day)
    return {"key": key, "before": round(before, 4),
            "after": round(item["closeness"], 4), "delta": round(step, 4)}


def form_tie(
    agent: dict[str, Any],
    neighbor_key: Any,
    *,
    role: str = "acquaintance",
    closeness: float = 0.35,
    current_day: int = 0,
    tie_origin: str = "",
) -> dict[str, Any] | None:
    """Open a relationship the agent did not have before.

    Over a day nobody's social circle reorganises; over a year it does — new
    colleagues, a partner's friends, neighbours after a move. Without this the
    graph can only ever shrink (decay plus Dunbar pruning), so a decade-long
    run ends with everyone lonelier than they started — an artefact of the
    model rather than a finding.
    """
    if not isinstance(agent, dict):
        return None
    relationships = agent.setdefault("relationships", {})
    if not isinstance(relationships, dict):
        return None
    key = str(neighbor_key)
    if key in relationships:
        return None
    item = ensure_relationship_schema(
        {"closeness": max(0.0, min(1.0, float(closeness)))},
        role=role if role in ROLE_CONFIG else "acquaintance",
        tie_origin=tie_origin or "in_sim",
        current_day=current_day,
    )
    item["last_contact_day"] = int(current_day)
    item["last_interaction_day"] = int(current_day)
    relationships[key] = item
    neighbors = agent.setdefault("social_neighbors", [])
    if isinstance(neighbors, list):
        try:
            nid = int(neighbor_key)
        except (TypeError, ValueError):
            nid = None
        if nid is not None and nid not in neighbors:
            neighbors.append(nid)
    return item


def migrate_relationships(agent: dict[str, Any], current_day: int = 0) -> None:
    """Walk ``agent['relationships']`` once and apply the schema."""
    rels = agent.setdefault("relationships", {}) if isinstance(agent, dict) else {}
    if not isinstance(rels, dict):
        return
    for _key, item in list(rels.items()):
        ensure_relationship_schema(item, current_day=current_day)


# ---------------------------------------------------------------------------
# Role-aware weighting (used by sampling / dialog ranking)
# ---------------------------------------------------------------------------

# Per-category weight multipliers — kin and close friends are stickier
# in social context retrieval, weak online ties carry less.
_CATEGORY_WEIGHT_BIAS = {
    "kin": 1.30,
    "friend": 1.10,
    "work": 1.00,
    "past": 0.85,
    "community": 0.90,
    "other": 1.00,
}


def role_aware_weight(item: dict[str, Any] | None) -> float:
    """Like ``human_realism.relationship_weight`` but role-aware."""
    if not isinstance(item, dict):
        return 0.05
    closeness = float(item.get("closeness", 0.5))
    trust = float(item.get("trust", 0.5))
    obligation = float(item.get("obligation", 0.5))
    friction = float(item.get("friction", 0.5))
    cat = role_config(item.get("role", "")).get("category", "other")
    bias = _CATEGORY_WEIGHT_BIAS.get(cat, 1.0)
    base = closeness * 0.45 + trust * 0.30 + obligation * 0.20 - friction * 0.15
    return max(0.01, bias * base)


# ---------------------------------------------------------------------------
# Backstory (off-screen roster) generation
# ---------------------------------------------------------------------------

_BACKSTORY_SCHEMA_HINT = """请输出一个 JSON 对象，仅包含字段 "ghosts"，其值为一个数组。
每个元素描述一个不在模拟内的"场外熟人"，字段如下：
- ghost_id: 字符串 ID（例如 "g_mother"，需在该智能体内唯一）
- name: 中文姓名
- role: 必须取以下之一：mother, father, parent, sibling, grandparent, relative, spouse, partner, child, best_friend, close_friend, friend, classmate, ex, former_coworker, old_friend, coworker, boss, subordinate, mentor, client, neighbor, online_friend, acquaintance
- tie_origin: 短语，例如 hometown / college / first_job / online / neighborhood
- city: 该 ghost 当前所在城市（中文）
- vibe: 一句话性格速写
- closeness: 0~1 浮点
- last_contact_days_ago: 整数（距上次联系的天数，亲属通常 < 7，老同学可能 > 90）
要求覆盖至少：父母、兄弟姐妹（若有）、伴侣或前任（按性格设定）、2~3 位老朋友/同学、1~2 位前同事或导师、1 位邻居或网友。
总数控制在 8~14 之间。仅输出 JSON，不要解释。"""


def _strip(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def _parse_backstory_json(blob: str) -> list[dict[str, Any]]:
    text = str(blob or "")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        items = data.get("ghosts") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [item for item in items if isinstance(item, dict)]


def _heuristic_ghosts(agent: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic fallback when the LLM call fails or is absent."""
    name = _strip(agent.get("name", "")) or "本人"
    hometown = _strip(agent.get("living") or agent.get("residence") or "本地")
    seeds = [
        {"ghost_id": "g_mother", "name": f"{name}的母亲", "role": "mother",
         "tie_origin": "hometown", "city": hometown, "vibe": "关心子女、爱唠叨",
         "closeness": 0.85, "last_contact_days_ago": 3},
        {"ghost_id": "g_father", "name": f"{name}的父亲", "role": "father",
         "tie_origin": "hometown", "city": hometown, "vibe": "话不多但务实",
         "closeness": 0.78, "last_contact_days_ago": 7},
        {"ghost_id": "g_sibling", "name": f"{name}的兄弟姐妹", "role": "sibling",
         "tie_origin": "hometown", "city": hometown, "vibe": "彼此熟悉但不天天聊",
         "closeness": 0.65, "last_contact_days_ago": 14},
        {"ghost_id": "g_close_friend_1", "name": "老朋友A", "role": "close_friend",
         "tie_origin": "college", "city": hometown, "vibe": "讲义气的老友",
         "closeness": 0.70, "last_contact_days_ago": 30},
        {"ghost_id": "g_classmate_1", "name": "老同学B", "role": "classmate",
         "tie_origin": "college", "city": "其他城市", "vibe": "偶尔朋友圈点赞",
         "closeness": 0.40, "last_contact_days_ago": 90},
        {"ghost_id": "g_former_coworker_1", "name": "前同事C", "role": "former_coworker",
         "tie_origin": "first_job", "city": "其他城市", "vibe": "项目期间合作很紧",
         "closeness": 0.45, "last_contact_days_ago": 60},
        {"ghost_id": "g_mentor", "name": "老师D", "role": "mentor",
         "tie_origin": "college", "city": "其他城市", "vibe": "曾给过关键建议",
         "closeness": 0.55, "last_contact_days_ago": 45},
        {"ghost_id": "g_neighbor", "name": "邻居E", "role": "neighbor",
         "tie_origin": "neighborhood", "city": hometown, "vibe": "见面会打招呼",
         "closeness": 0.35, "last_contact_days_ago": 10},
    ]
    return seeds


def bootstrap_social_roster(
    agent: dict[str, Any],
    llm_call: Callable[..., str] | None = None,
    *,
    current_day: int = 0,
    rng: random.Random | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Generate (or augment) the agent's off-screen social roster.

    Idempotent: by default it is a no-op when the agent already has any
    ``kind="ghost"`` record (we trust pre-existing rosters across runs).
    Pass ``force=True`` to regenerate.

    Returns the list of ghost records that were added (may be empty).
    """
    if not isinstance(agent, dict):
        return []
    relationships = agent.setdefault("relationships", {})
    if not isinstance(relationships, dict):
        relationships = {}
        agent["relationships"] = relationships
    has_ghost = any(
        isinstance(v, dict) and str(v.get("kind", "")) == "ghost"
        for v in relationships.values()
    )
    if has_ghost and not force:
        return []

    raw_items: list[dict[str, Any]] = []
    if llm_call is not None:
        prompt = _build_backstory_prompt(agent)
        try:
            blob = llm_call(prompt, task="social_backstory", agent_id=agent.get("id"))
        except Exception as exc:  # noqa: BLE001 - LLM provider raises arbitrary types
            _LOG.warning("social_backstory LLM failed: %s", exc)
            blob = ""
        raw_items = _parse_backstory_json(blob)
    if not raw_items:
        raw_items = _heuristic_ghosts(agent)

    added: list[dict[str, Any]] = []
    used_ids: set[str] = set(str(k) for k in relationships.keys())
    rng = rng or random.Random(agent.get("id") or 0)
    for raw in raw_items[:20]:  # safety cap
        record = _record_from_backstory(raw, current_day, used_ids, rng)
        if record is None:
            continue
        ghost_id = record["_key"]
        del record["_key"]
        relationships[ghost_id] = record
        used_ids.add(ghost_id)
        added.append(record)
    return added


def _build_backstory_prompt(agent: dict[str, Any]) -> str:
    fields = []
    for key in ("name", "age", "job", "living", "residence", "personality", "values", "daily_life", "family"):
        val = _strip(agent.get(key, ""))
        if val:
            fields.append(f"- {key}: {val}")
    profile_text = "\n".join(fields) if fields else "(无)"
    # When the family module has already assigned a household, the roster must
    # not contradict it — an invented second spouse is worse than none. The
    # constraint is stated here *and* enforced afterwards by
    # ``gaworld.family.ties.reconcile_ghost_kin``; the prompt saves tokens,
    # the code guarantees consistency.
    family_rule = ""
    if _strip(agent.get("family", "")):
        family_rule = (
            "\n注意：该居民的婚姻与家庭状况已在上面的 family 字段中确定，"
            "**不要**再编造配偶、伴侣、子女或前任；只补充父母、兄弟姐妹、"
            "朋友、同学、前同事、邻居等其他关系。\n"
        )
    return (
        "你在为一个生活模拟里的虚拟居民补全场外社交档案。"
        "请基于该居民的个人资料，编造一个可信的、不在本模拟内的熟人网络。\n\n"
        f"居民资料：\n{profile_text}\n"
        f"{family_rule}\n"
        f"{_BACKSTORY_SCHEMA_HINT}"
    )


_VALID_ROLES = set(ROLE_CONFIG.keys())


def _record_from_backstory(
    raw: dict[str, Any],
    current_day: int,
    used_ids: set[str],
    rng: random.Random,
) -> dict[str, Any] | None:
    role = _strip(raw.get("role")).lower()
    if role not in _VALID_ROLES:
        # Allow caller to still keep it but mark as acquaintance.
        role = "acquaintance"
    name = _strip(raw.get("name"))
    if not name:
        return None
    requested_id = _strip(raw.get("ghost_id") or raw.get("id"))
    if not requested_id or not requested_id.startswith("g_"):
        requested_id = f"g_{role}_{rng.randrange(10000, 99999)}"
    final_id = requested_id
    n = 1
    while final_id in used_ids:
        n += 1
        final_id = f"{requested_id}_{n}"

    closeness_raw = raw.get("closeness")
    try:
        closeness = float(closeness_raw)
    except (TypeError, ValueError):
        closeness = 0.5
    closeness = max(0.05, min(0.99, closeness))
    days_ago_raw = raw.get("last_contact_days_ago")
    try:
        days_ago = int(days_ago_raw)
    except (TypeError, ValueError):
        days_ago = 30
    days_ago = max(0, days_ago)
    last_contact_day = max(0, current_day - days_ago)

    cfg = role_config(role)
    obligation_base = float(cfg["obligation_base"])
    item = {
        "kind": "ghost",
        "role": role,
        "tie_origin": _strip(raw.get("tie_origin")) or cfg.get("category", ""),
        "profile": {
            "name": name,
            "city": _strip(raw.get("city")),
            "vibe": _strip(raw.get("vibe")),
        },
        "closeness": closeness,
        "trust": min(0.95, closeness * 0.9 + 0.1),
        "obligation": obligation_base,
        "obligation_base": obligation_base,
        "friction": max(0.05, 0.5 - closeness * 0.3),
        "decay_rate": float(cfg["decay_rate"]),
        "channels": list(cfg["channels"]),
        "last_interaction_day": last_contact_day,
        "last_contact_day": last_contact_day,
    }
    item["_key"] = final_id
    return item


# ---------------------------------------------------------------------------
# Decay + Dunbar
# ---------------------------------------------------------------------------

# When a tie hasn't been touched for this many days we begin applying a
# "guilt" obligation boost — small, but persistent.
_NEGLECT_GUILT_THRESHOLD_DAYS = 7
_NEGLECT_GUILT_PER_DAY = 0.005
_MIN_CLOSENESS_FLOOR = 0.03


def decay_relationships(
    agent: dict[str, Any],
    current_day: int,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply role-aware decay; bump obligation on long-neglected ties.

    Returns a small report dict for logging/tests.
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    relationships = agent.get("relationships", {}) if isinstance(agent, dict) else {}
    if not isinstance(relationships, dict):
        return {"touched": 0}
    touched = 0
    for _key, item in relationships.items():
        if not isinstance(item, dict):
            continue
        ensure_relationship_schema(item, current_day=current_day)
        raw_last = item.get("last_contact_day")
        if raw_last is None:
            raw_last = item.get("last_interaction_day")
        last = int(raw_last) if raw_last is not None else int(current_day)
        gap = max(0, int(current_day) - last)
        if gap <= 0:
            continue
        touched += 1
        rate = float(item.get("decay_rate", DEFAULT_ROLE_CONFIG["decay_rate"]))
        # Closeness decays toward 0; we clamp at a small floor so the tie
        # isn't fully erased (still recallable).
        closeness = float(item.get("closeness", 0.5))
        closeness = max(_MIN_CLOSENESS_FLOOR, closeness - rate * gap)
        item["closeness"] = closeness
        # Trust follows closeness slowly.
        trust = float(item.get("trust", 0.5))
        item["trust"] = max(_MIN_CLOSENESS_FLOOR, trust - rate * 0.5 * gap)
        # Neglected → guilt: obligation creeps up but capped near base*1.4.
        if gap >= _NEGLECT_GUILT_THRESHOLD_DAYS:
            base = float(item.get("obligation_base", DEFAULT_ROLE_CONFIG["obligation_base"]))
            cap = min(1.0, base * 1.4)
            extra = (gap - _NEGLECT_GUILT_THRESHOLD_DAYS) * _NEGLECT_GUILT_PER_DAY
            current_obl = float(item.get("obligation", base))
            item["obligation"] = max(current_obl, min(cap, current_obl + extra))
    return {"touched": touched, "current_day": current_day}


def enforce_dunbar(
    agent: dict[str, Any],
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Cap total ties at the outer Dunbar limit; tag tier on survivors.

    Protected roles (kin) are never pruned. Among non-protected, the
    weakest by ``role_aware_weight`` are dropped until we are under the
    outer cap. Returns ``{kept, pruned, tiers}``.
    """
    limits = {**DUNBAR_TIERS, **(limits or {})}
    outer = int(limits.get("weak", 150))
    relationships = agent.get("relationships", {}) if isinstance(agent, dict) else {}
    if not isinstance(relationships, dict):
        return {"kept": 0, "pruned": 0, "tiers": {}}

    items: list[tuple[str, dict[str, Any], float, bool]] = []
    for key, item in relationships.items():
        if not isinstance(item, dict):
            continue
        ensure_relationship_schema(item)
        cfg = role_config(item.get("role", ""))
        protected = bool(cfg.get("protected", False)) or item.get("kind") == "agent"
        items.append((key, item, role_aware_weight(item), protected))

    pruned = 0
    if len(items) > outer:
        non_protected = [t for t in items if not t[3]]
        non_protected.sort(key=lambda t: t[2])  # weakest first
        overflow = len(items) - outer
        for key, _item, _w, _p in non_protected[:overflow]:
            relationships.pop(key, None)
            pruned += 1
        items = [t for t in items if t[0] in relationships]

    # Re-tier survivors by weight (top 5 inner / 15 close / 50 acq / rest weak).
    items.sort(key=lambda t: t[2], reverse=True)
    inner = int(limits.get("inner", 5))
    close = int(limits.get("close", 15))
    acq = int(limits.get("acquaintance", 50))
    counts = {"inner": 0, "close": 0, "acquaintance": 0, "weak": 0}
    for idx, (_key, item, _w, _p) in enumerate(items):
        if idx < inner:
            tier = "inner"
        elif idx < close:
            tier = "close"
        elif idx < acq:
            tier = "acquaintance"
        else:
            tier = "weak"
        item["dunbar_tier"] = tier
        counts[tier] += 1
    return {"kept": len(items), "pruned": pruned, "tiers": counts}


# ---------------------------------------------------------------------------
# Ghost events (off-screen life events driven by relationships)
# ---------------------------------------------------------------------------

# Templates that ground LLM-generated ghost events; if LLM is absent we
# pick one of these directly.
GHOST_EVENT_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "ghost_birthday",
        "title_fmt": "{name}的生日",
        "desc_fmt": "{name}（{role_zh}）今天生日，需要花时间问候或安排礼物。",
        "channel": "chat",
        "min_closeness": 0.30,
        "categories": ["kin", "friend", "past"],
        "state_effects": {"emotion": 0.04, "time_pressure": 0.04, "social_need": -0.04},
        "signal": "positive",
    },
    {
        "key": "ghost_illness",
        "title_fmt": "{name}生病了",
        "desc_fmt": "{name}（{role_zh}）身体不适，托人来联系希望关心一下。",
        "channel": "call",
        "min_closeness": 0.45,
        "categories": ["kin", "friend"],
        "state_effects": {"emotion": -0.06, "stress": 0.10, "time_pressure": 0.06},
        "signal": "neutral",
    },
    {
        "key": "ghost_milestone",
        "title_fmt": "{name}的喜事",
        "desc_fmt": "{name}（{role_zh}）有重要好消息（升职/结婚/孩子出生），希望被告知。",
        "channel": "chat",
        "min_closeness": 0.30,
        "categories": ["kin", "friend", "past", "work"],
        "state_effects": {"emotion": 0.08, "social_need": -0.04},
        "signal": "positive",
    },
    {
        "key": "ghost_request",
        "title_fmt": "{name}的求助",
        "desc_fmt": "{name}（{role_zh}）遇到困难，希望得到建议或小额支援。",
        "channel": "call",
        "min_closeness": 0.40,
        "categories": ["kin", "friend"],
        "state_effects": {"emotion": -0.03, "stress": 0.08, "econ_security": -0.04, "time_pressure": 0.05},
        "signal": "neutral",
    },
    {
        "key": "ghost_reconnect",
        "title_fmt": "{name}发来消息",
        "desc_fmt": "很久没有联系的{name}（{role_zh}）突然发来消息，简单寒暄。",
        "channel": "chat",
        "min_closeness": 0.0,
        "categories": ["past", "community"],
        "state_effects": {"emotion": 0.03, "social_need": -0.03},
        "signal": "positive",
        "needs_long_gap": True,
    },
    {
        "key": "ghost_conflict",
        "title_fmt": "与{name}的小冲突",
        "desc_fmt": "与{name}（{role_zh}）在某事上意见不合，言语之间有点冷。",
        "channel": "chat",
        "min_closeness": 0.45,
        "categories": ["kin", "friend", "work"],
        "state_effects": {"emotion": -0.08, "stress": 0.10, "self_control": -0.04},
        "signal": "negative",
    },
]


_ROLE_ZH = {
    "mother": "母亲", "father": "父亲", "parent": "父母", "sibling": "兄弟姐妹",
    "grandparent": "祖辈", "relative": "亲戚", "spouse": "伴侣", "partner": "伴侣",
    "child": "孩子", "best_friend": "挚友", "close_friend": "好友", "friend": "朋友",
    "classmate": "同学", "ex": "前任", "former_coworker": "前同事",
    "old_friend": "老朋友", "coworker": "同事", "boss": "上司",
    "subordinate": "下属", "mentor": "导师", "client": "客户",
    "neighbor": "邻居", "online_friend": "网友", "acquaintance": "熟人",
}


def _select_ghost(
    relationships: dict[str, Any],
    current_day: int,
    template: dict[str, Any],
    rng: random.Random,
) -> tuple[str, dict[str, Any]] | None:
    """Pick a ghost compatible with ``template`` by weighted sampling."""
    candidates: list[tuple[str, dict[str, Any], float]] = []
    for key, item in relationships.items():
        if not isinstance(item, dict) or item.get("kind") != "ghost":
            continue
        ensure_relationship_schema(item, current_day=current_day)
        role = item.get("role", "")
        cat = role_config(role).get("category", "other")
        if template.get("categories") and cat not in template["categories"]:
            continue
        if float(item.get("closeness", 0.5)) < float(template.get("min_closeness", 0.0)):
            continue
        raw_last = item.get("last_contact_day")
        if raw_last is None:
            raw_last = item.get("last_interaction_day", current_day)
        last = int(raw_last) if raw_last is not None else int(current_day)
        gap = max(0, int(current_day) - last)
        if template.get("needs_long_gap") and gap < 30:
            continue
        # Weight: closeness + obligation + a touch of gap (long-neglected
        # ties are slightly more likely to "reach out").
        weight = (
            float(item.get("closeness", 0.5)) * 1.0
            + float(item.get("obligation", 0.5)) * 0.6
            + min(0.5, gap * 0.01)
        )
        candidates.append((key, item, max(0.01, weight)))
    if not candidates:
        return None
    total = sum(w for _k, _i, w in candidates)
    pick = rng.uniform(0.0, total)
    acc = 0.0
    for key, item, w in candidates:
        acc += w
        if pick <= acc:
            return key, item
    return candidates[-1][0], candidates[-1][1]


def generate_ghost_event(
    agent: dict[str, Any],
    current_day: int,
    llm_call: Callable[..., str] | None = None,
    rng: random.Random | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Sample a ghost + template, materialise an off-screen event.

    Returns a dict shaped like a life_events event payload (without the
    sim-wide fields like ``id`` / ``status``) plus a ``ghost_key`` field.
    Also writes back ``last_contact_day`` and a relationship signal.

    Returns ``None`` if no eligible ghost exists.
    """
    cfg = cfg if isinstance(cfg, dict) else {}
    rng = rng or random.Random()
    relationships = agent.get("relationships", {}) if isinstance(agent, dict) else {}
    if not isinstance(relationships, dict):
        return None

    # Shuffle templates so we don't always try the same one first.
    templates = list(GHOST_EVENT_TEMPLATES)
    rng.shuffle(templates)
    selected = None
    for tpl in templates:
        picked = _select_ghost(relationships, current_day, tpl, rng)
        if picked is not None:
            selected = (tpl, picked[0], picked[1])
            break
    if selected is None:
        return None
    template, ghost_key, ghost_item = selected

    name = _strip(ghost_item.get("profile", {}).get("name")) or "熟人"
    role = ghost_item.get("role", "")
    role_zh = _ROLE_ZH.get(role, "熟人")

    # LLM is optional; when present we ask it to produce a sharper title
    # and one-paragraph description grounded in the template.
    title = template["title_fmt"].format(name=name, role_zh=role_zh)
    description = template["desc_fmt"].format(name=name, role_zh=role_zh)
    if llm_call is not None:
        try:
            blob = llm_call(
                _ghost_event_prompt(agent, ghost_item, template, current_day),
                task="ghost_event",
                agent_id=agent.get("id"),
            )
            parsed = _parse_ghost_event_json(blob)
            if parsed.get("title"):
                title = _strip(parsed["title"])[:80] or title
            if parsed.get("description"):
                description = _strip(parsed["description"])[:600] or description
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("ghost_event LLM failed: %s", exc)

    # Update the ghost record: signal + last_contact_day refresh.
    _apply_ghost_event_to_record(ghost_item, current_day, template["signal"])

    return {
        "template_key": template["key"],
        "title": title,
        "description": description,
        "severity": 0.55,
        "impact_tags": ["relationship", "off_screen", role or "ghost"],
        "state_effects": dict(template.get("state_effects", {})),
        "channel": template.get("channel", "chat"),
        "ghost_key": ghost_key,
        "ghost_name": name,
        "ghost_role": role,
        "signal": template["signal"],
    }


def _ghost_event_prompt(
    agent: dict[str, Any],
    ghost_item: dict[str, Any],
    template: dict[str, Any],
    current_day: int,
) -> str:
    profile = ghost_item.get("profile", {}) if isinstance(ghost_item, dict) else {}
    return (
        f"为模拟居民 {_strip(agent.get('name'))} 编写一段{template['key']}事件描述。\n"
        f"对方：{profile.get('name', '')}（关系：{ghost_item.get('role', '')}）。\n"
        f"对方所在城市：{profile.get('city', '')}；性格：{profile.get('vibe', '')}\n"
        f"渠道：{template.get('channel', 'chat')}\n"
        "请输出 JSON：{\"title\": \"事件标题(≤16字)\", \"description\": \"两三句话的描述\"}。"
    )


def _parse_ghost_event_json(blob: str) -> dict[str, Any]:
    text = str(blob or "")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _apply_ghost_event_to_record(
    item: dict[str, Any],
    current_day: int,
    signal: str,
) -> None:
    closeness = float(item.get("closeness", 0.5))
    trust = float(item.get("trust", 0.5))
    obligation = float(item.get("obligation", 0.5))
    friction = float(item.get("friction", 0.5))
    if signal == "positive":
        closeness = min(1.0, closeness + 0.04)
        trust = min(1.0, trust + 0.02)
        friction = max(0.0, friction - 0.02)
    elif signal == "negative":
        closeness = max(0.0, closeness - 0.03)
        trust = max(0.0, trust - 0.03)
        friction = min(1.0, friction + 0.05)
    else:  # neutral / ambivalent
        closeness = min(1.0, closeness + 0.01)
        obligation = min(1.0, obligation + 0.01)
    item["closeness"] = closeness
    item["trust"] = trust
    item["obligation"] = obligation
    item["friction"] = friction
    item["last_contact_day"] = int(current_day)
    item["last_interaction_day"] = int(current_day)


# ---------------------------------------------------------------------------
# Social bridges (homophily) and disclosure (information asymmetry)
# ---------------------------------------------------------------------------

def _ghost_iter(agent: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    rels = agent.get("relationships", {}) if isinstance(agent, dict) else {}
    if not isinstance(rels, dict):
        return ()
    return ((k, v) for k, v in rels.items() if isinstance(v, dict) and v.get("kind") == "ghost")


def _name_token(name: str) -> str:
    return re.sub(r"\s+", "", _strip(name)).lower()


def shared_ghosts(
    agent_a: dict[str, Any],
    agent_b: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return ghost bridges between two agents.

    A bridge is reported when both agents have ghost records whose
    ``tie_origin`` matches, **or** city matches, **or** the (normalized)
    name overlaps. Each bridge surfaces both sides so callers can show
    the context in dialog ("听说你也是xx大学的").
    """
    a_items = list(_ghost_iter(agent_a))
    b_items = list(_ghost_iter(agent_b))
    if not a_items or not b_items:
        return []
    bridges: list[dict[str, Any]] = []
    for a_key, a_item in a_items:
        a_origin = _strip(a_item.get("tie_origin", "")).lower()
        a_city = _strip((a_item.get("profile") or {}).get("city", "")).lower()
        a_name = _name_token((a_item.get("profile") or {}).get("name", ""))
        for b_key, b_item in b_items:
            b_origin = _strip(b_item.get("tie_origin", "")).lower()
            b_city = _strip((b_item.get("profile") or {}).get("city", "")).lower()
            b_name = _name_token((b_item.get("profile") or {}).get("name", ""))
            via = None
            if a_origin and a_origin == b_origin:
                via = f"tie_origin:{a_origin}"
            elif a_city and a_city == b_city:
                via = f"city:{a_city}"
            elif a_name and a_name == b_name:
                via = "name"
            if via:
                bridges.append({
                    "via": via,
                    "agent_a_ghost": a_key,
                    "agent_b_ghost": b_key,
                    "a_name": (a_item.get("profile") or {}).get("name", ""),
                    "b_name": (b_item.get("profile") or {}).get("name", ""),
                })
    return bridges


def disclose_ghost(
    observer: dict[str, Any],
    source_id: int | str,
    ghost_record: dict[str, Any],
    ghost_key: str,
    current_day: int = 0,
) -> dict[str, Any]:
    """Copy a snippet of ``ghost_record`` into ``observer.known_others``.

    Information asymmetry: an agent only knows about another agent's
    ghosts after that agent has disclosed them (in dialog, in a memory,
    etc.). ``known_others`` is structured as::

        observer["known_others"][str(source_id)][ghost_key] = {snippet}

    Returns the snippet that was stored.
    """
    if not isinstance(observer, dict):
        return {}
    known = observer.setdefault("known_others", {})
    if not isinstance(known, dict):
        known = {}
        observer["known_others"] = known
    bucket = known.setdefault(str(source_id), {})
    if not isinstance(bucket, dict):
        bucket = {}
        known[str(source_id)] = bucket
    profile = ghost_record.get("profile", {}) if isinstance(ghost_record, dict) else {}
    snippet = {
        "role": ghost_record.get("role", ""),
        "tie_origin": ghost_record.get("tie_origin", ""),
        "name": profile.get("name", ""),
        "city": profile.get("city", ""),
        "vibe": profile.get("vibe", ""),
        "disclosed_on_day": int(current_day),
    }
    bucket[ghost_key] = snippet
    return snippet


def known_ghosts_of(
    observer: dict[str, Any],
    source_id: int | str,
) -> dict[str, dict[str, Any]]:
    """Return ghosts the observer knows about for a given source agent.

    Returns an empty dict when nothing has been disclosed yet (this is
    the realistic default).
    """
    known = observer.get("known_others", {}) if isinstance(observer, dict) else {}
    if not isinstance(known, dict):
        return {}
    bucket = known.get(str(source_id), {})
    return bucket if isinstance(bucket, dict) else {}


__all__ = [
    "ROLE_CONFIG",
    "DEFAULT_ROLE_CONFIG",
    "DUNBAR_TIERS",
    "role_config",
    "ensure_relationship_schema",
    "migrate_relationships",
    "role_aware_weight",
    "bootstrap_social_roster",
    "decay_relationships",
    "enforce_dunbar",
    "generate_ghost_event",
    "GHOST_EVENT_TEMPLATES",
    "shared_ghosts",
    "disclose_ghost",
    "known_ghosts_of",
]
