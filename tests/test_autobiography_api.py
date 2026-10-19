"""The 自传 (autobiography) dashboard delegate: routing, materials, jobs.

Four behaviours we cover for real, because all four were either buggy or
silent at one point:

* ``POST /api/agents/<id>/autobiography`` returns a 202 with a job id, not
  a 200 — the LLM call is too long for a synchronous handler. Anything
  else starves the dashboard's request thread.
* The same path on ``GET`` returns the latest on-disk artefact so the
  user can come back to it without remembering the job id.
* Job sub-routes (``GET /api/agents/<id>/autobiography/jobs/<job_id>``)
  expose live progress and a 404 once the record is GC'd.
* The background compose is careful with the now-canonical
  ``residents.agent_detail`` home (the old ``dashboard_server._agent_detail``
  raises a deliberate ``AttributeError`` to catch stale callers).
"""

from __future__ import annotations

import os
import time

import pytest

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_unknown_get_endpoint_is_404():
    from gaworld.apps import autobiography_api

    _, status = autobiography_api.handle_get("/api/autobiography/nope")
    assert status == 404


def test_unknown_post_endpoint_is_404():
    from gaworld.apps import autobiography_api

    _, status = autobiography_api.handle_post("/api/autobiography/nope", {})
    assert status == 404


def test_invalid_agent_id_is_400():
    from gaworld.apps import autobiography_api

    _, status = autobiography_api.handle_post("/api/agents/not-a-number/autobiography", {})
    assert status == 400
    _, status = autobiography_api.handle_get("/api/agents/not-a-number/autobiography")
    assert status == 400


# ---------------------------------------------------------------------------
# Job dispatch
# ---------------------------------------------------------------------------


def _wait_for_job(job_id, timeout=5.0):
    from gaworld.apps import autobiography_api

    deadline = time.time() + timeout
    while time.time() < deadline:
        record = autobiography_api.job_status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def test_post_returns_202_with_job_id(monkeypatch, tmp_path):
    """POST must not block — even if the LLM were instantaneous, the route
    must hand out a job id and let the caller poll. Synchronous behaviour
    would couple the studio panel to the LLM's total render time."""
    from gaworld.apps import autobiography_api

    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))

    def fast_compose(agent_id):
        path = os.path.join(str(tmp_path), f"agent_{agent_id}.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# X 自传\n\n" + "我" * 20000)
        return {
            "agent_id": agent_id, "name": "X", "markdown": "我" * 20000,
            "length": 20000, "length_cjk": 20000, "path": path,
            "profile_block_size": 0,
        }

    monkeypatch.setattr(autobiography_api, "compose", fast_compose)
    payload, status = autobiography_api.handle_post("/api/agents/12/autobiography", {})
    assert status == 202
    assert "job_id" in payload
    record = _wait_for_job(payload["job_id"])
    assert record["status"] == "done"
    assert record["result"]["agent_id"] == 12


def test_post_returns_409_when_already_running(monkeypatch):
    """Two parallel compose calls for the same agent must not race the
    same materials — the second is rejected with a clean BUSY error so
    the panel can show a clear "已经在生成中" toast."""
    from gaworld.apps import autobiography_api

    started = threading_for_test()

    def slow_compose(_agent_id):
        started.set()
        time.sleep(0.5)
        return {
            "agent_id": _agent_id, "name": "X", "markdown": "我",
            "length": 1, "length_cjk": 1, "path": "/tmp/x.md",
            "profile_block_size": 0,
        }

    monkeypatch.setattr(autobiography_api, "compose", slow_compose)
    payload, status = autobiography_api.handle_post("/api/agents/12/autobiography", {})
    assert status == 202
    started.wait(timeout=2.0)
    # Second request, while the first is still inside compose
    _, second = autobiography_api.handle_post("/api/agents/12/autobiography", {})
    assert second == 409
    _wait_for_job(payload["job_id"])


def threading_for_test():
    import threading
    return threading.Event()


def test_job_status_returns_404_for_unknown_id():
    from gaworld.apps import autobiography_api
    assert autobiography_api.job_status("does-not-exist") is None


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def _stub_dashboard_detail(agent_id: int) -> dict:
    return {
        "identity": {
            "id": agent_id, "name": "测试居民", "gender": "女", "age": 32,
            "hukou": "杭州", "residence": "杭州",
        },
        "state": {"emotion": 0.6, "stress": 0.4},
        "profile_text": "## 职业与工作节奏\n设计师。\n## 性格\n温和但坚定。",
        "memory": {
            "long_term": [
                {"day": 1, "time": "10:00", "text": "清晨在西湖边散步。"},
                {"day": 2, "time": "18:00", "text": "傍晚与朋友吃了顿饭。"},
            ],
            "habits": [], "intentions": {"goal_1": "完成设计稿"}, "schedule": [],
        },
        "goals": {"long_term": [{"title": "开一家小店", "progress": 0.3, "domain": "career"}], "medium_term": [], "short_term": []},
        "social": {"relations": [{"name": "小明", "role": "朋友", "tier": "inner", "closeness": 0.8, "trust": 0.7}]},
        "finance": {"income_monthly": 12000, "expense_monthly": 8000, "savings": 50000, "debt": 0, "job_label": "设计师"},
        "home": {},
    }


