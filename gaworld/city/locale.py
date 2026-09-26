"""Research the human texture of a city: what its residents are called.

:mod:`gaworld.city.knowledge` answers "what does this city *do*?" (industries,
labour demand).  This module answers "who *lives* there?" — the surname
distribution, the given-name fashion, how housing is spoken about, and what the
local equivalent of the hukou ladder is.  The result is a
:class:`~gaworld.population.locale.LocaleProfile` cached in the bundle as
``locale.json`` and consumed by ``add_population``.

The question is genuinely per-city rather than per-country.  A national Chinese
surname list is wrong for Guangdong, where 陈/黄/梁/林/罗 dominate far beyond
their national share and a manufacturing city's migrant share runs past 60%;
"American names" is likewise not one distribution.  A single LLM call at
creation time is cheap next to the simulation it seeds, and it generalises to
cities nobody hand-curated a pack for.

Failure is never fatal.  A city whose locale research fails falls back to the
mainland-China default — the pools the sampler always used — and the manifest
records that it did, so an American city full of 王伟s is explainable rather
than mysterious.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from gaworld.city.bundle import CityBundle
from gaworld.city.geocode import Place
from gaworld.city.knowledge import _parse_json_object
from gaworld.logging_setup import get_logger
from gaworld.population.locale import DEFAULT_LOCALE, LocaleProfile, normalize_locale

_LOG = get_logger("gaworld.city.locale")

#: Output budget. The pools run to a few hundred short strings, which the
#: providers' 512-token default truncates mid-array.
LOCALE_MAX_TOKENS = 3000

_PROMPT = """你是一位人口学者。下面是一座真实城市，请描述**这座城市的居民**在命名与居住上的地方特征，只输出一个 JSON 对象。

城市：{name}
所在地：{where}
规模：{scale}{population}

要求：
- 姓氏、名字要反映**这座城市所在地区**的真实分布，不是全国平均。广东要以陈黄梁林罗为主而不是照搬全国百家姓；美国城市要用当地族裔构成对应的姓名。
- given_mode 取 "compose"（姓 + 1~2 个字组成名，中日韩用）或 "whole"（名字是完整的词，其他语言用）。
- 中文名用 compose，given_male / given_female / given_neutral 填**单个汉字**；英文等用 whole，填完整的名。
- residency 是四档户籍/居住身份，顺序固定为 [本地, 同省/同州, 外省/外州, 外国]，**必须用中文词**，按当地行政层级来叫。中国用「本地/省内/外省/外国」，美国用「本市/本州/外州/外国」。
- residence_suffixes 是当地常见的居住形态，**用中文词**描述，比如中国县城是「自住房/老小区/商品房」，美国郊区是「独栋住宅/联排住宅/出租公寓」。
- suggested_overrides 给这座城市的人口结构估计；不确定的字段就省略，不要编造。

只输出 JSON，不要解释：
{{
  "code": "地区代码，如 zh-CN-GD / en-US",
  "label": "一句话地区名，如 广东珠三角",
  "given_mode": "compose|whole",
  "joiner": "姓名之间的连接符，中文填 \\"\\"，英文填 \\" \\"",
  "given_first": false,
  "surnames": ["按当地常见度排序的 40~80 个姓"],
  "given_male": ["男性名用字或名，40 个以上"],
  "given_female": ["女性名用字或名，40 个以上"],
  "given_neutral": ["男女通用的，没有就给空数组"],
  "residence_suffixes": ["6~10 种居住形态"],
  "residency": ["本地", "省内", "外省", "外国"],
  "suggested_overrides": {{
    "demography": {{"median_age": 34.0, "migrant_share": 0.55,
                    "share_under_18": 0.15, "share_over_65": 0.11}},
    "education_work": {{"tertiary_rate": 0.35, "employment_rate": 0.70}},
    "income": {{"median_monthly": 6500.0, "gini": 0.42}}
  }}
}}

说明：income.median_monthly 一律折算成**人民币月收入**，因为经济模块只认一种货币。
"""


def default_locale_llm(prompt: str) -> str:
    """The model call behind locale research. Shares the knowledge task key:
    both are "go look up facts about this place and return JSON"."""
    from gaworld.llm.providers import call_llm

    return call_llm(prompt, task="city_knowledge", max_tokens=LOCALE_MAX_TOKENS)


def _where(place: Place) -> str:
    """The most specific administrative description available for *place*.

    ``display_name`` is Nominatim's full "城区, 市, 省, 国家" chain, which is
    exactly the regional context the prompt needs — a bare country name would
    lose the Guangdong-vs-Heilongjiang distinction the whole module exists for.
    """
    parts = [str(place.display_name or place.name or place.query).strip()]
    if place.country and place.country not in parts[0]:
        parts.append(place.country)
    return "，".join(p for p in parts if p)


def research_locale(
    place: Place,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> LocaleProfile:
    """Ask a model what this city's residents are called. Raises on failure."""
    population = f"，常住人口约 {place.population:,}" if place.population else ""
    prompt = _PROMPT.format(
        name=place.name or place.query,
        where=_where(place),
        scale=place.scale,
        population=population,
    )
    raw = (llm_fn or default_locale_llm)(prompt)
    data = _parse_json_object(raw)
    if not data:
        raise ValueError("locale research returned no JSON object")
    return normalize_locale({**data, "source": "llm"})


# ---------------------------------------------------------------------------
# Bundle IO
# ---------------------------------------------------------------------------


def save_locale(city: CityBundle, locale: LocaleProfile) -> None:
    city.locale_path.write_text(
        json.dumps(locale.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_locale(city: CityBundle) -> LocaleProfile:
    """The city's cached locale, or the mainland-China default."""
    if not city.locale_path.exists():
        return DEFAULT_LOCALE
    try:
        data = json.loads(city.locale_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("unreadable locale.json in %s (%s); using the default", city.slug, exc)
        return DEFAULT_LOCALE
    if not isinstance(data, dict):
        return DEFAULT_LOCALE
    return normalize_locale(data)


def build_locale(
    city: CityBundle,
    place: Place,
    *,
    offline: bool = False,
    llm_fn: Callable[[str], str] | None = None,
) -> LocaleProfile:
    """Research and cache a locale for *city*, degrading to the default.

    Mirrors ``build_knowledge``: best effort, never raises, and records what
    actually happened on the bundle so a fallback is visible after the fact.
    """
    locale: LocaleProfile | None = None
    if not offline:
        try:
            locale = research_locale(place, llm_fn=llm_fn)
        except Exception as exc:  # noqa: BLE001 - locale must never block creation
            _LOG.warning("locale research failed for %s: %s", place.name or city.slug, exc)

    if locale is None:
        locale = DEFAULT_LOCALE
        city.record("locale.default", reason="offline" if offline else "research_failed")
    else:
        city.record("locale.research", code=locale.code, label=locale.label)

    save_locale(city, locale)
    return locale


__all__ = [
    "LOCALE_MAX_TOKENS",
    "build_locale",
    "default_locale_llm",
    "load_locale",
    "research_locale",
    "save_locale",
]
