"""Paired question-cluster estimates; messages are never independent samples.

A cell that could not be measured is not a wrong answer. It is excluded from
the comparison, counted separately, and the run reports ``incomplete`` — the
numbers that were measured are still shown.
"""

from __future__ import annotations

import random
import statistics

LABELS = {
    "better": "有证据表明候选组织成绩更高",
    "worse": "有证据表明候选组织成绩更低",
    "uncertain": "尚无充分证据表明候选组织更有效",
    "incomplete": "实验数据不完整，暂不能判断",
}

#: The arm every candidate is compared with.
CONTROL = "baseline"

#: The candidate a study leads with; its verdict is the study's headline.
PRIMARY = "candidate"


def verdict_label(verdict, label=""):
    """The sentence a verdict is reported with, naming the candidate."""
    if not label:
        return LABELS[verdict]
    name = f"「{label}」"
    return {
        "better": f"有证据表明{name}成绩更高",
        "worse": f"有证据表明{name}成绩更低",
        "uncertain": f"尚无充分证据表明{name}更有效",
        "incomplete": "实验数据不完整，暂不能判断",
    }[verdict]


REASON_LABELS = {
    "budget_exceeded": "超出本次设置的资源上限",
    "scoring_unavailable": "评审没有给出可用分数",
    "request_failed": "模型服务没有完成本次请求",
    "protocol_drift": "已保存的回答与当前提示词不一致",
}


def _arm_stats(arm, values, unmeasured):
    if not values:
        return {
            "mean": None,
            "completion_rate": None,
            "calls": 0,
            "input_chars": 0,
            "output_chars": 0,
            "elapsed": 0,
            "tokens": None,
            "unmeasured": len([r for r in unmeasured if r["arm"] == arm]),
        }
    return {
        "mean": statistics.mean(r["score"] for r in values),
        "completion_rate": statistics.mean(bool(r["valid"]) for r in values),
        "calls": sum(r.get("metrics", {}).get("calls", 0) for r in values),
        "input_chars": sum(r.get("metrics", {}).get("input_chars", 0) for r in values),
        "output_chars": sum(r.get("metrics", {}).get("output_chars", 0) for r in values),
        "elapsed": sum(r.get("metrics", {}).get("elapsed", 0) for r in values),
        "tokens": None,
        "unmeasured": len([r for r in unmeasured if r["arm"] == arm]),
    }


def _compare(groups, arm, control, *, delta, seed, complete=True):
    """The paired difference of one candidate against the control.

    A cell that could not be measured carries no score; it is left out of the
    pairing, counted as unmeasured, and the run says so instead of guessing.
    """
    by_task = {}
    for pair in groups.values():
        if arm not in pair or control not in pair:
            continue
        left, right = pair[arm], pair[control]
        if left.get("score") is None or right.get("score") is None:
            continue
        by_task.setdefault(left["task_id"], []).append(left["score"] - right["score"])
    differences = [statistics.mean(values) for values in by_task.values()]
    if not differences:
        return {
            "verdict": "incomplete",
            "conclusion": LABELS["incomplete"],
            "difference": None,
            "interval": None,
            "independent_tasks": 0,
            "exploratory": True,
        }
    rng = random.Random(seed)
    distribution = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
    interval = [distribution[49], distribution[1949]]
    verdict = "uncertain"
    if not complete:
        verdict = "incomplete"
    elif len(differences) >= 30:
        if interval[0] > delta:
            verdict = "better"
        elif interval[1] < -delta:
            verdict = "worse"
    return {
        "verdict": verdict,
        "conclusion": LABELS[verdict],
        "difference": statistics.mean(differences),
        "interval": interval,
        "independent_tasks": len(differences),
        "exploratory": len(differences) < 30,
    }


