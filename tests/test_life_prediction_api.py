"""The 人生预测 (life prediction) dashboard delegate: routing, the three
operator inputs, jobs, and the two things that must *not* happen.

Behaviours worth pinning down, because each one was a real decision rather
than an accident:

* ``POST /api/agents/<id>/life-prediction`` returns a 202 with a job id — the
  document is one 20k-character model call and must not block the request
  thread.
* The three inputs (人生大致走向 / 人生随机性 / 时代动荡性) reach the prompt,
  and the two knobs reach it as a *band of prose*, not as a bare number: the
  model has no intuition about "randomness 73".
* The prediction is **not** folded into the resident's long-term memory. A
  autobiography is a fact about the past; a prediction is a hypothesis about
  the future, and a resident that reads its own forecast as settled truth
  would act it out.
* The knobs are clamped: a body that sends ``"90"`` and one that sends ``90``
  must mean the same thing, and a junk value must fall back to the neutral
  middle rather than to zero.
"""

from __future__ import annotations

import os
import pathlib
import time

import pytest

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_unknown_get_endpoint_is_404():
    from gaworld.apps import life_prediction_api

    _, status = life_prediction_api.handle_get("/api/life-prediction/nope")
    assert status == 404


def test_unknown_post_endpoint_is_404():
    from gaworld.apps import life_prediction_api

    _, status = life_prediction_api.handle_post("/api/life-prediction/nope", {})
    assert status == 404


def test_invalid_agent_id_is_400():
    from gaworld.apps import life_prediction_api

    _, status = life_prediction_api.handle_post("/api/agents/not-a-number/life-prediction", {})
    assert status == 400
    _, status = life_prediction_api.handle_get("/api/agents/not-a-number/life-prediction")
    assert status == 400


# ---------------------------------------------------------------------------
# Job dispatch
# ---------------------------------------------------------------------------


def _wait_for_job(job_id, timeout=5.0):
    from gaworld.apps import life_prediction_api

    deadline = time.time() + timeout
    while time.time() < deadline:
        record = life_prediction_api.job_status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def test_post_returns_202_with_job_id(monkeypatch, tmp_path):
    """POST must hand out a job id and let the caller poll — even if the
    model call were instantaneous, a synchronous handler would couple the
    studio panel to the LLM's total render time."""
    from gaworld.apps import life_prediction_api

    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))

    def fast_compose(agent_id, **kwargs):
        path = os.path.join(str(tmp_path), f"agent_{agent_id}.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# X 的人生预测\n\n" + "我" * 20000)
        return {
            "agent_id": agent_id,
            "name": "X",
            "markdown": "我" * 20000,
            "length": 20000,
            "length_cjk": 20000,
            "path": path,
            "profile_block_size": 0,
        }

    monkeypatch.setattr(life_prediction_api, "compose", fast_compose)
    payload, status = life_prediction_api.handle_post("/api/agents/12/life-prediction", {})
    assert status == 202
    assert "job_id" in payload
    record = _wait_for_job(payload["job_id"])
    assert record["status"] == "done"
    assert record["result"]["agent_id"] == 12


def test_post_returns_409_when_already_running(monkeypatch):
    """Two parallel compose calls for the same agent must not race — the
    second is rejected with a clean BUSY error so the panel can show a clear
    "已经在生成中" toast."""
    import threading

    from gaworld.apps import life_prediction_api

    started = threading.Event()

    def slow_compose(_agent_id, **kwargs):
        started.set()
        time.sleep(0.5)
        return {
            "agent_id": _agent_id,
            "name": "X",
            "markdown": "我",
            "length": 1,
            "length_cjk": 1,
            "path": "/tmp/x.md",
            "profile_block_size": 0,
        }

    monkeypatch.setattr(life_prediction_api, "compose", slow_compose)
    payload, status = life_prediction_api.handle_post("/api/agents/12/life-prediction", {})
    assert status == 202
    started.wait(timeout=2.0)
    _, second = life_prediction_api.handle_post("/api/agents/12/life-prediction", {})
    assert second == 409
    _wait_for_job(payload["job_id"])


def test_job_status_returns_none_for_unknown_id():
    from gaworld.apps import life_prediction_api

    assert life_prediction_api.job_status("does-not-exist") is None


# ---------------------------------------------------------------------------
# The three inputs
# ---------------------------------------------------------------------------


def test_clamp_scale_clamps_and_defaults():
    """A slider sends a number, a hand-written body sends a string, and a
    broken body sends nothing — all three must land on a sane 0–100 value."""
    from gaworld.apps import life_prediction_api

    assert life_prediction_api._clamp_scale(90) == 90
    assert life_prediction_api._clamp_scale("73") == 73
    assert life_prediction_api._clamp_scale(73.6) == 74
    assert life_prediction_api._clamp_scale(-5) == 0
    assert life_prediction_api._clamp_scale(500) == 100
    # A missing or junk knob means "no preference", not "nothing can go wrong".
    assert life_prediction_api._clamp_scale(None) == 50
    assert life_prediction_api._clamp_scale("abc") == 50
    assert life_prediction_api._clamp_scale(float("nan")) == 50


