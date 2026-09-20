"""Panel parameter contract for synthetic populations.

This module owns the *single* definition of the population knobs. The
dashboard reads it over ``/api/population/schema`` rather than re-declaring
the fields in JavaScript — the 9 state variables are currently declared twice
(``gaworld/apps/dashboard_server.py`` and ``site/dashboard/studio.js``) and we
do not want to repeat that.

Two entry points matter:

``normalize_spec``    preset defaults + user overrides + clamping → PopulationSpec
``check_feasibility`` pure-maths precheck the panel can run on every keystroke,
                      without generating anybody
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Category vocabularies
# ---------------------------------------------------------------------------

# Age bands used by the IPF contingency table. Individual ages are sampled
# inside a band afterwards, so the bands only need to be coarse enough for the
# joint table to stay well-conditioned at N=500.
AGE_BANDS: tuple[str, ...] = ("0-17", "18-34", "35-54", "55-64", "65+")
AGE_BAND_RANGES: dict[str, tuple[int, int]] = {
    "0-17": (0, 17),
    "18-34": (18, 34),
    "35-54": (35, 54),
    "55-64": (55, 64),
    "65+": (65, 92),
}

SEXES: tuple[str, ...] = ("男", "女")

EDUCATION_LEVELS: tuple[str, ...] = (
    "小学及以下",
    "初中",
    "高中/中专",
    "大专",
    "本科",
    "硕士及以上",
)
#: Education levels that count towards ``education_work.tertiary_rate``.
TERTIARY_LEVELS: frozenset[str] = frozenset({"大专", "本科", "硕士及以上"})

EMPLOYMENT_STATUSES: tuple[str, ...] = ("employed", "unemployed", "not_in_labor_force")

#: Must stay in sync with ``JOB_INDUSTRY_MAP`` in ``gaworld/economy/finance.py``
#: — the generated job text has to contain a keyword the economy can classify.
INDUSTRIES: tuple[str, ...] = ("tech", "finance", "medical", "education", "service", "trade")
#: Pseudo-industry for anyone not currently employed.
NO_INDUSTRY = "none"

HUKOU_LABELS: tuple[str, ...] = ("本地", "省内", "外省", "外国")

#: The nine [0,1] state variables written to the state CSV. Order matters: it
#: is the CSV column order after ``id,name,gender,age,hukou,residence``.
STATE_VAR_KEYS: tuple[str, ...] = (
    "emotion",
    "stress",
    "econ_security",
    "city_identity",
    "policy_sensitivity",
    "platform_dependence",
    "risk_preference",
    "voice_propensity",
    "mobility_intent",
)

#: Column order of ``data/hangzhou_agents_state_init.csv``.
CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "gender",
    "age",
    "hukou",
    "residence",
    *STATE_VAR_KEYS,
)

HOUSEHOLD_TYPES: tuple[str, ...] = (
    "single",
    "couple",
    "nuclear",
    "single_parent",
    "multigen",
    "shared_rental",
)

IssueLevel = Literal["error", "warning"]


# ---------------------------------------------------------------------------
# Spec sections
# ---------------------------------------------------------------------------


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(num):
        return float(default)
    return float(min(max(num, low), high))


def _normalize_mix(raw: Any, keys: tuple[str, ...], defaults: Mapping[str, float]) -> dict[str, float]:
    """Coerce a category→weight mapping to non-negative weights summing to 1.

    A *partial* mapping means the unlisted categories are zero, not that they
    keep their default weight. ``{"tech": 3, "service": 1}`` reads as "75%
    tech, 25% service" to anyone who writes it; quietly re-adding the other
    four industries at their preset weights would be a nasty surprise.
    """
    source: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    fallback: Mapping[str, float] = defaults if not source else dict.fromkeys(keys, 0.0)
    values = {key: max(0.0, _clamp(source.get(key, fallback[key]), 0.0, 1e9, fallback[key])) for key in keys}
    total = sum(values.values())
    if total <= 0:
        return dict(defaults)
    return {key: value / total for key, value in values.items()}


@dataclass(frozen=True)
class Demography:
    median_age: float = 36.0
    share_under_18: float = 0.16
    share_over_65: float = 0.14
    sex_ratio_m_per_100f: float = 104.0
    migrant_share: float = 0.38
    #: Youngest age that gets instantiated as an agent. GAWorld agents plan a
    #: day, hold opinions and reflect; a demographically-correct pyramid
    #: reaching down to age 0 would hand the cognition pipeline toddlers to
    #: reason about. School age is the lowest point where a daily schedule and
    #: a social circle are meaningful, so the 0-17 band is sampled from here
    #: up. The under-6 population is simply not represented.
    min_agent_age: int = 6


@dataclass(frozen=True)
class Household:
    mean_size: float = 2.6
    share_single_person: float = 0.25
    share_multigen: float = 0.18
    share_shared_rental: float = 0.12
    max_size: int = 6
    spouse_age_gap_mean: float = 2.0
    fertility_children_mean: float = 1.1


@dataclass(frozen=True)
class EducationWork:
    #: Share of adults (18+) holding a 大专 or higher qualification.
    tertiary_rate: float = 0.35
    #: Share of the *working-age* population (18-64) that holds a job — the
    #: standard demographic definition. Expressing it over the whole
    #: population instead would make it silently conflict with the age
    #: pyramid, since children and elders cannot be employed.
    employment_rate: float = 0.68
    #: Share of the working-age population in the labour force but jobless.
    unemployment_rate: float = 0.05
    gig_platform_share: float = 0.10
    industry_mix: dict[str, float] = field(
        default_factory=lambda: {
            "tech": 0.18,
            "finance": 0.08,
            "medical": 0.07,
            "education": 0.09,
            "service": 0.38,
            "trade": 0.20,
        }
    )


@dataclass(frozen=True)
class Income:
    median_monthly: float = 6500.0
    gini: float = 0.42
    pareto_tail_alpha: float = 2.2
    tail_threshold_pct: float = 0.95


@dataclass(frozen=True)
class Geography:
    district_weights: dict[str, float] = field(
        default_factory=lambda: {
            "余杭": 0.18,
            "滨江": 0.12,
            "西湖": 0.15,
            "上城": 0.13,
            "拱墅": 0.12,
            "钱塘": 0.10,
            "萧山": 0.12,
            "临平": 0.08,
        }
    )


@dataclass(frozen=True)
class Psychology:
    state_means: dict[str, float] = field(
        default_factory=lambda: {
            "emotion": 0.58,
            "stress": 0.55,
            "econ_security": 0.52,
            "city_identity": 0.55,
            "policy_sensitivity": 0.50,
            "platform_dependence": 0.50,
            "risk_preference": 0.45,
            "voice_propensity": 0.45,
            "mobility_intent": 0.45,
        }
    )
    state_sd: float = 0.12
    #: When true, individual state values are nudged by their attributes
    #: (income → econ_security, hukou → city_identity, gig work →
    #: platform_dependence, …) instead of being pure iid noise.
    couple_states_to_attributes: bool = True


@dataclass(frozen=True)
class SocialNetwork:
    mean_degree: float = 12.0
    homophily_strength: float = 0.55
    geo_decay: float = 0.35
    rewire_p: float = 0.10
    workplace_size_alpha: float = 2.0
    dunbar_weak_cap: int = 150


@dataclass(frozen=True)
class PopulationSpec:
    size: int = 500
    seed: int = 42
    preset: str = "cn_county_town"
    name: str = "generated_town"
    demography: Demography = field(default_factory=Demography)
    household: Household = field(default_factory=Household)
    education_work: EducationWork = field(default_factory=EducationWork)
    income: Income = field(default_factory=Income)
    geography: Geography = field(default_factory=Geography)
    psychology: Psychology = field(default_factory=Psychology)
    social_network: SocialNetwork = field(default_factory=SocialNetwork)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

#: Preset → partial spec overrides. Only the fields that differ from the
#: dataclass defaults are listed, so adding a new knob does not require
#: touching every preset.
PRESETS: dict[str, dict[str, Any]] = {
    "cn_county_town": {},
    "cn_tier1_district": {
        "demography": {
            "median_age": 34.0,
            "share_under_18": 0.14,
            "share_over_65": 0.12,
            "migrant_share": 0.55,
        },
        "education_work": {
            "tertiary_rate": 0.52,
            "employment_rate": 0.74,
            "industry_mix": {
                "tech": 0.30,
                "finance": 0.14,
                "medical": 0.07,
                "education": 0.09,
                "service": 0.28,
                "trade": 0.12,
            },
        },
        "income": {"median_monthly": 11000.0, "gini": 0.46},
        "household": {"mean_size": 2.3, "share_single_person": 0.32, "share_shared_rental": 0.22},
    },
    "aging_community": {
        "demography": {
            "median_age": 52.0,
            "share_under_18": 0.09,
            "share_over_65": 0.34,
            "migrant_share": 0.12,
        },
        "education_work": {
            "tertiary_rate": 0.18,
            "employment_rate": 0.42,
            "industry_mix": {
                "tech": 0.04,
                "finance": 0.04,
                "medical": 0.18,
                "education": 0.08,
                "service": 0.46,
                "trade": 0.20,
            },
        },
        "income": {"median_monthly": 4200.0, "gini": 0.36},
        "household": {"mean_size": 2.1, "share_single_person": 0.34, "share_multigen": 0.24},
        "psychology": {"state_means": {"mobility_intent": 0.28, "platform_dependence": 0.32}},
    },
    "college_town": {
        # median_age 27 rather than a "student town" 22: with 10% minors and
        # 7% elders pinned, 26 is the mathematically lowest reachable median
        # (see median_age_bounds), so anything lower would ship a preset that
        # trips its own feasibility check.
        "demography": {
            "median_age": 27.0,
            "share_under_18": 0.10,
            "share_over_65": 0.07,
            "migrant_share": 0.62,
        },
        "education_work": {
            "tertiary_rate": 0.80,
            "employment_rate": 0.35,
            "industry_mix": {
                "tech": 0.22,
                "finance": 0.06,
                "medical": 0.06,
                "education": 0.34,
                "service": 0.24,
                "trade": 0.08,
            },
        },
        "income": {"median_monthly": 4500.0, "gini": 0.34},
        "household": {
            "mean_size": 2.0,
            "share_single_person": 0.22,
            "share_shared_rental": 0.45,
            # Few elders here, so three-generation households are rare.
            "share_multigen": 0.05,
        },
        "psychology": {"state_means": {"mobility_intent": 0.62, "platform_dependence": 0.66}},
    },
    "us_suburb": {
        "demography": {
            "median_age": 39.0,
            "share_under_18": 0.23,
            "share_over_65": 0.16,
            "migrant_share": 0.14,
        },
        "education_work": {"tertiary_rate": 0.45, "employment_rate": 0.63},
        "income": {"median_monthly": 5800.0, "gini": 0.48},
        "household": {"mean_size": 2.5, "share_single_person": 0.28, "share_shared_rental": 0.05},
    },
    "custom": {},
}


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    return value if isinstance(value, Mapping) else {}


def normalize_spec(raw: Mapping[str, Any] | None = None) -> PopulationSpec:
    """Build a validated :class:`PopulationSpec` from loose panel input.

    Preset defaults are applied first, then the caller's overrides, then every
    value is clamped into range. Unknown keys are ignored rather than raising,
    so an older panel talking to a newer backend degrades gracefully.
    """
    raw = dict(raw or {})
    preset = str(raw.get("preset") or "cn_county_town")
    if preset not in PRESETS:
        preset = "custom"
    merged = _deep_merge(PRESETS.get(preset, {}), raw)

    demo_raw = _section(merged, "demography")
    demography = Demography(
        median_age=_clamp(demo_raw.get("median_age"), 18.0, 65.0, 36.0),
        share_under_18=_clamp(demo_raw.get("share_under_18"), 0.0, 0.40, 0.16),
        share_over_65=_clamp(demo_raw.get("share_over_65"), 0.0, 0.50, 0.14),
        sex_ratio_m_per_100f=_clamp(demo_raw.get("sex_ratio_m_per_100f"), 80.0, 130.0, 104.0),
        migrant_share=_clamp(demo_raw.get("migrant_share"), 0.0, 0.90, 0.38),
        min_agent_age=int(_clamp(demo_raw.get("min_agent_age"), 0, 17, 6)),
    )

    hh_raw = _section(merged, "household")
    household = Household(
        mean_size=_clamp(hh_raw.get("mean_size"), 1.0, 6.0, 2.6),
        share_single_person=_clamp(hh_raw.get("share_single_person"), 0.0, 0.80, 0.25),
        share_multigen=_clamp(hh_raw.get("share_multigen"), 0.0, 0.60, 0.18),
        share_shared_rental=_clamp(hh_raw.get("share_shared_rental"), 0.0, 0.50, 0.12),
        max_size=int(_clamp(hh_raw.get("max_size"), 2, 12, 6)),
        spouse_age_gap_mean=_clamp(hh_raw.get("spouse_age_gap_mean"), -5.0, 10.0, 2.0),
        fertility_children_mean=_clamp(hh_raw.get("fertility_children_mean"), 0.0, 4.0, 1.1),
    )

    ew_raw = _section(merged, "education_work")
    education_work = EducationWork(
        tertiary_rate=_clamp(ew_raw.get("tertiary_rate"), 0.0, 1.0, 0.35),
        employment_rate=_clamp(ew_raw.get("employment_rate"), 0.0, 1.0, 0.68),
        unemployment_rate=_clamp(ew_raw.get("unemployment_rate"), 0.0, 0.40, 0.05),
        gig_platform_share=_clamp(ew_raw.get("gig_platform_share"), 0.0, 0.50, 0.10),
        industry_mix=_normalize_mix(ew_raw.get("industry_mix"), INDUSTRIES, EducationWork().industry_mix),
    )

    inc_raw = _section(merged, "income")
    income = Income(
        median_monthly=_clamp(inc_raw.get("median_monthly"), 1000.0, 100000.0, 6500.0),
        gini=_clamp(inc_raw.get("gini"), 0.15, 0.65, 0.42),
        pareto_tail_alpha=_clamp(inc_raw.get("pareto_tail_alpha"), 1.2, 4.0, 2.2),
        tail_threshold_pct=_clamp(inc_raw.get("tail_threshold_pct"), 0.80, 0.99, 0.95),
    )

    geo_raw = _section(merged, "geography")
    districts_raw = geo_raw.get("district_weights")
    default_districts = Geography().district_weights
    if isinstance(districts_raw, Mapping) and districts_raw:
        keys = tuple(str(k) for k in districts_raw)
        fallback = dict.fromkeys(keys, 1.0)
        geography = Geography(district_weights=_normalize_mix(districts_raw, keys, fallback))
    else:
        geography = Geography(
            district_weights=_normalize_mix(default_districts, tuple(default_districts), default_districts)
        )

    psy_raw = _section(merged, "psychology")
    means_raw = psy_raw.get("state_means")
    default_means = Psychology().state_means
    means_source: Mapping[str, Any] = means_raw if isinstance(means_raw, Mapping) else {}
    psychology = Psychology(
        state_means={
            key: _clamp(means_source.get(key, default_means[key]), 0.0, 1.0, default_means[key])
            for key in STATE_VAR_KEYS
        },
        state_sd=_clamp(psy_raw.get("state_sd"), 0.0, 0.30, 0.12),
        couple_states_to_attributes=bool(psy_raw.get("couple_states_to_attributes", True)),
    )

    net_raw = _section(merged, "social_network")
    social_network = SocialNetwork(
        mean_degree=_clamp(net_raw.get("mean_degree"), 2.0, 40.0, 12.0),
        homophily_strength=_clamp(net_raw.get("homophily_strength"), 0.0, 1.0, 0.55),
        geo_decay=_clamp(net_raw.get("geo_decay"), 0.0, 1.0, 0.35),
        rewire_p=_clamp(net_raw.get("rewire_p"), 0.0, 0.50, 0.10),
        workplace_size_alpha=_clamp(net_raw.get("workplace_size_alpha"), 1.2, 3.0, 2.0),
        dunbar_weak_cap=int(_clamp(net_raw.get("dunbar_weak_cap"), 50, 500, 150)),
    )

    spec = PopulationSpec(
        size=int(_clamp(merged.get("size"), 20, 5000, 500)),
        seed=int(_clamp(merged.get("seed"), 0, 2**31 - 1, 42)),
        preset=preset,
        name=str(merged.get("name") or "generated_town"),
        demography=demography,
        household=household,
        education_work=education_work,
        income=income,
        geography=geography,
        psychology=psychology,
        social_network=social_network,
    )
    return _resolve_structural_conflicts(spec)


def _resolve_structural_conflicts(spec: PopulationSpec) -> PopulationSpec:
    """Repair combinations that are impossible rather than merely unlikely.

    Only conflicts that would make sampling *undefined* are fixed here (age
    shares over 100%, household-type shares over 100%). Everything softer is
    left alone and surfaced by :func:`check_feasibility`, so the panel can
    explain the trade-off instead of silently overriding the user.
    """
    demo = spec.demography
    age_total = demo.share_under_18 + demo.share_over_65
    if age_total >= 0.98:
        scale = 0.95 / age_total
        demo = replace(
            demo, share_under_18=demo.share_under_18 * scale, share_over_65=demo.share_over_65 * scale
        )

    hh = spec.household
    hh_total = hh.share_single_person + hh.share_multigen + hh.share_shared_rental
    if hh_total > 0.95:
        scale = 0.95 / hh_total
        hh = replace(
            hh,
            share_single_person=hh.share_single_person * scale,
            share_multigen=hh.share_multigen * scale,
            share_shared_rental=hh.share_shared_rental * scale,
        )

    return replace(spec, demography=demo, household=hh)


# ---------------------------------------------------------------------------
# Feasibility precheck
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """One feasibility finding, addressed to a specific panel knob."""

    level: IssueLevel
    code: str
    knob: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def piecewise_uniform_median(band_shares: Mapping[str, float]) -> float:
    """Median of a distribution that is uniform inside each age band.

    Lives here rather than in ``synth`` so :func:`check_feasibility` can reason
    about reachable median ages without importing the sampler.
    """
    cumulative = 0.0
    for band in AGE_BANDS:
        share = float(band_shares.get(band, 0.0))
        if share <= 0:
            continue
        if cumulative + share >= 0.5:
            low, high = AGE_BAND_RANGES[band]
            return low + ((0.5 - cumulative) / share) * (high + 1 - low)
        cumulative += share
    return float(AGE_BAND_RANGES[AGE_BANDS[-1]][1])


def median_age_bounds(spec: PopulationSpec) -> tuple[float, float]:
    """Reachable ``[min, max]`` median age given the two age-share knobs.

    The under-18 and over-65 shares are pinned by their own knobs, so the only
    freedom left is how the working-age mass is spread across 18-34/35-54/
    55-64. Piling it all into the youngest band gives the lowest achievable
    median; all into the oldest gives the highest.
    """
    demo = spec.demography
    working = max(0.0, 1.0 - demo.share_under_18 - demo.share_over_65)
    base = {"0-17": demo.share_under_18, "65+": demo.share_over_65, "18-34": 0.0, "35-54": 0.0, "55-64": 0.0}
    youngest = {**base, "18-34": working}
    oldest = {**base, "55-64": working}
    return piecewise_uniform_median(youngest), piecewise_uniform_median(oldest)


def household_size_bounds(spec: PopulationSpec) -> tuple[float, float]:
    """Feasible ``[min, max]`` mean household size given the single-person share.

    With a share ``s`` of one-person households, the remaining ``1-s`` have at
    least 2 and at most ``max_size`` members, so::

        1·s + 2·(1-s)  ≤  mean_size  ≤  1·s + max_size·(1-s)

    Checking only the lower bound (an easy mistake) misses the far more common
    user error of asking for many single-person households *and* a large mean.
    """
    share_single = spec.household.share_single_person
    low = 1.0 * share_single + 2.0 * (1.0 - share_single)
    high = 1.0 * share_single + float(spec.household.max_size) * (1.0 - share_single)
    return low, high


def check_feasibility(spec: PopulationSpec) -> list[Issue]:
    """Pure-maths precheck — cheap enough to run on every panel keystroke.

    Returns ``error`` issues for combinations that cannot be satisfied at all
    and ``warning`` issues for ones that will be satisfied only approximately.
    Never raises: the panel is expected to render these, not crash on them.
    """
    issues: list[Issue] = []
    demo = spec.demography
    hh = spec.household
    ew = spec.education_work

    working_age_share = 1.0 - demo.share_under_18 - demo.share_over_65
    if working_age_share <= 0.02:
        issues.append(
            Issue(
                "error",
                "no_working_age_population",
                "demography.share_under_18",
                f"少儿比 {demo.share_under_18:.0%} + 老龄比 {demo.share_over_65:.0%} "
                f"几乎占满全部人口，劳动年龄人口只剩 {working_age_share:.1%}。",
                "调低 share_under_18 或 share_over_65。",
            )
        )

    # Median age is not free once the two age shares are pinned.
    min_median, max_median = median_age_bounds(spec)
    if demo.median_age < min_median - 0.5 or demo.median_age > max_median + 0.5:
        issues.append(
            Issue(
                "warning",
                "median_age_unreachable",
                "demography.median_age",
                f"在少儿比 {demo.share_under_18:.0%} / 老龄比 {demo.share_over_65:.0%} 之下，"
                f"中位年龄只能落在 {min_median:.0f}–{max_median:.0f} 岁，"
                f"设定的 {demo.median_age:.0f} 岁无法达成。",
                f"把 median_age 调到 {min_median:.0f}–{max_median:.0f} 之间，或调整年龄结构占比。",
            )
        )

    low, high = household_size_bounds(spec)
    if hh.mean_size < low - 1e-9:
        issues.append(
            Issue(
                "error",
                "household_mean_too_small",
                "household.mean_size",
                f"单人户占比 {hh.share_single_person:.0%} 时，户均规模至少是 {low:.2f}，"
                f"但设定为 {hh.mean_size:.2f}。",
                f"把 mean_size 提到 {low:.2f} 以上，或调低 share_single_person。",
            )
        )
    if hh.mean_size > high + 1e-9:
        issues.append(
            Issue(
                "error",
                "household_mean_too_large",
                "household.mean_size",
                f"单人户占比 {hh.share_single_person:.0%} 且最大户规模 {hh.max_size} 时，"
                f"户均规模最多是 {high:.2f}，但设定为 {hh.mean_size:.2f}。",
                f"把 mean_size 降到 {high:.2f} 以下，调低 share_single_person，或放大 max_size。",
            )
        )

    # employment_rate and unemployment_rate are both shares *of the
    # working-age population*, so together they cannot exceed 1.
    if ew.employment_rate + ew.unemployment_rate > 1.0 + 1e-9:
        issues.append(
            Issue(
                "error",
                "labor_force_over_one",
                "education_work.unemployment_rate",
                f"就业率 {ew.employment_rate:.0%} + 失业率 {ew.unemployment_rate:.0%} 超过 100%，"
                "两者都是劳动年龄人口内部的占比。",
                f"把失业率降到 {max(0.0, 1.0 - ew.employment_rate):.0%} 以下。",
            )
        )

    # The panel shows employment as a working-age rate, but users often read
    # it as a whole-population rate. Surface the implied headcount so the two
    # readings cannot be confused.
    employed_share_of_total = ew.employment_rate * working_age_share
    if employed_share_of_total < 0.20:
        issues.append(
            Issue(
                "warning",
                "few_employed_overall",
                "education_work.employment_rate",
                f"就业率是劳动年龄人口口径；结合年龄结构，全人口中只有 "
                f"{employed_share_of_total:.0%}（约 {round(employed_share_of_total * spec.size)} 人）在业。",
                "如需更多在业者，可提高就业率或调低少儿/老龄占比。",
            )
        )

    # Multigen households each need at least one elder, so the elder headcount
    # caps how many of them can exist.
    households_estimate = max(1.0, spec.size / max(hh.mean_size, 1.0))
    elders_needed = hh.share_multigen * households_estimate
    elders_available = demo.share_over_65 * spec.size
    if elders_needed > elders_available + 1e-9:
        reachable = elders_available / households_estimate
        issues.append(
            Issue(
                "warning",
                "multigen_needs_more_elders",
                "household.share_multigen",
                f"三代同堂户需要 {elders_needed:.0f} 位老人，但按老龄比只有 {elders_available:.0f} 位，"
                f"实际最多做到 {reachable:.0%}。",
                f"把 share_multigen 降到 {reachable:.0%} 以下，或提高 share_over_65。",
            )
        )

    if spec.social_network.mean_degree >= spec.size:
        issues.append(
            Issue(
                "error",
                "degree_exceeds_population",
                "social_network.mean_degree",
                f"平均度 {spec.social_network.mean_degree:.0f} 不小于人口规模 {spec.size}。",
                "调低 mean_degree 或放大 size。",
            )
        )

    if spec.size < 50 and spec.social_network.mean_degree > spec.size / 3:
        issues.append(
            Issue(
                "warning",
                "degree_high_for_small_population",
                "social_network.mean_degree",
                "小规模人口下的高平均度会让网络接近全连通，同质性与小世界性质失去意义。",
                "调低 mean_degree，或把 size 提到 100 以上。",
            )
        )

    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)


__all__ = [
    "AGE_BANDS",
    "AGE_BAND_RANGES",
    "CSV_COLUMNS",
    "EDUCATION_LEVELS",
    "EMPLOYMENT_STATUSES",
    "HOUSEHOLD_TYPES",
    "HUKOU_LABELS",
    "INDUSTRIES",
    "NO_INDUSTRY",
    "PRESETS",
    "SEXES",
    "STATE_VAR_KEYS",
    "TERTIARY_LEVELS",
    "Demography",
    "EducationWork",
    "Geography",
    "Household",
    "Income",
    "Issue",
    "PopulationSpec",
    "Psychology",
    "SocialNetwork",
    "check_feasibility",
    "has_errors",
    "household_size_bounds",
    "median_age_bounds",
    "normalize_spec",
    "piecewise_uniform_median",
]
