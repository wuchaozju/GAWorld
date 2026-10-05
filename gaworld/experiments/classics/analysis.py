"""Score a classic-paradigm run: one paired contrast per paradigm.

Per resident, the measure is averaged over draws within each condition
(and, for anchoring, the treatment − control difference is averaged over
the three items). The effect is the mean of those per-resident
differences; its interval and p-value are the same resampling the
parallel-worlds paired gate uses (:mod:`gaworld.parallel.causal`).

Verdict, direction only (grade (c)):

* ``replicated`` — the classic direction, two-sided sign-flip p < 0.05;
* ``reversed``  — the opposite direction, p < 0.05;
* ``not_replicated`` — neither;
* ``insufficient`` — fewer than :data:`MIN_PAIRS` residents answered both
  conditions readably.

Human figures are shown beside the residents' levels and never enter it.
Income and age splits are exploratory and never enter it either.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from gaworld.experiments.classics.paradigms import PARADIGMS, Paradigm
from gaworld.parallel.causal import ALPHA, RNG_SEED, bootstrap_ci, sign_flip_p

#: Fewer residents with a readable answer in both conditions than this → no verdict.
MIN_PAIRS = 10

VERDICT_LABELS = {
    "replicated": "复现",
    "not_replicated": "未复现",
    "reversed": "反向",
    "insufficient": "样本不足",
}


def load_rows(path: str | Path) -> list[dict]:
    """Successful rows, last one per key (a resumed run may have retried a cell)."""
    rows: dict[str, dict] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from an interrupted run
            if row.get("key") and "raw" in row and "error" not in row:
                rows[row["key"]] = row
    return list(rows.values())


def _paired_effect(diffs: list[float], seed_offset: int) -> dict:
    values = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(RNG_SEED + seed_offset)
    low, high, _ = bootstrap_ci(values, rng)
    return {
        "n": len(diffs),
        "effect": round(float(values.mean()), 4),
        "ci": [round(low, 4), round(high, 4)],
        "p": round(sign_flip_p(values, rng), 4),
    }


def _verdict(effect: dict) -> str:
    if effect["n"] < MIN_PAIRS:
        return "insufficient"
    if effect["p"] >= ALPHA or effect["effect"] == 0:
        return "not_replicated"
    return "replicated" if effect["effect"] > 0 else "reversed"


def _split(diffs: dict[int, float], covariate: dict[int, float]) -> dict | None:
    """Effect below / at-or-above the median of a covariate (exploratory)."""
    ids = [sid for sid in diffs if sid in covariate]
    if len(ids) < 2 * MIN_PAIRS:
        return None
    median = statistics.median(covariate[sid] for sid in ids)
    low = [diffs[sid] for sid in ids if covariate[sid] < median]
    high = [diffs[sid] for sid in ids if covariate[sid] >= median]
    if not low or not high:
        return None
    return {
        "median": round(median, 1),
        "below": {"n": len(low), "effect": round(statistics.fmean(low), 4)},
        "above": {"n": len(high), "effect": round(statistics.fmean(high), 4)},
    }


def analyze_paradigm(paradigm: Paradigm, rows: list[dict], *, seed_offset: int = 0) -> dict:
    items = {item.id: item for item in paradigm.items}
    cell_values: dict[tuple[int, str, str], list[float]] = defaultdict(list)
    levels: dict[str, list[float]] = defaultdict(list)
    covariates: dict[str, dict[int, float]] = {"monthly_income": {}, "age": {}}
    unparsed = 0
    for row in rows:
        if row.get("paradigm") != paradigm.id or row.get("item") not in items:
            continue
        if row.get("condition") not in paradigm.conditions:
            continue
        value = paradigm.parse(row["raw"], items[row["item"]], row["condition"])
        if value is None:
            unparsed += 1
            continue
        sid = int(row["subject_id"])
        cell_values[(sid, row["item"], row["condition"])].append(value)
        levels[row["condition"]].append(value)
        for key in covariates:
            if row.get(key) is not None:
                covariates[key][sid] = float(row[key])

    per_subject: dict[int, list[float]] = defaultdict(list)
    for sid in {key[0] for key in cell_values}:
        for item_id in items:
            treated = cell_values.get((sid, item_id, paradigm.treatment))
            control = cell_values.get((sid, item_id, paradigm.control))
            if treated and control:
                per_subject[sid].append(statistics.fmean(treated) - statistics.fmean(control))
    diffs = {sid: statistics.fmean(values) for sid, values in per_subject.items()}

    out: dict = {
        "id": paradigm.id,
        "name": paradigm.name,
        "claim": paradigm.claim,
        "reference": paradigm.reference,
        "measure": paradigm.measure,
        "percent": paradigm.percent,
        "conditions": {
            cond: {
                "label": paradigm.condition_labels[cond],
                "n": len(levels[cond]),
                "mean": round(statistics.fmean(levels[cond]), 4) if levels[cond] else None,
                "human": paradigm.human.get(cond, ""),
            }
            for cond in paradigm.conditions
        },
        "human_effect": paradigm.human.get("effect", ""),
        "unparsed": unparsed,
        "caveat": paradigm.caveat,
        "grade": "c",
    }
    if diffs:
        effect = _paired_effect([diffs[sid] for sid in sorted(diffs)], seed_offset)
    else:
        effect = {"n": 0, "effect": None, "ci": [None, None], "p": None}
    out["paired"] = effect
    out["verdict"] = _verdict(effect) if diffs else "insufficient"
    out["heterogeneity"] = {key: _split(diffs, values) for key, values in covariates.items()}
    if paradigm.id == "anchoring":
        out["anchoring_index"] = _anchoring_index(paradigm, cell_values)
    return out


def _anchoring_index(paradigm: Paradigm, cell_values: dict) -> dict:
    """(median estimate after the high anchor − after the low) ÷ (high − low), per item."""
    index = {}
    for item in paradigm.items:
        medians = {}
        for cond in ("low", "high"):
            estimates = [
                10**v
                for (_, item_id, c), vs in cell_values.items()
                if item_id == item.id and c == cond
                for v in vs
            ]
            medians[cond] = statistics.median(estimates) if estimates else None
        if None in medians.values():
            index[item.id] = None
            continue
        spread = item.params["high"] - item.params["low"]
        index[item.id] = round((medians["high"] - medians["low"]) / spread, 3)
    return index


def summarize(rows: list[dict], paradigm_ids: list[str] | None = None) -> dict:
    ids = [pid for pid in (paradigm_ids or list(PARADIGMS)) if any(r.get("paradigm") == pid for r in rows)]
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "subjects": len({r.get("subject_id") for r in rows}),
        "providers": dict(Counter(r.get("provider") or "未记录" for r in rows)),
        "paradigms": [analyze_paradigm(PARADIGMS[pid], rows, seed_offset=i) for i, pid in enumerate(ids)],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _level(value: float | None, percent: bool) -> str:
    if value is None:
        return "—"
    return f"{value:.0%}" if percent else f"{value:.3f}"


def _signed(value: float | None) -> str:
    return "—" if value is None else f"{value:+.3f}"


def render_markdown(summary: dict, name: str = "") -> str:
    lines = [
        f"# 经典实验库{(' · ' + name) if name else ''}",
        "",
        f"居民 {summary['subjects']} 人 · 模型 "
        + "、".join(f"{k}（{n} 次）" for k, n in summary["providers"].items())
        + f" · 生成于 {summary['generated']}",
        "",
        "> 级别 (c)：这些是扮演居民的模型怎么答，不是现实效应有多大。判定只看方向（配对符号翻转检验，p<0.05）；"
        "人类数字只作对照，收入 / 年龄分组是探索性的，都不进判定。",
    ]
    if len(summary["providers"]) > 1:
        lines.append("> ⚠️ 结果混合了多个模型，合并分析把它们当成一个总体。")
    lines += ["", "| 范式 | 预期方向 | 效应 | 95% CI | p | 人数 | 判定 |", "|---|---|---|---|---|---|---|"]
    for p in summary["paradigms"]:
        c, t = (p["conditions"][k]["label"] for k in PARADIGMS[p["id"]].conditions)
        eff = p["paired"]
        ci = "—" if eff["ci"][0] is None else f"[{eff['ci'][0]:+.3f}, {eff['ci'][1]:+.3f}]"
        lines.append(
            f"| {p['name']} | {p['measure']}：{t} > {c} | {_signed(eff['effect'])} | {ci} | "
            f"{'—' if eff['p'] is None else eff['p']} | {eff['n']} | {VERDICT_LABELS[p['verdict']]} |"
        )
    for p in summary["paradigms"]:
        lines += [
            "",
            f"## {p['name']}",
            "",
            f"经典结论：{p['claim']}（{p['reference']}）。指标：{p['measure']}。",
            "",
        ]
        for cond in p["conditions"].values():
            human = f" · 人类 {cond['human']}" if cond["human"] else ""
            lines.append(
                f"- {cond['label']}：居民 {_level(cond['mean'], p['percent'])}（{cond['n']} 条）{human}"
            )
        if p["human_effect"]:
            lines.append(f"- 人类的效应：{p['human_effect']}")
        if p.get("anchoring_index"):
            lines.append(
                "- 锚定指数："
                + "，".join(f"{item} {'—' if v is None else v}" for item, v in p["anchoring_index"].items())
            )
        eff = p["paired"]
        if eff["effect"] is not None:
            lines.append(
                f"- 配对效应 {_signed(eff['effect'])}，95% CI [{eff['ci'][0]:+.3f}, {eff['ci'][1]:+.3f}]，"
                f"p={eff['p']}（{eff['n']} 人）→ **{VERDICT_LABELS[p['verdict']]}**"
            )
        else:
            lines.append(f"- 没有人在两个条件下都给出可读的回答 → **{VERDICT_LABELS[p['verdict']]}**")
        splits = [
            (label, p["heterogeneity"].get(key))
            for key, label in (("monthly_income", "月收入"), ("age", "年龄"))
        ]
        parts = [
            f"{label}低于中位数 {s['median']:g} 的 {_signed(s['below']['effect'])}（{s['below']['n']} 人）/ "
            f"其余 {_signed(s['above']['effect'])}（{s['above']['n']} 人）"
            for label, s in splits
            if s
        ]
        if parts:
            lines.append("- 异质性（探索性）：" + "；".join(parts))
        if p["unparsed"]:
            lines.append(f"- 读不出的回答 {p['unparsed']} 条，不计入")
        lines.append(f"- 注意：{p['caveat']}")
    return "\n".join(lines) + "\n"


__all__ = ["MIN_PAIRS", "VERDICT_LABELS", "analyze_paradigm", "load_rows", "render_markdown", "summarize"]
