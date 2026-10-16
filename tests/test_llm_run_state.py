import time

import pytest
import requests


def http_error(status=429, headers=None, body='{"error":{"message":"Token Plan (2062)"}}'):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = body.encode()
    return requests.HTTPError("provider failure", response=response)


def test_retry_after_seconds_date_and_invalid():
    from gaworld.llm.run_state import retry_delay

    assert retry_delay(http_error(headers={"Retry-After": "60"}), now=0) == 60
    assert retry_delay(http_error(headers={"Retry-After": "Thu, 01 Jan 1970 00:02:00 GMT"}), now=0) == 120
    assert retry_delay(http_error(headers={"Retry-After": "invalid"}), now=0) == 30


def test_shared_ledger_cooldown_and_consecutive_failure_budget(tmp_path):
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    first, second = RunLedger(path), RunLedger(path)
    first.cooldown("primary", 20)
    assert second.snapshot()["providers"]["primary"]["cooldown_until"] > time.time() + 19
    for _ in range(3):
        first.request(ok=False)
    assert second.snapshot()["aborted"]
    with pytest.raises(RuntimeError, match="失败预算"):
        second.check()


def test_oversized_server_wait_is_not_shortened_or_retried(tmp_path, monkeypatch):
    from gaworld.llm import providers

    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", str(tmp_path / "run.sqlite"))
    calls = []

    def fail():
        calls.append(1)
        raise http_error(headers={"Retry-After": "900"})

    with pytest.raises(RuntimeError, match="等待预算"):
        providers._retrying(fail, provider="test", attempts=3)
    assert len(calls) == 1
    from gaworld.llm.run_state import RunLedger

    peer = RunLedger(str(tmp_path / "run.sqlite"))
    assert peer.snapshot()["aborted"]
    assert peer.snapshot()["providers"]["test"]["cooldown_until"] > time.time() + 899


def test_provider_stats_and_invalid_brief_are_persisted(tmp_path):
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    ledger = RunLedger(path)
    ledger.provider("model", ok=False, latency_ms=30)
    ledger.provider("fallback", ok=True, latency_ms=90)
    ledger.request(ok=True, fell_back=True)
    ledger.invalid_brief()
    snapshot = RunLedger(path).snapshot()
    assert snapshot["requests"] == 1
    assert snapshot["failure_count"] == 1
    assert snapshot["requests_fell_back"] == 1
    assert snapshot["invalid_briefs"] == 1


def test_daily_research_never_silently_uses_placeholder(tmp_path, monkeypatch):
    from gaworld.sim._fastforward import _run_digest

    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", str(tmp_path / "run.sqlite"))
    monkeypatch.setenv("GAWORLD_RESEARCH_DAILY_BRIEF", "1")
    with pytest.raises(RuntimeError, match="简报"):
        _run_digest(
            {"id": 1},
            prompt="test",
            task="fast_forward_day",
            max_delta=0.1,
            brief_max_chars=240,
            max_memories=1,
            llm_fn=lambda *a, **kw: "invalid json",
        )


def test_ledger_counters_are_atomic_across_processes(tmp_path):
    import subprocess
    import sys

    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    ledger = RunLedger(path)
    script = "from gaworld.llm.run_state import RunLedger; import sys; l=RunLedger(sys.argv[1]); [l.provider('p',ok=True,latency_ms=1) for _ in range(20)]"
    procs = [subprocess.Popen([sys.executable, "-c", script, path]) for _ in range(2)]
    assert [p.wait(timeout=15) for p in procs] == [0, 0]
    assert ledger.snapshot()["call_count"] == 40


def test_wire_retry_failures_are_counted_separately_from_router_chains(tmp_path, monkeypatch):
    from gaworld.llm import providers
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    monkeypatch.setattr(RunLedger, "wait", lambda *args, **kwargs: None)
    statuses = iter((429, 200))

    def response(*args, **kwargs):
        r = requests.Response()
        r.status_code = next(statuses)
        r._content = b'{"response":"success"}'
        r._content_consumed = True
        return r

    monkeypatch.setattr(providers.requests, "post", response)
    result = providers.OllamaProvider("http://localhost:11434/api/generate", "stub").call("test")
    assert result == "success"
    snapshot = RunLedger(path).snapshot()
    assert snapshot["http_attempts"] == 2
    assert snapshot["http_failures"] == 1
