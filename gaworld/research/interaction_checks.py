"""Group-level evidence for peer feedback and short-context own-answer memory."""

from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from itertools import combinations

from gaworld.research import result_checks as rc
from gaworld.research.interaction_probe import ARMS

SCOPE = "仅检验结构化回答反馈与短期上下文记忆；群体一致不代表正确或无偏，不证明长期社会惯例。"
CONTRASTS = {
    "peer": ("同伴反馈（保留自己过往回答）", {"both": 1, "self": -1}, "both - self"),
    "memory": ("自己过往回答（保留同伴反馈）", {"both": 1, "peers": -1}, "both - peers"),
    "interaction": (
        "二者共同作用",
        {"both": 1, "self": -1, "peers": -1, "fresh": 1},
        "both - self - peers + fresh",
    ),
}


def normalize(raw):
    raw = raw if isinstance(raw, dict) else {}
    enabled = raw.get("enabled") is True
    result = {"enabled": enabled}
    for key, default, low, high in [("rounds", 1, 1, 3), ("group_size", 4, 2, 8)]:
        value = raw.get(key, default)
        valid = type(value) is int and low <= value <= high
        if enabled and not valid:
            raise ValueError(f"互动检查的 {key} 必须为 {low}–{high} 的整数")
        result[key] = value if valid else default
    return result


def partition(pairs, settings, seed):
    if not settings["enabled"]:
        return []
    conditions = defaultdict(list)
    for member, cid in pairs:
        conditions[cid].append(member)
    groups = []
    for cid, members in conditions.items():
        if len(set(members)) != len(members) or len(members) < 2:
            raise ValueError("互动检查每个条件至少两位不同居民")
        members = sorted(members)
        random.Random(f"feedback-groups:{seed}:{cid}").shuffle(members)
        count = math.ceil(len(members) / settings["group_size"])
        if len(members) // count < 2:
            raise ValueError("互动小组至少两位居民；请调大小组人数上限或调整样本量")
        for i in range(count):
            groups.append({"id": f"{cid}/IG{i + 1}", "condition": cid, "members": members[i::count]})
    return groups


def _index(rows):
    indexed = {(r["agent_id"], r["condition"]): r for r in rows}
    return indexed, len(indexed) == len(rows)


def _audit(spec, baseline, run):
    """Reject malformed/duplicate structure before interpreting repeated records."""
    if run.get("settings") != spec["interaction_probe"]:
        return None
    groups, rounds = run.get("groups") or [], run.get("rounds") or []
    if not groups or len(rounds) != spec["interaction_probe"]["rounds"]:
        return None
    membership = {}
    ids = set()
    for group in groups:
        if group["id"] in ids or len(group["members"]) < 2:
            return None
        ids.add(group["id"])
        for member in group["members"]:
            key = member, group["condition"]
            if key in membership:
                return None
            membership[key] = group["id"]
    base, unique = _index(baseline)
    if not unique or set(base) != set(membership):
        return None
    indexed_rounds = []
    for number, round_ in enumerate(rounds, 1):
        rows, unique = _index(round_.get("responses", []))
        if round_.get("round") != number or not unique or set(rows) != set(membership):
            return None
        if any(r.get("group") != membership[key] for key, r in rows.items()):
            return None
        indexed_rounds.append(rows)
    return base, indexed_rounds


def _value(record, item):
    value = (record.get("answers") or {}).get(item["id"])
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if item["kind"] == "choice":
        return value if value == int(value) and 0 <= value < len(item["options"]) else None
    if any(
        bound is not None and (value < bound if key == "min" else value > bound)
        for key in ("min", "max")
        for bound in [item.get(key)]
    ):
        return None
    return value


def _disagreement(values, nominal):
    return statistics.mean((a != b) if nominal else abs(a - b) for a, b in combinations(values, 2))


