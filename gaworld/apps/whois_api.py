"""Dashboard backend for 谁是真人 (Who's Human), a playground game.

A few residents and a few people sit in one anonymous group chat about an
everyday topic. Everyone shows up only as a number. Each round everybody
writes one message at once; when the last one is in, the round appears to
the room as a whole. After the last round every person marks each other
number "真人" or "居民", and when the ballots are in the room reveals who
was who.

It is the one kind of evidence about residents a model cannot produce about
itself: whether people can tell them from people. Every revealed room is
archived (:mod:`gaworld.apps.game_archive`, kind ``whois``) and
GAWorld-Bench Track D pools the ballots.

Design choices, each of which a result has to be read against:

* **Rounds are simultaneous** and a round only becomes visible once it is
  complete. Who answers instantly is the cheapest tell there is, so players
  never see who has written, who has voted, or how many people are in the
  room — only the host's panel does.
* **Residents are not told about the guessing.** They chat as themselves,
  under the persona the simulator runs; what is measured is that persona,
  not a model coached to fool anyone.
* **Residents are asked for short, spoken messages** — the same voice rules
  as the persuasion game. A 200-character paragraph in a group chat would
  be a tell of the prompt rather than of the persona. That instruction is
  the cue every result has to be read with.
* A **seat link** is the invitation, as for serious games: it opens that seat
  to whoever holds it. The host's view (which shows who is who) needs
  ownership of the room — the host should not play.

Rooms live in memory while they are played; only revealed rooms are written,
to the archive.
"""

from __future__ import annotations

import copy
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.games_api import first_json_object, persona_block
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.whois_api")

MIN_AGENTS, MAX_AGENTS = 1, 5
MIN_HUMANS, MAX_HUMANS = 1, 5
MIN_SEATS, MAX_SEATS = 3, 8
MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS = 2, 5, 3
MAX_MESSAGE_CHARS = 200
MAX_REASON_CHARS = 200
VERDICTS = ("human", "resident")
STATUSES = ("chatting", "guessing", "revealed")
#: Shown in a round for a seat that said nothing (an absent person, or a
#: resident whose model call failed twice).
SILENT = "（没说话）"

#: Built-in topics. Everyday on purpose: the persona's own life is where
#: residents and people differ, and an abstract topic invites essays.
TOPICS: tuple[dict[str, str], ...] = (
    {"id": "weekend", "emoji": "🛋️", "title": "上个周末", "text": "上个周末你都干了些啥？"},
    {"id": "annoy", "emoji": "😤", "title": "最近的烦心事", "text": "最近有什么让你挺烦的小事？"},
    {"id": "money", "emoji": "💰", "title": "多出来一万块", "text": "要是这个月突然多出一万块，你会怎么花？"},
    {
        "id": "food",
        "emoji": "🍜",
        "title": "附近吃什么",
        "text": "你住的附近有什么吃的值得推荐，又踩过什么雷？",
    },
    {"id": "work", "emoji": "💼", "title": "最累的是什么", "text": "你现在的工作或日子里，最累的是哪一块？"},
)

_VOICE_RULES = (
    "用你平时在微信群里说话的样子回：口语，一两句，不超过 60 字。"
    "可以接某个编号的话、可以问别人、可以有点跑题；别用书面语，别分点，别总结，别客套。"
    "说的内容要是你自己的生活。不要扮演助手，不要说「作为一个 AI」。"
)

_ROOMS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()
_DRIVING: set[str] = set()

#: Injected by tests; ``None`` means the configured provider via ``call_llm``.
_LLM_OVERRIDE: Callable[[str], str] | None = None
#: Injected by tests: ``(city, agent_id or None, taken) -> persona``.
_PERSONA_OVERRIDE: Callable[[str, int | None, set[int]], dict[str, Any]] | None = None


def _llm(prompt: str) -> str:
    if _LLM_OVERRIDE is not None:
        return _LLM_OVERRIDE(prompt)
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task="games.whois", temperature=0.8, allow_fallback=True))


def _persona(city: str, agent_id: int | None, taken: set[int]) -> dict[str, Any]:
    if _PERSONA_OVERRIDE is not None:
        return _PERSONA_OVERRIDE(city, agent_id, taken)
    from gaworld.research.serious_game import resident_persona

    return resident_persona(city, agent_id, taken=taken)


def reset() -> None:
    """Drop every room. Used by tests; production code never calls it."""
    with _LOCK:
        _ROOMS.clear()
        _DRIVING.clear()


