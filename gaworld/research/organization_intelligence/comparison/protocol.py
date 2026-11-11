"""Immutable paired tasks, roster, rules and resource/analysis decisions."""

from __future__ import annotations

import math
from pathlib import Path

from gaworld.collaboration import organization_engine, organization_methods
from gaworld.collaboration.organization_methods import (
    baseline,
    estimate,
    instructions,
    integer,
    normalize_method,
)
from gaworld.collaboration.organization_methods import digest as digest
from gaworld.llm import failures
from gaworld.research.organization_intelligence.comparison import benchmarks
from gaworld.research.organization_intelligence.comparison.execution import POLICY

VERSION = "organization-comparison-2"

#: How many organizations one comparison may hold: one control and up to
#: three candidates. A wider comparison would cost more calls than the
#: report and the screen can explain.
MAX_ARMS = 4

#: The id of the control arm. It never changes: the protocols frozen before
#: the arms existed use the same id, so their cells stay readable.
CONTROL_ID = "baseline"

#: The mechanisms a comparison may hold equal or let differ, one factor each.
#: ``roles`` is the role *wording* two teams both work under; ``topology`` is
#: who talks to whom; ``rounds`` is how long they talk; ``review`` covers
#: cross-review and the revisions that follow; ``decision`` is how the final
#: answer is produced.
FACTORS = ("roles", "topology", "rounds", "review", "decision")

#: By default only the communication structure differs. Every other mechanism
#: is held equal, so a result can be attributed instead of being a bundle.
DEFAULT_FACTORS = {
    "roles": "same",
    "topology": "candidate",
    "rounds": "same",
    "review": "same",
    "decision": "same",
}

_LIMIT_MAX = {
    "calls": 400,
    "prompt_chars": 5000000,
    "input_chars": 20000000,
    "output_chars": 2000000,
}


def resolve_factors(payload) -> dict:
    """Read the factor table, accepting the older single ``comparison_mode``."""
    incoming = payload.get("factors")
    if incoming is None:
        mode = payload.get("comparison_mode", "auto")
        if mode == "whole_method":
            return dict.fromkeys(FACTORS, "candidate")
        return dict(DEFAULT_FACTORS)
    if not isinstance(incoming, dict) or set(incoming) - set(FACTORS):
        raise ValueError("对比因子不合法")
    factors = {name: incoming.get(name, "same") for name in FACTORS}
    for value in factors.values():
        if value not in {"same", "candidate"}:
            raise ValueError("对比因子只能是 same 或 candidate")
    if all(value == "same" for value in factors.values()):
        raise ValueError("至少要有一个因子允许不同，否则没有可比较的差异")
    return factors


def apply_factors(candidate, control, factors, *, align_roles=True):
    """Make the control match the candidate on every factor held equal.

    A custom baseline keeps the role wording its author wrote: it was
    described on purpose, unlike a built-in baseline whose "成员 1/2/3"
    wording would otherwise differ from the candidate for no reason.
    """
    result = {k: (list(v) if isinstance(v, list) else v) for k, v in control.items()}
    if factors["roles"] == "same" and align_roles:
        result["roles"] = list(candidate["roles"])
    if factors["topology"] == "same":
        result["topology"] = dict(candidate["topology"])
    if factors["rounds"] == "same":
        result["rounds"] = candidate["rounds"]
    if factors["review"] == "same":
        result["review"] = candidate["review"]
        result["revisions"] = candidate["revisions"]
    if factors["decision"] == "same":
        result["decision"] = candidate["decision"]
    return result


def differing_factors(candidate, control):
    """The factors that actually differ once the control has been aligned."""
    changed = []
    if list(candidate["roles"]) != list(control["roles"]):
        changed.append("roles")
    if digest(candidate["topology"]) != digest(control["topology"]):
        changed.append("topology")
    if candidate["rounds"] != control["rounds"]:
        changed.append("rounds")
    if bool(candidate["review"]) != bool(control["review"]) or int(candidate["revisions"]) != int(
        control["revisions"]
    ):
        changed.append("review")
    if candidate["decision"] != control["decision"]:
        changed.append("decision")
    return changed


