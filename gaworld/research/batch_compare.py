"""Deterministic run-level summaries; never pool residents across cities."""

from __future__ import annotations

import itertools
import math
import statistics
from typing import Any

from gaworld.parallel.causal import t_interval


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def compare(batch: dict[str, Any], selected: list[str] | None = None) -> dict[str, Any]:
    all_cells = batch["cells"]
    if selected is not None and (
        not isinstance(selected, list)
        or any(not isinstance(v, str) for v in selected)
        or not set(selected) <= {c["id"] for c in all_cells}
    ):
        raise ValueError("所选运行不属于此批次")
    cells = [c for c in all_cells if selected is None or c["id"] in selected]
    metrics = {}
    for cell in cells:
        key = (cell["provider"], cell["city"])
        metric = metrics.setdefault(
            key,
            {
                "provider": cell["provider"],
                "city": cell["city"],
                "planned": 0,
                "failed": 0,
                "measured_runs": 0,
                "requests": None,
                "requests_failed": None,
            },
        )
        metric["planned"] += 1
        metric["failed"] += cell["status"] in {"failed", "interrupted", "stopped"}
        stats = (
            (cell.get("result") or {}).get("telemetry")
            or (cell.get("run_status") or {}).get("telemetry")
            or {}
        )
        if stats.get("available") is not False and "requests" in stats:
            metric["measured_runs"] += 1
            for field in ("requests", "requests_failed"):
                metric[field] = (metric[field] or 0) + int(stats.get(field) or 0)
    for metric in metrics.values():
        metric["task_failure_rate"] = metric["failed"] / metric["planned"]
        metric["request_failure_rate"] = (
            metric["requests_failed"] / metric["requests"] if metric["requests"] else None
        )
    issues = []
    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for cell in cells:
        result = cell.get("result") or {}
        reason = ""
        if cell["status"] != "done":
            reason = cell.get("error") or cell["status"]
        elif result.get("protocol_hash") != batch["protocol_hash"]:
            reason = "研究协议版本不同"
        elif (
            result.get("provider") != cell["provider"]
            or not result.get("model")
            or (
                batch.get("models", {}).get(cell["provider"], {}).get("model")
                and result.get("model") != batch["models"][cell["provider"]]["model"]
            )
        ):
            reason = "实际模型与指定模型不符或未记录"
        elif result.get("mode") != (
            batch["protocol"].get("execution_mode")
            or ("lean_tick" if batch["protocol"].get("fast") else "tick")
        ):
            reason = "实际执行模式与协议不符"
        elif not result.get("valid"):
            reason = "运行不完整或没有可比数据"
        if reason:
            issues.append({"cell_id": cell["id"], "status": cell["status"], "reason": reason})
            continue
        for hypothesis in result.get("hypotheses", []):
            effect = hypothesis.get("mean_effect")
            if not _number(effect):
                issues.append({"cell_id": cell["id"], "reason": f"{hypothesis.get('id')} 缺少有限效应值"})
                continue
            # Unknown provenance remains visible as a singleton, never as replicates.
            unknown = cell["id"] if result.get("epoch") is None or not result.get("sample_hash") else ""
            key = (
                cell["provider"],
                cell["city"],
                hypothesis["id"],
                result["model"],
                result["mode"],
                result.get("epoch"),
                result.get("sample_hash"),
                result.get("model_config_hash"),
                unknown,
            )
            buckets.setdefault(key, []).append(
                {
                    "cell_id": cell["id"],
                    "seed": cell["seed"],
                    "repeat": cell["repeat"],
                    "effect": float(effect),
                    "direction": hypothesis["direction"],
                    "verdict": hypothesis.get("verdict", "unmeasured"),
                }
            )
    groups = []
    for key, rows in buckets.items():
        provider, city, hypothesis, model, mode, epoch, sample_hash, config_hash, _ = key
        effects = [r["effect"] for r in rows]
        unique = len({r["seed"] for r in rows})
        independent = batch["matrix"]["seed_strategy"] == "vary" and unique == len(rows) and unique >= 2
        interval = t_interval(effects) if independent else None
        groups.append(
            {
                "provider": provider,
                "city": city,
                "hypothesis": hypothesis,
                "model": model,
                "mode": mode,
                "epoch": epoch,
                "sample_hash": sample_hash,
                "model_config_hash": config_hash,
                "n": len(effects),
                "mean": statistics.mean(effects),
                "sd": statistics.stdev(effects) if len(effects) >= 2 else None,
                "ci95": list(interval) if interval is not None else None,
                "direction_rate": sum(
                    (r["effect"] < 0 if r["direction"] == "decrease" else r["effect"] > 0) for r in rows
                )
                / len(rows),
                "unique_seeds": unique,
                "seed_robustness": independent,
                "verdicts": {
                    v: sum(r["verdict"] == v for r in rows) for v in sorted({r["verdict"] for r in rows})
                },
                "rows": rows,
            }
        )
    contrasts = []
    for left, right in itertools.combinations(groups, 2):
        if (
            left["hypothesis"] != right["hypothesis"]
            or left["mode"] != right["mode"]
            or left["epoch"] != right["epoch"]
            or left["epoch"] is None
        ):
            continue
        if (
            left["city"] == right["city"]
            and left["provider"] != right["provider"]
            and left["sample_hash"] == right["sample_hash"]
        ):
            paired = {r["seed"]: r["effect"] for r in left["rows"]}
            differences = [r["effect"] - paired[r["seed"]] for r in right["rows"] if r["seed"] in paired]
            if not left["seed_robustness"] or not right["seed_robustness"] or len(differences) < 2:
                continue
            interval = t_interval(differences)
            contrasts.append(
                {
                    "kind": "model",
                    "left": left["provider"],
                    "right": right["provider"],
                    "city": left["city"],
                    "hypothesis": left["hypothesis"],
                    "difference": statistics.mean(differences),
                    "paired_seeds": len(differences),
                    "ci95": list(interval) if interval else None,
                }
            )
        elif (
            left["provider"] == right["provider"]
            and left["city"] != right["city"]
            and left["model"] == right["model"]
            and left["model_config_hash"] == right["model_config_hash"]
        ):
            contrasts.append(
                {
                    "kind": "city",
                    "left": left["city"],
                    "right": right["city"],
                    "provider": left["provider"],
                    "hypothesis": left["hypothesis"],
                    "difference": right["mean"] - left["mean"],
                    "paired_seeds": 0,
                    "ci95": None,
                    "note": "城市内处理效应均值之差；城市居民不配对，不作显著性判定",
                }
            )
    return {
        "runtime_metrics": list(metrics.values()),
        "counts": {
            "planned": len(all_cells),
            "selected": len(cells),
            "done": sum(c["status"] == "done" for c in cells),
            "failed": sum(c["status"] in {"failed", "interrupted", "stopped"} for c in cells),
            "pending": sum(c["status"] in {"pending", "running", "queued", "cancelled"} for c in cells),
        },
        "groups": groups,
        "contrasts": contrasts,
        "issues": issues,
        "note": "以运行效应为单位；区间仅用于至少两个不同种子的完整重复。固定种子仅描述输出波动。缺失运行不补值。95% 区间未作多重比较校正。",
    }


