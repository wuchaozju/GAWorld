"""Moltbook integration: accounts store, client, action log, plugin, dashboard API.

No test opens a socket. The client takes an injected session that answers from
a route table and records every request, so the assertions are about what
would have gone over the wire — headers, paths, bodies — and about what the
resident's record shows afterwards.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from gaworld.apps import moltbook_api
from gaworld.kernel import build_kernel
from gaworld.moltbook import accounts
from gaworld.moltbook import log as action_log
from gaworld.moltbook.client import (
    MoltbookClient,
    MoltbookError,
    numeric_answer,
    post_id_of,
    posts_of,
    verification_challenge,
)
from gaworld.moltbook.plugin import MoltbookPlugin, _parse_post

REPO = Path(__file__).resolve().parents[1]
DASHBOARD = REPO / "site" / "dashboard"

KEY = "moltbook_secret_key_1234"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Answers from ``routes`` keyed by ``(method, path)``; records every call."""

    def __init__(self, routes=None):
        self.calls = []
        self.routes = dict(routes or {})

    def request(self, method, url, json=None, params=None, headers=None, timeout=None):
        call = {"method": method, "url": url, "json": json, "params": params, "headers": headers, "timeout": timeout}
        self.calls.append(call)
        path = url.split("/api/v1", 1)[1] if "/api/v1" in url else url
        handler = self.routes.get((method, path))
        if handler is None:
            return FakeResponse(404, {"success": False, "error": f"no route {method} {path}"})
        return handler(call) if callable(handler) else handler

    def sent(self, method, path):
        return [c for c in self.calls if c["method"] == method and c["url"].endswith(path)]


def registered(name="lin_su"):
    return FakeResponse(
        200,
        {
            "success": True,
            "agent": {
                "name": name,
                "api_key": KEY,
                "claim_url": "https://www.moltbook.com/claim/moltbook_claim_abc",
                "verification_code": "reef-7Q2K",
            },
        },
    )


def status(value):
    return FakeResponse(200, {"success": True, "status": value})


def posted(post_id="post_1", challenge=False):
    payload = {"success": True, "post": {"id": post_id, "title": "x"}}
    if challenge:
        payload["verification_required"] = True
        payload["verification"] = {
            "challenge_text": "A lobster molts 3 times a year for 14 years. How many molts?",
            "verification_code": "vc_123",
        }
    return FakeResponse(200, payload)


