"""Append-only report storage for the mobile digital twin.

``reports.jsonl`` is the single source of truth. Every downstream consumer —
the mirror stage, the perception-injection stage, and the offline calibration
script — derives from it and none of them write to it.

``snapshot.json`` is a derived cache of the newest report by timestamp, kept so
the mirror stage and the phone can read current state without scanning the full
log. It is regenerated on every append, never edited independently.
"""

from __future__ import annotations

import json
import os
import threading


DEFAULT_ROOT = "output/twin"

# What an `update` amendment is allowed to change.
#
# Location is deliberately absent. It came off the device sensor at a specific
# moment; letting a user rewrite it turns measured data into asserted data, and
# the calibration corpus silently stops being a record of where anyone actually
# was. A wrong fix is deleted, not edited.
PATCHABLE_FIELDS = ("action_tag", "note")

# One lock for the whole subsystem. The server is threaded, and at this scale
# (a handful of users) per-agent locks would add contention bookkeeping for no
# measurable gain.
_LOCK = threading.RLock()


def agent_dir(agent_id, root=DEFAULT_ROOT):
    return os.path.join(str(root), f"agent_{int(agent_id)}")


def _reports_path(agent_id, root=DEFAULT_ROOT):
    return os.path.join(agent_dir(agent_id, root=root), "reports.jsonl")


def _snapshot_path(agent_id, root=DEFAULT_ROOT):
    return os.path.join(agent_dir(agent_id, root=root), "snapshot.json")


def load_raw(agent_id, root=DEFAULT_ROOT):
    """Every stored line, reports and amendments alike, in file order."""
    path = _reports_path(agent_id, root=root)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A truncated write (killed process, full disk) must not make
                # every later read fail. Skip the line and keep going.
                continue
    return rows


def load_reports(agent_id, root=DEFAULT_ROOT, since_ts=None):
    """Return effective reports: amendments folded in, deletions removed.

    Folding at read time means every consumer — the mirror stage, perception
    injection, the trail, calibration — sees corrected data without knowing
    amendments exist.
    """
    rows = load_raw(agent_id, root=root)

    # Later amendments supersede earlier ones for the same target.
    amendments = {}
    for row in rows:
        if row.get("kind") == "amend" and row.get("target"):
            amendments[str(row["target"])] = row

    reports = []
    for row in rows:
        if row.get("kind") == "amend":
            continue
        amendment = amendments.get(str(row.get("report_id")))
        if amendment is not None:
            if amendment.get("op") == "delete":
                continue
            patch = amendment.get("patch") or {}
            row = dict(row)
            for key in PATCHABLE_FIELDS:
                if key in patch:
                    row[key] = patch[key]
        if since_ts is not None and float(row.get("ts", 0)) <= float(since_ts):
            continue
        reports.append(row)
    return reports


def append_reports(agent_id, reports, root=DEFAULT_ROOT):
    """Append reports, skipping any ``report_id`` already stored.

    Returns ``{"accepted": int, "duplicates": int}``.
    """
    with _LOCK:
        # Dedup against the RAW log, not the folded view: a deleted report
        # disappears from load_reports(), and deduping against that would let
        # the offline queue re-append an id the server has already seen.
        existing = {
            str(row.get("report_id"))
            for row in load_raw(agent_id, root=root)
            if row.get("report_id")
        }
        directory = agent_dir(agent_id, root=root)
        os.makedirs(directory, exist_ok=True)

        accepted = []
        duplicates = 0
        for record in reports or []:
            report_id = str(record.get("report_id") or "")
            if not report_id or report_id in existing:
                duplicates += 1
                continue
            existing.add(report_id)
            accepted.append(record)

        if accepted:
            with open(_reports_path(agent_id, root=root), "a", encoding="utf-8") as handle:
                for record in accepted:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            _refresh_snapshot(agent_id, root=root)

        return {"accepted": len(accepted), "duplicates": duplicates}


def append_amendment(agent_id, amend_id, target, op, patch=None, root=DEFAULT_ROOT):
    """Append a correction or deletion referencing an earlier report.

    The log stays append-only and ``report_id`` stays the idempotency key;
    corrections are new records that point back at an old one.
    """
    if op not in ("delete", "update"):
        raise ValueError(f"unknown amendment op {op!r}")
    clean = {}
    for key in PATCHABLE_FIELDS:
        if patch and key in patch:
            clean[key] = patch[key]
    record = {
        "report_id": str(amend_id),
        "kind": "amend",
        "target": str(target),
        "op": op,
        "patch": clean,
        "ts": 0,
    }
    with _LOCK:
        existing = {
            str(row.get("report_id"))
            for row in load_raw(agent_id, root=root)
            if row.get("report_id")
        }
        if record["report_id"] in existing:
            return {"accepted": 0, "duplicates": 1}
        directory = agent_dir(agent_id, root=root)
        os.makedirs(directory, exist_ok=True)
        with open(_reports_path(agent_id, root=root), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        _refresh_snapshot(agent_id, root=root)
        return {"accepted": 1, "duplicates": 0}


def _refresh_snapshot(agent_id, root=DEFAULT_ROOT):
    """Rewrite snapshot.json as the newest *effective* report by timestamp."""
    reports = load_reports(agent_id, root=root)
    if not reports:
        # Everything was deleted. Removing the file matters: leaving it would
        # keep the phone showing a position the user just erased.
        try:
            os.remove(_snapshot_path(agent_id, root=root))
        except OSError:
            pass
        return
    newest = max(reports, key=lambda item: float(item.get("ts", 0)))
    directory = agent_dir(agent_id, root=root)
    os.makedirs(directory, exist_ok=True)
    with open(_snapshot_path(agent_id, root=root), "w", encoding="utf-8") as handle:
        json.dump(newest, handle, ensure_ascii=False, indent=2)


def read_snapshot(agent_id, root=DEFAULT_ROOT):
    """Return the newest report, or ``None`` when the agent has never reported."""
    path = _snapshot_path(agent_id, root=root)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def is_fresh(snapshot, now_ts, ttl_minutes):
    """Whether a snapshot is recent enough for the mirror channel to apply."""
    if not snapshot:
        return False
    try:
        age_seconds = float(now_ts) - float(snapshot.get("ts", 0))
    except (TypeError, ValueError):
        return False
    return 0 <= age_seconds <= float(ttl_minutes) * 60
