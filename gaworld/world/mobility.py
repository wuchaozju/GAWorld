"""Habitual transport mode: everyone has a usual way of getting around.

Mode choice used to be a pure function of the trip — two residents making
the same trip with the same ownership flags always took the same mode, and
one resident took whatever the distance ladder said on every single trip.
People do not travel like that. A retired teacher takes the bus, a courier
rides the e-bike everywhere, a driver drives; and now and then each of them
does something else — a taxi when late, a walk on a fine evening.

So each resident gets a **default mode**, decided once from their own
circumstances (:func:`assign_default_mode`), and each trip uses it when it
fits, with a small chance of an alternative (:func:`trip_mode`).

The default starts from the city's own mode model applied to the resident's
commute, so the level of each mode's share stays where that model put it;
personal circumstances then move individual residents:

* age — from ``ELDERLY_AGE`` a resident no longer drives or rides, and
  takes the bus (free for the elderly in most Chinese cities) or walks;
* job — couriers and delivery riders ride their e-bike, professional
  drivers drive;
* lifestyle stated in the profile — walking, cycling for exercise, a
  low-carbon habit.

Pure functions; the plugin in ``world/plugin.py`` applies them.
"""

from __future__ import annotations

from gaworld.world.city_map import (
    WEATHER_MODE_ADJUSTMENTS,
    _feasible_modes,
    distance_between,
    metro_is_usable,
)

#: Chinese names, for logs and prompts.
MODE_LABELS = {
    "walk": "步行",
    "bike": "自行车",
    "e-bike": "电动车",
    "bus": "公交",
    "metro": "地铁",
    "car": "开车",
    "taxi": "打车",
}

#: Age from which a resident no longer drives or rides as a matter of habit.
ELDERLY_AGE = 70
#: Trips shorter than this are walked whatever the habit — nobody drives
#: 300 m to the corner shop.
WALK_ANYWAY_KM = 0.5
#: Distance assumed for someone with no commute (retired, unemployed, at home):
#: their usual trip is an errand in the neighbourhood.
ERRAND_KM = 1.5
#: A weather weight below this makes an open-air habit give way to the model's
#: sheltered choice (same threshold the ladder uses for its weather upgrade).
WEATHER_GIVES_WAY = 0.6

_DELIVERY_JOBS = ("外卖", "快递", "骑手", "配送", "跑腿")
_DRIVER_JOBS = ("司机", "网约车", "出租", "代驾")
_WALKER_WORDS = ("散步", "步行", "慢生活")
_CYCLIST_WORDS = ("骑行", "骑车", "单车")
_GREEN_WORDS = ("环保", "低碳", "绿色出行")


def _age(agent) -> int:
    try:
        return int(agent.get("age") or 0)
    except (TypeError, ValueError):
        return 0


def _profile(agent) -> str:
    return " ".join(str(agent.get(k, "")) for k in ("job", "daily_life", "personality", "values"))


def feasible_modes(agent, distance_km, metro_ok):
    """Modes this resident could take for a trip of this length."""
    return _feasible_modes(agent, None, None, None, distance_km, metro_ok)


def _errand_mode(agent) -> str:
    """The usual mode of someone whose usual trip is a short errand."""
    return "e-bike" if agent.get("has_two_wheeler", True) else "walk"


def adjust_for_circumstances(agent, base_mode, distance_km, metro_ok) -> str:
    """Move *base_mode* where this resident's situation says otherwise."""
    feasible = feasible_modes(agent, distance_km, metro_ok)
    job = str(agent.get("job", ""))
    profile = _profile(agent)
    mode = base_mode

    if any(k in job for k in _DELIVERY_JOBS) and "e-bike" in feasible:
        mode = "e-bike"
    elif any(k in job for k in _DRIVER_JOBS) and "car" in feasible:
        mode = "car"
    elif any(k in profile for k in _WALKER_WORDS) and "walk" in feasible:
        mode = "walk"
    elif any(k in profile for k in _CYCLIST_WORDS) and "bike" in feasible:
        mode = "bike"
    elif any(k in profile for k in _GREEN_WORDS) and mode in ("car", "taxi"):
        mode = next((m for m in ("metro", "bus", "e-bike", "bike") if m in feasible), mode)

    if _age(agent) >= ELDERLY_AGE and mode in ("car", "e-bike", "bike"):
        mode = (
            "walk"
            if distance_km <= 1.2
            else next((m for m in ("bus", "metro", "taxi") if m in feasible), "walk")
        )
    return mode if mode in feasible else base_mode


def assign_default_mode(agent, city_map) -> str:
    """Decide this resident's usual mode and store it on the agent.

    Deterministic: the same resident in the same city gets the same habit on
    every start, so nothing has to be persisted.
    """
    from gaworld.world.city_map import choose_transport_mode

    locs = agent.get("locations", {}) or {}
    home = locs.get("home")
    work = locs.get("workplace")
    if home and work and work != home and distance_between(city_map, home, work) > 0:
        base, distance_km = choose_transport_mode(agent, city_map, home, work)
        metro_ok = metro_is_usable(city_map, home, work)
    else:
        base, distance_km, metro_ok = _errand_mode(agent), ERRAND_KM, False
    mode = adjust_for_circumstances(agent, base, distance_km, metro_ok)
    agent["default_transport"] = mode
    return mode


def trip_mode(agent, model_mode, distance_km, metro_ok, *, weather=None, deviation=0.0, rng=None):
    """The mode actually taken: the habit when it fits this trip, else the
    model's choice; with probability *deviation* some other feasible mode.

    Returns ``(mode, reason)`` with reason one of ``"habit"``, ``"model"``,
    ``"alternative"``.
    """
    habit = agent.get("default_transport")
    feasible = feasible_modes(agent, distance_km, metro_ok)
    adj = WEATHER_MODE_ADJUSTMENTS.get(str(weather or ""), {})

    chosen, reason = model_mode, "model"
    if habit in feasible and distance_km > WALK_ANYWAY_KM and float(adj.get(habit, 1.0)) >= WEATHER_GIVES_WAY:
        chosen, reason = habit, "habit"

    if rng is not None and deviation > 0 and distance_km > WALK_ANYWAY_KM and rng.random() < deviation:
        others = [m for m in feasible if m != chosen]
        if others:
            # Weather still shapes the odd choice: nobody "fancies a walk"
            # in a downpour as often as on a clear evening.
            weights = [max(0.05, float(adj.get(m, 1.0))) for m in others]
            chosen = rng.choices(others, weights=weights, k=1)[0]
            reason = "alternative"
    return chosen, reason


__all__ = [
    "ELDERLY_AGE",
    "MODE_LABELS",
    "adjust_for_circumstances",
    "assign_default_mode",
    "feasible_modes",
    "trip_mode",
]
