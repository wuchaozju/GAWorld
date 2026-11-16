"""Real HTTP authentication and cross-account/world security, with no provider calls."""

import copy
import http.client
import json
import threading
import time
from contextlib import closing
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gaworld.accounts import AccountError, AccountStore, api_tokens
from gaworld.accounts.context import USER, WORLD
from gaworld.apps import dashboard_server as ds
from gaworld.apps import parallel_worlds_api as parallel
from gaworld.apps import world_paths

PASSWORD = "local-test-password-only"
SPEC = {
    "name": "API isolation",
    "sim_days": 1,
    "agent_ids": [1],
    "worlds": [{"label": "baseline"}, {"label": "treatment"}],
}


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = AccountStore(str(tmp_path / "accounts.sqlite"))
    store.init_schema()
    admin = store.create_user("admin", PASSWORD, role="admin")
    alice = store.create_user("alice", PASSWORD)
    bob = store.create_user("bob", PASSWORD)
    world = store.create_world(alice["id"], "Alice world")
    other_world = store.create_world(alice["id"], "Alice second world")
    bob_world = store.create_world(bob["id"], "Bob world")
    monkeypatch.setenv("GAWORLD_ACCOUNTS_DB", store.path)
    monkeypatch.setenv("GAWORLD_MULTI_USER", "true")
    monkeypatch.delenv("GAWORLD_DASHBOARD_TOKEN", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, payload=None, token=None, cookie=None, headers=None):
        merged = dict(headers or {})
        if token:
            merged["Authorization"] = "Bearer " + token
        if cookie:
            merged["Cookie"] = cookie
        data = json.dumps(payload).encode() if payload is not None else None
        if data is not None:
            merged["Content-Type"] = "application/json"
        with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)) as connection:
            connection.request(method, path, data, merged)
            response = connection.getresponse()
            raw = response.read()
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode()
            return response.status, body, dict(response.getheaders())

    cookie = "gaworld_session=" + store.open_session(alice["id"])

    def mint(scopes=None, user=alice, target=world):
        return api_tokens.create(
            store,
            user,
            {
                "name": "integration",
                "world_id": target["id"],
                "scopes": scopes or ["parallel:read", "parallel:run"],
            },
        )

    parallel._reset_for_tests()
    user_context, world_context = USER.set(None), WORLD.set(None)
    yield SimpleNamespace(
        store=store,
        admin=admin,
        alice=alice,
        bob=bob,
        world=world,
        other=other_world,
        bob_world=bob_world,
        request=request,
        mint=mint,
        cookie=cookie,
        base=f"http://127.0.0.1:{server.server_port}",
        tmp=tmp_path,
    )
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    parallel._reset_for_tests()
    USER.reset(user_context)
    WORLD.reset(world_context)


def test_management_secret_once_and_revoke(service):
    s = service
    payload = {
        "name": "Partner",
        "world_id": s.world["id"],
        "scopes": ["parallel:read"],
        "expires_days": 7,
        "password": PASSWORD,
    }
    status, created, headers = s.request("POST", "/api/auth/tokens", payload, cookie=s.cookie)
    assert status == 201
    assert "no-store" in headers["Cache-Control"]
    secret = created["token"]
    assert secret.startswith("gaw_pat_")
    rows = s.request("GET", "/api/auth/tokens", cookie=s.cookie)[1]["tokens"]
    assert len(rows) == 1 and rows[0]["name"] == "Partner"
    assert secret not in json.dumps(rows) and "token_hash" not in json.dumps(rows)
    assert secret.encode() not in s.tmp.joinpath("accounts.sqlite").read_bytes()
    assert s.request("GET", "/api/auth/me", token=secret)[0] == 200
    assert s.request("POST", "/api/auth/tokens/revoke", {"id": rows[0]["id"]}, cookie=s.cookie)[1]["revoked"]
    assert s.request("GET", "/api/auth/me", token=secret)[0] == 401


