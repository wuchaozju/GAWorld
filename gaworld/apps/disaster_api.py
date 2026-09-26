"""Dashboard backend for 灾害模式 (Disaster Mode), the playground's third game.

You pick a batch of residents and a disaster; the disaster then unfolds in
*stages* (the quake, the aftershocks, the third day), and every resident
reacts to each stage **in character**. What comes out is not a winner but a
picture: who runs, who hoards, who helps, and how that mix shifts once the
second stage arrives.

Two deliberate design choices:

* **One LLM call per resident per stage — no judge.** The resident answers in
  a small JSON object (``action`` / ``detail`` / ``panic`` / ``help`` / ``say``)
  picked from a fixed action vocabulary, so the aggregate falls out of the
  answers themselves. A round therefore costs ``agents × stages + 1`` calls
  (the ``+1`` is the closing city digest).
* **The crowd is part of the prompt from stage 2 on.** Each resident is told
  what the others around them did in the previous stage — a single line built
  from the statistics we already have, not another call. Without it every
  stage is an independent draw and the interesting part of a disaster (people
  copying each other, or refusing to) never shows up.

Conventions follow :mod:`gaworld.apps.arena_api`: a background job with
progress, an in-memory store, and every LLM entry point injectable
(``answer_fn=`` / ``summary_fn=``) so tests never touch a provider. Nothing
here writes to a city bundle — a game is a sandbox, not a simulation run.
"""

from __future__ import annotations

import statistics
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gaworld.apps.games_api import first_json_object
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.disaster_api")

#: Residents in one round. A round is ``agents × stages`` sequential LLM
#: calls, so this is the difference between a coffee and a lunch break.
MAX_AGENTS = 12
#: Stages actually played when the caller says nothing.
DEFAULT_STAGES = 2
#: Every built-in disaster is written with three stages; custom ones are
#: clamped to the same ceiling for the same cost reason.
MAX_STAGES = 3

#: The action vocabulary. The resident must pick exactly one of these, which
#: is what makes the per-stage histogram comparable across disasters.
ACTIONS: tuple[str, ...] = (
    "避险逃离",
    "囤积物资",
    "救助他人",
    "求助求援",
    "照常生活",
    "打探消息",
)
#: Where an off-vocabulary answer lands. Kept out of ``ACTIONS`` so the model
#: is never offered it as a choice.
OTHER_ACTION = "其他"

_MAX_JOBS = 20


# ---------------------------------------------------------------------------
# Disaster bank
# ---------------------------------------------------------------------------

