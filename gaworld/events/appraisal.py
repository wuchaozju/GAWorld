"""事件评估·规则层。

回答一个问题：**这件事对这个人有多重？**

不调模型、零 token，永远运行。产出的 ``perceived_severity``（主体预估严重度）
与 ``concerns``（各领域的关注权重）是整条影响链的缩放依据——**实际影响 =
客观影响 × 主体预估**。

敏感度由三处叠加：

* **人格**（大五 z 分，0 = 总体平均）：N 高 → 冲击放大；C 高 → 对不可控的钱与
  时间更焦虑、对可规划的事更稳；E 高 → 社交与家庭事件放大；O 高 → 陌生情境放大；
  A 高 → 冲突放大、恢复类事件倾向求助。
* **状态脆弱性**：stress 高、经济安全感低、时间压力高 → 放大。
* **情境匹配**：失业 × 有孩/存款薄 → 更重；疾病 × 同住老人小孩 → 更重。
  这一条是"客观影响 × 主体预估"最有价值的部分：同一件事对不同的人落在不同领域。

模型层（:mod:`gaworld.events.appraisal_llm`）看得更细，但被夹在规则值的
0.5–1.8 倍之间——一个把小事想得比天大的居民不会让世界跟着他走。
"""

from __future__ import annotations

from typing import Any

from gaworld.events.impact import Impact, objective_severity
from gaworld.personality.traits import traits_of

#: 应对方式。给日志、记录与提示词用——居民"怎么应对"是行为的一部分，
#: 不是装饰：外化情绪的人会去找人说话，内敛消化的人会自己扛着。
COPING_STYLES: tuple[str, ...] = (
    "行动解决",  # 列清单，逐项处理
    "求助他人",  # 找人商量、借钱、托人
    "内敛消化",  # 自己扛，不说
    "外化情绪",  # 说出来，靠倾诉缓解
    "探索重构",  # 当成新机会重新安排
)

_WORK_KEYWORDS = ("工作", "上班", "值班", "加班", "开会", "通勤")


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _family_record(agent: Any) -> dict[str, Any]:
    if not isinstance(agent, dict):
        return {}
    ext = agent.get("ext")
    if not isinstance(ext, dict):
        return {}
    record = ext.get("family")
    return record if isinstance(record, dict) else {}


def _coresident_members(record: dict[str, Any]) -> list[dict[str, Any]]:
    members = record.get("members") if isinstance(record, dict) else None
    if not isinstance(members, list):
        return []
    return [m for m in members if isinstance(m, dict) and m.get("coresident")]


def _dependents(record: dict[str, Any]) -> int:
    """Children and elders living under the same roof."""
    count = 0
    for member in _coresident_members(record):
        if member.get("role") in ("child", "father", "mother", "parent"):
            count += 1
    return count


def _economic_exposure(agent: Any) -> dict[str, Any]:
    """How exposed this resident is to money shocks."""
    econ = agent.get("economy") if isinstance(agent, dict) else None
    econ = econ if isinstance(econ, dict) else {}
    accounts = econ.get("accounts") if isinstance(econ.get("accounts"), dict) else {}
    savings = _to_float(accounts.get("savings", 0.0), 0.0)
    monthly = _to_float(econ.get("gross_monthly_salary", 0.0), 0.0)
    debt = _to_float(econ.get("debt", 0.0), 0.0)
    employed = str(agent.get("employment", "employed") or "employed") == "employed"
    # "Thin buffer": less than one month of salary in savings.
    thin = monthly > 0 and savings < monthly
    return {
        "savings": savings,
        "debt": debt,
        "employed": employed,
        "thin_buffer": bool(thin),
        "has_debt": debt > 0,
    }


def _schedule_activities(schedule: Any) -> list[str]:
    if not isinstance(schedule, (list, tuple)):
        return []
    out: list[str] = []
    for item in schedule:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append(str(item[1]))
        elif isinstance(item, dict):
            out.append(str(item.get("activity", "")))
    return out


def _has_work(schedule: Any) -> bool:
    return any(any(k in act for k in _WORK_KEYWORDS) for act in _schedule_activities(schedule))


def _is_social_event(domains: set[str], event: dict[str, Any]) -> bool:
    if "family" in domains or "social" in domains:
        return True
    tags = {str(t).lower() for t in (event.get("impact_tags") or [])}
    return bool(tags & {"family", "relationship", "social", "conflict", "trust"})


def _is_conflict_event(event: dict[str, Any]) -> bool:
    tags = {str(t).lower() for t in (event.get("impact_tags") or [])}
    if tags & {"conflict", "trust", "framed"}:
        return True
    key = str(event.get("template_key", "")).lower()
    return key in ("framed", "relationship_break")


def _is_isolating_event(domains: set[str], event: dict[str, Any]) -> bool:
    if "family" in domains or "social" in domains:
        return False
    key = str(event.get("template_key", "")).lower()
    return key in ("illness", "chronic_condition", "unemployment", "bereavement")


