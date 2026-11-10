"""Repeated independent draws: descriptive noise and resident-level contrasts."""

from __future__ import annotations

import math
import random
import statistics
from itertools import combinations

from gaworld.research import result_checks as rc

SCOPE = "仅反映固定输入与模型下的重复回答；抽样区间不涵盖供应商权重变化，不证明因果或现实无偏。"


def normalize(raw):
    raw = raw if isinstance(raw, dict) else {}
    enabled = raw.get("enabled") is True
    n = raw.get("repeats", 3)
    valid = type(n) is int and 2 <= n <= 5
    if enabled and not valid:
        raise ValueError("重复回答次数须为 2–5 的整数")
    return {"enabled": enabled, "repeats": n if valid else 3}


def execute(spec, variants, answer, prompt_fn, parse_fn, canonical, persona, condition, seed, agent_id):
    jobs = [(name, i) for name in ["main", *variants] for i in range(spec["sampling_probe"]["repeats"])]
    random.Random(f"repeated:{seed}:{agent_id}:{condition['id']}").shuffle(jobs)
    records = []
    for name, index in jobs:
        variant = spec if name == "main" else variants[name]
        prompt = prompt_fn(persona, variant, condition)
        # Each repetition is its own draw, so each gets its own seed: the point
        # of the probe is that repeated answers differ.
        repeat_seed = rc.derive_seed(seed, agent_id, condition["id"], name, index)
        try:
            raw = str(rc.call_with_seed(answer, prompt, repeat_seed))
            record = canonical(parse_fn(variant, raw), variant, spec)
            if not record["ok"]:
                record["error"] = "无法解析有效回答"
        except Exception as exc:
            raw = ""
            record = {"ok": False, "answers": {}, "error": f"{type(exc).__name__}: {exc}"}
        records.append(
            {
                **record,
                "variant": name,
                "repetition": index,
                "raw": raw[:12000],
                "prompt_hash": rc.fingerprint(prompt),
            }
        )
    return records


def attach(comparison, spec, responses):
    if not spec.get("sampling_probe", {}).get("enabled"):
        return comparison
    from gaworld.research.replication_checks import variants

    names = ["main", *variants(spec)]
    contrasts = {
        name: (name, "main") for name in names if name != "main" and not name.startswith("identity_")
    }
    if "identity_a" in names:
        contrasts["identity"] = ("identity_b", "identity_a")
    family = max(1, len(spec["items"]) * len(spec["conditions"]) * len(contrasts))
    expected = {(name, i) for name in names for i in range(spec["sampling_probe"]["repeats"])}
    keys = [(r["agent_id"], r["condition"]) for r in responses]
    valid = len(keys) == len(set(keys))
    indexed = {}
    for r in responses:
        records = r.get("sampling") or []
        index = {}
        if not isinstance(records, list):
            records = []
            valid = False
        for v in records:
            if not isinstance(v, dict) or not isinstance(v.get("answers"), dict):
                valid = False
                continue
            name, repetition = v.get("variant"), v.get("repetition")
            if not isinstance(name, str) or type(repetition) is not int:
                valid = False
                continue
            index[(name, repetition)] = v
            for item in spec["items"]:
                value = v["answers"].get(item["id"])
                if value is None:
                    continue
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or (item.get("min") is not None and value < item["min"])
                    or (item.get("max") is not None and value > item["max"])
                    or (
                        item["kind"] == "choice"
                        and (value != int(value) or not 0 <= value < len(item["options"]))
                    )
                ):
                    valid = False
        if len(index) != len(records) or set(index) != expected:
            valid = False
        indexed[(r["agent_id"], r["condition"])] = index
    source = rc.fingerprint({"spec": spec, "responses": responses})
    for row in comparison["cells"]:
        item = next(i for i in spec["items"] if i["id"] == row["item"])
        selected = [v for k, v in indexed.items() if k[1] == row["condition"]]
        evidence = {"repeats": spec["sampling_probe"]["repeats"], "unit": "resident", "scope": SCOPE}

        def values(index, name, item=item):
            array = [
                (index.get((name, i), {}).get("answers") or {}).get(item["id"])
                for i in range(spec["sampling_probe"]["repeats"])
            ]
            return array if all(v is not None for v in array) else None

        if not valid:
            result = rc.check(
                "sampling", "insufficient", "重复记录缺失或重复，不支持推断。" + SCOPE, **evidence
            )
        else:
            noise = {}
            for name in names:
                arrays = [a for v in selected if (a := values(v, name)) is not None]
                noise[name] = {
                    "complete_residents": len(arrays),
                    "missing": len(selected) - len(arrays),
                    "mean_disagreement"
                    if item["kind"] == "choice"
                    else "mean_within_resident_sd": statistics.mean(
                        statistics.mean(a != b for a, b in combinations(v, 2))
                        if item["kind"] == "choice"
                        else statistics.stdev(v)
                        for v in arrays
                    )
                    if arrays
                    else None,
                }
            evidence["noise"] = noise
            results = {}
            for name, (a, b) in contrasts.items():
                pairs = [
                    (va, vb)
                    for v in selected
                    if (va := values(v, a)) is not None and (vb := values(v, b)) is not None
                ]
                missing = len(selected) - len(pairs)
                if item["kind"] == "choice":
                    results[name] = rc.check(
                        "sampling",
                        "observed",
                        "逐选项报告重复平均占比差，不对选项编号求均值。",
                        option_shifts={
                            label: statistics.mean(
                                statistics.mean(v == i for v in va) - statistics.mean(v == i for v in vb)
                                for va, vb in pairs
                            )
                            if pairs
                            else None
                            for i, label in enumerate(item["options"])
                        },
                        missing=missing,
                    )
                else:
                    deltas = [statistics.mean(va) - statistics.mean(vb) for va, vb in pairs]
                    result = rc.interval_check(
                        "sampling",
                        statistics.mean(deltas) if deltas else 0,
                        [(statistics.variance(deltas) / len(deltas) if len(deltas) > 1 else 0, len(deltas))],
                        item.get("sampling_margin"),
                        family=family,
                    )
                    result["evidence"].update(
                        contrast=f"{a} - {b}", missing=missing, pairs=len(pairs), unit="resident"
                    )
                    if missing and result["status"] == "stable":
                        result.update(status="insufficient", detail="存在缺失居民，不能判断全部样本等价")
                    results[name] = result
                results[name]["label"] = name
            evidence["contrasts"] = results
            statuses = [v["status"] for v in results.values()]
            status = (
                "observed"
                if item["kind"] == "choice" or not statuses
                else "detected"
                if "detected" in statuses
                else "stable"
                if all(s == "stable" for s in statuses)
                else "insufficient"
            )
            result = rc.check(
                "sampling",
                status,
                "仅用额外重复回答比较居民均值；原始单次检查保持独立。差值只适用于完整居民。" + SCOPE,
                **evidence,
            )
        card = row["result_checks"]
        card["checks"] = [result if c["id"] == "sampling" else c for c in card["checks"]]
        base = card.setdefault("before_sampling_hash", card["source_hash"])
        card["source_hash"] = rc.fingerprint({"base": base, "sampling": source})
    return comparison
