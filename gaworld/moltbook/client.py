"""A thin client over Moltbook's ``/api/v1``.

Only the calls the plugin and the workbench make are wrapped: register,
status, post, comment, upvote, feed, verify. Each returns the parsed JSON
payload; anything Moltbook reports as a failure — an HTTP error status, or a
body carrying ``success: false`` / ``error`` — raises :class:`MoltbookError`
so callers have one path to log.

Response shapes are read leniently (``payload["agent"]["api_key"]`` or
``payload["api_key"]``, ``posts`` or ``items`` …): the service is young and
its envelopes have shifted before. A field that is genuinely missing surfaces
as an empty string, never as a crash inside a simulation tick.
"""

from __future__ import annotations

import json
import re

import requests

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.moltbook.client")

DEFAULT_BASE_URL = "https://www.moltbook.com/api/v1"
DEFAULT_TIMEOUT = 20.0
USER_AGENT = "GAWorld-Moltbook/1.0"


class MoltbookError(RuntimeError):
    """A request Moltbook refused, or one that never reached it."""

    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload if isinstance(payload, dict) else {}


class MoltbookClient:
    def __init__(self, base_url=DEFAULT_BASE_URL, api_key="", timeout=DEFAULT_TIMEOUT, session=None):
        self.base_url = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = str(api_key or "")
        self.timeout = float(timeout)
        # Injected in tests; created lazily otherwise so building a client
        # never opens a socket.
        self._session = session

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    # -- transport -------------------------------------------------------

    def _request(self, method, path, *, body=None, params=None):
        url = self.base_url + "/" + str(path).lstrip("/")
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.session.request(
                method, url, json=body, params=params, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise MoltbookError(f"moltbook unreachable: {exc}") from exc
        payload = _payload_of(response)
        status = int(getattr(response, "status_code", 0) or 0)
        error = _error_of(payload)
        if status >= 400 or error:
            raise MoltbookError(error or f"HTTP {status}", status=status, payload=payload)
        return payload

    # -- account ---------------------------------------------------------

    def register(self, name, description=""):
        """Create an agent. Returns the key and the claim link the owner must open."""
        payload = self._request("POST", "/agents/register", body={"name": name, "description": description})
        agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
        api_key = str(agent.get("api_key") or "")
        if not api_key:
            raise MoltbookError("registration returned no api_key", payload=payload)
        return {
            "name": str(agent.get("name") or name),
            "api_key": api_key,
            "claim_url": str(agent.get("claim_url") or ""),
            "verification_code": str(agent.get("verification_code") or ""),
            "raw": payload,
        }

    def status(self):
        payload = self._request("GET", "/agents/status")
        return {"status": status_of(payload), "raw": payload}

    def me(self):
        return self._request("GET", "/agents/me")

    # -- content ---------------------------------------------------------

    def create_post(self, submolt, title, content):
        return self._request("POST", "/posts", body={"submolt": submolt, "title": title, "content": content})

    def create_comment(self, post_id, content, parent_id=None):
        body = {"content": content}
        if parent_id:
            body["parent_id"] = parent_id
        return self._request("POST", f"/posts/{post_id}/comments", body=body)

    def upvote_post(self, post_id):
        return self._request("POST", f"/posts/{post_id}/upvote")

    def feed(self, sort="hot", limit=10):
        payload = self._request("GET", "/feed", params={"sort": sort, "limit": int(limit)})
        return posts_of(payload)

    def verify(self, verification_code, answer):
        """Answer the anti-spam challenge attached to a fresh post or comment."""
        return self._request("POST", "/verify", body={"verification_code": verification_code, "answer": str(answer)})


# ---------------------------------------------------------------------------
# Payload readers — tolerant of envelope drift
# ---------------------------------------------------------------------------


def _payload_of(response):
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data}
    return {"raw": str(getattr(response, "text", "") or "")[:500]}


def _error_of(payload):
    if payload.get("success") is False or payload.get("error"):
        error = payload.get("error") or payload.get("message") or "request failed"
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error, ensure_ascii=False)
        hint = payload.get("hint")
        return f"{error} ({hint})" if hint else str(error)
    return ""


def status_of(payload):
    """``claimed`` / ``pending_claim`` / … from whichever field carries it."""
    agent = payload.get("agent") if isinstance(payload.get("agent"), dict) else {}
    for candidate in (payload.get("status"), agent.get("status")):
        if isinstance(candidate, str) and candidate:
            return candidate
    if payload.get("is_claimed") is True or payload.get("claimed") is True:
        return "claimed"
    return "unknown"


def post_id_of(payload):
    post = payload.get("post") if isinstance(payload.get("post"), dict) else payload
    for key in ("id", "post_id"):
        if post.get(key):
            return str(post[key])
    return ""


def posts_of(payload):
    for key in ("posts", "items", "data", "feed"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def verification_challenge(payload):
    """The challenge Moltbook may attach to a new post, or ``None``."""
    if not payload.get("verification_required"):
        return None
    block = payload.get("verification") if isinstance(payload.get("verification"), dict) else payload
    text = block.get("challenge_text") or block.get("challenge") or block.get("message") or ""
    code = block.get("verification_code") or block.get("code") or ""
    if not text or not code:
        return None
    return {"challenge_text": str(text), "verification_code": str(code)}


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def numeric_answer(text):
    """The last number in a model reply, in the two-decimal form ``/verify`` expects."""
    matches = _NUMBER_RE.findall(str(text or ""))
    if not matches:
        return None
    return f"{float(matches[-1]):.2f}"
