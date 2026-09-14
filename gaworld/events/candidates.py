"""State-aware life-event candidates for a single agent.

The 事件模板 dropdown in the dashboard is a fixed list: every resident is
offered the same twelve events regardless of who they are. This module is the
other half — given one agent's current situation (age, job, household, money,
state variables) it ranks a larger catalogue and returns only the events that
actually apply to that person right now, so 离婚 is offered to someone married,
退休 to someone old enough, and 平台规则突变 to someone who lives off a platform.

Ranking is pure: the caller assembles the context dict from whatever artifacts
it has (``dashboard_server`` does the reading) and gets back candidates that
can be posted straight back as life events.

Context keys, all optional::

    age              int
    hukou            str   ("本地" / "外省" …)
    job              str   free text, as it appears in the profile
    employment       str   employed | unemployed | retired | student
    self_employed    bool
    marital_status   str   single | married | cohabit | divorced | widowed
    children         int   number of children
    has_parents      bool  at least one living parent
    balance          float liquid assets
    debt             float
    state            dict  the simulator's state variables, 0..1
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from gaworld.events.life import LIFE_EVENT_TEMPLATES

Context = dict[str, Any]

#: How many tags the dashboard asks for by default, and the range it accepts.
DEFAULT_CANDIDATE_LIMIT = 16
MIN_CANDIDATE_LIMIT = 10
MAX_CANDIDATE_LIMIT = 20

#: Every candidate starts here; ``weight`` moves it up or down from this base.
BASE_SCORE = 1.0

#: How long a fired event keeps its own tag out of the cloud, in simulation
#: days, keyed by the event's scale. A flu has no business being suggested
#: again next week, and a divorce none being suggested again next season — but
#: both come back eventually, and when they do it is the ranking, not this
#: table, that decides whether they resurface.
CANDIDATE_COOLDOWN_DAYS: dict[str, int] = {"day": 30, "month": 180, "year": 730}
DEFAULT_CANDIDATE_COOLDOWN_DAYS = 180

_NON_EMPLOYED_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("student", ("学生", "在读", "在校")),
    ("retired", ("退休", "离退")),
    ("unemployed", ("待业", "失业", "无业", "求职中")),
)

_SELF_EMPLOYED_KEYWORDS = ("创业", "个体", "自雇", "自营", "自由职业", "开店", "小店", "老板", "合伙")


def employment_from_job(job: str) -> str:
    """Coarse employment status read off the profile's job text."""
    text = str(job or "")
    for status, keywords in _NON_EMPLOYED_KEYWORDS:
        if any(word in text for word in keywords):
            return status
    return "employed" if text.strip() else "unknown"


def is_self_employed(job: str) -> bool:
    """True when the job text reads as running one's own thing."""
    text = str(job or "")
    return any(word in text for word in _SELF_EMPLOYED_KEYWORDS)


# ---------------------------------------------------------------------------
# Context accessors. Every one tolerates a missing or malformed field, because
# the context is assembled from run artifacts that may not exist yet.
# ---------------------------------------------------------------------------

def _sv(ctx: Context, key: str, default: float = 0.5) -> float:
    """One state variable, clamped to 0..1."""
    state = ctx.get("state")
    raw = state.get(key, default) if isinstance(state, dict) else default
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return default


def _num(ctx: Context, key: str, default: float = 0.0) -> float:
    try:
        return float(ctx.get(key, default))
    except (TypeError, ValueError):
        return default


def _int(ctx: Context, key: str, default: int = 0) -> int:
    try:
        return int(ctx.get(key, default))
    except (TypeError, ValueError):
        return default


def _text(ctx: Context, key: str) -> str:
    return str(ctx.get(key) or "").strip()


def _employment(ctx: Context) -> str:
    status = _text(ctx, "employment")
    return status or employment_from_job(_text(ctx, "job"))


def _has_job(ctx: Context) -> bool:
    return _employment(ctx) in {"employed", "unknown"}


def _marital(ctx: Context) -> str:
    return _text(ctx, "marital_status").lower()


def _partnered(ctx: Context) -> bool:
    """Is there a partner in this person's life right now?

    ``has_partner`` is read off the household members and wins when present:
    members are the ground truth the household type itself is derived from,
    and a record can carry a stale ``marital_status`` while the members say
    otherwise. Callers without household facts fall back to the status field.
    """
    explicit = ctx.get("has_partner")
    if explicit is not None:
        return bool(explicit)
    return _marital(ctx) in {"married", "cohabit", "partner"}


