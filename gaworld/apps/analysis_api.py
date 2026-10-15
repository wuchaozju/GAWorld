"""Branch comparison analysis: the existing Parallel-Worlds analysis, exposed.

``POST /api/analysis/compare`` takes a PW-compatible manifest and runs the
unmodified ``gaworld.parallel`` analysis over it (no simulation is launched),
writing the usual artifacts (``report.json``, ``divergence_metrics.csv``,
``divergence_summary.md``, ``causal_effects.csv``) under
``output/comparisons/<comparison-id>/``.

The request must not become an arbitrary file-read endpoint: every
manifest-supplied path is jailed to the repository root with the same
realpath + prefix containment the benchmark harness uses (``bench_api``), so
traversal, outside-root absolute paths and symlink escapes are rejected
before anything is read.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from gaworld.apps import world_paths
from gaworld.parallel import runner as prunner

COMPARISONS_REL = os.path.join("output", "comparisons")


def _repo_path(value: Any) -> str:
    """Jail a manifest-supplied path inside the repository root."""
    root = os.path.realpath(world_paths.REPO_ROOT)
    path = os.path.realpath(os.path.join(root, str(value)))
    if path != root and not path.startswith(root + os.sep):
        raise ValueError(f"path must stay inside the repository: {value!r}")
    return path


def _validate_manifest(manifest: Any) -> tuple[dict[str, Any], str]:
    """Return ``(manifest, message)``; message is empty when valid."""
    if not isinstance(manifest, dict):
        return {}, "manifest must be an object"
    worlds = manifest.get("worlds")
    if not isinstance(worlds, dict) or not worlds:
        return {}, "manifest.worlds must be a non-empty object"
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        return {}, "manifest.spec must be an object"
    baseline_id = spec.get("baseline_id")
    if not baseline_id:
        return {}, "manifest.spec.baseline_id is required"
    if baseline_id not in worlds:
        return {}, f"baseline world not in manifest.worlds: {baseline_id}"
    for world_id, entry in worlds.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("state_csv"), str):
            return {}, f"world {world_id}: state_csv is required"
        if not isinstance(entry.get("dir"), str):
            return {}, f"world {world_id}: dir is required"
    return manifest, ""


def _jailed_worlds(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Jail every world path; raise ValueError naming the offending world."""
    jailed: dict[str, dict[str, Any]] = {}
    for world_id, entry in manifest.get("worlds", {}).items():
        try:
            state_csv = _repo_path(entry["state_csv"])
            world_dir = _repo_path(entry["dir"])
        except ValueError as exc:
            raise ValueError(f"world {world_id}: {exc}") from exc
        if not os.path.exists(state_csv):
            raise ValueError(
                f"world {world_id}: state history not found: {entry['state_csv']}"
            )
        jailed[world_id] = {**entry, "state_csv": state_csv, "dir": world_dir}
    return jailed


def compare_branch_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Run the PW analysis over ``manifest``; ``({"report", "artifacts_dir"}, 200)``."""
    manifest, message = _validate_manifest(manifest)
    if message:
        return {"error": message}, 400
    try:
        _jailed_worlds(manifest)
    except ValueError as exc:
        return {"error": str(exc)}, 400

    root = os.path.realpath(world_paths.REPO_ROOT)
    comparison_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{manifest.get('id', 'cmp')}-{uuid.uuid4().hex[:6]}"
    artifacts_rel = os.path.join(COMPARISONS_REL, comparison_id)
    artifact_manifest = {**manifest, "root": artifacts_rel}
    report = prunner.analyze_experiment(root, manifest)
    prunner.write_report(root, artifact_manifest, report)
    return {"report": report, "artifacts_dir": artifacts_rel}, 200


def handle_post(path: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    if path == "/api/analysis/compare":
        payload = payload or {}
        return compare_branch_manifest(payload.get("manifest"))
    return {"error": "Unknown endpoint"}, 404


__all__ = ["compare_branch_manifest", "handle_post"]
