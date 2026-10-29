"""Finite, versioned organization rules shared by experiments and cooperation."""

from __future__ import annotations

import hashlib
import json

VERSION = "organization-method-1"
KINDS = {"random": "随机网络", "full": "全员互联", "hierarchy": "层级组织", "independent": "独立作答后汇总"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} 必须是 {low}–{high} 的整数")
    return value


def baseline(kind="random", slots=3):
    if kind not in KINDS:
        raise ValueError("不支持的基本组织方式")
    return normalize_method(
        {
            "name": KINDS[kind],
            "roles": [f"成员 {i + 1}" for i in range(slots)],
            "topology": {"kind": kind},
            "rounds": 0 if kind == "independent" else 2,
        }
    )


def normalize_method(payload):
    if not isinstance(payload, dict):
        raise ValueError("组织方式必须是对象")
    if payload.get("version", VERSION) != VERSION:
        raise ValueError("不支持该组织方式版本")
    if type(payload.get("review", False)) is not bool:
        raise ValueError("review 必须为布尔值")
    if payload.get("revisions", 0) and not payload.get("review", False):
        raise ValueError("修订必须先开启审阅")
    allowed = {
        "version",
        "name",
        "roles",
        "topology",
        "rounds",
        "decision",
        "review",
        "revisions",
        "rules",
        "source",
        "unsupported",
        "memory",
        "description",
    }
    if set(payload) - allowed:
        raise ValueError("存在不支持的组织规则字段：" + ", ".join(sorted(set(payload) - allowed)))
    if payload.get("unsupported") or payload.get("memory", "reset") != "reset":
        raise ValueError("本版暂不支持：" + str(payload.get("unsupported") or "跨题学习或成员更替"))
    roles = payload.get("roles", ["分析", "核对", "决策"])
    if not isinstance(roles, list) or not 2 <= len(roles) <= 12:
        raise ValueError("组织需要 2–12 个角色槽位")
    if any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in roles):
        raise ValueError("每个角色必须是 1–500 字的文字")
    topology = payload.get("topology", {"kind": "full"})
    if not isinstance(topology, dict) or topology.get("kind") not in {*KINDS, "custom"}:
        raise ValueError("不支持的通信结构")
    if set(topology) - {"kind", "probability", "edges"}:
        raise ValueError("不支持的通信参数")
    probability = topology.get("probability", 0.5)
    if type(probability) not in (int, float) or not 0 <= probability <= 1:
        raise ValueError("连边概率必须在 0–1 之间")
    connections = topology.get("edges", [])
    if not isinstance(connections, list) or len(connections) > 144:
        raise ValueError("通信边不合法")
    for edge in connections:
        if not isinstance(edge, list) or len(edge) != 2:
            raise ValueError("通信边需要两个角色槽位编号（从0开始）")
        for slot in edge:
            integer(slot, "角色槽位", 0, len(roles) - 1)
        if edge[0] == edge[1]:
            raise ValueError("不能向自身连边")
    decision = payload.get("decision", "auto")
    if decision not in {"auto", "vote", "synthesis"}:
        raise ValueError("不支持的决策规则")
    rules = payload.get("rules", [])
    if not isinstance(rules, list) or len(rules) > 40:
        raise ValueError("规则来源列表不合法")
    clean_rules = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("origin") not in {"source", "inferred", "user"}:
            raise ValueError("规则必须标明 source/inferred/user 来源")
        clean_rules.append({k: str(rule.get(k, ""))[:4000] for k in ("text", "quote", "origin")})
    source = payload.get("source", {})
    if not isinstance(source, dict):
        raise ValueError("材料来源必须是对象")
    return {
        "version": VERSION,
        "name": str(payload.get("name") or "新的组织方式")[:120],
        "description": str(payload.get("description", ""))[:2000],
        "roles": [r.strip() for r in roles],
        "topology": {
            "kind": topology["kind"],
            "probability": float(probability),
            "edges": sorted([list(x) for x in set(map(tuple, connections))]),
        },
        "rounds": integer(payload.get("rounds", 2), "讨论轮数", 0, 6),
        "decision": decision,
        "review": bool(payload.get("review", False)),
        "revisions": integer(payload.get("revisions", 0), "修订次数", 0, 2),
        "memory": "reset",
        "rules": clean_rules,
        "source": {"title": str(source.get("title", ""))[:500], "text": str(source.get("text", ""))[:60000]},
        "unsupported": [],
    }


def method_hash(method):
    return digest(normalize_method(method))
