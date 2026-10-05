"""FamilyPlugin — households as a first-class part of an agent's life.

Wiring, and why each hook is the one it is:

- ``agents.built`` — households must exist before anything reads an agent.
  This is also the only point where rewriting ``locations["home"]`` is safe,
  because nothing has moved yet. Co-residents get the *same* home node, which
  is what makes the existing co-location loop produce family interaction
  instead of two strangers with matching addresses.
- ``on_simulation_start`` — kin ties are written here, not at
  ``agents.built``, because in between the simulator resets/reloads
  ``agent["relationships"]`` and then asks an LLM for an off-screen roster.
  Writing earlier would be silently discarded; writing here also lets us
  prune the roster's invented spouses.
- ``on_day_end`` (priority ``-10``) — after the economy has booked the day,
  bill the household's dependants and let partners cover each other. Also
  precomputes *tomorrow's* family duties, because daily routines are
  generated before ``on_day_start`` fires.
- ``perception.sections`` — who is at home right now.
- ``state.effects`` — household emotional contagion.

The plugin degrades rather than fails: no economy runtime means no billing,
no life-event queue means no family events, and the family still shows up in
prompts and relationships.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.family import events as family_events
from gaworld.family import finance as family_finance
from gaworld.family import lifecycle, promote
from gaworld.family.assign import assign_households, pair_roommates
from gaworld.family.duties import care_load, duty_hint
from gaworld.family.lifecycle import apply_transition, family_facts, refresh_household_type
from gaworld.family.narrative import family_brief, family_section, family_summary_line
from gaworld.family.schema import Household, family_config
from gaworld.family.ties import TIE_PRESETS, apply_family_ties, reconcile_ghost_kin
from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger
from gaworld.sim._utils import _resolve_day_context, calendar_from_config
from gaworld.travel import itinerary as travel_itinerary
from gaworld.world import away

_LOG = get_logger("gaworld.family.plugin")

#: Life events that change who lives in the household.
TRANSITION_KEYS = ("marriage", "childbirth", "bereavement", "divorce", "separation")
_VERBS = {"marriage": "结婚", "childbirth": "添丁", "bereavement": "亲人离世",
          "divorce": "离婚", "separation": "分手"}

#: (what the change is, the peer's role in the holder's record) -> the new
#: member's role as the peer sees it.
_RELATIVE = {
    ("childbirth", "spouse"): "child", ("childbirth", "partner"): "child",
    ("childbirth", "child"): "sibling",
    ("childbirth", "father"): "grandchild", ("childbirth", "mother"): "grandchild",
    ("childbirth", "parent"): "grandchild",
    ("marriage", "child"): "parent",
    ("marriage", "father"): "child", ("marriage", "mother"): "child",
    ("marriage", "parent"): "child",
}


class FamilyPlugin(Plugin):
    id = "family"

    # Deliberately empty: family works without the economy or the life-event
    # queue, so declaring them here (which would disable the whole plugin
    # when one is absent) would trade a working feature for a strict edge.
    requires = ()

    def setup(self, ctx):
        self._cfg = family_config(getattr(ctx, "config", None))
        self._calendar = calendar_from_config(getattr(ctx, "config", None))
        self._seed = self._cfg.get("seed", 20260813)
        if not self._cfg.get("enabled", True):
            return
        ctx.bus.on("agents.built", self._build_households)
        if (self._cfg.get("members_as_agents") or {}).get("enabled", False):
            # Ahead of every other `agents.built` handler (home environment is
            # at 10), so the new residents get seeded like everyone else.
            ctx.bus.on("agents.built", self._promote_members, priority=20)
        ctx.bus.on("on_simulation_start", self._wire_ties)
        ctx.bus.on("on_day_start", self._enqueue_events)
        ctx.bus.on("on_day_end", self._settle, priority=-10)
        ctx.bus.on("perception.sections", self._perception_section)
        ctx.bus.on("state.effects", self._contagion)
        # Long-horizon steps: the household ages along with the agent.
        ctx.bus.on("life.step", self._age_household, priority=15)
        # Marriage / childbirth / bereavement land here once the life-events
        # plugin has applied them.
        ctx.bus.on("life.event.applied", self._apply_life_transition)

    # -- construction -------------------------------------------------------

    def _build_households(self, hook_ctx):
        ctx = hook_ctx["sim"]
        agents = hook_ctx.get("agents") or []
        state = ctx.plugin_state(self.id)
        # Promotion builds the households early (priority 20); the regular
        # handler must not then re-sample them and drop the new residents.
        if state.get("built_for") is agents:
            return
        state["built_for"] = agents
        assignment = assign_households(agents, getattr(ctx, "config", None))
        pair_roommates(assignment, agents, getattr(ctx, "config", None))
        state["assignment"] = assignment
        state["by_agent"] = assignment.by_agent

        for agent in agents:
            record = assignment.by_agent.get(int(agent["id"]))
            if not record:
                continue
            ctx.agent_ext(agent, self.id).update(record)
            # `family` sits next to `personality` / `daily_life` because it is
            # a profile attribute the prompt builders render, not plugin
            # bookkeeping — the bookkeeping lives in `ext` above.
            agent["family"] = family_brief(record)
            agent["family_today"] = ""

        summary = assignment.summary()
        _LOG.info("family: %s", summary)
        print(
            "👪 家庭结构已生成："
            f"{summary['households']} 户 / {summary['agents']} 人，"
            f"其中仿真内夫妻 {summary['in_sim_couples']} 对，"
            f"有子女 {summary['with_children']} 人；"
            f"婚姻状态 {summary['marital_statuses']}"
        )
        try:
            ctx.recorder.record("family.summary", summary)
            for household in assignment.households:
                ctx.recorder.record("family.household", household.to_dict())
        except Exception as exc:
            _LOG.warning("family household recording failed: %s", exc)

    def _record_for(self, ctx, agent) -> dict[str, Any]:
        return ctx.agent_ext(agent, self.id)

    def _promote_members(self, hook_ctx):
        """Make co-resident school-age children and elders residents.

        See :mod:`gaworld.family.promote`. Runs once, before day 1: builds the
        households, appends the new residents to the run's agent list (the
        same list the main loop initialises after this event), and rewires
        every record that listed them as off-screen ghosts.
        """
        ctx = hook_ctx["sim"]
        agents = hook_ctx.get("agents")
        if agents is None:
            return
        self._build_households(hook_ctx)
        cfg = self._cfg.get("members_as_agents") or {}
        records = {int(a["id"]): self._record_for(ctx, a) for a in agents}
        entries = promote.plan(agents, records, cfg)
        if not entries:
            return
        base = max(promote.PROMOTED_ID_BASE, max(int(a["id"]) for a in agents) + 1)
        id_by_key = {(e["household_id"], e["key"]): base + i for i, e in enumerate(entries)}
        city_map = (getattr(ctx, "extras", None) or {}).get("city_map")
        assignment = ctx.plugin_state(self.id).get("assignment")
        new_agents = []
        for entry in entries:
            new_id = id_by_key[(entry["household_id"], entry["key"])]
            resident = promote.build_agent(entry, new_id)
            self._place(resident, entry["holders"][0], entry["kind"], city_map)
            new_agents.append((entry, resident))
        for entry, resident in new_agents:
            record = promote.own_record(entry, resident, id_by_key)
            ctx.agent_ext(resident, self.id).update(record)
            if assignment is not None:
                assignment.by_agent[int(resident["id"])] = self._record_for(ctx, resident)
        # Only now rewrite the holders' records: own_record read them as they
        # were sampled, ghosts and all.
        for entry, resident in new_agents:
            for holder in entry["holders"]:
                for member in self._record_for(ctx, holder).get("members") or []:
                    if str(member.get("key")) == entry["key"] and member.get("kind") != "agent":
                        member.update(kind="agent", agent_id=int(resident["id"]),
                                      key=str(resident["id"]))
        for _entry, resident in new_agents:
            agents.append(resident)
        ctx.set_agents(agents)
        for agent in agents:
            record = self._record_for(ctx, agent)
            if record.get("members"):
                agent["family"] = family_brief(record)
                agent.setdefault("family_today", "")
        children = sum(1 for e, _ in new_agents if e["kind"] == "child")
        print(f"👪 家人成为居民：{len(new_agents)} 人（子女 {children}，长辈 {len(new_agents) - children}）")

    def _place(self, resident, holder, kind, city_map):
        """Live at the household's home; a child's workplace is a school."""
        home = str((holder.get("locations") or {}).get("home", "") or "")
        workplace = home
        if kind == "child" and city_map is not None:
            try:
                from gaworld.sim._location import _infer_workplace

                workplace = _infer_workplace(resident, city_map, home_node=home) or home
            except Exception as exc:  # a placement must not stop the run
                _LOG.warning("school placement failed for %s: %s", resident.get("name"), exc)
        resident["locations"] = {
            "home": home, "workplace": workplace, "current": home, "destination": home,
            "in_transit": False, "transport_mode": "", "travel_minutes": 0,
            "travel_progress": 1.0, "travel_route": [home], "travel_congestion": 1.0,
            "travel_cost": 0.0, "rush_hour": False, "arrival_time": "",
            "frequent_places": {}, "preferred_modes": {},
            "commute_route": {"mode": "", "distance_km": 0.0, "avg_minutes": 0, "trip_count": 0},
            "daily_travel_cost": 0.0,
        }

    # -- ties ---------------------------------------------------------------

    def _wire_ties(self, hook_ctx):
        ctx = hook_ctx["sim"]
        day = int(hook_ctx.get("day", 1) or 1)
        for agent in hook_ctx.get("agents") or []:
            record = self._record_for(ctx, agent)
            members = record.get("members") or []
            if not members:
                continue
            apply_family_ties(agent, members, current_day=day)
            dropped = reconcile_ghost_kin(agent, members)
            if dropped:
                _LOG.debug("family: pruned contradicting ghosts %s for %s", dropped, agent.get("id"))
            # Names may have been reconciled against the off-screen roster
            # above, so the brief is rebuilt rather than reused.
            agent["family"] = family_brief(record)
            # A promoted child or elder is cared for; the duties are the adults'.
            agent["family_today"] = "" if record.get("dependant") else self._duty_text(
                record, day=day, ctx=ctx)
            self._publish_facts(agent, record)
            print(family_summary_line(str(agent.get("name", agent.get("id"))), record))
            # Recorded *here* rather than at `agents.built`: only now are the
            # member names reconciled against the off-screen roster, so this is
            # the first point where the row matches what the prompts will see.
            try:
                ctx.recorder.record(
                    "family.agent",
                    {
                        "agent_id": int(agent["id"]),
                        "name": str(agent.get("name", "")),
                        "age": agent.get("age"),
                        "gender": agent.get("gender", ""),
                        "household_id": record.get("household_id", ""),
                        "household_type": record.get("household_type", ""),
                        "marital_status": record.get("marital_status", ""),
                        "brief": agent["family"],
                        "members": members,
                        "care_load": round(care_load(record, getattr(ctx, "config", None)), 3),
                    },
                )
            except Exception as exc:
                _LOG.warning("family agent recording failed: %s", exc)

    # -- daily --------------------------------------------------------------

    def _duty_text(self, record, *, day, ctx) -> str:
        is_weekend = self._is_weekend(day)
        return duty_hint(record, day=day, is_weekend=is_weekend, config=getattr(ctx, "config", None))

    def _is_weekend(self, day) -> bool:
        """Weekend by the run's calendar, the same rule the main loop uses.

        This used to import ``_resolve_day_context`` from a module that does
        not define it and read config keys that do not exist, so it always
        fell back to "day 1 is a Monday" — whatever ``calendar`` said.
        """
        return _resolve_day_context(day, **self._calendar).get("day_type") == "weekend"

    def _enqueue_events(self, hook_ctx):
        """One shared life event per household per day, at most."""
        ctx = hook_ctx["sim"]
        if not self._cfg.get("events", {}).get("enabled", True):
            return
        day = int(hook_ctx.get("day", 1) or 1)
        assignment = ctx.plugin_state(self.id).get("assignment")
        if assignment is None:
            return
        agents_by_id = hook_ctx.get("agents_by_id") or {}
        try:
            from gaworld.events.life import add_life_event
        except ImportError:  # pragma: no cover - life events always ship
            return
        for household in assignment.households:
            in_sim = [aid for aid in household.agent_ids if aid in agents_by_id]
            if not in_sim:
                continue
            record = assignment.by_agent.get(in_sim[0])
            payload = family_events.sample_family_event(
                record, day=day, config=getattr(ctx, "config", None)
            )
            if not payload:
                continue
            payload.update(
                {
                    "schedule_mode": "scheduled",
                    # Every co-resident member gets the same event in the same
                    # tick — a family event is shared by construction.
                    "agent_ids": [int(aid) for aid in in_sim],
                    "created_by": "family",
                }
            )
            try:
                add_life_event(payload, getattr(ctx, "config", None))
            except Exception as exc:
                _LOG.warning("family event injection failed (%s): %s", household.id, exc)

    # -- perception ---------------------------------------------------------

    def _age_household(self, hook_ctx):
        """Age every household member, and let children grow up and move out.

        Household members carry an ``age`` that was written once at assignment
        and never touched again, so over a ten-year run a five-year-old stayed
        five and a seventy-year-old parent stayed seventy — the family was
        frozen while the resident aged around it. That is the family analogue
        of the agent-ageing gap, and it matters more here: care load, family
        duties and the household *type* are all read off these ages.

        A child crossing adulthood stops being co-resident (they move out),
        which is the one composition change that follows from ageing alone and
        needs no new mechanic. Marriage, births and bereavement are real
        changes too, but they are decisions and events rather than arithmetic,
        so they are not invented here.
        """
        try:
            span_days = max(1, int(hook_ctx.get("period_days") or 1))
        except (TypeError, ValueError):
            span_days = 1
        ctx = hook_ctx["sim"]
        day = hook_ctx.get("day")
        adult_age = 18
        for agent in hook_ctx.get("agents") or []:
            record = self._record_for(ctx, agent)
            members = record.get("members") or []
            if not members:
                continue
            carried = float(record.get("_member_age_days", 0.0)) + span_days
            years, carried = divmod(carried, 365.0)
            record["_member_age_days"] = carried
            if not years:
                continue
            moved_out = []
            for member in members:
                if not isinstance(member, dict):
                    continue
                try:
                    member_age = int(float(member.get("age") or 0))
                except (TypeError, ValueError):
                    continue
                if member_age <= 0:
                    continue
                member["age"] = member_age + int(years)
                if (
                    str(member.get("role", "")) == "child"
                    and member.get("coresident")
                    # An in-sim child has a home node and a schedule; moving
                    # them out takes more than a flag on this record.
                    and member.get("kind") != "agent"
                    and member_age < adult_age <= member["age"]
                ):
                    member["coresident"] = False
                    moved_out.append(str(member.get("name") or member.get("key") or "子女"))
            # The brief and duty text are read off the members, so they have
            # to be rebuilt or the prompts keep quoting the old ages.
            refresh_household_type(record)
            agent["family"] = family_brief(record)
            self._publish_facts(agent, record)
            if moved_out:
                text = (
                    f"[Household Day {day}] {agent.get('name', agent['id'])}: "
                    f"{'、'.join(moved_out)} 成年离家\n"
                )
                daily_logs = hook_ctx.get("daily_logs")
                if daily_logs is not None:
                    daily_logs[agent["id"]] += text
                print(text.strip())

    def _publish_facts(self, agent, record) -> None:
        """Expose the household as checkable facts, not only as prose.

        ``agent["family"]`` is an authored brief — right for a prompt, useless
        for "does this person have a partner?". Eligibility checks and the
        digest's action menu both need the latter.
        """
        try:
            agent["family_facts"] = family_facts(record)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("family facts failed for %s: %s", agent.get("id"), exc)

    def _apply_life_transition(self, hook_ctx):
        """Turn a family life event into an actual change of household.

        Without this a digest could report a marriage and the household would
        still say 单身 — the prose-versus-model gap these events exist to
        close. Eligibility is re-checked inside the transition, so an event
        injected from the dashboard cannot marry someone who already has a
        spouse either.

        Every in-sim resident of the household sees the change: a baby born to
        one partner of an in-sim couple is the other partner's child too, and a
        promoted child's sibling.
        """
        event = hook_ctx.get("life_event") or {}
        key = str(event.get("template_key", ""))
        if key not in TRANSITION_KEYS:
            return
        ctx = hook_ctx["sim"]
        agent = hook_ctx.get("agent") or {}
        day = int(hook_ctx.get("day") or 0)
        record = self._record_for(ctx, agent)
        if not record:
            return
        # Seeded per event, so the same run makes the same draws whatever
        # order the events arrive in.
        rng = random.Random(f"{self._seed}::{agent.get('id')}::{day}::{key}")
        if key in ("divorce", "separation"):
            change = self._split(ctx, agent, record, key, day, rng)
        else:
            peers = self._peers(ctx, agent, record)
            change = apply_transition(key, record, agent, day=day, rng=rng)
            if change:
                self._mirror(ctx, agent, record, key, change, peers, day)
        if not change:
            return
        self._refresh(ctx, agent, record, day, new_members=[change.get("member") or {}])
        member = change.get("member") or {}
        text = (
            f"[Household Day {day}] {agent.get('name', agent.get('id'))}: "
            f"{_VERBS[key]} — {member.get('name', '')}（{member.get('role', '')}）"
            f"，户类型 → {record.get('household_type')}"
            + (f"；{change['mover_name']} 搬到 {change['new_home']}" if change.get("mover_name") else "")
            + "\n"
        )
        daily_logs = hook_ctx.get("daily_logs")
        if daily_logs is not None:
            daily_logs[agent["id"]] = daily_logs.get(agent["id"], "") + text
        print(text.strip())

    # -- household-wide changes ---------------------------------------------

    def _peers(self, ctx, agent, record):
        """In-sim family who live with ``agent``, with their role in its record."""
        by_id = getattr(ctx, "agents_by_id", None) or {}
        out = []
        for member in record.get("members") or []:
            if member.get("kind") != "agent" or not member.get("coresident"):
                continue
            role = str(member.get("role", ""))
            if role == "roommate":
                continue
            try:
                peer = by_id.get(int(member.get("agent_id")))
            except (TypeError, ValueError):
                peer = None
            if peer is not None and peer is not agent:
                out.append((peer, role))
        return out

    def _mirror(self, ctx, agent, record, key, change, peers, day):
        """Carry a composition change into every co-resident resident's record."""
        member = change.get("member") or {}
        for peer, role in peers:
            peer_record = self._record_for(ctx, peer)
            if key == "bereavement":
                for theirs in peer_record.get("members") or []:
                    if str(theirs.get("key")) == str(member.get("key")):
                        theirs.update(coresident=False, deceased=True, deceased_day=int(day))
                if str(member.get("role")) in lifecycle.PARTNER_ROLES:
                    continue
            else:
                relative = _RELATIVE.get((key, role))
                if relative is None:
                    continue
                copy = dict(member, role=relative)
                if key == "marriage":
                    copy["note"] = "继父母" if relative == "parent" else "子女的配偶"
                peer_record.setdefault("members", []).append(copy)
            self._refresh(ctx, peer, peer_record, day, new_members=[] if key == "bereavement" else
                          [m for m in peer_record["members"] if m.get("key") == member.get("key")])

    def _refresh(self, ctx, agent, record, day, new_members=()):
        """Re-derive everything read off a record after it changed."""
        if record.get("dependant"):
            holder = next((p for p, _ in self._peers(ctx, agent, record)
                           if not self._record_for(ctx, p).get("dependant")), None)
            if holder is not None:
                record["household_type"] = self._record_for(ctx, holder).get("household_type", "")
        else:
            refresh_household_type(record)
        fresh = [m for m in new_members if m and m.get("key") and m.get("coresident", True)]
        if fresh:
            apply_family_ties(agent, fresh, current_day=day)
        agent["family"] = family_brief(record)
        self._publish_facts(agent, record)
        assignment = ctx.plugin_state(self.id).get("assignment")
        if assignment is not None:
            assignment.by_agent[int(agent["id"])] = record

    def _retire_tie(self, agent, key):
        """The partner's relationship record becomes an ex's."""
        rel = (agent.get("relationships") or {}).get(str(key))
        if not isinstance(rel, dict):
            return
        preset = TIE_PRESETS["ex"]
        rel["role"] = "ex"
        rel["coresident"] = False
        for field in ("closeness", "trust", "obligation"):
            rel[field] = min(float(rel.get(field, preset[field]) or 0.0), preset[field])
        rel["friction"] = max(float(rel.get("friction", 0.0) or 0.0), preset["friction"])

    def _split(self, ctx, agent, record, key, day, rng):
        """Divorce or separation. An in-sim couple stops sharing a home."""
        eligible = lifecycle.can_divorce if key == "divorce" else lifecycle.can_separate
        if not eligible(agent, record):
            return None
        partner = lifecycle.partner_of(record)
        by_id = getattr(ctx, "agents_by_id", None) or {}
        other = None
        if partner.get("kind") == "agent":
            try:
                other = by_id.get(int(partner.get("agent_id")))
            except (TypeError, ValueError):
                other = None
        if other is None:
            # Off-screen partner: they leave; promoted children stay here.
            dependants = [p for p, _ in self._peers(ctx, agent, record)]
            partner_key = str(partner.get("key"))
            change = lifecycle.split(record, agent, day=day, rng=rng)
            self._retire_tie(agent, partner_key)
            for dep in dependants:
                dep_record = self._record_for(ctx, dep)
                for theirs in dep_record.get("members") or []:
                    if str(theirs.get("key")) == partner_key:
                        theirs.update(coresident=False, note="父母分开后不同住")
                self._refresh(ctx, dep, dep_record, day)
            return change

        # In-sim couple: a seeded coin decides who moves out. Children and
        # co-resident elders stay at the old home with the other partner.
        other_record = self._record_for(ctx, other)
        if rng.random() < 0.5:
            mover, stayer, mover_rec, stayer_rec = agent, other, record, other_record
        else:
            mover, stayer, mover_rec, stayer_rec = other, agent, other_record, record
        dependants = [p for p, _ in self._peers(ctx, stayer, stayer_rec) if p is not mover]
        changes = {
            int(stayer["id"]): lifecycle.split(stayer_rec, stayer, day=day, rng=rng, keeps_children=True),
            int(mover["id"]): lifecycle.split(mover_rec, mover, day=day, rng=rng, keeps_children=False),
        }
        lifecycle.vacate(mover_rec)
        self._retire_tie(stayer, str(mover["id"]))
        self._retire_tie(mover, str(stayer["id"]))
        for dep in dependants:
            dep_record = self._record_for(ctx, dep)
            for theirs in dep_record.get("members") or []:
                if str(theirs.get("key")) == str(mover["id"]):
                    theirs.update(coresident=False, note="离异后搬出")
            rel = (dep.get("relationships") or {}).get(str(mover["id"]))
            if isinstance(rel, dict):
                rel["coresident"] = False
        for theirs in (mover.get("relationships") or {}).values():
            if isinstance(theirs, dict) and theirs.get("family"):
                theirs["coresident"] = False
        new_home = self._move_out(ctx, mover, mover_rec, day)
        for person, rec in ((stayer, stayer_rec), (mover, mover_rec)):
            if person is not agent:
                self._refresh(ctx, person, rec, day)
        for dep in dependants:
            self._refresh(ctx, dep, self._record_for(ctx, dep), day)
        change = changes[int(agent["id"])]
        if change:
            change["mover_name"] = str(mover.get("name", mover["id"]))
            change["new_home"] = new_home if new_home != stayer.get("locations", {}).get("home") \
                else "原地址（地图上没有别的住宅节点）"
        return change

    def _move_out(self, ctx, mover, mover_rec, day) -> str:
        """Give the partner who leaves a home of their own."""
        locations = mover.setdefault("locations", {})
        old_home = str(locations.get("home", "") or "")
        new_home = old_home
        city_map = (getattr(ctx, "extras", None) or {}).get("city_map")
        if city_map is not None and old_home:
            try:
                from gaworld.world.city_map import resolve_best_location

                for node, _km in resolve_best_location(
                    city_map, old_home, ["residential"], top_k=8, max_radius_km=20.0
                ):
                    if node != old_home:
                        new_home = node
                        break
            except Exception as exc:  # placement must not stop the run
                _LOG.warning("move-out placement failed for %s: %s", mover.get("name"), exc)
        locations["home"] = new_home
        assignment = ctx.plugin_state(self.id).get("assignment")
        if assignment is not None:
            mover_id = int(mover["id"])
            for household in assignment.households:
                if mover_id in household.agent_ids:
                    household.agent_ids.remove(mover_id)
                    split_off = Household(
                        id=f"{household.id}-d{day}", type=mover_rec.get("household_type", "single"),
                        agent_ids=[mover_id], district=household.district, home=new_home,
                    )
                    assignment.households.append(split_off)
                    mover_rec["household_id"] = split_off.id
                    break
        return new_home

    def _perception_section(self, hook_ctx):
        ctx = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        record = self._record_for(ctx, agent)
        if not record.get("members"):
            return None
        locations = agent.get("locations") or {}
        at_home = bool(locations.get("current")) and locations.get("current") == locations.get("home")
        section = family_section(record, at_home=at_home)
        if not section:
            return None
        duty = agent.get("family_today") or ""
        # Out of town, `at_home` is False and the duty line disappears on its
        # own — correct, but silent. Say it instead: the household did not stop
        # needing doing just because this member is away.
        trip = away.trip_of(agent)
        if trip:
            return section + "\n" + travel_itinerary.absence_line(trip)
        return section + ("\n" + duty if duty and at_home else "")

    # -- state --------------------------------------------------------------

    def _contagion(self, hook_ctx):
        ctx = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        record = self._record_for(ctx, agent)
        members = record.get("members") or []
        if not members:
            return
        agents_by_id = {int(a["id"]): a for a in (ctx.agents or []) if isinstance(a, dict)}
        peers = []
        coresident_ids: set[int] = set()
        for member in members:
            if member.get("kind") != "agent" or not member.get("agent_id"):
                continue
            peer = agents_by_id.get(int(member["agent_id"]))
            if peer is None:
                continue
            peers.append(peer)
            if member.get("coresident"):
                coresident_ids.add(int(member["agent_id"]))
        if not peers:
            return
        deltas = family_events.contagion_effects(
            agent,
            peers,
            coresident_ids=coresident_ids,
            config=getattr(ctx, "config", None),
        )
        state = agent.setdefault("state", {})
        for key, delta in deltas.items():
            if key not in state:
                continue
            try:
                state[key] = max(0.0, min(1.0, float(state[key]) + delta))
            except (TypeError, ValueError):
                continue

    # -- money --------------------------------------------------------------

    def _settle(self, hook_ctx):
        ctx = hook_ctx["sim"]
        day = int(hook_ctx.get("day", 1) or 1)
        assignment = ctx.plugin_state(self.id).get("assignment")
        if assignment is None:
            return
        agents_by_id = {int(a["id"]): a for a in (hook_ctx.get("agents") or []) if isinstance(a, dict)}

        if self._cfg.get("finance", {}).get("enabled", True):
            charge_fn = self._make_charge_fn(hook_ctx)
            for household in assignment.households:
                members = [agents_by_id[aid] for aid in household.agent_ids if aid in agents_by_id]
                if not members:
                    continue
                records = [
                    assignment.by_agent[aid]
                    for aid in household.agent_ids
                    if aid in assignment.by_agent
                ]
                charged = 0.0
                if charge_fn is not None:
                    charged = family_finance.charge_dependants(
                        members, records, charge_fn=charge_fn, config=getattr(ctx, "config", None)
                    )
                transferred = 0.0
                if len(members) >= 2:
                    transferred = family_finance.settle_couple(
                        members[0], members[1], getattr(ctx, "config", None)
                    )
                if charged or transferred:
                    try:
                        ctx.recorder.record(
                            "family.finance",
                            {
                                "household": household.id,
                                "dependant_cost": charged,
                                "partner_transfer": transferred,
                            },
                        )
                    except Exception as exc:
                        _LOG.debug("family finance recording failed: %s", exc)

            # Household economics as a slow tilt on state.
            for agent in agents_by_id.values():
                record = self._record_for(ctx, agent)
                if not record.get("members") or record.get("dependant"):
                    continue
                partner_earns = self._partner_earns(record, agents_by_id)
                effects = family_finance.household_state_effects(
                    record, partner_earns=partner_earns, config=getattr(ctx, "config", None)
                )
                state = agent.setdefault("state", {})
                for key, delta in effects.items():
                    if key in state:
                        try:
                            state[key] = max(0.0, min(1.0, float(state[key]) + float(delta)))
                        except (TypeError, ValueError):
                            continue

        # Tomorrow's duties, because daily routines are generated before
        # `on_day_start` fires.
        for agent in agents_by_id.values():
            record = self._record_for(ctx, agent)
            if record.get("members") and not record.get("dependant"):
                agent["family_today"] = self._duty_text(record, day=day + 1, ctx=ctx)

    def _partner_earns(self, record, agents_by_id) -> bool:
        for member in record.get("members", []) or []:
            if member.get("role") not in ("spouse", "partner") or not member.get("coresident"):
                continue
            if member.get("kind") == "agent":
                peer = agents_by_id.get(int(member.get("agent_id") or -1))
                econ = (peer or {}).get("economy") or {}
                try:
                    return float(econ.get("net_monthly_salary", 0) or 0) > 0
                except (TypeError, ValueError):
                    return False
            # Off-screen spouses of working age are assumed to earn; retired
            # ones are not. Cheap, but it is the only signal available.
            return 18 <= int(member.get("age", 0) or 0) <= 60
        return False

    def _make_charge_fn(self, hook_ctx):
        """Resolve the economy's public expense entry point, or ``None``."""
        try:
            from gaworld.economy.finance import charge_external_expense
        except ImportError:
            return None
        runtime = (hook_ctx.get("extension_state") or {}).get("economy_module") or {}
        if not runtime.get("enabled", False):
            return None

        def _charge(agent, category, amount):
            return charge_external_expense(agent, category, amount, hook_ctx)

        return _charge
