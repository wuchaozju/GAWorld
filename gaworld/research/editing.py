"""Validated content editing; identity and existing results stay immutable."""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from gaworld.parallel.spec import normalize_event, sanitize_world_config
from gaworld.research import measures, survey
from gaworld.research.protocol import EXECUTION_MODES, MAX_SIM_DAYS, Protocol

PLAN_FIELDS = {
    "title": str,
    "summary": str,
    "research_questions": list,
    "hypotheses": list,
    "paper_digest": dict,
    "feasibility": dict,
    "capability_map": list,
    "design": dict,
    "designs": list,
    "recommended_design": int,
    "steps": list,
    "validation": list,
    "gaps": list,
    "estimated_cost": dict,
    "material": str,
}


def validate_code_overrides(patch: dict[str, Any]) -> None:
    from gaworld.accounts.context import USER

    user = USER.get()
    if user and user.get("role") != "admin" and set(patch) & {"plugins", "pipeline"}:
        raise ValueError("普通用户的研究条件不能替换服务器插件或加载自定义代码")


def bounded_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("方案必须是一个对象")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > 256_000:
        raise ValueError("方案内容过长（上限 256000 字符）")
    return copy.deepcopy(value)


def plan_edit(current: dict[str, Any], changes: Any) -> dict[str, Any]:
    changes = bounded_object(changes)
    if set(changes) - PLAN_FIELDS.keys():
        raise ValueError("不能修改方案身份、所有者或未知字段")
    result = copy.deepcopy(current)
    for key, value in changes.items():
        if not isinstance(value, PLAN_FIELDS[key]):
            raise ValueError(f"方案字段 {key} 类型不正确")
        result[key] = value
    if not result.get("title", "").strip():
        raise ValueError("标题不能为空")
    for key in ("research_questions", "hypotheses", "validation"):
        if any(not isinstance(item, str) for item in result.get(key, [])):
            raise ValueError(f"{key} 必须是文字列表")
    for key in ("capability_map", "steps", "gaps", "designs"):
        if any(not isinstance(item, dict) for item in result.get(key, [])):
            raise ValueError(f"{key} 必须是对象列表")
    if result.get("designs"):
        index = result.get("recommended_design", 0)
        if not 0 <= index < len(result["designs"]):
            raise ValueError("推荐设计编号超出范围")
        result["design"] = copy.deepcopy(result["designs"][index])
    history = copy.deepcopy(current.get("revisions") or [])
    history.append({k: v for k, v in current.items() if k not in {"revisions", "markdown"}})
    result["revisions"] = history
    return result


