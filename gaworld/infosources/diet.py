"""Media diet: which sources one resident actually reads, and how much.

People do not sample the whole internet uniformly. A community doctor reads
医疗 sources, a programmer reads Hacker News and arXiv, and almost everyone
glances at whatever is trending. The diet turns that into a weighted list of
source ids per resident, from three things the agent already carries:

* the **job** — a keyword table maps it onto domain tags, which are matched
  against each source's ``topics``;
* the **interest keywords** extracted from the profile — matched against
  source names and topics, through a small alias table (股票 → 投资, …);
* **person-level state**: ``platform_dependence`` scales the social share,
  Big Five openness (``rules`` channel) widens the diet towards sources that
  match nothing and towards the other language.

Deterministic: same agent, same registry → same diet. Randomness lives only in
:func:`pick_item`, which draws one item per info-seek from the diet.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from typing import Any

from gaworld.infosources.feed import FeedCache
from gaworld.infosources.schema import InfoItem, Source
from gaworld.personality.traits import traits_of

PLUGIN_ID = "infosources"

#: ``(job keywords) -> (source topics)``. First match wins for the primary
#: profession; every matching row contributes, so "医学院教师" reads both.
PROFESSION_TOPICS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("医", "护士", "护理", "药", "诊", "健康", "康复", "心理咨询"), ("医疗", "健康", "科学")),
    (
        (
            "程序", "软件", "开发", "算法", "工程师", "数据", "AI", "人工智能", "IT",
            "运维", "架构", "前端", "后端", "测试",
        ),
        ("科技", "互联网", "编程", "人工智能"),
    ),
    (("科研", "研究员", "博士", "学者", "实验室", "高校", "教授"), ("学术", "科学")),
    (("教师", "老师", "教育", "培训", "辅导", "幼儿园", "学生", "班主任"), ("教育", "文化")),
    (
        (
            "金融", "银行", "投资", "证券", "基金", "会计", "财务", "保险", "理财",
            "审计", "信贷", "交易员",
        ),
        ("财经", "经济", "投资"),
    ),
    (("律师", "法务", "法律", "法官", "检察", "仲裁"), ("法律", "政策", "社会")),
    (("公务员", "政府", "街道", "社区", "事业单位", "政务", "机关"), ("政策", "社会", "本地")),
    (
        (
            "设计", "编辑", "记者", "作家", "艺术", "摄影", "文化", "出版", "广告",
            "文案", "主播", "策展", "音乐",
        ),
        ("文化", "设计", "娱乐"),
    ),
    (
        (
            "销售", "市场", "运营", "电商", "创业", "老板", "经理", "产品", "采购",
            "品牌", "公关", "贸易",
        ),
        ("商业", "互联网", "财经"),
    ),
    (("外卖", "快递", "司机", "网约车", "骑手", "物流", "配送", "代驾"), ("本地", "民生", "社会")),
    (("农", "种植", "养殖", "渔", "果园", "茶"), ("农业", "本地", "民生")),
    (("退休", "主妇", "自由职业", "待业", "无业", "家务"), ("民生", "本地", "社会")),
    (("体育", "健身", "教练", "运动", "球"), ("体育", "健康")),
    (
        (
            "厨师", "餐饮", "服务员", "店员", "零售", "导购", "收银", "理发", "美容",
            "保洁", "保安",
        ),
        ("本地", "民生", "商业"),
    ),
    (
        ("建筑", "工地", "装修", "工人", "制造", "车间", "技工", "电工", "维修", "机械"),
        ("民生", "本地", "经济"),
    ),
)

#: Interest keyword → topic aliases, on top of literal topic-name matches.
INTEREST_TOPICS: dict[str, tuple[str, ...]] = {
    "股票": ("投资", "财经"),
    "基金": ("投资", "财经"),
    "理财": ("财经", "投资"),
    "房价": ("财经", "本地"),
    "买房": ("财经", "本地"),
    "ai": ("人工智能", "科技"),
    "人工智能": ("人工智能", "科技"),
    "编程": ("编程", "科技"),
    "代码": ("编程", "科技"),
    "数码": ("数码", "科技"),
    "手机": ("数码", "科技"),
    "科技": ("科技",),
    "健身": ("体育", "健康"),
    "跑步": ("体育", "健康"),
    "养生": ("健康",),
    "育儿": ("教育", "健康"),
    "孩子": ("教育",),
    "读书": ("文化",),
    "电影": ("娱乐", "文化"),
    "游戏": ("娱乐",),
    "追剧": ("娱乐",),
    "音乐": ("文化", "娱乐"),
    "旅游": ("文化", "本地"),
    "美食": ("本地", "民生"),
    "政策": ("政策",),
    "新闻": ("综合", "社会"),
    "国际": ("国际",),
    "创业": ("商业",),
    "行业": ("商业", "科技"),
    "论文": ("学术",),
    "科研": ("学术", "科学"),
    "研究": ("学术", "科学"),
    "research": ("学术", "科学"),
    "trend": ("科技", "商业"),
}

#: Tags that mean "mainstream reach": anyone may bump into these.
GENERAL_TOPICS: frozenset[str] = frozenset({"综合", "热点", "社会", "本地"})

DEFAULT_MAX_SOURCES = 8
DEFAULT_EN_WEIGHT = 0.5


def profession_topics(job: str) -> list[str]:
    """Domain tags for a job title; ``[]`` when nothing in the table matches."""
    text = str(job or "")
    lowered = text.lower()
    out: list[str] = []
    for keywords, topics in PROFESSION_TOPICS:
        if any(k.lower() in lowered if k.isascii() else k in text for k in keywords):
            for topic in topics:
                if topic not in out:
                    out.append(topic)
    return out


def interest_topics(interests: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for raw in interests:
        token = str(raw or "").strip()
        if not token:
            continue
        lowered = token.lower()
        for alias, topics in INTEREST_TOPICS.items():
            if alias in lowered or alias in token:
                out.update(topics)
    return out


def _unit(z: float) -> float:
    """Big Five z score → [0, 1] with 0.5 at the population mean."""
    return max(0.0, min(1.0, (float(z) + 2.5) / 5.0))


def score_source(
    source: Source,
    *,
    job_topics: Iterable[str],
    interests: Iterable[str],
    platform_dependence: float = 0.5,
    openness_z: float = 0.0,
    agent_lang: str = "zh",
    en_weight: float = DEFAULT_EN_WEIGHT,
) -> tuple[float, list[str]]:
    """Affinity of one resident for one source, plus the reasons it scored."""
    topics = set(source.topics)
    reasons: list[str] = []
    score = 0.15  # baseline reach: anyone might stumble on anything
    job_hits = sorted(topics & set(job_topics))
    if job_hits:
        score += 1.0 * len(job_hits)
        reasons.append("职业:" + "/".join(job_hits))
    general_hits = topics & GENERAL_TOPICS
    if general_hits:
        score += 0.35 * min(len(general_hits), 2)
    interest_list = [str(i).strip() for i in interests if str(i).strip()]
    literal_hits = sorted(
        t for t in topics if any(t in i or i in t for i in interest_list if len(i) >= 2)
    )
    alias_hits = sorted((topics & interest_topics(interest_list)) - set(literal_hits))
    name_hit = any(i and i in source.name for i in interest_list if len(i) >= 2)
    interest_hits = literal_hits + alias_hits + (["站名"] if name_hit else [])
    if interest_hits:
        score += 0.5 * min(len(interest_hits), 3)
        reasons.append("兴趣:" + "/".join(interest_hits))
    if source.kind == "social":
        score *= 0.6 + 0.8 * max(0.0, min(1.0, float(platform_dependence)))
    elif source.kind == "professional":
        score *= 0.8 + 0.4 * _unit(openness_z)
        if not job_hits and not interest_hits:
            score *= 0.6  # a trade site nobody at home works in
    if source.lang != agent_lang:
        score *= max(0.1, min(1.0, float(en_weight) * (1.0 + 0.4 * float(openness_z))))
        reasons.append(f"外语:{source.lang}")
    if not job_hits and not interest_hits:
        score += 0.1 * max(0.0, float(openness_z))  # openness widens the diet
    score *= max(0.0, float(source.weight))
    return round(score, 4), reasons


def build_media_diet(
    agent: Mapping[str, Any],
    sources: Iterable[Source],
    *,
    interests: Iterable[str] = (),
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank the registry for one resident and keep the top ``max_sources``.

    Each entry is ``{source_id, name, kind, domain, weight, reason}`` with the
    weights normalised to sum to 1, so the list is both a sampling distribution
    and a human-readable "who reads what" record.
    """
    cfg = dict(config or {})
    max_sources = max(1, int(cfg.get("max_sources", DEFAULT_MAX_SOURCES)))
    en_weight = float(cfg.get("en_weight", DEFAULT_EN_WEIGHT))
    state = agent.get("state", {}) if isinstance(agent.get("state"), Mapping) else {}
    try:
        platform_dependence = float(state.get("platform_dependence", 0.5))
    except (TypeError, ValueError):
        platform_dependence = 0.5
    openness_z = float(traits_of(agent, "rules").get("o", 0.0))
    job_topics = profession_topics(str(agent.get("job", "")))
    interest_list = list(interests)
    ranked: list[tuple[float, str, Source, list[str]]] = []
    for source in sources:
        if not source.enabled:
            continue
        score, reasons = score_source(
            source,
            job_topics=job_topics,
            interests=interest_list,
            platform_dependence=platform_dependence,
            openness_z=openness_z,
            en_weight=en_weight,
        )
        if score <= 0:
            continue
        ranked.append((score, source.id, source, reasons))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = ranked[:max_sources]
    total = sum(row[0] for row in chosen) or 1.0
    return [
        {
            "source_id": source.id,
            "name": source.name,
            "kind": source.kind,
            "domain": source.domain,
            "weight": round(score / total, 4),
            "reason": "；".join(reasons) if reasons else "泛读",
        }
        for score, _sid, source, reasons in chosen
    ]


