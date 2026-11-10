"""Simultaneous proposals and explicit signatures; narration never creates consent."""

from __future__ import annotations

import re
from typing import Any

INTENTS = {"propose", "accept", "reject", "ask", "respond", "maintain", "defer", "shelve", "withdraw"}


def normalize_policy(value: Any, roles: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("协商规则须为对象")
    ids = {r["id"] for r in roles}
    required = value.get("required_roles", [r["id"] for r in roles])
    withdrawals = value.get("withdrawal_roles", required)
    if (
        not isinstance(required, list)
        or not required
        or set(required) - ids
        or len(set(required)) != len(required)
    ):
        raise ValueError("协议必需主体无效")
    if not isinstance(withdrawals, list) or set(withdrawals) - ids:
        raise ValueError("退出权限无效")
    issues = value.get("issues", [])
    if (
        not isinstance(issues, list)
        or len(issues) > 12
        or any(not isinstance(i, str) or not i for i in issues)
    ):
        raise ValueError("协商议题须为最多12个非空标识")
    return {
        "required_roles": required,
        "withdrawal_roles": withdrawals,
        "issues": list(dict.fromkeys(issues)),
    }


def decision(value: Any, session: dict[str, Any], rid: str) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    intent = str(value.get("intent", "maintain"))
    if intent not in INTENTS:
        raise ValueError("行动意图无效")
    result: dict[str, Any] = {"intent": intent}
    if intent in {"propose", "accept", "reject"}:
        pid = str(value.get("proposal_id", ""))
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", pid):
            raise ValueError("需要有效提案id")
        result["proposal_id"] = pid
        if intent == "propose":
            terms = str(value.get("terms", "")).strip()[:1200]
            if not terms:
                raise ValueError("提案需要具体条款")
            issue = str(value.get("issue") or "main")[:60]
            issues = session["spec"]["negotiation"]["issues"]
            if issues and issue not in issues:
                raise ValueError("提案议题不在登记范围")
            result.update(terms=terms, issue=issue)
            old = session.get("proposals", {}).get(pid)
            if old and old["author"] != rid:
                raise ValueError("只能修改自己提出的提案；请另建提案")
        else:
            proposal = session.get("proposals", {}).get(pid)
            try:
                version = int(value.get("proposal_version", 0))
            except (ValueError, TypeError) as exc:
                raise ValueError("提案版本无效") from exc
            if not proposal or proposal["version"] != version:
                raise ValueError("请明确回应当前有效的提案版本")
            result["proposal_version"] = version
    if intent == "withdraw" and rid not in session["spec"]["negotiation"]["withdrawal_roles"]:
        raise ValueError("本角色没有登记的退出权限")
    target = str(value.get("target_role_id", ""))
    if target:
        if target not in {r["id"] for r in session["spec"]["roles"]}:
            raise ValueError("回应对象不存在")
        result["target_role_id"] = target
    facts = value.get("disclose_fact_ids", [])
    if not isinstance(facts, list):
        raise ValueError("披露信息须为id列表")
    role = next(r for r in session["spec"]["roles"] if r["id"] == rid)
    known = {f["id"]: f for f in role.get("private_facts", [])}
    if any(fid not in known or not known[fid]["disclosable"] for fid in facts):
        raise ValueError("不能披露不存在或受限制的私密事实")
    result["disclose_fact_ids"] = list(dict.fromkeys(facts))
    return result


def settle(session: dict[str, Any]) -> None:
    policy = session["spec"]["negotiation"]
    proposals = session.setdefault("proposals", {})
    decisions = {
        rid: move.get("decision", {"intent": "maintain"}) for rid, move in session["actions"].items()
    }
    proposed_ids = [d["proposal_id"] for d in decisions.values() if d["intent"] == "propose"]
    collisions = {pid for pid in proposed_ids if proposed_ids.count(pid) > 1}
    session["decision_errors"] = [
        {
            "role_id": rid,
            "proposal_id": d["proposal_id"],
            "reason": "同轮提案id冲突；双方须使用不同id重新提出",
        }
        for rid, d in decisions.items()
        if d["intent"] == "propose" and d["proposal_id"] in collisions
    ]
    changed = set()
    # All proposals are processed before signatures, independent of seat order.
    for rid, d in sorted(decisions.items()):
        if d["intent"] == "propose" and d["proposal_id"] not in collisions:
            pid = d["proposal_id"]
            old = proposals.get(pid)
            if old and old["terms"] == d["terms"] and old["issue"] == d["issue"]:
                continue
            proposals[pid] = {
                "id": pid,
                "author": rid,
                "terms": d["terms"],
                "issue": d["issue"],
                "version": (old["version"] + 1) if old else 1,
                "accepted_by": [],
                "rejected_by": [],
            }
            changed.add(pid)
    for rid, d in sorted(decisions.items()):
        if d["intent"] in {"accept", "reject"}:
            p = proposals.get(d["proposal_id"])
            if p and p["version"] == d["proposal_version"] and d["proposal_id"] not in changed:
                field = "accepted_by" if d["intent"] == "accept" else "rejected_by"
                opposite = "rejected_by" if field == "accepted_by" else "accepted_by"
                if rid not in p[field]:
                    p[field].append(rid)
                p[opposite] = [r for r in p[opposite] if r != rid]
        role = next(r for r in session["spec"]["roles"] if r["id"] == rid)
        for fact in role.get("private_facts", []):
            if fact["id"] in d.get("disclose_fact_ids", []):
                key = f"{rid}:{fact['id']}"
                session.setdefault("disclosed_facts", {})[key] = {
                    "role_id": rid,
                    "text": fact["text"],
                    "round": session["round_index"],
                }
    required = set(policy["required_roles"])
    accepted = [p for p in proposals.values() if required <= set(p["accepted_by"])]
    issues = set(policy["issues"] or ["main"])
    # A design without a fixed issue list accepts the single submitted issue.
    if not policy["issues"] and accepted:
        issues = {p["issue"] for p in accepted}
    covered = {p["issue"] for p in accepted}
    kind = "partial" if covered else "ongoing"
    if issues <= covered:
        kind = "agreement"
    # An authorized required party withdrawing prevents a joint agreement.
    if any(d["intent"] == "withdraw" and rid in required for rid, d in decisions.items()):
        kind = "breakdown"
    elif kind != "agreement" and all(decisions.get(rid, {}).get("intent") == "shelve" for rid in required):
        kind = "shelved"
    elif kind != "agreement" and all(decisions.get(rid, {}).get("intent") == "defer" for rid in required):
        kind = "deferred"
    session["outcome"] = {
        "kind": kind,
        "agreements": [p["id"] for p in accepted],
        "unresolved_issues": sorted(issues - covered),
        "source": "registered_rules",
    }
