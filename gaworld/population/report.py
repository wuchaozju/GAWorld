"""Validation and review charts for a generated population.

Two jobs, deliberately in one module because they answer the same question
from opposite ends:

``validate_population``   did we generate anything *impossible*? (hard gate)
``build_report``          how close did we land to what was asked? (soft gate)

The second matters as much as the first. A population panel that silently
delivers 58% employment when the user asked for 68% is worse than one that
refuses, so every marginal is reported as target-vs-achieved and the caller is
expected to show the gap.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np

from gaworld.population.network import HouseholdRecord, WorkplaceRecord, graph_metrics
from gaworld.population.schema import (
    AGE_BAND_RANGES,
    AGE_BANDS,
    EDUCATION_LEVELS,
    INDUSTRIES,
    STATE_VAR_KEYS,
    TERTIARY_LEVELS,
    PopulationSpec,
)
from gaworld.population.synth import Person

CHILD_MAX_AGE = 17
ELDER_MIN_AGE = 65
#: Legal-ish floor for paid work; anything below is a hard failure.
MIN_WORKING_AGE = 16


@dataclass(frozen=True)
class Finding:
    level: Literal["error", "warning"]
    code: str
    message: str
    count: int = 0
    sample: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finding(level: Literal["error", "warning"], code: str, message: str, offenders: list[int]) -> Finding:
    return Finding(level, code, message, count=len(offenders), sample=tuple(offenders[:8]))


# ---------------------------------------------------------------------------
# Hard gate
# ---------------------------------------------------------------------------


def validate_population(
    spec: PopulationSpec,
    people: list[Person],
    households: list[HouseholdRecord],
    neighbours: dict[int, list[int]],
) -> list[Finding]:
    """Structural checks. ``error`` findings mean the output must not ship."""
    findings: list[Finding] = []
    by_id = {p.id: p for p in people}

    def add(level: Literal["error", "warning"], code: str, message: str, offenders: list[int]) -> None:
        if offenders:
            findings.append(_finding(level, code, message, offenders))

    add(
        "error",
        "underage_worker",
        f"未满 {MIN_WORKING_AGE} 岁却处于就业状态",
        [p.id for p in people if p.age < MIN_WORKING_AGE and p.employment == "employed"],
    )
    add(
        "error",
        "child_with_tertiary_education",
        "未成年人拥有大专及以上学历",
        [p.id for p in people if p.age <= CHILD_MAX_AGE and p.education in TERTIARY_LEVELS],
    )
    add(
        "error",
        "income_without_job",
        "未就业却有工资性收入",
        [
            p.id
            for p in people
            if p.employment != "employed"
            and p.income_monthly > 0
            and p.age < ELDER_MIN_AGE
            and p.employment != "unemployed"
        ],
    )
    add(
        "error",
        "employed_without_industry",
        "在业但没有行业归属（经济模块将无法归类）",
        [p.id for p in people if p.employment == "employed" and p.industry not in INDUSTRIES],
    )
    add(
        "error",
        "state_out_of_range",
        "存在 [0,1] 之外的状态变量",
        [
            p.id
            for p in people
            if any(not (0.0 <= float(p.state.get(key, -1)) <= 1.0) for key in STATE_VAR_KEYS)
        ],
    )
    add(
        "error",
        "missing_state_key",
        "状态变量不完整",
        [p.id for p in people if any(key not in p.state for key in STATE_VAR_KEYS)],
    )

    duplicate_ids = [pid for pid, count in Counter(p.id for p in people).items() if count > 1]
    if duplicate_ids:
        findings.append(_finding("error", "duplicate_id", "agent id 重复", duplicate_ids))
    duplicate_names = [name for name, count in Counter(p.name for p in people).items() if count > 1]
    if duplicate_names:
        findings.append(
            Finding(
                "warning",
                "duplicate_name",
                "存在重名（模拟可运行，但访谈/日志会难以分辨）",
                count=len(duplicate_names),
            )
        )

    # Household coherence.
    assigned = [pid for record in households for pid in record.member_ids]
    if len(assigned) != len(people) or len(set(assigned)) != len(people):
        findings.append(
            Finding(
                "error",
                "household_coverage",
                f"家庭分配不完整：{len(set(assigned))} 人被分配，共 {len(people)} 人",
                count=abs(len(people) - len(set(assigned))),
            )
        )

    lone_children: list[int] = []
    impossible_parents: list[int] = []
    for record in households:
        members = [by_id[i] for i in record.member_ids if i in by_id]
        children = [m for m in members if m.age <= CHILD_MAX_AGE]
        adults = [m for m in members if m.age > CHILD_MAX_AGE]
        if children and not adults:
            lone_children.extend(m.id for m in children)
        for child in children:
            if adults and max(a.age for a in adults) - child.age < 15:
                impossible_parents.append(child.id)
    add("error", "child_without_adult", "家庭中有未成年人但没有成年人", lone_children)
    add(
        "warning",
        "implausible_parent_age",
        "家庭中最年长的成年人与子女年龄差不足 15 岁",
        impossible_parents,
    )

    # Residence must remain parseable by the map layer ("区·板块").
    add(
        "error",
        "unparseable_residence",
        "residence 不符合「区·板块」格式，会导致 init_agent_locations 退化",
        [p.id for p in people if "·" not in p.residence],
    )

    # Network health.
    isolated = [pid for pid, peers in neighbours.items() if not peers]
    if len(isolated) > max(1, int(0.05 * len(people))):
        findings.append(_finding("warning", "many_isolated_nodes", "社交网络孤立节点超过 5%", isolated))
    metrics = graph_metrics(neighbours)
    if metrics["largest_component_share"] < 0.90:
        findings.append(
            Finding(
                "warning",
                "fragmented_network",
                f"最大连通分量只覆盖 {metrics['largest_component_share']:.0%} 的人口",
            )
        )

    over_cap = [p.id for p in people if len(p.relationships) > spec.social_network.dunbar_weak_cap]
    add("error", "dunbar_cap_exceeded", "关系数超过 Dunbar 上限（enforce_dunbar 未生效）", over_cap)

    return findings


def has_errors(findings: list[Finding]) -> bool:
    return any(f.level == "error" for f in findings)


# ---------------------------------------------------------------------------
# Review charts + target-vs-achieved
# ---------------------------------------------------------------------------


def gini(values: list[float]) -> float:
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    total = sum(ordered)
    if n == 0 or total <= 0:
        return 0.0
    return (2.0 * sum((i + 1) * v for i, v in enumerate(ordered))) / (n * total) - (n + 1) / n


def lorenz_curve(values: list[float], points: int = 21) -> list[dict[str, float]]:
    ordered = sorted(float(v) for v in values if v > 0)
    if not ordered:
        return []
    cumulative = np.cumsum(ordered)
    cumulative = cumulative / cumulative[-1]
    curve = []
    for i in range(points):
        share = i / (points - 1)
        index = min(len(ordered) - 1, round(share * len(ordered)) - 1)
        curve.append(
            {
                "population_share": round(share, 4),
                "income_share": round(float(cumulative[index]) if index >= 0 else 0.0, 4),
            }
        )
    return curve


def age_pyramid(people: list[Person], bin_width: int = 5) -> list[dict[str, Any]]:
    bins: dict[int, dict[str, int]] = {}
    for person in people:
        key = (person.age // bin_width) * bin_width
        bucket = bins.setdefault(key, {"男": 0, "女": 0})
        bucket[person.gender] = bucket.get(person.gender, 0) + 1
    return [
        {"age_from": key, "age_to": key + bin_width - 1, "male": value["男"], "female": value["女"]}
        for key, value in sorted(bins.items())
    ]


def _delta(target: float, achieved: float) -> dict[str, float]:
    return {
        "target": round(float(target), 4),
        "achieved": round(float(achieved), 4),
        "delta": round(float(achieved) - float(target), 4),
    }


def build_report(
    spec: PopulationSpec,
    people: list[Person],
    households: list[HouseholdRecord],
    workplaces: list[WorkplaceRecord],
    neighbours: dict[int, list[int]],
    fit_report: dict[str, Any],
) -> dict[str, Any]:
    """Everything the review step of the panel needs, as plain JSON."""
    size = len(people)
    ages = [p.age for p in people]
    adults = [p for p in people if p.age > CHILD_MAX_AGE]
    working_age = [p for p in people if CHILD_MAX_AGE < p.age < ELDER_MIN_AGE]
    employed = [p for p in people if p.employment == "employed"]
    employed_income = [p.income_monthly for p in employed]

    achieved = {
        "median_age": _delta(spec.demography.median_age, statistics.median(ages) if ages else 0),
        "share_under_18": _delta(
            spec.demography.share_under_18, sum(a <= CHILD_MAX_AGE for a in ages) / max(size, 1)
        ),
        "share_over_65": _delta(
            spec.demography.share_over_65, sum(a >= ELDER_MIN_AGE for a in ages) / max(size, 1)
        ),
        "migrant_share": _delta(
            spec.demography.migrant_share,
            sum(1 for p in people if p.hukou != "本地") / max(size, 1),
        ),
        "employment_rate": _delta(
            spec.education_work.employment_rate,
            sum(1 for p in working_age if p.employment == "employed") / max(len(working_age), 1),
        ),
        "tertiary_rate": _delta(
            spec.education_work.tertiary_rate,
            sum(1 for p in adults if p.education in TERTIARY_LEVELS) / max(len(adults), 1),
        ),
        "income_median": _delta(
            spec.income.median_monthly,
            statistics.median(employed_income) if employed_income else 0.0,
        ),
        "income_gini": _delta(spec.income.gini, gini(employed_income)),
        "household_mean_size": _delta(spec.household.mean_size, size / max(len(households), 1)),
        "share_single_person": _delta(
            spec.household.share_single_person,
            sum(1 for h in households if h.type == "single") / max(len(households), 1),
        ),
        "share_multigen": _delta(
            spec.household.share_multigen,
            sum(1 for h in households if h.type == "multigen") / max(len(households), 1),
        ),
        "share_shared_rental": _delta(
            spec.household.share_shared_rental,
            sum(1 for h in households if h.type == "shared_rental") / max(len(households), 1),
        ),
        "mean_degree": _delta(
            spec.social_network.mean_degree,
            sum(len(v) for v in neighbours.values()) / max(size, 1),
        ),
    }

    industry_counts = Counter(p.industry for p in employed)
    achieved_industry = {
        name: _delta(
            spec.education_work.industry_mix[name], industry_counts.get(name, 0) / max(len(employed), 1)
        )
        for name in INDUSTRIES
    }

    state_summary = {}
    for key in STATE_VAR_KEYS:
        values = np.array([p.state[key] for p in people], dtype=float)
        state_summary[key] = {
            "target_mean": round(spec.psychology.state_means[key], 4),
            "mean": round(float(values.mean()), 4),
            "sd": round(float(values.std()), 4),
            "p10": round(float(np.percentile(values, 10)), 4),
            "p25": round(float(np.percentile(values, 25)), 4),
            "p50": round(float(np.percentile(values, 50)), 4),
            "p75": round(float(np.percentile(values, 75)), 4),
            "p90": round(float(np.percentile(values, 90)), 4),
        }

    return {
        "size": size,
        "achieved": achieved,
        "achieved_industry_mix": achieved_industry,
        "fit": fit_report,
        "charts": {
            "age_pyramid": age_pyramid(people),
            "lorenz": lorenz_curve(employed_income),
            "household_sizes": [
                {"size": key, "count": value}
                for key, value in sorted(Counter(len(h.member_ids) for h in households).items())
            ],
            "household_types": dict(Counter(h.type for h in households)),
            "education": {
                level: sum(1 for p in people if p.education == level) for level in EDUCATION_LEVELS
            },
            "age_bands": {
                band: sum(1 for p in people if AGE_BAND_RANGES[band][0] <= p.age <= AGE_BAND_RANGES[band][1])
                for band in AGE_BANDS
            },
            "state_distribution": state_summary,
        },
        "network": graph_metrics(neighbours),
        "workplaces": {
            "count": len(workplaces),
            "size_histogram": [
                {"size": key, "count": value}
                for key, value in sorted(Counter(len(w.member_ids) for w in workplaces).items())
            ],
        },
    }


def worst_gaps(report: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """The knobs that had to give, largest relative miss first.

    This is what turns "your population is ready" into "your population is
    ready, but employment landed at 62% rather than 68% because the age
    structure caps it" — the difference between a panel a researcher can trust
    and one they cannot.
    """
    rows = []
    for name, entry in report.get("achieved", {}).items():
        target = float(entry["target"])
        if abs(target) < 1e-9:
            continue
        rows.append(
            {
                "knob": name,
                "target": entry["target"],
                "achieved": entry["achieved"],
                "relative_error": round(abs(entry["delta"]) / abs(target), 4),
            }
        )
    rows.sort(key=lambda row: -row["relative_error"])
    return rows[:limit]


__all__ = [
    "Finding",
    "age_pyramid",
    "build_report",
    "gini",
    "has_errors",
    "lorenz_curve",
    "validate_population",
    "worst_gaps",
]
