"""Plain-language summaries derived from saved plans and scored evidence."""

from __future__ import annotations

from typing import Any


def _english(data: dict[str, Any]) -> bool:
    return str(data.get("language") or (data.get("protocol") or {}).get("language") or "zh-CN") == "en"


def plan_summary(plan: dict[str, Any], design_index: int | None = None) -> dict[str, Any]:
    en = _english(plan)
    missing = "Not provided" if en else "未提供"
    designs = plan.get("designs") or []
    index = plan.get("recommended_design", 0) if design_index is None else design_index
    design = designs[max(0, min(int(index), len(designs) - 1))] if designs else plan.get("design") or {}
    conditions = [
        f"{c.get('name', '')}: {c.get('manipulation') or missing}" for c in design.get("conditions") or []
    ]
    measures = [
        f"{m.get('name', '')}: {m.get('operationalization') or missing}" for m in design.get("measures") or []
    ]
    cost = (plan.get("estimated_cost") or {}).get("llm_calls") or missing
    if designs and int(index) != int(plan.get("recommended_design") or 0):
        cost = (
            "No separate estimate for this design; recommended design estimate: "
            if en
            else "当前设计未单独估算；推荐设计的估算为："
        ) + cost
    return {
        "title": "Study at a glance" if en else "先读懂这份方案",
        "lead": " / ".join(plan.get("research_questions") or []) or plan.get("summary") or missing,
        "facts": [
            {"label": "Selected design" if en else "当前设计", "text": design.get("name") or missing},
            {
                "label": "Who and how long" if en else "研究对象与时长",
                "text": " · ".join(
                    str(design.get(k)) for k in ("city", "population", "timeline") if design.get(k)
                )
                or missing,
            },
            {"label": "What changes" if en else "比较什么", "text": "; ".join(conditions) or missing},
            {"label": "What is measured" if en else "观察什么", "text": "; ".join(measures) or missing},
            {
                "label": "Estimated model calls" if en else "预计运行量",
                "text": cost,
            },
        ],
        "notice": "A proposed simulation design; feasibility and cost still need protocol checks."
        if en
        else "这是待检验的仿真设计；可运行性和调用量仍需生成运行方案后检查。",
        "next": "Review the selected design, then create the run protocol."
        if en
        else "先确认当前实验设计，再点击「转成研究」检查并运行。",
        "findings": [],
    }


