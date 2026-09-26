"""AI social scientist, phase one: plan → protocol → run → verdicts → report.

The model and the simulator are both stubbed. What is under test is the
pre-registration surviving normalisation (and what gets dropped being said
so), the preflight gate, the mapping onto a parallel worlds spec, the
deterministic verdict rules, the report, the study store, and the HTTP
surface with its stage transitions.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from gaworld.apps import research_api
from gaworld.research import backends, measures, workbench
from gaworld.research import study as study_mod
from gaworld.research.evaluate import evaluate
from gaworld.research.interpret import build_interpret_prompt, interpretation_from_answer
from gaworld.research.protocol import (
    DEFAULT_SEEDS,
    Protocol,
    apply_overrides,
    build_compile_prompt,
    preflight,
    protocol_from_answer,
)
from gaworld.research.report import render_study_markdown
from gaworld.research.workbench import ResearchError

PLAN = {
    "id": "20260919-000000-abc123",
    "kind": "idea",
    "title": "租金补贴与邻里交往",
    "language": "zh-CN",
    "summary": "有无补贴两个世界，看压力与情绪。",
    "research_questions": ["租金补贴是否降低低收入家庭的压力？"],
    "hypotheses": ["H1：补贴组压力低于对照组"],
    "design": {
        "city": "柳溪",
        "population": "50 人",
        "agents": "",
        "timeline": "14 天",
        "conditions": [{"name": "对照", "manipulation": "无"}, {"name": "补贴", "manipulation": "第 2 天起发放"}],
        "events": ["租金补贴"],
        "measures": [{"name": "压力", "operationalization": "state 里的 stress", "source": "state/agent_state_history.csv"}],
    },
    "gaps": [{"limitation": "没有住房市场", "workaround": "把补贴写成事件"}],
    "estimated_cost": {"llm_calls": "几百次"},
}

#: A cooperative compile answer, with two hypotheses that cannot run.
ANSWER = {
    "title": "租金补贴的压力效应",
    "sample": {"city": "默认世界", "agent_ids": [1, 2, 3], "note": "三位居民"},
    "sim_days": 5,
    "fast": True,
    "conditions": [
        {"id": "baseline", "label": "基准", "role": "baseline", "events": []},
        {
            "id": "subsidy",
            "label": "补贴",
            "role": "treatment",
            "events": [{"day": 2, "time": "09:00", "name": "租金补贴", "description": "低收入家庭收到租金补贴。"}],
        },
    ],
    "measures": ["stress", "压力", "不存在的指标"],
    "hypotheses": [
        {"id": "H1", "statement": "补贴降低压力", "measure": "stress", "treatment": "subsidy", "control": "baseline",
         "direction": "decrease", "min_effect": 0.02, "aggregation": "final"},
        {"id": "H2", "statement": "补贴提升情绪", "measure": "情绪", "treatment": "补贴", "direction": "上升", "min_effect": 0.01},
        {"id": "H3", "statement": "测不到", "measure": "出生数", "treatment": "subsidy", "control": "baseline", "direction": "increase"},
        {"id": "H4", "statement": "条件不存在", "measure": "stress", "treatment": "nope", "control": "baseline", "direction": "increase"},
    ],
    "validity": {"seeds": [42, 43], "placebo": True},
    "notes": "没有住房市场。",
}

INTERPRETATION = {
    "findings": [
        {"hypothesis": "H1", "claim": "补贴降低了压力", "evidence": "均值效应 -0.1"},
        {"hypothesis": "H9", "claim": "凭空的结论", "evidence": ""},
    ],
    "limitations": ["只有三位居民"],
    "next_studies": [{"title": "剂量反应", "rationale": "看补贴额度", "change": "加两个额度世界"}],
}


def make_protocol(answer=ANSWER, plan=PLAN) -> Protocol:
    return protocol_from_answer(json.loads(json.dumps(answer, ensure_ascii=False)), plan)


def fake_report(values, *, baseline="baseline", missing=()):
    """A parallel worlds report shaped like ``build_report``'s, from metric → world → series."""
    world_ids = sorted({world for by_world in values.values() for world in by_world})
    return {
        "baseline_id": baseline,
        "trajectories": values,
        "worlds": [
            {"id": world, "label": world, "is_baseline": world == baseline, "has_data": world not in missing,
             "status": "error" if world in missing else "done"}
            for world in world_ids
        ],
        "deltas": [],
    }


