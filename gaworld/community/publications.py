"""Private drafts become immutable public versions in one database transaction."""

from __future__ import annotations

import copy
import json
import time

from .validation import content, digest, identifier


class Publications:
    def draft(self, user, data, *, source=None):
        user = self.authorize(user)
        payload = content(data)
        payload["source"] = copy.deepcopy(source or {})
        payload["include_template"] = data.get("include_template") is True
        if not payload["include_template"]:
            payload["source"].pop("template", None)
        payload["kind"] = (source or {}).get("kind", "plan")
        payload["result_status"] = (source or {}).get("result_status", "plan")
        pid, did = str(data.get("publication_id") or identifier()), identifier()
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT author_id FROM community_publications WHERE id=?", (pid,)
            ).fetchone()
            if data.get("publication_id") and (not existing or existing[0] != user["id"]):
                raise ValueError("成果不存在或不属于你")
            from gaworld.accounts.resources import check_community_storage, limit

            pending = db.execute(
                "SELECT count(*) FROM community_drafts WHERE author_id=? AND published_version IS NULL",
                (user["id"],),
            ).fetchone()[0]
            maximum = limit(self.accounts, "max_pending_publications_per_user")
            if maximum > 0 and pending >= maximum:
                raise ValueError("未发布草稿数量已达到上限")
            check_community_storage(
                self.accounts, db, user["id"], len(json.dumps(payload, ensure_ascii=False).encode())
            )
            revision = digest(payload)
            db.execute(
                "INSERT INTO community_drafts VALUES(?,?,?,?,?,NULL,?)",
                (did, user["id"], pid, revision, json.dumps(payload, ensure_ascii=False), time.time()),
            )
        return {"id": did, "publication_id": pid, "revision": revision, **payload}

    def get_draft(self, user, did):
        user = self.authorize(user)
        with self.accounts._db() as db:
            row = db.execute(
                "SELECT * FROM community_drafts WHERE id=? AND author_id=?", (did, user["id"])
            ).fetchone()
        if not row:
            raise ValueError("发布草稿不存在")
        return {**dict(row), "content": json.loads(row["content"])}

    def publish(self, user, did, revision):
        user = self.authorize(user)
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = db.execute(
                "SELECT * FROM community_drafts WHERE id=? AND author_id=?", (did, user["id"])
            ).fetchone()
            if not draft or draft["revision"] != revision:
                raise ValueError("发布预览已过期，请重新预览")
            pid = draft["publication_id"]
            if draft["published_version"] is not None:
                previous = self._publication(db, pid, draft["published_version"])
                if previous is None:
                    raise ValueError("该成果已撤回或下架，请创建新的发布版本")
                return previous
            existing = db.execute("SELECT * FROM community_publications WHERE id=?", (pid,)).fetchone()
            if existing and (
                existing["status"] == "hidden"
                or db.execute("SELECT 1 FROM community_holds WHERE publication_id=?", (pid,)).fetchone()
            ):
                raise ValueError("成果已被下架，请联系管理员")
            if existing and existing["author_id"] != user["id"]:
                raise ValueError("成果不属于你")
            from gaworld.accounts.resources import check_community_storage

            check_community_storage(self.accounts, db, user["id"], len(draft["content"].encode()))
            now = time.time()
            version = existing["current_version"] + 1 if existing else 1
            if not existing:
                db.execute(
                    "INSERT INTO community_publications(id,author_id,created_at) VALUES(?,?,?)",
                    (pid, user["id"], now),
                )
            db.execute(
                "INSERT INTO community_versions VALUES(?,?,?,?,?)",
                (pid, version, draft["content"], revision, now),
            )
            db.execute(
                "UPDATE community_publications SET current_version=?,status='published' WHERE id=?",
                (version, pid),
            )
            db.execute("UPDATE community_drafts SET published_version=? WHERE id=?", (version, did))
            if version > 1:
                for row in db.execute(
                    "SELECT user_id FROM community_bookmarks WHERE target_type='publication' AND target_id=?",
                    (pid,),
                ):
                    self.notify(db, row[0], "publication", pid, f"成果已更新为 v{version}")
            self.audit(db, user, "publication", pid, "publish", f"v{version}")
            return self._publication(db, pid, version)

    def _publication(self, db, pid, version=None):
        row = db.execute(
            "SELECT * FROM community_publications WHERE id=? AND status='published'", (pid,)
        ).fetchone()
        if not row:
            return None
        record = db.execute(
            "SELECT * FROM community_versions WHERE publication_id=? AND version=?",
            (pid, version or row["current_version"]),
        ).fetchone()
        if not record:
            return None
        data = json.loads(record["content"])
        source = data.pop("source", {})
        data["reusable"] = bool(source.get("template")) and data["license"] != "read_only"
        data["source_revision"] = source.get("revision", "")
        data["public_template"] = source.get("template", {})
        data["attachments"] = [{k: v for k, v in a.items() if k != "text"} for a in data["attachments"]]
        return {
            **data,
            **dict(row),
            "version": record["version"],
            "checksum": record["checksum"],
            "published_at": record["created_at"],
            "author": self.public_profile(db, row["author_id"]),
            "versions": [
                r[0]
                for r in db.execute(
                    "SELECT version FROM community_versions WHERE publication_id=? ORDER BY version DESC",
                    (pid,),
                )
            ],
        }

    def publication(self, pid, version=None):
        with self.accounts._db() as db:
            return self._publication(db, pid, version)

    def publications(self, *, query="", kind="", tag="", offset=0, limit=24, author_id=None):
        with self.accounts._db() as db:
            params = []
            where = "p.status='published'"
            if author_id is not None:
                where += " AND p.author_id=?"
                params.append(author_id)
            if query:
                where += " AND (json_extract(v.content,'$.title') LIKE ? OR json_extract(v.content,'$.summary') LIKE ?)"
                params.extend(["%" + query[:200] + "%"] * 2)
            if kind:
                where += " AND json_extract(v.content,'$.kind')=?"
                params.append(kind)
            if tag:
                where += " AND EXISTS(SELECT 1 FROM json_each(v.content,'$.tags') WHERE value=?)"
                params.append(tag)
            rows = db.execute(
                "SELECT p.id FROM community_publications p JOIN community_versions v ON v.publication_id=p.id"
                " AND v.version=p.current_version WHERE "
                + where
                + " ORDER BY p.featured DESC,p.created_at DESC LIMIT ? OFFSET ?",
                (*params, min(100, max(1, int(limit))), max(0, int(offset))),
            ).fetchall()
            return [self._publication(db, r[0]) for r in rows]

    def mine(self, user):
        user = self.authorize(user, verified=False)
        with self.accounts._db() as db:
            publications = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM community_publications WHERE author_id=? ORDER BY created_at DESC",
                    (user["id"],),
                )
            ]
            drafts = [
                {**dict(r), "content": json.loads(r["content"])}
                for r in db.execute(
                    "SELECT * FROM community_drafts WHERE author_id=? AND published_version IS NULL ORDER BY created_at DESC LIMIT 100",
                    (user["id"],),
                )
            ]
        for item in publications:
            with self.accounts._db() as db:
                row = db.execute(
                    "SELECT content FROM community_versions WHERE publication_id=? AND version=?",
                    (item["id"], item["current_version"]),
                ).fetchone()
            item["title"] = json.loads(row[0])["title"]
        return {"publications": publications, "drafts": drafts}

    def withdraw(self, user, pid):
        user = self.authorize(user)
        with self.accounts._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT author_id,status FROM community_publications WHERE id=?", (pid,)
            ).fetchone()
            if not row or row[0] != user["id"]:
                raise ValueError("成果不存在或不属于你")
            db.execute("UPDATE community_publications SET status='withdrawn' WHERE id=?", (pid,))
            self.audit(db, user, "publication", pid, "withdraw", "作者撤回")
        return {"ok": True}

    def attachment(self, pid, version, aid):
        with self.accounts._db() as db:
            if not self._publication(db, pid, version):
                return None
            row = db.execute(
                "SELECT content FROM community_versions WHERE publication_id=? AND version=?", (pid, version)
            ).fetchone()
            return next((a for a in json.loads(row[0])["attachments"] if a["id"] == aid), None)

    def fork_payload(self, user, pid, version):
        self.authorize(user)
        with self.accounts._db() as db:
            if not self._publication(db, pid, version):
                raise ValueError("公开版本不存在")
            row = db.execute(
                "SELECT content FROM community_versions WHERE publication_id=? AND version=?", (pid, version)
            ).fetchone()
            data = json.loads(row[0])
        if data["license"] == "read_only" or not data["source"].get("template"):
            raise ValueError("该版本未授权复用或未包含可复用方案")
        return {
            "template": data["source"]["template"],
            "provenance": {
                "publication_id": pid,
                "version": version,
                "license": data["license"],
                "revision": digest(data["source"]["template"]),
            },
        }