def study_summary(study: dict[str, Any]) -> dict[str, Any]:
    en = _english(study)
    protocol = study.get("protocol") or {}
    evaluation = study.get("evaluation") or {}
    hypotheses = evaluation.get("hypotheses") or []
    stage = study.get("stage") or "protocol"
    labels = {
        "supported": "Supported in this simulation" if en else "本次仿真支持",
        "contradicted": "Opposite to the prediction" if en else "与预期方向相反",
        "inconclusive": "Evidence is inconclusive" if en else "证据尚不足以判断",
        "unmeasured": "No comparable measurements" if en else "没有可比较的测量结果",
    }
    findings = []
    for item in hypotheses:
        verdict = item.get("verdict") or "unmeasured"
        limit = ""
        if item.get("direction_only") or item.get("measure_grade") == "c":
            limit = (
                "Read direction only; the effect size cannot support a claim."
                if en
                else "该指标只能观察方向；效应大小不能作为结论依据。"
            )
        findings.append(
            {
                "id": item.get("id") or "",
                "title": item.get("statement") or item.get("id") or "",
                "verdict": verdict,
                "text": labels.get(verdict, labels["unmeasured"]),
                "evidence": "; ".join(str(reason) for reason in item.get("reasons") or [])
                or ("See the measurements below." if en else "请结合下方测量数据阅读。"),
                "limit": limit,
            }
        )
    if hypotheses:
        counts = {key: sum(item.get("verdict") == key for item in hypotheses) for key in labels}
        lead = (
            f"{counts['supported']} supported, {counts['contradicted']} opposite, "
            f"{counts['inconclusive']} inconclusive, {counts['unmeasured']} unmeasured. Read the reasons below."
            if en
            else f"逐条假设判定：{counts['supported']} 条支持、{counts['contradicted']} 条反向、"
            f"{counts['inconclusive']} 条尚不能判断、{counts['unmeasured']} 条未测到。请结合每条依据阅读。"
        )
    elif stage == "error":
        lead = (
            "The run did not finish. A failure record cannot answer the research question."
            if en
            else "研究未完成；失败记录不能回答研究问题。"
        )
    else:
        lead = "Comparable statistical results are not available yet." if en else "尚未生成可比较的统计结果。"
    if stage == "evaluated":
        next_step = (
            "Statistics are ready to read and download; the optional model interpretation is pending."
            if en
            else "统计已完成，可先阅读和下载报告；模型补充解读仍在生成。"
        )
        if study.get("live") is False:
            next_step = (
                "Statistics are saved. Interpretation did not finish; the report is still available."
                if en
                else "统计结果已保存，补充解读未完成；仍可阅读和下载报告。"
            )
    elif stage == "protocol":
        next_step = (
            "Check the sample, conditions and budget before approval."
            if en
            else "核对居民样本、实验条件和调用预算，通过检查后批准运行。"
        )
    elif stage == "approved":
        next_step = (
            "The protocol is approved. Start the run when ready." if en else "运行方案已批准，可以开始运行。"
        )
    elif stage == "error":
        next_step = (
            "Check the failure and logs before creating a new attempt."
            if en
            else "先查看失败原因与日志，再决定是否重置并重新运行。"
        )
    elif stage == "running":
        next_step = (
            "Wait for simulation and scoring; refreshing the page will not restart the study."
            if en
            else "等待仿真和统计完成；刷新页面不会重新启动研究。"
        )
    else:
        next_step = (
            "Review data quality and limitations before drawing conclusions."
            if en
            else "结合数据质量和局限阅读结果，再决定下一步研究。"
        )
    sample_ids = (
        (study.get("runtime") or {}).get("actual_agent_ids")
        or (protocol.get("sample") or {}).get("agent_ids")
        or []
    )
    sample = str(len(sample_ids)) if sample_ids else ("From run configuration" if en else "按运行配置")
    seeds = (protocol.get("validity") or {}).get("seeds") or []
    issues = (evaluation.get("quality") or {}).get("issues") or []
    notice = (
        "Simulation evidence does not establish effects on real people."
        if en
        else "这里的证据来自智能体仿真，不能直接推断真实人群的效果。"
    )
    if protocol.get("purpose") == "exploratory" or protocol.get("execution_mode") == "daily_brief":
        notice += " Exploratory pilot only." if en else " 本研究为探索试跑，不作正式假设验证。"
    if issues:
        notice += (
            f" Data quality issues: {len(issues)}."
            if en
            else f" 另有 {len(issues)} 项数据质量问题，详见统计明细。"
        )
    return {
        "title": "At a glance" if en else "先看结果与下一步",
        "lead": lead,
        "findings": findings,
        "facts": [
            {"label": "Residents" if en else "参与居民数", "text": sample},
            {
                "label": "Planned days / worlds / seeds" if en else "计划天数 / 世界数 / 种子数",
                "text": f"{protocol.get('sim_days', '—')} / {len(protocol.get('conditions') or [])} / {len(seeds)}",
            },
        ],
        "notice": notice,
        "next": next_step,
        "terms_title": "How to read the statistics" if en else "如何读统计表",
        "terms": [
            {
                "label": "Effect" if en else "效应",
                "text": "Treatment minus control; a negative value means the treatment is lower."
                if en
                else "处理组减去对照组；负值表示处理组更低，正值表示更高。",
            },
            {
                "label": "95% CI" if en else "95% 区间",
                "text": "The paired bootstrap interval describes estimation uncertainty; crossing zero weakens evidence for a clear direction."
                if en
                else "居民配对的自助法区间用于表达估计的不确定性；跨过 0 时，方向证据不足。",
            },
            {
                "label": "q" if en else "q 值",
                "text": "A p-value adjusted for multiple comparisons; read it with effect, interval and quality checks."
                if en
                else "经过多重比较校正的 p 值；需要连同效应、区间和质量检查一起看。",
            },
            {
                "label": "Seed" if en else "种子",
                "text": "An independent random starting point used to check whether results repeat."
                if en
                else "控制随机过程的起点；换种子重复运行，用于观察结果是否稳定。",
            },
        ],
    }


def markdown(brief: dict[str, Any]) -> str:
    lines = [f"## {brief['title']}", "", str(brief["lead"]), ""]
    lines.extend(f"- **{fact['label']}**: {fact['text']}" for fact in brief.get("facts") or [])
    for finding in brief.get("findings") or []:
        lines += [
            "",
            f"### {finding['id']} · {finding['text']}",
            "",
            str(finding["title"]),
            "",
            str(finding["evidence"]),
        ]
        if finding.get("limit"):
            lines += ["", str(finding["limit"])]
    lines += ["", f"> {brief['notice']}", "", str(brief["next"]), ""]
    if brief.get("terms"):
        lines += [f"### {brief['terms_title']}", ""]
        lines.extend(f"- **{term['label']}**: {term['text']}" for term in brief["terms"])
        lines += [""]
    return "\n".join(lines)