def _bereavable(ctx: Context) -> bool:
    """Is there actually somebody to lose?

    ``context_from_agent`` sets ``bereavable`` from the household, which is
    the precise answer: ``family.lifecycle.bereave`` declines when no
    co-resident elder (or elderly partner) exists, and an event the family
    layer then refuses is narrative with nothing behind it. Callers without
    household facts (the dashboard reads the agent files) fall back to the
    broader "has some family at all" test.
    """
    explicit = ctx.get("bereavable")
    if explicit is not None:
        return bool(explicit)
    return bool(ctx.get("has_parents", True)) or _partnered(ctx) or _int(ctx, "children") > 0


def _local_hukou(ctx: Context) -> bool:
    hukou = _text(ctx, "hukou")
    return bool(hukou) and "外" not in hukou and "省" not in hukou


# ---------------------------------------------------------------------------
# Ranking rules for the twelve dropdown templates. Titles, descriptions and
# state effects stay in life.py — only the "does this apply, and how strongly"
# half lives here, so the two lists can never drift apart.
# ---------------------------------------------------------------------------

_TEMPLATE_RULES: dict[str, dict[str, Callable[[Context], Any]]] = {
    # Family and retirement moves live in LIFE_EVENT_TEMPLATES (the digest's
    # action menu reads that list), so their gates and weights attach here
    # rather than duplicating the templates as extra candidates.
    "marriage": {
        "gate": lambda ctx: not _partnered(ctx) and _marital(ctx) != "married" and _int(ctx, "age", 30) >= 22,
        "weight": lambda ctx: (0.4 if _marital(ctx) == "cohabit" else 0.0) + 0.3 * _sv(ctx, "emotion"),
    },
    "childbirth": {
        "gate": lambda ctx: _partnered(ctx) and _int(ctx, "age", 30) <= 45,
        "weight": lambda ctx: 0.4 if _int(ctx, "children") == 0 else -0.2,
    },
    "bereavement": {
        "gate": _bereavable,
        "weight": lambda ctx: _int(ctx, "age", 30) / 90.0,
    },
    "relocation": {
        "weight": lambda ctx: 0.4 * _sv(ctx, "mobility_intent") - 0.2 * _sv(ctx, "city_identity"),
    },
    "retirement": {
        "gate": lambda ctx: _int(ctx, "age", 30) >= 55 and _employment(ctx) != "retired",
        "weight": lambda ctx: max(0.0, (_int(ctx, "age", 30) - 55) / 15.0),
    },
    "illness": {
        "weight": lambda ctx: 0.6 * _sv(ctx, "fatigue_debt", 0.3) + 0.4 * _sv(ctx, "stress"),
    },
    "lottery": {
        "weight": lambda ctx: 0.4 * _sv(ctx, "risk_preference") - 0.2,
    },
    "framed": {
        "weight": lambda ctx: 0.5 * _sv(ctx, "voice_propensity") + 0.3 * _sv(ctx, "stress") - 0.2,
    },
    "promotion": {
        "gate": _has_job,
        "weight": lambda ctx: 0.5 * _sv(ctx, "self_control", 0.6) + 0.4 * (1.0 - _sv(ctx, "stress")),
    },
    "family_emergency": {
        "gate": lambda ctx: ctx.get("has_parents", True) or _int(ctx, "children") > 0 or _partnered(ctx),
        "weight": lambda ctx: 0.3 + 0.2 * _int(ctx, "children"),
    },
    "job_change": {
        "gate": _has_job,
        "weight": lambda ctx: 0.5 * _sv(ctx, "mobility_intent") + 0.5 * (1.0 - _sv(ctx, "econ_security")),
    },
    "unemployment": {
        "gate": _has_job,
        "weight": lambda ctx: 0.7 * (1.0 - _sv(ctx, "econ_security")) + 0.4 * _sv(ctx, "stress"),
    },
    "relocation": {
        "weight": lambda ctx: 0.5 * _sv(ctx, "mobility_intent") + 0.5 * (1.0 - _sv(ctx, "city_identity")),
    },
    "further_study": {
        "gate": lambda ctx: _int(ctx, "age", 30) <= 55,
        "weight": lambda ctx: 0.4 * _sv(ctx, "risk_preference") + max(0.0, (45 - _int(ctx, "age", 30)) / 50.0),
    },
    "entrepreneurship": {
        "gate": lambda ctx: _employment(ctx) != "retired" and not ctx.get("self_employed", False),
        "weight": lambda ctx: 0.6 * _sv(ctx, "risk_preference") + 0.3 * (1.0 - _sv(ctx, "econ_security")),
    },
    "chronic_condition": {
        "gate": lambda ctx: _int(ctx, "age", 30) >= 30,
        "weight": lambda ctx: _int(ctx, "age", 30) / 120.0 + 0.4 * _sv(ctx, "fatigue_debt", 0.3),
    },
    "relationship_break": {
        "weight": lambda ctx: 0.5 * (1.0 - _sv(ctx, "emotion")) + 0.4 * _sv(ctx, "stress"),
    },
}


