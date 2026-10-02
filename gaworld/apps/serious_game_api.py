"""Dashboard backend for 严肃游戏 — the research workbench's serious-game tab.

Reached through :mod:`gaworld.apps.research_api`, which forwards everything
under ``/api/research/games`` here, the way ``games_api`` forwards the
guessing game.

Two things take a model call long enough that no request should wait:

* **designing** a game (description → spec) is a job on a :class:`JobStore`;
* **driving** a session — agents acting, the facilitator resolving a round,
  the debrief — runs on a daemon thread per session, started whenever the
  session might be able to move (it was created, a human acted, the host
  pressed 「不等了」). A session that has to wait for a human simply stops;
  the next human action starts the driver again.

Sessions are kept in memory while the process lives and written to disk
after every change, so a restart loses nothing but an in-flight model call:
a session found ``resolving``/``debriefing`` with no live driver is driven
again on the next read.

Model calls never run under the lock. The driver copies what it needs, makes
the call, then takes the lock to write the result — and re-checks that the
round has not moved underneath it in the meantime.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.game_jobs import JobStore
from gaworld.logging_setup import get_logger
from gaworld.research import serious_game as sg

_LOG = get_logger("gaworld.dashboard.serious_game_api")

_JOBS = JobStore("sgdesign")
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()
_DRIVING: set[str] = set()
#: Kicked while already driven; the driver goes round again before it stops.
_REKICK: set[str] = set()

#: Injected by tests; ``None`` means the configured provider via ``call_llm``.
_LLM_OVERRIDE: Callable[[str, str, str], str] | None = None

PREFIX = "/api/research/games"


def _llm(provider: str, task: str, temperature: float = 0.7, max_tokens: int = 1200) -> Callable[[str], str]:
    def call(prompt: str) -> str:
        if _LLM_OVERRIDE is not None:
            return _LLM_OVERRIDE(prompt, task, provider)
        from gaworld.llm.providers import call_llm

        return str(
            call_llm(
                prompt,
                task=f"research.serious_game.{task}",
                provider=provider or None,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )

    return call


def reset() -> None:
    """Drop in-memory state. Used by tests; production code never calls it."""
    with _LOCK:
        _SESSIONS.clear()
        _DRIVING.clear()
        _REKICK.clear()
    _JOBS.reset()


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


def start_design(payload: dict[str, Any]) -> dict[str, Any]:
    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("先写一段游戏描述")
    provider = str(payload.get("provider") or "")
    rounds = int(payload.get("rounds") or 0)
    roles = int(payload.get("roles") or 0)

    def work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        progress(0.1, "正在设计游戏…")
        game = sg.design_game(
            description,
            _llm(provider, "design", temperature=0.6, max_tokens=4000),
            rounds=rounds,
            roles=roles,
            provider=provider,
        )
        if ownership.stamp():
            game.update(ownership.stamp())
            sg.save_game(game)
        return {"game_id": game["id"], "game": game}

    return {"job_id": _JOBS.run(work)}


def _game(game_id: str) -> dict[str, Any]:
    """A game the current user may see; anyone else's is reported as missing."""
    game = sg.load_game(game_id)
    if game is None or not ownership.visible(game):
        raise KeyError(game_id)
    return game


