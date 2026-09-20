"""item -> dimension -> scorecard, plus the reliability statistics that decide
whether the scores are allowed to count at all.

Gate order matters: an item that fails the discrimination check is removed
*before* its dimension is averaged, because a rubric line the judge cannot use
to tell real from corrupted contributes noise, not signal.
"""

import statistics
from collections import defaultdict


# ───────────────────────── reliability ─────────────────────────

def krippendorff_alpha_ordinal(ratings: list[list[int | None]]) -> float | None:
    """Ordinal Krippendorff's alpha. ``ratings[i]`` = one unit's scores across
    judges, ``None`` for abstain. Returns None when there is nothing to compare.
    """
    units = [[r for r in row if r is not None] for row in ratings]
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None

    values = sorted({v for u in units for v in u})
    if len(values) < 2:
        return 1.0

    # Coincidence matrix.
    coincidence: dict[tuple[int, int], float] = defaultdict(float)
    for u in units:
        m = len(u)
        for i, a in enumerate(u):
            for j, b in enumerate(u):
                if i != j:
                    coincidence[(a, b)] += 1.0 / (m - 1)
    n_total = sum(coincidence.values())
    if n_total <= 0:
        return None
    marginals = {v: sum(coincidence[(v, k)] for k in values) for v in values}

    def delta_sq(c: int, k: int) -> float:
        lo, hi = (c, k) if c <= k else (k, c)
        span = [v for v in values if lo <= v <= hi]
        return (sum(marginals[g] for g in span)
                - (marginals[lo] + marginals[hi]) / 2.0) ** 2

    do = sum(coincidence[(c, k)] * delta_sq(c, k) for c in values for k in values)
    de = sum(marginals[c] * marginals[k] * delta_sq(c, k)
             for c in values for k in values if c != k)
    if de <= 0:
        return None
    return 1.0 - (n_total - 1) * do / de


