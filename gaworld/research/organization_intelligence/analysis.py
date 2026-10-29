"""Objective scores and paired block contrasts; no invented uncertainty."""

from __future__ import annotations

from statistics import mean

from .protocol import ARMS, LIMIT


def evaluate(rows, repeats):
    test = [r for r in rows if r["phase"] == "test"]
    expected = {(b, arm, t) for b in range(repeats) for arm in ARMS for t in range(3, 6)}
    keys = [(r["block"], r["arm"], r["task_index"]) for r in test]
    complete = set(keys) == expected and len(keys) == len(expected)
    result = {
        "complete": complete,
        "blocks": [],
        "contrasts": [],
        "limitations": LIMIT,
        "inference": "仅描述性配对结果；不计算显著性，不将任务数当作独立样本数。",
    }
    if not complete:
        result["inference"] = "数据不完整，禁止比较条件或判断组织收益。"
        return result
    for b in range(repeats):
        values = {}
        for arm in ARMS:
            selected = [r for r in test if r["block"] == b and r["arm"] == arm]
            values[arm] = {
                "utility": mean(r["normalized_utility"] for r in selected),
                "accuracy": mean(r["optimal"] for r in selected),
            }
        result["blocks"].append({"block": b, "arms": values})
    contrasts = [
        ("组织通信相对独立汇总（均无共享档案）", {"incumbent_no_archive": 1, "independent": -1}),
        ("组织通信相对集中单智能体（均无共享档案）", {"incumbent_no_archive": 1, "pooled": -1}),
        ("全员更替后的档案收益", {"replacement_archive": 1, "replacement_no_archive": -1}),
        ("保留档案时的成员更替效应", {"replacement_archive": 1, "incumbent_archive": -1}),
        (
            "更替与档案的交互",
            {
                "replacement_archive": 1,
                "replacement_no_archive": -1,
                "incumbent_archive": -1,
                "incumbent_no_archive": 1,
            },
        ),
    ]
    for label, weights in contrasts:
        differences = [sum(b["arms"][a]["utility"] * w for a, w in weights.items()) for b in result["blocks"]]
        result["contrasts"].append(
            {"label": label, "block_differences": differences, "mean": mean(differences), "n_blocks": repeats}
        )
    return result


def report(record):
    spec = record["protocol"]
    info = record.get("rate_limit") or {}
    out = [
        f"# {spec['title']}",
        "",
        f"研究编号：{record['id']} · 状态：{record['status']}",
        "",
        f"协议：{spec['version']} · SHA-256：{record['protocol_hash']}",
        f"模型：{spec['model']['name']} / {spec['model'].get('model', '')}",
        f"城市：{spec['city'] or '当前世界'} · 随机种子：{spec['seed']} · 独立运行组：{spec['repeats']}",
        "",
        spec["limitations"],
        "",
        spec["design"],
        "",
        f"计划请求：{spec['budget']['requests']}；"
        f"已记录响应：{record.get('calls_completed', 0)}；状态说明：{info.get('message') or record.get('error') or '无'}",
        "",
        "## 留出任务结果",
        "",
    ]
    telemetry = record.get("telemetry") or {}
    out += [
        f"HTTP提交：{telemetry.get('http_attempts', 0)}；HTTP失败：{telemetry.get('http_failures', 0)}；"
        f"输入字符：{record.get('input_chars', 0)}；输出字符：{record.get('output_chars', 0)}。",
        f"组织档案归纳：计划 {spec['budget']['archive_requests']} 次，已保存 {len(record.get('archives', []))} 份。",
        f"活动时间：{record.get('elapsed_seconds', 0):.1f} 秒；"
        f"日历时间：{record.get('wall_seconds', 0):.1f} 秒；暂停：{record.get('paused_seconds', 0):.1f} 秒。",
        "token用量与金额：当前传输层未提供，不能由字符数推算。",
        "",
    ]
    if spec.get("runtime_policy"):
        out += [
            f"请求开始间隔至少 {spec['runtime_policy']['min_interval_seconds']} 秒；限流暂停，需显式恢复，无自动重试或模型回退。",
            f"有效回答：{record.get('valid_responses', 0)}；其中断点复用：{record.get('replayed_responses', 0)}；"
            f"本地格式转义恢复：{record.get('format_repairs', 0)}（原文始终保留）。",
            "输入/输出字符包含复用回答；HTTP统计只计当前记录的新提交。",
        ]
    provenance = spec.get("recovery")
    if provenance:
        out += [
            f"恢复来源：{provenance['source_id']}；已冻结 {provenance['responses']} 份有效回答。"
            "这是一次研究的延续，不作为新的独立重复，也不汇总其他失败记录的结果。"
        ]
    if info:
        out += [info.get("hint", ""), f"最早可重试时间（Unix）：{info['retry_at']}；需等待服务商配额恢复。"]
    if record.get("error"):
        out += ["", "### 原始错误诊断", "", record["error"], ""]
    analysis = evaluate(record.get("rows", []), spec["repeats"])
    out.append(analysis["inference"])
    if analysis["complete"]:
        out += ["", "| 条件 | 平均效用/最优效用 | 最优选择率 |", "|---|---:|---:|"]
        for arm, label in ARMS.items():
            score = mean(b["arms"][arm]["utility"] for b in analysis["blocks"])
            accuracy = mean(b["arms"][arm]["accuracy"] for b in analysis["blocks"])
            out.append(f"| {label} | {score:.3f} | {accuracy:.1%} |")
        out += ["", "## 配对差异", ""]
        for c in analysis["contrasts"]:
            out.append(f"- {c['label']}：{c['mean']:+.3f}；逐组差异 {c['block_differences']}")
    out += [
        "",
        "## 可追溯产物",
        "",
        "protocol.json 保存模型、居民、任务、隐藏真值和预注册设置；"
        "events.jsonl 保存请求上下文、完整提示词、原始响应与失败；study.json 保存任务得分、组织档案与进度。",
        "",
        "本实验不改变城市居民或生产组织。相同居民可跨运行组出现；独立性指任务种子与模型会话。"
        "此任务只检验信息汇集及档案传承，不能推导一般智能、制度自发演化或真人组织效应。",
    ]
    return "\n".join(out) + "\n"