#: Built-in disasters. Stages are written city-agnostically (no street names,
#: no local institutions) so the same script runs in any city bundle, and they
#: escalate along the axis that actually changes behaviour: how long it has
#: been going on and what has stopped working.
DISASTER_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "earthquake",
        "name": "地震",
        "emoji": "🌍",
        "summary": "凌晨的强震，余震不断，第三天开始重建",
        "stages": [
            "凌晨 3 点 17 分，一场 6.8 级地震把整座城市摇醒。楼在响，玻璃碎了一地，"
            "电断了，手机只剩一两格信号，楼道里全是往下跑的人。",
            "12 小时后：余震还在继续，自来水停了，小区空地上支起了帐篷，"
            "超市门口排起长队。官方通报主震已过，但仍有 5 级余震的可能。",
            "第三天：救援队进城，学校操场改成安置点，一部分小区恢复供电。"
            "你住的那栋楼被贴了黄色告示——要等进一步检测才能住人。",
        ],
    },
    {
        "id": "epidemic",
        "name": "疫情",
        "emoji": "🦠",
        "summary": "不明肺炎、封控与全员核酸，两个月后的放开",
        "stages": [
            "本地医院一天内接诊三十多例不明原因肺炎，官方通报了首例确诊，"
            "建议减少聚集。药店的口罩一夜之间卖空，群里开始传各种说法。",
            "两周后：确诊过千，学校停课，部分小区封闭管理，你所在的街道开始全员核酸。"
            "谣言比通知传得快，有人囤了半年的米。",
            "两个月后：新增开始回落，管控逐步放开。有些店再没开过门，"
            "有人还困在后遗症里，也有人觉得这一切早就该结束了。",
        ],
    },
    {
        "id": "war",
        "name": "战争",
        "emoji": "🛡️",
        "summary": "边境冲突升级，物价与征召，走还是留",
        "stages": [
            "边境冲突升级，深夜的防空警报第一次拉响。加油站排起长队，"
            "银行 ATM 前的队伍绕了半条街，新闻里的说法一小时一个样。",
            "一周后：主要公路设了检查站，物价翻倍，征召通告贴到了社区公告栏，"
            "网络时断时续。有人已经带着家人往南走了。",
            "一个月后：前线离这里还有两百公里，城里多了外地来的人，"
            "学校腾出教室安置他们。你得决定：留下，还是走。",
        ],
    },
    {
        "id": "flood",
        "name": "洪水",
        "emoji": "🌊",
        "summary": "暴雨漫堤、断电断网，退水后的一地淤泥",
        "stages": [
            "连续暴雨 36 小时，河水漫过堤坝，低洼路段积水到腰。地铁停运，"
            "气象台发布红色预警，物业在群里喊着让一楼住户搬东西上楼。",
            "第二天：一楼全部进水，小区断电断网，救援皮艇在街面上来回，"
            "超市的货架空了一半，能充上电的地方排着队。",
            "第五天：水退了，满地淤泥，家里的电器基本报废。保险公司的电话打不通，社区开始挨家挨户统计损失。",
        ],
    },
    {
        "id": "blackout",
        "name": "大停电",
        "emoji": "🔌",
        "summary": "全城断电，现金重新变成唯一能用的钱",
        "stages": [
            "傍晚 6 点，全城停电。红绿灯灭了，电梯里困了人，手机基站靠备用电池撑着，信号一格一格往下掉。",
            "12 小时后：电还没来。冰箱里的东西开始坏，加油站抽不上油，"
            "扫码付不了款，现金重新成了唯一能用的钱。",
            "第三天：部分城区恢复供电，官方说全面恢复还要几天。"
            "医院靠柴油发电机维持，小区群里在互相借充电宝和蜡烛。",
        ],
    },
)


def list_disasters() -> list[dict[str, Any]]:
    """The catalogue shown in the picker."""
    return [
        {
            "id": d["id"],
            "name": d["name"],
            "emoji": d["emoji"],
            "summary": d["summary"],
            "stages": list(d["stages"]),
        }
        for d in DISASTER_BANK
    ]


def disaster_by_id(disaster_id: str) -> dict[str, Any] | None:
    for item in DISASTER_BANK:
        if item["id"] == disaster_id:
            return item
    return None


def _custom_disaster(custom: dict[str, Any]) -> dict[str, Any]:
    """Turn the free-form ``custom`` payload into a bank-shaped disaster.

    ``stages`` may be a list or one blob of text: a user who pastes three
    paragraphs means three stages, and a user who types one sentence means
    one.
    """
    raw_stages = custom.get("stages")
    if isinstance(raw_stages, str):
        parts = [line.strip() for line in raw_stages.splitlines()]
    elif isinstance(raw_stages, (list, tuple)):
        parts = [str(line).strip() for line in raw_stages]
    else:
        parts = []
    stages = [p for p in parts if p]
    if not stages:
        raise ValueError("自定义灾难要至少写一段情境")
    return {
        "id": "custom",
        "name": str(custom.get("name") or "自定义灾难").strip() or "自定义灾难",
        "emoji": str(custom.get("emoji") or "⚠️"),
        "summary": stages[0][:40],
        "stages": stages[:MAX_STAGES],
    }


def resolve_disaster(disaster_id: str, custom: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pick the disaster to play: a built-in one, or the caller's own."""
    if custom:
        return _custom_disaster(custom)
    found = disaster_by_id(str(disaster_id or ""))
    if found is None:
        raise ValueError(f"没有这种灾难：{disaster_id or '（未选）'}")
    return found


# ---------------------------------------------------------------------------
# LLM entry points
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, *, task: str, temperature: float) -> str:
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task=task, temperature=temperature, allow_fallback=True))