def candidate_id(index):
    """The id of the candidate at ``index`` (0 is the primary one)."""
    return "candidate" if index == 0 else f"candidate-{index + 1}"


def seed_offset(index):
    """The seed offset of the candidate at ``index``.

    The primary candidate keeps offset 0 and the control keeps offset 1, so
    a two-arm study draws exactly the seeds it drew before the arms existed.
    The extra candidates follow with 2, 3, ...
    """
    return 0 if index == 0 else index + 1


def arms_of(spec):
    """The arms of a frozen protocol, the ones frozen earlier included.

    A protocol without an ``arms`` key describes two arms: the candidate
    (seed offset 0) and the control (seed offset 1). Deriving them keeps the
    old cells, their seeds and their scores valid.
    """
    arms = spec.get("arms")
    if isinstance(arms, list) and arms:
        return arms
    factors = spec.get("factors") or dict(DEFAULT_FACTORS)
    return [
        {
            "id": candidate_id(0),
            "label": (spec.get("candidate") or {}).get("name") or "候选",
            "method": spec["candidate"],
            "factors": factors,
            "seed_offset": 0,
            "is_control": False,
        },
        {
            "id": CONTROL_ID,
            "label": (spec.get("baseline") or {}).get("name") or "对照",
            "method": spec["baseline"],
            "factors": factors,
            "seed_offset": 1,
            "is_control": True,
        },
    ]


def arm_method(spec, arm_id):
    """The method one arm runs."""
    for arm in arms_of(spec):
        if arm["id"] == arm_id:
            return arm["method"]
    raise LookupError("找不到实验单元对应的组织方式")


#: The semantic identity of a cell: what decides its prompts and its score.
#: It changes when the meaning changes — not when a file is edited. A study
#: frozen under this build can be resumed under it, and the per-request
#: prompt hash refuses any answer that would have been sent differently.
BUILD = "organization-comparison-1"


def runtime_fingerprint():
    """What decides a cell's prompts and score, in one value.

    Hashing the files on disk would block every saved study after a
    comment was added. These are the declared versions instead; each one is
    bumped by hand when the meaning behind it changes.
    """
    return digest(
        {
            "build": BUILD,
            "engine": organization_engine.VERSION,
            "method": organization_methods.VERSION,
            "protocol": VERSION,
        }
    )


def code_fingerprint():
    """Which files the study was run with. For the audit trail only."""
    files = [
        Path(organization_engine.__file__),
        Path(organization_engine.__file__).with_name("organization_methods.py"),
        Path(failures.__file__),
        *Path(__file__).parent.glob("*.py"),
    ]
    return digest({p.name: digest(p.read_text()) for p in sorted(files)})


def _candidates(payload, members, primary, primary_factors, custom):
    """The candidates of a comparison: the primary one and the extra ones.

    Every candidate carries its own factor table. The table says which
    mechanisms may differ from the control; the control is aligned to the
    primary candidate, and the other candidates are compared against that
    same control — the report states what actually differs for each of them.
    """
    extra = payload.get("candidates")
    if extra is None:
        extra = []
    if not isinstance(extra, list):
        raise ValueError("候选组织列表不合法")
    if len(extra) + 2 > MAX_ARMS:
        raise ValueError(f"一次最多比较{MAX_ARMS}个组织：1个对照加最多{MAX_ARMS - 1}个候选")
    candidates = [
        {
            "id": candidate_id(0),
            "label": primary["name"],
            "method": primary,
            "factors": primary_factors,
            "seed_offset": seed_offset(0),
            "is_control": False,
        }
    ]
    for position, item in enumerate(extra, start=1):
        if not isinstance(item, dict):
            raise ValueError("候选组织不合法")
        method = normalize_method(item.get("method"))
        if len(method["roles"]) != len(members):
            raise ValueError(f"候选组织「{method['name']}」的角色数量必须与居民数量一致")
        label = str(item.get("label") or "").strip()
        if not label:
            raise ValueError("每个候选组织都要有自己的名称")
        own = item.get("factors")
        table = resolve_factors({"factors": own}) if own else dict(primary_factors)
        candidates.append(
            {
                "id": candidate_id(position),
                "label": label,
                "method": method,
                "factors": table,
                "seed_offset": seed_offset(position),
                "is_control": False,
            }
        )
    labels = [item["label"] for item in candidates]
    if len(set(labels)) != len(labels):
        raise ValueError("候选组织的名称不能重复，请给每个候选起一个能区分的名称")
    return candidates


