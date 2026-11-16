"""事件评估·模型层：思考-反应-行动。

一次模型调用，把"这件事对我意味着什么"变成结构化数据：

* **思考**（``thought``）——他怎么理解这件事；
* **反应**（``emotion``）——情绪怎么变；
* **预估**（``appraisal``）——影响落在哪些领域、多重、多久；
* **行动**（``plan``）——接下来几天要做什么。

产出会进入三个地方：提示词（让后续的感知、计划、反思真的看到这件事）、
状态（情绪增量）、以及级联（行动计划变成真的日程改写与求助）。

**只调一次，且有门槛。** ``event_impact.appraisal.llm_min_severity`` 以下的事件
只走规则层——小事值得一个模型调用，是留给真正有后果的事的。

**不覆盖规则层，只夹逼。** 模型的 ``perceived_severity`` 被限制在规则值的
0.5–1.8 倍之间：模型看得更细，但一个人的一次判断不能把客观事实推翻。
"""

from __future__ import annotations

import json
from typing import Any

from gaworld.llm import providers as _llm_providers
from gaworld.logging_setup import get_logger
from gaworld.personality import personality_line

_LOG = get_logger("gaworld.events.appraisal_llm")

#: 模型给出的预估严重度相对规则值的允许区间。
PERCEPTION_BAND = (0.5, 1.8)

#: 情绪增量的绝对上限。一次事件不该把情绪从 0.9 打到 0.0。
MAX_EMOTION_DELTA = 0.30

_VALID_ACTION_KINDS = ("activity_replace", "activity_add", "contact", "seek_info")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _extract_json(text: str) -> dict[str, Any]:
    """The first complete JSON object in ``text``.

    Brace-counting rather than a regex: the response nests objects three deep
    and a non-greedy ``\\{.*?\\}`` would stop at the first inner brace and hand
    back a fragment that parses as nothing.
    """
    if not text:
        return {}
    blob = ""
    fence = text.find("```")
    if fence >= 0:
        end = text.find("```", fence + 3)
        if end > fence:
            blob = text[fence + 3 : end]
    if not blob:
        start = text.find("{")
        if start < 0:
            return {}
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start : index + 1]
                    break
    if not blob:
        return {}
    blob = blob.strip()
    if blob.startswith("json"):
        blob = blob[4:].strip()
    try:
        parsed = json.loads(blob)
    except (ValueError, TypeError):
        from gaworld.sim._schedule import repair_inner_quotes

        try:
            parsed = json.loads(repair_inner_quotes(blob))
        except (ValueError, TypeError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _agent_digest(agent: Any) -> str:
    """A compact description of who this resident is."""
    if not isinstance(agent, dict):
        return ""
    state = agent.get("state") if isinstance(agent.get("state"), dict) else {}
    lines = [
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "action"),
        f"当前状态：压力 {state.get('stress', 0.5):.2f}、情绪 {state.get('emotion', 0.5):.2f}、"
        f"经济安全感 {state.get('econ_security', 0.5):.2f}、时间压力 {state.get('time_pressure', 0.25):.2f}",
    ]
    family = agent.get("family")
    if family:
        lines.append(f"家庭：{family}")
    return "\n".join(lines)


def _objective_digest(impacts: list[Any]) -> str:
    if not impacts:
        return "（系统判断这件事不会明显改变你的日常）"
    chunks = []
    for imp in impacts:
        note = getattr(imp, "note", "") or ""
        domain = getattr(imp, "domain", "")
        chunks.append(f"- {domain}：{note}")
    return "\n".join(chunks)


def _event_digest(event: dict[str, Any]) -> str:
    return (
        f"标题：{event.get('title', event.get('name', '事件'))}\n"
        f"经过：{event.get('description', '')}\n"
        f"严重度：{_to_float(event.get('severity', 0.5), 0.5):.2f}"
    )


