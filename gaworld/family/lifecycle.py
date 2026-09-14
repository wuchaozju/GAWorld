"""Household composition changes that happen *during* a run.

``assign.py`` builds every household once, before day 1, and nothing ever
changed it again: over a decade-long run a resident could age thirty years
while their household stayed exactly as it was sampled — never marrying,
never having a child, never losing the parent who lived with them. The
household *type*, the care load and the family duties are all read off that
composition, so a frozen household freezes those too.

This module owns the transitions, as pure functions over the per-agent family
record (the dict in ``agent_ext(agent, "family")``: ``marital_status``,
``household_type``, ``members``). They are deliberately separate from the
life-event plugin that triggers them — the plugin decides *whether* something
happens, these decide what it means.

Three rules run through all of it:

* **The type is derived, never asserted.** After any change the household
  type is recomputed from who actually lives there, mirroring how ``assign``
  treats type as a read-out rather than a quota.
* **Eligibility is checked here, not guessed by a model.** A digest can
  propose "got married"; only :func:`can_marry` decides whether that is
  possible for this person, so a 70-year-old with a living spouse cannot
  marry again because the LLM felt like it.
* **New relatives are off-screen ghosts.** Marrying an in-sim resident would
  need both sides to agree and both households to merge; a ghost spouse is
  the same thing ``assign`` already creates for everyone it cannot pair.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.family.lifecycle")

#: Roles that make a household multi-generational when they live in.
ELDER_ROLES = ("father", "mother", "parent", "grandparent")
#: Roles that mean "there is a partner in this household".
PARTNER_ROLES = ("spouse", "partner")

#: Age bounds for the transitions. Deliberately wide — these gate out the
#: absurd (a 70-year-old giving birth), not the merely uncommon.
MARRIAGE_MIN_AGE = 20
MARRIAGE_MAX_AGE = 75
CHILDBIRTH_MIN_AGE = 18
CHILDBIRTH_MAX_AGE = 45
MAX_CHILDREN = 3
#: An elder becomes plausibly at risk from here; below it bereavement of a
#: co-resident parent is not something a year should invent.
BEREAVEMENT_MIN_ELDER_AGE = 65


def _members(record: dict[str, Any]) -> list[dict[str, Any]]:
    members = record.get("members") if isinstance(record, dict) else None
    return [m for m in members if isinstance(m, dict)] if isinstance(members, list) else []


def _age_of(agent: dict[str, Any]) -> int:
    try:
        return int(float(agent.get("age", 0) or 0))
    except (TypeError, ValueError):
        return 0


def derive_household_type(record: dict[str, Any]) -> str:
    """Recompute the household type from who currently lives there.

    Mirrors ``assign._couple_type``'s logic but reads the record's member
    dicts, so it can run after a composition change rather than only at
    assignment. Type is a read-out: asserting it separately is how it drifts
    away from the members.
    """
    members = _members(record)
    resident = [m for m in members if m.get("coresident")]
    partner = next(
        (m for m in resident if str(m.get("role", "")) in PARTNER_ROLES), None
    )
    has_child = any(str(m.get("role", "")) == "child" for m in resident)
    has_elder = any(str(m.get("role", "")) in ELDER_ROLES for m in resident)
    has_roommate = any(str(m.get("role", "")) == "roommate" for m in resident)

    if partner is not None:
        if has_elder:
            return "multigen"
        if has_child:
            return "nuclear"
        return "cohabit" if str(partner.get("role")) == "partner" else "couple"
    if has_child:
        return "single_parent"
    if has_elder:
        return "with_parents"
    if has_roommate:
        return "shared"
    return "single"


def refresh_household_type(record: dict[str, Any]) -> str:
    """Recompute and store the type; returns it."""
    household_type = derive_household_type(record)
    if isinstance(record, dict):
        record["household_type"] = household_type
    return household_type


def family_facts(record: dict[str, Any]) -> dict[str, Any]:
    """A small machine-readable summary of the household.

    ``agent["family"]`` is authored prose — good for a prompt, useless for a
    predicate. Eligibility checks and the digest's action menu both need to
    ask plain questions ("is there a partner?", "how old is the youngest
    child?"), so the facts are published separately.
    """
    members = _members(record)
    resident = [m for m in members if m.get("coresident")]
    children = [m for m in members if str(m.get("role", "")) == "child"]
    elders = [
        m for m in resident if str(m.get("role", "")) in ELDER_ROLES
    ]

    def _age(member: dict[str, Any]) -> int:
        try:
            return int(float(member.get("age", 0) or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "marital_status": str(record.get("marital_status", "") or ""),
        "household_type": str(record.get("household_type", "") or ""),
        "has_partner": any(str(m.get("role", "")) in PARTNER_ROLES for m in members),
        "child_count": len(children),
        "coresident_child_count": sum(1 for m in children if m.get("coresident")),
        "youngest_child_age": min((_age(m) for m in children), default=None),
        "coresident_elder_count": len(elders),
        "oldest_elder_age": max((_age(m) for m in elders), default=None),
    }


# ---------------------------------------------------------------------------
# Eligibility — what is even possible for this person right now
# ---------------------------------------------------------------------------

def can_marry(agent: dict[str, Any], record: dict[str, Any]) -> bool:
    facts = family_facts(record)
    if facts["has_partner"] or facts["marital_status"] == "married":
        return False
    return MARRIAGE_MIN_AGE <= _age_of(agent) <= MARRIAGE_MAX_AGE


def can_bear_child(agent: dict[str, Any], record: dict[str, Any]) -> bool:
    facts = family_facts(record)
    # A child needs a partner in the household; lone parenthood exists but is
    # not something a digest should be able to conjure without one.
    if not facts["has_partner"]:
        return False
    if facts["child_count"] >= MAX_CHILDREN:
        return False
    return CHILDBIRTH_MIN_AGE <= _age_of(agent) <= CHILDBIRTH_MAX_AGE


def can_be_bereaved(agent: dict[str, Any], record: dict[str, Any]) -> bool:
    """True when there is somebody old enough to plausibly lose."""
    return bereavable_member(record) is not None


def bereavable_member(record: dict[str, Any]) -> dict[str, Any] | None:
    """The household member a bereavement would be about — the oldest elder.

    Restricted to co-resident elders past :data:`BEREAVEMENT_MIN_ELDER_AGE`
    (and to an elderly partner), so a run cannot kill a 40-year-old spouse
    because a model wanted a dramatic year.
    """
    candidates = []
    for member in _members(record):
        if not member.get("coresident"):
            continue
        role = str(member.get("role", ""))
        try:
            age = int(float(member.get("age", 0) or 0))
        except (TypeError, ValueError):
            continue
        if role in ELDER_ROLES and age >= BEREAVEMENT_MIN_ELDER_AGE:
            candidates.append((age, member))
        elif role in PARTNER_ROLES and age >= BEREAVEMENT_MIN_ELDER_AGE + 10:
            candidates.append((age, member))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

_GIVEN_M = ("伟", "强", "磊", "洋", "杰", "涛", "明", "超", "鹏", "宇")
_GIVEN_F = ("芳", "娜", "敏", "静", "丽", "燕", "娟", "婷", "雪", "颖")


def _ghost_name(rng: random.Random, gender: str, surname: str = "") -> str:
    pool = _GIVEN_F if gender == "女" else _GIVEN_M
    base = surname or rng.choice("陈林黄张李王刘杨赵周")
    return f"{base}{rng.choice(pool)}"


def _opposite_gender(gender: str) -> str:
    return "男" if str(gender).strip() == "女" else "女"


def marry(
    record: dict[str, Any],
    agent: dict[str, Any],
    *,
    day: int = 0,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Add a spouse and move the household to a couple/multigen type.

    The spouse is an off-screen ghost: marrying an in-sim resident would have
    to be agreed by both agents and merge two households, which is a
    different (and much larger) feature than "this person got married".
    """
    if not can_marry(agent, record):
        return None
    _rng = rng or random
    gender = _opposite_gender(agent.get("gender", ""))
    age = max(MARRIAGE_MIN_AGE, _age_of(agent) + _rng.randint(-4, 4))
    spouse = {
        "key": f"g_spouse_{day}",
        "name": _ghost_name(_rng, gender),
        "role": "spouse",
        "kind": "ghost",
        "age": age,
        "gender": gender,
        "coresident": True,
        "agent_id": None,
        "note": "婚后共同生活",
    }
    record.setdefault("members", []).append(spouse)
    record["marital_status"] = "married"
    record["bond"] = "spouse"
    return {
        "type": "marriage",
        "member": spouse,
        "household_type": refresh_household_type(record),
    }


def bear_child(
    record: dict[str, Any],
    agent: dict[str, Any],
    *,
    day: int = 0,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Add a newborn to the household."""
    if not can_bear_child(agent, record):
        return None
    _rng = rng or random
    gender = _rng.choice(("男", "女"))
    surname = str(agent.get("name", ""))[:1]
    child = {
        "key": f"g_child_{day}",
        "name": _ghost_name(_rng, gender, surname),
        "role": "child",
        "kind": "ghost",
        "age": 0,
        "gender": gender,
        "coresident": True,
        "agent_id": None,
        "note": "新生儿",
    }
    record.setdefault("members", []).append(child)
    return {
        "type": "childbirth",
        "member": child,
        "household_type": refresh_household_type(record),
    }


def bereave(
    record: dict[str, Any],
    agent: dict[str, Any],
    *,
    day: int = 0,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Lose a co-resident elder (or an elderly partner).

    The member is kept on the record but marked ``deceased`` and moved out of
    co-residence rather than deleted, so narrative and memory can still refer
    to them — a parent who died is not a parent who never existed.
    """
    member = bereavable_member(record)
    if member is None:
        return None
    member["coresident"] = False
    member["deceased"] = True
    member["deceased_day"] = int(day)
    if str(member.get("role", "")) in PARTNER_ROLES:
        record["marital_status"] = "widowed"
        record["bond"] = ""
    return {
        "type": "bereavement",
        "member": member,
        "household_type": refresh_household_type(record),
    }


#: Template key -> (eligibility predicate, transition).
TRANSITIONS = {
    "marriage": (can_marry, marry),
    "childbirth": (can_bear_child, bear_child),
    "bereavement": (can_be_bereaved, bereave),
}


def apply_transition(
    key: str,
    record: dict[str, Any],
    agent: dict[str, Any],
    *,
    day: int = 0,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """Run the family transition named by a life-event template key."""
    entry = TRANSITIONS.get(str(key))
    if entry is None:
        return None
    _eligible, transition = entry
    try:
        return transition(record, agent, day=day, rng=rng)
    except Exception as exc:  # noqa: BLE001 - a bad record must not kill the run
        _LOG.warning("family transition %s failed for %s: %s", key, agent.get("id"), exc)
        return None


__all__ = [
    "TRANSITIONS",
    "apply_transition",
    "bear_child",
    "bereavable_member",
    "bereave",
    "can_be_bereaved",
    "can_bear_child",
    "can_marry",
    "derive_household_type",
    "family_facts",
    "marry",
    "refresh_household_type",
]
