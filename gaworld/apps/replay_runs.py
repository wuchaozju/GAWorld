"""Discovery of replayable simulation traces.

The replay page used to read one hard-coded path (``output/visualization/
simulation_trace.json``), so every new run buried the previous one. This module
enumerates every trace on disk instead: the live one, the per-run archives the
visualizer keeps under ``<visualization>/runs/<run_id>/``, and the traces that
scenario runs (compare-event) leave in their own output trees.

Reading is deliberately cheap: a trace can be tens of megabytes, and a listing
of a hundred runs must not parse them all. ``meta`` is the first key the
visualizer writes, so only the head of each file is read.
"""

from __future__ import annotations

import json
import os
from glob import glob
from typing import Any

TRACE_NAME = "simulation_trace.json"

# ``meta`` sits at the top of the file; 64 KiB is far more than it ever needs.
META_HEAD_BYTES = 64 * 1024

# Only fall back to a full parse for files small enough that it does not stall
# the listing endpoint.
FULL_PARSE_MAX_BYTES = 4 * 1024 * 1024


def _extract_meta_object(text: str) -> dict[str, Any] | None:
    """Pull the ``"meta": { ... }`` object out of a JSON prefix."""
    key = text.find('"meta"')
    if key < 0:
        return None
    start = text.find("{", key + len('"meta"'))
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : pos + 1])
                except json.JSONDecodeError:
                    return None
    return None


def read_trace_meta(path: str) -> dict[str, Any]:
    """Return a trace's ``meta`` block without parsing the whole file."""
    try:
        with open(path, "rb") as f:
            head = f.read(META_HEAD_BYTES)
    except OSError:
        return {}
    meta = _extract_meta_object(head.decode("utf-8", errors="ignore"))
    if isinstance(meta, dict):
        return meta
    try:
        if os.path.getsize(path) > FULL_PARSE_MAX_BYTES:
            return {}
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    meta = payload.get("meta") if isinstance(payload, dict) else None
    return meta if isinstance(meta, dict) else {}


def _visualization_dirs(repo_root: str, live_dir: str) -> list[str]:
    """Directories that may hold a trace, newest-run detection aside.

    Scenario runs nest their output tree a few levels under ``output/`` (e.g.
    ``output/comparisons/<scenario>/with_event/visualization``), so the depths
    are enumerated explicitly rather than walking the whole tree — ``output/``
    also holds memory stores with tens of thousands of files.
    """
    output_root = os.path.join(repo_root, "output")
    # The configured live dir first, then the conventional default (which a
    # custom live dir must not hide) and every nested scenario output tree.
    dirs = [os.path.join(repo_root, live_dir), os.path.join(output_root, "visualization")]
    for depth in range(1, 5):
        pattern = os.path.join(output_root, *(["*"] * depth), "visualization")
        dirs.extend(sorted(glob(pattern)))
    seen: set[str] = set()
    unique = []
    for path in dirs:
        real = os.path.realpath(path)
        if real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        unique.append(path)
    return unique


def _run_dirs(visualization_dir: str) -> list[str]:
    """The visualization dir itself plus each archived run inside it."""
    found = []
    if os.path.exists(os.path.join(visualization_dir, TRACE_NAME)):
        found.append(visualization_dir)
    found.extend(
        sorted(
            os.path.dirname(p)
            for p in glob(os.path.join(visualization_dir, "runs", "*", TRACE_NAME))
        )
    )
    return found


def _label_for(rel_dir: str, kind: str) -> str:
    parts = rel_dir.split("/")
    if kind == "archive":
        # output/<...>/visualization/runs/<run_id> -> "<scenario> · <run_id>"
        run_id = parts[-1]
        scenario = "/".join(parts[1:-3])  # drop "output", "visualization/runs/<id>"
        return f"{scenario} · {run_id}" if scenario else run_id
    scenario = "/".join(parts[1:-1])  # drop "output" and "visualization"
    return scenario or "visualization"


def list_runs(repo_root: str, live_dir: str = "output/visualization") -> list[dict[str, Any]]:
    """Every replayable trace under ``repo_root``, newest first.

    The live trace (the path a running simulation writes to) always comes
    first, so the replay page keeps opening on the current run by default.
    """
    live_trace = os.path.realpath(os.path.join(repo_root, live_dir, TRACE_NAME))
    runs: list[dict[str, Any]] = []
    for visualization_dir in _visualization_dirs(repo_root, live_dir):
        for run_dir in _run_dirs(visualization_dir):
            trace_path = os.path.join(run_dir, TRACE_NAME)
            rel_dir = os.path.relpath(run_dir, repo_root).replace(os.sep, "/")
            if rel_dir.startswith(".."):
                continue  # output dir configured outside the repo: not servable
            is_live = os.path.realpath(trace_path) == live_trace
            is_archive = os.path.basename(os.path.dirname(run_dir)) == "runs"
            kind = "live" if is_live else ("archive" if is_archive else "scenario")
            meta = read_trace_meta(trace_path)
            sim_meta = meta.get("sim_meta") if isinstance(meta.get("sim_meta"), dict) else {}
            # Archived runs keep the avatars of the visualization dir above them.
            avatar_dir = os.path.dirname(os.path.dirname(rel_dir)) if is_archive else rel_dir
            try:
                size_bytes = os.path.getsize(trace_path)
                mtime = os.path.getmtime(trace_path)
            except OSError:
                size_bytes, mtime = 0, 0.0
            runs.append(
                {
                    "id": rel_dir,
                    "kind": kind,
                    "label": _label_for(rel_dir, kind),
                    "trace_url": "/" + rel_dir + "/" + TRACE_NAME,
                    "latest_url": "/" + rel_dir + "/latest_frame.json" if is_live else "",
                    "avatar_base": "/" + avatar_dir + "/",
                    "frame_count": int(meta.get("frame_count") or 0),
                    "finished": bool(meta.get("finished")),
                    "generated_at": str(meta.get("generated_at") or ""),
                    "last_updated": str(meta.get("last_updated") or ""),
                    "sim_days": sim_meta.get("sim_days"),
                    "agent_count": len(sim_meta.get("agent_ids") or []),
                    "size_bytes": size_bytes,
                    "mtime": mtime,
                }
            )
    runs.sort(key=lambda r: (r["kind"] != "live", -r["mtime"]))
    return runs
