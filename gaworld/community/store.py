"""Community service facade with independent, explicitly public read methods."""

from __future__ import annotations

from .discussions import Discussions
from .publications import Publications
from .social import Social


class CommunityStore(Publications, Discussions, Social):
    def __init__(self, accounts):
        self.accounts = accounts

    def authorize(self, user, *, verified=True, management=False):
        if management and (user or {}).get("id") == 0 and (user or {}).get("role") == "admin":
            return user
        current = self.accounts.get_user((user or {}).get("id", -1))
        if not current or not current.get("enabled"):
            raise ValueError("请先登录有效账号")
        if verified and not current.get("email_verified"):
            raise ValueError("请先验证邮箱")
        return current

    @staticmethod
    def public_profile(db, uid):
        row = db.execute(
            "SELECT public_id,display_name,bio,interests,avatar FROM account_profiles WHERE user_id=?", (uid,)
        ).fetchone()
        return dict(row) if row else {"display_name": "研究者"}

    def profile(self, public_id):
        with self.accounts._db() as db:
            row = db.execute(
                "SELECT user_id FROM account_profiles WHERE public_id=? AND enabled=1", (public_id,)
            ).fetchone()
            if not row:
                return None
            result = self.public_profile(db, row[0])
        return {**result, "publications": self.publications(author_id=row[0])}

    def settings(self, user, data=None):
        user = self.authorize(user, management=True)
        if user["role"] != "admin":
            raise ValueError("平台资源设置需要管理员权限")
        from gaworld.accounts.resources import DEFAULTS, limit

        keys = {*DEFAULTS, "daily_llm_calls_per_user"}
        if data is not None:
            for key, value in data.items():
                if key not in keys or type(value) is not int or value < 0 or value > 1000000:
                    raise ValueError("额度须为 0–1000000 的整数；0 表示不限制")
            for key, value in data.items():
                self.accounts.set_setting(key, value)
            self.accounts.audit(user, "community_limits", str(data))
        return {key: limit(self.accounts, key) for key in DEFAULTS} | {
            "daily_llm_calls_per_user": self.accounts.get_setting("daily_llm_calls_per_user", 0)
        }

    def delete_draft(self, user, did):
        user = self.authorize(user)
        with self.accounts._db() as db:
            deleted = db.execute(
                "DELETE FROM community_drafts WHERE id=? AND author_id=? AND published_version IS NULL",
                (did, user["id"]),
            ).rowcount
        if not deleted:
            raise ValueError("未发布草稿不存在或不属于你")
        return {"ok": True}
