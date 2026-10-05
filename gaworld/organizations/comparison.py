"""Descriptive comparisons of two completed cumulative metric exports."""

from __future__ import annotations

import math
from typing import Any

SCOPE = "cumulative_current_generation"
DIMENSIONS = ("age_band", "gender", "employment")
COUNTS = (
    "applications",
    "eligible_applications",
    "coverage_numerator",
    "coverage_denominator",
    "aid_paid_cents",
    "balance_cents",
    "arrears_cents",
    "budget_utilization_denominator_cents",
    "vacancies",
    "occupied",
    "hires",
    "rejections",
    "wage_owed_cents",
    "wage_paid_cents",
    "waiting_days_sum",
    "waiting_days_denominator",
)
GROUP_COUNTS = (
    "applications",
    "eligible_applications",
    "aid_paid_cents",
    "paid_aid_applications",
    "hires",
    "rejections",
    "waiting_days_sum",
)
DEFINITIONS = {
    "scope": "截至相同完成日的本世代累计快照；不将逐日累计快照相加。",
    "direction": "差值 = 右侧减左侧；单次描述性差异不构成因果效应或显著性检验。",
    "coverage": "社区：实付资助申请数/已决策合格申请数；企业：录用数/已决策合格应聘数。",
    "waiting": "已决策申请的等待天数总和/已决策申请数；零分母为null。",
    "budget_utilization": "实际支出/显式拨款；使用导出比例及拨款分母，不从比例倒推分币支出。",
    "groups": "按决策前冻结信息分组，按申请计数；同一人跨日申请可重复计数，未知值保留。",
    "rule_history": "规则标签是当前规则；版本大于1时，累计结果可能包含较早规则的决策。",
    "comparability": "同日、同组织不等于同人口、初始预算或相同输入；这些实验条件须由研究者核验。",
}


