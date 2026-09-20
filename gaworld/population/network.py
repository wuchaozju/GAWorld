"""Households, workplaces and the social graph for a synthetic population.

Sampling independent individuals is the easy half. What makes a population
behave like a society is its *structure*: who lives with whom, who works
alongside whom, and who the remaining friendships connect. Those are built
here, in that order — households first, because they determine who is
available to be a coworker or a friend.

Ties are emitted straight into the shape ``gaworld/social/network.py`` already
expects (``ensure_relationship_schema``), and the result is passed through the
existing ``enforce_dunbar`` so kin survive pruning and everyone gets a tier.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from gaworld.population.schema import EDUCATION_LEVELS, PopulationSpec
from gaworld.population.synth import Person, derive_rng
from gaworld.social.network import DUNBAR_TIERS, enforce_dunbar, ensure_relationship_schema

CHILD_MAX_AGE = 17
ELDER_MIN_AGE = 65

#: Tie strengths by role. Kin start close and trusting; workplace and
#: neighbourhood ties start weak enough that the simulation has somewhere to go.
_TIE_PRESETS: dict[str, dict[str, float]] = {
    "spouse": {"closeness": 0.85, "trust": 0.85, "obligation": 0.85, "friction": 0.25},
    "child": {"closeness": 0.88, "trust": 0.85, "obligation": 0.90, "friction": 0.20},
    "parent": {"closeness": 0.82, "trust": 0.80, "obligation": 0.78, "friction": 0.25},
    "sibling": {"closeness": 0.68, "trust": 0.72, "obligation": 0.62, "friction": 0.30},
    "grandparent": {"closeness": 0.72, "trust": 0.78, "obligation": 0.70, "friction": 0.20},
    "relative": {"closeness": 0.50, "trust": 0.58, "obligation": 0.40, "friction": 0.28},
    "coworker": {"closeness": 0.42, "trust": 0.48, "obligation": 0.42, "friction": 0.32},
    "neighbor": {"closeness": 0.34, "trust": 0.40, "obligation": 0.28, "friction": 0.28},
    "friend": {"closeness": 0.55, "trust": 0.58, "obligation": 0.40, "friction": 0.25},
    "acquaintance": {"closeness": 0.28, "trust": 0.35, "obligation": 0.18, "friction": 0.25},
}


@dataclass
class HouseholdRecord:
    id: int
    type: str
    member_ids: list[int] = field(default_factory=list)
    district: str = ""


@dataclass
class WorkplaceRecord:
    id: int
    industry: str
    member_ids: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------


def build_households(spec: PopulationSpec, people: list[Person]) -> list[HouseholdRecord]:
    """Partition ``people`` into households and stamp roles onto each Person.

    Deliberately **child-first**. Planning household counts from the type-share
    knobs and then filling them produces nonsense whenever the age pyramid
    disagrees with the household knobs — you ask for 26% nuclear families, the
    town only has 80 children, the family households starve and every leftover
    adult becomes a one-person household. So the order is inverted:

    1. every child is placed into a family household (nuclear / single-parent /
       multigen, split by the knobs' *relative* weights);
    2. elders fill the multigen households, then join the general pool;
    3. remaining adults are packed into single / couple / shared households,
       sized to hit ``mean_size`` and ``share_single_person`` as closely as the
       leftover headcount allows.

    Nobody is ever left unassigned, and the gap between requested and achieved
    household statistics is reported rather than papered over.
    """
    rng = derive_rng(spec.seed, "household")
    hh = spec.household
    by_id = {p.id: p for p in people}

    children = sorted([p.id for p in people if p.age <= CHILD_MAX_AGE], key=lambda i: -by_id[i].age)
    elders = [p.id for p in people if p.age >= ELDER_MIN_AGE]
    adults = [p.id for p in people if CHILD_MAX_AGE < p.age < ELDER_MIN_AGE]
    rng.shuffle(adults)
    rng.shuffle(elders)

    target_households = max(1, round(len(people) / max(hh.mean_size, 1.0)))

    households: list[HouseholdRecord] = []
    counter = 0

    def new_household(kind: str, members: list[int]) -> None:
        nonlocal counter
        if not members:
            return
        counter += 1
        households.append(HouseholdRecord(id=counter, type=kind, member_ids=list(members)))

    def take(pool: list[int], count: int) -> list[int]:
        taken = pool[: max(0, count)]
        del pool[: max(0, count)]
        return taken

    def pick_partner(pool: list[int], anchor_id: int) -> int | None:
        """Nearest-age candidate, offset by the configured spouse age gap."""
        if not pool:
            return None
        anchor = by_id[anchor_id]
        gap = hh.spouse_age_gap_mean if anchor.gender == "男" else -hh.spouse_age_gap_mean
        wanted = anchor.age - gap
        # Scan a bounded window so this stays O(N) overall rather than O(N²).
        window = pool[:40]
        best = min(window, key=lambda i: abs(by_id[i].age - wanted))
        pool.remove(best)
        return best

    # --- Step 1+2: family households, driven by the actual child headcount ---
    children_per_family = max(0.5, hh.fertility_children_mean)
    n_family = min(
        len(children),
        max(1, round(len(children) / children_per_family)) if children else 0,
    )
    remainder = max(0.0, 1.0 - hh.share_single_person - hh.share_multigen - hh.share_shared_rental)
    family_weights = {
        "multigen": hh.share_multigen,
        "nuclear": remainder * 0.58,
        "single_parent": remainder * 0.12,
    }
    weight_total = sum(family_weights.values()) or 1.0
    family_plan: list[str] = []
    for kind, weight in family_weights.items():
        family_plan.extend([kind] * round(n_family * weight / weight_total))
    family_plan.extend(["nuclear"] * max(0, n_family - len(family_plan)))
    rng.shuffle(family_plan)

    for kind in family_plan:
        if not children:
            break
        if kind == "single_parent" and adults:
            members = take(adults, 1)
        elif len(adults) >= 2:
            anchor = take(adults, 1)[0]
            partner = pick_partner(adults, anchor)
            members = [anchor] + ([partner] if partner is not None else [])
        elif adults:
            members = take(adults, 1)
            kind = "single_parent"
        else:
            break
        # Only take children a parent in this household could plausibly have.
        # Without this filter a 19-year-old anchor ends up "parenting" a
        # 17-year-old, which the validator then flags.
        oldest = max(by_id[i].age for i in members)
        n_children = max(1, int(rng.poisson(hh.fertility_children_mean)))
        eligible = [i for i in children if oldest - by_id[i].age >= 15][:n_children]
        for child_id in eligible:
            children.remove(child_id)
        members += eligible
        if not eligible:
            kind = "couple" if len(members) >= 2 else "single"
        if kind == "multigen" and elders:
            members += take(elders, 1 if rng.random() < 0.6 else min(2, len(elders)))
        elif kind == "multigen":
            kind = "nuclear"
        new_household(kind, members)

    # Any child the plan could not reach joins an existing family household —
    # preferring one whose oldest adult is plausibly old enough to be a parent.
    families = [h for h in households if h.type in ("nuclear", "single_parent", "multigen")]

    def oldest_adult_age(record: HouseholdRecord) -> int:
        ages = [by_id[i].age for i in record.member_ids if by_id[i].age > CHILD_MAX_AGE]
        return max(ages) if ages else 0

    for index, child_id in enumerate(children):
        child_age = by_id[child_id].age
        candidates = [h for h in families if oldest_adult_age(h) - child_age >= 15]
        if candidates:
            candidates[index % len(candidates)].member_ids.append(child_id)
        elif families:
            families[index % len(families)].member_ids.append(child_id)
        elif adults:
            new_household("single_parent", [take(adults, 1)[0], child_id])
        else:
            new_household("single", [child_id])
    children.clear()

    # --- Step 3: pack the remaining adults and elders ---
    # Slots are budgeted from the knobs first, then *sized* to consume exactly
    # the leftover headcount. Filling greedily instead would let household type
    # drift far from the request (mostly by labelling every random pair a
    # shared rental).
    rest = adults + elders
    rng.shuffle(rest)
    adults.clear()
    elders.clear()

    if rest:
        remaining_households = max(1, target_households - len(households))

        # Top up multigen households. A three-generation household does not
        # require minors — adult children living with elderly parents counts —
        # so the child-driven pass above systematically undershoots the knob.
        multigen_so_far = sum(1 for h in households if h.type == "multigen")
        multigen_wanted = round(hh.share_multigen * target_households) - multigen_so_far
        elder_pool = [i for i in rest if by_id[i].age >= ELDER_MIN_AGE]
        adult_pool = [i for i in rest if by_id[i].age < ELDER_MIN_AGE]
        for _ in range(max(0, multigen_wanted)):
            if len(adult_pool) < 2 or not elder_pool or remaining_households <= 1:
                break
            members = [adult_pool.pop(0), adult_pool.pop(0), elder_pool.pop(0)]
            new_household("multigen", members)
            for member_id in members:
                rest.remove(member_id)
            remaining_households -= 1
        if not rest:
            remaining_households = 0

    if rest:
        n_single = max(0, min(round(hh.share_single_person * target_households), remaining_households))
        n_shared = max(
            0, min(round(hh.share_shared_rental * target_households), remaining_households - n_single)
        )
        n_couple = max(0, remaining_households - n_single - n_shared)

        sizes = [1] * n_single + [2] * n_shared + [2] * n_couple
        kinds = ["single"] * n_single + ["shared_rental"] * n_shared + ["couple"] * n_couple

        # Reconcile the slot budget with the actual headcount.
        surplus = len(rest) - sum(sizes)
        while surplus < 0 and len(kinds) > 1:
            # Too few people: drop the last two-person slot.
            for index in range(len(kinds) - 1, -1, -1):
                if sizes[index] > 1:
                    surplus += sizes.pop(index)
                    kinds.pop(index)
                    break
            else:
                break
        if surplus < 0 and sizes:
            sizes[-1] = max(1, sizes[-1] + surplus)
            surplus = 0
        growable = [i for i, kind in enumerate(kinds) if kind == "shared_rental"] or [
            i for i, kind in enumerate(kinds) if kind == "couple"
        ]
        cursor = 0
        while surplus > 0 and growable:
            index = growable[cursor % len(growable)]
            if sizes[index] < hh.max_size:
                sizes[index] += 1
                surplus -= 1
            elif all(sizes[i] >= hh.max_size for i in growable):
                sizes[-1] += surplus
                surplus = 0
            cursor += 1
        # A grown "couple" is no longer a couple.
        kinds = [
            "shared_rental" if kind == "couple" and size > 2 else kind
            for kind, size in zip(kinds, sizes, strict=True)
        ]

        # Shared rentals skew young; couples are age-matched. Serving shared
        # slots from the young end of the pool and couples from the middle
        # keeps both plausible without a matching solver.
        rest.sort(key=lambda i: by_id[i].age)
        for kind, size in sorted(
            zip(kinds, sizes, strict=True), key=lambda item: 0 if item[0] == "shared_rental" else 1
        ):
            if not rest:
                break
            if kind == "couple" and len(rest) >= 2:
                anchor = take(rest, 1)[0]
                partner = pick_partner(rest, anchor)
                new_household("couple", [anchor] + ([partner] if partner is not None else []))
            else:
                new_household(kind, take(rest, min(size, len(rest))))
        while rest:  # pragma: no cover - only if slot sizing under-counted
            new_household("single", take(rest, 1))

    for record in households:
        record.member_ids.sort()
        record.district = by_id[record.member_ids[0]].district if record.member_ids else ""
        for member_id in record.member_ids:
            person = by_id[member_id]
            person.household_id = record.id
            person.household_type = record.type
            person.household_role = _household_role(person, record, by_id)
            # Everyone in a household shares its address.
            person.residence = by_id[record.member_ids[0]].residence
            person.district = by_id[record.member_ids[0]].district

    return households


def _household_role(person: Person, record: HouseholdRecord, by_id: dict[int, Person]) -> str:
    if record.type == "shared_rental":
        return "roommate"
    if person.age <= CHILD_MAX_AGE:
        return "child"
    if person.age >= ELDER_MIN_AGE and record.type == "multigen":
        return "grandparent"
    adults = [by_id[i] for i in record.member_ids if CHILD_MAX_AGE < by_id[i].age < ELDER_MIN_AGE]
    if len(record.member_ids) == 1:
        return "head"
    if len(adults) >= 2:
        return "spouse"
    return "head"


# ---------------------------------------------------------------------------
# Workplaces
# ---------------------------------------------------------------------------


def build_workplaces(spec: PopulationSpec, people: list[Person]) -> list[WorkplaceRecord]:
    """Group employed people into firms with power-law sizes.

    Workplaces exist to *generate ties*, not as an attribute: a handful of
    large employers plus a long tail of small ones produces a much more
    realistic coworker graph than assigning everyone in an industry to one
    blob.
    """
    rng = derive_rng(spec.seed, "workplace")
    alpha = spec.social_network.workplace_size_alpha
    workplaces: list[WorkplaceRecord] = []
    counter = 0
    by_industry: dict[str, list[int]] = defaultdict(list)
    for person in people:
        if person.employment == "employed":
            by_industry[person.industry].append(person.id)

    by_id = {p.id: p for p in people}
    for industry, member_ids in by_industry.items():
        pool = list(member_ids)
        rng.shuffle(pool)
        while pool:
            # Pareto sizes, clipped so one firm cannot swallow the industry.
            size = int(min(len(pool), max(2, math.ceil(rng.pareto(alpha) * 4))))
            counter += 1
            chunk = pool[:size]
            del pool[:size]
            workplaces.append(WorkplaceRecord(id=counter, industry=industry, member_ids=chunk))
            for member_id in chunk:
                by_id[member_id].workplace_id = counter
    return workplaces


# ---------------------------------------------------------------------------
# Social graph
# ---------------------------------------------------------------------------


def _attribute_similarity(a: Person, b: Person, spec: PopulationSpec) -> float:
    """Homophily score in [0,1] over the dimensions we actually model."""
    age_sim = 1.0 - min(abs(a.age - b.age) / 40.0, 1.0)
    edu_sim = 1.0 - abs(EDUCATION_LEVELS.index(a.education) - EDUCATION_LEVELS.index(b.education)) / (
        len(EDUCATION_LEVELS) - 1
    )
    industry_sim = 1.0 if a.industry == b.industry else 0.0
    hukou_sim = 1.0 if a.hukou == b.hukou else 0.0
    score = 0.30 * age_sim + 0.20 * edu_sim + 0.25 * industry_sim + 0.25 * hukou_sim
    strength = spec.social_network.homophily_strength
    # strength=0 → everyone equally likely; strength=1 → similarity dominates.
    return (1.0 - strength) + strength * score


def _geo_factor(a: Person, b: Person, spec: PopulationSpec) -> float:
    """Distance penalty. Districts are categorical, so this is same/different.

    The spec has no coordinates — ``district_weights`` is a name→share map —
    so proximity can only be modelled at district granularity. ``geo_decay``
    is therefore the penalty applied to cross-district ties.
    """
    if a.district == b.district:
        return 1.0
    return max(1e-3, 1.0 - spec.social_network.geo_decay)


def build_social_graph(
    spec: PopulationSpec,
    people: list[Person],
    households: list[HouseholdRecord],
    workplaces: list[WorkplaceRecord],
) -> dict[int, list[int]]:
    """Attach ``relationships`` to every Person; return the neighbour index.

    Ties come from four sources, in priority order: household (kin/roommate),
    workplace (coworker), same-address neighbours, and finally elective
    friendships sampled by homophily × geography with a Watts–Strogatz style
    random rewire so the graph keeps small-world path lengths instead of
    fragmenting into cliques.
    """
    by_id = {p.id: p for p in people}
    for person in people:
        person.relationships = {}

    def link(a_id: int, b_id: int, role: str, origin: str) -> None:
        if a_id == b_id:
            return
        _add_tie(by_id[a_id], b_id, role, origin)
        _add_tie(by_id[b_id], a_id, _reciprocal_role(role, by_id[b_id], by_id[a_id]), origin)

    # 1. Household ties.
    for household in households:
        for i, a_id in enumerate(household.member_ids):
            for b_id in household.member_ids[i + 1 :]:
                link(a_id, b_id, _kin_role(by_id[a_id], by_id[b_id], household), "household")

    # 2. Workplace ties. Small firms are near-complete; large ones are split
    #    into "teams" so a 60-person employer does not create 1,770 edges.
    work_rng = derive_rng(spec.seed, "work_ties")
    for workplace in workplaces:
        members = workplace.member_ids
        if len(members) <= 6:
            for i, a_id in enumerate(members):
                for b_id in members[i + 1 :]:
                    link(a_id, b_id, "coworker", "workplace")
        else:
            shuffled = list(members)
            work_rng.shuffle(shuffled)
            for start in range(0, len(shuffled), 5):
                team = shuffled[start : start + 5]
                for i, a_id in enumerate(team):
                    for b_id in team[i + 1 :]:
                        link(a_id, b_id, "coworker", "workplace")

    # 3. Neighbours: a couple of ties among households at the same address.
    neighbour_rng = derive_rng(spec.seed, "neighbors")
    by_address: dict[str, list[int]] = defaultdict(list)
    for record in households:
        if record.member_ids:
            by_address[by_id[record.member_ids[0]].residence].append(record.id)
    households_by_id = {h.id: h for h in households}
    for household_ids in by_address.values():
        if len(household_ids) < 2:
            continue
        for household_id in household_ids:
            others = [h for h in household_ids if h != household_id]
            neighbour_rng.shuffle(others)
            for other_id in others[:2]:
                a_members = households_by_id[household_id].member_ids
                b_members = households_by_id[other_id].member_ids
                if a_members and b_members:
                    link(a_members[0], b_members[0], "neighbor", "neighborhood")

    # 4. Elective friendships up to the mean-degree budget.
    _add_friendships(spec, people, by_id, link)

    limits = {**DUNBAR_TIERS, "weak": spec.social_network.dunbar_weak_cap}
    neighbours: dict[int, list[int]] = {}
    for person in people:
        agent_view: dict[str, Any] = {"relationships": person.relationships}
        enforce_dunbar(agent_view, limits)
        neighbours[person.id] = sorted(int(key) for key in person.relationships)
    return neighbours


def _add_friendships(
    spec: PopulationSpec,
    people: list[Person],
    by_id: dict[int, Person],
    link: Any,
) -> None:
    rng = derive_rng(spec.seed, "friendship")
    target_edges = round(spec.social_network.mean_degree * len(people) / 2)
    existing = sum(len(p.relationships) for p in people) // 2
    remaining = max(0, target_edges - existing)
    if remaining <= 0 or len(people) < 2:
        return

    ids = [p.id for p in people]
    rewire_p = spec.social_network.rewire_p
    # Propose a small candidate set per edge and keep the best-scoring pair:
    # cheaper than materialising the full N² weight matrix and, at these
    # sizes, indistinguishable in the resulting degree distribution.
    candidates_per_edge = 8
    attempts = 0
    added = 0
    while added < remaining and attempts < remaining * 12:
        attempts += 1
        a_id = ids[int(rng.integers(len(ids)))]
        a = by_id[a_id]
        if rng.random() < rewire_p:
            # Watts-Strogatz style shortcut: ignore similarity entirely.
            b_id = ids[int(rng.integers(len(ids)))]
        else:
            picks = rng.integers(len(ids), size=candidates_per_edge)
            best_id, best_score = None, -1.0
            for index in picks:
                candidate_id = ids[int(index)]
                if candidate_id == a_id or str(candidate_id) in a.relationships:
                    continue
                b = by_id[candidate_id]
                score = _attribute_similarity(a, b, spec) * _geo_factor(a, b, spec)
                if score > best_score:
                    best_id, best_score = candidate_id, score
            b_id = best_id if best_id is not None else a_id
        if b_id == a_id or str(b_id) in a.relationships:
            continue
        role = "friend" if rng.random() < 0.65 else "acquaintance"
        link(a_id, b_id, role, "elective")
        added += 1


def _kin_role(a: Person, b: Person, record: HouseholdRecord) -> str:
    """Role of ``b`` as seen from ``a`` inside a shared household."""
    if record.type == "shared_rental":
        return "friend"
    a_child = a.age <= CHILD_MAX_AGE
    b_child = b.age <= CHILD_MAX_AGE
    if a_child and b_child:
        return "sibling"
    if b_child:
        return "child"
    if a_child:
        return "parent"
    if a.age >= ELDER_MIN_AGE or b.age >= ELDER_MIN_AGE:
        return "relative" if abs(a.age - b.age) < 15 else "grandparent"
    if abs(a.age - b.age) <= 15 and a.gender != b.gender:
        return "spouse"
    return "relative"


def _reciprocal_role(role: str, viewer: Person, other: Person) -> str:
    """Invert an asymmetric kin role for the other end of the tie."""
    if role == "child":
        return "grandparent" if viewer.age >= ELDER_MIN_AGE else "parent"
    if role == "parent":
        return "child"
    if role == "grandparent":
        return "child" if other.age <= CHILD_MAX_AGE else "relative"
    return role


def _add_tie(person: Person, other_id: int, role: str, origin: str) -> None:
    key = str(other_id)
    if key in person.relationships:
        return
    preset = _TIE_PRESETS.get(role, _TIE_PRESETS["acquaintance"])
    item: dict[str, Any] = dict(preset)
    item["last_interaction_day"] = 0
    person.relationships[key] = ensure_relationship_schema(
        item, role=role, kind="agent", tie_origin=origin, current_day=0
    )


# ---------------------------------------------------------------------------
# Graph metrics (used by the report layer)
# ---------------------------------------------------------------------------


def graph_metrics(neighbours: dict[int, list[int]]) -> dict[str, Any]:
    """Degree, clustering and path-length statistics for the review charts."""
    ids = sorted(neighbours)
    degrees = np.array([len(neighbours[i]) for i in ids], dtype=float)
    adjacency = {i: set(neighbours[i]) for i in ids}

    clustering_values = []
    for node in ids:
        peers = list(adjacency[node])
        if len(peers) < 2:
            clustering_values.append(0.0)
            continue
        links = sum(1 for i, a in enumerate(peers) for b in peers[i + 1 :] if b in adjacency[a])
        clustering_values.append(2.0 * links / (len(peers) * (len(peers) - 1)))

    nodes = len(ids)
    mean_degree = float(degrees.mean()) if nodes else 0.0
    clustering = float(np.mean(clustering_values)) if clustering_values else 0.0
    path_length = _sampled_path_length(adjacency)

    # Small-worldness is a *relative* property: high clustering compared to a
    # random graph of the same size and degree, with path length still close
    # to random. Absolute thresholds ("clustering > 0.15") are meaningless
    # because both quantities move with mean degree.
    random_clustering = mean_degree / nodes if nodes else 0.0
    random_path = math.log(nodes) / math.log(mean_degree) if nodes > 1 and mean_degree > 1 else 0.0
    sigma = 0.0
    if random_clustering > 0 and random_path > 0 and path_length > 0:
        sigma = (clustering / random_clustering) / (path_length / random_path)

    return {
        "nodes": nodes,
        "edges": int(degrees.sum() // 2),
        "mean_degree": mean_degree,
        "max_degree": int(degrees.max()) if nodes else 0,
        "isolated": int((degrees == 0).sum()),
        "clustering": clustering,
        "random_clustering": random_clustering,
        "mean_path_length": path_length,
        "random_path_length": random_path,
        "small_world_sigma": sigma,
        "largest_component_share": _largest_component_share(adjacency),
        "degree_histogram": _degree_histogram(degrees),
    }


def _degree_histogram(degrees: np.ndarray) -> list[dict[str, int]]:
    if not len(degrees):
        return []
    counts: dict[int, int] = defaultdict(int)
    for value in degrees.astype(int):
        counts[int(value)] += 1
    return [{"degree": k, "count": counts[k]} for k in sorted(counts)]


def _largest_component_share(adjacency: dict[int, set[int]]) -> float:
    seen: set[int] = set()
    largest = 0
    for start in adjacency:
        if start in seen:
            continue
        stack = [start]
        component = 0
        seen.add(start)
        while stack:
            node = stack.pop()
            component += 1
            for peer in adjacency.get(node, ()):
                if peer not in seen:
                    seen.add(peer)
                    stack.append(peer)
        largest = max(largest, component)
    return largest / len(adjacency) if adjacency else 0.0


def _sampled_path_length(adjacency: dict[int, set[int]], samples: int = 30) -> float:
    """Mean shortest-path length, estimated from a few BFS roots.

    Exact all-pairs BFS is O(N·E); at N=500 that is affordable but pointless —
    a 30-root sample pins the number down to well within the precision anyone
    reads it at.
    """
    ids = sorted(adjacency)
    if len(ids) < 2:
        return 0.0
    roots = ids[:: max(1, len(ids) // samples)][:samples]
    total, pairs = 0, 0
    for root in roots:
        distance = {root: 0}
        queue = [root]
        while queue:
            node = queue.pop(0)
            for peer in adjacency.get(node, ()):
                if peer not in distance:
                    distance[peer] = distance[node] + 1
                    queue.append(peer)
        for node, dist in distance.items():
            if node != root:
                total += dist
                pairs += 1
    return total / pairs if pairs else 0.0


__all__ = [
    "HouseholdRecord",
    "WorkplaceRecord",
    "build_households",
    "build_social_graph",
    "build_workplaces",
    "graph_metrics",
]
