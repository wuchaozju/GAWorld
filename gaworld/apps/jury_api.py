"""Dashboard backend for 陪审团 (Jury Deliberation), the playground's eighth game.

The player writes a *case*: a short prose description of what one resident
of a particular city is alleged to have done, with a starting position
(presumed innocent / presumed guilty). A jury of three to five of that
city's other residents then discusses it for three rounds, hears each
other's arguments, and finally casts anonymous ballots on two questions:
*guilt* (有罪 / 无罪) and *sentence* (the only thing on the sheet — the
caller picks the question from a menu).

Four things worth knowing before reading the code:

* **The jury is the game.** A bare *guilty / not guilty* call from a single
  model on a short case prompt is a coin-flip test of which way the model
  leans, and any prompt big enough to anchor a stance becomes that model's
  essay. So the run is a *deliberation*: every juror speaks every round,
  hears what the others have said, and casts an anonymous ballot at the
  end. The interesting number is the spread — how unanimous a verdict a
  jury could reach on the same case in this city with these people.

* **The player does not play a role.** The user gave the case prompt and
  watches the show. A lawyer-and-witness variant was considered and
  rejected: with the model on both sides the rebuttal and the rejoinder
  converge on whichever side the model started last, and the verdict
  comes from the same call that wrote the closing argument. Letting the
  model be *only* the jurors keeps the verdict an actual measurement of
  what those personas think about that case.

* **The verdict is not a model call.** Jurors each emit
  ``{verdict, confidence, say}`` with verdict drawn from a fixed
  two-way vocabulary and confidence on a 0–100 scale. The chair is not
  a model either — the result is the *plurality*, the *median
  confidence*, the *spread* (max minus min), and the *dissenting
  quotes*. Letting the model name the winner produces the same
  auto-summary-as-verdict failure the rumor game caught (see
  :mod:`gaworld.apps.rumor_api`).

* **The persona fights the agreeable default.** Asked neutrally, every
  juror "feels the evidence is a bit thin, but trusts the system" — the
  same socially-desirable answer the persuasion game got. The prompt says
  plainly that the point of a jury is *not* to follow the room: a juror
  is expected to defend a position even if the others have moved on,
  and to say so when their mind changes.

Conventions follow :mod:`gaworld.apps.rumor_api`: a
:class:`JobStore` for progress, in-memory state, injectable LLM entry
points (``deliberate_fn=`` / ``verdict_fn=``), nothing written back to a
city bundle, and a catalogue endpoint so the player can browse the
preset cases without starting anything.
"""

from __future__ import annotations

import statistics
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.game_jobs import JobStore
from gaworld.apps.games_api import first_json_object, persona_block
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.jury_api")

#: Jurors in one run. The interesting spread needs at least three: with
#: two the verdict is binary, with three you can already show dissent.
#: Cost is ``rounds × jurors + 1`` model calls.
MIN_JURORS = 3
MAX_JURORS = 5
#: Rounds the jury deliberates. Three is enough to see one side shift
#: once and one side hold — the interesting shape of a real jury.
DEFAULT_ROUNDS = 3
MAX_ROUNDS = 5
#: Words each juror speaks in one round. A short remark fits in a real
#: deliberation box; longer turns turn into closing arguments and the
#: vote loses the median voice.
ROUND_BUDGET = 200

#: The two outcomes. 弃权 is not on it on purpose: a juror who refuses
#: to take sides after three rounds is, by definition, *not* on the
#: jury.
VERDICTS: tuple[str, ...] = ("有罪", "无罪")
#: A jury with confidence >= this counts as certain. Below it, the
#: voter is saying *I am guessing*. Both buckets land in the tally, but
#: the histogram separates them.
CONFIDENT_AT = 70

#: Question presets. The verdict on the *crime* is always asked; this
#: list picks what the second ballot measures. The crime is the
#: interesting one, so the menu is short on purpose.
SENTENCE_QUESTIONS: tuple[dict[str, str], ...] = (
    {
        "key": "literal",
        "label": "就是字面上的量刑",
        "text": "照你对这个案子的判断，量刑该多重？用一句话说，并打分（0–100）。",
    },
    {
        "key": "hardship",
        "label": "对被告的同情度",
        "text": "你有多同情被告？（0 = 完全不同情，100 = 极度同情）",
    },
    {
        "key": "reform",
        "label": "能不能改造",
        "text": "这个人还能不能改造？用一句话回答（0 = 没救了，100 = 完全能改造）。",
    },
)


