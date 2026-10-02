"""Dashboard backend for 猜人局 (Read the Room), the playground's sixth game.

Everything else in the playground takes a minute and a pile of model calls.
This one is a single call and a few seconds: you read one resident's file,
you are handed a dilemma with three or four ways out, and you guess which one
they take. Then they answer, and you find out whether you actually understood
the person you have been simulating.

Three notes:

* **One call per round, and the deal is free.** Dealing a round picks the
  resident and the dilemma and returns the file — no model is touched until
  you commit to a guess. So browsing costs nothing and a wrong guess costs
  one call.
* **Letters, not sentences.** The resident answers ``{"choice": "B", ...}``
  against a fixed option list, which makes scoring exact and leaves nothing
  for a judge to do.
* **Asking again is the point, not a retry.** ``ask_again`` puts the same
  dilemma to the same resident a second and third time and records what came
  back. Three identical answers mean the persona is stable; three different
  ones mean the file is thin — and that is a measurement of the bundle worth
  having, produced by somebody playing a game.

State lives in memory only, like every other game here, and nothing is ever
written back to a city bundle.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.guess_api")

#: Rounds kept in memory. A round is small; this is about a session's worth.
MAX_ROUNDS = 100
#: Extra samples one round can collect, on top of the answer that scored it.
MAX_SAMPLES = 3
#: How much of the profile the player is shown. Enough to have an opinion,
#: short enough that reading it is part of the game rather than a chore.
FILE_CHARS = 700


# ---------------------------------------------------------------------------
# Dilemma bank
# ---------------------------------------------------------------------------

#: Built-in dilemmas. Each one splits people rather than having a right
#: answer: if the options ranked from obvious to absurd, guessing would be
#: free and the game would teach nothing.
DILEMMA_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "wallet",
        "title": "捡到钱包",
        "emoji": "👛",
        "text": "你在小区门口捡到一个钱包，里面有一千多块现金、身份证和几张卡，没有电话。你会怎么做？",
        "options": [
            {"key": "A", "text": "送到派出所"},
            {"key": "B", "text": "在小区群里发失物招领，等人来认"},
            {"key": "C", "text": "按身份证地址自己找上门还"},
            {"key": "D", "text": "先放着，看有没有人找，找不到就算了"},
        ],
    },
    {
        "id": "job",
        "title": "两份工作",
        "emoji": "💼",
        "text": "两个工作机会：一个工资高四成但通勤来回三小时、经常加班；"
        "一个工资持平、走路十分钟到、事少但几乎没有升迁空间。你选哪个？",
        "options": [
            {"key": "A", "text": "去工资高的那个"},
            {"key": "B", "text": "留在家门口这个"},
            {"key": "C", "text": "两个都不去，再等等看"},
        ],
    },
    {
        "id": "noise",
        "title": "楼上装修",
        "emoji": "🔨",
        "text": "楼上装修三个月了，天天早上七点开始砸墙，周末也不停。你会怎么办？",
        "options": [
            {"key": "A", "text": "直接上门找他们理论"},
            {"key": "B", "text": "找物业，让物业去说"},
            {"key": "C", "text": "打 12345 投诉"},
            {"key": "D", "text": "忍着，装修总会结束的"},
        ],
    },
    {
        "id": "money",
        "title": "借钱",
        "emoji": "💸",
        "text": "一个关系不错但不算太亲的亲戚开口借五万块钱，说是周转，三个月还。"
        "这笔钱你拿得出来，但会动到家里的备用金。你会怎么做？",
        "options": [
            {"key": "A", "text": "借，全额，不好意思提借条"},
            {"key": "B", "text": "借，但写借条说清还款时间"},
            {"key": "C", "text": "只借一部分，比如一两万"},
            {"key": "D", "text": "找个理由回绝"},
        ],
    },
    {
        "id": "health",
        "title": "身体不舒服",
        "emoji": "🏥",
        "text": "你连着两周有点不对劲——容易累、睡不好、偶尔胸闷。不耽误干活，但一直没好。你会怎么做？",
        "options": [
            {"key": "A", "text": "去大医院挂号做全面检查"},
            {"key": "B", "text": "先去社区医院看看"},
            {"key": "C", "text": "上网查查，先自己调理"},
            {"key": "D", "text": "不管它，忙过这阵再说"},
        ],
    },
    {
        "id": "windfall",
        "title": "一笔意外的钱",
        "emoji": "🧧",
        "text": "你突然多出十万块钱（年终奖、拆迁款或者亲戚给的）。第一反应是拿它做什么？",
        "options": [
            {"key": "A", "text": "存起来不动"},
            {"key": "B", "text": "还房贷或者其他欠款"},
            {"key": "C", "text": "拿去投资或者做点小生意"},
            {"key": "D", "text": "花掉一部分：换车、旅游、给家里添东西"},
        ],
    },
)


def list_dilemmas() -> list[dict[str, Any]]:
    return [dict(item) for item in DILEMMA_BANK]


def dilemma_by_id(dilemma_id: str) -> dict[str, Any] | None:
    for item in DILEMMA_BANK:
        if item["id"] == dilemma_id:
            return item
    return None


# ---------------------------------------------------------------------------
# LLM entry point
# ---------------------------------------------------------------------------


def _default_choice_llm(prompt: str) -> str:
    from gaworld.llm.providers import call_llm

    # Warm enough to be a person rather than an optimiser, which is also what
    # makes the repeat-sampling question interesting.
    return str(call_llm(prompt, task="games.guess", temperature=0.7, allow_fallback=True))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _choice_prompt(persona_text: str, dilemma: dict[str, Any]) -> str:
    options = "\n".join(f"{o['key']}. {o['text']}" for o in dilemma["options"])
    return (
        f"{persona_text}\n\n"
        f"【你遇到的事】{dilemma['text']}\n\n"
        f"可选的做法：\n{options}\n\n"
        "按你自己的性格、处境和习惯选一个——你真的会做的那个，不是听起来最得体的那个。"
        "钱、时间、面子、跟人打交道累不累，这些对你各有多重要，只有你自己清楚。\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"choice": "选项字母", "why": "一句话说明为什么，第一人称"}'
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_choice(raw: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    """Read one resident's pick; ``choice`` is ``""`` when nothing matched.

    Falls back to matching the option *text* when the model answers in
    prose — "我会送到派出所" is a valid answer to a human, and losing the
    round to formatting would be the wrong lesson for the player.
    """
    keys = {str(o["key"]).upper(): o for o in options}
    text = str(raw or "").strip()
    payload = first_json_object(text)
    picked = str(payload.get("choice") or "").strip().upper() if payload else ""
    why = str(payload.get("why") or "").strip()[:200] if payload else ""

    if picked not in keys:
        picked = next((key for key in keys if key in picked), "")
    if not picked:
        haystack = text or ""
        hit = next((o for o in options if o["text"] and o["text"] in haystack), None)
        picked = str(hit["key"]).upper() if hit else ""
    return {"choice": picked, "why": why or text[:120]}


# ---------------------------------------------------------------------------
# Round store
# ---------------------------------------------------------------------------

_ROUNDS: dict[str, dict[str, Any]] = {}
_ROUNDS_LOCK = threading.Lock()


def _store(record: dict[str, Any]) -> None:
    record.update(ownership.stamp())
    with _ROUNDS_LOCK:
        _ROUNDS[record["id"]] = record
        while len(_ROUNDS) > MAX_ROUNDS:
            oldest = min(_ROUNDS.values(), key=lambda r: r["created_at"])
            _ROUNDS.pop(oldest["id"], None)


def _require(round_id: str) -> dict[str, Any]:
    with _ROUNDS_LOCK:
        record = _ROUNDS.get(str(round_id))
    if record is None or not ownership.visible(record):
        raise KeyError(round_id)
    return record


def reset_rounds() -> None:
    """Drop every round. Used by tests; production code never calls it."""
    with _ROUNDS_LOCK:
        _ROUNDS.clear()


def scoreboard() -> dict[str, Any]:
    """How the player is doing this session, plus the persona-stability read."""
    with _ROUNDS_LOCK:
        records = ownership.owned(_ROUNDS.values())
    played = [r for r in records if r["guess"]]
    correct = [r for r in played if r["correct"]]
    played.sort(key=lambda r: r["created_at"])

    streak = 0
    for record in reversed(played):
        if not record["correct"]:
            break
        streak += 1
    best = 0
    running = 0
    for record in played:
        running = running + 1 if record["correct"] else 0
        best = max(best, running)

    resampled = [r for r in played if len(r["samples"]) > 1]
    stable = [r for r in resampled if len({s["choice"] for s in r["samples"]}) == 1]
    return {
        "played": len(played),
        "correct": len(correct),
        "accuracy": round(len(correct) / len(played), 2) if played else 0.0,
        "streak": streak,
        "best_streak": best,
        "resampled": len(resampled),
        "stable": len(stable),
        "history": [
            {
                "id": r["id"],
                "name": r["agent"]["name"],
                "dilemma": r["dilemma"]["title"],
                "guess": r["guess"],
                "choice": r["choice"],
                "correct": r["correct"],
                "created_at": r["created_at"],
            }
            for r in reversed(played[-20:])
        ],
    }


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


def _agent_card(city: str, agent_id: int) -> dict[str, Any]:
    from gaworld.apps.games_api import persona_block
    from gaworld.interview.roster import load_population, profile_block

    people = {int(p["id"]): p for p in load_population(city)}
    person = people.get(int(agent_id))
    if person is None:
        raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
    profile = profile_block(city, int(agent_id))
    persona = {
        "agent_id": int(agent_id),
        "name": person["name"],
        "age": person["age"],
        "gender": person["gender"],
        "job": person["job"],
        "profile_md": profile,
    }
    return {
        "agent_id": int(agent_id),
        "name": str(person["name"]),
        "age": int(person["age"] or 0),
        "gender": str(person["gender"] or ""),
        "job": str(person["job"] or ""),
        "residence": str(person["residence"] or ""),
        # What the player reads, and what the resident is prompted with: the
        # same file, so a lost round is the player's read, not missing data.
        "file": str(profile or "").strip()[:FILE_CHARS],
        "persona_text": persona_block(persona),
    }


def deal(
    *,
    city: str = "",
    agent_id: int | None = None,
    dilemma_id: str = "",
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Open a round: a resident, a dilemma, and the file. No model call."""
    chooser = rng or random
    if agent_id is None:
        from gaworld.interview.roster import load_population

        people = load_population(city)
        if not people:
            raise ValueError(f"城市 {city or '默认世界'} 里没有居民")
        agent_id = int(chooser.choice(people)["id"])

    dilemma = dilemma_by_id(dilemma_id) if dilemma_id else dict(chooser.choice(DILEMMA_BANK))
    if dilemma is None:
        raise ValueError(f"没有这个题目：{dilemma_id}")

    agent = _agent_card(city, int(agent_id))
    record = {
        "id": f"guess-{uuid.uuid4().hex[:8]}",
        "city": str(city or ""),
        "agent": agent,
        "dilemma": dict(dilemma),
        "guess": "",
        "choice": "",
        "why": "",
        "correct": False,
        "samples": [],
        "created_at": time.time(),
        "answered_at": None,
    }
    _store(record)
    return public_round(record)


