"""Seed-paired descriptive effects with strict preregistered completeness gates."""

import math
import random
import statistics

from .protocol import digest
from .queue import graph


def contrast(values):
    rng = random.Random(20261024)
    mean = statistics.mean(values)
    boot = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(2000))
    return {
        "mean": mean,
        "seed_differences": values,
        "n_seeds": len(values),
        "ci95": [boot[49], boot[1949]] if len(values) > 1 else None,
    }


def evaluate(spec, rows):
    expected = {identifier: payload for identifier, _, payload in graph(spec)}
    actual = {r.get("task_id"): r for r in rows}
    complete = len(rows) == len(actual) == len(expected) and set(actual) == set(expected)
    if complete:
        complete = all(
            all(actual[key].get(k) == v for k, v in p.items())
            and actual[key].get("budget_violations") == 0
            and math.isfinite(actual[key]["net_reward"])
            for key, p in expected.items()
        )
    out = {
        "complete": complete,
        "episodes": len(rows),
        "expected": len(expected),
        "external_calls": 0,
        "contrasts": [],
        "cells": [],
        "strata": [],
    }
    if not complete:
        return out
    grouped = {}
    for row in rows:
        if row["phase"] == "test":
            key = row["seed"], row["procedure"], row["memory"], row["turnover"]
            grouped.setdefault(key, []).append(row)
    means = {key: statistics.mean(r["net_reward"] for r in group) for key, group in grouped.items()}
    for cell in spec["cells"]:
        selected = [
            r
            for r in rows
            if r["phase"] == "test" and all(r[k] == cell[k] for k in ("procedure", "memory", "turnover"))
        ]
        out["cells"].append(
            {
                **cell,
                "n_seeds": len(spec["seeds"]),
                **{
                    metric: statistics.mean(r[metric] for r in selected)
                    for metric in (
                        "net_reward",
                        "reward",
                        "cost",
                        "checks",
                        "local_reports_shared",
                        "common_report_duplicates_removed",
                        "corrections",
                        "delay_steps",
                    )
                },
            }
        )
    definitions = [
        ("primary_memory_after_turnover", lambda s: means[s, 1, 1, 1] - means[s, 1, 0, 1]),
        ("procedure_without_memory_after_turnover", lambda s: means[s, 1, 0, 1] - means[s, 0, 0, 1]),
        ("turnover_loss_without_org_memory", lambda s: means[s, 1, 0, 0] - means[s, 1, 0, 1]),
        ("turnover_loss_with_org_memory", lambda s: means[s, 1, 1, 0] - means[s, 1, 1, 1]),
        (
            "memory_reduces_turnover_loss",
            lambda s: (means[s, 1, 0, 0] - means[s, 1, 0, 1]) - (means[s, 1, 1, 0] - means[s, 1, 1, 1]),
        ),
    ]
    out["contrasts"] = [{"id": name, **contrast([fn(s) for s in spec["seeds"]])} for name, fn in definitions]
    for stratum in sorted({r["stratum"] for r in rows if r["phase"] == "test"}):
        deltas = []
        for seed in spec["seeds"]:
            vals = {}
            for p in (0, 1):
                group = [
                    r["net_reward"]
                    for r in rows
                    if r["phase"] == "test"
                    and r["seed"] == seed
                    and r["procedure"] == p
                    and r["memory"] == 0
                    and r["turnover"] == 1
                    and r["stratum"] == stratum
                ]
                if group:
                    vals[p] = statistics.mean(group)
            if len(vals) == 2:
                deltas.append(vals[1] - vals[0])
        if deltas:
            out["strata"].append(
                {"stratum": stratum, "procedure_net_gain": statistics.mean(deltas), "n_seeds": len(deltas)}
            )
    out["result_hash"] = digest(rows)
    return out


def markdown(record, analysis):
    lines = [
        f"# {record['protocol']['title']} · {record['id']}",
        "",
        f"引擎 {record['protocol']['version']}；构建 `{record.get('build_id', 'fixture')}`；外部模型请求 0。",
        "",
        "这是人工角色的有限规则机制模拟。没有运行乌镇居民或实时LLM协商，也不构成真人或通用智能证据。",
        "",
        f"任务完整度：{analysis['episodes']} / {analysis['expected']}。",
    ]
    if not analysis["complete"]:
        return "\n".join([*lines, "", "数据未完整或未通过配对校验；暂无处理效应结论。"])
    lines += [
        "",
        "训练10题后克隆原成员/全员更替支线；每支线20道相同留出题。测试期间记忆冻结。净收益扣除符号通信、核验和延迟成本。统计单位为种子，95%区间为种子配对差的百分位bootstrap（2000次），不以任务数当独立样本。",
        "",
        "| 条件 | 种子数 | 平均净收益 | 客观收益 | 成本 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in analysis["cells"]:
        lines.append(
            f"| {row['id']} | {row['n_seeds']} | {row['net_reward']:.3f} | {row['reward']:.3f} | {row['cost']:.3f} |"
        )
    lines += [
        "",
        "P0=等权提案投票，P1=证据去重与有限核验；M1=保留跨任务组织来源计数；T1=全员替换。",
        "",
        "| 预注册比较 | 配对净收益差 | 95%区间 |",
        "|---|---:|---|",
    ]
    for row in analysis["contrasts"]:
        interval = row["ci95"]
        ci = f"[{interval[0]:.3f}, {interval[1]:.3f}]" if interval else "单种子，不估计"
        lines.append(f"| {row['id']} | {row['mean']:.3f} | {ci} |")
    lines += [
        "",
        "主比较为primary_memory_after_turnover；其他为探索性次要比较，不做多重检验显著性宣称。",
        "",
        "| 预设任务分层 | 无记忆且更替后P1−P0净收益 | 配对种子数 |",
        "|---|---:|---:|",
    ]
    for row in analysis["strata"]:
        lines.append(f"| {row['stratum']} | {row['procedure_net_gain']:.3f} | {row['n_seeds']} |")
    lines += [
        "",
        "local_reports_shared和common_report_duplicates_removed只计数实际报告及去重操作，是流程结构描述，不能当作独有证据的因果贡献或重复信息放大效应。corrections是核验导致分项首选变化的次数，不等同最终决策获益。",
        "",
        "共同信息可靠性与核验价格在结果前固定；保留所有正负结果。来源可靠性为外部稳定来源的计数，不从离职成员向新人转移私人能力。所设噪声、规则、训练量与成本都属于模型假设；不能外推到现实组织。旧记忆与环境突变的冲突尚属后续研究，本轮没有检验。",
        "",
        f"结果SHA-256：`{analysis['result_hash']}`",
    ]
    return "\n".join(lines) + "\n"
