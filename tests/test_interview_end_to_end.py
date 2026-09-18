"""End-to-end: real child processes, real agents, a stub model endpoint.

Everything else in the interview suite stubs either the subprocess or the
simulator. This test stubs neither: it stands up a local OpenAI-compatible
HTTP server, points the config at it, and runs a real round — parent
orchestrator, real ``python -m gaworld.interview`` children, real
``build_agent``, real prompts, real parsing, real Markdown.

It is the only place that would catch the whole class of "the pieces are each
fine and the wiring is wrong": a child that inherits the wrong city, progress
events that never reach the parent, a spec the child cannot deserialize, or a
payload written to stdout where import noise eats it.

Marked ``slow`` because each child pays a full interpreter + simulator import.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

pytestmark = pytest.mark.slow


class _Handler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible chat endpoint.

    Answers by question text so the assertions can tell the two questions
    apart, and records every prompt so the test can prove the continuity
    replay really crossed the process boundary.
    """

    prompts: ClassVar[list[str]] = []
    lock: ClassVar[threading.Lock] = threading.Lock()

    def log_message(self, *args):  # silence the default stderr logging
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        content = payload["messages"][-1]["content"]
        prompt = content if isinstance(content, str) else content[0]["text"]
        with _Handler.lock:
            _Handler.prompts.append(prompt)

        # Branch on the question *currently* being asked, not on anything
        # anywhere in the prompt: continuity means a later prompt replays the
        # earlier questions verbatim, so a naive substring check answers
        # question 2 as if it were question 1.
        asked = prompt.split("【问题】", 1)[-1].split("【回答要求】", 1)[0]
        if "你支持吗" in asked:
            body = json.dumps({"choice": ["支持"], "reason": "通勤会快一些"}, ensure_ascii=False)
        elif "会搬走吗" in asked:
            body = json.dumps({"yes": False, "reason": "家在这里"}, ensure_ascii=False)
        elif "请写一段中文摘要" in prompt:
            body = "多数受访者支持，理由集中在通勤时间。"
        else:
            body = json.dumps({"answer": "我觉得还行，就是有点吵。"}, ensure_ascii=False)

        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": body}}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def stub_model():
    _Handler.prompts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    server.server_close()


@pytest.fixture
def wired(tmp_path, monkeypatch, stub_model):
    """Point the *child* processes at the stub model and a temp output tree."""
    from gaworld.interview import session as session_mod
    from gaworld.interview import store

    monkeypatch.setattr(store, "PROJECT_ROOT", tmp_path)
    overrides = {
        "llm": {
            "providers": {
                "stub": {
                    "type": "openai",
                    "base_url": stub_model,
                    "model": "stub-vision",
                    "api_key": "not-a-real-key",
                    "vision": True,
                }
            },
            "routing": {"default": "stub", "fallback": []},
        },
        # Keep the child's memory / vector store out of the developer's
        # output/ tree; the interview reads memory, and seeding the vector DB
        # writes a sqlite file.
        "memory_dir": str(tmp_path / "memory"),
        "vector_db_path": str(tmp_path / "memory" / "vector_db.sqlite"),
        "log_dir": str(tmp_path / "logs"),
    }
    monkeypatch.setenv("GAWORLD_CONFIG_OVERRIDES", json.dumps(overrides, ensure_ascii=False))
    monkeypatch.setenv("GAWORLD_IGNORE_LOCAL_CONFIG", "1")
    # The parent's own router was built at import time from the unpatched
    # config, so the summary call would hit the developer's real backend.
    monkeypatch.setattr(session_mod, "_summarizer", lambda provider: lambda prompt: "")
    return session_mod


def _respondents(count=2):
    from gaworld.interview.roster import agent_respondents, cohort_respondents

    people = agent_respondents("")[:count]
    cohorts = cohort_respondents("")[:1]
    if not people:
        pytest.skip("default world has no population on disk")
    return [item.to_dict() for item in people + cohorts]


def test_a_real_round_runs_through_a_child_process(wired):
    from gaworld.interview import store

    session = wired.run_round(
        {
            "title": "通勤调查",
            "context": "市里打算把 5 号线延到城西",
            "questions": [
                {"text": "你支持吗", "kind": "choice", "options": ["支持", "不支持"]},
                {"text": "你会搬走吗", "kind": "boolean"},
                {"text": "还有什么想说的", "kind": "open"},
            ],
            "respondents": _respondents(),
            "concurrency": 3,
            "summarize": False,
        }
    )

    # Every respondent answered every question.
    assert len(session["transcripts"]) == len(session["respondents"])
    for entry in session["transcripts"].values():
        assert entry["error"] == ""
        assert len(entry["answers"]) == 3

    # The typed answers parsed into countable form.
    stats = {item["question"]["id"]: item["stats"] for item in session["analysis"]["questions"]}
    choice_rows = {row["label"]: row for row in stats["q1"]["rows"]}
    assert choice_rows["支持"]["respondents"] == len(session["respondents"])
    assert choice_rows["不支持"]["respondents"] == 0
    boolean_rows = {row["label"]: row for row in stats["q2"]["rows"]}
    assert boolean_rows["否"]["respondents"] == len(session["respondents"])

    # The document landed on disk and carries the answers verbatim.
    markdown = store.load_report(session["id"])
    assert "# 通勤调查" in markdown
    assert "通勤会快一些" in markdown
    assert "我觉得还行" in markdown


