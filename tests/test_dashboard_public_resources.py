"""A fresh public deployment must work before its first simulation run."""

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gaworld.apps import dashboard_server as ds


@pytest.fixture
def dashboard(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(ds, "_effective_config", lambda: {
        "visualization": {"output_dir": "output/cities/test/visualization"},
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_empty_trace_is_json_not_missing_static_file(dashboard):
    with urllib.request.urlopen(dashboard + "/api/trace/data", timeout=5) as response:
        assert response.headers.get_content_type() == "application/json"
        assert json.load(response) == {"trace": {}, "latest": {}}


def test_trace_uses_current_city_output(dashboard, tmp_path):
    out = tmp_path / "output/cities/test/visualization"
    out.mkdir(parents=True)
    trace = {"meta": {"generated_at": "test-run"}, "frames": [{"index": 0}]}
    latest = {"frame": {"index": 1, "agents": []}}
    (out / "simulation_trace.json").write_text(json.dumps(trace), encoding="utf-8")
    (out / "latest_frame.json").write_text(json.dumps(latest), encoding="utf-8")
    with urllib.request.urlopen(dashboard + "/api/trace/data", timeout=5) as response:
        assert json.load(response) == {"trace": trace, "latest": latest}
    assert ds._latest_trace_meta() == {"trace_meta": trace["meta"], "latest": latest}


def test_avatar_does_not_require_a_run(dashboard, monkeypatch):
    monkeypatch.setattr(ds, "_agent_state", lambda agent_id: {"id": int(agent_id), "name": "Test"})
    with urllib.request.urlopen(dashboard + "/api/agents/1/avatar", timeout=5) as response:
        assert response.headers.get_content_type() == "image/svg+xml"
        assert b"<svg" in response.read()


def test_missing_avatar_agent_returns_json_404(dashboard, monkeypatch):
    monkeypatch.setattr(ds, "_agent_state", lambda agent_id: None)
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(dashboard + "/api/agents/999/avatar", timeout=5)
    assert error.value.code == 404
    assert json.load(error.value) == {"error": "Agent not found"}


def test_dashboard_css_assets_exist():
    root = Path(__file__).resolve().parents[1]
    css = (root / "site/dashboard/styles.css").read_text(encoding="utf-8")
    for path in re.findall(r'url\("(/[^\"]+)"\)', css):
        assert (root / path.lstrip("/")).is_file(), path


def test_shared_tokens_cover_dashboard_and_console():
    root = Path(__file__).resolve().parents[1]
    tokens = (root / "site/tokens.css").read_text(encoding="utf-8")
    for name in ("dashboard/styles.css", "dashboard/studio.css", "console/console.css"):
        css = (root / "site" / name).read_text(encoding="utf-8")
        defined = set(re.findall(r"(--[a-z-]+)\s*:", tokens + css))
        assert set(re.findall(r"var\((--[a-z-]+)", css)) <= defined


def test_dashboard_resolves_the_selected_city_before_final_env_override(monkeypatch):
    monkeypatch.setattr(ds, "_dashboard_config", lambda: {"city": "wuzhen"})
    monkeypatch.delenv("GAWORLD_CONFIG_OVERRIDES", raising=False)
    cfg = ds._effective_config()
    assert cfg["visualization"]["output_dir"] == "output/cities/wuzhen/visualization"
    assert cfg["memory_dir"] == "output/cities/wuzhen/memory"
    monkeypatch.setenv("GAWORLD_CONFIG_OVERRIDES", json.dumps({
        "visualization": {"output_dir": "output/private-smoke/visualization"},
    }))
    assert ds._effective_config()["visualization"]["output_dir"] == "output/private-smoke/visualization"
