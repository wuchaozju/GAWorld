"""`/api/economy/*`: friend-loan graph, per-agent ledger, overview alias.

The loan books are produced by the real ``_process_friend_loans`` so the test
reads what the simulator writes, and a deliberately broken pair must surface as
a mismatch — a one-sided loan is money created or destroyed in the plumbing.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.economy import finance


def _agent(aid, name, checking, savings, distress=False, neighbors=()):
    return {
        "id": aid, "name": name, "social_neighbors": list(neighbors),
        "relationships": {str(n): {"closeness": 0.9, "trust": 0.9} for n in neighbors},
        "economy": {"_distress_today": distress, "monthly_expense_estimate": 3000.0,
                    "accounts": {"checking": checking, "savings": savings}, "debt": 0.0},
    }


class EconomyApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = ds.REPO_ROOT
        ds.REPO_ROOT = self.tmp.name
        self.agents_dir = os.path.join(self.tmp.name, "output", "economy", "agents")
        os.makedirs(self.agents_dir)
        borrower = _agent(1, "小王", 100.0, 0.0, distress=True, neighbors=(2,))
        lender = _agent(2, "老李", 20000.0, 50000.0)
        lender["economy"]["debt"] = 1200.0
        agents = [borrower, lender]
        finance._process_friend_loans({a["id"]: a for a in agents}, agents, {})
        self.assertTrue(borrower["economy"].get("friend_debts"), "fixture: no loan was made")
        for a in agents:
            with open(os.path.join(self.agents_dir, f"agent_{a['id']}_snapshot.json"), "w") as f:
                json.dump({"agent_id": a["id"], "name": a["name"], "economy": a["economy"]}, f)
        with open(os.path.join(self.agents_dir, "agent_1_ledger.csv"), "w") as f:
            f.write("day,agent_id,balance,macro_phase\n1,1,100.5,expansion\n2,1,90,peak\n3,1,80,peak\n")
        self.loan = borrower["economy"]["friend_debts"]["2"]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        ds.REPO_ROOT = self._saved
        self.tmp.cleanup()

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_loan_graph_bank_debt_and_consistency(self):
        status, body = self._get("/api/economy/loans")
        self.assertEqual(status, 200)
        self.assertTrue(body["consistent"])
        self.assertEqual(body["friend_loans"], [{"borrower": "1", "borrower_name": "小王", "lender": "2",
                                                 "lender_name": "老李", "amount": self.loan}])
        self.assertEqual(body["bank_debt"], [{"agent_id": "2", "name": "老李", "debt": 1200.0}])

        path = os.path.join(self.agents_dir, "agent_2_snapshot.json")
        with open(path) as f:
            snap = json.load(f)
        snap["economy"]["friend_credits"] = {}
        with open(path, "w") as f:
            json.dump(snap, f)
        _, body = self._get("/api/economy/loans")
        self.assertFalse(body["consistent"])
        self.assertEqual(body["mismatches"][0]["lender_records"], 0.0)

    def test_ledger(self):
        _, body = self._get("/api/economy/ledger?agent_id=1&limit=2")
        self.assertEqual([r["day"] for r in body["rows"]], [2.0, 3.0])
        self.assertEqual(body["rows"][0]["macro_phase"], "peak")
        self.assertEqual(body["friend_debts"], {"2": self.loan})
        self.assertEqual(self._get("/api/economy/ledger?agent_id=9")[0], 404)
        self.assertEqual(self._get("/api/economy/ledger?agent_id=x")[0], 400)
        self.assertEqual(self._get("/api/economy/ledger?agent_id=1&limit=-1")[0], 400)

    def test_overview_is_the_external_systems_payload(self):
        status, body = self._get("/api/economy/overview")
        self.assertEqual(status, 200)
        for key in ("macro", "sectors", "conservation", "wealth", "ledger"):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()
