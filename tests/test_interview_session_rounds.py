"""Multi-city fan-out, round merging, and follow-up continuity.

``_run_city`` is stubbed: spawning a real child would need a real model and a
real city. What is exercised here is everything the parent owns — one child
per city, answers appended across rounds, prior Q&A handed to the next round,
and a city that dies not taking the others with it.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from gaworld.interview import session as session_mod
from gaworld.interview import store
from gaworld.interview.schema import Answer, Transcript


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_mod, "PROJECT_ROOT", tmp_path)
    # No summariser: the summary is an extra model call and its absence is
    # already covered in the aggregation tests.
    return tmp_path


def _respondents():
    return [
        {"kind": "agent", "city": "", "ref": "1", "label": "张三"},
        {"kind": "agent", "city": "绍兴", "ref": "7", "label": "李四"},
        {"kind": "cohort", "city": "绍兴", "ref": "c001", "label": "群体", "members": [1, 2, 3, 4]},
    ]


def _stub_cities(monkeypatch, answer_for=None, fail_cities=()):
    """Replace the child-process call with an in-process answer generator."""
    seen: list[str] = []

    def fake_run_city(*, session_id, round_no, slug, spec, material_payload, on_turn, on_stage=None):
        seen.append(slug)
        if on_stage:
            on_stage(f"准备 {slug or '默认世界'}")
        if slug in fail_cities:
            raise RuntimeError(f"{slug} 的子进程挂了")
        transcripts = []
        for respondent in spec.respondents:
            answers = []
            for question in spec.questions:
                on_turn(f"{respondent.label} {question.id}")
                if answer_for:
                    answers.append(answer_for(respondent, question, spec))
                else:
                    answers.append(Answer(question_id=question.id, text=f"{respondent.ref} 的答案"))
            transcripts.append(Transcript(respondent=respondent, answers=answers))
        return transcripts

    monkeypatch.setattr(session_mod, "_run_city", fake_run_city)
    return seen


def test_one_child_per_city(isolated_root, monkeypatch):
    seen = _stub_cities(monkeypatch)
    session_mod.run_round(
        {
            "title": "t",
            "questions": [{"text": "A"}],
            "respondents": _respondents(),
            "summarize": False,
        }
    )
    assert sorted(seen) == ["", "绍兴"]


def test_every_respondent_gets_a_transcript(isolated_root, monkeypatch):
    _stub_cities(monkeypatch)
    session = session_mod.run_round(
        {"title": "t", "questions": [{"text": "A"}], "respondents": _respondents(), "summarize": False}
    )
    assert set(session["transcripts"]) == {"agent::1", "agent:绍兴:7", "cohort:绍兴:c001"}


def test_a_failing_city_does_not_discard_the_others(isolated_root, monkeypatch):
    _stub_cities(monkeypatch, fail_cities={"绍兴"})
    session = session_mod.run_round(
        {"title": "t", "questions": [{"text": "A"}], "respondents": _respondents(), "summarize": False}
    )
    assert session["transcripts"]["agent::1"]["answers"][0]["text"] == "1 的答案"
    assert "子进程挂了" in session["transcripts"]["agent:绍兴:7"]["error"]
    # And the failure is on the record rather than only in a log.
    assert any("绍兴" in item for item in session["rounds"][0]["failures"])


def test_report_is_written_and_names_the_unreached_city(isolated_root, monkeypatch):
    _stub_cities(monkeypatch, fail_cities={"绍兴"})
    session = session_mod.run_round(
        {"title": "通勤调查", "questions": [{"text": "A"}], "respondents": _respondents(), "summarize": False}
    )
    markdown = store.load_report(session["id"])
    assert "# 通勤调查" in markdown
    assert "李四" in markdown
    assert "子进程挂了" in markdown


def test_second_round_appends_and_keeps_question_ids_distinct(isolated_root, monkeypatch):
    _stub_cities(monkeypatch)
    first = session_mod.run_round(
        {
            "title": "t",
            "questions": [{"text": "A"}, {"text": "B"}],
            "respondents": _respondents(),
            "summarize": False,
        }
    )
    second = session_mod.run_round(
        {"session_id": first["id"], "questions": [{"text": "C"}], "summarize": False}
    )
    ids = [q["id"] for q in second["questions"]]
    assert ids == ["q1", "q2", "q3"]
    assert [q["round"] for q in second["questions"]] == [1, 1, 2]
    assert len(second["transcripts"]["agent::1"]["answers"]) == 3
    assert len(second["rounds"]) == 2


def test_second_round_receives_the_first_rounds_answers(isolated_root, monkeypatch):
    """The continuous-memory requirement, at the orchestration seam."""
    captured: dict[str, object] = {}

    def answer_for(respondent, question, spec):
        if question.round == 2:
            captured["history"] = spec.history.get(respondent.uid)
            captured["history_questions"] = [q.text for q in spec.history_questions]
        return Answer(question_id=question.id, text=f"{question.id} 的答案")

    _stub_cities(monkeypatch, answer_for=answer_for)
    first = session_mod.run_round(
        {"title": "t", "questions": [{"text": "你住哪儿"}], "respondents": _respondents(), "summarize": False}
    )
    session_mod.run_round(
        {"session_id": first["id"], "questions": [{"text": "通勤远吗"}], "summarize": False}
    )
    assert captured["history_questions"] == ["你住哪儿"]
    assert captured["history"][0]["text"] == "q1 的答案"


def test_progress_reaches_one(isolated_root, monkeypatch):
    _stub_cities(monkeypatch)
    seen: list[float] = []
    session_mod.run_round(
        {"title": "t", "questions": [{"text": "A"}], "respondents": _respondents(), "summarize": False},
        report=lambda fraction, message: seen.append(fraction),
    )
    assert seen[-1] == pytest.approx(1.0)
    assert all(0.0 <= value <= 1.0 for value in seen)


def test_analysis_tallies_a_choice_question_across_cities(isolated_root, monkeypatch):
    def answer_for(respondent, question, spec):
        pick = "支持" if respondent.city == "绍兴" else "不支持"
        return Answer(question_id=question.id, choice=[pick])

    _stub_cities(monkeypatch, answer_for=answer_for)
    session = session_mod.run_round(
        {
            "title": "t",
            "questions": [{"text": "你支持吗", "kind": "choice", "options": ["支持", "不支持"]}],
            "respondents": _respondents(),
            "summarize": False,
        }
    )
    stats = session["analysis"]["questions"][0]["stats"]
    rows = {row["label"]: row for row in stats["rows"]}
    # 绍兴 contributes one individual plus a cohort of four.
    assert rows["支持"]["people"] == 5
    assert rows["不支持"]["people"] == 1
    assert "city" in session["analysis"]["questions"][0]["breakdown"]


def test_image_payloads_are_moved_out_of_the_session_file(isolated_root, monkeypatch):
    """session.json is read in full on every follow-up and every panel fetch."""
    import base64

    _stub_cities(monkeypatch)
    png = base64.b64encode(b"fake-png-bytes").decode("ascii")
    session = session_mod.run_round(
        {
            "title": "t",
            "questions": [
                {
                    "text": "看图说话",
                    "attachments": [
                        {
                            "kind": "image",
                            "value": f"data:image/jpeg;base64,{png}",
                            "caption": "一张工地照片",
                        }
                    ],
                }
            ],
            "respondents": _respondents(),
            "summarize": False,
        }
    )
    raw = (store.session_dir(session["id"]) / "session.json").read_text(encoding="utf-8")
    assert png not in raw, "the base64 payload is still inline"

    attachment = session["questions"][0]["attachments"][0]
    stored = pathlib.Path(attachment["value"])
    assert stored.is_file()
    assert stored.read_bytes() == b"fake-png-bytes"
    assert stored.suffix == ".jpg"
    # The caption survives — the report needs it, and it is the degradation path.
    assert attachment["caption"] == "一张工地照片"
    # And the session still loads: Attachment.from_dict rejects an empty value.
    assert store.session_questions(store.load_session(session["id"]))[0].attachments


def test_an_undecodable_image_keeps_its_record_rather_than_vanishing(isolated_root, monkeypatch):
    _stub_cities(monkeypatch)
    session = session_mod.run_round(
        {
            "title": "t",
            "questions": [
                {
                    "text": "看图说话",
                    "attachments": [{"kind": "image", "value": "!!!not-base64!!!", "caption": "说明"}],
                }
            ],
            "respondents": _respondents(),
            "summarize": False,
        }
    )
    assert session["questions"][0]["attachments"][0]["caption"] == "说明"


def test_child_env_pins_the_city_without_dropping_existing_overrides(monkeypatch):
    monkeypatch.setenv("GAWORLD_CONFIG_OVERRIDES", json.dumps({"sim_days": 3}))
    env = session_mod._child_env("绍兴柯桥")
    overrides = json.loads(env["GAWORLD_CONFIG_OVERRIDES"])
    assert overrides == {"sim_days": 3, "city": "绍兴柯桥"}


def test_child_env_survives_a_malformed_existing_override(monkeypatch):
    monkeypatch.setenv("GAWORLD_CONFIG_OVERRIDES", "{not json")
    overrides = json.loads(session_mod._child_env("x")["GAWORLD_CONFIG_OVERRIDES"])
    assert overrides == {"city": "x"}


def test_child_timeout_scales_with_the_work_not_the_wall_clock():
    small = session_mod._child_timeout(5, 4)
    large = session_mod._child_timeout(500, 4)
    assert large > small > session_mod.CHILD_STARTUP_SECONDS
    # More lanes means less wall-clock for the same work.
    assert session_mod._child_timeout(500, 8) < session_mod._child_timeout(500, 2)
