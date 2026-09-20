"""Sample individuals from a :class:`~gaworld.population.schema.PopulationSpec`.

The panel only lets a user state *marginal* distributions ("median age 36",
"employment 68%"), but real attributes are correlated. The pipeline here
bridges the two:

1. fit an age-band distribution to the three age knobs (bisection on a tilt
   parameter, so median age is hit rather than merely bounded);
2. IPF a ``age × sex × education × employment × industry`` contingency table
   onto those marginals, with structural zeros for impossible cells
   (employed children, elders in tech, "employed with no industry", …);
3. sample one cell per person and fill in exact age, income, residence and the
   nine state variables conditionally.

Income uses a rank-transform trick: an attribute-driven latent score is
converted to a uniform rank and pushed through the target income quantile
function. That way the requested median/Gini hold *exactly* while income still
correlates with education, industry and age.

Every random draw comes from a named sub-stream (see :func:`derive_rng`), so
adjusting one knob does not reshuffle unrelated attributes.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaworld.population.schema import (
    AGE_BAND_RANGES,
    AGE_BANDS,
    EDUCATION_LEVELS,
    EMPLOYMENT_STATUSES,
    INDUSTRIES,
    NO_INDUSTRY,
    SEXES,
    STATE_VAR_KEYS,
    TERTIARY_LEVELS,
    PopulationSpec,
    piecewise_uniform_median,
)

INDUSTRY_SLOTS: tuple[str, ...] = (*INDUSTRIES, NO_INDUSTRY)

#: Job titles per industry. Wording is a **contract with the economy module**,
#: not decoration: ``_infer_industry`` and ``_job_income_band`` in
#: ``gaworld/economy/finance.py`` do substring matching against
#: ``JOB_INDUSTRY_MAP`` / ``JOB_INCOME_BANDS``, so a title must contain a
#: keyword for its own industry and must *not* contain one belonging to an
#: industry checked earlier in that dict (tech → finance → medical →
#: education → service → trade). "跨境电商运营", for example, looks like trade
#: but matches ``运营`` under service first and would be misclassified.
#: ``tests/test_population.py`` enforces this round-trip.
#:
#: Trade titles fall through ``JOB_INCOME_BANDS`` to its 22-62/hour default,
#: which is the right level for small traders anyway; every band keyword that
#: would match them (销售/店员/运营) is also a *service* industry keyword and
#: would hijack the industry.
JOB_TITLES: dict[str, tuple[str, ...]] = {
    "tech": ("算法工程师", "后端研发工程师", "前端工程师", "产品经理", "交互设计师", "系统架构师"),
    "finance": ("银行金融顾问", "证券分析师", "会计", "保险销售代理", "金融投资顾问", "金融风控专员"),
    "medical": ("社区医生", "护士", "康复科医生", "医院药剂师", "内科医生", "医疗器械销售"),
    "education": ("小学教师", "中学教师", "培训机构教师", "大学教师", "学校教务行政", "课后托管教师"),
    "service": ("餐饮店员", "网约车司机", "物流分拣员", "客服专员", "行政助理", "美发店员", "销售代表"),
    "trade": ("电商店铺经营", "批发商", "零售店经营者", "菜市场摆摊", "跨境电商经营", "五金店经营者"),
}

#: Job text for people without an industry, keyed by why they have no job.
NON_EMPLOYED_JOBS: dict[str, tuple[str, ...]] = {
    "student": ("学生",),
    "unemployed": ("待业中", "失业待业"),
    "retired": ("退休",),
    "homemaker": ("无业，家庭照料为主",),
}

SURNAMES: tuple[str, ...] = tuple(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾"
    "肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱侯江尹薛闫段雷黎史陶毛贺顾龙万钱严覃武戴莫孔向汤"
)
GIVEN_CHARS_M: tuple[str, ...] = tuple(
    "伟强磊军洋勇杰涛明超platform".replace("platform", "")
    + "峰鹏华健旭辉宇泽宸轩浩然睿钦擎柏迅骏昊霖坤锐晨凯彬帆亮航嘉承",
)
GIVEN_CHARS_F: tuple[str, ...] = tuple(
    "芳娜敏静秀丽艳娟霞香月莹雪琳婷玲燕红梅倩颖岚妍晴柔宁菲萱瑶琪韵怡цвет".replace("цвет", "")
    + "涵瑾露岑荷薇",
)
GIVEN_CHARS_NEUTRAL: tuple[str, ...] = tuple("安然嘉一之子川舟野知行同和平新望初文")

RESIDENCE_SUFFIXES: tuple[str, ...] = (
    "商品房",
    "合租",
    "老小区",
    "青年公寓",
    "改造社区",
    "居住区",
    "社区",
    "自住房",
)


# ---------------------------------------------------------------------------
# Seeded sub-streams
# ---------------------------------------------------------------------------


def derive_rng(master_seed: int, stream: str) -> np.random.Generator:
    """Return an independent generator for a named attribute stream.

    Deriving per-stream seeds (rather than drawing everything from one
    generator) means tweaking, say, the network knobs cannot silently
    re-roll everybody's age — the single most confusing thing a population
    panel can do to a user.
    """
    digest = hashlib.sha256(f"{int(master_seed)}::{stream}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


# ---------------------------------------------------------------------------
# Income distribution helpers
# ---------------------------------------------------------------------------


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation).

    Hand-rolled to keep ``scipy`` out of the dependency set; accurate to about
    1e-9 in the relative sense, far beyond what income modelling needs.
    """
    p = min(max(float(p), 1e-12), 1.0 - 1e-12)
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def lognormal_sigma_from_gini(gini: float) -> float:
    """Invert ``gini = 2·Φ(σ/√2) − 1`` for a lognormal distribution."""
    gini = min(max(float(gini), 0.001), 0.95)
    return float(_norm_ppf((gini + 1.0) / 2.0) * math.sqrt(2.0))