def build_prompt(
    agent: Any,
    event: dict[str, Any],
    rule: dict[str, Any],
    impacts: list[Any],
) -> str:
    """The appraisal prompt: who you are, what happened, what it might touch."""
    concerns = rule.get("concerns") or {}
    concern_text = (
        "、".join(f"{k}（{v:.2f}）" for k, v in sorted(concerns.items(), key=lambda kv: -kv[1]))
        or "无特别偏向"
    )
    return f"""
你是{agent.get("name", "居民")}。下面是一件刚刚发生在你身上的事。

{_agent_digest(agent)}

【事件】
{_event_digest(event)}

【这件事客观上会波及的地方】
{_objective_digest(impacts)}

【你原本的判断】
你估计这件事的严重程度是 {_to_float(rule.get("perceived_severity"), 0.5):.2f} 左右，最在意的是：{concern_text}。
请结合你自己的性格、处境和经历，重新掂量一次。

要求：
1) 先用第一人称写一段 1-3 句的**思考**：这件事到底怎么落到你头上，你脑子里在转什么。
2) 给出你的**预估**：perceived_severity 用 0-1 的小数；primary_concern 填最主要受影响的领域
   （economic/family/schedule/environment 之一）；concerns 列出受影响的领域数组；
   duration_days 是这件事会持续多少天；expected_consequences 写 2-3 条你预想的后果。
3) 给出你的**情绪反应**：delta_emotion 与 delta_stress 用 -0.3 到 0.3 的小数（正数是变好/压力上升），
   tone 用一句话描述你此刻的情绪基调。
4) 给出你的**行动计划**（actions 数组，1-3 条），每条形如：
   {{"kind": "activity_replace", "target": "上午的班", "replacement": "去医院"}}
   或 {{"kind": "activity_add", "activity": "联系中介", "time": "15:00", "minutes": 60}}
   或 {{"kind": "contact", "target": "伴侣", "note": "想跟对方说一声"}}
   kind 只能是 activity_replace / activity_add / contact / seek_info。
   另可给出 seek_help_from（你想找谁帮忙，姓名或关系）和 info_needed（你还需要了解什么）。
5) 只输出 JSON 对象，不要输出其他文字。结构：
{{"thought": "...", "appraisal": {{"perceived_severity": 0.0, "primary_concern": "...",
 "concerns": ["..."], "duration_days": 1, "expected_consequences": ["..."]}},
 "emotion": {{"delta_emotion": 0.0, "delta_stress": 0.0, "tone": "..."}},
 "plan": {{"actions": [], "seek_help_from": [], "info_needed": []}}}}
"""


def parse_appraisal(text: str) -> dict[str, Any]:
    """The model's answer, normalized."""
    raw = _extract_json(text or "")
    if not raw:
        return {}
    out: dict[str, Any] = {}

    thought = str(raw.get("thought", "") or "").strip()
    if thought:
        out["thought"] = thought[:600]

    appraisal = raw.get("appraisal")
    appraisal = appraisal if isinstance(appraisal, dict) else {}
    if "perceived_severity" in appraisal:
        out["perceived_severity"] = _clip(_to_float(appraisal.get("perceived_severity"), 0.5), 0.0, 1.0)
    primary = str(appraisal.get("primary_concern", "") or "").strip().lower()
    if primary:
        out["primary_concern"] = primary
    concerns = appraisal.get("concerns")
    if isinstance(concerns, list):
        out["concerns"] = [str(c).strip().lower() for c in concerns if str(c).strip()][:6]
    duration = appraisal.get("duration_days")
    if duration is not None:
        out["duration_days"] = max(1, int(_to_float(duration, 1)))
    consequences = appraisal.get("expected_consequences")
    if isinstance(consequences, list):
        out["expected_consequences"] = [str(c).strip() for c in consequences if str(c).strip()][:5]

    emotion = raw.get("emotion")
    emotion = emotion if isinstance(emotion, dict) else {}
    deltas: dict[str, float] = {}
    for key in ("delta_emotion", "delta_stress"):
        if key in emotion:
            deltas[key] = _clip(_to_float(emotion.get(key), 0.0), -MAX_EMOTION_DELTA, MAX_EMOTION_DELTA)
    tone = str(emotion.get("tone", "") or "").strip()
    if tone:
        deltas["tone"] = tone[:120]
    if deltas:
        out["emotion"] = deltas

    plan = raw.get("plan")
    plan = plan if isinstance(plan, dict) else {}
    actions: list[dict[str, Any]] = []
    for item in plan.get("actions") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "") or "").strip().lower()
        if kind not in _VALID_ACTION_KINDS:
            continue
        action = {"kind": kind}
        for key in ("target", "replacement", "activity", "time", "note"):
            value = str(item.get(key, "") or "").strip()
            if value:
                action[key] = value[:80]
        minutes = item.get("minutes")
        if minutes is not None:
            action["minutes"] = max(5, min(480, round(_to_float(minutes, 30))))
        if action.get("kind") == "activity_replace" and not action.get("replacement"):
            continue
        if action.get("kind") == "activity_add" and not action.get("activity"):
            continue
        actions.append(action)
    if actions:
        out["actions"] = actions[:3]
    for key in ("seek_help_from", "info_needed"):
        value = plan.get(key)
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()][:5]
            if items:
                out[key] = items

    return out


