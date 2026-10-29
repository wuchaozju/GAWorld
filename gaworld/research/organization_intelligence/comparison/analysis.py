"""Paired question-cluster estimates; messages are never independent samples."""

from __future__ import annotations

import random
import statistics

LABELS = {
    "better": "有证据表明候选组织成绩更高",
    "worse": "有证据表明候选组织成绩更低",
    "uncertain": "尚无充分证据表明候选组织更有效",
    "incomplete": "实验数据不完整，暂不能判断",
}


def analyze(rows, *, expected, delta=0, seed=20261026):
    keys = [(r["task_id"], r["repeat"], r["arm"]) for r in rows]
    groups = {}
    for row in rows:
        groups.setdefault((row["task_id"], row["repeat"]), {})[row["arm"]] = row
    complete = (
        len(rows) == expected
        and len(keys) == len(set(keys))
        and all(set(g) == {"candidate", "baseline"} for g in groups.values())
    )
    result = {
        "complete": complete,
        "verdict": "incomplete",
        "conclusion": LABELS["incomplete"],
        "independent_tasks": 0,
        "rows": len(rows),
        "expected": expected,
        "difference": None,
        "interval": None,
        "delta": delta,
        "arms": {},
    }
    if not complete or not rows:
        return result
    by_task = {}
    for (task_id, _), pair in groups.items():
        by_task.setdefault(task_id, []).append(pair["candidate"]["score"] - pair["baseline"]["score"])
    differences = [statistics.mean(values) for values in by_task.values()]
    rng = random.Random(seed)
    distribution = sorted(statistics.mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
    interval = [distribution[49], distribution[1949]]
    verdict = "uncertain"
    if len(differences) >= 30:
        if interval[0] > delta:
            verdict = "better"
        elif interval[1] < -delta:
            verdict = "worse"
    result.update(
        verdict=verdict,
        conclusion=LABELS[verdict],
        independent_tasks=len(differences),
        difference=statistics.mean(differences),
        interval=interval,
        exploratory=len(differences) < 30,
    )
    for arm in ("candidate", "baseline"):
        values = [r for r in rows if r["arm"] == arm]
        result["arms"][arm] = {
            "mean": statistics.mean(r["score"] for r in values),
            "completion_rate": statistics.mean(bool(r["valid"]) for r in values),
            "calls": sum(r.get("metrics", {}).get("calls", 0) for r in values),
            "input_chars": sum(r.get("metrics", {}).get("input_chars", 0) for r in values),
            "output_chars": sum(r.get("metrics", {}).get("output_chars", 0) for r in values),
            "elapsed": sum(r.get("metrics", {}).get("elapsed", 0) for r in values),
            "tokens": None,
        }
    result["categories"] = []
    for category in sorted({r.get("category", "未分类") for r in rows}):
        subset = [r for r in rows if r.get("category", "未分类") == category]
        means = {
            arm: statistics.mean(r["score"] for r in subset if r["arm"] == arm)
            for arm in ("candidate", "baseline")
        }
        result["categories"].append(
            {
                "category": category,
                "candidate": means["candidate"],
                "baseline": means["baseline"],
                "difference": means["candidate"] - means["baseline"],
                "questions": len({r["task_id"] for r in subset}),
                "exploratory": True,
            }
        )
    return result


def report(record):
    spec, result = record["protocol"], record["analysis"]
    lines = [
        f"# {spec['title']}",
        "",
        result["conclusion"],
        "",
        f"状态：{record['status']}；已完成 {len(record['rows'])}/{spec['expected']} 个实验单元。",
        f"候选组织：{spec['candidate']['name']}；对照：{spec['baseline']['name']}。",
        f"题库：{spec['benchmark']['name']}；模型：{spec['model']['model']}。",
        f"主指标：0–1成绩，越高越好；最小改善幅度：{spec['delta']}。",
        "",
        "| 组织 | 平均成绩 | 完成率 | 实际调用 | 输入字符 | 输出字符 | 调用耗时（秒） |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, values in result.get("arms", {}).items():
        lines.append(
            f"| {arm} | {values['mean']:.4f} | {values['completion_rate']:.1%} | {values['calls']} | "
            f"{values.get('input_chars', 0)} | {values.get('output_chars', 0)} | {values.get('elapsed', 0):.2f} |"
        )
    lines.extend(
        [
            "",
            f"配对差异：{result['difference']}；95%题目簇bootstrap区间：{result['interval']}。",
            f"独立题目数：{result['independent_tasks']}。每题重复不作为新增独立题。",
            "",
            "## 探索性题型分析",
            "",
            "这些子类比较不替代预先确定的主结果。",
            "",
            *[
                f"- {c['category']}（{c['questions']}题）：候选{c['candidate']:.4f}，对照{c['baseline']:.4f}，差异{c['difference']:.4f}。"
                for c in result.get("categories", [])
            ],
            "",
            "## 组织规则与来源",
            "",
            f"比较范围：{'仅通信结构' if spec['scope'] == 'topology' else '整套组织方式'}。双方任务预算：{spec['limits']}。",
            f"材料：{spec['candidate']['source']['title'] or '用户自定义'}。",
            *[
                f"- {r['text']}（{r['origin']}）" + (f"\n  原文：{r['quote']}" if r.get("quote") else "")
                for r in spec["candidate"]["rules"]
            ],
            *[
                f"- {spec[arm]['name']}：角色 {'、'.join(spec[arm]['roles'])}；通信 {spec[arm]['topology']['kind']}；"
                f"讨论{spec[arm]['rounds']}轮；审阅{spec[arm]['review']}；修订{spec[arm]['revisions']}次；决策{spec[arm]['decision']}。"
                for arm in ("candidate", "baseline")
            ],
            "",
            "## 失败与错误案例",
            "",
            *(
                [
                    f"- {r['task_id']} / {r['arm']} / 重复{r['repeat'] + 1}：{r.get('error') or '最终答案错误或不符合要求'}"
                    for r in record["rows"]
                    if not r["valid"] or r["score"] < 1
                ][:10]
                or ["未记录失败案例。"]
            ),
            "",
            "## 实验范围与限制",
            "",
            "结论仅适用于本次模型、成员、题库和运行限制。成绩与资源消耗分别报告。",
            "token和金额未知时不估造；调用/字符限制不能视为相同token成本。",
            "少于30道独立题为探索性结果；未发现优势不能解释为等效。",
            "若使用模型评审，评分代表固定量表下的模型判断。",
            f"协议：{record['protocol_hash']}；执行器：{spec['engine_version']}。",
        ]
    )
    return "\n".join(lines) + "\n"
