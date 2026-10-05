"""Co-resident children and elders as residents in their own right.

Off by default (``family.members_as_agents``). Every household member used to
be an off-screen ghost: a nine-year-old existed as a line in a parent's
family brief, a duty ("接孩子放学") and a bill, but never went to school,
never met anyone and never felt anything. With this on, at the start of a
run the co-resident school-age children and co-resident elders become
simulated residents — their own schedule, perception, memory and position
on the map, living at the household's home node.

What they deliberately are *not*:

* **Not economic actors.** They get no bank account; the household keeps
  paying for them through the existing dependant charge
  (``family.finance``), exactly as before. Giving a nine-year-old the
  economy's low-income band would have them "earning" from homework.
* **Not travellers on their own.** The travel triggers skip them.
* **Not created mid-run.** Promotion happens once, before day 1. A child who
  turns six during the run, and a newborn, stay off-screen.

The resident carries ``family_dependant: True`` so the economy and the travel
triggers can tell. Ids are ``PROMOTED_ID_BASE + n`` in a stable order, so a
seeded run promotes the same people under the same ids every time.
"""

from __future__ import annotations

from typing import Any

#: Promoted residents get ids from here up, clear of any profile corpus.
PROMOTED_ID_BASE = 1_000_000

ELDER_ROLES = ("father", "mother", "parent", "grandparent")

#: Neutral starting state. Every key a profile-built resident has is filled,
#: because the main loop records state history keyed on the first agent's keys.
_STATE_DEFAULTS = {
    "emotion": 0.6, "stress": 0.3, "fatigue_debt": 0.2, "self_control": 0.6,
    "time_pressure": 0.25, "risk_preference": 0.4, "voice_propensity": 0.4,
    "mobility_intent": 0.3, "stance_score": 0.0, "toxicity_score": 0.0,
    "misinformation_risk": 0.0, "cross_viewpoint_exposure": 0.0,
    "intervention_reward": 0.0,
}


def school_level(age: int) -> str:
    if age <= 11:
        return "小学生"
    if age <= 14:
        return "初中生"
    return "高中生"


