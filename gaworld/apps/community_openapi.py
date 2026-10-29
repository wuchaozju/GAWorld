"""OpenAPI definitions kept beside the community delegation surface."""


def paths():
    from gaworld.apps.openapi import BOOL, INT, OBJ, STR, _obj, _op, _q

    operations = {
        "/api/auth/config": ("get", None),
        "/api/auth/verify": ("post", _obj(("code",), code=STR)),
        "/api/auth/recover": ("post", _obj(("email",), email=STR)),
        "/api/auth/resend": ("post", _obj(("email",), email=STR)),
        "/api/auth/recover/reset": ("post", _obj(("code", "password"), code=STR, password=STR)),
        "/api/auth/profile": (
            "post",
            _obj(("display_name",), display_name=STR, bio=STR, interests=STR, avatar=STR),
        ),
        "/api/auth/sessions/close-others": ("post", OBJ),
        "/api/auth/users/status": ("post", _obj(("user_id",), user_id=INT, enabled=BOOL, moderator=BOOL)),
        "/api/workspace/overview": ("get", None),
        "/api/community/publications": ("get", None),
        "/api/community/publications/{publication_id}": ("get", None),
        "/api/community/people/{public_id}": ("get", None),
        "/api/community/posts/{post_id}": ("get", None),
        "/api/community/attachment": ("get", None),
        "/api/community/mine": ("get", None),
        "/api/community/revision-source": ("post", _obj(("id",), id=STR)),
        "/api/community/source": ("post", _obj(("kind", "id"), kind=STR, id=STR)),
        "/api/community/drafts": ("post", _obj(("title", "body"), title=STR, body=STR, source=OBJ)),
        "/api/community/publish": ("post", _obj(("draft_id", "revision"), draft_id=STR, revision=STR)),
        "/api/community/withdraw": ("post", _obj(("id",), id=STR)),
        "/api/community/fork": (
            "post",
            _obj(("id", "version", "world_id"), id=STR, version=INT, world_id=STR),
        ),
        "/api/community/comments/edit": ("post", _obj(("id", "body"), id=STR, body=STR)),
        "/api/community/comments/delete": ("post", _obj(("id",), id=STR)),
        "/api/community/notifications/seen": ("post", OBJ),
        "/api/community/moderate": (
            "post",
            _obj(
                ("target_type", "target_id", "action", "reason"),
                target_type=STR,
                target_id=STR,
                action=STR,
                reason=STR,
            ),
        ),
    }
    operations["/api/community/drafts/delete"] = ("post", _obj(("id",), id=STR))
    shared = {"settings", "posts", "comments", "bookmarks", "notifications", "reports"}
    query = tuple(
        _q(k, k)
        for k in (
            "q",
            "kind",
            "tag",
            "offset",
            "category",
            "version",
            "target_type",
            "target_id",
            "id",
            "attachment_id",
        )
    )
    result = {
        path: {
            method: _op(
                "community",
                path.rsplit("/", 1)[-1],
                body=body,
                query=query if method == "get" else (),
                errors={"400": "Invalid request", "404": "Not found", "503": "Community not initialized"},
            )
        }
        for path, (method, body) in operations.items()
    }
    for name in shared:
        methods = {"get": _op("community", name, query=query)}
        if name != "notifications":
            methods["post"] = _op("community", name, body=OBJ, errors={"400": "Invalid request"})
        result["/api/community/" + name] = methods
    return result
