"""Authorize source versions and construct explicitly reusable, credential-free drafts."""

from __future__ import annotations

import re
import time

from gaworld.accounts.context import WORLD
from gaworld.research import workbench, workspaces

from .validation import digest

# Textual research design fields only; never copy runtime overrides or provider config.
PLAN_FIELDS = {
    "title",
    "summary",
    "research_questions",
    "hypotheses",
    "design",
    "designs",
    "recommended_design",
    "validation",
}
DESIGN_FIELDS = {
    "name",
    "approach",
    "strengths",
    "weaknesses",
    "city",
    "population",
    "agents",
    "timeline",
    "conditions",
    "events",
    "measures",
    "manipulation",
    "operationalization",
    "source",
}


def _design(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_design(v) for v in value[:100]]
    if isinstance(value, dict):
        return {k: _design(v) for k, v in value.items() if k in DESIGN_FIELDS}
    return value if isinstance(value, (int, float, bool)) else None


def template(plan):
    return {k: _design(v) for k, v in plan.items() if k in PLAN_FIELDS}


def source_preview(user, data):
    kind, sid = data.get("kind"), str(data.get("id") or "")
    if kind == "plan":
        record = workbench.load_plan(sid)
        if not workspaces.visible(record):
            raise ValueError("来源研究不存在或不属于当前工作台")
        plan, body, status = record, record.get("summary", ""), "plan"
    elif kind == "study":
        from gaworld.apps.research_api import _load_study

        found = _load_study(sid)
        record, plan, body = found.to_dict(), found.source_plan, found.report_markdown
        status = (
            "completed" if found.stage == "reported" else "failed" if found.stage == "error" else "partial"
        )
    elif kind == "simulation":
        from gaworld.apps import world_paths

        world = WORLD.get() or {}
        if world.get("owner_id") != user["id"] or sid != world.get("id"):
            raise ValueError("只能分享自己的当前世界")
        # Snapshot only metadata; raw residents, paths and live runtime stay private.
        record = {k: world.get(k) for k in ("id", "name", "city", "owner_id")}
        from gaworld import worlds

        config = worlds.read_config(world_paths.REPO_ROOT, sid)
        record["config_revision"] = digest(config)
        plan, body, status = (
            {},
            f"仿真案例：{world['name']}\n城市模板：{world.get('city', '')}\n请填写方法、运行结果与局限。",
            "plan",
        )
    else:
        raise ValueError("来源类型不支持")
    if record.get("owner_id") != user["id"] and not (
        user.get("role") == "admin" and record.get("owner_id") is None
    ):
        raise ValueError("不能发布他人的私人来源")
    public_template = template(plan)
    # Only redact credentials known from source structured configuration, not arbitrary author text.
    secrets = []

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    re.search(r"api_key|password|secret|access_token", key, re.I)
                    and isinstance(item, str)
                    and item
                ):
                    secrets.append(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(record)

    def scrub(value):
        if isinstance(value, str):
            for private in secrets:
                value = value.replace(private, "[已隐藏]")
            return value
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return {
        "kind": kind,
        "id": sid,
        "world_id": str(record.get("world_id") or (WORLD.get() or {}).get("id") or ""),
        "revision": digest(record),
        "template": scrub(public_template),
        "title": str(plan.get("title") or record.get("name") or "研究成果"),
        "body": scrub(body),
        "result_status": status,
    }


def fork(store, user, pid, version, world_id):
    payload = store.fork_payload(user, pid, version)
    current = str((WORLD.get() or {}).get("id") or "")
    if world_id != current:
        raise ValueError("目标世界已改变，请重新选择")
    if current and (WORLD.get() or {}).get("owner_id") != user["id"]:
        raise ValueError("请选择自己的世界")
    # Preserve the conceptual design but require reconfiguration and explicit compilation/run.
    data = {
        **payload["template"],
        "id": workbench.new_plan_id(),
        "kind": "idea",
        "language": "zh-CN",
        "provider": "",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "steps": [],
        "material": "从公开研究复制的方案；请选择本人的城市、居民和模型，修改配置后再编译运行。",
    }
    data["title"] = "改编 · " + str(data.get("title") or "研究方案")
    plan = workbench.ResearchPlan.from_dict(data)
    workbench.save_plan(
        plan,
        {
            **workspaces.stamp(),
            "provenance": payload["provenance"],
            "adapted": True,
            "requires_configuration": True,
        },
    )
    return {"plan_id": plan.id, "world_id": current, "status": "draft", "requires_configuration": True}