def _gini_of(values: np.ndarray) -> float:
    ordered = np.sort(np.asarray(values, dtype=float))
    n = ordered.size
    total = ordered.sum()
    if n == 0 or total <= 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2.0 * (index * ordered).sum()) / (n * total) - (n + 1) / n)


def solve_income_sigma(spec: PopulationSpec, *, grid: int = 2000) -> float:
    """Find the lognormal σ whose *spliced* distribution has the target Gini.

    ``lognormal_sigma_from_gini`` inverts the closed form for a pure lognormal,
    but the Pareto upper tail adds inequality on top — using it directly
    overshoots the requested Gini by a few points. Bisecting on the realised
    Gini of the actual quantile function removes that bias, so the number on
    the panel is the number in the data.
    """
    target = spec.income.gini
    quantiles = (np.arange(grid) + 0.5) / grid

    def realised(sigma: float) -> float:
        values = np.array(
            [
                income_quantile(
                    float(u),
                    spec.income.median_monthly,
                    sigma,
                    spec.income.pareto_tail_alpha,
                    spec.income.tail_threshold_pct,
                )
                for u in quantiles
            ]
        )
        return _gini_of(values)

    lo, hi = 1e-4, 4.0
    if realised(hi) < target:
        return hi
    if realised(lo) > target:
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if realised(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def income_quantile(u: float, median: float, sigma: float, alpha: float, tail_pct: float) -> float:
    """Income at rank ``u``: lognormal body spliced to a Pareto upper tail.

    A pure lognormal understates top incomes. Above ``tail_pct`` the quantile
    switches to a Pareto with index ``alpha`` (smaller = heavier tail), matched
    in level at the splice point so the function stays continuous.
    """
    u = min(max(float(u), 1e-9), 1.0 - 1e-9)
    if u <= tail_pct:
        return float(median * math.exp(sigma * _norm_ppf(u)))
    threshold = median * math.exp(sigma * _norm_ppf(tail_pct))
    # Pareto survival: S(x) = (threshold/x)^alpha, rescaled onto (tail_pct, 1].
    tail_u = (u - tail_pct) / (1.0 - tail_pct)
    return float(threshold * (1.0 - min(tail_u, 1.0 - 1e-9)) ** (-1.0 / max(alpha, 1e-6)))


# ---------------------------------------------------------------------------
# Age structure
# ---------------------------------------------------------------------------


def solve_age_band_shares(spec: PopulationSpec) -> tuple[dict[str, float], float]:
    """Fit age-band shares to ``share_under_18``/``share_over_65``/``median_age``.

    The two extreme bands are pinned by their knobs. The remaining mass is
    distributed across the three working-age bands by an exponential tilt
    ``exp(-λ·midpoint)``, and ``λ`` is bisected until the implied median hits
    the target. Returns the shares plus the *achieved* median, which may differ
    from the target when the age shares make it unreachable — the report layer
    surfaces that gap instead of hiding it.
    """
    demo = spec.demography
    mid_bands = ("18-34", "35-54", "55-64")
    midpoints = np.array([sum(AGE_BAND_RANGES[b]) / 2.0 for b in mid_bands])
    working_mass = max(0.0, 1.0 - demo.share_under_18 - demo.share_over_65)

    def shares_for(lam: float) -> dict[str, float]:
        weights = np.exp(-lam * (midpoints - midpoints.mean()) / 10.0)
        weights = weights / weights.sum() * working_mass
        out = {"0-17": demo.share_under_18, "65+": demo.share_over_65}
        for band, weight in zip(mid_bands, weights, strict=True):
            out[band] = float(weight)
        return {band: out[band] for band in AGE_BANDS}

    # Larger lambda tilts mass towards younger working-age bands.
    lo, hi = -12.0, 12.0
    target = demo.median_age
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if piecewise_uniform_median(shares_for(mid)) > target:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2.0
    shares = shares_for(lam)
    return shares, piecewise_uniform_median(shares)


# ---------------------------------------------------------------------------
# IPF over the joint attribute table
# ---------------------------------------------------------------------------

_DIMS = ("age", "sex", "education", "employment", "industry")
_DIM_LABELS: dict[str, tuple[str, ...]] = {
    "age": AGE_BANDS,
    "sex": SEXES,
    "education": EDUCATION_LEVELS,
    "employment": EMPLOYMENT_STATUSES,
    "industry": INDUSTRY_SLOTS,
}
_SHAPE = tuple(len(_DIM_LABELS[d]) for d in _DIMS)


def _structural_mask() -> np.ndarray:
    """1.0 where a combination is possible, 0.0 where it is nonsense.

    IPF preserves zeros, so encoding impossibilities here is what keeps
    8-year-old software engineers out of the sample.
    """
    mask = np.ones(_SHAPE)
    age_idx = {b: i for i, b in enumerate(AGE_BANDS)}
    edu_idx = {e: i for i, e in enumerate(EDUCATION_LEVELS)}
    emp_idx = {e: i for i, e in enumerate(EMPLOYMENT_STATUSES)}
    ind_idx = {i: n for n, i in enumerate(INDUSTRY_SLOTS)}

    # Employment and industry are two views of the same fact.
    for emp in EMPLOYMENT_STATUSES:
        for industry in INDUSTRY_SLOTS:
            employed = emp == "employed"
            has_industry = industry != NO_INDUSTRY
            if employed != has_industry:
                mask[:, :, :, emp_idx[emp], ind_idx[industry]] = 0.0

    # Minors: never in the labour force, never tertiary-educated.
    child = age_idx["0-17"]
    mask[child, :, :, emp_idx["employed"], :] = 0.0
    mask[child, :, :, emp_idx["unemployed"], :] = 0.0
    for level in TERTIARY_LEVELS:
        mask[child, :, edu_idx[level], :, :] = 0.0

    # Elders: retired rather than "unemployed"; a few still work.
    elder = age_idx["65+"]
    mask[elder, :, :, emp_idx["unemployed"], :] = 0.0

    # Young adults have not had time for the top qualification in numbers.
    return mask


def _seed_table(spec: PopulationSpec) -> np.ndarray:
    """Prior table before IPF: independent marginals × plausibility tilts."""
    mask = _structural_mask()
    table = mask.copy()
    age_idx = {b: i for i, b in enumerate(AGE_BANDS)}
    edu_idx = {e: i for i, e in enumerate(EDUCATION_LEVELS)}
    ind_idx = {i: n for n, i in enumerate(INDUSTRY_SLOTS)}

    # Education correlates with birth cohort: younger bands skew higher.
    edu_tilt = {
        "0-17": (3.0, 2.0, 1.0, 0.0, 0.0, 0.0),
        "18-34": (0.2, 0.6, 1.4, 1.8, 2.4, 1.2),
        "35-54": (0.6, 1.4, 1.8, 1.4, 1.4, 0.6),
        "55-64": (1.6, 1.8, 1.4, 0.8, 0.6, 0.25),
        "65+": (2.4, 1.8, 1.0, 0.5, 0.35, 0.15),
    }
    for band, weights in edu_tilt.items():
        for level, weight in zip(EDUCATION_LEVELS, weights, strict=True):
            table[age_idx[band], :, edu_idx[level], :, :] *= max(weight, 1e-6)

    # Tertiary education steers industry.
    industry_tilt = {
        "tech": {"大专": 1.2, "本科": 2.2, "硕士及以上": 2.6},
        "finance": {"大专": 1.1, "本科": 2.0, "硕士及以上": 2.2},
        "medical": {"大专": 1.3, "本科": 1.8, "硕士及以上": 2.0},
        "education": {"大专": 1.2, "本科": 2.0, "硕士及以上": 2.4},
        "service": {"小学及以下": 1.6, "初中": 1.8, "高中/中专": 1.6},
        "trade": {"初中": 1.5, "高中/中专": 1.6, "大专": 1.1},
    }
    for industry, tilts in industry_tilt.items():
        for level, weight in tilts.items():
            table[:, :, edu_idx[level], :, ind_idx[industry]] *= weight

    # Elders who do work concentrate in service/trade, not tech.
    for industry in ("tech", "finance"):
        table[age_idx["65+"], :, :, :, ind_idx[industry]] *= 0.1

    return table * mask


#: Share of the 65+ population still doing paid work. Not a panel knob: it is
#: a background regularity rather than something a user tunes, and exposing it
#: would invite the "employment rate" reading to drift again.
ELDER_EMPLOYMENT_RATE = 0.12


def _target_marginals(spec: PopulationSpec, age_shares: dict[str, float]) -> dict[str, np.ndarray]:
    """Target marginals keyed by name; see ``_MARGINAL_AXES`` for their axes.

    ``employment`` is a *joint* (age × employment) marginal rather than a 1-D
    one. With only the 1-D version, IPF is free to satisfy the total employed
    headcount by putting elders to work, which silently drags the working-age
    employment rate below what the panel promised.
    """
    demo = spec.demography
    ew = spec.education_work

    age = np.array([age_shares[b] for b in AGE_BANDS], dtype=float)

    male_share = demo.sex_ratio_m_per_100f / (100.0 + demo.sex_ratio_m_per_100f)
    sex = np.array([male_share, 1.0 - male_share], dtype=float)

    # tertiary_rate is defined over adults; children are pinned to the bottom
    # three levels by the structural mask, so only the adult mass is split.
    adult_share = max(1e-6, 1.0 - age_shares["0-17"])
    tertiary_mass = ew.tertiary_rate * adult_share
    non_tertiary_adult = adult_share - tertiary_mass
    edu = np.zeros(len(EDUCATION_LEVELS))
    lower_split = (0.18, 0.34, 0.48)  # 小学及以下 / 初中 / 高中中专
    upper_split = (0.34, 0.52, 0.14)  # 大专 / 本科 / 硕士及以上
    for i, weight in enumerate(lower_split):
        edu[i] = non_tertiary_adult * weight
    for offset, weight in enumerate(upper_split):
        edu[3 + offset] = tertiary_mass * weight
    # Children spread over the bottom three levels by school stage.
    for i, weight in enumerate((0.42, 0.34, 0.24)):
        edu[i] += age_shares["0-17"] * weight

    # (age band × employment status) joint marginal.
    employment = np.zeros((len(AGE_BANDS), len(EMPLOYMENT_STATUSES)))
    emp_i = EMPLOYMENT_STATUSES.index("employed")
    unemp_i = EMPLOYMENT_STATUSES.index("unemployed")
    nilf_i = EMPLOYMENT_STATUSES.index("not_in_labor_force")
    for band_i, band in enumerate(AGE_BANDS):
        mass = age_shares[band]
        if band == "0-17":
            employment[band_i, nilf_i] = mass
        elif band == "65+":
            employment[band_i, emp_i] = mass * ELDER_EMPLOYMENT_RATE
            employment[band_i, nilf_i] = mass * (1.0 - ELDER_EMPLOYMENT_RATE)
        else:
            employed_here = mass * ew.employment_rate
            unemployed_here = min(mass * ew.unemployment_rate, max(0.0, mass - employed_here))
            employment[band_i, emp_i] = employed_here
            employment[band_i, unemp_i] = unemployed_here
            employment[band_i, nilf_i] = max(0.0, mass - employed_here - unemployed_here)

    employed_total = float(employment[:, emp_i].sum())
    industry = np.array(
        [ew.industry_mix[name] * employed_total for name in INDUSTRIES] + [1.0 - employed_total],
        dtype=float,
    )

    return {
        "age": age / age.sum(),
        "sex": sex / sex.sum(),
        "education": edu / edu.sum(),
        "employment": employment / employment.sum(),
        "industry": industry / industry.sum(),
    }


#: Which table axes each named marginal constrains. ``employment`` spans two
#: axes so the working-age employment rate cannot be satisfied by employing
#: pensioners instead.
_MARGINAL_AXES: dict[str, tuple[int, ...]] = {
    "age": (0,),
    "sex": (1,),
    "education": (2,),
    "employment": (0, 3),
    "industry": (4,),
}


def _collapse(table: np.ndarray, axes: tuple[int, ...]) -> np.ndarray:
    """Sum ``table`` down to just ``axes``, keeping their original order."""
    keep = set(axes)
    return table.sum(axis=tuple(i for i in range(table.ndim) if i not in keep))


def _expand(values: np.ndarray, axes: tuple[int, ...], ndim: int) -> np.ndarray:
    """Reshape a marginal back to a broadcastable ``ndim``-dimensional view."""
    shape = [1] * ndim
    for position, axis in enumerate(axes):
        shape[axis] = values.shape[position]
    return values.reshape(shape)


def ipf_fit(
    seed: np.ndarray,
    targets: dict[str, np.ndarray],
    *,
    max_iter: int = 60,
    tolerance: float = 5e-3,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Iterative proportional fitting onto the marginals in ``_MARGINAL_AXES``.

    Returns the fitted table and a convergence report. Non-convergence is a
    *signal*, not a failure: it means the requested marginals contradict each
    other given the structural zeros, which is exactly what the panel wants to
    tell the user about.
    """
    table = np.array(seed, dtype=float)
    total = table.sum()
    if total <= 0:
        raise ValueError("seed table is empty — structural mask removed every cell")
    table /= total

    def max_deviation(current: np.ndarray) -> float:
        return max(
            float(np.abs(_collapse(current, axes) - targets[name]).max())
            for name, axes in _MARGINAL_AXES.items()
        )

    deviation = float("inf")
    iterations = 0
    for round_index in range(1, max_iter + 1):
        iterations = round_index
        for name, axes in _MARGINAL_AXES.items():
            current = _collapse(table, axes)
            with np.errstate(divide="ignore", invalid="ignore"):
                scale = np.where(current > 0, targets[name] / np.where(current > 0, current, 1.0), 0.0)
            table = table * _expand(scale, axes, table.ndim)
        table_sum = table.sum()
        if table_sum <= 0:
            raise ValueError("IPF collapsed to an empty table — marginals are contradictory")
        table /= table_sum
        deviation = max_deviation(table)
        if deviation <= tolerance:
            break

    report = {
        "iterations": iterations,
        "max_marginal_deviation": deviation,
        "converged": deviation <= tolerance,
        "tolerance": tolerance,
        "targets": {name: targets[name].tolist() for name in _MARGINAL_AXES},
        "achieved": {name: _collapse(table, axes).tolist() for name, axes in _MARGINAL_AXES.items()},
        "labels": {dim: list(_DIM_LABELS[dim]) for dim in _DIMS},
    }
    return table, report


# ---------------------------------------------------------------------------
# Individual sampling
# ---------------------------------------------------------------------------


def integerise(probabilities: np.ndarray, size: int, rng: np.random.Generator) -> np.ndarray:
    """Turn cell probabilities into exact integer counts, then a shuffled draw.

    Drawing ``size`` independent multinomial samples would leave every
    marginal off by a sampling error of order ``√size`` — at N=500 that is
    ±11 people per category, enough for a user to see "employment 68%" on the
    panel and 62% in the result. Largest-remainder allocation instead pins the
    counts to the fitted table, so achieved marginals match the request up to
    integer rounding.

    Returns an array of flat cell indices, one per person, in random order.
    """
    probabilities = np.asarray(probabilities, dtype=float)
    probabilities = probabilities / probabilities.sum()
    exact = probabilities * size
    counts = np.floor(exact).astype(int)
    shortfall = size - int(counts.sum())
    if shortfall > 0:
        # Assign leftovers to the largest fractional parts; ties broken by a
        # seeded jitter so the result stays deterministic but unbiased.
        remainder = exact - counts
        jitter = rng.random(remainder.shape) * 1e-9
        order = np.argsort(-(remainder + jitter))
        counts[order[:shortfall]] += 1
    picks = np.repeat(np.arange(len(counts)), counts)
    rng.shuffle(picks)
    return picks


@dataclass
class Person:
    """One synthetic resident, before households and networks are attached."""

    id: int
    name: str
    gender: str
    age: int
    hukou: str
    residence: str
    district: str
    education: str
    employment: str
    industry: str
    job: str
    income_monthly: float
    is_gig: bool
    state: dict[str, float]
    household_id: int = -1
    household_role: str = ""
    household_type: str = ""
    workplace_id: int = -1
    relationships: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def age_band(self) -> str:
        for band, (low, high) in AGE_BAND_RANGES.items():
            if low <= self.age <= high:
                return band
        return AGE_BANDS[-1]


def _make_names(spec: PopulationSpec, genders: list[str]) -> list[str]:
    rng = derive_rng(spec.seed, "name")
    used: set[str] = set()
    names: list[str] = []
    for gender in genders:
        pool = GIVEN_CHARS_M if gender == "男" else GIVEN_CHARS_F
        pool = pool + GIVEN_CHARS_NEUTRAL
        for _ in range(200):
            surname = SURNAMES[rng.integers(len(SURNAMES))]
            length = 1 if rng.random() < 0.35 else 2
            given = "".join(pool[rng.integers(len(pool))] for _ in range(length))
            candidate = f"{surname}{given}"
            if candidate not in used:
                break
        else:  # pragma: no cover - only if the name pools are exhausted
            candidate = f"{surname}{given}{len(names)}"
        used.add(candidate)
        names.append(candidate)
    return names


def _attribute_income_score(person_bits: dict[str, Any], rng: np.random.Generator) -> float:
    """Latent score driving where someone lands in the income distribution."""
    edu_rank = EDUCATION_LEVELS.index(person_bits["education"]) / (len(EDUCATION_LEVELS) - 1)
    industry_premium = {
        "tech": 0.75,
        "finance": 0.80,
        "medical": 0.55,
        "education": 0.40,
        "service": 0.15,
        "trade": 0.35,
    }.get(person_bits["industry"], 0.0)
    age = person_bits["age"]
    # Experience premium peaks in the late 40s then flattens.
    experience = min(max((age - 22) / 25.0, 0.0), 1.0) * 0.6
    noise = float(rng.normal(0.0, 0.55))
    return 1.0 * edu_rank + 0.9 * industry_premium + experience + noise


def _sample_state(
    spec: PopulationSpec,
    bits: dict[str, Any],
    income_rank: float,
    rng: np.random.Generator,
) -> dict[str, float]:
    means = spec.psychology.state_means
    sd = spec.psychology.state_sd
    values = {key: float(means[key] + rng.normal(0.0, sd)) for key in STATE_VAR_KEYS}

    if spec.psychology.couple_states_to_attributes:
        centered_income = income_rank - 0.5
        age = bits["age"]
        values["econ_security"] += 0.45 * centered_income
        values["stress"] -= 0.20 * centered_income
        if bits["employment"] == "unemployed":
            values["econ_security"] -= 0.20
            values["stress"] += 0.15
        if bits["hukou"] != "本地":
            values["city_identity"] -= 0.18
            values["mobility_intent"] += 0.15
        if bits["is_gig"]:
            values["platform_dependence"] += 0.25
            values["econ_security"] -= 0.10
        # Older residents settle down; younger ones move and post more.
        youth = min(max((40 - age) / 30.0, -1.0), 1.0)
        values["mobility_intent"] += 0.15 * youth
        values["platform_dependence"] += 0.12 * youth
        values["risk_preference"] += 0.10 * youth
        edu_rank = EDUCATION_LEVELS.index(bits["education"]) / (len(EDUCATION_LEVELS) - 1)
        values["policy_sensitivity"] += 0.15 * (edu_rank - 0.5)
        values["voice_propensity"] += 0.18 * (edu_rank - 0.5)

    return {key: float(np.clip(value, 0.0, 1.0)) for key, value in values.items()}


def synthesize_people(spec: PopulationSpec) -> tuple[list[Person], dict[str, Any]]:
    """Generate ``spec.size`` residents and a fitting report.

    The report carries the IPF convergence details and target-vs-achieved
    marginals so the panel can show which knob had to give.
    """
    age_shares, achieved_median_age = solve_age_band_shares(spec)
    targets = _target_marginals(spec, age_shares)
    table, ipf_report = ipf_fit(_seed_table(spec), targets)

    cell_rng = derive_rng(spec.seed, "cells")
    picks = integerise(table.reshape(-1), spec.size, cell_rng)
    indices = np.array(np.unravel_index(picks, _SHAPE)).T

    age_rng = derive_rng(spec.seed, "age")
    hukou_rng = derive_rng(spec.seed, "hukou")
    geo_rng = derive_rng(spec.seed, "geo")
    job_rng = derive_rng(spec.seed, "job")
    income_rng = derive_rng(spec.seed, "income")
    state_rng = derive_rng(spec.seed, "state")

    districts = list(spec.geography.district_weights)
    district_p = np.array([spec.geography.district_weights[d] for d in districts], dtype=float)
    district_p = district_p / district_p.sum()

    bits_list: list[dict[str, Any]] = []
    for age_i, sex_i, edu_i, emp_i, ind_i in indices:
        band = AGE_BANDS[age_i]
        low, high = AGE_BAND_RANGES[band]
        # Do not instantiate agents below the modelling floor (see
        # ``Demography.min_agent_age``); the child band starts there instead.
        low = max(low, min(spec.demography.min_agent_age, high))
        employment = EMPLOYMENT_STATUSES[emp_i]
        industry = INDUSTRY_SLOTS[ind_i]
        is_gig = bool(
            employment == "employed"
            and industry in ("service", "trade")
            and job_rng.random() < spec.education_work.gig_platform_share
        )
        bits_list.append(
            {
                "age": int(age_rng.integers(low, high + 1)),
                "gender": SEXES[sex_i],
                "education": EDUCATION_LEVELS[edu_i],
                "employment": employment,
                "industry": industry,
                "is_gig": is_gig,
            }
        )

    # Hukou: migrants skew young and working-age, so draw against an age tilt
    # rather than uniformly — otherwise the town gets implausible 80-year-old
    # first-generation migrants.
    migrant_weights = np.array(
        [1.6 if 18 <= b["age"] <= 45 else (0.9 if b["age"] < 18 else 0.35) for b in bits_list]
    )
    migrant_p = migrant_weights / migrant_weights.sum()
    n_migrants = round(spec.demography.migrant_share * spec.size)
    migrant_ids = set(
        hukou_rng.choice(spec.size, size=min(n_migrants, spec.size), replace=False, p=migrant_p).tolist()
    )
    for i, bits in enumerate(bits_list):
        if i in migrant_ids:
            roll = hukou_rng.random()
            bits["hukou"] = "省内" if roll < 0.25 else ("外国" if roll > 0.99 else "外省")
        else:
            bits["hukou"] = "本地"

    # Income: rank-transform an attribute-driven score so the requested median
    # and Gini hold exactly while income still correlates with attributes.
    sigma = solve_income_sigma(spec)
    scores = np.array(
        [
            _attribute_income_score(bits, income_rng) if bits["employment"] == "employed" else -np.inf
            for bits in bits_list
        ]
    )
    employed_positions = [i for i, bits in enumerate(bits_list) if bits["employment"] == "employed"]
    ranks = np.zeros(spec.size)
    if employed_positions:
        order = sorted(employed_positions, key=lambda i: scores[i])
        for rank, idx in enumerate(order):
            ranks[idx] = (rank + 0.5) / len(order)

    people: list[Person] = []
    names = _make_names(spec, [bits["gender"] for bits in bits_list])
    for i, bits in enumerate(bits_list):
        if bits["employment"] == "employed":
            income = income_quantile(
                float(ranks[i]),
                spec.income.median_monthly,
                sigma,
                spec.income.pareto_tail_alpha,
                spec.income.tail_threshold_pct,
            )
            titles = JOB_TITLES[bits["industry"]]
            job = str(titles[job_rng.integers(len(titles))])
            if bits["is_gig"]:
                job = f"{job}（平台接单）"
        elif bits["age"] < 18:
            income = 0.0
            job = NON_EMPLOYED_JOBS["student"][0]
        elif bits["age"] >= 65:
            income = spec.income.median_monthly * 0.35
            job = NON_EMPLOYED_JOBS["retired"][0]
        elif bits["employment"] == "unemployed":
            income = spec.income.median_monthly * 0.15
            pool = NON_EMPLOYED_JOBS["unemployed"]
            job = str(pool[job_rng.integers(len(pool))])
        else:
            # Homemakers have no income of their own — they are supported by
            # the household. Giving them a token wage would both misstate the
            # income distribution and trip the "income without a job" check.
            income = 0.0
            job = NON_EMPLOYED_JOBS["homemaker"][0]

        district = districts[int(geo_rng.choice(len(districts), p=district_p))]
        suffix = RESIDENCE_SUFFIXES[geo_rng.integers(len(RESIDENCE_SUFFIXES))]
        state = _sample_state(
            spec, bits, float(ranks[i]) if bits["employment"] == "employed" else 0.35, state_rng
        )

        people.append(
            Person(
                id=i + 1,
                name=names[i],
                gender=bits["gender"],
                age=bits["age"],
                hukou=bits["hukou"],
                residence=f"{district}·{suffix}",
                district=district,
                education=bits["education"],
                employment=bits["employment"],
                industry=bits["industry"],
                job=job,
                income_monthly=round(float(income), 2),
                is_gig=bits["is_gig"],
                state=state,
            )
        )

    report: dict[str, Any] = {
        "ipf": ipf_report,
        "age_band_shares": age_shares,
        "median_age": {"target": spec.demography.median_age, "achieved": achieved_median_age},
        "lognormal_sigma": sigma,
    }
    return people, report


__all__ = [
    "AGE_BAND_RANGES",
    "JOB_TITLES",
    "Person",
    "derive_rng",
    "income_quantile",
    "integerise",
    "ipf_fit",
    "lognormal_sigma_from_gini",
    "solve_age_band_shares",
    "solve_income_sigma",
    "synthesize_people",
]
