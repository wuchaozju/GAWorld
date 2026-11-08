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
from gaworld.apps import resident_dossier as dossier
from gaworld.logging_setup import get_logger

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
# Material gathering — shared with the life prediction (gaworld.apps.
# resident_dossier), so both writers see the same evidence in the same shape.
# ---------------------------------------------------------------------------


def _safe_text(value: Any, limit: int = 4000) -> str:
    """Stringify, strip control noise and cap the length."""
    return dossier.safe_text(value, limit)


def _gather_materials(agent_id: int) -> dict[str, Any]:
    """Collect every signal the studio panel knows about this resident."""
    return dossier.gather(agent_id)


def _format_materials(materials: dict[str, Any]) -> str:
    """Turn the gathered signals into a compact, structured briefing."""
    return dossier.format(materials)


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


#: How many characters of the autobiography to fold into long-term memory.
    #: ~700 Chinese characters is enough to anchor self-image without bloating
    #: every subsequent cognition prompt with the whole 20k-character essay.
_MEMORY_SUMMARY_CHARS = 700


def _summarize_for_memory(markdown: str, name: str) -> str:
    """Build a single long-term memory line that captures the autobiography's
    self-image, so the next simulation tick reads it as a stable fact.

    We keep the chapter titles (the spine of the essay) and the first
    paragraph of each chapter — that gives the agent a one-shot refresh of "who
    I decided I was" without flooding every prompt with 20k characters.
    """
    lines = markdown.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    current: list[str] = []
    in_code = False

    def flush() -> None:
        if current:
            para = " ".join(line.strip() for line in current if line.strip()).strip()
            if para:
                kept.append(para[:240])
            current.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            # Keep H1 title and H2 chapter names — they are the spine.
            kept.append(stripped)
            continue
        current.append(stripped)

    flush()
    spine = "\n".join(kept[: _MEMORY_SUMMARY_CHARS // 4])
    return f"[自传 摘要] 我（{name}）写过一篇自传，章节与首段如下：\n{spine}"[:_MEMORY_SUMMARY_CHARS]


def _append_memory(agent_id: int, summary: str) -> None:
    """Append *summary* to the resident's long-term memory store.

    Best-effort: the dashboard must not fail the whole compose call because
    the resident already had an autobiography summary or the memory store is
    unwritable. We log a warning so a human can investigate.

    The active user/world context is captured by ``ownership.spawn`` so a
    shared deployment writes the new memory into the right user's world
    rather than the shared default.
    """
    from gaworld.accounts import ownership
    from gaworld.apps import residents as residents_mod

    def _write() -> None:
        residents_mod.append_agent_memory(
            agent_id,
            {"kind": "memory", "text": summary},
        )

    try:
        ownership.spawn(_write)()
    except ValueError as exc:
        _LOG.warning(
            "autobiography: memory summary rejected for agent %s: %s",
            agent_id,
            exc,
        )
    except Exception:
        _LOG.warning(
            "autobiography: could not append memory for agent %s",
            agent_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Synchronous core — the part that actually talks to the LLM
# ---------------------------------------------------------------------------


def _output_dir() -> str:
    """Where the markdown lives for the request's active world.

    Falls back to the module-level base (``output/autobiography``) when the
    dashboard has not entered a world, so the smoke tests and the default
    single-user mode still write to a known location.
    """
    base = _OUTPUT_DIR
    try:
        from gaworld.apps import world_paths

        if world_paths.current_world():
            base = os.path.join(world_paths.run_root(), "autobiography")
    except Exception:
        _LOG.debug("autobiography: world_paths unavailable, using base", exc_info=True)
    return base


def _output_path(agent_id: int) -> str:
    return os.path.join(_output_dir(), f"agent_{int(agent_id)}.md")


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

    # Fold a distilled self-portrait into the resident's long-term memory so
    # the next simulation tick already knows what the agent decided to call
    # themselves. Done last (after the file is durable) and best-effort: a
    # memory-store failure must not erase the autobiography we just wrote.
    summary = _summarize_for_memory(markdown, name)
    _append_memory(agent_id, summary)

    return {
        "agent_id": int(agent_id),
        "name": name,
        "markdown": markdown,
        "length": len(markdown),
        "length_cjk": _count_cjk_chars(markdown),
        "path": path,
        "profile_block_size": len(materials_block),
        "memory_summary_chars": len(summary),
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
    with open(path, encoding="utf-8") as handle:
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


__all__ = ["compose", "enqueue", "handle_download", "handle_get", "handle_post", "job_status"]


def handle_download(path: str) -> tuple[str | None, str, str, int]:
    """``GET /api/agents/<id>/autobiography/download`` — stream the saved file.

    Returns ``(filename, content_type, body, status)`` so the dashboard can
    answer with a real ``Content-Disposition: attachment`` header instead of
    a JSON wrapper. ``body`` is read straight off disk so it survives any
    re-render of the studio panel — the user might have closed the panel
    between the original compose and clicking download.

    Status ``200`` carries ``body``; status ``404`` returns ``body=None`` and
    the dashboard synthesises a small JSON error reply.
    """
    parts = path.strip("/").split("/")
    if len(parts) != 5 or parts[0] != "api" or parts[1] != "agents" or parts[3] != "autobiography" or parts[4] != "download":
        return None, "application/json", "{}", 404
    try:
        agent_id = int(parts[2])
    except ValueError:
        return None, "application/json", '{"error": "Invalid agent id"}', 400
    output_path = _output_path(agent_id)
    if not os.path.exists(output_path):
        return None, "application/json", '{"error": "尚未生成自传"}', 404
    with open(output_path, encoding="utf-8") as handle:
        body = handle.read()
    filename = f"agent-{agent_id}-autobiography.md"
    return filename, "text/markdown; charset=utf-8", body, 200
