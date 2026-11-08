"""Replication-specific quality, human-reference and opt-in presentation checks."""

from __future__ import annotations

import copy
import statistics

from gaworld.research import identity_checks
from gaworld.research import result_checks as rc


def variants(spec: dict) -> dict[str, dict]:
    result = {}
    settings = spec.get("bias_checks") or {}
    if settings.get("order") and any(i["kind"] == "choice" for i in spec["items"]):
        variant = copy.deepcopy(spec)
        for item in variant["items"]:
            if item["kind"] == "choice":
                item["options"].reverse()
        result["order"] = variant
    if settings.get("wording") and any(i.get("audit_wording") for i in spec["items"]):
        variant = copy.deepcopy(spec)
        for item in variant["items"]:
            if item.get("audit_wording"):
                item["text"] = item["audit_wording"]
        result["wording"] = variant
    result.update(identity_checks.variants(spec))
    return result


def canonical(parsed: dict, variant: dict, original: dict) -> dict:
    original_items = {i["id"]: i for i in original["items"]}
    for item in variant["items"]:
        value = parsed["answers"].get(item["id"])
        if value is not None and item["kind"] == "choice":
            label = item["options"][int(value)]
            parsed["answers"][item["id"]] = float(original_items[item["id"]]["options"].index(label))
    return parsed


def quality(spec: dict, responses: list[dict], residents: list[dict]) -> dict:
    keys = [(r["agent_id"], r["condition"]) for r in responses]
    rows = []
    from gaworld.research.replication import in_group

    for condition in spec["conditions"]:
        for item in spec["items"]:
            for group in [None, *spec.get("groups", [])]:
                members = None if group is None else {r["agent_id"] for r in residents if in_group(r, group)}
                selected = [
                    r
                    for r in responses
                    if r["condition"] == condition["id"] and (members is None or r["agent_id"] in members)
                ]
                missing = sum((r.get("answers") or {}).get(item["id"]) is None for r in selected)
                rows.append(
                    {
                        "item": item["id"],
                        "condition": condition["id"],
                        "group": group["id"] if group else "",
                        "records": len(selected),
                        "missing": missing,
                        "errors": sum(bool(r.get("error")) for r in selected),
                        "rate": missing / len(selected) if selected else None,
                    }
                )
    return {
        "records": len(responses),
        "duplicate_records": len(keys) - len(set(keys)),
        "missing_answers": sum(r["missing"] for r in rows if not r["group"]),
        "by_cell": rows,
        "refusal_status": "拒答仅在原始回答中核查；无法解析不自动归因为拒答",
    }


def _component(values: list[float]) -> tuple[float, int]:
    return (statistics.variance(values) / len(values), len(values)) if len(values) >= 2 else (0, len(values))


def _human_component(human: dict | None):
    if not human:
        return None
    sd, n = human.get("sd"), human.get("n")
    if sd is None or n is None or n < 2 or sd < 0:
        return None
    return sd**2 / n, n


def _disjoint_groups(left: dict, right: dict) -> bool:
    """Sample non-overlap alone cannot establish independent human subgroups."""
    for key in ("gender", "hukou"):
        if left.get(key) and right.get(key) and left[key] != right[key]:
            return True
    return any(
        a.get("age_max") is not None and b.get("age_min") is not None and a["age_max"] < b["age_min"]
        for a, b in ((left, right), (right, left))
    )


