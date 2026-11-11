"""Casting previews and preparation of host interventions (no background calls)."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from gaworld.research import game_casting
from gaworld.research import serious_game as sg


def preview(game: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.interview.roster import recruitment_population

    spec = game["spec"]
    if spec.get("schema_version", 1) != 2:
        raise ValueError("旧设计请先升级到新版，再预览资格匹配")
    seats = payload.get("seats", [])
    if not isinstance(seats, list) or any(not isinstance(s, dict) for s in seats):
        raise ValueError("座位配置须为列表")
    by_role = {s.get("role_id"): s for s in seats}
    roles = [r for r in spec["roles"] if by_role.get(r["id"], {}).get("kind", "agent") != "human"]
    selected = {
        r["id"]: int(by_role[r["id"]]["agent_id"])
        for r in roles
        if by_role.get(r["id"], {}).get("agent_id") not in (None, "")
    }
    matches = (
        game_casting.match_roles(
            roles,
            recruitment_population(str(payload.get("city", ""))),
            seed=int(payload.get("seed", 0)),
            selected=selected,
            mode=str(payload.get("casting_mode", "matched")),
            assumptions=payload.get("assumptions", {}),
        )
        if roles
        else []
    )
    freeze = {
        "spec": spec,
        "matches": matches,
        "seats": seats,
        "seed": int(payload.get("seed", 0)),
        "city": payload.get("city", ""),
        "mode": payload.get("casting_mode", "matched"),
        "assumptions": payload.get("assumptions", {}),
    }
    signature = hashlib.sha256(json.dumps(freeze, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"matches": matches, "preview_hash": signature, "game_id": game["id"]}


def prepare_intervention(session: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and freeze an external role before it is placed in the durable queue."""
    data = {
        k: copy.deepcopy(v)
        for k, v in payload.items()
        if k in {"id", "text", "visibility", "indicator_changes", "role", "seat", "required_roles"}
    }
    if "role" not in data:
        if "required_roles" in data:
            raise ValueError("签约主体变更必须随角色入场显式登记")
        return data
    if not isinstance(data["role"], dict) or not isinstance(data.get("seat"), dict):
        raise ValueError("新角色需要角色卡和座位配置")
    queued = [e["role"] for e in session["intervention_queue"] if e.get("role")]
    roles = session["spec"]["roles"] + queued + [data["role"]]
    ids = [r.get("id") for r in roles]
    if len(roles) > sg.MAX_ROLES or len(set(ids)) != len(ids) or not all(ids):
        raise ValueError("外部角色需要唯一id，且本局最多8个角色")
    normal = sg.normalize_spec({**session["spec"], "roles": roles})
    role = normal["roles"][-1]
    if "required_roles" in data:
        policy = {**normal["negotiation"], "required_roles": data["required_roles"]}
        from gaworld.research.game_negotiation import normalize_policy

        data["required_roles"] = normalize_policy(policy, normal["roles"])["required_roles"]
    seat_request = {**data["seat"], "role_id": role["id"]}
    from gaworld.interview.roster import recruitment_population

    taken = {int(s["persona"]["agent_id"]) for s in session["seats"] if s.get("persona", {}).get("agent_id")}
    taken |= {
        int(e["seat"]["persona"]["agent_id"])
        for e in session["intervention_queue"]
        if e.get("seat", {}).get("persona", {}).get("agent_id")
    }
    population = (
        []
        if seat_request.get("kind") == "human"
        else [p for p in recruitment_population(session["city"]) if int(p["id"]) not in taken]
    )
    requests = [{"role_id": r["id"], "kind": "human"} for r in normal["roles"][:-1]] + [seat_request]
    temporary = sg.new_session(
        {"id": session["game_id"], "spec": normal},
        requests,
        city=session["city"],
        population=population,
        seed=session["seed"],
        casting_mode=session["casting_mode"],
        assumptions=payload.get("assumptions", {}),
    )
    data["role"], data["seat"] = role, temporary["seats"][-1]
    return data
