"""研究工作台: turning an idea or a paper into a GAWorld study plan.

The model is stubbed throughout — these tests are about the prompt carrying
the right material, the answer surviving validation, the document rendering,
the store, and the HTTP surface (a bad request is a 400, a job lands).
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from gaworld.apps import research_api
from gaworld.research import workbench
from gaworld.research.workbench import (
    MAX_MATERIAL_CHARS,
    ResearchError,
    ResearchPlan,
    analyze,
    build_prompt,
    normalize_request,
    render_markdown,
)

#: A well-formed answer, as a cooperative model would return it.
ANSWER = {
    "title": "租金补贴与邻里交往",
    "summary": "用平行世界对照有无补贴两个世界，看社交网络与压力的差异。",
    "research_questions": ["租金补贴是否扩大低收入家庭的社交圈？"],
    "hypotheses": ["H1：补贴组的 Dunbar 外圈人数高于对照组"],
    "paper_digest": {"theory": "社会资本", "method": "面板数据", "key_variables": ["补贴", "社交圈"], "findings": "正相关"},
    "feasibility": {"score": 78, "verdict": "", "rationale": "平行世界与经济系统都在。"},
    "capability_map": [
        {"need": "对照世界", "feature": "平行世界实验", "how": "两个世界只差补贴事件", "entry": "控制台「平行世界」"},
        {"need": "人口", "feature": "参数化人口合成", "how": "生成 500 人", "entry": "python -m gaworld.population"},
    ],
    "design": {
        "city": "虚构县城",
        "population": "500 人，收入基尼 0.4",
        "agents": "默认大五",
        "timeline": "180 天，按月快进",
        "conditions": [{"name": "对照", "manipulation": "无"}, {"name": "补贴", "manipulation": "第 30 天起发放"}],
        "events": ["租金补贴政策"],
        "measures": [{"name": "外圈人数", "operationalization": "output/network 的度数", "source": "output/network/"}],
    },
    "steps": [
        {"title": "造城", "detail": "离线生成", "commands": ["python -m gaworld.city create 柳溪 --offline"], "panel": "城市"},
        {"title": "加人口", "detail": "500 人", "commands": [], "panel": "人口与群体"},
        "跑平行世界",
        {"title": "", "detail": "", "commands": [], "panel": ""},
    ],
    "validation": ["多种子重复三次", "安慰剂：一个不影响租金的事件"],
    "gaps": [{"limitation": "没有住房市场", "workaround": "把补贴写成经济干预"}],
    "estimated_cost": {"llm_calls": "500 人 × 6 月 × 2 世界 ≈ 6000 次", "note": "用本地模型"},
}


def stub_llm(answer):
    """An ``llm_fn`` that answers with *answer*, fenced the way models do."""

    def call(prompt):
        return "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"

    return call


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(workbench, "PROJECT_ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "FEATURES.md").write_text("# 功能\n| 平行世界实验 | 对照 | CLI |\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Request + prompt
# ---------------------------------------------------------------------------


def test_empty_material_is_rejected():
    with pytest.raises(ResearchError):
        normalize_request({"text": "   "})


def test_unknown_kind_is_rejected():
    with pytest.raises(ResearchError):
        normalize_request({"text": "x", "kind": "poem"})


def test_defaults_and_truncation():
    request = normalize_request({"text": "a" * (MAX_MATERIAL_CHARS + 10), "language": "fr", "provider": " m1 "})
    assert request["kind"] == "idea"
    assert request["language"] == "zh-CN"
    assert request["provider"] == "m1"
    assert request["truncated"] is True
    assert len(request["text"]) == MAX_MATERIAL_CHARS


def test_prompt_carries_catalogue_material_and_language():
    request = normalize_request({"text": "补贴与社交", "kind": "paper", "title": "T", "language": "en"})
    prompt = build_prompt(request, "| 平行世界实验 | ... |")
    assert "平行世界实验" in prompt
    assert "补贴与社交" in prompt
    assert "论文" in prompt
    assert "English" in prompt
    assert "截断" not in prompt


def test_prompt_marks_truncated_material():
    request = normalize_request({"text": "a" * (MAX_MATERIAL_CHARS + 1)})
    assert "截断" in build_prompt(request, "")


def test_catalogue_is_read_from_disk(isolated_root):
    assert "平行世界实验" in workbench.load_catalogue()
    (isolated_root / "docs" / "FEATURES.md").unlink()
    assert workbench.load_catalogue() == ""


# ---------------------------------------------------------------------------
# Answer → plan
# ---------------------------------------------------------------------------


def test_analysis_validates_the_answer():
    plan = analyze({"text": "想法", "kind": "idea"}, llm_fn=stub_llm(ANSWER), catalogue="", provider="m1")
    assert plan.title == "租金补贴与邻里交往"
    assert plan.provider == "m1"
    # The verdict was blank; it is derived from the score, not left empty.
    assert plan.feasibility == {"score": 78, "verdict": "high", "rationale": "平行世界与经济系统都在。"}
    assert [row["feature"] for row in plan.capability_map] == ["平行世界实验", "参数化人口合成"]
    # A bare string is a step; an all-empty object is not.
    assert [step["title"] for step in plan.steps] == ["造城", "加人口", "跑平行世界"]
    assert plan.steps[0]["commands"] == ["python -m gaworld.city create 柳溪 --offline"]
    assert plan.design["conditions"][1] == {"name": "补贴", "manipulation": "第 30 天起发放"}
    assert plan.design["measures"][0]["source"] == "output/network/"
    # An idea has no paper to digest, whatever the model volunteered.
    assert plan.paper_digest == {}
    assert plan.material == "想法"


def test_paper_keeps_its_digest():
    plan = analyze({"text": "论文正文", "kind": "paper"}, llm_fn=stub_llm(ANSWER), catalogue="")
    assert plan.paper_digest["theory"] == "社会资本"
    assert plan.paper_digest["key_variables"] == ["补贴", "社交圈"]


def test_unparseable_answer_is_an_error():
    with pytest.raises(ResearchError):
        analyze({"text": "想法"}, llm_fn=lambda prompt: "我觉得这个研究很好。", catalogue="")


def test_empty_answer_is_an_error():
    with pytest.raises(ResearchError):
        analyze({"text": "想法"}, llm_fn=stub_llm({"title": "只有标题"}), catalogue="")


def test_model_failure_is_reported_not_raised_raw():
    def broken(prompt):
        raise RuntimeError("connection refused")

    with pytest.raises(ResearchError, match="connection refused"):
        analyze({"text": "想法"}, llm_fn=broken, catalogue="")


# ---------------------------------------------------------------------------
# Alternative designs
# ---------------------------------------------------------------------------

DESIGNS_ANSWER = {
    **{key: value for key, value in ANSWER.items() if key != "design"},
    "designs": [
        {"name": "忠实复现", "approach": "照原文", "strengths": "可比", "weaknesses": "贵", **ANSWER["design"]},
        {"name": "机制检验", "approach": "只留补贴", "city": "小村", "conditions": [{"name": "补贴", "manipulation": "发钱"}]},
        "不是对象",
        {},
    ],
    "recommended": 1,
}


def test_plan_keeps_every_design_and_the_recommendation():
    plan = analyze({"text": "想法"}, llm_fn=stub_llm(DESIGNS_ANSWER), catalogue="")
    assert [d["name"] for d in plan.designs] == ["忠实复现", "机制检验"]
    assert plan.recommended_design == 1
    # `design` is the recommended one, so a study compiles it by default.
    assert plan.design == plan.designs[1]
    assert plan.design["city"] == "小村"
    assert plan.designs[0]["weaknesses"] == "贵"


def test_out_of_range_recommendation_falls_back_to_the_first():
    plan = analyze({"text": "想法"}, llm_fn=stub_llm({**DESIGNS_ANSWER, "recommended": 9}), catalogue="")
    assert plan.recommended_design == 0
    assert plan.design["name"] == "忠实复现"


def test_single_design_answer_still_parses_as_one_design():
    plan = analyze({"text": "想法"}, llm_fn=stub_llm(ANSWER), catalogue="")
    assert len(plan.designs) == 1
    assert plan.designs[0]["city"] == "虚构县城"


def test_prompt_asks_for_several_designs():
    prompt = build_prompt(normalize_request({"text": "想法"}), "目录")
    assert '"designs"' in prompt and '"recommended"' in prompt


def test_markdown_lists_every_design_and_marks_the_recommended_one():
    plan = analyze({"text": "想法"}, llm_fn=stub_llm(DESIGNS_ANSWER), catalogue="")
    markdown = render_markdown(plan)
    assert "### 设计 1：忠实复现" in markdown
    assert "### 设计 2：机制检验（推荐）" in markdown
    assert "**优势**: 可比" in markdown


# ---------------------------------------------------------------------------
# Paper read-through (step one)
# ---------------------------------------------------------------------------

DIGEST_ANSWER = {
    "title": "补贴与社会资本",
    "paper_digest": {"theory": "社会资本理论", "method": "双重差分", "key_variables": ["补贴", "网络规模"], "findings": "正向"},
    "research_questions": ["补贴能否扩大社交网络？"],
    "hypotheses": ["H1：补贴组网络更大"],
}


def test_digest_reads_the_paper_without_the_catalogue():
    seen = {}

    def call(prompt):
        seen["prompt"] = prompt
        return json.dumps(DIGEST_ANSWER, ensure_ascii=False)

    digest = workbench.digest_paper({"text": "论文正文 XYZ", "kind": "idea"}, llm_fn=call)
    assert "论文正文 XYZ" in seen["prompt"]
    assert "功能目录" not in seen["prompt"]
    assert digest["title"] == "补贴与社会资本"
    assert digest["paper_digest"]["method"] == "双重差分"
    assert digest["hypotheses"] == ["H1：补贴组网络更大"]
    assert digest["truncated"] is False


def test_digest_with_nothing_in_it_is_an_error():
    with pytest.raises(ResearchError):
        workbench.digest_paper({"text": "论文"}, llm_fn=stub_llm({"title": "只有标题"}))
    with pytest.raises(ResearchError):
        workbench.digest_paper({"text": "论文"}, llm_fn=lambda prompt: "读不懂")


def test_confirmed_digest_steers_the_prompt_and_wins_in_the_plan():
    edited = {
        "paper_digest": {"theory": "研究者改过的理论", "key_variables": ["租金"]},
        "research_questions": ["改过的问题"],
        "hypotheses": ["H1：改过的假设"],
    }
    seen = {}

    def call(prompt):
        seen["prompt"] = prompt
        return json.dumps(ANSWER, ensure_ascii=False)

    plan = analyze({"text": "论文", "kind": "paper", "digest": edited}, llm_fn=call, catalogue="")
    assert "已确认的论文解读" in seen["prompt"]
    assert "研究者改过的理论" in seen["prompt"]
    # The model restated ANSWER's digest; the user's edit is what the plan keeps.
    assert plan.paper_digest["theory"] == "研究者改过的理论"
    assert plan.research_questions == ["改过的问题"]
    assert plan.hypotheses == ["H1：改过的假设"]


def test_confirmed_digest_is_ignored_for_an_idea_and_when_empty():
    assert normalize_request({"text": "想法", "digest": DIGEST_ANSWER})["digest"] is None
    assert normalize_request({"text": "论文", "kind": "paper", "digest": {"hypotheses": []}})["digest"] is None
    assert "已确认的论文解读" not in build_prompt(normalize_request({"text": "想法"}), "")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def test_markdown_has_every_section():
    plan = analyze({"text": "论文", "kind": "paper"}, llm_fn=stub_llm(ANSWER), catalogue="", provider="m1")
    doc = render_markdown(plan)
    assert doc.startswith("# 租金补贴与邻里交往\n")
    assert "可行性: high 78分" in doc
    assert "## 论文摘要" in doc
    assert "| 对照世界 | 平行世界实验 |" in doc
    assert "### 1. 造城  (页签: 城市)" in doc
    assert "```bash\npython -m gaworld.city create 柳溪 --offline\n```" in doc
    assert "- **局限**: 没有住房市场" in doc
    assert "> 论文" in doc


def test_markdown_labels_follow_the_plan_language():
    plan = analyze({"text": "idea", "language": "en"}, llm_fn=stub_llm(ANSWER), catalogue="")
    doc = render_markdown(plan)
    assert "## Capability map" in doc
    assert "## Implementation steps" in doc
    assert "功能映射" not in doc


def test_markdown_escapes_pipes_in_table_cells():
    answer = dict(ANSWER)
    answer["capability_map"] = [{"need": "a|b", "feature": "f", "how": "h", "entry": "e"}]
    plan = analyze({"text": "x"}, llm_fn=stub_llm(answer), catalogue="")
    assert "| a\\|b | f | h | e |" in render_markdown(plan)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_save_list_load_delete(isolated_root):
    plan = analyze({"text": "x"}, llm_fn=stub_llm(ANSWER), catalogue="")
    path = workbench.save_plan(plan)
    assert path.parent == isolated_root / "output" / "research"
    listed = workbench.list_plans()
    assert [item["id"] for item in listed] == [plan.id]
    assert listed[0]["verdict"] == "high"
    assert listed[0]["steps"] == 3
    loaded = workbench.load_plan(plan.id)
    assert loaded["title"] == plan.title
    assert loaded["markdown"].startswith("# ")
    assert ResearchPlan.from_dict(loaded).steps == plan.steps
    assert workbench.delete_plan(plan.id) is True
    assert workbench.load_plan(plan.id) is None
    assert workbench.delete_plan(plan.id) is False


def test_plan_ids_cannot_escape_the_store(isolated_root):
    with pytest.raises(ResearchError):
        workbench.load_plan("../../etc/passwd")


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


def test_unknown_endpoints_are_404():
    assert research_api.handle_get("/api/research/nope")[1] == 404
    assert research_api.handle_post("/api/research/nope", {})[1] == 404
    assert research_api.handle_get("/api/research/jobs/plan-deadbeef")[1] == 404
    assert research_api.handle_get("/api/research/plans/nope-0000")[1] == 404


def test_empty_request_is_a_400_not_a_job():
    body, status = research_api.handle_post("/api/research/analyze", {"text": ""})
    assert status == 400
    assert "error" in body


def test_context_lists_providers_catalogue_and_plans(isolated_root, monkeypatch):
    monkeypatch.setattr(research_api, "_providers", lambda: [{"name": "m1", "model": "x", "is_default": True}])
    body, status = research_api.handle_get("/api/research/context")
    assert status == 200
    assert body["providers"][0]["name"] == "m1"
    assert body["catalogue"]["available"] is True
    assert body["plans"] == []


def test_analysis_job_lands_and_is_exportable(isolated_root, monkeypatch):
    import gaworld.llm.providers as providers

    seen = {}

    def fake_call(prompt, **kwargs):
        seen["prompt"] = prompt
        seen["kwargs"] = kwargs
        return json.dumps(ANSWER, ensure_ascii=False)

    monkeypatch.setattr(providers, "call_llm", fake_call)
    monkeypatch.setattr(providers, "resolve_provider", lambda **kwargs: kwargs.get("provider") or "routed")

    body, status = research_api.handle_post(
        "/api/research/analyze", {"text": "补贴", "kind": "idea", "provider": "m1", "language": "zh-CN"}
    )
    assert status == 202
    record = _await_job(body["job_id"])
    assert record["status"] == "done", record
    assert seen["kwargs"]["provider"] == "m1"
    assert seen["kwargs"]["task"] == "research"
    assert seen["kwargs"]["max_tokens"] == workbench.PLAN_MAX_TOKENS
    assert "平行世界实验" in seen["prompt"]  # the catalogue from disk

    plan_id = record["result"]["plan_id"]
    detail, status = research_api.handle_get(f"/api/research/plans/{plan_id}")
    assert status == 200
    assert detail["provider"] == "m1"
    export, status = research_api.handle_get(f"/api/research/plans/{plan_id}/export")
    assert status == 200
    assert export["filename"].endswith(f"-{plan_id}.md")
    assert export["markdown"].startswith("# 租金补贴与邻里交往")

    listed, _ = research_api.handle_get("/api/research/plans")
    assert [item["id"] for item in listed["plans"]] == [plan_id]
    deleted, _ = research_api.handle_post("/api/research/delete", {"plan_id": plan_id})
    assert deleted["deleted"] is True
    assert research_api.handle_get(f"/api/research/plans/{plan_id}")[1] == 404


def test_digest_job_returns_the_reading(monkeypatch):
    import gaworld.llm.providers as providers

    seen = {}

    def fake_call(prompt, **kwargs):
        seen["kwargs"] = kwargs
        return json.dumps(DIGEST_ANSWER, ensure_ascii=False)

    monkeypatch.setattr(providers, "call_llm", fake_call)
    body, status = research_api.handle_post("/api/research/digest", {"text": "论文", "provider": "m1"})
    assert status == 202
    record = _await_job(body["job_id"])
    assert record["status"] == "done", record
    assert record["result"]["paper_digest"]["theory"] == "社会资本理论"
    assert seen["kwargs"] == {"task": "research", "provider": "m1", "max_tokens": workbench.DIGEST_MAX_TOKENS}
    assert research_api.handle_post("/api/research/digest", {"text": ""})[1] == 400


def test_failed_model_call_marks_the_job(isolated_root, monkeypatch):
    import gaworld.llm.providers as providers

    def broken(prompt, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(providers, "call_llm", broken)
    monkeypatch.setattr(providers, "resolve_provider", lambda **kwargs: "m1")
    body, _ = research_api.handle_post("/api/research/analyze", {"text": "x"})
    record = _await_job(body["job_id"])
    assert record["status"] == "error"
    assert "model down" in record["message"]


def test_extract_decodes_plain_text():
    data = base64.b64encode("论文摘要：……".encode("utf-8")).decode("ascii")
    body, status = research_api.handle_post("/api/research/extract", {"name": "paper.txt", "data": "data:text/plain;base64," + data})
    assert status == 200
    assert body["text"] == "论文摘要：……"
    assert body["pages"] == 1


def test_extract_rejects_garbage():
    assert research_api.handle_post("/api/research/extract", {"name": "a.txt", "data": ""})[1] == 400
    assert research_api.handle_post("/api/research/extract", {"name": "a.txt", "data": "%%%"})[1] == 400


def test_extract_pdf_needs_pypdf_or_says_so():
    data = base64.b64encode(b"%PDF-1.4 not really a pdf").decode("ascii")
    body, status = research_api.handle_post("/api/research/extract", {"name": "p.pdf", "data": data})
    # Either pypdf is missing (told to install or paste) or it is present and
    # the bytes are not a PDF (told the file is unreadable). Never a 500.
    assert status == 400
    assert body["error"]
