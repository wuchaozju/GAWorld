"""Generic interventions over HTTP and the SSE record stream.

Failure modes this guards, each invisible until a user hit it:

* **A queued request that nothing applies.** The dashboard and the simulator
  are different processes; the queue is only real if the simulator-side
  ``drain`` feeds it through ``controller.intervene`` — tested against a real
  kernel, not a mock.
* **Requests accepted for a run that is gone.** A crashed run never clears its
  ``active`` flag, so liveness is the pid; a dead pid must answer 409.
* **Lazily registered interventions never become reachable.** The twin
  registers on its first tick, after the manifest is published.
* **The stream replays history or tears lines.** It must start at the current
  end, send only complete lines, and honour the table filter.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import kernel_api
from gaworld.kernel import build_kernel
from gaworld.kernel import remote


def _kernel(tmp):
    ctx = build_kernel(
        {"records": {"output_dir": os.path.join(tmp, "records")}},
        load_entry_points=False,
    )
    ctx.set_agents([{"id": 1, "state": {"stress": 0.2}}])
    ctx.clock.start_day(3)
    return ctx


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "kernel", "interventions.json")
        self.ctx = _kernel(self.tmp.name)

    def tearDown(self):
        self.ctx.recorder.close()
        self.tmp.cleanup()

    def test_enqueued_request_is_applied_through_the_controller(self):
        remote.publish(self.ctx, self.path)
        item = remote.enqueue(self.path, "set_agent_state", {"agent_id": 1, "key": "stress", "value": 0.9})
        self.assertEqual(remote.drain(self.ctx, self.path), 1)
        self.assertEqual(self.ctx.agents_by_id[1]["state"]["stress"], 0.9)
        done = remote.lookup(self.path, item["id"])
        self.assertEqual(done["status"], "applied")
        self.assertEqual(done["applied_at"]["day"], 3)
        with open(os.path.join(self.tmp.name, "records", "controller.intervention.jsonl")) as f:
            self.assertEqual(json.loads(f.readline())["name"], "set_agent_state")

    def test_bad_kwargs_fail_without_stopping_the_queue(self):
        remote.publish(self.ctx, self.path)
        bad = remote.enqueue(self.path, "set_agent_state", {"agent_id": 99, "key": "stress", "value": 1})
        good = remote.enqueue(self.path, "set_agent_state", {"agent_id": 1, "key": "stress", "value": 0.5})
        self.assertEqual(remote.drain(self.ctx, self.path), 2)
        self.assertEqual(remote.lookup(self.path, bad["id"])["status"], "failed")
        self.assertIn("unknown agent", remote.lookup(self.path, bad["id"])["error"])
        self.assertEqual(remote.lookup(self.path, good["id"])["status"], "applied")

    def test_unknown_name_and_dead_run_are_rejected(self):
        remote.publish(self.ctx, self.path)
        with self.assertRaises(KeyError):
            remote.enqueue(self.path, "no_such_thing", {})
        remote.close(self.ctx, self.path)
        with self.assertRaises(LookupError):
            remote.enqueue(self.path, "set_agent_state", {})

    def test_crashed_run_counts_as_not_running(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        remote.publish(self.ctx, self.path)
        data = remote.read(self.path)
        data["pid"] = proc.pid
        remote._write(self.path, data)
        with self.assertRaises(LookupError):
            remote.enqueue(self.path, "set_agent_state", {})

    def test_new_run_drops_requests_left_by_the_previous_one(self):
        remote.publish(self.ctx, self.path)
        remote.enqueue(self.path, "set_agent_state", {"agent_id": 1, "key": "stress", "value": 1})
        remote.publish(self.ctx, self.path)
        self.assertEqual(remote.read(self.path)["pending"], [])

    def test_lazily_registered_intervention_reaches_the_manifest(self):
        remote.publish(self.ctx, self.path)
        self.ctx.controller.register_intervention("late_one", lambda ctx, **kw: "ok")
        remote.drain(self.ctx, self.path)
        self.assertIn("late_one", remote.read(self.path)["registered"])
        item = remote.enqueue(self.path, "late_one", {})
        remote.drain(self.ctx, self.path)
        self.assertEqual(remote.lookup(self.path, item["id"])["result"], "ok")

    def test_parallel_worlds_get_their_own_queue(self):
        self.assertEqual(remote.path_for({}), remote.DEFAULT_PATH)
        self.assertEqual(remote.path_for({"kernel": {"interventions_path": "w/q.json"}}), "w/q.json")


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = (ds.REPO_ROOT, ds.RECORDS_DIR, kernel_api.POLL_SECONDS)
        ds.REPO_ROOT = self.tmp.name
        ds.RECORDS_DIR = os.path.join(self.tmp.name, "records")
        os.makedirs(ds.RECORDS_DIR)
        kernel_api.POLL_SECONDS = 0.05
        self.ctx = _kernel(self.tmp.name)
        self.qpath = os.path.join(self.tmp.name, remote.DEFAULT_PATH)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ctx.recorder.close()
        ds.REPO_ROOT, ds.RECORDS_DIR, kernel_api.POLL_SECONDS = self._saved
        self.tmp.cleanup()

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_post_queue_poll_roundtrip(self):
        status, body = self._call("POST", "/api/interventions/set_agent_state", {"agent_id": 1})
        self.assertEqual(status, 409)
        remote.publish(self.ctx, self.qpath)
        status, listing = self._call("GET", "/api/interventions")
        self.assertTrue(listing["running"])
        self.assertIn("remove_agent", listing["registered"])
        status, body = self._call("POST", "/api/interventions/nope", {})
        self.assertEqual(status, 404)
        self.assertIn("set_agent_state", body["registered"])
        status, item = self._call(
            "POST", "/api/interventions/set_agent_state", {"agent_id": 1, "key": "stress", "value": 0.7}
        )
        self.assertEqual(status, 202)
        remote.drain(self.ctx, self.qpath)
        status, done = self._call("GET", f"/api/interventions/{item['id']}")
        self.assertEqual((status, done["status"]), (200, "applied"))
        self.assertEqual(self._call("GET", "/api/interventions/zzz")[0], 404)

    def test_stream_pushes_only_new_complete_rows_of_selected_tables(self):
        with open(os.path.join(ds.RECORDS_DIR, "traffic.tick.jsonl"), "w") as f:
            f.write(json.dumps({"old": True}) + "\n")
        port = self.server.server_address[1]
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(b"GET /api/events/stream?tables=traffic.tick HTTP/1.1\r\nHost: x\r\n\r\n")
        reader = sock.makefile("rb")
        buf = b""
        while b": connected" not in buf:
            buf += reader.readline()
        self.assertIn(b"text/event-stream", buf)
        with open(os.path.join(ds.RECORDS_DIR, "family.agent.jsonl"), "w") as f:
            f.write(json.dumps({"skip": True}) + "\n")
        with open(os.path.join(ds.RECORDS_DIR, "traffic.tick.jsonl"), "a") as f:
            f.write(json.dumps({"n": 1}) + "\n" + '{"torn": ')
            f.flush()
        frame = []
        while True:
            line = reader.readline().decode()
            if line.startswith(":"):
                continue
            if line == "\n" and frame:
                break
            if line.strip():
                frame.append(line.strip())
        self.assertEqual(frame, ["event: traffic.tick", 'data: {"n": 1}'])
        sock.close()


if __name__ == "__main__":
    unittest.main()
