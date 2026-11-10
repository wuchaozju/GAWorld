"""Deterministic, evidence-based one-to-one casting for serious games."""

from __future__ import annotations

import random
import re
from typing import Any

OPS = {"eq", "ne", "in", "contains", "gte", "lte"}


def validate_conditions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("资格条件须为不超过20项的列表")
    result = []
    for item in value:
        if not isinstance(item, dict) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,59}", str(item.get("field", ""))
        ):
            raise ValueError("资格字段须为英文标识")
        if item.get("op") not in OPS or "value" not in item:
            raise ValueError("资格条件的操作或比较值无效")
        if item["op"] == "in" and not isinstance(item["value"], list):
            raise ValueError("in 条件需要列表")
        result.append({k: item[k] for k in ("field", "op", "value")})
    return result


def satisfies(person: dict[str, Any], condition: dict[str, Any]) -> bool:
    actual = person.get(condition["field"])
    if actual is None or actual == "":
        return False
    expected, op = condition["value"], condition["op"]
    try:
        if op == "eq":
            return type(actual) is type(expected) and actual == expected  # bool is not an integer fact
        if op == "ne":
            return actual != expected
        if op == "in":
            return actual in expected
        if op == "contains":
            return str(expected).casefold() in str(actual).casefold()
        if op == "gte":
            return float(actual) >= float(expected)
        if op == "lte":
            return float(actual) <= float(expected)
    except (TypeError, ValueError):
        return False
    return False


def match_roles(
    roles: list[dict[str, Any]],
    people: list[dict[str, Any]],
    *,
    seed: int = 0,
    selected: dict[str, int] | None = None,
    mode: str = "matched",
    assumptions: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Use augmenting paths so an easy seat cannot consume a uniquely eligible resident.

    Preferences order candidates; hard eligibility always wins over preference.
    Explicit assumptions are per role and never modify a population row.
    """
    if mode not in {"matched", "roleplay"}:
        raise ValueError("身份安排方式无效")
    selected = {k: int(v) for k, v in (selected or {}).items()}
    if len(set(selected.values())) != len(selected):
        raise ValueError("同一居民不能重复入座")
    if set(selected) - {r["id"] for r in roles}:
        raise ValueError("指定了不存在的角色")
    by_id = {int(p.get("id", p.get("agent_id"))): p for p in people}
    rng = random.Random(int(seed))
    ordered = sorted(by_id)
    rng.shuffle(ordered)
    candidates: dict[str, list[int]] = {}
    evidence: dict[tuple[str, int], dict[str, Any]] = {}
    for role in roles:
        rid = role["id"]
        conditions = validate_conditions(role.get("eligibility", []))
        prefs = validate_conditions(role.get("preferences", []))
        facts = (assumptions or {}).get(rid, {})
        if not isinstance(facts, dict) or set(facts) & {"id", "agent_id", "name", "age", "gender", "job"}:
            raise ValueError("情境假设不能改写居民身份")
        valid = []
        for aid in ordered:
            person = {**by_id[aid], **facts}
            unknown = [c["field"] for c in conditions if person.get(c["field"]) in (None, "")]
            required = [f for f in role.get("required_facts", []) if person.get(f) in (None, "")]
            if mode == "matched" and (
                unknown or required or not all(satisfies(person, c) for c in conditions)
            ):
                continue
            evidence[rid, aid] = {
                "conditions": conditions,
                "assumptions": facts,
                "reason": "角色扮演（不要求背景一致）"
                if mode == "roleplay"
                else "满足登记资格"
                if conditions
                else "未设硬性资格",
                "unknown": sorted(set(unknown + required)),
            }
            valid.append(aid)
        valid.sort(key=lambda aid: -sum(satisfies({**by_id[aid], **facts}, c) for c in prefs))
        if rid in selected:
            valid = [selected[rid]] if selected[rid] in valid else []
        if not valid:
            raise ValueError(f"{role['name']}没有满足资格的候选居民；请补充证据/本局假设，或调整资格")
        candidates[rid] = valid
    assigned: dict[int, str] = {}

    def place(rid: str, visited: set[int]) -> bool:
        for aid in candidates[rid]:
            if aid in visited:
                continue
            visited.add(aid)
            previous = assigned.get(aid)
            if previous is None or (previous not in selected and place(previous, visited)):
                assigned[aid] = rid
                return True
        return False

    for role in sorted(roles, key=lambda r: (r["id"] not in selected, len(candidates[r["id"]]))):
        if not place(role["id"], set()):
            raise ValueError("资格匹配无法为所有角色找到不同的候选居民")
    reverse = {rid: aid for aid, rid in assigned.items()}
    return [
        {
            "role_id": r["id"],
            "agent_id": reverse[r["id"]],
            "resident": by_id[reverse[r["id"]]],
            **evidence[r["id"], reverse[r["id"]]],
        }
        for r in roles
    ]