def quadratic_weighted_kappa(a: list[int], b: list[int], k: int = 3) -> float | None:
    """QWK between two raters over categories 0..k-1."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    obs = [[0.0] * k for _ in range(k)]
    for x, y in pairs:
        obs[x][y] += 1
    n = len(pairs)
    ha = [sum(obs[i]) for i in range(k)]
    hb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) ** 2) / ((k - 1) ** 2)
            num += w * obs[i][j]
            den += w * ha[i] * hb[j] / n
    return None if den == 0 else 1.0 - num / den


# ───────────────────────── aggregation ─────────────────────────

def item_summary(results: list[dict]) -> dict:
    """Collapse all unit-level results for one item."""
    # A capability-gated item carries no real units; counting its placeholder as
    # "0/1 evaluated" reads like a failure when the item was never applicable.
    missing = sorted({c for r in results for c in (r.get("missing_capabilities") or [])})
    real = [r for r in results if not r.get("missing_capabilities")]
    scored = [r["score"] for r in real if not r.get("abstain") and r.get("score") is not None]
    n = len(real)
    return {
        "n_units": n,
        "n_scored": len(scored),
        "abstain_rate": round(1 - len(scored) / n, 3) if n else 1.0,
        "mean_score": round(statistics.mean(scored), 3) if scored else None,
        "score_hist": {str(v): scored.count(v) for v in (0, 1, 2)},
        "missing_capabilities": missing,
    }


def discrimination(mean_real: float | None, mean_ablated: float | None) -> float | None:
    """(real - ablated) / 2, normalised to the 0..2 scale."""
    if mean_real is None or mean_ablated is None:
        return None
    return round((mean_real - mean_ablated) / 2.0, 3)


def build_scorecard(rubric: dict, item_results: dict[str, list[dict]],
                    coverage: dict, *, discrimination_by_item: dict | None = None,
                    reliability: dict | None = None, manifest: dict | None = None) -> dict:
    """item_results: item_id -> list of per-unit result dicts."""
    gates = rubric.get("gates", {})
    d_min = gates.get("discrimination_min", 0.15)
    abstain_max = gates.get("abstain_max", 0.30)
    disc = discrimination_by_item or {}

    items_out, dropped = {}, []
    for item in rubric["items"]:
        iid = item["id"]
        summary = item_summary(item_results.get(iid, []))
        summary["dim"] = item["dim"]
        summary["unit"] = item["unit"]
        summary["checker"] = item["checker"]
        summary["weight"] = item.get("weight", 1)
        summary["discrimination"] = disc.get(iid)
        if summary["missing_capabilities"]:
            summary["status"] = "missing_data"
        elif summary["discrimination"] is not None and summary["discrimination"] < d_min:
            summary["status"] = "dropped_low_discrimination"
            dropped.append(iid)
        elif summary["discrimination"] is None:
            summary["status"] = "unverified_no_ablation"
        else:
            summary["status"] = "ok"
        items_out[iid] = summary

    dims = {}
    for dim_id, meta in rubric["dimensions"].items():
        total = [i for i in items_out.values() if i["dim"] == dim_id]
        # Items the run has no data for are not "failed" -- they are out of
        # scope for this run and must not drag the dimension's abstain rate.
        applicable = [i for i in total if i["status"] != "missing_data"]
        members = [i for i in applicable if i["status"] != "dropped_low_discrimination"]
        usable = [i for i in members if i["mean_score"] is not None]
        # Coverage is capped by the unit kinds that actually contributed. Items
        # abstained out (missing data) must not drag the dimension to zero --
        # they already cost it by not being counted.
        cov = _dim_coverage(usable or members, coverage)
        counts = {"n_items_used": len(usable), "n_items_applicable": len(applicable),
                  "n_items_total": len(total)}
        if not usable:
            reason = ("本次运行无对应数据" if not applicable
                      else "无可用 item（全部弃权或被判别力剔除）")
            dims[dim_id] = {"name": meta["name"], "score": None, "status": "unassessed",
                            "reason": reason, "coverage": cov, **counts}
            continue
        total_w = sum(i["weight"] for i in usable)
        raw = sum(i["weight"] * i["mean_score"] for i in usable) / (2.0 * total_w)
        mean_abstain = statistics.mean(i["abstain_rate"] for i in members) if members else 1.0
        score = round(raw * cov, 3)
        status = "ok"
        if mean_abstain > abstain_max:
            status = "unassessed"
        elif any(i["status"] == "unverified_no_ablation" for i in usable):
            status = "unverified"
        dims[dim_id] = {
            "name": meta["name"], "score": score, "raw_score": round(raw, 3),
            "coverage": cov, "abstain_rate": round(mean_abstain, 3),
            "pass": bool(score >= meta.get("pass", 0.6)) if status == "ok" else False,
            "threshold": meta.get("pass"), "status": status, **counts,
        }

    return {
        "rubric_version": rubric.get("rubric_version"),
        "dimensions": dims,
        "items": items_out,
        "dropped_items": dropped,
        "coverage": coverage,
        "reliability": reliability or {},
        "manifest": manifest or {},
        "gate": _trust_gate(dims, reliability or {}, gates),
    }


def _dim_coverage(items: list[dict], coverage: dict) -> float:
    """A dimension is capped by the coverage of the unit kinds it scored on."""
    vals = [coverage.get(i["unit"], 0.0) for i in items]
    return round(min(vals), 3) if vals else 0.0


def _trust_gate(dims: dict, reliability: dict, gates: dict) -> dict:
    """Three-state gate, matching GAWorld-Bench's convention."""
    if not any(d.get("status") == "ok" for d in dims.values()):
        state, reason = "UNVERIFIED", "没有任何维度达到可评状态（数据不足或全部弃权）"
    elif any(d.get("status") == "unverified" for d in dims.values()):
        state, reason = "UNVERIFIED", "存在未做消融判别力检验的 item"
    else:
        state, reason = "OK", ""
    alpha = reliability.get("krippendorff_alpha")
    if alpha is not None and alpha < gates.get("human_alpha_min", 0.6):
        state, reason = "UNVERIFIED", f"judge 间一致性 alpha={alpha:.2f} 低于门槛"
    if reliability.get("any_dimension_untrustworthy"):
        state, reason = "UNTRUSTWORTHY", "存在判别力不足的维度，分数无意义"
    return {"state": state, "reason": reason}


# ───────────────────────── report ─────────────────────────