def runs_for(*seed_values):
    """``[(seed, {metric: {world: series}}), ...]`` → what ``run_protocol`` returns."""
    return [{"seed": seed, "root": f"output/parallel_worlds/x_s{seed}", "status": "done", "report": fake_report(values)}
            for seed, values in seed_values]


def series(baseline, subsidy, placebo=None, *, metric="stress"):
    by_world = {"baseline": [0.5, baseline], "subsidy": [0.5, subsidy]}
    if placebo is not None:
        by_world["placebo"] = [0.5, placebo]
    return {metric: by_world}


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FEATURES.md").write_text("# 功能\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------


def test_registry_resolves_ids_and_labels():
    reg = measures.registry()
    assert reg["stress"].label == "压力"
    assert measures.resolve("压力").id == "stress"
    assert measures.resolve("STRESS").id == "stress"
    assert measures.resolve("出生数") is None
    assert "| stress | 压力 |" in measures.render_registry()


# ---------------------------------------------------------------------------
# Compile prompt + normalisation
# ---------------------------------------------------------------------------


def test_compile_prompt_carries_plan_registry_and_language():
    prompt = build_compile_prompt(PLAN, registry_table="| stress | 压力 |", language="en")
    assert "第 2 天起发放" in prompt
    assert "state 里的 stress" in prompt
    assert "没有住房市场" in prompt
    assert "| stress | 压力 |" in prompt
    assert "English" in prompt


def test_protocol_keeps_what_can_run_and_records_the_rest():
    protocol = make_protocol()
    assert protocol.title == "租金补贴的压力效应"
    assert protocol.plan_id == PLAN["id"]
    assert [cond["id"] for cond in protocol.conditions] == ["baseline", "subsidy", "placebo"]
    assert [cond["role"] for cond in protocol.conditions] == ["baseline", "treatment", "placebo"]
    # The placebo lands on the first treatment day so its noise is measured
    # over the same horizon as the effect.
    assert protocol.conditions[2]["events"][0]["day"] == 2
    assert protocol.baseline_id == "baseline"
    assert [h["id"] for h in protocol.hypotheses] == ["H1", "H2"]
    h2 = protocol.hypotheses[1]
    assert h2 == {
        "id": "H2", "statement": "补贴提升情绪", "measure": "emotion", "treatment": "subsidy", "control": "baseline",
        "direction": "increase", "min_effect": 0.01, "aggregation": "final",
    }
    assert [m["id"] for m in protocol.measures] == ["stress", "emotion"]
    dropped = [item for item in protocol.dropped if item["what"] == "hypothesis"]
    assert len(dropped) == 2
    assert "出生数" in dropped[0]["reason"]
    assert "nope" in dropped[1]["reason"]
    assert protocol.seeds == [42, 43]
    assert protocol.sample["agent_ids"] == [1, 2, 3]
    assert protocol.fast is True
    assert protocol.sim_days == 5
    assert protocol.notes == "没有住房市场。"


def test_protocol_without_conditions_is_an_error():
    with pytest.raises(ResearchError):
        protocol_from_answer({"title": "x", "conditions": []}, PLAN)


def test_roles_and_ids_are_inferred_when_missing():
    answer = {
        "conditions": [
            {"label": "什么都不做"},
            {"label": "轻度限行", "events": [{"day": 3, "time": "07:00", "name": "限行", "description": "单双号"}]},
            {"label": "安慰剂通告", "events": [{"day": 3, "time": "10:00", "name": "通告", "description": "例行"}]},
        ],
        "hypotheses": [{"measure": "stress", "treatment": "轻度限行", "control": "什么都不做", "direction": "increase"}],
        "validity": {"placebo": False},
    }
    protocol = protocol_from_answer(answer, PLAN)
    assert [(c["id"], c["role"]) for c in protocol.conditions] == [
        ("baseline", "baseline"), ("t1", "treatment"), ("placebo", "placebo"),
    ]
    assert protocol.hypotheses[0]["id"] == "H1"
    assert protocol.hypotheses[0]["treatment"] == "t1"
    assert protocol.seeds == list(DEFAULT_SEEDS)


