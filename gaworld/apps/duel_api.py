"""Dashboard backend for 双队竞赛 (Team Duel), the playground's fifth game.

Two teams of residents get the *same* task and two *different* methods — one
team may only work top-down, the other only bottom-up — and a judge scores
what each of them actually produced. The question the game answers is not
"can an agent write a plan" but "which route works better *in this city, with
these people*": a team of shopkeepers and a team of officials do not get the
same mileage out of the same method.

Four things worth knowing before reading the code:

* **The method is a constraint, not flavour text.** Told only that their team
  "leans on incentives", both teams write the same 多方协同、加强宣传 plan and
  the comparison has nothing left to compare. So the prompt names the rival
  route and forbids it outright. This is the same fight against the agreeable
  default that :mod:`gaworld.apps.rumor_api` picks over verification.

* **Both teams plan from the same snapshot.** From round two on, a team sees
  the rival's plan — that is what makes it a competition rather than two
  parallel homework assignments. But the rival plan is snapshotted at the
  *start* of the round: running A then B inside one round would let B answer
  A's fresh plan while A only ever saw a stale one, and the second team would
  win on turn order rather than on method.

* **The judge never learns whose plan is whose.** The two plans are relabelled
  方案一 / 方案二 in a shuffled order, so neither position bias nor a judge's
  taste for the phrase "自下而上" can attach to a team. The mapping is
  reported in the result so a player can audit it.

* **The judge scores each criterion; the arithmetic is ours.** Models state
  totals that contradict their own numbers. So the verdict is decided by the
  summed scores, and the winner the model *said* is kept beside it as
  ``judge_said`` — when the two disagree, that disagreement is the interesting
  part, not something to paper over.

Cost is ``rounds × (members + 2) + 1`` model calls: one per member per round,
one plan per team per round, one judge call at the end.

Conventions follow :mod:`gaworld.apps.rumor_api`: a background job with
progress, in-memory state, injectable LLM entry points (``move_fn=`` /
``plan_fn=`` / ``judge_fn=``), and nothing ever written back to a city bundle.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.duel_api")

#: Residents in one duel, both teams together.
MAX_MEMBERS = 10
#: Per team. A fifth voice adds cost without adding a new angle.
MAX_PER_TEAM = 5
#: Rounds played when the caller says nothing, and the ceiling. Two is the
#: cheapest number that still shows adaptation: round one is blind, round two
#: answers the rival.
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 3

#: The scoring sheet. Global rather than per-task so two runs on different
#: tasks are still readable side by side.
CRITERIA: tuple[tuple[str, str], ...] = (
    ("effect", "目标达成"),
    ("feasible", "可行性"),
    ("cost", "代价"),
    ("side", "副作用"),
)
#: Per criterion, so a plan tops out at ``10 × len(CRITERIA)``.
MAX_SCORE = 10

_TEAM_NAMES = {"A": "甲队", "B": "乙队"}
_MAX_JOBS = 20


# ---------------------------------------------------------------------------
# Task bank
# ---------------------------------------------------------------------------

#: Built-in tasks. Every one ships **two contrasting methods**, because the
#: pairing is the game: a task with only one sensible route produces two
#: identical plans and a coin-flip verdict. All of them are civic problems a
#: resident could really be part of, so the personas have something to bring.
TASK_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "elevator",
        "title": "老楼加装电梯",
        "emoji": "🛗",
        "text": "一栋六层老楼要加装电梯。低层住户觉得没用还挡光，高层住户等不及，费用要按户分摊。",
        "goal": "三个月内让这栋楼的住户达成一致并开工。",
        "method_a": {
            "title": "自上而下",
            "text": "走行政路子：申请政府补贴、统一设计施工、由街道出面开协调会，按规定流程推进。",
        },
        "method_b": {
            "title": "自下而上",
            "text": "走邻里路子：业主自己组织，一户一户谈，低层的补偿方案由住户之间商量出来，不等上面拨款。",
        },
    },
    {
        "id": "garbage",
        "title": "垃圾分类落地",
        "emoji": "🗑️",
        "text": "小区推垃圾分类半年了，厨余桶里还是什么都有，督导员一走就打回原形。",
        "goal": "让分类正确率稳定提上去，而且督导员撤了也不反弹。",
        "method_a": {
            "title": "罚与盯",
            "text": "靠约束：定时定点投放、撤掉楼道桶、装摄像头、乱扔的曝光并罚款，物业逐户上门警告。",
        },
        "method_b": {
            "title": "奖与带",
            "text": "靠激励：积分换米面油、楼栋之间评比、找几个热心居民当带头人，把分类变成邻里之间的事。",
        },
    },
    {
        "id": "typhoon",
        "title": "台风前转移群众",
        "emoji": "🌀",
        "text": "台风 12 小时后登陆，低洼片区和危房必须清空，但很多人不愿意走——怕家里东西丢，也不信这次真会淹。",
        "goal": "登陆前把该走的人都转移出来，尽量不留人、也不结怨。",
        "method_a": {
            "title": "强制转移",
            "text": "硬手段：挨户敲门、下达强制转移令、必要时断电断水，登记造册，不走的签风险告知书。",
        },
        "method_b": {
            "title": "动员说服",
            "text": "软手段：靠熟人带动,让已经搬走的邻居去劝，公开安置点条件、承诺看管财物、先转移老人孩子带动全家。",
        },
    },
    {
        "id": "hiring",
        "title": "小厂招不到人",
        "emoji": "🏭",
        "text": "本地一家小厂常年缺工，招来的人干两个月就走，订单排到下季度却不敢接。",
        "goal": "三个月内把人招满并且留住。",
        "method_a": {
            "title": "加钱抢人",
            "text": "砸成本：直接加薪、开入职奖金、给老带新提成、包吃包住，比同行开得高就行。",
        },
        "method_b": {
            "title": "改活留人",
            "text": "改条件：改排班不让人熬夜、把最脏最累的工序改掉、给晋升和带徒弟的路子，让干得久的人有奔头。",
        },
    },
    {
        "id": "shop",
        "title": "街边小店救客流",
        "emoji": "🏪",
        "text": "一家开了七年的街边小店，今年客流掉了四成，隔壁新开的连锁店在打价格战。",
        "goal": "半年内把营业额拉回来，而且别把自己拖垮。",
        "method_a": {
            "title": "价格战",
            "text": "正面打：跟着降价、做特价爆款引流、外卖平台满减、发传单抢周边小区的客。",
        },
        "method_b": {
            "title": "熟客经营",
            "text": "错开打：不降价，做会员和预定、给老客留货、上连锁店没有的手工品类、靠街坊口碑和社群维系。",
        },
    },
    {
        "id": "phone",
        "title": "让孩子放下手机",
        "emoji": "📱",
        "text": "片区里初中生晚上普遍刷手机到半夜，家长管不动，学校说管不着校外。",
        "goal": "一个学期内让这批孩子的睡眠时间真的提上去。",
        "method_a": {
            "title": "管住设备",
            "text": "堵：家长统一收手机、路由器定时断网、学校查寝查机、签家庭公约并互相监督。",
        },
        "method_b": {
            "title": "给个去处",
            "text": "疏：把球场活动室晚上开放、组织社团和比赛、找大孩子带小孩子，让线下比手机更有意思。",
        },
    },
)


def list_tasks() -> list[dict[str, Any]]:
    return [dict(task) for task in TASK_BANK]


def task_by_id(task_id: str) -> dict[str, Any] | None:
    for task in TASK_BANK:
        if task["id"] == task_id:
            return dict(task)
    return None


def resolve_task(task_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    """The task to play, from the bank or written by the player.

    A custom task must carry both methods: one method is not a duel, and
    defaulting the missing one would silently turn the run into a comparison
    the player never asked for.
    """
    if custom:
        text = str(custom.get("text") or "").strip()
        method_a = str((custom.get("method_a") or {}).get("text") or "").strip()
        method_b = str((custom.get("method_b") or {}).get("text") or "").strip()
        if not text:
            raise ValueError("自定义任务要写清楚要做什么")
        if not method_a or not method_b:
            raise ValueError("两个队各要一个办法，不然没得比")
        return {
            "id": "custom",
            "title": str(custom.get("title") or "自定义任务")[:40],
            "emoji": "🎯",
            "text": text[:600],
            "goal": str(custom.get("goal") or "把这件事办成。")[:200],
            "method_a": {
                "title": str((custom.get("method_a") or {}).get("title") or "甲队的办法")[:20],
                "text": method_a[:400],
            },
            "method_b": {
                "title": str((custom.get("method_b") or {}).get("title") or "乙队的办法")[:20],
                "text": method_b[:400],
            },
        }
    task = task_by_id(str(task_id or ""))
    if task is None:
        raise ValueError(f"没有这个任务：{task_id!r}")
    return task


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_move_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.duel", temperature=0.7)


def _default_plan_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.duel.plan", temperature=0.5)


def _default_judge_llm(prompt: str) -> str:
    return _call_llm(prompt, task="games.duel.judge", temperature=0.0)


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


@dataclass
class Member:
    """One resident on one side, plus what they contributed each round."""

    agent_id: int
    name: str
    age: int
    job: str
    team: str
    persona_text: str
    moves: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "age": self.age,
            "job": self.job,
            "team": self.team,
            "moves": list(self.moves),
        }


@dataclass
class Team:
    key: str
    name: str
    method: dict[str, Any]
    members: list[Member] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)

    @property
    def latest_plan(self) -> dict[str, Any] | None:
        return self.plans[-1] if self.plans else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "method": dict(self.method),
            "members": [m.to_dict() for m in self.members],
            "plans": list(self.plans),
        }


def load_members(city: str, team_a: list[int], team_b: list[int]) -> list[Member]:
    """Build both rosters from one population read.

    Rejects an id that appears on both sides: a resident who plans against
    themselves makes the comparison meaningless, and silently dropping the
    duplicate would hide a mis-click behind a quietly smaller team.
    """
    from gaworld.apps.games_api import persona_block
    from gaworld.interview.roster import load_population, profile_block

    ids_a = [int(i) for i in team_a][:MAX_PER_TEAM]
    ids_b = [int(i) for i in team_b][:MAX_PER_TEAM]
    overlap = set(ids_a) & set(ids_b)
    if overlap:
        raise ValueError(f"#{sorted(overlap)[0]} 同时在两个队里，一个人不能左右互搏")
    if not ids_a or not ids_b:
        raise ValueError("两个队各至少要一个人")
    if len(ids_a) + len(ids_b) > MAX_MEMBERS:
        raise ValueError(f"两队合计最多 {MAX_MEMBERS} 人")

    by_id = {int(p["id"]): p for p in load_population(city)}
    members: list[Member] = []
    for team_key, ids in (("A", ids_a), ("B", ids_b)):
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
            members.append(
                Member(
                    agent_id=agent_id,
                    name=str(person["name"]),
                    age=int(person["age"] or 0),
                    job=str(person["job"] or ""),
                    team=team_key,
                    persona_text=persona_block(persona),
                )
            )
    return members


def _build_teams(task: dict[str, Any], members: list[Member]) -> dict[str, Team]:
    teams = {
        "A": Team(key="A", name=_TEAM_NAMES["A"], method=dict(task["method_a"])),
        "B": Team(key="B", name=_TEAM_NAMES["B"], method=dict(task["method_b"])),
    }
    for member in members:
        teams[member.team].members.append(member)
    return teams


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _plan_text(plan: dict[str, Any] | None) -> str:
    if not plan:
        return "（还没有）"
    steps = "；".join(str(s) for s in (plan.get("steps") or []))
    return f"{plan.get('headline', '')}（做法：{steps or '—'}）"


def _move_prompt(
    member: Member,
    team: Team,
    rival: Team,
    task: dict[str, Any],
    round_index: int,
    rival_plan: dict[str, Any] | None,
) -> str:
    pressure = ""
    if round_index > 0:
        pressure = (
            f"\n你们队上一轮交的方案：{_plan_text(team.latest_plan)}\n"
            f"另一队上一轮交的方案：{_plan_text(rival_plan)}\n"
            "对手的东西摆在你面前了——这一轮要比他们做得好，但仍然只能走你们这条路。\n"
        )
    return (
        f"{member.persona_text}\n\n"
        f"【要办的事】{task['text']}\n"
        f"【算办成了】{task['goal']}\n"
        f"【你在哪一队】你被编进{team.name}。你们队定死了只用这一个办法——"
        f"{team.method['title']}：{team.method['text']}\n"
        f"另一队走的是完全相反的路子（{rival.method['title']}）。那条路你们不许用，"
        "也不用替他们说好话。\n"
        f"{pressure}\n"
        "现在轮到你出一招。按你**自己的身份**来：你手上有什么、认识谁、这件事碰到你哪里，"
        "就从那儿下手。要能落到实处——具体到做什么、找谁、什么时候，别喊口号，别写"
        "「加强宣传」「多方联动」这种谁都能说的话。你要是觉得你们队这个办法在你这儿行不通，"
        "就说清楚卡在哪，把握给低分。\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"move": "你要做的具体一件事", "why": "为什么这招在你这儿管用（或者为什么难）", '
        '"confidence": 0-100 的整数（你对这招有多大把握）}'
    )


def _plan_prompt(
    team: Team,
    rival: Team,
    task: dict[str, Any],
    round_index: int,
    rival_plan: dict[str, Any] | None,
) -> str:
    contributions = "\n".join(
        f"- {m.name}（{m.job or '—'}）：{(m.moves[-1] if m.moves else {}).get('move', '—')}"
        f"｜理由：{(m.moves[-1] if m.moves else {}).get('why', '—')}"
        f"｜把握 {(m.moves[-1] if m.moves else {}).get('confidence', 0)}"
        for m in team.members
    )
    history = ""
    if round_index > 0:
        history = (
            f"\n你们上一轮交的方案：{_plan_text(team.latest_plan)}\n"
            f"另一队上一轮交的方案：{_plan_text(rival_plan)}\n"
            "这一轮要在自己那条路上做得更扎实，不是去抄对面的做法。\n"
        )
    return (
        f"你是{team.name}的召集人。你们这个队只能用一个办法："
        f"{team.method['title']}——{team.method['text']}\n"
        f"另一队用的是{rival.method['title']}，那条路你们不能用。\n\n"
        f"【要办的事】{task['text']}\n"
        f"【算办成了】{task['goal']}\n\n"
        f"队员各自报上来的招：\n{contributions or '（没人报）'}\n"
        f"{history}\n"
        "把这些拼成一份能交上去的方案。用得上的就用，用不上的就舍掉，"
        "队员说做不到的地方别装作能做到。具体、有先后顺序、指明谁去做。\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"headline": "一句话说清你们打算怎么办成这件事", '
        '"steps": ["第一步", "第二步", "第三步"], "risk": "你们这套最可能栽在哪"}'
    )


def _judge_prompt(task: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> str:
    sheet = "\n".join(f" - {label}（{key}）：0-{MAX_SCORE} 分" for key, label in CRITERIA)
    return (
        "你是一名评审。同一件事，两个班子各交了一份方案，用的是不同的路子。请逐项打分。\n\n"
        f"【要办的事】{task['text']}\n"
        f"【算办成了】{task['goal']}\n\n"
        f"【方案一】{_plan_text(first)}\n最可能栽在：{first.get('risk', '—')}\n\n"
        f"【方案二】{_plan_text(second)}\n最可能栽在：{second.get('risk', '—')}\n\n"
        f"四个维度各打 0–{MAX_SCORE} 分（分越高越好）：\n{sheet}\n"
        "（「代价」和「副作用」打的是**这份方案好不好**：代价越小、副作用越少，分越高。）\n"
        "只看在这件事上哪份更可能真的做成，别因为某种路子听起来更正规、更有力度就给高分；"
        "也别因为两份都写得像模像样就都给高分——写得漂亮但落不了地的，可行性就该低。\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"one": {' + ", ".join(f'"{key}": 0-{MAX_SCORE}' for key, _ in CRITERIA) + "}, "
        '"two": {同样四项}, "winner": "one" 或 "two" 或 "tie", "reason": "一句话说清赢在哪"}'
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_move(raw: str) -> dict[str, Any]:
    """One member's JSON reply; an unreadable one contributes nothing."""
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {"move": text[:160] or "—", "why": "", "confidence": 0}
    try:
        confidence = int(float(payload.get("confidence", 0)))
    except (TypeError, ValueError):
        confidence = 0
    return {
        "move": str(payload.get("move") or "").strip()[:200] or "—",
        "why": str(payload.get("why") or "").strip()[:200],
        "confidence": max(0, min(100, confidence)),
    }


