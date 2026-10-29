"""Version-bound discussions with author edits and scoped moderation."""

from __future__ import annotations

import time

from .validation import identifier, text


class Discussions:
    def target(self, db, kind, target_id, version=0):
        if kind == "publication":
            return self._publication(db, target_id, version or None)
        if kind == "post":
            row = db.execute(
                "SELECT * FROM community_posts WHERE id=? AND status='published'", (target_id,)
            ).fetchone()
            return dict(row) if row else None
        return None

    def get_post(self, pid):
        with self.accounts._db() as db:
            row = self.target(db, "post", pid)
            return {**row, "author": self.public_profile(db, row["author_id"])} if row else None

    def posts(self, *, category="", offset=0):
        with self.accounts._db() as db:
            rows = db.execute(
                "SELECT * FROM community_posts WHERE status='published' AND (?='' OR category=?)"
                " ORDER BY created_at DESC LIMIT 24 OFFSET ?",
                (category, category, max(0, int(offset))),
            )
            return [{**dict(r), "author": self.public_profile(db, r["author_id"])} for r in rows]

    def post(self, user, data):
        user = self.authorize(user)
        title, body = text(data, "title", 160, required=True), text(data, "body", 20000, required=True)
        category = data.get("category", "question")
        if category not in {"question", "method", "share"}:
            raise ValueError("帖子分类须为研究问题、方法讨论或成果分享")
        pid, linked = identifier(), str(data.get("publication_id") or "")
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            from gaworld.accounts.resources import check_community_storage

            check_community_storage(self.accounts, db, user["id"], len(body.encode()))
            if category == "share" and (not linked or not self._publication(db, linked)):
                raise ValueError("请选择一个公开成果")
            db.execute(
                "INSERT INTO community_posts(id,author_id,title,body,category,publication_id,created_at) VALUES(?,?,?,?,?,?,?)",
                (pid, user["id"], title, body, category, linked, time.time()),
            )
        return self.get_post(pid)

    def comments(self, kind, tid, version=0, offset=0):
        with self.accounts._db() as db:
            if not self.target(db, kind, tid, version):
                return []
            rows = db.execute(
                "SELECT * FROM community_comments WHERE target_type=? AND target_id=?"
                " AND (?=0 OR version=?) ORDER BY created_at,id LIMIT 100 OFFSET ?",
                (kind, tid, int(version), int(version), max(0, int(offset))),
            )
            return [
                {
                    **dict(r),
                    "body": r["body"] if r["status"] == "published" else "评论已删除",
                    "author": self.public_profile(db, r["author_id"]),
                }
                for r in rows
            ]

    def comment(self, user, data):
        user = self.authorize(user)
        body = text(data, "body", 5000, required=True)
        kind, tid = data.get("target_type"), str(data.get("target_id") or "")
        version, parent_id, cid = (
            int(data.get("version") or 0),
            str(data.get("parent_id") or ""),
            identifier(),
        )
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            from gaworld.accounts.resources import check_community_storage

            check_community_storage(self.accounts, db, user["id"], len(body.encode()))
            target = self.target(db, kind, tid, version)
            if not target or target["locked"]:
                raise ValueError("讨论不存在或已锁定")
            if kind == "publication" and version <= 0:
                raise ValueError("请选择具体成果版本")
            parent = None
            if parent_id:
                parent = db.execute("SELECT * FROM community_comments WHERE id=?", (parent_id,)).fetchone()
                if (
                    not parent
                    or (parent["target_type"], parent["target_id"], parent["version"]) != (kind, tid, version)
                    or parent["parent_id"]
                ):
                    raise ValueError("回复只能关联同一目标和版本的一级评论")
            db.execute(
                "INSERT INTO community_comments(id,author_id,target_type,target_id,version,parent_id,body,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (cid, user["id"], kind, tid, version, parent_id, body, time.time()),
            )
            recipients = {target["author_id"]}
            if parent:
                recipients.add(parent["author_id"])
            for uid in recipients - {user["id"]}:
                self.notify(db, uid, kind, tid, "你的讨论收到新回复")
        return {"id": cid, "version": version}

    def edit_comment(self, user, cid, body):
        user = self.authorize(user)
        body = text({"body": body}, "body", 5000, required=True)
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM community_comments WHERE id=? AND author_id=? AND status='published'",
                (cid, user["id"]),
            ).fetchone()
            if not row or not self.target(db, row["target_type"], row["target_id"], row["version"]):
                raise ValueError("评论不存在或不属于你")
            from gaworld.accounts.resources import check_community_storage

            check_community_storage(self.accounts, db, user["id"], len(body.encode()))
            db.execute(
                "INSERT INTO community_comment_edits(comment_id,body,at) VALUES(?,?,?)",
                (cid, row["body"], time.time()),
            )
            db.execute(
                "UPDATE community_comments SET body=?,edited_at=? WHERE id=?", (body, time.time(), cid)
            )
        return {"ok": True}

    def delete_comment(self, user, cid):
        user = self.authorize(user)
        with self.accounts._db() as db:
            row = db.execute(
                "SELECT * FROM community_comments WHERE id=? AND author_id=?", (cid, user["id"])
            ).fetchone()
            if not row:
                raise ValueError("评论不存在或不属于你")
            db.execute("UPDATE community_comments SET status='deleted' WHERE id=?", (cid,))
        return {"ok": True}

    def moderate(self, user, kind, tid, action, reason):
        user = self.authorize(user, management=True)
        if user["role"] != "admin" and not user.get("moderator"):
            raise ValueError("该操作需要社区管理权限")
        reason = text({"reason": reason}, "reason", 1000, required=True)
        tables = {
            "publication": "community_publications",
            "post": "community_posts",
            "comment": "community_comments",
        }
        table = tables.get(kind)
        if table is None or action not in {"hide", "restore", "lock", "unlock", "feature", "unfeature"}:
            raise ValueError("管理操作无效")
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(f"SELECT status FROM {table} WHERE id=?", (tid,)).fetchone()
            if not existing:
                raise ValueError("目标不存在")
            held = (
                kind == "publication"
                and db.execute("SELECT 1 FROM community_holds WHERE publication_id=?", (tid,)).fetchone()
            )
            if action == "restore" and existing[0] != "hidden" and not held:
                raise ValueError("只能恢复被管理员隐藏的内容")
            if action == "hide" and existing[0] not in {"published", "hidden"}:
                raise ValueError("不能修改作者已撤回或删除的内容")
            if kind == "publication" and action == "hide":
                db.execute("INSERT OR IGNORE INTO community_holds VALUES(?,?)", (tid, time.time()))
            if kind == "publication" and action == "restore":
                db.execute("DELETE FROM community_holds WHERE publication_id=?", (tid,))
            if action in {"hide", "restore"}:
                db.execute(
                    f"UPDATE {table} SET status=? WHERE id=?",
                    (
                        "hidden"
                        if action == "hide"
                        else "withdrawn"
                        if existing[0] == "withdrawn"
                        else "published",
                        tid,
                    ),
                )
            elif action in {"lock", "unlock"} and kind != "comment":
                db.execute(f"UPDATE {table} SET locked=? WHERE id=?", (int(action == "lock"), tid))
            elif action in {"feature", "unfeature"} and kind == "publication":
                db.execute(f"UPDATE {table} SET featured=? WHERE id=?", (int(action == "feature"), tid))
            else:
                raise ValueError("该目标不支持此操作")
            db.execute(
                "UPDATE community_reports SET status='resolved',resolution=? WHERE target_type=? AND target_id=? AND status='open'",
                (reason, kind, tid),
            )
            self.audit(db, user, kind, tid, action, reason)
        return {"ok": True}
