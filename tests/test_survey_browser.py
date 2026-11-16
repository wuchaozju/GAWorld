"""Survey pages reconnect to the same paid job after gateway errors and reloads."""

import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
JOB_ID = "round-12345678"


@pytest.fixture
def survey_page():
    playwright = pytest.importorskip("playwright.sync_api")
    state = {"active": False, "mode": "running", "posts": 0, "polls": 0, "errors": [], "lose_post": False}
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: state["errors"].append(str(error)))

            def serve(route):
                request = route.request
                path = urlsplit(request.url).path
                if path.startswith("/api/"):
                    data = {}
                    if path == "/api/worlds":
                        data = {"mode": "accounts", "current": None}
                    elif path == "/api/interview/roster":
                        data = {"cities": [], "groups": [], "providers": []}
                    elif path == "/api/interview/jobs":
                        data = {"jobs": [{"id": JOB_ID, "status": "running"}] if state["active"] else []}
                    elif path == "/api/interview/run":
                        state["posts"] += 1
                        state["active"] = True
                        if state["lose_post"]:
                            return route.abort("connectionrefused")
                        data = {"job_id": JOB_ID, "plan": {"calls": 1}}
                    elif path == "/api/interview/jobs/" + JOB_ID:
                        state["polls"] += 1
                        if state["mode"] == "outage":
                            return route.fulfill(status=502, content_type="text/html", body="Bad Gateway")
                        if state["mode"] == "offline":
                            return route.abort("connectionrefused")
                        if state["mode"] == "done":
                            data = {"status": "done", "result": {"session_id": "saved-survey"}}
                        else:
                            data = {"status": "running", "progress": 0.4, "message": "Answering 4/10"}
                    elif path == "/api/interview/sessions/saved-survey":
                        data = {
                            "id": "saved-survey",
                            "title": "Recovered survey",
                            "respondents": [],
                            "rounds": [],
                        }
                    return route.fulfill(json=data)
                file = (ROOT / path.lstrip("/")).resolve()
                if file.is_relative_to(ROOT) and file.is_file():
                    return route.fulfill(
                        body=file.read_bytes(),
                        content_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                    )
                return route.abort()

            page.route("**/*", serve)
            yield page, state
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_survey_reconnects_and_resumes_without_resubmitting(survey_page, width):
    page, state = survey_page
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto("http://gaworld.test/site/dashboard/survey.html")
    page.wait_for_function("window.__gaworldSurvey && !window.__gaworldSurvey.state.busy")
    page.evaluate("""() => {
      const app = window.__gaworldSurvey;
      app.state.step = 2;
      app.state.picked = {'agent::1': {uid:'agent::1',kind:'agent',city:'',ref:'1',label:'Test resident'}};
      app.state.draft[0].text = 'Do you agree?';
      app.render();
    }""")
    page.locator("#svRun").click()
    page.wait_for_function("document.getElementById('svProgress').textContent.includes('4/10')")
    assert state["posts"] == 1
    state["mode"] = "outage"
    page.wait_for_function("document.getElementById('svProgress').textContent.includes('请勿重复提交')")
    assert page.locator("#svRun").is_disabled()
    assert page.evaluate("window.__gaworldSurvey.state.busy")
    assert "interview_job=" + JOB_ID in page.url
    state["mode"] = "running"
    page.reload()
    page.wait_for_function("document.getElementById('svProgress').textContent.includes('4/10')")
    assert page.evaluate("window.__gaworldSurvey.state.busy")
    state["mode"] = "offline"
    page.wait_for_function("document.getElementById('svProgress').textContent.includes('请勿重复提交')")
    assert page.evaluate("window.__gaworldSurvey.state.busy")
    state["mode"] = "done"
    page.wait_for_function("window.__gaworldSurvey.state.sessionId === 'saved-survey'")
    assert state["posts"] == 1
    assert "interview_job=" not in page.url
    assert page.evaluate("sessionStorage.length") == 0
    assert not page.evaluate("window.__gaworldSurvey.state.busy")
    assert page.locator("#svPanel").inner_text().find("Recovered survey") >= 0
    assert state["errors"] == []


def test_survey_discovers_an_active_job_when_post_response_was_lost(survey_page):
    page, state = survey_page
    state["active"] = True
    page.goto("http://gaworld.test/site/dashboard/survey.html")
    page.wait_for_function("document.getElementById('svProgress').textContent.includes('4/10')")
    assert state["posts"] == 0
    assert page.evaluate("window.__gaworldSurvey.state.busy")
    assert "interview_job=" + JOB_ID in page.url
    assert state["errors"] == []


def test_lost_submission_response_recovers_without_replaying_post(survey_page):
    page, state = survey_page
    state["lose_post"] = True
    page.goto("http://gaworld.test/site/dashboard/survey.html")
    page.wait_for_function("window.__gaworldSurvey && !window.__gaworldSurvey.state.busy")
    page.evaluate("""() => {
      const app = window.__gaworldSurvey;
      app.state.step = 2;
      app.state.picked = {'agent::1': {uid:'agent::1',kind:'agent',city:'',ref:'1',label:'Test resident'}};
      app.state.draft[0].text = 'Do you agree?';
      app.render();
    }""")
    page.locator("#svRun").click()
    page.wait_for_function("document.getElementById('svProgress').textContent.includes('4/10')")
    assert state["posts"] == 1
    assert page.locator("#svRun").is_disabled()
    assert page.evaluate("window.__gaworldSurvey.state.busy")
    assert state["errors"] == []
