"""X MCP integration: App-only Bearer client + the "x" search engine.

Covers three layers:

1. ``XMCPClient`` — MCP handshake (initialize → initialized →
   tools/list), tool/argument discovery from the advertised schema,
   and normalization of tool results into web_search-shaped items.
2. Quota guardrails — missing token, 429 cooldown, throttle.
3. ``gaworld.sim._news`` wiring — the "x" engine returns results,
   falls through the engine chain when empty, and x.com URLs skip the
   (login-walled) page fetch, using the post text snippet directly.
"""

import json as jsonlib
import unittest
from unittest import mock

import requests

from gaworld.io import x_mcp
from gaworld.io.x_mcp import XMCPClient, x_mcp_search
from gaworld.sim import _news


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self.text = text or (jsonlib.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


def _install_fake_server(client, *, tool_name="search_posts", posts=None, call_log=None):
    """Replace the client's HTTP session with a canned MCP server."""
    posts = posts if posts is not None else [
        {"id": "111", "text": "AI 教育 最新进展：新的课程发布"},
        {"id": "222", "text": "第二条相关帖子"},
    ]

    def _post(url, json=None, headers=None, timeout=None):
        if call_log is not None:
            call_log.append({"method": json.get("method"), "headers": dict(headers or {})})
        method = json.get("method")
        rpc_id = json.get("id")
        if method == "initialize":
            return _FakeResponse(
                payload={
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "serverInfo": {"name": "xmcp"},
                    },
                },
                headers={"Content-Type": "application/json", "Mcp-Session-Id": "sess-1"},
            )
        if method == "notifications/initialized":
            return _FakeResponse(status_code=202, headers={})
        if method == "tools/list":
            return _FakeResponse(
                payload={
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "tools": [
                            {"name": "lookup_user", "inputSchema": {"properties": {"id": {}}}},
                            {
                                "name": tool_name,
                                "inputSchema": {
                                    "properties": {
                                        "query": {"type": "string"},
                                        "max_results": {"type": "number"},
                                    }
                                },
                            },
                        ]
                    },
                }
            )
        if method == "tools/call":
            body = jsonlib.dumps({"data": posts})
            return _FakeResponse(
                payload={
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {"content": [{"type": "text", "text": body}]},
                }
            )
        raise AssertionError(f"unexpected method {method}")

    client._session = mock.Mock()
    client._session.post = mock.Mock(side_effect=_post)
    return client._session.post


class TestXMCPClient(unittest.TestCase):
    def _client(self, **kwargs):
        kwargs.setdefault("min_interval_seconds", 0.0)
        return XMCPClient("https://api.x.com/mcp", "tok-abc", **kwargs)

    def test_handshake_and_search_normalization(self):
        client = self._client()
        call_log = []
        _install_fake_server(client, call_log=call_log)

        items = client.search_posts("AI 教育", max_results=5)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://x.com/i/status/111")
        self.assertEqual(items[0]["snippet"], "AI 教育 最新进展：新的课程发布")
        self.assertTrue(items[0]["title"])
        methods = [c["method"] for c in call_log]
        self.assertEqual(
            methods,
            ["initialize", "notifications/initialized", "tools/list", "tools/call"],
        )
        # Bearer on every request; session id echoed back after initialize.
        for entry in call_log:
            self.assertEqual(entry["headers"]["Authorization"], "Bearer tok-abc")
        self.assertEqual(call_log[-1]["headers"]["Mcp-Session-Id"], "sess-1")

    def test_arguments_follow_advertised_schema(self):
        client = self._client()
        post_mock = _install_fake_server(client)
        client.search_posts("关键词", max_results=3)
        tool_call = [
            kwargs["json"]
            for _, kwargs in post_mock.call_args_list
            if kwargs["json"].get("method") == "tools/call"
        ][0]
        self.assertEqual(
            tool_call["params"]["arguments"], {"query": "关键词", "max_results": 3}
        )

    def test_repeat_query_served_from_cache(self):
        client = self._client()
        post_mock = _install_fake_server(client)
        first = client.search_posts("AI 教育")
        calls_after_first = post_mock.call_count
        second = client.search_posts("AI 教育")
        self.assertEqual(first, second)
        self.assertEqual(post_mock.call_count, calls_after_first)

    def test_429_sets_cooldown_and_stops_calling(self):
        client = self._client()
        client._session = mock.Mock()
        client._session.post = mock.Mock(return_value=_FakeResponse(status_code=429, headers={}))
        self.assertEqual(client.search_posts("q1"), [])
        calls = client._session.post.call_count
        self.assertEqual(client.search_posts("q2"), [])
        self.assertEqual(client._session.post.call_count, calls)

    def test_credits_depleted_in_result_body_sets_cooldown(self):
        # Live-observed shape: JSON-RPC 200 but isError result carrying an
        # X API problem body with status 402 ("credits depleted").
        client = self._client()
        post_mock = _install_fake_server(client)
        original_post = post_mock.side_effect

        def _post(url, json=None, headers=None, timeout=None):
            if json.get("method") == "tools/call":
                body = jsonlib.dumps(
                    {"detail": "credits depleted", "status": 402, "title": "Payment Required"}
                )
                return _FakeResponse(
                    payload={
                        "jsonrpc": "2.0",
                        "id": json["id"],
                        "result": {
                            "content": [{"type": "text", "text": body}],
                            "isError": True,
                        },
                    }
                )
            return original_post(url, json=json, headers=headers, timeout=timeout)

        client._session.post = mock.Mock(side_effect=_post)
        self.assertEqual(client.search_posts("q1"), [])
        calls = client._session.post.call_count
        # New query during cooldown: no further HTTP.
        self.assertEqual(client.search_posts("q2"), [])
        self.assertEqual(client._session.post.call_count, calls)

    def test_auth_failure_sets_long_cooldown_not_disable(self):
        client = self._client()
        client._session = mock.Mock()
        client._session.post = mock.Mock(return_value=_FakeResponse(status_code=401, headers={}))
        self.assertEqual(client.search_posts("q"), [])
        # Cooldown, not permanent disable: intermittent gateway 401s recover.
        self.assertFalse(client._disabled)
        calls = client._session.post.call_count
        self.assertEqual(client.search_posts("q2"), [])
        self.assertEqual(client._session.post.call_count, calls)

    def test_sse_response_parsed(self):
        client = self._client()
        _install_fake_server(client)

        original_post = client._session.post.side_effect

        def _post(url, json=None, headers=None, timeout=None):
            if json.get("method") == "tools/call":
                body = jsonlib.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": json["id"],
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": jsonlib.dumps(
                                        {"data": [{"id": "333", "text": "sse post"}]}
                                    ),
                                }
                            ]
                        },
                    }
                )
                return _FakeResponse(
                    headers={"Content-Type": "text/event-stream"},
                    text=f"event: message\ndata: {body}\n\n",
                )
            return original_post(url, json=json, headers=headers, timeout=timeout)

        client._session.post = mock.Mock(side_effect=_post)
        items = client.search_posts("sse")
        self.assertEqual(items[0]["url"], "https://x.com/i/status/333")


