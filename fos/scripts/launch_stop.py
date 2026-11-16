#!/usr/bin/env python3
"""Operator stop control for the study's launch wrapper: graceful, then hard.

The wrapper's sweep phase runs the pending (depth x blinding) legs
concurrently. This module owns how an operator stop request is represented
and honoured so that a stop never loses finished work:

  * The FIRST SIGINT/SIGTERM (or a request() call) is a GRACEFUL stop: the
    launcher finishes the legs that are already running (their records are
    written when a leg completes, so nothing is lost), does not start any
    leg after the flag is set, records the run with state
    "stopped_gracefully" and exits cleanly.
  * A SECOND signal (or the --force flag at launch, which makes even the
    first signal hard) is a HARD stop: the shared abort signal fires, every
    in-flight leg stops at its next chat call, and leg-granular resume
    applies (TASK-1522) - a later --resume re-runs exactly the legs that
    did not finish.

The stop flag is deliberately a plain thread-safe object: the signal
handlers set it, the launcher polls it between and during phases, and the
tests drive it directly with synthetic legs (no GPU, no model server).

Function map:
    AbortSignal         - stop-now flag carrying the reason legs record.
    StopFlag            - two-level stop flag (running / graceful / hard).
    install_stop_handlers - point SIGINT/SIGTERM at a StopFlag.
    restore_stop_handlers - put the previous handlers back.
    _drive_legs         - launch leg starters concurrently, honouring the
                          flag; logs per-leg completion lines and the
                          operator stop messages.
"""

from __future__ import annotations

import signal
import threading
from typing import Any, Callable

STOP_POLL_SECONDS = 0.25

WATCHDOG_REASON = (
    "chat server lost; run aborted (check the model manager and rerun with --resume)"
)

GRACEFUL_MESSAGE = (
    "graceful stop requested — finishing current leg(s), "
    "{remaining} calls remaining in flight"
)
HARD_MESSAGE = (
    "hard stop requested (second signal or --force) — aborting in-flight "
    "legs now; finished legs are kept, unfinished legs rerun with --resume"
)
HARD_ABORT_REASON = (
    "run hard-stopped by the operator (second signal or --force); "
    "leg aborted - rerun with --resume"
)


class AbortSignal:
    """A stop-now signal shared by the health watchdog and a hard operator
    stop, carrying the reason a stopped leg should record.

    The real legs' chat wrapper checks is_set() before every call and raises
    RuntimeError(reason), so a set flag stops every in-flight leg at its
    next call boundary. The watchdog sets it with its default reason (dead
    chat server); a hard operator stop overwrites the reason first.
    """

    def __init__(self, reason: str) -> None:
        self._flag = threading.Event()
        self.reason = reason

    def is_set(self) -> bool:
        return self._flag.is_set()

    def set(self, reason: str | None = None) -> None:
        if reason is not None:
            self.reason = reason
        self._flag.set()


class StopFlag:
    """A two-level operator stop request shared between signals and launcher.

    First request() is a graceful stop; any later request escalates to a
    hard stop (and force_first makes even the first one hard, which is what
    the wrapper's --force flag does).
    """

    def __init__(self, force_first: bool = False) -> None:
        self.force_first = force_first
        self._lock = threading.Lock()
        self._graceful = False
        self._hard = False

    def request(self) -> str:
        """Record one stop request; return the resulting level."""
        with self._lock:
            if self.force_first or self._graceful or self._hard:
                self._hard = True
                return "hard"
            self._graceful = True
            return "graceful"

    def level(self) -> str:
        """running, graceful or hard."""
        with self._lock:
            if self._hard:
                return "hard"
            if self._graceful:
                return "graceful"
            return "running"


def install_stop_handlers(stop: StopFlag) -> dict[int, Any]:
    """Point SIGINT and SIGTERM at the shared stop flag.

    Call only from the main thread (signal.signal requirement). The launcher
    keeps polling the flag, so handlers stay minimal (just request()).
    Returns the previous handlers so restore_stop_handlers can put them back.
    """
    previous: dict[int, Any] = {}

    def _handler(signum: int, _frame: Any) -> None:
        stop.request()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _handler)
    return previous


def restore_stop_handlers(previous: dict[int, Any]) -> None:
    """Restore the signal handlers install_stop_handlers replaced."""
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _drive_legs(
    pending: list[dict[str, Any]],
    stop: StopFlag,
    abort: AbortSignal,
    log: Callable[[str], None],
    start_leg: Callable[[dict[str, Any]], threading.Thread],
    *,
    planned_calls: int,
    calls_done: Callable[[], int],
    poll_seconds: float = STOP_POLL_SECONDS,
) -> str:
    """Launch the pending legs and wait for them, honouring the stop flag.

    Legs are started one at a time and only while the flag is still running,
    so a stop that lands before (or between) launches leaves the remaining
    legs unstarted - they stay for a later --resume. Once legs are running:

      * a graceful stop is announced once ("finishing current leg(s), N
        calls remaining in flight") and the running legs are allowed to
        finish, so nothing is lost;
      * a hard stop raises the shared abort signal (which is how chat_fn
        stops the real legs; synthetic legs in the offline tests observe the
        same signal) and the in-flight legs stop at their next call.

    Every time a leg finishes, a "legs completed X/Y, legs remaining Z"
    line is logged so the operator knows what a stop would cost right now.

    Returns the final stop level: "running", "graceful" or "hard".
    """
    planned_total = len(pending)
    threads: list[threading.Thread] = []
    for leg in pending:
        if stop.level() != "running":
            log(
                f"{stop.level()} stop requested before leg launch - "
                f"not starting {planned_total - len(threads)} of "
                f"{planned_total} planned leg(s) (they will run on --resume)"
            )
            break
        threads.append(start_leg(leg))
    if not threads:
        return stop.level()

    finished = [False] * len(threads)
    completed = 0
    announced_graceful = False
    hard_raised = False

    def _announce_and_count() -> None:
        """Print the operator messages once per level, count finished legs."""
        nonlocal announced_graceful, hard_raised, completed
        level = stop.level()
        if level == "graceful" and not announced_graceful:
            announced_graceful = True
            remaining = max(0, planned_calls - calls_done())
            log(GRACEFUL_MESSAGE.format(remaining=remaining))
        elif level == "hard" and not hard_raised:
            hard_raised = True
            if not abort.is_set():  # the watchdog may already have tripped it
                abort.set(HARD_ABORT_REASON)
            log(HARD_MESSAGE)
        for index, thread in enumerate(threads):
            if not finished[index] and not thread.is_alive():
                finished[index] = True
                completed += 1
                log(
                    f"legs completed {completed}/{planned_total}, "
                    f"legs remaining {planned_total - completed}"
                )

    while any(thread.is_alive() for thread in threads):
        _announce_and_count()
        for thread in threads:
            thread.join(timeout=poll_seconds)
    # A stop requested in the last instant still gets announced before return.
    _announce_and_count()
    return stop.level()
