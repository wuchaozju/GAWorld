"""地区档案 —— 一座城市「长什么样、当地人怎么过日子」。

已经有三层调研，各自回答一件事：

======================  =================================================
``geocode``            这是哪里（经纬度、行政链、规模）
``knowledge``          这座城做什么（产业、发展重点、紧缺岗位）
``locale``             这里的人叫什么（姓氏、居住形态、户籍层级）
======================  =================================================

缺的是第四层：**这个地方本身**。地形、水系、气候的细节、灾害、方言、
饮食、出行方式、节庆物产、公共服务。少了它，城市只能停在「纬度带 +
规模」这种粗粒度上——杭州和临安都会被写成"亚热带、梅雨持续、空气潮湿"，
而临安真正的样子是山地丘陵、苕溪穿城、梅雨集中期211毫米、酸雨率百分之百、
三月到六月连着下。这些差别只有在居民的日常和环境的天气里才看得出来。

这一层落到三处：

* **环境**（:mod:`gaworld.city.environment`）：天气事件、事件生成的上下文。
* **城市背景**（:mod:`gaworld.city.config`）：每个居民每一步思考都会看到的那句话。
* **居民**（:mod:`gaworld.city.agents`）：人口结构建议、当地生计，
  以及每个居民档案里那句「他平时到底怎么过日子」。

调研是有界的：六次搜索 + 一次模型调用。拿不到就退回原来的粗粒度行为，
绝不阻塞建城——这和 :mod:`gaworld.city.knowledge`、:mod:`gaworld.city.locale`
是同一条纪律：**没有证据的字段宁可不写，也不编一个看起来合理的**。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gaworld.city.geocode import Place
from gaworld.city.knowledge import _parse_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.region")

SCHEMA_VERSION = "1.0"

#: Demography knobs a region may suggest — the same marginals the sampler can
#: actually hit. Anything else the model invents is dropped.
REGION_DEMOGRAPHY_KEYS = ("median_age", "share_under_18", "share_over_65", "migrant_share")
REGION_WORK_KEYS = ("tertiary_rate", "employment_rate")
REGION_INCOME_KEYS = ("median_monthly", "gini")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegionProfile:
    """一个地方的样子。字段全部是可空的字符串/列表：缺就是缺。"""

    code: str = ""
    label: str = ""
    summary: str = ""
    #: 地形与海拔 —— 「西北高东南低，境内多山丘」
    terrain: str = ""
    #: 主要水系 —— 「苕溪自西向东穿城而过」
    water: str = ""
    #: 气候总述，含年均温与降水
    climate: str = ""
    #: 本地真实存在的灾害与极端天气，写成**可以当天播报的事件**
    hazards: tuple[str, ...] = ()
    #: 季节节律，同样写成可播报的现象
    seasons: tuple[str, ...] = ()
    #: 地方文化、民风
    culture: tuple[str, ...] = ()
    #: 本地方言名
    dialect: str = ""
    #: 饮食与物产
    diet: tuple[str, ...] = ()
    #: 当地人怎么出门
    commuting: tuple[str, ...] = ()
    #: 本地节庆，写成可播报的事件
    festivals: tuple[str, ...] = ()
    #: 地标与去处
    landmarks: tuple[str, ...] = ()
    #: 医疗、教育等公共服务
    services: tuple[str, ...] = ()
    #: 当地人主要靠什么谋生
    livelihood: str = ""
    #: 居民日常习惯的短句，直接进人物档案
    habits: tuple[str, ...] = ()
    #: 上工的人才有的习惯（通勤、干活），学生和退休的人不适用
    work_habits: tuple[str, ...] = ()
    #: 人口结构建议（demography / education_work / income 三段）
    suggested_overrides: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, str]] = field(default_factory=list)
    source: str = "stub"  # web | imagined | stub
    built_at: str = ""

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "code": self.code,
            "label": self.label,
            "summary": self.summary,
            "terrain": self.terrain,
            "water": self.water,
            "climate": self.climate,
            "hazards": list(self.hazards),
            "seasons": list(self.seasons),
            "culture": list(self.culture),
            "dialect": self.dialect,
            "diet": list(self.diet),
            "commuting": list(self.commuting),
            "festivals": list(self.festivals),
            "landmarks": list(self.landmarks),
            "services": list(self.services),
            "livelihood": self.livelihood,
            "habits": list(self.habits),
            "work_habits": list(self.work_habits),
            "suggested_overrides": dict(self.suggested_overrides),
            "sources": list(self.sources),
            "source": self.source,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RegionProfile:
        raw = dict(data or {})
        return normalize_region(raw)

    # -- read-outs ---------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.summary,
                self.terrain,
                self.climate,
                self.hazards,
                self.seasons,
                self.culture,
                self.habits,
                self.livelihood,
            )
        )

    def natural_events(self, *, limit: int = 5) -> list[str]:
        """Weather events for the environment layer.

        Only the region's own hazards and seasonal phenomena qualify. The
        latitude-band fallback in :mod:`gaworld.city.environment` is *wrong*
        for most places once we know better — "台风外围环流" belongs to a
        coastal city, not to a mountain town 300km inland — so a region with
        real evidence replaces the band list entirely rather than padding it.
        """
        events = list(self.hazards) + list(self.seasons)
        return events[:limit]

    def social_events(self, *, limit: int = 5) -> list[str]:
        """Social events for the environment layer.

        Festivals only.  ``culture`` holds traits ("宗族观念强"), and a trait
        broadcast as a daily event would read as nonsense — the event pool is
        sampled from, so every entry has to be something that *happens*.
        """
        return list(self.festivals)[:limit]

    def background(self) -> str:
        """The paragraph every resident sees in every cognition prompt."""
        parts: list[str] = []
        if self.label:
            parts.append(self.label)
        if self.terrain:
            parts.append(self.terrain)
        if self.water:
            parts.append(self.water)
        if self.climate:
            parts.append(self.climate)
        if self.livelihood:
            parts.append(f"当地人主要靠{self.livelihood}谋生")
        if self.culture:
            parts.append("当地" + "、".join(self.culture[:2]))
        if self.dialect:
            parts.append(f"方言为{self.dialect}")
        if self.diet:
            parts.append("日常饮食以" + "、".join(self.diet[:3]) + "为主")
        if self.commuting:
            parts.append("出行多靠" + "、".join(self.commuting[:2]))
        return "；".join(part.rstrip("。") for part in parts if part) + "。" if parts else ""

    def prompt_block(self, *, max_chars: int = 360) -> str:
        """A compact briefing that rides along on every cognition call.

        Kept short for the same reason as :meth:`gaworld.city.knowledge.CityProfile.prompt_block`:
        it is paid for per agent per step, not once.
        """
        if self.is_empty:
            return ""
        bits: list[str] = []
        if self.summary:
            bits.append(self.summary)
        if self.terrain:
            bits.append(self.terrain)
        if self.water:
            bits.append(self.water)
        if self.climate:
            bits.append(self.climate)
        if self.livelihood:
            bits.append(f"本地生计：{self.livelihood}")
        if self.culture:
            bits.append("民风：" + "、".join(self.culture[:2]))
        if self.dialect:
            bits.append(f"方言{self.dialect}")
        if self.diet:
            bits.append("饮食：" + "、".join(self.diet[:2]))
        if self.commuting:
            bits.append("出行：" + "、".join(self.commuting[:2]))
        text = "；".join(bits)
        return text[:max_chars]

    def traits(self) -> dict[str, Any]:
        """The slice of this region that belongs in a resident's profile.

        Plain data on purpose: :mod:`gaworld.population.writer` must not
        depend on the city layer, and a dict is the cheapest way to keep that
        direction clean.
        """
        return {
            "place": self.label,
            "habits": list(self.habits),
            "work_habits": list(self.work_habits),
            "diet": list(self.diet),
            "commuting": list(self.commuting),
            "culture": list(self.culture),
            "dialect": self.dialect,
            "livelihood": self.livelihood,
        }

    def rag_chunks(self, *, max_chunks: int = 4) -> list[str]:
        """Short local facts to seed each resident's external-info memory."""
        chunks: list[str] = []
        where = self.label or self.code
        if self.summary:
            chunks.append(f"[本地概况] {where}：{self.summary}")
        if self.terrain or self.water:
            detail = "，".join(part for part in (self.terrain, self.water) if part)
            chunks.append(f"[本地地理] {where}{detail}。")
        if self.climate:
            chunks.append(f"[本地气候] {where}{self.climate}。")
        if self.hazards:
            chunks.append(f"[本地灾害] {where}常有的天气风险：" + "、".join(self.hazards[:3]) + "。")
        if self.livelihood:
            chunks.append(f"[本地生计] {where}的居民主要靠{self.livelihood}谋生。")
        if self.dialect:
            chunks.append(f"[本地风俗] {where}的方言是{self.dialect}。")
        return chunks[:max_chunks]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _text(value: Any, *, limit: int = 200) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:limit]


