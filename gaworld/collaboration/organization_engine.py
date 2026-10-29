"""Recipient-enforced synchronous execution with resumable per-call checkpoints."""

from __future__ import annotations

import json
import random
import time
from collections import Counter

from gaworld.collaboration._parsing import extract_json
from gaworld.collaboration.organization_methods import digest, normalize_method

VERSION = "organization-engine-1"


class BudgetExceeded(ValueError):
    """An experiment cell exhausted its predeclared resource limits."""


def execution_metrics(state, *, include_scoring=False):
    attempts = state.get("attempts", []) + (state.get("scoring_attempts", []) if include_scoring else [])
    return {
        "calls": len(attempts),
        "input_chars": sum(c.get("input_chars", 0) for c in attempts),
        "output_chars": sum(c.get("output_chars", 0) for c in attempts),
        "tokens": None,
        "elapsed": sum(c.get("elapsed", 0) for c in attempts),
    }


def edges(method, seed=0):
    n = len(method["roles"])
    topology = method["topology"]
    kind = topology["kind"]
    if kind == "custom":
        return [tuple(x) for x in topology["edges"]]
    rng = random.Random(seed)
    pairs = []
    for a in range(n):
        for b in range(a + 1, n):
            connect = (
                kind == "full"
                or (kind == "hierarchy" and a == 0)
                or (kind == "random" and rng.random() < topology["probability"])
            )
            if connect:
                pairs.extend(((a, b), (b, a)))
    return pairs


def run_method(
    method, members, task, llm, *, seed=0, limits=None, state=None, checkpoint=None, before_call=None
):
    method = normalize_method(method)
    if len(members) != len(method["roles"]):
        raise ValueError("所选居民人数与组织角色数量不符")
    if set(task) - {"id", "prompt", "options", "observations", "response_format"}:
        raise ValueError("执行输入包含未授权的评分或隐藏数据")
    caps = {"calls": 200, "prompt_chars": 40000, "input_chars": 500000, "output_chars": 12000}
    if set(limits or {}) - set(caps):
        raise ValueError("不支持的资源上限")
    caps.update(limits or {})
    for key, value in caps.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"资源上限不合法：{key}")
    state = state if state is not None else {}
    signature = digest(
        {"method": method, "members": members, "task": task, "seed": seed, "limits": caps, "engine": VERSION}
    )
    if state.get("signature", signature) != signature:
        raise ValueError("恢复时组织、题目、成员或限制发生变化")
    state["signature"] = signature
    calls = state.setdefault("calls", [])
    attempts = state.setdefault("attempts", [])
    cursor = 0
    graph = edges(method, seed)
    observations = task.get("observations") or [""] * len(members)
    if len(observations) != len(members):
        raise ValueError("局部信息数量必须等于组织角色数量")

    def ask(slot, phase, messages, own=None):
        nonlocal cursor
        if before_call:
            before_call()
        instruction = "按自己的角色和可见信息完成任务。仅输出JSON：answer（最终答案或结构化对象）、message（给团队的简短说明）。"
        if phase == "review":
            instruction = "审阅 messages 中提交的成果，指出具体错误和可执行的修改建议。仅输出JSON：answer（建议答案）、message（审阅意见）。"
        elif phase == "revise":
            instruction = "根据 messages 的审阅意见修订 own 中的成果。仅输出JSON：answer（修订后的答案）、message（修改说明）。"
        elif phase == "synthesis":
            instruction = "汇总 messages 中的成员终稿，独立检查矛盾后给出唯一最终成果，不再追问。仅输出JSON：answer（完整最终答案或成果）、message（汇总说明）。"
        payload = {
            "task": {k: task[k] for k in ("id", "prompt", "options", "response_format") if k in task},
            "member": members[slot],
            "role": method["roles"][slot],
            "observation": observations[slot],
            "phase": phase,
            "messages": messages,
            "own": own,
            "instruction": instruction,
        }
        prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        fingerprint = digest(prompt)
        if cursor < len(calls):
            item = calls[cursor]
            if item["prompt_hash"] != fingerprint:
                raise ValueError("恢复调用与保存记录不一致")
        else:
            if (
                len(attempts) >= caps["calls"]
                or len(prompt) > caps["prompt_chars"]
                or sum(c["input_chars"] for c in attempts) + len(prompt) > caps["input_chars"]
            ):
                raise BudgetExceeded("本题已达到保存的调用或上下文上限")
            started = time.monotonic()
            item = {
                "prompt_hash": fingerprint,
                "prompt": prompt,
                "response": "",
                "agent_id": members[slot]["id"],
                "phase": phase,
                "input_chars": len(prompt),
                "output_chars": 0,
                "elapsed": 0,
                "status": "started",
            }
            attempts.append(item)
            if checkpoint:
                checkpoint(state, item)
            try:
                raw = str(llm(prompt, agent_id=members[slot]["id"]))
            except Exception as exc:
                item.update(status="failed", error=type(exc).__name__, elapsed=time.monotonic() - started)
                if checkpoint:
                    checkpoint(state, item)
                raise
            item.update(
                response=raw, output_chars=len(raw), elapsed=time.monotonic() - started, status="completed"
            )
            calls.append(item)
            if checkpoint:
                checkpoint(state, item)
        cursor += 1
        if item["output_chars"] > caps["output_chars"]:
            raise BudgetExceeded("模型回答超过保存的输出长度上限")
        try:
            parsed = extract_json(item["response"])
        except (ValueError, TypeError):
            parsed = {}
        return {"answer": parsed.get("answer"), "message": str(parsed.get("message", ""))[:4000]}

    current = [ask(i, "private", []) for i in range(len(members))]
    for _ in range(method["rounds"]):
        previous = current
        current = [
            ask(
                i,
                "communicate",
                [{"sender": members[j]["id"], **previous[j]} for j in range(len(members)) if (j, i) in graph],
                previous[i],
            )
            for i in range(len(members))
        ]
    if method["review"]:
        reviews = [
            ask((i + 1) % len(members), "review", [{"sender": members[i]["id"], **current[i]}])
            for i in range(len(members))
        ]
        for _ in range(method["revisions"]):
            current = [
                ask(
                    i, "revise", [{"sender": members[(i + 1) % len(members)]["id"], **reviews[i]}], current[i]
                )
                for i in range(len(members))
            ]
    decision = method["decision"]
    if decision == "auto":
        decision = "vote" if task.get("options") else "synthesis"
    if decision == "vote":
        candidates = [
            json.dumps(x["answer"], sort_keys=True, ensure_ascii=False)
            for x in current
            if x["answer"] is not None
        ]
        counts = Counter(candidates)
        winner = min(counts, key=lambda x: (-counts[x], x)) if counts else "null"
        answer = {"answer": json.loads(winner)}
    else:
        answer = ask(
            0, "synthesis", [{"sender": members[i]["id"], **value} for i, value in enumerate(current)]
        )
    return {
        "answer": answer,
        "edges": [list(x) for x in graph],
        "engine_version": VERSION,
        "method_hash": digest(method),
        "metrics": {
            "calls": len(attempts),
            "input_chars": sum(c["input_chars"] for c in attempts),
            "output_chars": sum(c["output_chars"] for c in attempts),
            "tokens": None,
            "elapsed": sum(c["elapsed"] for c in attempts),
        },
        "state": state,
    }
