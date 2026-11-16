"""Population jobs, cached inputs and files stay inside the requesting user's world."""

import json
import shutil
import time
from pathlib import Path

import pytest

from gaworld.apps import population_api, world_paths
from tests import test_accounts as support


@pytest.fixture
def population_host(monkeypatch, tmp_path, request):
    monkeypatch.setenv("GAWORLD_URL_PREFIX", "/GAWorld")
    host = support.HttpTest()
    host.setUp()
    request.addfinalizer(host.tearDown)
    host.store = support._store(host.tmp.name)
    users = {name: host.store.create_user(name, support.PASSWORD) for name in ("alice", "bob")}
    host.worlds = {name: host.store.create_world(u["id"], name) for name, u in users.items()}
    host.worlds["alice2"] = host.store.create_world(users["alice"]["id"], "alice2")
    host.store.set_world_visibility(host.worlds["alice"]["id"], "class")
    host.root = tmp_path / "repo"
    host.root.mkdir()
    monkeypatch.setattr(world_paths, "REPO_ROOT", str(host.root))
    monkeypatch.setattr(world_paths, "DASHBOARD_CONFIG_PATH", str(host.root / "dashboard_config.json"))
    monkeypatch.setattr(population_api, "_JOBS", {})
    source = Path(__file__).resolve().parents[1]
    for rel in [
        "site/dashboard/population.html",
        "site/dashboard/population.js",
        "site/dashboard/population-runtime.js",
        "site/dashboard/population.css",
        "site/dashboard/page-shell.css",
        "site/dashboard/styles.css",
        "site/dashboard/i18n.js",
        "site/dashboard/_button-busy.js",
        "site/dashboard/locales/en.json",
        "site/dashboard/locales/zh-CN.json",
        "site/theme.js",
        "site/url.js",
        "site/tokens.css",
        "site/brand.css",
        "site/city-lab.css",
        "site/community/context.js",
        "site/auth/brand/gaworld-symbol-a.png",
    ]:
        dest = host.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, dest)
    return host


def login(host, name, world=None):
    response, _ = host._req(
        "POST", "/GAWorld/api/auth/login", {"nickname": name, "password": support.PASSWORD}
    )
    assert response.status == 200
    cookie = response.getheader("Set-Cookie").split(";", 1)[0]
    if world:
        response, _ = host._req(
            "POST", "/GAWorld/api/worlds/select", {"id": host.worlds[world]["id"]}, cookie=cookie
        )
        assert response.status == 200
        cookie += "; " + response.getheader("Set-Cookie").split(";", 1)[0]
    return cookie


def post(host, path, body, cookie):
    return host._req("POST", "/GAWorld/api/population/" + path, body, cookie=cookie)


def wait(host, job, cookie):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response, record = host._req("GET", "/GAWorld/api/population/jobs/" + job, cookie=cookie)
        assert response.status == 200, record
        if record["status"] != "running":
            assert record["status"] == "done", record.get("error")
            return record["result"]
        time.sleep(0.02)
    pytest.fail("population job did not finish")


def generate(host, size, cookie, write=False):
    response, body = post(host, "generate", {"spec": {"size": size, "seed": 3}, "write": write}, cookie)
    assert response.status == 202, body
    return body["job_id"], wait(host, body["job_id"], cookie)


def test_member_can_preview_but_generate_requires_an_owned_world(population_host):
    host = population_host
    for cookie in [login(host, "alice"), login(host, "bob", "alice")]:
        assert post(host, "preview", {"spec": {"size": 30}}, cookie)[0].status == 200
        for path in ["generate", "group-run", "validate"]:
            assert post(host, path, {"spec": {"size": 30}}, cookie)[0].status == 403


def test_population_jobs_last_and_export_are_isolated(population_host):
    host = population_host
    a, b = login(host, "alice", "alice"), login(host, "bob", "bob")
    ajob, _ = generate(host, 24, a)
    bjob, _ = generate(host, 36, b)
    for cookie, size in [(a, 24), (b, 36)]:
        last = host._req("GET", "/GAWorld/api/population/last", cookie=cookie)[1]
        assert last["count"] == size
        response, exported = host._req("GET", "/GAWorld/api/population/export?format=json", cookie=cookie)
        assert response.status == 200
        assert json.loads(exported["content"])["spec"]["size"] == size
        response, started = post(
            host, "group-run", {"source": "last", "days": 1, "materialization_budget": 1}, cookie
        )
        assert response.status == 202, started
        assert wait(host, started["job_id"], cookie)["cost"]["population"] == size
    response, started = post(host, "validate", {"days": 1, "materialization_budget": 1}, a)
    assert response.status == 202, started
    assert wait(host, started["job_id"], a)["verdict"]["population"] == 24
    assert host._req("GET", "/GAWorld/api/population/jobs/" + ajob, cookie=b)[0].status == 404
    assert host._req("GET", "/GAWorld/api/population/jobs/" + bjob, cookie=a)[0].status == 404
    a2 = login(host, "alice", "alice2")
    assert host._req("GET", "/GAWorld/api/population/last", cookie=a2)[1]["count"] == 0
    assert host._req("GET", "/GAWorld/api/population/jobs/" + ajob, cookie=a2)[0].status == 404


