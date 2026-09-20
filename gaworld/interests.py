"""Interest and skill-growth profiles for simulation agents."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable, Optional

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interests")


KIND_HOBBY = "hobby"
KIND_SKILL = "skill"
ALLOWED_KINDS = {KIND_HOBBY, KIND_SKILL}

DEFAULT_MAX_ITEMS = 6

# Hidi & Renninger four-phase interest development model. Phase is a
# *derived* property of (level, total_minutes) — nothing new is persisted.
PHASE_TRIGGERED = "触发期"
PHASE_MAINTAINED = "维持期"
PHASE_EMERGING = "浮现期"
PHASE_WELL_DEVELOPED = "成熟期"

# Level thresholds crossed upward emit a milestone in the episode progress
# dict so diaries/reflections can reference tangible achievements.
MILESTONES = ((0.35, "入门"), (0.60, "熟练"), (0.85, "精通"))

DEFAULT_DECAY = {
    "enabled": True,
    "grace_days": 2,
    "daily_rate": 0.012,
    "floor": 0.05,
}
DEFAULT_EVOLUTION = {
    "enabled": True,
    "retire_after_days": 14,
    "adopt_chance": 0.35,
    "max_new_per_day": 1,
    # Career adoption from local labour demand, as a fraction of adopt_chance.
    "opportunity_factor": 0.5,
}

_PROMPT_TEMPLATE = """你是一个仿真社会的兴趣与技能成长建模助手。
请根据虚构居民 profile，推导该居民自然拥有或计划发展的兴趣爱好与技能。

profile:
姓名：{name}
年龄：{age}
职业：{job}
性格：{personality}
日常生活：{daily_life}
价值观：{values}
{city_hint}
只输出 JSON：
{{
  "items": [
    {{
      "name": "2-8字中文名称",
      "kind": "hobby 或 skill",
      "category": "运动/阅读/艺术/技术/社交/健康/职业/生活/其他",
      "motivation": "为什么会想投入",
      "level": 0.0到1.0,
      "priority": 0.0到1.0,
      "weekly_target_minutes": 30到420,
      "preferred_time_blocks": ["morning","afternoon","evening","weekend"],
      "activity_templates": ["可放入日程的中文活动短语"],
      "career_link": true或false,
      "sociality": 0.0到1.0
    }}
  ],
  "notes": "≤80字整体说明"
}}

要求：
1) items 总数不超过 {max_items}，至少包含 1 个 hobby 和 1 个 skill。
2) 不要编造极端具体经历；基于职业、性格、生活习惯做合理推断。
3) activity_templates 要能自然影响日常安排，例如“练习摄影”“阅读专业书”“跑步训练”。
4) 若给出了"所在城市"信息，可据此推断一到两项与本地产业或紧缺岗位相关的 skill
   （例如城市正发展旅游业，居民可能学习导游或酒店服务）；但要符合此人的职业与性格，
   不要让每个人都去学同样的东西。
