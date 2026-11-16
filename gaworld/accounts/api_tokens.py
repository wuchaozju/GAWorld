"""Revocable, world-bound personal API credentials; only SHA-256 hashes persist."""

from __future__ import annotations

import hashlib
import json
import secrets
import time

from .store import AccountError

SCOPES = frozenset({"parallel:read", "parallel:run"})
_COLUMNS = "id, user_id, name, prefix, world_id, scopes, created_at, expires_at, last_used_at, revoked_at"


def migrate(store):
    with store._db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS api_tokens (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL, prefix TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                world_id TEXT NOT NULL REFERENCES worlds(id), scopes TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL,
                last_used_at REAL, revoked_at REAL
            );
            CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens(user_id);
        """)


def _public(row):
    item = dict(row)
    item["scopes"] = json.loads(item["scopes"])
    item["active"] = item["revoked_at"] is None and item["expires_at"] > time.time()
    return item


def list_tokens(store, user_id):
    with store._db() as db:
        return [
            _public(row)
            for row in db.execute(
                f"SELECT {_COLUMNS} FROM api_tokens WHERE user_id=? "
                "ORDER BY (revoked_at IS NULL AND expires_at>?) DESC, created_at DESC LIMIT 100",
                (user_id, time.time()),
            )
        ]


def create(store, user, payload):
    name = payload.get("name")
    scopes = payload.get("scopes")
    days = payload.get("expires_days", 30)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise AccountError("Token name must contain 1-80 characters")
    if (
        not isinstance(scopes, list)
        or not scopes
        or any(not isinstance(s, str) or s not in SCOPES for s in scopes)
    ):
        raise AccountError("Choose parallel:read and/or parallel:run")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise AccountError("expires_days must be an integer between 1 and 365")
    world_id = payload.get("world_id")
    if not isinstance(world_id, str):
        raise AccountError("Select an owned world")
    world = store.get_world(world_id)
    if world is None or world["owner_id"] != user["id"]:
        raise AccountError("Select an owned world")
    secret = "gaw_pat_" + secrets.token_urlsafe(32)
    token_id, now = secrets.token_hex(16), time.time()
    with store._db() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute(
            "SELECT COUNT(*) FROM api_tokens WHERE user_id=? AND revoked_at IS NULL AND expires_at>?",
            (user["id"], now),
        ).fetchone()[0]
        if count >= 20:
            raise AccountError("At most 20 active tokens; revoke an old token first")
        db.execute(
            "INSERT INTO api_tokens (id,user_id,name,prefix,token_hash,world_id,scopes,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                token_id,
                user["id"],
                name.strip(),
                secret[:16],
                hashlib.sha256(secret.encode()).hexdigest(),
                world_id,
                json.dumps(sorted(set(scopes))),
                now,
                now + days * 86400,
            ),
        )
        row = db.execute(f"SELECT {_COLUMNS} FROM api_tokens WHERE id=?", (token_id,)).fetchone()
    store.audit(user, "api_token_create", token_id)
    return {"token": secret, "record": _public(row)}


def revoke(store, user, token_id):
    if not isinstance(token_id, str):
        raise AccountError("Token id must be a string")
    with store._db() as db:
        changed = db.execute(
            "UPDATE api_tokens SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
            (time.time(), token_id, user["id"]),
        ).rowcount
    if changed:
        store.audit(user, "api_token_revoke", token_id)
    return bool(changed)


def authenticate(store, secret):
    if not secret.startswith("gaw_pat_") or len(secret) > 128:
        return None
    with store._db() as db:
        row = db.execute(
            f"SELECT {_COLUMNS} FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",
            (hashlib.sha256(secret.encode()).hexdigest(), time.time()),
        ).fetchone()
    if row is None:
        return None
    user, world = store.get_user(row["user_id"]), store.get_world(row["world_id"])
    if (
        not user
        or not user.get("enabled", True)
        or not user.get("email_verified", True)
        or not world
        or world["owner_id"] != user["id"]
    ):
        return None
    # An administrator's personal token never inherits cross-account privileges.
    user = {**user, "role": "member", "can_create_city": False, "api_token_id": row["id"]}
    return user, world, _public(row)


def touch(store, token_id):
    now = time.time()
    with store._db() as db:
        db.execute(
            "UPDATE api_tokens SET last_used_at=? WHERE id=? AND (last_used_at IS NULL OR last_used_at<?)",
            (now, token_id, now - 60),
        )
