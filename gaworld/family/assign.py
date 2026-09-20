"""Assign every agent a marital status, a family and a household.

The assignment is a pure function of (agent roster, config, seed): call it
twice and you get the same families. Each random draw comes from a per-agent
named sub-stream, so adding an agent or tweaking the fertility knobs cannot
silently re-roll everybody else's marriage — the same reasoning as
``gaworld.population.synth.derive_rng``, using stdlib ``random`` because the
draws here are scalar and per-agent rather than vectorised.

Order matters, and it is deliberately *status first, structure second*:

1. marital status per agent (age x gender categorical) — the demographics;
2. in-sim pairing of the married/cohabiting, then off-screen spouses for
   whoever is left over — the "混合" model;
3. children, then co-resident parents/elders — these depend on the couple;
4. household type derived from what was built, never chosen up front.

Choosing household types up front and then filling them is the failure mode
``gaworld/population/network.py`` documents at length: the type shares and the
age pyramid disagree and one of them silently loses. Here the types are a
*read-out* of the assignment, so they cannot disagree with anything.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from gaworld.family.overrides import (
    apply_to_status,
    forced_bond,
    forced_pairs,
    load_overrides,
    pinned_ghost_partner,
    pinned_members,
)
from gaworld.family.schema import (
    Household,
    Member,
    band_lookup,
    family_config,
)
from gaworld.population.synth import GIVEN_CHARS_F, GIVEN_CHARS_M, GIVEN_CHARS_NEUTRAL, SURNAMES


def _rng(seed: Any, agent_id: Any, stream: str) -> random.Random:
    return random.Random(f"{seed}::{agent_id}::{stream}")


def _pick(rng: random.Random, shares: dict[str, float]) -> str:
    """Draw a key from ``{key: weight}``; weights need not sum to 1."""
    items = [(k, max(0.0, float(v))) for k, v in (shares or {}).items()]
    total = sum(w for _, w in items)
    if total <= 0:
        return items[0][0] if items else "never"
    roll = rng.random() * total
    acc = 0.0
    for key, weight in items:
        acc += weight
        if roll <= acc:
            return key
    return items[-1][0]


def _surname(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return "陈"
    # Two-character compound surnames are rare enough in the roster that the
    # first character is the right default.
    return name[0]


def _given_name(rng: random.Random, gender: str) -> str:
    pool = (GIVEN_CHARS_M if gender == "男" else GIVEN_CHARS_F) + GIVEN_CHARS_NEUTRAL
    length = 1 if rng.random() < 0.35 else 2
    return "".join(rng.choice(pool) for _ in range(length))


def _ghost_name(rng: random.Random, gender: str, surname: str | None = None) -> str:
    sur = surname or rng.choice(SURNAMES)
    return f"{sur}{_given_name(rng, gender)}"


def _district(agent: dict[str, Any]) -> str:
    text = str(agent.get("residence", "") or "").strip()
    if not text:
        return ""
    for sep in ("·", "・", " ", "，", ","):
        if sep in text:
            return text.split(sep)[0]
    return text[:3]


def _opposite(gender: str) -> str:
    return "女" if gender == "男" else "男"


@dataclass
class FamilyAssignment:
    """Result of :func:`assign_households`."""

    households: list[Household] = field(default_factory=list)
    #: agent id -> per-agent family record (the thing stored on the agent)
    by_agent: dict[int, dict[str, Any]] = field(default_factory=dict)

    def household_for(self, agent_id: int) -> Household | None:
        hid = (self.by_agent.get(int(agent_id)) or {}).get("household_id")
        for hh in self.households:
            if hh.id == hid:
                return hh
        return None

    def summary(self) -> dict[str, Any]:
        types: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for record in self.by_agent.values():
            types[record["household_type"]] = types.get(record["household_type"], 0) + 1
            statuses[record["marital_status"]] = statuses.get(record["marital_status"], 0) + 1
        in_sim_pairs = sum(
            1
            for record in self.by_agent.values()
            for m in record["members"]
            if m["role"] in ("spouse", "partner") and m["kind"] == "agent"
        ) // 2
        return {
            "agents": len(self.by_agent),
            "households": len(self.households),
            "household_types": types,
            "marital_statuses": statuses,
            "in_sim_couples": in_sim_pairs,
            "with_children": sum(
                1
                for record in self.by_agent.values()
                if any(m["role"] == "child" for m in record["members"])
            ),
        }


# ---------------------------------------------------------------------------
# Step 1 — marital status
# ---------------------------------------------------------------------------


def sample_marital_status(agent: dict[str, Any], cfg: dict[str, Any]) -> str:
    age = int(agent.get("age", 30) or 30)
    gender = str(agent.get("gender", "男") or "男")
    band = band_lookup(cfg.get("marital_status_bands", []), age)
    if not band:
        return "never"
    shares = band.get("female" if gender == "女" else "male") or {}
    return _pick(_rng(cfg.get("seed"), agent.get("id"), "marital"), shares)


def _is_cohabiting(agent: dict[str, Any], status: str, cfg: dict[str, Any]) -> bool:
    if status != "never":
        return False
    co = cfg.get("cohabitation", {})
    age = int(agent.get("age", 30) or 30)
    if not (int(co.get("age_min", 24)) <= age <= int(co.get("age_max", 38))):
        return False
    return _rng(cfg.get("seed"), agent.get("id"), "cohabit").random() < float(co.get("share", 0.1))


# ---------------------------------------------------------------------------
# Step 2 — pairing
# ---------------------------------------------------------------------------


def _pair_in_sim(
    agents: list[dict[str, Any]],
    bond_of: dict[int, str],
    cfg: dict[str, Any],
) -> dict[int, int]:
    """Greedy deterministic matching of agents who share a bond kind.

    Returns ``{agent_id: partner_agent_id}`` for matched pairs only.

    Two agents drawn from a 12-million-person city are, in reality, almost
    never married to each other; pairing them is a *modelling* choice that
    buys in-sim family interaction. ``in_sim_pair_share`` is therefore a
    knob, not a constant, and the honest default is well under 1.0.
    """
    pairing = cfg.get("pairing", {})
    if not pairing.get("prefer_in_sim", True):
        return {}
    max_gap = int(pairing.get("max_age_gap", 8))
    pref_gap = float(pairing.get("spouse_age_gap_mean", 2.0))
    district_bonus = float(pairing.get("same_district_bonus", 2.0))
    share = float(pairing.get("in_sim_pair_share", 0.6))

    matched: dict[int, int] = {}
    by_id = {int(a["id"]): a for a in agents}
    candidates = sorted(bond_of.keys())
    males = [aid for aid in candidates if str(by_id[aid].get("gender", "")) == "男"]
    females = [aid for aid in candidates if str(by_id[aid].get("gender", "")) != "男"]
    budget = round(min(len(males), len(females)) * max(0.0, min(1.0, share)))
    taken: set[int] = set()

    for male_id in males:
        if len(matched) // 2 >= budget:
            break
        male = by_id[male_id]
        best: tuple[float, int] | None = None
        for female_id in females:
            if female_id in taken:
                continue
            if bond_of[female_id] != bond_of[male_id]:
                continue
            female = by_id[female_id]
            gap = int(male.get("age", 0)) - int(female.get("age", 0))
            if abs(gap) > max_gap:
                continue
            score = -abs(gap - pref_gap)
            if _district(male) and _district(male) == _district(female):
                score += district_bonus
            if best is None or score > best[0]:
                best = (score, female_id)
        if best is not None:
            female_id = best[1]
            taken.add(female_id)
            matched[male_id] = female_id
            matched[female_id] = male_id
    return matched


# ---------------------------------------------------------------------------
# Step 3 — children
# ---------------------------------------------------------------------------


def _child_count(parent_age: int, rng: random.Random, cfg: dict[str, Any]) -> int:
    fert = cfg.get("fertility", {})
    band = band_lookup(fert.get("p_any_child", []), parent_age, {"p": 0.5})
    if rng.random() >= float(band.get("p", 0.5)):
        return 0
    count = 1
    if rng.random() < float(fert.get("p_second_child", 0.32)):
        count += 1
        if rng.random() < float(fert.get("p_third_child", 0.04)):
            count += 1
    return count


def _make_children(
    anchor: dict[str, Any],
    partner_age: int | None,
    surname: str,
    rng: random.Random,
    cfg: dict[str, Any],
) -> list[Member]:
    """Children of the household anchored on ``anchor``.

    Ages are derived from the parent's age at first birth, then clamped so a
    child is never older than the parent's fertile window allows. Children
    above ``coresident_child_max_age`` stay kin but move out.
    """
    fert = cfg.get("fertility", {})
    parent_age = int(anchor.get("age", 30) or 30)
    reference_age = max(parent_age, int(partner_age or 0))
    count = _child_count(reference_age, rng, cfg)
    if count <= 0:
        return []
    lo, hi = fert.get("parent_age_at_first_birth", [27, 34])
    first_birth_age = rng.randint(int(lo), int(hi))
    max_child_age = reference_age - first_birth_age
    if max_child_age < 0:
        return []
    coresident_max = int(fert.get("coresident_child_max_age", 22))
    children: list[Member] = []
    child_age = max_child_age
    for index in range(count):
        if child_age < 0:
            break
        gender = "男" if rng.random() < 0.52 else "女"
        children.append(
            Member(
                key=f"g_child_{index + 1}",
                name=_ghost_name(rng, gender, surname),
                role="child",
                kind="ghost",
                age=int(child_age),
                gender=gender,
                coresident=child_age <= coresident_max,
            )
        )
        # Siblings are spaced 2-5 years apart, youngest last.
        child_age -= rng.randint(2, 5)
    return children


# ---------------------------------------------------------------------------
# Step 4 — parents and elders
# ---------------------------------------------------------------------------


def _parent_members(
    agent: dict[str, Any],
    rng: random.Random,
    coresident: bool,
    cfg: dict[str, Any],
    prefix: str = "g",
) -> list[Member]:
    age = int(agent.get("age", 30) or 30)
    surname = _surname(agent.get("name", ""))
    father_age = age + rng.randint(24, 32)
    mother_age = father_age - rng.randint(0, 4)
    return [
        Member(
            key=f"{prefix}_father",
            name=_ghost_name(rng, "男", surname),
            role="father",
            kind="ghost",
            age=father_age,
            gender="男",
            coresident=coresident,
        ),
        Member(
            key=f"{prefix}_mother",
            name=_ghost_name(rng, "女"),
            role="mother",
            kind="ghost",
            age=mother_age,
            gender="女",
            coresident=coresident,
        ),
    ]


def _attach_remote_parents(
    agent: dict[str, Any],
    record: dict[str, Any],
    cfg: dict[str, Any],
) -> None:
    """Add still-living parents who live elsewhere, if none are recorded yet.

    Survival is drawn per parent from their implied age, so a 65-year-old
    agent is much more likely to have buried a parent than a 28-year-old.
    The keys match the ones the off-screen roster bootstrap already uses
    (``g_father`` / ``g_mother``), so the two describe one person rather
    than two.
    """
    members = record.setdefault("members", [])
    existing = {str(m.get("key")) for m in members}
    if {"g_father", "g_mother"} & existing or "g_coresident_parent" in existing:
        return
    # A pinned co-resident elder is this agent's parent; adding a second,
    # differently-named pair living elsewhere would give them four.
    if any(
        m.get("role") in ("father", "mother", "parent") and m.get("coresident")
        for m in members
    ):
        return
    age = int(agent.get("age", 30) or 30)
    rng = _rng(cfg.get("seed"), agent.get("id"), "remote_parents")
    surname = _surname(agent.get("name", ""))
    father_age = age + rng.randint(24, 32)
    mother_age = father_age - rng.randint(0, 4)
    for key, role, gender, parent_age, sur in (
        ("g_father", "father", "男", father_age, surname),
        ("g_mother", "mother", "女", mother_age, None),
    ):
        # Rough survival curve: near-certain under 70, falling away after.
        alive_p = 1.0 if parent_age < 70 else max(0.05, 1.0 - (parent_age - 70) * 0.055)
        if rng.random() >= alive_p:
            continue
        members.append(
            Member(
                key=key,
                name=_ghost_name(rng, gender, sur),
                role=role,
                kind="ghost",
                age=int(parent_age),
                gender=gender,
                coresident=False,
                note="不同住的父母",
            ).to_dict()
        )


def _with_parents(agent: dict[str, Any], cfg: dict[str, Any]) -> bool:
    co = cfg.get("coresidence", {})
    hukou = str(agent.get("hukou", "") or "")
    local = hukou in ("本地", "省内", "杭州", "城镇", "本市")
    share = float(co.get("with_parents_local" if local else "with_parents_migrant", 0.1))
    return _rng(cfg.get("seed"), agent.get("id"), "with_parents").random() < share


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def assign_households(
    agents: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    overrides: dict[int, dict[str, Any]] | None = None,
) -> FamilyAssignment:
    """Build households for ``agents`` (a list of agent dicts).

    ``overrides`` pins individual agents' families (Agent Studio writes them
    to ``data/family_overrides.json``). They are consulted *during* the
    assignment rather than patched onto the result, so everything downstream
    — household type, home sharing, duties, billing — follows from the pinned
    family the same way it follows from a sampled one. Pass ``{}`` to ignore
    the file entirely; pass ``None`` to load it.
    """
    cfg = family_config(config)
    seed = cfg.get("seed")
    if overrides is None:
        overrides = load_overrides(config)
    roster = [a for a in agents if isinstance(a, dict) and a.get("id") is not None]
    by_id = {int(a["id"]): a for a in roster}
    # A pinned partner who is not in this run's roster cannot be honoured;
    # dropping the claim here keeps every later step from special-casing it.
    known = set(by_id)
    overrides = {
        aid: record
        for aid, record in (overrides or {}).items()
        if int(aid) in known
    }

    # -- statuses ----------------------------------------------------------
    status: dict[int, str] = {}
    bond: dict[int, str] = {}
    for agent in roster:
        aid = int(agent["id"])
        st = apply_to_status(aid, sample_marital_status(agent, cfg), overrides)
        status[aid] = st
        pinned_bond = forced_bond(aid, overrides)
        if pinned_bond is not None:
            # "" means the operator pinned *no* partner — distinct from
            # "nothing pinned", so it must suppress the sampled one.
            if pinned_bond:
                bond[aid] = pinned_bond
        elif st == "married":
            bond[aid] = "spouse"
        elif _is_cohabiting(agent, st, cfg):
            bond[aid] = "partner"

    # Pinned in-sim couples are placed first and removed from the greedy
    # pool: an operator's explicit pair must not lose to the age-gap score,
    # and whoever the greedy would have matched them with falls back to an
    # off-screen spouse on its own.
    pinned = {
        aid: target
        for aid, target in forced_pairs(overrides).items()
        if aid in known and target in known
    }
    for aid, target in pinned.items():
        bond.setdefault(aid, bond.get(target, "spouse"))
        bond[target] = bond[aid]
    # An agent whose partner is pinned *off-screen* must also leave the greedy
    # pool, or the matcher happily marries them to someone in-sim and the pin
    # is silently ignored.
    ghost_pinned = {
        aid
        for aid, record in overrides.items()
        if isinstance((record or {}).get("partner"), dict)
        and (record or {})["partner"].get("kind") == "ghost"
    }
    remaining = {
        aid: kind
        for aid, kind in bond.items()
        if aid not in pinned and aid not in ghost_pinned
    }
    matched = dict(pinned)
    matched.update(_pair_in_sim(roster, remaining, cfg))

    # -- households --------------------------------------------------------
    households: list[Household] = []
    by_agent: dict[int, dict[str, Any]] = {}
    handled: set[int] = set()
    counter = 0

    def _new_household(agent_ids: list[int], hh_type: str, ghosts: list[Member]) -> Household:
        nonlocal counter
        counter += 1
        anchor = by_id[agent_ids[0]]
        hh = Household(
            id=f"hh_{counter:03d}",
            type=hh_type,
            agent_ids=list(agent_ids),
            ghost_members=list(ghosts),
            district=_district(anchor),
            home=str((anchor.get("locations") or {}).get("home", "") or ""),
        )
        households.append(hh)
        return hh

    # 1) couples first (they own the children and the multigen elder).
    # ``matched`` holds both directions; each pair is visited once, keyed by
    # its lower agent id. The *anchor* (whose surname the children take, and
    # whose age drives fertility) is the husband when there is one — a pinned
    # pair need not have one, and keying the visit on gender would drop such
    # a pair on the floor entirely.
    for first_id in sorted(matched):
        second_id = matched[first_id]
        if first_id > second_id or first_id in handled or second_id in handled:
            continue
        pair = (first_id, second_id)
        anchor_id = next(
            (aid for aid in pair if str(by_id[aid].get("gender", "")) == "男"), first_id
        )
        other_id = second_id if anchor_id == first_id else first_id
        husband, wife = by_id[anchor_id], by_id[other_id]
        rng = _rng(seed, f"{first_id}-{second_id}", "couple")
        kind = bond.get(anchor_id) or bond.get(other_id) or "spouse"
        ghosts: list[Member] = []
        if kind == "spouse":
            # A pin on either partner speaks for the household: they share
            # these children, so one pinned list wins over both samples.
            pinned_children, pinned_elders = pinned_members(anchor_id, overrides)
            if pinned_children is None:
                pinned_children, pinned_elders = pinned_members(other_id, overrides)
            if pinned_children is None:
                ghosts.extend(
                    _make_children(
                        husband, int(wife.get("age", 0)), _surname(husband.get("name", "")), rng, cfg
                    )
                )
            else:
                ghosts.extend(pinned_children)
            if pinned_elders is None:
                ghosts.extend(_maybe_elder(husband, wife, ghosts, rng, cfg))
            else:
                ghosts.extend(pinned_elders)
        hh_type = _couple_type(kind, ghosts)
        hh = _new_household([anchor_id, other_id], hh_type, ghosts)
        for aid, partner_id in ((anchor_id, other_id), (other_id, anchor_id)):
            partner = by_id[partner_id]
            members = [
                Member(
                    key=str(partner_id),
                    name=str(partner.get("name", "")),
                    role=kind,
                    kind="agent",
                    age=int(partner.get("age", 0) or 0),
                    gender=str(partner.get("gender", "")),
                    coresident=True,
                    agent_id=partner_id,
                ),
                *ghosts,
            ]
            by_agent[aid] = _record(hh, status[aid], members, kind)
            handled.add(aid)

    # 2) everyone else
    for agent in roster:
        aid = int(agent["id"])
        if aid in handled:
            continue
        by_agent[aid] = _solo_household(
            agent, status[aid], bond.get(aid), cfg, _new_household, overrides
        )
        handled.add(aid)

    # 3) parents living elsewhere. Everyone has parents; only some live with
    # them. Without this pass an agent's mother only exists if she moved in,
    # and "call your parents" / elder support never fire for anyone else.
    for agent in roster:
        _attach_remote_parents(agent, by_agent[int(agent["id"])], cfg)

    _share_home(households, by_id)
    return FamilyAssignment(households=households, by_agent=by_agent)


def _couple_type(kind: str, ghosts: list[Member]) -> str:
    has_coresident_child = any(m.role == "child" and m.coresident for m in ghosts)
    has_elder = any(m.role in ("father", "mother", "parent") and m.coresident for m in ghosts)
    if kind == "partner":
        return "cohabit"
    if has_elder and has_coresident_child:
        return "multigen"
    if has_elder:
        return "multigen"
    if has_coresident_child:
        return "nuclear"
    return "couple"


def _maybe_elder(
    anchor: dict[str, Any],
    partner: dict[str, Any] | None,
    ghosts: list[Member],
    rng: random.Random,
    cfg: dict[str, Any],
) -> list[Member]:
    """Draw a co-resident grandparent for a couple (三代同堂).

    More likely when a young child needs looking after — which is the actual
    mechanism behind the household type in urban China, not a free-floating
    share.
    """
    co = cfg.get("coresidence", {})
    young_max = int(co.get("young_child_max_age", 6))
    has_young = any(m.role == "child" and m.age <= young_max for m in ghosts)
    share = float(
        co.get("multigen_with_young_child", 0.34) if has_young else co.get("multigen_base", 0.16)
    )
    if rng.random() >= share:
        return []
    grandparent_gender = "女" if rng.random() < 0.65 else "男"
    base_age = int(anchor.get("age", 35) or 35) + rng.randint(25, 32)
    surname = _surname(anchor.get("name", "")) if grandparent_gender == "男" else None
    return [
        Member(
            key="g_coresident_parent",
            name=_ghost_name(rng, grandparent_gender, surname),
            role="mother" if grandparent_gender == "女" else "father",
            kind="ghost",
            age=base_age,
            gender=grandparent_gender,
            coresident=True,
            note="帮忙带孩子/操持家务" if has_young else "同住照应",
        )
    ]


def _solo_household(
    agent: dict[str, Any],
    status: str,
    bond_kind: str | None,
    cfg: dict[str, Any],
    new_household,
    overrides: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Household for an agent with no in-sim partner.

    Covers five shapes: off-screen spouse, off-screen partner, single parent,
    living with parents, and living alone / sharing a rental.
    """
    aid = int(agent["id"])
    overrides = overrides or {}
    pinned_children, pinned_elders = pinned_members(aid, overrides)
    rng = _rng(cfg.get("seed"), aid, "household")
    members: list[Member] = []
    hh_type = "single"

    if bond_kind:  # married or cohabiting, but nobody in-sim to pair with
        spouse = pinned_ghost_partner(aid, overrides)
        if spouse is None:
            gap = float(cfg.get("pairing", {}).get("spouse_age_gap_mean", 2.0))
            gender = _opposite(str(agent.get("gender", "男")))
            spouse_age = int(agent.get("age", 30) or 30) + (-gap if gender == "女" else gap)
            spouse_age = max(20, round(spouse_age + rng.randint(-2, 2)))
            spouse = Member(
                key="g_spouse",
                name=_ghost_name(rng, gender),
                role=bond_kind,
                kind="ghost",
                age=spouse_age,
                gender=gender,
                coresident=True,
            )
        spouse_age = spouse.age
        members.append(spouse)
        if bond_kind == "spouse":
            father_surname = _surname(
                agent.get("name", "") if str(agent.get("gender")) == "男" else spouse.name
            )
            if pinned_children is None:
                children = _make_children(agent, spouse_age, father_surname, rng, cfg)
            else:
                children = list(pinned_children)
            members.extend(children)
            if pinned_elders is None:
                members.extend(_maybe_elder(agent, None, children, rng, cfg))
            else:
                members.extend(pinned_elders)
            hh_type = _couple_type("spouse", members)
        else:
            hh_type = "cohabit"
    elif status in ("divorced", "widowed"):
        father_surname = _surname(agent.get("name", "")) if str(agent.get("gender")) == "男" else None
        if pinned_children is None:
            children = _make_children(
                agent, None, father_surname or _surname(agent.get("name", "")), rng, cfg
            )
        else:
            children = list(pinned_children)
        if status == "divorced":
            # Custody: the children live with this agent ~55% of the time —
            # but not when the operator pinned who lives where.
            keeps = rng.random() < 0.55
            if pinned_children is None:
                for child in children:
                    child.coresident = child.coresident and keeps
            members.append(
                Member(
                    key="g_ex_spouse",
                    name=_ghost_name(rng, _opposite(str(agent.get("gender", "男")))),
                    role="ex",
                    kind="ghost",
                    age=int(agent.get("age", 35) or 35) + rng.randint(-3, 3),
                    gender=_opposite(str(agent.get("gender", "男"))),
                    coresident=False,
                    note="离异后仍因子女保持联系" if children else "",
                )
            )
        members.extend(children)
        hh_type = "single_parent" if any(m.role == "child" and m.coresident for m in members) else "single"
    elif pinned_elders:
        members.extend(pinned_elders)
        hh_type = "with_parents"
    elif pinned_elders is None and _with_parents(agent, cfg):
        members.extend(_parent_members(agent, rng, coresident=True, cfg=cfg))
        hh_type = "with_parents"
    else:
        share = float(cfg.get("coresidence", {}).get("shared_rental_share", 0.45))
        hh_type = "shared" if rng.random() < share else "single"

    # Elderly agents living with an adult child (the mirror of with_parents).
    co = cfg.get("coresidence", {})
    if (
        hh_type in ("single", "shared")
        and int(agent.get("age", 0) or 0) >= int(co.get("elder_with_child_age", 70))
        and rng.random() < float(co.get("elder_with_child_share", 0.35))
    ):
        child_gender = "男" if rng.random() < 0.5 else "女"
        members = [
            Member(
                key="g_adult_child",
                name=_ghost_name(rng, child_gender, _surname(agent.get("name", ""))),
                role="child",
                kind="ghost",
                age=max(20, int(agent.get("age", 70)) - rng.randint(26, 34)),
                gender=child_gender,
                coresident=True,
                note="成年子女，同住照料",
            )
        ]
        hh_type = "multigen"

    ghosts = [m for m in members if m.kind == "ghost"]
    hh = new_household([aid], hh_type, ghosts)
    return _record(hh, status, members, bond_kind)