class TestXMCPSearchEntry(unittest.TestCase):
    def test_missing_token_returns_empty_without_http(self):
        with mock.patch.object(x_mcp, "_clients", {}):
            result = x_mcp_search(
                "query",
                config={"x_mcp": {"bearer_token_env": "GAWORLD_TEST_UNSET_TOKEN"}},
            )
        self.assertEqual(result, [])

    def test_disabled_block_returns_empty(self):
        self.assertEqual(
            x_mcp_search("query", config={"x_mcp": {"enabled": False}}), []
        )

    def test_site_operator_stripped(self):
        self.assertEqual(
            x_mcp._strip_web_operators("AI 教育 site:zhihu.com"), "AI 教育"
        )


class TestNewsWiring(unittest.TestCase):
    def test_web_search_x_engine_returns_results(self):
        fake = [{"url": "https://x.com/i/status/1", "title": "t", "snippet": "post"}]
        with mock.patch.object(_news, "x_mcp_search", return_value=fake) as m:
            engine, results = _news.web_search("query", config={"engines": ["x"]})
        self.assertEqual(engine, "x")
        self.assertEqual(results, fake)
        m.assert_called_once()

    def test_web_search_falls_through_when_x_empty(self):
        with mock.patch.object(_news, "x_mcp_search", return_value=[]), \
             mock.patch.object(
                 _news.requests,
                 "get",
                 side_effect=requests.RequestException("offline"),
             ) as web_get:
            engine, results = _news.web_search(
                "query", config={"engines": ["x", "baidu"]}
            )
        self.assertEqual((engine, results), ("", []))
        web_get.assert_called_once()  # baidu was attempted after x

    def test_x_result_skips_page_fetch_and_uses_snippet(self):
        fake = [
            {
                "url": "https://x.com/i/status/42",
                "title": "帖子标题",
                "snippet": "帖子全文内容",
            }
        ]

        def _no_fetch(*args, **kwargs):
            raise AssertionError("fetch_news_excerpt must not be called for x.com")

        with mock.patch.object(_news, "web_search", return_value=("x", fake)), \
             mock.patch.object(_news, "fetch_news_excerpt", side_effect=_no_fetch):
            target = _news._web_search_target(
                agent={"id": 1, "name": "测试"},
                query="q",
                interests=[],
                preferred_sites=[],
                seen_urls=set(),
                config={},
            )
        self.assertIsNotNone(target)
        self.assertEqual(target["content"], "帖子全文内容")
        self.assertEqual(target["engine"], "x")


if __name__ == "__main__":
    unittest.main()