def prepare(payload, members):
    """Everything the frozen protocol needs, before it is frozen.

    Returned apart from the protocol so the dashboard can show a plan
    (cells, calls, wall clock, whether the declared limits fit) before the
    study is saved.
    """
    candidate = normalize_method(payload["candidate"])
    if len(members) != len(candidate["roles"]) or len({m["id"] for m in members}) != len(members):
        raise ValueError("请选择与角色数量相同、编号唯一的居民")
    custom = payload.get("baseline") == "custom"
    control_raw = (
        normalize_method(payload.get("baseline_method"))
        if custom
        else baseline(payload.get("baseline", "random"), len(members))
    )
    if len(control_raw["roles"]) != len(members):
        raise ValueError("对照组织的角色数量必须与候选组织一致")
    factors = resolve_factors(payload)
    control = apply_factors(candidate, control_raw, factors, align_roles=not custom)
    changed = differing_factors(candidate, control)
    scope = "topology" if changed == ["topology"] else "whole_method"
    candidates = _candidates(payload, members, candidate, factors, custom)
    arms = list(candidates)
    arms.append(
        {
            "id": CONTROL_ID,
            "label": control["name"],
            "method": control,
            "factors": factors,
            "seed_offset": 1,
            "is_control": True,
        }
    )
    changed_by_arm = {
        arm["id"]: ([] if arm["is_control"] else differing_factors(arm["method"], control)) for arm in arms
    }
    bank = payload.get("benchmark")
    if not isinstance(bank, dict):
        bank = benchmarks.builtin(
            payload.get("problem", "information"),
            payload.get("count", 30),
            len(members),
            payload.get("seed", 20261026),
        )
    bank = benchmarks.validate(bank.get("tasks"), bank.get("name", "题库"), bank.get("scorer", "exact"))
    for q in bank["tasks"]:
        benchmarks.public_task(q, len(members))
    repeats = integer(payload.get("repeats", 3), "每题重复次数", 1, 10)
    seed = integer(payload.get("seed", 20261026), "种子", 0, 2**31 - 1)
    delta = payload.get("delta", 0)
    if type(delta) not in (int, float) or not math.isfinite(delta) or not 0 <= delta <= 1:
        raise ValueError("最小改善幅度必须在0–1之间")
    shapes = {arm["id"]: estimate(arm["method"], len(members)) for arm in arms}
    needed = {
        key: max(shapes[arm]["limits"][key] for arm in shapes) for key in shapes[arms[0]["id"]]["limits"]
    }
    limits = dict(needed)
    incoming = payload.get("limits", {})
    if not isinstance(incoming, dict) or set(incoming) - set(limits):
        raise ValueError("资源上限字段不合法")
    for key, value in incoming.items():
        limits[key] = integer(value, key, 1, _LIMIT_MAX[key])
    generation = integer(payload.get("max_tokens", 2048), "每次输出token上限", 64, 4096)
    expected = len(bank["tasks"]) * repeats * len(arms)
    plan = {
        "cells": expected,
        "calls_per_cell": {arm: shapes[arm]["calls_per_cell"] for arm in shapes},
        "limits": limits,
        "needed_limits": needed,
        "sufficient": limits["calls"] >= max(shapes[arm]["calls_per_cell"] for arm in shapes),
        "warnings": [],
    }
    plan["total_calls"] = len(bank["tasks"]) * repeats * sum(shapes[arm]["calls_per_cell"] for arm in shapes)
    policy = POLICY.copy()
    interval = int(policy.get("min_interval_seconds", 0))
    lanes = max(1, int(policy.get("concurrency", 1)))
    plan["min_interval_seconds"] = interval
    plan["concurrency"] = lanes
    plan["min_seconds"] = int(plan["total_calls"] * interval / lanes)
    for key in ("prompt_chars", "input_chars", "output_chars"):
        if limits[key] < needed[key]:
            plan["warnings"].append(
                f"{key} 上限 {limits[key]} 小于本次设置需要的 {needed[key]}，运行可能提前停止。"
            )
    if not plan["sufficient"]:
        plan["warnings"].append("每题调用次数上限不足以完成一次实验单元，无法开始。")
    for arm in candidates[1:]:
        # The control is one method. If this candidate asked for a mechanism
        # to be held equal that the shared control does not hold equal, the
        # difference is real and the reader has to see it.
        aligned = apply_factors(arm["method"], control_raw, arm["factors"], align_roles=not custom)
        if set(differing_factors(arm["method"], aligned)) - set(changed_by_arm[arm["id"]]):
            plan["warnings"].append(
                f"候选「{arm['label']}」声明允许不同的因子与实际对照臂不一致，以各臂实际差异为准。"
            )
    return {
        "candidate": candidate,
        "control": control,
        "custom": custom,
        "factors": factors,
        "changed": changed,
        "changed_by_arm": changed_by_arm,
        "arms": arms,
        "candidates": candidates,
        "scope": scope,
        "bank": bank,
        "repeats": repeats,
        "seed": seed,
        "delta": float(delta),
        "limits": limits,
        "generation": generation,
        "expected": expected,
        "plan": plan,
        "policy": policy,
    }