def test_round_trip_and_overrides():
    protocol = Protocol.from_dict(make_protocol().to_dict())
    apply_overrides(protocol, {"seeds": "7, 8, 8", "sim_days": "9", "fast": False, "agent_ids": "4,5", "sim_provider": "m1"})
    assert protocol.seeds == [7, 8]
    assert protocol.sim_days == 9
    assert protocol.fast is False
    assert protocol.sample["agent_ids"] == [4, 5]
    assert protocol.sim_provider == "m1"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def test_preflight_passes_and_prices_the_study():
    protocol = make_protocol()
    check = preflight(protocol, default_agents=50)
    assert check["ok"] is True
    assert check["errors"] == []
    # agent_ids win over the config's population; fast mode is one call per agent-day.
    assert check["budget"]["estimated_calls"] == 3 * 5 * 1 * 3 * 2
    assert protocol.budget == check["budget"]
    assert sum("已丢弃" in item for item in check["warnings"]) == 2


def test_preflight_blocks_what_cannot_be_judged():
    protocol = make_protocol()
    protocol.sim_days = 2
    protocol.fast = False
    protocol.sample["agent_ids"] = []
    protocol.hypotheses = []
    protocol.conditions = [cond for cond in protocol.conditions if cond["role"] != "treatment"]
    check = preflight(protocol, default_agents=50, call_budget=1000)
    assert check["ok"] is False
    joined = "\n".join(check["errors"])
    assert "没有处理条件" in joined
    assert "没有一条可评估的假设" in joined
    assert "事件没有时间显形" in joined
    assert "超过上限" in joined


def test_preflight_warns_about_missing_noise_floor():
    protocol = make_protocol()
    protocol.validity["seeds"] = [42]
    protocol.conditions = [cond for cond in protocol.conditions if cond["role"] != "placebo"]
    check = preflight(protocol)
    assert check["ok"] is True
    assert any("只有一个种子" in item for item in check["warnings"])
    assert any("没有安慰剂世界" in item for item in check["warnings"])


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def test_protocol_maps_onto_a_parallel_worlds_spec():
    spec = backends.experiment_spec(make_protocol(), 43)
    assert spec.seed == 43
    assert spec.fast is True
    assert spec.sim_days == 5
    assert spec.agent_ids == [1, 2, 3]
    assert spec.baseline_id == "baseline"
    assert [world.id for world in spec.worlds] == ["baseline", "subsidy", "placebo"]
    assert spec.worlds[1].events[0]["name"] == "租金补贴"
    assert spec.worlds[2].events[0]["name"] == "市政通告"


def test_run_protocol_runs_every_seed_and_honours_stop():
    protocol = make_protocol()
    seen = []
    messages = []

    def run_seed(spec, seed, report):
        seen.append((spec.seed, seed))
        report(0.5, "跑到一半")
        return {"root": f"r{seed}", "status": "done", "report": {}}

    runs = backends.run_protocol(protocol, run_seed=run_seed, report=lambda p, m: messages.append((p, m)))
    assert seen == [(42, 42), (43, 43)]
    assert [run["seed"] for run in runs] == [42, 43]
    assert messages[0] == (0.25, "种子 42：跑到一半")
    assert backends.slim_runs(runs) == [{"seed": 42, "root": "r42", "status": "done"}, {"seed": 43, "root": "r43", "status": "done"}]

    stop = threading.Event()

    def stop_after_first(spec, seed, report):
        stop.set()
        return {"root": f"r{seed}", "status": "stopped", "report": {}}

    assert len(backends.run_protocol(protocol, run_seed=stop_after_first, stop=stop)) == 1


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_supported_when_every_seed_agrees_and_clears_noise():
    protocol = make_protocol()
    runs = runs_for(
        (42, {**series(0.5, 0.4, 0.51), **series(0.5, 0.53, 0.5, metric="emotion")}),
        (43, {**series(0.52, 0.41, 0.515), **series(0.5, 0.54, 0.505, metric="emotion")}),
    )
    result = evaluate(protocol, runs)
    h1, h2 = result["hypotheses"]
    assert h1["verdict"] == "supported"
    assert h1["mean_effect"] == pytest.approx(-0.105)
    # The larger of the two seeds' placebo gaps (0.01 and 0.005).
    assert h1["noise"] == pytest.approx(0.01)
    assert h1["effects"][0]["effect"] == pytest.approx(-0.1)
    assert h1["effects"][0]["placebo_gap"] == pytest.approx(0.01)
    assert "2/2 个种子的方向与预测一致" in h1["reasons"][0]
    assert h2["verdict"] == "supported"
    assert result["summary"] == {"supported": 2, "contradicted": 0, "inconclusive": 0, "unmeasured": 0}
    assert result["quality"]["ok"] is True
    assert result["values"]["stress"]["subsidy"] == {42: 0.4, 43: 0.41}
    assert result["seeds"] == [42, 43]