def feed():
    return FakeResponse(
        200,
        {
            "success": True,
            "posts": [
                {"id": "p9", "title": "Hello from the reef", "author": {"name": "clawd"}, "submolt": {"name": "general"}},
                {"id": "p8", "title": "On memory", "author": {"name": "ada"}, "submolt": {"name": "philosophy"}},
            ],
        },
    )


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "accounts.json")

    def test_switch_round_trip_keeps_the_account_when_turned_off(self):
        self.assertIsNone(accounts.get(1, path=self.path))
        record = accounts.set_enabled(1, True, path=self.path)
        self.assertTrue(record["enabled"])
        self.assertEqual(record["status"], accounts.STATUS_UNREGISTERED)
        # Enabled but keyless is not connected: there is nothing to post with.
        self.assertEqual(accounts.connected(self.path), {})

        accounts.save_registration(1, name="lin_su", api_key=KEY, claim_url="https://c", verification_code="reef-1", path=self.path)
        self.assertEqual(list(accounts.connected(self.path)), [1])
        self.assertEqual(accounts.get(1, path=self.path)["status"], accounts.STATUS_PENDING)

        accounts.set_enabled(1, False, path=self.path)
        self.assertEqual(accounts.connected(self.path), {})
        self.assertEqual(accounts.get(1, path=self.path)["api_key"], KEY)

        accounts.set_status(1, "claimed", path=self.path)
        self.assertEqual(accounts.get(1, path=self.path)["status"], "claimed")

    def test_public_view_never_carries_the_key(self):
        accounts.save_registration(3, name="wang", api_key=KEY, path=self.path)
        view = accounts.public_view(accounts.get(3, path=self.path))
        self.assertNotIn("api_key", view)
        self.assertTrue(view["has_key"])
        self.assertNotIn(KEY, json.dumps(view))
        self.assertTrue(view["api_key_hint"].startswith("molt"))
        self.assertIsNone(accounts.public_view(None))

    def test_corrupt_file_reads_as_empty(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(accounts.get(1, path=self.path))
        self.assertEqual(accounts.connected(self.path), {})


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------


class ClientTest(unittest.TestCase):
    def test_register_sends_no_bearer_and_reads_the_nested_agent(self):
        session = FakeSession({("POST", "/agents/register"): registered()})
        client = MoltbookClient(session=session)
        result = client.register("lin_su", "a resident")
        self.assertEqual(result["api_key"], KEY)
        self.assertEqual(result["verification_code"], "reef-7Q2K")
        self.assertIn("/claim/", result["claim_url"])
        call = session.calls[0]
        self.assertEqual(call["url"], "https://www.moltbook.com/api/v1/agents/register")
        self.assertEqual(call["json"], {"name": "lin_su", "description": "a resident"})
        self.assertNotIn("Authorization", call["headers"])
        self.assertEqual(call["headers"]["Content-Type"], "application/json")

    def test_register_flat_envelope_and_missing_key(self):
        session = FakeSession({("POST", "/agents/register"): FakeResponse(200, {"api_key": "k2", "claim_url": "u"})})
        self.assertEqual(MoltbookClient(session=session).register("a")["api_key"], "k2")
        session = FakeSession({("POST", "/agents/register"): FakeResponse(200, {"success": True})})
        with self.assertRaises(MoltbookError):
            MoltbookClient(session=session).register("a")

    def test_bearer_header_and_error_envelope(self):
        session = FakeSession({
            ("GET", "/agents/status"): FakeResponse(
                200, {"success": False, "error": "Agent not claimed", "hint": "open the claim url"}
            )
        })
        client = MoltbookClient(api_key=KEY, session=session, base_url="https://www.moltbook.com/api/v1/")
        with self.assertRaises(MoltbookError) as caught:
            client.status()
        self.assertIn("Agent not claimed", str(caught.exception))
        self.assertIn("open the claim url", str(caught.exception))
        self.assertEqual(session.calls[0]["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(session.calls[0]["url"], "https://www.moltbook.com/api/v1/agents/status")

    def test_http_error_status_and_unreachable(self):
        session = FakeSession({("POST", "/posts"): FakeResponse(429, {"error": "rate limited"})})
        with self.assertRaises(MoltbookError) as caught:
            MoltbookClient(api_key=KEY, session=session).create_post("general", "t", "c")
        self.assertEqual(caught.exception.status, 429)

        class Down:
            def request(self, *a, **k):
                raise requests.ConnectionError("refused")

        with self.assertRaises(MoltbookError) as caught:
            MoltbookClient(api_key=KEY, session=Down()).status()
        self.assertIn("unreachable", str(caught.exception))

    def test_non_json_body_is_not_a_crash(self):
        session = FakeSession({("GET", "/agents/status"): FakeResponse(502, None, text="<html>bad gateway")})
        with self.assertRaises(MoltbookError) as caught:
            MoltbookClient(api_key=KEY, session=session).status()
        self.assertEqual(caught.exception.status, 502)

    def test_status_post_feed_and_verify_shapes(self):
        session = FakeSession({
            ("GET", "/agents/status"): status("claimed"),
            ("POST", "/posts"): posted(challenge=True),
            ("GET", "/feed"): feed(),
            ("POST", "/verify"): FakeResponse(200, {"success": True}),
            ("POST", "/posts/post_1/comments"): FakeResponse(200, {"success": True, "comment": {"id": "c1"}}),
            ("POST", "/posts/post_1/upvote"): FakeResponse(200, {"success": True}),
        })
        client = MoltbookClient(api_key=KEY, session=session)
        self.assertEqual(client.status()["status"], "claimed")
        payload = client.create_post("general", "title", "body")
        self.assertEqual(post_id_of(payload), "post_1")
        self.assertEqual(verification_challenge(payload)["verification_code"], "vc_123")
        self.assertIsNone(verification_challenge({"success": True}))
        self.assertEqual([p["id"] for p in client.feed(limit=2)], ["p9", "p8"])
        self.assertEqual(session.sent("GET", "/feed")[0]["params"], {"sort": "hot", "limit": 2})
        client.verify("vc_123", "42.00")
        self.assertEqual(session.sent("POST", "/verify")[0]["json"], {"verification_code": "vc_123", "answer": "42.00"})
        client.create_comment("post_1", "nice", parent_id="c0")
        self.assertEqual(session.sent("POST", "/posts/post_1/comments")[0]["json"], {"content": "nice", "parent_id": "c0"})
        client.upvote_post("post_1")
        self.assertEqual(posts_of({"items": [{"id": 1}, "junk"]}), [{"id": 1}])

    def test_numeric_answer(self):
        self.assertEqual(numeric_answer("The answer is 42"), "42.00")
        self.assertEqual(numeric_answer("3 × 14 = 42.5 molts"), "42.50")
        self.assertIsNone(numeric_answer("no idea"))
        self.assertIsNone(numeric_answer(None))


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------


class LogTest(unittest.TestCase):
    def test_append_load_recent_and_torn_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in range(3):
                action_log.append(5, {"kind": "post", "summary": f"p{n}"}, root=tmp)
            with open(action_log.path_for(5, root=tmp), "a", encoding="utf-8") as fh:
                fh.write('{"kind": "post", "summ')
            rows = action_log.load(5, root=tmp)
            self.assertEqual([r["summary"] for r in rows], ["p0", "p1", "p2"])
            self.assertTrue(all(r["agent_id"] == 5 and r["ok"] and "ts" in r for r in rows))
            self.assertEqual([r["summary"] for r in action_log.recent(5, limit=2, root=tmp)], ["p2", "p1"])
            self.assertEqual(action_log.load(6, root=tmp), [])


# ---------------------------------------------------------------------------
# plugin
# ---------------------------------------------------------------------------


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.accounts_path = str(self.root / "accounts.json")
        self.log_dir = str(self.root / "moltbook")
        self.now = [1_000.0]
        self.session = FakeSession({
            ("GET", "/agents/status"): status("claimed"),
            ("POST", "/posts"): posted(),
            ("GET", "/feed"): feed(),
            ("POST", "/verify"): FakeResponse(200, {"success": True}),
        })
        self.factories = []

    def _factory(self, base_url, api_key, timeout):
        self.factories.append((base_url, api_key, timeout))
        return MoltbookClient(base_url=base_url, api_key=api_key, timeout=timeout, session=self.session)

    def _kernel(self, llm=None, enabled=True, compose_with_llm=None):
        cfg = {
            "city": "测试城",
            "records": {"output_dir": str(self.root / "records")},
            "moltbook": {
                "enabled": enabled,
                "accounts_path": self.accounts_path,
                "log_dir": self.log_dir,
                "min_post_interval_seconds": 1800,
                "read_feed": True,
                "feed_limit": 2,
                "compose_with_llm": bool(llm) if compose_with_llm is None else compose_with_llm,
                "timeout_seconds": 7,
            },
        }
        ctx = build_kernel(cfg, llm=llm, load_entry_points=False)
        agents = [
            {"id": 1, "name": "林素", "age": 34, "job": "社区医生", "residence": "测试城"},
            {"id": 2, "name": "老王"},
        ]
        ctx.set_agents(agents)
        plugin = MoltbookPlugin(client_factory=self._factory, now=lambda: self.now[0])
        ctx.registry.register(plugin)
        ctx.registry.setup_all(ctx)
        return ctx, agents, plugin

    def _connect(self, agent_id=1, enabled=True):
        accounts.save_registration(agent_id, name=f"molt_{agent_id}", api_key=KEY, path=self.accounts_path)
        accounts.set_enabled(agent_id, enabled, path=self.accounts_path)

    def _start(self, ctx, agents):
        ctx.bus.emit("on_simulation_start", agents=agents, agents_by_id=ctx.agents_by_id, config=ctx.config)

    def _step(self, ctx, agent, day, time_str, action, reflection="有点累"):
        ctx.bus.emit(
            "on_agent_post_step",
            agent=agent, day=day, time_str=time_str,
            step={"activity": "工作", "action": action, "reflection": reflection, "resolved_location": "社区医院"},
        )

    def _day_end(self, ctx, day, daily_logs=None):
        ctx.bus.emit("on_day_end", day=day, agents=ctx.agents, agents_by_id=ctx.agents_by_id, daily_logs=daily_logs or {})

    def _rows(self, agent_id=1):
        return action_log.load(agent_id, root=self.log_dir)

    def test_only_switched_on_residents_with_keys_get_a_client(self):
        self._connect(1)
        accounts.set_enabled(2, True, path=self.accounts_path)  # on, but never registered
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self.assertEqual(list(plugin._clients), [1])
        self.assertEqual(self.factories, [("https://www.moltbook.com/api/v1", KEY, 7.0)])
        rows = self._rows(1)
        self.assertEqual([r["kind"] for r in rows], ["status"])
        self.assertIn("已认领", rows[0]["summary"])
        self.assertEqual(accounts.get(1, path=self.accounts_path)["status"], "claimed")
        self.assertEqual(self._rows(2), [])
        self.assertEqual(ctx.agent_ext(agents[0], "moltbook")["status"], "claimed")

    def test_switched_off_resident_is_left_alone(self):
        self._connect(1, enabled=False)
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self._rows(1), [])

    def test_globally_disabled_registers_nothing(self):
        self._connect(1)
        ctx, agents, plugin = self._kernel(enabled=False)
        self._start(ctx, agents)
        self._day_end(ctx, 1)
        self.assertEqual(self.session.calls, [])

    def test_day_end_posts_the_digest_reads_the_feed_and_records_both(self):
        self._connect(1)
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "给三位老人量血压", reflection="上午很顺")
        self._step(ctx, agents[0], 1, "12:30", "在食堂吃了面")
        self._day_end(ctx, 1)

        post = self.session.sent("POST", "/posts")
        self.assertEqual(len(post), 1)
        body = post[0]["json"]
        self.assertEqual(body["submolt"], "general")
        self.assertEqual(body["title"], "第 1 天：林素 在 测试城 的一天")
        self.assertIn("09:00 工作：给三位老人量血压——上午很顺", body["content"])
        self.assertIn("12:30 工作：在食堂吃了面", body["content"])
        self.assertEqual(post[0]["headers"]["Authorization"], f"Bearer {KEY}")

        rows = self._rows(1)
        self.assertEqual([r["kind"] for r in rows], ["status", "post", "feed"])
        self.assertEqual(rows[1]["detail"]["post_id"], "post_1")
        self.assertEqual(rows[1]["day"], 1)
        self.assertIn("Hello from the reef", rows[2]["summary"])
        self.assertEqual([p["author"] for p in rows[2]["detail"]["posts"]], ["clawd", "ada"])
        # The same rows land on the recorder's shared timeline.
        recorded = (self.root / "records" / "moltbook.actions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["kind"] for line in recorded], ["status", "post", "feed"])
        self.assertTrue(all(json.loads(line)["agent_id"] == 1 for line in recorded))
        # The day's buffer was consumed.
        self.assertEqual(ctx.agent_ext(agents[0], "moltbook")["buffer"], [])

    def test_days_inside_the_spacing_fold_into_the_next_post(self):
        self._connect(1)
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        self.assertEqual(len(self.session.sent("POST", "/posts")), 1)

        self.now[0] += 10  # the next simulated day, ten wall-clock seconds later
        self._step(ctx, agents[0], 2, "10:00", "家访")
        self._day_end(ctx, 2)
        self.assertEqual(len(self.session.sent("POST", "/posts")), 1)
        self.assertEqual(len(ctx.agent_ext(agents[0], "moltbook")["buffer"]), 1)

        self.now[0] += 1800
        self._step(ctx, agents[0], 3, "11:00", "写病历")
        self._day_end(ctx, 3)
        posts = self.session.sent("POST", "/posts")
        self.assertEqual(len(posts), 2)
        self.assertIn("家访", posts[1]["json"]["content"])
        self.assertIn("写病历", posts[1]["json"]["content"])
        self.assertEqual(posts[1]["json"]["title"], "第 3 天：林素 在 测试城 的一天")

    def test_unclaimed_account_is_logged_once_and_never_posts(self):
        self._connect(1)
        self.session.routes[("GET", "/agents/status")] = status("pending_claim")
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        self.assertEqual(self.session.sent("POST", "/posts"), [])
        rows = self._rows(1)
        self.assertEqual([r["kind"] for r in rows], ["status"])
        self.assertIn("认领", rows[0]["summary"])
        self.assertEqual(accounts.get(1, path=self.accounts_path)["status"], "pending_claim")

    def test_status_failure_is_a_row_not_a_crash(self):
        self._connect(1)
        self.session.routes[("GET", "/agents/status")] = FakeResponse(401, {"error": "Invalid API key"})
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        rows = self._rows(1)
        self.assertEqual(rows[0]["kind"], "error")
        self.assertFalse(rows[0]["ok"])
        self.assertEqual(rows[0]["detail"]["http_status"], 401)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        self.assertEqual(self.session.sent("POST", "/posts"), [])

    def test_refused_post_is_logged_and_not_retried_next_day(self):
        self._connect(1)
        self.session.routes[("POST", "/posts")] = FakeResponse(429, {"success": False, "error": "Rate limit: 1 post per 30 minutes"})
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        self.now[0] += 10
        self._day_end(ctx, 2)
        self.assertEqual(len(self.session.sent("POST", "/posts")), 1)
        self.assertEqual(self.session.sent("GET", "/feed"), [])
        rows = self._rows(1)
        self.assertEqual(rows[-1]["kind"], "error")
        self.assertIn("Rate limit", rows[-1]["summary"])
        self.assertEqual(rows[-1]["detail"]["http_status"], 429)
        # The day is kept for the next allowed post.
        self.assertEqual(len(ctx.agent_ext(agents[0], "moltbook")["buffer"]), 1)

    def test_model_writes_the_post_and_answers_the_challenge(self):
        self._connect(1)
        self.session.routes[("POST", "/posts")] = posted(challenge=True)
        prompts = []

        def llm(prompt, task=None, agent_id=None, **_):
            prompts.append((task, agent_id, prompt))
            if task == "moltbook_verify":
                return "3 × 14 = 42"
            return '这是我的帖子：{"title": "今天量了很多血压", "content": "上午顺利。\\n下午有点累。"}'

        ctx, agents, plugin = self._kernel(llm=llm)
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "给三位老人量血压")
        self._day_end(ctx, 1)

        body = self.session.sent("POST", "/posts")[0]["json"]
        self.assertEqual(body["title"], "今天量了很多血压")
        self.assertEqual(body["content"], "上午顺利。\n下午有点累。")
        self.assertEqual([p[0] for p in prompts], ["moltbook_post", "moltbook_verify"])
        self.assertTrue(all(p[1] == 1 for p in prompts))
        self.assertIn("林素", prompts[0][2])
        self.assertIn("社区医生", prompts[0][2])
        self.assertIn("给三位老人量血压", prompts[0][2])
        self.assertIn("lobster molts", prompts[1][2])
        self.assertEqual(self.session.sent("POST", "/verify")[0]["json"], {"verification_code": "vc_123", "answer": "42.00"})
        kinds = [r["kind"] for r in self._rows(1)]
        self.assertEqual(kinds, ["status", "post", "verify", "feed"])

    def test_model_failure_falls_back_to_the_digest(self):
        self._connect(1)

        def llm(prompt, **_):
            raise RuntimeError("model down")

        ctx, agents, plugin = self._kernel(llm=llm)
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        body = self.session.sent("POST", "/posts")[0]["json"]
        self.assertEqual(body["title"], "第 1 天：林素 在 测试城 的一天")
        self.assertIn("看诊", body["content"])

    def test_challenge_without_a_model_is_recorded_as_unanswered(self):
        self._connect(1)
        self.session.routes[("POST", "/posts")] = posted(challenge=True)
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._step(ctx, agents[0], 1, "09:00", "看诊")
        self._day_end(ctx, 1)
        self.assertEqual(self.session.sent("POST", "/verify"), [])
        rows = self._rows(1)
        self.assertEqual([r["kind"] for r in rows], ["status", "post", "error", "feed"])
        self.assertIn("验证题", rows[2]["summary"])

    def test_fast_forward_day_posts_the_brief_from_daily_logs(self):
        self._connect(1)
        ctx, agents, plugin = self._kernel()
        self._start(ctx, agents)
        self._day_end(ctx, 30, daily_logs={1: "这一个月都在忙社区体检。", 2: "无关"})
        body = self.session.sent("POST", "/posts")[0]["json"]
        self.assertEqual(body["content"], "这一个月都在忙社区体检。")
        self.assertEqual(body["title"], "第 30 天：林素 在 测试城 的一天")
        # No steps, no brief: nothing to say, nothing sent.
        self.now[0] += 1800
        self._day_end(ctx, 31)
        self.assertEqual(len(self.session.sent("POST", "/posts")), 1)

    def test_parse_post_accepts_json_or_prose(self):
        self.assertEqual(_parse_post('{"title": "T", "content": "C"}'), ("T", "C"))
        self.assertEqual(_parse_post("标题行\n第一段\n第二段"), ("标题行", "第一段\n第二段"))
        self.assertIsNone(_parse_post("只有一行"))
        self.assertIsNone(_parse_post('{"title": "", "content": "C"}'))
        self.assertIsNone(_parse_post(""))

    def test_builtin_assembly_includes_the_plugin(self):
        from gaworld.plugins import builtin_plugins

        self.assertIn("moltbook", [p.id for p in builtin_plugins()])


# ---------------------------------------------------------------------------
# dashboard API
# ---------------------------------------------------------------------------


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.session = FakeSession({("POST", "/agents/register"): registered()})
        cfg = {
            "accounts_path": str(root / "accounts.json"),
            "log_dir": str(root / "moltbook"),
            "base_url": "https://www.moltbook.com/api/v1",
            "timeout_seconds": 5,
        }
        identities = {1: {"id": 1, "name": "林素", "age": 34, "residence": "测试城"}}
        patches = [
            mock.patch.object(moltbook_api, "_cfg", lambda: dict(cfg)),
            mock.patch.object(moltbook_api, "_agent_identity", lambda agent_id: identities.get(agent_id)),
            mock.patch.object(
                moltbook_api, "_client",
                lambda api_key="": MoltbookClient(api_key=api_key, session=self.session),
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_blank_view_and_validation(self):
        payload, code = moltbook_api.handle_get("/api/moltbook/agent", {"id": "1"})
        self.assertEqual(code, 200)
        self.assertFalse(payload["enabled"])
        self.assertFalse(payload["has_key"])
        self.assertEqual(payload["status"], "unregistered")
        self.assertEqual(payload["actions"], [])
        self.assertEqual(payload["default_name"], "gaworld_1")
        self.assertTrue(payload["log_path"].endswith("agent_1/actions.jsonl"))
        # The city page style of query dict (lists) works too.
        self.assertEqual(moltbook_api.handle_get("/api/moltbook/agent", {"id": ["1"]})[1], 200)
        self.assertEqual(moltbook_api.handle_get("/api/moltbook/agent", {})[1], 400)
        self.assertEqual(moltbook_api.handle_get("/api/moltbook/agent", {"id": "x"})[1], 400)
        self.assertEqual(moltbook_api.handle_get("/api/moltbook/nope", {})[1], 404)
        self.assertEqual(moltbook_api.handle_post("/api/moltbook/nope", {})[1], 404)
        self.assertEqual(moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": "abc"})[1], 400)

    def test_toggle_on_registers_once_and_off_keeps_the_account(self):
        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": True, "name": "lin_su"})
        self.assertEqual(code, 200, payload)
        self.assertTrue(payload["enabled"])
        self.assertTrue(payload["has_key"])
        self.assertEqual(payload["status"], "pending_claim")
        self.assertEqual(payload["name"], "lin_su")
        self.assertIn("/claim/", payload["claim_url"])
        self.assertEqual(payload["verification_code"], "reef-7Q2K")
        self.assertEqual(payload["profile_url"], "https://www.moltbook.com/u/lin_su")
        self.assertNotIn("api_key", payload)
        self.assertNotIn(KEY, json.dumps(payload))
        self.assertEqual(payload["actions"][0]["kind"], "register")
        self.assertEqual(payload["action_count"], 1)
        sent = self.session.sent("POST", "/agents/register")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["json"]["name"], "lin_su")
        self.assertIn("林素", sent[0]["json"]["description"])
        self.assertIn("GAWorld", sent[0]["json"]["description"])

        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": False})
        self.assertEqual(code, 200)
        self.assertFalse(payload["enabled"])
        self.assertTrue(payload["has_key"])

        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": True})
        self.assertEqual(code, 200)
        self.assertTrue(payload["enabled"])
        self.assertEqual(len(self.session.sent("POST", "/agents/register")), 1)

    def test_toggle_on_uses_the_default_name_and_rejects_bad_ones(self):
        self.session.routes[("POST", "/agents/register")] = lambda call: registered(call["json"]["name"])
        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": True})
        self.assertEqual(code, 200)
        self.assertEqual(payload["name"], "gaworld_1")
        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 2, "enabled": True, "name": "has space"})
        self.assertEqual(code, 404)  # unknown resident comes first
        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": True, "name": "has space"})
        self.assertEqual(code, 200)  # already registered: the name is ignored

    def test_registration_failure_is_reported_and_recorded(self):
        self.session.routes[("POST", "/agents/register")] = FakeResponse(409, {"success": False, "error": "Name already taken"})
        payload, code = moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": True, "name": "taken"})
        self.assertEqual(code, 502)
        self.assertIn("Name already taken", payload["error"])
        view, _ = moltbook_api.handle_get("/api/moltbook/agent", {"id": "1"})
        self.assertFalse(view["enabled"])
        self.assertFalse(view["has_key"])
        self.assertEqual(view["actions"][0]["kind"], "error")
        self.assertFalse(view["actions"][0]["ok"])

    def test_refresh_needs_an_account_and_updates_the_status(self):
        payload, code = moltbook_api.handle_post("/api/moltbook/refresh", {"agent_id": 1})
        self.assertEqual(code, 409)
        moltbook_api.handle_post("/api/moltbook/toggle", {"agent_id": 1, "enabled": True})
        self.session.routes[("GET", "/agents/status")] = status("claimed")
        payload, code = moltbook_api.handle_post("/api/moltbook/refresh", {"agent_id": 1})
        self.assertEqual(code, 200)
        self.assertEqual(payload["status"], "claimed")
        self.assertEqual(payload["actions"][0]["kind"], "status")
        self.assertEqual(self.session.sent("GET", "/agents/status")[0]["headers"]["Authorization"], f"Bearer {KEY}")
        self.session.routes[("GET", "/agents/status")] = FakeResponse(500, {"error": "boom"})
        payload, code = moltbook_api.handle_post("/api/moltbook/refresh", {"agent_id": 1})
        self.assertEqual(code, 502)

    def test_dashboard_server_forwards_both_verbs(self):
        source = (REPO / "gaworld" / "apps" / "dashboard_server.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('path.startswith("/api/moltbook")'), 2)
        self.assertIn("moltbook_api.handle_get(path, query)", source)
        self.assertIn("moltbook_api.handle_post(path, payload)", source)


# ---------------------------------------------------------------------------
# workbench + config surface
# ---------------------------------------------------------------------------


class SurfaceTest(unittest.TestCase):
    def test_studio_renders_the_card_and_both_locales_carry_its_keys(self):
        studio = (DASHBOARD / "studio.js").read_text(encoding="utf-8")
        for needle in ("${moltbookCard()}", "/api/moltbook/agent?id=", "/api/moltbook/toggle", "/api/moltbook/refresh",
                       'id="mbToggle"', "bindMoltbookStep();", "store.moltbook = null;"):
            self.assertIn(needle, studio)
        used = set(re.findall(r'__f?\("(sd\.mb_[a-z_]+)"', studio))
        used |= {f"sd.mb_kind.{kind}" for kind in action_log.KINDS}
        self.assertGreater(len(used), 20)
        for name in ("zh-CN.json", "en.json"):
            with self.subTest(locale=name):
                locale = json.loads((DASHBOARD / "locales" / name).read_text(encoding="utf-8"))
                missing = sorted(key for key in used if key not in locale)
                self.assertEqual(missing, [])

    def test_config_defaults_and_docs(self):
        from gaworld.settings import config_docs
        from gaworld.settings.integrations import integration_settings

        block = integration_settings()["moltbook"]
        self.assertTrue(block["enabled"])
        self.assertEqual(block["accounts_path"], accounts.DEFAULT_PATH)
        self.assertEqual(block["log_dir"], action_log.DEFAULT_DIR)
        self.assertEqual(config_docs.section_index()["moltbook"], "integrations")
        self.assertTrue(config_docs.help_for("moltbook"))
        self.assertTrue(config_docs.help_en_for("moltbook.min_post_interval_seconds"))
        self.assertEqual(config_docs.label_for("moltbook.log_dir"), "行动记录目录")
        self.assertEqual(config_docs.label_en_for("moltbook.submolt"), "Default submolt")


if __name__ == "__main__":
    unittest.main()
