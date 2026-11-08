"""Matched target/context identity cues; no persona rewriting or fairness verdicts."""

from __future__ import annotations

import copy
import math
import random
import statistics
from collections import defaultdict
from typing import Any

from gaworld.research import result_checks as rc

TOKEN = "{{identity}}"
LIMITS = {"template": 2000, "a": 100, "b": 100}
SCOPE = "只反映这组材料的身份线索敏感性，不自动说明不公正；受访居民自身档案未改变。"


def normalize(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    result = {"enabled": raw.get("enabled") is True}
    for field, limit in LIMITS.items():
        value = raw.get(field, "")
        if result["enabled"] and (not isinstance(value, str) or len(value.strip()) > limit):
            raise ValueError(f"身份检查的 {field} 必须是最多 {limit} 字符的文字")
        result[field] = value.strip()[:limit] if isinstance(value, str) else ""
    if result["enabled"]:
        if result["template"].count(TOKEN) != 1:
            raise ValueError("身份检查的共同材料必须包含且仅包含一个 {{identity}}")
        if not result["a"] or not result["b"] or result["a"] == result["b"]:
            raise ValueError("身份检查需要两个不同且非空的身份线索")
        if TOKEN in result["a"] or TOKEN in result["b"]:
            raise ValueError("身份线索不能再包含 {{identity}} 占位符")
    return result


def variants(spec: dict) -> dict[str, dict]:
    settings = normalize(spec.get("identity_probe"))
    if not settings["enabled"]:
        return {}
    result = {}
    for side in ("a", "b"):
        variant = copy.deepcopy(spec)
        material = settings["template"].replace(TOKEN, settings[side])
        variant["intro"] = "\n\n".join(filter(None, [spec.get("intro"), material]))
        result[f"identity_{side}"] = variant
    return result


def orders(pairs: list[tuple[int, str]], seed: int) -> dict[tuple[int, str], list[str]]:
    """Seeded, approximately equal A-first/B-first counts within each condition."""
    groups = defaultdict(list)
    for pair in pairs:
        groups[pair[1]].append(pair)
    result = {}
    for cid, group in groups.items():
        group = sorted(group)
        random.Random(f"identity:{seed}:{cid}").shuffle(group)
        for index, pair in enumerate(group):
            result[pair] = ["identity_a", "identity_b"] if index % 2 == 0 else ["identity_b", "identity_a"]
    return result


def _value(probe: dict, item: dict):
    value = (probe.get("answers") or {}).get(item["id"])
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if item["kind"] == "choice" and (value != int(value) or not 0 <= value < len(item["options"])):
        return None
    return value


def measure(item: dict, rows: list[dict], settings: dict, *, family: int) -> dict:
    """Level comparison B-A; pairs are not selected by main-answer success."""
    pairs, missing_a, missing_b, errors_a, errors_b = [], 0, 0, 0, 0
    for row in rows:
        probes = row.get("probes") or {}
        a, b = probes.get("identity_a") or {}, probes.get("identity_b") or {}
        x, y = _value(a, item), _value(b, item)
        missing_a += x is None
        missing_b += y is None
        errors_a += bool(a.get("error"))
        errors_b += bool(b.get("error"))
        if x is not None and y is not None:
            pairs.append((x, y))
    keys = [(r["agent_id"], r["condition"]) for r in rows]
    duplicates = len(keys) - len(set(keys))
    evidence = {
        "contrast": "B - A",
        "a": settings["a"],
        "b": settings["b"],
        "template": settings["template"],
        "pairs": len(pairs),
        "records": len(rows),
        "missing": len(rows) - len(pairs),
        "missing_a": missing_a,
        "missing_b": missing_b,
        "errors_a": errors_a,
        "errors_b": errors_b,
        "duplicate_records": duplicates,
        "unit": "resident",
        "scope": SCOPE,
    }
    if duplicates:
        return rc.check(
            "identity", "insufficient", "存在重复记录，不能确认独立配对样本。" + SCOPE, **evidence
        )
    if not pairs:
        return rc.check("identity", "insufficient", "没有完整的身份对照回答。" + SCOPE, **evidence)
    if item["kind"] == "choice":
        return rc.check(
            "identity",
            "observed",
            "选项变化是描述性记录，单次改变也可能来自随机性。" + SCOPE,
            **evidence,
            switch_rate=sum(x != y for x, y in pairs) / len(pairs),
            option_shifts={
                label: statistics.mean((y == k) - (x == k) for x, y in pairs)
                for k, label in enumerate(item["options"])
            },
        )
    diffs = [y - x for x, y in pairs]
    variance = statistics.variance(diffs) / len(diffs) if len(diffs) >= 2 else 0
    result = rc.interval_check(
        "identity",
        statistics.mean(diffs),
        [(variance, len(diffs))],
        item.get("identity_margin"),
        family=family,
    )
    result["evidence"].update(evidence, units=item.get("unit") or "原始题目单位")
    if evidence["missing"]:
        if result["status"] == "stable":
            result.update(status="insufficient", detail="存在缺失对照，不能据完整回答子样本判断整体等价")
        result["detail"] += "；差值与区间仅针对完整配对子样本"
    result["detail"] += "。" + SCOPE
    return result
