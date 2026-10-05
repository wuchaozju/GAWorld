"""Research loop, phase two: run the worlds, then interview their residents.

See ``gaworld/research/survey.py`` and docs/proposals/2026-09-19-ai-social-scientist.md
§四. What a composite study adds is a measure of what residents *say* — on
the same 0–1 scale as the state metrics — scored per world after the run,
with each world's own memories and end-of-run state.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from gaworld.interview.local import read_final_states
from gaworld.research import backends, survey
from gaworld.research.evaluate import evaluate
from gaworld.research.protocol import Protocol, preflight, protocol_from_answer
from gaworld.research.report import render_study_markdown
from tests.test_research_study import fake_report

PLAN = {"id": "P1", "title": "补贴与信任", "language": "zh-CN"}


def _answer(**over):
    answer = {
        "title": "补贴与信任",
        "kind": "composite",
        "sim_days": 5,
        "conditions": [
            {"id": "baseline", "label": "基准", "role": "baseline", "events": []},
            {"id": "subsidy", "label": "补贴", "role": "treatment",
             "events": [{"day": 2, "time": "09:00", "name": "补贴", "description": "每户发放补贴"}]},
        ],
        "survey": {"context": "社区做个简短调查。", "questions": [
            {"id": "Q1", "text": "我信任市政府会处理好民生问题。", "kind": "scale"},
            {"id": "Q2", "text": "过去一周你的生活有没有变好？", "kind": "boolean"},
            {"id": "Q3", "text": "你最担心什么？", "kind": "open"},
        ]},
        "hypotheses": [
            {"id": "H1", "statement": "补贴提高信任", "measure": "survey.Q1", "treatment": "subsidy",
             "control": "baseline", "direction": "increase", "min_effect": 0.05},
            {"id": "H2", "statement": "补贴让人觉得生活变好", "measure": "Q2", "treatment": "subsidy",
             "control": "baseline", "direction": "increase", "min_effect": 0.05},
            {"id": "H3", "statement": "开放题不能计分", "measure": "survey.Q3", "treatment": "subsidy",
             "control": "baseline", "direction": "increase"},
        ],
        "validity": {"seeds": [42, 43], "placebo": True},
    }
    answer.update(over)
    return answer


def _transcript(aid, q1=None, q2=None):
    answers = []
    if q1 is not None:
        answers.append({"question_id": "Q1", "choice": [q1] if q1 else [], "unparsed": not q1})
    if q2 is not None:
        answers.append({"question_id": "Q2", "boolean": q2, "unparsed": q2 is None})
    return {"respondent": {"ref": str(aid)}, "answers": answers}


class TestSurveyBlock:
    def test_kinds_ids_and_the_default_scale(self):
        dropped = []
        block = survey.normalize_survey({"questions": [
            {"text": "A", "kind": "likert"}, {"text": "B", "type": "yesno"}, {"text": "C"},
            {"text": "D", "kind": "scale", "options": ["低", "中", "高"]}, {"text": ""},
        ]}, dropped=dropped)
        kinds = [(q["id"], q["kind"], len(q["options"])) for q in block["questions"]]
        assert kinds == [("Q1", "scale", 5), ("Q2", "boolean", 0), ("Q3", "open", 0), ("Q4", "scale", 3)]
        assert dropped and "为空" in dropped[0]["reason"]

    def test_only_countable_questions_become_measures(self):
        block = survey.normalize_survey(_answer()["survey"])
        assert sorted(survey.survey_measures(block)) == ["survey.Q1", "survey.Q2"]

    def test_scores_are_on_the_0_to_1_scale_and_unparsed_answers_do_not_count(self):
        block = survey.normalize_survey(_answer()["survey"])
        options = block["questions"][0]["options"]
        scores = survey.score(block, [
            _transcript(1, options[0], True), _transcript(2, options[-1], False),
            _transcript(3, options[2], True), _transcript(4, "", None),
        ])
        by_resident = scores["survey.Q1"].pop("by_resident")
        assert scores["survey.Q1"] == {"value": 0.5, "n": 3, "unparsed": 1, "asked": 4}
        assert by_resident == {"1": 0.0, "2": 1.0, "3": 0.5}
        assert scores["survey.Q2"]["value"] == round(2 / 3, 6)
        assert survey.score(block, [])["survey.Q1"]["value"] is None


class TestProtocol:
    def test_a_survey_makes_it_composite_and_hypotheses_can_use_it(self):
        protocol = protocol_from_answer(_answer(kind="parallel_worlds"), PLAN)
        assert protocol.kind == "composite"
        assert [h["measure"] for h in protocol.hypotheses] == ["survey.Q1", "survey.Q2"]
        assert any("survey.Q3" in d["reason"] for d in protocol.dropped)
        labels = {m["id"]: m["label"] for m in protocol.measures}
        assert labels["survey.Q1"].startswith("问卷 Q1")

    def test_preflight_counts_the_interviews_and_needs_a_countable_question(self):
        protocol = protocol_from_answer(_answer(), PLAN)
        result = preflight(protocol, default_agents=10, call_budget=10**6)
        # 10 residents × 3 questions × 3 worlds (placebo added) × 2 seeds.
        assert result["budget"]["survey_calls"] == 10 * 3 * 3 * 2
        assert result["ok"], result["errors"]
        bare = Protocol.from_dict({**protocol.to_dict(), "survey": {"questions": [
            {"id": "Q3", "text": "?", "kind": "open", "options": []}]}})
        assert any("可计分" in e for e in preflight(bare)["errors"])

    def test_without_a_survey_nothing_changes(self):
        answer = _answer(kind="parallel_worlds")
        answer.pop("survey")
        answer["hypotheses"] = [{"id": "H1", "measure": "stress", "treatment": "subsidy",
                                 "control": "baseline", "direction": "decrease", "min_effect": 0.01}]
        protocol = protocol_from_answer(answer, PLAN)
        assert protocol.kind == "parallel_worlds" and protocol.survey == {}


def _fake_seed(spec, seed, report):
    values = {"stress": {cond.id: [0.5, 0.5] for cond in spec.worlds}}
    return {"root": f"pw/s{seed}", "id": f"s{seed}", "status": "done", "report": fake_report(values)}


def _fake_survey(protocol, run, report):
    trust = {"baseline": 0.4, "subsidy": 0.7, "placebo": 0.41}
    return {wid: {"scores": {"survey.Q1": {"value": value, "n": 10, "unparsed": 0, "asked": 10},
                             "survey.Q2": {"value": None, "n": 0, "unparsed": 10, "asked": 10}}}
            for wid, value in trust.items()}


def _survey_per_resident(diffs):
    """Each resident answers 0.5 in the baseline and placebo, 0.5 + d under subsidy."""

    def block(answers):
        return {"scores": {"survey.Q1": {"value": sum(answers.values()) / len(answers), "n": len(answers),
                                         "unparsed": 0, "asked": len(answers), "by_resident": answers}}}

    def run_survey(protocol, run, report):
        base = {str(i): 0.5 for i in range(len(diffs))}
        treated = {str(i): 0.5 + d for i, d in enumerate(diffs)}
        return {"baseline": block(base), "subsidy": block(treated), "placebo": block(dict(base))}

    return run_survey


class TestRunAndJudge:
    def test_survey_scores_are_judged_like_any_measure(self):
        protocol = protocol_from_answer(_answer(), PLAN)
        runs = backends.run_protocol(protocol, run_seed=_fake_seed, run_survey=_fake_survey)
        assert all("survey" in run for run in runs)
        result = evaluate(protocol, runs)
        h1 = next(h for h in result["hypotheses"] if h["id"] == "H1")
        assert h1["verdict"] == "supported", h1["reasons"]
        assert round(h1["mean_effect"], 6) == 0.3
        h2 = next(h for h in result["hypotheses"] if h["id"] == "H2")
        assert h2["verdict"] == "unmeasured"
        issues = " ".join(i["issue"] for i in result["quality"]["issues"])
        assert "无法计分" in issues

    def test_the_same_residents_answers_are_paired_across_worlds(self):
        protocol = protocol_from_answer(_answer(), PLAN)
        runs = backends.run_protocol(protocol, run_seed=_fake_seed, run_survey=_survey_per_resident([0.25] * 10))
        h1 = next(h for h in evaluate(protocol, runs)["hypotheses"] if h["id"] == "H1")
        assert h1["verdict"] == "supported", h1["reasons"]
        paired = h1["effects"][0]["paired"]
        assert paired["n"] == 10 and paired["ate"] == 0.25 and paired["q_value"] < 0.05
        assert any("配对检验都在同一方向显著" in r for r in h1["reasons"])

    def test_a_few_residents_moving_a_lot_do_not_carry_the_verdict(self):
        # Mean +0.1 clears min_effect and the placebo, but only 2 of 10 residents moved.
        protocol = protocol_from_answer(_answer(), PLAN)
        runs = backends.run_protocol(protocol, run_seed=_fake_seed,
                                     run_survey=_survey_per_resident([0.5, 0.5] + [0.0] * 8))
        h1 = next(h for h in evaluate(protocol, runs)["hypotheses"] if h["id"] == "H1")
        assert round(h1["mean_effect"], 6) == 0.1
        assert h1["verdict"] == "inconclusive", h1["reasons"]
        assert any("降为 inconclusive" in r for r in h1["reasons"])

    def test_a_parallel_worlds_protocol_never_calls_the_survey(self):
        answer = _answer(kind="parallel_worlds")
        answer.pop("survey")
        answer["hypotheses"] = [{"id": "H1", "measure": "stress", "treatment": "subsidy",
                                 "control": "baseline", "direction": "decrease"}]
        protocol = protocol_from_answer(answer, PLAN)

        def boom(*_args):
            raise AssertionError("survey ran")

        runs = backends.run_protocol(protocol, run_seed=_fake_seed, run_survey=boom)
        assert all("survey" not in run for run in runs)

    def test_the_report_shows_the_questions_and_who_answered(self):
        protocol = protocol_from_answer(_answer(), PLAN)
        runs = backends.run_protocol(protocol, run_seed=_fake_seed, run_survey=_fake_survey)
        study = {"title": "t", "protocol": protocol.to_dict(), "runs": backends.slim_runs(runs),
                 "evaluation": evaluate(protocol, runs), "stage": "evaluated"}
        text = render_study_markdown(study)
        assert "我信任市政府会处理好民生问题" in text and "问卷作答" in text


class TestWorldInterview:
    def test_each_world_is_asked_with_its_own_overrides_and_final_state(self, tmp_path, monkeypatch):
        protocol = protocol_from_answer(_answer(), PLAN)
        root = "output/parallel_worlds/s42"
        worlds = {}
        for cond in protocol.conditions:
            wdir = os.path.join(root, "worlds", cond["id"])
            os.makedirs(tmp_path / wdir / "state")
            with open(tmp_path / wdir / "state" / "agent_state_history.csv", "w", encoding="utf-8") as fh:
                fh.write("agent_id,step,metric,value\n3,0,stress,0.5\n3,1,stress,0.2\n7,0,stress,0.4\n"
                         "1000001,0,stress,0.4\n")
            worlds[cond["id"]] = {"dir": wdir, "overrides": {"memory_dir": f"{wdir}/memory"},
                                  "state_csv": os.path.join(wdir, "state", "agent_state_history.csv")}
        os.makedirs(tmp_path / root, exist_ok=True)
        with open(tmp_path / root / "experiment.json", "w", encoding="utf-8") as fh:
            json.dump({"id": "s42", "root": root, "spec": {"agent_ids": []}, "worlds": worlds}, fh)
        seen = []

        def fake_run(cmd, cwd, env, capture_output, text, timeout):
            spec_path, out_path = cmd[cmd.index("--spec") + 1], cmd[cmd.index("--out") + 1]
            with open(spec_path, encoding="utf-8") as fh:
                spec = json.load(fh)
            seen.append((json.loads(env["GAWORLD_CONFIG_OVERRIDES"]), spec))
            options = spec["questions"][0]["options"]
            transcripts = [_transcript(int(r["ref"]), options[-1], True) for r in spec["respondents"]]
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump({"transcripts": transcripts}, fh)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(backends.subprocess, "run", fake_run)
        runner = backends.default_survey_runner(repo_root=str(tmp_path))
        result = runner(protocol, {"seed": 42, "root": root}, lambda p, m: None)
        assert set(result) == {cond["id"] for cond in protocol.conditions}
        assert result["subsidy"]["scores"]["survey.Q1"]["value"] == 1.0
        overrides, spec = seen[0]
        assert overrides["memory_dir"].endswith("/memory")
        # Promoted household members have no profile to interview from.
        assert [r["ref"] for r in spec["respondents"]] == ["3", "7"]
        assert spec["final_state_csv"].endswith("state/agent_state_history.csv")
        assert os.path.exists(tmp_path / root / "worlds" / "subsidy" / "survey.json")


def test_final_states_are_the_last_step_per_metric(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text("agent_id,step,metric,value\n3,0,stress,0.5\n3,2,stress,0.2\n3,1,stress,0.9\n"
                    "3,0,emotion,0.6\n", encoding="utf-8")
    assert read_final_states(str(path)) == {3: {"stress": 0.2, "emotion": 0.6}}
    assert read_final_states(str(tmp_path / "missing.csv")) == {}


# -- a real interview child per world ----------------------------------------


class _StubModel(BaseHTTPRequestHandler):
    """OpenAI-compatible endpoint that answers by the respondent's stress.

    Residents whose persona says ``压力0.20`` (the end state of the treated
    world below) agree and say yes; everyone else disagrees and says no. So
    the scores can only come out right if each child read its own world's
    final state.
    """

    prompts: ClassVar[list[str]] = []

    def log_message(self, *args):
        return

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
        content = payload["messages"][-1]["content"]
        prompt = content if isinstance(content, str) else content[0]["text"]
        _StubModel.prompts.append(prompt)
        calm = "压力0.20" in prompt
        asked = prompt.split("【问题】", 1)[-1].split("【回答要求】", 1)[0]
        if "信任市政府" in asked:
            body = {"choice": ["非常同意" if calm else "非常不同意"], "reason": "-"}
        elif "变好" in asked:
            body = {"yes": calm, "reason": "-"}
        else:
            body = {"answer": "物价。"}
        data = json.dumps({"choices": [{"message": {"role": "assistant",
                                                    "content": json.dumps(body, ensure_ascii=False)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.mark.slow
def test_each_world_child_answers_from_that_worlds_final_state(tmp_path, monkeypatch):
    from gaworld.interview.roster import agent_respondents

    refs = [int(item.ref) for item in agent_respondents("")[:2]]
    if not refs:
        pytest.skip("default world has no population on disk")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _StubModel.prompts = []
    monkeypatch.setenv("GAWORLD_IGNORE_LOCAL_CONFIG", "1")
    try:
        protocol = protocol_from_answer(_answer(), PLAN)
        root = tmp_path / "s42"
        worlds = {}
        for cond in protocol.conditions:
            wdir = root / "worlds" / cond["id"]
            (wdir / "state").mkdir(parents=True)
            stress = 0.2 if cond["id"] == "subsidy" else 0.9
            (wdir / "state" / "agent_state_history.csv").write_text(
                "agent_id,step,metric,value\n" + "".join(f"{aid},0,stress,0.5\n{aid},9,stress,{stress}\n" for aid in refs),
                encoding="utf-8")
            worlds[cond["id"]] = {"dir": str(wdir), "overrides": {
                "llm": {"providers": {"stub": {"type": "openai", "model": "stub", "api_key": "not-a-real-key",
                                               "base_url": f"http://127.0.0.1:{server.server_port}/v1"}},
                        "routing": {"default": "stub", "fallback": []}},
                "memory_dir": str(wdir / "memory"),
                "vector_db_path": str(wdir / "memory" / "vector_db.sqlite"),
                "log_dir": str(wdir / "logs"),
            }}
        (root / "experiment.json").write_text(
            json.dumps({"id": "s42", "root": str(root), "spec": {"agent_ids": refs}, "worlds": worlds}),
            encoding="utf-8")
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        runner = backends.default_survey_runner(repo_root=repo_root, timeout=300)
        result = runner(protocol, {"seed": 42, "root": str(root)}, lambda p, m: None)
    finally:
        server.shutdown()
        server.server_close()

    for cond in protocol.conditions:
        assert "error" not in result[cond["id"]], result[cond["id"]]
    expected = {"subsidy": 1.0, "baseline": 0.0, "placebo": 0.0}
    for world_id, value in expected.items():
        scores = result[world_id]["scores"]
        assert scores["survey.Q1"]["value"] == value, (world_id, scores)
        assert scores["survey.Q2"]["value"] == value, (world_id, scores)
        assert scores["survey.Q1"]["n"] == len(refs)
    assert any("压力0.20" in p for p in _StubModel.prompts)
    assert any("压力0.90" in p for p in _StubModel.prompts)
    assert (root / "worlds" / "subsidy" / "survey.json").exists()
