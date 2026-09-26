"""The cultural layer of a synthetic population: names, housing, residency.

:mod:`gaworld.population.schema` describes a population *statistically* —
median age, migrant share, industry mix.  Those knobs are culture-free: a
median age of 39 means the same thing in Dongguan and in Ohio.  Everything a
resident is actually *called*, however, is not: the sampler used to hard-code a
national Chinese surname list, PRC hukou tiers and 商品房/老小区 housing forms,
so a city built from ``us_suburb`` came out statistically American and
culturally Chinese ("王伟，本地户籍，住 西古山·商品房").

A :class:`LocaleProfile` is that second layer, split out so it can vary per
city.  :mod:`gaworld.city.locale` researches one per city with an LLM and
caches it in the bundle; this module only holds the shape, the validation and
the mainland-China default that everything falls back to.

Two deliberate limits, both following from "names localise, profiles stay
Chinese":

* Job titles are **not** here.  ``JOB_TITLES`` in :mod:`~gaworld.population.synth`
  is a keyword contract with ``gaworld/economy/finance.py``, which infers an
  agent's industry and income band by substring-matching Chinese words.
  Localising job text would silently break industry inference.
* ``residency`` labels stay Chinese words even for a foreign locale (a US city
  gets 本市/本州/外州/外国 rather than the hukou ladder), because
  ``gaworld.sim.agents_loader.parse_profile`` reads the ``…户籍，`` clause and
  the profile prose around it is Chinese either way.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

#: Name-assembly modes.  ``compose`` builds a given name out of 1–2 characters
#: drawn from a character pool (CJK); ``whole`` picks one ready-made given name
#: from the pool (most other scripts).
NAME_MODES = ("compose", "whole")

#: Demography knobs a locale may suggest.  Restricted to the marginals the
#: sampler can actually hit; anything else the model invents is dropped.
#: Values are *suggestions* — see ``suggested_overrides``.
LOCALE_DEMOGRAPHY_KEYS = (
    "median_age",
    "share_under_18",
    "share_over_65",
    "migrant_share",
)

#: Same, for the education/work and income sections.
LOCALE_WORK_KEYS = ("tertiary_rate", "employment_rate")
LOCALE_INCOME_KEYS = ("median_monthly", "gini")


@dataclass(frozen=True)
class LocaleProfile:
    """Everything about a population that depends on *where* the city is."""

    code: str = "zh-CN"
    label: str = "中国内地"
    given_mode: str = "compose"
    #: Placed between surname and given name; "" for CJK, " " for western names.
    joiner: str = ""
    #: True when the given name comes first ("Michael Chen").
    given_first: bool = False
    surnames: tuple[str, ...] = ()
    given_male: tuple[str, ...] = ()
    given_female: tuple[str, ...] = ()
    #: Drawn from for either gender, on top of the gendered pool.
    given_neutral: tuple[str, ...] = ()
    #: Housing forms, used as the second half of "区名·形态".
    residence_suffixes: tuple[str, ...] = ()
    #: Residency tiers in the order local / same-region / other-region / foreign.
    #: Position 0 is load-bearing: the sampler treats it as "not a migrant".
    residency: tuple[str, str, str, str] = ("本地", "省内", "外省", "外国")
    #: Population marginals this locale suggests, as a partial spec fragment
    #: ({"demography": {...}, "income": {...}}).  Applied only when the caller
    #: did not pick a preset of their own — see ``gaworld.city.agents``.
    suggested_overrides: dict[str, Any] = field(default_factory=dict)
    #: Where this profile came from, for the manifest: "builtin" | "llm".
    source: str = "builtin"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Mainland-China default.  This is the pool the sampler used before locales
#: existed, so an un-researched city generates exactly what it always did.
DEFAULT_LOCALE = LocaleProfile(
    code="zh-CN",
    label="中国内地",
    given_mode="compose",
    joiner="",
    given_first=False,
    surnames=tuple(
        "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
        "肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱侯江尹薛闫段雷黎史陶毛贺顾龙万钱严覃武戴莫孔向汤"
    ),
    given_male=tuple(
        "伟强磊军洋勇杰涛明超"
        "峰鹏华健旭辉宇泽宸轩浩然睿钦擎柏迅骏昊霖坤锐晨凯彬帆亮航嘉承"
    ),
    given_female=tuple(
        "芳娜敏静秀丽艳娟霞香月莹雪琳婷玲燕红梅倩颖岚妍晴柔宁菲萱瑶琪韵怡"
        "涵瑾露岑荷薇"
    ),
    given_neutral=tuple("安然嘉一之子川舟野知行同和平新望初文"),
    residence_suffixes=(
        "商品房",
        "合租",
        "老小区",
        "青年公寓",
        "改造社区",
        "居住区",
        "社区",
        "自住房",
    ),
    residency=("本地", "省内", "外省", "外国"),
    source="builtin",
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _string_tuple(value: Any, *, limit: int = 400, max_len: int = 40) -> tuple[str, ...]:
    """Coerce loose model output into a clean, de-duplicated string pool."""
    if isinstance(value, str):
        # A model asked for a character pool sometimes answers with one long
        # string ("王李张…") rather than a list. Both readings are useful, and
        # splitting a CJK run into characters is what the compose mode wants.
        items: list[Any] = list(value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or len(text) > max_len or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


def _overrides(raw: Any) -> dict[str, Any]:
    """Keep only the spec knobs a locale is allowed to suggest.

    Values are left unclamped: ``normalize_spec`` clamps every one of them and
    ``check_feasibility`` reports the combinations that cannot be hit, so a
    model that claims a median age of 200 costs the user a finding rather than
    a crash.
    """
    if not isinstance(raw, Mapping):
        return {}
    sections = (
        ("demography", LOCALE_DEMOGRAPHY_KEYS),
        ("education_work", LOCALE_WORK_KEYS),
        ("income", LOCALE_INCOME_KEYS),
    )
    out: dict[str, Any] = {}
    for section, keys in sections:
        source = raw.get(section)
        if not isinstance(source, Mapping):
            continue
        kept = {}
        for key in keys:
            try:
                kept[key] = float(source[key])
            except (KeyError, TypeError, ValueError):
                continue
        if kept:
            out[section] = kept
    return out


def normalize_locale(raw: Mapping[str, Any] | None) -> LocaleProfile:
    """Build a usable :class:`LocaleProfile` out of loose input.

    Every pool falls back to :data:`DEFAULT_LOCALE` *field by field* rather than
    as a whole: a model that nails the surnames but forgets the housing forms
    should cost the user Chinese housing words in an otherwise American city,
    not an entirely Chinese population.
    """
    raw = dict(raw or {})
    mode = str(raw.get("given_mode") or "").strip().lower()
    if mode not in NAME_MODES:
        mode = DEFAULT_LOCALE.given_mode

    residency = _string_tuple(raw.get("residency"), limit=4)
    if len(residency) != 4:
        residency = DEFAULT_LOCALE.residency

    return LocaleProfile(
        code=str(raw.get("code") or DEFAULT_LOCALE.code).strip()[:32],
        label=str(raw.get("label") or DEFAULT_LOCALE.label).strip()[:40],
        given_mode=mode,
        joiner=str(raw.get("joiner") or "")[:2],
        given_first=bool(raw.get("given_first", False)),
        surnames=_string_tuple(raw.get("surnames")) or DEFAULT_LOCALE.surnames,
        given_male=_string_tuple(raw.get("given_male")) or DEFAULT_LOCALE.given_male,
        given_female=_string_tuple(raw.get("given_female")) or DEFAULT_LOCALE.given_female,
        # Neutral names are genuinely optional — a locale with strictly
        # gendered given names should get an empty pool, not the Chinese one.
        given_neutral=_string_tuple(raw.get("given_neutral")),
        residence_suffixes=(
            _string_tuple(raw.get("residence_suffixes")) or DEFAULT_LOCALE.residence_suffixes
        ),
        residency=residency,  # type: ignore[arg-type]
        suggested_overrides=_overrides(raw.get("suggested_overrides")),
        source=str(raw.get("source") or "llm").strip()[:16],
    )


# ---------------------------------------------------------------------------
# Name assembly
# ---------------------------------------------------------------------------


def compose_name(locale: LocaleProfile, is_male: bool, rng: Any) -> str:
    """Draw one full name.

    ``rng`` is a ``numpy.random.Generator``.  The draw order for the built-in
    compose mode is unchanged from when these pools lived in ``synth`` — one
    surname draw, one length roll, then one draw per character — so an existing
    seed still produces the same town.
    """
    pool = (locale.given_male if is_male else locale.given_female) + locale.given_neutral
    if not pool:
        pool = locale.given_male + locale.given_female + locale.given_neutral
    surnames = locale.surnames or DEFAULT_LOCALE.surnames

    surname = surnames[rng.integers(len(surnames))]
    if locale.given_mode == "whole":
        given = str(pool[rng.integers(len(pool))]) if pool else ""
    else:
        length = 1 if rng.random() < 0.35 else 2
        given = "".join(str(pool[rng.integers(len(pool))]) for _ in range(length))

    first, second = (given, surname) if locale.given_first else (surname, given)
    return f"{first}{locale.joiner}{second}"


__all__ = [
    "DEFAULT_LOCALE",
    "LOCALE_DEMOGRAPHY_KEYS",
    "LOCALE_INCOME_KEYS",
    "LOCALE_WORK_KEYS",
    "NAME_MODES",
    "LocaleProfile",
    "compose_name",
    "normalize_locale",
]
