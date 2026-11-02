"""Connection reuse with real local sockets, without model/network services."""

from __future__ import annotations

import json
import shutil
import socket
import ssl
import subprocess
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests


@pytest.fixture(autouse=True)
def clean_connections():
    from gaworld.llm.http_transport import close_connections

    yield
    close_connections()


@contextmanager
def running_endpoint(tls_context=None):
    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self):
            super().__init__(("127.0.0.1", 0), Handler)
            self.accepted = 0
            self.seen = []
            self.lock = threading.Lock()

        def get_request(self):
            conn, addr = super().get_request()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.lock:
                self.accepted += 1
            return conn, addr

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle(self):
            # An intentionally abandoned stream may reset a keepalive socket.
            with suppress(ConnectionResetError, BrokenPipeError):
                super().handle()

        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            with self.server.lock:
                self.server.seen.append(
                    {
                        "headers": dict(self.headers),
                        "body": json.loads(body or b"{}"),
                        "peer": self.client_address,
                    }
                )
            if self.path.endswith("/chat/completions"):
                payload = b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
            elif self.path.endswith("/ollama"):
                payload = b'{"response":"OK","done":true}\n'
            else:
                payload = b"first\nsecond\n" if self.path == "/stream" else b'{"answer":"OK"}'
            self.send_response(429 if self.path == "/limited" else 200)
            self.send_header("Content-Type", "application/json")
            if self.path.startswith("/chunked/"):
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(len(payload)))
            self.send_header("Set-Cookie", "private=value; Path=/")
            self.end_headers()
            if self.path.startswith("/chunked/"):
                self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
            else:
                self.wfile.write(payload)

    server = Server()
    if tls_context is not None:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def endpoint():
    with running_endpoint() as running:
        yield running


@pytest.fixture
def tls_endpoint(tmp_path):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("openssl is needed to generate a temporary loopback certificate")
    cert = tmp_path / "server.pem"
    key = tmp_path / "server.key"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,digitalSignature,keyEncipherment",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    with running_endpoint(context) as (server, url):
        yield server, url.replace("http:", "https:"), str(cert)


def post(url, **kwargs):
    # Before implementation, exercise the current transport to show the
    # connection-reuse assertion actually detects the existing overhead.
    from gaworld.llm import providers

    return providers._post(url, timeout=2, **kwargs)


def test_consecutive_model_posts_reuse_one_tcp_connection(endpoint):
    server, url = endpoint
    for i in range(4):
        with post(url, json={"turn": i}) as response:
            assert response.json() == {"answer": "OK"}
    assert len(server.seen) == 4
    assert server.accepted == 1
    assert [item["body"] for item in server.seen] == [{"turn": i} for i in range(4)]


def test_cookie_auth_and_extra_headers_do_not_survive_a_request(endpoint):
    server, url = endpoint
    post(url, json={}, headers={"Authorization": "Bearer user-one", "X-Private": "first"}).close()
    post(url, json={}, headers={"Authorization": "Bearer user-two"}).close()
    post(url, json={}).close()
    assert server.seen[0]["headers"]["Authorization"] == "Bearer user-one"
    assert server.seen[1]["headers"]["Authorization"] == "Bearer user-two"
    assert "Authorization" not in server.seen[2]["headers"]
    assert "X-Private" not in server.seen[1]["headers"]
    assert all("Cookie" not in row["headers"] for row in server.seen)
    assert server.accepted == 1


def test_explicit_cookie_only_applies_to_that_request(endpoint):
    server, url = endpoint
    post(url, json={}, cookies={"chosen": "once"}).close()
    post(url, json={}).close()
    assert server.seen[0]["headers"]["Cookie"] == "chosen=once"
    assert "Cookie" not in server.seen[1]["headers"]


def test_workers_have_separate_reusable_connections(endpoint):
    server, url = endpoint
    barrier = threading.Barrier(3)

    def work(worker):
        barrier.wait(timeout=3)
        for _ in range(2):
            post(url, json={"worker": worker}).close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(work, range(3)))
    assert len(server.seen) == 6
    assert server.accepted == 3
    peers = {}
    for row in server.seen:
        peers.setdefault(row["body"]["worker"], set()).add(row["peer"])
    assert all(len(values) == 1 for values in peers.values())


def test_stream_consumption_then_another_request_reuses_connection(endpoint):
    server, url = endpoint
    with post(url + "/stream", json={}, stream=True) as response:
        assert list(response.iter_lines()) == [b"first", b"second"]
    post(url, json={}).close()
    assert server.accepted == 1


def test_closing_unread_stream_does_not_block_future_requests(endpoint):
    server, url = endpoint
    response = post(url + "/stream", json={}, stream=True)
    response.close()
    assert post(url, json={}).json() == {"answer": "OK"}
    assert len(server.seen) == 2