def test_bands_cover_the_whole_scale():
    """Every knob value must land in a band, and the bands must read
    differently — a scale where the extremes say the same thing is a scale
    that does nothing."""
    from gaworld.apps import life_prediction_api

    seen = set()
    for value in range(0, 101, 10):
        label, meaning = life_prediction_api._band(value)
        assert label and meaning
        seen.add(meaning)
    assert len(seen) >= 4


def test_compose_passes_the_three_inputs_into_the_prompt(monkeypatch, tmp_path):
    """人生大致走向 must reach the model verbatim, and the two knobs must
    reach it as a band of prose rather than as a bare number."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    captured: list[dict] = []

    def fake_call_llm(prompt, **kwargs):
        captured.append({"prompt": prompt, **kwargs})
        return "# 测试居民 的人生预测\n\n## 我出发的那些年\n我先去了南方。"

    monkeypatch.setattr(providers, "call_llm", fake_call_llm)

    from gaworld.apps import life_prediction_api

    payload = life_prediction_api.compose(12, direction="去南方做制造业管理", randomness=85, turbulence=20)
    assert payload["agent_id"] == 12
    assert payload["name"] == "测试居民"
    assert payload["direction"] == "去南方做制造业管理"
    assert payload["randomness"] == 85
    assert payload["turbulence"] == 20
    assert payload["markdown"].startswith("# 测试居民 的人生预测")
    assert os.path.exists(payload["path"])

    prompt = captured[0]["prompt"]
    assert "去南方做制造业管理" in prompt
    assert "85/100" in prompt
    assert "20/100" in prompt
    # The dossier still grounds the prediction in the same evidence the
    # autobiography uses.
    for needle in ["杭州", "Big Five", "清晨在西湖边散步", "开一家小店"]:
        assert needle in prompt, f"missing from prompt: {needle!r}"
    assert captured[0]["task"] == "life_prediction"
    assert captured[0]["agent_id"] == 12
    assert captured[0]["max_tokens"] >= 20_000


def test_direction_is_optional(monkeypatch, tmp_path):
    """No 人生大致走向 means "let the dossier decide", and the prompt has to
    say so — an empty string must not reach the model as a blank order."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    captured: list[dict] = []

    def fake_call_llm(prompt, **kwargs):
        captured.append({"prompt": prompt, **kwargs})
        return "# 测试居民 的人生预测\n\n## 晚年\n我老了。"

    monkeypatch.setattr(providers, "call_llm", fake_call_llm)

    from gaworld.apps import life_prediction_api

    life_prediction_api.compose(12)
    prompt = captured[0]["prompt"]
    assert "使用者未指定" in prompt


