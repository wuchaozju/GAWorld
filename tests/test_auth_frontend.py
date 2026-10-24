"""Login must never submit credentials through the browser's default GET."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from gaworld.apps.dashboard_server import DashboardHandler

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scripts", [True, False])
def test_auth_waits_for_configuration_and_never_uses_native_get(scripts):
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(java_script_enabled=scripts)
        page = context.new_page()
        pending = []
        requests = []

        def route(request):
            path = request.request.url.split("http://auth.test", 1)[1]
            if path == "/login":
                request.fulfill(path=str(ROOT / "site/auth/index.html"), content_type="text/html")
            elif path == "/site/auth/auth.js":
                request.fulfill(path=str(ROOT / "site/auth/auth.js"), content_type="text/javascript")
            elif path == "/api/auth/config":
                pending.append(request)
            elif path == "/api/auth/login":
                requests.append(request.request)
                request.fulfill(status=400, json={"error": "test rejection"})
            else:
                request.fulfill(status=404)

        context.route("**/*", route)
        try:
            page.goto("http://auth.test/login", wait_until="domcontentloaded")
            assert page.locator("#form").get_attribute("method") == "post"
            assert page.locator("#submit").is_disabled()
            page.locator("#nickname").fill("local-user")
            page.locator("#password").fill("local-test-password")
            page.locator("#password").press("Enter")
            page.wait_for_timeout(100)
            assert page.url == "http://auth.test/login"
            assert not requests
            if scripts:
                assert len(pending) == 1
                pending[0].fulfill(json={"registration": "invite"})
                page.wait_for_function("!document.querySelector('#submit').disabled")
                page.locator("#submit").click()
                page.wait_for_function("document.querySelector('#error').textContent === 'test rejection'")
                assert len(requests) == 1
                assert requests[0].method == "POST"
                assert requests[0].url == "http://auth.test/api/auth/login"
                assert requests[0].post_data_json["password"] == "local-test-password"
        finally:
            context.close()
            browser.close()


def test_request_logs_redact_authentication_query_fields(capsys):
    handler = Mock()
    handler.address_string.return_value = "127.0.0.1"
    handler.log_date_time_string.return_value = "test"
    DashboardHandler.log_message(
        handler,
        "%s",
        "GET /login?password=secret1&confirm=secret2&code=secret3&token=secret4&PASSWORD=secret5",
    )
    output = capsys.readouterr().err
    assert "secret" not in output
    assert output.count("***") == 5
