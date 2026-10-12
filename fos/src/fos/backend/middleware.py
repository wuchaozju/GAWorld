"""
ASGI middleware for extracting the user's language preference from requests.

Reads the X-Language HTTP header and sets a per-request contextvar so that
T() automatically returns translations in the correct language without
requiring every call site to pass locale= explicitly.

Contains: LocaleMiddleware
"""

from litestar.middleware.base import AbstractMiddleware
from litestar.types import Receive, Scope, Send

from fos.i18n import set_request_locale


class LocaleMiddleware(AbstractMiddleware):
    """Sets the request-scoped locale from the X-Language header."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            raw = headers.get(b"x-language", b"en")
            locale = raw.decode("utf-8", errors="ignore").strip().lower()[:2]
            set_request_locale(locale)
        await self.app(scope, receive, send)
