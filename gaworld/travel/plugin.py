"""TravelPlugin — residents leave the city and come back.

Three hooks, no changes to the main loop:

- ``on_day_start`` (observe): land whoever is due back, keep whoever is still
  away on a trip-shaped day, then decide who sets off today. The day-start
  payload already carries the mutable ``schedule_map``, so rewriting one
  agent's day is a dict assignment — the master timeline never moves.
- ``location.resolve`` (filter, lowest priority so nothing can undo it):
  blank the destination while away. ``move_agent`` then takes its
  ``target == origin`` branch and reports ``status: "stationary"`` — no
  displacement, no commute fare, and no road load, because ``TrafficPlugin``
  counts only ``arrived`` / ``departed`` / ``in_transit``.
- ``perception.compose`` (collect): tell the agent it is not in town. Without
  this the trip is invisible to the only part of the agent that matters.
- ``env.events.reach`` (filter): the city's weather and street events stop
  reaching someone who is away; its economy / politics / technology news
  does not.

Money: the round trip is billed once, at departure, through the economy's
public ``charge_external_expense`` entry point, so currency conservation
holds. Days away also carry a living surcharge — hotels and eating out. A
working day missed on a family visit or holiday is paid annual leave, up to
``paid_leave_days_per_year`` (``credit_paid_leave``); later ones are unpaid.

Cost (``compress_away_days``): a day away skips routine generation
(``day.routine.skip``) and the per-step cognition stages
(``step["_skip_stages"]``); one fast-forward day digest per agent per day
writes a memory and bounded state drift instead.

Off by default. Switching it on changes who is present in the city on any
given day, so earlier runs are not comparable.
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger
from gaworld.sim._utils import _resolve_day_context, calendar_from_config
from gaworld.travel import destination, itinerary, trigger
from gaworld.world import away

_LOG = get_logger("gaworld.travel.plugin")

#: A trip's destination is bounded by its length — a two-day business trip
#: does not cross the country. Kilometres allowed per day away.
KM_PER_DAY = 600.0

#: City environment events that need you to be here: weather and other
#: natural events, and street-level "social" ones (a jammed arterial, a
#: market day). Economic, political and technology news reaches anyone.
LOCAL_EVENT_TYPES = frozenset({"natural", "social"})

#: Per-step cognition a compressed day away skips — each is one or more LLM
#: calls. Movement, state update, memory bookkeeping and the step record still
#: run, so the ledger, the timeline and state history stay continuous.
AWAY_SKIPPED_STAGES = (
    "perceive", "interrupts", "plan", "adjust_activity", "select_action", "reflect",
)


class TravelPlugin(Plugin):
    """Business trips, family visits and holidays (see module docstring)."""

    id = "travel"

    def setup(self, ctx):
        cfg = ctx.config.get("travel", {}) or {}
        self._cfg = cfg
        self._calendar = calendar_from_config(ctx.config)
        self._enabled = bool(cfg.get("enabled", False))
        if not self._enabled:
            return
        self._seed = ctx.config.get("random_seed", None)
        if self._seed is None:
            self._seed = cfg.get("seed", 20260919)
        self._max_share = float(cfg.get("max_away_share", 0.15))
        self._fare_per_km = cfg.get("fare_per_km", {}) or {}
        self._daily_surcharge = float(cfg.get("daily_surcharge", 180.0))
        self._leave_days = int(cfg.get("paid_leave_days_per_year", 5))
        # The settings ship this on; a bare config (tests, embedding) leaves it
        # off so that nothing calls a model unasked.
        self._compress = bool(cfg.get("compress_away_days", False))
        # Organization commands must establish today's employer before leave
        # income is paid. Disabled organizations retain the original ordering.
        day_priority = -10 if (ctx.config.get("organizations") or {}).get("enabled", False) else 0
        ctx.bus.on("on_day_start", self._day_start, priority=day_priority)
        ctx.bus.on("env.events.reach", self._events_reach)
        if self._compress:
            ctx.bus.on("day.routine.skip", self._skip_routine)
            ctx.bus.on("on_agent_pre_step", self._skip_cognition)
        # Lowest priority: this runs after every other location filter, so a
        # redirect cannot quietly put an absent agent back on the map.
        ctx.bus.on("location.resolve", self._pin_away, priority=-50)
        # Priority 40 puts "you are not in this city" ahead of the local
        # physical line (30), which goes quiet while the agent is away.
        ctx.bus.on("perception.compose", self._perception_section, priority=40)

    # -- hooks ---------------------------------------------------------------

    def _pin_away(self, desired_location, hook_ctx):
        """Blank the destination for anyone out of town."""
        agent = hook_ctx.get("agent")
        if away.is_away(agent):
            return ""
        return None

    def _events_reach(self, events, hook_ctx):
        """Out of town, the city's weather and street events do not reach you.

        Its economic, political and technology news still does — and city
        policy (``policy_events``) never comes through here at all, so it keeps
        applying to residents wherever they are.
        """
        if not events or not away.trip_of(hook_ctx.get("agent")):
            return None
        return [ev for ev in events
                if not (isinstance(ev, dict) and str(ev.get("type", "")) in LOCAL_EVENT_TYPES)]

    def _skip_routine(self, value, hook_ctx):
        """No new routine for a day the trip will replace anyway."""
        trip = away.trip_of(hook_ctx.get("agent"))
        if trip and int(hook_ctx.get("day") or 0) <= int(trip.get("return_day", 0)):
            return True
        return None

    def _skip_cognition(self, hook_ctx):
        """Away, the itinerary is the plan: no per-step LLM deliberation."""
        agent, step = hook_ctx.get("agent"), hook_ctx.get("step")
        if not isinstance(step, dict) or not away.trip_of(agent):
            return
        activity = str(step.get("activity") or step.get("scheduled_activity") or "")
        step["_skip_stages"] = AWAY_SKIPPED_STAGES
        step.setdefault("_act", activity)
        step.setdefault("_effective_activity", activity)
        step.setdefault("_action_meta", {"decision_driver": "离城行程"})

    def _perception_section(self, hook_ctx):
        agent = hook_ctx["agent"]
        trip = away.trip_of(agent)
        if not trip:
            return None
        return itinerary.perception_line(trip, int(hook_ctx.get("day") or trip["depart_day"]))

    def _day_start(self, hook_ctx):
        day = int(hook_ctx.get("day", 1) or 1)
        agents = hook_ctx.get("agents") or []
        schedule_map = hook_ctx.get("schedule_map")
        city_map = hook_ctx.get("city_map")
        if not isinstance(schedule_map, dict):
            return
        is_weekend = self._is_weekend(day)

        # 1. Land anyone whose last day away was yesterday, and re-shape the
        #    day of anyone still out there.
        travelling = 0
        for agent in agents:
            trip = away.trip_of(agent)
            if not trip:
                continue
            if day > int(trip.get("return_day", day)):
                self._land(agent, trip, day, hook_ctx)
                continue
            travelling += 1
            agent.setdefault("locations", {})["current"] = away.away_label(trip.get("place"))
            self._leave(agent, trip, day, is_weekend, hook_ctx)
            schedule_map[agent["id"]] = itinerary.schedule_for(trip, day)
            self._charge(agent, "food", self._daily_surcharge, hook_ctx)

        # 2. Decide today's departures, up to the share cap. Agents are
        #    considered in list order, which is stable across runs — the cap
        #    must not depend on iteration order.
        cap = int(self._max_share * max(1, len(agents)))
        for agent in agents:
            if travelling >= cap:
                break
            if away.is_away(agent) or agent.get("family_dependant"):
                # Already on a trip, a real out-of-town position reported by
                # the digital twin (not ours to move), or a child / elder the
                # household looks after — they do not set off on their own.
                continue
            intent = trigger.decide(
                agent, day, is_weekend=is_weekend, cfg=self._cfg, seed=self._seed
            )
            if not intent:
                continue
            if self._depart(agent, intent, day, city_map, schedule_map, hook_ctx, is_weekend):
                travelling += 1

        # 3. One digest per agent away today stands in for the per-step
        #    cognition _skip_cognition switches off.
        if self._compress:
            for agent in agents:
                trip = away.trip_of(agent)
                if trip:
                    self._digest(agent, trip, day, hook_ctx)

    # -- trip lifecycle ------------------------------------------------------

    def _depart(self, agent, intent, day, city_map, schedule_map, hook_ctx, is_weekend) -> bool:
        days = max(1, int(intent.get("days", 2)))
        place, km = destination.pick(
            city_map,
            trigger.rng_for(self._seed, agent.get("id"), day, "destination"),
            prefer=intent.get("tie_city", ""),
            max_km=KM_PER_DAY * days,
        )
        if not place:
            return False
        leg = destination.journey(km, self._fare_per_km)
        trip = {
            "status": "away",
            "purpose": intent["purpose"],
            "place": place,
            "distance_km": km,
            "mode": leg["mode"],
            "hours": leg["hours"],
            "fare": leg["fare"],
            # The node to come back to. Never re-derived from the away label:
            # `shortest_path_with_distance` answers ([], 0.0) for an unknown
            # origin, which would make the journey home free and instant.
            "home_node": str(agent.get("locations", {}).get("home", "")),
            "depart_day": day,
            "return_day": day + days - 1,
            "tie_key": intent.get("tie_key", ""),
            "tie_name": intent.get("tie_name", ""),
        }
        agent.setdefault("ext", {})["travel"] = trip
        agent.setdefault("locations", {})["current"] = away.away_label(place)
        self._leave(agent, trip, day, is_weekend, hook_ctx)
        schedule_map[agent["id"]] = itinerary.schedule_for(trip, day)
        # Booked as a return ticket, like a real one.
        self._charge(agent, "transport", leg["fare"] * 2.0, hook_ctx)
        self._note(
            hook_ctx,
            agent,
            f"[Travel Day {day}] 出发去{place}"
            f"（{itinerary.PURPOSE_ZH.get(trip['purpose'], '外出')}，"
            f"{days} 天，{km:.0f} km，{itinerary.MODE_ZH.get(leg['mode'], '')}）\n",
        )
        self._record(hook_ctx, "travel.depart", agent, trip)
        return True

    def _land(self, agent, trip, day, hook_ctx):
        """Back in the city: restore the map position and close the trip."""
        home = away.home_node_of(agent)
        locations = agent.setdefault("locations", {})
        if home:
            locations["current"] = home
            locations["destination"] = home
            locations["travel_route"] = [home]
        locations["in_transit"] = False
        locations["travel_progress"] = 1.0
        agent.get("ext", {}).pop("travel", None)
        self._settle_visit(agent, trip, day)
        self._note(
            hook_ctx,
            agent,
            f"[Travel Day {day}] 从{trip.get('place', '外地')}回到本市\n",
        )
        self._record(hook_ctx, "travel.return", agent, trip)

    def _settle_visit(self, agent, trip, day):
        """A visit that actually happened resets the tie it was made for.

        This is the point of the family trigger: ``decay_relationships`` raises
        obligation on a neglected tie every day and nothing could ever spend
        it. Going resets ``last_contact_day``, which lets it fall again.
        """
        key = str(trip.get("tie_key", "") or "")
        if not key:
            return
        rel = (agent.get("relationships") or {}).get(key)
        if not isinstance(rel, dict):
            return
        rel["last_contact_day"] = int(day)
        rel["closeness"] = min(1.0, float(rel.get("closeness", 0.5) or 0.5) + 0.08)
        rel["obligation"] = max(0.0, float(rel.get("obligation", 0.5) or 0.5) - 0.25)

    def _leave(self, agent, trip, day, is_weekend, hook_ctx):
        """A working day missed on a family visit or holiday is annual leave.

        Business trips are work (their days stay income activities), and
        weekends are not leave.
        """
        if is_weekend or trip.get("purpose") == "business":
            return
        runtime = (hook_ctx.get("extension_state") or {}).get("economy_module") or {}
        if not runtime.get("enabled", False):
            return
        from gaworld.economy.finance import credit_paid_leave

        record = credit_paid_leave(agent, hook_ctx, day=day, days_per_year=self._leave_days)
        if not record:
            return
        if record["type"] == "paid_leave":
            text = (f"带薪年假（今年第 {record['days_used']}/{record['allowance']} 天，"
                    f"{record['pay']:.0f} 元）")
        else:
            text = f"无薪假（今年的 {record['allowance']} 天年假已用完）"
        self._note(hook_ctx, agent, f"[Travel Day {day}] {text}\n")

    def _digest(self, agent, trip, day, hook_ctx):
        """One fast-forward day digest: a memory and bounded state drift.

        The same call the month/year fast-forward makes per day, fed the
        itinerary as the day's schedule and the "you are not in town" line as
        the day's description. Neighbours are left out: nobody from the city
        is there.
        """
        from gaworld.llm import providers
        from gaworld.sim import _diary
        from gaworld.sim._fastforward import (
            apply_state_changes,
            max_state_delta_for,
            simulate_agent_day,
        )

        config = hook_ctx.get("config")
        digest = simulate_agent_day(
            agent,
            day=day,
            day_desc=itinerary.perception_line(trip, day),
            base_schedule=itinerary.schedule_for(trip, day),
            config=config,
            llm_fn=providers.call_llm,
            rng=trigger.rng_for(self._seed, agent.get("id"), day, "digest"),
        )
        apply_state_changes(
            agent, digest.get("state_changes", {}), max_delta=max_state_delta_for("day", config)
        )
        for line in digest.get("memories") or [digest.get("memory", "")]:
            text = str(line or "").strip()
            if text:
                _diary._append_memory_record(
                    agent, text, entry_type="memory", day=day, time_str="travel_digest"
                )
        brief = str(digest.get("brief", "")).strip() or "（在外的一天）"
        mark = "⚠️ [占位·模型未产出] " if digest.get("fallback") else ""
        self._note(hook_ctx, agent, f"[Travel Day {day}] {mark}{brief}\n")

    # -- plumbing ------------------------------------------------------------

    def _charge(self, agent, category, amount, hook_ctx):
        """Book a conserving expense, when there is an economy to book it in."""
        runtime = (hook_ctx.get("extension_state") or {}).get("economy_module") or {}
        if not runtime.get("enabled", False):
            return 0.0
        try:
            from gaworld.economy.finance import charge_external_expense
        except ImportError:
            return 0.0
        return charge_external_expense(agent, category, amount, hook_ctx)

    def _note(self, hook_ctx, agent, text):
        logs = hook_ctx.get("daily_logs")
        if isinstance(logs, dict):
            try:
                logs[agent["id"]] += text
            except (KeyError, TypeError):
                pass

    def _record(self, hook_ctx, table, agent, trip):
        sim = hook_ctx.get("sim")
        recorder = getattr(sim, "recorder", None)
        if recorder is None:
            return
        try:
            recorder.record(table, {"agent_id": agent.get("id"), **trip})
        except Exception as exc:  # noqa: BLE001 — recording must never break a day
            _LOG.debug("travel recording failed: %s", exc)

    def _is_weekend(self, day) -> bool:
        """Weekend by the run's calendar, the same rule the main loop uses.

        This used to import ``_resolve_day_context`` from a module that does
        not define it and read config keys that do not exist, so it always
        fell back to "day 1 is a Monday" — whatever ``calendar`` said.
        """
        return _resolve_day_context(day, **self._calendar).get("day_type") == "weekend"
