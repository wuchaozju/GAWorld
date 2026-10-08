"""Accounts (proposal 2026-10-01-multi-user, P1).

* The store: invite-only registration with a mandatory password, one-time
  codes, case-insensitive nicknames, reset codes that sign everyone out.
* The policy: members read everything but write only what touches nothing
  shared; city edits need `can_create_city` and being the city's creator.
* Over HTTP: no database = the single-user console, unchanged; with one, a
  visitor is sent to /login and the token holder is still an admin.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.accounts import AccountError, AccountStore, policy
from gaworld.accounts import __main__ as cli
from gaworld.apps import dashboard_server as ds

PASSWORD = "correct horse"


def _store(tmp: str) -> AccountStore:
    store = AccountStore(os.path.join(tmp, "accounts.sqlite"))
    store.init_schema()
    return store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = _store(self.tmp.name)
        self.admin = self.store.create_user("老师", PASSWORD, role="admin")

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_needs_a_live_one_time_code_and_a_password(self):
        code, other = self.store.create_invites(2, label="周三班", can_create_city=True)
        with self.assertRaises(AccountError):
            self.store.register(code, "小王", "short")
        with self.assertRaises(AccountError):
            self.store.register("not-a-code", "小王", PASSWORD)
        user = self.store.register(code, "小王", PASSWORD)
        self.assertEqual((user["role"], user["label"], user["can_create_city"]), ("member", "周三班", True))
        with self.assertRaises(AccountError):
            self.store.register(code, "小李", PASSWORD)  # used
        with self.assertRaises(AccountError):
            self.store.register(other, "小王", PASSWORD)  # nickname taken
        with self.assertRaises(AccountError):
            self.store.register(other, "老师", PASSWORD)
        expired = self.store.create_invites(1, expires_days=-1)[0]
        with self.assertRaises(AccountError):
            self.store.register(expired, "小赵", PASSWORD)

    def test_nicknames_are_case_insensitive_and_checked(self):
        self.store.create_user("Alice", PASSWORD)
        with self.assertRaises(AccountError):
            self.store.create_user("alice", PASSWORD)
        self.assertEqual(self.store.authenticate("ALICE", PASSWORD)["nickname"], "Alice")
        for bad in ("", "   ", "a\tb", "x" * 33):
            with self.assertRaises(AccountError):
                self.store.create_user(bad, PASSWORD)

    def test_authenticate_and_sessions(self):
        self.assertIsNone(self.store.authenticate("老师", "wrong password"))
        self.assertIsNone(self.store.authenticate("nobody", PASSWORD))
        token = self.store.open_session(self.admin["id"])
        self.assertEqual(self.store.session_user(token)["id"], self.admin["id"])
        self.assertIsNone(self.store.session_user("forged"))
        self.store.close_session(token)
        self.assertIsNone(self.store.session_user(token))
        old = self.store.open_session(self.admin["id"])
        with mock.patch("gaworld.accounts.store.time.time", return_value=time.time() + 8 * 86400):
            self.assertIsNone(self.store.session_user(old))

    def test_password_is_stored_salted(self):
        self.store.create_user("学生", PASSWORD)
        with self.store._db() as db:
            hashes = [row[0] for row in db.execute("SELECT password_hash FROM users ORDER BY id")]
        self.assertNotIn(PASSWORD, "".join(hashes))
        self.assertNotEqual(hashes[0], hashes[1])

    def test_reset_code_is_single_use_and_signs_out(self):
        token = self.store.open_session(self.admin["id"])
        code = self.store.issue_reset(self.admin["id"])
        with self.assertRaises(AccountError):
            self.store.reset_password(code, "short")
        self.store.reset_password(code, "a new password")
        self.assertIsNone(self.store.session_user(token))
        self.assertIsNotNone(self.store.authenticate("老师", "a new password"))
        with self.assertRaises(AccountError):
            self.store.reset_password(code, "another password")

    def test_change_password_checks_the_old_one(self):
        with self.assertRaises(AccountError):
            self.store.change_password(self.admin["id"], "wrong password", "a new password")
        self.store.change_password(self.admin["id"], PASSWORD, "a new password")
        self.assertIsNotNone(self.store.authenticate("老师", "a new password"))

    def test_city_owner_and_audit(self):
        self.store.set_city_owner("wuzhen", self.admin["id"])
        self.assertEqual(self.store.city_owner("wuzhen"), self.admin["id"])
        self.store.forget_city("wuzhen")
        self.assertIsNone(self.store.city_owner("wuzhen"))
        self.store.audit(self.admin, "POST", "/api/config")
        self.assertEqual(self.store.list_audit()[0]["detail"], "/api/config")


MEMBER = {"id": 2, "role": "member", "can_create_city": False}
BUILDER = {"id": 3, "role": "member", "can_create_city": True}
ADMIN = {"id": 1, "role": "admin", "can_create_city": False}


class PolicyTest(unittest.TestCase):
    def test_levels(self):
        cases = {
            ("GET", "/login"): "public",
            ("GET", "/site/auth/index.html"): "public",
            ("POST", "/api/auth/login"): "public",
            ("GET", "/api/auth/me"): "public",
            ("GET", "/console"): "member",
            ("GET", "/api/config"): "member",
            ("GET", "/api/auth/users"): "admin",
            ("POST", "/api/auth/logout"): "member",
            ("POST", "/api/auth/invites"): "admin",
            ("POST", "/api/interview/run"): "member",
            ("POST", "/api/games/duel/start"): "member",
            ("POST", "/api/research/games/abc/act"): "member",
            ("POST", "/api/research/games/abc/delete"): "member",  # the handler checks the owner
            ("POST", "/api/interview/delete"): "member",
            ("POST", "/api/research/studies/abc/delete"): "admin",
            ("POST", "/api/todos/delete"): "admin",
            ("POST", "/api/persona/distill"): "member",
            ("POST", "/api/persona/deploy"): "admin",
            ("POST", "/api/config"): "world",
            ("POST", "/api/settings/save"): "admin",
            ("POST", "/api/run/start"): "world",
            ("POST", "/api/city/select"): "admin",
            ("POST", "/api/city/create"): "city",
            ("POST", "/api/city/delete"): "city",
            ("POST", "/api/agents/3/memory"): "world",
            ("POST", "/api/agents/3/big5"): "world",  # the world's own copy under seed/
        }
        for (method, path), level in cases.items():
            self.assertEqual(policy.required(method, path), level, (method, path))

    def test_allows(self):
        self.assertFalse(policy.allows(None, "member"))
        self.assertTrue(policy.allows(None, "public"))
        self.assertTrue(policy.allows(MEMBER, "member"))
        self.assertFalse(policy.allows(MEMBER, "city"))
        self.assertTrue(policy.allows(BUILDER, "city"))
        self.assertFalse(policy.allows(BUILDER, "admin"))
        self.assertTrue(policy.allows(ADMIN, "admin"))
        self.assertTrue(policy.allows(ADMIN, "city"))


class CityCreatorTest(unittest.TestCase):
    """A builder may edit only the cities they created (checked by the dashboard)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = _store(self.tmp.name)
        self.builder = self.store.create_user("建城者", PASSWORD, can_create_city=True)
        self.bundle = SimpleNamespace(slug="柳溪村")

    def tearDown(self):
        self.tmp.cleanup()

    def _refusal(self, user, path, payload):
        handler = SimpleNamespace(accounts=self.store, user=user)
        with mock.patch("gaworld.city.bundle.resolve_city", return_value=self.bundle):
            return ds.DashboardHandler._city_write_refusal(handler, path, payload)

    def test_creator_only(self):
        self.assertEqual(
            self._refusal(self.builder, "/api/city/population", {"city": "柳溪村"}), "只能修改自己建立的城市"
        )
        self.store.set_city_owner("柳溪村", self.builder["id"])
        self.assertIsNone(self._refusal(self.builder, "/api/city/population", {"city": "柳溪村"}))
        self.assertIsNone(self._refusal(ds.TOKEN_ADMIN, "/api/city/delete", {"city": "x"}))

    def test_create_may_not_overwrite(self):
        self.assertIsNone(self._refusal(self.builder, "/api/city/create", {"name": "新城"}))
        self.assertEqual(
            self._refusal(self.builder, "/api/city/create", {"name": "新城", "force": True}),
            "覆盖已有城市需要管理员",
        )


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "accounts.sqlite")
        self.env = mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": self.db})
        self.env.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def _req(self, method, path, body=None, cookie=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        all_headers = dict(headers or {})
        if cookie:
            all_headers["Cookie"] = cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            all_headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=all_headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        return resp, payload

    def _login(self, nickname, password=PASSWORD):
        resp, _ = self._req("POST", "/api/auth/login", {"nickname": nickname, "password": password})
        self.assertEqual(resp.status, 200)
        cookie = resp.getheader("Set-Cookie")
        for attr in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attr, cookie)
        return cookie.split(";", 1)[0]

    def test_without_database_nothing_changes(self):
        resp, me = self._req("GET", "/api/auth/me")
        self.assertEqual((resp.status, me), (200, {"mode": "single"}))
        self.assertEqual(self._req("GET", "/api/interventions")[0].status, 200)

    def test_sign_in_is_public_but_assets_stay_gated(self):
        store = _store(self.tmp.name)
        store.create_user("老师", PASSWORD, role="admin")
        for method in ("GET", "HEAD"):
            resp, _ = self._req(method, "/login")
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.getheader("Content-Type"))
        self.assertEqual(self._req("GET", "/site/assets/city-lab-atlas.svg")[0].status, 303)

    def test_classroom_flow(self):
        store = _store(self.tmp.name)
        store.create_user("老师", PASSWORD, role="admin")

        resp, _ = self._req("GET", "/console")
        self.assertEqual(resp.status, 303)
        self.assertEqual(resp.getheader("Location"), "/login?next=%2Fconsole")
        self.assertEqual(self._req("GET", "/login")[0].status, 200)
        self.assertEqual(self._req("GET", "/join?code=x")[0].status, 200)
        self.assertEqual(self._req("GET", "/api/interventions")[0].status, 401)
        self.assertEqual(self._req("GET", "/api/auth/me")[1], {"mode": "accounts", "user": None})
        self.assertEqual(
            self._req("POST", "/api/auth/login", {"nickname": "老师", "password": "nope nope"})[0].status, 401
        )

        teacher = self._login("老师")
        resp, body = self._req("POST", "/api/auth/invites", {"count": 2, "label": "周三班"}, cookie=teacher)
        self.assertEqual(resp.status, 200)
        code = body["codes"][0]

        resp, body = self._req(
            "POST", "/api/auth/register", {"code": code, "nickname": "小王", "password": "short"}
        )
        self.assertEqual(resp.status, 400)
        resp, body = self._req(
            "POST", "/api/auth/register", {"code": code, "nickname": "小王", "password": PASSWORD}
        )
        self.assertEqual(resp.status, 200)
        student = resp.getheader("Set-Cookie").split(";", 1)[0]

        self.assertEqual(self._req("GET", "/api/auth/me", cookie=student)[1]["user"]["nickname"], "小王")
        self.assertEqual(self._req("GET", "/console", cookie=student)[0].status, 200)
        self.assertEqual(self._req("GET", "/api/interventions", cookie=student)[0].status, 200)
        for path in (
            "/api/config",
            "/api/settings/save",
            "/api/run/start",
            "/api/city/select",
            "/api/research/studies",
            "/api/auth/invites",
        ):
            resp, body = self._req("POST", path, {}, cookie=student)
            self.assertEqual(resp.status, 403, path)
            self.assertIn("没有权限", body["error"])
        resp, body = self._req("POST", "/api/city/create", {"name": "x"}, cookie=student)
        self.assertEqual((resp.status, body["error"]), (403, "没有权限：需要「建立城市」权限"))
        self.assertEqual(self._req("GET", "/api/auth/users", cookie=student)[0].status, 403)

        users = self._req("GET", "/api/auth/users", cookie=teacher)[1]["users"]
        self.assertEqual([u["nickname"] for u in users], ["老师", "小王"])
        actions = [row["action"] for row in self._req("GET", "/api/auth/audit", cookie=teacher)[1]["audit"]]
        for action in ("login", "login_failed", "invite", "register"):
            self.assertIn(action, actions)

        resp, _ = self._req("POST", "/api/auth/logout", {}, cookie=student)
        self.assertIn("Max-Age=0", resp.getheader("Set-Cookie"))
        self.assertEqual(self._req("GET", "/api/interventions", cookie=student)[0].status, 401)

    def test_admin_resets_a_password(self):
        store = _store(self.tmp.name)
        store.create_user("老师", PASSWORD, role="admin")
        pupil = store.create_user("小李", PASSWORD)
        teacher = self._login("老师")
        resp, body = self._req("POST", f"/api/auth/users/{pupil['id']}/reset", {}, cookie=teacher)
        self.assertEqual(resp.status, 200)
        resp, _ = self._req("POST", "/api/auth/reset", {"code": body["code"], "password": "brand new pw"})
        self.assertEqual(resp.status, 200)
        self._login("小李", "brand new pw")
        resp, body = self._req("POST", f"/api/auth/users/{pupil['id']}/city", {"allow": True}, cookie=teacher)
        self.assertTrue(body["user"]["can_create_city"])

    def test_personal_keys_are_isolated_over_http(self):
        from pathlib import Path

        from gaworld.apps import settings_api

        store = _store(self.tmp.name)
        store.create_user("teacher", PASSWORD, role="admin")
        store.create_user("student", PASSWORD)
        teacher, student = self._login("teacher"), self._login("student")
        endpoint = "/api/settings/llm/credential"
        cfg = {"llm": {"providers": {"test": {
            "type": "openai", "base_url": "https://test.invalid/v1", "model": "test",
        }}}}
        path = str(Path(self.tmp.name).resolve() / "private-keys" / "keys.json")
        with mock.patch.dict(os.environ, {"GAWORLD_LLM_SECRETS_PATH": path}), \
                mock.patch.object(settings_api.world_paths, "effective_config", return_value=cfg):
            self.assertEqual(self._req("POST", endpoint, {"name": "test", "api_key": "unused"})[0].status, 401)
            resp, body = self._req("POST", endpoint, {"name": "test", "api_key": "student-test-key"}, cookie=student)
            self.assertEqual(resp.status, 200)
            self.assertNotIn("student-test-key", json.dumps(body))
            overview = self._req("GET", "/api/settings/overview", cookie=student)[1]
            self.assertTrue(overview["providers"][0]["key_ready"])
            self.assertTrue(overview["can_manage_credentials"])
            teacher_view = self._req("GET", "/api/settings/overview", cookie=teacher)[1]
            self.assertFalse(teacher_view["providers"][0]["key_ready"])
            self.assertNotIn("student-test-key", json.dumps(teacher_view))
            self.assertEqual(self._req("POST", endpoint, {
                "name": "test", "action": "delete", "user_id": 2}, cookie=teacher)[0].status, 400)
            self.assertEqual(self._req("POST", "/api/settings/llm/test", {
                "name": "test", "config": cfg["llm"]["providers"]["test"]}, cookie=student)[0].status, 403)
            self.assertEqual(self._req("POST", endpoint, {
                "name": "test", "action": "delete"}, cookie=student)[0].status, 200)

    def test_operator_token_is_still_an_admin(self):
        _store(self.tmp.name)
        with mock.patch.dict(os.environ, {"GAWORLD_DASHBOARD_TOKEN": "op-token"}):
            auth = {"Authorization": "Bearer op-token"}
            self.assertEqual(self._req("GET", "/api/auth/users", headers=auth)[0].status, 200)
            self.assertEqual(self._req("GET", "/api/auth/me", headers=auth)[1]["user"]["role"], "admin")
            self.assertEqual(self._req("GET", "/api/interventions")[0].status, 401)


class CliTest(unittest.TestCase):
    def test_init_invite_and_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "a.sqlite")
            with mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db}):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["invite"]), 1)  # no database yet
                with mock.patch("sys.stdin", io.StringIO(PASSWORD + "\n")), redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["init", "--admin", "老师", "--password-stdin"]), 0)
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(cli.main(["invite", "--count", "3", "--label", "周三班"]), 0)
                codes = out.getvalue().split()
                self.assertEqual(len(codes), 3)
                store = AccountStore(db)
                store.register(codes[0], "小王", PASSWORD)
                out = io.StringIO()
                with redirect_stdout(out):
                    cli.main(["city-permission", "--nickname", "小王", "--allow"])
                    cli.main(["users"])
                self.assertIn("可建城", out.getvalue())
                with mock.patch("sys.stdin", io.StringIO(PASSWORD + "\n")), redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(["init", "--admin", "x", "--password-stdin"]), 1)


if __name__ == "__main__":
    unittest.main()
