"""Hard request admission uses the shared ledger, before any network send."""

from concurrent.futures import ThreadPoolExecutor

import pytest
import requests


def test_budget_survives_reopen_and_stops_before_an_extra_attempt(tmp_path):
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    ledger = RunLedger(path)
    ledger.configure_http_budget(1)
    ledger.reserve_http_attempt()
    peer = RunLedger(path)
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        peer.reserve_http_attempt()
    state = ledger.snapshot()
    assert state["http_budget"] == 1
    assert state["http_reserved"] == 1
    assert state["http_attempts"] == 0  # reservation is not a completed request
    assert state["aborted"] and state["reason_code"] == "budget_exhausted"
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        ledger.check()


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2", None])
def test_hard_budget_must_be_an_explicit_positive_integer(tmp_path, limit):
    from gaworld.llm.run_state import RunLedger

    with pytest.raises(ValueError):
        RunLedger(str(tmp_path / "run.sqlite")).configure_http_budget(limit)


def test_configured_budget_cannot_be_raised_by_another_worker(tmp_path):
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    ledger = RunLedger(path)
    ledger.configure_http_budget(3)
    RunLedger(path).configure_http_budget(3)  # idempotent initialization
    with pytest.raises(ValueError, match="预算"):
        RunLedger(path).configure_http_budget(4)
    assert ledger.snapshot()["http_budget"] == 3


def test_concurrent_workers_reserve_exactly_the_approved_count(tmp_path):
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    RunLedger(path).configure_http_budget(3)

    def reserve(_):
        try:
            RunLedger(path).reserve_http_attempt()
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(24))) == 3
    assert RunLedger(path).snapshot()["http_reserved"] == 3


def test_reservation_is_atomic_across_processes(tmp_path):
    import subprocess
    import sys

    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    RunLedger(path).configure_http_budget(3)
    script = """
from gaworld.llm.run_state import RunLedger
import sys
ledger = RunLedger(sys.argv[1])
for _ in range(10):
    try:
        ledger.reserve_http_attempt()
        print('sent')
    except RuntimeError:
        pass
"""
    workers = [
        subprocess.Popen([sys.executable, "-c", script, path], stdout=subprocess.PIPE) for _ in range(3)
    ]
    output = [worker.communicate(timeout=15)[0] for worker in workers]
    assert [worker.returncode for worker in workers] == [0, 0, 0]
    assert sum(value.count(b"sent") for value in output) == 3


def test_retries_consume_http_budget_and_no_fallback_is_called(tmp_path, monkeypatch):
    from gaworld.llm import providers
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    RunLedger(path).configure_http_budget(2)
    monkeypatch.setattr(RunLedger, "wait", lambda *args: None)
    sends = []

    def fail(*args, **kwargs):
        sends.append(1)
        raise requests.ConnectionError("fixture connection")

    monkeypatch.setattr(providers, "http_post", fail)
    primary = providers.OllamaProvider("http://fixture.invalid/api/generate", "fixture", attempts=3)

    class Fallback:
        calls = 0

        def call(self, prompt):
            self.calls += 1
            return "unexpected fallback"

    fallback = Fallback()
    router = object.__new__(providers.LLMRouter)
    router.providers = {"a": primary, "b": fallback}
    router.routing = {"default": "a", "fallback": ["b"]}
    router.config = {}
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        router.call("fixture")
    assert len(sends) == 2
    assert fallback.calls == 0
    assert RunLedger(path).snapshot()["http_attempts"] == 2


def test_unconfigured_research_ledger_keeps_existing_request_behavior(tmp_path, monkeypatch):
    from gaworld.llm import providers
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    response = requests.Response()
    response.status_code = 200
    monkeypatch.setattr(providers, "http_post", lambda *args, **kwargs: response)
    for _ in range(3):
        assert providers._post("http://fixture.invalid", timeout=1).status_code == 200
    assert RunLedger(path).snapshot()["http_budget"] is None
    assert RunLedger(path).snapshot()["http_attempts"] == 3


def test_inflight_failure_cannot_replace_budget_stop_reason(tmp_path):
    from gaworld.llm.run_state import RunLedger

    ledger = RunLedger(str(tmp_path / "run.sqlite"), failure_budget=1)
    ledger.configure_http_budget(1)
    ledger.reserve_http_attempt()
    with pytest.raises(RuntimeError):
        ledger.reserve_http_attempt()
    ledger.request(ok=False)
    state = ledger.snapshot()
    assert state["reason_code"] == "budget_exhausted"
    assert "budget_exhausted" in state["reason"]


def test_budgeted_posts_cannot_follow_unreserved_redirects(tmp_path, monkeypatch):
    from gaworld.llm import providers
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    RunLedger(path).configure_http_budget(1)
    captured = {}

    def redirect(*args, **kwargs):
        captured.update(kwargs)
        response = requests.Response()
        response.status_code = 307
        response._content = b""
        response._content_consumed = True
        return response

    monkeypatch.setattr(providers, "http_post", redirect)
    with pytest.raises(requests.HTTPError):
        providers._post("http://fixture.invalid", timeout=1, allow_redirects=True)
    assert captured["allow_redirects"] is False
    assert RunLedger(path).snapshot()["http_attempts"] == 1
    assert RunLedger(path).snapshot()["http_failures"] == 1


def test_authorization_scheme_retries_cannot_bypass_cap(tmp_path, monkeypatch):
    from gaworld.llm import providers
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    RunLedger(path).configure_http_budget(1)
    submitted = []

    def reject(*args, **kwargs):
        submitted.append(kwargs)
        response = requests.Response()
        response.status_code = 401
        response._content = b'{"error":"invalid_auth"}'
        return response

    monkeypatch.setattr(providers, "http_post", reject)
    provider = providers.AnthropicProvider(
        "http://fixture.invalid", "fixture", api_key="fixture-key", authorization_retry_schemes=["raw"]
    )
    with pytest.raises(RuntimeError, match="budget_exhausted"):
        provider.call("fixture")
    assert len(submitted) == 1
