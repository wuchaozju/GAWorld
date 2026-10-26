from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import gaworld.apps.dashboard_server as ds
from gaworld.apps import world_paths


class FakeCrowdsourcingService:
    def __init__(self):
        self.calls = []
        self.shutdown_calls = 0
        self.sessions = {
            "cw1": {
                "id": "cw1",
                "kind": "crowdsourcing",
                "task": "夜间照明方案",
                "strategy": "market",
                "agent_ids": [1, 2, 3],
                "pool_size": 3,
                "rounds": 2,
                "status": "running",
                "artifacts": [
                    {"path": "artifacts/final.md", "filename": "final.md"},
                    {"path": "../../outside.txt", "filename": "outside.txt"},
                    {"path": "/etc/passwd", "filename": "passwd"},
                    "/etc/shadow",
                ],
            }
        }

    def shutdown(self):
        self.shutdown_calls += 1

    def strategies(self):
        self.calls.append(("strategies",))
        return {
            "strategies": [{"id": "market", "name": "市场竞价", "mechanics": ["bid", "clear"]}],
            "defaults": {"strategy": "market"},
            "limits": {"max_pool_size": 200, "max_rounds": 8},
        }

    def create_crowd(
        self,
        agent_ids,
        *,
        task,
        strategy="market",
        rounds=3,
        participants_per_round=5,
        criteria="",
        prune=None,
    ):
        self.calls.append(
            (
                "create_crowd",
                list(agent_ids),
                task,
                strategy,
                rounds,
                participants_per_round,
                criteria,
                prune,
            )
        )
        if not str(task).strip():
            raise ValueError("task is required")
        if not isinstance(agent_ids, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) for item in agent_ids
        ):
            raise ValueError("agent_ids must be an array of integers")
        payload = {
            "id": "cw_new",
            "kind": "crowdsourcing",
            "task": task,
            "strategy": strategy,
            "agent_ids": list(agent_ids),
            "rounds": rounds,
            "participants_per_round": participants_per_round,
            "criteria": criteria,
            "prune": prune or {},
            "status": "queued",
            "artifacts": [],
        }
        self.sessions[payload["id"]] = payload
        return SimpleNamespace(to_dict=lambda: dict(payload))

    def list_sessions(self, *, status=""):
        self.calls.append(("list_sessions", status))
        if status == "explode":
            raise RuntimeError("unexpected service failure")
        return [
            dict(session) for session in self.sessions.values() if not status or session["status"] == status
        ]

    def health(self):
        return {"malformed_sessions": []}

    def get_session(self, session_id):
        self.calls.append(("get_session", session_id))
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return dict(self.sessions[session_id])

    def rounds(self, session_id):
        self.calls.append(("rounds", session_id))
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return [{"index": 1, "selected": [1, 2], "attempts": []}]

    def events(self, session_id, *, after=0):
        if session_id not in self.sessions:
            raise KeyError(session_id)
        self.calls.append(("events", session_id, after))
        return [{"seq": seq, "type": "bid", "content": f"event {seq}"} for seq in range(after + 1, 4)]

    def pause(self, session_id):
        return self._action("pause", session_id, "paused")

    def resume(self, session_id):
        return self._action("resume", session_id, "running")

    def cancel(self, session_id):
        return self._action("cancel", session_id, "cancelled")

    def _action(self, action, session_id, status):
        if session_id not in self.sessions:
            raise KeyError(session_id)
        self.calls.append((action, session_id))
        result = dict(self.sessions[session_id])
        result["status"] = status
        self.sessions[session_id] = result
        return result