def test_contradicted_when_every_seed_moves_the_other_way():
    protocol = make_protocol()
    protocol.hypotheses = protocol.hypotheses[:1]
    runs = runs_for((42, series(0.5, 0.6, 0.5)), (43, series(0.5, 0.62, 0.51)))
    item = evaluate(protocol, runs)["hypotheses"][0]
    assert item["verdict"] == "contradicted"
    assert "反方向" in "".join(item["reasons"])


def test_inconclusive_when_seeds_disagree_or_noise_swallows_the_effect():
    protocol = make_protocol()
    protocol.hypotheses = protocol.hypotheses[:1]
    mixed = evaluate(protocol, runs_for((42, series(0.5, 0.4, 0.5)), (43, series(0.5, 0.6, 0.5))))["hypotheses"][0]
    assert mixed["verdict"] == "inconclusive"
    assert any("方向不一致" in reason for reason in mixed["reasons"])
    noisy = evaluate(protocol, runs_for((42, series(0.5, 0.45, 0.6)), (43, series(0.5, 0.46, 0.4))))["hypotheses"][0]
    assert noisy["verdict"] == "inconclusive"
    assert noisy["noise"] == pytest.approx(0.1)


def test_single_seed_without_placebo_cannot_be_supported():
    protocol = make_protocol()
    protocol.hypotheses = protocol.hypotheses[:1]
    protocol.conditions = [cond for cond in protocol.conditions if cond["role"] != "placebo"]
    protocol.validity["seeds"] = [42]
    item = evaluate(protocol, runs_for((42, series(0.5, 0.3))))["hypotheses"][0]
    assert item["verdict"] == "inconclusive"
    assert any("只有一个种子" in reason for reason in item["reasons"])
    # A single seed *with* a placebo world has a noise floor and may pass.
    with_placebo = make_protocol()
    with_placebo.hypotheses = with_placebo.hypotheses[:1]
    assert evaluate(with_placebo, runs_for((42, series(0.5, 0.3, 0.505))))["hypotheses"][0]["verdict"] == "supported"


def test_unmeasured_and_quality_issues():
    protocol = make_protocol()
    protocol.hypotheses = protocol.hypotheses[:1]
    run = {"seed": 42, "root": "r", "status": "error",
           "report": fake_report({"stress": {"baseline": [0.5, 0.5], "placebo": [0.5, 0.5]}}, missing=("subsidy",))}
    result = evaluate(protocol, [run])
    assert result["hypotheses"][0]["verdict"] == "unmeasured"
    issues = result["quality"]["issues"]
    assert any(issue["condition"] == "subsidy" and "没有状态数据" in issue["issue"] for issue in issues)
    assert any("没有变化" in issue["issue"] for issue in issues)


def test_mean_aggregation_reads_the_whole_series():
    protocol = make_protocol()
    protocol.hypotheses = [dict(protocol.hypotheses[0], aggregation="mean", min_effect=0.0)]
    runs = runs_for(
        (42, {"stress": {"baseline": [0.5, 0.5, 0.5], "subsidy": [0.5, 0.2, 0.5], "placebo": [0.5, 0.5, 0.5]}}),
        (43, {"stress": {"baseline": [0.5, 0.5, 0.5], "subsidy": [0.5, 0.2, 0.5], "placebo": [0.5, 0.5, 0.5]}}),
    )
    item = evaluate(protocol, runs)["hypotheses"][0]
    assert item["effects"][0]["effect"] == pytest.approx(-0.1)
    assert item["verdict"] == "supported"


# ---------------------------------------------------------------------------
# Interpretation + report
# ---------------------------------------------------------------------------


def _evaluated_study():
    protocol = make_protocol()
    runs = runs_for(
        (42, {**series(0.5, 0.4, 0.51), **series(0.5, 0.53, 0.5, metric="emotion")}),
        (43, {**series(0.52, 0.41, 0.515), **series(0.5, 0.54, 0.505, metric="emotion")}),
    )
    evaluation = evaluate(protocol, runs)
    study = study_mod.new_study(PLAN, protocol.to_dict(), preflight(protocol), provider="m1")
    study.runs = backends.slim_runs(runs)
    study.evaluation = evaluation
    study.interpretation = interpretation_from_answer(json.loads(json.dumps(INTERPRETATION)), evaluation)
    study.set_stage("reported")
    return protocol, study


