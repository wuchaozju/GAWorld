"""Opt-in research ledger shared by all world subprocesses of one attempt.

The environment is set only by the research backend. Ordinary simulations
keep their original retry behavior and do not create a ledger.
"""

from __future__ import annotations

import contextlib
import contextvars
import email.utils
import functools
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_PROVIDER: contextvars.ContextVar[str] = contextvars.ContextVar("research_provider", default="")
_LEDGER_PATH: contextvars.ContextVar[str] = contextvars.ContextVar("research_ledger_path", default="")


def retry_delay(exc: BaseException, *, now: float | None = None) -> float:
    response = getattr(exc, "response", None)
    raw = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        seconds = float(raw)
        if seconds >= 0 and seconds < float("inf"):
            return seconds
    except (TypeError, ValueError):
        pass
    try:
        stamp = email.utils.parsedate_to_datetime(raw).timestamp()
        return max(0.0, stamp - (time.time() if now is None else now))
    except (TypeError, ValueError, OverflowError):
        return 30.0


class RunLedger:
    def __init__(self, path: str, *, failure_budget: int = 3, wait_budget: float = 120.0) -> None:
        self.path = path
        self.failure_budget = failure_budget
        self.wait_budget = wait_budget
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO state VALUES (1, '{}')")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _change(self, fn: Any) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            data = json.loads(conn.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            fn(data)
            conn.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(data),))
        return data

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            data = json.loads(conn.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
        defaults: dict[str, Any] = {
            "available": True,
            "requests": 0,
            "call_count": 0,
            "failure_count": 0,
            "requests_failed": 0,
            "requests_fell_back": 0,
            "invalid_briefs": 0,
            "valid_briefs": 0,
            "brief_parse_failures": 0,
            "brief_repair_attempts": 0,
            "recovered_briefs": 0,
            "brief_tracking_version": 0,
            "total_latency_ms": 0,
            "http_attempts": 0,
            "http_failures": 0,
            "cooldown_seconds": 0,
            "providers": {},
            "aborted": False,
            "reason": "",
        }
        return {**defaults, **data}

    def check(self) -> None:
        state = self.snapshot()
        if state["aborted"]:
            raise RuntimeError(state["reason"])

    def abort(self, reason: str) -> None:
        self._change(lambda data: data.update(aborted=True, reason=reason))

    def cooldown(self, name: str, seconds: float) -> None:
        def change(data: dict[str, Any]) -> None:
            entry = data.setdefault("providers", {}).setdefault(name, {})
            entry["cooldown_until"] = max(entry.get("cooldown_until", 0), time.time() + seconds)

        self._change(change)

    def wait(self, name: str) -> None:
        started = time.monotonic()
        try:
            while True:
                self.check()
                until = self.snapshot()["providers"].get(name, {}).get("cooldown_until", 0)
                remaining = until - time.time()
                if remaining <= 0:
                    return
                if (
                    remaining + time.monotonic() - started + self.snapshot()["cooldown_seconds"]
                    > self.wait_budget
                ):
                    self.abort("provider 等待预算已超出；未继续提交请求")
                    raise RuntimeError("provider 等待预算已超出；遵循 Retry-After，未继续重试")
                time.sleep(min(0.25, remaining))
        finally:
            elapsed = time.monotonic() - started
            if elapsed > 0.05:
                self._change(
                    lambda data: data.update(cooldown_seconds=data.get("cooldown_seconds", 0) + elapsed)
                )

    def provider(self, name: str, *, ok: bool, latency_ms: int) -> None:
        def change(data: dict[str, Any]) -> None:
            for key, value in (
                ("call_count", 1),
                ("failure_count", int(not ok)),
                ("total_latency_ms", latency_ms),
            ):
                data[key] = data.get(key, 0) + value
            entry = data.setdefault("providers", {}).setdefault(name, {})
            for key, value in (("calls", 1), ("failures", int(not ok)), ("total_latency_ms", latency_ms)):
                entry[key] = entry.get(key, 0) + value

        self._change(change)

    def http_attempt(self, *, ok: bool) -> None:
        def change(data: dict[str, Any]) -> None:
            data["http_attempts"] = data.get("http_attempts", 0) + 1
            data["http_failures"] = data.get("http_failures", 0) + int(not ok)

        self._change(change)

    def request(self, *, ok: bool, fell_back: bool = False) -> None:
        def change(data: dict[str, Any]) -> None:
            data["requests"] = data.get("requests", 0) + 1
            data["requests_failed"] = data.get("requests_failed", 0) + int(not ok)
            data["requests_fell_back"] = data.get("requests_fell_back", 0) + int(fell_back)
            data["consecutive_failures"] = 0 if ok else data.get("consecutive_failures", 0) + 1
            if data["consecutive_failures"] >= self.failure_budget:
                data.update(aborted=True, reason="provider 连续失败预算已耗尽；请检查限流、配额或本地连接")

        self._change(change)

    def note_error(self, name: str, exc: BaseException) -> None:
        response = getattr(exc, "response", None)
        is_quota = response is not None and response.status_code == 429 and "2062" in response.text
        category = (
            "token_plan_2062"
            if is_quota
            else "rate_limit"
            if response is not None and response.status_code == 429
            else type(exc).__name__
        )

        def change(data: dict[str, Any]) -> None:
            entry = data.setdefault("providers", {}).setdefault(name, {})
            entry["last_error"] = category
            if is_quota:
                data["quota_failures"] = data.get("quota_failures", 0) + 1
                if data["quota_failures"] >= self.failure_budget:
                    data.update(aborted=True, reason="Token Plan 2062 失败预算已耗尽；等待配额恢复或检查套餐")

        self._change(change)

    def invalid_brief(self) -> None:
        def change(data: dict[str, Any]) -> None:
            data["invalid_briefs"] = data.get("invalid_briefs", 0) + 1
            if data["invalid_briefs"] >= self.failure_budget and not data.get("aborted"):
                data.update(
                    aborted=True,
                    reason=(
                        f"研究简报失败预算已耗尽：{data['invalid_briefs']} 次简报在格式修复后仍不可用；"
                        "已停止后续世界，请查看简报解析日志。已生成的部分数据保留，但不能据此认定研究成功。"
                    ),
                )

        self._change(change)

    def brief_event(self, event: str, diagnostic: dict[str, Any] | None = None) -> None:
        key = {
            "valid": "valid_briefs",
            "parse_failed": "brief_parse_failures",
            "repair": "brief_repair_attempts",
            "recovered": "recovered_briefs",
        }[event]

        def change(data: dict[str, Any]) -> None:
            data[key] = data.get(key, 0) + 1
            data["brief_tracking_version"] = 1
            if diagnostic is not None:
                data["last_brief_failure"] = diagnostic

        self._change(change)


@functools.lru_cache(maxsize=32)
def _ledger(path: str) -> RunLedger:
    return RunLedger(path)


def current_ledger() -> RunLedger | None:
    path = _LEDGER_PATH.get() or os.environ.get("GAWORLD_RESEARCH_RUN_STATE", "")
    return _ledger(path) if path else None


@contextlib.contextmanager
def ledger_context(path: str) -> Iterator[None]:
    token = _LEDGER_PATH.set(path)
    try:
        yield
    finally:
        _LEDGER_PATH.reset(token)


@contextlib.contextmanager
def provider_context(name: str) -> Iterator[None]:
    token = _PROVIDER.set(name)
    try:
        yield
    finally:
        _PROVIDER.reset(token)


def research_retry(exc: BaseException, name: str, delay: float) -> bool:
    """Schedule a shared cooldown. False means no research context."""
    ledger = current_ledger()
    if ledger is None:
        return False
    name = _PROVIDER.get() or name
    ledger.note_error(name, exc)
    response = getattr(exc, "response", None)
    seconds = retry_delay(exc) if response is not None and response.status_code == 429 else delay
    ledger.cooldown(name, seconds)
    if seconds > ledger.wait_budget:
        ledger.abort("provider 等待预算已超出；服务商 Retry-After 未被缩短")
        raise RuntimeError("provider 等待预算已超出；服务商 Retry-After 未被缩短") from exc
    ledger.wait(name)
    return True


def before_attempt(name: str) -> None:
    ledger = current_ledger()
    if ledger is not None:
        ledger.wait(_PROVIDER.get() or name)


def terminal_error(exc: BaseException, name: str) -> None:
    ledger = current_ledger()
    if ledger is not None:
        name = _PROVIDER.get() or name
        ledger.note_error(name, exc)
        response = getattr(exc, "response", None)
        if response is not None and response.status_code == 429:
            ledger.cooldown(name, retry_delay(exc))
