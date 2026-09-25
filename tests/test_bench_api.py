"""`/api/bench/*`: benchmark harnesses as background jobs.

Guards: a payload that smuggles arbitrary flags or paths outside the repo into
the harness command line; two jobs overwriting one scorecard file; a job whose
own scorecard is lost when the next run rewrites the shared results file; and
the dashboard routing branch. The harness runs for real (``--synthetic``, no
LLM) against a copy of ``benchmark/`` so the real results are untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from gaworld.apps import bench_api
from gaworld.apps import dashboard_server as ds


class ArgvTest(unittest.TestCase):
    def test_whitelist_types_and_paths(self):
        argv = bench_api.build_argv("bench", {"track": "C", "run": True, "days": "3", "fast": False,
                                              "output_dir": "output"})
        self.assertEqual(argv[1:], ["gaworld_bench.py", "--track", "C", "--output-dir",
                                    os.path.realpath(os.path.join(ds.REPO_ROOT, "output")),
                                    "--run", "--days", "3"])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            bench_api.build_argv("bench", {"results_dir": "/tmp"})
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            bench_api.build_argv("rubric", {"output_dir": "../../etc"})
        with self.assertRaisesRegex(ValueError, "days"):
            bench_api.build_argv("bench", {"days": "three"})
        with self.assertRaisesRegex(ValueError, "unknown harness"):
            bench_api.build_argv("nope", {})


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        shutil.copytree(os.path.join(REPO, "benchmark"), os.path.join(self.tmp.name, "benchmark"),
                        ignore=shutil.ignore_patterns("results", "__pycache__"))
        self._saved = ds.REPO_ROOT
        ds.REPO_ROOT = self.tmp.name
        bench_api._JOBS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        ds.REPO_ROOT = self._saved
        bench_api._JOBS.clear()
        self.tmp.cleanup()

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def _wait(self, job_id):
        for _ in range(600):
            _, job = self._call("GET", f"/api/bench/jobs/{job_id}")
            if job["status"] != "running":
                return job
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_synthetic_runs_keep_their_own_scorecards(self):
        self.assertEqual(self._call("GET", "/api/bench/scorecard")[1], {"bench": None, "rubric": None})
        status, job = self._call("POST", "/api/bench/run", {"kind": "bench", "synthetic": True})
        self.assertEqual(status, 202)
        done = self._wait(job["id"])
        self.assertEqual((done["status"], done["returncode"]), ("done", 0))
        self.assertEqual(done["scorecard"]["tracks"]["C"]["score"], 1.0)
        self.assertIn("--synthetic", done["command"])
        self.assertIn("Scorecard", done["log_tail"])

        status, rjob = self._call("POST", "/api/bench/run", {"kind": "rubric", "synthetic": True})
        self.assertEqual(status, 202)
        rdone = self._wait(rjob["id"])
        self.assertEqual(rdone["status"], "done")
        self.assertIn("dimensions", rdone["scorecard"])
        # The first job still carries its own card after the second run.
        _, again = self._call("GET", f"/api/bench/jobs/{job['id']}")
        self.assertEqual(again["scorecard"]["tracks"]["C"]["score"], 1.0)

        _, latest = self._call("GET", "/api/bench/scorecard")
        self.assertIsNotNone(latest["bench"]["scorecard"])
        _, listing = self._call("GET", "/api/bench/reports")
        self.assertEqual(len(listing["reports"]), 1)
        _, report = self._call("GET", f"/api/bench/reports/{listing['reports'][0]}")
        self.assertIn("#", report["markdown"])
        self.assertEqual(self._call("GET", "/api/bench/reports/../../x.md")[0], 404)
        self.assertEqual(self._call("POST", "/api/bench/run", {"kind": "bench", "bogus": 1})[0], 400)

    def test_a_second_job_while_one_runs_is_refused(self):
        bench_api._JOBS["busy"] = {"id": "busy", "kind": "bench", "argv": ["py", "gaworld_bench.py"],
                                   "status": "running", "started_at": time.time(),
                                   "log_path": os.path.join(self.tmp.name, "none.log")}
        status, body = self._call("POST", "/api/bench/run", {"kind": "rubric", "synthetic": True})
        self.assertEqual((status, body["job"]["id"]), (409, "busy"))

    def test_failed_harness_is_reported_as_failed(self):
        status, job = self._call("POST", "/api/bench/run",
                                 {"kind": "rubric", "output_dir": "no_such_dir"})
        done = self._wait(job["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIsNone(done["scorecard"])


if __name__ == "__main__":
    unittest.main()