def test_continuity_survives_the_process_boundary(wired):
    """Question 3's prompt, built inside a child, must replay answers 1 and 2."""
    wired.run_round(
        {
            "title": "t",
            "questions": [
                {"text": "你支持吗", "kind": "choice", "options": ["支持", "不支持"]},
                {"text": "还有什么想说的", "kind": "open"},
            ],
            "respondents": _respondents(1),
            "concurrency": 1,
            "summarize": False,
        }
    )
    later = [p for p in _Handler.prompts if "还有什么想说的" in p]
    assert later, "the open question was never asked"
    assert any("通勤会快一些" in prompt for prompt in later), (
        "the earlier answer was not replayed into the later prompt"
    )


def test_a_second_round_replays_the_first_rounds_answers(wired):
    first = wired.run_round(
        {
            "title": "t",
            "questions": [{"text": "你支持吗", "kind": "choice", "options": ["支持", "不支持"]}],
            "respondents": _respondents(1),
            "concurrency": 1,
            "summarize": False,
        }
    )
    _Handler.prompts = []
    second = wired.run_round(
        {
            "session_id": first["id"],
            "questions": [{"text": "还有什么想说的", "kind": "open"}],
            "summarize": False,
        }
    )
    assert [q["round"] for q in second["questions"]] == [1, 2]
    assert any("你支持吗" in prompt for prompt in _Handler.prompts), (
        "round 2 did not carry round 1's question into the prompt"
    )


def test_an_image_reaches_the_model_as_an_image_part(wired):
    import base64

    png = base64.b64encode(b"fake-png-bytes").decode("ascii")
    wired.run_round(
        {
            "title": "t",
            "questions": [
                {
                    "text": "还有什么想说的",
                    "kind": "open",
                    "attachments": [
                        {
                            "kind": "image",
                            "value": f"data:image/png;base64,{png}",
                            "caption": "一张工地照片",
                        }
                    ],
                }
            ],
            "respondents": _respondents(1),
            "concurrency": 1,
            "summarize": False,
        }
    )
    asked = [p for p in _Handler.prompts if "还有什么想说的" in p]
    assert asked
    # The prompt tells the model a picture came along, rather than pretending
    # the caption is the picture.
    assert any("见本次附带的图像" in prompt for prompt in asked)


def test_the_selected_city_does_not_leak_into_the_child(wired, monkeypatch):
    """A child must interview the city it was given, not the config's default."""
    from gaworld.city.bundle import list_cities
    from gaworld.interview.roster import agent_respondents

    bundles = [b for b in list_cities() if agent_respondents(b.slug)]
    if not bundles:
        pytest.skip("no populated city bundle on disk")
    slug = bundles[0].slug
    respondent = agent_respondents(slug)[0]

    session = wired.run_round(
        {
            "title": "t",
            "questions": [{"text": "还有什么想说的", "kind": "open"}],
            "respondents": [respondent.to_dict()],
            "concurrency": 1,
            "summarize": False,
        }
    )
    entry = session["transcripts"][respondent.uid]
    assert entry["error"] == ""
    assert entry["answers"][0]["text"]
    # The persona was built from that city's own population. The label is
    # city-qualified ("绍兴柯桥·闫然（35岁·男）"), so pull the bare name out of it.
    name = respondent.label.split("（")[0].split("·")[-1]
    asked = [p for p in _Handler.prompts if "还有什么想说的" in p]
    assert any(name in prompt for prompt in asked)


def test_env_overrides_from_the_parent_reach_the_child(wired):
    """The stub model only answers because the parent's overrides survived."""
    session = wired.run_round(
        {
            "title": "t",
            "questions": [{"text": "还有什么想说的", "kind": "open"}],
            "respondents": _respondents(1),
            "concurrency": 1,
            "summarize": False,
        }
    )
    assert _Handler.prompts, "the child never reached the stub endpoint"
    entry = next(iter(session["transcripts"].values()))
    assert entry["answers"][0]["text"] == "我觉得还行，就是有点吵。"
    assert os.environ.get("GAWORLD_CONFIG_OVERRIDES")
