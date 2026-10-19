"""Clone a protocol into a separately reviewed daily-brief pilot."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from gaworld.research.protocol import Protocol
from gaworld.sim._fastforward import LONG_RUN_STATE_KEYS


def exclude_unused_measures(protocol: Protocol) -> list[str]:
    """Remove only unsupported display metrics; never change a hypothesis."""
    if protocol.mode != "daily_brief":
        return []
    allowed = set(LONG_RUN_STATE_KEYS)
    allowed.update("survey." + str(q.get("id")) for q in protocol.survey.get("questions", []))
    used = {h.get("measure") for h in protocol.hypotheses}
    removed = [m["id"] for m in protocol.measures if m.get("id") not in allowed | used]
    protocol.measures = [m for m in protocol.measures if m.get("id") not in removed]
    return removed


def compatibility_errors(protocol: Protocol, config: dict[str, Any] | None = None) -> list[str]:
    allowed = set(LONG_RUN_STATE_KEYS)
    if protocol.kind == "composite":
        allowed.update("survey." + str(q.get("id")) for q in (protocol.survey or {}).get("questions", []))
    requested = {str(m.get("id")) for m in protocol.measures}
    requested.update(str(h.get("measure")) for h in protocol.hypotheses)
    errors = [f"按天简报不支持指标 {metric}，请使用日内模式。" for metric in sorted(requested - allowed)]
    # Parallel worlds already disable the inherited distributed relay and
    # Moltbook posting in world_overrides. Only multiplayer can remain active
    # from the base config. Explicit tick-only conditions still need rejection.
    inherited = {"multiplayer": (config or {}).get("multiplayer")}
    for patch in [inherited, *(c.get("config") or {} for c in protocol.conditions)]:
        for key in ("multiplayer", "distributed", "moltbook"):
            if (patch.get(key) or {}).get("enabled"):
                errors.append(f"按天简报不支持 {key} 日内交互机制。")
    return errors


def sample_identity(config: dict[str, Any], repo_root: str = "") -> dict[str, Any]:
    source = config.get("csv_path")
    if not source:
        return {"city": str(config.get("city") or "默认世界")}
    path = (Path(repo_root) / str(source)).resolve()
    if not path.is_file():
        raise ValueError("实际居民样本 CSV 不存在")
    city = config.get("city") or (path.parent.name if path.parent.parent.name == "cities" else "默认世界")
    return {"city": str(city), "csv_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def validate_sample(protocol: Protocol, config: dict[str, Any], repo_root: str = "") -> dict[str, Any]:
    identity = sample_identity(config, repo_root)
    prior = protocol.sample.get("seed_identity") or {}
    if prior.get("csv_path") and identity.get("csv_path") != prior["csv_path"]:
        raise ValueError("原研究与当前城市的样本来源不同，请切回原城市后创建或运行快速版本")
    if prior.get("sha256") and identity.get("sha256") != prior["sha256"]:
        raise ValueError("居民样本已改变，请重新创建和审阅协议")
    ids = protocol.sample.get("agent_ids") or config.get("agent_ids") or []
    if identity.get("csv_path"):
        with open(identity["csv_path"], encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            existing = {int(row.get("agent_id") or row.get("id") or 0) for row in rows}
        missing = sorted({int(value) for value in ids} - existing)
        if missing:
            raise ValueError(f"当前城市没有样本居民 {missing}")
    return identity


def original_sample(study: Any, repo_root: str) -> dict[str, Any]:
    """Read actual seed identity from saved runtime or legacy run manifests."""
    runtime = study.runtime or {}
    if runtime.get("seed_identity"):
        return {"agent_ids": runtime.get("actual_agent_ids"), "seed_identity": runtime["seed_identity"]}
    evidence: list[dict[str, Any]] = []
    root = Path(repo_root).resolve()
    prefix = f"study_{study.id}" + (f"_r{study.attempt}" if study.attempt > 1 else "")
    for run in study.runs:
        directory = (root / str(run.get("root") or "")).resolve()
        expected = root / "output" / "parallel_worlds" / f"{prefix}_s{run.get('seed')}"
        if directory != expected.resolve() or expected.is_symlink():
            raise ValueError("原研究样本记录不属于该研究尝试")
        if not directory.is_relative_to(root / "output" / "parallel_worlds"):
            raise ValueError("原研究样本路径非法")
        for path in directory.glob("worlds/*/run_manifests/*.json"):
            if path.is_symlink() or not path.resolve().is_relative_to(directory):
                raise ValueError("原研究样本记录路径非法")
            manifest = json.loads(path.read_text())
            config = manifest.get("config") or {}
            if config.get("csv_path"):
                evidence.append(
                    {
                        "agent_ids": list(config.get("agent_ids") or []),
                        "seed_identity": {"csv_path": str((root / config["csv_path"]).resolve())},
                    }
                )
    if evidence:
        signatures = {(e["seed_identity"]["csv_path"], tuple(e["agent_ids"])) for e in evidence}
        if len(signatures) != 1:
            raise ValueError("原研究各世界的实际居民样本不一致，不能直接创建可比快速版本")
        return evidence[0]
    return {
        "agent_ids": runtime.get("actual_agent_ids")
        or study.protocol.get("sample", {}).get("agent_ids")
        or [],
        "seed_identity": study.protocol.get("sample", {}).get("seed_identity") or {},
    }


def quick_protocol(
    parent: Protocol, config: dict[str, Any], *, repo_root: str = ""
) -> tuple[Protocol, dict[str, Any]]:
    result = Protocol.from_dict(copy.deepcopy(parent.to_dict()))
    ids = parent.sample.get("agent_ids") or config.get("agent_ids") or []
    try:
        ids = list(dict.fromkeys(int(value) for value in ids if int(value) > 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("无法解析实际居民样本") from exc
    if not ids:
        raise ValueError("没有可用于快速试跑的实际居民样本")
    identity = validate_sample(parent, config, repo_root)
    result.execution_mode = "daily_brief"
    result.fast = False
    result.purpose = "exploratory"
    result.validity["seeds"] = [parent.seeds[0] if parent.seeds else 42]
    result.sample["agent_ids"] = ids
    result.sample["city"] = identity["city"]
    result.sample["seed_identity"] = identity
    result.title = parent.title + " · 快速试跑"
    result.notes = (
        parent.notes + "\n近似探索/流程检查：按天简报，独立于原研究。样本文字描述不代表实际执行人口。"
    )[:3000]
    changes = {
        "execution_mode": {"before": parent.mode, "after": result.mode},
        "purpose": {"before": parent.purpose, "after": result.purpose},
        "seeds": {"before": parent.seeds, "after": result.seeds},
        "sample": {"before": copy.deepcopy(parent.sample), "after": copy.deepcopy(result.sample)},
    }
    removed = exclude_unused_measures(result)
    if removed:
        changes["excluded_unused_measures"] = removed
        result.notes += "\n已排除未被假设使用的不兼容指标：" + "、".join(removed)
    return result, changes
