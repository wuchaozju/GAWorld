"""Dashboard backend for "生成自传" — one autobiographical long-form document
synthesised from an agent's identity, Big Five profile, narrative profile,
long-term memory, goals and life events.

Two routes, both delegated from ``dashboard_server``:

* ``POST /api/agents/<id>/autobiography`` → enqueue a job, returns ``job_id``
  immediately (the LLM call writes 20k Chinese characters and easily runs
  for several minutes; a synchronous handler would block the dashboard's
  request thread and starve every other panel).
* ``GET /api/agents/<id>/autobiography/jobs/<job_id>`` → poll job status.
  Returns ``{status, progress, message, result}``; ``status`` is one of
  ``running`` / ``done`` / ``error``.

The job model mirrors ``gaworld.apps.interview_api``: a single module-level
``_JOBS`` table, ``ownership.spawn`` to detach from the request handler,
``ownership.visible`` to scope jobs to the calling user on a shared
deployment.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import uuid
from typing import Any

from gaworld.accounts import ownership
from gaworld.apps import residents
from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG

_LOG = get_logger("gaworld.dashboard.autobiography")

#: How many characters we hope the LLM lands on. ~20k characters is what the
#: feature brief asks for; the prompt asks for a self-contained biographical
#: narrative in that range so the panel can show a real document.
_TARGET_LENGTH_CHARS = 20000

#: Output budget for the model call. The provider caps token output, not
#: characters; 24k output tokens is a comfortable ceiling for ~20k Chinese
#: characters with prose padding and an occasional short English word.
_MAX_OUTPUT_TOKENS = 24000

#: Where the rendered Markdown is parked on disk so the user can grab it
#: again from outside the dashboard. ``output/autobiography/agent_<id>.md``
#: matches the per-agent output convention used by ``output/diaries``.
_OUTPUT_DIR = os.path.join("output", "autobiography")

#: job id → record. One module-level dict, same shape as interview_api.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10

#: At most one autobiography per agent at a time. A user clicking the
#: button twice would otherwise race the same materials + burn two LLM
#: calls; we simply refuse the second one with a 409 so the panel can show
#: a clear "已经在生成中" toast.
_RUN_LOCKS: dict[int, threading.Lock] = {}
_RUN_LOCKS_META = threading.Lock()


# ---------------------------------------------------------------------------
# Material gathering
# ---------------------------------------------------------------------------


def _safe_text(value: Any, limit: int = 4000) -> str:
    """Stringify, strip control noise and cap the length.

    A single multi-line diary entry, an unfiltered memory dump or an
    accidentally-blob memory item must not blow the prompt context; each
    contributor is hard-capped so the assembled prompt stays inside budget.
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\x00", "")
    if len(text) > limit:
        text = text[:limit] + "\n…(已截断)…\n"
    return text.strip()


def _gather_materials(agent_id: int) -> dict[str, Any]:
    """Collect every signal the studio panel knows about this resident.

    Imports stay local so a tiny request (``/api/agents/<id>/big5``) does not
    pay for the prompt-formatting helpers.

    ``residents`` is the new home of the agent-detail loader (moved out of
    ``dashboard_server``); the old name there now raises a deliberate
    ``AttributeError`` to catch stale callers.
    """
    detail = residents.agent_detail(agent_id) or {}
    identity = detail.get("identity") or {}

    big5 = None
    try:
        big5 = residents.agent_big5(agent_id)
    except Exception:
        _LOG.warning("autobiography: could not read big5 for agent %s", agent_id, exc_info=True)

    finance = detail.get("finance_state") or {}
    social = detail.get("social") or {}
    goals = detail.get("goals") or {}
    home = detail.get("home") or {}

    long_term = ((detail.get("memory") or {}).get("long_term")) or []
    habits = ((detail.get("memory") or {}).get("habits")) or []
    intentions = ((detail.get("memory") or {}).get("intentions")) or {}
    schedule = ((detail.get("memory") or {}).get("schedule")) or []

    life_events: list[dict[str, Any]] = []
    try:
        from gaworld.events.life import list_life_events
        all_events = list_life_events(CONFIG, include_consumed=True) or []
        for ev in all_events:
            try:
                if int((ev.get("agent_id") or ev.get("resident_id") or 0)) == int(agent_id):
                    life_events.append(ev)
            except (TypeError, ValueError):
                continue
    except Exception:
        _LOG.warning("autobiography: could not read life events for agent %s", agent_id, exc_info=True)

    return {
        "identity": identity,
        "profile_text": detail.get("profile_text") or "",
        "big5": big5,
        "state": detail.get("state") or {},
        "finance": finance,
        "social": social,
        "goals": goals,
        "home": home,
        "memory": {
            "long_term": long_term,
            "habits": habits,
            "intentions": intentions,
            "schedule": schedule,
        },
        "life_events": life_events,
    }