5) 仅输出 JSON，不要解释。"""


@dataclass
class GrowthItem:
    name: str
    kind: str
    category: str = "其他"
    motivation: str = ""
    level: float = 0.2
    priority: float = 0.5
    weekly_target_minutes: int = 120
    preferred_time_blocks: list[str] = field(default_factory=list)
    activity_templates: list[str] = field(default_factory=list)
    career_link: bool = False
    sociality: float = 0.3
    last_practiced_day: int = 0
    total_minutes: int = 0
    streak_days: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GrowthItem":
        return cls(
            name=_clean_text(payload.get("name", ""), max_chars=24),
            kind=_coerce_kind(payload.get("kind", "")),
            category=_clean_text(payload.get("category", "其他"), max_chars=20) or "其他",
            motivation=_clean_text(payload.get("motivation", ""), max_chars=80),
            level=_clamp(payload.get("level", 0.2)),
            priority=_clamp(payload.get("priority", 0.5)),
            weekly_target_minutes=_coerce_int(payload.get("weekly_target_minutes", 120), 30, 420),
            preferred_time_blocks=_coerce_list(payload.get("preferred_time_blocks"), limit=4),
            activity_templates=_coerce_list(payload.get("activity_templates"), limit=4),
            career_link=bool(payload.get("career_link", False)),
            sociality=_clamp(payload.get("sociality", 0.3)),
            last_practiced_day=max(0, _coerce_int(payload.get("last_practiced_day", 0), 0, 100000)),
            total_minutes=max(0, _coerce_int(payload.get("total_minutes", 0), 0, 10000000)),
            streak_days=max(0, _coerce_int(payload.get("streak_days", 0), 0, 100000)),
        )


@dataclass
class GrowthProfile:
    agent_id: int
    items: list[GrowthItem] = field(default_factory=list)
    notes: str = ""
    source_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": int(self.agent_id),
            "items": [item.to_dict() for item in self.items],
            "notes": self.notes,
            "source_hash": self.source_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GrowthProfile":
        raw_items = payload.get("items", [])
        items = []
        if isinstance(raw_items, list):
            for raw in raw_items:
                if isinstance(raw, dict):
                    item = GrowthItem.from_dict(raw)
                    if item.name:
                        items.append(item)
        return cls(
            agent_id=int(payload.get("agent_id", 0) or 0),
            items=items,
            notes=_clean_text(payload.get("notes", ""), max_chars=200),
            source_hash=str(payload.get("source_hash", "")),
        )


LlmFn = Callable[[str], str]


def profile_signature(agent: dict[str, Any], city_signature: str = "") -> str:
    """Cache key for a derived growth profile.

    *city_signature* must be included whenever the city steers the derivation
    (see ``derive_growth_profile``): the same resident in a textile town and in
    a tourism town should not share one cached set of skills, and without this
    the second city's influence would silently never appear.
    """
    parts = [
        str(agent.get("job", "")),
        str(agent.get("personality", "")),
        str(agent.get("daily_life", "")),
        str(agent.get("values", "")),
        str(city_signature or ""),
    ]
    return hashlib.md5("\x01".join(parts).encode("utf-8")).hexdigest()


def agent_growth_path(agent_id: int, memory_dir: str) -> str:
    return os.path.join(memory_dir, f"agent_{int(agent_id)}_growth.json")


def load_agent_growth_profile(agent_id: int, memory_dir: str) -> dict[str, Any]:
    path = agent_growth_path(agent_id, memory_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    profile = GrowthProfile.from_dict(payload)
    return profile.to_dict() if profile.items else {}


def save_agent_growth_profile(agent_id: int, profile: dict[str, Any] | GrowthProfile, memory_dir: str) -> None:
    os.makedirs(memory_dir, exist_ok=True)
    path = agent_growth_path(agent_id, memory_dir)
    if isinstance(profile, GrowthProfile):
        payload = profile.to_dict()
    elif isinstance(profile, dict):
        payload = GrowthProfile.from_dict({**profile, "agent_id": int(agent_id)}).to_dict()
    else:
        return
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_growth_cache(path: str) -> dict[int, GrowthProfile]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        _LOG.warning("growth cache unreadable, ignoring: %s", path)
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[int, GrowthProfile] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        try:
            agent_id = int(key)
        except (TypeError, ValueError):
            continue
        profile = GrowthProfile.from_dict({**value, "agent_id": agent_id})
        if profile.items:
            out[agent_id] = profile
    return out


def save_growth_cache(path: str, cache: dict[int, GrowthProfile]) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = {str(k): v.to_dict() for k, v in cache.items()}
    # Process-unique tmp: compare-event runs two scenarios in parallel that may
    # target the same global cache path; a shared "{path}.tmp" races on os.replace.
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def derive_growth_profile(
    agent: dict[str, Any],
    *,
    llm: LlmFn,
    cache: Optional[dict[int, GrowthProfile]] = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    city_hint: str = "",
    city_signature: str = "",
) -> GrowthProfile:
    agent_id = int(agent.get("id", 0) or 0)
    source_hash = profile_signature(agent, city_signature)
    if cache is not None:
        cached = cache.get(agent_id)
        if cached is not None and cached.source_hash == source_hash and cached.items:
            return _limit_profile(cached, max_items=max_items)
    prompt = _build_prompt(agent, max_items=max_items, city_hint=city_hint)
    try:
        raw = llm(prompt)
    except Exception as exc:  # noqa: BLE001 - LLM failures should not stop simulation.
        _LOG.warning("growth profile LLM call failed for agent %s: %s", agent_id, exc)
        raw = ""
    payload = _parse_json_dict(raw)
    profile = _coerce_profile(agent_id, payload, source_hash=source_hash, max_items=max_items)
    if not profile.items or not _has_kinds(profile.items):
        profile = _fallback_growth_profile(agent, source_hash=source_hash, max_items=max_items)
    if cache is not None:
        cache[agent_id] = profile
    return profile


def bootstrap_growth_profiles(
    agents: Iterable[dict[str, Any]],
    *,
    cache_path: str,
    memory_dir: str,
    llm: LlmFn,
    max_items: int = DEFAULT_MAX_ITEMS,
    stateful: bool = True,
    city_hint: str = "",
    city_signature: str = "",
) -> dict[int, GrowthProfile]:
    cache = load_growth_cache(cache_path)
    out: dict[int, GrowthProfile] = {}
    for agent in agents:
        agent_id = int(agent.get("id", 0) or 0)
        if not agent_id:
            continue
        stored = load_agent_growth_profile(agent_id, memory_dir) if stateful else {}
        stored_profile = GrowthProfile.from_dict(stored) if stored else None
        signature = profile_signature(agent, city_signature)
        if stored_profile and stored_profile.source_hash == signature and stored_profile.items:
            profile = _limit_profile(stored_profile, max_items=max_items)
            cache[agent_id] = profile
        else:
            profile = derive_growth_profile(
                agent, llm=llm, cache=cache, max_items=max_items,
                city_hint=city_hint, city_signature=city_signature,
            )
            if stateful:
                save_agent_growth_profile(agent_id, profile, memory_dir)
        agent["growth_profile"] = profile.to_dict()
        out[agent_id] = profile
    save_growth_cache(cache_path, cache)
    return out


def format_growth_context(profile: dict[str, Any] | GrowthProfile | None, *, max_items: int = DEFAULT_MAX_ITEMS) -> str:
    if profile is None:
        return "无"
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile)
    if not gp.items:
        return "无"
    lines = []
    for item in sorted(gp.items, key=lambda x: x.priority, reverse=True)[:max_items]:
        templates = "、".join(item.activity_templates[:2]) or f"练习{item.name}"
        kind = "兴趣" if item.kind == KIND_HOBBY else "技能"
        career = "；与职业发展相关" if item.career_link else ""
        lines.append(
            f"- {item.name}（{kind}/{item.category}，{growth_phase(item)}，优先级{item.priority:.2f}，"
            f"水平{item.level:.2f}，每周目标{item.weekly_target_minutes}分钟；"
            f"偏好时段：{','.join(item.preferred_time_blocks) or '灵活'}；"
            f"可安排：{templates}{career}）"
        )
    return "\n".join(lines) if lines else "无"


def growth_phase(item: dict[str, Any] | GrowthItem) -> str:
    """Classify an item into the four-phase interest development model."""
    if isinstance(item, GrowthItem):
        level, minutes = item.level, item.total_minutes
    else:
        level = _clamp(item.get("level", 0.2))
        minutes = max(0, _coerce_int(item.get("total_minutes", 0), 0, 10000000))
    if level < 0.25 and minutes < 300:
        return PHASE_TRIGGERED
    if level < 0.45:
        return PHASE_MAINTAINED
    if level < 0.70:
        return PHASE_EMERGING
    return PHASE_WELL_DEVELOPED


def growth_focus(profile: dict[str, Any] | GrowthProfile | None, limit: int = 2) -> list[str]:
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile or {})
    items = sorted(gp.items, key=lambda item: (item.priority, -item.level), reverse=True)
    return [item.name for item in items[: max(0, int(limit))] if item.name]


def match_growth_items(
    profile: dict[str, Any] | GrowthProfile | None,
    *texts: Any,
) -> list[dict[str, Any]]:
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile or {})
    blob = " ".join(str(t or "") for t in texts)
    if not blob:
        return []
    matches = []
    for item in gp.items:
        terms = [item.name, item.category, *item.activity_templates]
        if any(term and term in blob for term in terms):
            matches.append(item.to_dict())
            continue
        if item.kind == KIND_SKILL and any(k in blob for k in ["学习", "练习", "训练", "研究", "课程", "项目", "作品"]):
            if any(k in blob for k in _skill_keywords(item)):
                matches.append(item.to_dict())
        elif item.kind == KIND_HOBBY and any(k in blob for k in ["放松", "休闲", "兴趣", "娱乐", "散步", "阅读"]):
            if any(k in blob for k in _hobby_keywords(item)):
                matches.append(item.to_dict())
    return _dedupe_match_dicts(matches)


def update_growth_from_episode(
    profile: dict[str, Any] | GrowthProfile | None,
    episode: dict[str, Any],
    *,
    step_minutes: int = 30,
) -> tuple[dict[str, Any], dict[str, Any]]:
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile or {})
    if not gp.items:
        payload = gp.to_dict()
        return payload, {"matches": [], "minutes": 0, "level_changes": {}, "milestones": [], "reason": "no_profile"}
    matches = match_growth_items(
        gp,
        episode.get("final_activity", ""),
        episode.get("action", ""),
        episode.get("reflection", ""),
    )
    if not matches:
        payload = gp.to_dict()
        return payload, {"matches": [], "minutes": 0, "level_changes": {}, "milestones": [], "reason": "no_match"}
    match_names = {str(item.get("name", "")) for item in matches}
    minutes = max(1, int(step_minutes or 30))
    day = int(episode.get("day", 0) or 0)
    level_changes: dict[str, dict[str, float]] = {}
    milestones: list[dict[str, str]] = []
    for item in gp.items:
        if item.name not in match_names:
            continue
        before = item.level
        item.total_minutes += minutes
        if day > 0:
            if item.last_practiced_day == day - 1:
                item.streak_days += 1
            elif item.last_practiced_day != day:
                item.streak_days = 1
            item.last_practiced_day = day
        practice_factor = min(0.035, minutes / max(600.0, item.weekly_target_minutes * 4.0))
        priority_factor = 0.6 + item.priority * 0.6
        # Power-law learning curve: gains shrink as mastery grows.
        mastery_factor = 1.0 - 0.6 * item.level
        # Habit momentum: an unbroken streak compounds practice quality.
        streak_factor = 1.0 + min(0.30, 0.03 * item.streak_days)
        item.level = _clamp(item.level + practice_factor * priority_factor * mastery_factor * streak_factor)
        if abs(item.level - before) > 0.0001:
            level_changes[item.name] = {
                "before": round(before, 4),
                "after": round(item.level, 4),
            }
            for threshold, label in MILESTONES:
                if before < threshold <= item.level:
                    milestones.append({"name": item.name, "label": label})
    payload = gp.to_dict()
    progress = {
        "matches": sorted(match_names),
        "minutes": minutes,
        "level_changes": level_changes,
        "milestones": milestones,
        "reason": "matched_activity_or_action",
    }
    return payload, progress


def apply_daily_growth_decay(
    profile: dict[str, Any] | GrowthProfile | None,
    day: int,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Day-end forgetting tick: unpracticed items lose level, streaks break.

    Retention grows with accumulated practice (consolidated skills barely
    decay) and is phase-aware: triggered-phase interests are fragile,
    well-developed ones are self-sustaining.
    """
    cfg = {**DEFAULT_DECAY, **(config or {})}
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile or {})
    changes: dict[str, dict[str, float]] = {}
    if not cfg.get("enabled", True) or not gp.items:
        return gp.to_dict(), {"level_changes": changes}
    day = int(day or 0)
    grace_days = max(0, int(cfg.get("grace_days", 2)))
    daily_rate = max(0.0, float(cfg.get("daily_rate", 0.012)))
    floor = _clamp(cfg.get("floor", 0.05))
    for item in gp.items:
        idle_days = day - int(item.last_practiced_day or 0)
        if idle_days <= 0:
            continue
        if idle_days > 1 and item.streak_days:
            item.streak_days = 0
        if idle_days <= grace_days:
            continue
        retention = min(0.8, item.total_minutes / 3000.0)
        phase = growth_phase(item)
        phase_factor = {PHASE_TRIGGERED: 1.5, PHASE_WELL_DEVELOPED: 0.5}.get(phase, 1.0)
        before = item.level
        item.level = _clamp(item.level - daily_rate * (1.0 - retention) * phase_factor, lo=min(floor, before))
        if abs(item.level - before) > 0.0001:
            changes[item.name] = {"before": round(before, 4), "after": round(item.level, 4)}
    return gp.to_dict(), {"level_changes": changes}