def attach(
    spec: dict,
    responses: list[dict],
    design: str,
    residents: list[dict],
    comparison: dict,
    *,
    provenance: dict | None = None,
) -> dict:
    """Add evidence without changing the legacy comparison score or its sample."""
    from gaworld.research.replication import in_group

    q = quality(spec, responses, residents)
    comparison["response_quality"] = q
    items = {i["id"]: i for i in spec["items"]}
    groups = {g["id"]: g for g in spec.get("groups", [])}
    humans = {(h["item"], h["condition"], h.get("group", "")): h for h in spec["results"]}
    rows = (
        comparison["cells"]
        + comparison["effects"]
        + comparison.get("group_cells", [])
        + comparison.get("group_gaps", [])
    )
    family = max(1, len(spec["items"]) * len(spec["conditions"]) * (1 + len(groups)) ** 2 * 2)
    source = rc.fingerprint(
        {
            "spec": spec,
            "responses": responses,
            "design": design,
            "residents": residents,
            "provenance": provenance,
        }
    )
    probe_variants = variants(spec)

    def values(qid, cid, gid=""):
        members = None if not gid else {p["agent_id"] for p in residents if in_group(p, groups[gid])}
        return {
            r["agent_id"]: r["answers"][qid]
            for r in responses
            if r["condition"] == cid
            and (members is None or r["agent_id"] in members)
            and r.get("answers", {}).get(qid) is not None
        }

    for row in rows:
        item = items[row["item"]]
        cid, gid = row["condition"], row.get("group", "")
        qs = [
            r for r in q["by_cell"] if r["item"] == item["id"] and r["condition"] == cid and r["group"] == gid
        ]
        checks = [
            rc.check(
                "quality", "observed", q["refusal_status"], cells=qs, duplicate_records=q["duplicate_records"]
            )
        ]
        human_check = rc.check("human", "insufficient", "缺少真人方差、独立样本量或可比较的数值尺度")
        a = values(item["id"], cid, gid)
        h = humans.get((item["id"], cid, gid))
        hc = _human_component(h)
        if item["kind"] != "choice" and h and h.get("mean") is not None and hc and a:
            difference = statistics.mean(a.values()) - h["mean"]
            components = [_component(list(a.values())), hc]
            usable = True
            if "agent_effect" in row:
                bid, bgid = row.get("base", cid), row.get("base_group", "")
                base = values(item["id"], bid, bgid)
                hb = humans.get((item["id"], bid, bgid))
                hbc = _human_component(hb)
                usable = bool(base and hbc and hb.get("mean") is not None)
                if usable:
                    if "base_group" in row or design != "paired":
                        components += [_component(list(base.values())), hbc]
                        difference -= statistics.mean(base.values()) - hb["mean"]
                        if set(a) & set(base):
                            usable = False
                    else:
                        shared = sorted(set(a) & set(base))
                        diffs = [a[k] - base[k] for k in shared]
                        if diffs:
                            components = [_component(diffs), hc, hbc]
                            difference = statistics.mean(diffs) - (h["mean"] - hb["mean"])
                        else:
                            usable = False
                    if "base_group" not in row and spec.get("human_design") != "between":
                        usable = False
                        human_check["detail"] = "真人配对关系或协方差未知，不能按独立组计算效应差异区间"
                    if "base_group" in row and not _disjoint_groups(groups[gid], groups[bgid]):
                        usable = False
                        human_check["detail"] = "真人分组可能重叠且协方差未知，不能按独立组计算差异区间"
            if usable:
                human_check = rc.interval_check(
                    "human", difference, components, item.get("equivalence_margin"), family=family
                )
                human_check["evidence"]["units"] = item.get("unit") or "原始题目单位"
        if q["duplicate_records"] or (q["missing_answers"] and human_check["status"] == "stable"):
            human_check["status"] = "insufficient"
            human_check["detail"] = (
                "存在缺失或重复记录；不能据完整回答子样本判断整体等价，重复记录不支持统计推断"
            )
        checks.append(human_check)
        identity = spec.get("identity_probe") or {}
        if identity.get("enabled") and "agent_effect" not in row:
            members = None if not gid else {p["agent_id"] for p in residents if in_group(p, groups[gid])}
            selected = [
                r
                for r in responses
                if r["condition"] == cid and (members is None or r["agent_id"] in members)
            ]
            checks.append(
                identity_checks.measure(
                    item,
                    selected,
                    identity,
                    family=max(1, len(spec["items"]) * len(spec["conditions"]) * (1 + len(groups))),
                )
            )
        if "agent_effect" not in row and not gid:
            for name, variant in probe_variants.items():
                applicable = (name == "order" and item["kind"] == "choice") or (
                    name == "wording" and item.get("audit_wording")
                )
                if not applicable:
                    continue
                if q["duplicate_records"]:
                    checks.append(rc.check(name, "insufficient", "存在重复记录，不能确认独立配对样本"))
                    continue
                paired = [
                    (
                        r.get("answers", {}).get(item["id"]),
                        r.get("probes", {}).get(name, {}).get("answers", {}).get(item["id"]),
                    )
                    for r in responses
                    if r["condition"] == cid
                ]
                good = [(x, y) for x, y in paired if x is not None and y is not None]
                if not good:
                    checks.append(rc.check(name, "insufficient", "没有可配对的检查回答"))
                elif item["kind"] == "choice":
                    # Nominal codes have no metric distance: expose switches and all option shifts.
                    checks.append(
                        rc.check(
                            name,
                            "observed",
                            "同一居民的选项变化为描述性证据；尚未建立等价性",
                            pairs=len(good),
                            missing=len(paired) - len(good),
                            switch_rate=sum(x != y for x, y in good) / len(good),
                            option_shifts={
                                label: statistics.mean((y == k) - (x == k) for x, y in good)
                                for k, label in enumerate(item["options"])
                            },
                        )
                    )
                else:
                    diffs = [y - x for x, y in good]
                    probe = rc.interval_check(
                        name,
                        statistics.mean(diffs),
                        [_component(diffs)],
                        item.get("equivalence_margin"),
                        family=family * 2,
                    )
                    probe["evidence"].update(
                        pairs=len(good),
                        missing=len(paired) - len(good),
                        wording=variant["items"][spec["items"].index(item)]["text"],
                    )
                    if (probe["status"] == "stable" and len(good) != len(paired)) or q["duplicate_records"]:
                        probe.update(status="insufficient", detail="存在缺失或重复；不能判断整体等价")
                    checks.append(probe)
        row["result_checks"] = rc.card(row["ref"], checks, source=source)
    comparison["result_checks"] = rc.card(
        "本次调查",
        [
            rc.check(
                "quality",
                "observed",
                "逐题、逐条件、逐分组统计；部分缺答计入缺失，重复记录不增加独立样本量",
                **q,
            )
        ],
        source=source,
    )
    return comparison
