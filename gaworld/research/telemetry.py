"""Recover bounded historical counters without rewriting study artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def historical_snapshot(study: Any, repo_root: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "source": "final_world_manifests",
        "providers": {},
        "worlds_with_statistics": 0,
        "expected_worlds": 0,
    }
    root = Path(repo_root).resolve()
    prefix = f"study_{study.id}" + (f"_r{study.attempt}" if study.attempt > 1 else "")
    for run in study.runs:
        directory = root / "output" / "parallel_worlds" / f"{prefix}_s{run.get('seed')}"
        if directory.is_symlink() or not directory.resolve().is_relative_to(
            root / "output" / "parallel_worlds"
        ):
            continue
        if (root / str(run.get("root") or "")).resolve() != directory.resolve():
            continue
        for condition in study.protocol.get("conditions") or []:
            world = directory / "worlds" / str(condition.get("id"))
            result["expected_worlds"] += 1
            finals = []
            for path in world.glob("run_manifests/*.json"):
                from gaworld.research.run_logs import safe_path

                try:
                    safe_path(path, directory)
                except ValueError:
                    continue
                if (
                    path.is_symlink()
                    or not path.resolve().is_relative_to(directory.resolve())
                    or path.stat().st_size > 1024 * 1024
                ):
                    continue
                try:
                    payload = json.loads(path.read_text())
                except (OSError, ValueError):
                    continue
                if payload.get("outcome") != "in_progress" and (payload.get("llm") or {}).get("call_count"):
                    finals.append((path.name, payload["llm"]))
            if not finals:
                continue
            stats = max(finals, key=lambda pair: pair[0])[1]
            result["available"] = True
            result["worlds_with_statistics"] += 1
            for key in (
                "requests",
                "requests_failed",
                "requests_fell_back",
                "call_count",
                "failure_count",
                "total_latency_ms",
            ):
                result[key] = result.get(key, 0) + stats.get(key, 0)
            for name, counters in (stats.get("by_provider") or {}).items():
                target = result["providers"].setdefault(name, {})
                for key in ("calls", "failures", "total_latency_ms"):
                    target[key] = target.get(key, 0) + counters.get(key, 0)
    result["partial"] = result["worlds_with_statistics"] < result["expected_worlds"]
    return result