# ---------------------------------------------------------------------------
# Case bank
# ---------------------------------------------------------------------------

#: Built-in cases. Every one is short enough that a real deliberation
#: can resolve it in three rounds, and the whole thing is decided by
#: who you seat on the jury, not by which way the model happens to
#: lean. Civic-flavoured on purpose, because a city worth running a
#: jury in is a city of ordinary situations.
CASE_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "parking",
        "title": "老王挪车",
        "emoji": "🚗",
        "defendants": "老王",
        "facts": "深夜两点，老王怀疑楼下那辆面包车挡住了他明早出门的车位，叫了两次车主没应，就把车从 5 号楼前挪到了 50 米外的路边。"
        "第二天一早，面包车主要去拉货，迟到了两个小时，损失了一单生意。面包车主说老王『擅自开我车、还给我弄丢了一单』；老王说车没锁、自己当时挪之前拍了照。",
        "starting": "无罪推定",
    },
    {
        "id": "garden",
        "title": "菜地之争",
        "emoji": "🥬",
        "defendants": "张姐",
        "facts": "张姐在小区公共绿地上围了一小块地种菜，用的是邻居堆在楼下的旧砖头。物业说这是违建，让她拆。"
        "张姐说自己种菜是给老伴治病用的土药材，没有卖，也不影响别人走路；其他邻居有的支持，有的说她挡了路。",
        "starting": "无罪推定",
    },
    {
        "id": "wifi",
        "title": "邻居蹭网",
        "emoji": "📶",
        "defendants": "陈先生",
        "facts": "陈先生上个月开始用放大功率的设备，把自家 wifi 信号覆盖到了楼上楼下好几户。楼上独居老人感激他『不要钱的网』，楼下做小生意的年轻人说陈先生把他家网速拖到不能快用。"
        "陈先生说自己只是『顺手开了强信号』，没收钱也没盗号。",
        "starting": "无罪推定",
    },
    {
        "id": "noise",
        "title": "广场舞噪音",
        "emoji": "💃",
        "defendants": "刘阿姨",
        "facts": "刘阿姨每晚八点半准时到小区广场领舞，喇叭声量开到最大，三年来一直没改。楼下住户连续三个月失眠，有两个孩子说过『在准备考试』。"
        "刘阿姨说自己白天不上班、晚上才得空,邻居投诉过她也没换地方，但她说『这是公共场所，又不是我家的』。",
        "starting": "无罪推定",
    },
    {
        "id": "report",
        "title": "举报同事",
        "emoji": "📝",
        "defendants": "小赵",
        "facts": "小赵在公司发现疑似虚报差旅费的现象，向总部实名举报。调查下来，确属实情，那位同事被处分。"
        "但那位同事是带小赵入行的师傅,在小团队里很受用,举报之后小赵被穿小鞋、冷处理,半年后被迫走人。小赵说『我做了对的事』;她说她是『害群之马』,公司没保护她。",
        "starting": "无罪推定",
    },
    {
        "id": "delivery",
        "title": "外卖送错单",
        "emoji": "🍱",
        "defendants": "外卖员小吴",
        "facts": "外卖员小吴一晚连送 16 单，在最后几单里把两份饭送反了。一份是病人不能吃油的，另一份定时定点上班的吃了饭就睡。"
        "投诉后,平台罚了他 500 元。小吴说系统派单太离谱,同事 6 道同时间送;他请求重新考虑,平台没有调解。",
        "starting": "无罪推定",
    },
)


def list_cases() -> list[dict[str, Any]]:
    return [dict(case) for case in CASE_BANK]


def case_by_id(case_id: str) -> dict[str, Any] | None:
    for case in CASE_BANK:
        if case["id"] == str(case_id or ""):
            return dict(case)
    return None


