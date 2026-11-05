"""Predeclared artificial population, paired tasks and finite decision policies."""

import hashlib
import json

VERSION = "OI-2.0"
TITLE = "组织如何保存决策能力？"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def freeze(payload):
    if set(payload) - {"seed", "seeds"}:
        raise ValueError("OI-2只接受seed和seeds；此模板不调用模型")
    seed, seeds = payload.get("seed", 20261024), payload.get("seeds", 10)
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed必须为0到2147483647的整数")
    if type(seeds) is not int or not 1 <= seeds <= 100:
        raise ValueError("seeds必须为1到100的整数")
    return {
        "version": VERSION,
        "title": TITLE,
        "seed": seed,
        "seeds": list(range(seed, seed + seeds)),
        "training_tasks": 10,
        "test_tasks": 20,
        "cells": [
            {"id": f"P{p}M{m}T{t}", "procedure": p, "memory": m, "turnover": t}
            for p in (0, 1)
            for m in (0, 1)
            for t in (0, 1)
        ],
        "budget": {"external_calls": 0, "episodes": seeds * 200, "messages": 6, "checks": 2},
        "population": "三名同能力分布的人工角色：需求、道路、资源；未调用乌镇居民或LLM",
        "primary": "全员替换、证据程序：保留组织记忆减去移除组织记忆的净收益（按种子配对）",
        "learning": "只在训练时按所选方案公开的分项结果更新来源计数；测试期间不更新记忆",
        "costs": {"message": 0.08, "delay_per_step": 0.04, "check_costs": [0.3, 4.0]},
        "task_distribution": "四候选点、三分项；共同来源可靠率0.9/0.5/0.1随机置换，局部观测有噪声；核验成本交替；关键分项交替增强",
        "rules": {
            "P0": "三人各以局部观测和共同消息形成提案，等权投票；平票取最小候选编号",
            "P1": "六条报告按证据ID去重；来源后验加权；便宜且分歧大时至多核验两项，再按总效用决策",
            "M": "组织只存外部来源Beta计数；私人只存本角色观测Beta计数；初始均Beta(2,2)",
            "T": "训练状态克隆；全员更替只清除私人记忆，能力与外生噪声保持配对",
        },
        "scope": "研究者指定有限规则的机制模拟；不是实时LLM协商、制度内生形成或真人证据",
        "missing": "缺任一预注册episode或有重复时不计算处理效应，不补零，不拼接独立运行",
    }
