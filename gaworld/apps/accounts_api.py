"""``/api/auth/*``: sign in, register with an invite, reset, and admin chores.

Access levels are enforced before this module is reached (``_guard`` in
``dashboard_server`` with :mod:`gaworld.accounts.policy`); handlers here only
get the signed-in user (or None on the public endpoints). Every handler returns
``(payload, status, set_cookie)`` -- the cookie value is a full ``Set-Cookie``
header or None.
"""

from __future__ import annotations

from typing import Any

from gaworld.accounts import AccountError, AccountStore

SESSION_COOKIE = "gaworld_session"


def session_cookie(token: str) -> str:
    return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={7 * 24 * 3600}"


def clear_cookie() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


Result = tuple[dict[str, Any], int, str | None]


def handle_get(store: AccountStore | None, user: dict[str, Any] | None, path: str) -> Result:
    path = path.rstrip("/")
    if path == "/api/auth/me":
        if store is None:
            return {"mode": "single"}, 200, None
        return {"mode": "accounts", "user": user}, 200, None
    if store is None:
        return {"error": "账号功能未开启"}, 404, None
    if path == "/api/auth/users":
        return {"users": store.list_users()}, 200, None
    if path == "/api/auth/invites":
        return {"invites": store.list_invites()}, 200, None
    if path == "/api/auth/audit":
        return {"audit": store.list_audit()}, 200, None
    if path == "/api/auth/usage":
        from gaworld.accounts import usage

        tally = usage.TALLY.snapshot()
        from gaworld.apps import dashboard_server as ds

        rows = [
            {
                **user,
                "today": tally["today"].get(user["id"], 0),
                "total": tally["total"].get(user["id"], 0),
                "last_seen": ds.LAST_SEEN.get(user["id"]),
            }
            for user in store.list_users()
        ]
        return {"users": rows, "quota": store.get_setting("daily_llm_calls_per_user", 0)}, 200, None
    return {"error": f"unknown endpoint: {path}"}, 404, None


def handle_post(
    store: AccountStore | None,
    user: dict[str, Any] | None,
    path: str,
    payload: dict[str, Any],
    session: str = "",
) -> Result:
    if store is None:
        return {"error": "账号功能未开启"}, 404, None
    path = path.rstrip("/")
    try:
        return _post(store, user, path, payload, session)
    except AccountError as exc:
        return {"error": str(exc)}, 400, None


def _post(
    store: AccountStore, user: dict[str, Any] | None, path: str, payload: dict[str, Any], session: str
) -> Result:
    if path == "/api/auth/login":
        found = store.authenticate(str(payload.get("nickname") or ""), str(payload.get("password") or ""))
        if found is None:
            store.audit(None, "login_failed", str(payload.get("nickname") or "")[:64])
            return {"error": "昵称或密码不正确"}, 401, None
        store.audit(found, "login")
        return {"user": found}, 200, session_cookie(store.open_session(found["id"]))
    if path == "/api/auth/register":
        created = store.register(
            payload.get("code", ""), payload.get("nickname", ""), payload.get("password", "")
        )
        store.audit(created, "register", created["label"])
        return {"user": created}, 200, session_cookie(store.open_session(created["id"]))
    if path == "/api/auth/reset":
        changed = store.reset_password(payload.get("code", ""), payload.get("password", ""))
        store.audit(changed, "password_reset")
        return {"user": changed}, 200, session_cookie(store.open_session(changed["id"]))
    if path == "/api/auth/logout":
        if session:
            store.close_session(session)
        return {"ok": True}, 200, clear_cookie()
    if user is None or not user.get("id"):
        # The env-token admin has no row to change or invite from.
        return {"error": "该操作需要以账号登录"}, 403, None
    if path == "/api/auth/password":
        store.change_password(user["id"], payload.get("old", ""), payload.get("new", ""))
        store.audit(user, "password_change")
        # Changing the password signs every session out, this one included.
        return {"user": user}, 200, session_cookie(store.open_session(user["id"]))
    if path == "/api/auth/invites":
        codes = store.create_invites(
            int(payload.get("count") or 1),
            created_by=user["id"],
            label=str(payload.get("label") or ""),
            expires_days=float(payload.get("expires_days") or 14),
            can_create_city=bool(payload.get("can_create_city")),
        )
        store.audit(user, "invite", f"count={len(codes)} label={payload.get('label') or ''}")
        return {"codes": codes}, 200, None
    parts = path.split("/")  # ["", "api", "auth", "users"|"invites", "<id>", "<action>"]
    if len(parts) == 6 and parts[3] == "invites" and parts[5] == "revoke":
        try:
            revoked = store.revoke_invite(int(parts[4]))
        except ValueError:
            raise AccountError("邀请码编号必须是整数") from None
        if revoked:
            store.audit(user, "invite_revoke", parts[4])
        return {"revoked": revoked}, 200, None
    if len(parts) == 6 and parts[3] == "users":
        try:
            target = int(parts[4])
        except ValueError:
            raise AccountError("用户编号必须是整数") from None
        if parts[5] == "reset":
            code = store.issue_reset(target)
            store.audit(user, "reset_issue", f"user_id={target}")
            return {"code": code}, 200, None
        if parts[5] == "city":
            changed = store.set_can_create_city(target, bool(payload.get("allow")))
            store.audit(user, "city_permission", f"user_id={target} allow={changed['can_create_city']}")
            return {"user": changed}, 200, None
    return {"error": f"unknown endpoint: {path}"}, 404, None