def resolve_case(case_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    """The case to try, from the bank or written by the player.

    A custom case needs at least a fact statement; without one the jury
    has nothing to deliberate. The defaulting *starting* position is
    always *presumed innocent* — every modern civic jury starts there,
    and silently flipping it would let the player rig the verdict
    without typing the word.
    """
    if custom:
        facts = str(custom.get("facts") or "").strip()
        if not facts:
            raise ValueError("请把这个案子写清楚:发生了什么、谁做了什么")
        return {
            "id": "custom",
            "title": str(custom.get("title") or "自定义案件")[:40],
            "emoji": "📝",
            "defendants": str(custom.get("defendants") or "被告")[:40],
            "facts": facts[:1200],
            "starting": "无罪推定",
        }
    case = case_by_id(str(case_id or ""))
    if case is None:
        raise ValueError(f"没有这个案件:{case_id!r}")
    return case


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_deliberate_llm(prompt: str) -> str:
    """A juror's voice — warm, opinionated, willing to change their mind."""

    return _call_llm(prompt, task="games.jury", temperature=0.7)


def _default_verdict_llm(prompt: str) -> str:
    """The per-employee vote at the end. Deterministic on purpose."""

    return _call_llm(prompt, task="games.jury.verdict", temperature=0.0)


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


@dataclass
class Juror:
    """One resident on the jury, plus what they said and how they voted."""

    agent_id: int
    name: str
    age: int
    job: str
    residence: str
    persona_text: str = ""
    #: What each juror said in each round. ``speech[round_index]`` is
    #: what they said *going into* round ``round_index+1``.
    speeches: list[dict[str, Any]] = field(default_factory=list)
    #: Final ballot, or ``""`` until any per-employee vote has fired.
    verdict: str = ""
    #: 0–100. Bucketed at :data:`CONFIDENT_AT` for the histogram.
    confidence: int = 0
    #: Free-form answer to the secondary question, or ``None``.
    secondary_value: str | None = None
    #: The line the juror wrote on their ballot card — quoted in the
    #: result so the player can see *why* each side voted the way it did.
    quote: str = ""

    @property
    def confident(self) -> bool:
        return self.confidence >= CONFIDENT_AT

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "age": self.age,
            "job": self.job,
            "residence": self.residence,
            "speeches": list(self.speeches),
            "verdict": self.verdict,
            "confidence": self.confidence,
            "confident": self.confident,
            "secondary_value": self.secondary_value,
            "quote": self.quote,
        }


def _load_jurors(city: str, agent_ids: list[int]) -> list[Juror]:
    """Build the jury from one population read.

    Rejects an id that is repeated on the same jury: a juror who
    deliberates with themselves is not a jury. (A duplicate juror would
    be the same model call twice, and the second turn would carry
    forward the first's words as someone else's.)
    """
    from gaworld.interview.roster import load_population, profile_block

    ids = [int(i) for i in (agent_ids or []) if int(i or 0) > 0]
    if not ids:
        raise ValueError("陪审团至少要有一个人")
    if len(set(ids)) != len(ids):
        raise ValueError("陪审团里不能有重复的人")
    if not (MIN_JURORS <= len(ids) <= MAX_JURORS):
        raise ValueError(f"陪审团人数应在 {MIN_JURORS} 到 {MAX_JURORS} 人之间")

    by_id = {int(p["id"]): p for p in load_population(city)}
    jurors: list[Juror] = []
    for agent_id in ids:
        person = by_id.get(agent_id)
        if person is None:
            raise ValueError(f"城市 {city or '默认世界'} 里没有 #{agent_id} 这个人")
        persona = {
            "agent_id": agent_id,
            "name": person["name"],
            "age": person["age"],
            "gender": person["gender"],
            "job": person["job"],
            "profile_md": profile_block(city, agent_id),
        }
        jurors.append(
            Juror(
                agent_id=agent_id,
                name=str(person["name"]),
                age=int(person["age"] or 0),
                job=str(person["job"] or ""),
                residence=str(person.get("residence") or ""),
                persona_text=persona_block(persona),
            )
        )
    return jurors


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_VOICE_RULES = "用第一人称说话，像一个真实的人在参与讨论。不要扮演 AI，不要复述其他人的话，不要给清单式短论。"


def _deliberation_intro(case: dict[str, Any], question: dict[str, str]) -> str:
    """The unchanging preamble of every deliberation prompt."""
    return (
        "你是某小区一名普通居民，被随机抽中担任陪审员，参加一场模拟陪审。\n"
        f"【要审的案件】{case['title']}（被告：{case['defendants']}）。\n"
        f"【案情】{case['facts']}\n"
        f"【推定】{case['starting']}。\n"
        f"【待裁要点】两个投票:1) 有罪 / 无罪; 2) {question['text']}\n"
        f"{_VOICE_RULES}\n"
    )


