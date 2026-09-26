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

from typing import Any

from gaworld.family import events as family_events
from gaworld.family import finance as family_finance
from gaworld.family.assign import assign_households, pair_roommates
from gaworld.family.duties import care_load, duty_hint
from gaworld.family.lifecycle import apply_transition, family_facts, refresh_household_type
from gaworld.family.narrative import family_brief, family_section, family_summary_line
from gaworld.family.schema import family_config
from gaworld.family.ties import apply_family_ties, reconcile_ghost_kin
from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger
from gaworld.travel import itinerary as travel_itinerary
from gaworld.world import away

_LOG = get_logger("gaworld.family.plugin")


class FamilyPlugin(Plugin):
    id = "family"

    # Deliberately empty: family works without the economy or the life-event
    # queue, so declaring them here (which would disable the whole plugin
    # when one is absent) would trade a working feature for a strict edge.
    requires = ()

    def setup(self, ctx):
        self._cfg = family_config(getattr(ctx, "config", None))
        if not self._cfg.get("enabled", True):
            return
        ctx.bus.on("agents.built", self._build_households)
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
        assignment = assign_households(agents, getattr(ctx, "config", None))
        pair_roommates(assignment, agents, getattr(ctx, "config", None))
        state = ctx.plugin_state(self.id)
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
            agent["family_today"] = self._duty_text(record, day=day, ctx=ctx)
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
        is_weekend = self._is_weekend(day, ctx)
        return duty_hint(record, day=day, is_weekend=is_weekend, config=getattr(ctx, "config", None))

    def _is_weekend(self, day, ctx) -> bool:
        """Weekend detection mirroring ``_resolve_day_context``.

        Imported lazily and guarded: the day-context helper lives in the
        simulator module, and the family layer must not hard-depend on it.
        """
        try:
            from gaworld.sim._schedule import _resolve_day_context

            config = getattr(ctx, "config", {}) or {}
            context = _resolve_day_context(
                day,
                start_weekday_idx=int(config.get("sim_start_weekday_index", 0) or 0),
                weekend_indexes=tuple(config.get("sim_weekend_indexes", (5, 6)) or (5, 6)),
                start_date=config.get("sim_start_date"),
            )
            return context.get("day_type") == "weekend"
        except Exception:
            return (int(day or 1) % 7) in (6, 0)

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
        """
        event = hook_ctx.get("life_event") or {}
        key = str(event.get("template_key", ""))
        if key not in ("marriage", "childbirth", "bereavement"):
            return
        ctx = hook_ctx["sim"]
        agent = hook_ctx.get("agent") or {}
        day = int(hook_ctx.get("day") or 0)
        record = self._record_for(ctx, agent)
        if not record:
            return
        change = apply_transition(key, record, agent, day=day, rng=self._rng)
        if not change:
            return
        member = change.get("member") or {}
        agent["family"] = family_brief(record)
        self._publish_facts(agent, record)
        verb = {"marriage": "结婚", "childbirth": "添丁", "bereavement": "亲人离世"}[key]
        text = (
            f"[Household Day {day}] {agent.get('name', agent.get('id'))}: "
            f"{verb} — {member.get('name', '')}（{member.get('role', '')}）"
            f"，户类型 → {change.get('household_type')}\n"
        )
        daily_logs = hook_ctx.get("daily_logs")
        if daily_logs is not None:
            daily_logs[agent["id"]] = daily_logs.get(agent["id"], "") + text
        print(text.strip())

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
                if not record.get("members"):
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
            if record.get("members"):
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
