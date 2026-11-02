"""Frozen request pacing and interruptible waiting; no hidden retry or fallback."""

from __future__ import annotations

import time

POLICY = {"min_interval_seconds": 10, "automatic_retries": 0, "on_429": "pause_manual_resume"}


def now():
    return time.time()


def wait_for_request(db, identifier, interval, check, *, clock=None, sleep=None):
    clock, sleep = clock or now, sleep or time.sleep
    record = db.get(identifier)
    until = (record.get("last_request_at") or 0) + interval
    try:
        if until > clock():
            db.update(identifier, lambda r: r.update(waiting={"kind": "request_spacing", "until": until}))
        while until > clock():
            check()
            remaining = until - clock()
            if remaining <= 0:
                break
            sleep(min(0.2, remaining))
        check()
        db.update(identifier, lambda r: r.update(last_request_at=clock()))
    finally:
        db.update(identifier, lambda r: r.update(waiting=None))