def public_round(record: dict[str, Any]) -> dict[str, Any]:
    """The round as the browser sees it — persona prompt text withheld."""
    agent = {k: v for k, v in record["agent"].items() if k != "persona_text"}
    return {
        "id": record["id"],
        "city": record["city"],
        "agent": agent,
        "dilemma": record["dilemma"],
        "guess": record["guess"],
        "choice": record["choice"],
        "why": record["why"],
        "correct": record["correct"],
        "samples": list(record["samples"]),
        "settled": bool(record["guess"]),
        "created_at": record["created_at"],
        "answered_at": record["answered_at"],
    }


def answer(round_id: str, guess: str, *, llm_fn: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Lock in the guess, ask the resident, score the round."""
    record = _require(round_id)
    if record["guess"]:
        raise ValueError("这一局已经猜过了")
    keys = {str(o["key"]).upper() for o in record["dilemma"]["options"]}
    guess = str(guess or "").strip().upper()
    if guess not in keys:
        raise ValueError("先选一个选项")

    sample = _sample(record, llm_fn)
    record["guess"] = guess
    record["choice"] = sample["choice"]
    record["why"] = sample["why"]
    record["correct"] = bool(sample["choice"]) and sample["choice"] == guess
    record["answered_at"] = time.time()
    return public_round(record)


def ask_again(round_id: str, *, llm_fn: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Put the same dilemma to the same resident again (consistency check)."""
    record = _require(round_id)
    if not record["guess"]:
        raise ValueError("先猜一次再说")
    if len(record["samples"]) >= MAX_SAMPLES:
        raise ValueError(f"最多问 {MAX_SAMPLES} 次")
    _sample(record, llm_fn)
    return public_round(record)


def _sample(record: dict[str, Any], llm_fn: Callable[[str], str] | None) -> dict[str, Any]:
    ask = llm_fn or _default_choice_llm
    prompt = _choice_prompt(record["agent"]["persona_text"], record["dilemma"])
    try:
        raw = ask(prompt)
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("guess round %s failed: %s", record["id"], exc)
        raw = ""
    sample = parse_choice(raw, record["dilemma"]["options"])
    sample["at"] = time.time()
    record["samples"].append(sample)
    return sample


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/guess/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/games/guess/catalogue":
            return {"dilemmas": list_dilemmas(), "max_samples": MAX_SAMPLES}, 200
        if path == "/api/games/guess/scoreboard":
            return scoreboard(), 200
        if path.startswith("/api/games/guess/rounds/"):
            try:
                return public_round(_require(path.rsplit("/", 1)[-1])), 200
            except KeyError:
                return {"error": "Unknown round"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("guess GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown guess endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/guess/deal":
            raw_agent = payload.get("agent_id")
            return deal(
                city=str(payload.get("city") or ""),
                agent_id=int(raw_agent) if raw_agent not in (None, "") else None,
                dilemma_id=str(payload.get("dilemma_id") or ""),
            ), 200
        if path == "/api/games/guess/answer":
            return answer(str(payload.get("round_id") or ""), str(payload.get("guess") or "")), 200
        if path == "/api/games/guess/again":
            return ask_again(str(payload.get("round_id") or "")), 200
    except KeyError:
        return {"error": "Unknown round"}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("guess POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown guess endpoint"}, 404


__all__ = [
    "DILEMMA_BANK",
    "FILE_CHARS",
    "MAX_SAMPLES",
    "answer",
    "ask_again",
    "deal",
    "dilemma_by_id",
    "handle_get",
    "handle_post",
    "list_dilemmas",
    "parse_choice",
    "public_round",
    "reset_rounds",
    "scoreboard",
]