def _format_materials(materials: dict[str, Any]) -> str:
    """Turn the gathered signals into a compact, structured briefing.

    The LLM is told to write in the voice of a biographer; the briefing is
    the dossier that biographer has on their clipboard.
    """
    identity = materials["identity"] or {}
    big5 = materials["big5"] or {}
    state = materials["state"] or {}
    big5_values = big5.get("values") or {}
    big5_authored = big5.get("authored") or {}
    big5_paragraph = big5.get("paragraph") or ""
    big5_consistency = big5.get("consistency")

    lines: list[str] = []
    lines.append("# 居民档案（写自传用）")
    lines.append("")
    lines.append(f"- 编号：{identity.get('id') or '?'}")
    lines.append(f"- 姓名：{identity.get('name') or '?'}")
    lines.append(f"- 性别：{identity.get('gender') or '?'}")
    lines.append(f"- 年龄：{identity.get('age') or '?'}")
    lines.append(f"- 户籍：{identity.get('hukou') or '?'}")
    lines.append(f"- 现居地：{identity.get('residence') or '?'}")

    if state:
        lines.append("")
        lines.append("## 当前状态变量（0–1，越大越强）")
        for key, value in state.items():
            try:
                lines.append(f"- {key}: {float(value):.2f}")
            except (TypeError, ValueError):
                continue

    if big5_values:
        lines.append("")
        lines.append("## Big Five 大五人格（z 分）")
        names_zh = big5.get("names") or {}
        for dim, z in big5_values.items():
            label = names_zh.get(dim) or dim
            authored = big5_authored.get(dim) if isinstance(big5_authored, dict) else None
            authored_str = f"（自述：{float(authored):+.2f}）" if authored is not None else ""
            try:
                lines.append(f"- {label} ({dim}): {float(z):+.2f}{authored_str}")
            except (TypeError, ValueError):
                continue
        if big5_paragraph:
            lines.append("")
            lines.append("### 人设心理段落")
            lines.append(big5_paragraph)
        if big5_consistency is not None:
            lines.append("")
            try:
                lines.append(f"### 自述 vs 实测一致性: {float(big5_consistency):.2f}")
            except (TypeError, ValueError):
                pass

    profile_text = materials.get("profile_text") or ""
    if profile_text:
        lines.append("")
        lines.append("## 叙事档案（Markdown）")
        lines.append(_safe_text(profile_text, limit=4000))

    goals = materials.get("goals") or {}
    if goals:
        lines.append("")
        lines.append("## 三层目标")
        for tier in ("long_term", "medium_term", "short_term"):
            items = goals.get(tier) or []
            if items:
                lines.append(f"### {tier}")
                for item in items:
                    title = item.get("title") if isinstance(item, dict) else str(item)
                    progress = (item.get("progress") if isinstance(item, dict) else None)
                    domain = (item.get("domain") if isinstance(item, dict) else None)
                    meta = ""
                    if progress is not None:
                        try:
                            meta += f" 进度={float(progress) * 100:.0f}%"
                        except (TypeError, ValueError):
                            pass
                    if domain:
                        meta += f" 领域={domain}"
                    lines.append(f"- {title}{meta}")

    memory = materials.get("memory") or {}
    long_term = memory.get("long_term") or []
    if long_term:
        lines.append("")
        lines.append(f"## 长期记忆（共 {len(long_term)} 条，按时间倒序给出最多 30 条）")
        items = list(long_term)
        items.sort(key=lambda m: m.get("time") or m.get("day") or 0, reverse=True)
        for item in items[:30]:
            text = _safe_text(item.get("text") if isinstance(item, dict) else item, limit=400)
            day = item.get("day") if isinstance(item, dict) else None
            when = item.get("time") if isinstance(item, dict) else None
            ts = ""
            if day is not None or when is not None:
                ts = f"[{day or ''}{' ' + when if when else ''}] "
            lines.append(f"- {ts}{text}")

    habits = memory.get("habits") or []
    if habits:
        lines.append("")
        lines.append("## 习惯")
        for item in habits[:20]:
            lines.append(f"- {_safe_text(item.get('text') if isinstance(item, dict) else item, limit=200)}")

    intentions = memory.get("intentions") or {}
    if intentions:
        lines.append("")
        lines.append("## 当前意图")
        if isinstance(intentions, dict):
            for key, value in list(intentions.items())[:20]:
                lines.append(f"- {key}: {_safe_text(value, limit=200)}")
        else:
            for item in list(intentions)[:20]:
                lines.append(f"- {_safe_text(item, limit=200)}")

    schedule = memory.get("schedule") or []
    if schedule:
        lines.append("")
        lines.append("## 今日日程")
        for item in schedule[:20]:
            lines.append(f"- {_safe_text(item.get('text') if isinstance(item, dict) else item, limit=200)}")

    social = materials.get("social") or {}
    if social:
        lines.append("")
        lines.append("## 社交关系")
        relations = social.get("relations") if isinstance(social, dict) else None
        if isinstance(relations, list):
            for rel in relations[:20]:
                if not isinstance(rel, dict):
                    lines.append(f"- {_safe_text(rel, limit=200)}")
                    continue
                name = rel.get("name", "？")
                role = rel.get("role", "")
                tier = rel.get("tier", "")
                closeness = rel.get("closeness")
                trust = rel.get("trust")
                bits = [f"{name}"]
                if role:
                    bits.append(f"角色={role}")
                if tier:
                    bits.append(f"圈层={tier}")
                if closeness is not None:
                    try:
                        bits.append(f"亲密度={float(closeness):.2f}")
                    except (TypeError, ValueError):
                        pass
                if trust is not None:
                    try:
                        bits.append(f"信任={float(trust):.2f}")
                    except (TypeError, ValueError):
                        pass
                lines.append(f"- {' | '.join(bits)}")

    finance = materials.get("finance") or {}
    if finance:
        lines.append("")
        lines.append("## 财务画像")
        for key in ("income_monthly", "expense_monthly", "savings", "debt", "job_label"):
            if key in finance:
                lines.append(f"- {key}: {_safe_text(finance.get(key), limit=200)}")

    life_events = materials.get("life_events") or []
    if life_events:
        lines.append("")
        lines.append(f"## 生命事件（共 {len(life_events)} 条）")
        for ev in life_events[:30]:
            if not isinstance(ev, dict):
                lines.append(f"- {_safe_text(ev, limit=200)}")
                continue
            label = ev.get("template_key") or ev.get("key") or ev.get("title") or "事件"
            day = ev.get("triggered_day") or ev.get("day")
            when = f"[{day}] " if day is not None else ""
            lines.append(f"- {when}{label}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt + LLM call
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """你是一位严谨的人物传记写作者，擅长为一位数字居民撰写第一人称自传体长文。
你的写作风格：
- 用第一人称"我"的口吻，语调贴合居民的年龄、性别、职业、性格特征；
- 时间线连贯，从小到大再到如今，把现在可观测的事件作为"现在"的一部分自然衔接；
- 引用档案中关键的人生事件、关系、目标与状态，但不要逐条复述；
- 行文像一篇可读的书稿，避免空话套话；
- 不要输出 JSON、不要输出代码块、不要 Markdown 标题外的内容以外的结构。

只输出 Markdown 正文（用 # ## 作为章节标题），长度约 2 万字（中文计字）。"""


def _build_prompt(materials_block: str, name: str) -> str:
    return f"""请为居民「{name}」撰写一篇第一人称自传。

# 写作要求
1. 时间跨度：从小写到当下（含童年、求学、初入职场、转折、关系、家庭、当下生活）。
2. 章节安排建议（可增删，但需覆盖）：
   - # 童年
   - # 求学
   - # 踏入社会
   - # 转折与低谷
   - # 关系与家庭
   - # 如今的我
   - # 内心独白
3. 把档案里的职业、性格特征（Big Five）、关键记忆、目标、生命事件、关系、财务画像等，自然融入相应的人生阶段，不要逐条罗列。
4. 字数约 2 万字（中文计字，浮动 ±10% 可接受）。少于此范围明显不够，多于此范围 30% 以上请裁剪。
5. 输出为 Markdown：第一行写标题「# {name} 自传」，下面用 ## 二级章节，再往下可用段落与简短列表。
6. 不输出任何非 Markdown 文本，不要包夹「下面是」「好的」等多余说明。

# 居民档案
{materials_block}
"""


def _strip_code_fences(text: str) -> str:
    """LLMs sometimes wrap long Chinese text in ``` fences; strip them so the
    downloaded file is plain Markdown.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)
    return stripped.strip()


def _count_cjk_chars(text: str) -> int:
    """Chinese characters in the body — what the user's "字数 2 万" refers to.
    Markdown punctuation, English words and whitespace are intentionally
    excluded so the count tracks perceived length.
    """
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


# ---------------------------------------------------------------------------
# Synchronous core — the part that actually talks to the LLM
# ---------------------------------------------------------------------------


def _output_path(agent_id: int) -> str:
    return os.path.join(_OUTPUT_DIR, f"agent_{int(agent_id)}.md")


def compose(agent_id: int, *, provider: str | None = None) -> dict[str, Any]:
    """Render and persist the autobiographical document for ``agent_id``.

    Returns ``{markdown, length, length_cjk, path, profile_block_size}`` so
    the panel can both render the body and surface file metadata.

    Long-running by design — called from a background thread by ``enqueue``,
    never directly from a request handler.
    """
    from gaworld.llm.providers import call_llm

    materials = _gather_materials(agent_id)
    identity = materials["identity"] or {}
    name = identity.get("name") or f"居民{agent_id}"

    materials_block = _format_materials(materials)
    prompt = _build_prompt(materials_block, name)

    raw = call_llm(
        prompt,
        task="autobiography",
        agent_id=agent_id,
        provider=provider,
        system=_SYSTEM_PROMPT,
        temperature=0.7,
        max_tokens=_MAX_OUTPUT_TOKENS,
    )
    markdown = _strip_code_fences(raw or "")
    if not markdown:
        raise RuntimeError("LLM 没有返回自传内容")

    # 兜底：若首行不是 # 标题，自动补上
    if not markdown.startswith("#"):
        markdown = f"# {name} 自传\n\n{markdown}"

    path = _output_path(agent_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    return {
        "agent_id": int(agent_id),
        "name": name,
        "markdown": markdown,
        "length": len(markdown),
        "length_cjk": _count_cjk_chars(markdown),
        "path": path,
        "profile_block_size": len(materials_block),
    }


# ---------------------------------------------------------------------------
# Job plumbing — mirrors ``interview_api``
# ---------------------------------------------------------------------------


def _lock_for(agent_id: int) -> threading.Lock:
    """One lock per agent id; lazily created and kept forever.

    We never delete the entry because the dict is small (one per resident
    ever asked for an autobiography) and ``Lock`` objects cannot be freed
    while held.
    """
    with _RUN_LOCKS_META:
        lock = _RUN_LOCKS.get(agent_id)
        if lock is None:
            lock = threading.Lock()
            _RUN_LOCKS[agent_id] = lock
        return lock


def _new_job(agent_id: int) -> str:
    job_id = f"autobio-{agent_id}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "agent_id": int(agent_id),
            "kind": "autobiography",
            "status": "running",
            "progress": 0.0,
            "message": "启动中…",
            "started_at": time.time(),
            "finished_at": None,
            **ownership.stamp(),
            "result": None,
            "error": None,
        }
        finished = [
            (record["started_at"], key)
            for key, record in _JOBS.items()
            if record["status"] != "running"
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


def job_status(job_id: str) -> dict[str, Any] | None:
    """Return the live job record, or ``None`` if it does not exist or is
    someone else's. NaN/Infinity values are sanitised so the JSON parser
    can't throw the whole payload away on a stray float.
    """
    with _JOBS_LOCK:
        record = _JOBS.get(job_id)
        if not record or not ownership.visible(record):
            return None
        return json.loads(json.dumps(record, ensure_ascii=False), parse_constant=lambda _: None)


def enqueue(agent_id: int) -> dict[str, Any]:
    """Start a background compose. Returns ``{job_id, agent_id}``.

    Raises ``RuntimeError("BUSY")`` if another compose for this same agent
    is already in flight; the panel turns that into a 409 with a useful
    message rather than a 500.
    """
    lock = _lock_for(int(agent_id))
    if not lock.acquire(blocking=False):
        raise RuntimeError("BUSY")
    job_id = _new_job(agent_id)

    def work() -> None:
        try:
            _update_job(job_id, progress=0.1, message="整理档案…")
            result = compose(agent_id)
            _update_job(
                job_id,
                status="done",
                progress=1.0,
                message="完成",
                result=result,
                finished_at=time.time(),
            )
        except Exception as exc:
            _LOG.exception("autobiography job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                finished_at=time.time(),
            )
        finally:
            lock.release()

    ownership.spawn(work, name=f"autobiography-{job_id}")
    return {"job_id": job_id, "agent_id": int(agent_id)}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_post(path: str, _payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """``POST /api/agents/<id>/autobiography`` → enqueue a job."""
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "api" or parts[1] != "agents" or parts[3] != "autobiography":
        return {"error": "Unknown endpoint"}, 404
    try:
        agent_id = int(parts[2])
    except ValueError:
        return {"error": "Invalid agent id"}, 400
    try:
        return enqueue(agent_id), 202
    except RuntimeError as exc:
        if str(exc) == "BUSY":
            return {"error": "已在为该居民生成自传，请等当前任务完成"}, 409
        _LOG.warning("autobiography enqueue failed for %s: %s", agent_id, exc)
        return {"error": str(exc)}, 502
    except Exception as exc:
        _LOG.exception("autobiography enqueue failed for %s", agent_id)
        return {"error": f"生成自传失败：{exc}"}, 500


def handle_get(path: str, _query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """Two read endpoints:

    * ``GET /api/agents/<id>/autobiography`` → latest on-disk artefact, if any.
    * ``GET /api/agents/<id>/autobiography/jobs/<job_id>`` → live job status.
    """
    parts = path.strip("/").split("/")
    if len(parts) not in (4, 6) or parts[0] != "api" or parts[1] != "agents" or parts[3] != "autobiography":
        return {"error": "Unknown endpoint"}, 404
    try:
        agent_id = int(parts[2])
    except ValueError:
        return {"error": "Invalid agent id"}, 400

    # Job sub-snapshot — must come before the "latest artefact" branch so
    # the prefix ``/autobiography/jobs/...`` is not shadowed by a regex
    # that only matches the bare endpoint.
    if len(parts) == 6 and parts[4] == "jobs":
        record = job_status(parts[5])
        if record is None:
            return {"error": "Unknown job"}, 404
        return record, 200

    # Latest artefact — handy for "上次写过那篇" so the user does not have
    # to keep a job id around. The on-disk file is the source of truth.
    path = _output_path(agent_id)
    if not os.path.exists(path):
        return {"error": "尚未生成自传"}, 404
    with open(path, "r", encoding="utf-8") as handle:
        markdown = handle.read()
    return {
        "agent_id": int(agent_id),
        "name": "",
        "markdown": markdown,
        "length": len(markdown),
        "length_cjk": _count_cjk_chars(markdown),
        "path": path,
        "from_cache": True,
    }, 200


__all__ = ["compose", "enqueue", "handle_get", "handle_post", "job_status"]