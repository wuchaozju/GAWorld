"""Dashboard backend for 同居模式 (Roommate Mode), the playground's tenth game.

Pick 2–6 residents, give them a one-line apartment vibe (the player writes it,
the game does not), and watch them live together. The game is the playground's
first *long-lived* one: the others answer in a few seconds, finish, and yield a
result. A roommate session keeps running: every "tick" of virtual time the
residents pick something to do, bump into each other in rooms, and (sometimes)
talk — the play observes rather than plays, and the model is only called when
something interesting actually happens, so the cost stays bounded.

Five things worth knowing before reading the code:

* **Apartment is fixed; residents are the variable.** The floor plan is a
  constant — kitchen, living room, master bedroom, second bedroom, study,
  bathroom, balcony — so the player can draw it once and read it every time.
  Residents are randomly assigned to bedrooms; the rest of the apartment is
  shared.
* **Activity drives co-presence.** Each resident has an ``activity`` and a
  ``location``; two residents in the same room for two consecutive ticks
  *may* spark an interaction, with a probability scaled by their personality
  affinity. An activity like "cook" raises the probability; "study alone"
  lowers it. The model is called for the interaction; idle ticks cost nothing.
* **One model call per interaction, structured JSON.** The prompt asks for a
  short dialogue line, an inner thought, a mood delta, and a relationship
  delta with whoever triggered it. ``first_json_object`` and a tiny
  post-processor turn whatever the model says into a row in the event log;
  no judge call is needed because every dial is what the model reports.
* **Time is virtual, accelerated.** ``tick_minutes = 5`` by default. The
  session clock is ``now - session_started`` advanced in 5-minute hops; the
  player sees a clock on the dashboard that ticks as the page polls.
  ``tick()`` is exposed so the front-end controls pacing (1x / 2x / pause).
* **Everything stays in memory.** A roommate session lives in a dict, like a
  persuasion session, and the city bundle is never written back. Reloading
  the dashboard loses the room; a player who wants persistence uses the
  Markdown export.

Conventions follow :mod:`gaworld.apps.games_api` and
:mod:`gaworld.apps.competence_api`: a long-lived in-memory session, an
``ownership`` stamp for accounts mode, and every LLM entry point injectable
(``reaction_fn=``) so tests never touch a provider. Nothing here writes to a
city bundle — a game is a sandbox, not a simulation run.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.games_api import first_json_object, load_persona, persona_block
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.roommate_api")

#: A small pool for the *interaction* model calls. Interactions can take
#: several seconds each, and the front-end ticks every 250 ms — running
#: them synchronously would block ``tick()`` and stall the dashboard. Each
#: pending call is dispatched here; the worker thread appends the resulting
#: :class:`Event` to the session's event log when the model replies (or
#: silently drops it on failure).
_INTERACTION_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="roommate")
_INTERACTION_LOCK = threading.Lock()
_PENDING_FUTURES: list[Future[Any]] = []

#: How long a single model call may hang before we cut it off and surface
#: a placeholder event. Most providers return in under 30 s; we give 90 s
#: of slack for slow local models, but never wait longer — a hung call
#: would otherwise stall the event log indefinitely (the player sees no
#: bubbles, no relationship updates, just endless movement).
_INTERACTION_TIMEOUT = 90.0

#: Generic placeholder content used when the model call times out. It is
#: not a real conversation — the dashboard marks it as a *fallback* so the
#: player can tell, and the mood / relationship deltas are zero so it does
#: not poison the simulation.
_FALLBACK_DIALOGUE = "{a}:…\n{b}:…"
_FALLBACK_THOUGHT = "{a}:(在想要说什么)\n{b}:(在想要说什么)"


def _gc_pending_futures() -> None:
    """Drop finished futures so the list does not grow without bound."""
    with _INTERACTION_LOCK:
        kept = [f for f in _PENDING_FUTURES if not f.done()]
        _PENDING_FUTURES.clear()
        _PENDING_FUTURES.extend(kept)


def _cancel_stale_futures() -> None:
    """Cancel any interaction that has been running past
    ``_INTERACTION_TIMEOUT``. ``add_done_callback`` will then run on the
    cancel path and emit a fallback event."""
    cutoff = time.time() - _INTERACTION_TIMEOUT
    with _INTERACTION_LOCK:
        alive = []
        for fut in _PENDING_FUTURES:
            if fut.done():
                continue
            submitted = getattr(fut, "_submit_time", None) or cutoff
            if submitted < cutoff:
                fut.cancel()
            else:
                alive.append(fut)
        _PENDING_FUTURES.clear()
        _PENDING_FUTURES.extend(alive)


def _maybe_emit_fallback(
    session_id: str,
    a_id: int,
    b_id: int,
    room: str,
    tick_idx: int,
    fut: Future[Any],
) -> None:
    """Callback run when an interaction future resolves. If the worker
    failed (exception or cancellation), or if it hung past the deadline
    and got cancelled, drop a placeholder event so the dashboard still
    shows *something*. The fallback marks the event with ``note="fallback"``
    so the renderer can render it as dimmer / without bubble content."""
    try:
        exc = fut.exception()
    except Exception:
        exc = None
    cancelled = fut.cancelled()
    # If the worker succeeded, ``_run_interaction_worker`` already wrote
    # the real event. Check the session's events to see whether this
    # interaction is already there — if so, do not double-write.
    try:
        session = _require(session_id)
    except KeyError:
        return
    already = any(
        e.actor_ids == [a_id, b_id] and e.tick == tick_idx and e.kind == "interact"
        for e in session.events
    )
    if already and not cancelled and exc is None:
        return
    a = next((r for r in session.residents if r.agent_id == a_id), None)
    b = next((r for r in session.residents if r.agent_id == b_id), None)
    if a is None or b is None:
        return
    event = Event(
        seq=0,
        tick=tick_idx,
        at=time.time(),
        kind="interact",
        actor_ids=[a_id, b_id],
        room=room,
        dialogue=_FALLBACK_DIALOGUE.format(a=a.name, b=b.name),
        thought=_FALLBACK_THOUGHT.format(a=a.name, b=b.name),
        mood_delta=0.0,
        relationship_delta={str(b_id): 0.0, str(a_id): 0.0},
        note="fallback",
    )
    _append_event(session, event)

#: Residents in one session. Two is "roommates", six is "a share house".
MIN_AGENTS = 2
MAX_AGENTS = 6

#: Virtual minutes per tick. 5 minutes keeps dialogue density believable
#: (you don't talk to your roommate every five minutes of real time, but you
#: do talk to them every five minutes of *interesting* time).
DEFAULT_TICK_MINUTES = 5

#: A session goes on for this many virtual hours before it stops generating
#: new events on its own. The player can end it sooner; the budget is here so
#: a forgotten session doesn't leak forever. ``24`` is one full day — long
#: enough to see the night-cycle (lights dim, residents head home) without
#: leaving a runaway session on the dashboard.
DEFAULT_MAX_HOURS = 24

#: Wall-clock hour at which residents get nudged towards their bedrooms
#: and the apartment's lights dim. ``22`` is the natural "good night" beat.
NIGHT_HOUR = 22
#: Wall-clock hour at which the apartment wakes up again. ``6`` is a soft
# dawn — light returns, residents start moving.
DAWN_HOUR = 6

#: How many ticks the simulation may advance on a single ``tick`` call from
#: the front-end. Larger values let the player fast-forward without
#: flooding the page; smaller values let them see a per-tick board.
MAX_TICKS_PER_REQUEST = 6

#: Resident activity vocabulary. Picked each tick based on the resident's
#: role + a small randomness; an activity is always paired with a room.
ACTIVITIES: tuple[str, ...] = (
    "做早餐",
    "吃早餐",
    "看书",
    "写日记",
    "处理工作邮件",
    "打电话",
    "刷短视频",
    "打扫房间",
    "做午餐",
    "吃午餐",
    "午睡",
    "健身",
    "练琴",
    "画一会儿画",
    "发呆",
    "下楼散步",
    "打电话给家人",
    "洗衣服",
    "晾衣服",
    "做晚餐",
    "吃晚餐",
    "追剧",
    "看窗外",
    "跟宠物玩",
    "泡茶",
    "洗澡",
    "睡前阅读",
)

#: Room catalogue. The floor plan is the same in every session so the SVG on
#: the front-end can be hand-drawn once.
ROOMS: tuple[dict[str, Any], ...] = (
    {"id": "kitchen", "label": "厨房", "x": 60, "y": 60, "w": 160, "h": 110},
    {"id": "living", "label": "客厅", "x": 230, "y": 60, "w": 200, "h": 140},
    {"id": "master", "label": "主卧", "x": 440, "y": 60, "w": 150, "h": 130},
    {"id": "second", "label": "次卧", "x": 600, "y": 60, "w": 130, "h": 130},
    {"id": "study", "label": "书房", "x": 60, "y": 190, "w": 130, "h": 120},
    {"id": "bath", "label": "卫生间", "x": 200, "y": 190, "w": 110, "h": 90},
    {"id": "balcony", "label": "阳台", "x": 320, "y": 210, "w": 110, "h": 100},
    {"id": "hallway", "label": "走廊", "x": 440, "y": 200, "w": 290, "h": 110},
)

#: Rooms a resident can be assigned to sleep in. The master bedroom is
#: reserved for the eldest or first picked; the rest get one of the seconds.
SLEEP_ROOMS: tuple[str, ...] = ("master", "second")

#: Activity → room mapping. The simulation picks an activity first, then
#: routes it to the matching room. Activities not in this dict fall back to
#: the living room so the resident is never "nowhere".
ACTIVITY_ROOM: dict[str, str] = {
    "做早餐": "kitchen", "吃早餐": "kitchen",
    "做午餐": "kitchen", "吃午餐": "kitchen",
    "做晚餐": "kitchen", "吃晚餐": "kitchen",
    "看书": "study", "写日记": "study", "处理工作邮件": "study",
    "练琴": "study", "画一会儿画": "study",
    "刷短视频": "living", "打电话": "living", "看电视": "living", "追剧": "living",
    "健身": "living", "跟宠物玩": "living",
    "打电话给家人": "living",
    "午睡": "master", "睡前阅读": "master", "发呆": "master", "看窗外": "master",
    "洗澡": "bath", "洗衣服": "bath",
    "晾衣服": "balcony", "下楼散步": "balcony", "泡茶": "kitchen",
    "打扫房间": "living",
}

#: Activities that hint "I am busy / in my own world" — used to dampen
#: the probability of an interaction when two residents meet in a room.
SOLO_ACTIVITIES: frozenset[str] = frozenset({
    "看书", "写日记", "处理工作邮件", "练琴", "画一会儿画",
    "午睡", "睡前阅读", "发呆", "洗澡",
})

#: Mood label thresholds. The continuous -1..+1 score is bucketed so the
#: dashboard can show a coloured chip without a chart library.
MOOD_LABELS: tuple[tuple[float, str], ...] = (
    (0.6, "兴高采烈"),
    (0.2, "心情不错"),
    (-0.2, "平平淡淡"),
    (-0.6, "有点低落"),
    (-1.1, "情绪崩溃"),
)

#: A resident's mood drifts toward 0 over time even when nothing happens,
#: so a great first hour doesn't stay great forever.
MOOD_DECAY_PER_TICK = 0.05

#: Relationship score: -100 (actively dislike) .. +100 (best friends). One
#: interaction nudges it by a small amount; the model is asked for a delta.
RELATIONSHIP_DECAY_PER_TICK = 1.0

#: Probability a co-present pair triggers an interaction in a given tick,
#: after activity adjustment. Two busy residents rarely talk; two idle ones
#: in the kitchen usually do.
BASE_INTERACTION_PROB = 0.55

#: Maximum events kept in the dashboard board. Older events fall off the
#: end; the simulation history is not capped (the player can export it).
MAX_EVENTS = 200

#: How much of the profile goes into the persona block. Big enough for
#: personality + voice + values, small enough that a six-person session
#: still fits two of them in one prompt.
PERSONA_CHARS = 1100

_VOICE_RULES = (
    "用第一人称说话,像真人微信聊天一样。不要扮演助手,不要说「作为一个 AI」,"
    "不要罗列要点,不要复述对方的话。"
)


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_reaction_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.roommate", temperature=0.8)


# ---------------------------------------------------------------------------
# Resident + session state
# ---------------------------------------------------------------------------


@dataclass
class Resident:
    """One resident in the apartment."""

    agent_id: int
    name: str
    age: int
    gender: str
    job: str
    profile_md: str
    #: Room id from :data:`ROOMS`. ``None`` until the session starts.
    bedroom: str | None = None
    #: What they are doing *this* tick.
    activity: str = ""
    #: Where they are *this* tick.
    room: str = "living"
    #: -1 (崩溃) .. +1 (兴高采烈), bucketed by :data:`MOOD_LABELS`.
    mood: float = 0.0
    #: Avatar emoji chosen for the dashboard tile.
    emoji: str = "🙂"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "age": self.age,
            "gender": self.gender,
            "job": self.job,
            "bedroom": self.bedroom,
            "activity": self.activity,
            "room": self.room,
            "mood": round(self.mood, 2),
            "mood_label": _mood_label(self.mood),
            "emoji": self.emoji,
        }


@dataclass
class Event:
    """One row in the event stream."""

    seq: int
    tick: int
    at: float  # wall clock when it was generated
    kind: str  # "interact" | "alone" | "move" | "scene" | "direct"
    actor_ids: list[int] = field(default_factory=list)
    room: str = ""
    dialogue: str = ""
    thought: str = ""
    #: Ordered list of {"who": name, "text": "..."} so the front-end can
    #: play a turn-by-turn bubble instead of splitting a packed ``dialogue``
    #: string by line. Populated for ``interact`` and ``direct`` events.
    turns: list[dict[str, str]] = field(default_factory=list)
    mood_delta: float = 0.0
    relationship_delta: dict[str, float] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tick": self.tick,
            "at": self.at,
            "kind": self.kind,
            "actor_ids": list(self.actor_ids),
            "room": self.room,
            "dialogue": self.dialogue,
            "thought": self.thought,
            "turns": [{"who": t.get("who", ""), "text": t.get("text", "")} for t in (self.turns or [])],
            "mood_delta": round(self.mood_delta, 2),
            "relationship_delta": {str(k): round(float(v), 2) for k, v in self.relationship_delta.items()},
            "note": self.note,
        }


@dataclass
class RoommateSession:
    id: str
    city: str
    vibe: str
    residents: list[Resident]
    tick_minutes: int
    max_hours: int
    tick_index: int = 0
    virtual_clock_minutes: int = 8 * 60  # session starts at 08:00 in the morning
    #: The clock at which the session was opened — the deadline is anchored
    #: to *this*, not re-derived on every ``tick`` call, so the deadline does
    #: not drift forward each time the front-end advances the simulation.
    opening_clock_minutes: int = 8 * 60
    events: list[Event] = field(default_factory=list)
    #: relationship[other_id] = -100..+100; stored bidirectionally.
    relationships: dict[int, dict[int, float]] = field(default_factory=dict)
    #: ``True`` while the simulation may still advance. The front-end toggles
    #: this for its play/pause control; the server also flips it off when the
    #: virtual clock passes ``max_hours``.
    running: bool = True
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    #: Increments per ``Event`` so the front-end can detect a new row without
    #: diffing lists.
    last_seq: int = 0
    owner_id: int | None = field(default_factory=lambda: ownership.stamp().get("owner_id"))

    @property
    def settled(self) -> bool:
        return self.finished_at is not None

    def to_dict(self) -> dict[str, Any]:
        clock_hour = (self.virtual_clock_minutes // 60) % 24
        is_night = clock_hour >= NIGHT_HOUR or clock_hour < DAWN_HOUR
        # ``night_progress`` ramps from 0 (no night) to 1 (full night) so
        # the canvas can smoothly fade the apartment between day and night
        # without snapping at the boundary.
        if is_night:
            if clock_hour >= NIGHT_HOUR:
                ramp = (clock_hour - NIGHT_HOUR + self.virtual_clock_minutes % 60 / 60) / 4
            else:
                ramp = ((24 - NIGHT_HOUR) + clock_hour + self.virtual_clock_minutes % 60 / 60) / 4
            night_progress = max(0.0, min(1.0, ramp))
        else:
            ramp = (clock_hour - DAWN_HOUR + self.virtual_clock_minutes % 60 / 60) / (NIGHT_HOUR - DAWN_HOUR)
            night_progress = max(0.0, min(1.0, 1 - ramp))
        return {
            "id": self.id,
            "city": self.city,
            "vibe": self.vibe,
            "tick_index": self.tick_index,
            "tick_minutes": self.tick_minutes,
            "max_hours": self.max_hours,
            "virtual_clock_minutes": self.virtual_clock_minutes,
            "virtual_clock": _format_clock(self.virtual_clock_minutes),
            "is_night": is_night,
            "night_progress": night_progress,
            "running": self.running,
            "finished": self.settled,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "last_seq": self.last_seq,
            "residents": [r.to_dict() for r in self.residents],
            "events": [e.to_dict() for e in self.events[-MAX_EVENTS:]],
            "events_truncated": len(self.events) > MAX_EVENTS,
            "relationships": {
                str(a): {str(b): round(v, 2) for b, v in pairs.items()}
                for a, pairs in self.relationships.items()
            },
            "rooms": list(ROOMS),
        }


_SESSIONS: dict[str, RoommateSession] = {}
_SESSIONS_LOCK = threading.Lock()


def reset_sessions() -> None:
    """Drop every session. Used by tests; production code never calls it."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


