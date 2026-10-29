"""G — cross-platform PID liveness (gaworld/kernel/proclive.py).

Linux behaviour must stay byte-equivalent to the old os.kill/ps logic;
the three-case distinction (absent / exists-uninspectable / exists-with-
commandline) is proven with patched platform functions.
"""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch


class TestPosixReal(unittest.TestCase):
    def test_own_pid_exists_and_command_matches(self):
        from gaworld.kernel import proclive

        pid = os.getpid()
        self.assertTrue(proclive.pid_exists(pid))
        self.assertTrue(proclive.command_matches(pid, "python"))
        self.assertIn("python", proclive.process_command(pid) or "")

    def test_absent_pid(self):
        from gaworld.kernel import proclive

        self.assertFalse(proclive.pid_exists(2**22))
        self.assertIsNone(proclive.process_command(2**22))
        self.assertFalse(proclive.command_matches(2**22, "generative_city_sim"))

    def test_child_process_command_visible(self):
        from gaworld.kernel import proclive

        child = subprocess.Popen(["sleep", "5"])
        try:
            self.assertTrue(proclive.pid_exists(child.pid))
            self.assertTrue(proclive.command_matches(child.pid, "sleep"))
        finally:
            child.kill()
            child.wait()


class TestThreeCases(unittest.TestCase):
    """Case distinction via the platform seam, platform-independent."""

    def test_remote_is_running_maps_three_cases(self):
        from gaworld.kernel import remote

        manifest = {"active": True, "pid": 4321}
        with patch.object(remote.proclive, "pid_exists", return_value=False):
            self.assertFalse(remote.is_running(manifest))  # absent
        with patch.object(remote.proclive, "pid_exists", return_value=True):
            self.assertTrue(remote.is_running(manifest))  # exists, uninspectable
        self.assertFalse(remote.is_running({"active": True, "pid": "x"}))
        self.assertFalse(remote.is_running({"active": False, "pid": 4321}))

    def test_is_simulator_process_identity_check(self):
        from gaworld.apps import runs

        with patch("gaworld.kernel.proclive.command_matches", return_value=True) as m:
            self.assertTrue(runs.is_simulator_process(999))
            m.assert_called_once_with(999, "generative_city_sim")
        with patch("gaworld.kernel.proclive.command_matches", return_value=False):
            # recycled pid: exists but wrong image
            self.assertFalse(runs.is_simulator_process(999))

    def test_win32_pid_exists_distinguishes_access_denied(self):
        from gaworld.kernel import proclive

        FAKE_ERR = {"code": 5}  # ERROR_ACCESS_DENIED
        fake_kernel32 = __import__("types").SimpleNamespace(
            OpenProcess=lambda a, b, pid: 0,
            GetLastError=lambda: FAKE_ERR["code"],
            CloseHandle=lambda h: None,
        )
        fake_ctypes = __import__("types").SimpleNamespace(
            wintypes=__import__("types").SimpleNamespace(DWORD=int)
        )
        fake_ctypes.windll = __import__("types").SimpleNamespace(kernel32=fake_kernel32)
        modules = {
            "ctypes": fake_ctypes,
            "ctypes.wintypes": fake_ctypes.wintypes,
        }
        saved_platform = sys.platform
        sys.platform = "win32"
        try:
            with patch.dict(sys.modules, modules):
                import importlib

                importlib.reload(proclive)
                self.assertTrue(proclive.pid_exists(5))  # access denied → exists
                FAKE_ERR["code"] = 87  # ERROR_INVALID_PARAMETER
                self.assertFalse(proclive.pid_exists(5))  # truly absent
        finally:
            sys.platform = saved_platform
            importlib.reload(proclive)


if __name__ == "__main__":
    unittest.main()
