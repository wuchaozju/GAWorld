"""Freeze the OI-1 exploratory protocol, population and generated task bank."""

from __future__ import annotations

import copy
import hashlib
import json
import random

VERSION = "OI-1.1"
TITLE = "人换了，组织还会吗？"
ARMS = {
    "incumbent_archive": "原成员 · 保留组织档案",
    "incumbent_no_archive": "原成员 · 移除组织档案",
    "replacement_archive": "全员更替 · 保留组织档案",
    "replacement_no_archive": "全员更替 · 移除组织档案",
    "independent": "独立判断 · 固定规则汇总",
    "pooled": "单智能体 · 集中全部信息",
}
LIMIT = "探索性人工组织实验；不检验一般智能或现实组织效能。三组重复不支持显著性结论。"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def integer(payload, key, default, low, high):
    value = payload.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} 必须是 {low}–{high} 的整数")
    return value


def freeze(payload, people, model):
    repeats = integer(payload, "repeats", 3, 1, 20)
    seed = integer(payload, "seed", 20261020, 0, 2**31 - 100)
    adults = [copy.deepcopy(p) for p in people if int(p.get("age") or 0) >= 18]
    if len({p["id"] for p in adults}) != len(adults) or len(adults) < 6:
        raise ValueError("需要至少 6 位编号唯一的成年居民；不重复抽样或补造居民")
    blocks = []
    for b in range(repeats):
        rng = random.Random(seed + b)
        selected = rng.sample(adults, 6)
        weights = rng.sample([1, 3, 7], 3)
        tasks, seen = [], set()
        while len(tasks) < 6:
            options = [[rng.randint(1, 9) for _ in range(3)] for _ in range(4)]
            if digest(options) in seen:
                continue
            seen.add(digest(options))
            utilities = [sum(w * v for w, v in zip(weights, row, strict=True)) for row in options]
            tasks.append({"id": f"b{b}-t{len(tasks)}", "options": options, "utilities": utilities})
        order = list(ARMS)
        rng.shuffle(order)
        training_order = ["organized", "independent", "pooled"]
        rng.shuffle(training_order)
        blocks.append(
            {
                "id": b,
                "seed": seed + b,
                "incumbents": selected[:3],
                "replacements": selected[3:],
                "weights": weights,
                "tasks": tasks,
                "test_order": order,
                "training_order": training_order,
            }
        )
    return {
        "version": VERSION,
        "title": TITLE,
        "kind": "exploratory",
        "seed": seed,
        "repeats": repeats,
        "city": str(payload.get("city") or ""),
        "model": copy.deepcopy(model),
        "train_tasks": 3,
        "test_tasks": 3,
        "turnover": 1.0,
        "temperature": 0.3,
        "max_tokens": 2048,
        "max_prompt_chars": 60000,
        "archive_chars": 1800,
        "arms": ARMS.copy(),
        "blocks": blocks,
        "population_hash": digest(adults),
        "budget": {
            "requests": repeats * 109,
            "max_output_tokens": repeats * 109 * 2048,
            "archive_requests": repeats,
            "retries": 0,
            "fallback": False,
        },
        "primary": "每组、每条件三个留出任务的平均 chosen_utility / optimal_utility",
        "secondary": "最优选择率；实际请求、HTTP 尝试、输入输出字符数（不是 token 或金额）",
        "limitations": LIMIT,
        "design": "训练后冻结记忆；测试不反馈答案。原成员保留各自经验；新成员无私人经验。"
        "组织档案是额外的一次归纳调用，其成本单列。基线每题同为四次调用，实际输入长度并不相同。",
    }