def render_markdown(scorecard: dict) -> str:
    manifest = scorecard.get("manifest", {})
    lines = ["# GAWorld-Rubric-Bench Scorecard", "",
             f"- rubric 版本：`{scorecard.get('rubric_version')}`"
             f"（hash `{manifest.get('rubric_hash')}`）",
             f"- 抽样 seed：`{manifest.get('sample_seed')}`"
             f"｜judges：`{manifest.get('judges') or '（无，仅规则项）'}`"
             f"｜消融：`{manifest.get('ablations_run') or '未跑'}`",
             f"- run 模式：`{manifest.get('run_mode', 'unknown')}`"
             + (f"｜缺失能力：`{'、'.join(manifest['missing_capabilities'])}`"
                if manifest.get("missing_capabilities") else "｜数据能力齐全"),
             f"- Trust gate：**{scorecard['gate']['state']}**"
             + (f"（{scorecard['gate']['reason']}）" if scorecard['gate']['reason'] else "")]
    if manifest.get("run_mode") == "fast_forward":
        lines += ["", "> ⚡ **快进运行**。日内 tick 循环被绕过，因此没有 episodes，"
                       "日记来自确定性模板。R1/R3/R4 与 R2.2/R2.4 会因缺少数据能力而弃权——"
                       "这是运行模式的限制，不是模型表现。需要另跑一份短的全保真 run 来补。"]
    if scorecard.get("mode") == "synthetic":
        lines += ["", "> ⚠️ **合成自检模式**。数据是构造的，LLM 条目由 stub judge 打分。"
                       "只有 `checker=rule` 的条目在此模式下有意义（用于验证管线与消融算子）；"
                       "LLM 条目的分数与判别力**不可解读**。"]
    lines += ["", "## 维度分", "",
              "| 维度 | 分数 | 门槛 | 覆盖度 | 弃权率 | 计分/适用/总 item | 状态 |",
              "|------|------|------|--------|--------|-------------------|------|"]
    for dim_id, d in scorecard["dimensions"].items():
        score = "n/a" if d["score"] is None else f"{d['score']:.3f}"
        counts = (f"{d.get('n_items_used', 0)}/{d.get('n_items_applicable', 0)}"
                  f"/{d.get('n_items_total', 0)}")
        lines.append(f"| {dim_id} {d['name']} | {score} | {d.get('threshold')} | "
                     f"{d.get('coverage')} | {d.get('abstain_rate', '-')} | "
                     f"{counts} | {d['status']} |")

    lines += ["", "## Item 明细", "",
              "| item | checker | 已评/总数 | 弃权率 | 均分 | 判别力 | 状态 |",
              "|------|---------|-----------|--------|------|--------|------|"]
    for iid, it in scorecard["items"].items():
        if it["status"] == "missing_data":
            lines.append(f"| {iid} | {it['checker']} | — | — | — | — | "
                         f"本次运行无此数据（缺 {'、'.join(it['missing_capabilities'])}） |")
            continue
        mean = "n/a" if it["mean_score"] is None else f"{it['mean_score']:.2f}"
        disc = "未测" if it["discrimination"] is None else f"{it['discrimination']:.2f}"
        lines.append(f"| {iid} | {it['checker']} | {it['n_scored']}/{it['n_units']} | "
                     f"{it['abstain_rate']:.2f} | {mean} | {disc} | {it['status']} |")

    if scorecard["dropped_items"]:
        lines += ["", "## 被剔除的 item（判别力不足）", "",
                  "这些条目无法把人为破坏的样本判低分，本次评分中已剔除并进入重写队列：", "",
                  "- " + "\n- ".join(scorecard["dropped_items"])]
        if scorecard.get("mode") == "synthetic":
            lines += ["", "> 注意：合成模式下 `llm` / `hybrid` 条目由 stub judge 打分，"
                           "被剔除反映的是 **stub 的识别能力**，不是这些 rubric 条目本身无效。"
                           "只有 `rule` 条目出现在此列表才值得担心。"]

    lines += ["", "## 读数须知", "",
              "- 分数按 rubric 版本断代，跨版本不可比。",
              "- `unverified` = 未做判别力检验，分数仅供参考，不得进对外材料。",
              "- 弃权率高通常意味着数据字段缺失，而不是模型差——见 item 明细。",
              "- 「计分/适用/总 item」：适用 < 总 = 本次运行缺对应数据；计分 < 适用 = 有条目被弃权"
              "或因判别力不足剔除。计分数很小的维度分要当窄口径读。"]
    return "\n".join(lines) + "\n"