# ---------------------------------------------------------------------------
# Persona loading
# ---------------------------------------------------------------------------


def _avatar_for(agent_id: int, gender: str) -> str:
    """Pick a fixed emoji per resident so the dashboard tile is stable."""
    pool_neutral = ("🙂", "😄", "🧐", "🤓", "😊", "🥰", "😎", "🤔", "🫶", "🌟")
    pool_female = ("👩", "👧", "👩‍🦰", "👩‍🦱", "🧑‍🎤", "👩‍🍳", "👩‍🎓")
    pool_male = ("👨", "👦", "👨‍🦰", "👨‍🦱", "🧑‍🎤", "👨‍🍳", "👨‍🎓")
    g = (gender or "").strip()
    if g in {"女", "F", "female"}:
        pool = pool_female
    elif g in {"男", "M", "male"}:
        pool = pool_male
    else:
        pool = pool_neutral
    return pool[agent_id % len(pool)]


def _load_residents(city: str, agent_ids: list[int]) -> list[Resident]:
    residents: list[Resident] = []
    for agent_id in agent_ids:
        persona = load_persona(city, agent_id)
        residents.append(Resident(
            agent_id=int(agent_id),
            name=str(persona.get("name") or f"#{agent_id}"),
            age=int(persona.get("age") or 0),
            gender=str(persona.get("gender") or ""),
            job=str(persona.get("job") or ""),
            profile_md=str(persona.get("profile_md") or ""),
            emoji=_avatar_for(int(agent_id), str(persona.get("gender") or "")),
        ))
    return residents


