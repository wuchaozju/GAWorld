"""Dashboard backend for the Agent Arena.

A *delegate* module, not more routes bolted into ``dashboard_server.py``.
The arena is a self-contained LLM-evaluation sandbox:

* agents are loaded from a city bundle via :mod:`gaworld.city.agents`;
* tasks are picked from a built-in template bank or generated on the fly
  by an LLM judge acting as a question author;
* a single judge LLM grades every answer against the canonical solution;
* the leaderboard ranks contestants by accuracy and median latency;
* the user picks a Top-K to retain, and the rest are *flagged* (we never
  delete profiles — elimination is a status marker on the agent record);
* re-stocking pulls agents either from another city (``pull_from_city``)
  or from the existing bulk-import workflow.

The module never registers an HTTP route: ``dashboard_server._handle_api_*``
forwards ``/api/arena/*`` here via the same delegate pattern as
``population_api`` and ``persona_api``.

Notes on LLM calls:
* ``call_llm`` is the only LLM entry point we touch. Tests inject a stub
  via the ``llm_fn=`` parameter on each public function; nothing in this
  module imports :mod:`gaworld.llm.providers` directly so a missing key
  in the dev environment does not block tests.
* The judge prompt is intentionally strict: it returns ``{"score": 0|1}``
  with no half-credit. Median latency is the second axis of ranking.
"""

from __future__ import annotations

import json
import random
import statistics
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from gaworld.city.bundle import resolve_city
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.arena_api")

# ---------------------------------------------------------------------------
# Job plumbing — same shape as population_api / import_api.
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 20


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
            _LOG.exception("arena job %s failed", job_id)

    thread = threading.Thread(target=runner, name=f"arena-{job_id}", daemon=True)
    thread.start()


