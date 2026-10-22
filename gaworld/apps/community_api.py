"""Public community reads and authenticated, owner-checked writes."""

from gaworld import accounts
from gaworld.accounts.context import USER
from gaworld.apps import world_paths
from gaworld.community import sources
from gaworld.community.store import CommunityStore


def service():
    store = accounts.enabled_store(world_paths.REPO_ROOT)
    return CommunityStore(store) if store else None


def _one(query, key, default=""):
    return (query.get(key) or [default])[0]


def handle_get(path, query):
    store = service()
    prefix = "/api/community/"
    endpoint = path.removeprefix(prefix).strip("/")
    parts = endpoint.split("/")
    if store is None:
        return (
            ({"publications": [], "posts": [], "message": "社区账号服务尚未启用"}, 200)
            if endpoint in {"publications", "posts"}
            else ({"error": "社区账号服务尚未启用"}, 404)
        )
    user = USER.get()
    if endpoint == "publications":
        return {
            "publications": store.publications(
                query=_one(query, "q"),
                kind=_one(query, "kind"),
                tag=_one(query, "tag"),
                offset=int(_one(query, "offset", 0)),
            )
        }, 200
    if len(parts) == 2 and parts[0] == "publications":
        item = store.publication(parts[1], int(_one(query, "version", 0)) or None)
        return (item, 200) if item else ({"error": "成果不存在或已撤回"}, 404)
    if len(parts) == 2 and parts[0] == "people":
        item = store.profile(parts[1])
        return (item, 200) if item else ({"error": "用户不存在"}, 404)
    if endpoint == "posts":
        return {
            "posts": store.posts(category=_one(query, "category"), offset=int(_one(query, "offset", 0)))
        }, 200
    if len(parts) == 2 and parts[0] == "posts":
        item = store.get_post(parts[1])
        return (item, 200) if item else ({"error": "帖子不存在"}, 404)
    if endpoint == "comments":
        return {
            "comments": store.comments(
                _one(query, "target_type"),
                _one(query, "target_id"),
                int(_one(query, "version", 0)),
                int(_one(query, "offset", 0)),
            )
        }, 200
    if endpoint == "attachment":
        item = store.attachment(
            _one(query, "id"), int(_one(query, "version", 0)), _one(query, "attachment_id")
        )
        return (item, 200) if item else ({"error": "附件不存在"}, 404)
    if endpoint == "settings":
        return store.settings(user), 200
    if endpoint == "mine":
        return store.mine(user), 200
    if endpoint == "bookmarks":
        return {"bookmarks": store.bookmarks(user)}, 200
    if endpoint == "notifications":
        return {"notifications": store.notifications(user)}, 200
    if endpoint == "reports":
        return {"reports": store.reports(user)}, 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path, payload):
    store = service()
    if store is None:
        return {"error": "请先由管理员初始化账号服务"}, 503
    endpoint = path.removeprefix("/api/community/").strip("/")
    user = store.authorize(USER.get(), management=endpoint in {"moderate", "settings"})
    if endpoint == "settings":
        return store.settings(user, payload), 200
    if endpoint == "drafts/delete":
        return store.delete_draft(user, payload.get("id")), 200
    if endpoint == "revision-source":
        with store.accounts._db() as db:
            import json

            row = db.execute(
                "SELECT v.content FROM community_publications p JOIN community_versions v ON v.publication_id=p.id AND v.version=p.current_version WHERE p.id=? AND p.author_id=?",
                (payload.get("id"), user["id"]),
            ).fetchone()
        if not row:
            raise ValueError("成果不存在或不属于你")
        return {"content": json.loads(row[0])}, 200
    if endpoint == "source":
        return sources.source_preview(user, payload), 200
    if endpoint == "drafts":
        source = None
        if payload.get("source"):
            requested = payload["source"]
            source = sources.source_preview(user, requested)
            if source["revision"] != requested.get("revision"):
                raise ValueError("来源已修改，请重新预览")
        return store.draft(user, payload, source=source), 200
    if endpoint == "publish":
        draft = store.get_draft(user, payload.get("draft_id", ""))
        source = draft["content"].get("source")
        if source and draft["published_version"] is None:
            current = sources.source_preview(user, source)
            if source["revision"] != current["revision"]:
                raise ValueError("来源已修改，请重新预览后发布")
        return store.publish(user, draft["id"], payload.get("revision", "")), 200
    if endpoint == "withdraw":
        return store.withdraw(user, payload.get("id", "")), 200
    if endpoint == "fork":
        return sources.fork(
            store,
            user,
            payload.get("id", ""),
            int(payload.get("version", 0)),
            str(payload.get("world_id") or ""),
        ), 200
    if endpoint == "posts":
        return store.post(user, payload), 200
    if endpoint == "comments":
        return store.comment(user, payload), 200
    if endpoint == "comments/edit":
        return store.edit_comment(user, payload.get("id", ""), payload.get("body", "")), 200
    if endpoint == "comments/delete":
        return store.delete_comment(user, payload.get("id", "")), 200
    if endpoint == "bookmarks":
        if not isinstance(payload.get("enabled"), bool):
            raise ValueError("enabled 必须是布尔值")
        return store.bookmark(
            user, payload.get("target_type"), payload.get("target_id"), payload["enabled"]
        ), 200
    if endpoint == "notifications/seen":
        return store.seen(user), 200
    if endpoint == "reports":
        return store.report(
            user, payload.get("target_type"), payload.get("target_id"), payload.get("reason", "")
        ), 200
    if endpoint == "moderate":
        return store.moderate(
            user,
            payload.get("target_type"),
            payload.get("target_id"),
            payload.get("action"),
            payload.get("reason", ""),
        ), 200
    return {"error": "Unknown endpoint"}, 404