def test_transport_does_not_retry_rate_limited_posts(endpoint):
    server, url = endpoint
    with post(url + "/limited", json={}) as response:
        with pytest.raises(requests.HTTPError):
            response.raise_for_status()
    assert len(server.seen) == 1


def test_cleanup_closes_idle_connections_and_next_request_rebuilds_pool(endpoint):
    from gaworld.llm.http_transport import close_connections

    server, url = endpoint
    post(url, json={}).close()
    close_connections()
    post(url, json={}).close()
    assert server.accepted == 2


def test_pool_is_not_reused_after_process_identity_changes(monkeypatch):
    from gaworld.llm import http_transport

    original = http_transport._thread_pool()
    with monkeypatch.context() as child:
        child.setattr(http_transport.os, "getpid", lambda: original.pid + 1)
        replacement = http_transport._thread_pool()
        assert replacement is not original
        replacement.close()
    original.close()


def test_tls_policy_change_does_not_reuse_a_pool_from_another_policy(endpoint):
    server, url = endpoint
    # Even though this fixture is HTTP, the transport must isolate policies
    # itself to support older requests versions whose pools do not key TLS
    # settings. Otherwise a later verified HTTPS request could inherit state
    # from an earlier unverified request to the same origin.
    post(url, json={}, verify=True).close()
    post(url, json={}, verify=False).close()
    post(url, json={}, verify=True).close()
    assert server.accepted == 3


def test_effective_environment_ca_settings_are_rechecked_per_request(endpoint, monkeypatch):
    server, url = endpoint
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "first-test-ca.pem")
    post(url, json={}).close()
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "second-test-ca.pem")
    post(url, json={}).close()
    assert server.accepted == 2


def test_verified_tls_connections_are_reused_and_untrusted_cert_is_rejected(tls_endpoint, monkeypatch):
    server, url, ca = tls_endpoint
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    for _ in range(2):
        with post(url, json={}, verify=ca) as response:
            assert response.json() == {"answer": "OK"}
    assert server.accepted == 1
    with pytest.raises(requests.exceptions.SSLError):
        post(url, json={}, verify=True)
    assert len(server.seen) == 2


def test_worker_pool_owners_are_released_when_threads_finish(endpoint):
    from gaworld.llm import http_transport

    _, url = endpoint

    def work(_):
        post(url, json={}).close()
        return weakref.ref(http_transport._thread_pool())

    with ThreadPoolExecutor(max_workers=2) as pool:
        owners = list(pool.map(work, range(4)))
    assert all(owner() is None for owner in owners)


def test_after_fork_hook_discards_inherited_thread_and_registry_state():
    from gaworld.llm import http_transport

    old_pool = http_transport._thread_pool()
    try:
        http_transport._after_fork()
        assert http_transport._thread_pool() is not old_pool
    finally:
        old_pool.close()


def test_proxy_auth_changes_do_not_accumulate_old_proxy_managers(endpoint):
    from gaworld.llm import http_transport

    server, proxy = endpoint
    for index in range(12):
        address = proxy.replace("http://", f"http://fixture-{index}:password@")
        with post("http://fixture-model.invalid/v1", json={}, proxies={"http": address}) as response:
            assert response.json() == {"answer": "OK"}
        assert len(http_transport._thread_pool().adapter.proxy_manager) == 1
    assert len(server.seen) == 12
    assert len({row["headers"]["Proxy-Authorization"] for row in server.seen}) == 12


def test_proxy_environment_change_replaces_the_previous_adapter(endpoint, monkeypatch):
    from gaworld.llm import http_transport

    server, proxy = endpoint
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("http_proxy", proxy.replace("http://", "http://fixture-one:password@"))
    post("http://fixture-model.invalid/v1", json={}).close()
    first = http_transport._thread_pool().adapter
    monkeypatch.setenv("http_proxy", proxy.replace("http://", "http://fixture-two:password@"))
    post("http://fixture-model.invalid/v1", json={}).close()
    assert http_transport._thread_pool().adapter is not first
    assert len(server.seen) == 2


@pytest.mark.parametrize("kind", ["openai", "ollama"])
def test_actual_provider_can_stop_at_done_in_a_chunked_stream(endpoint, kind):
    from gaworld.llm import providers

    server, url = endpoint
    if kind == "openai":
        provider = providers.OpenAIProvider(
            url + "/chunked",
            "fixture-model",
            api_key="fixture-key",
            stream=True,
            attempts=1,
        )
    else:
        provider = providers.OllamaProvider(url + "/chunked/ollama", "fixture-model", attempts=1)
    for _ in range(3):
        assert provider.call("fixture prompt") == "OK"
    # Done-triggered early close is allowed to discard a connection; don't
    # change parsing/latency just to force reuse of an unfinished HTTP body.
    assert len(server.seen) == 3
