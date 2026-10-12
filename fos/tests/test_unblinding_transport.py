# Tests for the health-wait helper and chat-failure behavior in
# scripts/unblinding_sweep.py. These checks run fully offline against a stub
# health server or fake transports, so no real model server is ever needed.
#
# The bug these tests lock in: right after the model manager answers a
# /switch request with 202, the old (dying) llama-server can still answer the
# health endpoint with 200 for a tiny moment before its socket closes. The
# sweep script used to accept that first 200 as "healthy", then fire every
# chat call into the dead window and record silent failures. wait_for_healthy
# now refuses to call the server healthy after a switch unless it has first
# seen the endpoint NOT healthy at least once (require_downtime=True).
#
# What each test checks:
#   test_wait_for_healthy_polls_until_a_loading_server_turns_healthy
#       - A server that answers 503 twice and then 200 is waited on; the wait
#         must poll more than once and finish healthy.
#   test_wait_for_healthy_gives_up_when_the_server_never_recovers
#       - A server that never returns 200 makes the wait return False quickly.
#   test_wait_after_switch_ignores_health_until_a_real_outage_is_seen
#       - A transport that always answers 200 is NOT accepted after a switch
#         (it is treated as the dying old server); the wait gives up.
#   test_wait_without_switch_accepts_the_first_healthy_reply
#       - Without a switch pending, the first 200 counts immediately.
#   test_wait_after_switch_gives_up_when_the_old_server_dies_for_good
#       - One stale 200 followed by refusals forever still gives up.
#   test_wait_after_switch_accepts_health_once_a_real_outage_happened
#       - Stale 200, then a refusal (real outage), then 200 -> healthy.
#   test_chat_fn_returns_empty_and_warns_when_the_port_is_closed
#       - Chat calls against a closed port return "" with one stderr warning.
#   test_chat_fn_returns_empty_and_warns_when_the_server_answers_http_503
#       - The same "" + warning behavior for an HTTP 503 error reply.

import importlib.util
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "unblinding_sweep.py"


def _load_sweep_script():
    """Load scripts/unblinding_sweep.py as a fresh module each call."""
    spec = importlib.util.spec_from_file_location("unblinding_sweep", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"no loader for {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module.__name__, None)
    return module


class _FakeResponse:
    """A pretend HTTP reply; the only thing read is the status code."""

    def __init__(self, status: int) -> None:
        self.status = status


def _sequence_transport(*steps):
    """Build a fake transport that plays each step once, then the last forever.

    A step is an int (the HTTP status to answer with) or an exception to
    raise. The fake transport records how many times it was called.
    """
    counts = {"calls": 0}

    def transport(_url: str) -> _FakeResponse:
        index = min(counts["calls"], len(steps) - 1)
        counts["calls"] += 1
        step = steps[index]
        if isinstance(step, Exception):
            raise step
        return _FakeResponse(step)

    return transport, counts


@pytest.fixture
def health_server():
    """Start stub HTTP servers; each test picks the status run to serve.

    Returns a start(statuses) callable that boots one server on a free local
    port and hands back its base url and the handler class (which counts hits
    on the class attribute "hits").
    """
    running = []

    def start(statuses):
        def do_GET(self):
            cls = type(self)
            cls.hits += 1
            index = min(cls.hits - 1, len(cls.statuses) - 1)
            self.send_response(cls.statuses[index])
            self.send_header("Content-Length", "0")
            self.end_headers()

        handler = type(
            "StubHealthHandler",
            (BaseHTTPRequestHandler,),
            {
                "statuses": tuple(statuses),
                "hits": 0,
                "do_GET": do_GET,
                "log_message": lambda *args: None,
            },
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        running.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}", handler

    yield start

    for httpd in running:
        httpd.shutdown()
        httpd.server_close()


# The helper under test is fetched through the freshly loaded module so that
# the very first run (before the helper exists) fails loudly here instead of
# half-way through a test.
_sweep_script = _load_sweep_script()
wait_for_healthy = _sweep_script.wait_for_healthy  # ImportError while RED


class TestWaitForHealthy:
    def test_wait_for_healthy_polls_until_a_loading_server_turns_healthy(
        self, health_server
    ):
        base_url, handler = health_server((503, 503, 200))
        healthy = wait_for_healthy(
            f"{base_url}/health",
            timeout_s=10.0,
            poll_s=0.01,
            transport=urllib.request.urlopen,
        )
        assert healthy is True
        assert handler.hits >= 2

    def test_wait_for_healthy_gives_up_when_the_server_never_recovers(
        self, health_server
    ):
        base_url, _handler = health_server((503,))
        started = time.monotonic()
        healthy = wait_for_healthy(
            f"{base_url}/health",
            timeout_s=0.1,
            poll_s=0.01,
            transport=urllib.request.urlopen,
        )
        assert healthy is False
        assert time.monotonic() - started < 5.0

    def test_wait_after_switch_ignores_health_until_a_real_outage_is_seen(self):
        transport, _counts = _sequence_transport(200, 200)
        healthy = wait_for_healthy(
            "http://stale.example/health",
            timeout_s=0.2,
            poll_s=0.01,
            transport=transport,
            require_downtime=True,
        )
        assert healthy is False

    def test_wait_without_switch_accepts_the_first_healthy_reply(self):
        transport, counts = _sequence_transport(200)
        healthy = wait_for_healthy(
            "http://fresh.example/health",
            timeout_s=0.2,
            poll_s=0.01,
            transport=transport,
        )
        assert healthy is True
        assert counts["calls"] == 1

    def test_wait_after_switch_gives_up_when_the_old_server_dies_for_good(self):
        transport, _counts = _sequence_transport(200, ConnectionRefusedError())
        healthy = wait_for_healthy(
            "http://dying.example/health",
            timeout_s=0.2,
            poll_s=0.01,
            transport=transport,
            require_downtime=True,
        )
        assert healthy is False

    def test_wait_after_switch_accepts_health_once_a_real_outage_happened(self):
        transport, _counts = _sequence_transport(200, ConnectionRefusedError(), 200)
        healthy = wait_for_healthy(
            "http://recovers.example/health",
            timeout_s=2.0,
            poll_s=0.01,
            transport=transport,
            require_downtime=True,
        )
        assert healthy is True


class TestBuildSweepChatFn:
    def test_chat_fn_returns_empty_and_warns_when_the_port_is_closed(self, capsys):
        chat_fn = _sweep_script.build_sweep_chat_fn(
            "http://127.0.0.1:1", "some-model", 16, 1.0
        )
        result = chat_fn([{"role": "user", "content": "hello"}], 0.5)
        assert result == ""
        warning = capsys.readouterr().err
        assert warning.count("warning:") == 1
        assert "recording this draw as failed" in warning
        assert "refused" in warning.lower() or "timed out" in warning.lower()

    def test_chat_fn_returns_empty_and_warns_when_the_server_answers_http_503(
        self, monkeypatch, capsys
    ):
        def _raise_503(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:1", 503, "Service Unavailable", {}, None
            )

        monkeypatch.setattr(urllib.request, "urlopen", _raise_503)
        chat_fn = _sweep_script.build_sweep_chat_fn(
            "http://127.0.0.1:1", "some-model", 16, 1.0
        )
        result = chat_fn([{"role": "user", "content": "hello"}], 0.5)
        assert result == ""
        warning = capsys.readouterr().err
        assert warning.count("warning:") == 1
        assert "503" in warning
        assert "recording this draw as failed" in warning
