"""Parsing and estimands for the demand-estimation prompt experiment.

Three statistics carry the argument:

``demand curve``
    Purchase probability by relative price, averaged per product first
    and then across products, so a cheap product does not get 40× the
    weight of an expensive one. Humans slope down; Gui & Toubia (2025)
    find GPT under a blinded prompt produces an inverted U.

``confounding slope``
    For each elicited variable, the slope of its *relative value*
    against the relative price. Under a valid experiment the treatment
    cannot move a pre-treatment variable, so the correct answer is zero.
    Anything visibly positive is the paper's Figure 1 failure.

``fidelity``
    Agent arms only: how far the elicited value sits from what the world
    actually recorded. A resident who misremembers what they paid is a
    different failure from one whose memory drifts with the price tag,
    and the two need separate numbers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PURCHASE_YES = ("购买", "会买", "买", "purchase", "yes")
_PURCHASE_NO = ("不购买", "不会买", "不买", "not purchase", "no")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def parse_purchase(raw: str) -> bool | None:
    """Map a free-text answer to a purchase decision.

    Checks the negative forms first: ``"不购买"`` contains ``"购买"``, so
    the order is load-bearing.
    """
    text = str(raw or "").strip().lower()
    if not text:
        return None
    for token in _PURCHASE_NO:
        if token in text:
            return False
    for token in _PURCHASE_YES:
        if token in text:
            return True
    return None


def parse_elicit(raw: str, fields: tuple[str, ...]) -> dict[str, float] | None:
    """Pull the requested numbers out of a comma-separated answer."""
    numbers = _NUMBER.findall(str(raw or ""))
    if len(numbers) < len(fields):
        return None
    return {name: float(value) for name, value in zip(fields, numbers[: len(fields)])}


def load_results(path: str | Path, *, dedupe: bool = True) -> list[dict]:
    """Read a results log.

    ``dedupe`` keeps the first row per cell key. Two runs pointed at the
    same output directory — or a resume racing a run that had not yet
    exited — append a second answer for cells that already had one, and
    silently double-weighting those cells would bias whichever arm was
    in flight at the time.
    """
    rows: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not dedupe:
        return rows

    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = row.get("key")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(row)
    return unique


# ---------------------------------------------------------------------
# Small stats helpers. Kept in plain Python so the analysis is testable
# without a numeric stack and readable without one either.
# ---------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def ols_slope(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of y on x."""
    if len(points) < 2:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x, mean_y = _mean(xs), _mean(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator


def pearson(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x, mean_y = _mean(xs), _mean(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in points)
    return covariance / (var_x**0.5 * var_y**0.5)


def _by_product_then_price(
    rows: list[dict], value_of
) -> list[tuple[float, float, int]]:
    """Average within product first, then across products, per price level.

    Two-stage aggregation keeps a product with many usable answers from
    dominating the curve.
    """
    buckets: dict[tuple[int, float], list[float]] = {}
    for row in rows:
        value = value_of(row)
        if value is None:
            continue
        buckets.setdefault((row["product_id"], row["relative_price"]), []).append(float(value))

    per_price: dict[float, list[float]] = {}
    counts: dict[float, int] = {}
    for (_, relative_price), values in buckets.items():
        per_price.setdefault(relative_price, []).append(_mean(values))
        counts[relative_price] = counts.get(relative_price, 0) + len(values)
    return [(price, _mean(per_price[price]), counts[price]) for price in sorted(per_price)]


def demand_curve(rows: list[dict]) -> list[tuple[float, float, int]]:
    """``[(relative_price, purchase_probability, n)]``."""
    purchase_rows = [row for row in rows if row.get("question") == "purchase"]
    return _by_product_then_price(
        purchase_rows,
        lambda row: None if row.get("purchase") is None else float(bool(row["purchase"])),
    )


def elicited_curve(rows: list[dict], field: str) -> list[tuple[float, float, int]]:
    """Relative value of an elicited variable, by relative price.

    Each product's elicited values are divided by that product's own mean
    across the price grid and centred at zero, which is what makes 40
    products with different absolute scales aggregable (paper Figure 1).
    """
    elicit_rows = [
        row
        for row in rows
        if row.get("question") == "elicit" and isinstance(row.get("elicited"), dict)
        and field in row["elicited"]
    ]
    if not elicit_rows:
        return []

    per_product: dict[int, list[float]] = {}
    for row in elicit_rows:
        per_product.setdefault(row["product_id"], []).append(float(row["elicited"][field]))
    baselines = {pid: _mean(values) for pid, values in per_product.items()}

    def relative_value(row: dict) -> float | None:
        baseline = baselines.get(row["product_id"])
        if not baseline:
            return None
        return float(row["elicited"][field]) / baseline - 1.0

    return _by_product_then_price(elicit_rows, relative_value)


def confounding(rows: list[dict], field: str) -> dict:
    """Slope and correlation of an elicited variable against the treatment."""
    curve = elicited_curve(rows, field)
    points = [(price, value) for price, value, _ in curve]
    return {
        "field": field,
        "curve": [{"relative_price": p, "relative_value": round(v, 4), "n": n} for p, v, n in curve],
        "slope": ols_slope(points),
        "r": pearson(points),
        "n_points": len(points),
    }


def fidelity(rows: list[dict], field: str, world_key: str) -> dict | None:
    """Mean absolute relative gap between an elicited value and the world's.

    Only defined for grounded arms, which are the only ones that have a
    recorded truth to be wrong about.
    """
    gaps = []
    for row in rows:
        world = row.get("world")
        elicited = row.get("elicited")
        if not isinstance(world, dict) or not isinstance(elicited, dict):
            continue
        truth = world.get(world_key)
        guess = elicited.get(field)
        if not truth or guess is None:
            continue
        gaps.append(abs(float(guess) - float(truth)) / float(truth))
    if not gaps:
        return None
    return {"field": field, "mean_abs_relative_error": round(_mean(gaps), 4), "n": len(gaps)}


def transition_width(curve: list[tuple[float, float, int]]) -> float | None:
    """How much price it takes demand to fall from saturated to collapsed.

    Distance from the last point at or above 0.95 to the first point at
    or below 0.05 *after* it. One grid step is a step function; several
    is a ramp. ``None`` when the curve never reaches one of the two ends,
    because then there is no transition on the observed range.

    A property of the demand curve alone, so it is defined for every arm
    — including the ones that were never told a competitor price.
    """
    saturated = [price for price, probability, _ in curve if probability >= 0.95]
    collapsed = [price for price, probability, _ in curve if probability <= 0.05]
    if not saturated or not collapsed:
        return None
    after = [price for price in collapsed if price > max(saturated)]
    return round(min(after) - max(saturated), 4) if after else None


def focalism(rows: list[dict]) -> dict | None:
    """Has the simulated customer collapsed into "buy iff price <= competitor"?

    This is the cost side of the paper's trade-off (Figure 4): controlling
    a covariate by naming it in the prompt makes it artificially salient,
    and the decision degenerates into a step function on that one
    comparison. Two readings, because neither alone is conclusive:

    ``step_rule_agreement``
        Share of answers matching the degenerate rule. A real consumer
        agrees with it often — cheap things do get bought — so this is
        only interpretable *relative to another arm*, never against an
        absolute threshold.

    ``transition_width``
        Relative-price distance from the last point where demand is still
        saturated (>= 0.95) to the first point where it has collapsed
        (<= 0.05). A step function crosses in one grid step;
        heterogeneous consumers take several. ``None`` when the curve
        never reaches one of the two ends, since then there is no ramp to
        measure. This is the discriminating statistic of the two.

        Deliberately *not* "the span of all points strictly between 0.05
        and 0.95": an occasional refusal at a very low price is not part
        of the transition, and letting it in inflates the width of
        exactly the arm this analysis is trying to scrutinise.

    Defined only for arms that were given a competitor price; ``None``
    otherwise, since there is no rule to agree with.
    """
    decisions = [
        row
        for row in rows
        if row.get("question") == "purchase"
        and row.get("purchase") is not None
        and isinstance(row.get("world"), dict)
        and row["world"].get("competitor_price")
    ]
    if not decisions:
        return None

    agreements = [
        bool(row["purchase"]) == (float(row["price"]) <= float(row["world"]["competitor_price"]))
        for row in decisions
    ]
    return {
        "step_rule_agreement": round(_mean([float(item) for item in agreements]), 4),
        "transition_width": transition_width(demand_curve(rows)),
        "n": len(decisions),
    }


def shape(curve: list[tuple[float, float, int]], *, drop_free: bool = True) -> dict:
    """Is the demand curve downward sloping, or is it the paper's inverted U?"""
    points = [(p, v) for p, v, _ in curve if not (drop_free and p == 0.0)]
    if len(points) < 3:
        return {"monotone_share": None, "peak_relative_price": None, "inverted_u": None}
    steps = [points[i + 1][1] - points[i][1] for i in range(len(points) - 1)]
    decreasing = sum(1 for step in steps if step <= 0) / len(steps)
    peak = max(points, key=lambda item: item[1])[0]
    return {
        "monotone_share": round(decreasing, 4),
        "peak_relative_price": peak,
        # A peak away from the cheapest price is the signature the paper
        # reports: demand rising with price over the bottom of the range.
        "inverted_u": peak > points[0][0],
    }


def summarize(rows: list[dict], *, elicit_fields: tuple[str, ...] = ()) -> dict:
    """Per-arm summary of every estimand the run supports."""
    arms = sorted({row.get("arm", "") for row in rows if row.get("arm")})
    world_keys = {
        "last_price": "last_paid",
        "competitor_price": "competitor_price",
        "shelf_life_days": "shelf_life_days",
    }

    summary: dict = {"arms": {}, "n_rows": len(rows)}
    for arm in arms:
        arm_rows = [row for row in rows if row.get("arm") == arm]
        purchase_rows = [row for row in arm_rows if row.get("question") == "purchase"]
        elicit_rows = [row for row in arm_rows if row.get("question") == "elicit"]
        curve = demand_curve(arm_rows)

        entry: dict = {
            "n_calls": len(arm_rows),
            "n_errors": sum(1 for row in arm_rows if "error" in row),
            "demand_curve": [
                {"relative_price": p, "purchase_probability": round(v, 4), "n": n} for p, v, n in curve
            ],
            "shape": shape(curve),
            "parse_failure_rate": {
                "purchase": round(
                    sum(1 for row in purchase_rows if row.get("purchase") is None)
                    / max(1, len(purchase_rows)),
                    4,
                ),
                "elicit": round(
                    sum(1 for row in elicit_rows if not isinstance(row.get("elicited"), dict))
                    / max(1, len(elicit_rows)),
                    4,
                ),
            },
        }
        entry["focalism"] = focalism(arm_rows)
        entry["transition_width"] = transition_width(curve)
        if elicit_rows:
            entry["confounding"] = [confounding(arm_rows, field) for field in elicit_fields]
            checks = [fidelity(arm_rows, field, world_keys[field]) for field in elicit_fields
                      if field in world_keys]
            entry["fidelity"] = [item for item in checks if item]
        summary["arms"][arm] = entry
    return summary


def render_markdown(summary: dict) -> str:
    """Human-readable report; the JSON stays the machine-readable one."""
    lines = ["# 需求估计提示词实验报告", "", f"总调用数：{summary.get('n_rows', 0)}", ""]

    lines += ["## 需求曲线（各 arm 的购买概率）", ""]
    arms = list(summary.get("arms", {}))
    prices = sorted(
        {
            point["relative_price"]
            for arm in arms
            for point in summary["arms"][arm]["demand_curve"]
        }
    )
    if prices:
        lines.append("| 相对价格 | " + " | ".join(arms) + " |")
        lines.append("|---" * (len(arms) + 1) + "|")
        for price in prices:
            cells = []
            for arm in arms:
                match = next(
                    (
                        point
                        for point in summary["arms"][arm]["demand_curve"]
                        if point["relative_price"] == price
                    ),
                    None,
                )
                cells.append(f"{match['purchase_probability']:.3f}" if match else "—")
            lines.append(f"| {price:.0%} | " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## 形状检验", "", "| arm | 单调下降占比 | 峰值相对价格 | 倒 U |", "|---|---|---|---|"]
    for arm in arms:
        entry = summary["arms"][arm]["shape"]
        monotone = "—" if entry["monotone_share"] is None else f"{entry['monotone_share']:.2f}"
        peak = "—" if entry["peak_relative_price"] is None else f"{entry['peak_relative_price']:.0%}"
        lines.append(f"| {arm} | {monotone} | {peak} | {entry['inverted_u']} |")
    lines.append("")

    lines += [
        "## 混淆诊断（协变量对处理价格的斜率，正确答案是 0）",
        "",
        "| arm | 变量 | 斜率 | 相关系数 |",
        "|---|---|---|---|",
    ]
    for arm in arms:
        for item in summary["arms"][arm].get("confounding", []):
            slope = "—" if item["slope"] is None else f"{item['slope']:+.4f}"
            correlation = "—" if item["r"] is None else f"{item['r']:+.3f}"
            lines.append(f"| {arm} | {item['field']} | {slope} | {correlation} |")
    lines.append("")

    focalism_rows = [(arm, summary["arms"][arm]["focalism"]) for arm in arms
                     if summary["arms"][arm].get("focalism")]
    if focalism_rows:
        lines += [
            "## 生态效度（阶跃退化检验，仅供给了竞品价的 arm）",
            "",
            "| arm | 阶跃规则符合率 | 过渡带宽度 | n |",
            "|---|---|---|---|",
        ]
        for arm, item in focalism_rows:
            width = "—" if item["transition_width"] is None else f"{item['transition_width']:.2f}"
            lines.append(
                f"| {arm} | {item['step_rule_agreement']:.3f} | {width} | {item['n']} |"
            )
        lines += ["", "> 过渡带宽度 = 从最后一个饱和点(≥0.95)到第一个坍缩点(≤0.05)的相对价格距离。一个网格步长(0.20)= 论文 Figure 4 的阶跃退化；“—”表示曲线没有跨完整个过渡。", ""]

    fidelity_rows = [
        (arm, item)
        for arm in arms
        for item in summary["arms"][arm].get("fidelity", [])
    ]
    if fidelity_rows:
        lines += ["## 世界一致性（仅 agent arm：自述值与世界记录的偏差）", "",
                  "| arm | 变量 | 平均相对误差 | n |", "|---|---|---|---|"]
        for arm, item in fidelity_rows:
            lines.append(
                f"| {arm} | {item['field']} | {item['mean_abs_relative_error']:.3f} | {item['n']} |"
            )
        lines.append("")

    lines += ["## 解析失败率", "", "| arm | purchase | elicit |", "|---|---|---|"]
    for arm in arms:
        rates = summary["arms"][arm]["parse_failure_rate"]
        lines.append(f"| {arm} | {rates['purchase']:.3f} | {rates['elicit']:.3f} |")
    return "\n".join(lines) + "\n"
