"""Goal hierarchy (life / long-term / short-term) for agents.

Data model, JSON persistence, LLM bootstrap with heuristic fallback,
daily progress application, weekly/event reviews, prompt formatting and
episode-salience matching.

Lifecycle is owned by :mod:`gaworld.goals_plugin`; read-side consumers
(intention/routine/diary/interview prompts, salience) stay inline in the
sim — the same interim coupling the interests module uses (see
``gaworld/interests_plugin.py`` module docstring).

Design doc: docs/superpowers/specs/2026-07-18-long-term-goals-design.md
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from gaworld.logging_setup import get_logger
from gaworld.personality import personality_line

_LOG = get_logger("gaworld.goals")

LlmFn = Callable[[str], str]

DEFAULT_GOALS_CONFIG: dict[str, Any] = {
    "enabled": True,
    "review_interval_days": 7,
    "event_review_severity": 0.7,
    "max_life_goals": 2,
    "max_long_term": 3,
    "max_short_term": 4,
    "max_daily_progress_delta": 0.34,
    "review_log_keep": 12,
    "relevance_floor": 0.2,
    "relevance_cap": 0.9,
    "max_reviews_per_day": 20,
}

VALID_STATUS = {"active", "completed", "abandoned", "paused"}
VALID_DOMAINS = {"career", "family", "health", "wealth", "social", "self"}
_TIERS = ("life_goals", "long_term_goals", "short_term_goals")
_ID_PREFIX = {"life_goals": "lg", "long_term_goals": "ltg", "short_term_goals": "stg"}
# Inactive (completed/abandoned) goals kept per tier so files stay bounded.
_MAX_INACTIVE_KEPT = 8


def goals_config(config: dict | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_GOALS_CONFIG)
    if isinstance(config, dict):
        cfg.update({k: v for k, v in config.items() if v is not None})
    return cfg


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return lo


# ---------------------------------------------------------------------
# Persistence — mirrors gaworld.memory.experience file conventions.
# ---------------------------------------------------------------------

def agent_goals_path(agent_id: Any, memory_dir: str) -> str:
    return os.path.join(memory_dir, f"agent_{int(agent_id)}_goals.json")


def load_agent_goals(agent_id: Any, memory_dir: str) -> dict[str, Any]:
    path = agent_goals_path(agent_id, memory_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        _LOG.warning("goals file unreadable for agent %s; will re-bootstrap", agent_id)
        return {}
    return payload if isinstance(payload, dict) else {}


def save_agent_goals(agent_id: Any, goals: dict[str, Any], memory_dir: str) -> None:
    if not isinstance(goals, dict):
        return
    os.makedirs(memory_dir, exist_ok=True)
    path = agent_goals_path(agent_id, memory_dir)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------
# Parsing & normalization
# ---------------------------------------------------------------------

def parse_goals_json(text: Any) -> dict[str, Any]:
    match = re.search(r"\{.*\}", str(text or ""), re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _norm_goal(item: Any, tier: str, idx: int, day: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("title", "")).strip()
    if not title:
        return None
    goal: dict[str, Any] = {
        "id": str(item.get("id", "")).strip() or f"{_ID_PREFIX[tier]}{idx}",
        "title": title,
        "status": item.get("status") if item.get("status") in VALID_STATUS else "active",
    }
    if tier == "life_goals":
        goal["domain"] = item.get("domain") if item.get("domain") in VALID_DOMAINS else "self"
        goal["description"] = str(item.get("description", "")).strip()
        return goal
    goal["parent"] = str(item.get("parent", "")).strip()
    goal["progress"] = _clamp(item.get("progress", 0.0))
    try:
        goal["created_day"] = int(item.get("created_day", day) or day)
        goal["updated_day"] = int(item.get("updated_day", day) or day)
    except (TypeError, ValueError):
        goal["created_day"] = goal["updated_day"] = int(day)
    if tier == "long_term_goals":
        try:
            goal["horizon_days"] = max(30, int(item.get("horizon_days", 180) or 180))
        except (TypeError, ValueError):
            goal["horizon_days"] = 180
    else:
        try:
            goal["target_day"] = int(item.get("target_day", day + 14) or (day + 14))
        except (TypeError, ValueError):
            goal["target_day"] = int(day) + 14
        goal["recent_note"] = str(item.get("recent_note", "")).strip()
    return goal


def normalize_goals(payload: Any, *, config: dict | None = None, day: int = 0) -> dict[str, Any]:
    """Validate/clean a goals payload. Returns {} when nothing valid remains."""
    cfg = goals_config(config)
    if not isinstance(payload, dict):
        return {}
    limits = {
        "life_goals": int(cfg["max_life_goals"]),
        "long_term_goals": int(cfg["max_long_term"]),
        "short_term_goals": int(cfg["max_short_term"]),
    }
    out: dict[str, Any] = {}
    for tier in _TIERS:
        raw = payload.get(tier, [])
        cleaned = []
        for idx, item in enumerate(raw if isinstance(raw, list) else [], start=1):
            goal = _norm_goal(item, tier, idx, day)
            if goal is not None:
                cleaned.append(goal)
        active = [g for g in cleaned if g["status"] == "active"]
        inactive = [g for g in cleaned if g["status"] != "active"]
        out[tier] = active[: limits[tier]] + inactive[-_MAX_INACTIVE_KEPT:]
    if not any(out[tier] for tier in _TIERS):
        return {}
    life_ids = [g["id"] for g in out["life_goals"] if g["status"] == "active"]
    long_ids = [g["id"] for g in out["long_term_goals"] if g["status"] == "active"]
    for g in out["long_term_goals"]:
        if g.get("parent") not in life_ids and life_ids:
            g["parent"] = life_ids[0]
    for g in out["short_term_goals"]:
        if g.get("parent") not in long_ids and long_ids:
            g["parent"] = long_ids[0]
    try:
        out["last_review_day"] = int(payload.get("last_review_day", 0) or 0)
    except (TypeError, ValueError):
        out["last_review_day"] = 0
    out["needs_review"] = bool(payload.get("needs_review", False))
    log = payload.get("review_log", [])
    out["review_log"] = [
        x for x in (log if isinstance(log, list) else []) if isinstance(x, dict)
    ][-int(cfg["review_log_keep"]):]
    return out


# ---------------------------------------------------------------------
# Heuristic fallback — mirrors realism._fallback_intentions in spirit.
# ---------------------------------------------------------------------

def _fallback_goals(agent: dict, *, day: int = 0, config: dict | None = None) -> dict[str, Any]:
    job = str(agent.get("job", ""))
    state = agent.get("state", {}) if isinstance(agent.get("state"), dict) else {}
    econ = _clamp(state.get("econ_security", 0.5), 0.0, 1.0)
    if any(k in job for k in ("退休", "无业", "待业", "失业", "家庭主妇", "家庭主夫")):
        life = {"title": "健康安稳地生活，和家人朋友保持联结", "domain": "health"}
        long_term = {"title": "半年内保持规律作息和身体锻炼", "horizon_days": 180}
        short = {"title": "这两周保持每天散步或锻炼"}
    elif "学生" in job:
        life = {"title": "完成学业并找到自己热爱的方向", "domain": "self"}
        long_term = {"title": "本学期成绩稳步提升", "horizon_days": 120}
        short = {"title": "这两周跟上课程进度并按时完成作业"}
    elif econ < 0.45:
        life = {"title": "让家人过上经济安稳的生活", "domain": "wealth"}
        long_term = {"title": "一年内提高收入稳定性", "horizon_days": 365}
        short = {"title": "这两周控制开支并留意增收机会"}
    else:
        life = {"title": "在事业和生活之间找到平衡", "domain": "career"}
        long_term = {"title": "半年内在主业上有可见的进步", "horizon_days": 180}
        short = {"title": "这两周把手头的主要事务按时推进"}
    payload = {
        "life_goals": [{**life, "id": "lg1", "status": "active", "description": ""}],
        "long_term_goals": [
            {**long_term, "id": "ltg1", "parent": "lg1", "progress": 0.0, "status": "active"}
        ],
        "short_term_goals": [
            {**short, "id": "stg1", "parent": "ltg1", "progress": 0.0,
             "status": "active", "target_day": int(day) + 14}
        ],
    }
    return normalize_goals(payload, config=config, day=day)


# ---------------------------------------------------------------------
# Bootstrap (one LLM call per agent, once; heuristic fallback)
# ---------------------------------------------------------------------

def _build_bootstrap_prompt(agent: dict, cfg: dict) -> str:
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "goals"),
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    return f"""
你是城市生活模拟器的“人生规划推导器”。请根据角色资料推导其目标体系。
角色资料：
{profile_text}
当前状态：{json.dumps(agent.get('state', {}), ensure_ascii=False)}
只输出 JSON：
{{
  "life_goals": [{{"title":"...","domain":"career|family|health|wealth|social|self","description":"一句话"}}],
  "long_term_goals": [{{"title":"...","parent_index":1,"horizon_days":365}}],
  "short_term_goals": [{{"title":"...","parent_index":1,"target_day_offset":14}}]
}}
要求：
1) life_goals 1-{cfg['max_life_goals']} 个：方向性的人生追求，符合年龄、职业与价值观。
2) long_term_goals 1-{cfg['max_long_term']} 个：数月尺度、可评估进度；parent_index 指向所属人生目标序号（从1开始）。
3) short_term_goals 2-{cfg['max_short_term']} 个：1-2 周尺度、能直接落到日常安排；parent_index 指向所属长期目标序号。
4) 目标要具体、贴近角色真实生活，不要空洞口号；全部中文短语。
5) 仅输出 JSON，不要其他文字。
"""


def _coerce_bootstrap_payload(payload: dict, *, day: int, config: dict) -> dict[str, Any]:
    life, long_term, short = [], [], []
    for idx, item in enumerate(payload.get("life_goals", []) or [], start=1):
        if isinstance(item, dict):
            life.append({**item, "id": f"lg{idx}", "status": "active"})
    for idx, item in enumerate(payload.get("long_term_goals", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        try:
            parent = int(item.get("parent_index", 1) or 1)
        except (TypeError, ValueError):
            parent = 1
        long_term.append({**item, "id": f"ltg{idx}", "parent": f"lg{parent}",
                          "progress": 0.0, "status": "active"})
    for idx, item in enumerate(payload.get("short_term_goals", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        try:
            parent = int(item.get("parent_index", 1) or 1)
        except (TypeError, ValueError):
            parent = 1
        try:
            offset = int(item.get("target_day_offset", 14) or 14)
        except (TypeError, ValueError):
            offset = 14
        short.append({**item, "id": f"stg{idx}", "parent": f"ltg{parent}",
                      "progress": 0.0, "status": "active",
                      "target_day": int(day) + max(3, offset)})
    return normalize_goals(
        {"life_goals": life, "long_term_goals": long_term, "short_term_goals": short},
        config=config,
        day=day,
    )


def derive_goals(agent: dict, *, llm: LlmFn, day: int = 0, config: dict | None = None) -> dict[str, Any]:
    cfg = goals_config(config)
    try:
        raw = llm(_build_bootstrap_prompt(agent, cfg))
    except Exception as exc:  # noqa: BLE001 - any LLM failure must fall back, never crash the sim
        _LOG.warning("goals bootstrap LLM call failed for agent %s: %s", agent.get("id"), exc)
        raw = ""
    payload = parse_goals_json(raw)
    goals = _coerce_bootstrap_payload(payload, day=day, config=cfg) if payload else {}
    if not goals or not goals.get("short_term_goals"):
        goals = _fallback_goals(agent, day=day, config=cfg)
    return goals


def bootstrap_goals(agents: list, *, llm: LlmFn, memory_dir: str,
                    stateful: bool = True, config: dict | None = None, day: int = 0) -> None:
    """Attach ``agent["goals"]`` for every agent; stored file wins over LLM."""
    cfg = goals_config(config)
    for agent in agents:
        try:
            agent_id = int(agent.get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not agent_id:
            continue
        stored = load_agent_goals(agent_id, memory_dir) if stateful else {}
        goals = normalize_goals(stored, config=cfg, day=day) if stored else {}
        if not goals:
            goals = derive_goals(agent, llm=llm, day=day, config=cfg)
            if stateful:
                save_agent_goals(agent_id, goals, memory_dir)
        agent["goals"] = goals


# ---------------------------------------------------------------------
# Prompt formatting & episode-salience matching (read side, no LLM)
# ---------------------------------------------------------------------

def format_goals_context(goals: Any, *, max_items: int = 8) -> str:
    """Compact goals block for prompts. Short-term/long-term goals carry
    ``[id]`` markers so consolidate_day's ``goal_progress`` can reference them."""
    if not isinstance(goals, dict) or not any(goals.get(t) for t in _TIERS):
        return "无"
    lines: list[str] = []
    life = [g for g in goals.get("life_goals", []) if g.get("status") == "active"]
    if life:
        lines.append("人生方向：" + "；".join(str(g.get("title", "")) for g in life))
    for g in goals.get("long_term_goals", []):
        if g.get("status") != "active":
            continue
        lines.append(
            f"- 长期[{g.get('id')}]：{g.get('title')}（进度 {_clamp(g.get('progress', 0.0)):.0%}）"
        )
    for g in goals.get("short_term_goals", []):
        if g.get("status") != "active":
            continue
        note = f"；最近：{g['recent_note']}" if g.get("recent_note") else ""
        lines.append(
            f"- 短期[{g.get('id')}]：{g.get('title')}"
            f"（进度 {_clamp(g.get('progress', 0.0)):.0%}，目标 Day {g.get('target_day', '?')}{note}）"
        )
    return "\n".join(lines[: max(1, max_items)]) if lines else "无"


