from __future__ import annotations

import json
import os
import sys
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds


def test_todo_board_create_update_and_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "TODO_BOARD_PATH", str(tmp_path / "todo_board.json"))

    created = ds._create_todo_item(
        {
            "title": "Dashboard submit",
            "proposer": "ft",
            "details": "Make the team board shared.",
            "priority": "high",
        }
    )

    assert created["ok"] is True
    assert len(created["items"]) == 1
    item = created["items"][0]
    assert item["status"] == "pending"
    assert item["owner"] == ""

    updated = ds._update_todo_item({**item, "owner": "wsy", "status": "in_progress"})
    assert updated["items"][0]["owner"] == "wsy"
    assert updated["items"][0]["status"] == "in_progress"

    cleared = ds._save_todo_board([])
    assert cleared["items"] == []
    assert ds._todo_board_payload() == {"items": []}


def test_todo_board_rejects_missing_required_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "TODO_BOARD_PATH", str(tmp_path / "todo_board.json"))

    try:
        ds._create_todo_item({"title": "Missing proposer", "details": "Bad payload"})
    except ValueError as exc:
        assert "title, proposer and details are required" in str(exc)
    else:
        raise AssertionError("missing fields should fail")


def test_todo_form_endpoint_redirects_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(ds, "TODO_BOARD_PATH", str(tmp_path / "todo_board.json"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = urllib.parse.urlencode(
            {
                "title": "Form fallback",
                "proposer": "ft",
                "details": "HTML form should work even if JS fails.",
                "priority": "medium",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/todos/create-form",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
        saved = json.loads((tmp_path / "todo_board.json").read_text(encoding="utf-8"))
        assert saved["items"][0]["title"] == "Form fallback"
    finally:
        server.shutdown()
        server.server_close()
