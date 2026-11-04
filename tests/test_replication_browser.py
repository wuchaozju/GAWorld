"""Custom survey sample sizes reach the run API; invalid input never starts a job."""

import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from gaworld.research.replication import normalize_spec
from tests.test_replication import RAW_SPEC

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width", [1440, 390])
def test_custom_sample_size_in_research_workbench(width):
    playwright = pytest.importorskip("playwright.sync_api")
    spec = normalize_spec(RAW_SPEC)
    runs = []
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if path.startswith("/api/"):
                    data = {}
                    if path == "/api/worlds":
                        data = {"mode": "accounts", "current": {"id": "owned-test-world"}}
                    elif path == "/api/research/replication":
                        data = {"runs": [], "min_sample": 7, "max_sample": 75, "default_sample": 30}
                    elif path.endswith("/replication/extract"):
                        data = {"job_id": "extract-test"}
                    elif path.endswith("/replication/jobs/extract-test"):
                        data = {"status": "done", "result": {"spec": spec}}
                    elif path.endswith("/replication/run"):
                        runs.append(request.post_data_json)
                        data = {"job_id": "run-test"}
                    elif path.endswith("/replication/jobs/run-test"):
                        data = {"status": "error", "error": "Mock job: no model calls"}
                    return route.fulfill(json=data)
                file = (ROOT / path.lstrip("/")).resolve()
                if file.is_relative_to(ROOT) and file.is_file():
                    return route.fulfill(
                        body=file.read_bytes(),
                        content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                    )
                return route.abort()

            page.route("**/*", serve)
            page.goto("http://gaworld.test/site/dashboard/research.html?tab=replication")
            page.locator("#rpText").fill("Mock paper")
            page.locator("#rpExtract").click()
            page.wait_for_function("!document.getElementById('rpExtract').disabled")
            assert page.locator("#rpRunCard").is_visible(), (
                errors,
                page.locator("#rpExtractProgress").inner_text(),
                page.locator("#rpProgress").inner_text(),
            )
            page.locator("#rpRunCard").wait_for(timeout=5000)
            assert errors == []
            sample = page.locator("#rpSample")
            assert sample.get_attribute("type") == "number"
            sample.wait_for(timeout=5000)
            assert sample.input_value() == "30"
            assert sample.get_attribute("min") == "7"
            assert sample.get_attribute("max") == "75"
            assert page.locator("#rpSamplePresets option").evaluate_all(
                "options => options.map(option => Number(option.value))"
            ) == [10, 20, 30, 50]
            sample.fill("37")
            page.evaluate("window.setLocale('en', false)")
            assert sample.input_value() == "37"
            hint = page.locator("#rpSampleHint").inner_text()
            assert "7" in hint and "75" in hint
            assert "Enter any integer" in hint
            assert "{min}" not in hint and "{max}" not in hint
            if width == 390:
                page.evaluate("window.setLocale('zh-CN', false)")
            assert "37" in page.locator("#rpCost").inner_text()
            page.locator('input[name="rpDesign"][value="paired"]').check()
            assert "74" in page.locator("#rpCost").inner_text()
            for invalid in ["", "0", "6", "76", "3.5"]:
                sample.fill(invalid)
                page.locator("#rpRun").click()
                assert not runs
                assert not sample.evaluate("el => el.checkValidity()")
                assert page.locator("#rpProgress.is-error").inner_text()
            for valid in [7, 37, 75]:
                sample.fill(str(valid))
                with page.expect_request(lambda r: r.url.endswith("/replication/run")):
                    page.locator("#rpRun").click()
                page.wait_for_function("!document.getElementById('rpRun').disabled")
                assert runs[-1]["sample_size"] == valid
                assert runs[-1]["design"] == "paired"
            assert len(runs) == 3
            assert errors == []
            if directory := os.environ.get("GAWORLD_SAMPLE_SCREENSHOTS"):
                folder = Path(directory)
                folder.mkdir(parents=True, exist_ok=True)
                page.locator("#rpRunCard").screenshot(path=str(folder / f"sample-size-{width}.png"))
        finally:
            browser.close()
