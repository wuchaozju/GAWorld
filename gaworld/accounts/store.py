"""Accounts for a shared classroom deployment: users, sessions, invites, audit.

One SQLite file (``output/accounts/accounts.sqlite`` by default). Its existence
is the switch: without it the dashboard stays the single-user console it has
always been. Codes and session tokens are shown once and stored only as
SHA-256 hashes; passwords are salted scrypt.

A connection is opened per call: the dashboard is a ThreadingHTTPServer and
sqlite3 connections are not shareable across threads.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from collections.abc import Iterator
from typing import Any

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
MAX_NICKNAME_LENGTH = 32
SESSION_SECONDS = 7 * 24 * 3600
RESET_SECONDS = 24 * 3600

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    can_create_city INTEGER NOT NULL DEFAULT 0,
    label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
    code_hash TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    can_create_city INTEGER NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL,
    created_by INTEGER,
    created_at REAL NOT NULL,
    used_by INTEGER,
    used_at REAL
);
CREATE TABLE IF NOT EXISTS resets (
    code_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at REAL NOT NULL,
    used_at REAL
);
CREATE TABLE IF NOT EXISTS city_owners (
    slug TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    city TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'class', 'open')),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    user_id INTEGER,
    nickname TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""

_USER_COLUMNS = "id, nickname, role, can_create_city, label, created_at"


class AccountError(ValueError):
    """A request the caller can fix (bad code, weak password, taken nickname)."""


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, key = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), key)


#: Burned on unknown nicknames so a login reply takes as long either way.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def check_password(password: str) -> str:
    password = str(password or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccountError(f"密码最多 {MAX_PASSWORD_LENGTH} 位")
    return password


def check_nickname(nickname: str) -> str:
    nickname = str(nickname or "").strip()
    if not nickname:
        raise AccountError("昵称不能为空")
    if len(nickname) > MAX_NICKNAME_LENGTH:
        raise AccountError(f"昵称最多 {MAX_NICKNAME_LENGTH} 个字符")
    if not nickname.isprintable():
        raise AccountError("昵称不能包含控制字符")
    return nickname


def _user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "role": row["role"],
        "can_create_city": bool(row["can_create_city"]),
        "label": row["label"],
        "created_at": row["created_at"],
    }


class AccountStore:
    def __init__(self, path: str) -> None:
        self.path = path

    @contextlib.contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self._db() as db:
            db.executescript(_SCHEMA)

    # -- users ------------------------------------------------------------

    def create_user(
        self,
        nickname: str,
        password: str,
        *,
        role: str = "member",
        can_create_city: bool = False,
        label: str = "",
    ) -> dict[str, Any]:
        nickname = check_nickname(nickname)
        password_hash = hash_password(check_password(password))
        with self._db() as db:
            return self._insert_user(db, nickname, password_hash, role, can_create_city, label)

    def _insert_user(
        self,
        db: sqlite3.Connection,
        nickname: str,
        password_hash: str,
        role: str,
        can_create_city: bool,
        label: str,
    ) -> dict[str, Any]:
        try:
            cur = db.execute(
                "INSERT INTO users (nickname, password_hash, role, can_create_city, label, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (nickname, password_hash, role, int(bool(can_create_city)), label, time.time()),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountError(f"昵称「{nickname}」已被使用") from exc
        row = db.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _user(row)  # type: ignore[return-value]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._db() as db:
            return _user(db.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone())

    def list_users(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(f"SELECT {_USER_COLUMNS} FROM users ORDER BY id").fetchall()
        return [_user(row) for row in rows]  # type: ignore[misc]

    def authenticate(self, nickname: str, password: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                f"SELECT {_USER_COLUMNS}, password_hash FROM users WHERE nickname = ?",
                (str(nickname or "").strip(),),
            ).fetchone()
        if row is None:
            verify_password(str(password or ""), _DUMMY_HASH)
            return None
        return _user(row) if verify_password(str(password or ""), row["password_hash"]) else None

    def change_password(self, user_id: int, old: str, new: str) -> None:
        user = self.get_user(user_id)
        if user is None or self.authenticate(user["nickname"], old) is None:
            raise AccountError("原密码不正确")
        self._set_password(user_id, new)

    def _set_password(self, user_id: int, password: str) -> None:
        password_hash = hash_password(check_password(password))
        with self._db() as db:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def set_can_create_city(self, user_id: int, allow: bool) -> dict[str, Any]:
        with self._db() as db:
            db.execute("UPDATE users SET can_create_city = ? WHERE id = ?", (int(bool(allow)), user_id))
        user = self.get_user(user_id)
        if user is None:
            raise AccountError(f"没有编号为 {user_id} 的用户")
        return user

    # -- sessions ---------------------------------------------------------

    def open_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (_digest(token), user_id, now + SESSION_SECONDS),
            )
        return token

    def session_user(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self._db() as db:
            row = db.execute(
                "SELECT u.id, u.nickname, u.role, u.can_create_city, u.label, u.created_at FROM sessions s"
                " JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
                (_digest(token), time.time()),
            ).fetchone()
        return _user(row)

    def close_session(self, token: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))

    # -- invites and resets -----------------------------------------------

    def create_invites(
        self,
        count: int,
        *,
        created_by: int | None = None,
        label: str = "",
        expires_days: float = 14,
        can_create_city: bool = False,
    ) -> list[str]:
        count = int(count)
        if not 1 <= count <= 200:
            raise AccountError("一次生成 1–200 个邀请码")
        now = time.time()
        codes = [secrets.token_urlsafe(9) for _ in range(count)]
        with self._db() as db:
            db.executemany(
                "INSERT INTO invites (code_hash, label, can_create_city, expires_at, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        _digest(code),
                        str(label or ""),
                        int(bool(can_create_city)),
                        now + float(expires_days) * 86400,
                        created_by,
                        now,
                    )
                    for code in codes
                ],
            )
        return codes

    def list_invites(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT i.rowid AS id, i.label, i.can_create_city, i.expires_at, i.created_at, i.used_at,"
                " u.nickname AS used_by"
                " FROM invites i LEFT JOIN users u ON u.id = i.used_by ORDER BY i.created_at DESC"
            ).fetchall()
        return [dict(row) | {"can_create_city": bool(row["can_create_city"])} for row in rows]

    def revoke_invite(self, invite_id: int) -> bool:
        """Delete an unused invite; a used one stays as the record of who joined."""
        with self._db() as db:
            cur = db.execute("DELETE FROM invites WHERE rowid = ? AND used_at IS NULL", (int(invite_id),))
        return cur.rowcount > 0

    def register(self, code: str, nickname: str, password: str) -> dict[str, Any]:
        nickname = check_nickname(nickname)
        password_hash = hash_password(check_password(password))
        now = time.time()
        with self._db() as db:
            invite = db.execute(
                "SELECT * FROM invites WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
                (_digest(str(code or "").strip()), now),
            ).fetchone()
            if invite is None:
                raise AccountError("邀请码无效、已使用或已过期")
            user = self._insert_user(
                db, nickname, password_hash, "member", bool(invite["can_create_city"]), invite["label"]
            )
            db.execute(
                "UPDATE invites SET used_by = ?, used_at = ? WHERE code_hash = ?",
                (user["id"], now, invite["code_hash"]),
            )
        return user

    def issue_reset(self, user_id: int) -> str:
        if self.get_user(user_id) is None:
            raise AccountError(f"没有编号为 {user_id} 的用户")
        code = secrets.token_urlsafe(9)
        with self._db() as db:
            db.execute("DELETE FROM resets WHERE user_id = ? AND used_at IS NULL", (user_id,))
            db.execute(
                "INSERT INTO resets (code_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (_digest(code), user_id, time.time() + RESET_SECONDS),
            )
        return code

    def reset_password(self, code: str, password: str) -> dict[str, Any]:
        check_password(password)
        now = time.time()
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM resets WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
                (_digest(str(code or "").strip()), now),
            ).fetchone()
            if row is None:
                raise AccountError("重置码无效、已使用或已过期")
            db.execute("UPDATE resets SET used_at = ? WHERE code_hash = ?", (now, row["code_hash"]))
        self._set_password(row["user_id"], password)
        return self.get_user(row["user_id"])  # type: ignore[return-value]

    # -- city ownership ---------------------------------------------------

    def set_city_owner(self, slug: str, user_id: int) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO city_owners (slug, user_id) VALUES (?, ?)"
                " ON CONFLICT(slug) DO UPDATE SET user_id = excluded.user_id",
                (slug, user_id),
            )

    def city_owner(self, slug: str) -> int | None:
        with self._db() as db:
            row = db.execute("SELECT user_id FROM city_owners WHERE slug = ?", (slug,)).fetchone()
        return None if row is None else int(row["user_id"])

    def forget_city(self, slug: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM city_owners WHERE slug = ?", (slug,))

    # -- worlds -----------------------------------------------------------

    def create_world(self, owner_id: int, name: str, city: str = "") -> dict[str, Any]:
        name = str(name or "").strip()
        if not name:
            raise AccountError("世界名称不能为空")
        if len(name) > 64:
            raise AccountError("世界名称最多 64 个字符")
        world_id = "w" + secrets.token_hex(4)
        with self._db() as db:
            db.execute(
                "INSERT INTO worlds (id, name, owner_id, city, visibility, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (world_id, name, owner_id, str(city or ""), "private", time.time()),
            )
        return self.get_world(world_id)  # type: ignore[return-value]

    def get_world(self, world_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute(
                "SELECT w.*, u.nickname AS owner FROM worlds w JOIN users u ON u.id = w.owner_id WHERE w.id = ?",
                (str(world_id or ""),),
            ).fetchone()
        return None if row is None else dict(row)

    def list_worlds(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT w.*, u.nickname AS owner FROM worlds w JOIN users u ON u.id = w.owner_id ORDER BY w.created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_world_visibility(self, world_id: str, visibility: str) -> dict[str, Any]:
        if visibility not in ("private", "class", "open"):
            raise AccountError("可见性只能是 private / class / open")
        with self._db() as db:
            db.execute("UPDATE worlds SET visibility = ? WHERE id = ?", (visibility, world_id))
        world = self.get_world(world_id)
        if world is None:
            raise AccountError(f"没有编号为 {world_id} 的世界")
        return world

    def delete_world(self, world_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM worlds WHERE id = ?", (world_id,))

    # -- settings ---------------------------------------------------------

    def get_setting(self, key: str, default: int) -> int:
        with self._db() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        try:
            return int(row["value"]) if row is not None else default
        except ValueError:
            return default

    def set_setting(self, key: str, value: int) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(int(value))),
            )

    # -- audit ------------------------------------------------------------

    def audit(self, user: dict[str, Any] | None, action: str, detail: str = "") -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO audit (at, user_id, nickname, action, detail) VALUES (?, ?, ?, ?, ?)",
                (time.time(), (user or {}).get("id"), (user or {}).get("nickname", ""), action, detail[:500]),
            )

    def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(row) for row in rows]