# ---------------------------------------------------------------------------
# The rest of the catalogue: events the dropdown never offered, most of which
# only make sense for part of the population.
# ---------------------------------------------------------------------------

EXTRA_LIFE_EVENT_CANDIDATES: list[dict[str, Any]] = [
    {
        "key": "divorce",
        "scale": "year",
        "title": "离婚",
        "description": "结束一段婚姻，住处、财务和亲子安排都要重新划分。",
        "severity": 0.90,
        "impact_tags": ["family", "relationship", "conflict", "money"],
        "state_effects": {"emotion": -0.20, "stress": 0.20, "econ_security": -0.12, "social_need": 0.10},
        "gate": lambda ctx: _marital(ctx) == "married",
        "weight": lambda ctx: 0.5 * _sv(ctx, "stress") + 0.5 * (1.0 - _sv(ctx, "emotion")),
    },
    {
        "key": "separation",
        "scale": "month",
        "title": "同居关系结束",
        "description": "与同住伴侣分开，住处和日常开销要独自承担。",
        "severity": 0.78,
        "impact_tags": ["relationship", "housing", "emotion"],
        "state_effects": {"emotion": -0.16, "stress": 0.14, "econ_security": -0.08, "social_need": 0.12},
        "gate": lambda ctx: _marital(ctx) == "cohabit",
        "weight": lambda ctx: 0.5 * (1.0 - _sv(ctx, "emotion")),
    },
    {
        "key": "new_relationship",
        "scale": "month",
        "title": "开始一段恋情",
        "description": "遇到合适的人开始交往，时间分配和情绪状态都被牵动。",
        "severity": 0.55,
        "impact_tags": ["relationship", "emotion", "routine"],
        "state_effects": {"emotion": 0.16, "social_need": -0.16, "time_pressure": 0.06},
        "gate": lambda ctx: not _partnered(ctx),
        "weight": lambda ctx: 0.5 * _sv(ctx, "social_need", 0.4) + 0.3 * _sv(ctx, "emotion"),
    },
    {
        "key": "child_milestone",
        "scale": "year",
        "title": "孩子升学",
        "description": "孩子面临入学或升学，接送、陪读和教育支出同时加码。",
        "severity": 0.6,
        "impact_tags": ["family", "obligation", "money"],
        "state_effects": {"time_pressure": 0.14, "stress": 0.10, "econ_security": -0.08},
        "gate": lambda ctx: _int(ctx, "children") > 0,
        "weight": lambda ctx: 0.2 * _int(ctx, "children"),
    },
    {
        "key": "parent_illness",
        "scale": "year",
        "title": "父母重病",
        "description": "父母查出重病，需要长期陪护和一笔不小的医疗开销。",
        "severity": 0.86,
        "impact_tags": ["family", "obligation", "health", "money"],
        "state_effects": {"emotion": -0.14, "stress": 0.20, "time_pressure": 0.14, "econ_security": -0.12},
        "gate": lambda ctx: bool(ctx.get("has_parents", True)),
        "weight": lambda ctx: _int(ctx, "age", 30) / 80.0,
    },
    {
        "key": "home_purchase",
        "scale": "year",
        "title": "买房",
        "description": "签下一套房子，首付掏空积蓄，往后多年背上月供。",
        "severity": 0.75,
        "impact_tags": ["housing", "money", "routine"],
        "state_effects": {"econ_security": -0.16, "city_identity": 0.14, "stress": 0.10, "emotion": 0.08},
        "gate": lambda ctx: _num(ctx, "balance") >= 150000 or _sv(ctx, "econ_security") >= 0.6,
        "weight": lambda ctx: 0.5 * _sv(ctx, "econ_security") + 0.3 * _sv(ctx, "city_identity"),
    },
    {
        "key": "debt_crisis",
        "scale": "year",
        "title": "债务危机",
        "description": "欠款集中到期，现金流断裂，开支要压到最低并四处周转。",
        "severity": 0.88,
        "impact_tags": ["money", "stress", "routine"],
        "state_effects": {"econ_security": -0.24, "stress": 0.22, "emotion": -0.14, "self_control": -0.06},
        "weight": lambda ctx: 0.7 * (1.0 - _sv(ctx, "econ_security")) + (0.4 if _num(ctx, "debt") > 0 else 0.0),
    },
    {
        "key": "pay_cut",
        "scale": "month",
        "title": "收入锐减",
        "description": "单量、订单或工资被砍，收入明显缩水，开销要重新算过。",
        "severity": 0.74,
        "impact_tags": ["money", "career", "stress"],
        "state_effects": {"econ_security": -0.18, "stress": 0.16, "emotion": -0.10},
        "gate": _has_job,
        "weight": lambda ctx: 0.5 * (1.0 - _sv(ctx, "econ_security")) + 0.4 * _sv(ctx, "platform_dependence"),
    },
    {
        "key": "injury",
        "scale": "day",
        "title": "意外受伤",
        "description": "一次意外造成外伤，短期内行动受限，工作和家务都得让路。",
        "severity": 0.76,
        "impact_tags": ["health", "routine", "obligation"],
        "state_effects": {"fatigue_debt": 0.16, "stress": 0.14, "emotion": -0.10, "energy": -0.12},
        "weight": lambda ctx: 0.5 * _sv(ctx, "fatigue_debt", 0.3) + 0.3 * _sv(ctx, "time_pressure", 0.25),
    },
    {
        "key": "traffic_accident",
        "scale": "day",
        "title": "交通事故",
        "description": "路上出了事故，要处理伤情、赔偿和交涉，接下来几天全乱。",
        "severity": 0.82,
        "impact_tags": ["health", "conflict", "routine", "money"],
        "state_effects": {"stress": 0.20, "emotion": -0.14, "econ_security": -0.10, "fatigue_debt": 0.10},
        "weight": lambda ctx: 0.5 * _sv(ctx, "time_pressure", 0.25) + 0.3 * _sv(ctx, "mobility_intent"),
    },
    {
        "key": "scam_loss",
        "scale": "month",
        "title": "遭遇诈骗",
        "description": "被一场网络骗局套走一笔钱，既心疼也开始怀疑线上的一切。",
        "severity": 0.8,
        "impact_tags": ["money", "trust", "emotion"],
        "state_effects": {"econ_security": -0.16, "emotion": -0.16, "stress": 0.14, "platform_dependence": -0.10},
        "weight": lambda ctx: 0.5 * _sv(ctx, "platform_dependence") + 0.3 * (1.0 - _sv(ctx, "self_control", 0.6)),
    },
    {
        "key": "viral_fame",
        "scale": "month",
        "title": "网络走红",
        "description": "一条内容意外爆火，陌生人的关注和评论一下子涌过来。",
        "severity": 0.68,
        "impact_tags": ["platform", "emotion", "social"],
        "state_effects": {"emotion": 0.12, "platform_dependence": 0.12, "voice_propensity": 0.10, "stress": 0.08},
        "weight": lambda ctx: 0.5 * _sv(ctx, "platform_dependence") + 0.4 * _sv(ctx, "voice_propensity"),
    },
    {
        "key": "public_grievance",
        "scale": "month",
        "title": "公开维权",
        "description": "为一件切身的不公站出来申诉、投诉或发声，事情拖着不好收场。",
        "severity": 0.78,
        "impact_tags": ["conflict", "policy", "stress"],
        "state_effects": {"voice_propensity": 0.14, "policy_sensitivity": 0.12, "stress": 0.14, "emotion": -0.08},
        "weight": lambda ctx: 0.4 * _sv(ctx, "voice_propensity") + 0.4 * _sv(ctx, "policy_sensitivity") + 0.2 * _sv(ctx, "stress"),
    },
    {
        "key": "award",
        "scale": "month",
        "title": "获得表彰",
        "description": "工作上被公开表扬或拿到奖励，短期内干劲和自我评价都往上走。",
        "severity": 0.5,
        "impact_tags": ["career", "emotion"],
        "state_effects": {"emotion": 0.14, "stress": -0.06, "self_control": 0.06, "econ_security": 0.06},
        "gate": _has_job,
        "weight": lambda ctx: 0.4 * _sv(ctx, "self_control", 0.6) + 0.3 * (1.0 - _sv(ctx, "stress")),
    },
    {
        "key": "old_friend_reunion",
        "scale": "month",
        "title": "老友重逢",
        "description": "多年没见的朋友重新联系上，聚了几次，久违的关系被接上。",
        "severity": 0.45,
        "impact_tags": ["social", "emotion"],
        "state_effects": {"emotion": 0.12, "social_need": -0.16, "stress": -0.06},
        "weight": lambda ctx: 0.6 * _sv(ctx, "social_need", 0.4),
    },
    {
        "key": "adopt_pet",
        "scale": "year",
        "title": "养了只宠物",
        "description": "把一只猫或狗接回家，作息里多出固定的照料时间，也多了个伴。",
        "severity": 0.5,
        "impact_tags": ["routine", "emotion", "obligation"],
        "state_effects": {"emotion": 0.12, "social_need": -0.12, "time_pressure": 0.08, "econ_security": -0.04},
        "weight": lambda ctx: 0.4 * _sv(ctx, "social_need", 0.4) + 0.3 * (1.0 - _sv(ctx, "emotion")),
    },
    {
        "key": "burnout",
        "scale": "month",
        "title": "职业倦怠",
        "description": "对工作彻底提不起劲，效率下滑，开始怀疑这份职业还值不值得。",
        "severity": 0.72,
        "impact_tags": ["career", "emotion", "health"],
        "state_effects": {"emotion": -0.16, "stress": 0.14, "fatigue_debt": 0.14, "self_control": -0.10},
        "gate": _has_job,
        "weight": lambda ctx: 0.4 * _sv(ctx, "stress") + 0.4 * _sv(ctx, "fatigue_debt", 0.3) + 0.2 * _sv(ctx, "time_pressure", 0.25),
    },
    {
        "key": "fitness_turn",
        "scale": "year",
        "title": "开始规律锻炼",
        "description": "被身体状况提醒，开始固定时间运动，作息随之调整。",
        "severity": 0.45,
        "impact_tags": ["health", "routine"],
        "state_effects": {"energy": 0.12, "fatigue_debt": -0.12, "self_control": 0.10, "emotion": 0.08},
        "weight": lambda ctx: 0.5 * _sv(ctx, "fatigue_debt", 0.3) + 0.3 * _sv(ctx, "self_control", 0.6),
    },
    {
        "key": "inheritance",
        "scale": "year",
        "title": "继承一笔遗产",
        "description": "从长辈那里继承一笔钱或一处房产，经济压力骤然松动。",
        "severity": 0.7,
        "impact_tags": ["money", "family"],
        "state_effects": {"econ_security": 0.20, "stress": -0.10, "emotion": -0.04, "risk_preference": 0.06},
        "gate": lambda ctx: _int(ctx, "age", 30) >= 30,
        "weight": lambda ctx: 0.2 * (1.0 - _sv(ctx, "econ_security")) - 0.2,
    },
    {
        "key": "leave_city",
        "scale": "year",
        "title": "离开这座城市",
        "description": "决定回老家或去另一座城市生活，工作、社交和落脚点全部重来。",
        "severity": 0.84,
        "impact_tags": ["mobility", "housing", "career", "community"],
        "state_effects": {"city_identity": -0.24, "mobility_intent": 0.14, "stress": 0.14, "social_need": 0.10},
        "weight": lambda ctx: 0.5 * _sv(ctx, "mobility_intent") + 0.5 * (1.0 - _sv(ctx, "city_identity")) - (0.2 if _local_hukou(ctx) else 0.0),
    },
    {
        "key": "lawsuit",
        "scale": "year",
        "title": "卷入官司",
        "description": "被拖进一场诉讼，要跑材料、请人咨询，结果长期悬着。",
        "severity": 0.85,
        "impact_tags": ["conflict", "money", "stress"],
        "state_effects": {"stress": 0.20, "emotion": -0.14, "econ_security": -0.12, "policy_sensitivity": 0.10},
        "weight": lambda ctx: 0.4 * _sv(ctx, "voice_propensity") + 0.3 * _sv(ctx, "stress") - 0.1,
    },
    {
        "key": "business_failure",
        "scale": "year",
        "title": "生意失败",
        "description": "自己做的这摊事做不下去了，本钱赔进去，还要收拾后续。",
        "severity": 0.88,
        "impact_tags": ["career", "employment", "money", "risk"],
        "state_effects": {"econ_security": -0.24, "stress": 0.20, "emotion": -0.16, "risk_preference": -0.10},
        "gate": lambda ctx: bool(ctx.get("self_employed", False)) or is_self_employed(_text(ctx, "job")),
        "weight": lambda ctx: 0.4 * (1.0 - _sv(ctx, "econ_security")),
    },
    {
        "key": "platform_rule_shock",
        "scale": "month",
        "title": "平台规则突变",
        "description": "赖以吃饭的平台改了派单或抽成规则，收入和作息都被重新定义。",
        "severity": 0.76,
        "impact_tags": ["platform", "money", "routine", "policy"],
        "state_effects": {"econ_security": -0.14, "stress": 0.16, "policy_sensitivity": 0.12, "platform_dependence": -0.06},
        "gate": lambda ctx: _sv(ctx, "platform_dependence") >= 0.5,
        "weight": lambda ctx: 0.6 * _sv(ctx, "platform_dependence") + 0.3 * _sv(ctx, "policy_sensitivity"),
    },
    {
        "key": "unfair_treatment",
        "scale": "month",
        "title": "遭遇不公对待",
        "description": "因为身份、户籍或出身被区别对待了一次，事后一直咽不下这口气。",
        "severity": 0.7,
        "impact_tags": ["conflict", "emotion", "policy"],
        "state_effects": {"emotion": -0.14, "city_identity": -0.12, "policy_sensitivity": 0.12, "voice_propensity": 0.08},
        "weight": lambda ctx: 0.4 * (1.0 - _sv(ctx, "city_identity")) + 0.3 * _sv(ctx, "policy_sensitivity") + (0.3 if not _local_hukou(ctx) else 0.0),
    },
    {
        "key": "mentor_opportunity",
        "scale": "year",
        "title": "遇到贵人",
        "description": "有人愿意带一把——介绍机会、指点路子，前面的路忽然宽了一点。",
        "severity": 0.55,
        "impact_tags": ["career", "social", "emotion"],
        "state_effects": {"emotion": 0.12, "econ_security": 0.08, "risk_preference": 0.06, "social_need": -0.08},
        "weight": lambda ctx: 0.3 * _sv(ctx, "social_need", 0.4) + 0.3 * _sv(ctx, "voice_propensity") - 0.1,
    },
    {
        "key": "reemployment",
        "scale": "year",
        "title": "重新找到工作",
        "description": "结束待业状态回到岗位上，收入恢复，作息重新被工作切分。",
        "severity": 0.7,
        "impact_tags": ["career", "employment", "routine", "income"],
        "state_effects": {"econ_security": 0.18, "stress": -0.08, "emotion": 0.14, "time_pressure": 0.10},
        "gate": lambda ctx: _employment(ctx) == "unemployed",
        "weight": lambda ctx: 0.6,
    },
]


