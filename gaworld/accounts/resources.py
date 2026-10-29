"""Admission limits for owned worlds, stored community records and private output."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .store import AccountError

DEFAULTS = {
    "max_worlds_per_user": 20,
    "max_storage_mb_per_user": 512,
    "max_community_storage_mb_per_user": 50,
    "max_pending_publications_per_user": 100,
}


def limit(store, key):
    return store.get_setting(key, DEFAULTS[key] if os.environ.get("GAWORLD_REGISTRATION") == "open" else 0)


def check_world_count(store, db, uid):
    maximum = limit(store, "max_worlds_per_user")
    count = db.execute("SELECT count(*) FROM worlds WHERE owner_id=?", (uid,)).fetchone()[0]
    if maximum > 0 and count >= maximum:
        raise AccountError(f"世界数量已达到上限（{maximum}）")


def community_storage(db, uid):
    total = 0
    for table, column in (
        ("community_drafts", "content"),
        ("community_posts", "body"),
        ("community_comments", "body"),
    ):
        total += db.execute(
            f"SELECT coalesce(sum(length(CAST({column} AS BLOB))),0) FROM {table} WHERE author_id=?", (uid,)
        ).fetchone()[0]
    total += db.execute(
        "SELECT coalesce(sum(length(CAST(v.content AS BLOB))),0) FROM community_versions v"
        " JOIN community_publications p ON p.id=v.publication_id WHERE p.author_id=?",
        (uid,),
    ).fetchone()[0]
    total += db.execute(
        "SELECT coalesce(sum(length(CAST(e.body AS BLOB))),0) FROM community_comment_edits e JOIN community_comments c ON c.id=e.comment_id WHERE c.author_id=?",
        (uid,),
    ).fetchone()[0]
    return total


def check_community_storage(store, db, uid, added):
    maximum = limit(store, "max_community_storage_mb_per_user")
    if maximum > 0 and community_storage(db, uid) + added > maximum * 1024 * 1024:
        raise AccountError(f"社区存储已达到上限（{maximum} MB）")


def check_private_storage(store, uid, repo_root):
    maximum = limit(store, "max_storage_mb_per_user")
    if maximum <= 0:
        return
    total = 0
    root = Path(repo_root)
    directories = [root / "output" / "worlds" / w["id"] for w in store.list_worlds() if w["owner_id"] == uid]
    files = []
    for pattern in (
        "output/parallel_worlds/*/experiment.json",
        "output/research/studies/*/study.json",
        "output/research/*.json",
    ):
        for manifest in root.glob(pattern):
            if manifest.is_symlink() or any(
                parent.is_symlink() for parent in manifest.parents if parent != root
            ):
                continue
            try:
                record = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get("owner_id") == uid:
                if manifest.parent == root / "output" / "research":
                    files.append(manifest)
                else:
                    directories.append(manifest.parent)
    # Only owned output is counted. Existing work is never stopped or removed.
    for directory in directories:
        if not directory.is_symlink():
            files.extend(path for path in directory.rglob("*") if path.is_file() and not path.is_symlink())
    for path in files:
        total += path.stat().st_size
        if total > maximum * 1024 * 1024:
            raise AccountError(f"私人研究存储超过 {maximum} MB，请导出并清理不再需要的产物")
