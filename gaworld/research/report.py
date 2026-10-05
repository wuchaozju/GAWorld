"""The study report: pre-registration first, then what happened.

The order is the argument. A reader sees the predictions — direction,
minimum effect, which two worlds — before any number, so a result cannot
be quietly re-described as what was expected all along. Verdicts are
printed with the reasons the evaluator gave; the model's reading comes
after, with any finding it could not tie to a hypothesis marked as such.
"""

from __future__ import annotations

from typing import Any

_L = {
    "zh-CN": {
        "stage": "阶段", "plan": "来源方案", "model": "编译模型", "created": "创建时间", "sim_model": "仿真模型",
        "routed": "按配置路由", "prereg": "预注册", "sample": "样本", "agents": "参与居民", "all_agents": "配置里的全部居民",
        "days": "仿真天数", "fast": "快速模式", "seeds": "种子", "placebo": "安慰剂世界", "yes": "有", "no": "无",
        "conditions": "条件", "cid": "id", "label": "名称", "role": "角色", "events": "事件", "none": "无",
        "hypotheses": "假设与预测", "hid": "id", "statement": "假设", "measure": "指标", "contrast": "对比",
        "direction": "预测方向", "min_effect": "最小效应", "aggregation": "聚合", "dropped": "编译时丢弃的内容",
        "preflight": "跑前检查", "errors": "错误", "warnings": "警告", "budget": "估算调用量",
        "runs": "执行记录", "seed": "种子", "dir": "目录", "status": "状态", "worlds": "各世界",
        "results": "结果", "effects_per_seed": "各种子效应", "treatment_value": "处理值", "control_value": "对照值",
        "effect": "效应", "placebo_gap": "安慰剂偏差", "paired": "居民配对检验（事件后 ATE · 95% CI · q）", "mean": "均值效应", "noise": "噪声底线", "verdict": "判定",
        "reasons": "判定依据", "summary": "汇总", "quality": "数据质量", "quality_ok": "所有世界都有数据，所有指标都有变化。",
        "interpretation": "解读", "interpretation_missing": "解读不可用", "findings": "发现", "ungrounded": "（未挂到任何假设，不作数）",
        "limitations": "局限", "next": "后续研究", "change": "改动", "notes": "备注", "values": "各世界终值",
        "world": "世界", "increase": "上升", "decrease": "下降",
        "supported": "支持", "contradicted": "反向", "inconclusive": "不确定", "unmeasured": "未测到",
        "baseline": "基准", "treatment": "处理", "placebo_role": "安慰剂",
        "survey": "问卷（跑完后在每个世界里用该世界的记忆采访居民）", "survey_context": "开场白",
        "scale": "量表", "boolean": "是/否", "open": "开放题（不计分）",
        "survey_answers": "问卷作答", "answered": "计分人数", "unparsed": "无法计分", "respondents": "受访者",
        "provenance": "指标来源", "grade": "等级", "basis": "由什么驱动",
        "grade_legend": "等级取它依赖的机制里最弱的一级（定义见 benchmark/MECHANISM_PROVENANCE.md）。(c) = 自定的合理猜测或按目标标定的旋钮：不得单独立论，只读方向，效应大小不作数。",
        "direction_only": "（{grade} 级：只读方向，大小不作数）",
        "cites_size": "（对只读方向的指标写了效应大小，大小不作数）",
    },
    "en": {
        "stage": "Stage", "plan": "Source plan", "model": "Compiled by", "created": "Created", "sim_model": "Simulation model",
        "routed": "routed by config", "prereg": "Pre-registration", "sample": "Sample", "agents": "Residents", "all_agents": "every resident in the config",
        "days": "Simulated days", "fast": "Fast mode", "seeds": "Seeds", "placebo": "Placebo world", "yes": "yes", "no": "no",
        "conditions": "Conditions", "cid": "id", "label": "Label", "role": "Role", "events": "Events", "none": "none",
        "hypotheses": "Hypotheses & predictions", "hid": "id", "statement": "Hypothesis", "measure": "Measure", "contrast": "Contrast",
        "direction": "Predicted direction", "min_effect": "Min effect", "aggregation": "Aggregation", "dropped": "Dropped at compile time",
        "preflight": "Preflight", "errors": "Errors", "warnings": "Warnings", "budget": "Estimated LLM calls",
        "runs": "Execution", "seed": "Seed", "dir": "Directory", "status": "Status", "worlds": "Worlds",
        "results": "Results", "effects_per_seed": "Effect per seed", "treatment_value": "Treatment", "control_value": "Control",
        "effect": "Effect", "placebo_gap": "Placebo gap", "paired": "Paired resident test (post-event ATE · 95% CI · q)", "mean": "Mean effect", "noise": "Noise floor", "verdict": "Verdict",
        "reasons": "Reasons", "summary": "Summary", "quality": "Data quality", "quality_ok": "Every world has data and every measure varied.",
        "interpretation": "Interpretation", "interpretation_missing": "Interpretation unavailable", "findings": "Findings", "ungrounded": "(not tied to any hypothesis; disregard)",
        "limitations": "Limitations", "next": "Next studies", "change": "Change", "notes": "Notes", "values": "Final values per world",
        "world": "World", "increase": "increase", "decrease": "decrease",
        "supported": "supported", "contradicted": "contradicted", "inconclusive": "inconclusive", "unmeasured": "unmeasured",
        "baseline": "baseline", "treatment": "treatment", "placebo_role": "placebo",
        "survey": "Survey (asked in every world after the run, with that world's memories)", "survey_context": "Opening",
        "scale": "scale", "boolean": "yes/no", "open": "open (not scored)",
        "survey_answers": "Survey responses", "answered": "Scored", "unparsed": "Unscorable", "respondents": "Respondents",
        "provenance": "Measure provenance", "grade": "Grade", "basis": "Driven by",
        "grade_legend": "A measure's grade is the weakest among the mechanisms behind it (defined in benchmark/MECHANISM_PROVENANCE.md). (c) = a reasonable guess of ours or a knob tuned to a target: it cannot carry a conclusion alone — read the direction, not the size.",
        "direction_only": " (grade {grade}: direction only, the size does not count)",
        "cites_size": " (states a size on a direction-only measure; the size does not count)",
    },
}


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _num(value: Any, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f"{float(value):+.4f}" if signed else f"{float(value):.4f}"


def _paired(test: dict[str, Any] | None) -> str:
    if not test:
        return "—"
    q = test.get("q_value")
    return (
        f"{_num(test.get('ate'))} [{_num(test.get('ci_low'))}, {_num(test.get('ci_high'))}]"
        f" q={'—' if q is None else f'{float(q):.3g}'}"
    )


def render_study_markdown(study: dict[str, Any]) -> str:
    """The downloadable document for one study, at whatever stage it is."""
    protocol = study.get("protocol") or {}
    L = _L.get(str(study.get("language") or protocol.get("language") or "zh-CN"), _L["zh-CN"])
    role_label = {"baseline": L["baseline"], "treatment": L["treatment"], "placebo": L["placebo_role"]}

    lines: list[str] = [f"# {study.get('title') or protocol.get('title') or 'Study'}", ""]
    meta = [
        f"{L['stage']}: {study.get('stage', '')}",
        f"{L['plan']}: {study.get('plan_id', '')}",
        f"{L['model']}: {study.get('provider') or L['routed']}",
        f"{L['sim_model']}: {protocol.get('sim_provider') or L['routed']}",
        f"{L['created']}: {study.get('created_at', '')}",
    ]
    lines += [" · ".join(meta), ""]

    # -- pre-registration ----------------------------------------------------
    sample = protocol.get("sample") or {}
    validity = protocol.get("validity") or {}
    lines += [f"## {L['prereg']}", ""]
    agents = sample.get("agent_ids") or []
    lines.append(f"- **{L['agents']}**: {', '.join(str(a) for a in agents) if agents else L['all_agents']}")
    if sample.get("city"):
        lines.append(f"- **{L['sample']}**: {sample['city']}" + (f" — {sample['note']}" if sample.get("note") else ""))
    lines.append(f"- **{L['days']}**: {protocol.get('sim_days', '')} · {L['fast']}: {L['yes'] if protocol.get('fast') else L['no']}")
    seeds = validity.get("seeds") or []
    has_placebo = any(cond.get("role") == "placebo" for cond in protocol.get("conditions") or [])
    lines.append(f"- **{L['seeds']}**: {', '.join(str(s) for s in seeds)} · {L['placebo']}: {L['yes'] if has_placebo else L['no']}")
    lines.append("")

    lines += [f"### {L['conditions']}", "", f"| {L['cid']} | {L['label']} | {L['role']} | {L['events']} |", "|---|---|---|---|"]
    for cond in protocol.get("conditions") or []:
        events = "; ".join(
            f"Day {e.get('day')} {e.get('time')} {e.get('name')}" for e in cond.get("events") or []
        ) or L["none"]
        if cond.get("config"):
            events += f" · config: {_cell(cond['config'])}"
        lines.append(f"| {cond.get('id')} | {_cell(cond.get('label'))} | {role_label.get(cond.get('role'), cond.get('role'))} | {_cell(events)} |")
    lines.append("")

    lines += [
        f"### {L['hypotheses']}", "",
        f"| {L['hid']} | {L['statement']} | {L['measure']} | {L['contrast']} | {L['direction']} | {L['min_effect']} | {L['aggregation']} |",
        "|---|---|---|---|---|---|---|",
    ]
    grades = {str(m.get("id")): m for m in protocol.get("measures") or [] if isinstance(m, dict)}
    for item in protocol.get("hypotheses") or []:
        grade = (grades.get(str(item.get("measure"))) or {}).get("grade")
        lines.append(
            f"| {item.get('id')} | {_cell(item.get('statement'))} | {item.get('measure')}{f' ({grade})' if grade else ''} "
            f"| {item.get('treatment')} vs {item.get('control')} | {L.get(item.get('direction', ''), item.get('direction'))} "
            f"| {_num(item.get('min_effect'), signed=False)} | {item.get('aggregation')} |"
        )
    lines.append("")
    graded = [m for m in grades.values() if m.get("grade")]
    if graded:
        lines += [f"### {L['provenance']}", "", L["grade_legend"], "",
                  f"| {L['measure']} | {L['grade']} | {L['basis']} |", "|---|---|---|"]
        lines += [f"| {m.get('id')} | ({m.get('grade')}) | {_cell(m.get('basis'))} |" for m in graded]
        lines.append("")
    survey = protocol.get("survey") or {}
    if survey.get("questions"):
        lines += [f"### {L['survey']}", ""]
        if survey.get("context"):
            lines += [f"{L['survey_context']}：{survey['context']}", ""]
        for question in survey["questions"]:
            kind = L.get(question.get("kind", ""), question.get("kind", ""))
            options = " / ".join(question.get("options") or [])
            lines.append(f"- **{question.get('id')}**（{kind}{'：' + options if options else ''}）{question.get('text')}")
        lines.append("")
    if protocol.get("dropped"):
        lines += [f"**{L['dropped']}**", ""]
        lines += [f"- {item.get('what')} · {_cell(item.get('where'))}: {_cell(item.get('reason'))}" for item in protocol["dropped"]]
        lines.append("")

    preflight = study.get("preflight") or {}
    if preflight:
        lines += [f"### {L['preflight']}", ""]
        budget = preflight.get("budget") or {}
        if budget:
            lines.append(
                f"- **{L['budget']}**: {budget.get('estimated_calls', 0):,} / {budget.get('limit', 0):,} "
                f"({budget.get('agents')} × {budget.get('sim_days')}d × {budget.get('calls_per_agent_day')} "
                f"× {budget.get('worlds')} worlds × {budget.get('seeds')} seeds)"
            )
        for label, key in ((L["errors"], "errors"), (L["warnings"], "warnings")):
            for item in preflight.get(key) or []:
                lines.append(f"- **{label}**: {item}")
        lines.append("")

    # -- execution -----------------------------------------------------------
    runs = study.get("runs") or []
    if runs:
        lines += [f"## {L['runs']}", "", f"| {L['seed']} | {L['dir']} | {L['status']} | {L['worlds']} |", "|---|---|---|---|"]
        for run in runs:
            worlds = ", ".join(f"{wid}: {status}" for wid, status in (run.get("world_status") or {}).items())
            lines.append(f"| {run.get('seed')} | `{run.get('root', '')}` | {run.get('status', '')} | {_cell(worlds)} |")
        lines.append("")

    # -- results -------------------------------------------------------------
    evaluation = study.get("evaluation") or {}
    if evaluation:
        lines += [f"## {L['results']}", ""]
        summary = evaluation.get("summary") or {}
        lines.append(f"**{L['summary']}**: " + " · ".join(f"{L.get(k, k)} {v}" for k, v in summary.items()))
        lines.append("")
        for item in evaluation.get("hypotheses") or []:
            verdict = item.get("verdict", "")
            lines += [f"### {item.get('id')} · {L.get(verdict, verdict)}", ""]
            if item.get("statement"):
                lines += [item["statement"], ""]
            lines += [
                f"| {L['seed']} | {L['treatment_value']} | {L['control_value']} | {L['effect']} | {L['placebo_gap']} | {L['paired']} |",
                "|---|---|---|---|---|---|",
            ]
            for row in item.get("effects") or []:
                lines.append(
                    f"| {row.get('seed')} | {_num(row.get('treatment_value'), signed=False)} | {_num(row.get('control_value'), signed=False)} "
                    f"| {_num(row.get('effect'))} | {_num(row.get('placebo_gap'), signed=False)} | {_paired(row.get('paired'))} |"
                )
            lines.append("")
            caveat = L["direction_only"].format(grade=item.get("measure_grade") or "?") if item.get("direction_only") else ""
            lines.append(f"- **{L['mean']}**: {_num(item.get('mean_effect'))}{caveat} · **{L['noise']}**: {_num(item.get('noise'), signed=False)}")
            lines.append(f"- **{L['reasons']}**: " + "；".join(item.get("reasons") or []))
            lines.append("")

        quality = evaluation.get("quality") or {}
        lines += [f"### {L['quality']}", ""]
        if quality.get("issues"):
            for issue in quality["issues"]:
                where = " · ".join(str(part) for part in (issue.get("seed"), issue.get("condition")) if part is not None)
                lines.append(f"- {issue.get('issue')}" + (f"（{where}）" if where else "") + (f"：{issue.get('detail')}" if issue.get("detail") else ""))
        else:
            lines.append(L["quality_ok"])
        lines.append("")

        values = evaluation.get("values") or {}
        if values:
            seeds = evaluation.get("seeds") or []
            lines += [f"### {L['values']}", "", f"| {L['measure']} | {L['world']} | " + " | ".join(f"s{s}" for s in seeds) + " |", "|---" * (2 + len(seeds)) + "|"]
            for metric, by_world in values.items():
                for world_id, by_seed in by_world.items():
                    # Seed keys are ints in memory and strings once the study
                    # has been through JSON; the table must read both.
                    cells = " | ".join(
                        _num(by_seed.get(s, by_seed.get(str(s))), signed=False) for s in seeds
                    )
                    lines.append(f"| {metric} | {world_id} | {cells} |")
            lines.append("")

        surveyed = [run for run in runs if isinstance(run.get("survey"), dict)]
        if surveyed:
            lines += [f"### {L['survey_answers']}", "",
                      f"| {L['seed']} | {L['world']} | {L['measure']} | {L['answered']} | {L['unparsed']} |",
                      "|---|---|---|---|---|"]
            for run in surveyed:
                for world_id, block in run["survey"].items():
                    if not isinstance(block, dict):
                        continue
                    if block.get("error"):
                        lines.append(f"| {run.get('seed')} | {world_id} | — | — | {_cell(block['error'])} |")
                        continue
                    for metric, score in (block.get("scores") or {}).items():
                        lines.append(f"| {run.get('seed')} | {world_id} | {metric} | {score.get('n', 0)} | {score.get('unparsed', 0)} |")
            lines.append("")

    # -- interpretation ------------------------------------------------------
    interpretation = study.get("interpretation") or {}
    if evaluation:
        lines += [f"## {L['interpretation']}", ""]
        if interpretation.get("error") or not interpretation:
            lines += [f"_{L['interpretation_missing']}_" + (f": {interpretation.get('error')}" if interpretation.get("error") else ""), ""]
        else:
            if interpretation.get("findings"):
                lines += [f"### {L['findings']}", ""]
                for finding in interpretation["findings"]:
                    tag = ("" if finding.get("grounded") else f" {L['ungrounded']}") + (L["cites_size"] if finding.get("cites_size") else "")
                    lines.append(f"- **{finding.get('hypothesis') or '?'}**{tag}: {finding.get('claim')}"
                                 + (f" — {finding['evidence']}" if finding.get("evidence") else ""))
                lines.append("")
            if interpretation.get("limitations"):
                lines += [f"### {L['limitations']}", ""] + [f"- {item}" for item in interpretation["limitations"]] + [""]
            if interpretation.get("next_studies"):
                lines += [f"### {L['next']}", ""]
                for item in interpretation["next_studies"]:
                    lines.append(f"- **{item.get('title')}**: {item.get('rationale', '')}"
                                 + (f"  \n  {L['change']}: {item['change']}" if item.get("change") else ""))
                lines.append("")

    if protocol.get("notes"):
        lines += [f"## {L['notes']}", "", protocol["notes"], ""]
    if study.get("error"):
        lines += ["", f"**Error**: {study['error']}", ""]
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["render_study_markdown"]
