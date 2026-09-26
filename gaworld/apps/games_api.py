"""Dashboard backend for the 游戏场 (Agent Playground).

The playground is a *hub*: one place where a user plays short, interactive
games against the residents of a city. Four games live there today:

* **斗兽场 (Agent Arena)** — unchanged, and still served by
  :mod:`gaworld.apps.arena_api` under ``/api/arena/*``. The playground only
  links to it; moving its routes would break every existing caller.
* **说服游戏 (Persuasion)** — implemented here. Pick one resident, ask a
  question, read the answer, then chat for at most *N* turns trying to move
  them. Re-asking the original question at the end decides the game: a judge
  LLM compares the first answer with the last one, and a real change of
  position is a win.
* **灾害模式 (Disaster Mode)** — a batch of residents live through a disaster
  stage by stage. Big enough to deserve its own module, so this one only
  forwards ``/api/games/disaster/*`` to :mod:`gaworld.apps.disaster_api`.
* **谣言扩散局 (Rumor Spread)** — a rumor moves through a network derived from
  the roster, and the run reports the diffusion tree. Same arrangement:
  ``/api/games/rumor/*`` forwards to :mod:`gaworld.apps.rumor_api`.

Adding another game means adding a ``/api/games/<game>/*`` branch in
:func:`handle_get` / :func:`handle_post` plus a page under
``site/dashboard/``; the hub page is static markup, so nothing here has to
know about the catalogue.

Notes, mirroring the conventions in :mod:`gaworld.apps.arena_api`:

* Sessions live in memory only. The playground never writes to a city
  bundle — a game is a sandbox, not a simulation run — so restarting the
  dashboard clears the board.
* Every LLM call goes through a function that tests replace (``answer_fn``,
  ``judge_fn``). Nothing at import time touches
  :mod:`gaworld.llm.providers`, so a missing API key does not block tests.
* The roster and the persona come from :mod:`gaworld.interview.roster`,
  which already knows how a city's ``agents.csv`` + ``profiles.md`` are laid
  out and that ``""`` means the default world.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.games_api")

#: Chat rounds allowed in one persuasion session when the caller says nothing.
DEFAULT_MAX_TURNS = 5
#: Hard ceiling. A session is one prompt per turn plus two at settlement, so
#: an unbounded ``max_turns`` is an unbounded bill.
MAX_TURNS_LIMIT = 20
#: How much of the profile Markdown goes into the persona block. Long enough
#: for personality + values (the parts that decide whether somebody budges),
#: short enough that the transcript still fits alongside it.
PERSONA_CHARS = 1500

_MAX_SESSIONS = 50


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_answer_llm(prompt: str) -> str:
    """The resident's voice — warm enough to argue back."""
    return _call_llm(prompt, task="games.persuasion", temperature=0.7)


def _default_judge_llm(prompt: str) -> str:
    """The referee — deterministic on purpose."""
    return _call_llm(prompt, task="games.persuasion.judge", temperature=0.0)


# ---------------------------------------------------------------------------
# Structured replies
# ---------------------------------------------------------------------------


def first_json_object(text: Any) -> dict[str, Any]:
    """The first complete JSON object in a model reply, or ``{}``.

    A depth scan rather than a regex, because the two ways a reply goes wrong
    are both fatal to a ``{...}`` match: a stray closing brace (``{"a": 1}}``) and
    a sentence after the object. Greedy matching swallows the junk and fails;
    non-greedy stops at the first ``}`` and fails on any nested object. This
    walks the braces, honours strings, and returns the first balanced object
    that actually parses — a fenced ```json block included, since the fence
    contains no braces of its own.

    Shared by every playground game that asks for structured output.
    """
    if not isinstance(text, str):
        return {}
    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        payload = json.loads(text[start : index + 1])
                    except ValueError:
                        break
                    return payload if isinstance(payload, dict) else {}
        start = text.find("{", start + 1)
    return {}


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


