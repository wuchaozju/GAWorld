"""Serious games (严肃游戏): a description in, a playable game out.

The researcher writes a paragraph — "a neighbourhood committee, the property
company and three residents negotiate a garbage-sorting fee over five
rounds" — and a model compiles it into a structured game:

    description
      → design prompt → JSON spec (setting, roles with public / private
        briefs, indicators, rounds, scoring criteria, debrief questions)
      → validated into a plain dict (``normalize_spec``)
      → a session seats every role with either a resident or a human
      → per round: every seat acts at once (agents by model call, humans
        through the browser); when all actions are in, a facilitator call
        narrates the outcome and moves the indicators
      → after the last round, a debrief call scores each role per criterion
        and answers the debrief questions

As in :mod:`gaworld.research.workbench`, the model emits **JSON, not prose**,
and everything after the parse is defensive: a missing field costs an empty
line, not a failed game.

Rounds are simultaneous on purpose. A human sitting at the table cannot be
asked to wait for six model calls in a row before their turn, and agents
acting in sequence would see each other's move inside the round while the
humans would not. Everyone acts on the same history; the facilitator
resolves the round as a whole.

A resident who plays a role keeps their own persona: the prompt is their
profile first and the role brief second, so a cautious hairdresser plays
the property manager as a cautious hairdresser would. That is the point of
seating residents rather than a bare model.

Everything lives under ``output/research/serious_games/`` — designs as
``<id>.json``, sessions as ``sessions/<id>.json``. Nothing is ever written
back into a city bundle. This module owns no threads and no HTTP; the
dashboard delegate (:mod:`gaworld.apps.serious_game_api`) drives it.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.research.serious_game")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAMES_DIRNAME = "output/research/serious_games"

MAX_DESCRIPTION_CHARS = 8_000
MIN_ROLES, MAX_ROLES = 2, 8
MAX_ROUNDS = 10
DEFAULT_ROUNDS = 4
MAX_INDICATORS = 5
MAX_ACTION_CHARS = 600
#: Score scale used by the debrief: 1 (poor) … 5 (excellent).
SCORE_MAX = 5

SEAT_KINDS = ("agent", "human")
#: Session lifecycle. ``acting`` = the round is open; ``resolving`` and
#: ``debriefing`` = a model call is in flight; ``finished`` / ``failed`` are final.
STATUSES = ("acting", "resolving", "debriefing", "finished", "failed")

LLMFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int = 1200) -> str:
    return str(value or "").strip()[:limit]


def _texts(value: Any, limit: int = 12, chars: int = 400) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [t for t in (_text(v, chars) for v in value) if t][:limit]


def _slug(value: Any, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return slug[:32] or fallback


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_json(raw: Any) -> dict[str, Any]:
    from gaworld.apps.games_api import first_json_object

    return first_json_object(raw)


# ---------------------------------------------------------------------------
# Design: description → spec
# ---------------------------------------------------------------------------

_SPEC_SCHEMA = """{
  "title": "游戏名",
  "summary": "一两句话：这个游戏在模拟什么",
  "learning_objectives": ["玩家玩完应该体会到/学到的东西"],
  "setting": "背景设定：时间、地点、局面、利害关系（200 字以内）",
  "roles": [
    {"id": "英文小写短标识", "name": "角色名", "public": "所有人都知道的身份与立场",
     "goal": "这个角色想达成的目标", "private": "只有该角色知道的信息、底线或约束",
     "suggested_player": "适合由怎样的人来扮演（年龄/职业/性格）"}
  ],
  "indicators": [
    {"id": "英文小写短标识", "name": "指标名", "initial": 50, "min": 0, "max": 100,
     "description": "这个数字代表什么"}
  ],
  "rounds": [
    {"title": "本轮标题", "event": "这一轮开始时发生的事", "prompt": "这一轮每个角色要做的决定",
     "options": ["可选的做法（可以为空数组，表示自由行动）"]}
  ],
  "scoring": [{"criterion": "评分维度", "description": "怎样算做得好"}],
  "debrief_questions": ["复盘时要讨论的问题"]
}"""


def design_prompt(description: str, *, rounds: int = 0, roles: int = 0) -> str:
    wants = []
    if rounds:
        wants.append(f"正好 {rounds} 轮")
    if roles:
        wants.append(f"正好 {roles} 个角色")
    shape = (
        ("；".join(wants) + "。")
        if wants
        else (f"轮数 2–{MAX_ROUNDS}（通常 {DEFAULT_ROUNDS} 轮），角色 {MIN_ROLES}–{MAX_ROLES} 个。")
    )
    return (
        "你是一位严肃游戏（serious game）设计师，擅长把社会议题做成角色扮演、多方博弈的桌面推演。\n"
        "下面是研究者对想要的游戏的描述。请把它设计成一个可以直接开玩的回合制游戏：\n"
        "- 每个角色有公开身份、自己的目标和只有自己知道的私密信息，目标之间要有真实的张力，不能有显然的最优解；\n"
        "- 每一轮所有角色同时行动，所以每轮的事件和决定要让每个角色都有事可做；\n"
        f"- 指标 0–{MAX_INDICATORS} 个，是主持人每轮根据大家的行动调整的公共数值；\n"
        "- 评分维度对应学习目标，复盘问题帮助玩家反思。\n"
        f"规模：{shape}\n"
        "参与者可能是真人，也可能是模拟城市里的居民智能体，文字要让普通人一读就懂。\n\n"
        f"【研究者的描述】\n{description}\n\n"
        "只输出一个 JSON 对象，不要任何解释，结构如下：\n"
        f"{_SPEC_SCHEMA}"
    )


def normalize_spec(data: dict[str, Any]) -> dict[str, Any]:
    """Validate a model's (or a user's) spec into the shape the game runs on.

    Raises ``ValueError`` only when the game would be unplayable — fewer than
    two roles or no rounds. Everything else is trimmed, clamped or defaulted.
    """
    if not isinstance(data, dict):
        raise ValueError("游戏设计不是一个 JSON 对象")

    roles: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_roles = data.get("roles") or []
    if isinstance(raw_roles, dict):  # {"role_id": {...}} — seen from some models
        raw_roles = [{"id": key, **value} for key, value in raw_roles.items() if isinstance(value, dict)]
    for index, raw in enumerate(raw_roles if isinstance(raw_roles, list) else []):
        name = (
            _text(raw.get("name") or raw.get("title") or raw.get("role"), 40) if isinstance(raw, dict) else ""
        )
        if not name:
            continue
        role_id = _slug(raw.get("id"), f"r{index + 1}")
        while role_id in seen:
            role_id = f"{role_id}_{index + 1}"
        seen.add(role_id)
        roles.append(
            {
                "id": role_id,
                "name": name,
                "public": _text(raw.get("public"), 400),
                "goal": _text(raw.get("goal"), 400),
                "private": _text(raw.get("private"), 600),
                "suggested_player": _text(raw.get("suggested_player"), 200),
            }
        )
    roles = roles[:MAX_ROLES]
    if len(roles) < MIN_ROLES:
        raise ValueError(f"游戏至少要有 {MIN_ROLES} 个角色")

    indicators: list[dict[str, Any]] = []
    for index, raw in enumerate(data.get("indicators") or []):
        if not isinstance(raw, dict) or not _text(raw.get("name")):
            continue
        low = _num(raw.get("min"), 0.0)
        high = _num(raw.get("max"), 100.0)
        if high <= low:
            low, high = 0.0, 100.0
        initial = min(high, max(low, _num(raw.get("initial"), (low + high) / 2)))
        indicators.append(
            {
                "id": _slug(raw.get("id"), f"i{index + 1}"),
                "name": _text(raw.get("name"), 30),
                "initial": initial,
                "min": low,
                "max": high,
                "description": _text(raw.get("description"), 200),
            }
        )
    indicators = indicators[:MAX_INDICATORS]

    rounds: list[dict[str, Any]] = []
    for index, raw in enumerate(data.get("rounds") or []):
        if not isinstance(raw, dict):
            continue
        event = _text(raw.get("event"), 800)
        prompt = _text(raw.get("prompt"), 400)
        if not event and not prompt:
            continue
        rounds.append(
            {
                "title": _text(raw.get("title"), 40) or f"第 {index + 1} 轮",
                "event": event,
                "prompt": prompt or "你这一轮怎么做？",
                "options": _texts(raw.get("options"), limit=6, chars=120),
            }
        )
    rounds = rounds[:MAX_ROUNDS]
    if not rounds:
        raise ValueError("游戏至少要有一轮")

    scoring = []
    for raw in data.get("scoring") or []:
        if isinstance(raw, dict) and _text(raw.get("criterion")):
            scoring.append(
                {
                    "criterion": _text(raw.get("criterion"), 40),
                    "description": _text(raw.get("description"), 200),
                }
            )
        elif isinstance(raw, str) and raw.strip():
            scoring.append({"criterion": _text(raw, 40), "description": ""})
    if not scoring:
        scoring = [{"criterion": "达成目标", "description": "离自己角色的目标有多近"}]

    return {
        "title": _text(data.get("title"), 80) or "未命名的严肃游戏",
        "summary": _text(data.get("summary"), 400),
        "learning_objectives": _texts(data.get("learning_objectives"), limit=8),
        "setting": _text(data.get("setting"), 1500),
        "roles": roles,
        "indicators": indicators,
        "rounds": rounds,
        "scoring": scoring[:6],
        "debrief_questions": _texts(data.get("debrief_questions"), limit=8),
    }


def design_game(
    description: str,
    llm_fn: LLMFn,
    *,
    rounds: int = 0,
    roles: int = 0,
    provider: str = "",
) -> dict[str, Any]:
    """One model call: description → a saved game design."""
    description = _text(description, MAX_DESCRIPTION_CHARS)
    if not description:
        raise ValueError("先写一段游戏描述")
    rounds = max(0, min(MAX_ROUNDS, int(rounds or 0)))
    roles = 0 if not roles else max(MIN_ROLES, min(MAX_ROLES, int(roles)))
    prompt = design_prompt(description, rounds=rounds, roles=roles)
    spec: dict[str, Any] | None = None
    problem = ""
    # One retry: a long JSON answer goes wrong now and then (cut short, a
    # section renamed), and a second sample usually does not.
    for _attempt in range(2):
        payload = parse_json(
            llm_fn(
                prompt
                if not problem
                else f"{prompt}\n\n上一次的输出不能用：{problem}。请严格按结构重新输出。"
            )
        )
        if not payload:
            problem = "没有返回可解析的 JSON"
            continue
        try:
            spec = normalize_spec(payload)
            break
        except ValueError as exc:
            problem = str(exc)
    if spec is None:
        raise ValueError(f"模型两次都没给出能玩的设计（{problem}），换个模型或再试一次")
    game = {
        "id": _new_id("sg"),
        "description": description,
        "provider": provider,
        "created_at": time.time(),
        "spec": spec,
    }
    save_game(game)
    return game


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def new_session(
    game: dict[str, Any],
    seats: list[dict[str, Any]],
    *,
    city: str = "",
    provider: str = "",
    persona_fn: Callable[[str, int | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Seat every role and open round one. No model call.

    *seats* is ``[{"role_id", "kind": "agent"|"human", "agent_id"?, "player_name"?}]``;
    a role missing from it is seated with a random resident. *persona_fn*
    resolves ``(city, agent_id or None)`` to a persona card and is injected
    so tests need no city bundle.
    """
    spec = game["spec"]
    by_role = {str(s.get("role_id") or ""): s for s in seats if isinstance(s, dict)}
    taken: set[int] = set()
    seated: list[dict[str, Any]] = []
    for role in spec["roles"]:
        wanted = by_role.get(role["id"], {})
        kind = str(wanted.get("kind") or "agent")
        if kind not in SEAT_KINDS:
            raise ValueError(f"座位类型只能是 agent 或 human：{kind}")
        seat: dict[str, Any] = {"role_id": role["id"], "kind": kind, "token": secrets.token_urlsafe(9)}
        if kind == "human":
            seat["player_name"] = _text(wanted.get("player_name"), 30) or f"玩家·{role['name']}"
        else:
            raw_agent = wanted.get("agent_id")
            agent_id = int(raw_agent) if raw_agent not in (None, "") else None
            if persona_fn is None:
                persona = resident_persona(city, agent_id, taken=taken)
            else:
                persona = persona_fn(city, agent_id)
            if persona.get("agent_id") is not None:
                taken.add(int(persona["agent_id"]))
            seat["persona"] = persona
            seat["player_name"] = str(persona.get("name") or role["name"])
        seated.append(seat)

    session = {
        "id": _new_id("sgs"),
        "game_id": game["id"],
        "title": spec["title"],
        "city": str(city or ""),
        "provider": str(provider or ""),
        "spec": spec,
        "seats": seated,
        "indicators": {ind["id"]: ind["initial"] for ind in spec["indicators"]},
        "round_index": 0,
        "actions": {},
        "rounds": [],
        "debrief": None,
        "status": "acting",
        "error": "",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    return session


def resident_persona(city: str, agent_id: int | None, *, taken: set[int]) -> dict[str, Any]:
    """A resident's persona card; ``agent_id=None`` picks one not yet seated."""
    import random

    from gaworld.apps.games_api import load_persona
    from gaworld.interview.roster import load_population

    if agent_id is None:
        people = [p for p in load_population(city) if int(p["id"]) not in taken]
        if not people:
            raise ValueError(f"城市 {city or '默认世界'} 里没有可用的居民")
        agent_id = int(random.choice(people)["id"])
    return load_persona(city, int(agent_id))


def role_of(session: dict[str, Any], role_id: str) -> dict[str, Any]:
    for role in session["spec"]["roles"]:
        if role["id"] == role_id:
            return role
    raise KeyError(role_id)


def seat_by_token(session: dict[str, Any], token: str) -> dict[str, Any] | None:
    for seat in session["seats"]:
        if token and seat["token"] == token:
            return seat
    return None


def current_round(session: dict[str, Any]) -> dict[str, Any] | None:
    rounds = session["spec"]["rounds"]
    index = session["round_index"]
    return rounds[index] if 0 <= index < len(rounds) else None


def pending_seats(session: dict[str, Any], kind: str | None = None) -> list[dict[str, Any]]:
    """Seats that have not acted in the open round."""
    if session["status"] != "acting":
        return []
    return [
        seat
        for seat in session["seats"]
        if seat["role_id"] not in session["actions"] and (kind is None or seat["kind"] == kind)
    ]


def record_action(
    session: dict[str, Any], role_id: str, action: str, *, choice: str = "", thought: str = ""
) -> None:
    if session["status"] != "acting":
        raise ValueError("这一轮已经结束，等下一轮开始")
    if role_id in session["actions"]:
        raise ValueError("这一轮你已经行动过了")
    action = _text(action, MAX_ACTION_CHARS)
    if not action and not choice:
        raise ValueError("写下你这一轮的行动")
    session["actions"][role_id] = {
        "action": action,
        "choice": _text(choice, 120),
        "thought": _text(thought, 300),
        "at": time.time(),
    }
    session["updated_at"] = time.time()


# ---------------------------------------------------------------------------
# Prompts for play
# ---------------------------------------------------------------------------


def _indicator_lines(session: dict[str, Any]) -> str:
    rows = []
    for ind in session["spec"]["indicators"]:
        value = session["indicators"].get(ind["id"], ind["initial"])
        rows.append(f"- {ind['name']}：{value:g}（{ind['min']:g}–{ind['max']:g}）{ind['description']}")
    return "\n".join(rows) or "（本游戏没有公共指标）"


def _history(session: dict[str, Any], *, limit: int = 6) -> str:
    if not session["rounds"]:
        return "（这是第一轮，之前还没有发生什么）"
    names = {r["id"]: r["name"] for r in session["spec"]["roles"]}
    blocks = []
    for record in session["rounds"][-limit:]:
        moves = "\n".join(
            f"  · {names.get(role_id, role_id)}：{move['choice'] + '——' if move.get('choice') else ''}{move['action']}"
            for role_id, move in record["actions"].items()
        )
        blocks.append(f"【{record['title']}】\n{moves}\n  结果：{record['narration']}")
    return "\n".join(blocks)


def _roster(session: dict[str, Any]) -> str:
    return "\n".join(f"- {r['name']}：{r['public']}" for r in session["spec"]["roles"])


def agent_prompt(session: dict[str, Any], seat: dict[str, Any]) -> str:
    from gaworld.apps.games_api import persona_block

    spec = session["spec"]
    role = role_of(session, seat["role_id"])
    rnd = current_round(session) or {}
    options = rnd.get("options") or []
    option_text = (
        "可选的做法（选一个，也可以在行动里补充细节）：\n" + "\n".join(f"- {o}" for o in options) + "\n"
        if options
        else ""
    )
    return (
        f"{persona_block(seat.get('persona') or {})}\n\n"
        f"你现在在参加一个叫「{spec['title']}」的情景推演，你扮演的角色是【{role['name']}】。"
        "用你自己的性格、经历和说话方式来演这个角色——你会怎么做就怎么做，不要演成教科书里的标准答案。\n\n"
        f"【背景】{spec['setting']}\n\n"
        f"【在场的角色】\n{_roster(session)}\n\n"
        f"【你的角色】{role['public']}\n【你的目标】{role['goal']}\n"
        f"【只有你知道的】{role['private'] or '无'}\n\n"
        f"【当前局面】\n{_indicator_lines(session)}\n\n"
        f"【之前发生的事】\n{_history(session)}\n\n"
        f"【{rnd.get('title', '')}】{rnd.get('event', '')}\n{rnd.get('prompt', '')}\n{option_text}\n"
        "所有角色这一轮同时行动，你看不到别人这轮怎么做。用第一人称写你的行动或发言，具体、不超过 120 字。\n"
        "只输出一个 JSON 对象：\n"
        '{"choice": "选了哪个做法（没有选项就留空）", "action": "你做了什么、说了什么", '
        '"thought": "一句心里话，不会公开"}'
    )


def parse_agent_action(raw: str, options: list[str]) -> dict[str, str]:
    payload = parse_json(raw)
    action = _text(payload.get("action"), MAX_ACTION_CHARS) if payload else ""
    choice = _text(payload.get("choice"), 120) if payload else ""
    thought = _text(payload.get("thought"), 300) if payload else ""
    if options and choice and choice not in options:
        choice = next((o for o in options if choice in o or o in choice), choice)
    if not action and not choice:
        action = _text(raw, MAX_ACTION_CHARS) or "（没有行动）"
    return {"action": action, "choice": choice, "thought": thought}


def resolve_prompt(session: dict[str, Any]) -> str:
    spec = session["spec"]
    rnd = current_round(session) or {}
    names = {r["id"]: r["name"] for r in spec["roles"]}
    moves = "\n".join(
        f"- {names.get(role_id, role_id)}：{move['choice'] + '——' if move.get('choice') else ''}{move['action']}"
        for role_id, move in session["actions"].items()
    )
    ind_schema = ", ".join(f'"{i["id"]}": 变化量' for i in spec["indicators"])
    role_schema = ", ".join(f'"{r["id"]}": "对该角色的影响"' for r in spec["roles"])
    return (
        f"你是情景推演「{spec['title']}」的主持人，要公正、具体地裁定这一轮的结果。\n\n"
        f"【背景】{spec['setting']}\n\n"
        f"【角色】\n"
        + "\n".join(f"- {r['name']}：{r['public']}；目标：{r['goal']}" for r in spec["roles"])
        + "\n\n"
        f"【当前指标】\n{_indicator_lines(session)}\n\n"
        f"【之前的回合】\n{_history(session)}\n\n"
        f"【本轮：{rnd.get('title', '')}】{rnd.get('event', '')}\n"
        f"【本轮各角色的行动】（同时发生）\n{moves}\n\n"
        "根据这些行动的合理后果裁定：发生了什么、各方得失、指标怎么变（变化量为正数或负数，"
        "不要让指标越界；行动没有触及的指标保持 0）。叙述 150 字以内，像新闻简报一样具体。\n"
        "只输出一个 JSON 对象：\n"
        f'{{"narration": "本轮结果", "indicator_changes": {{{ind_schema}}}, "role_outcomes": {{{role_schema}}}}}'
    )


def apply_resolution(session: dict[str, Any], raw: str) -> dict[str, Any]:
    """Close the open round with the facilitator's ruling; open the next one."""
    payload = parse_json(raw)
    spec = session["spec"]
    rnd = current_round(session) or {"title": ""}
    changes: dict[str, float] = {}
    raw_changes = _dict(payload.get("indicator_changes"))
    for ind in spec["indicators"]:
        delta = _num(raw_changes.get(ind["id"]), 0.0)
        before = session["indicators"].get(ind["id"], ind["initial"])
        after = min(ind["max"], max(ind["min"], before + delta))
        changes[ind["id"]] = round(after - before, 2)
        session["indicators"][ind["id"]] = round(after, 2)
    outcomes_raw = _dict(payload.get("role_outcomes"))
    record = {
        "index": session["round_index"],
        "title": rnd["title"],
        "event": rnd.get("event", ""),
        "actions": dict(session["actions"]),
        "narration": _text(payload.get("narration"), 1200) or _text(raw, 600) or "（主持人没有给出裁定）",
        "indicator_changes": changes,
        "indicators_after": dict(session["indicators"]),
        "role_outcomes": {r["id"]: _text(outcomes_raw.get(r["id"]), 300) for r in spec["roles"]},
    }
    session["rounds"].append(record)
    session["actions"] = {}
    session["round_index"] += 1
    session["status"] = "acting" if session["round_index"] < len(spec["rounds"]) else "debriefing"
    session["updated_at"] = time.time()
    return record


def debrief_prompt(session: dict[str, Any]) -> str:
    spec = session["spec"]
    seats = {s["role_id"]: s for s in session["seats"]}
    players = "\n".join(
        f"- {r['name']}（{'真人' if seats[r['id']]['kind'] == 'human' else '居民智能体'}·"
        f"{seats[r['id']]['player_name']}）：目标是{r['goal']}"
        for r in spec["roles"]
    )
    criteria = "\n".join(f"- {c['criterion']}：{c['description']}" for c in spec["scoring"])
    score_schema = ", ".join(f'"{c["criterion"]}": 1到{SCORE_MAX}的整数' for c in spec["scoring"])
    return (
        f"情景推演「{spec['title']}」结束了，你是复盘引导师。\n\n"
        f"【背景】{spec['setting']}\n\n【学习目标】\n"
        + "\n".join(f"- {o}" for o in spec["learning_objectives"])
        + f"\n\n【参与者】\n{players}\n\n【全部回合】\n{_history(session, limit=MAX_ROUNDS)}\n\n"
        f"【最终指标】\n{_indicator_lines(session)}\n\n【评分维度】\n{criteria}\n\n"
        "请依据各角色在回合中的实际行动做复盘：给每个角色按每个维度打分并说明依据，"
        "逐条评估学习目标是否达成，回答复盘问题，最后给出研究者可以带走的洞见。\n"
        "复盘问题：\n" + "\n".join(f"- {q}" for q in spec["debrief_questions"]) + "\n\n"
        "只输出一个 JSON 对象：\n"
        '{"summary": "整局一段话总结", '
        f'"scores": [{{"role_id": "角色id", "scores": {{{score_schema}}}, "comment": "依据"}}], '
        '"objectives": [{"objective": "学习目标", "met": "yes|partly|no", "evidence": "依据"}], '
        '"answers": [{"question": "复盘问题", "answer": "回答"}], '
        '"insights": ["洞见"]}'
    )


def apply_debrief(session: dict[str, Any], raw: str) -> dict[str, Any]:
    payload = parse_json(raw)
    spec = session["spec"]
    role_ids = {r["id"] for r in spec["roles"]}
    criteria = [c["criterion"] for c in spec["scoring"]]
    scores = []
    for item in payload.get("scores") or []:
        if not isinstance(item, dict) or item.get("role_id") not in role_ids:
            continue
        raw_scores = _dict(item.get("scores"))
        values = {c: int(min(SCORE_MAX, max(1, round(_num(raw_scores.get(c), 0) or 1)))) for c in criteria}
        scores.append(
            {
                "role_id": item["role_id"],
                "scores": values,
                "total": sum(values.values()),
                "comment": _text(item.get("comment"), 400),
            }
        )
    objectives = [
        {
            "objective": _text(o.get("objective"), 200),
            "met": o.get("met") if o.get("met") in ("yes", "partly", "no") else "partly",
            "evidence": _text(o.get("evidence"), 400),
        }
        for o in payload.get("objectives") or []
        if isinstance(o, dict) and _text(o.get("objective"))
    ]
    answers = [
        {"question": _text(a.get("question"), 200), "answer": _text(a.get("answer"), 800)}
        for a in payload.get("answers") or []
        if isinstance(a, dict) and _text(a.get("answer"))
    ]
    debrief = {
        "summary": _text(payload.get("summary"), 1500) or _text(raw, 800),
        "scores": scores,
        "objectives": objectives,
        "answers": answers,
        "insights": _texts(payload.get("insights"), limit=8, chars=400),
    }
    session["debrief"] = debrief
    session["status"] = "finished"
    session["updated_at"] = time.time()
    return debrief


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def public_view(session: dict[str, Any], *, seat_token: str = "", host: bool = False) -> dict[str, Any]:
    """The session as one viewer may see it.

    Every viewer sees the public side: the setting, the public role cards,
    the closed rounds, the indicators, who still has to act. A seat token adds
    that seat's private brief; the host (the researcher's own panel) sees all
    private briefs, the agents' unspoken thoughts and the seat tokens it needs
    to hand out join links. Nobody sees another player's move in the open
    round — the round is simultaneous.
    """
    spec = session["spec"]
    me = seat_by_token(session, seat_token)
    pending = {s["role_id"] for s in pending_seats(session)}
    roles = []
    for role in spec["roles"]:
        card = {k: role[k] for k in ("id", "name", "public", "suggested_player")}
        if host or (me and me["role_id"] == role["id"]):
            card["goal"] = role["goal"]
            card["private"] = role["private"]
        roles.append(card)
    seats = []
    for seat in session["seats"]:
        entry: dict[str, Any] = {
            "role_id": seat["role_id"],
            "kind": seat["kind"],
            "player_name": seat["player_name"],
            "acted": seat["role_id"] not in pending,
        }
        persona = seat.get("persona") or {}
        if persona:
            entry["agent"] = {k: persona.get(k) for k in ("agent_id", "name", "age", "gender", "job")}
        if host:
            entry["token"] = seat["token"]
        seats.append(entry)
    rounds = []
    for record in session["rounds"]:
        copy = dict(record)
        copy["actions"] = {
            rid: (move if host else {k: v for k, v in move.items() if k != "thought"})
            for rid, move in record["actions"].items()
        }
        rounds.append(copy)
    view: dict[str, Any] = {
        "id": session["id"],
        "game_id": session["game_id"],
        "title": session["title"],
        "city": session["city"],
        "status": session["status"],
        "error": session.get("error", ""),
        "summary": spec["summary"],
        "setting": spec["setting"],
        "learning_objectives": spec["learning_objectives"],
        "scoring": spec["scoring"],
        "indicator_defs": spec["indicators"],
        "indicators": dict(session["indicators"]),
        "roles": roles,
        "seats": seats,
        "round_index": session["round_index"],
        "round_count": len(spec["rounds"]),
        "current_round": current_round(session) if session["status"] == "acting" else None,
        "rounds": rounds,
        "debrief": session["debrief"],
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "host": host,
    }
    if me is not None:
        view["me"] = {
            "role_id": me["role_id"],
            "player_name": me["player_name"],
            "kind": me["kind"],
            "acted": me["role_id"] not in pending,
            "my_action": session["actions"].get(me["role_id"]),
        }
    if host:
        view["open_actions"] = dict(session["actions"])
    return view


def export_markdown(session: dict[str, Any]) -> str:
    spec = session["spec"]
    names = {r["id"]: r["name"] for r in spec["roles"]}
    seats = {s["role_id"]: s for s in session["seats"]}
    out = [f"# {spec['title']}", "", spec["summary"], "", "## 背景", "", spec["setting"], ""]
    if spec["learning_objectives"]:
        out += ["## 学习目标", ""] + [f"- {o}" for o in spec["learning_objectives"]] + [""]
    out += ["## 角色与参与者", "", "| 角色 | 参与者 | 公开身份 | 目标 |", "|---|---|---|---|"]
    for role in spec["roles"]:
        seat = seats.get(role["id"], {})
        who = ("真人 · " if seat.get("kind") == "human" else "居民 · ") + str(seat.get("player_name", ""))
        out.append(f"| {role['name']} | {who} | {role['public']} | {role['goal']} |")
    out.append("")
    for record in session["rounds"]:
        out += [f"## {record['title']}", "", f"> {record['event']}", ""]
        for role_id, move in record["actions"].items():
            choice = f"【{move['choice']}】" if move.get("choice") else ""
            out.append(f"- **{names.get(role_id, role_id)}**：{choice}{move['action']}")
        out += ["", f"**结果**：{record['narration']}", ""]
        moved = {k: v for k, v in record["indicator_changes"].items() if v}
        if moved:
            ind_names = {i["id"]: i["name"] for i in spec["indicators"]}
            out += ["指标变化：" + "，".join(f"{ind_names.get(k, k)} {v:+g}" for k, v in moved.items()), ""]
    debrief = session.get("debrief")
    if debrief:
        out += ["## 复盘", "", debrief["summary"], ""]
        if debrief["scores"]:
            criteria = [c["criterion"] for c in spec["scoring"]]
            out += [
                "| 角色 | " + " | ".join(criteria) + " | 总分 | 依据 |",
                "|---" * (len(criteria) + 3) + "|",
            ]
            for row in debrief["scores"]:
                cells = " | ".join(str(row["scores"].get(c, "")) for c in criteria)
                out.append(
                    f"| {names.get(row['role_id'], row['role_id'])} | {cells} | {row['total']} | {row['comment']} |"
                )
            out.append("")
        if debrief["objectives"]:
            mark = {"yes": "✅", "partly": "◐", "no": "✗"}
            out += (
                ["### 学习目标"]
                + [f"- {mark[o['met']]} {o['objective']}：{o['evidence']}" for o in debrief["objectives"]]
                + [""]
            )
        for item in debrief["answers"]:
            out += [f"### {item['question']}", "", item["answer"], ""]
        if debrief["insights"]:
            out += ["### 洞见"] + [f"- {i}" for i in debrief["insights"]] + [""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def games_root() -> Path:
    return PROJECT_ROOT / GAMES_DIRNAME


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(value or "")):
        raise KeyError(value)
    return str(value)


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_game(game: dict[str, Any]) -> None:
    _write(games_root() / f"{_safe_id(game['id'])}.json", game)


def load_game(game_id: str) -> dict[str, Any] | None:
    try:
        return _read(games_root() / f"{_safe_id(game_id)}.json")
    except KeyError:
        return None


def delete_game(game_id: str) -> bool:
    try:
        path = games_root() / f"{_safe_id(game_id)}.json"
    except KeyError:
        return False
    if not path.exists():
        return False
    path.unlink()
    return True


def list_games() -> list[dict[str, Any]]:
    root = games_root()
    rows = []
    for path in root.glob("*.json") if root.exists() else []:
        data = _read(path)
        if not data or not data.get("id"):
            continue
        spec = data.get("spec") or {}
        rows.append(
            {
                "id": data["id"],
                "title": spec.get("title", ""),
                "summary": spec.get("summary", ""),
                "roles": len(spec.get("roles") or []),
                "rounds": len(spec.get("rounds") or []),
                "created_at": data.get("created_at") or 0,
                "owner_id": data.get("owner_id"),
            }
        )
    rows.sort(key=lambda r: -r["created_at"])
    return rows


def save_session(session: dict[str, Any]) -> None:
    _write(games_root() / "sessions" / f"{_safe_id(session['id'])}.json", session)


def load_session(session_id: str) -> dict[str, Any] | None:
    try:
        return _read(games_root() / "sessions" / f"{_safe_id(session_id)}.json")
    except KeyError:
        return None


def delete_session(session_id: str) -> bool:
    try:
        path = games_root() / "sessions" / f"{_safe_id(session_id)}.json"
    except KeyError:
        return False
    if not path.exists():
        return False
    path.unlink()
    return True


def list_sessions() -> list[dict[str, Any]]:
    root = games_root() / "sessions"
    rows = []
    for path in root.glob("*.json") if root.exists() else []:
        data = _read(path)
        if not data or not data.get("id"):
            continue
        rows.append(
            {
                "id": data["id"],
                "game_id": data.get("game_id", ""),
                "title": data.get("title", ""),
                "status": data.get("status", ""),
                "round_index": data.get("round_index", 0),
                "round_count": len((data.get("spec") or {}).get("rounds") or []),
                "humans": sum(1 for s in data.get("seats") or [] if s.get("kind") == "human"),
                "agents": sum(1 for s in data.get("seats") or [] if s.get("kind") == "agent"),
                "created_at": data.get("created_at") or 0,
                "owner_id": data.get("owner_id"),
            }
        )
    rows.sort(key=lambda r: -r["created_at"])
    return rows


__all__ = [
    "DEFAULT_ROUNDS",
    "MAX_ROLES",
    "MAX_ROUNDS",
    "MIN_ROLES",
    "SEAT_KINDS",
    "STATUSES",
    "agent_prompt",
    "apply_debrief",
    "apply_resolution",
    "current_round",
    "debrief_prompt",
    "delete_game",
    "delete_session",
    "design_game",
    "design_prompt",
    "export_markdown",
    "games_root",
    "list_games",
    "list_sessions",
    "load_game",
    "load_session",
    "new_session",
    "normalize_spec",
    "parse_agent_action",
    "pending_seats",
    "public_view",
    "record_action",
    "resident_persona",
    "resolve_prompt",
    "role_of",
    "save_game",
    "save_session",
    "seat_by_token",
]
