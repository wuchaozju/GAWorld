"""Results belong to their maker; model calls count against a soft quota (P3).

* ``gaworld.accounts.ownership``: stamped on creation, listed / read / deleted
  only by the maker and admins; single-user mode sees everything; background
  jobs keep the asking user.
* Each store wired to it: interview sessions, research plans, personas (no
  overwriting someone else's portrait), persuasion, the arena's elimination
  ledger.
* ``gaworld.accounts.usage``: one line per model call, tallied per user per
  day; the dashboard refuses new model work once a member's quota is spent.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.accounts import AccountStore, ownership, policy, usage
from gaworld.accounts.context import USER

SA, SOLD = "20261002-000000-aaaaaa", "20261001-000000-bbbbbb"
PLAN = "20261002-000000-cccccc"
A = {"id": 2, "nickname": "小王", "role": "member"}
B = {"id": 3, "nickname": "小李", "role": "member"}
ADMIN = {"id": 1, "nickname": "老师", "role": "admin"}
PASSWORD = "correct horse"


@contextlib.contextmanager
def as_user(user):
    token = USER.set(user)
    try:
        yield
    finally:
        USER.reset(token)


class OwnershipTest(unittest.TestCase):
    def test_rules(self):
        record = {"owner_id": 2}
        self.assertTrue(ownership.visible(record))  # single-user mode
        self.assertEqual(ownership.stamp(), {})
        with as_user(A):
            self.assertEqual(ownership.stamp(), {"owner_id": 2, "owner": "小王"})
            self.assertTrue(ownership.visible(record))
            self.assertFalse(ownership.visible({}))
            self.assertFalse(ownership.sees_unowned())
            self.assertFalse(ownership.visible(None))
        with as_user(B):
            self.assertFalse(ownership.visible(record))
            self.assertEqual(ownership.owned([record, {"owner_id": 3}]), [{"owner_id": 3}])
        with as_user(ADMIN):
            self.assertTrue(ownership.visible(record))
            self.assertTrue(ownership.sees_unowned())

    def test_spawned_threads_keep_the_user(self):
        seen = []
        with as_user(A):
            ownership.spawn(lambda: seen.append(USER.get()), name="t").join(5)
        self.assertEqual(seen, [A])

    def test_owner_deletes_are_member_level(self):
        for path in (
            "/api/interview/delete",
            "/api/research/delete",
            "/api/persona/delete",
            "/api/research/games/g1/delete",
            "/api/research/games/sessions/s1/delete",
            "/api/research/policy/r1/delete",
        ):
            self.assertEqual(policy.required("POST", path), "member", path)
        self.assertEqual(policy.required("POST", "/api/research/studies/x/delete"), "admin")
        self.assertTrue(policy.quota_gated("/api/games/duel/run"))
        self.assertFalse(policy.quota_gated("/api/config"))


class StoresTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_interview_sessions(self):
        from gaworld.apps import interview_api
        from gaworld.interview import store

        with mock.patch.object(store, "PROJECT_ROOT", self.root):
            store.save_session({"id": SA, "title": "A", "owner_id": 2})
            store.save_session({"id": SOLD, "title": "before accounts"})
            with as_user(A):
                self.assertEqual([s["id"] for s in interview_api.sessions()["sessions"]], [SA])
            with as_user(B):
                self.assertEqual(interview_api.sessions()["sessions"], [])
                self.assertIsNone(interview_api.session_detail(SA))
                self.assertEqual(interview_api.delete({"session_id": SA})["deleted"], False)
                with self.assertRaises(ValueError):  # no follow-up rounds on someone else's session
                    interview_api.start_round({"session_id": SA})
            with as_user(ADMIN):
                self.assertEqual(len(interview_api.sessions()["sessions"]), 2)
            with as_user(A):
                self.assertTrue(interview_api.delete({"session_id": SA})["deleted"])

    def test_research_plans(self):
        from gaworld.apps import research_api
        from gaworld.research import workbench

        plan = workbench.ResearchPlan.from_dict(
            {
                "id": PLAN,
                "kind": "idea",
                "title": "T",
                "language": "zh",
                "provider": "",
                "created_at": "2026-10-02",
            }
        )
        with mock.patch.object(workbench, "plans_root", return_value=self.root):
            with as_user(A):
                workbench.save_plan(plan, ownership.stamp())
                self.assertEqual([p["id"] for p in research_api.plans()["plans"]], [PLAN])
            with as_user(B):
                self.assertEqual(research_api.plans()["plans"], [])
                from gaworld.research import study as study_mod

                with (
                    mock.patch.object(research_api, "_heal_all"),
                    mock.patch.object(research_api, "_providers", return_value=[]),
                    mock.patch.object(study_mod, "list_studies", return_value=[{"id": "st1"}]),
                ):
                    ctx = research_api.context()
                    self.assertEqual((ctx["plans"], ctx["studies"]), ([], []))
                self.assertIsNone(research_api.plan_detail(PLAN))
                self.assertFalse(research_api.delete({"plan_id": PLAN})["deleted"])
                self.assertEqual(research_api.handle_get("/api/research/studies")[0], {"studies": []})

    def test_personas(self):
        from gaworld.apps import persona_api

        os.makedirs(self.root / "zhang-san")
        with mock.patch.dict(os.environ, {"GAWORLD_PERSONA_DIR": str(self.root)}):
            with as_user(A):
                persona_api._write_owner("zhang-san")
                self.assertTrue(persona_api._mine("zhang-san"))
            with as_user(B):
                self.assertFalse(persona_api._mine("zhang-san"))
                self.assertFalse(persona_api.delete({"slug": "zhang-san"})["deleted"])
            self.assertTrue((self.root / "zhang-san").is_dir())

    def test_persuasion(self):
        from gaworld.apps import games_api

        with as_user(A):
            session = games_api.PersuasionSession(
                id="p1", city="", persona={"agent_id": 5, "name": "甲"}, question="?", max_turns=3
            )
            games_api._store(session)
        try:
            with as_user(B):
                self.assertIsNone(games_api.get_session("p1"))
                self.assertEqual(games_api.list_sessions(), [])
            with as_user(A):
                self.assertEqual(games_api.get_session("p1")["id"], "p1")
        finally:
            games_api.reset_sessions()

    def test_arena_ledger_is_per_user(self):
        from gaworld.apps import arena_api

        with mock.patch.object(arena_api, "_city_slug", side_effect=lambda ref: ref):
            try:
                with as_user(A):
                    arena_api.mark_eliminated("c", [1, 2])
                with as_user(B):
                    self.assertEqual(arena_api.eliminated_for("c"), [])
                    self.assertEqual(arena_api.survivors_for("c", [1, 2, 3]), [1, 2, 3])
                with as_user(A):
                    self.assertEqual(arena_api.eliminated_for("c"), [1, 2])
            finally:
                arena_api.reset_eliminated()


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "accounts.sqlite")
        self.env = mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": self.db})
        self.env.start()
        self.store = AccountStore(self.db)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_nothing_is_written_without_accounts(self):
        usage.record("x")
        self.assertIsNone(usage.usage_path())
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "usage.jsonl")))

    def test_calls_are_tallied_per_user_and_child_processes_inherit_the_user(self):
        self.store.init_schema()
        tally = usage.Tally()
        with as_user(A):
            usage.record("interview")
            usage.record("interview")
            env = usage.child_env({})
        self.assertEqual(env, {usage.ENV_USER: "2"})
        with mock.patch.dict(os.environ, env):  # a child process: no context, only the environment
            usage.record("sim")
        with as_user(B):
            usage.record("game")
        self.assertEqual(tally.today(2), 3)
        self.assertEqual(tally.today(3), 1)
        with as_user(B):
            usage.record("game")
        self.assertEqual(tally.today(3), 2)  # read incrementally

    def test_call_llm_records_even_when_the_call_fails(self):
        from gaworld.llm import providers

        self.store.init_schema()
        with as_user(A), mock.patch.object(providers.LLM_ROUTER, "call", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                providers.call_llm("hi", task="t")
        self.assertEqual(usage.Tally().today(2), 1)


class QuotaHttpTest(unittest.TestCase):
    def setUp(self):
        from gaworld.apps import dashboard_server as ds

        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "accounts.sqlite")
        self.store = AccountStore(db)
        self.store.init_schema()
        self.store.create_user("老师", PASSWORD, role="admin")
        self.student = self.store.create_user("小王", PASSWORD)
        self.env = mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db})
        self.env.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        self.tally = mock.patch.object(usage, "TALLY", usage.Tally())
        self.tally.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tally.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _req(self, method, path, body=None, cookie=""):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(
            method,
            path,
            body=json.dumps(body or {}),
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, json.loads(data) if data else None

    def _login(self, nickname):
        resp, _ = self._req("POST", "/api/auth/login", {"nickname": nickname, "password": PASSWORD})
        return resp.getheader("Set-Cookie").split(";", 1)[0]

    def test_quota_refuses_new_model_work_only(self):
        teacher, student = self._login("老师"), self._login("小王")
        self.assertEqual(
            self._req("POST", "/api/worlds/settings", {"daily_llm_calls_per_user": 2}, teacher)[1]["limits"][
                "daily_llm_calls_per_user"
            ],
            2,
        )
        with as_user(self.student):
            usage.record("x")
            usage.record("x")
        resp, body = self._req("POST", "/api/games/guess/deal", {}, student)
        self.assertEqual(resp.status, 429)
        self.assertIn("额度", body["error"])
        self.assertNotEqual(self._req("POST", "/api/auth/logout", {}, student)[0].status, 429)
        rows = self._req("GET", "/api/auth/usage", cookie=teacher)[1]
        self.assertEqual(rows["quota"], 2)
        self.assertEqual({r["nickname"]: r["today"] for r in rows["users"]}, {"老师": 0, "小王": 2})


if __name__ == "__main__":
    unittest.main()
