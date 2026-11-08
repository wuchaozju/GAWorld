"""Versioned, evidence-bound result cards. No model calls and no global bias score."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from scipy.stats import t

VERSION = 1
DIMENSIONS = {
    "sampling": "重复回答与随机波动",
    "order": "选项顺序",
    "wording": "问法",
    "identity": "身份与情境",
    "interaction": "互动与记忆",
    "model": "模型与评分",
    "human": "真人参照",
    "quality": "缺失与失败",
    "mechanism": "机制与参数",
}
STATUS = {
    "untested": "未检验",
    "insufficient": "证据不足",
    "detected": "检出方向性差异",
    "stable": "在预设容许范围内稳定",
    "not_applicable": "不适用",
    "observed": "描述性记录",
}
SCOPE = "仅适用于记录的样本、模型和条件；未检验不等于无偏，一致性不等于现实有效性。"


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def check(key: str, status: str = "untested", detail: str = "尚无相应对照证据", **evidence: Any) -> dict:
    return {"id": key, "label": DIMENSIONS[key], "status": status, "detail": detail, "evidence": evidence}


def card(ref: str, checks: list[dict] = (), *, source: Any = None) -> dict:
    supplied = {c["id"]: c for c in checks}
    rows = [supplied.get(key) or check(key) for key in DIMENSIONS]
    return {
        "version": VERSION,
        "ref": ref,
        "scope": SCOPE,
        "checks": rows,
        "source_hash": fingerprint(source if source is not None else rows),
    }


def interval_check(
    key: str,
    difference: float,
    components: list[tuple[float, int]],
    margin: float | None = None,
    *,
    family: int = 1,
) -> dict:
    """Bonferroni simultaneous 95% Welch-t intervals, conservative equivalence.

    Each component is (variance of a mean, independent sample size). Model
    sampling intervals describe the simulator only, never uncertainty about people.
    """
    evidence = {
        "difference": difference,
        "margin": margin,
        "family_size": family,
        "method": "Bonferroni 95% Welch-t interval",
        "components": components,
    }
    if (
        not math.isfinite(difference)
        or not components
        or any(n < 2 or v < 0 or not math.isfinite(v) for v, n in components)
    ):
        return check(key, "insufficient", "缺少可用的独立样本量或方差信息", **evidence)
    variance = sum(v for v, _ in components)
    if variance <= 0:
        return check(key, "insufficient", "观测方差为零，无法据此建立可靠的抽样区间", **evidence)
    df = variance**2 / sum(v**2 / (n - 1) for v, n in components)
    half = float(t.ppf(1 - 0.025 / max(1, family), df)) * math.sqrt(variance)
    low, high = difference - half, difference + half
    evidence.update(ci=[low, high], degrees_of_freedom=df)
    if margin is not None and math.isfinite(margin) and margin > 0 and -margin < low and high < margin:
        return check(key, "stable", "校正后区间完全位于预先指定的容许误差内；仅对本项比较成立", **evidence)
    if low > 0 or high < 0:
        return check(key, "detected", "校正后区间不含零；大小和实际意义仍须结合容许误差判断", **evidence)
    return check(key, "insufficient", "区间未排除零，也未支持预设范围内等价；不能解释成无偏", **evidence)


def markdown(value: dict | None) -> str:
    value = value or card("历史结果")

    def esc(text):
        return str(text).replace("|", "\\|").replace("\n", " ")

    lines = [
        f"\n**偏向性与适用范围 · {esc(value.get('ref', ''))}**",
        "",
        value["scope"],
        "",
        "| 检查 | 状态 | 依据 |",
        "|---|---|---|",
    ]
    for row in value["checks"]:
        details = row["detail"]
        if row.get("evidence"):
            details += "；" + json.dumps(row["evidence"], ensure_ascii=False, default=str)
        lines.append(f"| {esc(row['label'])} | {STATUS[row['status']]} | {esc(details)} |")
    return "\n".join(lines)


def hypothesis_card(row: dict, source: Any = None) -> dict:
    return card(
        row["id"],
        [
            check(
                "mechanism",
                "observed",
                row.get("measure_basis") or "机制来源未记录",
                grade=row.get("measure_grade"),
                direction_only=row.get("direction_only"),
                seeds=row.get("seeds_with_data"),
                note="种子一致与指标来源等级不能代替参数敏感性检验",
            )
        ],
        source=source or row,
    )
