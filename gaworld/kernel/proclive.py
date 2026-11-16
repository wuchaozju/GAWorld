"""Cross-platform process liveness and identity, no third-party deps.

Three distinguishable outcomes everywhere a pid is inspected:

- the pid does not exist (``pid_exists`` is False);
- the pid exists but cannot be inspected (``process_command`` returns None
  while ``pid_exists`` is True — e.g. a permission boundary; treated as
  "alive, unknown image");
- the pid exists and its image name is readable.

POSIX keeps the exact current behaviour (``os.kill(pid, 0)`` and
``ps -p <pid> -o command=``). Windows uses ``ctypes`` against the Win32
process API: ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` for
existence and ``QueryFullProcessImageNameW`` for the image name, so pid
recycling is caught by matching the image name.
"""

from __future__ import annotations

import os
import subprocess
import sys

_IMPL = "posix" if sys.platform != "win32" else "win32"

if _IMPL == "win32":
    import ctypes
    import ctypes.wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_ACCESS_DENIED = 5
    _ERROR_INVALID_PARAMETER = 87


def pid_exists(pid: int) -> bool:
    """Whether *pid* names a live process. ``False`` means absent."""
    pid = int(pid)
    if pid <= 0:
        return False
    if _IMPL == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        err = ctypes.windll.kernel32.GetLastError()
        # ERROR_ACCESS_DENIED: exists, but we may not even query it → alive.
        return err == _ERROR_ACCESS_DENIED
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command(pid: int) -> str | None:
    """The process's command/image line, or None when unreadable/absent."""
    pid = int(pid)
    if pid <= 0:
        return None
    if _IMPL == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            size = ctypes.wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    # /proc is exact and race-free where available; ps is the fallback (and
    # the only source on systems without procfs) but can transiently fail.
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read()
        if raw:
            return raw.replace(b"\x00", b" ").decode("utf-8", "replace").rstrip()
    except (OSError, ValueError):
        pass
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return result.stdout.rstrip("\n") if result.returncode == 0 else None


def command_matches(pid: int, token: str) -> bool:
    """Whether *pid* exists and its command line contains *token."""
    command = process_command(pid)
    return command is not None and token in command


def terminate(pid: int, sig: int | None = None) -> None:
    """Ask *pid* to terminate. POSIX sends *sig* (default SIGTERM); Windows
    uses ``TerminateProcess`` with a nonzero exit code."""
    pid = int(pid)
    if _IMPL == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(
            ctypes.wintypes.DWORD(0x0001), False, ctypes.wintypes.DWORD(pid)
        )
        if handle:
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, ctypes.wintypes.UINT(1))
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return
    import signal as _signal

    os.kill(pid, sig if sig is not None else _signal.SIGTERM)