def _goal_terms(text: Any) -> list[str]:
    tokens = [t for t in re.split(r"[，。；、！？\s/（）()\[\]]+", str(text or "")) if len(t) >= 2]
    terms = list(tokens)
    # Unsegmented CJK tokens (e.g. a whole goal title) rarely appear verbatim
    # in episode text; add character bigrams so keyword overlap still works.
    for tok in tokens:
        if len(tok) > 2 and re.search(r"[一-鿿]", tok):
            terms.extend(tok[i:i + 2] for i in range(len(tok) - 1))
    return terms


def match_goal_relevance(goals: Any, *texts: Any, config: dict | None = None) -> float:
    """Keyword overlap between active goals and episode text → salience input.

    Returns ``relevance_floor`` (unrelated) .. ``relevance_cap`` (strong
    short-term match). No LLM — same spirit as interests.match_growth_items.
    """
    cfg = goals_config(config)
    floor = float(cfg["relevance_floor"])
    cap = float(cfg["relevance_cap"])
    if not isinstance(goals, dict):
        return floor
    blob = " ".join(str(t or "") for t in texts)
    if not blob.strip():
        return floor
    best = floor
    for tier, weight in (("short_term_goals", 1.0), ("long_term_goals", 0.75), ("life_goals", 0.55)):
        for g in goals.get(tier, []):
            if g.get("status") != "active":
                continue
            terms = _goal_terms(g.get("title")) + _goal_terms(g.get("recent_note"))
            hits = sum(1 for t in terms if t and t in blob)
            if not hits:
                continue
            ratio = min(1.0, hits / max(1, min(len(terms), 3)))
            best = max(best, floor + (cap - floor) * weight * ratio)
    return min(cap, best)