def protocol_edit(current: dict[str, Any], changes: Any) -> Protocol:
    changes = bounded_object(changes)
    if set(changes) - Protocol.__dataclass_fields__.keys():
        raise ValueError("运行方案含未知字段")
    data = {**copy.deepcopy(current), **changes}
    for key in ("sample", "validity", "survey"):
        if not isinstance(data.get(key, {}), dict):
            raise ValueError(f"{key} 必须是对象")
    for key in ("conditions", "hypotheses", "measures"):
        if not isinstance(data.get(key), list) or any(not isinstance(v, dict) for v in data[key]):
            raise ValueError(f"{key} 必须是对象列表")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise ValueError("运行方案标题不能为空")
    if not isinstance(data.get("sim_days"), int) or not 1 <= data["sim_days"] <= MAX_SIM_DAYS:
        raise ValueError("仿真天数超出范围")
    if not isinstance(data.get("max_parallel", 2), int) or not 1 <= data.get("max_parallel", 2) <= 4:
        raise ValueError("世界并发数须为 1 到 4")
    if data.get("execution_mode") not in (*EXECUTION_MODES, "", None):
        raise ValueError("未知运行方式")
    ids = []
    for condition in data["conditions"]:
        cid = condition.get("id")
        if not isinstance(cid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", cid) or cid in ids:
            raise ValueError("条件 ID 不能为空或重复")
        ids.append(cid)
        if condition.get("role") not in {"baseline", "treatment", "placebo"}:
            raise ValueError("条件角色须为 baseline、treatment 或 placebo")
        if not isinstance(condition.get("label"), str):
            raise ValueError("条件名称须为文字")
        patch = condition.get("config") or {}
        if not isinstance(patch, dict):
            raise ValueError("条件配置须为对象")
        sanitize_world_config(patch, where=f"condition {cid}")
        validate_code_overrides(patch)
        if set(patch) & {"city", "csv_path", "md_path", "map_path", "llm", "long_run"}:
            raise ValueError("条件不能替换共享人口、模型或引擎")
        events = condition.get("events", [])
        if not isinstance(events, list):
            raise ValueError("事件须为列表")
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("day"), int) or event["day"] < 1:
                raise ValueError("事件须有正整数 day")
            if not isinstance(event.get("description"), str):
                raise ValueError("事件须有 description 文字")
            normalize_event(event, where=f"condition {cid}")
    if not 2 <= len(ids) <= 8 or sum(c["role"] == "baseline" for c in data["conditions"]) != 1:
        raise ValueError("需要 2–8 个条件且恰好一个基准条件")
    seeds = data["validity"].get("seeds", [])
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(not isinstance(s, int) for s in seeds)
        or len(seeds) > 20
    ):
        raise ValueError("种子须为非空整数列表，最多 20 个")
    residents = data["sample"].get("agent_ids", [])
    if not isinstance(residents, list) or any(not isinstance(i, int) or i < 1 for i in residents):
        raise ValueError("居民 ID 须为正整数列表")
    dropped = []
    if data.get("survey"):
        normalized = survey.normalize_survey(data["survey"], dropped=dropped)
        if dropped:
            raise ValueError("问卷包含不可识别的题目，请修正")
        data["survey"] = normalized
        if any(q.get("kind") in survey.MEASURED_KINDS for q in normalized["questions"]):
            data["kind"] = "composite"
    registered = {**measures.registry(), **survey.survey_measures(data["survey"])}
    if any(not isinstance(m.get("id"), str) for m in data["measures"]):
        raise ValueError("指标 ID 须为文字")
    mids = {m.get("id") for m in data["measures"]}
    if not mids <= registered.keys():
        raise ValueError("指标必须来自已有指标或问卷题")
    data["measures"] = [
        {
            "id": metric.id,
            "label": metric.label,
            "source": metric.source,
            "note": metric.note,
            "grade": metric.grade,
            "basis": metric.basis,
        }
        for metric in (registered[m["id"]] for m in data["measures"])
    ]
    hypothesis_ids = set()
    for h in data["hypotheses"]:
        hid = h.get("id")
        if not isinstance(hid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", hid) or hid in hypothesis_ids:
            raise ValueError("假设 ID 须为唯一的英文字母、数字、下划线或连字符")
        hypothesis_ids.add(hid)
        if not isinstance(h.get("statement"), str) or not h["statement"].strip():
            raise ValueError("假设须包含非空的 statement 文字")
        if any(not isinstance(h.get(key), str) for key in ("measure", "control", "treatment", "direction")):
            raise ValueError("假设的指标、比较条件和方向须为文字")
        if h.get("measure") not in mids or h.get("control") not in ids or h.get("treatment") not in ids:
            raise ValueError("假设引用了不存在的条件或指标")
        if h["control"] == h["treatment"] or h.get("direction") not in {"increase", "decrease"}:
            raise ValueError("假设须比较不同条件并指定 increase/decrease")
        if h.get("aggregation") not in measures.AGGREGATIONS:
            raise ValueError("假设 aggregation 须为 mean 或 final")
        effect = h.get("min_effect")
        if not isinstance(effect, (int, float)) or not math.isfinite(effect) or effect < 0:
            raise ValueError("最小效应须为非负有限数值")
    if current.get("purpose") == "exploratory" or data.get("execution_mode") == "daily_brief":
        data["purpose"] = "exploratory"
    data["plan_id"] = current.get("plan_id", "")
    return Protocol.from_dict(data)
