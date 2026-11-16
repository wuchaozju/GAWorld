"""事件影响单（Impact）与客观影响池。

一个事件落地时，除了心理状态增量（``state_effects``），还会产生一组**影响单**：
影响单是这个事件在某个领域造成的具体变化，由拥有该领域的子系统执行
（经济扣账、家庭照料、日程改写、环境状态）。

三层分离（见 ``docs/proposals/2026-11-15-event-impact-cascade.md``）：

* **客观影响池** —— 这件事在物理上会造成什么。本模块只负责这一层：
  人生事件从模板的 ``impacts`` 段读，环境事件从 :mod:`gaworld.events.impact_env`
  的规则表匹配。
* **主体预估** —— 这个居民**怎么看**这件事。在
  :mod:`gaworld.events.appraisal`（规则层）与
  :mod:`gaworld.events.appraisal_llm`（模型层）。
* **实际落地** —— 客观池经主体预估缩放筛选后的结果。在
  :mod:`gaworld.events.cascade`。

本模块不 import 任何领域模块：它只描述"发生了什么"，不负责"怎么改"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 第一版接入的四个领域。刻意与用户的四块诉求一一对应，不多不少：
#: 环境、家庭、经济、日程。
IMPACT_DOMAINS: tuple[str, ...] = ("economy", "family", "schedule", "environment")

#: 每个领域允许的影响类型。未知类型一律丢弃——影响池是声明式的，
#: 写错一个 kind 应当静默失效而不是让整个事件炸掉。
IMPACT_KINDS: dict[str, tuple[str, ...]] = {
    "economy": ("expense", "bonus", "income_change"),
    "family": ("care_load", "member_state"),
    "schedule": ("activity_replace", "activity_add"),
    "environment": ("condition",),
}

#: 影响强度的上限。一条影响最多放大到标准量��� 3 倍——一个严重度 0.9 的事件
#: 也不该让居民一天花掉三个月的车费。
MAX_SCALE = 3.0

#: 低于这个缩放系数的影响不再落地（噪声级）。
MIN_SCALE = 0.05


@dataclass
class Impact:
    """一件事在某个领域造成的具体变化。"""

    domain: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    scale: float = 1.0
    duration_days: int = 1
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "kind": self.kind,
            "params": dict(self.params),
            "scale": round(float(self.scale), 4),
            "duration_days": int(self.duration_days),
            "note": self.note,
        }

    def describe(self) -> str:
        """一句中文说明，给日志与记录用。"""
        return self.note or f"{self.domain}/{self.kind}"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_impact(raw: Any) -> Impact | None:
    """One raw impact spec into an :class:`Impact`, or ``None`` if unusable.

    ``None`` rather than an exception: an impact pool is data, and one bad
    entry in a template must not take the event down with it.
    """
    if not isinstance(raw, dict):
        return None
    domain = str(raw.get("domain", "")).strip().lower()
    kind = str(raw.get("kind", "")).strip().lower()
    if domain not in IMPACT_DOMAINS or kind not in IMPACT_KINDS[domain]:
        return None
    params = raw.get("params")
    if not isinstance(params, dict):
        params = {}
    scale = max(0.0, min(MAX_SCALE, _to_float(raw.get("scale", 1.0), 1.0)))
    duration = max(1, _to_int(raw.get("duration_days", 1), 1))
    return Impact(
        domain=domain,
        kind=kind,
        params=dict(params),
        scale=scale,
        duration_days=duration,
        note=str(raw.get("note", "") or "")[:120],
    )


def normalize_impacts(raw: Any) -> list[Impact]:
    """A raw impact list into normalized impacts (bad entries dropped)."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[Impact] = []
    for item in raw:
        impact = normalize_impact(item)
        if impact is not None:
            out.append(impact)
    return out


def impacts_to_dicts(impacts: Any) -> list[dict[str, Any]]:
    """Impacts as plain dicts, for JSON records."""
    if not impacts:
        return []
    out: list[dict[str, Any]] = []
    for item in impacts:
        if isinstance(item, Impact):
            out.append(item.to_dict())
        elif isinstance(item, dict):
            out.append(dict(item))
    return out


def template_impacts(template_key: str) -> list[Impact]:
    """The objective impact pool of a life-event template."""
    if not template_key:
        return []
    from gaworld.events.life import _TEMPLATES_BY_KEY

    template = _TEMPLATES_BY_KEY.get(str(template_key))
    if not isinstance(template, dict):
        return []
    return normalize_impacts(template.get("impacts"))


def life_event_impacts(event: Any) -> list[Impact]:
    """The objective impact pool of a life event (template + payload)."""
    if not isinstance(event, dict):
        return []
    impacts = template_impacts(str(event.get("template_key", "")))
    extra = normalize_impacts(event.get("impacts"))
    return impacts + extra


def env_event_impacts(event: Any) -> list[Impact]:
    """The objective impact pool of an environment event (rule table)."""
    if not isinstance(event, dict):
        return []
    from gaworld.events.impact_env import match_env_impacts

    return match_env_impacts(event)


def impact_pool_for_event(event: Any) -> list[Impact]:
    """The objective impact pool of any event, dispatching on its kind.

    A life event carries ``template_key`` (and may be rendered as an env
    event with ``life_event: True``); everything else goes through the
    environment rule table.
    """
    if not isinstance(event, dict):
        return []
    if event.get("life_event") or event.get("template_key"):
        impacts = life_event_impacts(event)
        if impacts:
            return impacts
    return env_event_impacts(event)


def objective_severity(event: Any) -> float:
    """The event's own severity, 0..1 (0.5 when unspecified)."""
    if not isinstance(event, dict):
        return 0.5
    raw = event.get("severity")
    if raw is None:
        return 0.5
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5


__all__ = [
    "IMPACT_DOMAINS",
    "IMPACT_KINDS",
    "MAX_SCALE",
    "MIN_SCALE",
    "Impact",
    "env_event_impacts",
    "impact_pool_for_event",
    "impacts_to_dicts",
    "life_event_impacts",
    "normalize_impact",
    "normalize_impacts",
    "objective_severity",
    "template_impacts",
]