def evolve_growth_profile(
    profile: dict[str, Any] | GrowthProfile | None,
    day: int,
    *,
    social_candidates: Iterable[str] = (),
    opportunity_candidates: Iterable[str] = (),
    config: dict[str, Any] | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    rng: Optional[Any] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Day-end interest-set turnover: retire stale triggered-phase items,
    adopt new interests by social contagion.

    ``social_candidates`` are growth-item names observed on the day's
    social partners (assembled by the caller). Pure rules, no LLM.

    ``opportunity_candidates`` are skills the *city* is short of. They adopt
    through a separate path because the framing differs: picking up 导游 because
    the local government is pushing tourism is a career move — a ``skill``
    filed under 职业 — not a hobby caught from a friend.
    """
    import random as _random

    cfg = {**DEFAULT_EVOLUTION, **(config or {})}
    rng = rng or _random
    gp = profile if isinstance(profile, GrowthProfile) else GrowthProfile.from_dict(profile or {})
    changes: dict[str, list[str]] = {"retired": [], "adopted": []}
    if not cfg.get("enabled", True):
        return gp.to_dict(), changes
    day = int(day or 0)
    retire_after = max(1, int(cfg.get("retire_after_days", 14)))

    kept: list[GrowthItem] = []
    for item in gp.items:
        idle_days = day - int(item.last_practiced_day or 0)
        stale = (
            growth_phase(item) == PHASE_TRIGGERED
            and idle_days > retire_after
            and item.priority < 0.75
        )
        if stale and len(gp.items) - len(changes["retired"]) > 1:
            changes["retired"].append(item.name)
        else:
            kept.append(item)
    gp.items = kept

    adopt_chance = _clamp(cfg.get("adopt_chance", 0.35))
    max_new = max(0, int(cfg.get("max_new_per_day", 1)))
    existing = {item.name for item in gp.items}
    for name in social_candidates:
        if len(changes["adopted"]) >= max_new or len(gp.items) >= max(1, int(max_items)):
            break
        cleaned = _clean_text(name, max_chars=24)
        if not cleaned or cleaned in existing:
            continue
        if rng.random() > adopt_chance:
            continue
        gp.items.append(
            GrowthItem(
                name=cleaned,
                kind=KIND_HOBBY,
                category="社交",
                motivation="受身边人影响而产生兴趣",
                level=0.08,
                priority=0.45,
                weekly_target_minutes=60,
                preferred_time_blocks=["evening", "weekend"],
                activity_templates=[cleaned, f"和朋友一起{cleaned}"],
                sociality=0.8,
                last_practiced_day=day,
            )
        )
        existing.add(cleaned)
        changes["adopted"].append(cleaned)

    # Career-motivated adoption from local labour demand. Rarer than social
    # contagion by default (adopt_chance * opportunity_factor): a city's
    # economy nudges people over months, it does not restaff itself overnight.
    opportunity_chance = adopt_chance * _clamp(cfg.get("opportunity_factor", 0.5))
    for name in opportunity_candidates:
        if len(changes["adopted"]) >= max_new or len(gp.items) >= max(1, int(max_items)):
            break
        cleaned = _clean_text(name, max_chars=24)
        if not cleaned or cleaned in existing:
            continue
        if rng.random() > opportunity_chance:
            continue
        gp.items.append(
            GrowthItem(
                name=cleaned,
                kind=KIND_SKILL,
                category="职业",
                motivation="本地这一行机会变多，想学来增加就业选择",
                level=0.05,
                priority=0.55,
                weekly_target_minutes=90,
                preferred_time_blocks=["evening", "weekend"],
                activity_templates=[f"学习{cleaned}", f"了解{cleaned}相关课程"],
                career_link=True,
                sociality=0.3,
                last_practiced_day=day,
            )
        )
        existing.add(cleaned)
        changes["adopted"].append(cleaned)
    return gp.to_dict(), changes


def _build_prompt(agent: dict[str, Any], max_items: int, city_hint: str = "") -> str:
    return _PROMPT_TEMPLATE.format(
        max_items=max(1, int(max_items)),
        name=agent.get("name", ""),
        age=agent.get("age", ""),
        job=agent.get("job", ""),
        personality=agent.get("personality", ""),
        daily_life=agent.get("daily_life", ""),
        values=agent.get("values", ""),
        city_hint=f"所在城市：{city_hint}\n" if city_hint else "",
    )


def _parse_json_dict(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        return {}
    try:
        data = json.loads(text.strip())
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_profile(agent_id: int, payload: dict[str, Any], *, source_hash: str, max_items: int) -> GrowthProfile:
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    items = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = GrowthItem.from_dict(raw)
            if item.name and item.kind in ALLOWED_KINDS:
                items.append(item)
            if len(items) >= max(1, int(max_items)):
                break
    return GrowthProfile(
        agent_id=int(agent_id),
        items=_ensure_kind_coverage(items, max_items=max_items),
        notes=_clean_text(payload.get("notes", ""), max_chars=200) if isinstance(payload, dict) else "",
        source_hash=source_hash,
    )


def _fallback_growth_profile(agent: dict[str, Any], *, source_hash: str, max_items: int) -> GrowthProfile:
    blob = " ".join(
        str(agent.get(k, ""))
        for k in ("job", "personality", "daily_life", "values", "work_style")
    )
    hobby = GrowthItem(
        name="阅读",
        kind=KIND_HOBBY,
        category="阅读",
        motivation="用低成本方式放松并理解外部变化",
        level=0.35,
        priority=0.52,
        weekly_target_minutes=120,
        preferred_time_blocks=["evening", "weekend"],
        activity_templates=["阅读", "阅读感兴趣的内容"],
        career_link=False,
        sociality=0.15,
    )
    if any(k in blob for k in ["运动", "健身", "跑步", "健康", "晨练"]):
        hobby = GrowthItem(
            name="运动",
            kind=KIND_HOBBY,
            category="健康",
            motivation="通过规律活动保持身体和情绪稳定",
            level=0.38,
            priority=0.60,
            weekly_target_minutes=180,
            preferred_time_blocks=["morning", "evening", "weekend"],
            activity_templates=["跑步训练", "健身锻炼", "散步拉伸"],
            sociality=0.35,
        )
    elif any(k in blob for k in ["音乐", "唱歌", "艺术", "摄影", "画"]):
        hobby = GrowthItem(
            name="艺术创作",
            kind=KIND_HOBBY,
            category="艺术",
            motivation="用创作表达情绪并获得恢复感",
            level=0.30,
            priority=0.58,
            weekly_target_minutes=150,
            preferred_time_blocks=["evening", "weekend"],
            activity_templates=["练习摄影", "做一点创作", "听音乐放松"],
            sociality=0.30,
        )

    skill_name = "沟通表达"
    skill_category = "职业"
    skill_templates = ["练习沟通表达", "整理表达材料"]
    career_link = True
    if any(k in blob for k in ["程序", "代码", "工程师", "算法", "数据", "技术"]):
        skill_name = "编程技能"
        skill_category = "技术"
        skill_templates = ["练习编程", "学习技术资料", "做小项目"]
    elif any(k in blob for k in ["教师", "老师", "学生", "研究", "论文", "学校"]):
        skill_name = "研究学习"
        skill_category = "职业"
        skill_templates = ["阅读专业资料", "整理学习笔记", "研究课题"]
    elif any(k in blob for k in ["销售", "客服", "运营", "自媒体", "平台"]):
        skill_name = "内容运营"
        skill_category = "职业"
        skill_templates = ["学习内容运营", "复盘平台内容", "练习写作"]
    elif any(k in blob for k in ["医生", "护士", "医疗", "医院"]):
        skill_name = "专业进修"
        skill_category = "职业"
        skill_templates = ["阅读专业资料", "复盘工作案例", "学习新规范"]

    skill = GrowthItem(
        name=skill_name,
        kind=KIND_SKILL,
        category=skill_category,
        motivation="希望提升长期选择空间和工作稳定性",
        level=0.28,
        priority=0.68,
        weekly_target_minutes=180,
        preferred_time_blocks=["evening", "weekend"],
        activity_templates=skill_templates,
        career_link=career_link,
        sociality=0.35,
    )
    items = [hobby, skill][: max(1, int(max_items))]
    return GrowthProfile(
        agent_id=int(agent.get("id", 0) or 0),
        items=items,
        notes="基于职业、生活习惯和价值观规则推导。",
        source_hash=source_hash,
    )


def _limit_profile(profile: GrowthProfile, *, max_items: int) -> GrowthProfile:
    items = sorted(profile.items, key=lambda item: item.priority, reverse=True)[: max(1, int(max_items))]
    return GrowthProfile(
        agent_id=profile.agent_id,
        items=items,
        notes=profile.notes,
        source_hash=profile.source_hash,
    )


def _ensure_kind_coverage(items: list[GrowthItem], *, max_items: int) -> list[GrowthItem]:
    if not items:
        return items
    has_hobby = any(item.kind == KIND_HOBBY for item in items)
    has_skill = any(item.kind == KIND_SKILL for item in items)
    if has_hobby and has_skill:
        return items[: max(1, int(max_items))]
    if not has_hobby and len(items) < max_items:
        items.append(
            GrowthItem(
                name="阅读",
                kind=KIND_HOBBY,
                category="阅读",
                motivation="补充一个稳定的恢复型兴趣",
                activity_templates=["阅读"],
            )
        )
    if not has_skill and len(items) < max_items:
        items.append(
            GrowthItem(
                name="沟通表达",
                kind=KIND_SKILL,
                category="职业",
                motivation="补充一个通用职业技能方向",
                priority=0.58,
                activity_templates=["练习沟通表达"],
                career_link=True,
            )
        )
    return items[: max(1, int(max_items))]


def _has_kinds(items: list[GrowthItem]) -> bool:
    return any(item.kind == KIND_HOBBY for item in items) and any(item.kind == KIND_SKILL for item in items)


def _skill_keywords(item: GrowthItem) -> list[str]:
    blob = f"{item.name} {item.category}"
    kws = []
    if any(k in blob for k in ["编程", "技术", "数据", "代码"]):
        kws.extend(["代码", "技术", "数据", "项目"])
    if any(k in blob for k in ["研究", "学习", "专业"]):
        kws.extend(["研究", "学习", "专业", "资料"])
    if any(k in blob for k in ["沟通", "表达", "运营", "写作"]):
        kws.extend(["沟通", "表达", "写作", "内容"])
    return kws or [item.name]


def _hobby_keywords(item: GrowthItem) -> list[str]:
    blob = f"{item.name} {item.category}"
    kws = []
    if any(k in blob for k in ["运动", "健康"]):
        kws.extend(["运动", "跑步", "健身", "散步"])
    if any(k in blob for k in ["阅读"]):
        kws.extend(["阅读", "看书"])
    if any(k in blob for k in ["艺术", "创作", "音乐", "摄影"]):
        kws.extend(["创作", "音乐", "摄影", "画"])
    return kws or [item.name]


def _dedupe_match_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in items:
        name = str(item.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(item)
    return out


def _clean_text(value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


def _coerce_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"hobby", "interest", "兴趣", "爱好"}:
        return KIND_HOBBY
    if text in {"skill", "技能", "能力"}:
        return KIND_SKILL
    return KIND_HOBBY


def _coerce_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        text = _clean_text(item, max_chars=32)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _coerce_int(value: Any, lo: int, hi: int) -> int:
    try:
        ivalue = int(float(value))
    except (TypeError, ValueError):
        ivalue = lo
    return max(lo, min(hi, ivalue))


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        fvalue = float(value)
    except (TypeError, ValueError):
        fvalue = lo
    return float(max(lo, min(hi, fvalue)))


__all__ = [
    "GrowthItem",
    "GrowthProfile",
    "agent_growth_path",
    "apply_daily_growth_decay",
    "bootstrap_growth_profiles",
    "derive_growth_profile",
    "evolve_growth_profile",
    "format_growth_context",
    "growth_focus",
    "growth_phase",
    "load_agent_growth_profile",
    "load_growth_cache",
    "match_growth_items",
    "profile_signature",
    "save_agent_growth_profile",
    "save_growth_cache",
    "update_growth_from_episode",
]