def list_agents(city: str) -> list[dict[str, Any]]:
    """Residents of *city* that can be picked as an opponent.

    ``residence`` is the 小区 they live in — the rumor game groups the picker
    by it, because ties (and therefore a rumor) travel through addresses.
    """
    from gaworld.interview.roster import load_population

    return [
        {
            "id": person["id"],
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "job": person["job"],
            "residence": person["residence"],
        }
        for person in load_population(city)
    ]


def load_persona(city: str, agent_id: int) -> dict[str, Any]:
    """Persona card for one resident: the CSV row plus their profile block."""
    from gaworld.interview.roster import load_population, profile_block

    people = {int(person["id"]): person for person in load_population(city)}
    person = people.get(int(agent_id))
    if person is None:
        raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
    return {
        "agent_id": int(agent_id),
        "name": person["name"],
        "age": person["age"],
        "gender": person["gender"],
        "job": person["job"],
        "profile_md": profile_block(city, int(agent_id)),
    }


def persona_block(persona: dict[str, Any]) -> str:
    """Render the persona card as the system-style preamble of every prompt.

    Public because every game in the playground needs the same preamble —
    :mod:`gaworld.apps.disaster_api` and :mod:`gaworld.apps.rumor_api` build
    their prompts on top of it.
    """
    head = (
        f"你是{persona.get('name') or '这位居民'}，"
        f"{persona.get('age') or ''}岁，{persona.get('gender') or ''}。"
    )
    job = str(persona.get("job") or "").strip()
    if job:
        head += f"职业：{job}。"
    profile = str(persona.get("profile_md") or "").strip()
    if not profile:
        return head
    return head + "\n\n你的详细档案：\n" + profile[:PERSONA_CHARS]


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_VOICE_RULES = (
    "用第一人称说话，像真人聊天一样。不要扮演助手，不要说「作为一个 AI」，不要罗列要点，不要复述对方的话。"
)


def _opening_prompt(persona: dict[str, Any], question: str) -> str:
    return (
        f"{persona_block(persona)}\n\n"
        "现在有人问你下面这个问题。请按你自己的立场回答：先给出明确的答案，再用一两句话说明理由。\n"
        f"{_VOICE_RULES}\n"
        "回答控制在 120 字以内。\n\n"
        f"问题：{question}"
    )


def _transcript(messages: list[dict[str, Any]]) -> str:
    lines = []
    for item in messages:
        who = "对方" if item["role"] == "player" else "你"
        lines.append(f"{who}：{item['text']}")
    return "\n".join(lines) or "（还没有对话）"


def _reply_prompt(session: PersuasionSession) -> str:
    return (
        f"{persona_block(session.persona)}\n\n"
        "你正在和一个人聊天，对方在试图说服你改变看法。\n"
        "你不是一个容易被说服的人：只有当对方的理由真正打动你——贴合你的处境、价值观、利害关系——"
        "你才会松口甚至改变主意；否则就坚持己见，并说清你为什么不认同。不要为了客气而附和。\n"
        f"{_VOICE_RULES}\n"
        "回应控制在 100 字以内。\n\n"
        f"最初的问题：{session.question}\n"
        f"你最初的回答：{session.initial_answer}\n\n"
        f"到目前为止的对话：\n{_transcript(session.messages)}\n\n"
        "请回应对方最新的这句话。"
    )


def _final_prompt(session: PersuasionSession) -> str:
    return (
        f"{persona_block(session.persona)}\n\n"
        f"最初有人问你：{session.question}\n"
        f"你当时的回答是：{session.initial_answer}\n\n"
        f"随后你们有了这样一段对话：\n{_transcript(session.messages)}\n\n"
        "现在请重新回答最初那个问题。如果这段对话确实改变了你的想法，就说出你新的答案；"
        "如果没有，就照旧。诚实一点——被说动了就承认，没被说动也不必勉强。\n"
        f"{_VOICE_RULES}\n"
        "回答控制在 120 字以内。"
    )