def analyze(rows, *, expected, delta=0, seed=20261026, arms=None):
    arm_ids = list(arms) if arms else [PRIMARY, CONTROL]
    keys = [(r["task_id"], r["repeat"], r["arm"]) for r in rows]
    groups = {}
    for row in rows:
        groups.setdefault((row["task_id"], row["repeat"]), {})[row["arm"]] = row
    measured = [r for r in rows if r.get("measured", True)]
    unmeasured = [r for r in rows if not r.get("measured", True)]
    complete = (
        len(rows) == expected
        and len(keys) == len(set(keys))
        and all(set(g) == set(arm_ids) for g in groups.values())
        and not unmeasured
    )
    result = {
        "complete": complete,
        "verdict": "incomplete",
        "conclusion": LABELS["incomplete"],
        "independent_tasks": len({r.get("task_id") for r in rows}),
        "rows": len(rows),
        "measured_rows": len(measured),
        "unmeasured_rows": len(unmeasured),
        "unmeasured": [
            {
                "cell": r.get("cell"),
                "task_id": r.get("task_id"),
                "arm": r.get("arm"),
                "repeat": r.get("repeat"),
                "reason": REASON_LABELS.get(r.get("invalid_reason"), r.get("invalid_reason") or "未能测量"),
                "error": r.get("error") or "",
            }
            for r in unmeasured
        ],
        "difference": None,
        "interval": None,
        "delta": delta,
        "arms": {},
        "candidates": {},
    }
    for arm in arm_ids:
        result["arms"][arm] = _arm_stats(arm, [r for r in measured if r["arm"] == arm], unmeasured)
    candidates = [arm for arm in arm_ids if arm != CONTROL]
    for position, arm in enumerate(candidates):
        result["candidates"][arm] = _compare(
            groups, arm, CONTROL, delta=delta, seed=seed + position, complete=complete
        )
    primary = PRIMARY if PRIMARY in candidates else (candidates[0] if candidates else None)
    if complete and measured and primary:
        headline = result["candidates"][primary]
        result.update(
            verdict=headline["verdict"],
            conclusion=headline["conclusion"],
            independent_tasks=headline["independent_tasks"],
            difference=headline["difference"],
            interval=headline["interval"],
            exploratory=headline["exploratory"],
        )
    if not complete or not measured:
        return result
    result["categories"] = []
    for category in sorted({r.get("category", "未分类") for r in measured}):
        subset = [r for r in measured if r.get("category", "未分类") == category]
        means = {
            arm: statistics.mean(r["score"] for r in subset if r["arm"] == arm)
            for arm in arm_ids
            if [r for r in subset if r["arm"] == arm]
        }
        entry = {
            "category": category,
            "arms": means,
            "questions": len({r["task_id"] for r in subset}),
            "exploratory": True,
        }
        if primary and primary in means and CONTROL in means:
            entry["candidate"] = means[primary]
            entry["baseline"] = means[CONTROL]
            entry["difference"] = means[primary] - means[CONTROL]
        result["categories"].append(entry)
    return result


def _arm_labels(spec):
    """The name of every arm, the ones frozen before the arms existed included."""
    labels = {}
    for arm in spec.get("arms") or []:
        labels[arm["id"]] = arm.get("label") or arm["id"]
    labels.setdefault(PRIMARY, (spec.get("candidate") or {}).get("name") or PRIMARY)
    labels.setdefault(CONTROL, (spec.get("baseline") or {}).get("name") or CONTROL)
    return labels


def _scope_factors(spec, arm):
    """The factors one arm was allowed to differ in."""
    scope = spec.get("scope_factors")
    if isinstance(scope, dict):
        return scope.get(arm) or []
    return scope or []


