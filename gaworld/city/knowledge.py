"""What a city *is* — its industries, priorities and labour demand.

The city layer already knows a place's geography (map) and weather (environment).
This module adds the economic and social facts that decide what living there is
actually like: which industries dominate, which are growing, what the local
labour market wants. Agents read it through four channels — prompts, skill
growth, the job market and a city-level RAG store — so "this city is developing
tourism" can end up as "this resident started learning hospitality".

Industries are **free-form strings** ("旅游业", "纺织业"), not the six-way
taxonomy in :mod:`gaworld.economy.finance`. A real city's character lives in
exactly the distinctions that taxonomy collapses — folding 旅游业 into
``service`` alongside 物流 and 零售 would erase the thing we went and looked up.
:func:`industry_mix` does the mapping, once, at the economy boundary.

Sourcing is best-effort and layered, because a city must still be creatable
with no network:

    web search + LLM  ── fails ──▶  OSM map statistics  ── no map ──▶  minimal stub
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.knowledge")

SCHEMA_VERSION = "1.0"

#: Free-form industry name → the closest category in ``JOB_INDUSTRY_MAP``.
#: Only consulted at the economy boundary; the profile itself keeps the real
#: name. Order matters — the first keyword found wins.
INDUSTRY_CATEGORY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tech", ("科技", "软件", "互联网", "信息", "电子", "人工智能", "数字", "芯片", "通信")),
    ("finance", ("金融", "银行", "保险", "证券", "投资", "基金")),
    ("medical", ("医疗", "医药", "生物", "健康", "康养", "卫生")),
    ("education", ("教育", "培训", "学校", "高校", "科研")),
    ("trade", ("贸易", "电商", "批发", "零售", "商贸", "市场", "外贸")),
    # Deliberately last: it is the broadest bucket, so anything matching an
    # earlier, more specific hint should not be swallowed by it.
    ("service", ("旅游", "餐饮", "酒店", "文旅", "服务", "物流", "运输", "家政", "文化", "会展")),
)

#: Fallback category for an industry no hint matches (manufacturing, farming,
#: mining…). ``service`` is the least-wrong of the six for unclassified work.
DEFAULT_CATEGORY = "service"

#: OSM node category → (industry label, weight per node). Used to synthesise a
#: grounded profile when the web is unavailable: the map is real evidence, so a
#: town with 12 factories and no hotels does not get described as a resort.
MAP_CATEGORY_INDUSTRY: dict[str, str] = {
    "industry": "制造业",
    "commerce": "商贸零售",
    "education": "教育",
    "medical": "医疗健康",
    "leisure": "文旅休闲",
    "transit": "交通物流",
    "government": "公共服务",
}

_TRENDS = ("growing", "stable", "declining")


@dataclass
class Industry:
    """One local industry, named as the city itself would name it."""

    name: str
    weight: float = 0.0
    trend: str = "stable"
    note: str = ""

    def category(self) -> str:
        """The ``JOB_INDUSTRY_MAP`` bucket this industry belongs to."""
        for category, keywords in INDUSTRY_CATEGORY_HINTS:
            if any(keyword in self.name for keyword in keywords):
                return category
        return DEFAULT_CATEGORY


@dataclass
class CityProfile:
    """What agents get to know about the city they live in."""

    name: str = ""
    summary: str = ""
    industries: list[Industry] = field(default_factory=list)
    #: Where the place is deliberately heading ("全域旅游", "数字经济先行区").
    priorities: list[str] = field(default_factory=list)
    #: Skills and roles the local labour market is short of.
    labor_demand: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    source: str = "stub"  # web | map | stub
    built_at: str = ""
    schema_version: str = SCHEMA_VERSION

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["industries"] = [asdict(item) for item in self.industries]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CityProfile":
        raw = dict(data or {})
        industries = []
        for item in raw.pop("industries", []) or []:
            if not isinstance(item, dict):
                continue
            industries.append(
                Industry(
                    name=str(item.get("name", "")).strip(),
                    weight=_clamp(item.get("weight"), 0.0, 1.0),
                    trend=str(item.get("trend", "stable")) if item.get("trend") in _TRENDS else "stable",
                    note=str(item.get("note", "")).strip(),
                )
            )
        known = {f for f in cls.__dataclass_fields__ if f != "industries"}
        return cls(industries=[i for i in industries if i.name], **{k: v for k, v in raw.items() if k in known})

    # -- read-outs ---------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return not (self.industries or self.priorities or self.labor_demand or self.summary)

    def top_industries(self, limit: int = 3) -> list[Industry]:
        return sorted(self.industries, key=lambda i: -i.weight)[:limit]

    def growing(self) -> list[Industry]:
        return [i for i in self.industries if i.trend == "growing"]

    def prompt_block(self, *, max_chars: int = 420) -> str:
        """A compact briefing for LLM prompts.

        Kept short on purpose: this rides along on *every* cognition call, so
        the cost is paid per agent per step, not once.
        """
        if self.is_empty:
            return ""
        lines: list[str] = []
        if self.summary:
            lines.append(self.summary)
        tops = self.top_industries()
        if tops:
            arrow = {"growing": "↑", "declining": "↓", "stable": ""}
            lines.append(
                "主要产业：" + "、".join(f"{i.name}{arrow.get(i.trend, '')}" for i in tops)
            )
        if self.priorities:
            lines.append("发展重点：" + "、".join(self.priorities[:3]))
        if self.labor_demand:
            lines.append("本地紧缺：" + "、".join(self.labor_demand[:4]))
        text = "；".join(lines)
        return text[:max_chars]

    def industry_conditions(self, *, span: float = 0.25, trend_bonus: float = 0.12) -> dict[str, float]:
        """Per-category income multipliers for ``economy.macro.industry_conditions``.

        A category the city is heavy in pays better than the same job elsewhere,
        and a growing one better still — which is what turns "this city is
        developing tourism" into an actual reason to work in tourism.

        Values stay inside the ``[0.7, 1.4]`` band: the economy re-shuffles these
        each macro cycle and clips at ``[0.5, 1.5]``, so a starting point near
        the edge would leave no room for the cycle to mean anything.
        """
        mix = self.industry_mix()
        if not mix:
            return {}
        # Trend is a weighted *direction* in [-1, 1], not a weighted sum: size is
        # already carried by `span` below, and multiplying the trend by weight
        # too would double-count it — a big declining industry would come out
        # looking barely worse than a stable one.
        totals: dict[str, float] = {}
        signed: dict[str, float] = {}
        for industry in self.industries:
            if industry.weight <= 0:
                continue
            delta = {"growing": 1.0, "declining": -1.0}.get(industry.trend, 0.0)
            category = industry.category()
            totals[category] = totals.get(category, 0.0) + industry.weight
            signed[category] = signed.get(category, 0.0) + delta * industry.weight

        # Share maps linearly onto [1-span, 1+span], centred at half the local
        # economy. Scaling relative to a 1/6 uniform instead would peg every
        # real city at the cap — only two or three of the six categories are
        # ever present, so their shares are always far above 1/6, and the trend
        # term could then never move anything.
        conditions: dict[str, float] = {}
        for category, share in mix.items():
            direction = signed.get(category, 0.0) / totals[category] if totals.get(category) else 0.0
            value = 1.0 + span * (2.0 * share - 1.0) + trend_bonus * direction
            conditions[category] = round(max(0.7, min(1.4, value)), 3)
        return conditions

    def industry_mix(self) -> dict[str, float]:
        """Normalised weights over the six ``JOB_INDUSTRY_MAP`` categories.

        This is the only place free-form industry names are collapsed into the
        economy's taxonomy. Returns ``{}`` when there is nothing to say, so
        callers can keep their existing defaults rather than being handed a
        uniform distribution that pretends to be information.
        """
        mix: dict[str, float] = {}
        for industry in self.industries:
            if industry.weight <= 0:
                continue
            mix[industry.category()] = mix.get(industry.category(), 0.0) + industry.weight
        total = sum(mix.values())
        if total <= 0:
            return {}
        return {key: round(value / total, 4) for key, value in mix.items()}


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Building: web search + LLM
# ---------------------------------------------------------------------------

#: One query per facet. Three is a deliberate ceiling — each is a live search
#: and city creation is already a 20-60s interactive operation.
def search_queries(name: str) -> list[str]:
    return [f"{name} 主导产业 经济结构", f"{name} 发展规划 重点产业", f"{name} 就业 招聘 岗位需求"]


_BUILD_PROMPT = """你是城市经济画像分析助手。根据下面的搜索结果，总结这座城市的产业与就业状况。

