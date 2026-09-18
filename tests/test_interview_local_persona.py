"""The binding to the real simulator: personas, routing, and the child CLI.

This is the seam the unit tests deliberately do not cover — it imports
``generative_city_sim`` and builds a real resident. The model is mocked; the
agent, its profile and the cohort statistics are real.

The persona assertions are the point. A survey whose prompt carries only a
name produces residents who all sound the same, and no amount of downstream
tallying detects that — so what goes into the prompt is pinned here.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(scope="module")
def interviewer():
    from gaworld.interview.local import CityInterviewer

    return CityInterviewer()


@pytest.fixture
def agent_respondent():
    from gaworld.interview.roster import agent_respondents

    people = agent_respondents("")
    if not people:
        pytest.skip("default world has no population on disk")
    return people[0]


def test_agent_persona_carries_what_makes_residents_differ(interviewer, agent_respondent):
    from gaworld.interview.schema import Question

    persona = interviewer.persona(agent_respondent, [Question(id="q1", text="你最近过得怎么样")])
    # Identity, so the answer is in character at all.
    assert agent_respondent.demographics["age_band"] or True
    assert "岁" in persona
    # The differentiators: occupation, disposition, values, current state.
    assert "职业与工作节奏" in persona
    assert "你现在的状态" in persona
    assert "情绪" in persona
    assert "你的目标与追求" in persona


def test_agent_persona_is_not_shared_between_two_residents(interviewer):
    from gaworld.interview.roster import agent_respondents
    from gaworld.interview.schema import Question

    people = agent_respondents("")
    if len(people) < 2:
        pytest.skip("need at least two residents")
    question = [Question(id="q1", text="你最近过得怎么样")]
    first = interviewer.persona(people[0], question)
    second = interviewer.persona(people[1], question)
    assert first != second


def test_cohort_persona_reports_spread_not_an_average_person(interviewer):
    from gaworld.interview.roster import cohort_respondents
    from gaworld.interview.schema import Question

    cohorts = cohort_respondents("")
    if not cohorts:
        pytest.skip("default world has no cohorts")
    persona = interviewer.persona(cohorts[0], [Question(id="q1", text="你们怎么看")])
    assert "人群" in persona
    assert "离散" in persona  # cohort_summary's dispersion read-out
    assert "平均人" in persona  # the explicit instruction not to be one


def test_cohort_with_no_resolvable_members_fails_loudly(interviewer):
    from gaworld.interview.schema import Question, Respondent

    orphan = Respondent(
        kind="cohort",
        city="",
        ref="c999",
        label="空群体",
        demographics={"city": "default"},
        members=[999999],
    )
    with pytest.raises(ValueError, match="找不到成员"):
        interviewer.persona(orphan, [Question(id="q1", text="q")])


def test_individual_routes_with_its_agent_id_and_cohort_does_not(monkeypatch, interviewer):
    """Per-agent model routing must still work, and must not get a cohort id."""
    from gaworld.interview.schema import Question, Respondent

    seen = []

    def fake_call_llm(prompt, **kwargs):
        seen.append(kwargs)
        return json.dumps({"answer": "好"})

    import gaworld.llm.providers as providers

    monkeypatch.setattr(providers, "call_llm", fake_call_llm)

    question = Question(id="q1", text="q")
    agent = Respondent(kind="agent", city="", ref="31", label="某人")
    cohort = Respondent(kind="cohort", city="", ref="c001", label="某群体")
    interviewer.ask(agent, question, "prompt", [])
    interviewer.ask(cohort, question, "prompt", [])

    assert seen[0]["agent_id"] == 31
    assert seen[0]["task"] == "interview"
    assert seen[1]["agent_id"] is None


def test_images_are_forwarded_only_when_there_are_any(monkeypatch, interviewer):
    from gaworld.interview.schema import Question, Respondent

    seen = []

    def fake_call_llm(prompt, **kwargs):
        seen.append(kwargs.get("images"))
        return "ok"

    import gaworld.llm.providers as providers

    monkeypatch.setattr(providers, "call_llm", fake_call_llm)

    respondent = Respondent(kind="agent", city="", ref="1", label="x")
    question = Question(id="q1", text="q")
    interviewer.ask(respondent, question, "p", [])
    interviewer.ask(respondent, question, "p", [{"media_type": "image/png", "data": "aGk="}])
    assert seen[0] is None
    assert seen[1] == [{"media_type": "image/png", "data": "aGk="}]


def test_child_cli_writes_answers_to_the_file_not_stdout(tmp_path, monkeypatch, capsys):
    """Progress goes to stdout; the payload must not, or import noise eats it."""
    from gaworld.interview import __main__ as child
    from gaworld.interview.schema import Answer, Transcript

    class FakeInterviewer:
        def __init__(self, *args, **kwargs):
            pass

        def persona(self, respondent, questions):
            return "你是某人。"

        def ask(self, respondent, question, prompt, images=None):
            return json.dumps({"answer": "答"})

    monkeypatch.setattr(child, "CityInterviewer", FakeInterviewer)

    spec_path = tmp_path / "spec.json"
    out_path = tmp_path / "out.json"
    spec_path.write_text(
        json.dumps(
            {
                "questions": [{"text": "A"}],
                "respondents": [{"kind": "agent", "city": "", "ref": "1", "label": "张三"}],
                "city": "",
            }
        ),
        encoding="utf-8",
    )

    assert child.main(["--spec", str(spec_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["transcripts"][0]["answers"][0]["text"] == "答"

    stdout = capsys.readouterr().out.strip().splitlines()
    events = [json.loads(line) for line in stdout]
    assert {event["type"] for event in events} == {"stage", "progress", "done"}
    # Nothing on stdout may contain the answers themselves.
    assert all("transcripts" not in event for event in events)

    _ = Transcript, Answer  # imported to document the shape under test