def test_interpret_prompt_and_claim_check():
    protocol, study = _evaluated_study()
    prompt = build_interpret_prompt(protocol, study.evaluation)
    assert "| H1 |" in prompt and "supported" in prompt
    assert "placebo（placebo）" in prompt
    findings = study.interpretation["findings"]
    assert findings[0]["grounded"] is True and findings[0]["verdict"] == "supported"
    assert findings[1]["grounded"] is False
    with pytest.raises(ResearchError):
        interpretation_from_answer({}, study.evaluation)


def test_report_has_every_section_and_marks_ungrounded_claims():
    _, study = _evaluated_study()
    doc = render_study_markdown(study.to_dict())
    assert doc.startswith("# 租金补贴的压力效应\n")
    assert "## 预注册" in doc
    assert "| subsidy | 补贴 | 处理 | Day 2 09:00 租金补贴 |" in doc
    assert "| H1 | 补贴降低压力 | stress | subsidy vs baseline | 下降 | 0.0200 | final |" in doc
    assert "编译时丢弃的内容" in doc
    assert "## 执行记录" in doc and "`output/parallel_worlds/x_s42`" in doc
    assert "### H1 · 支持" in doc
    assert "- **均值效应**: -0.1050 · **噪声底线**: 0.0100" in doc
    assert "所有世界都有数据" in doc
    assert "- **H1**: 补贴降低了压力 — 均值效应 -0.1" in doc
    assert "- **H9** （未挂到任何假设，不作数）: 凭空的结论" in doc
    assert "### 后续研究" in doc
    assert "## 备注" in doc

    study.language = "en"
    english = render_study_markdown(study.to_dict())
    assert "## Pre-registration" in english and "### H1 · supported" in english


def test_report_renders_before_any_run():
    protocol = make_protocol()
    study = study_mod.new_study(PLAN, protocol.to_dict(), preflight(protocol))
    doc = render_study_markdown(study.to_dict())
    assert "## 预注册" in doc
    assert "## 结果" not in doc


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_study_store_round_trip(isolated_root):
    _, study = _evaluated_study()
    study.report_markdown = render_study_markdown(study.to_dict())
    directory = study_mod.save_study(study)
    assert directory == isolated_root / "output" / "research" / "studies" / study.id
    assert (directory / "report.md").read_text(encoding="utf-8").startswith("# ")
    assert "report_markdown" not in json.loads((directory / "study.json").read_text(encoding="utf-8"))
    loaded = study_mod.load_study(study.id)
    assert loaded.stage == "reported"
    assert loaded.report_markdown.startswith("# ")
    listed = study_mod.list_studies()
    assert [item["id"] for item in listed] == [study.id]
    assert listed[0]["summary"]["supported"] == 2
    assert listed[0]["hypotheses"] == 2
    assert study_mod.delete_study(study.id) is True
    assert study_mod.load_study(study.id) is None
    with pytest.raises(ResearchError):
        study_mod.load_study("../../etc")


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def _await_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = research_api.job_status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")


