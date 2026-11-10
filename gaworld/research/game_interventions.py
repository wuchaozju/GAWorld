"""Durable, idempotent interventions applied only at a round boundary."""

from __future__ import annotations

import copy
import time
from typing import Any

from gaworld.research.game_rules import finite


def visible(events: list[dict[str, Any]], role_id: str = "", *, host: bool = False) -> list[dict[str, Any]]:
    return [copy.deepcopy(e) for e in events if host or e["visibility"] in ("public", role_id)]


def enqueue(session: dict[str, Any], payload: dict[str, Any]) -> None:
    if session.get("schema_version") != 2 or session["status"] not in {"acting", "resolving", "paused"}:
        raise ValueError("只有进行中的新版对局可干预")
    iid = str(payload.get("id", "")).strip()[:80]
    if not iid:
        raise ValueError("干预需要唯一id")
    if any(e["id"] == iid for e in session["interventions"] + session["intervention_queue"]):
        return
    if len(session["intervention_queue"]) >= 20 or len(session["interventions"]) >= 100:
        raise ValueError("本局干预数量达到上限")
    scope = str(payload.get("visibility", "public"))
    if scope not in {"public", *(r["id"] for r in session["spec"]["roles"])}:
        raise ValueError("干预可见范围无效")
    changes = payload.get("indicator_changes", {})
    if not isinstance(changes, dict) or set(changes) - set(session["indicators"]):
        raise ValueError("干预指标无效")
    if scope != "public" and changes:
        raise ValueError("公共指标变动必须是公共事件")
    text = str(payload.get("text", "")).strip()[:1600]
    if not text:
        raise ValueError("写下干预内容")
    event = {
        "id": iid,
        "text": text,
        "visibility": scope,
        "submitted_at": time.time(),
        "submitted_by": payload.get("submitted_by"),
        "indicator_changes": {k: finite(v) for k, v in changes.items()},
    }
    for key in ("role", "seat", "required_roles"):
        if key in payload:
            event[key] = copy.deepcopy(payload[key])
    if "role" in event and scope != "public":
        raise ValueError("新角色入场须公开宣布")
    session["intervention_queue"].append(event)
    if session["status"] == "paused":
        apply_queued(session)


def apply_queued(session: dict[str, Any]) -> None:
    if session.get("actions") or session["status"] not in {"acting", "paused"}:
        return
    while session["intervention_queue"]:
        event = copy.deepcopy(session["intervention_queue"][0])
        if not any(e["id"] == event["id"] for e in session["interventions"]):
            if event.get("role"):
                role, seat = event["role"], event["seat"]
                if role["id"] in {r["id"] for r in session["spec"]["roles"]}:
                    raise ValueError("外部角色id已存在")
                session["spec"]["roles"].append(role)
                session["seats"].append(seat)
                session["private_state"][role["id"]] = copy.deepcopy(role["private_state"])
                # Quorum remains frozen unless the host records an explicit amendment.
                if "required_roles" in event:
                    session["spec"]["negotiation"]["required_roles"] = event["required_roles"]
                    for p in session["proposals"].values():
                        p["accepted_by"] = []
            actual = {}
            for iid, delta in event["indicator_changes"].items():
                ind = next(i for i in session["spec"]["indicators"] if i["id"] == iid)
                before = session["indicators"][iid]
                session["indicators"][iid] = min(ind["max"], max(ind["min"], before + delta))
                actual[iid] = session["indicators"][iid] - before
            event.update(applied_round=session["round_index"], indicator_changes=actual)
            session["interventions"].append(event)
        session["intervention_queue"].pop(0)


def resume(session: dict[str, Any], *, extra_rounds: int = 0) -> None:
    if session.get("schema_version") != 2 or session["status"] != "paused":
        raise ValueError("对局未在回合边界暂停")
    if session["round_index"] >= len(session["spec"]["rounds"]) and not extra_rounds:
        raise ValueError("轮数预算已用尽，继续需明确追加轮数")
    if extra_rounds:
        if not 0 < int(extra_rounds) <= 10 or len(session["spec"]["rounds"]) + int(extra_rounds) > 20:
            raise ValueError("本局最多20轮，每次追加不超过10轮")
        session["spec"]["rounds"].extend(copy.deepcopy(session["spec"]["rounds"][-1:]) * int(extra_rounds))
        session.setdefault("budget_amendments", []).append(
            {"round": session["round_index"], "extra_rounds": int(extra_rounds)}
        )
    apply_queued(session)
    session["pause_requested"] = False
    session["status"] = "acting"
    if session["outcome"]["kind"] == "deferred":
        session["outcome"]["kind"] = "ongoing"
