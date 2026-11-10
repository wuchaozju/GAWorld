"""One admission policy for protocol planning, approval and execution."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_BUDGET = 50_000
DEFAULT_MAXIMUM = 1_000_000
POLICY_VERSION = 1


def resolved_agent_ids(config: dict[str, Any], repo_root: str) -> list[int]:
    ids = config.get("agent_ids")
    if isinstance(ids, list) and ids:
        return list(dict.fromkeys(int(value) for value in ids))
    if config.get("csv_path"):
        path = Path(repo_root) / str(config["csv_path"])
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(
                dict.fromkeys(int(row.get("agent_id") or row.get("id")) for row in csv.DictReader(handle))
            )
    return []


def positive_budget(value: Any, name: str = "call_budget") -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 1 <= value <= 1_000_000_000:
        raise ValueError(f"{name} 须为 1–1,000,000,000 的整数")
    return value


def resolve_budget(
    config: dict[str, Any],
    protocol: dict[str, Any],
    *,
    member: bool,
    member_limit: int | None = None,
) -> dict[str, Any]:
    settings = config.get("research_workbench") or {}
    maximum = positive_budget(settings.get("max_call_budget", DEFAULT_MAXIMUM), "max_call_budget")
    default = min(positive_budget(settings.get("call_budget", DEFAULT_BUDGET)), maximum)
    if member:
        account = positive_budget(
            member_limit if member_limit is not None else settings.get("member_call_budget", DEFAULT_BUDGET),
            "member_call_budget",
        )
        maximum = min(maximum, account)
        default = min(default, maximum)
    requested = protocol.get("call_budget")
    limit = positive_budget(default if requested is None else requested)
    if limit > maximum:
        raise ValueError(f"请求研究预算 {limit:,} 超过当前权限上限 {maximum:,}，请调整预算或联系管理员")
    hard = positive_budget(
        protocol.get("http_budget") if protocol.get("http_budget") is not None else limit, "http_budget"
    )
    if hard > limit:
        raise ValueError("实际 HTTP 请求硬预算不能高于已请求的研究预算上限")
    return {
        "version": POLICY_VERSION,
        "call_budget": limit,
        "http_budget": hard,
        "maximum": maximum,
        "default": default,
        "unit": "http_attempts",
    }


def approval_fingerprint(
    protocol: dict[str, Any], config: dict[str, Any], policy: dict[str, Any], repo_root: str
) -> str:
    """Bind actual inputs/settings without persisting provider secrets."""
    from gaworld.research.batch_inputs import FILES, model_fingerprint, parameters

    llm = config.get("llm") or {}
    selected = protocol.get("sim_provider") or (llm.get("routing") or {}).get("default")
    providers = llm.get("providers") or {}
    selected = selected or next(iter(providers), "")
    inputs: dict[str, Any] = {}
    for key in sorted(FILES):
        node = config
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        source = node
        if source:
            path = (Path(repo_root) / str(source)).resolve()
            inputs[key] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            }
    scientific = {key: value for key, value in protocol.items() if key != "budget"}
    value = {
        "protocol": scientific,
        "policy": policy,
        "inputs": inputs,
        "agents": protocol.get("sample", {}).get("agent_ids") or resolved_agent_ids(config, repo_root),
        "city": config.get("city"),
        "provider": selected,
        "routing": llm.get("routing") or {},
        "providers": {
            name: {
                "settings": model_fingerprint(cfg),
                "endpoint": {key: cfg.get(key) for key in ("url", "base_url", "endpoint")},
            }
            for name, cfg in providers.items()
            if isinstance(cfg, dict)
        },
        "model": model_fingerprint(providers.get(selected) or {}),
        "endpoint": {
            key: (providers.get(selected) or {}).get(key) for key in ("url", "base_url", "endpoint")
        },
        "parameters": parameters(config),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def mode_checks(protocol: Any, config: dict[str, Any], *, agents: int, call_budget: int) -> dict[str, Any]:
    from gaworld.research.protocol import EXECUTION_MODES, Protocol, preflight
    from gaworld.research.quick import compatibility_errors

    checks = {}
    for mode in EXECUTION_MODES:
        candidate = Protocol.from_dict(copy.deepcopy(protocol.to_dict()))
        candidate.execution_mode = mode
        candidate.fast = mode == "lean_tick"
        compatibility = compatibility_errors(candidate, config) if mode == "daily_brief" else []
        check = preflight(candidate, default_agents=agents, call_budget=call_budget)
        checks[mode] = {
            "compatible": not compatibility,
            "errors": compatibility,
            "estimated_calls": check["budget"].get("estimated_calls"),
            "within_budget": check["budget"].get("estimated_calls", 0) <= call_budget,
            "calls_per_agent_day": check["budget"].get("calls_per_agent_day"),
            "purpose": "exploratory" if mode == "daily_brief" else protocol.purpose,
        }
    return checks


def budget_candidates(
    protocol: Any, config: dict[str, Any], *, call_budget: int, repo_root: str = "."
) -> list[dict[str, Any]]:
    """Reviewed revisions only: preserve conditions, metrics and observation days."""
    from gaworld.research.protocol import Protocol, apply_overrides, preflight

    ids = list(protocol.sample.get("agent_ids") or resolved_agent_ids(config, repo_root))
    proposals = []
    seeds = protocol.seeds
    if len(seeds) > 1:
        proposals.append(({"seeds": seeds[:1]}, "减少种子；需重新审阅跨种子验证能力"))
    if len(ids) > 1:
        proposals.append(({"agent_ids": ids[: max(1, len(ids) // 2)]}, "减少居民；需重新审阅样本代表性"))
        proposals.append(
            ({"agent_ids": ids[:1], "seeds": seeds[:1]}, "单居民单种子流程检查；不代表原研究规模")
        )
    if protocol.mode == "tick":
        proposals.append(({"execution_mode": "lean_tick"}, "精简日内认知；仍保留日内循环，需审阅机制差异"))
    candidates = []
    seen = set()
    for overrides, note in proposals:
        revision = apply_overrides(Protocol.from_dict(copy.deepcopy(protocol.to_dict())), overrides)
        check = preflight(revision, default_agents=max(1, len(ids)), call_budget=call_budget)
        signature = json.dumps(overrides, sort_keys=True)
        if check["ok"] and signature not in seen:
            candidates.append(
                {
                    "overrides": overrides,
                    "note": note,
                    "review_required": True,
                    "estimated_calls": check["budget"]["estimated_calls"],
                }
            )
            seen.add(signature)
    return candidates