def _judge_prompt(question: str, initial_answer: str, final_answer: str) -> str:
    return (
        "你是一名严格的裁判，判断一个人在一段对话之后，对同一个问题的立场是否发生了**实质**改变。\n"
        "判定规则：\n"
        " - 核心结论变了（是→否、支持→反对、选 A →选 B、拒绝→接受）→ changed=true\n"
        " - 只是措辞、语气不同，或补充了细节、做了让步但结论不变 → changed=false\n"
        ' 只允许输出形如 {"changed": true, "reason": "一句话理由"} 的 JSON 对象，不要解释。\n\n'
        f"问题：{question}\n"
        f"最初的回答：{initial_answer}\n"
        f"最终的回答：{final_answer}\n"
    )


def judge_change(
    question: str,
    initial_answer: str,
    final_answer: str,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> tuple[bool, str]:
    """Did the resident's position actually move? ``(changed, reason)``."""
    fn = llm_fn or _default_judge_llm
    try:
        raw = fn(_judge_prompt(question, initial_answer, final_answer))
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("persuasion judge call failed: %s", exc)
        return False, f"裁判调用失败：{exc}"
    try:
        payload = json.loads(raw)
        return bool(payload.get("changed")), str(payload.get("reason") or "")
    except (ValueError, TypeError, AttributeError):
        # Tolerate a provider that wraps the verdict in prose.
        text = str(raw).lower()
        return ('"changed": true' in text or "changed: true" in text), str(raw).strip()[:200]


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


@dataclass
class PersuasionSession:
    id: str
    city: str
    persona: dict[str, Any]
    question: str
    max_turns: int
    initial_answer: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    outcome: str = ""  # "" while open, then "success" / "failed"
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def agent_id(self) -> int:
        return int(self.persona["agent_id"])

    @property
    def turns_used(self) -> int:
        return sum(1 for item in self.messages if item["role"] == "player")

    @property
    def settled(self) -> bool:
        return self.outcome != ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "city": self.city,
            "agent_id": self.agent_id,
            "agent_name": self.persona.get("name") or f"#{self.agent_id}",
            "question": self.question,
            "initial_answer": self.initial_answer,
            "max_turns": self.max_turns,
            "turns_used": self.turns_used,
            "turns_left": max(0, self.max_turns - self.turns_used),
            "messages": list(self.messages),
            "final_answer": self.final_answer,
            "outcome": self.outcome,
            "reason": self.reason,
            "status": "settled" if self.settled else "open",
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


_SESSIONS: dict[str, PersuasionSession] = {}
_SESSIONS_LOCK = threading.Lock()


def _store(session: PersuasionSession) -> None:
    with _SESSIONS_LOCK:
        _SESSIONS[session.id] = session
        settled = [(s.created_at, key) for key, s in _SESSIONS.items() if s.settled]
        while len(_SESSIONS) > _MAX_SESSIONS and settled:
            settled.sort()
            _, oldest = settled.pop(0)
            _SESSIONS.pop(oldest, None)


def _require(session_id: str) -> PersuasionSession:
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(str(session_id))
    if session is None:
        raise KeyError(session_id)
    return session


def get_session(session_id: str) -> dict[str, Any] | None:
    try:
        return _require(session_id).to_dict()
    except KeyError:
        return None


def list_sessions() -> list[dict[str, Any]]:
    """Open games first, newest first inside each group."""
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
    sessions.sort(key=lambda s: (s.settled, -s.created_at))
    return [
        {
            "id": s.id,
            "city": s.city,
            "agent_id": s.agent_id,
            "agent_name": s.persona.get("name") or f"#{s.agent_id}",
            "question": s.question,
            "turns_used": s.turns_used,
            "max_turns": s.max_turns,
            "status": "settled" if s.settled else "open",
            "outcome": s.outcome,
            "created_at": s.created_at,
        }
        for s in sessions
    ]


def reset_sessions() -> None:
    """Drop every session. Used by tests; production code never calls it."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


def start_session(
    *,
    city: str,
    agent_id: int,
    question: str,
    max_turns: int = DEFAULT_MAX_TURNS,
    persona: dict[str, Any] | None = None,
    answer_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Ask the opening question and open a session on the answer."""
    question = str(question or "").strip()
    if not question:
        raise ValueError("请先提一个问题")
    turns = max(1, min(int(DEFAULT_MAX_TURNS if max_turns is None else max_turns), MAX_TURNS_LIMIT))
    card = persona if persona is not None else load_persona(city, agent_id)
    answer = answer_fn or _default_answer_llm

    session = PersuasionSession(
        id=f"persuade-{uuid.uuid4().hex[:8]}",
        city=str(city or ""),
        persona=card,
        question=question,
        max_turns=turns,
    )
    session.initial_answer = str(answer(_opening_prompt(card, question))).strip()
    _store(session)
    return session.to_dict()


def send_message(
    session_id: str,
    message: str,
    *,
    answer_fn: Callable[[str], str] | None = None,
    judge_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Play one chat turn; settle automatically when the last turn is used."""
    session = _require(session_id)
    message = str(message or "").strip()
    if not message:
        raise ValueError("说点什么吧")
    if session.settled:
        raise ValueError("这一局已经结束了")
    if session.turns_used >= session.max_turns:
        raise ValueError("聊天轮数已经用完，请点「复问并结算」")

    answer = answer_fn or _default_answer_llm
    session.messages.append({"role": "player", "text": message, "at": time.time()})
    reply = str(answer(_reply_prompt(session))).strip()
    session.messages.append({"role": "agent", "text": reply, "at": time.time()})

    if session.turns_used >= session.max_turns:
        return settle(session.id, answer_fn=answer_fn, judge_fn=judge_fn)
    return session.to_dict()


def settle(
    session_id: str,
    *,
    answer_fn: Callable[[str], str] | None = None,
    judge_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Re-ask the original question and score the game."""
    session = _require(session_id)
    if session.settled:
        return session.to_dict()
    answer = answer_fn or _default_answer_llm

    session.final_answer = str(answer(_final_prompt(session))).strip()
    changed, reason = judge_change(
        session.question,
        session.initial_answer,
        session.final_answer,
        llm_fn=judge_fn,
    )
    session.outcome = "success" if changed else "failed"
    session.reason = reason
    session.finished_at = time.time()
    return session.to_dict()


# ---------------------------------------------------------------------------
# HTTP delegation
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    if path.startswith("/api/games/disaster/"):
        from gaworld.apps import disaster_api

        return disaster_api.handle_get(path, query)
    if path.startswith("/api/games/rumor/"):
        from gaworld.apps import rumor_api

        return rumor_api.handle_get(path, query)
    try:
        if path == "/api/games/agents":
            return {"agents": list_agents(_one(query, "city"))}, 200
        if path == "/api/games/persuasion/sessions":
            return {"sessions": list_sessions()}, 200
        if path.startswith("/api/games/persuasion/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            record = get_session(session_id)
            if record is None:
                return {"error": "Unknown session"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("games GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown games endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    if path.startswith("/api/games/disaster/"):
        from gaworld.apps import disaster_api

        return disaster_api.handle_post(path, payload)
    if path.startswith("/api/games/rumor/"):
        from gaworld.apps import rumor_api

        return rumor_api.handle_post(path, payload)
    try:
        if path == "/api/games/persuasion/start":
            return start_session(
                city=str(payload.get("city") or ""),
                agent_id=int(payload.get("agent_id") or 0),
                question=str(payload.get("question") or ""),
                max_turns=int(payload.get("max_turns") or DEFAULT_MAX_TURNS),
            ), 200
        if path == "/api/games/persuasion/say":
            return send_message(
                str(payload.get("session_id") or ""),
                str(payload.get("message") or ""),
            ), 200
        if path == "/api/games/persuasion/settle":
            return settle(str(payload.get("session_id") or "")), 200
    except KeyError:
        return {"error": "Unknown session"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("games POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown games endpoint"}, 404


def _one(query: dict[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


__all__ = [
    "DEFAULT_MAX_TURNS",
    "MAX_TURNS_LIMIT",
    "PersuasionSession",
    "first_json_object",
    "get_session",
    "handle_get",
    "handle_post",
    "judge_change",
    "list_agents",
    "list_sessions",
    "load_persona",
    "persona_block",
    "reset_sessions",
    "send_message",
    "settle",
    "start_session",
]
