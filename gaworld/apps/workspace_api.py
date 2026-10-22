"""Personal metadata aggregated across owned worlds; details keep their world ACL."""

from gaworld import accounts
from gaworld.accounts.context import USER
from gaworld.apps import world_paths


def handle_get(path, query):
    if path != "/api/workspace/overview":
        return {"error": "Unknown endpoint"}, 404
    user = USER.get()
    store = accounts.enabled_store(world_paths.REPO_ROOT)
    if not store or not user or not user.get("id"):
        return {"error": "个人工作空间需要账号登录"}, 401
    from gaworld.accounts import usage
    from gaworld.community.store import CommunityStore
    from gaworld.research import study, workbench

    uid = user["id"]
    worlds = [w for w in store.list_worlds() if w["owner_id"] == uid]
    plans = [r for r in workbench.list_plans() if r.get("owner_id") == uid]
    studies = [r for r in study.list_studies() if r.get("owner_id") == uid]
    community = CommunityStore(store)
    return {
        "user": store.get_user(uid),
        "worlds": worlds,
        "plans": plans,
        "studies": studies,
        "publications": community.mine(user),
        "notifications": community.notifications(user),
        "usage": {
            "today": usage.TALLY.today(uid),
            "daily_limit": store.get_setting("daily_llm_calls_per_user", 0),
        },
        "current_world": str((world_paths.current_world() or {}).get("id") or ""),
    }, 200