def _assign_bedrooms(residents: list[Resident]) -> None:
    """First resident gets the master; the others get the second bedroom."""
    if not residents:
        return
    residents[0].bedroom = SLEEP_ROOMS[0]
    for r in residents[1:]:
        r.bedroom = SLEEP_ROOMS[1] if len(SLEEP_ROOMS) > 1 else SLEEP_ROOMS[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mood_label(score: float) -> str:
    for threshold, label in MOOD_LABELS:
        if score >= threshold:
            return label
    return "情绪崩溃"


def _format_clock(total_minutes: int) -> str:
    day_minutes = 24 * 60
    day = total_minutes // day_minutes
    within = total_minutes % day_minutes
    h, m = divmod(within, 60)
    suffix = f" 第{day + 1}天" if day else ""
    return f"{h:02d}:{m:02d}{suffix}"


def _pair_score(session: RoommateSession, a_id: int, b_id: int) -> float:
    return session.relationships.get(int(a_id), {}).get(int(b_id), 0.0)


def _bump_relationship(session: RoommateSession, a_id: int, b_id: int, delta: float) -> None:
    a_id = int(a_id)
    b_id = int(b_id)
    if a_id == b_id:
        return
    delta = max(-15.0, min(15.0, float(delta)))
    pairs = session.relationships.setdefault(a_id, {})
    pairs[b_id] = max(-100.0, min(100.0, pairs.get(b_id, 0.0) + delta))
    mirror = session.relationships.setdefault(b_id, {})
    mirror[a_id] = pairs[b_id]


def _mood_decay(session: RoommateSession) -> None:
    for r in session.residents:
        # Pull toward 0 by MOOD_DECAY_PER_TICK (a great first hour doesn't
        # stay great forever). Without this, early events dominate forever.
        if r.mood > 0:
            r.mood = max(0.0, r.mood - MOOD_DECAY_PER_TICK)
        elif r.mood < 0:
            r.mood = min(0.0, r.mood + MOOD_DECAY_PER_TICK)


def _relationship_decay(session: RoommateSession) -> None:
    decay = RELATIONSHIP_DECAY_PER_TICK
    for a_id, pairs in list(session.relationships.items()):
        for b_id, value in list(pairs.items()):
            new_value = 0.0 if abs(value) <= decay else (value - decay if value > 0 else value + decay)
            pairs[b_id] = new_value


# ---------------------------------------------------------------------------
# Tick logic
# ---------------------------------------------------------------------------


def _pick_activity(resident: Resident, rng: random.Random) -> str:
    """Pick an activity appropriate for the current clock hour."""
    hour = (session_clock_hour := _current_hour(None)) if False else None  # noqa: F841
    return rng.choice(ACTIVITIES)


def _current_hour(session: RoommateSession | None) -> int:
    """The current virtual hour, used to bias activity selection."""
    if session is None:
        return 12
    return (session.virtual_clock_minutes // 60) % 24


def _activity_for_hour(hour: int, rng: random.Random) -> str:
    """Bias the activity vocabulary by hour so the day reads like a day."""
    if 6 <= hour < 9:
        pool = ("做早餐", "吃早餐", "刷短视频", "看书")
    elif 9 <= hour < 12:
        pool = ("处理工作邮件", "看书", "练琴", "打电话", "画一会儿画")
    elif 12 <= hour < 14:
        pool = ("做午餐", "吃午餐", "午睡", "刷短视频")
    elif 14 <= hour < 18:
        pool = ("处理工作邮件", "看书", "画一会儿画", "健身", "练琴", "打电话给家人")
    elif 18 <= hour < 21:
        pool = ("做晚餐", "吃晚餐", "追剧", "打电话", "下楼散步")
    elif 21 <= hour < 24:
        pool = ("追剧", "泡茶", "看书", "写日记", "看窗外", "打电话给家人")
    else:
        pool = ("睡前阅读", "发呆", "洗澡", "午睡")
    return rng.choice(pool)


def _room_for_activity(activity: str) -> str:
    return ACTIVITY_ROOM.get(activity, "living")


def _step_resident(resident: Resident, session: RoommateSession, rng: random.Random) -> Event | None:
    """Update one resident for this tick. Returns a 'move' event when they
    physically move to a new room, so the front-end can animate it.

    Night-time rule: between :data:`NIGHT_HOUR` and midnight every
    resident gets pulled back to their own bedroom regardless of what
    they were doing. This keeps the apartment from feeling restless
    when the player's virtual clock rolls past bedtime, and gives the
    scene an obvious day/night rhythm."""
    old_room = resident.room
    hour = _current_hour(session)
    is_night = hour >= NIGHT_HOUR or hour < DAWN_HOUR
    activity = _activity_for_hour(hour, rng)
    room = _room_for_activity(activity)

    if is_night and resident.bedroom:
        # Bedrooms are private — once they're home, leave them there.
        activity = "睡前阅读" if hour >= NIGHT_HOUR - 1 else "睡觉"
        room = resident.bedroom

    resident.activity = activity
    if room != old_room:
        resident.room = room
        return Event(
            seq=0,  # filled in by the caller
            tick=session.tick_index,
            at=time.time(),
            kind="move",
            actor_ids=[resident.agent_id],
            room=room,
            note=f"{resident.name} 去{_room_label(room)}{activity}",
        )
    return None


def _co_present_pairs(session: RoommateSession) -> list[tuple[Resident, Resident, str]]:
    """Every (a, b, room) where a and b are both in the same non-private room."""
    pairs: list[tuple[Resident, Resident, str]] = []
    by_room: dict[str, list[Resident]] = {}
    for r in session.residents:
        by_room.setdefault(r.room, []).append(r)
    for room, group in by_room.items():
        if len(group) < 2:
            continue
        if room in {"master", "second"}:
            # Bedrooms are private; only count when the two residents *happen*
            # to be there together (e.g. one walks in).
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pairs.append((a, b, room))
    return pairs


def _interaction_probability(a: Resident, b: Resident, room: str) -> float:
    """How likely are these two to talk this tick?"""
    prob = BASE_INTERACTION_PROB
    # Both busy → unlikely.
    if a.activity in SOLO_ACTIVITIES and b.activity in SOLO_ACTIVITIES:
        prob *= 0.15
    elif a.activity in SOLO_ACTIVITIES or b.activity in SOLO_ACTIVITIES:
        prob *= 0.45
    # Kitchen is a magnet.
    if room == "kitchen":
        prob *= 1.3
    elif room == "balcony":
        prob *= 1.15
    # Hallway is just passing through — short.
    if room == "hallway":
        prob *= 0.6
    return min(0.95, max(0.05, prob))


def _interact_prompt(a: Resident, b: Resident, room: str, vibe: str) -> str:
    persona_a = {"name": a.name, "age": a.age, "gender": a.gender, "job": a.job, "profile_md": a.profile_md}
    persona_b = {"name": b.name, "age": b.age, "gender": b.gender, "job": b.job, "profile_md": b.profile_md}
    return (
        f"{persona_block(persona_a)}\n\n"
        f"{persona_block(persona_b)}\n\n"
        f"现在是虚拟时间 {_format_clock(0)}。{a.name}和{b.name}在公寓的「{_room_label(room)}」碰上了。"
        f"两人刚才各自在：{a.activity} / {b.activity}。\n"
        f"公寓的氛围：{vibe or '几个合得来的朋友住在同一间公寓里。'}\n\n"
        "请扮演**这场相遇的导演**:以这两人的身份写一段真实、自然的日常对话(可以寒暄、可以聊今天的新闻/工作/感情、可以拌嘴、可以沉默),然后告诉他们各自心里在想什么。\n\n"
        "请严格用以下 JSON 输出(不要解释、不要 Markdown):\n"
        "{\n"
        '  "room": "房间id(kitchen/living/master/second/study/bath/balcony/hallway)",\n'
        '  "lines": [\n'
        '    {"who": "a_name", "text": "一句中文对话"},'
        '    {"who": "b_name", "text": "一句中文对话"},\n'
        '    ... 共 2-6 条对话,自然分回合\n'
        "  ],\n"
        '  "thought_a": "a 这时的内心独白,一句话,中文",\n'
        '  "thought_b": "b 这时的内心独白,一句话,中文",\n'
        '  "mood_delta_a": -1 到 1 的小数(这场相遇让 a 的心情变了多少),\n'
        '  "mood_delta_b": -1 到 1 的小数,\n'
        '  "rel_delta": -15 到 15 的小数(两人关系的变化,正值更亲近,负值更疏远)\n'
        "}\n\n"
        "要求:\n"
        "- 对话生活化,符合两人各自的职业、年龄、口吻\n"
        "- 内心独白是「他/她没说出口的话」,反映真实想法而不是客套\n"
        "- 心情和关系的小数请如实反映事件强度:一次普通寒暄 ±0.05,一场认真聊天 ±0.2,一次冲突 ±0.4"
    )


def _room_label(room_id: str) -> str:
    for r in ROOMS:
        if r["id"] == room_id:
            return str(r["label"])
    return room_id


def _parse_interaction(raw: str, default_room: str) -> dict[str, Any]:
    """Pull the structured fields out of the model's reply.

    The model is asked for a JSON object; ``first_json_object`` already walks
    the braces. The post-processing here only enforces shape (clamp numbers,
    drop empty dialogue lines) so the dashboard never crashes on a stray key.
    """
    parsed = first_json_object(raw) if isinstance(raw, str) else {}
    if not parsed:
        return {
            "room": default_room,
            "lines": [],
            "thought_a": "",
            "thought_b": "",
            "mood_delta_a": 0.0,
            "mood_delta_b": 0.0,
            "rel_delta": 0.0,
        }
    lines = []
    for item in parsed.get("lines") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        who = str(item.get("who") or "").strip()
        lines.append({"who": who, "text": text})
    try:
        mood_a = max(-1.0, min(1.0, float(parsed.get("mood_delta_a") or 0)))
    except (TypeError, ValueError):
        mood_a = 0.0
    try:
        mood_b = max(-1.0, min(1.0, float(parsed.get("mood_delta_b") or 0)))
    except (TypeError, ValueError):
        mood_b = 0.0
    try:
        rel = max(-15.0, min(15.0, float(parsed.get("rel_delta") or 0)))
    except (TypeError, ValueError):
        rel = 0.0
    return {
        "room": str(parsed.get("room") or default_room),
        "lines": lines,
        "thought_a": str(parsed.get("thought_a") or "").strip(),
        "thought_b": str(parsed.get("thought_b") or "").strip(),
        "mood_delta_a": mood_a,
        "mood_delta_b": mood_b,
        "rel_delta": rel,
    }


def _format_dialogue(lines: list[dict[str, str]]) -> str:
    return "\n".join(f"{item.get('who', '')}:{item.get('text', '')}" for item in lines if item.get("text"))


# ---------------------------------------------------------------------------
# Public session API
# ---------------------------------------------------------------------------


def start_session(
    *,
    city: str,
    agent_ids: list[int],
    vibe: str = "",
    tick_minutes: int = DEFAULT_TICK_MINUTES,
    max_hours: int = DEFAULT_MAX_HOURS,
    reaction_fn: Callable[[str], str] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Open a new roommate session. No model calls happen here — the front-end
    drives the simulation through :func:`tick` calls."""
    rng = rng or random.Random()
    if not agent_ids:
        raise ValueError("至少选两位居民同居")
    ids = [int(a) for a in agent_ids]
    if len(ids) < MIN_AGENTS:
        raise ValueError(f"同居模式至少需要 {MIN_AGENTS} 位居民")
    if len(ids) > MAX_AGENTS:
        raise ValueError(f"同居模式最多 {MAX_AGENTS} 位居民")
    if len(set(ids)) != len(ids):
        raise ValueError("同一个居民只能选一次")
    tick = max(1, min(int(tick_minutes or DEFAULT_TICK_MINUTES), 30))
    hours = max(1, min(int(max_hours or DEFAULT_MAX_HOURS), 999))

    residents = _load_residents(city, ids)
    if len(residents) < len(ids):
        raise ValueError("有居民找不到档案,请换一个城市或重新选人")
    _assign_bedrooms(residents)

    session = RoommateSession(
        id=f"roommate-{uuid.uuid4().hex[:8]}",
        city=str(city or ""),
        vibe=str(vibe or "").strip(),
        residents=residents,
        tick_minutes=tick,
        max_hours=hours,
    )
    session.opening_clock_minutes = session.virtual_clock_minutes
    # Seed the simulation: give each resident an opening activity so the first
    # frame the front-end renders isn't everyone in the living room doing
    # nothing.
    for r in residents:
        r.activity = _activity_for_hour(8, rng)
        r.room = _room_for_activity(r.activity)

    # Stash the reaction fn on the session for later ticks; tests inject a
    # fake one here so the loop never talks to a real provider.
    session._reaction_fn = reaction_fn  # type: ignore[attr-defined]
    session._rng = rng  # type: ignore[attr-defined]

    _store(session)
    return session.to_dict()


def get_session(session_id: str) -> dict[str, Any] | None:
    try:
        return _require(session_id).to_dict()
    except KeyError:
        return None


def list_sessions() -> list[dict[str, Any]]:
    with _SESSIONS_LOCK:
        sessions = [s for s in _SESSIONS.values() if ownership.visible({"owner_id": s.owner_id})]
    sessions.sort(key=lambda s: -s.created_at)
    return [
        {
            "id": s.id,
            "city": s.city,
            "vibe": s.vibe,
            "tick_index": s.tick_index,
            "running": s.running,
            "finished": s.settled,
            "created_at": s.created_at,
            "residents": [r.name for r in s.residents],
        }
        for s in sessions
    ]


def end_session(session_id: str) -> dict[str, Any] | None:
    """Player stopped watching: mark finished so the session can be evicted."""
    try:
        session = _require(session_id)
    except KeyError:
        return None
    if not session.settled:
        session.finished_at = time.time()
        session.running = False
    return session.to_dict()


#: Activities a player is allowed to *direct* a resident into. These map to
#: the matching room — anything not in this list is rejected at the door so
#: the front-end cannot ask a resident to "drive a car" or anything else
#: the floor plan does not support.
_DIRECT_ACTIVITIES: frozenset[str] = frozenset({
    "做早餐", "吃早餐",
    "做午餐", "吃午餐",
    "做晚餐", "吃晚餐",
    "看书", "写日记", "处理工作邮件", "画一会儿画", "练琴",
    "刷短视频", "追剧", "看电视",
    "健身", "跟宠物玩", "打电话", "打电话给家人",
    "午睡", "睡前阅读", "发呆",
    "洗澡", "洗衣服", "晾衣服",
    "泡茶", "下楼散步",
})


def direct_resident(
    session_id: str,
    *,
    agent_id: int,
    activity: str,
    room: str | None = None,
    note: str = "",
    reaction_fn: Callable[[str], str] | None = None,
) -> dict[str, Any] | None:
    """Player-driven override: send a resident to *room* doing *activity*.

    Unlike :func:`tick`, no virtual clock advances. The session simply
    records a ``direct`` event, updates the resident's state so the
    front-end snaps the sprite toward the new room, and (if a
    ``reaction_fn`` is given) lets the model riff a one-liner the
    resident "says" as they go. Without a model call, the event note
    itself becomes the bubble text — the player still sees *something*.

    Returns the updated session dict, or ``None`` when the session is
    gone. Raises :class:`ValueError` when the inputs are bad (unknown
    resident, activity not in the catalogue, room id not in the layout).
    """
    try:
        session = _require(session_id)
    except KeyError:
        return None
    if session.settled:
        raise ValueError("同居已结束,不能再指令")
    aid = int(agent_id)
    resident = next((r for r in session.residents if r.agent_id == aid), None)
    if resident is None:
        raise ValueError(f"房间里没有 #{aid} 这位居民")
    activity = str(activity or "").strip()
    if activity not in _DIRECT_ACTIVITIES:
        raise ValueError(f"活动 '{activity}' 没法在这间公寓里做")
    # Use the caller's reaction_fn if given; otherwise fall back to the
    # one stashed on the session at start time (tests inject there).
    if reaction_fn is None:
        reaction_fn = getattr(session, "_reaction_fn", None)
    target_room = (room or _room_for_activity(activity) or "").strip() or resident.room
    if not any(r["id"] == target_room for r in ROOMS):
        raise ValueError(f"房间 '{target_room}' 不存在")
    old_room = resident.room
    resident.activity = activity
    resident.room = target_room

    # If a reaction_fn is injected (tests), let the model add a one-liner;
    # otherwise we just write the player's intent back as the bubble.
    turn_text = ""
    thought_text = ""
    if reaction_fn is not None:
        try:
            prompt = (
                f"{resident.name}正在去公寓的「{_room_label(target_room)}」{activity}。"
                f"玩家刚刚指令他/她这么做。请用一句话写出他/她会说的话,真实而口语化。\n"
                "请严格用 JSON 输出(不要解释、不要 Markdown):\n"
                '{"say":"一句中文","think":"一句中文内心独白"}\n'
            )
            raw = reaction_fn(prompt)
            parsed = first_json_object(raw) if isinstance(raw, str) else {}
            turn_text = str(parsed.get("say") or "").strip()
            thought_text = str(parsed.get("think") or "").strip()
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("direct_resident reaction failed for %s: %s", aid, exc)
    if not turn_text:
        turn_text = f"{resident.name} 走去{_room_label(target_room)}{activity}"
    if not thought_text:
        thought_text = f"({resident.name}按玩家的意思做了这件事)"
    turns = [{"who": resident.name, "text": turn_text}]
    event = Event(
        seq=0,
        tick=session.tick_index,
        at=time.time(),
        kind="direct",
        actor_ids=[aid],
        room=target_room,
        dialogue=f"{resident.name}:{turn_text}",
        thought=f"{resident.name}:{thought_text}",
        turns=turns,
        note=(note or f"玩家让 {resident.name} 去{_room_label(target_room)}{activity}"),
    )
    if old_room != target_room:
        # Also append a move event so the side panel reads like a journal:
        # the player sees "X 去厨房做早餐" (move) followed by "X: …" (direct).
        _append_event(session, Event(
            seq=0,
            tick=session.tick_index,
            at=time.time(),
            kind="move",
            actor_ids=[aid],
            room=target_room,
            note=f"{resident.name} 去{_room_label(target_room)}{activity}",
        ))
    _append_event(session, event)
    # Bump mood a tiny amount — being directed is mildly annoying
    # (autonomy loss) but doing an activity you chose is mildly pleasant.
    resident.mood = max(-1.0, min(1.0, resident.mood - 0.02))
    # Mark running so the next tick still works after a direct.
    session.running = True
    return session.to_dict()


def tick(session_id: str, *, steps: int = 1) -> dict[str, Any] | None:
    """Advance the simulation by *steps* ticks. The front-end calls this once
    a turn; longer bursts come from the fast-forward button."""
    try:
        session = _require(session_id)
    except KeyError:
        return None
    if session.settled:
        return session.to_dict()
    # ``running`` is a player pause flag — flipping it off does not freeze
    # the simulation, it only stops it advancing on a tick. Re-tick flips
    # it back on so the player can resume after the night/day cycle ends.
    session.running = True
    steps = max(1, min(int(steps or 1), MAX_TICKS_PER_REQUEST))
    reaction_fn: Callable[[str], str] | None = getattr(session, "_reaction_fn", None)
    rng: random.Random = getattr(session, "_rng", None) or random.Random()
    #: The deadline is anchored to ``opening_clock_minutes`` (set when the
    #: session was created) and is *not* recomputed on every call — otherwise
    #: each tick would push the deadline forward and the session would never
    #: finish.
    deadline = session.opening_clock_minutes + session.max_hours * 60

    for _ in range(steps):
        _advance_one_tick(session, rng=rng, reaction_fn=reaction_fn)
        if session.virtual_clock_minutes >= deadline:
            session.running = False
            session.finished_at = time.time()
            break
    return session.to_dict()


def _advance_one_tick(
    session: RoommateSession,
    *,
    rng: random.Random,
    reaction_fn: Callable[[str], str] | None,
) -> None:
    session.tick_index += 1
    session.virtual_clock_minutes += session.tick_minutes

    # 1) every resident picks a new activity + room
    for resident in session.residents:
        move_event = _step_resident(resident, session, rng)
        if move_event is not None:
            _append_event(session, move_event)

    # 2) mood / relationships drift toward neutral
    _mood_decay(session)
    _relationship_decay(session)

    # 3) every co-present pair *may* spark an interaction — dispatched
    # to a worker pool so a slow LLM does not block the front-end tick.
    _gc_pending_futures()
    _cancel_stale_futures()
    for a, b, room in _co_present_pairs(session):
        prob = _interaction_probability(a, b, room)
        # Nudge probability up when they already like each other.
        rel = _pair_score(session, a.agent_id, b.agent_id)
        prob = min(0.95, prob + max(-0.2, min(0.2, rel / 200.0)))
        if rng.random() > prob:
            continue
        # Capture locals now — the worker cannot reach the live session
        # object safely without the session lock.
        fn = reaction_fn or _default_reaction_llm
        prompt = _interact_prompt(a, b, room, session.vibe)
        a_id, b_id = a.agent_id, b.agent_id
        tick_idx = session.tick_index
        vibe = session.vibe
        future = _INTERACTION_EXECUTOR.submit(_run_interaction_worker,
                                              session.id, a_id, b_id, room, prompt, fn, tick_idx, vibe)
        future._submit_time = time.time()  # type: ignore[attr-defined]
        with _INTERACTION_LOCK:
            _PENDING_FUTURES.append(future)
        # Watchdog: if the worker does not finish in ``timeout`` seconds,
        # cancel the future and emit a placeholder event so the dashboard
        # keeps moving. ``add_done_callback`` runs on the worker thread
        # once the future resolves, cancelled or not.
        future.add_done_callback(lambda f, sid=session.id, ai=a_id, bi=b_id, r=room, t=tick_idx:
                                _maybe_emit_fallback(sid, ai, bi, r, t, f))


def _run_interaction_worker(
    session_id: str,
    a_id: int,
    b_id: int,
    room: str,
    prompt: str,
    fn: Callable[[str], str],
    tick_idx: int,
    vibe: str,
) -> None:
    """Run one interaction end-to-end in a worker thread, then write the
    result back into the session under its lock."""
    try:
        raw = fn(prompt)
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("roommate reaction failed for %s/%s: %s", a_id, b_id, exc)
        raw = ""
    parsed = _parse_interaction(raw, default_room=room)
    try:
        session = _require(session_id)
    except KeyError:
        return
    a = next((r for r in session.residents if r.agent_id == a_id), None)
    b = next((r for r in session.residents if r.agent_id == b_id), None)
    if a is None or b is None:
        return
    # Distinguish a real reply from a provider failure / hang: ``raw`` is
    # non-empty only when the model actually answered. Empty ``raw`` means
    # we hit an exception, and we should not paint a bubble from that.
    # The dashboard will keep showing the previous (real) bubble instead.
    if not raw and not parsed.get("thought_a") and not parsed.get("thought_b"):
        _LOG.warning("roommate interaction %s/%s produced no content; skipping event", a_id, b_id)
        return
    a.mood = max(-1.0, min(1.0, a.mood + parsed["mood_delta_a"]))
    b.mood = max(-1.0, min(1.0, b.mood + parsed["mood_delta_b"]))
    _bump_relationship(session, a_id, b_id, parsed["rel_delta"])
    lines = parsed.get("lines") or []
    event = Event(
        seq=0,
        tick=tick_idx,
        at=time.time(),
        kind="interact",
        actor_ids=[a_id, b_id],
        room=parsed["room"] or room,
        dialogue=_format_dialogue(lines),
        thought=f"{a.name}:{parsed['thought_a']} | {b.name}:{parsed['thought_b']}",
        turns=[{"who": t.get("who", ""), "text": t.get("text", "")} for t in lines],
        mood_delta=(parsed["mood_delta_a"] + parsed["mood_delta_b"]) / 2,
        relationship_delta={str(b_id): parsed["rel_delta"], str(a_id): parsed["rel_delta"]},
    )
    _append_event(session, event)


def _trigger_interaction(
    session: RoommateSession,
    a: Resident,
    b: Resident,
    room: str,
    *,
    reaction_fn: Callable[[str], str] | None,
) -> None:
    """Synchronous variant kept for tests that inject a fake ``reaction_fn``
    and want the event appended before the assertion runs."""
    fn = reaction_fn or _default_reaction_llm
    try:
        raw = fn(_interact_prompt(a, b, room, session.vibe))
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("roommate reaction failed for %s/%s: %s", a.agent_id, b.agent_id, exc)
        return
    parsed = _parse_interaction(raw, default_room=room)

    a.mood = max(-1.0, min(1.0, a.mood + parsed["mood_delta_a"]))
    b.mood = max(-1.0, min(1.0, b.mood + parsed["mood_delta_b"]))
    _bump_relationship(session, a.agent_id, b.agent_id, parsed["rel_delta"])

    lines = parsed.get("lines") or []
    event = Event(
        seq=0,
        tick=session.tick_index,
        at=time.time(),
        kind="interact",
        actor_ids=[a.agent_id, b.agent_id],
        room=parsed["room"] or room,
        dialogue=_format_dialogue(lines),
        thought=f"{a.name}:{parsed['thought_a']} | {b.name}:{parsed['thought_b']}",
        turns=[{"who": t.get("who", ""), "text": t.get("text", "")} for t in lines],
        mood_delta=(parsed["mood_delta_a"] + parsed["mood_delta_b"]) / 2,
        relationship_delta={str(b.agent_id): parsed["rel_delta"], str(a.agent_id): parsed["rel_delta"]},
    )
    _append_event(session, event)


def _append_event(session: RoommateSession, event: Event) -> None:
    session.last_seq += 1
    event.seq = session.last_seq
    session.events.append(event)


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


_MAX_SESSIONS = 30


def _store(session: RoommateSession) -> None:
    with _SESSIONS_LOCK:
        _SESSIONS[session.id] = session
        finished = [(s.created_at, key) for key, s in _SESSIONS.items() if s.settled]
        while len(_SESSIONS) > _MAX_SESSIONS and finished:
            finished.sort()
            _, oldest = finished.pop(0)
            _SESSIONS.pop(oldest, None)


def _require(session_id: str) -> RoommateSession:
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(str(session_id))
    if session is None or not ownership.visible({"owner_id": session.owner_id}):
        raise KeyError(session_id)
    return session


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/roommate/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/roommate/catalogue":
            return {
                "max_agents": MAX_AGENTS,
                "min_agents": MIN_AGENTS,
                "default_tick_minutes": DEFAULT_TICK_MINUTES,
                "default_max_hours": DEFAULT_MAX_HOURS,
                "max_ticks_per_request": MAX_TICKS_PER_REQUEST,
                "rooms": list(ROOMS),
                "activities": list(ACTIVITIES),
                "mood_labels": [{"threshold": t, "label": l} for t, l in MOOD_LABELS],
            }, 200
        if path == "/api/games/roommate/sessions":
            return {"sessions": list_sessions()}, 200
        if path.startswith("/api/games/roommate/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            record = get_session(session_id)
            if record is None:
                return {"error": "Unknown session"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("roommate GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/roommate/start":
            return start_session(
                city=str(payload.get("city") or ""),
                agent_ids=[int(i) for i in (payload.get("agent_ids") or [])],
                vibe=str(payload.get("vibe") or ""),
                tick_minutes=int(payload.get("tick_minutes") or DEFAULT_TICK_MINUTES),
                max_hours=int(payload.get("max_hours") or DEFAULT_MAX_HOURS),
            ), 200
        if path == "/api/games/roommate/tick":
            session_id = str(payload.get("session_id") or "")
            steps = int(payload.get("steps") or 1)
            record = tick(session_id, steps=steps)
            if record is None:
                return {"error": "Unknown session"}, 404
            return record, 200
        if path == "/api/games/roommate/end":
            session_id = str(payload.get("session_id") or "")
            record = end_session(session_id)
            if record is None:
                return {"error": "Unknown session"}, 404
            return record, 200
        if path.startswith("/api/games/roommate/sessions/") and path.endswith("/direct"):
            # POST /api/games/roommate/sessions/{id}/direct
            # body: {agent_id, activity, room?, note?}
            session_id = path.rsplit("/", 2)[-2]
            record = direct_resident(
                session_id,
                agent_id=int(payload.get("agent_id") or 0),
                activity=str(payload.get("activity") or ""),
                room=str(payload.get("room") or "") or None,
                note=str(payload.get("note") or ""),
            )
            if record is None:
                return {"error": "Unknown session"}, 404
            return record, 200
    except KeyError:
        return {"error": "Unknown session"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("roommate POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "DEFAULT_MAX_HOURS",
    "DEFAULT_TICK_MINUTES",
    "MAX_AGENTS",
    "MAX_TICKS_PER_REQUEST",
    "MIN_AGENTS",
    "MOOD_LABELS",
    "ROOMS",
    "Resident",
    "RoommateSession",
    "direct_resident",
    "end_session",
    "get_session",
    "handle_get",
    "handle_post",
    "list_sessions",
    "reset_sessions",
    "start_session",
    "tick",
]