def update_game(game_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    game = _game(game_id)
    game["spec"] = sg.normalize_spec(payload.get("spec") or {})
    sg.save_game(game)
    return game


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def _get(session_id: str) -> dict[str, Any]:
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            session = sg.load_session(session_id)
            if session is None:
                raise KeyError(session_id)
            _SESSIONS[session_id] = session
        return session


def _save(session: dict[str, Any]) -> None:
    with _LOCK:
        sg.save_session(session)


def _hosted(session_id: str) -> dict[str, Any]:
    """A session the current user hosts (or may administer)."""
    session = _get(session_id)
    if not ownership.visible(session):
        raise KeyError(session_id)
    return session


def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    game = _game(str(payload.get("game_id") or ""))
    session = sg.new_session(
        game,
        list(payload.get("seats") or []),
        city=str(payload.get("city") or ""),
        provider=str(payload.get("provider") or ""),
    )
    session.update(ownership.stamp())
    with _LOCK:
        _SESSIONS[session["id"]] = session
        _save(session)
    _kick(session["id"])
    return sg.public_view(session, host=True)


def view(session_id: str, *, seat: str = "", host: bool = False) -> dict[str, Any]:
    session = _get(session_id)
    # A seat link is the invitation: it opens that seat's view to whoever holds
    # it. Without a valid one, only the host may look.
    with _LOCK:
        by_seat = bool(seat) and sg.seat_by_token(session, seat) is not None
    if not by_seat and not ownership.visible(session):
        raise KeyError(session_id)
    host = host and not by_seat
    with _LOCK:
        stalled = session["status"] in ("resolving", "debriefing") and session_id not in _DRIVING
        data = sg.public_view(session, seat_token=seat, host=host)
    if stalled:
        _kick(session_id)
    return data


def act(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get(session_id)
    token = str(payload.get("seat") or "")
    with _LOCK:
        seat = sg.seat_by_token(session, token)
        if seat is None:
            raise ValueError("这个座位链接无效")
        if seat["kind"] != "human":
            raise ValueError("这个座位由居民智能体扮演")
        sg.record_action(
            session,
            seat["role_id"],
            str(payload.get("action") or ""),
            choice=str(payload.get("choice") or ""),
        )
        _save(session)
    _kick(session_id)
    return view(session_id, seat=token)


def force_resolve(session_id: str) -> dict[str, Any]:
    """Host gives up waiting: absent humans sit the round out."""
    session = _hosted(session_id)
    with _LOCK:
        if session["status"] != "acting":
            raise ValueError("这一轮不在等人")
        if sg.pending_seats(session, "agent"):
            raise ValueError("居民还在思考，稍等")
        for seat in sg.pending_seats(session, "human"):
            sg.record_action(session, seat["role_id"], "（这一轮没有行动）")
        _save(session)
    _kick(session_id)
    return view(session_id, host=True)


def delete_session(session_id: str) -> dict[str, Any]:
    _hosted(session_id)
    with _LOCK:
        if session_id in _DRIVING:
            raise ValueError("这局正在推进，稍后再删")
        _SESSIONS.pop(session_id, None)
        return {"deleted": sg.delete_session(session_id), "session_id": session_id}


def export(session_id: str) -> dict[str, Any]:
    session = _hosted(session_id)
    with _LOCK:
        markdown = sg.export_markdown(session)
    return {"filename": f"{session_id}.md", "markdown": markdown}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _kick(session_id: str, *, background: bool = True) -> None:
    with _LOCK:
        if session_id in _DRIVING:
            _REKICK.add(session_id)
            return
        _DRIVING.add(session_id)
    if background:
        ownership.spawn(_drive, session_id, name=f"sg-{session_id}")
    else:
        _drive(session_id)


def _drive(session_id: str) -> None:
    """Move the session as far as it can go without a human.

    A kick that arrives after ``_step`` decided to wait but before this driver
    leaves ``_DRIVING`` would otherwise be dropped, so it is honoured here.
    """
    again = True
    while again:
        try:
            while _step(session_id):
                pass
        except Exception as exc:  # pragma: no cover - surfaced through the session
            _LOG.exception("serious game %s failed", session_id)
            with _LOCK:
                session = _SESSIONS.get(session_id)
                if session is not None:
                    session["status"] = "failed"
                    session["error"] = f"{type(exc).__name__}: {exc}"
                    _save(session)
        finally:
            with _LOCK:
                again = session_id in _REKICK
                _REKICK.discard(session_id)
                if not again:
                    _DRIVING.discard(session_id)


def _step(session_id: str) -> bool:
    """One unit of progress; ``False`` when the session has to wait or is done."""
    session = _get(session_id)
    with _LOCK:
        status = session["status"]
        provider = session["provider"]
        round_index = session["round_index"]
        agent_seat = next(iter(sg.pending_seats(session, "agent")), None)
        waiting_humans = bool(sg.pending_seats(session, "human"))
        if status == "acting" and agent_seat is not None:
            prompt = sg.agent_prompt(session, agent_seat)
            options = (sg.current_round(session) or {}).get("options") or []
        elif status == "acting" and not waiting_humans:
            session["status"] = "resolving"
            _save(session)
            return True
        elif status == "resolving":
            prompt = sg.resolve_prompt(session)
        elif status == "debriefing":
            prompt = sg.debrief_prompt(session)
        else:
            return False

    if status == "acting" and agent_seat is not None:
        raw = _llm(provider, "act", temperature=0.8, max_tokens=500)(prompt)
        move = sg.parse_agent_action(raw, options)
        with _LOCK:
            if session["round_index"] != round_index or agent_seat["role_id"] in session["actions"]:
                return True
            sg.record_action(
                session, agent_seat["role_id"], move["action"], choice=move["choice"], thought=move["thought"]
            )
            _save(session)
        return True

    if status == "resolving":
        raw = _llm(provider, "resolve", temperature=0.4, max_tokens=1500)(prompt)
        with _LOCK:
            if session["status"] == "resolving" and session["round_index"] == round_index:
                sg.apply_resolution(session, raw)
                _save(session)
        return True

    raw = _llm(provider, "debrief", temperature=0.3, max_tokens=3500)(prompt)
    with _LOCK:
        if session["status"] == "debriefing":
            sg.apply_debrief(session, raw)
            _save(session)
    return False


# ---------------------------------------------------------------------------
# Routing — reached via research_api's /api/research/games branch.
# ---------------------------------------------------------------------------


def _parts(path: str) -> list[str]:
    """``/api/research/games/a/b`` → ``["a", "b"]``."""
    return [p for p in path[len(PREFIX) :].split("/") if p]


def _one(query: dict[str, Any] | None, key: str) -> str:
    value = (query or {}).get(key, "")
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    parts = _parts(path)
    try:
        if not parts:
            return {"games": ownership.owned(sg.list_games()), "sessions": ownership.owned(sg.list_sessions())}, 200
        if parts[0] == "jobs" and len(parts) == 2:
            record = _JOBS.status(parts[1])
            return (record, 200) if record else ({"error": "Unknown job"}, 404)
        if parts[0] == "sessions" and len(parts) >= 2:
            if len(parts) == 3 and parts[2] == "export":
                return export(parts[1]), 200
            seat = _one(query, "seat")
            return view(parts[1], seat=seat, host=not seat), 200
        if len(parts) == 1:
            return _game(parts[0]), 200
    except KeyError:
        return {"error": "Unknown game or session"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown serious-game endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    parts = _parts(path)
    try:
        if parts == ["design"]:
            return start_design(payload), 202
        if parts == ["sessions"]:
            return create_session(payload), 200
        if len(parts) == 3 and parts[0] == "sessions":
            session_id, action = parts[1], parts[2]
            if action == "act":
                return act(session_id, payload), 200
            if action == "resolve":
                return force_resolve(session_id), 200
            if action == "delete":
                return delete_session(session_id), 200
        if len(parts) == 2 and parts[1] == "update":
            return update_game(parts[0], payload), 200
        if len(parts) == 2 and parts[1] == "delete":
            _game(parts[0])
            return {"deleted": sg.delete_game(parts[0]), "game_id": parts[0]}, 200
    except KeyError:
        return {"error": "Unknown game or session"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown serious-game endpoint"}, 404


__all__ = [
    "act",
    "create_session",
    "delete_session",
    "export",
    "force_resolve",
    "handle_get",
    "handle_post",
    "reset",
    "start_design",
    "update_game",
    "view",
]
