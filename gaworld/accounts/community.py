"""Additive public-community identities; legacy invite identities remain verified."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from .store import AccountError, AccountStore, _digest, check_nickname, check_password, hash_password

Sender = Callable[[str, str, str], None]
SCHEMA = """
CREATE TABLE IF NOT EXISTS account_schema(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS account_profiles(
 user_id INTEGER PRIMARY KEY REFERENCES users(id), public_id TEXT NOT NULL UNIQUE,
 display_name TEXT NOT NULL, email TEXT UNIQUE COLLATE NOCASE, email_verified INTEGER NOT NULL DEFAULT 1,
 enabled INTEGER NOT NULL DEFAULT 1, moderator INTEGER NOT NULL DEFAULT 0,
 bio TEXT NOT NULL DEFAULT '', interests TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS account_tokens(
 digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 expires_at REAL NOT NULL, used_at REAL);
CREATE TABLE IF NOT EXISTS account_rate_limits(key TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS call_baselines(day TEXT NOT NULL, user_id INTEGER NOT NULL, calls INTEGER NOT NULL,
 PRIMARY KEY(day,user_id));
CREATE TABLE IF NOT EXISTS call_reservations(
 id TEXT PRIMARY KEY, day TEXT NOT NULL, user_id INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS call_reservation_usage ON call_reservations(day,user_id,status);
"""


def migrate(store: AccountStore) -> None:
    with store._db() as db:
        legacy = not db.execute("SELECT 1 FROM sqlite_master WHERE name='account_schema'").fetchone()
        backup_path = store.path + ".pre-community.sqlite"
        if (
            legacy
            and db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            and not os.path.exists(backup_path)
        ):
            with sqlite3.connect(backup_path) as backup:
                os.chmod(backup_path, 0o600)
                db.backup(backup)
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT id,nickname FROM users"):
            db.execute(
                "INSERT OR IGNORE INTO account_profiles(user_id,public_id,display_name) VALUES(?,?,?)",
                (row["id"], "u" + secrets.token_hex(10), row["nickname"]),
            )
        db.execute("INSERT OR IGNORE INTO account_schema VALUES(1,?)", (time.time(),))
        from gaworld.community.schema import SCHEMA as community_schema

        db.executescript(community_schema)


def augment(store: AccountStore, user: dict[str, Any] | None) -> dict[str, Any] | None:
    if user is None:
        return None
    with store._db() as db:
        row = db.execute("SELECT * FROM account_profiles WHERE user_id=?", (user["id"],)).fetchone()
    # AccountStore.create_user/invite may have inserted a user since migration.
    if row is None:
        return {**user, "email_verified": True, "enabled": True, "display_name": user["nickname"]}
    return {**user, **{key: row[key] for key in dict(row) if key != "user_id"}}


def email_address(value: str) -> str:
    value = str(value or "").strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
        raise AccountError("请输入有效邮箱")
    return value


def issue_token(db: sqlite3.Connection, uid: int, kind: str) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM account_tokens WHERE user_id=? AND kind=?", (uid, kind))
    db.execute(
        "INSERT INTO account_tokens VALUES(?,?,?,?,NULL)", (_digest(token), uid, kind, time.time() + 3600)
    )
    return token


def register_open(
    store: AccountStore, username: str, password: str, email: str, display_name: str, sender: Sender
) -> dict[str, Any]:
    if os.environ.get("GAWORLD_REGISTRATION", "invite") != "open" or not store.has_admin():
        raise AccountError("开放注册未启用，请联系管理员")
    username, email = check_nickname(username), email_address(email)
    if not re.fullmatch(r"[A-Za-z0-9_\-]{3,32}", username):
        raise AccountError("用户名须为 3–32 位字母、数字、下划线或连字符")
    display_name = check_nickname(display_name or username)
    password_hash = hash_password(check_password(password))
    try:
        with store._db() as db:
            db.execute("BEGIN IMMEDIATE")
            user = store._insert_user(db, username, password_hash, "member", False, "")
            db.execute(
                "UPDATE account_profiles SET display_name=?,email=?,email_verified=0 WHERE user_id=?",
                (display_name, email, user["id"]),
            )
            token = issue_token(db, user["id"], "verify")
    except sqlite3.IntegrityError as exc:
        raise AccountError("用户名或邮箱已被使用") from exc
    sender(email, "verify", token)
    return store.get_user(user["id"])


def _consume(db: sqlite3.Connection, token: str, kind: str) -> int:
    row = db.execute(
        "SELECT user_id FROM account_tokens WHERE digest=? AND kind=? AND used_at IS NULL AND expires_at>?",
        (_digest(str(token)), kind, time.time()),
    ).fetchone()
    if row is None:
        raise AccountError("链接无效、已使用或已过期")
    db.execute("UPDATE account_tokens SET used_at=? WHERE digest=?", (time.time(), _digest(token)))
    return int(row[0])


def verify_email(store: AccountStore, token: str) -> dict[str, Any]:
    with store._db() as db:
        db.execute("BEGIN IMMEDIATE")
        uid = _consume(db, token, "verify")
        db.execute("UPDATE account_profiles SET email_verified=1 WHERE user_id=? AND enabled=1", (uid,))
    return store.get_user(uid)


def recover(store: AccountStore, email: str, sender: Sender, *, kind: str = "recover") -> None:
    email = email_address(email)
    with store._db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT user_id,email_verified FROM account_profiles WHERE email=? AND enabled=1", (email,)
        ).fetchone()
        if row is None or (kind == "verify" and row["email_verified"]):
            return
        token = issue_token(db, row["user_id"], kind)
    sender(email, kind, token)


def reset_email_password(store: AccountStore, token: str, password: str) -> None:
    password_hash = hash_password(check_password(password))
    with store._db() as db:
        db.execute("BEGIN IMMEDIATE")
        uid = _consume(db, token, "recover")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))
        db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))


def set_status(store: AccountStore, uid: int, *, enabled: bool, moderator: bool | None = None) -> None:
    with store._db() as db:
        db.execute("UPDATE account_profiles SET enabled=? WHERE user_id=?", (int(enabled), uid))
        if moderator is not None:
            db.execute("UPDATE account_profiles SET moderator=? WHERE user_id=?", (int(moderator), uid))
        if not enabled:
            db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            db.execute("DELETE FROM account_tokens WHERE user_id=?", (uid,))


def update_profile(store: AccountStore, uid: int, data: dict) -> dict:
    name = check_nickname(data.get("display_name", ""))
    bio, interests, avatar = (str(data.get(k) or "").strip() for k in ("bio", "interests", "avatar"))
    if (
        len(bio) > 2000
        or len(interests) > 500
        or (avatar and not avatar.startswith("https://"))
        or len(avatar) > 500
    ):
        raise AccountError("简介或兴趣过长，头像须为 HTTPS 地址")
    with store._db() as db:
        db.execute(
            "UPDATE account_profiles SET display_name=?,bio=?,interests=?,avatar=? WHERE user_id=?",
            (name, bio, interests, avatar, uid),
        )
    return store.get_user(uid)


def rate_limit(store: AccountStore, key: str, limit: int, seconds: int = 300) -> None:
    key = hashlib.sha256(key.encode()).hexdigest()
    window = int(time.time()) // seconds * seconds
    with store._db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "DELETE FROM account_rate_limits WHERE window<?", (int(time.time()) - max(86400, seconds * 2),)
        )
        db.execute(
            "INSERT INTO account_rate_limits VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET"
            " count=CASE WHEN window=excluded.window THEN count+1 ELSE 1 END,window=excluded.window",
            (key, window),
        )
        count = db.execute("SELECT count FROM account_rate_limits WHERE key=?", (key,)).fetchone()[0]
    if count > limit:
        raise AccountError("操作过于频繁，请稍后再试")


def reserve_call(store: AccountStore, uid: int) -> str:
    user = store.get_user(uid)
    if not user or not user["enabled"] or not user["email_verified"]:
        raise AccountError("账号未验证或已停用，无法调用模型")
    from .usage import TALLY

    baseline = TALLY.today(uid)
    day, token = time.strftime("%Y-%m-%d"), secrets.token_hex(16)
    limit = store.get_setting("daily_llm_calls_per_user", 0)
    with store._db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO call_baselines VALUES(?,?,?)", (day, uid, baseline))
        used = db.execute(
            "SELECT count(*) FROM call_reservations WHERE day=? AND user_id=? AND status!='released'",
            (day, uid),
        ).fetchone()[0]
        base = db.execute(
            "SELECT calls FROM call_baselines WHERE day=? AND user_id=?", (day, uid)
        ).fetchone()[0]
        if limit > 0 and user["role"] != "admin" and used + base >= limit:
            raise AccountError("今日模型调用额度已用尽")
        db.execute(
            "INSERT INTO call_reservations VALUES(?,?,?,?,?)", (token, day, uid, "reserved", time.time())
        )
    return token


def settle_call(store: AccountStore, token: str, *, attempted: bool = True) -> None:
    with store._db() as db:
        db.execute(
            "UPDATE call_reservations SET status=? WHERE id=? AND status='reserved'",
            ("attempted" if attempted else "released", token),
        )


def begin_model_call():
    """Check in-process and child-process identities before contacting a provider."""
    from pathlib import Path

    from . import enabled_store
    from .context import USER
    from .usage import ENV_USER

    user = USER.get()
    uid = (user or {}).get("id")
    if uid is None:
        try:
            uid = int(os.environ.get(ENV_USER, ""))
        except ValueError:
            return None
    if uid == 0:  # Existing operator-token admin.
        return None
    store = enabled_store(str(Path(__file__).resolve().parents[2]))
    if store is None:
        return None
    return store, reserve_call(store, uid)