def freeze(payload, members, model):
    prepared = prepare(payload, members)
    candidate = prepared["candidate"]
    control = prepared["control"]
    arms = prepared["arms"]
    bank = prepared["bank"]
    limits = prepared["limits"]
    expected = prepared["expected"]
    plan = prepared["plan"]
    return {
        "version": VERSION,
        "runtime_fingerprint": runtime_fingerprint(),
        "code_fingerprint": code_fingerprint(),
        "execution_policy": prepared["policy"],
        "engine_version": organization_engine.VERSION,
        "title": str(payload.get("title") or candidate["name"] + " · 组织对照实验")[:200],
        "candidate": candidate,
        "baseline": control,
        "baseline_kind": "custom" if prepared["custom"] else payload.get("baseline", "random"),
        "factors": prepared["factors"],
        "arms": arms,
        "scope_factors": prepared["changed_by_arm"],
        "instructions": {arm["id"]: instructions(arm["method"]) for arm in arms},
        "benchmark": bank,
        "members": members,
        "model": model,
        "seed": prepared["seed"],
        "repeats": prepared["repeats"],
        "delta": prepared["delta"],
        "limits": limits,
        "max_tokens": prepared["generation"],
        "temperature": 0.3,
        "expected": expected,
        "scope": prepared["scope"],
        "plan": plan,
        "scoring_attempts_per_cell": 2 if bank["scorer"] == "rubric" else 0,
        "budget": {
            "max_requests": plan["total_calls"] + expected * (2 if bank["scorer"] == "rubric" else 0),
            "max_scoring_requests": expected * (2 if bank["scorer"] == "rubric" else 0),
            "max_output_tokens": plan["total_calls"] * prepared["generation"],
        },
        "statistics": {"unit": "question", "bootstrap": 2000, "minimum_questions": 30},
        "failure_score": 0,
        "tokens_known": False,
    }
