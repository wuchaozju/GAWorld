"""A member can select models in their own world without editing shared providers."""

import json

import pytest

from gaworld import worlds
from gaworld.apps import world_paths
from tests import test_accounts as support


@pytest.fixture
def routing_host(monkeypatch, tmp_path, request):
    monkeypatch.delenv("GAWORLD_LLM_SECRETS_PATH", raising=False)
    monkeypatch.setenv("GAWORLD_URL_PREFIX", "/GAWorld")
    host = support.HttpTest()
    host.setUp()
    request.addfinalizer(host.tearDown)
    host.store = support._store(host.tmp.name)
    owner = host.store.create_user("owner", support.PASSWORD)
    host.store.create_user("reader", support.PASSWORD)
    host.world = host.store.create_world(owner["id"], "Owned world")
    host.store.set_world_visibility(host.world["id"], "class")
    host.global_path = tmp_path / "global.json"
    host.global_path.write_text(
        json.dumps(
            {
                "llm": {
                    "providers": {
                        "model_a": {"type": "ollama", "model": "a"},
                        "model_b": {"type": "openai", "model": "b", "base_url": "https://example.invalid/v1"},
                        "model_c": {"type": "ollama", "model": "c"},
                    },
                    "routing": {
                        "default": "model_a",
                        "tasks": {"schedule": "model_a", "reflection": "model_c"},
                    },
                }
            }
        )
    )
    monkeypatch.setattr(world_paths, "DASHBOARD_CONFIG_PATH", str(host.global_path))
    monkeypatch.setattr(worlds, "config_path", lambda root, wid: str(tmp_path / wid / "config.json"))
    host.world_path = tmp_path / host.world["id"] / "config.json"
    host.world_path.parent.mkdir()
    host.world_path.write_text(json.dumps({"sim_days": 7}))
    return host


def signed_in(host, nickname="owner", select=True):
    response, _ = host._req(
        "POST",
        "/GAWorld/api/auth/login",
        {
            "nickname": nickname,
            "password": support.PASSWORD,
        },
    )
    assert response.status == 200
    cookie = response.getheader("Set-Cookie").split(";", 1)[0]
    if select:
        response, _ = host._req("POST", "/GAWorld/api/worlds/select", {"id": host.world["id"]}, cookie=cookie)
        assert response.status == 200
        cookie += "; " + response.getheader("Set-Cookie").split(";", 1)[0]
    return cookie


def test_owner_changes_only_their_world_and_matching_tasks(routing_host):
    host = routing_host
    cookie = signed_in(host)
    before = host.global_path.read_bytes()
    view = host._req("GET", "/GAWorld/api/settings/overview", cookie=cookie)[1]
    assert view["can_edit_model_routing"] and not view["can_edit_config"]
    response, result = host._req(
        "POST",
        "/GAWorld/api/settings/llm/routing",
        {
            "routing": {"default": "model_b"},
        },
        cookie=cookie,
    )
    assert response.status == 200, result
    saved = json.loads(host.world_path.read_text())
    assert saved["sim_days"] == 7
    assert saved["llm"]["routing"] == {"default": "model_b", "tasks": {"schedule": "model_b"}}
    assert host.global_path.read_bytes() == before
    assert result["tree"]["llm"]["routing"]["tasks"]["reflection"] == "model_c"
    assert result["sources"]["llm.routing.default"] == "world"


@pytest.mark.parametrize("nickname,select", [("reader", True), ("owner", False)])
def test_shared_and_foreign_worlds_remain_read_only(routing_host, nickname, select):
    host = routing_host
    cookie = signed_in(host, nickname, select)
    before = host.world_path.read_bytes()
    view = host._req("GET", "/GAWorld/api/settings/overview", cookie=cookie)[1]
    assert not view["can_edit_model_routing"]
    response, _ = host._req(
        "POST",
        "/GAWorld/api/settings/llm/routing",
        {
            "routing": {"default": "model_b"},
        },
        cookie=cookie,
    )
    assert response.status == 403
    assert host.world_path.read_bytes() == before


@pytest.mark.parametrize(
    "body",
    [
        {"routing": {"default": "missing"}},
        {"routing": {"providers": {"x": {"url": "http://localhost"}}}},
        {"routing": {"tasks": {"schedule": "missing"}}},
        {"routing": {"fallback": "model_b"}},
        {"routing": {"agents": {"../x": "model_b"}}},
        {"routing": {"default": "model_b"}, "world_id": "wffffffff"},
    ],
)
def test_routing_rejects_invalid_models_and_other_configuration(routing_host, body):
    host = routing_host
    cookie = signed_in(host)
    before = host.world_path.read_bytes()
    response, _ = host._req("POST", "/GAWorld/api/settings/llm/routing", body, cookie=cookie)
    assert response.status == 400
    assert host.world_path.read_bytes() == before


def test_owner_still_cannot_write_global_configuration_or_providers(routing_host):
    host = routing_host
    cookie = signed_in(host)
    for path, body in [
        ("/api/settings/save", {"config": {"llm": {"routing": {"default": "model_b"}}}}),
        ("/api/settings/llm/provider", {"name": "x", "type": "ollama", "config": {"model": "x"}}),
    ]:
        assert host._req("POST", "/GAWorld" + path, body, cookie=cookie)[0].status == 403


def test_member_can_switch_models_and_save_from_the_page(routing_host):
    playwright = pytest.importorskip("playwright.sync_api")
    host = routing_host
    before = host.global_path.read_bytes()
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            base = f"http://127.0.0.1:{host.port}/GAWorld"
            response = page.request.post(
                base + "/api/auth/login",
                data={
                    "nickname": "owner",
                    "password": support.PASSWORD,
                },
            )
            assert response.status == 200
            assert page.request.post(base + "/api/worlds/select", data={"id": host.world["id"]}).status == 200
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/site/dashboard/settings.html?tab=llm")
            picker = page.locator('.llm-pick select[data-path="llm.routing.default"]')
            picker.wait_for()
            assert picker.is_enabled()
            assert page.locator("#llmAddBox").count() == 0
            assert picker.locator('option[value="model_b"]').count() == 1, picker.inner_html()
            assert picker.input_value() == "model_a"
            picker.select_option("model_b", timeout=5000)
            assert picker.input_value() == "model_b"
            with page.expect_response(
                lambda response: response.url.endswith("/api/settings/llm/routing")
            ) as saved:
                page.locator("#setSave").click()
            assert saved.value.status == 200
            page.reload()
            picker.wait_for()
            assert picker.input_value() == "model_b"
            assert host.global_path.read_bytes() == before
            assert page.request.post(base + "/api/worlds/select", data={"id": ""}).status == 200
            page.reload()
            picker.wait_for()
            assert picker.is_disabled()
            setup = page.locator("#llmWorldSetup")
            assert setup.is_visible()
            assert setup.get_attribute("href") == "/GAWorld/console#settings"
            setup.click()
            page.wait_for_url("**/console#settings")
            page.locator("#worldSelect").wait_for()
            assert page.locator("#worldManageBtn").is_visible()
            assert errors == []
        finally:
            browser.close()