def _request_json(base_url, path, *, method="GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def get_json(api_server, path):
    status, payload = _request_json(api_server["url"], path)
    assert status == 200
    return payload


def post_json(api_server, path, payload):
    status, response = _request_json(api_server["url"], path, method="POST", payload=payload)
    assert status == 200
    return response


@pytest.fixture(autouse=True)
def reset_crowdsourcing_service():
    reset = getattr(ds, "_reset_crowdsourcing_service_for_tests", lambda: None)
    reset()
    yield
    reset()


@pytest.fixture
def api_server(monkeypatch, tmp_path):
    fake = FakeCrowdsourcingService()
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(
        world_paths,
        "effective_config",
        lambda: {
            "crowdsourcing": {
                "sessions_dir": "runtime/sessions",
            }
        },
    )
    monkeypatch.setattr(ds, "_CROWDSOURCING_SERVICE", fake, raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    host, port = server.server_address
    fixture = {
        "url": f"http://{host}:{port}",
        "service": fake,
        "root": tmp_path,
    }
    yield fixture
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_the_strategy_catalogue_is_served(api_server):
    payload = get_json(api_server, "/api/crowdsourcing/strategies")

    assert payload["strategies"][0]["id"] == "market"
    assert payload["limits"]["max_pool_size"] == 200


def test_the_session_list_carries_the_health_report(api_server):
    payload = get_json(api_server, "/api/crowdsourcing/sessions")

    assert [item["id"] for item in payload["sessions"]] == ["cw1"]
    assert payload["health"] == {"malformed_sessions": []}


def test_one_session_is_served(api_server):
    payload = get_json(api_server, "/api/crowdsourcing/sessions/cw1")

    assert payload["task"] == "夜间照明方案"
    assert payload["strategy"] == "market"


def test_the_rounds_endpoint_serves_the_trajectory(api_server):
    payload = get_json(api_server, "/api/crowdsourcing/sessions/cw1/rounds")

    assert payload["rounds"][0]["selected"] == [1, 2]


def test_the_events_endpoint_filters_by_sequence(api_server):
    payload = get_json(api_server, "/api/crowdsourcing/sessions/cw1/events?after=1")

    assert [event["seq"] for event in payload["events"]] == [2, 3]


def test_artifact_paths_cannot_escape_the_session(api_server):
    payload = get_json(api_server, "/api/crowdsourcing/sessions/cw1")

    artifacts = payload["artifacts"]
    # The one artifact inside the session keeps its path and gets a URL.
    inside = next(item for item in artifacts if item.get("filename") == "final.md")
    assert inside["path"] == "artifacts/final.md"
    assert inside["url"].endswith("/cw1/artifacts/final.md")
    # The ones pointing outside it lose their path, and the entry that is
    # not an artifact at all is dropped.
    assert all("path" not in item for item in artifacts if item.get("filename") in {"outside.txt", "passwd"})
    assert all(isinstance(item, dict) for item in artifacts)
    assert len(artifacts) == 3


def test_a_crowd_session_can_be_started(api_server):
    payload = post_json(
        api_server,
        "/api/crowdsourcing/sessions",
        {
            "task": "设计夜间照明方案",
            "agent_ids": [1, 2, 3],
            "strategy": "market",
            "rounds": 2,
            "participants_per_round": 2,
            "criteria": "可行性",
            "prune": {"enabled": True, "keep": 2, "explore_ratio": 0.25},
        },
    )

    assert payload["id"] == "cw_new"
    assert payload["status"] == "queued"
    assert payload["strategy"] == "market"
    created = next(call for call in api_server["service"].calls if call[0] == "create_crowd")
    assert created[1] == [1, 2, 3]
    assert created[3] == "market"
    assert created[4] == 2
    assert created[7] == {"enabled": True, "keep": 2, "explore_ratio": 0.25}


def test_an_invalid_pool_is_rejected(api_server):
    status, payload = _request_json(
        api_server["url"],
        "/api/crowdsourcing/sessions",
        method="POST",
        payload={"task": "t", "agent_ids": ["not-an-id"]},
    )

    assert status == 400
    assert "error" in payload


def test_a_missing_task_is_rejected(api_server):
    status, payload = _request_json(
        api_server["url"],
        "/api/crowdsourcing/sessions",
        method="POST",
        payload={"task": "", "agent_ids": [1, 2]},
    )

    assert status == 400
    assert "error" in payload


def test_a_malformed_prune_block_is_rejected(api_server):
    status, payload = _request_json(
        api_server["url"],
        "/api/crowdsourcing/sessions",
        method="POST",
        payload={"task": "t", "agent_ids": [1, 2], "prune": "narrow"},
    )

    assert status == 400
    assert "error" in payload


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
def test_the_session_actions_are_served(api_server, action):
    payload = post_json(api_server, f"/api/crowdsourcing/sessions/cw1/{action}", {})

    assert payload["id"] == "cw1"
    assert payload["status"] in {"paused", "running", "cancelled"}


def test_an_unknown_crowd_session_is_a_bad_request(api_server):
    # A missing session is a client mistake, which the dashboard reports as
    # 400 — the same as the collaboration sessions do.
    status, payload = _request_json(api_server["url"], "/api/crowdsourcing/sessions/cw_missing")

    assert status == 400
    assert "error" in payload


def test_an_unknown_crowd_endpoint_is_a_404(api_server):
    status, payload = _request_json(api_server["url"], "/api/crowdsourcing/nonsense")

    assert status == 404
    assert payload == {"error": "Unknown endpoint"}