def markdown(batch: dict[str, Any], comparison: dict[str, Any]) -> str:
    def cell(value: Any) -> str:
        return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")

    lines = [
        f"# {cell(batch['title'])} · 批次比较",
        "",
        f"批次：{batch['id']} · 状态：{batch['status']}",
        f"协议 SHA-256：{batch['protocol_hash']}",
        "",
        str(comparison["counts"]),
        "",
        comparison["note"],
        "",
        "| 模型 | 城市 | 假设 | 模式 / 版本 | 有效运行 | 均值 | 标准差 | 95% 区间 | 方向一致率 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for group in comparison["groups"]:
        lines.append(
            "| "
            + " | ".join(
                cell(v)
                for v in (
                    group["provider"] + " / " + group["model"],
                    group["city"] or "当前世界",
                    group["hypothesis"],
                    f"{group['mode']} / {group['epoch']}",
                    group["n"],
                    group["mean"],
                    group["sd"],
                    group["ci95"],
                    group["direction_rate"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 运行可靠性与实测请求",
            "",
            "| 模型 | 城市 | 计划 | 失败 | 任务失败率 | 有统计的运行 | 请求 | 请求失败率 |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for metric in comparison["runtime_metrics"]:
        lines.append(
            "| "
            + " | ".join(
                cell(metric.get(k))
                for k in (
                    "provider",
                    "city",
                    "planned",
                    "failed",
                    "task_failure_rate",
                    "measured_runs",
                    "requests",
                    "request_failure_rate",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 比较（右侧减左侧）",
            "",
            "```json",
            __import__("json").dumps(comparison["contrasts"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## 全部任务",
            "",
            "| 任务 | 模型 | 城市 | 种子 | 状态 | 子研究 | 说明 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for run in batch["cells"]:
        lines.append(
            "| "
            + " | ".join(
                cell(run.get(k)) for k in ("id", "provider", "city", "seed", "status", "study_id", "error")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 排除与缺失",
            "",
            *[f"- {cell(i['cell_id'])}: {cell(i['reason'])}" for i in comparison["issues"]],
            "",
            "这些是指定模型与仿真配置下的结果，不能直接作为现实世界效力证据。",
        ]
    )
    return "\n".join(lines) + "\n"