def merge_with_rule(rule: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    """The model may sharpen the rule reading, but not overturn it.

    The rule value is a floor-and-ceiling band: ``perceived_severity`` from the
    model is clamped to ``[rule * 0.5, rule * 1.8]``. Concerns merge (the
    model's list reinforces the rule's weights rather than replacing them).
    """
    merged = dict(rule)
    merged["source"] = "rules+model" if llm else "rules"
    if not llm:
        return merged

    if "thought" in llm:
        merged["thought"] = llm["thought"]
    if "expected_consequences" in llm:
        merged["expected_consequences"] = llm["expected_consequences"]
    if "emotion" in llm:
        merged["emotion"] = llm["emotion"]
    for key in ("actions", "seek_help_from", "info_needed"):
        if key in llm:
            merged[key] = llm[key]

    base = _to_float(rule.get("perceived_severity_raw", rule.get("perceived_severity")), 0.5)
    if "perceived_severity" in llm:
        low = base * PERCEPTION_BAND[0]
        high = base * PERCEPTION_BAND[1]
        model_value = _to_float(llm["perceived_severity"], base)
        # The band is computed against the *unclipped* rule reading: at a high
        # objective severity a clipped base would leave the model no room.
        merged["perceived_severity_raw"] = round(_clip(model_value, low, high), 4)
        merged["perceived_severity"] = round(_clip(model_value, 0.0, 1.0), 4)
        merged["perceived_severity_model"] = round(model_value, 4)

    concerns = dict(rule.get("concerns") or {})
    for domain in llm.get("concerns") or []:
        if domain in concerns:
            # The model may add weight to a domain, never take it away: it
            # sees the resident's situation more closely, but it does not get
            # to decide the household's exposure.
            concerns[domain] = round(min(2.5, concerns[domain] * 1.25), 4)
        else:
            concerns[domain] = 0.75
    if concerns:
        merged["concerns"] = concerns
        merged["primary_concern"] = max(concerns, key=concerns.get)

    if llm.get("primary_concern") in concerns:
        merged["primary_concern"] = llm["primary_concern"]

    if "duration_days" in llm:
        rule_days = int(_to_float(rule.get("duration_days"), 1))
        merged["duration_days"] = max(1, round((rule_days + llm["duration_days"]) / 2))

    return merged


def llm_appraisal(
    agent: Any,
    event: dict[str, Any],
    rule: dict[str, Any],
    impacts: list[Any],
    *,
    config: Any = None,
) -> dict[str, Any]:
    """One model call for the appraisal; ``{}`` when it does not happen.

    Never raises: a failed call must not take the event down. The caller
    falls back to the rule reading, which is always there.
    """
    if not isinstance(agent, dict) or not isinstance(event, dict):
        return {}
    try:
        prompt = build_prompt(agent, event, rule, impacts)
        response = _llm_providers.call_llm(prompt, task="event_appraisal", agent_id=agent.get("id"))
    except Exception as exc:  # the sim must not block on this path
        _LOG.warning("event appraisal call failed for agent %s: %s", agent.get("id"), exc)
        return {}
    parsed = parse_appraisal(response)
    if not parsed:
        _LOG.warning("event appraisal produced no usable JSON for agent %s", agent.get("id"))
        return {}
    return parsed


__all__ = [
    "MAX_EMOTION_DELTA",
    "PERCEPTION_BAND",
    "build_prompt",
    "llm_appraisal",
    "merge_with_rule",
    "parse_appraisal",
]