def _trait_sensitivity(
    traits: dict[str, float],
    domains: set[str],
    event: dict[str, Any],
    rationale: list[str],
) -> float:
    """The personality part of the sensitivity multiplier."""
    n = _to_float(traits.get("n"))
    c = _to_float(traits.get("c"))
    e = _to_float(traits.get("e"))
    o = _to_float(traits.get("o"))
    a = _to_float(traits.get("a"))

    adj = 0.0
    if n > 0:
        adj += 0.20 * n
        rationale.append("神经质偏高，同一件事的冲击被放大")
    elif n < -0.4:
        adj += 0.20 * n  # 情绪稳定的居民恢复更快
        rationale.append("情绪比较稳定，冲击相对有限")

    if "economy" in domains or "schedule" in domains:
        if c > 0:
            adj += 0.12 * c
            rationale.append("做事有条理，钱与时间上的不确定性让他更焦虑")
        elif c < -0.4:
            adj -= 0.08
            rationale.append("对这类变动有准备，应对起来比较稳")

    if _is_social_event(domains, event) and e > 0:
        adj += 0.15 * e
        rationale.append("外向，容易把家里的事说出去，情绪被放大")
    elif _is_isolating_event(domains, event) and e < 0:
        adj -= 0.07
        rationale.append("习惯自己处理，孤立事件对情绪的冲击相对小")

    if o > 0.3 and _is_isolating_event(domains, event):
        adj += 0.10 * o
        rationale.append("对新情境好奇，同一件事他会多想一层")

    if _is_conflict_event(event):
        if a > 0:
            adj += 0.12 * a
            rationale.append("在意关系，被误解或冲突伤得更重")
    elif a > 0.3:
        adj += 0.08 * a
        rationale.append("习惯先找人商量，恢复起来更快")

    return adj


def _state_sensitivity(agent: Any, rationale: list[str]) -> float:
    """The vulnerability part of the sensitivity multiplier."""
    state = agent.get("state") if isinstance(agent, dict) else None
    state = state if isinstance(state, dict) else {}
    adj = 0.0

    stress = _to_float(state.get("stress", 0.5), 0.5)
    if stress > 0.5:
        adj += 0.25 * (stress - 0.5) * 2
        rationale.append("本来就绷着，新的打击落上去更重")

    econ_security = _to_float(state.get("econ_security", 0.5), 0.5)
    if econ_security < 0.5:
        adj += 0.20 * (0.5 - econ_security) * 2
        rationale.append("经济安全感本来就不高，钱的冲击被放大")

    time_pressure = _to_float(state.get("time_pressure", 0.25), 0.25)
    if time_pressure > 0.5:
        adj += 0.10 * (time_pressure - 0.5) * 2
        rationale.append("时间本来就紧，行程被打乱的代价更大")

    fatigue = _to_float(state.get("fatigue_debt", 0.2), 0.2)
    if fatigue > 0.65:
        adj += 0.10 * (fatigue - 0.65) * 2
        rationale.append("已经很累了，额外的负担压得慌")

    return adj


def _context_sensitivity(
    agent: Any,
    domains: set[str],
    schedule: Any,
    rationale: list[str],
) -> float:
    """The situation-match part: does this land harder for *this* resident?"""
    adj = 0.0
    record = _family_record(agent)
    dependents = _dependents(record)
    exposure = _economic_exposure(agent)

    if "economy" in domains:
        if dependents > 0:
            adj += 0.18
            rationale.append(f"家里有 {dependents} 个人靠他，钱的冲击直接落到其他人身上")
        if exposure["thin_buffer"]:
            adj += 0.12
            rationale.append("存款薄，扛不住突然的开支")
        if exposure["has_debt"]:
            adj += 0.08
            rationale.append("还背着债，现金流一紧就被放大")

    if "family" in domains:
        if dependents > 0:
            adj += 0.15
            rationale.append("同住的人要一起承担这件事")
        elif not record:
            adj -= 0.05
            rationale.append("一个人住，这件事主要影响自己")

    if "schedule" in domains and _has_work(schedule):
        adj += 0.10
        rationale.append("今天本来要上班，请假的机会成本更高")

    return adj


def _domain_interest(domain: str, traits: dict[str, float]) -> float:
    """How much this resident cares about this domain at all."""
    c = _to_float(traits.get("c"))
    e = _to_float(traits.get("e"))
    a = _to_float(traits.get("a"))
    o = _to_float(traits.get("o"))
    if domain == "economy":
        return max(0.4, 1.0 + 0.25 * c)
    if domain == "family":
        return max(0.4, 1.0 + 0.20 * a + 0.15 * e)
    if domain == "schedule":
        return max(0.4, 1.0 + 0.20 * c)
    if domain == "environment":
        return max(0.4, 1.0 + 0.15 * o)
    return 1.0