@pytest.mark.parametrize(
    "patch",
    [
        {"scopes": ["admin"]},
        {"scopes": []},
        {"scopes": "parallel:read"},
        {"scopes": [{}]},
        {"expires_days": 0},
        {"expires_days": 366},
        {"expires_days": True},
        {"expires_days": "30"},
        {"name": ""},
        {"world_id": []},
    ],
)
def test_invalid_token_settings(service, patch):
    s = service
    with pytest.raises(AccountError):
        api_tokens.create(
            s.store,
            s.alice,
            {"name": "test", "world_id": s.world["id"], "scopes": ["parallel:read"], **patch},
        )


def test_mint_requires_reauthentication_and_owned_world(service):
    s = service
    body = {"name": "app", "scopes": ["parallel:read"], "world_id": s.world["id"]}
    assert s.request("POST", "/api/auth/tokens", body, cookie=s.cookie)[0] == 403
    body.update(password=PASSWORD, world_id=s.bob_world["id"])
    assert s.request("POST", "/api/auth/tokens", body, cookie=s.cookie)[0] == 400
    assert s.request("GET", "/api/auth/tokens")[0] == 401


def test_invalid_bearer_never_falls_back_to_cookies(service, monkeypatch):
    s = service
    monkeypatch.setenv("GAWORLD_DASHBOARD_TOKEN", "operator-test-secret")
    cookies = s.cookie + "; gaworld_token=operator-test-secret"
    for header in ("Bearer invalid", "Basic anything", "Bearer", "Bearer one two", "Bearer \u00e9"):
        assert s.request("GET", "/api/auth/me", cookie=cookies, headers={"Authorization": header})[0] == 401
    assert s.request("GET", "/api/auth/me", token="operator-test-secret")[0] == 200
    assert s.request("GET", "/api/auth/me", cookie=s.cookie)[0] == 200


def test_scopes_and_cookie_cannot_escalate_or_switch_world(service, monkeypatch):
    s = service
    token = s.mint(["parallel:read"])["token"]
    assert s.request("POST", "/api/parallel-worlds/start", SPEC, token=token)[0] == 403
    for path in (
        "/api/auth/users",
        "/api/auth/tokens",
        "/api/worlds",
        "/api/config",
        "/output/accounts/accounts.sqlite",
    ):
        assert s.request("GET", path, token=token)[0] in (403, 404)
    for path in ("/api/auth/tokens", "/api/auth/tokens/revoke", "/api/worlds/select"):
        assert s.request("POST", path, {}, token=token)[0] == 403
    monkeypatch.setattr(
        parallel, "list_experiments", lambda: [{"world": WORLD.get()["id"], "user": USER.get()["id"]}]
    )
    cookie = "gaworld_world=" + s.bob_world["id"]
    status, body, _ = s.request("GET", "/api/parallel-worlds/experiments", token=token, cookie=cookie)
    assert status == 200 and body["experiments"] == [{"world": s.world["id"], "user": s.alice["id"]}]
    runner = s.mint()["token"]
    assert (
        s.request(
            "POST",
            "/api/parallel-worlds/preview",
            SPEC,
            token=runner,
            headers={"X-GAWorld-World": s.other["id"]},
        )[0]
        == 409
    )


@pytest.mark.parametrize(
    "cause", ["expired", "password", "disabled", "world_deleted", "world_transferred", "unverified"]
)
def test_credential_invalidated_by_account_or_world_changes(service, cause):
    s = service
    token = s.mint()["token"]
    with s.store._db() as db:
        if cause == "expired":
            db.execute("UPDATE api_tokens SET expires_at=0")
        elif cause == "disabled":
            db.execute("UPDATE account_profiles SET enabled=0 WHERE user_id=?", (s.alice["id"],))
        elif cause == "unverified":
            db.execute("UPDATE account_profiles SET email_verified=0 WHERE user_id=?", (s.alice["id"],))
        elif cause == "world_deleted":
            db.execute("DELETE FROM worlds WHERE id=?", (s.world["id"],))
        elif cause == "world_transferred":
            db.execute("UPDATE worlds SET owner_id=? WHERE id=?", (s.bob["id"], s.world["id"]))
    if cause == "password":
        s.store.change_password(s.alice["id"], PASSWORD, "a-new-local-password")
    assert s.request("GET", "/api/auth/me", token=token)[0] == 401


