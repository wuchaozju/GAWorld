"""Dashboard backend for 公投局 (Referendum), the playground's fifth game.

A motion with real stakes goes to a group of residents. They take a private
position first, then see where the crowd stands — the tally, the loudest
voices on each side, and whatever campaign line the player chose to put in
front of them — and vote for real. What comes out is the swing: who moved,
which way, and how much of it a single slogan was worth.

Why it is built the way it is:

* **Private first, public second.** Asking once and calling it a vote would
  measure the personas alone. Asking twice, with the crowd in between, is
  the only way to separate "what they think" from "what they will say once
  they know they are in the minority" — which is the thing a referendum
  actually decides.
* **The tally is free.** The public round quotes the counts and a couple of
  real sentences from round one; both come from data already in hand, so the
  social pressure costs no extra model call. A round is ``residents × 2 + 1``.
* **No judge.** Each reply is ``{stance, strength, say}`` with stance drawn
  from a fixed three-way vocabulary, so the swing, the margin and the
  polarisation all fall out of the answers.
* **The campaign line is the player's move.** It is optional and it is shown
  as what it is — a leaflet doing the rounds — never as fact. Watching one
  sentence move four votes is the game.

Conventions match :mod:`gaworld.apps.disaster_api`: a :class:`JobStore` for
progress, in-memory state, injectable LLM entry points (``answer_fn=`` /
``summary_fn=``), nothing written back to a city bundle.
"""

from __future__ import annotations

import statistics
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.game_jobs import JobStore
from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.referendum_api")

#: Voters in one run. A run is ``residents × 2 + 1`` model calls.
MAX_AGENTS = 14
#: How strident a position has to be before we call it polarised.
POLARISED_AT = 80
#: Quotes from round one shown to everybody in round two, per side. Two is
#: enough to feel like a room and short enough to leave space for the persona.
QUOTES_PER_SIDE = 2

#: The three ways to answer a motion. 弃权 is a real position, not a missing
#: one: a resident who refuses to take sides is telling you something.
STANCES: tuple[str, ...] = ("支持", "反对", "弃权")
OTHER_STANCE = "其他"


# ---------------------------------------------------------------------------
# Motion bank
# ---------------------------------------------------------------------------

#: Built-in motions. Every one of them costs somebody something — a motion
#: nobody loses by passes 14-0 and shows nothing. Written city-agnostically
#: so they run against any bundle.
MOTION_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "waste",
        "title": "垃圾中转站选址",
        "emoji": "🗑️",
        "text": "市里要在本片区建一座垃圾中转站，选址就在几个小区中间的空地上。"
        "建成后全区的垃圾不用再拉到城外，处理费每户每月降 15 块；"
        "但最近的居民楼离它不到 200 米。是否同意在此选址建站？",
    },
    {
        "id": "fee",
        "title": "物业费上调",
        "emoji": "💰",
        "text": "物业提出把物业费上调 30%，理由是电梯该大修、保安要加人、绿化多年没换。"
        "不涨的话电梯维修只能走维修基金，可能要停梯两个月。是否同意上调？",
    },
    {
        "id": "traffic",
        "title": "老城区限行",
        "emoji": "🚗",
        "text": "老城区拟在工作日早晚高峰按车牌单双号限行，公交加密、地铁票价打折。"
        "通勤开车的人一周有两三天不能开，做生意送货的要另想办法。是否同意限行？",
    },
    {
        "id": "school",
        "title": "学区重新划片",
        "emoji": "🏫",
        "text": "教育局拟重新划分学区：本片区一部分孩子改去新建的学校，硬件更好但要多走两站路，"
        "原来的老牌小学则腾出学位给邻区。是否同意这次划片？",
    },
    {
        "id": "market",
        "title": "菜市场改造",
        "emoji": "🥬",
        "text": "老菜市场要改造成生鲜超市：环境干净、有空调、扫码付款，"
        "但摊位租金翻倍，几十个老摊主多半租不起，菜价预计涨一成。是否同意改造？",
    },
)


def list_motions() -> list[dict[str, Any]]:
    return [dict(item) for item in MOTION_BANK]


def motion_by_id(motion_id: str) -> dict[str, Any] | None:
    for item in MOTION_BANK:
        if item["id"] == motion_id:
            return item
    return None


