"""Versioned indicator definitions and finite, auditable payoff rules. No eval."""

from __future__ import annotations

import math
import random
from typing import Any


def finite(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("规则数值无效") from exc
    if not math.isfinite(result):
        raise ValueError("规则数值必须有限")
    return result


def private_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > 20:
        raise ValueError("私人状态须为不超过20项的字典")
    result = {}
    for key, item in value.items():
        if not isinstance(item, dict) or not item.get("source") or not item.get("unit"):
            raise ValueError("私人收益/风险必须注明来源和单位")
        row = {
            "value": finite(item.get("value")),
            "unit": str(item["unit"])[:40],
            "source": str(item["source"])[:240],
            "description": str(item.get("description", ""))[:400],
        }
        for bound in ("min", "max"):
            if bound in item:
                row[bound] = finite(item[bound])
        if row.get("min", -math.inf) > row["value"] or row.get("max", math.inf) < row["value"]:
            raise ValueError("私人状态超出登记范围")
        result[str(key)] = row
    return result


def comparable(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = ("concept_id", "definition_version", "description", "unit", "method", "min", "max", "direction")
    return all(a.get(k) not in (None, "") and a.get(k) == b.get(k) for k in keys)


def normalize_rules(
    rules: Any, roles: list[dict[str, Any]], indicators: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(rules, list) or len(rules) > 40:
        raise ValueError("规则须为不超过40项的列表")
    targets = {f"indicator:{i['id']}" for i in indicators}
    targets |= {f"private:{r['id']}:{key}" for r in roles for key in r.get("private_state", {})}
    role_ids = {r["id"] for r in roles}
    seen, result = set(), []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("无效的收益规则")
        rid = str(rule.get("id", ""))
        if not rid or rid in seen or not rule.get("source") or rule.get("target") not in targets:
            raise ValueError("规则需要唯一id、来源和有效目标")
        if rule.get("actor") not in role_ids or rule.get("intent") not in {
            "propose",
            "accept",
            "reject",
            "ask",
            "respond",
            "maintain",
            "defer",
            "shelve",
            "withdraw",
        }:
            raise ValueError("规则需要有效角色与行动意图")
        op = rule.get("op", "add")
        if op not in {"add", "transfer", "risk"}:
            raise ValueError("规则操作仅支持add/transfer/risk")
        clean = {
            "id": rid,
            "actor": rule["actor"],
            "intent": rule["intent"],
            "op": op,
            "target": rule["target"],
            "delta": finite(rule.get("delta", 0)),
            "source": str(rule["source"])[:240],
            "once": bool(rule.get("once", True)),
        }
        if op == "transfer":
            other = str(rule.get("from", ""))
            if (
                not other.startswith("private:")
                or other not in targets
                or not clean["target"].startswith("private:")
            ):
                raise ValueError("转移规则需要两个私人资源账户")
            if clean["delta"] < 0:
                raise ValueError("转移量不能为负数")
            if other == clean["target"]:
                raise ValueError("资源不能转移给同一账户")
            role_by_id = {r["id"]: r for r in roles}
            src = other.split(":")
            dst = clean["target"].split(":")
            if (
                role_by_id[src[1]]["private_state"][src[2]]["unit"]
                != role_by_id[dst[1]]["private_state"][dst[2]]["unit"]
            ):
                raise ValueError("资源转移单位不一致")
            clean["from"] = other
        if op == "risk":
            p = finite(rule.get("probability"))
            if not 0 <= p <= 1:
                raise ValueError("风险概率须在0至1之间，未知概率不能估计")
            clean["probability"] = p
        condition = rule.get("condition")
        if condition:
            if (
                not isinstance(condition, dict)
                or condition.get("target") not in targets
                or condition.get("op") not in {"gte", "lte"}
            ):
                raise ValueError("阈值条件需要有效目标与gte/lte")
            clean["condition"] = {
                "target": condition["target"],
                "op": condition["op"],
                "value": finite(condition.get("value")),
            }
        seen.add(rid)
        result.append(clean)
    return result


def apply_rules(session: dict[str, Any]) -> list[dict[str, Any]]:
    """All registered targets are authoritative, even when no rule fires."""

    def cell(target: str) -> tuple[dict[str, Any], str, float, float, str]:
        parts = target.split(":")
        if parts[0] == "indicator":
            ind = next(i for i in session["spec"]["indicators"] if i["id"] == parts[1])
            return session["indicators"], parts[1], ind["min"], ind["max"], ind.get("unit", "")
        item = session["private_state"][parts[1]][parts[2]]
        return item, "value", item.get("min", -math.inf), item.get("max", math.inf), item["unit"]

    audit = []
    applied = session.setdefault("applied_rules", [])
    for rule in session["spec"].get("rules", []):
        decision = session["actions"].get(rule["actor"], {}).get("decision", {})
        if decision.get("intent") != rule["intent"] or (rule["once"] and rule["id"] in applied):
            continue
        # Accept-triggered payoffs require a valid signature on the current version.
        if rule["intent"] == "accept":
            proposal = session.get("proposals", {}).get(decision.get("proposal_id"), {})
            if rule["actor"] not in proposal.get("accepted_by", []):
                continue
        condition = rule.get("condition")
        if condition:
            container, key, _, _, _ = cell(condition["target"])
            if (condition["op"] == "gte" and container[key] < condition["value"]) or (
                condition["op"] == "lte" and container[key] > condition["value"]
            ):
                continue
        before_rng = random.Random(f"{session.get('seed', 0)}:{session['round_index']}:{rule['id']}")
        fired = rule["op"] != "risk" or before_rng.random() < rule["probability"]
        container, key, low, high, unit = cell(rule["target"])
        before = container[key]
        delta = rule["delta"] if fired else 0
        delta = min(high - before, max(low - before, delta))
        if rule["op"] == "transfer":
            origin, origin_key, origin_low, _, origin_unit = cell(rule["from"])
            if origin_unit != unit:
                raise ValueError("资源转移单位不一致")
            delta = max(0, min(delta, origin[origin_key] - max(0, origin_low)))
            origin[origin_key] -= delta
        container[key] = round(before + delta, 6)
        applied.append(rule["id"])
        audit.append(
            {
                "rule_id": rule["id"],
                "target": rule["target"],
                "before": before,
                "after": container[key],
                "delta": delta,
                "source": rule["source"],
                "fired": fired,
                **({"from": rule["from"]} if "from" in rule else {}),
            }
        )
    return audit