def test_cannot_revoke_another_accounts_token_or_inherit_admin(service):
    s = service
    created = s.mint(user=s.bob, target=s.bob_world)
    assert not s.request("POST", "/api/auth/tokens/revoke", {"id": created["record"]["id"]}, cookie=s.cookie)[
        1
    ]["revoked"]
    admin_world = s.store.create_world(s.admin["id"], "admin world")
    token = s.mint(user=s.admin, target=admin_world)["token"]
    assert s.request("GET", "/api/auth/me", token=token)[1]["user"]["role"] == "member"
    assert s.request("GET", "/api/auth/users", token=token)[0] == 403


@pytest.mark.parametrize(
    "patch",
    [
        {"config": {"plugins": ["arbitrary.module"]}},
        {"config": {"economy": {"output_dir": "/tmp/escape"}}},
        {"config": {"llm": {"providers": {"remote": {"base_url": "http://localhost"}}}}},
        {"seed_from_checkpoint": "output/another-users-run"},
    ],
)
def test_parallel_payload_cannot_load_code_paths_or_checkpoints(service, patch):
    payload = copy.deepcopy(SPEC)
    payload["worlds"][1].update(patch)
    assert (
        service.request("POST", "/api/parallel-worlds/preview", payload, token=service.mint()["token"])[0]
        == 400
    )


def test_preview_valid_and_cross_origin_denied(service):
    s = service
    token = s.mint()["token"]
    assert s.request("POST", "/api/parallel-worlds/preview", SPEC, token=token)[0] == 200
    assert (
        s.request(
            "POST",
            "/api/parallel-worlds/preview",
            SPEC,
            token=token,
            headers={"Origin": "https://untrusted.invalid"},
        )[0]
        == 403
    )


@pytest.mark.parametrize("length,status", [("bad", 400), ("-1", 400), ("4194305", 413)])
def test_token_body_limit(service, length, status):
    assert (
        service.request(
            "POST",
            "/api/parallel-worlds/preview",
            token=service.mint()["token"],
            headers={"Content-Length": length},
        )[0]
        == status
    )


def test_cross_world_job_read_and_stop_are_denied(service):
    s = service
    USER.set(s.alice)
    WORLD.set(s.other)
    job_id = parallel._new_job({"root": "test"})
    runner = Mock()
    parallel._ACTIVE.update(job_id=job_id, runner=runner, stop=threading.Event())
    token = s.mint()["token"]
    assert s.request("GET", "/api/parallel-worlds/job?id=" + job_id, token=token)[1] == {"job": None}
    assert s.request("POST", "/api/parallel-worlds/stop", {}, token=token)[0] == 403
    runner.stop.assert_not_called()
    own_token = s.mint(target=s.other)["token"]
    runner.snapshot.return_value = {}
    assert s.request("POST", "/api/parallel-worlds/stop", {}, token=own_token)[0] == 200
    runner.stop.assert_called_once()


def test_start_poll_report_and_owner_context_without_llm(service, monkeypatch):
    s = service
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(s.tmp))
    monkeypatch.setattr(parallel, "_config", lambda: {"agent_ids": [99], "sentinel": "owned-world-config"})
    calls = []

    def run(runner, on_progress):
        calls.append((USER.get()["id"], WORLD.get()["id"], runner.research_frozen_config))
        return {"worlds": []}

    monkeypatch.setattr(parallel.prunner.ExperimentRunner, "run", run)
    token = s.mint()["token"]
    status, started, _ = s.request("POST", "/api/parallel-worlds/start", SPEC, token=token)
    assert status == 202
    for _ in range(100):
        job = s.request("GET", "/api/parallel-worlds/job?id=" + started["job_id"], token=token)[1]["job"]
        if job["status"] != "running":
            break
        time.sleep(0.01)
    assert job["status"] == "done"
    assert calls == [(s.alice["id"], s.world["id"], {"agent_ids": [99], "sentinel": "owned-world-config"})]
    manifest = parallel.prunner.load_manifest(str(s.tmp), started["experiment"])
    assert manifest["owner_id"] == s.alice["id"] and manifest["world_id"] == s.world["id"]
    own = s.request("GET", "/api/parallel-worlds/experiments", token=token)
    assert len(own[1]["experiments"]) == 1
    bob_token = s.mint(user=s.bob, target=s.bob_world)["token"]
    assert s.request("GET", "/api/parallel-worlds/experiments", token=bob_token)[1]["experiments"] == []
    assert (
        s.request("GET", "/api/parallel-worlds/experiment?root=" + started["experiment"], token=bob_token)[0]
        == 404
    )