def _await_stage(study_id, stages, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail, _ = research_api.handle_get(f"/api/research/studies/{study_id}")
        if detail.get("stage") in stages:
            return detail
        time.sleep(0.02)
    raise AssertionError(f"study {study_id} never reached {stages}")


@pytest.fixture
def stubbed_api(isolated_root, monkeypatch):
    """A saved plan, a model that answers the compile and interpret prompts,
    and a seed runner that returns canned worlds instead of forking them."""
    import gaworld.llm.providers as providers

    plan = workbench.ResearchPlan(
        id=PLAN["id"], kind="idea", title=PLAN["title"], language="zh-CN", provider="m1",
        created_at="2026-09-19T00:00:00+00:00", summary=PLAN["summary"], design=PLAN["design"],
        hypotheses=PLAN["hypotheses"], material="想法",
    )
    workbench.save_plan(plan)

    seen = {"prompts": []}

    def fake_call(prompt, **kwargs):
        seen["prompts"].append(kwargs)
        if "预注册协议" in prompt:
            return json.dumps(ANSWER, ensure_ascii=False)
        if "研究解读助手" in prompt:
            return json.dumps(INTERPRETATION, ensure_ascii=False)
        raise AssertionError("unexpected prompt")

    monkeypatch.setattr(providers, "call_llm", fake_call)
    monkeypatch.setattr(providers, "resolve_provider", lambda **kwargs: kwargs.get("provider") or "routed")
    monkeypatch.setattr(research_api, "_base_config", lambda: {"agent_ids": [1, 2, 3, 4, 5, 6]})

    def fake_seed_runner(study):
        def run(spec, seed, report):
            report(1.0, "done")
            values = {**series(0.5, 0.4, 0.51), **series(0.5, 0.53, 0.5, metric="emotion")}
            return {"root": f"output/parallel_worlds/study_{study.id}_s{seed}", "id": f"study_{study.id}_s{seed}",
                    "status": "done", "world_status": {w.id: "done" for w in spec.worlds}, "report": fake_report(values)}
        return run

    monkeypatch.setattr(research_api, "_seed_runner", fake_seed_runner)
    monkeypatch.setattr(research_api, "_ACTIVE_STUDY", {"study_id": None, "job_id": None, "runner": None, "stop": None})
    return seen


def test_unknown_study_endpoints():
    assert research_api.handle_get("/api/research/studies/S0000-0000")[1] == 404
    assert research_api.handle_post("/api/research/studies/S0000-0000/approve", {})[1] == 404
    assert research_api.handle_post("/api/research/studies/S0000-0000/nope", {})[1] == 404
    assert research_api.handle_post("/api/research/studies", {"plan_id": "nope-0000"})[1] == 400
    assert research_api.handle_post("/api/research/studies", {"plan_id": "../x"})[1] == 400


def test_study_compiles_the_chosen_design(stubbed_api, monkeypatch):
    from gaworld.research import protocol as protocol_mod

    plan = workbench.load_plan(PLAN["id"])
    plan["designs"] = [{**PLAN["design"], "name": "甲"}, {**PLAN["design"], "name": "乙"}]
    workbench.save_plan(workbench.ResearchPlan.from_dict(plan))
    compiled = []
    original = protocol_mod.build_compile_prompt

    def spy(plan, **kwargs):
        compiled.append(plan["design"].get("name"))
        return original(plan, **kwargs)

    monkeypatch.setattr(protocol_mod, "build_compile_prompt", spy)
    body, status = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "design_index": 1})
    assert status == 202
    assert _await_job(body["job_id"])["status"] == "done"
    assert compiled == ["乙"]
    assert research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "design_index": 5})[1] == 400
    assert research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "design_index": "x"})[1] == 400


def test_copilot_flow_compile_approve_run_report(stubbed_api):
    body, status = research_api.handle_post(
        "/api/research/studies", {"plan_id": PLAN["id"], "provider": "m1", "sim_days": 6}
    )
    assert status == 202
    record = _await_job(body["job_id"])
    assert record["status"] == "done", record
    study_id = record["result"]["study_id"]
    assert record["result"]["stage"] == "protocol"
    assert record["result"]["preflight"]["ok"] is True
    assert stubbed_api["prompts"][0]["task"] == "research"
    assert stubbed_api["prompts"][0]["provider"] == "m1"

    detail, status = research_api.handle_get(f"/api/research/studies/{study_id}")
    assert status == 200
    assert detail["stage"] == "protocol"
    assert detail["protocol"]["sim_days"] == 6  # the override applied before preflight
    assert detail["provider"] == "m1"
    context, _ = research_api.handle_get("/api/research/context")
    assert [item["id"] for item in context["studies"]] == [study_id]
    assert context["measures"] > 0

    # Break the protocol with an override, and approval is refused until fixed.
    body, status = research_api.handle_post(f"/api/research/studies/{study_id}/update", {"sim_days": 2})
    assert status == 200 and body["preflight"]["ok"] is False
    assert research_api.handle_post(f"/api/research/studies/{study_id}/approve", {})[1] == 400
    assert research_api.handle_post(f"/api/research/studies/{study_id}/run", {})[1] == 400
    body, _ = research_api.handle_post(f"/api/research/studies/{study_id}/update", {"sim_days": 5})
    assert body["preflight"]["ok"] is True

    body, status = research_api.handle_post(f"/api/research/studies/{study_id}/approve", {})
    assert status == 200 and body["stage"] == "approved"
    assert research_api.handle_post(f"/api/research/studies/{study_id}/update", {"sim_days": 5})[1] == 400

    body, status = research_api.handle_post(f"/api/research/studies/{study_id}/run", {})
    assert status == 202
    record = _await_job(body["job_id"])
    assert record["status"] == "done", record
    detail = _await_stage(study_id, {"reported"})
    assert detail["evaluation"]["summary"]["supported"] == 2
    assert [run["seed"] for run in detail["runs"]] == [42, 43]
    assert "report" not in detail["runs"][0]
    assert detail["interpretation"]["findings"][0]["grounded"] is True
    assert detail["report_markdown"].startswith("# 租金补贴的压力效应")
    assert stubbed_api["prompts"][-1]["provider"] == "m1"

    export, status = research_api.handle_get(f"/api/research/studies/{study_id}/report")
    assert status == 200
    assert export["filename"].endswith(f"-{study_id}.md")
    assert "### H1 · 支持" in export["markdown"]

    assert research_api.handle_post(f"/api/research/studies/{study_id}/delete", {})[0]["deleted"] is True
    assert research_api.handle_get(f"/api/research/studies/{study_id}")[1] == 404