def _transcript_lines(speeches: list[dict[str, Any]]) -> str:
    """A flat transcript of what everyone has said so far.

    Each juror's latest speech carries the round it belongs to, so the
    transcript can be re-built every round without losing the order.
    """

    rows: list[str] = []
    for speech in speeches:
        who = speech.get("name") or f"#{speech.get('agent_id', '?')}"
        round_index = (speech.get("round") or 0) + 1
        rows.append(f"  · 第 {round_index} 轮 · {who}:{speech.get('text', '')}")
    return "\n".join(rows) or "（还没有发言）"


def _deliberation_prompt(
    juror: Juror,
    others: list[Juror],
    case: dict[str, Any],
    round_index: int,
    question: dict[str, str],
) -> str:
    """The prompt for one juror's speech in one round."""
    transcript = _transcript_lines([speech for other in [*others, juror] for speech in other.speeches])
    if round_index == 0:
        others_summary = "（其他陪审员还没发言）"
    else:
        others_summary = "其他陪审员到目前为止说过:\n" + transcript
    return (
        f"{juror.persona_text}\n\n"
        f"{_deliberation_intro(case, question)}\n"
        f"现在是第 {round_index + 1} 轮（共 {DEFAULT_ROUNDS if round_index + 1 <= DEFAULT_ROUNDS else MAX_ROUNDS} 轮）。\n"
        f"【你的处境】你已经在认真考虑这个案件。"
        f"{others_summary}\n"
        "现在轮到你发言。请说出你自己的观点——你倾向有罪还是无罪,理由是什么,"
        "有没有被前面陪审员说动了，或者你觉得谁的话你没听进去。\n"
        "注意:1) 陪审的意义就是不被别人的意见裹挟,即使全场都倾向一边,你也可以坚持——或者坦承你被说动了。\n"
        "2) 不要笼统讲『看证据』，具体讲你被哪个证据/哪条逻辑说服。\n"
        f"发言控制在 {ROUND_BUDGET} 字以内。"
    )


