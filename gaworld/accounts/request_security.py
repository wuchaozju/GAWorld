"""Same-origin mutations, rate limits and explicit expected-world consistency."""

from urllib.parse import urlparse

from gaworld.accounts import AccountError
from gaworld.accounts.community import rate_limit


def check_request(handler, path):
    if handler.command != "POST" or handler.accounts is None:
        return None
    if path.startswith(("/api/auth/", "/api/community/")):
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            return "请求长度无效", 400
        if length < 0 or length > 4 * 1024 * 1024:
            handler.close_connection = True
            return "请求内容超过 4 MB 限制", 413
    origin = handler.headers.get("Origin")
    if origin and (
        urlparse(origin).netloc != handler.headers.get("Host")
        or urlparse(origin).scheme not in {"http", "https"}
    ):
        return "请求来源不匹配", 403
    if handler.headers.get("Sec-Fetch-Site") == "cross-site":
        return "跨站请求被拒绝", 403
    try:
        if path.startswith("/api/auth/"):
            rate_limit(handler.accounts, handler.client_address[0] + ":" + path, 20)
        elif path.startswith("/api/community/"):
            rate_limit(handler.accounts, handler.client_address[0] + ":community", 120)
    except AccountError as exc:
        return str(exc), 429
    return None


def check_world(handler):
    if handler.command != "POST":
        return None
    from gaworld.accounts.context import WORLD

    expected = handler.headers.get("X-GAWorld-World")
    actual = str((WORLD.get() or {}).get("id") or "")
    if expected is not None and expected != actual:
        return "当前世界已改变，请刷新后重试", 409
    return None