def _record(
    household: Household,
    status: str,
    members: list[Member],
    bond_kind: str | None,
) -> dict[str, Any]:
    return {
        "household_id": household.id,
        "household_type": household.type,
        "marital_status": status,
        "bond": bond_kind or "",
        "members": [m.to_dict() for m in members],
    }


def _share_home(households: list[Household], by_id: dict[int, dict[str, Any]]) -> None:
    """Give every co-resident agent in a household the same ``home`` node.

    Without this, an in-sim married couple would live at two different
    addresses and never meet at home — the co-location loop is what turns a
    kin tie into a lived-in family.
    """
    for hh in households:
        if len(hh.agent_ids) < 2:
            if hh.agent_ids:
                anchor = by_id[hh.agent_ids[0]]
                hh.home = str((anchor.get("locations") or {}).get("home", "") or "")
            continue
        anchor = by_id[hh.agent_ids[0]]
        home = str((anchor.get("locations") or {}).get("home", "") or "")
        hh.home = home
        if not home:
            continue
        for aid in hh.agent_ids[1:]:
            locations = by_id[aid].get("locations")
            if not isinstance(locations, dict):
                continue
            old_home = locations.get("home")
            locations["home"] = home
            for key in ("current", "destination"):
                if locations.get(key) == old_home:
                    locations[key] = home
            route = locations.get("travel_route")
            if isinstance(route, list):
                locations["travel_route"] = [home if node == old_home else node for node in route]