def _lines(value: Any, *, limit: int = 8, max_len: int = 60) -> tuple[str, ...]:
    """Coerce loose model output into a clean, de-duplicated pool of short lines."""
    if isinstance(value, str):
        items: list[Any] = list(value.replace("；", ";").split(";"))
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item, limit=max_len)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


def _overrides(raw: Any) -> dict[str, Any]:
    """Keep only the spec knobs a region is allowed to suggest.

    Values are left unclamped on purpose: :func:`gaworld.population.schema.normalize_spec`
    clamps them and ``check_feasibility`` reports impossible combinations, so a
    model that claims a median age of 200 costs the user a finding rather than
    a crash.
    """
    if not isinstance(raw, dict):
        return {}
    sections = (
        ("demography", REGION_DEMOGRAPHY_KEYS),
        ("education_work", REGION_WORK_KEYS),
        ("income", REGION_INCOME_KEYS),
    )
    out: dict[str, Any] = {}
    for section, keys in sections:
        source = raw.get(section)
        if not isinstance(source, dict):
            continue
        kept: dict[str, float] = {}
        for key in keys:
            try:
                kept[key] = float(source[key])
            except (KeyError, TypeError, ValueError):
                continue
        if kept:
            out[section] = kept
    return out


def normalize_region(raw: dict[str, Any] | None) -> RegionProfile:
    """Build a usable :class:`RegionProfile` out of loose input."""
    data = dict(raw or {})
    return RegionProfile(
        code=_text(data.get("code"), limit=48),
        label=_text(data.get("label"), limit=60),
        summary=_text(data.get("summary"), limit=160),
        terrain=_text(data.get("terrain"), limit=120),
        water=_text(data.get("water"), limit=120),
        climate=_text(data.get("climate"), limit=160),
        hazards=_lines(data.get("hazards")),
        seasons=_lines(data.get("seasons")),
        culture=_lines(data.get("culture")),
        dialect=_text(data.get("dialect"), limit=40),
        diet=_lines(data.get("diet")),
        commuting=_lines(data.get("commuting")),
        festivals=_lines(data.get("festivals")),
        landmarks=_lines(data.get("landmarks")),
        services=_lines(data.get("services")),
        livelihood=_text(data.get("livelihood"), limit=120),
        habits=_lines(data.get("habits"), limit=6, max_len=40),
        work_habits=_lines(data.get("work_habits"), limit=6, max_len=40),
        suggested_overrides=_overrides(data.get("suggested_overrides")),
        sources=[s for s in (data.get("sources") or []) if isinstance(s, dict)],
        source=_text(data.get("source") or "stub", limit=16),
        built_at=_text(data.get("built_at"), limit=40),
    )


