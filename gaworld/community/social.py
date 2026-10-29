"""Bookmarks, minimal notifications and reports always recheck live visibility."""

from __future__ import annotations

import time

from .validation import identifier, text


class Social:
    def notify(self, db, uid, kind, tid, message):
        db.execute(
            "INSERT INTO community_notifications(id,user_id,target_type,target_id,message,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (identifier(), uid, kind, tid, message, time.time()),
        )

    def audit(self, db, user, kind, tid, action, reason):
        db.execute(
            "INSERT INTO community_actions(user_id,target_type,target_id,action,reason,created_at) VALUES(?,?,?,?,?,?)",
            (user["id"], kind, tid, action, reason, time.time()),
        )

    def bookmark(self, user, kind, tid, enabled):
        user = self.authorize(user)
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if enabled:
                if not self.target(db, kind, tid):
                    raise ValueError("目标不存在")
                db.execute(
                    "INSERT OR IGNORE INTO community_bookmarks VALUES(?,?,?,?)",
                    (user["id"], kind, tid, time.time()),
                )
            else:
                db.execute(
                    "DELETE FROM community_bookmarks WHERE user_id=? AND target_type=? AND target_id=?",
                    (user["id"], kind, tid),
                )
        return {"ok": True}

    def bookmarks(self, user):
        user = self.authorize(user, verified=False)
        with self.accounts._db() as db:
            rows = db.execute(
                "SELECT * FROM community_bookmarks WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
                (user["id"],),
            ).fetchall()
            return [
                {**dict(row), "target": target}
                for row in rows
                if (target := self.target(db, row["target_type"], row["target_id"]))
            ]

    def notifications(self, user):
        user = self.authorize(user, verified=False)
        with self.accounts._db() as db:
            rows = db.execute(
                "SELECT * FROM community_notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
                (user["id"],),
            ).fetchall()
            return [dict(row) for row in rows if self.target(db, row["target_type"], row["target_id"])]

    def seen(self, user):
        user = self.authorize(user, verified=False)
        with self.accounts._db() as db:
            db.execute("UPDATE community_notifications SET seen=1 WHERE user_id=?", (user["id"],))
        return {"ok": True}

    def report(self, user, kind, tid, reason):
        user = self.authorize(user)
        reason, rid = text({"reason": reason}, "reason", 1000, required=True), identifier()
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "comment":
                row = db.execute(
                    "SELECT * FROM community_comments WHERE id=? AND status='published'", (tid,)
                ).fetchone()
                target = row and self.target(db, row["target_type"], row["target_id"], row["version"])
            else:
                target = self.target(db, kind, tid)
            if not target:
                raise ValueError("目标不存在")
            db.execute(
                "INSERT INTO community_reports(id,user_id,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?,?)",
                (rid, user["id"], kind, tid, reason, time.time()),
            )
        return {"id": rid}

    def reports(self, user):
        user = self.authorize(user, management=True)
        if user["role"] != "admin" and not user.get("moderator"):
            raise ValueError("需要社区管理权限")
        with self.accounts._db() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM community_reports ORDER BY created_at DESC LIMIT 100")
            ]