def pair_roommates(assignment: FamilyAssignment, agents: list[dict[str, Any]], config=None) -> int:
    """Merge ``shared`` households into flatshares of 2-3 in-sim agents.

    Shared rental is the default living arrangement for young migrants in
    Hangzhou, and a flatmate is the only person a single agent sees at home.
    Returns the number of households merged away.
    """
    cfg = family_config(config)
    by_id = {int(a["id"]): a for a in agents if isinstance(a, dict) and a.get("id") is not None}
    singles = [
        hh
        for hh in assignment.households
        if hh.type == "shared" and len(hh.agent_ids) == 1 and not hh.ghost_members
    ]
    if len(singles) < 2:
        return 0
    # Group by district so flatmates are plausible, then pair by age.
    buckets: dict[str, list[Household]] = {}
    for hh in singles:
        buckets.setdefault(hh.district, []).append(hh)
    merged = 0
    rng = _rng(cfg.get("seed"), "roommates", "merge")
    for district in sorted(buckets):
        pool = sorted(buckets[district], key=lambda h: int(by_id[h.agent_ids[0]].get("age", 0) or 0))
        index = 0
        while index + 1 < len(pool):
            size = 3 if (len(pool) - index) >= 3 and rng.random() < 0.35 else 2
            group = pool[index : index + size]
            if len(group) < 2:
                break
            host = group[0]
            for other in group[1:]:
                host.agent_ids.extend(other.agent_ids)
                assignment.households.remove(other)
                merged += 1
            index += size
    _relink(assignment, by_id)
    return merged


def _relink(assignment: FamilyAssignment, by_id: dict[int, dict[str, Any]]) -> None:
    """Rewrite per-agent records after flatshares were merged.

    Only ``shared`` households are touched: a married couple also has two
    agent ids in one household, and calling them each other's flatmates
    would put "合租室友" next to "配偶" in the same brief.
    """
    for hh in assignment.households:
        if hh.type != "shared":
            continue
        for aid in hh.agent_ids:
            record = assignment.by_agent.get(aid)
            if record is None:
                continue
            record["household_id"] = hh.id
            record["household_type"] = hh.type
            existing = [m for m in record["members"] if m.get("kind") != "agent" or m.get("role") != "roommate"]
            roommates = [
                Member(
                    key=str(other),
                    name=str(by_id[other].get("name", "")),
                    role="roommate",
                    kind="agent",
                    age=int(by_id[other].get("age", 0) or 0),
                    gender=str(by_id[other].get("gender", "")),
                    coresident=True,
                    agent_id=other,
                ).to_dict()
                for other in hh.agent_ids
                if other != aid
            ]
            record["members"] = existing + roommates
    _share_home(assignment.households, by_id)