def test_population_files_stay_private_and_cannot_overwrite_seeds(population_host):
    host = population_host
    a = login(host, "alice", "alice")
    _, result = generate(host, 24, a, write=True)
    base = host.root / "output/worlds" / host.worlds["alice"]["id"] / "population"
    assert result["written"]
    for item in result["written"]:
        assert Path(item["path"]).is_relative_to(base)
        assert host._req("GET", "/GAWorld" + item["url"], cookie=a)[0].status == 200
        assert host._req("GET", "/GAWorld" + item["url"], cookie=login(host, "bob", "alice"))[0].status == 404
    for path in [
        "dashboard_config.json",
        "output/population",
        f"output/worlds/{host.worlds['alice']['id']}/seed",
    ]:
        assert (
            post(host, "generate", {"spec": {"size": 24}, "write": True, "out_dir": path}, a)[0].status == 400
        )
    base.mkdir(parents=True, exist_ok=True)
    (base / "escape").symlink_to(host.root, target_is_directory=True)
    path = str((base / "escape" / "overwritten.json").relative_to(host.root))
    assert post(host, "generate", {"spec": {"size": 24}, "write": True, "out_dir": path}, a)[0].status == 400
    assert not (host.root / "overwritten.json").exists()


def test_member_can_generate_from_population_page(population_host):
    playwright = pytest.importorskip("playwright.sync_api")
    host = population_host
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            base = f"http://127.0.0.1:{host.port}/GAWorld"
            assert (
                page.request.post(
                    base + "/api/auth/login", data={"nickname": "alice", "password": support.PASSWORD}
                ).status
                == 200
            )
            assert (
                page.request.post(base + "/api/worlds/select", data={"id": host.worlds["alice"]["id"]}).status
                == 200
            )
            page.goto(base + "/site/dashboard/population.html")
            page.locator('#popSteps [data-step="2"]').click()
            button = page.locator("#popGenerate")
            button.wait_for()
            assert button.is_enabled()
            with page.expect_response(lambda r: r.url.endswith("/api/population/generate")) as started:
                button.click()
            assert started.value.status == 202
            page.wait_for_function("document.querySelector('#popGenerate').textContent.includes('重新')")
            assert page.request.post(base + "/api/worlds/select", data={"id": ""}).status == 200
            page.reload()
            page.locator('#popSteps [data-step="2"]').click()
            page.locator("#popGenerate").wait_for()
            assert page.locator("#popGenerate").is_disabled()
        finally:
            browser.close()


def test_population_admission_is_bounded_per_owned_world(population_host, monkeypatch):
    host = population_host
    monkeypatch.setattr(population_api, "_run_in_background", lambda *args: None)
    a, b = login(host, "alice", "alice"), login(host, "bob", "bob")
    assert post(host, "generate", {"spec": {"size": 24}}, a)[0].status == 202
    assert post(host, "generate", {"spec": {"size": 24}}, a)[0].status == 400
    assert post(host, "generate", {"spec": {"size": 24}}, b)[0].status == 202


def test_idempotent_population_retry_keeps_world_and_server_admission_limits(population_host, monkeypatch):
    host = population_host
    monkeypatch.setattr(population_api, "_run_in_background", lambda *args: None)
    a, b = login(host, "alice", "alice"), login(host, "bob", "bob")
    payload = {"spec": {"size": 24}, "request_id": "member-population-request"}
    response, first = post(host, "generate", payload, a)
    assert response.status == 202
    response, repeated = post(host, "generate", payload, a)
    assert response.status == 202
    assert repeated["job_id"] == first["job_id"]
    assert post(host, "generate", {"spec": {"size": 25}}, a)[0].status == 400
    response, other = post(host, "generate", payload, b)
    assert response.status == 202
    assert other["job_id"] != first["job_id"]
    a2 = login(host, "alice", "alice2")
    assert post(host, "generate", {"spec": {"size": 24}}, a2)[0].status == 400


def test_population_model_call_uses_world_routing_and_accounts_for_usage(monkeypatch):
    from gaworld.accounts import community, usage
    from gaworld.accounts.context import USER, WORLD
    from gaworld.apps import population_scope
    from gaworld.llm import providers

    calls = []
    cfg = {
        "llm": {"providers": {"mine": {"type": "ollama", "model": "test"}}, "routing": {"default": "mine"}}
    }
    monkeypatch.setattr(world_paths, "effective_config", lambda: cfg)
    monkeypatch.setattr(community, "begin_model_call", lambda: ("reservation", "account"))
    monkeypatch.setattr(community, "settle_call", lambda *args: calls.append(("settled", args)))
    monkeypatch.setattr(usage, "record", lambda task: calls.append(("usage", task)))

    class Router:
        def __init__(self, config):
            assert config["llm"]["routing"]["default"] == "mine"

        def call(self, prompt, **kwargs):
            assert USER.get()["id"] == 42 and WORLD.get()["id"] == "w12345678"
            assert kwargs["allow_fallback"] is False
            return "answer"

    monkeypatch.setattr(providers, "LLMRouter", Router)
    user = USER.set({"id": 42, "role": "member"})
    world = WORLD.set({"id": "w12345678", "owner_id": 42})
    try:
        assert population_scope.model_call(None)("prompt", task="cohort") == "answer"
    finally:
        WORLD.reset(world)
        USER.reset(user)
    assert calls == [("settled", ("reservation", "account")), ("usage", "cohort")]
