"""Tests for the classic experiment library (gaworld.experiments.classics).

What we defend:

* every paradigm is a two-condition contrast with its human reference,
  citation and caveat, and its prompt carries the resident and never names
  the experiment;
* the two conditions differ only in the task, never in who is answering;
* parsers read the answers models actually give and refuse the rest
  (out-of-range money, non-positive estimates, unreadable choices);
* the grid is residents × items × conditions × draws, and a run resumes,
  refuses a second writer and stops on a dead backend;
* the verdict reads the paired direction only: replicated / reversed /
  not replicated / insufficient, with draws averaged within a resident.
"""

from __future__ import annotations

import json
import math
import re

import pytest

from gaworld.experiments.classics import (
    MIN_PAIRS,
    PARADIGMS,
    ClassicSpec,
    analyze_paradigm,
    build_cells,
    build_prompt,
    load_rows,
    render_markdown,
    run,
    runner,
    summarize,
)
from gaworld.experiments.classics import __main__ as cli
from gaworld.experiments.classics.paradigms import answer_json
from gaworld.experiments.subjects import load_subjects


@pytest.fixture(scope="module")
def subject():
    return load_subjects(limit=1)[0]


# ---------------------------------------------------------------------------
# Paradigms and prompts
# ---------------------------------------------------------------------------


def test_every_paradigm_is_a_documented_two_condition_contrast():
    assert set(PARADIGMS) == {
        "framing",
        "anchoring",
        "dictator_ultimatum",
        "ultimatum_responder",
        "trust_ingroup",
        "public_goods_mpcr",
    }
    for paradigm in PARADIGMS.values():
        assert len(paradigm.conditions) == 2 and paradigm.control != paradigm.treatment
        assert set(paradigm.condition_labels) == set(paradigm.conditions)
        assert paradigm.reference and paradigm.claim and paradigm.caveat and paradigm.measure
        assert paradigm.human, paradigm.id
        assert set(paradigm.human) <= {*paradigm.conditions, "effect"}


def test_prompts_carry_the_resident_and_never_name_the_experiment(subject):
    for paradigm in PARADIGMS.values():
        for item in paradigm.items:
            prompts = {c: build_prompt(paradigm, item, c, subject) for c in paradigm.conditions}
            for system, user in prompts.values():
                assert subject.name in user and f"{subject.monthly_income:.0f}" in user
                assert "{residence}" not in user
                for giveaway in ("实验", "框架", "锚", "独裁", "最后通牒", "Kahneman"):
                    assert giveaway not in system + user, (paradigm.id, giveaway)
            (_, control), (_, treated) = (prompts[c] for c in paradigm.conditions)
            assert control != treated
            # Same person in both: everything before the task is identical.
            assert control.split("\n\n")[0] == treated.split("\n\n")[0]


def test_trust_partner_names_the_residents_own_neighbourhood(subject):
    paradigm = PARADIGMS["trust_ingroup"]
    _, user = build_prompt(paradigm, paradigm.items[0], "neighbor", subject)
    assert f"住在{subject.residence}的居民" in user


def test_anchors_are_an_order_of_magnitude_apart_and_stated():
    paradigm = PARADIGMS["anchoring"]
    for item in paradigm.items:
        assert item.params["high"] / item.params["low"] >= 10
        assert f"比 {item.params['low']} {item.params['unit']}" in paradigm.task(item, "low")
        assert f"比 {item.params['high']} {item.params['unit']}" in paradigm.task(item, "high")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse(pid, raw, condition=None):
    paradigm = PARADIGMS[pid]
    return paradigm.parse(raw, paradigm.items[0], condition or paradigm.control)


def test_answer_json_tolerates_fences_and_prose():
    assert answer_json('好的：\n```json\n{"choice": "A"}\n```') == {"choice": "A"}
    assert answer_json('我选 {"offer": 30, "reason": "x"} 吧') == {"offer": 30, "reason": "x"}
    assert answer_json("没有 JSON") == {}


def test_framing_reads_the_sure_option():
    assert _parse("framing", '{"choice": "A"}') == 1.0
    assert _parse("framing", '{"choice": "方案B"}') == 0.0
    assert _parse("framing", '{"choice": "都不选"}') is None