def test_autopilot_runs_without_a_click(stubbed_api):
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True})
    record = _await_job(body["job_id"])
    assert record["status"] == "done", record
    assert record["result"]["stage"] == "approved"
    assert record["result"]["run_job_id"]
    detail = _await_stage(record["result"]["study_id"], {"reported"})
    assert detail["autopilot"] is True
    assert detail["evaluation"]["summary"]["supported"] == 2


def test_autopilot_stops_at_a_failed_preflight(stubbed_api):
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True, "sim_days": 1})
    record = _await_job(body["job_id"])
    assert record["status"] == "done", record
    assert record["result"]["stage"] == "protocol"
    assert record["result"]["preflight"]["ok"] is False
    assert "run_job_id" not in record["result"]


def test_one_study_runs_at_a_time(stubbed_api):
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"]})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    research_api.handle_post(f"/api/research/studies/{study_id}/approve", {})
    with research_api._JOBS_LOCK:
        research_api._JOBS["run-busy"] = {"id": "run-busy", "status": "running", "started_at": time.time()}
    research_api._ACTIVE_STUDY.update(study_id="other", job_id="run-busy")
    assert research_api.handle_post(f"/api/research/studies/{study_id}/run", {})[1] == 409
    assert research_api.handle_post(f"/api/research/studies/{study_id}/stop", {})[0]["stopping"] is False


def test_the_panel_can_pick_the_model_the_simulation_runs_on(stubbed_api):
    """The compile model and the model the residents run on are two choices."""
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"]})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    detail, _ = research_api.handle_get(f"/api/research/studies/{study_id}")
    assert detail["provider"] == "routed" and detail["protocol"]["sim_provider"] == ""

    body, status = research_api.handle_post(
        f"/api/research/studies/{study_id}/update", {"sim_provider": "m2"}
    )
    assert status == 200 and body["protocol"]["sim_provider"] == "m2"
    # …and it reaches the worlds: every task in every world is pinned to it.
    spec = backends.experiment_spec(Protocol.from_dict(body["protocol"]), 42)
    assert spec.llm_provider == "m2"
    assert study_mod.load_study(study_id).protocol["sim_provider"] == "m2"


def test_an_interrupted_run_stops_claiming_to_be_running(stubbed_api):
    """A restart leaves ``running`` on disk with nothing running behind it."""
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    _await_stage(study_id, {"reported"})
    stranded = study_mod.load_study(study_id)
    stranded.set_stage("running")
    study_mod.save_study(stranded)

    detail, status = research_api.handle_get(f"/api/research/studies/{study_id}")
    assert status == 200
    assert detail["stage"] == "error"
    assert detail["error"] == research_api.INTERRUPTED_MESSAGE
    assert detail["live"] is False and detail["paused"] is False
    assert [item["stage"] for item in research_api.studies()["studies"]] == ["error"]
    # Stopping what is not running tidies the record instead of doing nothing.
    assert research_api.handle_post(f"/api/research/studies/{study_id}/stop", {})[0]["stopping"] is False


def test_reset_clears_the_results_and_re_runs_under_a_new_attempt(stubbed_api):
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    _await_stage(study_id, {"reported"})
    assert (study_mod.study_dir(study_id) / "report.md").exists()

    body, status = research_api.handle_post(f"/api/research/studies/{study_id}/reset", {"run": True})
    assert status == 202
    assert body["stage"] == "approved" and body["attempt"] == 2
    _await_job(body["run_job_id"])
    detail = _await_stage(study_id, {"reported"})
    assert detail["attempt"] == 2
    assert [run["seed"] for run in detail["runs"]] == [42, 43]