# ---------------------------------------------------------------------
# Day-end light progress (piggybacks on consolidate_day's LLM call)
# ---------------------------------------------------------------------

def apply_goal_progress(goals: Any, goal_progress: Any, day: int,
                        *, config: dict | None = None) -> tuple[Any, list[str]]:
    """Apply consolidate_day's ``goal_progress`` items. Daily pass only moves
    progress forward (setbacks are the weekly review's job) and clamps the
    per-day gain to ``max_daily_progress_delta``. Returns (goals, notes)."""
    if not isinstance(goals, dict) or not isinstance(goal_progress, list):
        return goals, []
    cfg = goals_config(config)
    max_delta = float(cfg["max_daily_progress_delta"])
    by_id: dict[str, tuple[str, dict]] = {}
    for tier in ("long_term_goals", "short_term_goals"):
        for g in goals.get(tier, []):
            by_id[str(g.get("id"))] = (tier, g)
    notes: list[str] = []
    for item in goal_progress:
        if not isinstance(item, dict):
            continue
        entry = by_id.get(str(item.get("id", "")).strip())
        if entry is None:
            continue
        tier, goal = entry
        if goal.get("status") != "active":
            continue
        old = _clamp(goal.get("progress", 0.0))
        new = _clamp(item.get("progress", old))
        new = min(new, old + max_delta)
        new = max(new, old)
        goal["progress"] = round(new, 3)
        goal["updated_day"] = int(day)
        note = str(item.get("note", "")).strip()
        if note and tier == "short_term_goals":
            goal["recent_note"] = note[:60]
        if tier == "short_term_goals" and goal["progress"] >= 1.0:
            goal["status"] = "completed"
            notes.append(f"完成短期目标：{goal.get('title')}")
        elif new > old:
            notes.append(f"{goal.get('title')} 进度 {old:.0%}→{new:.0%}")
    return goals, notes