def test_anchoring_reads_a_log_estimate_and_refuses_non_positive():
    assert _parse("anchoring", '{"compare": "少", "estimate": 15}') == pytest.approx(math.log10(15))
    assert _parse("anchoring", '{"estimate": "约 1,200"}') == pytest.approx(math.log10(1200))
    assert _parse("anchoring", '{"estimate": 0}') is None


def test_money_answers_outside_the_pot_are_unusable():
    assert _parse("dictator_ultimatum", '{"offer": 30}') == 0.3
    assert _parse("trust_ingroup", '{"send": "50元"}') == 0.5
    assert _parse("public_goods_mpcr", '{"contribute": 120}') is None
    assert _parse("dictator_ultimatum", '{"offer": true}') is None


def test_responder_reads_rejection():
    assert _parse("ultimatum_responder", '{"accept": false}') == 1.0
    assert _parse("ultimatum_responder", '{"accept": "接受"}') == 0.0
    assert _parse("ultimatum_responder", '{"accept": "看情况"}') is None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _stub_answer(prompt, **_):
    """A textbook subject: gain → A, high anchor → big, ultimatum → more."""
    if "200 人将获救" in prompt:
        return '{"choice": "A"}'
    if "400 人将死亡" in prompt:
        return '{"choice": "B"}'
    match = re.search(r"比 (\d+) ", prompt)
    if match:
        return json.dumps({"compare": "少", "estimate": int(match.group(1)) * 0.8})
    if "拒绝的话" in prompt and "你给对方" in prompt:
        return '{"offer": 45}'
    if "你给对方" in prompt:
        return '{"offer": 20}'
    if "给你 20 元" in prompt:
        return '{"accept": false}'
    if "给你 50 元" in prompt:
        return '{"accept": true}'
    if "转给他" in prompt:
        return '{"send": 60}' if "一样住在" in prompt else '{"send": 40}'
    return '{"contribute": 70}' if "0.75" in prompt else '{"contribute": 30}'


def test_the_grid_is_residents_by_items_by_conditions_by_draws():
    cells = build_cells(ClassicSpec(paradigms=["framing", "anchoring"], subject_limit=5, draws=2))
    assert len(cells) == 5 * 2 * 2 + 5 * 3 * 2 * 2
    assert len({cell.key for cell in cells}) == len(cells)
    with pytest.raises(ValueError):
        ClassicSpec(paradigms=["nope"]).validate()


def test_a_run_resumes_and_analyses_to_the_textbook_answers(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "call_llm", lambda prompt, **kw: calls.append(prompt) or _stub_answer(prompt))
    monkeypatch.setattr(runner, "resolve_provider", lambda **kw: "stub")
    spec = ClassicSpec(subject_limit=12, output_dir=tmp_path, name="t", max_workers=4)
    path = run(spec)
    assert len(calls) == len(build_cells(spec))
    run(spec)  # everything already done
    assert len(calls) == len(build_cells(spec))
    assert not (tmp_path / "t" / "run.lock").exists()

    summary = summarize(load_rows(path))
    verdicts = {p["id"]: p["verdict"] for p in summary["paradigms"]}
    assert verdicts == dict.fromkeys(PARADIGMS, "replicated")
    framing = next(p for p in summary["paradigms"] if p["id"] == "framing")
    assert (framing["conditions"]["gain"]["mean"], framing["conditions"]["loss"]["mean"]) == (1.0, 0.0)
    anchoring = next(p for p in summary["paradigms"] if p["id"] == "anchoring")
    assert anchoring["anchoring_index"]["westlake"] == pytest.approx(0.8)
    assert summary["providers"] == {"stub": len(calls)}
    md = render_markdown(summary, "t")
    assert "复现" in md and "级别 (c)" in md and "72%（N=152）" in md


def test_a_second_writer_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "call_llm", lambda prompt, **kw: _stub_answer(prompt))
    monkeypatch.setattr(runner, "resolve_provider", lambda **kw: "stub")
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "run.lock").write_text("1", encoding="utf-8")
    with pytest.raises(RuntimeError, match="同名实验"):
        run(ClassicSpec(paradigms=["framing"], subject_limit=2, output_dir=tmp_path, name="t"))


