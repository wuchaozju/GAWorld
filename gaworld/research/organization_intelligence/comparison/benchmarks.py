"""Versioned data-only benchmarks; hidden references never enter actor inputs."""

from __future__ import annotations

import csv
import io
import itertools
import json
import math
import random

from gaworld.collaboration._parsing import extract_json
from gaworld.collaboration.organization_methods import digest, integer

VERSION = "organization-benchmark-1"


def validate(tasks, name="导入题库", scorer="exact"):
    if scorer not in {"exact", "choice", "allocation", "rubric"}:
        raise ValueError("不支持的评分器")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 1000:
        raise ValueError("题库需要 1–1000 道题")
    result, seen = [], set()
    allowed = {
        "id",
        "category",
        "prompt",
        "options",
        "reference",
        "observations",
        "constraints",
        "rubric",
        "scorer",
    }
    for index, raw in enumerate(tasks):
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise ValueError(f"第 {index + 1} 题包含不支持的字段；只允许题目数据")
        q = dict(raw)
        for key in ("id", "category", "prompt"):
            if not isinstance(q.get(key), str) or not q[key].strip() or len(q[key]) > 20000:
                raise ValueError(f"第 {index + 1} 题缺少合法的 {key}")
        if q["id"] in seen:
            raise ValueError("题目 ID 重复：" + q["id"])
        seen.add(q["id"])
        q["scorer"] = scorer
        if scorer != "rubric" and "reference" not in q:
            raise ValueError("题目缺少 reference 参考答案")
        if scorer == "rubric" and not str(q.get("rubric", "")).strip():
            raise ValueError("开放题必须提供 rubric 评分量表（0–1）")
        if scorer == "choice" and (not q.get("options") or q["reference"] not in q["options"]):
            raise ValueError("选择题需要非空选项及其中一个参考答案")
        if "observations" in q and (
            not isinstance(q["observations"], list) or not all(isinstance(x, str) for x in q["observations"])
        ):
            raise ValueError("observations 必须是每位成员各一段文字的列表")
        if "options" in q and not isinstance(q["options"], (dict, list)):
            raise ValueError("options 必须是选项列表或对象")
        if scorer == "allocation":
            c = q.get("constraints", {})
            if (
                not isinstance(c, dict)
                or not isinstance(c.get("costs"), list)
                or not isinstance(c.get("values"), list)
                or len(c["costs"]) != len(c["values"])
                or not 1 <= len(c["costs"]) <= 16
                or any(
                    type(x) not in (int, float) or not math.isfinite(x) or x < 0
                    for x in c["costs"] + c["values"]
                )
                or type(c.get("capacity")) not in (int, float)
                or c["capacity"] < 0
                or type(c.get("optimum")) not in (int, float)
                or c["optimum"] <= 0
            ):
                raise ValueError("资源分配题缺少合法的 costs/values/capacity/optimum 约束")
            if not math.isfinite(c["capacity"]) or not math.isfinite(c["optimum"]):
                raise ValueError("约束和目标值必须是有限数")
            optimum = max(
                sum(c["values"][j] for j in subset)
                for n in range(len(c["costs"]) + 1)
                for subset in itertools.combinations(range(len(c["costs"])), n)
                if sum(c["costs"][j] for j in subset) <= c["capacity"]
            )
            if not math.isclose(optimum, c["optimum"], rel_tol=1e-9):
                raise ValueError("提供的 optimum 与约束下的实际最优值不一致")
        result.append(q)
    bank = {
        "version": VERSION,
        "name": str(name)[:200],
        "scorer": scorer,
        "range": [0, 1],
        "direction": "higher",
        "failure_score": 0,
        "tasks": result,
    }
    return {**bank, "hash": digest(bank)}


def import_data(text, fmt="jsonl", mapping=None, *, name="导入题库", scorer="exact"):
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError("题库文件过大")
    if fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    elif fmt == "jsonl":
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError("JSONL 解析失败") from exc
    else:
        raise ValueError("只支持 JSONL 和 CSV")
    tasks = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("每题需要 JSON 对象")
        if mapping:
            names = {
                key: key
                for key in (
                    "id",
                    "category",
                    "prompt",
                    "reference",
                    "options",
                    "observations",
                    "constraints",
                    "rubric",
                )
            }
            names.update(mapping)
            row = {target: row[source] for target, source in names.items() if source in row}
        row = dict(row)
        if fmt == "csv":
            for field in ("observations", "options", "constraints", "reference"):
                if field in row:
                    try:
                        row[field] = json.loads(row[field])
                    except (ValueError, TypeError):
                        if field in {"observations", "options", "constraints"}:
                            raise ValueError(f"CSV 的 {field} 需要 JSON 格式") from None
        tasks.append(row)
    return validate(tasks, name, scorer)