def _stub_big5(agent_id: int) -> dict:
    return {
        "id": agent_id, "name": "测试居民",
        "values": {"O": 0.8, "C": 0.6, "E": -0.2, "A": 0.4, "N": -0.1},
        "authored": {"O": 0.5, "C": 0.4, "E": -0.3, "A": 0.4, "N": -0.2},
        "source": "sampled_authored", "paragraph": "她好奇而克制。",
        "consistency": 0.85, "poles": {}, "names": {"O": "开放性", "C": "尽责性", "E": "外向性", "A": "宜人性", "N": "神经质"},
        "floor": 0.5, "clip": 2.5,
    }


def test_compose_collects_every_signal_and_calls_llm(monkeypatch, tmp_path):
    """The LLM prompt must contain identity, Big Five, memory and goals —
    otherwise the biography degenerates into a vague profile rewrite."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    captured: list[dict] = []

    def fake_call_llm(prompt, **kwargs):
        captured.append({"prompt": prompt, **kwargs})
        return "# 测试居民 自传\n\n## 童年\n我出生在一个平凡的家庭。"

    monkeypatch.setattr(providers, "call_llm", fake_call_llm)

    from gaworld.apps import autobiography_api

    payload = autobiography_api.compose(12)
    assert payload["agent_id"] == 12
    assert payload["name"] == "测试居民"
    assert payload["length"] == len(payload["markdown"])
    assert payload["markdown"].startswith("# 测试居民 自传")
    assert payload["path"].startswith(str(tmp_path))
    assert os.path.exists(payload["path"])

    prompt = captured[0]["prompt"]
    for needle in ["杭州", "Big Five", "开放性", "清晨在西湖边散步", "开一家小店", "朋友"]:
        assert needle in prompt, f"missing from prompt: {needle!r}"

    assert captured[0]["task"] == "autobiography"
    assert captured[0]["agent_id"] == 12
    assert captured[0]["max_tokens"] >= 20_000


def test_compose_handles_empty_markdown(monkeypatch, tmp_path):
    """If the LLM returned nothing, ``compose`` should raise a RuntimeError
    rather than write an empty file — the job runner turns that into a
    clean error status the panel can surface."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: "")

    from gaworld.apps import autobiography_api

    with pytest.raises(RuntimeError, match="没有返回自传内容"):
        autobiography_api.compose(12)

    assert not (tmp_path / "agent_12.md").exists()