def _build_catalog() -> list[dict[str, Any]]:
    """Dropdown templates (with rules attached) + the state-specific extras."""
    catalog: list[dict[str, Any]] = []
    for template in LIFE_EVENT_TEMPLATES:
        entry = dict(template)
        entry.update(_TEMPLATE_RULES.get(str(entry.get("key")), {}))
        catalog.append(entry)
    catalog.extend(dict(item) for item in EXTRA_LIFE_EVENT_CANDIDATES)
    return catalog


LIFE_EVENT_CANDIDATES: list[dict[str, Any]] = _build_catalog()

_CANDIDATES_BY_KEY: dict[str, dict[str, Any]] = {
    str(item["key"]): item for item in LIFE_EVENT_CANDIDATES
}

#: Fields a ranked candidate exposes; the callables stay behind.
_PUBLIC_FIELDS = ("key", "title", "description", "scale", "severity", "impact_tags", "state_effects")


def candidate_by_key(key: str) -> dict[str, Any] | None:
    """The catalogue entry for ``key``, public fields only."""
    entry = _CANDIDATES_BY_KEY.get(str(key or "").strip())
    return _public(entry) if entry else None


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    return {field: entry[field] for field in _PUBLIC_FIELDS if field in entry}


def candidate_cooldown_days(key: str) -> int:
    """How long ``key`` stays hidden after it fires, in simulation days."""
    entry = _CANDIDATES_BY_KEY.get(str(key or "").strip())
    scale = str((entry or {}).get("scale", "") or "").strip()
    return CANDIDATE_COOLDOWN_DAYS.get(scale, DEFAULT_CANDIDATE_COOLDOWN_DAYS)