def parse_plan(raw: str) -> dict[str, Any]:
    """One team's JSON plan; prose survives as the headline rather than vanishing."""
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {"headline": text[:200] or "—", "steps": [], "risk": ""}
    steps = payload.get("steps")
    if isinstance(steps, str):
        steps = [steps]
    if not isinstance(steps, list):
        steps = []
    return {
        "headline": str(payload.get("headline") or "").strip()[:200] or "—",
        "steps": [str(s).strip()[:160] for s in steps if str(s).strip()][:6],
        "risk": str(payload.get("risk") or "").strip()[:200],
    }


def _score_block(payload: Any) -> dict[str, int]:
    block = payload if isinstance(payload, dict) else {}
    scores: dict[str, int] = {}
    for key, _label in CRITERIA:
        try:
            value = int(float(block.get(key, 0)))
        except (TypeError, ValueError):
            value = 0
        scores[key] = max(0, min(MAX_SCORE, value))
    scores["total"] = sum(scores[key] for key, _ in CRITERIA)
    return scores


def parse_verdict(raw: str) -> dict[str, Any]:
    """The judge's sheet: per-criterion scores plus the winner it *said*."""
    payload = first_json_object(str(raw or ""))
    said = str(payload.get("winner") or "").strip().lower()
    return {
        "one": _score_block(payload.get("one")),
        "two": _score_block(payload.get("two")),
        "judge_said": said if said in ("one", "two", "tie") else "",
        "reason": str(payload.get("reason") or "").strip()[:300],
    }


