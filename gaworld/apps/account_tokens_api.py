"""Session-only personal token management; Bearer tokens cannot mint credentials."""

from gaworld.accounts import AccountError, api_tokens


def handle(store, user, method, path, payload=None):
    if path not in {"/api/auth/tokens", "/api/auth/tokens/revoke"}:
        return None
    if not user or not user.get("id") or user.get("api_token_id"):
        return {"error": "Sign in with a personal account"}, 403, None
    if method == "GET" and path == "/api/auth/tokens":
        return (
            {"tokens": api_tokens.list_tokens(store, user["id"]), "scopes": sorted(api_tokens.SCOPES)},
            200,
            None,
        )
    if method != "POST":
        return {"error": "Unknown endpoint"}, 404, None
    payload = payload or {}
    try:
        if path.endswith("/revoke"):
            return {"revoked": api_tokens.revoke(store, user, payload.get("id"))}, 200, None
        if not user.get("email_verified", True):
            return {"error": "Verify your email first"}, 403, None
        if not store.authenticate(user["nickname"], str(payload.get("password") or "")):
            return {"error": "Current password is incorrect"}, 403, None
        return api_tokens.create(store, user, payload), 201, None
    except AccountError as exc:
        return {"error": str(exc)}, 400, None