def _default_reaction_llm(prompt: str) -> str:
    """The resident under stress. Warm, but it still has to return JSON."""
    return _call_llm(prompt, task="games.disaster", temperature=0.7)


def _default_summary_llm(prompt: str) -> str:
    """The closing city digest — one paragraph, so keep it steady."""
    return _call_llm(prompt, task="games.disaster.summary", temperature=0.3)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def _crowd_line(previous: dict[str, Any] | None) -> str:
    """What the neighbours did last stage, as one line of prompt.

    Built from statistics we already computed, so herd behaviour costs no
    extra LLM call. Returns ``""`` for the first stage, where there is no
    crowd yet.
    """
    if not previous:
        return ""
    counts = previous.get("actions") or {}
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return ""
    parts = "、".join(f"{n} 人{action}" for action, n in ranked[:3])
    return f"你看到身边的人：{parts}。"


def _reaction_prompt(
    persona_text: str,
    disaster: dict[str, Any],
    stage_index: int,
    stage_text: str,
    own_history: list[dict[str, Any]],
    crowd_line: str,
) -> str:
    history = ""
    if own_history:
        lines = "\n".join(
            f"第 {item['stage'] + 1} 阶段，你{item['action']}：{item['detail']}" for item in own_history
        )
        history = f"\n你之前做过的事：\n{lines}\n"
    actions = " / ".join(ACTIONS)
    return (
        f"{persona_text}\n\n"
        f"你所在的城市发生了{disaster['name']}。\n"
        f"【现在的情况】{stage_text}\n"
        f"{history}"
        f"{crowd_line}\n\n"
        "请以你自己的处境、性格、家庭和能力出发，决定接下来要做什么。"
        "你的职业、收入、上有老下有小、身体状况，都会影响这个决定——"
        "不要给一个'正确'的标准答案，给你这个人真的会做的事。\n"
        f"从这几类行动里选**一个**最贴近的：{actions}。\n"
        "只输出一个 JSON 对象，不要任何解释：\n"
        '{"action": "上面六类中的一个", "detail": "你具体要做什么，一句话", '
        '"panic": 1-5 的整数（1=基本不慌，5=极度恐慌）, "help": true 或 false（是否顾得上帮别人）, '
        '"say": "此刻你会说出口的一句话，第一人称"}'
    )