def test_compose_strips_code_fences(monkeypatch, tmp_path):
    """Some LLMs wrap the entire body in ```markdown … ``` fences; those
    must not survive into the saved file because they would render as a
    giant code block in the studio preview."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))

    fenced_body = "```markdown\n# 测试居民 自传\n\n## 童年\n我出生在杭州的小巷里。\n```"
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: fenced_body)

    from gaworld.apps import autobiography_api

    payload = autobiography_api.compose(12)
    assert not payload["markdown"].startswith("```")
    assert payload["markdown"].startswith("# 测试居民 自传")
    import re as _re
    assert _re.search(r"^```", payload["markdown"], _re.M) is None


def test_get_latest_artefact(monkeypatch, tmp_path):
    """``GET /api/agents/<id>/autobiography`` returns the cached file even
    after the original job has been GC'd — so the user can come back to
    the document without the polling session being live."""
    from gaworld.apps import autobiography_api

    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    body = "# X 自传\n\n" + "我" * 100
    path = os.path.join(str(tmp_path), "agent_12.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)

    out, status = autobiography_api.handle_get("/api/agents/12/autobiography")
    assert status == 200
    assert out["from_cache"] is True
    assert out["length"] == len(body)
    assert out["markdown"] == body


def test_get_latest_artefact_404_when_no_file(monkeypatch, tmp_path):
    from gaworld.apps import autobiography_api

    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    _, status = autobiography_api.handle_get("/api/agents/12/autobiography")
    assert status == 404


def test_dashboard_router_mounts_autobiography_routes():
    """The dashboard handler must wire up both the POST (enqueue) and the
    GET (cache + jobs) endpoints — otherwise the panel's button hits a
    404 instead of starting the job."""
    import gaworld.apps.dashboard_server as ds

    src = open(ds.__file__, encoding="utf-8").read()
    assert "/autobiography" in src
    assert "autobiography_api.handle_get" in src
    assert "autobiography_api.handle_post" in src
    assert "autobiography_api.handle_download" in src
    # The jobs sub-route must come first in the GET handler so it is not
    # shadowed by the cache-hit / "endswith /autobiography" branch.
    assert src.find("/autobiography/jobs/") < src.find('endswith("/autobiography")')
    # The download branch must come ahead of the JSON cache branch.
    assert src.find("/autobiography/download") < src.find('endswith("/autobiography")')


# ---------------------------------------------------------------------------
# Side effects — the panel keeps showing the essay after re-render, the
# download endpoint streams the file, and the essay feeds into long-term
# memory so the next simulation tick reads it.
# ---------------------------------------------------------------------------


def test_compose_appends_memory_summary(monkeypatch, tmp_path):
    """``compose`` must fold a distilled self-portrait into the resident's
    long-term memory so the next tick reads it as a stable fact. The summary
    is short on purpose: ~700 Chinese characters — enough to anchor
    self-image without bloating every subsequent cognition prompt."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))

    body = "# 测试居民 自传\n\n## 童年\n我出生在杭州的小巷里，母亲是小学老师。\n\n## 如今的我\n我在城西一家设计事务所工作。"
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: body)

    appended: list[dict] = []
    monkeypatch.setattr(
        residents_mod,
        "append_agent_memory",
        lambda agent_id, payload: appended.append({"agent_id": agent_id, "payload": payload}) or {
            "kind": "memory", "text": payload["text"], "count": 1, "long_term": [], "rag": {}
        },
    )

    import gaworld.accounts.ownership as ownership_mod
    from gaworld.apps import autobiography_api

    monkeypatch.setattr(ownership_mod, "spawn", lambda fn: fn)
    payload = autobiography_api.compose(12)
    assert appended, "compose should call append_agent_memory at least once"
    call = appended[0]
    assert call["agent_id"] == 12
    assert call["payload"]["kind"] == "memory"
    summary = call["payload"]["text"]
    assert summary.startswith("[自传 摘要]")
    assert "杭州" in summary  # carries the identity the LLM used
    assert "童年" in summary  # keeps chapter names as the essay's spine
    assert len(summary) <= autobiography_api._MEMORY_SUMMARY_CHARS + 5


def test_compose_survives_memory_failure(monkeypatch, tmp_path):
    """If the memory store refuses the summary (e.g. a stale world dir),
    ``compose`` must still write the markdown file. The next simulation
    tick can keep going; the user gets their essay back."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: "# X 自传\n\n我是一段长长的自传。" * 50)
    monkeypatch.setattr(residents_mod, "append_agent_memory", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated")))
    import gaworld.accounts.ownership as ownership_mod
    monkeypatch.setattr(ownership_mod, "spawn", lambda fn: fn)

    from gaworld.apps import autobiography_api
    payload = autobiography_api.compose(12)
    assert payload["markdown"].startswith("# X 自传")
    assert os.path.exists(payload["path"])


def test_handle_download_streams_markdown_file(monkeypatch, tmp_path):
    """``GET /api/agents/<id>/autobiography/download`` returns the saved
    markdown bytes plus a file name so the dashboard can answer with
    Content-Disposition. Status 200 carries the body; 404 carries None."""
    from gaworld.apps import autobiography_api

    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    body = "# X 自传\n\n" + "我" * 50
    path = os.path.join(str(tmp_path), "agent_12.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)

    filename, content_type, payload, status = autobiography_api.handle_download(
        "/api/agents/12/autobiography/download"
    )
    assert status == 200
    assert filename == "agent-12-autobiography.md"
    assert content_type == "text/markdown; charset=utf-8"
    assert payload == body


def test_handle_download_404_when_no_file(monkeypatch, tmp_path):
    from gaworld.apps import autobiography_api

    monkeypatch.setattr("gaworld.apps.autobiography_api._OUTPUT_DIR", str(tmp_path))
    _, _, _, status = autobiography_api.handle_download("/api/agents/12/autobiography/download")
    assert status == 404


def test_openapi_documents_autobiography_methods():
    """The dashboard uses ``openapi.allowed_methods`` to enforce 405 for
    methods the document does not list — the autobiography endpoints have
    to advertise every method the panel actually calls, or ``do_POST`` and
    ``do_GET`` start rejecting valid traffic with the wrong error message."""
    import gaworld.apps.openapi as openapi

    assert "POST" in openapi.allowed_methods("/api/agents/12/autobiography")
    assert "GET" in openapi.allowed_methods("/api/agents/12/autobiography")
    assert "GET" in openapi.allowed_methods("/api/agents/12/autobiography/download")
