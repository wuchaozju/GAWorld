"""Operator-pinned families that survive re-assignment.

Households are re-derived from (roster, config, seed) at the start of every
run. That is what makes them reproducible — and it is also why an edit made
in Agent Studio would be silently erased the next time the simulation
started, if the edit only touched ``relationships.json``.

So an edit is not a mutation of the result; it is an **input** that the
assigner consults. :func:`apply_to_status` and :func:`apply_to_household`
are called from ``assign.assign_households`` at the two points where an
operator's explicit choice has to win over the demographic draw:

1. before the marital-status sample is used, and
2. before children / co-resident elders are sampled.

Overrides live in ``data/family_overrides.json`` — next to the profiles and
the state CSV, because a deliberately specified family is *source data* in
the same sense a profile is, not run output.

Nothing here forces a household *type*: the type stays a read-out of what
the assignment produced (see the module docstring of ``assign.py``). Pin a
spouse and two children and you get 核心家庭 because that is what those
people are, not because anyone selected it from a dropdown.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from gaworld.family.schema import MARITAL_STATUSES, Member, family_config
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.family.overrides")

DEFAULT_PATH = os.path.join("data", "family_overrides.json")

#: Roles an operator may pin as a co-resident elder.
ELDER_ROLES = ("mother", "father", "parent", "grandparent")


def overrides_path(config: dict[str, Any] | None = None) -> str:
    return str(family_config(config).get("overrides_path", DEFAULT_PATH))


def load_overrides(config: dict[str, Any] | None = None) -> dict[int, dict[str, Any]]:
    """Read the override file. A missing or corrupt file is an empty dict.

    Corrupt is deliberately not fatal: an unreadable override file must not
    stop a simulation from starting, it must only stop the pinning.
    """
    path = overrides_path(config)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("family overrides unreadable (%s): %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for key, value in raw.items():
        try:
            agent_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            out[agent_id] = value
    return out


def save_overrides(data: dict[int, dict[str, Any]], config: dict[str, Any] | None = None) -> str:
    """Write the whole override map atomically. Returns the path."""
    path = overrides_path(config)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {str(int(k)): v for k, v in sorted(data.items()) if v}
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class OverrideError(ValueError):
    """Rejected override, with a message meant for the operator."""


def _clean_person(raw: Any, *, default_role: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise OverrideError("每个家庭成员必须是一个对象")
    name = str(raw.get("name", "") or "").strip()
    if not name:
        raise OverrideError(f"第 {index + 1} 位家庭成员缺少姓名")
    try:
        age = int(raw.get("age", 0) or 0)
    except (TypeError, ValueError):
        raise OverrideError(f"{name} 的年龄必须是整数") from None
    if not 0 <= age <= 120:
        raise OverrideError(f"{name} 的年龄超出 0-120 范围")
    gender = str(raw.get("gender", "") or "").strip() or "男"
    if gender not in ("男", "女"):
        raise OverrideError(f"{name} 的性别只能是「男」或「女」")
    role = str(raw.get("role", "") or default_role).strip() or default_role
    return {
        "name": name,
        "age": age,
        "gender": gender,
        "role": role,
        "coresident": bool(raw.get("coresident", True)),
        "note": str(raw.get("note", "") or "").strip(),
    }


def normalize_override(raw: dict[str, Any], *, agent_id: int) -> dict[str, Any]:
    """Validate one agent's override, raising :class:`OverrideError`.

    Returns the cleaned record. An empty record (nothing actually pinned)
    comes back as ``{}`` so callers can drop it rather than persist a
    no-op that looks like an edit.
    """
    if not isinstance(raw, dict):
        raise OverrideError("覆盖内容必须是一个对象")

    out: dict[str, Any] = {}

    status = raw.get("marital_status")
    if status not in (None, ""):
        if status not in MARITAL_STATUSES:
            raise OverrideError(f"婚姻状态只能是 {'/'.join(MARITAL_STATUSES)} 之一")
        out["marital_status"] = status

    partner = raw.get("partner")
    if isinstance(partner, dict) and partner.get("kind"):
        kind = str(partner.get("kind"))
        role = str(partner.get("role", "spouse") or "spouse")
        if role not in ("spouse", "partner"):
            raise OverrideError("伴侣关系只能是配偶或同居伴侣")
        if kind == "agent":
            try:
                partner_id = int(partner.get("agent_id"))
            except (TypeError, ValueError):
                raise OverrideError("仿真内配偶必须选择一位居民") from None
            if partner_id == agent_id:
                raise OverrideError("不能把自己指定为配偶")
            out["partner"] = {"kind": "agent", "agent_id": partner_id, "role": role}
        elif kind == "ghost":
            person = _clean_person(partner, default_role=role, index=0)
            person["role"] = role
            person["coresident"] = bool(partner.get("coresident", True))
            out["partner"] = {"kind": "ghost", **person}
        else:
            raise OverrideError("配偶类型只能是仿真内居民或场外人物")
    elif partner is None and "partner" in raw:
        # Explicit null = "pin this person as having no partner".
        out["partner"] = None

    for key, default_role in (("children", "child"), ("elders", "mother")):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise OverrideError(f"{key} 必须是一个列表")
        cleaned = [
            _clean_person(item, default_role=default_role, index=index)
            for index, item in enumerate(value)
        ]
        if key == "elders":
            for person in cleaned:
                if person["role"] not in ELDER_ROLES:
                    person["role"] = "mother" if person["gender"] == "女" else "father"
        else:
            for person in cleaned:
                person["role"] = "child"
        out[key] = cleaned

    note = str(raw.get("note", "") or "").strip()
    if note:
        out["note"] = note

    # A record that pins nothing is not an edit.
    if not any(k in out for k in ("marital_status", "partner", "children", "elders")):
        return {}
    return out


def cross_check(overrides: dict[int, dict[str, Any]]) -> list[str]:
    """Report mutual-partner conflicts. Returns human-readable warnings.

    A pinned in-sim spouse is a claim on *another* agent, so two operators
    (or one operator on two days) can pin contradicting pairs. The assigner
    resolves this deterministically by lowest agent id; this function exists
    so the panel can say so out loud instead of letting it be a surprise.
    """
    warnings: list[str] = []
    claims: dict[int, int] = {}
    for agent_id in sorted(overrides):
        partner = (overrides[agent_id] or {}).get("partner")
        if isinstance(partner, dict) and partner.get("kind") == "agent":
            claims[agent_id] = int(partner["agent_id"])
    for agent_id, target in sorted(claims.items()):
        counter = claims.get(target)
        if counter is not None and counter != agent_id:
            warnings.append(
                f"居民 {agent_id} 指定配偶为 {target}，但 {target} 指定的是 {counter}；"
                f"按 id 从小到大解析，后来的那条会被忽略。"
            )
    return warnings


# ---------------------------------------------------------------------------
# Hooks called by the assigner
# ---------------------------------------------------------------------------


def apply_to_status(
    agent_id: int,
    sampled: str,
    overrides: dict[int, dict[str, Any]],
) -> str:
    record = overrides.get(int(agent_id)) or {}
    status = record.get("marital_status")
    return status if status in MARITAL_STATUSES else sampled


def forced_bond(agent_id: int, overrides: dict[int, dict[str, Any]]) -> str | None:
    """``"spouse"`` / ``"partner"`` when a partner is pinned, else ``None``.

    Returns ``""`` when the operator pinned *no* partner, which the caller
    must distinguish from "nothing pinned" — hence the tri-state.
    """
    record = overrides.get(int(agent_id))
    if not record or "partner" not in record:
        return None
    partner = record["partner"]
    if partner is None:
        return ""
    return str(partner.get("role", "spouse") or "spouse")


def forced_pairs(overrides: dict[int, dict[str, Any]]) -> dict[int, int]:
    """Resolved mutual in-sim pairs, lowest agent id winning a conflict."""
    matched: dict[int, int] = {}
    for agent_id in sorted(overrides):
        partner = (overrides[agent_id] or {}).get("partner")
        if not isinstance(partner, dict) or partner.get("kind") != "agent":
            continue
        target = int(partner["agent_id"])
        if agent_id in matched or target in matched:
            continue
        matched[agent_id] = target
        matched[target] = agent_id
    return matched


def pinned_members(
    agent_id: int,
    overrides: dict[int, dict[str, Any]],
) -> tuple[list[Member] | None, list[Member] | None]:
    """``(children, elders)`` as :class:`Member` objects, or ``None`` each.

    ``None`` means "not pinned — sample it"; an empty list means "pinned to
    none", which is how an operator says *this couple has no children*.
    """
    record = overrides.get(int(agent_id)) or {}

    def _build(key: str, prefix: str) -> list[Member] | None:
        raw = record.get(key)
        if raw is None:
            return None
        members: list[Member] = []
        for index, person in enumerate(raw):
            members.append(
                Member(
                    key=f"g_{prefix}_{index + 1}",
                    name=str(person.get("name", "")),
                    role=str(person.get("role", prefix)),
                    kind="ghost",
                    age=int(person.get("age", 0) or 0),
                    gender=str(person.get("gender", "")),
                    coresident=bool(person.get("coresident", True)),
                    note=str(person.get("note", "") or ""),
                )
            )
        return members

    return _build("children", "child"), _build("elders", "pinned_parent")


def pinned_ghost_partner(agent_id: int, overrides: dict[int, dict[str, Any]]) -> Member | None:
    record = overrides.get(int(agent_id)) or {}
    partner = record.get("partner")
    if not isinstance(partner, dict) or partner.get("kind") != "ghost":
        return None
    return Member(
        key="g_spouse",
        name=str(partner.get("name", "")),
        role=str(partner.get("role", "spouse") or "spouse"),
        kind="ghost",
        age=int(partner.get("age", 0) or 0),
        gender=str(partner.get("gender", "")),
        coresident=bool(partner.get("coresident", True)),
        note=str(partner.get("note", "") or ""),
    )