城市：{name}

搜索结果：
{snippets}

要求：
- 只使用搜索结果中出现的信息，**不要凭常识补充或推测**；搜索结果没提到的就不要写。
- 产业名用当地真实说法（如"旅游业""纺织业""跨境电商"），不要归类成宽泛的"服务业"。
- weight 是该产业在本地经济中的相对比重，所有产业加起来约等于 1。
- trend 只能是 growing / stable / declining。

只输出 JSON：
{{
  "summary": "一句话概括这座城市的经济特征（40字以内）",
  "industries": [
    {{"name": "产业名", "weight": 0.0到1.0, "trend": "growing", "note": "一句话说明"}}
  ],
  "priorities": ["发展重点，2-4条"],
  "labor_demand": ["本地紧缺的技能或岗位，2-5条"]
}}"""


def _format_snippets(results: list[dict[str, str]], *, max_items: int = 8, max_chars: int = 300) -> str:
    lines = []
    for item in results[:max_items]:
        title = str(item.get("title", "")).strip()
        excerpt = str(item.get("excerpt") or item.get("content") or "").strip()
        if not (title or excerpt):
            continue
        lines.append(f"- {title}：{excerpt[:max_chars]}")
    return "\n".join(lines)


def _parse_json_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        blob = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", text, re.S)
        blob = match.group(0) if match else ""
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def build_from_web(
    name: str,
    *,
    search_fn: Callable[[str], list[dict[str, str]]],
    llm_fn: Callable[[str], str],
    max_queries: int = 3,
) -> CityProfile | None:
    """Search the web for *name* and have an LLM structure what came back.

    Returns ``None`` when the search yielded nothing usable or the LLM did not
    produce a parseable profile, so the caller falls back to the map. The LLM
    is explicitly told not to fill gaps from general knowledge: a confident
    invention about a real city is worse than an empty profile, because every
    downstream channel would treat it as fact.
    """
    results: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    for query in search_queries(name)[:max_queries]:
        try:
            hits = search_fn(query) or []
        except Exception as exc:  # noqa: BLE001 - a failed search must not stop creation
            _LOG.warning("city knowledge search failed for %r: %s", query, exc)
            continue
        for hit in hits:
            results.append(hit)
            url = str(hit.get("url", "")).strip()
            if url and not any(s["url"] == url for s in sources):
                sources.append({"title": str(hit.get("title", "")).strip()[:120], "url": url})

    snippets = _format_snippets(results)
    if not snippets:
        _LOG.info("no usable search results for %s; falling back to the map", name)
        return None

    try:
        raw = llm_fn(_BUILD_PROMPT.format(name=name, snippets=snippets))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("city knowledge LLM call failed for %s: %s", name, exc)
        return None

    payload = _parse_json_object(raw)
    if not payload:
        return None

    profile = CityProfile.from_dict(
        {
            "name": name,
            "summary": str(payload.get("summary", "")).strip()[:120],
            "industries": payload.get("industries") or [],
            "priorities": [str(p).strip() for p in (payload.get("priorities") or []) if str(p).strip()][:5],
            "labor_demand": [str(d).strip() for d in (payload.get("labor_demand") or []) if str(d).strip()][:6],
            "sources": sources[:8],
            "source": "web",
            "built_at": _utcnow(),
        }
    )
    return None if profile.is_empty else profile


# ---------------------------------------------------------------------------
# Building: OSM map statistics (the grounded fallback)
# ---------------------------------------------------------------------------

#: A map has to show at least this much before it can support any claim about
#: the local economy. OSM node counts measure *tagging density*, not employment:
#: a bundle holding 55 housing blocks and 22 schools would otherwise come out as
#: "100% education", which is a fabrication dressed as evidence — the exact
#: failure mode the web path is instructed to avoid.
MIN_INDUSTRY_CATEGORIES = 2
MIN_INDUSTRY_NODES = 6


def build_from_map(name: str, category_counts: dict[str, int]) -> CityProfile:
    """Derive a thin but *truthful* profile from what the map actually contains.

    No network and no LLM: the node mix is real evidence about the place, so
    this never claims anything the map does not show. Trends are all "stable" —
    a static snapshot cannot know a direction, and guessing one would be the
    same invention we are avoiding.

    When the map is too thin to support a conclusion, returns an **empty**
    profile rather than a confident wrong one. Every downstream channel then
    stays inert and the simulation behaves exactly as it did before.
    """
    counted = {
        MAP_CATEGORY_INDUSTRY[key]: value
        for key, value in (category_counts or {}).items()
        if key in MAP_CATEGORY_INDUSTRY and value > 0
    }
    if len(counted) < MIN_INDUSTRY_CATEGORIES or sum(counted.values()) < MIN_INDUSTRY_NODES:
        _LOG.info(
            "map too thin for an economic profile of %s (%d categories, %d nodes)",
            name, len(counted), sum(counted.values()),
        )
        return CityProfile(name=name, source="stub", built_at=_utcnow())
    total = sum(counted.values())
    industries = [
        Industry(name=label, weight=round(count / total, 4), trend="stable", note="按地图上的场所数量估算")
        for label, count in sorted(counted.items(), key=lambda kv: -kv[1])
    ] if total else []

    return CityProfile(
        name=name,
        summary=f"{name}的产业构成按地图场所分布估算，未接入外部资料。" if industries else "",
        industries=industries[:6],
        sources=[],
        source="map",
        built_at=_utcnow(),
    )


def map_category_counts(geojson: dict[str, Any] | None) -> dict[str, int]:
    """Count real-map point features per category."""
    counts: dict[str, int] = {}
    for feature in (geojson or {}).get("features", []):
        if (feature.get("geometry") or {}).get("type") != "Point":
            continue
        category = str((feature.get("properties") or {}).get("category", "")).strip()
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts


__all__ = [
    "CityProfile",
    "DEFAULT_CATEGORY",
    "INDUSTRY_CATEGORY_HINTS",
    "Industry",
    "build_from_map",
    "build_from_web",
    "map_category_counts",
    "search_queries",
]