# ---------------------------------------------------------------------------
# Job plumbing — same shape as rumor_api / disaster_api.
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _new_job(kind: str) -> str:
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
            "error": None,
            **ownership.stamp(),
        }
        finished = [
            (record["started_at"], key) for key, record in _JOBS.items() if record["status"] != "running"
        ]
        while len(_JOBS) > _MAX_JOBS and finished:
            finished.sort()
            _, oldest = finished.pop(0)
            _JOBS.pop(oldest, None)
    return job_id


def _update_job(job_id: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if record is not None:
            record.update(fields)


def _run_in_background(job_id: str, work: Callable[..., Any]) -> None:
    def runner() -> None:
        try:
            result = work(lambda p, m: _update_job(job_id, progress=p, message=m))
            _update_job(job_id, status="done", progress=1.0, finished_at=time.time(), result=result)
        except Exception as exc:  # pragma: no cover - surfaced via the API
            _update_job(
                job_id,
                status="failed",
                finished_at=time.time(),
                error=f"{type(exc).__name__}: {exc}",
            )
            _LOG.exception("duel job %s failed", job_id)

    ownership.spawn(runner, name=f"duel-{job_id}")


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        return dict(record) if record is not None and ownership.visible(record) else None


def list_runs() -> list[dict[str, Any]]:
    """Finished duels still in memory, newest first."""
    with _JOBS_LOCK:
        records = [dict(r) for r in _JOBS.values() if ownership.visible(r)]
    rows = []
    for record in records:
        result = record.get("result") or {}
        if record["status"] != "done" or not result:
            continue
        verdict = result.get("verdict") or {}
        rows.append(
            {
                "job_id": record["id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "task": (result.get("task") or {}).get("title"),
                "emoji": (result.get("task") or {}).get("emoji"),
                "winner": verdict.get("winner"),
                "score_a": ((verdict.get("scores") or {}).get("A") or {}).get("total"),
                "score_b": ((verdict.get("scores") or {}).get("B") or {}).get("total"),
                "created_at": result.get("created_at"),
            }
        )
    rows.sort(key=lambda r: -(r["created_at"] or 0))
    return rows


def reset_jobs() -> None:
    """Drop every job. Used by tests; production code never calls it."""
    with _JOBS_LOCK:
        _JOBS.clear()


# ---------------------------------------------------------------------------
# The game
# ---------------------------------------------------------------------------


def _decide(scores_a: dict[str, int], scores_b: dict[str, int]) -> str:
    if scores_a["total"] > scores_b["total"]:
        return "A"
    if scores_b["total"] > scores_a["total"]:
        return "B"
    return "tie"


def judge_plans(
    task: dict[str, Any],
    plan_a: dict[str, Any],
    plan_b: dict[str, Any],
    *,
    judge_fn: Callable[[str], str] | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Score both plans blind, then let the arithmetic pick the winner."""
    rng = rng or random.Random()
    # Which team is presented first. Shuffled so neither the judge's position
    # bias nor its taste for a method name can settle on one team.
    order = ["A", "B"]
    rng.shuffle(order)
    by_key = {"A": plan_a, "B": plan_b}
    raw = (judge_fn or _default_judge_llm)(_judge_prompt(task, by_key[order[0]], by_key[order[1]]))
    sheet = parse_verdict(raw)
    scores = {order[0]: sheet["one"], order[1]: sheet["two"]}
    winner = _decide(scores["A"], scores["B"])
    said = sheet["judge_said"]
    judge_said_team = ""
    if said == "one":
        judge_said_team = order[0]
    elif said == "two":
        judge_said_team = order[1]
    elif said == "tie":
        judge_said_team = "tie"
    return {
        "winner": winner,
        "scores": scores,
        "reason": sheet["reason"],
        "judge_said": judge_said_team,
        "order": order,
        "criteria": [{"key": key, "label": label} for key, label in CRITERIA],
        "max_score": MAX_SCORE * len(CRITERIA),
    }


def run_duel(
    *,
    city: str,
    team_a: list[int] | None = None,
    team_b: list[int] | None = None,
    task_id: str = "",
    custom: dict[str, Any] | None = None,
    rounds: int = DEFAULT_ROUNDS,
    members: list[Member] | None = None,
    move_fn: Callable[[str], str] | None = None,
    plan_fn: Callable[[str], str] | None = None,
    judge_fn: Callable[[str], str] | None = None,
    rng: random.Random | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Run both teams through the task and report the scored comparison."""
    progress = progress or (lambda p, m: None)
    task = resolve_task(task_id, custom)
    round_count = max(1, min(int(rounds or DEFAULT_ROUNDS), MAX_ROUNDS))
    if members is None:
        members = load_members(city, list(team_a or []), list(team_b or []))
    if not members:
        raise ValueError("两个队各至少要一个人")

    teams = _build_teams(task, members)
    if not teams["A"].members or not teams["B"].members:
        raise ValueError("两个队各至少要一个人")

    move = move_fn or _default_move_llm
    plan = plan_fn or _default_plan_llm
    total_calls = round_count * (len(members) + 2)
    spent = 0

    for round_index in range(round_count):
        # Snapshot first: both teams answer the same rival plan, so neither
        # wins on turn order (see the module docstring).
        snapshot = {key: team.latest_plan for key, team in teams.items()}
        for key in ("A", "B"):
            team = teams[key]
            rival = teams["B" if key == "A" else "A"]
            rival_plan = snapshot[rival.key]
            for member in team.members:
                spent += 1
                progress(min(0.95, spent / total_calls), f"第 {round_index + 1} 轮 · {member.name}")
                try:
                    raw = move(_move_prompt(member, team, rival, task, round_index, rival_plan))
                except Exception as exc:  # pragma: no cover - provider failure
                    raw = ""
                    _LOG.warning("duel move call failed for #%s: %s", member.agent_id, exc)
                record = parse_move(raw)
                record["round"] = round_index
                member.moves.append(record)

            spent += 1
            progress(min(0.95, spent / total_calls), f"第 {round_index + 1} 轮 · {team.name}汇总")
            try:
                raw_plan = plan(_plan_prompt(team, rival, task, round_index, rival_plan))
            except Exception as exc:  # pragma: no cover - provider failure
                raw_plan = ""
                _LOG.warning("duel plan call failed for %s: %s", team.key, exc)
            team_plan = parse_plan(raw_plan)
            team_plan["round"] = round_index
            team.plans.append(team_plan)

    progress(0.97, "评审打分中…")
    verdict = judge_plans(
        task,
        teams["A"].latest_plan or {},
        teams["B"].latest_plan or {},
        judge_fn=judge_fn,
        rng=rng,
    )
    return {
        "run_id": uuid.uuid4().hex[:8],
        "city": city,
        "task": task,
        "rounds": round_count,
        "teams": [teams["A"].to_dict(), teams["B"].to_dict()],
        "verdict": verdict,
        "stats": _stats(teams, verdict),
        "created_at": time.time(),
    }


def _stats(teams: dict[str, Team], verdict: dict[str, Any]) -> dict[str, Any]:
    """Per-team numbers the board shows above the plans."""
    per_team = {}
    for key, team in teams.items():
        confidences = [int(m.moves[-1]["confidence"]) for m in team.members if m.moves]
        per_team[key] = {
            "members": len(team.members),
            "avg_confidence": round(sum(confidences) / len(confidences)) if confidences else 0,
            "total": (verdict["scores"].get(key) or {}).get("total", 0),
        }
    margin = abs(per_team["A"]["total"] - per_team["B"]["total"])
    return {
        "teams": per_team,
        "margin": margin,
        # A verdict the judge contradicts is worth surfacing, not smoothing:
        # it usually means the two plans are genuinely close.
        "judge_disagreed": bool(verdict["judge_said"] and verdict["judge_said"] != verdict["winner"]),
    }


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then run the duel in the background."""
    city = str(payload.get("city") or "")
    team_a = [int(i) for i in (payload.get("team_a") or [])]
    team_b = [int(i) for i in (payload.get("team_b") or [])]
    if not team_a or not team_b:
        raise ValueError("两个队各至少要一个人")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    # Fail fast on an unknown or half-written task: better a 400 now than a
    # dead job after the first model call.
    resolve_task(str(payload.get("task_id") or ""), custom)

    job_id = _new_job("duel")
    _run_in_background(
        job_id,
        lambda progress: run_duel(
            city=city,
            team_a=team_a,
            team_b=team_b,
            task_id=str(payload.get("task_id") or ""),
            custom=custom,
            rounds=int(payload.get("rounds") or DEFAULT_ROUNDS),
            progress=progress,
        ),
    )
    return job_id


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/duel/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/games/duel/catalogue":
            return {
                "tasks": list_tasks(),
                "criteria": [{"key": key, "label": label} for key, label in CRITERIA],
                "max_members": MAX_MEMBERS,
                "max_per_team": MAX_PER_TEAM,
                "max_rounds": MAX_ROUNDS,
                "default_rounds": DEFAULT_ROUNDS,
                "max_score": MAX_SCORE * len(CRITERIA),
            }, 200
        if path == "/api/games/duel/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/duel/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("duel GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown duel endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/duel/run":
            return {"job_id": start_run(payload)}, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("duel POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown duel endpoint"}, 404


__all__ = [
    "CRITERIA",
    "DEFAULT_ROUNDS",
    "MAX_MEMBERS",
    "MAX_PER_TEAM",
    "MAX_ROUNDS",
    "MAX_SCORE",
    "TASK_BANK",
    "Member",
    "Team",
    "handle_get",
    "handle_post",
    "job_status",
    "judge_plans",
    "list_runs",
    "list_tasks",
    "load_members",
    "parse_move",
    "parse_plan",
    "parse_verdict",
    "reset_jobs",
    "resolve_task",
    "run_duel",
    "start_run",
    "task_by_id",
]