def cooldown_keys(context: Context | None = None) -> dict[str, int]:
    """Candidates hidden by a recent firing → simulation days until they return.

    Reads ``context["recent_events"]`` (``{"key", "day", "pending"}`` per event
    already filtered to this agent) against ``context["day"]``. A queued event
    that has not fired yet maps to ``0``: it is not on a clock, it simply has
    not happened, and offering it again would only queue a duplicate.
    """
    context = context if isinstance(context, dict) else {}
    history = context.get("recent_events")
    if not isinstance(history, list):
        return {}
    current_day = _int(context, "day", 0)
    hidden: dict[str, int] = {}
    for item in history:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        # Events from other subsystems (family, ghost, social) share the file
        # but have no tag to hide.
        if key not in _CANDIDATES_BY_KEY:
            continue
        if item.get("pending"):
            hidden.setdefault(key, 0)
            continue
        try:
            elapsed = current_day - int(item.get("day"))
        except (TypeError, ValueError):
            continue
        # A negative gap means the run was reset behind this event. Treat the
        # cooldown as long expired rather than hiding the tag until a fresh run
        # catches up to an old day number.
        if elapsed < 0:
            continue
        remaining = candidate_cooldown_days(key) - elapsed
        if remaining > 0:
            hidden[key] = max(hidden.get(key, 0), remaining)
    return hidden