def _measure(item, cid, run, audited, family):
    groups = [g for g in (run.get("groups") or []) if isinstance(g, dict) and g.get("condition") == cid]
    evidence = {
        "unit": "group",
        "weighting": "equal group weights",
        "groups": len(groups),
        "final_round": len(run.get("rounds") or []),
        "scope": SCOPE,
    }
    if audited is None:
        return rc.check(
            "interaction",
            "insufficient",
            "分组、轮次或居民记录缺失、重复或不一致，不能推断。" + SCOPE,
            **evidence,
        )
    baseline, rounds = audited
    complete = []
    errors = 0
    for group in groups:
        keys = [(member, cid) for member in group["members"]]
        values = {"baseline": [_value(baseline[k], item) for k in keys]}
        for n, rows in enumerate(rounds, 1):
            for arm in ARMS:
                records = [rows[k].get("arms", {}).get(arm, {}) for k in keys]
                values[(n, arm)] = [_value(r, item) for r in records]
                errors += sum(bool(r.get("error")) for r in records)
        if all(v is not None for array in values.values() for v in array):
            complete.append(values)
    evidence.update(complete_groups=len(complete), missing_groups=len(groups) - len(complete), errors=errors)
    if not complete:
        return rc.check(
            "interaction",
            "insufficient",
            "没有完整小组；基线或任一轮任一路的缺答均计入缺失。" + SCOPE,
            **evidence,
        )
    nominal = item["kind"] == "choice"
    evidence["disagreement"] = {
        "units": "pairwise mismatch fraction" if nominal else "original item units",
        "baseline": statistics.mean(_disagreement(g["baseline"], nominal) for g in complete),
        "rounds": [
            {
                "round": n,
                **{
                    arm: statistics.mean(_disagreement(g[(n, arm)], nominal) for g in complete)
                    for arm in ARMS
                },
            }
            for n in range(1, len(rounds) + 1)
        ],
        "note": "完整小组内的两两分歧；下降仅表示更一致，不表示正确或无偏",
    }
    last = len(rounds)
    if nominal:
        evidence["option_shifts"] = {
            key: {
                label: statistics.mean(
                    sum(
                        weight * statistics.mean(v == index for v in g[(last, arm)])
                        for arm, weight in weights.items()
                    )
                    for g in complete
                )
                for index, label in enumerate(item["options"])
            }
            for key, (_, weights, _) in CONTRASTS.items()
        }
        return rc.check(
            "interaction",
            "observed",
            "单选题逐选项报告占比变化，不计算选项编号的均值或等价性。" + SCOPE,
            **evidence,
        )
    contrasts = {}
    for key, (label, weights, formula) in CONTRASTS.items():
        deltas = [
            sum(weight * statistics.mean(g[(last, arm)]) for arm, weight in weights.items()) for g in complete
        ]
        variance = statistics.variance(deltas) / len(deltas) if len(deltas) >= 2 else 0
        contrast = rc.interval_check(
            "interaction",
            statistics.mean(deltas),
            [(variance, len(deltas))],
            item.get("interaction_margin"),
            family=family,
        )
        contrast["label"] = label
        contrast["evidence"].update(contrast=formula, units=item.get("unit") or "原始题目单位", unit="group")
        if evidence["missing_groups"] and contrast["status"] == "stable":
            contrast.update(status="insufficient", detail="存在缺失小组，不能判断全部预设小组等价")
        contrasts[key] = contrast
    evidence["contrasts"] = contrasts
    statuses = [c["status"] for c in contrasts.values()]
    status = (
        "detected"
        if "detected" in statuses
        else "stable"
        if all(s == "stable" for s in statuses)
        else "insufficient"
    )
    detail = "分别检查同伴反馈、自己过往回答与二者共同作用；独立统计单位为小组。"
    if evidence["missing_groups"]:
        detail += "差值与区间仅针对全程完整的小组，不能代表缺失小组。"
    return rc.check("interaction", status, detail + SCOPE, **evidence)


def attach(comparison, spec, baseline, run):
    if not spec.get("interaction_probe", {}).get("enabled"):
        return comparison
    run = run if isinstance(run, dict) else {}
    try:
        audited = _audit(spec, baseline, run)
    except (KeyError, TypeError, ValueError):
        audited = None
    items = {i["id"]: i for i in spec["items"]}
    family = max(1, 3 * len(spec["conditions"]) * sum(i["kind"] != "choice" for i in spec["items"]))
    source = rc.fingerprint({"spec": spec, "baseline": baseline, "interaction_run": run})
    for row in comparison["cells"]:
        result = _measure(items[row["item"]], row["condition"], run, audited, family)
        card = row["result_checks"]
        card["checks"] = [result if c["id"] == "interaction" else c for c in card["checks"]]
        base_hash = card.setdefault("before_interaction_hash", card["source_hash"])
        card["source_hash"] = rc.fingerprint({"previous": base_hash, "interaction": source})
    return comparison
