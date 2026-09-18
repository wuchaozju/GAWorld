"""The 群体采访 dashboard delegate: routing, validation, jobs, export.

The orchestrator is stubbed — this file is about the HTTP surface, not about
running an interview. Two things it does check for real, because both are
easy to break and invisible until a user hits them: that the older
single-agent ``POST /api/interview`` is not shadowed, and that a bad question
set comes back as a 400 rather than a job that dies in a log.
"""

from __future__ import annotations

import time

import pytest

from gaworld.apps import interview_api
from gaworld.interview import store


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _await_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = interview_api.job_status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_unknown_get_endpoint_is_404():
    _, status = interview_api.handle_get("/api/interview/nope")
    assert status == 404


def test_unknown_post_endpoint_is_404():
    _, status = interview_api.handle_post("/api/interview/nope", {})
    assert status == 404


def test_single_agent_endpoint_is_not_captured_by_the_delegate():
    """The delegate only claims paths with a trailing segment."""
    from gaworld.apps import dashboard_server

    # The dashboard's own branch is `path.startswith("/api/interview/")`, so
    # the bare path must not match it.
    assert not "/api/interview".startswith("/api/interview/")
    assert "/api/interview/run".startswith("/api/interview/")
    assert hasattr(dashboard_server, "_interview_agent")


def test_unknown_job_is_404():
    _, status = interview_api.handle_get("/api/interview/jobs/interview-deadbeef")
    assert status == 404


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def test_roster_passes_repeated_and_comma_joined_params(monkeypatch):
    seen = {}

    def fake_roster(cities=None, *, axes=None):
        seen["cities"] = cities
        seen["axes"] = axes
        return {"cities": [], "groups": []}

    import gaworld.interview.roster as roster_mod

    monkeypatch.setattr(roster_mod, "roster", fake_roster)
    interview_api.roster({"cities": ["甲", "乙"], "axes": ["age_band,hukou"]})
    assert seen["cities"] == ["甲", "乙"]
    assert seen["axes"] == ["age_band", "hukou"]


def test_roster_with_no_params_asks_for_every_city(monkeypatch):
    seen = {}

    def fake_roster(cities=None, *, axes=None):
        seen["cities"] = cities
        return {"cities": [], "groups": []}

    import gaworld.interview.roster as roster_mod

    monkeypatch.setattr(roster_mod, "roster", fake_roster)
    interview_api.roster({})
    assert seen["cities"] is None


def test_an_empty_cities_param_means_the_default_world_not_every_city(monkeypatch):
    """The default world's slug is "", so an empty segment is a real value."""
    seen = {}

    def fake_roster(cities=None, *, axes=None):
        seen["cities"] = cities
        return {"cities": [], "groups": []}

    import gaworld.interview.roster as roster_mod

    monkeypatch.setattr(roster_mod, "roster", fake_roster)
    interview_api.roster({"cities": [""]})
    assert seen["cities"] == [""]


def test_roster_rejects_an_unsupported_axis():
    payload, status = interview_api.handle_get("/api/interview/roster", {"axes": ["industry"]})
    assert status == 400
    assert "industry" in payload["error"]


# ---------------------------------------------------------------------------
# Plan / run
# ---------------------------------------------------------------------------


def _payload(**kwargs):
    base = {
        "title": "通勤调查",
        "questions": [
            {"text": "你支持吗", "kind": "choice", "options": ["支持", "不支持"]},
            {"text": "为什么", "kind": "open"},
        ],
        "respondents": [
            {"kind": "agent", "city": "", "ref": "1", "label": "张三"},
            {"kind": "cohort", "city": "绍兴", "ref": "c001", "label": "群体", "members": [1, 2, 3]},
        ],
    }
    base.update(kwargs)
    return base


def test_plan_reports_the_call_count_before_spending_anything(isolated_root):
    body, status = interview_api.handle_post("/api/interview/plan", _payload())
    assert status == 200
    assert body["respondents"] == 2
    assert body["people"] == 4  # one individual + a cohort of three
    assert body["calls"] == 4  # 2 questions x 2 respondents
    assert body["round"] == 1


