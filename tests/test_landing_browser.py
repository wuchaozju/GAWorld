"""Interaction contracts for the illustrated homepage, without model calls."""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def landing_browser():
    api = pytest.importorskip("playwright.sync_api")

    class LandingHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self.path = "/site/index.html"
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
