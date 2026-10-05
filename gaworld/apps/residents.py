"""Residents as Agent Studio reads and edits them, in the request's active world.

The profile Markdown and the state CSV (the seed), the per-agent runtime files
under the memory directory (relationships, memory, habits, goals, economy,
growth), the Big Five table, the skills library and capability caches — and the
one detail card the studio renders from all of them. Every path resolves
through :mod:`gaworld.apps.world_paths`, so a world edits its own copy.

Split out of ``dashboard_server``; its old names (``ds._agent_detail``,
``ds._read_state_rows`` …) raise, pointing here.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from copy import deepcopy

from gaworld.apps import world_paths as paths
from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG

_LOG = get_logger("gaworld.dashboard")


SKILLS_DIR = os.path.join(paths.REPO_ROOT, CONFIG.get("skills", {}).get("global_dir", "data/skills"))


RELAY_STATE_PATH = os.path.join(
    paths.REPO_ROOT,
    CONFIG.get("distributed", {}).get("server", {}).get("state_path", "output/distributed/relay_state.json"),
)


PROFILE_HEADER_RE = re.compile(r"^## Profile\s+(\d+)\s*[｜|]\s*(.+?)\s*$", re.MULTILINE)


# The nine normalized [0,1] state variables that seed each agent. Order matters
# only for display; the CSV column order is preserved on write regardless.
STATE_VAR_KEYS = (
    "emotion",
    "stress",
    "econ_security",
    "city_identity",
    "policy_sensitivity",
    "platform_dependence",
    "risk_preference",
    "voice_propensity",
    "mobility_intent",
)


def profile_sections():
    try:
        with open(paths.profile_path(), "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "", []
    matches = list(PROFILE_HEADER_RE.finditer(text))
    sections = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append({
            "id": int(match.group(1)),
            "name": match.group(2).strip(),
            "start": start,
            "end": end,
            "text": text[start:end].strip() + "\n",
        })
    return text, sections


def agents_summary():
    _, sections = profile_sections()
    configured = set(int(item) for item in paths.effective_config().get("agent_ids", []))
    return [
        {
            "id": section["id"],
            "name": section["name"],
            "configured": section["id"] in configured,
        }
        for section in sections
    ]


def agent_profile(agent_id):
    _, sections = profile_sections()
    for section in sections:
        if section["id"] == int(agent_id):
            return section
    return None


def save_agent_profile(agent_id, profile_text):
    full_text, sections = profile_sections()
    target = None
    for section in sections:
        if section["id"] == int(agent_id):
            target = section
            break
    if not target:
        raise ValueError(f"Profile {agent_id} not found")
    new_block = str(profile_text).strip() + "\n\n"
    updated = full_text[:target["start"]] + new_block + full_text[target["end"]:]
    with open(paths.profile_path(), "w", encoding="utf-8") as f:
        f.write(updated)
    return agent_profile(agent_id)


def read_state_rows():
    if not os.path.exists(paths.state_csv_path()):
        return [], []
    with open(paths.state_csv_path(), "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return fieldnames, rows


def row_id(row):
    try:
        return int(float(row.get("id")))
    except (TypeError, ValueError):
        return None


def _num(value, default=0.5):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _state_row_to_payload(row):
    try:
        age = int(float(row.get("age")))
    except (TypeError, ValueError):
        age = None
    return {
        "id": row_id(row),
        "name": (row.get("name") or "").strip(),
        "gender": (row.get("gender") or "").strip(),
        "age": age,
        "hukou": (row.get("hukou") or "").strip(),
        "residence": (row.get("residence") or "").strip(),
        "state": {key: _num(row.get(key)) for key in STATE_VAR_KEYS},
    }


def agent_state(agent_id):
    _, rows = read_state_rows()
    for row in rows:
        if row_id(row) == int(agent_id):
            return _state_row_to_payload(row)
    return None


def _atomic_write_state(fieldnames, rows):
    target = paths.state_csv_path()
    tmp_path = target + ".tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    os.replace(tmp_path, target)


def save_agent_state(agent_id, payload):
    fieldnames, rows = read_state_rows()
    if not fieldnames:
        raise ValueError("State CSV is missing or empty")
    target = next((row for row in rows if row_id(row) == int(agent_id)), None)
    if target is None:
        raise ValueError(f"Agent {agent_id} not found in state CSV")
    for key in ("name", "gender", "hukou", "residence"):
        if payload.get(key) not in (None, ""):
            target[key] = str(payload[key])
    if payload.get("age") not in (None, ""):
        target["age"] = str(int(payload["age"]))
    incoming = payload.get("state") or {}
    for key in STATE_VAR_KEYS:
        if incoming.get(key) is not None:
            target[key] = round(max(0.0, min(1.0, float(incoming[key]))), 4)
    _atomic_write_state(fieldnames, rows)
    result = agent_state(agent_id)
    try:
        _sync_profile_state_lines(agent_id, result["state"])
    except Exception:  # noqa: BLE001 - narrative sync is best-effort, never blocks the CSV write
        _LOG.exception("profile state sync failed for agent %s", agent_id)
    return result


def _sync_profile_state_lines(agent_id, state):
    """Mirror the CSV state onto the profile Markdown so the two don't drift.

    The CSV is authoritative. This rewrites only the two structured lines a
    profile block carries — the ``**研究增强变量初始化**`` bullets and the
    ``**核心状态变量**`` summary — leaving all narrative prose untouched. If a
    profile lacks those lines, nothing is changed.
    """
    section = agent_profile(agent_id)
    if not section:
        return
    text = section["text"]
    core = (
        f"**核心状态变量**：emotion {state['emotion']:.2f}｜stress {state['stress']:.2f}｜"
        f"econ_security {state['econ_security']:.2f}｜city_identity {state['city_identity']:.2f}"
    )
    new_text = re.sub(r"\*\*核心状态变量\*\*：.*", core, text)
    for key in ("policy_sensitivity", "platform_dependence", "risk_preference", "voice_propensity", "mobility_intent"):
        new_text = re.sub(rf"^- {key}：.*$", f"- {key}：{state[key]:.2f}", new_text, flags=re.MULTILINE)
    if new_text != text:
        save_agent_profile(agent_id, new_text)


def _social_snapshot(agent_id):
    rels = paths.read_json_file(paths.memory_file(agent_id, "_relationships"), {})
    if not isinstance(rels, dict) or not rels:
        return None
    tier_counts = {"inner": 0, "close": 0, "acquaintance": 0, "weak": 0}
    relations = []
    for key, item in rels.items():
        if not isinstance(item, dict):
            continue
        tier = item.get("dunbar_tier") or ""
        if tier in tier_counts:
            tier_counts[tier] += 1
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        relations.append({
            "id": key,
            "name": profile.get("name") or str(key),
            "role": item.get("role") or "",
            "kind": item.get("kind") or "agent",
            "tier": tier,
            "closeness": _num(item.get("closeness"), 0.0),
            "trust": _num(item.get("trust"), 0.0),
        })
    relations.sort(key=lambda r: r["closeness"], reverse=True)
    return {"count": len(relations), "tier_counts": tier_counts, "relations": relations[:40]}


DUNBAR_TIER_KEYS = ("inner", "close", "acquaintance", "weak")


# Shape a manually added tie starts from. The simulator's own relationship
# schema (gaworld/social/network.py) fills the rest on first load; these are
# the fields a hand-authored edge needs to be usable straight away.
_MANUAL_RELATION_DEFAULTS = {
    "kind": "ghost",
    "tie_origin": "manual",
    "channels": ["chat"],
    "obligation": 0.4,
    "obligation_base": 0.4,
    "friction": 0.2,
    "decay_rate": 0.002,
    "last_interaction_day": 0,
    "last_contact_day": 0,
    "dunbar_tier": "acquaintance",
}


def _new_relation_key(rels):
    index = 1
    while f"manual_{index}" in rels:
        index += 1
    return f"manual_{index}"


def save_agent_relationships(agent_id, payload):
    """Upsert / remove relationship edges edited in the Studio.

    Only the fields the UI exposes (name / role / tier / closeness / trust)
    are touched; every other key the simulator wrote — friction, channels,
    interaction days — is preserved on existing edges. ``relations`` upserts,
    ``removed`` deletes; ties outside the snapshot's top-40 window are left
    alone because neither list mentions them.
    """
    path = paths.memory_file(agent_id, "_relationships")
    rels = paths.read_json_file(path, {})
    if not isinstance(rels, dict):
        rels = {}
    for key in payload.get("removed") or []:
        rels.pop(str(key), None)
    for item in payload.get("relations") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip() or _new_relation_key(rels)
        entry = rels.get(key)
        if not isinstance(entry, dict):
            entry = deepcopy(_MANUAL_RELATION_DEFAULTS)
            rels[key] = entry
        profile = entry.get("profile")
        if not isinstance(profile, dict):
            profile = {}
            entry["profile"] = profile
        name = str(item.get("name") or "").strip()
        if name:
            profile["name"] = name
        role = str(item.get("role") or "").strip()
        if role:
            entry["role"] = role
        if item.get("tier") in DUNBAR_TIER_KEYS:
            entry["dunbar_tier"] = item["tier"]
        for field in ("closeness", "trust"):
            if item.get(field) is not None:
                entry[field] = round(max(0.0, min(1.0, float(item[field]))), 4)
    paths.atomic_write_json(path, rels)
    return _social_snapshot(agent_id) or {"count": 0, "tier_counts": {}, "relations": []}


def _scan_skill_dir(directory):
    items = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".md"):
                continue
            title = name[:-3]
            try:
                with open(os.path.join(directory, name), "r", encoding="utf-8") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped.startswith("#"):
                            title = stripped.lstrip("#").strip() or title
                            break
            except OSError:
                pass
            items.append({"file": name, "title": title})
    return items


def skills_library():
    return _scan_skill_dir(SKILLS_DIR)


def _private_skills(agent_id):
    # Mirrors SkillRegistry._private_dir: {memory_dir}/agent_{id}_skills
    memory_dir = paths.effective_config().get("memory_dir", "output/memory")
    return _scan_skill_dir(os.path.join(paths.REPO_ROOT, memory_dir, f"agent_{int(agent_id)}_skills"))


def _capabilities_snapshot(agent_id):
    real_work = paths.effective_config().get("real_work") or {}
    cache = real_work.get("capabilities_cache", "output/work/capabilities.json")
    data = paths.read_json_file(os.path.join(paths.REPO_ROOT, cache), {})
    if not isinstance(data, dict):
        return None
    entry = data.get(str(int(agent_id)))
    return entry if isinstance(entry, dict) else None


def _rag_snapshot(memory_items):
    # External-RAG memories are tagged with the [额外信息…] prefix (gaworld/sim/_rag.py).
    items = []
    for item in memory_items if isinstance(memory_items, list) else []:
        text = str(item).strip()
        if text.startswith("[额外信息"):
            items.append(text[:300])
    return {"count": len(items), "items": items[:20]}


RAG_TAG_PREFIX = "[额外信息"


MANUAL_RAG_PREFIX = "[额外信息 | 来源:manual] "


MEMORY_TEXT_MAX_CHARS = 600


MEMORY_LIST_LIMIT = 300


def _memory_items(memory):
    rows = []
    for index, raw in enumerate(memory if isinstance(memory, list) else []):
        text = str(raw).strip()
        if not text:
            continue
        rows.append({
            "index": index,
            "text": text[:MEMORY_TEXT_MAX_CHARS],
            "rag": text.startswith(RAG_TAG_PREFIX),
        })
    return rows[-MEMORY_LIST_LIMIT:]


def _habit_rows(habits):
    """Flatten the ``{phase}|{scope}|{activity}`` habit map into sorted rows."""
    rows = []
    for key, item in (habits.items() if isinstance(habits, dict) else []):
        if not isinstance(item, dict):
            continue
        parts = str(key).split("|")
        rows.append({
            "key": str(key),
            "phase": parts[0] if parts else "",
            "activity": parts[-1] if len(parts) > 1 else "",
            "preferred_action": str(item.get("preferred_action") or ""),
            "strength": _num(item.get("strength"), 0.0),
            "last_updated_day": item.get("last_updated_day"),
        })
    rows.sort(key=lambda row: row["strength"], reverse=True)
    return rows[:60]


def _schedule_rows(schedule):
    rows = []
    for item in schedule if isinstance(schedule, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "time": str(item.get("time") or ""),
            "activity": str(item.get("activity") or ""),
        })
    return rows[:80]


def _memory_detail(memory):
    intentions = memory.get("intentions")
    return {
        "long_term": _memory_items(memory.get("memory")),
        "habits": _habit_rows(memory.get("habits")),
        "intentions": intentions if isinstance(intentions, dict) else {},
        "schedule": _schedule_rows(memory.get("schedule")),
    }


def _index_memory_entry(agent_id, text):
    """Mirror a hand-added memory into the vector DB when one is already built.

    When the DB has no rows for this agent yet the simulator seeds it from the
    JSON file on its next start, so writing here would be redundant. Failures
    are swallowed: the JSON file is the source of truth and must not be held
    hostage to an embedding backend.
    """
    if paths.current_world():
        # The memory module binds the default world's vector DB at import; a
        # world's own index is rebuilt from the JSON when its simulator starts.
        return
    try:
        from gaworld.memory.store import vector_db_add_entry, vector_db_count_entries

        if vector_db_count_entries(int(agent_id)) > 0:
            vector_db_add_entry(int(agent_id), "memory", text)
    except Exception:  # noqa: BLE001 - best-effort index, never blocks the write
        _LOG.exception("vector index failed for agent %s", agent_id)


def append_agent_memory(agent_id, payload):
    """Append one hand-written long-term memory or RAG snippet."""
    kind = str(payload.get("kind") or "memory").strip().lower()
    if kind not in ("memory", "rag"):
        raise ValueError("kind must be 'memory' or 'rag'")
    text = re.sub(r"\s+", " ", str(payload.get("text") or "")).strip()
    if not text:
        raise ValueError("text is required")
    text = text[:MEMORY_TEXT_MAX_CHARS]
    if kind == "rag" and not text.startswith(RAG_TAG_PREFIX):
        text = MANUAL_RAG_PREFIX + text
    path = paths.memory_file(agent_id)
    items = paths.read_json_file(path, [])
    if not isinstance(items, list):
        items = []
    items.append(text)
    paths.atomic_write_json(path, items)
    _index_memory_entry(agent_id, text)
    return {
        "kind": kind,
        "text": text,
        "count": len(items),
        "long_term": _memory_items(items),
        "rag": _rag_snapshot(items),
    }


FINANCE_ACCOUNT_KEYS = ("checking", "savings", "investment", "housing_fund")


FINANCE_AMOUNT_KEYS = ("debt", "gross_monthly_salary", "net_monthly_salary", "monthly_rent")


FINANCE_RATE_KEYS = ("engel_coefficient", "savings_rate")


# Liquid accounts only — mirrors _total_balance in gaworld/economy/finance.py.
FINANCE_LIQUID_KEYS = ("checking", "savings", "investment")


def agent_finance(agent_id):
    econ = paths.read_json_file(paths.memory_file(agent_id, "_economy"), {})
    if isinstance(econ, dict) and econ:
        accounts = econ.get("accounts") if isinstance(econ.get("accounts"), dict) else {}
        payload = {
            "source": "state",
            "editable": True,
            "currency": str(econ.get("currency") or "CNY"),
            "accounts": {key: _num(accounts.get(key), 0.0) for key in FINANCE_ACCOUNT_KEYS},
            "balance": _num(econ.get("balance"), 0.0),
        }
        payload.update({key: _num(econ.get(key), 0.0) for key in FINANCE_AMOUNT_KEYS})
        payload.update({key: _num(econ.get(key), 0.0) for key in FINANCE_RATE_KEYS})
        return payload
    row = _finance_snapshot(agent_id)
    if not row:
        return None
    payload = {
        "source": "snapshot",
        "editable": False,
        "currency": str(row.get("currency") or "CNY"),
        "accounts": {key: _num(row.get(key), 0.0) for key in FINANCE_ACCOUNT_KEYS},
        "balance": _num(row.get("balance"), 0.0),
    }
    payload.update({key: _num(row.get(key), 0.0) for key in FINANCE_AMOUNT_KEYS})
    payload.update({key: _num(row.get(key), 0.0) for key in FINANCE_RATE_KEYS})
    return payload


def save_agent_finance(agent_id, payload):
    path = paths.memory_file(agent_id, "_economy")
    econ = paths.read_json_file(path, {})
    if not isinstance(econ, dict) or not econ:
        raise ValueError("No economy state for this agent yet — run the simulation once first")
    accounts = econ.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        econ["accounts"] = accounts
    incoming = payload.get("accounts") if isinstance(payload.get("accounts"), dict) else {}
    for key in FINANCE_ACCOUNT_KEYS:
        if incoming.get(key) is not None:
            accounts[key] = round(max(0.0, float(incoming[key])), 2)
    for key in FINANCE_AMOUNT_KEYS:
        if payload.get(key) is not None:
            econ[key] = round(max(0.0, float(payload[key])), 2)
    for key in FINANCE_RATE_KEYS:
        if payload.get(key) is not None:
            econ[key] = round(max(0.0, min(1.0, float(payload[key]))), 4)
    econ["balance"] = round(sum(_num(accounts.get(key), 0.0) for key in FINANCE_LIQUID_KEYS), 2)
    paths.atomic_write_json(path, econ)
    return agent_finance(agent_id)


def _growth_snapshot(agent_id):
    from gaworld.interests import load_agent_growth_profile

    memory_dir = os.path.join(paths.REPO_ROOT, paths.effective_config().get("memory_dir", "output/memory"))
    profile = load_agent_growth_profile(int(agent_id), memory_dir)
    return profile or None


def _openclaw_snapshot(agent_id):
    cfg = CONFIG.get("openclaw", {}) or {}
    state = paths.read_json_file(RELAY_STATE_PATH, {})
    directory = state.get("directory") if isinstance(state, dict) else {}
    directory = directory if isinstance(directory, dict) else {}

    entry = None
    openclaw_ids = set()
    for cluster, cluster_map in directory.items():
        if not isinstance(cluster_map, dict):
            continue
        for aid, item in cluster_map.items():
            if not isinstance(item, dict):
                continue
            if item.get("agent_type") == "openclaw":
                openclaw_ids.add(str(aid))
            if str(aid) == str(int(agent_id)) and entry is None:
                entry = {**item, "cluster": cluster}

    sent = received = 0
    messages = state.get("messages") if isinstance(state, dict) else []
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict):
            continue
        frm, to = str(msg.get("from_agent")), str(msg.get("to_agent"))
        if frm == str(int(agent_id)) and to in openclaw_ids:
            sent += 1
        elif to == str(int(agent_id)) and frm in openclaw_ids:
            received += 1

    is_openclaw = bool(entry and entry.get("agent_type") == "openclaw")
    return {
        "enabled": bool(cfg.get("enabled")),
        "registered": entry is not None,
        "is_openclaw_agent": is_openclaw,
        "cluster": entry.get("cluster") if entry else None,
        "node_id": entry.get("node_id") if entry else None,
        "messages_sent": sent,
        "messages_received": received,
        "connected": is_openclaw or (sent + received) > 0,
    }


def _cognition_snapshot(capabilities, growth, memory_counts, rag):
    """Derived cognitive index — NOT a measured IQ.

    Transparent composite of what the simulation actually tracks:
    skill breadth, deliverable capacity, growth levels, memory volume,
    and external (RAG) knowledge, mapped onto a familiar 60–140 scale.
    """
    caps = capabilities or {}
    growth_items = (growth or {}).get("items", []) or []
    avg_level = (
        sum(_num(item.get("level"), 0.0) for item in growth_items) / len(growth_items)
        if growth_items else 0.0
    )
    memory_total = sum(v for v in memory_counts.values() if isinstance(v, (int, float)))
    components = {
        "skill_breadth": min(1.0, len(caps.get("skills") or []) / 6.0),
        "deliverable_capacity": min(1.0, len(caps.get("deliverables") or []) / 4.0),
        "growth_level": avg_level,
        "memory_volume": min(1.0, memory_total / 200.0),
        "external_knowledge": min(1.0, rag.get("count", 0) / 10.0),
    }
    weights = {
        "skill_breadth": 0.25,
        "deliverable_capacity": 0.15,
        "growth_level": 0.25,
        "memory_volume": 0.2,
        "external_knowledge": 0.15,
    }
    score01 = sum(components[key] * weights[key] for key in weights)
    return {
        "score": round(60 + score01 * 80),
        "score01": round(score01, 4),
        "components": {key: round(value, 4) for key, value in components.items()},
    }


def _agent_card(identity, capabilities, private_skills, growth, openclaw):
    caps = capabilities or {}
    skills = list(caps.get("skills") or [])
    for skill in private_skills:
        if skill["title"] not in skills:
            skills.append(skill["title"])
    interests = list(caps.get("interests") or [])
    for item in (growth or {}).get("items", []) or []:
        name = item.get("name")
        if name and name not in interests:
            interests.append(name)
    return {
        "schema": "gaworld.agent-card/v1",
        "id": identity["id"],
        "name": identity["name"],
        "description": " · ".join(
            str(part) for part in (identity.get("gender"), f"{identity.get('age')}岁", identity.get("residence")) if part
        ),
        "job_label": caps.get("job_label") or "",
        "skills": skills,
        "interests": interests,
        "deliverables": list(caps.get("deliverables") or []),
        "adapters": list(caps.get("adapter_priority") or []),
        "openclaw_connected": bool(openclaw.get("connected")),
        "endpoints": {
            "detail": f"/api/agents/{identity['id']}/detail",
            "interview": "/api/interview",
        },
    }


def _finance_snapshot(agent_id):
    if not os.path.exists(paths.economy_snapshot_path()):
        return None
    try:
        with open(paths.economy_snapshot_path(), "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    if int(float(row.get("agent_id"))) == int(agent_id):
                        return dict(row)
                except (TypeError, ValueError):
                    continue
    except OSError:
        return None
    return None


#: The generator's authoring floor. A dimension at or above this was written
#: into the resident's 人格与行为倾向 paragraph; below it the paragraph is
#: silent. This one rule is the whole basis of the consistency flags below --
#: they are arithmetic on the scores, **not** an analysis of the text.
BIG5_AUTHORING_FLOOR = 0.5


#: Snapshot column: the five values the paragraph was authored from. Without it
#: the baseline is destroyed by the first edit and the contradiction becomes
#: invisible on reload -- which is the failure the panel exists to prevent.
BIG5_AUTHORED_COLUMN = "authored_z"


BIG5_DIMENSIONS = ("o", "c", "e", "a", "n")


#: Shown beside each slider so the reader knows what to look for in the
#: paragraph. Same wording as ``scripts/calibrate_big5.py``'s anchors, so the
#: panel and the calibrator describe the same poles.
BIG5_POLES = {
    "o": ("只走熟悉的路线、认准的做法很少改", "主动找新鲜事物、爱试没试过的做法"),
    "c": ("计划容易落空、事情往后拖", "提前排好顺序、被打断也会补回来"),
    "e": ("回避热闹场合、独处恢复精力", "主动搭话、独处久了会闷"),
    "a": ("说话直接、不太迁就别人", "先替别人考虑、难以拒绝"),
    "n": ("情绪很稳、别人急他不急", "容易往坏处想、情绪起落大"),
}


BIG5_NAMES_ZH = {
    "o": "开放性", "c": "尽责性", "e": "外向性", "a": "宜人性", "n": "神经质",
}


#: English twins, shipped alongside so the studio panel can label the sliders
#: in either language. Same approach as the config docs: both languages travel
#: in the payload and the client picks, rather than the server guessing from an
#: Accept-Language header the dashboard never sets.
BIG5_POLES_EN = {
    "o": ("sticks to familiar routes, rarely changes a settled approach",
          "seeks out what is new, likes trying what they have not tried"),
    "c": ("plans slip, things get put off",
          "orders things in advance, picks them back up after an interruption"),
    "e": ("avoids crowded occasions, recovers energy alone",
          "starts conversations, gets restless alone for long"),
    "a": ("speaks directly, does not bend much for others",
          "thinks of others first, finds it hard to refuse"),
    "n": ("steady, unhurried when others panic",
          "assumes the worst, large swings of mood"),
}


BIG5_NAMES_EN = {
    "o": "Openness", "c": "Conscientiousness", "e": "Extraversion",
    "a": "Agreeableness", "n": "Neuroticism",
}


def read_big5_rows():
    path = paths.big5_csv_path()
    if not os.path.exists(path):
        return [], []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _parse_authored(raw):
    """``"o=-0.35;c=0.48;..."`` -> dict, tolerating a missing or broken value."""
    out = {}
    for chunk in str(raw or "").split(";"):
        key, _, value = chunk.partition("=")
        key = key.strip()
        if key in BIG5_DIMENSIONS:
            try:
                out[key] = round(float(value), 4)
            except (TypeError, ValueError):
                continue
    return out


def _format_authored(values):
    return ";".join(f"{dim}={values.get(dim, 0.0):.4f}" for dim in BIG5_DIMENSIONS)


def _big5_paragraph(agent_id):
    section = agent_profile(agent_id)
    if not section:
        return ""
    match = re.search(r"\*\*人格与行为倾向\*\*：(.+)", section.get("text", "") or "")
    return match.group(1).strip() if match else ""


def _big5_consistency(current, authored, paragraph):
    """Per-dimension flags for "does the paragraph still describe this?".

    Derived from one rule -- the generator wrote a dimension into the paragraph
    iff ``|z| >= BIG5_AUTHORING_FLOOR`` -- applied to the value the paragraph
    was authored from versus the value now. **No keyword matching.** A keyword
    probe on this corpus already misled once (the personality proposal records
    an E probe reading -0.13 because the word list used topic nouns rather than
    valence-bearing phrases), and a wrong-but-confident indicator here would be
    worse than none: the operator would trust it instead of reading.

    * ``rewrite``      -- the paragraph describes this dimension and the score
      moved away from what it describes. ``severity: "flip"`` when the sign
      changed, which is a guaranteed contradiction rather than a drift.
    * ``now_missing``  -- the paragraph is silent here and the score is now
      distinctive, so the text under-describes the resident.
    * ``now_moot``     -- the paragraph describes a pole the resident no longer
      has, so the text over-describes them.
    * ``ok``           -- nothing to do.
    """
    flags = {}
    for dim in BIG5_DIMENSIONS:
        now = float(current.get(dim, 0.0))
        was = authored.get(dim)
        was_written = was is not None and abs(was) >= BIG5_AUTHORING_FLOOR
        is_written = abs(now) >= BIG5_AUTHORING_FLOOR
        state, severity = "ok", ""
        if was is None:
            state = "unknown"
        elif was_written and is_written:
            if (now > 0) != (was > 0):
                state, severity = "rewrite", "flip"
            elif abs(now - was) >= BIG5_AUTHORING_FLOOR:
                state, severity = "rewrite", "drift"
        elif was_written and not is_written:
            state = "now_moot"
        elif not was_written and is_written:
            state = "now_missing"
        flags[dim] = {
            "state": state,
            "severity": severity,
            "authored": was,
            "current": round(now, 4),
            "written_in_paragraph": was_written,
        }
    return flags


def agent_big5(agent_id):
    _, rows = read_big5_rows()
    target = next((r for r in rows if row_id(r) == int(agent_id)), None)
    if target is None:
        return None
    values = {}
    for dim in BIG5_DIMENSIONS:
        try:
            values[dim] = round(float(target.get(dim) or 0.0), 4)
        except (TypeError, ValueError):
            values[dim] = 0.0
    authored = _parse_authored(target.get(BIG5_AUTHORED_COLUMN))
    if not authored and str(target.get("source", "")).strip() == "sampled_authored":
        # Never hand-edited: the values on disk *are* what the paragraph was
        # written from, so they are the baseline.
        authored = dict(values)
    paragraph = _big5_paragraph(agent_id)
    return {
        "id": int(agent_id),
        "name": target.get("name", ""),
        "values": values,
        "authored": authored,
        "source": target.get("source", ""),
        "paragraph": paragraph,
        "consistency": _big5_consistency(values, authored, paragraph),
        "poles": BIG5_POLES,
        "names": BIG5_NAMES_ZH,
        "poles_en": BIG5_POLES_EN,
        "names_en": BIG5_NAMES_EN,
        "floor": BIG5_AUTHORING_FLOOR,
        "clip": 2.5,
    }


def save_agent_big5(agent_id, payload):
    """Write the five z scores back to the seed CSV.

    Three things happen besides the numbers:

    * ``source`` becomes ``hand_edited`` so a later run is not attributed to the
      sampler that no longer produced these values;
    * the authored baseline is snapshotted on the first edit, so the paragraph
      comparison survives reloads;
    * ``redundant`` is cleared, because it was the verdict of a collinearity
      gate run against values that have just changed.
    """
    fieldnames, rows = read_big5_rows()
    if not fieldnames:
        raise ValueError("Big Five CSV is missing or empty")
    target = next((r for r in rows if row_id(r) == int(agent_id)), None)
    if target is None:
        raise ValueError(f"Agent {agent_id} not found in {os.path.basename(paths.big5_csv_path())}")

    if BIG5_AUTHORED_COLUMN not in fieldnames:
        fieldnames = list(fieldnames) + [BIG5_AUTHORED_COLUMN]
    if not str(target.get(BIG5_AUTHORED_COLUMN, "")).strip():
        baseline = {}
        for dim in BIG5_DIMENSIONS:
            try:
                baseline[dim] = round(float(target.get(dim) or 0.0), 4)
            except (TypeError, ValueError):
                baseline[dim] = 0.0
        target[BIG5_AUTHORED_COLUMN] = _format_authored(baseline)

    incoming = payload.get("values") or {}
    changed = False
    for dim in BIG5_DIMENSIONS:
        if incoming.get(dim) is None:
            continue
        try:
            value = float(incoming[dim])
        except (TypeError, ValueError):
            raise ValueError(f"{dim} is not a number") from None
        if not math.isfinite(value):
            raise ValueError(f"{dim} is not finite")
        value = round(max(-2.5, min(2.5, value)), 4)
        if str(target.get(dim, "")) != str(value):
            changed = True
        target[dim] = value
    if changed:
        target["source"] = "hand_edited"
        if "redundant" in fieldnames:
            target["redundant"] = ""

    path = paths.big5_csv_path()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    os.replace(tmp_path, path)
    return agent_big5(agent_id)


def agent_detail(agent_id):
    state = agent_state(agent_id)
    if state is None:
        return None
    profile = agent_profile(agent_id) or {}
    memory = memory_payload(agent_id)
    home = _agent_home_payload(agent_id)

    def _count(value):
        return len(value) if isinstance(value, (list, dict)) else 0

    identity = {
        "id": state["id"],
        "name": state["name"],
        "gender": state["gender"],
        "age": state["age"],
        "hukou": state["hukou"],
        "residence": state["residence"],
    }
    memory_counts = {
        "long_term": _count(memory.get("memory")),
        "habits": _count(memory.get("habits")),
        "intentions": _count(memory.get("intentions")),
        "schedule": _count(memory.get("schedule")),
    }
    capabilities = _capabilities_snapshot(agent_id)
    private_skills = _private_skills(agent_id)
    growth = _growth_snapshot(agent_id)
    rag = _rag_snapshot(memory.get("memory"))
    openclaw = _openclaw_snapshot(agent_id)
    return {
        "identity": identity,
        "state": state["state"],
        "profile_text": profile.get("text", ""),
        "memory_counts": memory_counts,
        "memory": _memory_detail(memory),
        "finance": _finance_snapshot(agent_id),
        "finance_state": agent_finance(agent_id),
        "social": _social_snapshot(agent_id),
        "skills": skills_library(),
        "private_skills": private_skills,
        "capabilities": capabilities,
        "growth": growth,
        "goals": memory.get("goals", {}),
        "rag": rag,
        "openclaw": openclaw,
        "cognition": _cognition_snapshot(capabilities, growth, memory_counts, rag),
        "agent_card": _agent_card(identity, capabilities, private_skills, growth, openclaw),
        "home": home,
    }


def _agent_home_payload(agent_id):
    """Best-effort home block for the agent-detail payload.

    Defers to :mod:`gaworld.apps.home_api` so the writer (the plugin) and
    the reader (this endpoint) cannot drift. Returns ``{"has_home": False}``
    when no design exists yet — the front-end treats that as the empty
    state rather than as a 404."""
    try:
        from gaworld.apps import home_api
    except ImportError:  # pragma: no cover - import is always available
        return {"has_home": False}
    payload, status = home_api.handle_get(f"/api/home/{int(agent_id)}", {})
    if status != 200 or not isinstance(payload, dict):
        return {"has_home": False}
    summary = payload.get("summary") or {}
    design = payload.get("design") or {}
    return {
        "has_home": True,
        "summary": summary,
        "design": design,
        "recent_observations": (payload.get("observations") or [])[-30:],
    }


def _next_agent_id():
    _, rows = read_state_rows()
    ids = [rid for rid in (row_id(row) for row in rows) if rid is not None]
    _, sections = profile_sections()
    ids.extend(section["id"] for section in sections)
    return (max(ids) + 1) if ids else 1


def create_agent(payload):
    from gaworld.sim.agents_loader import _clip_state_value, _format_imported_profile_block

    agent_id = _next_agent_id()
    state_in = payload.get("state") or {}
    defaults = {
        "emotion": 0.55,
        "stress": 0.5,
        "econ_security": 0.5,
        "city_identity": 0.5,
        "policy_sensitivity": 0.5,
        "platform_dependence": 0.5,
        "risk_preference": 0.5,
        "voice_propensity": 0.5,
        "mobility_intent": 0.5,
    }
    state = {key: _clip_state_value(state_in.get(key), defaults[key]) for key in STATE_VAR_KEYS}
    profile_payload = {
        "name": str(payload.get("name") or f"新智能体{agent_id}"),
        "gender": str(payload.get("gender") or "未知"),
        "age": int(payload.get("age") or 30),
        "hukou": str(payload.get("hukou") or "未知"),
        "residence": str(payload.get("residence") or "杭州"),
        "job": str(payload.get("job") or "待补充"),
        "personality": str(payload.get("personality") or "待补充"),
        "daily_life": str(payload.get("daily_life") or "待补充"),
        "values": str(payload.get("values") or "待补充"),
        "education_income": str(payload.get("education_income") or "待补充"),
        "social_network": str(payload.get("social_network") or "待补充"),
        "state": state,
    }
    fieldnames, rows = read_state_rows()
    if not fieldnames:
        raise ValueError("State CSV is missing or empty")
    new_row = {
        "id": agent_id,
        "name": profile_payload["name"],
        "gender": profile_payload["gender"],
        "age": profile_payload["age"],
        "hukou": profile_payload["hukou"],
        "residence": profile_payload["residence"],
    }
    new_row.update({key: state[key] for key in STATE_VAR_KEYS})
    rows.append({key: new_row.get(key, "") for key in fieldnames})
    _atomic_write_state(fieldnames, rows)

    with open(paths.profile_path(), "a", encoding="utf-8") as f:
        f.write(_format_imported_profile_block(agent_id, profile_payload))

    return {"id": agent_id, "name": profile_payload["name"], "state": agent_state(agent_id)}


def _tail_text(path, max_chars=12000):
    if not os.path.exists(path):
        return ""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - max_chars))
        data = f.read()
    return data.decode("utf-8", errors="replace")


#: Shock-log entry types written by the employment life events.
_EMPLOYMENT_RECORD_TYPES = ("job_change", "unemployment", "rehired")


def _employment_payload(agent_id):
    """Current job + the job changes behind it, for the agent panel.

    Read from the per-agent economy state file — the only runtime artefact
    carrying a *live* job (the profile markdown holds the Day-1 one, which is
    exactly what stops being true after a 换工作/失业 event fires).
    """
    from gaworld.economy.finance import UNEMPLOYED_JOB_TEXT

    econ = paths.read_json_file(paths.memory_file(agent_id, "_economy"), {})
    if not isinstance(econ, dict) or not econ:
        return {}
    job = str(econ.get("job") or "")
    history = [row for row in econ.get("shock_log", [])
               if isinstance(row, dict) and row.get("type") in _EMPLOYMENT_RECORD_TYPES]
    return {
        "job": job,
        "status": "unemployed" if job == UNEMPLOYED_JOB_TEXT else "employed",
        "hourly_income": _num(econ.get("base_hourly_income"), 0.0),
        "previous_job": str(econ.get("previous_job") or ""),
        "recovery_days": int(_num(econ.get("_layoff_days_remaining"), 0)),
        "history": history[-5:],
    }


def memory_payload(agent_id):
    config = paths.effective_config()
    memory_dir = config.get("memory_dir", "output/memory")
    base = os.path.join(paths.REPO_ROOT, memory_dir)
    memory = paths.read_json_file(os.path.join(base, f"agent_{agent_id}.json"), [])
    schedule = paths.read_json_file(os.path.join(base, f"agent_{agent_id}_schedule.json"), {})
    habits = paths.read_json_file(os.path.join(base, f"agent_{agent_id}_habits.json"), {})
    intentions = paths.read_json_file(os.path.join(base, f"agent_{agent_id}_intentions.json"), {})
    goals = paths.read_json_file(os.path.join(base, f"agent_{agent_id}_goals.json"), {})
    episodes = _tail_text(os.path.join(base, f"agent_{agent_id}_episodes.jsonl"), max_chars=24000)
    log_dir = os.path.join(paths.REPO_ROOT, config.get("log_dir", "output/logs"))
    log_text = _tail_text(os.path.join(log_dir, f"agent_{agent_id}.log"), max_chars=24000)
    return {
        "memory": memory,
        "schedule": schedule,
        "habits": habits,
        "intentions": intentions,
        "goals": goals,
        "episodes_tail": episodes,
        "log_tail": log_text,
        "employment": _employment_payload(agent_id),
    }


def agent_goals_payload(agent_id):
    memory_dir = paths.effective_config().get("memory_dir", "output/memory")
    base = os.path.join(paths.REPO_ROOT, memory_dir)
    return paths.read_json_file(os.path.join(base, f"agent_{int(agent_id)}_goals.json"), {})


def save_agent_goals_payload(agent_id, payload):
    from gaworld.goals import normalize_goals

    if not isinstance(payload, dict):
        raise ValueError("goals payload must be a JSON object")
    normalized = normalize_goals(payload, day=int(payload.get("last_review_day", 0) or 0))
    if not normalized:
        raise ValueError("goals payload has no valid goals")
    memory_dir = paths.effective_config().get("memory_dir", "output/memory")
    base = os.path.join(paths.REPO_ROOT, memory_dir)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"agent_{int(agent_id)}_goals.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return normalized
    return normalized


#: Name in ``dashboard_server`` before the split -> name here; its guard
#: (``dashboard_server._MovedNamesGuard``) points stale uses at these.
DASHBOARD_ALIASES = {
    "_profile_sections": "profile_sections",
    "_agents_summary": "agents_summary",
    "_agent_profile": "agent_profile",
    "_save_agent_profile": "save_agent_profile",
    "_read_state_rows": "read_state_rows",
    "_row_id": "row_id",
    "_num": "_num",
    "_state_row_to_payload": "_state_row_to_payload",
    "_agent_state": "agent_state",
    "_atomic_write_state": "_atomic_write_state",
    "_save_agent_state": "save_agent_state",
    "_sync_profile_state_lines": "_sync_profile_state_lines",
    "_social_snapshot": "_social_snapshot",
    "DUNBAR_TIER_KEYS": "DUNBAR_TIER_KEYS",
    "_MANUAL_RELATION_DEFAULTS": "_MANUAL_RELATION_DEFAULTS",
    "_new_relation_key": "_new_relation_key",
    "_save_agent_relationships": "save_agent_relationships",
    "_scan_skill_dir": "_scan_skill_dir",
    "_skills_library": "skills_library",
    "_private_skills": "_private_skills",
    "_capabilities_snapshot": "_capabilities_snapshot",
    "_rag_snapshot": "_rag_snapshot",
    "RAG_TAG_PREFIX": "RAG_TAG_PREFIX",
    "MANUAL_RAG_PREFIX": "MANUAL_RAG_PREFIX",
    "MEMORY_TEXT_MAX_CHARS": "MEMORY_TEXT_MAX_CHARS",
    "MEMORY_LIST_LIMIT": "MEMORY_LIST_LIMIT",
    "_memory_items": "_memory_items",
    "_habit_rows": "_habit_rows",
    "_schedule_rows": "_schedule_rows",
    "_memory_detail": "_memory_detail",
    "_index_memory_entry": "_index_memory_entry",
    "_append_agent_memory": "append_agent_memory",
    "FINANCE_ACCOUNT_KEYS": "FINANCE_ACCOUNT_KEYS",
    "FINANCE_AMOUNT_KEYS": "FINANCE_AMOUNT_KEYS",
    "FINANCE_RATE_KEYS": "FINANCE_RATE_KEYS",
    "FINANCE_LIQUID_KEYS": "FINANCE_LIQUID_KEYS",
    "_agent_finance": "agent_finance",
    "_save_agent_finance": "save_agent_finance",
    "_growth_snapshot": "_growth_snapshot",
    "_openclaw_snapshot": "_openclaw_snapshot",
    "_cognition_snapshot": "_cognition_snapshot",
    "_agent_card": "_agent_card",
    "_finance_snapshot": "_finance_snapshot",
    "BIG5_AUTHORING_FLOOR": "BIG5_AUTHORING_FLOOR",
    "BIG5_AUTHORED_COLUMN": "BIG5_AUTHORED_COLUMN",
    "BIG5_DIMENSIONS": "BIG5_DIMENSIONS",
    "BIG5_POLES": "BIG5_POLES",
    "BIG5_NAMES_ZH": "BIG5_NAMES_ZH",
    "BIG5_POLES_EN": "BIG5_POLES_EN",
    "BIG5_NAMES_EN": "BIG5_NAMES_EN",
    "_read_big5_rows": "read_big5_rows",
    "_parse_authored": "_parse_authored",
    "_format_authored": "_format_authored",
    "_big5_paragraph": "_big5_paragraph",
    "_big5_consistency": "_big5_consistency",
    "_agent_big5": "agent_big5",
    "_save_agent_big5": "save_agent_big5",
    "_agent_detail": "agent_detail",
    "_agent_home_payload": "_agent_home_payload",
    "_next_agent_id": "_next_agent_id",
    "_create_agent": "create_agent",
    "_tail_text": "_tail_text",
    "_EMPLOYMENT_RECORD_TYPES": "_EMPLOYMENT_RECORD_TYPES",
    "_employment_payload": "_employment_payload",
    "_memory_payload": "memory_payload",
    "_agent_goals_payload": "agent_goals_payload",
    "_save_agent_goals_payload": "save_agent_goals_payload",
    "PROFILE_HEADER_RE": "PROFILE_HEADER_RE",
    "STATE_VAR_KEYS": "STATE_VAR_KEYS",
    "SKILLS_DIR": "SKILLS_DIR",
    "RELAY_STATE_PATH": "RELAY_STATE_PATH",
}