# ---------------------------------------------------------------------------
# Research: web search + LLM
# ---------------------------------------------------------------------------

#: One query per facet. Six is the ceiling — each is a live search and city
#: creation is already an interactive operation.
SEARCH_FACETS: tuple[tuple[str, str], ...] = (
    ("terrain", "{name} 地形 地势 山川 水系 海拔"),
    ("climate", "{name} 气候 年平均气温 年降水量 雨季 无霜期"),
    ("hazard", "{name} 气象灾害 梅雨 台风 寒潮 暴雨 酸雨 高温"),
    ("culture", "{name} 民俗 地方文化 传统 方言 节庆"),
    ("life", "{name} 饮食 特产 物产 交通 高铁 地铁 公交"),
    ("people", "{name} 人口结构 常住人口 户籍 外出务工 老人 学生 就业"),
)


def search_queries(name: str) -> list[str]:
    """The facet queries for *name*, in order."""
    return [template.format(name=name) for _, template in SEARCH_FACETS]


#: Output budget. The dossier is a few dozen short strings; the providers'
#: 512-token default would cut it off mid-object.
REGION_MAX_TOKENS = 4000

_PROMPT = """你是一位熟悉当地的地理与民俗研究者。下面是关于一个地点的检索结果，请据此整理出这个地区的「底色档案」，只输出一个 JSON 对象。

地点：{name}
所在地：{where}
规模：{scale}

检索结果：
{snippets}

要求：
- **只用检索结果里出现的信息**，不要凭常识补充；检索结果没提到的字段就留空字符串或空数组。
- 数字（气温、降水、人口比例）必须来自检索结果；没有依据就不要写进 suggested_overrides。
- hazards 写本地真实存在的灾害与极端天气，写成**可以当天播报的短句**（例："梅雨集中，山区局部山洪风险上升"），因为它们会被直接当作天气事件播报；不要写"注意防灾"这类祈使句。
- seasons 写季节节律，同样写成可播报的现象（例："3—6月梅雨集中，雨水不断"）。
- festivals 写本地节庆，写成可播报的事件（例："端午龙舟赛，江边聚集大量观赛人群"）。
- culture 写地方文化与民风（是**特征**，不是事件，不要写成当天发生的事）；diet 写本地饮食与物产；commuting 写当地人怎么出门；services 写医疗教育等公共服务。
- habits 写当地居民**真的会做的日常小事**，3~5 条，每条不超过 30 字，要能直接塞进人物档案（例："晚饭吃笋干面"）。**谁都能做的事**（吃、买、走亲戚、串门）。
- work_habits 写**上工的人**才有的习惯，2~4 条，每条不超过 30 字（例："骑电动车上下班""清晨进山采竹"）。学生和退休的人不适用。
- label 填"省·市·区"这种行政地名；code 填一个地区代码。

只输出 JSON，不要解释：
{{
  "code": "地区代码",
  "label": "省·市·区",
  "summary": "一句话概括这个地方（40 字以内）",
  "terrain": "地形与海拔一句话",
  "water": "主要水系一句话",
  "climate": "气候一句话，含年均温与降水",
  "hazards": ["可播报的灾害事件", "……"],
  "seasons": ["可播报的季节现象", "……"],
  "culture": ["地方文化与民风", "……"],
  "dialect": "方言名",
  "diet": ["本地饮食与物产", "……"],
  "commuting": ["当地人怎么出门", "……"],
  "festivals": ["可播报的节庆事件", "……"],
  "landmarks": ["地标与去处", "……"],
  "services": ["医疗教育等公共服务", "……"],
  "livelihood": "当地人主要靠什么谋生",
  "habits": ["谁都能做的日常小事", "……"],
  "work_habits": ["上工的人才有的习惯", "……"],
  "suggested_overrides": {{
    "demography": {{"median_age": 0.0, "share_under_18": 0.0, "share_over_65": 0.0, "migrant_share": 0.0}},
    "education_work": {{"tertiary_rate": 0.0, "employment_rate": 0.0}},
    "income": {{"median_monthly": 0.0, "gini": 0.0}}
  }}
}}

说明：suggested_overrides 里没有依据的字段**整个删掉**，不要填 0。
"""