# ---------------------------------------------------------------------
# Weekly / event-triggered reviews (one LLM call per review)
# ---------------------------------------------------------------------

def _recent_episode_lines(agent: dict, day: int, *, since_day: int = 0,
                          max_items: int = 8) -> list[str]:
    eps = [
        ep for ep in agent.get("episodes", [])
        if isinstance(ep, dict) and since_day < int(ep.get("day", 0) or 0) <= int(day)
    ]
    eps.sort(key=lambda e: float(e.get("decayed_salience", e.get("salience", 0.0))), reverse=True)
    return [
        f"Day {e.get('day')} {e.get('time', '')} {e.get('final_activity', '')} -> "
        f"{e.get('action', '')}（{str(e.get('reflection', ''))[:40]}）"
        for e in eps[:max_items]
    ]


def _review_prompt(agent: dict, goals: dict, *, day: int, trigger: str,
                   episode_lines: list[str], trigger_event: dict | None, cfg: dict) -> str:
    goals_text = json.dumps({t: goals.get(t, []) for t in _TIERS}, ensure_ascii=False, indent=2)
    event_text = ""
    if trigger == "event" and isinstance(trigger_event, dict):
        event_text = (
            f"\n触发本次回顾的重大事件：{trigger_event.get('title', '')}"
            f"（严重度 {_clamp(trigger_event.get('severity', 0.0)):.2f}）："
            f"{str(trigger_event.get('description', ''))[:100]}\n"
        )
    life_rule = (
        "5) 本次为重大事件回顾：若事件确实动摇了人生方向，最多在 life_goal_change 修改 1 条人生目标，否则给 null。"
        if trigger == "event"
        else "5) 不要改动人生目标，life_goal_change 恒为 null。"
    )
    kind = "因重大变故引发的" if trigger == "event" else "每周的"
    return f"""
你是{agent.get('name', '')}，正在进行一次{kind}个人目标回顾（今天是 Day {int(day)}）。
你的角色：{agent.get('job', '')}，{agent.get('personality', '')}
当前状态：{json.dumps(agent.get('state', {}), ensure_ascii=False)}
{event_text}
当前目标体系：
{goals_text}
自上次回顾以来的重要经历：
{json.dumps(episode_lines, ensure_ascii=False, indent=2)}

只输出 JSON：
{{
  "short_term_updates": [{{"id":"stg1","action":"keep|complete|adjust|abandon","title":"仅 adjust 时给新标题","progress":0.6}}],
  "new_short_term_goals": [{{"title":"...","parent":"ltg1","target_day_offset":14}}],
  "long_term_updates": [{{"id":"ltg1","action":"keep|complete|abandon","progress":0.3}}],
  "new_long_term_goals": [{{"title":"...","parent":"lg1","horizon_days":365}}],
  "life_goal_change": null,
  "summary": "一段中文回顾小结（50字内）"
}}
要求：
1) 已实际完成的短期目标标 complete；不再合适的标 abandon；方向对但内容要变的用 adjust。
2) 保持 active 短期目标 2-{cfg['max_short_term']} 个（不够就在 new_short_term_goals 里补，须挂在 active 长期目标下）。
3) 长期目标进度按真实经历修订，可升可降；完成或放弃后可在 new_long_term_goals 补充。
4) 目标要具体、符合近期经历，不要空洞口号。
{life_rule}
6) 仅输出 JSON，不要其他文字。
"""