def context_from_agent(agent: dict[str, Any] | None) -> Context:
    """Build a gate context from a *live* agent dict.

    The dashboard builds its context from the agent files on disk; the
    simulator has the agent in memory. Both need the same gate table — a
    second eligibility mechanism is how "70-year-olds can give birth" gets
    fixed in one place and stays broken in the other — so this is the adapter
    that lets the in-run caller reuse these rules.

    Household facts come from ``agent["family_facts"]`` (published by the
    family plugin) because ``agent["family"]`` is authored prose and cannot
    answer "is there a partner?".
    """
    agent = agent if isinstance(agent, dict) else {}
    facts = agent.get("family_facts")
    facts = facts if isinstance(facts, dict) else {}
    state = agent.get("state")
    state = dict(state) if isinstance(state, dict) else {}
    economy = agent.get("economy")
    economy = economy if isinstance(economy, dict) else {}
    context: Context = {
        "agent_id": agent.get("id"),
        "name": agent.get("name", ""),
        "age": agent.get("age", 30),
        "job": agent.get("job", ""),
        "employment": agent.get("employment", ""),
        "hukou": agent.get("hukou", ""),
        "marital_status": facts.get("marital_status", ""),
        # Derived from the household members, so it wins over the status field.
        "has_partner": facts.get("has_partner") if facts else None,
        "children": int(facts.get("child_count", 0) or 0),
        # `bereavement` asks this directly; an unknown household should not
        # silently rule the event out, but a known-empty one should.
        "has_parents": bool(facts.get("coresident_elder_count", 0)) if facts else True,
        # The precise answer, when the household is known: `lifecycle.bereave`
        # needs a co-resident elder (or an elderly partner) to act on.
        "bereavable": (
            bool(facts.get("oldest_elder_age") and int(facts["oldest_elder_age"]) >= 65)
            if facts else None
        ),
        "balance": economy.get("balance", 0.0),
        "debt": economy.get("debt", 0.0),
        "state": state,
    }
    return context