def test_compose_handles_empty_markdown(monkeypatch, tmp_path):
    """If the LLM returned nothing, ``compose`` raises rather than writing an
    empty file — the job runner turns that into a clean error status."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: "")

    from gaworld.apps import life_prediction_api

    with pytest.raises(RuntimeError, match="没有返回人生预测内容"):
        life_prediction_api.compose(12)

    assert not (tmp_path / "agent_12.md").exists()


def test_compose_strips_code_fences(monkeypatch, tmp_path):
    """Some LLMs wrap the entire body in ```markdown … ``` fences; those
    must not survive into the saved file."""
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    fenced = "```markdown\n# 测试居民 的人生预测\n\n## 晚年\n我老了。\n```"
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: fenced)

    from gaworld.apps import life_prediction_api

    payload = life_prediction_api.compose(12)
    assert payload["markdown"].startswith("# 测试居民 的人生预测")
    assert "```" not in payload["markdown"]


# ---------------------------------------------------------------------------
# Side effects — what the prediction must NOT do
# ---------------------------------------------------------------------------


def test_compose_does_not_write_to_memory(monkeypatch, tmp_path):
    """The prediction is read-only on purpose.

    The autobiography folds a summary of itself into the resident's
    long-term memory, because it is a fact about the past. A prediction is a
    hypothesis about the future: a resident that read its own forecast as
    settled truth would simply act it out, and the simulation would start
    from the answer it was supposed to be testing.
    """
    import gaworld.apps.residents as residents_mod
    import gaworld.llm.providers as providers

    monkeypatch.setattr(residents_mod, "agent_detail", lambda agent_id: _stub_dashboard_detail(agent_id))
    monkeypatch.setattr(residents_mod, "agent_big5", lambda agent_id: _stub_big5(agent_id))
    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))

    written: list = []
    monkeypatch.setattr(residents_mod, "append_agent_memory", lambda *a, **kw: written.append((a, kw)))
    monkeypatch.setattr(providers, "call_llm", lambda *a, **kw: "# 测试居民 的人生预测\n\n## 晚年\n我老了。")

    from gaworld.apps import life_prediction_api

    life_prediction_api.compose(12)
    assert written == [], "the prediction must not touch the resident's memory"


def test_get_latest_artefact(monkeypatch, tmp_path):
    """``GET /api/agents/<id>/life-prediction`` returns the cached file even
    after the original job has been GC'd."""
    from gaworld.apps import life_prediction_api

    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    body = "# X 的人生预测\n\n" + "我" * 100
    path = os.path.join(str(tmp_path), "agent_12.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)

    out, status = life_prediction_api.handle_get("/api/agents/12/life-prediction")
    assert status == 200
    assert out["from_cache"] is True
    assert out["markdown"] == body


def test_get_latest_artefact_404_when_no_file(monkeypatch, tmp_path):
    from gaworld.apps import life_prediction_api

    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    _, status = life_prediction_api.handle_get("/api/agents/12/life-prediction")
    assert status == 404


def test_download_streams_the_saved_file(monkeypatch, tmp_path):
    """The download endpoint hands the panel a real file, not a JSON
    wrapper — that is what lets the browser save it directly."""
    from gaworld.apps import life_prediction_api

    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    body = "# X 的人生预测\n\n" + "我" * 50
    with open(os.path.join(str(tmp_path), "agent_12.md"), "w", encoding="utf-8") as handle:
        handle.write(body)

    filename, content_type, payload, status = life_prediction_api.handle_download(
        "/api/agents/12/life-prediction/download"
    )
    assert status == 200
    assert filename == "agent-12-life-prediction.md"
    assert content_type.startswith("text/markdown")
    assert payload == body


def test_download_404_when_nothing_saved(monkeypatch, tmp_path):
    from gaworld.apps import life_prediction_api

    monkeypatch.setattr("gaworld.apps.life_prediction_api._OUTPUT_DIR", str(tmp_path))
    _, _, _, status = life_prediction_api.handle_download("/api/agents/12/life-prediction/download")
    assert status == 404


def test_dashboard_router_mounts_life_prediction_routes():
    """The dashboard handler must wire up the POST (enqueue) and the GET
    (cache + jobs + download) endpoints — otherwise the panel's button hits
    a 404 instead of starting the job."""
    import gaworld.apps.dashboard_server as ds

    src = pathlib.Path(ds.__file__).read_text(encoding="utf-8")
    assert "life_prediction_api.handle_get" in src
    assert "life_prediction_api.handle_post" in src
    assert "life_prediction_api.handle_download" in src
    # The jobs sub-route must come first in the GET handler so it is not
    # shadowed by the "endswith /life-prediction" branch.
    assert src.find("/life-prediction/jobs/") < src.find('endswith("/life-prediction")')
    # The download branch must come ahead of the JSON cache branch.
    assert src.find("/life-prediction/download") < src.find('endswith("/life-prediction")')


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _stub_dashboard_detail(agent_id: int) -> dict:
    return {
        "identity": {
            "id": agent_id,
            "name": "测试居民",
            "gender": "女",
            "age": 32,
            "hukou": "杭州",
            "residence": "杭州",
        },
        "state": {"emotion": 0.6, "stress": 0.4},
        "profile_text": "## 职业与工作节奏\n设计师。\n## 性格\n温和但坚定。",
        "memory": {
            "long_term": [
                {"day": 1, "time": "10:00", "text": "清晨在西湖边散步。"},
                {"day": 2, "time": "18:00", "text": "傍晚与朋友吃了顿饭。"},
            ],
            "habits": [],
            "intentions": {"goal_1": "完成设计稿"},
            "schedule": [],
        },
        "goals": {
            "long_term": [{"title": "开一家小店", "progress": 0.3, "domain": "career"}],
            "medium_term": [],
            "short_term": [],
        },
        "social": {
            "relations": [{"name": "小明", "role": "朋友", "tier": "inner", "closeness": 0.8, "trust": 0.7}]
        },
        "finance": {
            "income_monthly": 12000,
            "expense_monthly": 8000,
            "savings": 50000,
            "debt": 0,
            "job_label": "设计师",
        },
        "home": {},
    }


def _stub_big5(agent_id: int) -> dict:
    return {
        "id": agent_id,
        "name": "测试居民",
        "values": {"O": 0.8, "C": 0.6, "E": -0.2, "A": 0.4, "N": -0.1},
        "authored": {"O": 0.5, "C": 0.4, "E": -0.3, "A": 0.4, "N": -0.2},
        "source": "sampled_authored",
        "paragraph": "她好奇而克制。",
        "consistency": 0.85,
        "poles": {},
        "names": {"O": "开放性", "C": "尽责性", "E": "外向性", "A": "宜人性", "N": "神经质"},
        "floor": 0.5,
        "clip": 2.5,
    }