def test_reset_without_a_passing_preflight_goes_back_to_approval(stubbed_api):
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    _await_stage(study_id, {"reported"})
    study = study_mod.load_study(study_id)
    study.preflight = {"ok": False, "errors": ["调用量超预算"]}
    study_mod.save_study(study)

    body, status = research_api.handle_post(f"/api/research/studies/{study_id}/reset", {"run": True})
    assert status == 200
    assert body["stage"] == "protocol" and "run_job_id" not in body
    assert "跑前检查" in body["note"]
    reset = study_mod.load_study(study_id)
    assert reset.runs == [] and reset.evaluation == {} and reset.report_markdown == ""
    assert not (study_mod.study_dir(study_id) / "report.md").exists()


def test_pause_and_resume_need_a_live_run(stubbed_api):
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"]})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    assert research_api.handle_post(f"/api/research/studies/{study_id}/pause", {})[1] == 400
    assert research_api.handle_post(f"/api/research/studies/{study_id}/resume", {})[1] == 400


def test_pause_holds_the_next_seed_until_resume(stubbed_api, monkeypatch):
    gate = threading.Event()
    started: list[int] = []

    def slow_seed_runner(study):
        def run(spec, seed, report):
            started.append(seed)
            gate.wait(10)
            values = {**series(0.5, 0.4, 0.51), **series(0.5, 0.53, 0.5, metric="emotion")}
            return {"root": f"output/parallel_worlds/x_s{seed}", "id": f"x_s{seed}", "status": "done",
                    "world_status": {w.id: "done" for w in spec.worlds}, "report": fake_report(values)}
        return run

    monkeypatch.setattr(research_api, "_seed_runner", slow_seed_runner)
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.02)
    assert started == [42]

    assert research_api.handle_post(f"/api/research/studies/{study_id}/pause", {})[1] == 200
    detail, _ = research_api.handle_get(f"/api/research/studies/{study_id}")
    assert detail["live"] is True and detail["paused"] is True

    gate.set()  # the seed in flight finishes; the loop must hold before the next
    time.sleep(1.5)
    assert started == [42]

    assert research_api.handle_post(f"/api/research/studies/{study_id}/resume", {})[0]["paused"] is False
    detail = _await_stage(study_id, {"reported"}, timeout=10)
    assert started == [42, 43]
    assert detail["paused"] is False


def test_a_re_run_writes_its_own_experiment_tree(isolated_root, monkeypatch):
    """Otherwise the second attempt would overwrite the first one's worlds."""
    seen: dict = {}
    monkeypatch.setattr(research_api, "_base_config", lambda: {})
    monkeypatch.setattr(backends, "default_seed_runner", lambda **kwargs: seen.update(kwargs))
    study = study_mod.Study(id="S20260101-000000-abcd", plan_id="p", title="t")
    research_api._seed_runner(study)
    assert seen["experiment_prefix"] == "study_S20260101-000000-abcd"
    study.attempt = 3
    research_api._seed_runner(study)
    assert seen["experiment_prefix"] == "study_S20260101-000000-abcd_r3"


def test_failed_model_call_marks_the_study_job(stubbed_api, monkeypatch):
    import gaworld.llm.providers as providers

    def broken(prompt, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(providers, "call_llm", broken)
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"]})
    record = _await_job(body["job_id"])
    assert record["status"] == "error"
    assert "model down" in record["message"]


def test_failed_interpretation_does_not_fail_the_study(stubbed_api, monkeypatch):
    import gaworld.llm.providers as providers

    def compile_only(prompt, **kwargs):
        if "预注册协议" in prompt:
            return json.dumps(ANSWER, ensure_ascii=False)
        raise RuntimeError("interpreter down")

    monkeypatch.setattr(providers, "call_llm", compile_only)
    body, _ = research_api.handle_post("/api/research/studies", {"plan_id": PLAN["id"], "autopilot": True})
    study_id = _await_job(body["job_id"])["result"]["study_id"]
    detail = _await_stage(study_id, {"reported"})
    assert "interpreter down" in detail["interpretation"]["error"]
    assert "解读不可用" in detail["report_markdown"]
    assert detail["evaluation"]["summary"]["supported"] == 2
