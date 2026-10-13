"""Phase 3 integration tests: FOS talks to GAWorld population APIs.

Written TDD-RED for Phase 3 STAGE A (task 2513). GAWorld-unavailable and
drift-guard tests pin/protect existing behaviour; everything else fails
because the GAWorld population feature does not exist yet.

Assumptions about the implementation under test (documented for the
implementer, all following PHASE3-BRIEF.md §3–§7):

- ``fos/src/fos/backend/services/gaworld_agents.py`` gains:
    GAWORLD_API_URL: str            # default "http://127.0.0.1:8766"
    class GAWorldUnavailableError(Exception)
    list_populations() -> dict
    get_agents(city="", limit=200, offset=0) -> dict
    get_agent_detail(agent_id, city="") -> dict
    generate_population(spec: dict) -> dict   # {"job_id", "status"}
    poll_population_job(job_id) -> dict       # status mapped to
                                              # queued|running|completed|failed
    export_population(fmt="json") -> dict
    to_fos_agent(agent: dict) -> dict         # FOS agent shape that keeps
                                              # properties["gaworld_agent_id"]
  All HTTP goes through the module-level ``httpx`` import, so tests can
  monkeypatch ``gaworld_agents.httpx`` with a fake module (this file only
  relies on ``import httpx`` inside the service, not on any helper).
- The scenarios router (fos/src/fos/backend/api/routes/scenarios.py) exposes:
    GET  /scenarios/gaworld/populations
    GET  /scenarios/gaworld/agents?city=&limit=&offset=
    GET  /scenarios/gaworld/agents/{agent_id}?city=
    POST /scenarios/gaworld/populations/generate        (202)
    GET  /scenarios/gaworld/populations/jobs/{job_id}
    GET  /scenarios/gaworld/populations/export?format=
- GAWorld being down surfaces as HTTP 503 with the message
  "GAWorld backend unavailable" — never a raw traceback, never a silent
  fallback to hangzhou_50.json (brief §11).
- GAWorld agent ids are ints on the wire (verified against
  ``gaworld.apps.city_api.agents`` / ``gaworld.interview.roster.load_population``)
  and must stay ints end to end (brief scope guard).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from litestar import Litestar
from litestar.testing import TestClient

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "gaworld" / "city_agents_response.json"
)

# ---------------------------------------------------------------------------
# Fake GAWorld server: a tiny scripted httpx.Client standing in for the
# dashboard at 127.0.0.1:8766, with the REAL response shapes recorded from
# gaworld/apps/city_api.py and gaworld/apps/population_api.py.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None  # type: ignore[arg-type]
            )


_AGENT_PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8"))

_JOBS: dict[str, dict[str, Any]] = {}


def _fake_gaworld_routes(method: str, url: str, params: dict | None, body: dict | None):
    """Real GAWorld contract, minimally scripted. Returns (status, payload)."""
    path = url.split("8766")[-1] or url
    recorded_params: dict[str, list[str]] = {}
    if params:
        for key, value in params.items():
            recorded_params[key] = value if isinstance(value, list) else [str(value)]

    if method == "GET" and path == "/api/city/catalogue":
        return 200, {
            "cities": [
                {"slug": "", "name": "默认世界", "display_name": "默认世界", "population": 50},
                {"slug": "liuxi-cun", "name": "柳溪村", "display_name": "柳溪村", "population": 3},
            ],
            "selected": "liuxi-cun",
        }
    if method == "GET" and path == "/api/city/agents":
        return 200, _AGENT_PAYLOAD
    if method == "GET" and path == "/api/city/agent":
        wanted = int(recorded_params["id"][0])
        person = next(a for a in _AGENT_PAYLOAD["agents"] if a["id"] == wanted)
        return 200, {
            "city": _AGENT_PAYLOAD["city"],
            "agent": {**person, "profile_text": f"# {person['name']}\nAge: {person['age']}"},
        }
    if method == "POST" and path == "/api/population/generate":
        job_id = f"pop-{len(_JOBS) + 1:08x}"
        _JOBS[job_id] = {"status": body.get("_final_status", "done") if body else "done"}
        return 202, {"job_id": job_id, "status": "running"}
    if method == "GET" and path.startswith("/api/population/jobs/"):
        job_id = path.rsplit("/", 1)[-1]
        status = _JOBS.get(job_id, {}).get("status")
        if status is None:
            return 404, {"error": "Unknown job"}
        record = {
            "id": job_id,
            "kind": "pop",
            "status": status,
            "progress": 1.0 if status in ("done", "error") else 0.4,
            "message": "完成" if status == "done" else "启动中…",
            "result": None,
            "error": None,
        }
        if status == "done":
            record["result"] = {"ok": True, "people": _AGENT_PAYLOAD["agents"]}
        if status == "error":
            record["message"] = "合成失败"
            record["error"] = {"type": "ValueError", "detail": "boom"}
        return 200, record
    if method == "GET" and path == "/api/population/export":
        return 200, {
            "format": "json",
            "filename": "liuxi_manifest.json",
            "content_type": "application/json; charset=utf-8",
            "bom": False,
            "bytes": 42,
            "content": "{}",
        }
    return 404, {"error": f"Unexpected fake route: {method} {path}"}


class _FakeClient:
    """Stands in for ``httpx.Client``; records calls for assertions."""

    calls: list[tuple[str, str, dict | None]] = []
    fail_with_connect_error = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._kwargs = kwargs

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _send(self, method: str, url: str, params=None, json=None) -> _FakeResponse:
        type(self).calls.append((method, url, params))
        if type(self).fail_with_connect_error:
            raise httpx.ConnectError("connection refused", request=None)  # type: ignore[arg-type]
        status, payload = _fake_gaworld_routes(method, url, params, json)
        return _FakeResponse(status, payload)

    def get(self, url: str, params=None) -> _FakeResponse:
        return self._send("GET", url, params=params)

    def post(self, url: str, json=None) -> _FakeResponse:
        return self._send("POST", url, json=json)

    def close(self) -> None:
        pass


@pytest.fixture()
def fake_gaworld(monkeypatch):
    """Swap the service's httpx for the fake GAWorld server."""
    from fos.backend.services import gaworld_agents as svc

    _FakeClient.calls = []
    _FakeClient.fail_with_connect_error = False
    _JOBS.clear()
    fake_httpx = SimpleNamespace(
        Client=_FakeClient,
        ConnectError=httpx.ConnectError,
        HTTPStatusError=httpx.HTTPStatusError,
        HTTPError=httpx.HTTPError,
    )
    monkeypatch.setattr(svc, "httpx", fake_httpx)
    return _FakeClient