def builtin(kind="information", count=30, slots=3, seed=20261026):
    integer(count, "题数", 1, 1000)
    integer(slots, "人数", 2, 12)
    if kind not in {"information", "allocation"}:
        raise ValueError("题库类型不存在")
    rng, tasks = random.Random(seed), []
    for i in range(count):
        if kind == "information":
            values = [[rng.randint(0, 20) for _ in range(slots)] for _ in range(4)]
            labels = list("ABCD")
            best = max(range(4), key=lambda j: (sum(values[j]), -j))
            tasks.append(
                {
                    "id": f"info-{i}",
                    "category": "分散信息整合",
                    "prompt": "选择总收益最高的方案，收益为各成员掌握的分项之和。并列取字母最小。answer填写选项字母。",
                    "options": labels,
                    "reference": labels[best],
                    "observations": [
                        json.dumps({labels[j]: values[j][k] for j in range(4)}) for k in range(slots)
                    ],
                }
            )
        else:
            costs = [rng.randint(1, 6) for _ in range(5)]
            values = [rng.randint(1, 20) for _ in range(5)]
            capacity = max(costs)
            possibilities = [
                list(x)
                for n in range(6)
                for x in itertools.combinations(range(5), n)
                if sum(costs[j] for j in x) <= capacity
            ]
            best = max(possibilities, key=lambda x: sum(values[j] for j in x))
            constraints = {
                "costs": costs,
                "values": values,
                "capacity": capacity,
                "optimum": sum(values[j] for j in best),
            }
            tasks.append(
                {
                    "id": f"allocation-{i}",
                    "category": "约束资源分配",
                    "prompt": f"从编号0–4的项目中选择若干个，在预算{capacity}内最大化收益。每项目最多一次。answer填写项目编号列表。",
                    "reference": best,
                    "constraints": constraints,
                    "observations": [
                        json.dumps(
                            {
                                str(j): {"cost": costs[j], "value": values[j]}
                                for j in range(5)
                                if j % slots == k
                            }
                        )
                        for k in range(slots)
                    ],
                }
            )
    return validate(
        tasks,
        "分散信息整合" if kind == "information" else "约束资源分配",
        "choice" if kind == "information" else "allocation",
    )


def public_task(task, slots):
    observations = task.get("observations") or [""] * slots
    if len(observations) != slots:
        raise ValueError("题目局部信息与成员数量不符")
    return {
        "id": task["id"],
        "prompt": task["prompt"],
        "observations": observations,
        **({"options": task["options"]} if "options" in task else {}),
    }


def score(task, result, *, judge=None):
    answer = result.get("answer") if isinstance(result, dict) else None
    scorer = task.get("scorer", "exact")
    valid = answer is not None
    if not valid:
        return {"score": 0.0, "valid": False, "scorer": scorer}
    value = 0.0
    if scorer in {"choice", "exact"}:
        if scorer == "choice":
            valid = any(type(answer) is type(option) and answer == option for option in task["options"])
        value = float(valid and digest(answer) == digest(task["reference"]))
    elif scorer == "allocation":
        c = task["constraints"]
        valid = (
            isinstance(answer, list)
            and all(type(j) is int and 0 <= j < len(c["costs"]) for j in answer)
            and len(answer) == len(set(answer))
        )
        if valid:
            valid = sum(c["costs"][j] for j in answer) <= c["capacity"]
        value = sum(c["values"][j] for j in answer) / c["optimum"] if valid else 0.0
    elif scorer == "rubric":
        if judge is None:
            raise ValueError("开放题需要固定的评审模型")
        raw = judge(
            json.dumps(
                {
                    "task": task["prompt"],
                    "rubric": task["rubric"],
                    "response": answer,
                    "instruction": "按量表评分，仅输出JSON：score（0至1），reason。",
                },
                ensure_ascii=False,
            )
        )
        value = extract_json(raw).get("score")
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError("评审模型没有给出合法分数")
    return {"score": float(value), "valid": valid, "scorer": scorer}
