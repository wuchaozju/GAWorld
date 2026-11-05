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


#: How each communication structure works, told to every member of that method.
_TOPOLOGY_TEXT = {
    "random": "成员之间按通信结构随机连接：每轮讨论时，每位成员只接收与自己在通信结构中直接相连的成员上一轮的结果。",
    "full": "全员互联：每轮讨论时，每位成员都能看到所有其他成员上一轮的结果。",
    "hierarchy": "层级组织：编号最小的成员与所有其他成员双向交换信息，其他成员之间不直接通信。",
    "independent": "独立作答后汇总：成员各自独立完成并提交终稿，彼此不交换中间结果。",
    "custom": "自定义通信：成员只在完整规则指定的有向边上交换上一轮的结果。",
}


def instructions(method) -> list[str]:
    """Operative instructions for one method: how it works, then its own rules.

    Every method gets the structural description, so a comparison is never
    between "an instructed team" and "an uninstructed team". A method's own
    rules (extracted from a paper, or written by the user) are appended
    after it and stay that method's alone.
    """
    topology = method.get("topology") or {}
    kind = topology.get("kind", "full")
    text = [_TOPOLOGY_TEXT.get(kind, _TOPOLOGY_TEXT["full"])]
    rounds = int(method.get("rounds") or 0)
    if kind == "independent" or rounds <= 0:
        text.append("不进行多轮讨论，每位成员各自给出结果。")
    else:
        text.append(f"共进行 {rounds} 轮讨论，每一轮只使用上一轮的结果。")
    if method.get("review"):
        text.append("讨论结束后由下一位成员交叉审阅上一位的成果，指出具体错误并给出可执行的修改建议。")
        revisions = int(method.get("revisions") or 0)
        if revisions:
            text.append(f"每位成员依据收到的审阅意见修订 {revisions} 次。")
    decision = method.get("decision") or "auto"
    if decision == "vote":
        text.append(
            "最终成果由成员投票产生：得票最多的答案生效；出现平票时由系统按固定顺序裁决，成员不得为此自行协商。"
        )
    elif decision == "synthesis":
        text.append("最终成果由第一位成员汇总所有终稿、独立检查矛盾后给出唯一答案。")
    else:
        text.append("最终成果的产生方式按题型由系统决定：选择题按成员投票，其他题由第一位成员汇总。")
    for rule in method.get("rules") or []:
        body = str(rule.get("text", "")).strip()
        if body:
            text.append(body)
    return text


def estimate(method, slots=None) -> dict:
    """Calls, prompt size and resource caps that fit one method's own shape.

    The caps used to be fixed numbers, so a twelve-member team with six
    discussion rounds could not fit a single prompt inside them and every
    cell failed. They are derived from the method instead:

    ``calls``        how many model requests one cell needs,
    ``output_chars`` how much text one cell may produce in total,
    ``prompt_chars`` the ceiling for a single prompt (base fields plus every
                     answer that can be in flight),
    ``input_chars``  the ceiling for one cell's total input: each produced
                     answer is quoted in at most one prompt per member.
    """
    roles = method.get("roles") or []
    count = int(slots or len(roles))
    rounds = int(method.get("rounds") or 0)
    review = bool(method.get("review"))
    revisions = int(method.get("revisions") or 0) if review else 0
    per_role = 1 + rounds + (1 if review else 0) + revisions
    calls = count * per_role + 1  # +1 for a synthesizing decision
    output_chars = calls * 4000
    prompt_chars = 12000 + output_chars
    return {
        "slots": count,
        "calls_per_cell": calls,
        "limits": {
            "calls": calls + 4,
            "prompt_chars": prompt_chars,
            "input_chars": count * output_chars + calls * 12000,
            "output_chars": output_chars,
        },
    }


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
