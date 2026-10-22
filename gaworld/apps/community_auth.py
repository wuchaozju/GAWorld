"""Optional public-account endpoints layered over the existing invite auth API."""

from __future__ import annotations

import os

from gaworld.accounts import AccountError, community, mail


def config():
    return {
        "registration": os.environ.get("GAWORLD_REGISTRATION", "invite"),
        "public_community": os.environ.get("GAWORLD_REGISTRATION") == "open",
    }


def post(store, user, path, payload, session):
    from gaworld.apps.accounts_api import session_cookie

    if path == "/api/auth/register" and not payload.get("code"):
        created = community.register_open(
            store,
            payload.get("nickname", ""),
            payload.get("password", ""),
            payload.get("email", ""),
            payload.get("display_name", ""),
            mail.send,
        )
        store.audit(created, "open_register")
        return (
            {"user": created, "verification_required": True},
            200,
            session_cookie(store.open_session(created["id"])),
        )
    if path == "/api/auth/verify":
        verified = community.verify_email(store, payload.get("code", ""))
        return {"user": verified}, 200, session_cookie(store.open_session(verified["id"]))
    if path in {"/api/auth/recover", "/api/auth/resend"}:
        email = community.email_address(payload.get("email", ""))
        community.rate_limit(store, "email:" + email, 3, 3600)
        community.recover(
            store,
            email,
            mail.send,
            kind="verify" if path.endswith("resend") else "recover",
        )
        return {"ok": True, "message": "若该邮箱符合条件，邮件已发送，请检查收件箱"}, 200, None
    if path == "/api/auth/recover/reset":
        community.reset_email_password(store, payload.get("code", ""), payload.get("password", ""))
        return {"ok": True}, 200, None
    if path == "/api/auth/profile":
        if not user or not user.get("id"):
            raise AccountError("请以账号登录")
        return {"user": community.update_profile(store, user["id"], payload)}, 200, None
    if path == "/api/auth/sessions/close-others":
        if not user or not user.get("id"):
            raise AccountError("请以账号登录")
        with store._db() as db:
            db.execute(
                "DELETE FROM sessions WHERE user_id=? AND token_hash!=?",
                (user["id"], community._digest(session)),
            )
        return {"ok": True}, 200, None
    if path == "/api/auth/users/status":
        if not user or user.get("role") != "admin":
            return {"error": "需要管理员权限"}, 403, None
        uid = int(payload.get("user_id", 0))
        target = store.get_user(uid)
        if not target:
            raise AccountError("用户不存在")
        if target["role"] == "admin":
            raise AccountError("不能通过社区接口停用管理员")
        enabled = payload.get("enabled", True)
        moderator = payload.get("moderator")
        if not isinstance(enabled, bool) or (moderator is not None and not isinstance(moderator, bool)):
            raise AccountError("enabled 和 moderator 必须为布尔值")
        community.set_status(store, uid, enabled=enabled, moderator=moderator)
        store.audit(user, "account_status", f"user={uid} enabled={enabled} moderator={moderator}")
        return {"ok": True}, 200, None
    return None
