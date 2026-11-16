#!/usr/bin/env python3
"""Run-level manifest for the launch wrapper: started marker, resume merge.

The run-level manifest of one launch run lives at <run_dir>/manifest.json
and is the record of the whole run: configuration, timestamps, the persona
pool summary, and one entry per (depth x blinding) leg. This module owns
that file and the rules that keep it coherent across several invocations of
the same run (a launch that was stopped and resumed):

  * The FIRST invocation writes the manifest as soon as the run starts with
    state "running" and no legs yet, so an interrupted run is recognised
    (the guard refuses a non-resume rerun into a directory that holds one)
    and the run's true start time survives every resume.
  * A terminal write (state "complete", "stopped_gracefully" or "stopped"
    for an operator stop, TASK-1525) merges: every planned leg appears
    exactly once, in plan order - legs finished in this invocation come from
    its results, legs finished in an earlier invocation whose run-level
    manifest never recorded them are read back from the leg's own files
    (_leg_done_result), and legs recorded as ok in the earlier manifest are
    carried forward. The earliest start is kept, each resume invocation is
    recorded under "resumed", and the pools summary is carried forward when
    the pool phase was skipped. Resuming a fully completed run therefore
    never wipes the manifest.
  * Legs merge exactly once per planned (depth x blinding) leg. Inside a
    leg, records are now durable per cell (TASK-1533: launch_sweep appends
    each completed cell to the leg's jsonl and flushes it immediately), so
    "done" still means its files AND its own manifest exist (_leg_is_done)
    - a partial records file without a manifest is NOT done, and a resumed
    run continues the leg by skipping its durable cells rather than
    re-running it from scratch.

Function map:
    _run_dir_has_state(run_dir)  - Any durable sign of a launch attempt?
    _load_run_manifest(run_dir)  - The run-level manifest on disk, if any.
    _leg_done_result(...)        - One finished leg's summary, rebuilt from
                                   its own jsonl records.
    _build_run_payload(...)      - Assemble one coherent manifest payload.
    _write_run_manifest(...)     - Build the payload and write manifest.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from launch_support import Settings, _repo_sha  # noqa: E402
from launch_sweep import _leg_dir, _leg_is_done  # noqa: E402


def _run_dir_has_state(run_dir: Path) -> bool:
    """True when a run directory holds any durable sign of a launch attempt.

    The guard refuses a non-resume launch into a directory that already has
    a manifest.json, a pools.json, or any leg output (a leg manifest or a
    jsonl/csv under a depth_blinding folder): starting again there would
    overwrite completed stochastic records with fresh draws. An empty or
    missing directory has no state and is fine.
    """
    if not run_dir.exists():
        return False
    if (run_dir / "manifest.json").exists() or (run_dir / "pools.json").exists():
        return True
    for folder in run_dir.iterdir():
        if not folder.is_dir():
            continue
        if (folder / "manifest.json").exists():
            return True
        if any(folder.glob("*.jsonl")) or any(folder.glob("*.csv")):
            return True
    return False


def _load_run_manifest(run_dir: Path) -> dict[str, Any] | None:
    """The run-level manifest already on disk, if any."""
    target = run_dir / "manifest.json"
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _leg_done_result(
    run_dir: Path, safe_model: str, leg: dict[str, str]
) -> dict[str, Any] | None:
    """One finished leg's durable summary, rebuilt from its own files.

    A leg that finished in an earlier invocation but was never recorded in
    the run-level manifest (the run was interrupted before its final write)
    is reconstructed here from the leg's own jsonl: record count, parsed
    count, parse rate and mean elapsed seconds, shaped exactly like the
    entry launch_sweep records for a leg that finishes in this invocation.
    Returns None when the leg is not durably done (no files or a torn
    records file); the caller then marks the leg as never completed instead
    of silently dropping it.
    """
    if not _leg_is_done(run_dir, safe_model, leg):
        return None
    leg_dir = _leg_dir(run_dir, leg)
    base = leg_dir / f"{safe_model}_{leg['blinding']}"
    records = 0
    parsed = 0
    elapsed_total = 0.0
    try:
        with Path(f"{base}.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                records += 1
                if record.get("succeeded"):
                    parsed += 1
                elapsed_total += float(record.get("elapsed_seconds") or 0.0)
    except (OSError, json.JSONDecodeError):
        return None
    mean_elapsed = elapsed_total / records if records else 0.0
    return {
        **leg,
        "ok": True,
        "records": records,
        "parsed": parsed,
        "parse_rate": parsed / records if records else 0.0,
        "mean_elapsed": mean_elapsed,
        "files": [f"{base}.jsonl", f"{base}.csv", str(leg_dir / "manifest.json")],
    }


def _build_run_payload(
    *,
    settings: Settings,
    plan: dict[str, Any],
    products_path: Path,
    run_dir: Path,
    safe_model: str,
    targets: list[dict[str, str]],
    started: str,
    finished: str,
    leg_results: list[dict[str, Any]],
    pool_summary: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    resume_invocation: bool,
    state: str,
) -> dict[str, Any]:
    """Assemble one coherent run-manifest payload.

    In every terminal state ("complete", "stopped_gracefully" and "stopped"
    for an operator stop) every planned (depth, blinding) leg appears
    exactly once, in plan order: this invocation's result when the leg ran
    now, else the earlier manifest's ok entry, else the leg's own durable
    files, else a visible "never completed" failure entry - so a resumed or
    stopped run has no duplicate and no missing leg entries. A "running"
    marker carries no legs yet. pools carries this invocation's summary or,
    when the pool phase was skipped (already complete), the earlier
    manifest's summary. started is the earliest start across invocations.
    Every resumed invocation is appended to "resumed".
    """
    earlier = {
        (leg["depth"], leg["blinding"]): leg
        for leg in (prior or {}).get("legs") or []
        if leg.get("ok")
    }
    this = {(r["depth"], r["blinding"]): r for r in leg_results}
    terminal = state in ("complete", "stopped_gracefully", "stopped")
    merged_legs: list[dict[str, Any]] = []
    if terminal:
        for target in targets:
            key = (target["depth"], target["blinding"])
            if key in this:
                merged_legs.append(this[key])
            elif key in earlier:
                merged_legs.append(earlier[key])
            else:
                from_disk = _leg_done_result(run_dir, safe_model, target)
                merged_legs.append(
                    from_disk
                    if from_disk is not None
                    else {**target, "ok": False, "error": "leg never completed"}
                )
    pools = pool_summary if pool_summary is not None else (prior or {}).get("pools")
    resumed = list((prior or {}).get("resumed") or [])
    if state in ("complete", "stopped_gracefully", "stopped") and resume_invocation:
        resumed.append(
            {
                "at": finished,
                "legs": [f"{r['depth']}_{r['blinding']}" for r in leg_results],
                "argv": list(sys.argv),
            }
        )
    ok = (
        all(leg.get("ok", False) for leg in merged_legs)
        if state in ("complete", "stopped_gracefully", "stopped")
        else None
    )
    return {
        "run_name": run_dir.name,
        "profile": plan["profile"],
        "model": settings.model,
        "port": settings.port,
        "base_url": settings.base_url,
        "manager_url": settings.manager_url,
        "commit_sha": _repo_sha(),
        "products_file": str(products_path),
        "levels": plan["levels"],
        "draws": settings.draws,
        "seed": settings.seed,
        "k": plan["k"],
        "pool_seed": settings.pool_seed,
        "pool_overdraw": settings.pool_overdraw,
        "planned_sweep_calls": plan["sweep_calls"],
        "planned_pool_draws": plan["pool_draws"],
        "state": state,
        "started": (prior or {}).get("started") or started,
        "finished": finished,
        "ok": ok,
        "legs": merged_legs,
        "pools": pools,
        "resumed": resumed or None,
        "argv": list(sys.argv),
    }


def _write_run_manifest(
    settings: Settings,
    plan: dict[str, Any],
    products_path: Path,
    run_dir: Path,
    started: str,
    finished: str,
    leg_results: list[dict[str, Any]],
    pool_summary: dict[str, Any] | None,
    *,
    targets: list[dict[str, str]],
    safe_model: str,
    prior: dict[str, Any] | None = None,
    resume_invocation: bool = False,
    state: str = "complete",
) -> Path:
    """Build the run-level manifest payload and write it to manifest.json.

    state "running" writes the started marker of the first invocation
    (merged legs are empty, ok is null); state "complete" writes the final
    coherent record (see _build_run_payload). prior is the run-level
    manifest that existed when this invocation began, if any.
    """
    payload = _build_run_payload(
        settings=settings,
        plan=plan,
        products_path=products_path,
        run_dir=run_dir,
        safe_model=safe_model,
        targets=targets,
        started=started,
        finished=finished,
        leg_results=leg_results,
        pool_summary=pool_summary,
        prior=prior,
        resume_invocation=resume_invocation,
        state=state,
    )
    target = run_dir / "manifest.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