def default_region_search(query: str) -> list[dict[str, str]]:
    """Web search for the region layer, reusing the simulator's own engines."""
    from gaworld.settings import CONFIG
    from gaworld.sim._news import web_search

    _engine, results = web_search(query, config=(CONFIG.get("news", {}) or {}))
    return results


def default_region_llm(prompt: str) -> str:
    """The model call behind region research. Shares the knowledge task key:
    both are "go look up facts about this place and return JSON"."""
    from gaworld.llm.providers import call_llm

    return call_llm(prompt, task="city_knowledge", max_tokens=REGION_MAX_TOKENS)


def _where(place: Place) -> str:
    """The most specific administrative description available for *place*."""
    parts = [str(place.display_name or place.name or place.query).strip()]
    if place.country and place.country not in parts[0]:
        parts.append(place.country)
    return "，".join(p for p in parts if p)


def _format_snippets(results: list[dict[str, str]], *, max_items: int = 24, max_chars: int = 260) -> str:
    lines: list[str] = []
    for item in results[:max_items]:
        title = str(item.get("title", "")).strip()
        excerpt = str(item.get("excerpt") or item.get("content") or "").strip()
        if not (title or excerpt):
            continue
        lines.append(f"- {title}：{excerpt[:max_chars]}")
    return "\n".join(lines)