def _domain_exposure(
    domain: str,
    agent: Any,
    schedule: Any,
) -> float:
    """How much this domain actually touches this resident's life."""
    record = _family_record(agent)
    dependents = _dependents(record)
    exposure = _economic_exposure(agent)
    if domain == "economy":
        factor = 1.0
        if dependents > 0:
            factor *= 1.40
        if exposure["thin_buffer"]:
            factor *= 1.25
        if exposure["employed"]:
            factor *= 1.15
        return factor
    if domain == "family":
        if dependents > 0:
            return 1.60
        if record:
            return 1.15
        return 0.70
    if domain == "schedule":
        factor = 1.0
        if _has_work(schedule):
            factor *= 1.40
        activities = _schedule_activities(schedule)
        if len(activities) >= 4:
            factor *= 1.15
        return factor
    if domain == "environment":
        factor = 1.0
        vehicle = agent.get("vehicle") if isinstance(agent, dict) else None
        if not vehicle:
            factor *= 1.25
        return factor
    return 1.0


def _coping_style(traits: dict[str, float], state: dict[str, Any]) -> str:
    n = _to_float(traits.get("n"))
    e = _to_float(traits.get("e"))
    a = _to_float(traits.get("a"))
    c = _to_float(traits.get("c"))
    o = _to_float(traits.get("o"))
    stress = _to_float(state.get("stress", 0.5), 0.5)

    if n > 0.6 and e > 0.3:
        return "外化情绪"
    if n > 0.6:
        return "内敛消化"
    if a > 0.5 and n > 0.2:
        return "求助他人"
    if o > 0.5:
        return "探索重构"
    if stress > 0.65 and e < -0.2:
        return "内敛消化"
    if c > 0.4:
        return "行动解决"
    return "行动解决"


def _resilience(traits: dict[str, float]) -> float:
    n = _to_float(traits.get("n"))
    c = _to_float(traits.get("c"))
    a = _to_float(traits.get("a"))
    return _clip(1.0 + 0.12 * c - 0.15 * n + 0.08 * a, 0.55, 1.45)


def _duration_days(objective_impacts: list[Impact], traits: dict[str, float]) -> int:
    base = max((imp.duration_days for imp in objective_impacts), default=1)
    n = _to_float(traits.get("n"))
    # High neuroticism: the event keeps running in the head for longer.
    return max(1, round(base * (1.0 + 0.25 * max(0.0, n))))


def rule_appraisal(
    agent: Any,
    event: dict[str, Any],
    objective_impacts: list[Impact] | None = None,
    *,
    schedule: Any = None,
    config: Any = None,
) -> dict[str, Any]:
    """The rule-layer appraisal of an event for one resident.

    Always runs and always answers — an agent with no traits, no family, no
    economy and no schedule gets the neutral reading, not a crash.
    """
    impacts = list(objective_impacts or [])
    domains = {imp.domain for imp in impacts}
    traits = traits_of(agent, "rules") if isinstance(agent, dict) else {}
    state = agent.get("state") if isinstance(agent, dict) else None
    state = state if isinstance(state, dict) else {}
    severity = objective_severity(event)

    rationale: list[str] = []
    adj = 0.0
    adj += _trait_sensitivity(traits, domains, event, rationale)
    adj += _state_sensitivity(agent, rationale)
    adj += _context_sensitivity(agent, domains, schedule, rationale)

    sensitivity = max(0.4, min(2.2, 1.0 + adj))
    # Deliberately *not* clipped to 1.0: at severity 0.88 almost every
    # sensitive resident would saturate there, and the individual difference
    # — the whole point of the layer — would vanish. The ratio against the
    # objective severity is bounded where it matters (see
    # ``cascade.perception_factor``), and the displayed value is clipped
    # separately.
    perceived = severity * sensitivity

    concerns: dict[str, float] = {}
    for domain in sorted(domains):
        interest = _domain_interest(domain, traits)
        exposure = _domain_exposure(domain, agent, schedule)
        # Deliberately *not* normalized to the maximum: the absolute weight is
        # the point. A resident with a dependant is exposed to the economy
        # more than one who lives alone, and their economy impact has to be
        # larger — dividing by the max would erase exactly that difference.
        concerns[domain] = round(interest * exposure, 4)
    primary = max(concerns, key=concerns.get) if concerns else ""

    return {
        "objective_severity": round(severity, 4),
        "perceived_severity": round(_clip(perceived), 4),
        "perceived_severity_raw": round(perceived, 4),
        "sensitivity": round(sensitivity, 4),
        "concerns": concerns,
        "primary_concern": primary,
        "coping_style": _coping_style(traits, state),
        "resilience": round(_resilience(traits), 4),
        "duration_days": _duration_days(impacts, traits),
        "rationale": rationale,
        "source": "rules",
    }


__all__ = ["COPING_STYLES", "rule_appraisal"]
