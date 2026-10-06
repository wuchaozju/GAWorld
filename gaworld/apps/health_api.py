"""Non-sensitive readiness probe for authenticated and single-user deployments."""

from gaworld import accounts
from gaworld.apps import world_paths


def handle_get(path, query):
    if path != "/api/health":
        return {"error": "Unknown endpoint"}, 404
    try:
        store = accounts.enabled_store(world_paths.REPO_ROOT)
    except accounts.AccountConfigurationError:
        return {"ok": False, "service": "gaworld-dashboard"}, 503
    return {
        "ok": True,
        "service": "gaworld-dashboard",
        "accounts": store is not None,
        "accounts_required": accounts.required(),
    }, 200
