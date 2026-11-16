"""C — progress-aware day timeout and K — exit diagnostics in wait_for_day.

Uses tiny real timers (sub-second windows) against an output dir with a
never-arriving sim_state.json; a helper thread touches the log to simulate
observable progress.
"""

import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

PathLike = "str | os.PathLike"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fos", "src")))

from fos.core.experiment.scenes.gaworld.subprocess_manager import (  # noqa: E402
    GAWorldProcessError,
    GAWorldSubprocessManager,
    GAWorldTimeoutError,
)


def _manager(output_dir: PathLike = None, process=None):
    mgr = GAWorldSubprocessManager(
        gaworld_path=pathlib.Path("."),
        config_overrides={},
        output_dir=pathlib.Path(output_dir),
    )
    mgr.process = process
    return mgr


class FakeProcess:
    def __init__(self, code):
        self._code = code

    def poll(self):
        return self._code


class TestExitDiagnostics(unittest.TestCase):
    def test_clean_early_exit_named_exited_without_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(tmp, process=FakeProcess(0))
            (mgr.output_dir / "gaworld.log").write_text("line1\nline2\n")
            mem = mgr.output_dir / "memory"
            mem.mkdir()
            (mem / "sim_state.json").write_text(json.dumps({"last_day": 3}))
            with self.assertRaises(GAWorldProcessError) as ctx:
                mgr.wait_for_day(5, timeout=10, poll_interval=0.01)
            self.assertIn("exited_without_completion", str(ctx.exception))
            self.assertIn("code 0", str(ctx.exception))
            self.assertIn("3", str(ctx.exception))  # last completed day
            self.assertIn("GAWorld log tail", str(ctx.exception))

    def test_nonzero_exit_named_process_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(tmp, process=FakeProcess(2))
            (mgr.output_dir / "gaworld.log").write_text("boom\n")
            with self.assertRaises(GAWorldProcessError) as ctx:
                mgr.wait_for_day(5, timeout=10, poll_interval=0.01)
            self.assertIn("process_failed", str(ctx.exception))
            self.assertIn("2", str(ctx.exception))


class TestProgressAwareTimeout(unittest.TestCase):
    def _stateless_dir(self, tmp):
        return tmp  # no memory/sim_state.json → day never reached

    def test_frozen_run_times_out_with_stall_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(self._stateless_dir(tmp))
            with self.assertRaises(GAWorldTimeoutError) as ctx:
                mgr.wait_for_day(1, timeout=0.3, poll_interval=0.05)
            self.assertIn("stalled", str(ctx.exception))
            snap = json.loads((mgr.output_dir / "gaworld_wait_status.json").read_text())
            self.assertEqual("stalled_no_progress", snap["timeout_cause"])

    def test_progressing_run_survives_past_window_but_hits_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = _manager(self._stateless_dir(tmp))
            log = mgr.output_dir / "gaworld.log"
            stop = threading.Event()
            window = 0.4

            def touch():
                i = 0
                while not stop.is_set():
                    log.write_text(f"tick {i}")
                    i += 1
                    time.sleep(0.05)

            t = threading.Thread(target=touch, daemon=True)
            t.start()
            start = time.time()
            try:
                with self.assertRaises(GAWorldTimeoutError) as ctx:
                    # window 0.4s, cap 3×0.4 = 1.2s: a naive absolute deadline
                    # would have fired at 0.4s; progress must carry it to the cap.
                    mgr.wait_for_day(1, timeout=window, poll_interval=0.05, absolute_cap_s=window * 3)
            finally:
                stop.set()
                t.join()
            elapsed = time.time() - start
            self.assertIn("absolute cap", str(ctx.exception))
            snap = json.loads((mgr.output_dir / "gaworld_wait_status.json").read_text())
            self.assertEqual("absolute_cap", snap["timeout_cause"])
            self.assertGreaterEqual(elapsed, window * 2.5)

    def test_env_override_respected(self):
        from fos.core.experiment.scenes.gaworld import scene

        with tempfile.TemporaryDirectory() as _, tempfile.TemporaryDirectory() as out:
            mgr = _manager(out)
            log = mgr.output_dir / "gaworld.log"
            log.write_text("hi")
            env = {k: v for k, v in os.environ.items() if k != "FOS_GAWORLD_DAY_TIMEOUT_S"}
            env["FOS_GAWORLD_DAY_TIMEOUT_S"] = "0.3"
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(0.3, scene.resolve_day_timeout_s())
                with self.assertRaises(GAWorldTimeoutError):
                    mgr.wait_for_day(1, timeout=scene.resolve_day_timeout_s(), poll_interval=0.05)


if __name__ == "__main__":
    unittest.main()