def plan(agents: list[dict[str, Any]], records: dict[int, dict[str, Any]],
         cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Which off-screen members to promote, with every record that lists them.

    A member shared by an in-sim couple appears in both partners' records
    under the same key; it is promoted once, and both records are its
    holders. Returns entries ``{"key", "household_id", "kind", "member",
    "holders"}`` in a stable order (household, key), capped at
    ``max_new_agents``.
    """
    min_age = int(cfg.get("min_child_age", 6))
    elders = bool(cfg.get("elders", True))
    # Parents a young adult still lives with are often working age; they would
    # need a job and an income of their own, which a dependant does not have.
    min_elder_age = int(cfg.get("min_elder_age", 60))
    cap = max(0, int(cfg.get("max_new_agents", 20)))
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for agent in sorted(agents, key=lambda a: int(a["id"])):
        record = records.get(int(agent["id"])) or {}
        hid = str(record.get("household_id", "") or f"solo-{agent['id']}")
        for member in record.get("members") or []:
            if member.get("kind") == "agent" or not member.get("coresident") or member.get("deceased"):
                continue
            role = str(member.get("role", ""))
            age = int(member.get("age", 0) or 0)
            if role == "child" and min_age <= age < 18:
                kind = "child"
            elif role in ELDER_ROLES and elders and age >= min_elder_age:
                kind = "elder"
            else:
                continue
            entry = found.setdefault((hid, str(member.get("key"))), {
                "key": str(member.get("key")), "household_id": hid, "kind": kind,
                "member": dict(member), "holders": [],
            })
            entry["holders"].append(agent)
    return [found[k] for k in sorted(found)][:cap]


def build_agent(entry: dict[str, Any], new_id: int) -> dict[str, Any]:
    """A resident dict shaped like the profile loader's, for one member."""
    member = entry["member"]
    holder = entry["holders"][0]
    age = int(member.get("age", 0) or 0)
    child = entry["kind"] == "child"
    if child:
        job = school_level(age)
        personality = f"{age}岁的孩子，好奇、好动，情绪来得快去得也快，很依赖家里人。"
        daily_life = "工作日上学、放学写作业，周末在家或跟家人出门；作息由大人安排。"
        values = "在意父母和老师怎么看自己，也在意和同学处得好不好。"
        employment = "student"
    else:
        job = "退休在家"
        personality = "年纪大了，作息规律，凡事求稳，最牵挂的是家里人。"
        daily_life = "早起锻炼、买菜做饭，帮家里照看孩子和打理家务，傍晚在小区附近走走。"
        values = "看重家庭和睦和身体健康，对新鲜事物持观望态度。"
        employment = "retired"
    holder_state = holder.get("state") or {}
    state = {key: _STATE_DEFAULTS.get(key, holder_state.get(key, 0.5)) for key in holder_state}
    for key, value in _STATE_DEFAULTS.items():
        state.setdefault(key, value)
    # The household's circumstances are shared; the child's or elder's own
    # temperament is not, so only these follow the holder.
    for key in ("econ_security", "city_identity", "policy_sensitivity", "platform_dependence"):
        if key in holder_state:
            state[key] = holder_state[key]
    return {
        "id": int(new_id),
        "name": str(member.get("name", "")) or f"家属{new_id}",
        "age": age,
        "gender": str(member.get("gender", "")),
        "living": holder.get("living", ""),
        "job": job,
        "work_style": job,
        "personality": personality,
        "behavior_tendencies": "",
        "daily_life": daily_life,
        "values": values,
        "monthly_income": None,
        "hukou": holder.get("hukou", ""),
        "residence": holder.get("residence", ""),
        "employment": employment,
        "industry": "",
        "state": state,
        "memory": [],
        "social_neighbors": [],
        "family_dependant": True,
    }


#: How a promoted member relates to the other people in the household:
#: (member's kind, the other person's role in the holder's record) -> role.
_ROLE_TO = {
    ("child", "holder"): None,  # filled from the holder's gender
    ("child", "spouse"): None,
    ("child", "partner"): None,
    ("child", "child"): "sibling",
    ("child", "father"): "grandparent",
    ("child", "mother"): "grandparent",
    ("child", "parent"): "grandparent",
    ("elder", "spouse"): "child_in_law",
    ("elder", "partner"): "child_in_law",
    ("elder", "child"): "grandchild",
}


def _parent_role(person_gender: str) -> str:
    return "mother" if str(person_gender) == "女" else "father"


def own_record(entry: dict[str, Any], new_agent: dict[str, Any],
               id_by_key: dict[tuple[str, str], int]) -> dict[str, Any]:
    """The promoted resident's own family record, seen from them."""
    holders = entry["holders"]
    hid = entry["household_id"]
    first = holders[0]
    holder_record = ((first.get("ext") or {}).get("family") or {})
    members: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(key, name, role, kind, age, gender, agent_id=None):
        if key in seen or role is None:
            return
        seen.add(key)
        members.append({"key": key, "name": name, "role": role, "kind": kind, "age": int(age or 0),
                        "gender": gender, "coresident": True, "agent_id": agent_id, "note": ""})

    # ``assign`` draws a couple's co-resident elder as the husband's parent
    # (and a single resident's as their own), so with two holders the man is
    # the elder's child and the woman the child-in-law.
    own_child = next((h for h in holders if str(h.get("gender", "")) == "男"), holders[0])
    for holder in holders:
        if entry["kind"] == "child":
            role = _parent_role(holder.get("gender", ""))
        else:
            role = "child" if holder is own_child else "child_in_law"
        add(str(holder["id"]), holder.get("name", ""), role, "agent", holder.get("age", 0),
            holder.get("gender", ""), int(holder["id"]))
    for member in holder_record.get("members") or []:
        if not member.get("coresident") or str(member.get("key")) == entry["key"]:
            continue
        their = str(member.get("role", ""))
        if their == "roommate":
            continue
        if member.get("kind") == "agent":
            key = str(member.get("key"))
            if key in seen:
                continue
        role = _ROLE_TO.get((entry["kind"], their))
        if role is None and their in ("spouse", "partner") and entry["kind"] == "child":
            role = _parent_role(member.get("gender", ""))
        promoted = id_by_key.get((hid, str(member.get("key"))))
        if promoted is not None:
            add(str(promoted), member.get("name", ""), role, "agent", member.get("age", 0),
                member.get("gender", ""), promoted)
        else:
            add(str(member.get("key")), member.get("name", ""), role,
                str(member.get("kind", "ghost")), member.get("age", 0), member.get("gender", ""),
                member.get("agent_id"))
    return {
        "household_id": hid,
        "household_type": str(holder_record.get("household_type", "")),
        "marital_status": "never" if entry["kind"] == "child" else str(
            entry["member"].get("marital_status", "") or "widowed"),
        "bond": "",
        "dependant": True,
        "members": members,
    }


__all__ = ["PROMOTED_ID_BASE", "build_agent", "own_record", "plan", "school_level"]
