"""Interaction contracts for the illustrated homepage, without model calls."""

import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def landing_browser():
    api = pytest.importorskip("playwright.sync_api")

    class LandingHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            aliases = {
                "/": "/site/index.html",
                "/workspace": "/site/community/workspace.html",
                "/console": "/site/console/index.html",
            }
            if url.path in aliases:
                self.path = aliases[url.path] + ("?" + url.query if url.query else "")
            super().do_GET()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(LandingHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch()
        except Exception as exc:
            server.server_close()
            pytest.skip(f"Chromium unavailable: {exc}")
        try:
            yield browser, f"http://127.0.0.1:{server.server_port}"
        finally:
            browser.close()
            server.shutdown()
            server.server_close()


def test_animation_pause_stops_and_resumes_the_city(landing_browser):
    browser, base = landing_browser
    page = browser.new_page()
    page.set_default_timeout(3000)
    try:
        page.goto(base)
        canvas = page.locator("#world-canvas")
        canvas.wait_for(state="visible", timeout=3000)
        page.locator("#motion-toggle").click()
        assert page.locator("html").get_attribute("data-motion") == "paused"
        before = canvas.evaluate("el => el.toDataURL()")
        page.wait_for_timeout(160)
        assert canvas.evaluate("el => el.toDataURL()") == before
        page.locator("#motion-toggle").click()
        page.wait_for_function(
            "before => document.getElementById('world-canvas').toDataURL() !== before", arg=before
        )
    finally:
        page.close()


def test_reduced_motion_is_static_until_user_requests_animation(landing_browser):
    browser, base = landing_browser
    context = browser.new_context(reduced_motion="reduce")
    try:
        page = context.new_page()
        page.goto(base)
        assert page.locator("html").get_attribute("data-motion") == "paused"
        assert page.locator("#motion-toggle").get_attribute("aria-pressed") == "true"
        assert page.locator(".hero-copy").evaluate("el => getComputedStyle(el).opacity") == "1"
        assert page.locator(".world-stage").evaluate("el => getComputedStyle(el).opacity") == "1"
        page.locator("#motion-toggle").click()
        assert page.locator("html").get_attribute("data-motion") == "running"
    finally:
        context.close()


def test_diagram_controls_change_the_explanation_and_comparison(landing_browser):
    browser, base = landing_browser
    page = browser.new_page()
    page.set_default_timeout(3000)
    try:
        page.goto(base)
        page.locator('[data-network="work"]').click()
        assert page.locator("#social-network").get_attribute("data-layer") == "work"
        assert page.locator('[data-network="work"]').get_attribute("aria-pressed") == "true"
        previous = page.locator("#intervention-curve").get_attribute("d")
        page.locator("#intervention-level").fill("85")
        assert page.locator("#intervention-curve").get_attribute("d") != previous
        assert page.locator("#intervention-value").text_content() == "85"
        page.locator('[data-persona="work"]').click()
        assert "工作" in page.locator("#persona-insight").text_content()
    finally:
        page.close()


def test_feature_scenes_and_research_design_are_concrete(landing_browser):
    browser, base = landing_browser
    context = browser.new_context(reduced_motion="reduce")
    try:
        page = context.new_page()
        page.goto(base)
        assert page.locator("#platform .feature-card .feature-vignette svg").count() == 6
        assert page.locator("#research .protocol-step").count() == 6
        assert page.locator("#research .paired-estimator").is_visible()
        assert page.locator("#research .uncertainty-diagram").is_visible()
        assert page.locator('#research a[href="/console#research"]').count() >= 1
    finally:
        context.close()


def test_offscreen_diagrams_stay_paused_when_global_motion_resumes(landing_browser):
    browser, base = landing_browser
    page = browser.new_page()
    page.set_default_timeout(3000)
    try:
        page.goto(base)
        page.wait_for_function("document.getElementById('social-network').classList.contains('is-outside')")
        page.locator("#motion-toggle").click()
        page.locator("#motion-toggle").click()
        assert page.locator(".network-art").evaluate("svg => svg.animationsPaused()")
        page.locator("#social-network").scroll_into_view_if_needed()
        page.wait_for_function("!document.querySelector('.network-art').animationsPaused()")
        page.wait_for_function("document.getElementById('world-panel').classList.contains('is-outside')")
        frozen = page.locator("#world-canvas").evaluate("el => el.toDataURL()")
        page.wait_for_timeout(160)
        assert page.locator("#world-canvas").evaluate("el => el.toDataURL()") == frozen
    finally:
        page.close()


def _console_page(browser, base, *, width=390, role=None):
    """Exercise the real shell, with inert child documents and local API fixtures."""
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    page.set_default_timeout(3000)
    user = {"id": "u1", "role": role, "nickname": "很长的研究者名字" * 10}
    world = {"id": "w1", "name": "很长的研究世界名称" * 10, "owner": "u1", "can_write": False}

    def respond(route):
        request = route.request
        if request.resource_type == "document" and request.frame.parent_frame:
            route.fulfill(content_type="text/html", body="<h1>Test view</h1><input aria-label='Draft'>")
        elif "/api/" in request.url:
            data = {"mode": "single"}
            if role and request.url.endswith("/api/auth/me"):
                data = {"mode": "accounts", "user": user}
            elif role and request.url.endswith("/api/worlds"):
                data = {"mode": "accounts", "worlds": [world], "current": world}
            route.fulfill(content_type="application/json", body=json.dumps(data))
        else:
            route.continue_()

    page.route("**/*", respond)
    page.goto(base + "/site/console/index.html#dashboard")
    page.locator("#crumbView").filter(has_text="控制台").wait_for()
    return page


@pytest.mark.parametrize("width", [1440, 1024, 768, 390, 320])
@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_home_navigation_keeps_primary_entry_and_fits_viewport(landing_browser, width, language, theme):
    browser, base = landing_browser
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    try:
        page.add_init_script(
            f"localStorage.setItem('gaworld-language', '{language}');"
            f"localStorage.setItem('gaworld.theme', '{theme}');"
        )
        page.goto(base)
        entry = page.locator(".header .nav-console")
        assert entry.is_visible()
        box = entry.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width
        assert page.locator(".header").bounding_box()["height"] <= 90
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        page.close()


def test_home_mobile_menu_focus_escape_and_breakpoint_cleanup(landing_browser):
    browser, base = landing_browser
    page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page.set_default_timeout(3000)
    try:
        page.goto(base)
        page.locator("#menu-toggle").click()
        assert page.locator("#main-nav a").first.evaluate("el => el === document.activeElement")
        assert page.locator("main").evaluate("el => el.inert")
        assert page.locator("#themeMode").is_visible()
        assert page.locator("#language").is_visible()
        page.locator("#language").click()
        assert page.locator("html").get_attribute("lang") == "en"
        page.keyboard.press("Escape")
        assert page.locator("#menu-toggle").get_attribute("aria-expanded") == "false"
        assert page.locator("#menu-toggle").evaluate("el => el === document.activeElement")
        assert page.locator("#themeMode").is_hidden()
        page.locator("#menu-toggle").click()
        page.set_viewport_size({"width": 1440, "height": 900})
        assert page.locator("#main-nav").is_visible()
        assert page.locator("main").evaluate("el => !el.inert")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("#menu-toggle").get_attribute("aria-expanded") == "false"
        assert page.locator("#main-nav").is_hidden()
    finally:
        page.close()


def test_console_mobile_drawer_focus_and_background_isolation(landing_browser):
    browser, base = landing_browser
    page = _console_page(browser, base)
    try:
        assert page.locator("#crumbView").is_visible()
        assert page.locator("#sidebar").evaluate("el => el.inert")
        page.locator("#navToggle").click()
        assert page.locator('[data-tab="dashboard"]').evaluate("el => el === document.activeElement")
        assert page.locator("#frames").evaluate("el => el.inert")
        page.keyboard.press("End")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('#sidebar') !== null")
        page.keyboard.press("Shift+Tab")
        assert page.locator('[data-tab="docs"]').evaluate("el => el === document.activeElement")
        page.keyboard.press("Escape")
        assert page.locator("#navToggle").evaluate("el => el === document.activeElement")
        assert page.locator("#frames").evaluate("el => !el.inert")
        page.locator("#navToggle").click()
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_function("!document.body.classList.contains('nav-open')")
        assert page.locator("#sidebar").evaluate("el => !el.inert")
        assert page.locator("#frames").evaluate("el => !el.inert")
        assert page.locator("#navBackdrop").is_hidden()
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/site/console/index.html#account")
        page.locator("#navToggle").click()
        assert page.locator('[data-tab="workspace"]').evaluate("el => el === document.activeElement")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('#sidebar') !== null")
    finally:
        page.close()


@pytest.mark.parametrize("role", [None, "member", "admin"])
def test_console_tools_and_long_world_names_fit_mobile(landing_browser, role):
    browser, base = landing_browser
    page = _console_page(browser, base, width=320, role=role)
    try:
        if role:
            page.locator("#worldChip").wait_for(state="visible")
        assert page.locator(".console-bar").bounding_box()["height"] <= 120
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.locator("#consoleTools > summary").click()
        assert page.locator("#themeMode").is_visible()
        assert page.locator("#openNew").is_visible()
        assert page.locator("#userChip").is_visible() == bool(role)
        page.locator("#lang-en-btn").click()
        page.wait_for_function("document.documentElement.lang === 'en'")
        page.locator("#themeMode").select_option("dark")
        assert page.locator("html").get_attribute("data-theme") == "dark"
        panel = page.locator(".console-tools-panel").bounding_box()
        assert panel["x"] >= 0 and panel["x"] + panel["width"] <= 320
        page.keyboard.press("Escape")
        assert not page.locator("#consoleTools").evaluate("el => el.open")
        assert page.locator("#consoleTools > summary").evaluate("el => el === document.activeElement")
        page.locator("#navToggle").click()
        assert page.locator('[data-tab="admin"]').is_visible() == (role == "admin")
    finally:
        page.close()


def test_console_navigation_preserves_drafts_history_and_collapsed_preference(landing_browser):
    browser, base = landing_browser
    page = _console_page(browser, base, width=1440)
    try:
        page.frame_locator("#frames iframe:not([hidden])").get_by_label("Draft").fill("keep this")
        page.locator('[data-tab="city"]').click()
        page.wait_for_url("**#city")
        page.go_back()
        assert (
            page.frame_locator("#frames iframe:not([hidden])").get_by_label("Draft").input_value()
            == "keep this"
        )
        page.go_forward()
        assert page.locator('[data-tab="city"]').get_attribute("aria-selected") == "true"
        page.locator("#navToggle").click()
        page.reload()
        assert page.locator("body").evaluate("el => el.classList.contains('nav-collapsed')")
        page.goto(base + "/site/console/index.html#worlds")
        assert (
            page.locator("#frames iframe:not([hidden])")
            .get_attribute("src")
            .endswith("research.html?tab=worlds")
        )
        page.goto(base + "/site/console/index.html#simviz?run=test&frame=17")
        assert (
            page.locator("#frames iframe:not([hidden])")
            .get_attribute("src")
            .endswith("analytics.html?run=test&frame=17")
        )
    finally:
        page.close()


@pytest.mark.parametrize("width", [1440, 1024, 768, 390, 320])
@pytest.mark.parametrize("language", ["zh-CN", "en"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_console_layout_across_languages_themes_and_widths(landing_browser, width, language, theme):
    browser, base = landing_browser
    page = _console_page(browser, base, width=width, role="member")
    try:
        page.locator("#worldChip").wait_for(state="visible")
        page.locator("#consoleTools > summary").click()
        page.locator("#lang-en-btn" if language == "en" else "#lang-zh-btn").click()
        page.wait_for_function("lang => document.documentElement.lang === lang", arg=language)
        page.locator("#themeMode").select_option(theme)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for selector in ("#worldSelect", "#worldManageBtn", "#crumbView", ".console-tools-panel"):
            box = page.locator(selector).bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, selector
        page.keyboard.press("Escape")
        assert page.locator(".console-bar").bounding_box()["height"] <= (120 if width <= 860 else 64)
    finally:
        page.close()


def test_home_desktop_tools_close_and_restore_focus(landing_browser):
    browser, base = landing_browser
    page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    try:
        page.goto(base)
        page.locator("#homeTools > summary").click()
        assert page.locator("#themeMode").is_visible()
        page.locator("#themeMode").select_option("dark")
        page.keyboard.press("Escape")
        assert page.locator("#homeTools > summary").evaluate("el => el === document.activeElement")
        assert not page.locator("#homeTools").evaluate("el => el.open")
        page.locator("#homeTools > summary").click()
        page.locator(".hero h1").click()
        assert not page.locator("#homeTools").evaluate("el => el.open")
    finally:
        page.close()


def test_console_world_controls_remain_directly_usable(landing_browser):
    browser, base = landing_browser
    page = _console_page(browser, base, role="member")
    try:
        page.locator("#worldManageBtn").click()
        assert page.locator("#worldDialog").evaluate("el => el.open")
        page.locator("#worldCloseBtn").click()
        assert page.locator("#worldManageBtn").evaluate("el => el === document.activeElement")
        with page.expect_request("**/api/worlds/select") as selected:
            page.locator("#worldSelect").select_option("")
        assert selected.value.post_data_json == {"id": ""}
    finally:
        page.close()


@pytest.mark.parametrize("mode", ["single", "accounts", "token_admin"])
@pytest.mark.parametrize("width", [1440, 390])
def test_workspace_uses_one_shell_in_every_mode(landing_browser, mode, width):
    browser, base = landing_browser
    page = browser.new_page(viewport={"width": width, "height": 900}, reduced_motion="reduce")
    page.set_default_timeout(4000)
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    user = {"id": 1, "nickname": "研究员", "role": "member", "email_verified": True}
    if mode == "token_admin":
        user.update(id=0, role="admin")

    def respond(route):
        path = urlsplit(route.request.url).path
        requests.append(path)
        data = {"mode": "single" if mode == "single" else "accounts"}
        if path == "/api/auth/me" and mode != "single":
            data["user"] = user
        elif path == "/api/worlds" and mode != "single":
            data.update(worlds=[], current=None)
        elif path == "/api/workspace/overview":
            data = {
                "user": user,
                "plans": [],
                "studies": [],
                "worlds": [],
                "usage": {"today": 0},
                "current_world": "",
            }
        route.fulfill(content_type="application/json", body=json.dumps(data))

    page.route("**/api/**", respond)
    try:
        page.goto(base + "/workspace")
        page.wait_for_url("**/console#workspace")
        workspace = page.frame_locator("#frames iframe:not([hidden])")
        workspace.locator("#app h1").wait_for()
        assert page.locator("#crumbView").inner_text() == "空间总览"
        assert workspace.locator(".topbar, .work-nav").count() == 0
        assert len(page.frames) == 2
        assert workspace.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
        if mode != "accounts":
            assert "/api/workspace/overview" not in requests
            assert workspace.locator('a[href="/console#dashboard"]').is_visible()
        else:
            assert "研究员" in workspace.locator("#app h1").inner_text()
        workspace.locator('a[href="/console#research"]').first.click()
        page.wait_for_url("**/console#research")
        page.go_back()
        page.wait_for_url("**/console#workspace")
        if mode != "accounts":
            page.goto(base + "/workspace?view=account&from=legacy")
            page.wait_for_url("**/console#account?from=legacy")
            private_view = page.frame_locator("#frames iframe:not([hidden])")
            private_view.get_by_role("heading", name="个人内容需要账号").wait_for()
            private_view.get_by_role("link", name="返回空间总览").click()
            page.wait_for_url("**/console#workspace")
            assert "/api/workspace/overview" not in requests
            page.locator("#consoleTools > summary").click()
            page.locator("#lang-en-btn").click()
            workspace.get_by_role("heading", name="Your next study starts here.").wait_for()
            page.locator("#themeMode").select_option("dark")
            workspace.locator('html[data-theme="dark"]').wait_for(state="attached")
        assert not errors
    finally:
        page.close()