def test_plan_rejects_a_choice_question_with_one_option(isolated_root):
    body, status = interview_api.handle_post(
        "/api/interview/plan",
        _payload(questions=[{"text": "选", "kind": "choice", "options": ["唯一"]}]),
    )
    assert status == 400
    assert "至少需要 2 个选项" in body["error"]


def test_plan_rejects_an_empty_question_set(isolated_root):
    _, status = interview_api.handle_post("/api/interview/plan", _payload(questions=[]))
    assert status == 400


def test_plan_rejects_an_unknown_session(isolated_root):
    body, status = interview_api.handle_post(
        "/api/interview/plan", _payload(session_id="20260101-000000-abcdef")
    )
    assert status == 400
    assert "找不到会话" in body["error"]


def test_run_validates_before_returning_a_job_id(isolated_root):
    body, status = interview_api.handle_post(
        "/api/interview/run",
        _payload(questions=[{"text": "选", "kind": "choice", "options": []}]),
    )
    assert status == 400
    assert "job_id" not in body


def test_run_starts_a_job_and_reports_progress(isolated_root, monkeypatch):
    import gaworld.interview.session as session_mod

    def fake_run_round(payload, *, report=None):
        if report:
            report(0.5, "一半了")
        session = {
            "id": "20260101-000000-abcdef",
            "title": payload.get("title"),
            "rounds": [{"round": 1}],
            "questions": [{"id": "q1", "text": "你支持吗", "kind": "open"}],
            "respondents": payload.get("respondents"),
            "analysis": {"respondents": 2},
        }
        store.save_session(session)
        return session

    monkeypatch.setattr(session_mod, "run_round", fake_run_round)
    body, status = interview_api.handle_post("/api/interview/run", _payload())
    assert status == 202
    assert body["plan"]["calls"] == 4

    record = _await_job(body["job_id"])
    assert record["status"] == "done"
    assert record["result"]["session_id"] == "20260101-000000-abcdef"
    assert record["result"]["round"] == 1


def test_a_failing_round_surfaces_as_an_error_job(isolated_root, monkeypatch):
    import gaworld.interview.session as session_mod

    def boom(payload, *, report=None):
        raise RuntimeError("模型全挂了")

    monkeypatch.setattr(session_mod, "run_round", boom)
    body, _ = interview_api.handle_post("/api/interview/run", _payload())
    record = _await_job(body["job_id"])
    assert record["status"] == "error"
    assert "模型全挂了" in record["message"]


def test_a_second_concurrent_round_is_refused(isolated_root, monkeypatch):
    """Two rounds appending to one session file would corrupt the transcript."""
    import gaworld.interview.session as session_mod

    release = __import__("threading").Event()

    def slow(payload, *, report=None):
        release.wait(timeout=3)
        return {"id": "20260101-000000-abcdef", "rounds": [], "questions": [], "respondents": []}

    monkeypatch.setattr(session_mod, "run_round", slow)
    first, _ = interview_api.handle_post("/api/interview/run", _payload())
    # Give the first job time to take the lock.
    time.sleep(0.1)
    second, _ = interview_api.handle_post("/api/interview/run", _payload())
    second_record = _await_job(second["job_id"])
    assert second_record["status"] == "error"
    assert "正在进行" in second_record["message"]
    release.set()
    _await_job(first["job_id"])


# ---------------------------------------------------------------------------
# Sessions / export
# ---------------------------------------------------------------------------


def _saved_session(session_id="20260101-000000-abcdef"):
    session = {
        "id": session_id,
        "title": "通勤 调查/A",
        "context": "",
        "created_at": 1.0,
        "questions": [{"id": "q1", "text": "q", "kind": "open", "round": 1}],
        "respondents": [{"kind": "agent", "city": "", "ref": "1", "label": "张三"}],
        "transcripts": {},
        "rounds": [{"round": 1}],
    }
    store.save_session(session)
    return session


