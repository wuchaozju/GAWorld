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

Money: the round trip is billed once, at departure, through the economy's
public ``charge_external_expense`` entry point, so currency conservation
holds. Days away also carry a living surcharge — hotels and eating out.

Off by default. Switching it on changes who is present in the city on any
given day, so earlier runs are not comparable.
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger
from gaworld.travel import destination, itinerary, trigger
from gaworld.world import away

_LOG = get_logger("gaworld.travel.plugin")

#: A trip's destination is bounded by its length — a two-day business trip
#: does not cross the country. Kilometres allowed per day away.
KM_PER_DAY = 600.0


class TravelPlugin(Plugin):
    """Business trips, family visits and holidays (see module docstring)."""

    id = "travel"

    def setup(self, ctx):
        cfg = ctx.config.get("travel", {}) or {}
        self._cfg = cfg
        self._enabled = bool(cfg.get("enabled", False))
        if not self._enabled:
            return
        self._seed = ctx.config.get("random_seed", None)
        if self._seed is None:
            self._seed = cfg.get("seed", 20260919)
        self._max_share = float(cfg.get("max_away_share", 0.15))
        self._fare_per_km = cfg.get("fare_per_km", {}) or {}
        self._daily_surcharge = float(cfg.get("daily_surcharge", 180.0))
        ctx.bus.on("on_day_start", self._day_start)
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
        is_weekend = self._is_weekend(day, hook_ctx.get("sim"))

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
            schedule_map[agent["id"]] = itinerary.schedule_for(trip, day)
            self._charge(agent, "food", self._daily_surcharge, hook_ctx)

        # 2. Decide today's departures, up to the share cap. Agents are
        #    considered in list order, which is stable across runs — the cap
        #    must not depend on iteration order.
        cap = int(self._max_share * max(1, len(agents)))
        for agent in agents:
            if travelling >= cap:
                break
            if away.is_away(agent):
                # Either already on a trip, or a real out-of-town position
                # reported by the digital twin — which is not ours to move.
                continue
            intent = trigger.decide(
                agent, day, is_weekend=is_weekend, cfg=self._cfg, seed=self._seed
            )
            if not intent:
                continue
            if self._depart(agent, intent, day, city_map, schedule_map, hook_ctx):
                travelling += 1

    # -- trip lifecycle ------------------------------------------------------

    def _depart(self, agent, intent, day, city_map, schedule_map, hook_ctx) -> bool:
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

    def _is_weekend(self, day, sim) -> bool:
        """Weekend detection mirroring ``_resolve_day_context``.

        Imported lazily and guarded, for the same reason the family layer does
        it: the day-context helper lives in the simulator module and this
        package must not hard-depend on it.
        """
        try:
            from gaworld.sim._schedule import _resolve_day_context

            config = getattr(sim, "config", {}) or {}
            context = _resolve_day_context(
                day,
                start_weekday_idx=int(config.get("sim_start_weekday_index", 0) or 0),
                weekend_indexes=tuple(config.get("sim_weekend_indexes", (5, 6)) or (5, 6)),
                start_date=config.get("sim_start_date"),
            )
            return context.get("day_type") == "weekend"
        except Exception:  # noqa: BLE001 — degrade to the arithmetic fallback
            return (int(day or 1) % 7) in (6, 0)