def test_schema_upgrade_idempotent_and_token_limit(service):
    s = service
    s.store.init_schema()
    s.store.init_schema()
    for _ in range(20):
        s.mint()
    with pytest.raises(AccountError):
        s.mint()
    rows = api_tokens.list_tokens(s.store, s.alice["id"])
    assert api_tokens.revoke(s.store, s.alice, rows[0]["id"])
    assert s.mint()["token"]


def test_mount_and_quota_and_python_client(service, monkeypatch):
    from gaworld.accounts import usage
    from gaworld.client import GAWorldClient

    s = service
    monkeypatch.setenv("GAWORLD_URL_PREFIX", "/GAWorld")
    token = s.mint()["token"]
    client = GAWorldClient(s.base + "/GAWorld", token=token)
    open_request = client._opener.open

    def identified_request(request, **kwargs):
        assert request.get_header("User-agent") == "GAWorldClient/1.0"
        return open_request(request, **kwargs)

    monkeypatch.setattr(client._opener, "open", identified_request)
    assert client.me()["user"]["id"] == s.alice["id"]
    assert client.call("post_parallel_worlds_preview", body=SPEC)["spec"]["sim_days"] == 1
    s.store.set_setting("daily_llm_calls_per_user", 1)
    monkeypatch.setattr(usage.TALLY, "today", lambda _: 1)
    assert s.request("POST", "/GAWorld/api/parallel-worlds/start", SPEC, token=token)[0] == 429
    assert s.request("POST", "/GAWorld/api/parallel-worlds/preview", SPEC, token=token)[0] == 200


@pytest.mark.parametrize("width,prefix", [(1440, ""), (390, "/GAWorld")])
def test_browser_create_hide_revoke(service, monkeypatch, width, prefix):
    from playwright.sync_api import sync_playwright

    s = service
    monkeypatch.setenv("GAWORLD_URL_PREFIX", "/GAWorld")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 950})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        logged = page.request.post(
            s.base + prefix + "/api/auth/login", data={"nickname": "alice", "password": PASSWORD}
        )
        assert logged.ok
        page.goto(s.base + prefix + "/console#account")
        frame = page.frame_locator('iframe[title="account"]')
        frame.locator("#tokenName").fill("Partner test")
        frame.locator("#tokenWorld").select_option(s.world["id"])
        frame.locator("#tokenPassword").fill(PASSWORD)
        frame.locator("#tokenForm button").click()
        frame.locator("#tokenSecretPanel:not([hidden])").wait_for()
        secret = frame.locator("#tokenSecret").input_value()
        assert secret.startswith("gaw_pat_")
        assert frame.locator("#tokenPassword").input_value() == ""
        frame.locator("#tokenHide").click()
        assert frame.locator("#tokenSecret").input_value() == ""
        section = frame.locator(".api-tokens")
        section.scroll_into_view_if_needed()
        assert section.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        section.screenshot(path=str(s.tmp / f"api-tokens-{width}.png"))
        page.on("dialog", lambda dialog: dialog.accept())
        frame.locator("[data-revoke]").click()
        frame.locator("[data-revoke]").wait_for(state="detached")
        assert s.request("GET", "/api/auth/me", token=secret)[0] == 401
        assert not errors
        browser.close()