def _summary_prompt(disaster: dict[str, Any], run: dict[str, Any]) -> str:
    stats = run["stats"]["overall"]
    ranked = sorted((stats.get("actions") or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    spread = "、".join(f"{action} {n} 人次" for action, n in ranked) or "（无）"
    voices = []
    for person in run["agents"][:6]:
        last = person["reactions"][-1] if person["reactions"] else None
        if last:
            voices.append(f"- {person['name']}（{person.get('job') or '—'}）：{last['say']}")
    # Only ask about escalation when there is a later stage to escalate into;
    # otherwise the model invents a second act that never happened.
    drift = "什么行为在后面的阶段被放大了" if len(run["stages"]) > 1 else "谁的反应最出人意料"
    return (
        "你是一名社会学观察者，下面是一场灾难中若干居民的真实反应记录。\n"
        f"请写一段 150 字以内的简报：人群整体是怎么反应的，出现了哪几种分化，谁最脆弱，{drift}。"
        "要具体，不要空话，不要罗列要点。\n\n"
        f"灾难：{disaster['name']}\n"
        f"人数：{len(run['agents'])}，阶段数：{len(run['stages'])}\n"
        f"行动分布：{spread}\n"
        f"平均恐慌值：{stats.get('avg_panic')}（1-5），互助率：{stats.get('help_rate')}\n"
        f"其中几个人的原话：\n" + "\n".join(voices)
    )


# ---------------------------------------------------------------------------
# Parsing + aggregation
# ---------------------------------------------------------------------------


def _coerce_action(value: Any) -> str:
    """Map a free-form action onto the vocabulary; unknown → ``其他``."""
    text = str(value or "").strip()
    if text in ACTIONS:
        return text
    for action in ACTIONS:
        if action in text or text in action:
            return action
    return OTHER_ACTION


def parse_reaction(raw: str) -> dict[str, Any]:
    """Read one resident's JSON reply, tolerating prose around the object.

    A malformed reply never kills a round: it degrades to ``其他`` with a
    neutral panic level, and the raw text is kept as the quote so the user
    can see what actually came back.
    """
    text = str(raw or "").strip()
    payload = first_json_object(text)
    if not payload:
        return {
            "action": OTHER_ACTION,
            "detail": text[:120] or "（没有返回有效内容）",
            "panic": 3,
            "help": False,
            "say": text[:120],
        }
    try:
        panic = int(float(payload.get("panic", 3)))
    except (TypeError, ValueError):
        panic = 3
    return {
        "action": _coerce_action(payload.get("action")),
        "detail": str(payload.get("detail") or "").strip()[:200],
        "panic": max(1, min(5, panic)),
        "help": bool(payload.get("help")),
        "say": str(payload.get("say") or "").strip()[:200],
    }


def _aggregate(reactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Histogram + panic + altruism for one stage (or for the whole run)."""
    counts: dict[str, int] = {}
    for item in reactions:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    panics = [item["panic"] for item in reactions]
    helpers = sum(1 for item in reactions if item["help"])
    n = len(reactions)
    return {
        "n": n,
        "actions": counts,
        "avg_panic": round(statistics.mean(panics), 2) if panics else 0.0,
        "max_panic": max(panics) if panics else 0,
        "help_rate": round(helpers / n, 2) if n else 0.0,
    }


# ---------------------------------------------------------------------------
# Job plumbing — same shape as arena_api / population_api.
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
            _LOG.exception("disaster job %s failed", job_id)

    thread = threading.Thread(target=runner, name=f"disaster-{job_id}", daemon=True)
    thread.start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        return dict(record) if record is not None else None


def list_runs() -> list[dict[str, Any]]:
    """Finished rounds still in memory, newest first."""
    with _JOBS_LOCK:
        records = [dict(r) for r in _JOBS.values()]
    rows = []
    for record in records:
        result = record.get("result") or {}
        if record["status"] != "done" or not result:
            continue
        rows.append(
            {
                "job_id": record["id"],
                "run_id": result.get("run_id"),
                "city": result.get("city"),
                "disaster": (result.get("disaster") or {}).get("name"),
                "emoji": (result.get("disaster") or {}).get("emoji"),
                "agents": len(result.get("agents") or []),
                "stages": len(result.get("stages") or []),
                "avg_panic": (result.get("stats") or {}).get("overall", {}).get("avg_panic"),
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


@dataclass
class Participant:
    """One resident on the board, with their reactions so far."""

    agent_id: int
    name: str
    job: str = ""
    persona_text: str = ""
    reactions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        panics = [r["panic"] for r in self.reactions]
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "job": self.job,
            "reactions": list(self.reactions),
            "avg_panic": round(statistics.mean(panics), 2) if panics else 0.0,
            "helped": any(r["help"] for r in self.reactions),
        }


def _load_participants(city: str, agent_ids: list[int]) -> list[Participant]:
    from gaworld.apps.games_api import load_persona, persona_block

    people: list[Participant] = []
    for agent_id in agent_ids:
        persona = load_persona(city, agent_id)
        people.append(
            Participant(
                agent_id=int(persona["agent_id"]),
                name=str(persona.get("name") or f"#{agent_id}"),
                job=str(persona.get("job") or ""),
                persona_text=persona_block(persona),
            )
        )
    return people


def run_disaster(
    *,
    city: str,
    agent_ids: list[int],
    disaster_id: str = "",
    custom: dict[str, Any] | None = None,
    stages: int = DEFAULT_STAGES,
    participants: list[Participant] | None = None,
    answer_fn: Callable[[str], str] | None = None,
    summary_fn: Callable[[str], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Play one disaster: every resident reacts to every stage, in order."""
    progress = progress or (lambda p, m: None)
    ids = [int(i) for i in (agent_ids or [])][:MAX_AGENTS]
    if not ids and participants is None:
        raise ValueError("先选几个智能体")

    disaster = resolve_disaster(disaster_id, custom)
    stage_count = max(1, min(int(stages or DEFAULT_STAGES), MAX_STAGES, len(disaster["stages"])))
    stage_texts = list(disaster["stages"])[:stage_count]

    people = participants if participants is not None else _load_participants(city, ids)
    if not people:
        raise ValueError("先选几个智能体")

    answer = answer_fn or _default_reaction_llm
    per_stage: list[dict[str, Any]] = []
    total_steps = max(1, len(people) * len(stage_texts))
    step = 0

    for stage_index, stage_text in enumerate(stage_texts):
        crowd = _crowd_line(per_stage[-1] if per_stage else None)
        stage_reactions: list[dict[str, Any]] = []
        for person in people:
            step += 1
            progress(step / total_steps * 0.92, f"第 {stage_index + 1} 幕 · {person.name}")
            prompt = _reaction_prompt(
                person.persona_text, disaster, stage_index, stage_text, person.reactions, crowd
            )
            try:
                raw = answer(prompt)
            except Exception as exc:  # pragma: no cover - provider failure
                _LOG.warning("disaster reaction failed for #%s: %s", person.agent_id, exc)
                raw = ""
            reaction = parse_reaction(raw)
            reaction["stage"] = stage_index
            person.reactions.append(reaction)
            stage_reactions.append(reaction)
        summary = _aggregate(stage_reactions)
        summary["stage"] = stage_index
        summary["text"] = stage_text
        per_stage.append(summary)

    flat = [r for person in people for r in person.reactions]
    run = {
        "run_id": uuid.uuid4().hex[:8],
        "city": str(city or ""),
        "disaster": {"id": disaster["id"], "name": disaster["name"], "emoji": disaster["emoji"]},
        "stages": stage_texts,
        "agents": [person.to_dict() for person in people],
        "stats": {"per_stage": per_stage, "overall": _aggregate(flat)},
        "summary": "",
        "created_at": time.time(),
    }

    progress(0.95, "正在写城市简报…")
    try:
        digest = (summary_fn or _default_summary_llm)(_summary_prompt(disaster, run))
        run["summary"] = str(digest).strip()
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("disaster summary failed: %s", exc)
        run["summary"] = ""
    return run


def start_run(payload: dict[str, Any]) -> str:
    """Validate the request, then play the round in the background."""
    city = str(payload.get("city") or "")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if not agent_ids:
        raise ValueError("先选几个智能体")
    custom = payload.get("custom") if isinstance(payload.get("custom"), dict) else None
    # Fail fast on an unknown disaster: better a 400 now than a dead job.
    resolve_disaster(str(payload.get("disaster_id") or ""), custom)
    stages = int(payload.get("stages") or DEFAULT_STAGES)

    job_id = _new_job("disaster")
    _run_in_background(
        job_id,
        lambda progress: run_disaster(
            city=city,
            agent_ids=agent_ids,
            disaster_id=str(payload.get("disaster_id") or ""),
            custom=custom,
            stages=stages,
            progress=progress,
        ),
    )
    return job_id


# ---------------------------------------------------------------------------
# HTTP delegation — reached via games_api's /api/games/disaster/ branch.
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    try:
        if path == "/api/games/disaster/catalogue":
            return {
                "disasters": list_disasters(),
                "max_agents": MAX_AGENTS,
                "max_stages": MAX_STAGES,
                "default_stages": DEFAULT_STAGES,
                "actions": list(ACTIONS),
            }, 200
        if path == "/api/games/disaster/runs":
            return {"runs": list_runs()}, 200
        if path.startswith("/api/games/disaster/jobs/"):
            record = job_status(path.rsplit("/", 1)[-1])
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("disaster GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown disaster endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/games/disaster/run":
            return {"job_id": start_run(payload)}, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("disaster POST %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown disaster endpoint"}, 404


__all__ = [
    "ACTIONS",
    "DEFAULT_STAGES",
    "DISASTER_BANK",
    "MAX_AGENTS",
    "MAX_STAGES",
    "OTHER_ACTION",
    "Participant",
    "disaster_by_id",
    "handle_get",
    "handle_post",
    "job_status",
    "list_disasters",
    "list_runs",
    "parse_reaction",
    "reset_jobs",
    "resolve_disaster",
    "run_disaster",
    "start_run",
]