def _next_goal_id(items: list, prefix: str) -> str:
    existing = {str(g.get("id")) for g in items}
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def _apply_review(goals: dict, payload: dict, *, day: int, trigger: str, cfg: dict) -> dict:
    short_by_id = {str(g.get("id")): g for g in goals.get("short_term_goals", [])}
    for upd in payload.get("short_term_updates", []) or []:
        if not isinstance(upd, dict):
            continue
        g = short_by_id.get(str(upd.get("id", "")).strip())
        if g is None or g.get("status") != "active":
            continue
        action = str(upd.get("action", "keep")).strip()
        if action == "complete":
            g["status"] = "completed"
            g["progress"] = 1.0
        elif action == "abandon":
            g["status"] = "abandoned"
        elif action == "adjust":
            title = str(upd.get("title", "")).strip()
            if title:
                g["title"] = title
            g["progress"] = _clamp(upd.get("progress", g.get("progress", 0.0)))
        elif "progress" in upd:
            g["progress"] = _clamp(upd.get("progress", g.get("progress", 0.0)))
        g["updated_day"] = int(day)
    long_by_id = {str(g.get("id")): g for g in goals.get("long_term_goals", [])}
    for upd in payload.get("long_term_updates", []) or []:
        if not isinstance(upd, dict):
            continue
        g = long_by_id.get(str(upd.get("id", "")).strip())
        if g is None or g.get("status") != "active":
            continue
        action = str(upd.get("action", "keep")).strip()
        if action == "complete":
            g["status"] = "completed"
            g["progress"] = 1.0
        elif action == "abandon":
            g["status"] = "abandoned"
        elif "progress" in upd:
            g["progress"] = _clamp(upd.get("progress", g.get("progress", 0.0)))
        g["updated_day"] = int(day)
    for item in payload.get("new_long_term_goals", []) or []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        active = [g for g in goals["long_term_goals"] if g.get("status") == "active"]
        if len(active) >= int(cfg["max_long_term"]):
            break
        try:
            horizon = max(30, int(item.get("horizon_days", 180) or 180))
        except (TypeError, ValueError):
            horizon = 180
        goals["long_term_goals"].append({
            "id": _next_goal_id(goals["long_term_goals"], "ltg"),
            "parent": str(item.get("parent", "")).strip(),
            "title": str(item["title"]).strip(),
            "horizon_days": horizon,
            "progress": 0.0, "status": "active",
            "created_day": int(day), "updated_day": int(day),
        })
    for item in payload.get("new_short_term_goals", []) or []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        active = [g for g in goals["short_term_goals"] if g.get("status") == "active"]
        if len(active) >= int(cfg["max_short_term"]):
            break
        try:
            offset = max(3, int(item.get("target_day_offset", 14) or 14))
        except (TypeError, ValueError):
            offset = 14
        goals["short_term_goals"].append({
            "id": _next_goal_id(goals["short_term_goals"], "stg"),
            "parent": str(item.get("parent", "")).strip(),
            "title": str(item["title"]).strip(),
            "target_day": int(day) + offset,
            "progress": 0.0, "status": "active", "recent_note": "",
            "created_day": int(day), "updated_day": int(day),
        })
    if trigger == "event":
        change = payload.get("life_goal_change")
        if isinstance(change, dict) and str(change.get("id", "")).strip():
            for g in goals.get("life_goals", []):
                if str(g.get("id")) == str(change.get("id")).strip():
                    title = str(change.get("title", "")).strip()
                    if title:
                        g["title"] = title
                    desc = str(change.get("description", "")).strip()
                    if desc:
                        g["description"] = desc
                    break
    return normalize_goals(goals, config=cfg, day=day)