# ---------------------------------------------------------------------------
# The room (pure; no locks, no threads)
# ---------------------------------------------------------------------------


def _topic(payload: dict[str, Any]) -> dict[str, str]:
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    if custom:
        text = str(custom.get("text") or "").strip()[:200]
        if not text:
            raise ValueError("自定义话题要写一句话")
        return {"id": "custom", "emoji": "✍️", "title": str(custom.get("title") or text)[:30], "text": text}
    topic_id = str(payload.get("topic_id") or TOPICS[0]["id"])
    for topic in TOPICS:
        if topic["id"] == topic_id:
            return dict(topic)
    raise ValueError(f"没有这个话题：{topic_id}")


def _count(payload: dict[str, Any], key: str, low: int, high: int, default: int) -> int:
    try:
        value = int(payload.get(key) if payload.get(key) not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} 要是整数") from exc
    if not low <= value <= high:
        raise ValueError(f"{key} 要在 {low}–{high} 之间")
    return value


def new_room(payload: dict[str, Any]) -> dict[str, Any]:
    """Seat residents and people at random numbers and open round one. No model call."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    agents = _count(payload, "agents", MIN_AGENTS, MAX_AGENTS, len(agent_ids) or 3)
    if len(agent_ids) > agents:
        raise ValueError(f"选了 {len(agent_ids)} 位居民，但居民座位只有 {agents} 个")
    humans = _count(payload, "humans", MIN_HUMANS, MAX_HUMANS, 2)
    if not MIN_SEATS <= agents + humans <= MAX_SEATS:
        raise ValueError(f"一共 {MIN_SEATS}–{MAX_SEATS} 个座位，现在是 {agents + humans} 个")
    rounds = _count(payload, "rounds", MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS)
    topic = _topic(payload)

    taken: set[int] = set()
    seats: list[dict[str, Any]] = []
    for index in range(agents):
        wanted = agent_ids[index] if index < len(agent_ids) else None
        persona = _persona(city, wanted, taken)
        taken.add(int(persona["agent_id"]))
        seats.append({"kind": "agent", "persona": persona})
    seats += [{"kind": "human", "token": secrets.token_urlsafe(9)} for _ in range(humans)]
    # Numbers are drawn, not assigned in order: "the humans are the last two"
    # would end the game before it starts.
    numbers = list(range(1, len(seats) + 1))
    secrets.SystemRandom().shuffle(numbers)
    for seat, number in zip(seats, numbers, strict=True):
        seat["alias"] = f"{number}号"
    seats.sort(key=lambda s: int(s["alias"][:-1]))
    now = time.time()
    return {
        "id": f"whois-{uuid.uuid4().hex[:8]}",
        "city": city,
        "topic": topic,
        "rounds_total": rounds,
        "seats": seats,
        "round": 0,
        "open": {},
        "transcript": [],
        "votes": {},
        "status": "chatting",
        "created_at": now,
        "updated_at": now,
    }


def seat_by_token(room: dict[str, Any], token: str) -> dict[str, Any] | None:
    return next((s for s in room["seats"] if token and s.get("token") == token), None)


def _humans(room: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in room["seats"] if s["kind"] == "human"]


def pending(room: dict[str, Any], kind: str | None = None) -> list[dict[str, Any]]:
    """Seats that have not written in the open round."""
    if room["status"] != "chatting":
        return []
    return [s for s in room["seats"] if s["alias"] not in room["open"] and kind in (None, s["kind"])]


def _transcript_text(room: dict[str, Any]) -> str:
    if not room["transcript"]:
        return "（这是第一轮，还没人说话。）"
    blocks = []
    for record in room["transcript"]:
        lines = "\n".join(f"{m['alias']}：{m['text']}" for m in record["messages"])
        blocks.append(f"第 {record['round'] + 1} 轮\n{lines}")
    return "\n\n".join(blocks)


def agent_prompt(room: dict[str, Any], seat: dict[str, Any]) -> str:
    topic = room["topic"]
    return (
        f"{persona_block(seat.get('persona') or {})}\n\n"
        f"你在一个匿名的群聊里，跟几位同城的陌生人闲聊。群里每个人只显示编号，你是「{seat['alias']}」。\n"
        f"话题：{topic['text']}\n\n"
        f"【之前的聊天】\n{_transcript_text(room)}\n\n"
        f"现在是第 {room['round'] + 1} 轮，大家同时各发一条。{_VOICE_RULES}\n"
        '只输出一个 JSON 对象：{"message": "你要发的那一条"}'
    )


def parse_message(raw: str) -> str:
    payload = first_json_object(raw)
    text = str(payload.get("message") or "") if payload else str(raw or "")
    return " ".join(text.split())[:MAX_MESSAGE_CHARS]


def record_message(room: dict[str, Any], alias: str, text: str) -> None:
    if room["status"] != "chatting":
        raise ValueError("现在不是聊天的时候")
    if alias in room["open"]:
        raise ValueError("这一轮你已经说过了，等其他人")
    room["open"][alias] = " ".join(str(text or "").split())[:MAX_MESSAGE_CHARS] or SILENT
    room["updated_at"] = time.time()


def close_round_if_ready(room: dict[str, Any]) -> bool:
    """Publish the open round once every seat has written; True if it closed."""
    if room["status"] != "chatting" or pending(room):
        return False
    messages = [{"alias": s["alias"], "text": room["open"][s["alias"]]} for s in room["seats"]]
    room["transcript"].append({"round": room["round"], "messages": messages})
    room["open"] = {}
    room["round"] += 1
    if room["round"] >= room["rounds_total"]:
        room["status"] = "guessing"
    room["updated_at"] = time.time()
    return True


def record_vote(room: dict[str, Any], alias: str, verdicts: dict[str, Any], reason: str = "") -> None:
    if room["status"] != "guessing":
        raise ValueError("还没到猜的时候")
    if alias in room["votes"]:
        raise ValueError("你已经猜过了")
    others = [s["alias"] for s in room["seats"] if s["alias"] != alias]
    clean = {}
    for other in others:
        verdict = str((verdicts or {}).get(other) or "")
        if verdict not in VERDICTS:
            raise ValueError(f"{other} 还没选「真人」或「居民」")
        clean[other] = verdict
    room["votes"][alias] = {
        "verdicts": clean,
        "reason": str(reason or "").strip()[:MAX_REASON_CHARS],
        "at": time.time(),
    }
    room["updated_at"] = time.time()


def reveal_if_ready(room: dict[str, Any], *, force: bool = False) -> bool:
    """Reveal once every person has voted (or the host stops waiting)."""
    if room["status"] != "guessing":
        return False
    waiting = [s for s in _humans(room) if s["alias"] not in room["votes"]]
    if waiting and not (force and room["votes"]):
        return False
    room["status"] = "revealed"
    room["results"] = results(room)
    room["updated_at"] = time.time()
    return True


def results(room: dict[str, Any]) -> dict[str, Any]:
    """Who was judged what, by whom, and how well each person guessed."""
    kind = {s["alias"]: s["kind"] for s in room["seats"]}
    seats = {
        alias: {"alias": alias, "kind": k, "judged_human": 0, "judgments": 0} for alias, k in kind.items()
    }
    judges = []
    for judge, ballot in room["votes"].items():
        correct = 0
        for alias, verdict in ballot["verdicts"].items():
            seats[alias]["judgments"] += 1
            seats[alias]["judged_human"] += verdict == "human"
            correct += (verdict == "human") == (kind[alias] == "human")
        judges.append({"alias": judge, "correct": correct, "total": len(ballot["verdicts"])})

    def tally(k: str) -> tuple[int, int]:
        rows = [s for s in seats.values() if s["kind"] == k]
        return sum(s["judged_human"] for s in rows), sum(s["judgments"] for s in rows)

    resident_human, resident_n = tally("agent")
    human_human, human_n = tally("human")
    total = sum(j["total"] for j in judges)
    return {
        "seats": list(seats.values()),
        "judges": judges,
        "resident_judged_human": resident_human,
        "resident_judgments": resident_n,
        "human_judged_human": human_human,
        "human_judgments": human_n,
        "accuracy": round(sum(j["correct"] for j in judges) / total, 4) if total else None,
    }


def _seat_card(seat: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    card: dict[str, Any] = {"alias": seat["alias"]}
    if reveal:
        card["kind"] = seat["kind"]
        persona = seat.get("persona") or {}
        if persona:
            card["agent"] = {k: persona.get(k) for k in ("agent_id", "name", "age", "gender", "job")}
    return card


def public_view(room: dict[str, Any], *, token: str = "", host: bool = False) -> dict[str, Any]:
    """The room as one viewer may see it.

    A player sees the topic, the closed rounds and their own state — never who
    else has written or voted, nor how many people are in the room, until the
    reveal. The host sees everything, including the seat links.
    """
    revealed = room["status"] == "revealed"
    view: dict[str, Any] = {
        "id": room["id"],
        "city": room["city"],
        "topic": room["topic"],
        "status": room["status"],
        "round": min(room["round"] + 1, room["rounds_total"]),
        "rounds_total": room["rounds_total"],
        "seats": [_seat_card(s, reveal=revealed or host) for s in room["seats"]],
        "transcript": room["transcript"],
        "created_at": room["created_at"],
        "updated_at": room["updated_at"],
        "host": host,
    }
    if revealed:
        view["results"] = room["results"]
        view["votes"] = room["votes"]
    me = seat_by_token(room, token)
    if me is not None:
        alias = me["alias"]
        view["me"] = {
            "alias": alias,
            "posted": alias in room["open"],
            "my_message": room["open"].get(alias),
            "voted": alias in room["votes"],
            "my_votes": (room["votes"].get(alias) or {}).get("verdicts"),
        }
    if host:
        for card, seat in zip(view["seats"], room["seats"], strict=True):
            card["token"] = seat.get("token")
            card["posted"] = seat["alias"] in room["open"]
            card["voted"] = seat["alias"] in room["votes"]
    # A copy: the caller serialises it after the lock is released, while the
    # driver may be appending to the room it came from.
    return copy.deepcopy(view)


def archive_record(room: dict[str, Any]) -> dict[str, Any]:
    """What the archive keeps: everything but the seat links."""
    return {
        "room_id": room["id"],
        "city": room["city"],
        "topic": room["topic"],
        "rounds_total": room["rounds_total"],
        "seats": [_seat_card(s, reveal=True) for s in room["seats"]],
        "transcript": room["transcript"],
        "votes": room["votes"],
        "results": room["results"],
        "created_at": room["created_at"],
        "revealed_at": room["updated_at"],
    }


# ---------------------------------------------------------------------------
# Rooms in memory + the driver that lets residents speak
# ---------------------------------------------------------------------------


def _get(room_id: str) -> dict[str, Any]:
    with _LOCK:
        room = _ROOMS.get(room_id)
    if room is None:
        raise KeyError(room_id)
    return room


def _hosted(room_id: str) -> dict[str, Any]:
    room = _get(room_id)
    if not ownership.visible(room):
        raise KeyError(room_id)
    return room


def create_room(payload: dict[str, Any]) -> dict[str, Any]:
    room = new_room(payload)
    room.update(ownership.stamp())
    with _LOCK:
        _ROOMS[room["id"]] = room
    _kick(room["id"])
    return public_view(room, host=True)


def view(room_id: str, *, token: str = "", host: bool = False) -> dict[str, Any]:
    room = _get(room_id)
    with _LOCK:
        by_seat = seat_by_token(room, token) is not None
    if not by_seat and not ownership.visible(room):
        raise KeyError(room_id)
    with _LOCK:
        return public_view(room, token=token if by_seat else "", host=host and not by_seat)


def _human_seat(room: dict[str, Any], token: str) -> dict[str, Any]:
    seat = seat_by_token(room, token)
    if seat is None:
        raise ValueError("这个座位链接无效")
    return seat


def say(room_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    room = _get(room_id)
    token = str(payload.get("seat") or "")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("写点什么再发")
    with _LOCK:
        record_message(room, _human_seat(room, token)["alias"], text)
        closed = close_round_if_ready(room)
    if closed:
        _kick(room_id)
    return view(room_id, token=token)


def next_round(room_id: str) -> dict[str, Any]:
    """Host stops waiting: absent people sit the round out."""
    room = _hosted(room_id)
    with _LOCK:
        if room["status"] != "chatting":
            raise ValueError("现在不在等人发言")
        if pending(room, "agent"):
            raise ValueError("居民还在打字，稍等")
        for seat in pending(room, "human"):
            record_message(room, seat["alias"], "")
        close_round_if_ready(room)
    _kick(room_id)
    return view(room_id, host=True)


def vote(room_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    room = _get(room_id)
    token = str(payload.get("seat") or "")
    verdicts = payload.get("verdicts") if isinstance(payload.get("verdicts"), dict) else {}
    with _LOCK:
        record_vote(room, _human_seat(room, token)["alias"], verdicts, str(payload.get("reason") or ""))
        revealed = reveal_if_ready(room)
    if revealed:
        _archive(room)
    return view(room_id, token=token)


def reveal(room_id: str) -> dict[str, Any]:
    """Host stops waiting for ballots (at least one must be in)."""
    room = _hosted(room_id)
    with _LOCK:
        if room["status"] != "guessing":
            raise ValueError("现在不在等人猜")
        if not reveal_if_ready(room, force=True):
            raise ValueError("还没有人猜，没法揭晓")
    _archive(room)
    return view(room_id, host=True)


def list_rooms() -> list[dict[str, Any]]:
    with _LOCK:
        rooms = [r for r in _ROOMS.values() if ownership.visible(r)]
        return [
            {
                "id": r["id"],
                "topic": r["topic"]["title"],
                "status": r["status"],
                "seats": len(r["seats"]),
                "created_at": r["created_at"],
            }
            for r in sorted(rooms, key=lambda r: -r["created_at"])
        ]


def _archive(room: dict[str, Any]) -> None:
    from gaworld.apps import game_archive

    with _LOCK:
        record = archive_record(room)
    game_archive.save("whois", room["id"], record)


def _kick(room_id: str) -> None:
    with _LOCK:
        if room_id in _DRIVING:
            return
        _DRIVING.add(room_id)
    ownership.spawn(_drive, room_id, name=f"whois-{room_id}")


def _drive(room_id: str) -> None:
    """Let every resident write in the open round, then close it if it is complete."""
    try:
        while True:
            with _LOCK:
                room = _ROOMS.get(room_id)
                if room is None or room["status"] != "chatting":
                    return
                seat = next(iter(pending(room, "agent")), None)
                if seat is None:
                    if not close_round_if_ready(room):
                        return  # waiting for people
                    continue
                round_index = room["round"]
                prompt = agent_prompt(room, seat)
            text = ""
            for attempt in (1, 2):
                try:
                    text = parse_message(_llm(prompt))
                except Exception as exc:  # pragma: no cover - provider failure
                    _LOG.warning("whois %s: %s attempt %d failed: %s", room_id, seat["alias"], attempt, exc)
                if text:
                    break
            with _LOCK:
                if room["round"] == round_index and seat["alias"] not in room["open"]:
                    record_message(room, seat["alias"], text)
    finally:
        with _LOCK:
            _DRIVING.discard(room_id)


# ---------------------------------------------------------------------------
# HTTP — reached via games_api's /api/games/whois/ branch.
# ---------------------------------------------------------------------------

PREFIX = "/api/games/whois"


def _parts(path: str) -> list[str]:
    return [p for p in path[len(PREFIX) :].split("/") if p]


def _one(query: dict[str, Any] | None, key: str) -> str:
    value = (query or {}).get(key)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    parts = _parts(path)
    try:
        if parts == ["catalogue"]:
            limits = {
                "agents": [MIN_AGENTS, MAX_AGENTS],
                "humans": [MIN_HUMANS, MAX_HUMANS],
                "seats": [MIN_SEATS, MAX_SEATS],
                "rounds": [MIN_ROUNDS, MAX_ROUNDS],
                "default_rounds": DEFAULT_ROUNDS,
            }
            return {"topics": list(TOPICS), "limits": limits}, 200
        if parts == ["rooms"]:
            return {"rooms": list_rooms()}, 200
        if len(parts) == 2 and parts[0] == "rooms":
            seat = _one(query, "seat")
            return view(parts[1], token=seat, host=not seat), 200
    except KeyError:
        return {"error": "没有这个房间（或它不属于你）"}, 404
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("whois GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    parts = _parts(path)
    payload = payload if isinstance(payload, dict) else {}
    try:
        if parts == ["rooms"]:
            return create_room(payload), 200
        if len(parts) == 3 and parts[0] == "rooms":
            room_id, action = parts[1], parts[2]
            if action == "say":
                return say(room_id, payload), 200
            if action == "vote":
                return vote(room_id, payload), 200
            if action == "next":
                return next_round(room_id), 200
            if action == "reveal":
                return reveal(room_id), 200
    except KeyError:
        return {"error": "没有这个房间（或它不属于你）"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("whois POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "MAX_SEATS",
    "SILENT",
    "TOPICS",
    "VERDICTS",
    "agent_prompt",
    "archive_record",
    "close_round_if_ready",
    "handle_get",
    "handle_post",
    "new_room",
    "parse_message",
    "public_view",
    "record_message",
    "record_vote",
    "reset",
    "results",
    "reveal_if_ready",
]