def test_a_dead_backend_stops_the_run(tmp_path, monkeypatch):
    def boom(prompt, **kw):
        raise ConnectionError("quota")

    monkeypatch.setattr(runner, "call_llm", boom)
    monkeypatch.setattr(runner, "resolve_provider", lambda **kw: "stub")
    spec = ClassicSpec(
        paradigms=["anchoring"], subject_limit=12, output_dir=tmp_path, name="t", max_workers=1
    )
    with pytest.raises(RuntimeError, match="全部失败"):
        run(spec, abort_after=5)
    assert load_rows(tmp_path / "t" / "results.jsonl") == []


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _rows(pid, answers, *, item=None, provider="stub"):
    """answers: {(subject, condition): [raw, ...]}"""
    paradigm = PARADIGMS[pid]
    item = item or paradigm.items[0].id
    rows = []
    for (sid, condition), raws in answers.items():
        for draw, raw in enumerate(raws):
            rows.append(
                {
                    "key": f"{pid}|{item}|{condition}|{sid}|{draw}",
                    "paradigm": pid,
                    "item": item,
                    "condition": condition,
                    "subject_id": sid,
                    "draw": draw,
                    "raw": raw,
                    "age": 20 + sid,
                    "monthly_income": 3000 + 100 * sid,
                    "provider": provider,
                }
            )
    return rows


def _framing(n, gain, loss):
    answers = {}
    for sid in range(n):
        answers[(sid, "gain")] = [f'{{"choice": "{gain(sid)}"}}']
        answers[(sid, "loss")] = [f'{{"choice": "{loss(sid)}"}}']
    return _rows("framing", answers)


def test_verdicts_read_the_paired_direction():
    paradigm = PARADIGMS["framing"]
    same = analyze_paradigm(paradigm, _framing(30, lambda s: "A", lambda s: "B"))
    assert (same["verdict"], same["paired"]["effect"]) == ("replicated", 1.0)
    flipped = analyze_paradigm(paradigm, _framing(30, lambda s: "B", lambda s: "A"))
    assert flipped["verdict"] == "reversed"
    flat = analyze_paradigm(paradigm, _framing(30, lambda s: "AB"[s % 2], lambda s: "AB"[s % 2]))
    assert (flat["verdict"], flat["paired"]["effect"]) == ("not_replicated", 0.0)
    few = analyze_paradigm(paradigm, _framing(MIN_PAIRS - 1, lambda s: "A", lambda s: "B"))
    assert few["verdict"] == "insufficient"


def test_draws_are_averaged_within_a_resident_and_unreadable_answers_counted():
    answers = {}
    for sid in range(12):
        answers[(sid, "gain")] = ['{"choice": "A"}', '{"choice": "B"}']
        answers[(sid, "loss")] = ['{"choice": "B"}', "胡言乱语"]
    result = analyze_paradigm(PARADIGMS["framing"], _rows("framing", answers))
    assert result["paired"]["n"] == 12
    assert result["paired"]["effect"] == pytest.approx(0.5)
    assert result["unparsed"] == 12


def test_heterogeneity_splits_by_the_median_and_needs_enough_pairs():
    result = analyze_paradigm(
        PARADIGMS["framing"], _framing(24, lambda s: "A" if s < 12 else "B", lambda s: "B")
    )
    income = result["heterogeneity"]["monthly_income"]
    assert (income["below"]["effect"], income["above"]["effect"]) == (1.0, 0.0)
    assert income["below"]["n"] == 12
    small = analyze_paradigm(PARADIGMS["framing"], _framing(12, lambda s: "A", lambda s: "B"))
    assert small["heterogeneity"]["age"] is None


def test_mixed_models_are_flagged():
    rows = _framing(12, lambda s: "A", lambda s: "B")
    rows[0]["provider"] = "other"
    assert "混合了多个模型" in render_markdown(summarize(rows))


def test_cli_list_dry_run_and_missing_results(tmp_path, capsys):
    assert cli.main(["list"]) == 0
    assert "framing" in capsys.readouterr().out
    assert (
        cli.main(["run", "framing", "--subject-limit", "3", "--dry-run", "--output-dir", str(tmp_path)]) == 0
    )
    assert "6 次调用" in capsys.readouterr().out
    assert not any(tmp_path.iterdir())
    assert cli.main(["analyze", "--output-dir", str(tmp_path)]) == 1