def run_goal_review(agent: dict, *, llm: LlmFn, day: int, trigger: str = "weekly",
                    trigger_event: dict | None = None,
                    episode_lines: list[str] | None = None,
                    config: dict | None = None) -> tuple[Any, str]:
    """One review pass. On any LLM/parse failure the goals are returned
    unchanged (``last_review_day``/``needs_review`` untouched → retried later)."""
    cfg = goals_config(config)
    goals = agent.get("goals")
    if not isinstance(goals, dict) or not any(goals.get(t) for t in _TIERS):
        return goals, ""
    lines = episode_lines if isinstance(episode_lines, list) else _recent_episode_lines(
        agent, day, since_day=int(goals.get("last_review_day", 0) or 0))
    prompt = _review_prompt(agent, goals, day=day, trigger=trigger,
                            episode_lines=lines, trigger_event=trigger_event, cfg=cfg)
    try:
        raw = llm(prompt)
    except Exception as exc:  # noqa: BLE001 - review failure must not stop the day-end flow
        _LOG.warning("goals review LLM call failed for agent %s: %s", agent.get("id"), exc)
        return goals, ""
    payload = parse_goals_json(raw)
    if not payload:
        _LOG.warning("goals review unparseable for agent %s; keeping goals unchanged", agent.get("id"))
        return goals, ""
    goals = _apply_review(goals, payload, day=day, trigger=trigger, cfg=cfg)
    summary = str(payload.get("summary", "")).strip()
    goals["last_review_day"] = int(day)
    goals["needs_review"] = False
    goals.setdefault("review_log", []).append(
        {"day": int(day), "type": trigger, "summary": summary[:120]})
    goals["review_log"] = goals["review_log"][-int(cfg["review_log_keep"]):]
    agent["goals"] = goals
    return goals, summary
