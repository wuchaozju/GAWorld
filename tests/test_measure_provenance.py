"""Every measure says where its numbers come from, and a (c) one is read for direction only.

See ``gaworld/research/measures.py`` and ``benchmark/MECHANISM_PROVENANCE.md``.
A measure's grade is the weakest among the mechanisms that produce it. The
verdict rules do not change with it; what changes is how an effect may be
read and cited — the evaluator, the report, the interpretation check and
the Bench scorecard all say it next to the number.
"""

from __future__ import annotations

from gaworld.research import measures, survey
from gaworld.research.evaluate import evaluate, measure_provenance
from gaworld.research.interpret import build_interpret_prompt, check_claims
from gaworld.research.protocol import Protocol, build_compile_prompt
from gaworld.research.report import render_study_markdown
from tests.test_research_study import PLAN, make_protocol, runs_for, series


def _supported_runs():
    return runs_for(
        (42, {**series(0.5, 0.4, 0.51), **series(0.5, 0.53, 0.5, metric="emotion")}),
        (43, {**series(0.52, 0.41, 0.515), **series(0.5, 0.54, 0.505, metric="emotion")}),
    )


class TestCatalogue:
    def test_every_measure_has_a_grade_and_says_what_drives_it(self):
        for measure in measures.registry().values():
            assert measure.grade in measures.GRADES, measure.id
            assert len(measure.basis) > 20, measure.id

    def test_today_every_measure_is_c_and_read_for_direction_only(self):
        assert {m.grade for m in measures.registry().values()} == {"c"}
        assert measures.direction_only("c") and not measures.direction_only("b")
        assert not measures.direction_only("a")
        # A protocol saved before grades existed is read the cautious way.
        assert measures.direction_only(None) and measures.direction_only("?")

    def test_the_core_states_name_the_model_call_that_moves_them(self):
        reg = measures.registry()
        assert "infer_event_effect" in reg["econ_security"].basis
        assert "账本" in reg["econ_security"].basis
        assert "关键词" in reg["stance_score"].basis
        assert "−1–1" in reg["stance_score"].note  # it is not a 0–1 measure

    def test_survey_measures_are_model_self_report(self):
        block = survey.normalize_survey({"questions": [{"text": "我信任市政府。", "kind": "scale"}]})
        (measure,) = survey.survey_measures(block).values()
        assert measure.grade == "c" and "自述" in measure.basis

    def test_the_compiler_sees_the_grades(self):
        prompt = build_compile_prompt(PLAN)
        assert "| 等级 |" in prompt and "| stress | 压力 |" in prompt and "| (c) |" in prompt
        assert "只读方向" in prompt
        recorded = {m["id"]: m for m in make_protocol().measures}
        assert recorded["stress"]["grade"] == "c" and recorded["stress"]["basis"]


class TestEvaluation:
    def test_a_c_measure_keeps_its_verdict_and_says_the_size_does_not_count(self):
        h1 = evaluate(make_protocol(), _supported_runs())["hypotheses"][0]
        assert h1["verdict"] == "supported"
        assert (h1["measure_grade"], h1["direction_only"]) == ("c", True)
        assert "指标来源 (c) 级：只读方向，效应大小不作数" in h1["reasons"]

    def test_a_graded_b_measure_is_read_with_its_size(self):
        data = make_protocol().to_dict()
        data["measures"] = [{**m, "grade": "b", "basis": "测试用"} for m in data["measures"]]
        h1 = evaluate(Protocol.from_dict(data), _supported_runs())["hypotheses"][0]
        assert (h1["measure_grade"], h1["direction_only"]) == ("b", False)
        assert not any("只读方向" in r for r in h1["reasons"])

    def test_an_old_protocol_falls_back_to_the_catalogue(self):
        data = make_protocol().to_dict()
        data["measures"] = [{k: v for k, v in m.items() if k not in ("grade", "basis")} for m in data["measures"]]
        protocol = Protocol.from_dict(data)
        assert measure_provenance(protocol)["stress"]["grade"] == "c"
        assert evaluate(protocol, _supported_runs())["hypotheses"][0]["direction_only"] is True

    def test_an_unmeasured_hypothesis_gets_no_size_note(self):
        h1 = evaluate(make_protocol(), runs_for((42, {"emotion": {"baseline": [0.5], "subsidy": [0.6]}})))["hypotheses"][0]
        assert h1["verdict"] == "unmeasured"
        assert not any("只读方向" in r for r in h1["reasons"])


class TestReading:
    def test_the_interpretation_is_told_and_a_stated_size_is_flagged(self):
        protocol = make_protocol()
        evaluation = evaluate(protocol, _supported_runs())
        prompt = build_interpret_prompt(protocol, evaluation)
        assert "| 指标等级 |" in prompt and "| (c) |" in prompt and "claim 里只说方向" in prompt
        checked = check_claims({"findings": [
            {"hypothesis": "H1", "claim": "补贴使压力下降了 10 个百分点", "evidence": ""},
            {"hypothesis": "H1", "claim": "补贴使压力下降 0.105", "evidence": ""},
            {"hypothesis": "H1", "claim": "补贴降低了压力", "evidence": "s42: -0.100, s43: -0.110"},
        ]}, evaluation)
        assert [f["cites_size"] for f in checked["findings"]] == [True, True, False]

    def test_a_size_on_a_sized_measure_is_not_flagged(self):
        evaluation = {"hypotheses": [{"id": "H1", "verdict": "supported", "direction_only": False}]}
        checked = check_claims({"findings": [{"hypothesis": "H1", "claim": "下降 0.105"}]}, evaluation)
        assert checked["findings"][0]["cites_size"] is False

    def test_the_report_shows_grades_and_the_caveat(self):
        protocol = make_protocol()
        evaluation = evaluate(protocol, _supported_runs())
        study = {"title": "t", "protocol": protocol.to_dict(), "evaluation": evaluation, "stage": "reported",
                 "interpretation": check_claims({"findings": [
                     {"hypothesis": "H1", "claim": "压力下降 0.1", "evidence": ""}]}, evaluation)}
        doc = render_study_markdown(study)
        assert "### 指标来源" in doc and "不得单独立论，只读方向" in doc
        assert "（c 级：只读方向，大小不作数）" in doc
        assert "（对只读方向的指标写了效应大小，大小不作数）" in doc
        english = render_study_markdown({**study, "language": "en"})
        assert "### Measure provenance" in english and "direction only" in english
