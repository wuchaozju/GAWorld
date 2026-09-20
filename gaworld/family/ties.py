"""Write family membership into the agent's ``relationships`` dict.

Family is not a parallel social graph — it is the strongest part of the one
GAWorld already has. So this module emits ordinary relationship records in
the shape ``gaworld.social.network.ensure_relationship_schema`` expects, and
kin roles inherit that module's decay / obligation / Dunbar-protection
behaviour for free.

It also *reconciles*: ``bootstrap_social_roster`` asks an LLM for an
off-screen roster, and that roster happily invents a spouse for an agent the
demographics made single (and a different spouse for an agent already
married in-sim). :func:`reconcile_ghost_kin` drops those, because two
contradictory spouses in one relationship dict is worse than none.
"""

from __future__ import annotations

from typing import Any

from gaworld.family.schema import Member
from gaworld.social.network import ensure_relationship_schema

#: Opening tie strengths by family role. Kin start close; an ex starts
#: distant but frictional. Mirrors ``gaworld/population/network.py`` so a
#: synthetic population and the 51-agent roster produce comparable graphs.
TIE_PRESETS: dict[str, dict[str, float]] = {
    "spouse": {"closeness": 0.85, "trust": 0.85, "obligation": 0.85, "friction": 0.25},
    "partner": {"closeness": 0.80, "trust": 0.78, "obligation": 0.72, "friction": 0.26},
    "child": {"closeness": 0.88, "trust": 0.85, "obligation": 0.90, "friction": 0.20},
    "father": {"closeness": 0.78, "trust": 0.80, "obligation": 0.80, "friction": 0.25},
    "mother": {"closeness": 0.85, "trust": 0.82, "obligation": 0.80, "friction": 0.25},
    "parent": {"closeness": 0.82, "trust": 0.80, "obligation": 0.78, "friction": 0.25},
    "sibling": {"closeness": 0.68, "trust": 0.72, "obligation": 0.62, "friction": 0.30},
    "ex": {"closeness": 0.30, "trust": 0.35, "obligation": 0.30, "friction": 0.55},
    "roommate": {"closeness": 0.45, "trust": 0.50, "obligation": 0.30, "friction": 0.30},
}

#: Roles this module owns. A ghost carrying one of these that we did not
#: create is a contradiction and gets pruned.
OWNED_ROLES = ("spouse", "partner", "child", "ex", "roommate")


def _preset(role: str) -> dict[str, float]:
    return dict(TIE_PRESETS.get(role, TIE_PRESETS["sibling"]))


def apply_family_ties(
    agent: dict[str, Any],
    members: list[Member] | list[dict[str, Any]],
    *,
    current_day: int = 0,
) -> int:
    """Write one relationship record per family member. Returns the count.

    Existing records are updated, not replaced: an in-sim spouse who is also
    a social neighbour keeps whatever closeness the simulation has already
    earned, and only gains the role, the kin channels and the obligation
    floor.
    """
    if not isinstance(agent, dict):
        return 0
    rels = agent.setdefault("relationships", {})
    if not isinstance(rels, dict):
        rels = {}
        agent["relationships"] = rels

    written = 0
    for raw in members or []:
        member = raw if isinstance(raw, Member) else Member.from_dict(raw)
        if not member.key:
            continue
        preset = _preset(member.role)
        record = rels.get(member.key)
        if not isinstance(record, dict):
            record = dict(preset)
            rels[member.key] = record
        else:
            # Kin obligation is a floor, not an override — a neglected
            # relationship should still feel like family.
            record["obligation"] = max(
                float(record.get("obligation", 0.5) or 0.5), preset["obligation"]
            )
            record["closeness"] = max(
                float(record.get("closeness", 0.5) or 0.5), preset["closeness"] * 0.8
            )
        # The off-screen roster may already have named this person (the
        # bootstrap uses the same `g_father` / `g_mother` keys). Prefer the
        # existing name and mirror it back into the family record, so the
        # relationship and the prompt narrative describe one person — unless
        # it is the roster's *fallback* placeholder ("张三的父亲"), which is a
        # label rather than a name and reads badly in a household brief.
        existing_profile = record.get("profile")
        if isinstance(existing_profile, dict):
            existing_name = str(existing_profile.get("name", "") or "")
            agent_name = str(agent.get("name", "") or "")
            is_placeholder = bool(agent_name) and agent_name in existing_name
            if existing_name and existing_name != member.name and not is_placeholder:
                member.name = existing_name
                if isinstance(raw, dict):
                    raw["name"] = existing_name
            elif is_placeholder:
                existing_profile["name"] = member.name
        record["role"] = member.role
        record["kind"] = "agent" if member.kind == "agent" else "ghost"
        record["family"] = True
        record["coresident"] = bool(member.coresident)
        ensure_relationship_schema(
            record,
            role=member.role,
            kind=record["kind"],
            tie_origin="family",
            profile={
                "name": member.name,
                "age": member.age,
                "gender": member.gender,
                "note": member.note,
            },
            current_day=current_day,
        )
        # ``ensure_relationship_schema`` only fills missing keys; the role
        # config for a kin tie must win over whatever a generic record had.
        from gaworld.social.network import role_config

        cfg = role_config(member.role)
        record["channels"] = list(cfg["channels"])
        record["decay_rate"] = float(cfg["decay_rate"])
        record["obligation_base"] = float(cfg["obligation_base"])
        written += 1
    return written


def reconcile_ghost_kin(agent: dict[str, Any], members: list[dict[str, Any]]) -> list[str]:
    """Drop LLM-invented ghosts that contradict the assigned family.

    Returns the keys removed. Only ghosts are ever removed, and only in the
    roles this module owns — an invented mother or old classmate is fine and
    is left alone.
    """
    if not isinstance(agent, dict):
        return []
    rels = agent.get("relationships")
    if not isinstance(rels, dict):
        return []
    ours = {str(m.get("key")) for m in members or []}
    removed: list[str] = []
    for key, record in list(rels.items()):
        if not isinstance(record, dict):
            continue
        if str(key) in ours:
            continue
        if record.get("kind") != "ghost":
            continue
        if str(record.get("role", "")) in OWNED_ROLES:
            rels.pop(key, None)
            removed.append(str(key))
    return removed


def household_peers(agent: dict[str, Any]) -> list[int]:
    """In-sim agent ids that live with ``agent`` (spouse, roommates, ...)."""
    record = (agent.get("ext", {}) or {}).get("family", {}) if isinstance(agent, dict) else {}
    peers: list[int] = []
    for member in record.get("members", []) or []:
        if member.get("kind") == "agent" and member.get("coresident") and member.get("agent_id"):
            peers.append(int(member["agent_id"]))
    return peers