class ComparisonError(ValueError):
    """The exports do not support the requested comparison."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ComparisonError(f"{name} must be a nonempty string of at most 200 characters")
    return value


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ComparisonError(f"{name} must be a nonnegative integer")
    return value


def _ratio(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    try:
        result = numerator / denominator
    except OverflowError as exc:
        raise ComparisonError("ratio exceeds the supported numeric range") from exc
    if not math.isfinite(result):
        raise ComparisonError("ratio must be finite")
    return result


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _validate_rate(value: Any, expected: float | None, name: str) -> None:
    if expected is None:
        if value is not None:
            raise ComparisonError(f"{name} must be null for a zero denominator")
    elif not _finite_number(value) or not math.isclose(value, expected, abs_tol=1e-9):
        raise ComparisonError(f"{name} does not agree with its numerator and denominator")


def _groups(row: dict[str, Any]) -> None:
    groups = row.get("groups")
    if not isinstance(groups, dict):
        raise ComparisonError("groups must be an object")
    covered = "paid_aid_applications" if row["kind"] == "community" else "hires"
    for dimension in DIMENSIONS:
        distribution = groups.get(dimension)
        if not isinstance(distribution, dict) or "unknown" not in distribution:
            raise ComparisonError(f"missing {dimension} distribution or unknown group")
        for label, group in distribution.items():
            _text(label, "group label")
            if not isinstance(group, dict):
                raise ComparisonError("group record must be an object")
            for field in GROUP_COUNTS:
                _integer(group.get(field), f"{dimension}.{label}.{field}")
            if (
                group["eligible_applications"] > group["applications"]
                or group["rejections"] > group["applications"]
                or max(group["hires"], group["paid_aid_applications"]) > group["eligible_applications"]
            ):
                raise ComparisonError("group counts exceed their application denominator")
            if group[covered] + group["rejections"] != group["applications"]:
                raise ComparisonError("group outcomes do not partition decided applications")
        for field in (
            "applications",
            "eligible_applications",
            "aid_paid_cents",
            "hires",
            "rejections",
            "waiting_days_sum",
        ):
            if sum(group[field] for group in distribution.values()) != row[field]:
                raise ComparisonError(f"{dimension} group totals disagree with {field}")
        if sum(group[covered] for group in distribution.values()) != row["coverage_numerator"]:
            raise ComparisonError("group coverage totals disagree with organization coverage")


def _validate(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("scope") != SCOPE:
        raise ComparisonError(f"export scope must be {SCOPE}")
    generation = _text(payload.get("generation_id"), "generation_id")
    day = _integer(payload.get("day"), "day")
    if not day:
        raise ComparisonError("a completed day must be positive")
    rows = payload.get("organizations")
    if not isinstance(rows, list) or not rows:
        raise ComparisonError("export must contain organizations")
    organizations = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ComparisonError("organization record must be an object")
        oid = _text(row.get("organization_id"), "organization_id")
        if oid in organizations:
            raise ComparisonError(f"duplicate organization: {oid}")
        if row.get("generation_id") != generation or row.get("day") != day:
            raise ComparisonError("organization day/generation disagrees with export")
        if row.get("kind") not in {"community", "company"}:
            raise ComparisonError("unsupported organization kind")
        _text(row.get("rule"), "rule")
        if not _integer(row.get("rule_version"), "rule_version"):
            raise ComparisonError("rule_version must be positive")
        for field in COUNTS:
            _integer(row.get(field), field)
        if (
            row["eligible_applications"] > row["applications"]
            or row["coverage_denominator"] != row["eligible_applications"]
            or row["coverage_numerator"] > row["coverage_denominator"]
            or row["waiting_days_denominator"] != row["applications"]
            or row["rejections"] > row["applications"]
            or row["occupied"] > row["vacancies"]
            or row["wage_paid_cents"] > row["wage_owed_cents"]
        ):
            raise ComparisonError("organization counts/amounts disagree with their denominators")
        if row["coverage_numerator"] + row["rejections"] != row["applications"]:
            raise ComparisonError("organization outcomes do not partition decided applications")
        if row["arrears_cents"] != row["wage_owed_cents"] - row["wage_paid_cents"]:
            raise ComparisonError("arrears disagree with unpaid labor obligations")
        _validate_rate(
            row.get("coverage"), _ratio(row["coverage_numerator"], row["coverage_denominator"]), "coverage"
        )
        utilization = row.get("budget_utilization")
        if not row["budget_utilization_denominator_cents"]:
            _validate_rate(utilization, None, "budget_utilization")
        elif not _finite_number(utilization) or not 0 <= utilization <= 1:
            raise ComparisonError("budget_utilization must be a finite ratio between 0 and 1")
        reasons = row.get("rejection_reasons")
        if not isinstance(reasons, dict):
            raise ComparisonError("rejection_reasons must be an object")
        for reason, count in reasons.items():
            _text(reason, "rejection reason")
            _integer(count, "rejection count")
        if sum(reasons.values()) != row["rejections"]:
            raise ComparisonError("rejection reason counts disagree with total rejections")
        _groups(row)
        organizations[oid] = row
    return organizations


def _row(
    metric: str, left: int | float | None, right: int | float | None, unit: str | None = None
) -> dict[str, Any]:
    return {
        "metric": metric,
        "unit": unit
        or ("cents" if metric.endswith("_cents") else "days" if metric == "waiting_days_sum" else "count"),
        "left": left,
        "right": right,
        "difference": right - left if left is not None and right is not None else None,
    }


def _metrics(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    result = [_row(field, left[field], right[field]) for field in COUNTS]
    result.append(
        _row(
            "coverage",
            _ratio(left["coverage_numerator"], left["coverage_denominator"]),
            _ratio(right["coverage_numerator"], right["coverage_denominator"]),
            "ratio",
        )
    )
    result.append(
        _row("budget_utilization", left["budget_utilization"], right["budget_utilization"], "ratio")
    )
    result.append(
        _row(
            "mean_waiting_days",
            _ratio(left["waiting_days_sum"], left["waiting_days_denominator"]),
            _ratio(right["waiting_days_sum"], right["waiting_days_denominator"]),
            "days",
        )
    )
    return result


def _group_rows(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    covered = "paid_aid_applications" if left["kind"] == "community" else "hires"
    for dimension in DIMENSIONS:
        a, b = left["groups"][dimension], right["groups"][dimension]
        for label in sorted(a.keys() | b.keys()):
            empty = dict.fromkeys(GROUP_COUNTS, 0)
            x, y = a.get(label, empty), b.get(label, empty)
            rows = [_row(field, x[field], y[field]) for field in GROUP_COUNTS]
            rows.extend(
                [
                    _row("coverage_numerator", x[covered], y[covered]),
                    _row("coverage_denominator", x["eligible_applications"], y["eligible_applications"]),
                    _row(
                        "coverage",
                        _ratio(x[covered], x["eligible_applications"]),
                        _ratio(y[covered], y["eligible_applications"]),
                        "ratio",
                    ),
                    _row(
                        "mean_waiting_days",
                        _ratio(x["waiting_days_sum"], x["applications"]),
                        _ratio(y["waiting_days_sum"], y["applications"]),
                        "days",
                    ),
                ]
            )
            result.extend(dict(row, dimension=dimension, group=label) for row in rows)
    return result


def compare_metrics(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    organization_id: str | None = None,
    left_label: str = "A",
    right_label: str = "B",
) -> dict[str, Any]:
    """Compare cumulative outcomes, without inferring matched residents or causality."""
    a, b = _validate(left), _validate(right)
    if left["day"] != right["day"]:
        raise ComparisonError("comparison requires the same completed day")
    if organization_id is None:
        if a.keys() != b.keys():
            raise ComparisonError("organization IDs differ; select a common organization explicitly")
        ids = sorted(a)
    else:
        if organization_id not in a or organization_id not in b:
            raise ComparisonError("selected organization must exist in both exports")
        ids = [organization_id]
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "descriptive_cumulative_snapshot_comparison",
        "direction": "right_minus_left",
        "definitions": dict(DEFINITIONS),
        "sources": {
            side: {
                "generation_id": data["generation_id"],
                "day": data["day"],
                "scope": SCOPE,
                "label": _text(label, "source label"),
            }
            for side, data, label in (("left", left, left_label), ("right", right, right_label))
        },
        "organizations": [],
    }
    for oid in ids:
        x, y = a[oid], b[oid]
        if x["kind"] != y["kind"]:
            raise ComparisonError(f"organization kind differs: {oid}")
        report["organizations"].append(
            {
                "organization_id": oid,
                "kind": x["kind"],
                "current_rules": {
                    side: {"name": row["rule"], "version": row["rule_version"]}
                    for side, row in (("left", x), ("right", y))
                },
                "metrics": _metrics(x, y),
                "groups": _group_rows(x, y),
                "rejection_reasons": [
                    _row(reason, x["rejection_reasons"].get(reason, 0), y["rejection_reasons"].get(reason, 0))
                    for reason in sorted(x["rejection_reasons"].keys() | y["rejection_reasons"].keys())
                ],
            }
        )
    return report


def compare_files(left_path: Any, right_path: Any, output_dir: Any, **options: Any) -> dict[str, str]:
    """Write local reports without opening any organization database."""
    from gaworld.organizations.comparison_report import compare_files as write_report

    return write_report(left_path, right_path, output_dir, **options)
