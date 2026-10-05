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

from gaworld.apps import world_paths

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from gaworld.apps import bench_api
from gaworld.apps import dashboard_server as ds


class ArgvTest(unittest.TestCase):
    def test_whitelist_types_and_paths(self):
        argv = bench_api.build_argv("bench", {"track": "C", "run": True, "days": "3", "fast": False,
                                              "output_dir": "output"})
        self.assertEqual(argv[1:], ["gaworld_bench.py", "--track", "C", "--output-dir",
                                    os.path.realpath(os.path.join(world_paths.REPO_ROOT, "output")),
                                    "--run", "--days", "3"])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            bench_api.build_argv("bench", {"results_dir": "/tmp"})
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            bench_api.build_argv("rubric", {"output_dir": "../../etc"})
        with self.assertRaisesRegex(ValueError, "days"):
            bench_api.build_argv("bench", {"days": "three"})
        with self.assertRaisesRegex(ValueError, "unknown harness"):
            bench_api.build_argv("nope", {})
        # Judging a calibration set is a job too: it spends model calls.
        self.assertEqual(bench_api.build_argv("calibration", {"judge": True, "set": "s1", "judges": "a,b"})[1:],
                         ["rubric_calibrate.py", "--judge", "--set", "s1", "--judges", "a,b"])


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        shutil.copytree(os.path.join(REPO, "benchmark"), os.path.join(self.tmp.name, "benchmark"),
                        ignore=shutil.ignore_patterns("results", "__pycache__"))
        self._saved = world_paths.REPO_ROOT
        world_paths.REPO_ROOT = self.tmp.name
        bench_api._JOBS.clear()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        world_paths.REPO_ROOT = self._saved
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
        self.assertEqual(done["scorecard"]["trust_gate"], "FIXTURE")
        self.assertEqual(done["scorecard"]["provenance"]["source"], "synthetic")
        self.assertIn("--synthetic", done["command"])
        self.assertIn("Scorecard", done["log_tail"])

        status, rjob = self._call("POST", "/api/bench/run", {"kind": "rubric", "synthetic": True})
        self.assertEqual(status, 202)
        rdone = self._wait(rjob["id"])
        self.assertEqual(rdone["status"], "done")
        self.assertIn("dimensions", rdone["scorecard"])
        self.assertEqual(rdone["scorecard"]["gate"]["state"], "FIXTURE")
        # The first job still carries its own card after the second run.
        _, again = self._call("GET", f"/api/bench/jobs/{job['id']}")
        self.assertEqual(again["scorecard"]["tracks"]["C"]["score"], 1.0)

        # Fixtures never become the headline card or enter the report list.
        self.assertEqual(self._call("GET", "/api/bench/scorecard")[1], {"bench": None, "rubric": None})
        self.assertEqual(self._call("GET", "/api/bench/reports")[1], {"reports": []})

        # A run over real output does (here: an output dir with no economy data).
        status, real = self._call("POST", "/api/bench/run",
                                  {"kind": "bench", "track": "A", "output_dir": "benchmark"})
        self.assertEqual(status, 202)
        self.assertEqual(self._wait(real["id"])["status"], "done")
        _, latest = self._call("GET", "/api/bench/scorecard")
        self.assertEqual(latest["bench"]["scorecard"]["provenance"]["source"], "real")
        self.assertNotEqual(latest["bench"]["scorecard"]["trust_gate"], "FIXTURE")
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


class CalibrationHttpTest(unittest.TestCase):
    """Track R human calibration: blind tasks, per-annotator labels, analysis."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        shutil.copytree(os.path.join(REPO, "benchmark"), os.path.join(self.tmp.name, "benchmark"),
                        ignore=shutil.ignore_patterns("results", "__pycache__"))
        self._saved = world_paths.REPO_ROOT
        world_paths.REPO_ROOT = self.tmp.name
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        calib = bench_api._calibration()
        from rubric import runner, synth

        self.set_doc, key = calib.build_set(synth.build(n_agents=6, n_days=32, seed=2), runner.load_rubric(), n=12)
        calib.save_set(self.set_doc, key, bench_api._calibration_root())
        self.sid = self.set_doc["set_id"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        world_paths.REPO_ROOT = self._saved
        self.tmp.cleanup()

    _call = HttpTest._call

    def test_annotate_blind_then_analyze(self):
        status, listing = self._call("GET", "/api/bench/calibration")
        self.assertEqual((status, [row["set_id"] for row in listing["sets"]]), (200, [self.sid]))
        status, view = self._call("GET", f"/api/bench/calibration/{self.sid}?annotator=" + urllib.request.quote("甲"))
        self.assertEqual(status, 200)
        self.assertEqual(len(view["set"]["tasks"]), 12)
        self.assertEqual(view["labels"], {})
        self.assertNotIn("source", json.dumps(view["set"]["tasks"][0]))

        for name in ("甲", "乙"):
            for task in view["set"]["tasks"]:
                status, body = self._call("POST", f"/api/bench/calibration/{self.sid}/label",
                                          {"annotator": name, "task_id": task["task_id"], "score": 2})
                self.assertEqual(status, 200, body)
        # Each annotator sees only their own labels.
        _, mine = self._call("GET", f"/api/bench/calibration/{self.sid}?annotator=" + urllib.request.quote("乙"))
        self.assertEqual(len(mine["labels"]), 12)
        self.assertEqual(self._call("POST", f"/api/bench/calibration/{self.sid}/label",
                                    {"annotator": "甲", "task_id": "T01", "score": 5})[0], 400)
        self.assertEqual(self._call("POST", f"/api/bench/calibration/{self.sid}/label",
                                    {"annotator": "甲", "task_id": "T99", "score": 1})[0], 400)
        self.assertEqual(self._call("GET", "/api/bench/calibration/nope")[0], 404)
        self.assertEqual(self._call("POST", "/api/bench/calibration/nope/analyze")[0], 404)

        status, analysis = self._call("POST", f"/api/bench/calibration/{self.sid}/analyze")
        self.assertEqual(status, 200)
        self.assertEqual(analysis["complete_annotators"], ["乙", "甲"])
        self.assertEqual(analysis["gate"]["status"], "incomplete")  # only 12 tasks, and no judge yet
        _, listing = self._call("GET", "/api/bench/calibration")
        self.assertEqual(listing["sets"][0]["gate"]["status"], "incomplete")
        self.assertEqual(listing["sets"][0]["annotators"], {"乙": 12, "甲": 12})

    def test_building_from_a_run_with_nothing_to_score_is_a_400(self):
        os.makedirs(os.path.join(self.tmp.name, "empty_run"))
        status, body = self._call("POST", "/api/bench/calibration/build", {"output_dir": "empty_run"})
        self.assertEqual(status, 400)
        self.assertIn("没有任何 rubric 条目可评", body["error"])
        self.assertEqual(self._call("POST", "/api/bench/calibration/build", {"output_dir": "../../etc"})[0], 400)


if __name__ == "__main__":
    unittest.main()
