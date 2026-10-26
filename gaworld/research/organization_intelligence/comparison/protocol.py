"""Immutable paired tasks, roster, rules and resource/analysis decisions."""

from __future__ import annotations

import math
from pathlib import Path

from gaworld.collaboration import organization_engine
from gaworld.collaboration.organization_methods import baseline, integer, normalize_method
from gaworld.collaboration.organization_methods import digest as digest
from gaworld.research.organization_intelligence.comparison import benchmarks

VERSION = "organization-comparison-1"


def runtime_fingerprint():
    files = [
        Path(organization_engine.__file__),
        Path(organization_engine.__file__).with_name("organization_methods.py"),
        *Path(__file__).parent.glob("*.py"),
    ]
    return digest({p.name: digest(p.read_text()) for p in sorted(files)})


def freeze(payload, members, model):
    candidate = normalize_method(payload["candidate"])
    if len(members) != len(candidate["roles"]) or len({m["id"] for m in members}) != len(members):
        raise ValueError("请选择与角色数量相同、编号唯一的居民")
    control = baseline(payload.get("baseline", "random"), len(members))
    mode = payload.get("comparison_mode", "auto")
    if mode not in {"auto", "topology", "whole_method"}:
        raise ValueError("对比模式不合法")
    mechanism_keys = ("roles", "rounds", "decision", "review", "revisions")
    scope = "whole_method" if any(candidate[k] != control[k] for k in mechanism_keys) else "topology"
    if mode == "topology":
        for key in mechanism_keys:
            control[key] = candidate[key]
        scope = "topology"
    elif mode == "whole_method":
        scope = "whole_method"
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
    limits = {"calls": 100, "prompt_chars": 40000, "input_chars": 500000, "output_chars": 12000}
    incoming = payload.get("limits", {})
    if not isinstance(incoming, dict) or set(incoming) - set(limits):
        raise ValueError("资源上限字段不合法")
    for key, value in incoming.items():
        limits[key] = integer(
            value,
            key,
            1,
            {"calls": 200, "prompt_chars": 60000, "input_chars": 1000000, "output_chars": 20000}[key],
        )
    generation = integer(payload.get("max_tokens", 2048), "每次输出token上限", 64, 4096)
    expected = len(bank["tasks"]) * repeats * 2
    return {
        "version": VERSION,
        "runtime_fingerprint": runtime_fingerprint(),
        "engine_version": organization_engine.VERSION,
        "title": str(payload.get("title") or candidate["name"] + " · 组织对照实验")[:200],
        "candidate": candidate,
        "baseline": control,
        "benchmark": bank,
        "members": members,
        "model": model,
        "seed": seed,
        "repeats": repeats,
        "delta": float(delta),
        "limits": limits,
        "max_tokens": generation,
        "temperature": 0.3,
        "expected": expected,
        "scope": scope,
        "scoring_attempts_per_cell": 2 if bank["scorer"] == "rubric" else 0,
        "budget": {
            "max_requests": expected * (limits["calls"] + (2 if bank["scorer"] == "rubric" else 0)),
            "max_scoring_requests": expected * (2 if bank["scorer"] == "rubric" else 0),
            "max_output_tokens": expected
            * (limits["calls"] + (2 if bank["scorer"] == "rubric" else 0))
            * generation,
        },
        "statistics": {"unit": "question", "bootstrap": 2000, "minimum_questions": 30},
        "failure_score": 0,
        "tokens_known": False,
    }
