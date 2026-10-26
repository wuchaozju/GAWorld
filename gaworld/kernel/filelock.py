"""Cross-platform advisory file lock.

POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` on the first
byte of the lock file. Neither platform gets a no-op: on Windows the lock
region is a real mandatory byte-range lock, so two processes that both call
``file_lock`` on the same path serialize exactly like they do on Linux.

Lock files are the ``*.lock`` sidecars the callers already used (the JSON
payload keeps its own path); they are opened in append mode and never
truncated, so an existing lock is never broken by a reopen.
"""

from __future__ import annotations

import contextlib
import os
import sys

_IMPL = "posix" if sys.platform != "win32" else "win32"

if _IMPL == "win32":
    import msvcrt

    _LOCK_REGION_SIZE = 1
else:
    import fcntl


@contextlib.contextmanager
def file_lock(path: str):
    """Hold an exclusive advisory lock on *path* for the ``with`` body."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as lock:
        if _IMPL == "win32":
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, _LOCK_REGION_SIZE)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, _LOCK_REGION_SIZE)
        else:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