def report(record):
    spec, result = record["protocol"], record["analysis"]
    labels = _arm_labels(spec)
    candidates = list(result.get("candidates", {}))
    lines = [
        f"# {spec['title']}",
        "",
        result["conclusion"],
        "",
        f"状态：{record['status']}；已完成 {len(record['rows'])}/{spec['expected']} 个实验单元，"
        f"其中 {result.get('measured_rows', len(record['rows']))} 个单元可用于比较。",
        f"候选组织：{spec['candidate']['name']}；对照：{spec['baseline']['name']}。",
        f"题库：{spec['benchmark']['name']}；模型：{spec['model']['model']}。",
        f"主指标：0–1成绩，越高越好；最小改善幅度：{spec['delta']}。",
    ]
    factor_labels = {
        "roles": "角色分工",
        "topology": "通信结构",
        "rounds": "讨论轮数",
        "review": "审阅与修订",
        "decision": "决策方式",
    }
    for arm in candidates:
        factors = _scope_factors(spec, arm)
        if factors:
            lines.append(
                f"「{labels.get(arm, arm)}」允许不同的因子："
                + "、".join(factor_labels.get(f, f) for f in factors)
                + "；其余因子与对照臂相同。"
            )
    lines.extend(
        [
            "",
            "| 组织 | 平均成绩 | 完成率 | 实际调用 | 输入字符 | 输出字符 | 调用耗时（秒） | 未测量 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for arm, values in result.get("arms", {}).items():
        mean = "—" if values.get("mean") is None else f"{values['mean']:.4f}"
        rate = "—" if values.get("completion_rate") is None else f"{values['completion_rate']:.1%}"
        lines.append(
            f"| {labels.get(arm, arm)} | {mean} | {rate} | {values['calls']} | {values.get('input_chars', 0)} | "
            f"{values.get('output_chars', 0)} | {values.get('elapsed', 0):.2f} | {values.get('unmeasured', 0)} |"
        )
    if len(candidates) > 1:
        lines.extend(["", "## 每个候选与对照的比较", ""])
        for arm in candidates:
            entry = result["candidates"][arm]
            lines.append(
                f"- **{labels.get(arm, arm)}**：{verdict_label(entry['verdict'], labels.get(arm, ''))}"
                + (
                    f"；配对差异 {entry['difference']:.4f}，95%题目簇bootstrap区间 "
                    f"[{entry['interval'][0]:.4f}, {entry['interval'][1]:.4f}]，独立题目 {entry['independent_tasks']} 道。"
                    if entry.get("interval")
                    else ""
                )
            )
    lines.extend(
        [
            "",
            f"配对差异：{result['difference']}；95%题目簇bootstrap区间：{result['interval']}。",
            f"独立题目数：{result['independent_tasks']}。每题重复不作为新增独立题。",
        ]
    )
    if result.get("unmeasured"):
        lines.extend(["", "## 未能测量的实验单元", "", "这些单元没有计入比较，也没有被当作错误答案："])
        lines.extend(
            f"- {item['cell']}（{item['reason']}）{('：' + item['error']) if item.get('error') else ''}"
            for item in result["unmeasured"][:20]
        )
    lines.extend(
        [
            "",
            "## 探索性题型分析",
            "",
            "这些子类比较不替代预先确定的主结果。",
            "",
            *[
                f"- {c['category']}（{c['questions']}题）："
                + (
                    f"候选{c['candidate']:.4f}，对照{c['baseline']:.4f}，差异{c['difference']:.4f}。"
                    if "candidate" in c
                    else "、".join(
                        f"{labels.get(arm, arm)}{value:.4f}" for arm, value in c.get("arms", {}).items()
                    )
                    + "。"
                )
                for c in result.get("categories", [])
            ],
            "",
            "## 组织规则与来源",
            "",
            f"比较范围：{'、'.join(factor_labels.get(f, f) for f in _scope_factors(spec, PRIMARY)) or '整套组织方式'}。"
            f"双方任务预算：{spec['limits']}。",
            f"材料：{spec['candidate']['source']['title'] or '用户自定义'}。",
            *[
                f"- {r['text']}（{r['origin']}）" + (f"\n  原文：{r['quote']}" if r.get("quote") else "")
                for r in spec["candidate"]["rules"]
            ],
            "",
            "### 每一臂收到的做事规则",
            "",
            "组织方式必须让成员真的按它做事；下面几组文字就是各臂各自收到的指令。",
            "",
            *[
                f"- **{labels.get(arm, arm)}**：{'；'.join(spec.get('instructions', {}).get(arm, []))}"
                for arm in result.get("arms", {})
            ],
            "",
            "## 失败与错误案例",
            "",
            *(
                [
                    f"- {r['task_id']} / {labels.get(r.get('arm'), r.get('arm'))} / 重复{r['repeat'] + 1}："
                    f"{r.get('error') or '最终答案错误或不符合要求'}"
                    for r in record["rows"]
                    if not r.get("measured", True) or r.get("score") is None or r.get("score", 1) < 1
                ][:10]
                or ["未记录失败案例。"]
            ),
            "",
            "## 实验范围与限制",
            "",
            "结论仅适用于本次模型、成员、题库和运行限制。成绩与资源消耗分别报告。",
            "token和金额未知时不估造；调用/字符限制不能视为相同token成本。",
            "少于30道独立题为探索性结果；未发现优势不能解释为等效。",
            "未能测量的单元不计入比较，也不被记为错误答案。",
            "若使用模型评审，评分代表固定量表下的模型判断。",
            f"协议：{record['protocol_hash']}；执行器：{spec['engine_version']}。",
        ]
    )
    return "\n".join(lines) + "\n"
