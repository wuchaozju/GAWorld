"""Unit tests for the GAWorld-managed FOS backend supervisor.

TDD RED: move integrated FOS lifecycle from scripts/start_fos_integrated.sh
into Python. The supervisor (gaworld/apps/fos_supervisor.py) must:

- spawn the FOS backend with sys.executable -m uvicorn fos.backend.main:app
  bound to loopback only, in an additive copy of the environment carrying
  FOS_SINGLE_USER_MODE=true and FOS_SINGLE_USER_USERNAME=local and never
  FOS_SINGLE_USER_ALLOW_REMOTE_BIND;
- respect an explicit FOS_BACKEND_URL (external backend -> do not spawn);
- reuse an already-running healthy integrated backend (single_user_mode true)
  WITHOUT owning or killing it;
- fail with an actionable error when the port is held by a standalone
  (single_user_mode false) FOS backend or by a non-FOS process;
- verify readiness via /api/config before reporting success;
- terminate only processes it spawned.

All subprocess/network interaction is mocked; no sleeps.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import fos_supervisor as sup


class _FakePopen:
    """Minimal Popen double recording lifecycle calls."""

    def __init__(self):
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        return 0


def _cfg(single_user_mode=True):
    return {"app_name": "FOS Backend", "single_user_mode": single_user_mode}


class BuildChildEnvTests(unittest.TestCase):
    def test_env_is_additive_and_sets_integrated_mode(self):
        base = {"PATH": "/x", "MY_SECRET_TOKEN": "keep-me", "FOS_DB_PASSWORD": "keep"}
        env = sup.build_child_env(base)
        self.assertEqual(env["PATH"], "/x")
        self.assertEqual(env["MY_SECRET_TOKEN"], "keep-me")
        self.assertEqual(env["FOS_SINGLE_USER_MODE"], "true")
        self.assertEqual(env["FOS_SINGLE_USER_USERNAME"], "local")
        self.assertNotIn("FOS_SINGLE_USER_ALLOW_REMOTE_BIND", env)

    def test_preexisting_allow_remote_bind_is_stripped(self):
        base = {"FOS_SINGLE_USER_ALLOW_REMOTE_BIND": "true"}
        env = sup.build_child_env(base)
        self.assertNotIn("FOS_SINGLE_USER_ALLOW_REMOTE_BIND", env)

    def test_pythonpath_includes_fos_src(self):
        env = sup.build_child_env({})
        self.assertIn("fos", env.get("PYTHONPATH", "").replace(os.sep, "/"))


class SpawnCommandTests(unittest.TestCase):
    def test_spawn_uses_sys_executable_uvicorn_and_loopback(self):
        popen = _FakePopen()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sup.subprocess, "Popen", return_value=popen) as mp,
            mock.patch.object(sup, "_probe_config", side_effect=[None, _cfg(True)]),
            mock.patch.object(sup, "_port_probe_responds", return_value=False),
            mock.patch("time.sleep"),
        ):
            handle = sup.ensure_backend(poll_attempts=2)
        self.assertIsNotNone(handle)
        args = mp.call_args.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertIn("-m", args)
        self.assertIn("uvicorn", args)
        self.assertIn("fos.backend.main:app", args)
        self.assertIn("--host", args)
        self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
        self.assertIn("--port", args)
        self.assertEqual(args[args.index("--port") + 1], str(sup.DEFAULT_FOS_PORT))


class ReuseHealthyBackendTests(unittest.TestCase):
    def test_healthy_integrated_backend_is_reused_not_owned_nor_killed(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sup, "_probe_config", return_value=_cfg(True)),
            mock.patch.object(sup.subprocess, "Popen") as mp,
        ):
            handle = sup.ensure_backend()
        mp.assert_not_called()
        self.assertFalse(handle["owned"])
        sup.shutdown_backend(handle)  # must be a no-op, not a kill
        self.assertFalse(bool(handle.get("_popen")))


class IncompatibleBackendTests(unittest.TestCase):
    def test_standalone_backend_on_port_fails_without_spawn_or_kill(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sup, "_probe_config", return_value=_cfg(False)),
            mock.patch.object(sup.subprocess, "Popen") as mp,
        ):
            with self.assertRaises(sup.FosBackendError) as ctx:
                sup.ensure_backend()
        mp.assert_not_called()
        msg = str(ctx.exception).lower()
        self.assertIn("standalone", msg)
        self.assertIn("8000", msg)

    def test_non_fos_process_on_port_fails(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sup, "_probe_config", return_value=None),
            mock.patch.object(sup, "_port_probe_responds", return_value=True),
            mock.patch.object(sup.subprocess, "Popen") as mp,
        ):
            with self.assertRaises(sup.FosBackendError):
                sup.ensure_backend()
        mp.assert_not_called()


class ExternalBackendTests(unittest.TestCase):
    def test_explicit_external_backend_url_skips_spawn(self):
        env = dict(os.environ, FOS_BACKEND_URL="http://127.0.0.1:9999")
        with (
            mock.patch.object(sup.os, "environ", env),
            mock.patch.object(sup.subprocess, "Popen") as mp,
            mock.patch.object(sup, "_probe_config") as probe,
        ):
            handle = sup.ensure_backend()
        self.assertIsNone(handle)
        mp.assert_not_called()
        probe.assert_not_called()


class OwnedLifecycleTests(unittest.TestCase):
    def test_shutdown_terminates_owned_process(self):
        popen = _FakePopen()
        handle = {"owned": True, "_popen": popen, "url": sup.backend_base_url()}
        sup.shutdown_backend(handle)
        self.assertTrue(popen.terminated)
        self.assertFalse(popen.killed)

    def test_readiness_failure_terminates_spawned_process(self):
        popen = _FakePopen()
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sup.subprocess, "Popen", return_value=popen),
            mock.patch.object(sup, "_probe_config", return_value=None),
            mock.patch.object(sup, "_port_probe_responds", return_value=False),
            mock.patch("time.sleep"),
        ):
            with self.assertRaises(sup.FosBackendError):
                sup.ensure_backend(poll_attempts=2)
        self.assertTrue(popen.terminated)


class RunServerWiringTests(unittest.TestCase):
    def test_run_server_starts_and_shuts_down_managed_backend(self):
        from gaworld.apps import dashboard_server as ds

        ensure = mock.MagicMock(return_value={"owned": True, "_popen": _FakePopen()})
        shutdown = mock.MagicMock()

        class _DummyServer:
            def __init__(self, addr, handler):
                self.server_close = mock.MagicMock()

            def serve_forever(self):
                raise KeyboardInterrupt()

        env = {k: v for k, v in os.environ.items() if k != "FOS_BACKEND_URL"}
        with (
            mock.patch.object(ds, "_ensure_fos_backend", ensure, create=True),
            mock.patch.object(ds, "_shutdown_fos_backend", shutdown, create=True),
            mock.patch.object(ds, "ThreadingHTTPServer", _DummyServer),
            mock.patch.dict(os.environ, env, clear=True),
        ):
            ds.run_server(port=0)
        ensure.assert_called_once()
        shutdown.assert_called_once()


class CliHelpSmoke(unittest.TestCase):
    def test_gaworld_dashboard_help(self):
        import subprocess

        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        console_script = os.path.join(os.path.dirname(sys.executable), "gaworld")
        cmds = [
            [sys.executable, "generative_city_sim.py", "dashboard", "--help"],
        ]
        if os.path.exists(console_script):
            cmds.insert(0, [console_script, "dashboard", "--help"])
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("dashboard", (proc.stdout + proc.stderr).lower())


if __name__ == "__main__":
    unittest.main()