def job_status(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        return dict(record) if record is not None else None


# ---------------------------------------------------------------------------
# Task templates
# ---------------------------------------------------------------------------

#: Built-in task bank. Each template is a tuple ``(category, prompt, expected)``.
#: ``expected`` is either a string for exact match (after ``.strip().lower()``)
#: or a callable that accepts the answer and returns ``bool``/``0|1``.
TASK_BANK: tuple[dict[str, Any], ...] = (
    {
        "id": "arith-add",
        "category": "math",
        "title": "加法：基础",
        "prompt": "12 + 7 等于多少？只输出数字。",
        "expected": "19",
    },
    {
        "id": "arith-mul",
        "category": "math",
        "title": "乘法：双位",
        "prompt": "37 × 24 等于多少？只输出数字。",
        "expected": "888",
    },
    {
        "id": "gsm-tickets",
        "category": "math",
        "title": "GSM8K 风格：购票",
        "prompt": (
            "小李买 3 张成人票，每张 45 元；用 200 元现金支付。问：应找回多少钱？只输出数字，不要带单位。"
        ),
        "expected": "65",
    },
    {
        "id": "qa-capital",
        "category": "qa",
        "title": "常识问答：首都",
        "prompt": "法国的首都是哪座城市？只输出城市名。",
        "expected": "巴黎",
    },
    {
        "id": "qa-chemistry",
        "category": "qa",
        "title": "常识问答：元素",
        "prompt": "水的化学分子式是什么？只输出分子式。",
        "expected": "h2o",
    },
    {
        "id": "logic-sequence",
        "category": "logic",
        "title": "逻辑推理：数列",
        "prompt": "数列 2, 6, 18, 54, ? 的下一个数是多少？只输出数字。",
        "expected": "162",
    },
    {
        "id": "logic-conditional",
        "category": "logic",
        "title": "逻辑推理：条件",
        "prompt": (
            "如果所有的 A 都是 B，并且有些 B 不是 A，那么 '所有 A 都是 C ' 能推出吗？只回答 是 / 否。"
        ),
        "expected": "否",
    },
    {
        "id": "reading-summary",
        "category": "reading",
        "title": "阅读理解：摘要",
        "prompt": (
            "阅读下文并用一句话（≤30 字）概括主旨：\n\n"
            "2025 年浙江省推出了一项针对小微企业的税收减免新政，"
            "覆盖 12 个行业，预计每年减免税额约 17 亿元，"
            "惠及企业超过 4 万家。"
        ),
        # Evaluated by judge because summarisation is not a strict match.
        "expected": "浙江省对小微企业实施税收减免，惠及 4 万余家。",
    },
    {
        "id": "translate-en",
        "category": "translate",
        "title": "中英互译：英 → 中",
        "prompt": (
            "把下面的英文句子翻译成中文：\n"
            '"The early bird catches the worm, but the second mouse gets the cheese."\n'
            "只输出中文翻译。"
        ),
        "expected": "早起的鸟儿有虫吃，但第二只老鼠得到了奶酪。",
    },
    {
        "id": "math-perimeter",
        "category": "math",
        "title": "周长：长方形",
        "prompt": "一个长 12、宽 5 的长方形周长是多少？只输出数字。",
        "expected": "34",
    },
)


def task_by_id(task_id: str) -> dict[str, Any] | None:
    for task in TASK_BANK:
        if task["id"] == task_id:
            return task
    return None


# ---------------------------------------------------------------------------
# Agent loading
# ---------------------------------------------------------------------------


def _read_profiles_md(profiles_md_path) -> str:
    """Read the profiles Markdown, defaulting to empty when missing."""
    try:
        return profiles_md_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _list_agents(city_ref: str, *, city_root: Any = None) -> list[dict[str, Any]]:
    """Return one ``{id, name}`` per agent in *city_ref*.

    Reads the city's ``agents.csv`` and (when present) joins with the names
    stored in the profiles Markdown so the arena UI can display them.
    """
    bundle = resolve_city(city_ref, root=city_root)
    state_csv = bundle.state_csv_path
    if not state_csv.exists():
        return []
    import csv

    with state_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    # Reuse parse_profile to pick names out of profiles.md (preferred over
    # the state-csv name column which may have been anonymised to the
    # fake pool — the persona blocks still carry the original name).
    profiles_text = _read_profiles_md(bundle.profiles_md_path)
    name_by_id: dict[int, str] = {}
    for block in profiles_text.split("## Profile "):
        block = block.strip()
        if not block:
            continue
        try:
            from gaworld.sim.agents_loader import parse_profile

            fields = parse_profile("## Profile " + block)
            head = block.splitlines()[0]
            head_id = head.split("｜", 1)[0].strip()
            name_by_id[int(head_id)] = fields.get("name") or ""
        except Exception:
            continue

    agents: list[dict[str, Any]] = []
    for row in rows:
        try:
            agent_id = int(row["id"])
        except (KeyError, ValueError):
            continue
        agents.append(
            {
                "id": agent_id,
                "name": name_by_id.get(agent_id) or row.get("name") or f"#{agent_id}",
                "gender": row.get("gender") or "",
                "age": int(row.get("age") or 0),
                "industry": row.get("industry") or "",
            }
        )
    return agents


# ---------------------------------------------------------------------------
# Answer generation + judging
# ---------------------------------------------------------------------------


def _default_llm(prompt: str) -> str:
    """Default LLM caller; swappable in tests via ``llm_fn=``."""
    from gaworld.llm.providers import call_llm

    return str(call_llm(prompt, task="arena.answer", temperature=0.2, allow_fallback=True))


def _judge_prompt(question: str, expected: Any, answer: str) -> str:
    expected_str = expected if isinstance(expected, str) else str(expected)
    return (
        "你是一名严格的答题裁判。给定一道题与参考答案，请判断选手的回答是否实质正确。\n"
        "评分规则：\n"
        " - 完全正确（含等价表述、单位等价、中英翻译都贴合原意）→ score=1\n"
        " - 否则 → score=0\n"
        '只允许输出形如 {"score": 1} 或 {"score": 0} 的 JSON 对象，不要解释。\n\n'
        f"题目：{question}\n"
        f"参考答案：{expected_str}\n"
        f"选手回答：{answer}\n"
    )


def _score_with_judge(
    question: str,
    expected: Any,
    answer: str,
    *,
    llm_fn: Callable[[str], str] | None = None,
) -> int:
    """Score one answer.

    * If ``expected`` is a strict string we compare normalised strings
      first (cheap, deterministic).
    * Otherwise we delegate to the judge LLM, with a JSON parser that
      tolerates stray prose around the verdict.
    """
    if isinstance(expected, str) and _normalize(answer) == _normalize(expected):
        return 1
    if isinstance(expected, str) and expected.strip() == "":
        # No reference answer → can't grade strictly.
        return 0
    fn = llm_fn or _default_llm
    try:
        raw = fn(_judge_prompt(question, expected, answer))
    except Exception as exc:  # pragma: no cover - provider failure
        _LOG.warning("judge call failed: %s", exc)
        return 0
    try:
        payload = json.loads(raw)
        score = int(payload.get("score", 0))
        return 1 if score >= 1 else 0
    except (ValueError, TypeError):
        # Tolerate a stray "score: 1" or "1" reply.
        text = raw.strip().lower()
        if text.endswith("1") or '"score": 1' in text or "score: 1" in text:
            return 1
        return 0


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------


_GENERATE_PROMPT = (
    "请按以下要求生成 {n} 道题，作为一组 benchmark。\n"
    "要求：\n"
    " - 每道题覆盖类别：{categories}\n"
    " - 难度：{difficulty}\n"
    ' - 每题用 JSON 格式：{{"category": "...", "title": "...", '
    '"prompt": "...", "expected": "..."}}\n'
    " - 输出一行一个 JSON，整体放进一个 JSON 数组里。\n"
    '示例：[{{"category":"math","title":"加法","prompt":"1+1=?",'
    '"expected":"2"}}]\n'
)


def generate_questions(
    *,
    n: int,
    categories: list[str],
    difficulty: str,
    llm_fn: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Use the LLM to author ``n`` benchmark tasks."""
    fn = llm_fn or _default_llm
    prompt = _GENERATE_PROMPT.format(
        n=int(n),
        categories=", ".join(categories) or "math, qa, logic",
        difficulty=difficulty or "medium",
    )
    raw = fn(prompt)
    tasks: list[dict[str, Any]] = []
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            tasks = [item for item in payload if isinstance(item, dict)]
    except ValueError:
        # Some providers wrap the array in prose; try a lenient extract.
        import re

        for match in re.finditer(r"\{[^{}]*\"expected\"[^{}]*\}", raw):
            try:
                tasks.append(json.loads(match.group(0)))
            except ValueError:
                continue
    # Guarantee that every task has the four required fields.
    cleaned: list[dict[str, Any]] = []
    for task in tasks[:n]:
        if not all(k in task for k in ("category", "prompt", "expected")):
            continue
        cleaned.append(
            {
                "id": f"gen-{uuid.uuid4().hex[:6]}",
                "category": str(task["category"]),
                "title": str(task.get("title") or task["category"]),
                "prompt": str(task["prompt"]),
                "expected": str(task["expected"]),
            }
        )
    if not cleaned:
        raise ValueError("LLM 未生成任何可用题目，请重试或降低题数")
    return cleaned


# ---------------------------------------------------------------------------
# Contest data model
# ---------------------------------------------------------------------------


@dataclass
class ContestantResult:
    agent_id: int
    name: str
    correct: int = 0
    attempted: int = 0
    latencies: list[float] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (self.correct / self.attempted) if self.attempted else 0.0

    @property
    def median_latency(self) -> float:
        return statistics.median(self.latencies) if self.latencies else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "correct": self.correct,
            "attempted": self.attempted,
            "accuracy": round(self.accuracy, 4),
            "median_latency_s": round(self.median_latency, 3),
        }


@dataclass
class RoundResult:
    round_id: str
    city: str
    task_ids: list[str]
    leaderboard: list[ContestantResult]
    eliminated: list[int] = field(default_factory=list)
    survivors: list[int] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_id": self.round_id,
            "city": self.city,
            "task_ids": self.task_ids,
            "leaderboard": [c.to_dict() for c in self.leaderboard],
            "eliminated": self.eliminated,
            "survivors": self.survivors,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Run a round
# ---------------------------------------------------------------------------


def _build_agent_prompt(task_prompt: str, agent: dict[str, Any]) -> str:
    persona_bits = []
    if agent.get("industry"):
        persona_bits.append(f"行业：{agent['industry']}")
    if agent.get("age"):
        persona_bits.append(f"年龄：{agent['age']}")
    persona = "；".join(persona_bits) or "通用背景"
    return (
        f"你是 #{agent['id']} {agent.get('name', '')}（{persona}）。\n"
        "请直接、简洁地回答下面的题目，只输出答案本身，不要解释。\n\n"
        f"题目：{task_prompt}"
    )


def run_round(
    *,
    city_ref: str,
    agent_ids: list[int],
    task_ids: list[str] | None,
    custom_tasks: list[dict[str, Any]] | None = None,
    judge_fn: Callable[[str, Any, str], int] | None = None,
    answer_fn: Callable[[str], str] | None = None,
    city_root: Any = None,
    progress: Callable[[float, str], None] | None = None,
) -> RoundResult:
    """Execute a single arena round and return the leaderboard."""
    progress = progress or (lambda p, m: None)
    agents_all = _list_agents(city_ref, city_root=city_root)
    agents_by_id = {a["id"]: a for a in agents_all}
    contestants = [agents_by_id[i] for i in agent_ids if i in agents_by_id]
    if not contestants:
        raise ValueError("所选选手不在该城市里")

    tasks: list[dict[str, Any]] = []
    if custom_tasks:
        tasks.extend(custom_tasks)
    if task_ids:
        for tid in task_ids:
            task = task_by_id(tid)
            if task is not None:
                tasks.append(task)
    if not tasks:
        raise ValueError("至少要选一道题")

    judge = judge_fn or (lambda q, e, a: _score_with_judge(q, e, a, llm_fn=None))
    answer = answer_fn or _default_llm

    results: dict[int, ContestantResult] = {
        a["id"]: ContestantResult(agent_id=a["id"], name=a.get("name") or f"#{a['id']}") for a in contestants
    }

    total_steps = max(1, len(contestants) * len(tasks))
    step = 0
    for task in tasks:
        for agent in contestants:
            step += 1
            progress(step / total_steps * 0.95, f"问 {agent['name']}：{task['title']}")
            prompt = _build_agent_prompt(task["prompt"], agent)
            started = time.time()
            try:
                response = answer(prompt)
            except Exception as exc:  # pragma: no cover - provider failure
                response = f"[error] {exc}"
            elapsed = time.time() - started
            rec = results[agent["id"]]
            rec.attempted += 1
            rec.latencies.append(elapsed)
            score = judge(task["prompt"], task["expected"], response)
            rec.correct += score
            rec.answers.append(
                {
                    "task_id": task["id"],
                    "prompt": task["prompt"],
                    "expected": task["expected"],
                    "answer": response,
                    "score": score,
                    "latency_s": round(elapsed, 3),
                }
            )

    leaderboard = sorted(
        results.values(),
        key=lambda r: (-r.accuracy, r.median_latency),
    )
    return RoundResult(
        round_id=uuid.uuid4().hex[:8],
        city=city_ref,
        task_ids=[t["id"] for t in tasks],
        leaderboard=leaderboard,
    )


# ---------------------------------------------------------------------------
# Top-K retain / elimination / refill
# ---------------------------------------------------------------------------


#: In-memory store of elimination flags keyed by (city_slug, agent_id).
#: Persistent storage is intentionally avoided so an arena session never
#: mutates the long-lived city bundle; the front-end can still show the
#: survivors/eliminated lists until the next reload.
_ELIMINATED: dict[tuple[str, int], float] = {}
_ELIM_LOCK = threading.Lock()


def mark_eliminated(city_ref: str, agent_ids: Iterable[int]) -> list[int]:
    city_slug = _city_slug(city_ref)
    with _ELIM_LOCK:
        for agent_id in agent_ids:
            _ELIMINATED[(city_slug, int(agent_id))] = time.time()
    return sorted({int(i) for i in agent_ids})


def is_eliminated(city_ref: str, agent_id: int) -> bool:
    return (_city_slug(city_ref), int(agent_id)) in _ELIMINATED


def eliminated_for(city_ref: str) -> list[int]:
    slug = _city_slug(city_ref)
    return sorted(aid for (c, aid) in _ELIMINATED if c == slug)


def reset_eliminated(city_ref: str | None = None) -> None:
    """Clear the in-memory elimination ledger.

    Pass ``city_ref`` to clear one city; pass ``None`` to clear every city.
    Used by tests so they don't leak state across cases; production code
    never calls it.
    """
    with _ELIM_LOCK:
        if city_ref is None:
            _ELIMINATED.clear()
        else:
            slug = _city_slug(city_ref)
            for key in list(_ELIMINATED.keys()):
                if key[0] == slug:
                    _ELIMINATED.pop(key, None)


def survivors_for(city_ref: str, agent_ids: Iterable[int]) -> list[int]:
    slug = _city_slug(city_ref)
    return sorted(int(i) for i in agent_ids if (slug, int(i)) not in _ELIMINATED)


def _city_slug(city_ref: str) -> str:
    try:
        return resolve_city(city_ref).slug
    except Exception:
        return str(city_ref)


def apply_topk(city_ref: str, leaderboard: list[dict[str, Any]], k: int) -> dict[str, Any]:
    """Keep the top-K contestants in the leaderboard; mark the rest eliminated.

    *K* is clamped to ``[1, len(leaderboard)]``. Agents already eliminated
    (from a previous round) are not promoted back.
    """
    k = max(0, min(int(k), len(leaderboard)))
    keep_ids = {row["agent_id"] for row in leaderboard[:k]}
    drop_ids = {row["agent_id"] for row in leaderboard[k:]}
    drop_ids -= keep_ids
    mark_eliminated(city_ref, drop_ids)
    survivors = sorted(keep_ids)
    return {
        "city": _city_slug(city_ref),
        "k": k,
        "survivors": survivors,
        "eliminated": sorted(drop_ids),
        "all_eliminated": eliminated_for(city_ref),
    }


def refill_from_city(city_ref: str, *, other_city: str, n: int, city_root: Any = None) -> dict[str, Any]:
    """Pull *n* agents from *other_city* into *city_ref*.

    The pulled agents are *appended* to the destination city via the same
    :func:`gaworld.city.agents.add_agent` path used by single-agent edits.
    The destination's persona block carries the source name with a
    "(refill)" suffix so a quick visual scan reveals where they came from.
    """
    from gaworld.city.agents import add_agent

    destination = resolve_city(city_ref, root=city_root)
    source_agents = _list_agents(other_city, city_root=city_root)
    if not source_agents:
        raise ValueError(f"source city {other_city!r} has no agents")
    pool = [a for a in source_agents if not is_eliminated(other_city, a["id"])]
    if not pool:
        raise ValueError(f"source city {other_city!r} has no live agents")
    pick = random.sample(pool, k=min(int(n), len(pool)))
    added: list[int] = []
    for agent in pick:
        result = add_agent(
            destination,
            name=f"{agent['name']}（来自 {other_city}）",
            age=int(agent.get("age") or 35),
            gender=agent.get("gender") or "女",
            job=agent.get("industry") or "自由职业",
        )
        added.append(result["id"])
    return {
        "city": destination.slug,
        "from_city": other_city,
        "added_ids": added,
        "added_names": [f"{a['name']}（来自 {other_city}）" for a in pick],
    }


def refill_via_import(
    city_ref: str,
    *,
    city_root: Any,
    import_payload: dict[str, Any],
) -> dict[str, Any]:
    """Re-use the bulk-import endpoint to refill the arena roster.

    The payload format is the same as :func:`gaworld.apps.import_api.execute_import`.
    We call it directly (rather than HTTP round-tripping) so the arena can
    chain refill steps inside the same Python process.
    """
    from gaworld.apps import import_api

    return import_api.execute_import(city_root=city_root, **import_payload)


# ---------------------------------------------------------------------------
# HTTP delegation
# ---------------------------------------------------------------------------


def handle_get(
    path: str,
    query: dict[str, Any] | None = None,
    *,
    city_root: Any = None,
) -> tuple[dict[str, Any], int]:
    query = query or {}
    try:
        if path == "/api/arena/tasks":
            return {"tasks": list(TASK_BANK)}, 200
        if path == "/api/arena/agents":
            city = _one(query, "city")
            if not city:
                return {"error": "city is required"}, 400
            return {"agents": _list_agents(city, city_root=city_root)}, 200
        if path.startswith("/api/arena/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            record = job_status(job_id)
            if record is None:
                return {"error": "Unknown job"}, 404
            return record, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("arena GET %s failed: %s", path, exc)
        return {"error": str(exc)}, 500
    return {"error": "Unknown arena endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/arena/generate":
            tasks = generate_questions(
                n=int(payload.get("n") or 5),
                categories=list(payload.get("categories") or ["math", "qa"]),
                difficulty=str(payload.get("difficulty") or "medium"),
            )
            return {"tasks": tasks}, 200
        if path == "/api/arena/run":
            # ``{"job_id": ...}``, not the bare id: the front-end polls
            # ``/api/arena/jobs/<job_id>`` and reads the field by name.
            return {"job_id": _handle_run_payload(payload)}, 202
        if path == "/api/arena/retain":
            return _handle_retain_payload(payload), 200
        if path == "/api/arena/refill":
            return _handle_refill_payload(payload), 200
        if path == "/api/arena/state":
            city = str(payload.get("city") or "").strip()
            if not city:
                return {"error": "city is required"}, 400
            return {
                "city": _city_slug(city),
                "eliminated": eliminated_for(city),
            }, 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown arena endpoint"}, 404


def _one(query: dict[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


def _handle_run_payload(payload: dict[str, Any]) -> str:
    city_ref = str(payload.get("city") or "").strip()
    if not city_ref:
        raise ValueError("city is required")
    agent_ids = [int(i) for i in (payload.get("agent_ids") or [])]
    if not agent_ids:
        raise ValueError("agent_ids is required")
    task_ids = [str(t) for t in (payload.get("task_ids") or [])]
    custom_tasks = payload.get("custom_tasks") or None
    job_id = _new_job("arena")

    def work(report: Callable[[float, str], None]) -> dict[str, Any]:
        result = run_round(
            city_ref=city_ref,
            agent_ids=agent_ids,
            task_ids=task_ids or None,
            custom_tasks=custom_tasks,
            progress=report,
        )
        report(1.0, "完成")
        return result.to_dict()

    _run_in_background(job_id, work)
    return job_id


def _handle_retain_payload(payload: dict[str, Any]) -> dict[str, Any]:
    city_ref = str(payload.get("city") or "").strip()
    if not city_ref:
        raise ValueError("city is required")
    leaderboard = payload.get("leaderboard") or []
    if not isinstance(leaderboard, list):
        raise ValueError("leaderboard must be a list")
    k = int(payload.get("k") or 0)
    return apply_topk(city_ref, leaderboard, k)


def _handle_refill_payload(payload: dict[str, Any]) -> dict[str, Any]:
    city_ref = str(payload.get("city") or "").strip()
    if not city_ref:
        raise ValueError("city is required")
    city_root = payload.get("city_root")
    source = str(payload.get("from_city") or "").strip()
    if source:
        n = int(payload.get("n") or 1)
        return refill_from_city(city_ref, other_city=source, n=n, city_root=city_root)
    if payload.get("import_payload"):
        return refill_via_import(city_ref, city_root=city_root, import_payload=payload["import_payload"])
    raise ValueError("refill 需要 from_city 或 import_payload")


__all__ = [
    "TASK_BANK",
    "apply_topk",
    "eliminated_for",
    "generate_questions",
    "handle_get",
    "handle_post",
    "is_eliminated",
    "job_status",
    "mark_eliminated",
    "refill_from_city",
    "refill_via_import",
    "reset_eliminated",
    "run_round",
    "survivors_for",
    "task_by_id",
]