def diet_of(agent: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The diet the plugin stored for this agent, or ``[]``."""
    ext = agent.get("ext") if isinstance(agent, Mapping) else None
    if not isinstance(ext, Mapping):
        return []
    own = ext.get(PLUGIN_ID)
    diet = own.get("diet") if isinstance(own, Mapping) else None
    return [dict(entry) for entry in diet if isinstance(entry, Mapping)] if isinstance(diet, list) else []


def _keyword_hits(text: str, interests: Iterable[str]) -> list[str]:
    haystack = str(text or "").lower()
    return [i for i in (str(x).strip() for x in interests) if i and i.lower() in haystack][:8]


def pick_item(
    diet: list[dict[str, Any]],
    cache: FeedCache,
    *,
    interests: Iterable[str] = (),
    seen_urls: set[str] | None = None,
    rng: random.Random | Any = random,
) -> tuple[dict[str, Any], InfoItem, float, list[str]] | None:
    """Draw a source by diet weight, then the best unseen item in it.

    Falls through to the next-heaviest source when the drawn one has nothing
    new, so a resident whose favourite feed is down still reads something.
    """
    seen = seen_urls or set()
    interest_list = [str(i).strip() for i in interests if str(i).strip()]
    remaining = [dict(entry) for entry in diet if entry.get("source_id")]
    while remaining:
        total = sum(max(0.0, float(e.get("weight", 0.0))) for e in remaining)
        if total <= 0:
            chosen = remaining[0]
        else:
            draw = rng.random() * total
            chosen = remaining[-1]
            for entry in remaining:
                draw -= max(0.0, float(entry.get("weight", 0.0)))
                if draw <= 0:
                    chosen = entry
                    break
        remaining = [e for e in remaining if e is not chosen]
        items = cache.items_for(str(chosen["source_id"]))
        best: tuple[float, list[str], InfoItem] | None = None
        for index, item in enumerate(items):
            if not item.title or (item.url and item.url in seen):
                continue
            matched = _keyword_hits(f"{item.title} {item.excerpt}", interest_list)
            freshness = 0.3 * (1.0 - index / max(1, len(items)))
            score = len(matched) * 1.0 + freshness + rng.random() * 0.05
            if best is None or score > best[0]:
                best = (score, matched, item)
        if best is not None:
            return chosen, best[2], round(best[0], 4), best[1]
    return None


__all__ = [
    "DEFAULT_EN_WEIGHT",
    "DEFAULT_MAX_SOURCES",
    "GENERAL_TOPICS",
    "INTEREST_TOPICS",
    "PLUGIN_ID",
    "PROFESSION_TOPICS",
    "build_media_diet",
    "diet_of",
    "interest_topics",
    "pick_item",
    "profession_topics",
    "score_source",
]
