"""Who may call what, once accounts are on.

Members get an allowlist of writes that touch nothing shared: interviews,
games, research analysis and distilling a persona into ``output/personas/``.
What those make belongs to its maker (``gaworld.accounts.ownership``): only
they and admins list, read or delete it.
City-bundle edits need ``can_create_city`` (and, for an existing city, being
its creator — checked by the dashboard, which knows the city). World writes —
the run, its config, the residents' files, interventions — are allowed in the
request's active world to its owner (``gaworld.worlds``); in the shared default
world they stay admin-only. Everything else that writes is admin-only; reads
are open to every signed-in member (secrets are already masked by the API, and
the dashboard only lets a request into a world its user may see).
"""

from __future__ import annotations

from typing import Any, Literal

Level = Literal["public", "member", "city", "world", "admin"]

#: Pages and endpoints a visitor without a session must reach to sign in.
PUBLIC_PAGES = ("/login", "/join", "/reset")
PUBLIC_PREFIXES = ("/site/auth/",)
PUBLIC_API = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/reset"),
    ("GET", "/api/auth/me"),
}

ADMIN_READS = ("/api/auth/users", "/api/auth/invites", "/api/auth/audit", "/api/auth/usage")

#: Requests that start model calls: refused once a member's daily quota is used
#: up (the dashboard checks; admins are exempt). Saving config, stopping a run
#: or deleting something never is.
QUOTA_GATED_EXACT = {
    "/api/run/start",
    "/api/run/schedule",
    "/api/interview",
    "/api/interview/run",
    "/api/research/analyze",
    "/api/research/digest",
    "/api/persona/distill",
    "/api/research/policy/run",
    "/api/research/games/design",
    "/api/research/games/sessions",
    "/api/arena/run",
    "/api/arena/generate",
    "/api/city/create",
    "/api/city/population",
    "/api/city/agent",
    "/api/city/knowledge",
    "/api/city/news",
}
QUOTA_GATED_PREFIX = ("/api/games/",)


def quota_gated(path: str) -> bool:
    path = path.rstrip("/") or "/"
    return path in QUOTA_GATED_EXACT or path.startswith(QUOTA_GATED_PREFIX)


MEMBER_WRITES_EXACT = {
    "/api/auth/logout",
    "/api/auth/password",
    "/api/interview",
    "/api/interview/plan",
    "/api/interview/run",
    "/api/research/analyze",
    "/api/research/digest",
    "/api/research/extract",
    "/api/persona/distill",
}
MEMBER_WRITES_PREFIX = ("/api/games/", "/api/arena/", "/api/research/games", "/api/research/policy")

#: Deletes whose handler only removes the caller's own record.
OWNER_DELETES = {"/api/interview/delete", "/api/research/delete", "/api/persona/delete"}

#: Writes that land in the active world. Each was checked to resolve its path
#: through the world-aware config; the Big Five table and life events still
#: read global files and so stay admin-only.
WORLD_WRITES_EXACT = {
    "/api/config",
    "/api/run/start",
    "/api/run/stop",
    "/api/run/schedule",
    "/api/run/schedule/cancel",
    "/api/agents",
}
WORLD_WRITES_PREFIX = ("/api/interventions/",)
WORLD_AGENT_WRITES = ("profile", "state", "goals", "memory", "finance", "relationships")

#: City-bundle writes. `/api/city/select` repoints the shared world: admin.
CITY_WRITES = {
    "/api/city/create",
    "/api/city/population",
    "/api/city/agent",
    "/api/city/migrate",
    "/api/city/knowledge",
    "/api/city/news",
    "/api/city/delete",
}


def required(method: str, path: str) -> Level:
    path = path.rstrip("/") or "/"
    if (method, path) in PUBLIC_API or path in PUBLIC_PAGES or path.startswith(PUBLIC_PREFIXES):
        return "public"
    if method in ("GET", "HEAD"):
        return "admin" if path.startswith(ADMIN_READS) else "member"
    if path in CITY_WRITES:
        return "city"
    if path in WORLD_WRITES_EXACT or path.startswith(WORLD_WRITES_PREFIX):
        return "world"
    parts = path.split("/")  # ["", "api", "agents", "<id>", "<what>"]
    if len(parts) == 5 and parts[2] == "agents" and parts[4] in WORLD_AGENT_WRITES:
        return "world"
    if path in ("/api/worlds/settings", "/api/worlds/broadcast"):
        return "admin"
    if path.startswith("/api/play/"):
        return "member"  # playing a resident; the world's openness is checked by the handler
    if path.startswith("/api/worlds/"):
        return "member"  # creating, selecting; owning the world is checked by the handler
    # Deleting is owner business: these handlers check the record's owner
    # (gaworld.accounts.ownership); every other delete stays admin-only.
    if "delete" in path.split("/"):
        owner_checked = path in OWNER_DELETES or (
            path.startswith(("/api/research/games/", "/api/research/policy/")) and path.endswith("/delete")
        )
        return "member" if owner_checked else "admin"
    if path in MEMBER_WRITES_EXACT or path.startswith(MEMBER_WRITES_PREFIX):
        return "member"
    return "admin"


def allows(user: dict[str, Any] | None, level: Level, world: dict[str, Any] | None = None) -> bool:
    """*world* is the request's active world (None = the shared default)."""
    if level == "public":
        return True
    if user is None:
        return False
    if user.get("role") == "admin":
        return True
    if level == "member":
        return True
    if level == "city":
        return bool(user.get("can_create_city"))
    if level == "world":
        return world is not None and world.get("owner_id") == user.get("id")
    return False
