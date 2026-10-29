"""F — cross-platform file lock (gaworld/kernel/filelock.py).

Linux runs the real fcntl path and must actually serialize; the win32
branch is proven by import with sys.platform patched to 'win32'.
"""

import importlib
import os
import sys
import unittest


class TestPosixFileLock(unittest.TestCase):
    def test_serializes_two_holders(self):
        from gaworld.kernel import filelock

        path = os.path.join(os.environ.get("GAWORLD_TEST_TMP", "/tmp"), "flk_test.lock")
        order = []
        with filelock.file_lock(path):
            # While held, a second non-blocking POSIX claim must fail.
            import fcntl

            with open(path, "a") as other:
                with self.assertRaises(OSError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            order.append("first")
        with filelock.file_lock(path):
            order.append("second")
        self.assertEqual(["first", "second"], order)

    def test_creates_parent_dirs(self):
        import tempfile

        from gaworld.kernel import filelock

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "dir", "x.lock")
            with filelock.file_lock(path):
                self.assertTrue(os.path.exists(path))


class TestWin32ImportPath(unittest.TestCase):
    def test_import_resolves_without_fcntl_when_win32(self):
        fake_msvcrt = __import__("types").SimpleNamespace(
            locking=lambda fd, mode, size: None,
            LK_LOCK=1,
            LK_UNLCK=2,
            LK_NBLCK=6,
        )
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from gaworld.kernel import filelock

        saved = sys.modules.get("msvcrt")
        sys.modules["msvcrt"] = fake_msvcrt
        saved_platform = sys.platform
        saved_impl = filelock._IMPL
        saved_module = sys.modules.pop("gaworld.kernel.filelock", None)
        try:
            sys.platform = "win32"
            import gaworld.kernel.filelock as fresh

            self.assertEqual("win32", fresh._IMPL)
            # The win32 import path never references fcntl.
            self.assertNotIn("fcntl", vars(fresh))
            with fresh.file_lock(os.path.join("/tmp", "flk_win32.lock")):
                pass  # context manager works through the msvcrt path
        finally:
            sys.platform = saved_platform
            if saved is not None:
                sys.modules["msvcrt"] = saved
            else:
                sys.modules.pop("msvcrt", None)
            if saved_module is not None:
                sys.modules["gaworld.kernel.filelock"] = saved_module
            importlib.reload(filelock)
            self.assertEqual(saved_impl, filelock._IMPL)


if __name__ == "__main__":
    unittest.main()
