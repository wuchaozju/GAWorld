"""Serve registered collaboration artifacts through the authenticated API."""

from __future__ import annotations

import re
from pathlib import Path

from gaworld.apps.routes import Download

PREFIX = "/api/collaboration/files/"


def public_links(record):
    identifier = str(record.get("id", ""))
    if not re.fullmatch(r"cs_[A-Za-z0-9_-]+", identifier):
        return record
    scope = PREFIX + identifier + "/artifacts/"
    record["artifact_base_url"] = scope
    for artifact in record.get("artifacts", []):
        name = str(artifact.get("filename", ""))
        if name and Path(name).name == name and re.fullmatch(r"[A-Za-z0-9._-]+", name):
            artifact["url"] = scope + name
    return record


def handle_get(path, query=None):
    from gaworld.apps.dashboard_server import _get_collaboration_service

    parts = path[len(PREFIX) :].split("/")
    if (
        len(parts) != 3
        or not re.fullmatch(r"cs_[A-Za-z0-9_-]+", parts[0])
        or parts[1] != "artifacts"
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parts[2])
    ):
        return {"error": "找不到文件"}, 404
    try:
        service = _get_collaboration_service()
        record = service.get_session(parts[0])
        if not any(
            a.get("filename") == parts[2] and a.get("path") == "artifacts/" + parts[2]
            for a in record.get("artifacts", [])
        ):
            raise LookupError()
        base = service.store.root.absolute() / parts[0] / "artifacts"
        target = (base / parts[2]).resolve()
        target.relative_to(base)
        return Download(target.read_bytes(), "text/markdown; charset=utf-8", parts[2]), 200
    except (OSError, ValueError, LookupError):
        return {"error": "找不到文件"}, 404
