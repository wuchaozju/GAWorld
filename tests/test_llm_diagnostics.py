"""Fault cards contain actionable categories, never raw upstream data."""

import json
import socket
import subprocess

import pytest
import requests


def http_error(status, body="", message="private-key-and-request"):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode()
    return requests.HTTPError(message, response=response)


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (http_error(401), "authentication_failed", False),
        (http_error(403), "authentication_failed", False),
        (http_error(404), "model_not_found", False),
        (http_error(429, '{"error":{"code":"rate_limit_exceeded"}}'), "rate_limited", True),
        (http_error(429, '{"error":{"code":"insufficient_quota"}}'), "quota_exhausted", False),
        (http_error(429, '{"error":{"message":"Token Plan (2062)"}}'), "quota_exhausted", False),
        (http_error(503), "upstream_unavailable", True),
        (requests.Timeout("secret request"), "request_timeout", True),
        (requests.ConnectionError("private URL"), "connection_failed", True),
        (socket.gaierror(-2, "secret hostname"), "dns_failed", True),
        (ValueError("没有拿到密钥 OPENAI_API_KEY"), "configuration_missing", False),
        (ValueError("Provider 'private' not found in config."), "configuration_missing", False),
        (json.JSONDecodeError("secret data", "private body", 0), "output_format", False),
        (subprocess.CalledProcessError(1, ["private-token"]), "process_exit", False),
        (subprocess.CalledProcessError(-9, ["private-token"]), "process_signal", False),
        (RuntimeError("未识别的 secret message"), "task_failed", False),
    ],
)
def test_fault_category_does_not_echo_exception_or_body(error, code, retryable):
    from gaworld.llm.diagnostics import classify_error

    result = classify_error(error, stage="simulation", provider="fixture", model="fixture-model", attempts=3)
    assert result["code"] == code
    assert result["retryable"] is retryable
    assert result["stage"] == "simulation"
    assert result["attempts"] == 3
    assert result["message"] and result["next_action"]
    rendered = json.dumps(result)
    assert "secret" not in rendered and "private" not in rendered
    if code == "process_signal":
        assert result["signal"] == 9
        assert "内存不足" not in result["message"]


def test_cause_chain_keeps_original_http_category_and_safe_context():
    from gaworld.llm.diagnostics import classify_error

    inner = http_error(401)
    outer = ValueError("模型调用失败：private response")
    outer.__cause__ = inner
    result = classify_error(outer, provider="sk-top-secret-value", model="fixture", secrets=["fixture"])
    assert result["code"] == "authentication_failed"
    assert result["http_status"] == 401
    assert "sk-top-secret-value" not in json.dumps(result)
    assert result["model"] == "[REDACTED]"


@pytest.mark.parametrize("code", ["service_restarted", "user_stopped", "budget_exhausted"])
def test_explicit_terminal_reason_wins_over_wrapped_error(code):
    from gaworld.llm.diagnostics import classify_error

    result = classify_error(RuntimeError("private diagnostic"), reason_code=code)
    assert result["code"] == code
    assert result["retryable"] is False


def test_known_quota_is_not_retried_but_ordinary_rate_limit_is(monkeypatch):
    from gaworld.llm import providers

    monkeypatch.setattr(providers.time, "sleep", lambda *args: None)
    calls = []

    def quota():
        calls.append(1)
        raise http_error(429, '{"error":{"code":"insufficient_quota"}}')

    with pytest.raises(requests.HTTPError):
        providers._retrying(quota, attempts=3)
    assert len(calls) == 1
    calls.clear()

    def limited():
        calls.append(1)
        raise http_error(429, '{"error":{"code":"rate_limit_exceeded"}}')

    with pytest.raises(requests.HTTPError):
        providers._retrying(limited, attempts=3)
    assert len(calls) == 3


def test_research_quota_halts_other_worlds_without_retry(tmp_path, monkeypatch):
    from gaworld.llm import providers
    from gaworld.llm.run_state import RunLedger

    path = str(tmp_path / "run.sqlite")
    monkeypatch.setenv("GAWORLD_RESEARCH_RUN_STATE", path)
    calls = []

    def quota():
        calls.append(1)
        raise http_error(429, '{"error":{"code":"insufficient_quota"}}')

    with pytest.raises(requests.HTTPError):
        providers._retrying(quota, attempts=3)
    assert len(calls) == 1
    snapshot = RunLedger(path).snapshot()
    assert snapshot["reason_code"] == "quota_exhausted"
    assert snapshot["providers"][""]["last_error"] == "quota_exhausted"
    assert snapshot["providers"][""]["diagnostic"]["attempts"] == 1
    with pytest.raises(RuntimeError) as halted:
        RunLedger(path).check()
    from gaworld.llm.diagnostics import classify_error

    assert classify_error(halted.value)["code"] == "quota_exhausted"


def test_total_model_wait_timeout_is_not_safe_for_automatic_retry():
    from gaworld.llm.call_scope import ModelWaitTimeout
    from gaworld.llm.diagnostics import classify_error

    result = classify_error(ModelWaitTimeout("private request body"))
    assert result["code"] == "request_timeout"
    assert result["retryable"] is False


def test_temporary_timeout_and_configuration_are_recognized_through_wrappers():
    from gaworld.llm.diagnostics import classify_error

    cause = requests.ConnectionError("urllib3: NameResolutionError: private hostname")
    wrapper = RuntimeError("模型调用失败：private wrapper")
    wrapper.__cause__ = cause
    assert classify_error(wrapper)["code"] == "dns_failed"


def test_fault_classification_never_reads_a_live_error_stream():
    from gaworld.llm.diagnostics import classify_error

    class LiveResponse:
        status_code = 429

        @property
        def content(self):
            raise AssertionError("Classifying a fault must not perform more network I/O")

    result = classify_error(requests.HTTPError("private", response=LiveResponse()))
    assert result["code"] == "rate_limited"
