"""Frozen request pacing and interruptible waiting; no hidden retry or fallback."""

from __future__ import annotations

import time

#: ``min_interval_seconds`` spaces two requests apart; ``concurrency`` runs
#: that many cells at once, so the wall clock shrinks without sending more
#: requests per second than the spacing allows. ``automatic_retries`` is how
#: often one cell may be re-attempted after a transport failure — a failed
#: cell is marked unmeasured, never scored as a wrong answer.
POLICY = {
    "min_interval_seconds": 10,
    "concurrency": 2,
    "automatic_retries": 1,
    "retry_backoff_seconds": 2,
    "on_429": "pause_manual_resume",
}


def now():
    return time.time()


def wait_for_request(db, identifier, interval, check, *, lane=0, clock=None, sleep=None):
    """Space two requests of the same lane apart. Each lane keeps its own
    clock, so ``concurrency`` lanes really do run at the same time."""
    clock, sleep = clock or now, sleep or time.sleep
    key = "last_request_at" if lane == 0 else f"last_request_at_{lane}"
    live = db.live(identifier)
    until = (live.get(key) or 0) + interval
    try:
        if until > clock():
            db.touch(identifier, waiting={"kind": "request_spacing", "until": until})
        while until > clock():
            check()
            remaining = until - clock()
            if remaining <= 0:
                break
            sleep(min(0.2, remaining))
        check()
        db.touch(identifier, **{key: clock()})
    finally:
        db.touch(identifier, waiting=None)