def research_region(
    place: Place,
    *,
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    llm_fn: Callable[[str], str] | None = None,
    max_queries: int = 6,
) -> RegionProfile | None:
    """Search the web for *place* and have a model structure what came back.

    Returns ``None`` when the search yielded nothing usable or the model did
    not produce a parseable profile, so the caller falls back to the coarse
    latitude-band behaviour. The model is told not to fill gaps from general
    knowledge: a confident invention about a real place is worse than an
    empty profile, because every downstream channel treats it as fact.
    """
    name = place.name or place.query or ""
    if not name:
        return None
    search = search_fn or default_region_search

    results: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    empty_streak = 0
    for query in search_queries(name)[:max_queries]:
        try:
            hits = search(query) or []
        except Exception as exc:
            _LOG.warning("region search failed for %r: %s", query, exc)
            hits = []
        if not hits:
            # Two queries in a row with nothing back means the search backend
            # is unreachable, not that this place is undocumented. The other
            # four queries would each wait out their own timeout for the same
            # answer, so stop here.
            empty_streak += 1
            if empty_streak >= 2:
                _LOG.info("region search backend unreachable for %s; giving up", name)
                break
            continue
        empty_streak = 0
        for hit in hits:
            results.append(hit)
            url = str(hit.get("url", "")).strip()
            if url and not any(s["url"] == url for s in sources):
                sources.append({"title": str(hit.get("title", "")).strip()[:120], "url": url})

    snippets = _format_snippets(results)
    if not snippets:
        _LOG.info("no usable search results for %s; keeping the coarse region", name)
        return None

    prompt = _PROMPT.format(
        name=name,
        where=_where(place),
        scale=place.scale,
        snippets=snippets,
    )
    try:
        raw = (llm_fn or default_region_llm)(prompt)
    except Exception as exc:
        _LOG.warning("region LLM call failed for %s: %s", name, exc)
        return None

    payload = _parse_json_object(raw)
    if not payload:
        return None

    profile = normalize_region(
        {
            **payload,
            "code": payload.get("code") or f"{place.country or ''}-{name}"[:48],
            "label": payload.get("label") or _where(place),
            "sources": sources[:10],
            "source": "web",
            "built_at": _utcnow(),
        }
    )
    return None if profile.is_empty else profile


def region_from_imagined(
    *,
    label: str,
    summary: str,
    climate_label: str = "",
    livelihood: str = "",
    seasons: list[str] | None = None,
) -> RegionProfile:
    """A light dossier for a city that does not exist.

    An invented place has no web footprint to research, but it still deserves
    a coherent dossier rather than the latitude band's guess: the design pass
    already said what the place is about, so that becomes the dossier.
    """
    return normalize_region(
        {
            "code": "imagined",
            "label": label,
            "summary": summary,
            "climate": climate_label,
            "seasons": seasons or [],
            "livelihood": livelihood,
            "habits": [],
            "work_habits": [],
            "source": "imagined",
            "built_at": _utcnow(),
        }
    )


# ---------------------------------------------------------------------------
# Bundle IO
# ---------------------------------------------------------------------------


def save_region(city: Any, region: RegionProfile) -> None:
    path: Path = city.region_path
    path.write_text(json.dumps(region.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_region(city: Any) -> RegionProfile:
    """The city's cached dossier, or an empty one."""
    path: Path = city.region_path
    if not path.exists():
        return RegionProfile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("unreadable region.json in %s (%s); ignoring it", city.slug, exc)
        return RegionProfile()
    if not isinstance(data, dict):
        return RegionProfile()
    return normalize_region(data)


def build_region(
    city: Any,
    place: Place,
    *,
    offline: bool = False,
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    llm_fn: Callable[[str], str] | None = None,
) -> RegionProfile:
    """Research and cache a dossier for *city*, degrading to an empty one.

    Mirrors :func:`gaworld.city.locale.build_locale`: best effort, never
    raises, and records what actually happened on the bundle so a fallback is
    visible after the fact.
    """
    region: RegionProfile | None = None
    if not offline:
        try:
            region = research_region(place, search_fn=search_fn, llm_fn=llm_fn)
        except Exception as exc:
            _LOG.warning("region research failed for %s: %s", place.name or city.slug, exc)

    if region is None:
        region = RegionProfile()
        city.record("region.empty", reason="offline" if offline else "research_failed")
    else:
        city.record(
            "region.research",
            label=region.label,
            hazards=len(region.hazards),
            habits=len(region.habits),
        )

    save_region(city, region)
    return region


__all__ = [
    "REGION_DEMOGRAPHY_KEYS",
    "REGION_INCOME_KEYS",
    "REGION_MAX_TOKENS",
    "REGION_WORK_KEYS",
    "SEARCH_FACETS",
    "RegionProfile",
    "build_region",
    "default_region_llm",
    "default_region_search",
    "load_region",
    "normalize_region",
    "region_from_imagined",
    "research_region",
    "save_region",
    "search_queries",
]