def _verdict_prompt(
    juror: Juror,
    others: list[Juror],
    case: dict[str, Any],
    question: dict[str, str],
) -> str:
    """The prompt for one juror's final ballot."""
    transcript = _transcript_lines([speech for other in [*others, juror] for speech in other.speeches])
    other_summary = "其他陪审员说过:\n" + transcript
    return (
        f"{juror.persona_text}\n\n"
        f"{_deliberation_intro(case, question)}\n"
        f"【全部讨论】{other_summary}\n"
        "现在到最终投票。\n"
        "请投出两个票:\n"
        "  1) 罪名:有罪 / 无罪 (0 = 无罪, 100 = 有罪),给出 0–100 的 confidence 表示你有多确定\n"
        f"  2) {question['text']}\n"
        '只允许输出形如 {"verdict": "有罪", "confidence": 80, "say": "一句话理由", "secondary_value": "可选,一句话回答第二个问题"} 的 JSON 对象,不要解释。\n'
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_verdict(raw: str) -> dict[str, Any]:
    """The post-verdict record, with safe fallbacks for an ugly model reply.

    A juror that goes off-script should not be silently dropped: even a
    bad answer is data. The defaulting verdict is *无罪* (the starting
    position) so a misfire reads as a non-decision rather than as a
    not-guilty conviction the player cannot see happened.
    """
    payload = first_json_object(raw) or {}
    verdict = str(payload.get("verdict") or "").strip()
    if verdict not in VERDICTS:
        # Tolerate the model writing English / simplified, but only in
        # the obvious cases — anything else falls through.
        normalised = verdict.replace(" ", "").lower()
        if "无罪" in verdict or "notguilty" in normalised or "innocent" in normalised:
            verdict = "无罪"
        elif "有罪" in verdict or "guilty" in normalised:
            verdict = "有罪"
        else:
            verdict = "无罪"
    try:
        confidence = round(float(payload.get("confidence") or 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))
    secondary = payload.get("secondary_value")
    return {
        "verdict": verdict,
        "confidence": confidence,
        "quote": str(payload.get("say") or "").strip()[:240],
        "secondary_value": str(secondary).strip()[:240] if secondary is not None else None,
    }


# ---------------------------------------------------------------------------
# Job plumbing — one JobStore per game, see gaworld.apps.game_jobs.
# ---------------------------------------------------------------------------

_JOBS = JobStore("jury")


def job_status(job_id: str) -> dict[str, Any] | None:
    return _JOBS.status(job_id)


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""

    _JOBS.reset()


def list_runs() -> list[dict[str, Any]]:
    """Finished deliberations still in memory, newest first."""
    rows: list[dict[str, Any]] = []
    for record in _JOBS.results():
        result = record.get("result") or {}
        tally = result.get("tally") or {}
        rows.append(
            {
                "job_id": record["job_id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "case_title": (result.get("case") or {}).get("title"),
                "emoji": (result.get("case") or {}).get("emoji"),
                "verdict": tally.get("verdict"),
                "guilty": tally.get("guilty"),
                "not_guilty": tally.get("not_guilty"),
                "spread": tally.get("spread"),
                "created_at": result.get("created_at"),
            }
        )
    rows.sort(key=lambda r: -(r.get("created_at") or 0))
    return rows


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


@dataclass
class _RoundLog:
    """One round, with one speech per juror."""

    round_index: int
    speeches: list[dict[str, Any]] = field(default_factory=list)


def _stats_of_tally(tally: dict[str, Any], jurors: list[Juror]) -> dict[str, Any]:
    """Numbers the board shows above the verdict."""
    confidences = [int(j.confidence) for j in jurors if j.verdict]
    confident_guilty = sum(1 for j in jurors if j.verdict == "有罪" and j.confident)
    confident_not = sum(1 for j in jurors if j.verdict == "无罪" and j.confident)
    return {
        "jurors": len(jurors),
        "guilty": tally.get("guilty", 0),
        "not_guilty": tally.get("not_guilty", 0),
        "confident_guilty": confident_guilty,
        "confident_not_guilty": confident_not,
        "spread": tally.get("spread", 0),
        "median_confidence": int(statistics.median(confidences)) if confidences else 0,
    }


def _tally(jurors: list[Juror]) -> dict[str, Any]:
    """The verdict and the inputs, computed by code."""
    guilty = sum(1 for j in jurors if j.verdict == "有罪")
    not_guilty = sum(1 for j in jurors if j.verdict == "无罪")
    confidences = [int(j.confidence) for j in jurors if j.verdict]
    spread = (max(confidences) - min(confidences)) if confidences else 0
    if guilty > not_guilty:
        verdict = "有罪"
    elif not_guilty > guilty:
        verdict = "无罪"
    else:
        # A tie. The starting position is *presumed innocent*; flipping
        # that would let a tied jury convict on a coin flip.
        verdict = "无罪"
    dissenting = [
        {"agent_id": j.agent_id, "name": j.name, "verdict": j.verdict, "quote": j.quote}
        for j in jurors
        if j.verdict and j.verdict != verdict
    ]
    supporting = [
        {"agent_id": j.agent_id, "name": j.name, "verdict": j.verdict, "quote": j.quote}
        for j in jurors
        if j.verdict and j.verdict == verdict
    ]
    return {
        "verdict": verdict,
        "guilty": guilty,
        "not_guilty": not_guilty,
        "spread": spread,
        "supporting": supporting,
        "dissenting": dissenting,
    }


def run_jury(
    *,
    city: str,
    case_id: str,
    agent_ids: list[int],
    custom: dict[str, Any] | None = None,
    question_key: str = SENTENCE_QUESTIONS[0]["key"],
    rounds: int = DEFAULT_ROUNDS,
    jurors: list[Juror] | None = None,
    deliberate_fn: Callable[[str], str] | None = None,
    verdict_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Run the deliberation and return the scored result."""
    progress = progress or (lambda p, m: None)
    case = resolve_case(case_id, custom)
    question = _resolve_question(question_key)
    round_count = max(1, min(int(rounds or DEFAULT_ROUNDS), MAX_ROUNDS))
    if jurors is None:
        jurors = _load_jurors(city, agent_ids)
    if not jurors:
        raise ValueError("陪审团至少要有一个人")
    if len(jurors) > MAX_JURORS:
        jurors = jurors[:MAX_JURORS]

    deliberate = deliberate_fn or _default_deliberate_llm
    verdicts = verdict_fn or _default_verdict_llm
    total_calls = round_count * len(jurors) + 1
    spent = 0

    rounds_log: list[_RoundLog] = []
    for round_index in range(round_count):
        log = _RoundLog(round_index=round_index)
        for juror in jurors:
            spent += 1
            progress(
                min(0.95, spent / total_calls),
                f"第 {round_index + 1} 轮 · {juror.name}",
            )
            try:
                raw = deliberate(_deliberation_prompt(juror, jurors, case, round_index, question))
            except Exception as exc:  # pragma: no cover - provider failure
                raw = ""
                _LOG.warning("jury deliberation call failed for #%s: %s", juror.agent_id, exc)
            speech = {
                "round": round_index,
                "agent_id": juror.agent_id,
                "name": juror.name,
                "text": str(raw).strip()[: ROUND_BUDGET * 4],
            }
            juror.speeches.append(speech)
            log.speeches.append(speech)
        rounds_log.append(log)

    progress(0.97, "投票中…")
    for juror in jurors:
        try:
            raw = verdicts(_verdict_prompt(juror, jurors, case, question))
        except Exception as exc:  # pragma: no cover - provider failure
            raw = ""
            _LOG.warning("jury verdict call failed for #%s: %s", juror.agent_id, exc)
        record = parse_verdict(raw)
        juror.verdict = record["verdict"]
        juror.confidence = record["confidence"]
        juror.secondary_value = record["secondary_value"]
        juror.quote = record["quote"]

    tally = _tally(jurors)
    return {
        "run_id": uuid.uuid4().hex[:8],
        "city": city,
        "case": case,
        "question": question,
        "rounds": round_count,
        "jurors": [j.to_dict() for j in jurors],
        "rounds_log": [{"round": log.round_index, "speeches": list(log.speeches)} for log in rounds_log],
        "tally": tally,
        "stats": _stats_of_tally(tally, jurors),
        "created_at": time.time(),
    }


def _resolve_question(key: str) -> dict[str, str]:
    for item in SENTENCE_QUESTIONS:
        if item["key"] == str(key or ""):
            return dict(item)
    return dict(SENTENCE_QUESTIONS[0])


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then run the deliberation in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or []) if int(i or 0) > 0]
    if not agent_ids:
        raise ValueError("陪审团至少要有一个人")
    if len(set(agent_ids)) != len(agent_ids):
        raise ValueError("陪审团里不能有重复的人")
    if not (MIN_JURORS <= len(agent_ids) <= MAX_JURORS):
        raise ValueError(f"陪审团人数应在 {MIN_JURORS} 到 {MAX_JURORS} 人之间")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    # Fail fast on an unknown or half-written case: better a 400 now
    # than a dead job after the first model call.
    resolve_case(str(payload.get("case_id") or ""), custom)
    rounds = int(payload.get("rounds") or DEFAULT_ROUNDS)
    question_key = str(payload.get("question_key") or SENTENCE_QUESTIONS[0]["key"])
    case_id = str(payload.get("case_id") or "")

    def _work(progress: Callable[[float, str], None]) -> dict[str, Any]:
        return run_jury(
            city=city,
            case_id=case_id,
            agent_ids=agent_ids,
            custom=custom,
            question_key=question_key,
            rounds=rounds,
            progress=progress,
        )

    return _JOBS.run(_work)


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/jury/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/jury/catalogue":
            return {
                "cases": list_cases(),
                "questions": [dict(item) for item in SENTENCE_QUESTIONS],
                "min_jurors": MIN_JURORS,
                "max_jurors": MAX_JURORS,
                "default_rounds": DEFAULT_ROUNDS,
                "max_rounds": MAX_ROUNDS,
                "verdicts": list(VERDICTS),
                "confident_at": CONFIDENT_AT,
            }, 200
        if path == "/api/games/jury/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/jury/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("jury GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/jury/run":
            return {"job_id": start_run(payload)}, 202
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("jury POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "CASE_BANK",
    "CONFIDENT_AT",
    "DEFAULT_ROUNDS",
    "MAX_JURORS",
    "MAX_ROUNDS",
    "MIN_JURORS",
    "ROUND_BUDGET",
    "SENTENCE_QUESTIONS",
    "VERDICTS",
    "Juror",
    "case_by_id",
    "handle_get",
    "handle_post",
    "job_status",
    "list_cases",
    "list_runs",
    "parse_verdict",
    "reset_jobs",
    "resolve_case",
    "run_jury",
    "start_run",
]