def candidate_applies(key: str, context: Context | None = None) -> bool:
    """Whether ``key`` is even on the table for this situation.

    ``rank_life_event_candidates`` also sorts and truncates; this answers the
    gate question alone, for callers that want to know why a tag is missing.
    """
    entry = _CANDIDATES_BY_KEY.get(str(key or "").strip())
    return entry is not None and _applies(entry, context if isinstance(context, dict) else {})


def _applies(entry: dict[str, Any], context: Context) -> bool:
    gate = entry.get("gate")
    if not callable(gate):
        return True
    try:
        return bool(gate(context))
    except Exception:  # noqa: BLE001 - a broken rule must not blank the whole panel
        return False


def _score(entry: dict[str, Any], context: Context) -> float:
    weight = entry.get("weight")
    if not callable(weight):
        return BASE_SCORE
    try:
        return BASE_SCORE + float(weight(context))
    except Exception:  # noqa: BLE001 - same: fall back to the base score
        return BASE_SCORE


def rank_life_event_candidates(
    context: Context | None = None,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    """The events that apply to ``context`` right now, most relevant first.

    ``limit`` is clamped to 10..20 — the panel is a tag cloud, not a catalogue
    browser, and fewer than ten reads as a bug while more than twenty stops
    being a shortlist. Fewer are returned only when the agent's situation
    genuinely rules the rest out.

    An event that just fired on this agent drops out (see :func:`cooldown_keys`)
    and rejoins the pool when its cooldown expires — at which point it is back
    to competing on score like everything else, so it reappears only if the
    agent's situation still invites it.
    """
    context = context if isinstance(context, dict) else {}
    limit = max(MIN_CANDIDATE_LIMIT, min(MAX_CANDIDATE_LIMIT, int(limit)))
    hidden = cooldown_keys(context)
    scored = [
        dict(_public(entry), score=round(_score(entry, context), 4))
        for entry in LIFE_EVENT_CANDIDATES
        if entry["key"] not in hidden and _applies(entry, context)
    ]
    scored.sort(key=lambda item: (-item["score"], item["key"]))
    return scored[:limit]


def candidate_event_payload(
    key: str,
    agent_ids: Sequence[int] | Iterable[int] | str = (),
    severity: float | None = None,
) -> dict[str, Any]:
    """A life-event payload for ``key``, ready for ``add_life_event``.

    Raises ``ValueError`` for an unknown key rather than silently queueing an
    untitled event.
    """
    entry = candidate_by_key(key)
    if entry is None:
        raise ValueError(f"未知的候选事件：{key}")
    payload: dict[str, Any] = {
        "template_key": entry["key"],
        "title": entry["title"],
        "description": entry["description"],
        "severity": entry["severity"] if severity is None else severity,
        "impact_tags": list(entry.get("impact_tags", [])),
        "state_effects": dict(entry.get("state_effects", {})),
        "agent_ids": agent_ids,
        "schedule_mode": "immediate",
        "created_by": "dashboard-candidate",
    }
    return payload


#: Context fields the ranking actually reads — anything else can change without
#: the tag cloud needing a repaint.
_SIGNATURE_FIELDS = (
    "age",
    "hukou",
    "employment",
    "self_employed",
    "marital_status",
    "children",
    "has_parents",
)


def context_signature(context: Context | None = None) -> str:
    """Short digest of the ranking inputs, for cheap change detection.

    State variables are rounded to two decimals: the tag cloud should repaint
    when a resident's situation moves, not on every float that wobbles in the
    fourth decimal place each tick. The cooldown enters as the *set* of hidden
    keys rather than the day count, so the panel repaints exactly when a tag
    leaves or comes back — not on every step of the clock.
    """
    context = context if isinstance(context, dict) else {}
    state = context.get("state") if isinstance(context.get("state"), dict) else {}
    material = {
        field: context.get(field) for field in _SIGNATURE_FIELDS
    }
    material["cooldown"] = sorted(cooldown_keys(context))
    material["balance"] = round(_num(context, "balance") / 10000.0, 1)
    material["debt"] = round(_num(context, "debt") / 10000.0, 1)
    material["state"] = {
        str(key): round(float(value), 2)
        for key, value in sorted(state.items())
        if isinstance(value, (int, float))
    }
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