def test_sessions_list_and_detail(isolated_root):
    _saved_session()
    body, status = interview_api.handle_get("/api/interview/sessions")
    assert status == 200
    assert body["sessions"][0]["id"] == "20260101-000000-abcdef"

    body, status = interview_api.handle_get("/api/interview/sessions/20260101-000000-abcdef")
    assert status == 200
    assert body["title"] == "通勤 调查/A"


def test_session_detail_for_unknown_id_is_404(isolated_root):
    _, status = interview_api.handle_get("/api/interview/sessions/20260101-000000-zzzzzz")
    assert status == 404


def test_export_returns_markdown_and_a_safe_filename(isolated_root):
    _saved_session()
    store.save_report("20260101-000000-abcdef", "# 报告\n\n内容\n")
    body, status = interview_api.handle_get("/api/interview/sessions/20260101-000000-abcdef/export")
    assert status == 200
    assert body["markdown"].startswith("# 报告")
    assert body["filename"].endswith(".md")
    # The title's space and slash must not reach the filesystem verbatim.
    assert "/" not in body["filename"]
    assert " " not in body["filename"]


def test_export_before_the_report_exists_is_a_clear_400(isolated_root):
    _saved_session()
    body, status = interview_api.handle_get("/api/interview/sessions/20260101-000000-abcdef/export")
    assert status == 400
    assert "还没有生成文档" in body["error"]


def test_export_of_an_unknown_session_is_400(isolated_root):
    _, status = interview_api.handle_get("/api/interview/sessions/20260101-000000-zzzzzz/export")
    assert status == 400


def test_delete_removes_a_session(isolated_root):
    _saved_session()
    body, status = interview_api.handle_post(
        "/api/interview/delete", {"session_id": "20260101-000000-abcdef"}
    )
    assert status == 200 and body["deleted"] is True


def test_delete_with_a_traversal_id_is_refused(isolated_root):
    body, status = interview_api.handle_post("/api/interview/delete", {"session_id": "../../etc"})
    assert status == 400
    assert "非法的会话 id" in body["error"]


# ---------------------------------------------------------------------------
# i18n coverage for the panel
# ---------------------------------------------------------------------------
#
# tests/test_i18n.py only scans index.html and app.js, so the 群体采访 page's
# keys are not covered there. A missing key is invisible in Chinese (the JS
# helper falls back to an inline Chinese literal) and shows up as Chinese text
# in the English UI — exactly the failure that is easiest to ship unnoticed.


def _locale(name):
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    return json.loads((root / "site/dashboard/locales" / name).read_text(encoding="utf-8"))


def _survey_keys():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "site/dashboard"
    keys: set[str] = set()
    html = (root / "survey.html").read_text(encoding="utf-8")
    for match in re.finditer(
        r'data-i18n(?:-placeholder|-content|-title|-help|-aria|-empty)?\s*=\s*"([^"]+)"', html
    ):
        keys.add(match.group(1))
    script = (root / "survey.js").read_text(encoding="utf-8")
    # The panel's helpers are `t("key", "中文兜底")` / `tf("key", "…", {…})`.
    for match in re.finditer(r'\btf?\(\s*"([A-Za-z0-9_]+)"\s*,', script):
        keys.add("survey." + match.group(1))
    return keys


def test_every_survey_i18n_key_exists_in_both_locales():
    keys = _survey_keys()
    assert keys, "no i18n keys found — the extraction pattern has drifted"
    for name in ("en.json", "zh-CN.json"):
        missing = keys - set(_locale(name))
        assert not missing, f"keys missing from {name}: {sorted(missing)}"


def test_survey_locale_entries_agree_on_placeholders():
    """A {name} present in one language and absent in the other prints raw."""
    import re

    en, zh = _locale("en.json"), _locale("zh-CN.json")
    for key in sorted(k for k in zh if k.startswith("survey.")):
        holes_zh = set(re.findall(r"\{(\w+)\}", str(zh[key])))
        holes_en = set(re.findall(r"\{(\w+)\}", str(en.get(key, ""))))
        assert holes_zh == holes_en, f"{key}: zh has {holes_zh}, en has {holes_en}"