def _scenarios_app() -> Litestar:
    from fos.backend.api.routes.scenarios import router

    return Litestar(route_handlers=[router])


# ---------------------------------------------------------------------------
# RED — service layer
# ---------------------------------------------------------------------------


class TestServiceAgentList:
    def test_agent_list_maps_gaworld_response_preserving_exact_ids(self, fake_gaworld):
        """GAWorld ids are ints on the wire and must come back as ints."""
        from fos.backend.services import gaworld_agents as svc

        result = svc.get_agents(city="liuxi-cun")
        ids = [agent["id"] for agent in result["agents"]]
        assert ids == [1, 2, 34], ids
        assert all(isinstance(i, int) for i in ids)

    def test_pagination_params_are_passed_through(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        svc.get_agents(city="liuxi-cun", limit=2, offset=1)
        method, url, params = fake_gaworld.calls[-1]
        assert method == "GET"
        assert url.endswith("/api/city/agents"), url
        assert params is not None
        assert str(params.get("limit")) == "2"
        assert str(params.get("offset")) == "1"
        assert str(params.get("city")) == "liuxi-cun"

    def test_agent_detail_mapping(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        detail = svc.get_agent_detail(34, city="liuxi-cun")
        assert detail["agent"]["id"] == 34
        assert isinstance(detail["agent"]["id"], int)
        assert "profile_text" in detail["agent"]

    def test_list_populations_maps_catalogue(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        result = svc.list_populations()
        slugs = [p["slug"] for p in result["populations"]]
        assert "liuxi-cun" in slugs


class TestGenerationAndJobs:
    def test_generate_population_returns_job_ref(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        ref = svc.generate_population({"size": 30})
        assert set(ref) >= {"job_id", "status"}
        assert ref["status"] in ("queued", "running")

    def test_poll_success_maps_to_completed(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        ref = svc.generate_population({"size": 30})
        status = svc.poll_population_job(ref["job_id"])
        assert status["status"] == "completed"

    def test_poll_failure_maps_to_failed(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        ref = svc.generate_population({"_final_status": "error", "size": 30})
        status = svc.poll_population_job(ref["job_id"])
        assert status["status"] == "failed"

    def test_export_population(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        exported = svc.export_population("json")
        assert exported["format"] == "json"
        assert "content" in exported


class TestUnavailable:
    def test_connect_error_raises_typed_error(self, fake_gaworld):
        from fos.backend.services import gaworld_agents as svc

        fake_gaworld.fail_with_connect_error = True
        with pytest.raises(svc.GAWorldUnavailableError, match="GAWorld backend unavailable"):
            svc.get_agents(city="liuxi-cun")


class TestFosAgentShape:
    def test_fos_agent_config_stores_exact_gaworld_id(self, fake_gaworld):
        """Phase 4 depends on {"gaworld_agent_id": <id>} with the REAL type."""
        from fos.backend.services import gaworld_agents as svc

        result = svc.get_agents(city="liuxi-cun")
        fos_agents = [svc.to_fos_agent(a) for a in result["agents"]]
        by_id = {a["properties"]["gaworld_agent_id"]: a for a in fos_agents}
        assert set(by_id) == {1, 2, 34}
        assert all(isinstance(i, int) for i in by_id)
        assert by_id[34]["name"] == "徐桂兰"


# ---------------------------------------------------------------------------
# RED — routes
# ---------------------------------------------------------------------------


class TestRoutes:
    def test_agents_route_keeps_exact_ids_and_pagination(self, fake_gaworld):
        with TestClient(app=_scenarios_app()) as client:
            response = client.get("/scenarios/gaworld/agents", params={"city": "liuxi-cun", "limit": 2, "offset": 1})
        assert response.status_code == 200
        payload = response.json()
        assert [a["id"] for a in payload["agents"]] == [2, 34]
        assert all(isinstance(a["id"], int) for a in payload["agents"])

    def test_generate_route_returns_job_ref_202(self, fake_gaworld):
        with TestClient(app=_scenarios_app()) as client:
            response = client.post("/scenarios/gaworld/populations/generate", json={"spec": {"size": 30}})
        assert response.status_code == 202
        assert "job_id" in response.json()

    def test_poll_route_maps_done_to_completed(self, fake_gaworld):
        with TestClient(app=_scenarios_app()) as client:
            ref = client.post(
                "/scenarios/gaworld/populations/generate", json={"spec": {"size": 30}}
            ).json()
            polled = client.get(f"/scenarios/gaworld/populations/jobs/{ref['job_id']}")
        assert polled.status_code == 200
        assert polled.json()["status"] == "completed"

    def test_unavailable_is_clean_typed_error_not_traceback(self, fake_gaworld):
        fake_gaworld.fail_with_connect_error = True
        with TestClient(app=_scenarios_app()) as client:
            response = client.get("/scenarios/gaworld/agents", params={"city": "liuxi-cun"})
        assert response.status_code == 503
        assert "GAWorld backend unavailable" in response.json()["error"]

    def test_normal_path_does_not_read_hangzhou_snapshot(self, fake_gaworld, monkeypatch):
        """Brief §12: prove the new path never touches hangzhou_50.json."""
        from fos.core.experiment.scenes.gaworld import profiles as profiles_module

        def _forbidden(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("hangzhou_50.json snapshot path was read")

        monkeypatch.setattr(profiles_module, "load_profiles", _forbidden)
        with TestClient(app=_scenarios_app()) as client:
            response = client.get("/scenarios/gaworld/agents", params={"city": "liuxi-cun"})
        assert response.status_code == 200
        assert [a["id"] for a in response.json()["agents"]] == [1, 2, 34]


# ---------------------------------------------------------------------------
# GUARD — fixture drift detection against the real GAWorld contract
# ---------------------------------------------------------------------------


class TestContractFixture:
    def test_fixture_matches_recorded_gaworld_agent_shape(self):
        """Minimal recorded response; fails if the GAWorld contract drifts."""
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        # Recorded from gaworld.apps.city_api.agents: page metadata…
        assert {"city", "matched", "offset", "limit", "agents"} <= set(payload)
        # …city stamp…
        assert {"slug", "name", "selected"} <= set(payload["city"])
        # …and one agent row per roster.load_population, with an INT id.
        required_agent_keys = {
            "id",
            "name",
            "gender",
            "age",
            "hukou",
            "residence",
            "job",
            "state",
        }
        assert all(required_agent_keys <= set(a) for a in payload["agents"])
        assert all(isinstance(a["id"], int) for a in payload["agents"])