def resolve_motion(motion_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pick the motion to put to the vote: one from the bank, or the caller's."""
    if custom:
        text = str(custom.get("text") or "").strip()
        if not text:
            raise ValueError("自定义议案要写清楚投什么")
        return {
            "id": "custom",
            "title": str(custom.get("title") or "自定义议案").strip() or "自定义议案",
            "emoji": "✍️",
            "text": text,
        }
    found = motion_by_id(str(motion_id or ""))
    if found is None:
        raise ValueError(f"没有这个议案：{motion_id or '（未选）'}")
    return found


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_vote_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.referendum", temperature=0.7)


def _default_summary_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.referendum.summary", temperature=0.3)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

#: The same lesson the persuasion and rumor games had to learn: asked
#: neutrally, every resident produces the balanced, agreeable answer. A
#: referendum in which nobody has a stake is not a referendum.
_STAKES_RULE = (
    "这件事对你具体是好是坏，取决于你住哪、干什么、家里有谁、有多少钱——先想清楚这个，再表态。"
    "不要给一个面面俱到的中间答案；真实的人在这种事上是有倾向的。"
    "只有当你确实事不关己、或者真的两难时，才投弃权。"
)


def _private_prompt(persona_text: str, motion: dict[str, Any]) -> str:
    return (
        f"{persona_text}\n\n"
        f"片区里要就下面这件事表决，现在还没人知道别人的想法。\n"
        f"【议案】{motion['title']}：{motion['text']}\n\n"
        f"{_STAKES_RULE}\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"stance": "支持 或 反对 或 弃权", "strength": 0-100 的整数（你这个立场有多坚定）, '
        '"say": "一句话说明你为什么这么想，第一人称"}'
    )


def _crowd_block(tally: dict[str, int], quotes: list[dict[str, Any]], campaign: str) -> str:
    counts = "、".join(f"{stance} {tally.get(stance, 0)} 人" for stance in STANCES)
    lines = [f"现在大家的意见摆出来了：{counts}。"]
    for quote in quotes:
        lines.append(f"- {quote['name']}（{quote['stance']}）：{quote['say']}")
    if campaign:
        lines.append(f"\n另外，有人在群里和电梯口贴出了这样一句话：「{campaign}」")
    return "\n".join(lines)


def _own_line(own: dict[str, Any]) -> str:
    """Their own private position, or the honest version when it was
    unreadable — telling somebody their view was "其他" is nonsense."""
    if own.get("stance") in ("支持", "反对", "弃权"):
        return f"你刚才私下的想法是「{own['stance']}」，理由：{own.get('say') or '（没多说）'}"
    return "你刚才没拿定主意。"


def _public_prompt(
    persona_text: str,
    motion: dict[str, Any],
    own: dict[str, Any],
    crowd: str,
) -> str:
    return (
        f"{persona_text}\n\n"
        f"【议案】{motion['title']}：{motion['text']}\n"
        f"{_own_line(own)}\n\n"
        f"{crowd}\n\n"
        "现在是正式表决。你可以坚持原来的立场，也可以改——"
        "看到多数人怎么想之后改主意不丢人，被说到痛处而改也不丢人；"
        "但如果别人的理由并没有打动你，就照原来的投，不要为了合群而改。\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"stance": "支持 或 反对 或 弃权", "strength": 0-100 的整数, '
        '"say": "一句话说明你最终为什么这么投；如果你改了，说清是什么让你改的"}'
    )


def _summary_prompt(motion: dict[str, Any], run: dict[str, Any]) -> str:
    stats = run["stats"]
    flips = "；".join(
        f"{item['name']} 从{item['from']}改投{item['to']}（{item['say']}）" for item in run["flips"]
    )
    return (
        "你是一名社会学观察者，下面是一次片区表决的记录：先私下表态，"
        "再看到大家的意见和一句宣传口径之后正式投票。\n"
        "请写一段 150 字以内的简报：谁在为什么反对、谁在为什么支持，"
        "哪些人被多数意见带动了，哪些人顶住了，这次表决真正的分歧线在哪。"
        "要具体，不要空话，不要罗列要点。\n\n"
        f"议案：{motion['title']}——{motion['text']}\n"
        f"私下表态：{stats['private']}\n"
        f"正式表决：{stats['public']}\n"
        f"结果：{stats['result']}（支持 {stats['public']['支持']} / 反对 {stats['public']['反对']}）\n"
        f"改票的人：{flips or '没有人改票'}\n"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _coerce_stance(value: Any) -> str:
    """Map a free-form stance onto the vocabulary; unknown → ``其他``.

    Negations are checked first on purpose: "不支持" contains "支持" and
    "不同意" contains "同意", so a plain substring pass would record the
    opposite vote — the worst way to lose a ballot, because the tally still
    looks perfectly reasonable.
    """
    text = str(value or "").strip()
    if text in STANCES:
        return text
    for needle in ("不支持", "不同意", "不赞成", "反对"):
        if needle in text:
            return "反对"
    for needle in ("支持", "赞成", "同意"):
        if needle in text:
            return "支持"
    for needle in ("弃权", "中立", "不表态"):
        if needle in text:
            return "弃权"
    return OTHER_STANCE


def parse_vote(raw: str) -> dict[str, Any]:
    """Read one resident's ballot, tolerating prose around the JSON.

    An unreadable reply becomes ``其他`` with zero strength: it is counted as
    cast but it never lands on either side of the margin.
    """
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {"stance": OTHER_STANCE, "strength": 0, "say": text[:120]}
    try:
        strength = int(float(payload.get("strength", 50)))
    except (TypeError, ValueError):
        strength = 50
    return {
        "stance": _coerce_stance(payload.get("stance")),
        "strength": max(0, min(100, strength)),
        "say": str(payload.get("say") or "").strip()[:200],
    }


# ---------------------------------------------------------------------------
# Tallies
# ---------------------------------------------------------------------------


def tally(votes: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts per stance, plus the two numbers that describe the room."""
    counts = dict.fromkeys(STANCES, 0)
    counts[OTHER_STANCE] = 0
    for vote in votes:
        counts[vote["stance"]] = counts.get(vote["stance"], 0) + 1
    strengths = [v["strength"] for v in votes if v["stance"] in ("支持", "反对")]
    counts["avg_strength"] = round(statistics.mean(strengths), 1) if strengths else 0.0
    counts["polarised"] = sum(1 for v in votes if v["strength"] >= POLARISED_AT)
    return counts


def _result_line(counts: dict[str, Any]) -> str:
    for_, against = counts.get("支持", 0), counts.get("反对", 0)
    if for_ > against:
        return "通过"
    if against > for_:
        return "否决"
    return "平票"


# ---------------------------------------------------------------------------
# Jobs — one store per game (see gaworld.apps.game_jobs).
# ---------------------------------------------------------------------------

_JOBS = JobStore("referendum")


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    _JOBS.reset()


def list_runs() -> list[dict[str, Any]]:
    """Finished votes still in memory, newest first."""
    return [
        {
            "job_id": row["job_id"],
            "run_id": result.get("run_id"),
            "city": result.get("city"),
            "motion": (result.get("motion") or {}).get("title"),
            "emoji": (result.get("motion") or {}).get("emoji"),
            "voters": len(result.get("voters") or []),
            "result": (result.get("stats") or {}).get("result"),
            "flips": len(result.get("flips") or []),
            "created_at": result.get("created_at"),
        }
        for row in _JOBS.results()
        for result in [row["result"]]
    ]


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


@dataclass
class Voter:
    """One resident, their private position and their public one."""

    agent_id: int
    name: str
    age: int = 0
    job: str = ""
    residence: str = ""
    persona_text: str = ""
    private: dict[str, Any] = field(default_factory=dict)
    public: dict[str, Any] = field(default_factory=dict)

    @property
    def flipped(self) -> bool:
        return bool(self.private and self.public and self.private["stance"] != self.public["stance"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "age": self.age,
            "job": self.job,
            "residence": self.residence,
            "private": dict(self.private),
            "public": dict(self.public),
            "flipped": self.flipped,
        }


def load_voters(city: str, agent_ids: list[int]) -> list[Voter]:
    """Build the roll from the city bundle, in the order they were picked."""
    from gaworld.apps.games_api import persona_block
    from gaworld.interview.roster import load_population, profile_block

    people = {int(p["id"]): p for p in load_population(city)}
    voters: list[Voter] = []
    for agent_id in agent_ids:
        person = people.get(int(agent_id))
        if person is None:
            raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
        persona = {
            "agent_id": int(agent_id),
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "job": person["job"],
            "profile_md": profile_block(city, int(agent_id)),
        }
        voters.append(
            Voter(
                agent_id=int(agent_id),
                name=str(person["name"]),
                age=int(person["age"] or 0),
                job=str(person["job"] or ""),
                residence=str(person["residence"] or ""),
                persona_text=persona_block(persona),
            )
        )
    return voters


def _loud_quotes(voters: list[Voter]) -> list[dict[str, Any]]:
    """The most strident voice or two on each side of round one.

    Strength-ranked rather than graph-ranked: this game is about the public
    room, and in a public room it is the loudest who set the tone.
    """
    quotes: list[dict[str, Any]] = []
    for stance in ("支持", "反对"):
        side = [v for v in voters if v.private.get("stance") == stance and v.private.get("say")]
        side.sort(key=lambda v: (-v.private["strength"], v.agent_id))
        for voter in side[:QUOTES_PER_SIDE]:
            quotes.append({"name": voter.name, "stance": stance, "say": voter.private["say"]})
    return quotes


def run_referendum(
    *,
    city: str,
    agent_ids: list[int],
    motion_id: str = "",
    custom: dict[str, Any] | None = None,
    campaign: str = "",
    voters: list[Voter] | None = None,
    answer_fn: Callable[[str], str] | None = None,
    summary_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Private round, then the public one, then the swing."""
    progress = progress or (lambda p, m: None)
    motion = resolve_motion(motion_id, custom)
    campaign = str(campaign or "").strip()[:200]

    roll = (
        voters if voters is not None else load_voters(city, [int(i) for i in (agent_ids or [])][:MAX_AGENTS])
    )
    if len(roll) < 2:
        raise ValueError("至少选两个人才叫表决")

    answer = answer_fn or _default_vote_llm
    steps = len(roll) * 2
    step = 0

    for voter in roll:
        step += 1
        progress(step / steps * 0.92, f"私下表态 · {voter.name}")
        voter.private = _ask(answer, _private_prompt(voter.persona_text, motion), voter)

    private_counts = tally([v.private for v in roll])
    quotes = _loud_quotes(roll)
    crowd = _crowd_block(private_counts, quotes, campaign)

    for voter in roll:
        step += 1
        progress(step / steps * 0.92, f"正式表决 · {voter.name}")
        voter.public = _ask(answer, _public_prompt(voter.persona_text, motion, voter.private, crowd), voter)

    public_counts = tally([v.public for v in roll])
    flips = [
        {
            "agent_id": v.agent_id,
            "name": v.name,
            "from": v.private["stance"],
            "to": v.public["stance"],
            "say": v.public["say"],
        }
        for v in roll
        if v.flipped
    ]

    run = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "motion": dict(motion),
        "campaign": campaign,
        "quotes": quotes,
        "voters": [v.to_dict() for v in roll],
        "flips": flips,
        "stats": {
            "total": len(roll),
            "private": private_counts,
            "public": public_counts,
            "result": _result_line(public_counts),
            "margin": public_counts.get("支持", 0) - public_counts.get("反对", 0),
            "swing": public_counts.get("支持", 0) - private_counts.get("支持", 0),
            "flips": len(flips),
        },
        "summary": "",
        "created_at": time.time(),
    }

    progress(0.95, "正在写表决简报…")
    try:
        digest = (summary_fn or _default_summary_llm)(_summary_prompt(motion, run))
        run["summary"] = str(digest).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("referendum summary failed: %s", exc)
        run["summary"] = ""
    return run


def _ask(answer: Callable[[str], str], prompt: str, voter: Voter) -> dict[str, Any]:
    """Ask for one ballot, once more if the first one does not parse.

    Worth the extra call here in a way it is not elsewhere: a lost reaction
    in the disaster game costs one cell of a histogram, but a lost ballot
    corrupts the tally, the margin and the swing — and it does it invisibly,
    because a 5-1 result looks perfectly reasonable.
    """
    for attempt in (1, 2):
        try:
            raw = answer(prompt)
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("referendum vote failed for #%s: %s", voter.agent_id, exc)
            raw = ""
        vote = parse_vote(raw)
        if vote["stance"] != OTHER_STANCE:
            return vote
        if attempt == 1:
            _LOG.info("referendum ballot from #%s did not parse; asking again", voter.agent_id)
    return vote


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then hold the vote in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if len(agent_ids) < 2:
        raise ValueError("至少选两个人才叫表决")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    # Fail fast on an unknown motion: better a 400 now than a dead job.
    resolve_motion(str(payload.get("motion_id") or ""), custom)

    return _JOBS.run(
        lambda progress: run_referendum(
            city=city,
            agent_ids=agent_ids,
            motion_id=str(payload.get("motion_id") or ""),
            custom=custom,
            campaign=str(payload.get("campaign") or ""),
            progress=progress,
        )
    )


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/referendum/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/games/referendum/catalogue":
            return {
                "motions": list_motions(),
                "max_agents": MAX_AGENTS,
                "stances": list(STANCES),
            }, 200
        if path == "/api/games/referendum/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/referendum/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("referendum GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown referendum endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/referendum/run":
            return {"job_id": start_run(payload)}, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("referendum POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown referendum endpoint"}, 404


__all__ = [
    "MAX_AGENTS",
    "MOTION_BANK",
    "OTHER_STANCE",
    "POLARISED_AT",
    "STANCES",
    "Voter",
    "handle_get",
    "handle_post",
    "job_status",
    "list_motions",
    "list_runs",
    "load_voters",
    "motion_by_id",
    "parse_vote",
    "reset_jobs",
    "resolve_motion",
    "run_referendum",
    "start_run",
    "tally",
]
