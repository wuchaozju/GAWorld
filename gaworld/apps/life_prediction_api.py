"""Dashboard backend for "人生预测" — the resident's own narration of a life
that has not happened yet.

Where the autobiography (``gaworld.apps.autobiography_api``) answers "what
happened to me so far", the life prediction answers "what will happen to me,
all the way to the end". It is written in the same first-person voice but set
in the future: the narrator is the resident looking back from the far end of
their own life, so the text is written in hindsight rather than as a plan.

Three optional inputs shape the run, all of them supplied by the operator in
the studio panel:

* ``direction`` — 人生大致走向: a free-text sketch of where the life is
  heading ("去南方做制造业管理" / "留在体制内" / "什么都不想改变"). Empty
  means "let the dossier decide".
* ``randomness`` — 人生随机性, 0–100: how far the life drifts from whatever
  plan exists. Low is a straight line, high is a life repeatedly rewritten by
  contingency.
* ``turbulence`` — 时代动荡性, 0–100: how hard the era pushes back. Low is a
  calm decade in which effort still pays, high is a century that keeps
  remaking the person's circumstances.

Two points of design worth stating, because they are the difference between
this and the autobiography:

* **The prediction is not written into the resident's memory.** An
  autobiography is a fact about the past and belongs in the self-image; a
  prediction is a hypothesis about the future, and a resident that reads its
  own forecast as settled truth would simply act it out. So the document is
  read-only: it is written to disk and shown in the panel, and nothing else.
* **It is a single model call.** The trajectory is described, not simulated:
  the text is the deliverable, and the three knobs steer its shape rather than
  producing a second simulation to compare against.

Routes (delegated from ``dashboard_server``):

* ``POST /api/agents/<id>/life-prediction`` → enqueue a job, returns
  ``job_id`` immediately (a 20k-character generation runs for minutes; a
  synchronous handler would block the dashboard's request thread).
* ``GET /api/agents/<id>/life-prediction/jobs/<job_id>`` → poll job status.
* ``GET /api/agents/<id>/life-prediction`` → the latest on-disk artefact.
* ``GET /api/agents/<id>/life-prediction/download`` → the Markdown file.

The job model mirrors ``gaworld.apps.autobiography_api``: a module-level
``_JOBS`` table, ``ownership.spawn`` to detach from the request handler and
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

_LOG = get_logger("gaworld.dashboard.life_prediction")

#: How many characters we hope the LLM lands on — the same target as the
#: autobiography, so the two documents can be read side by side.
_TARGET_LENGTH_CHARS = 20000

#: Output budget for the model call: 24k output tokens is a comfortable
#: ceiling for ~20k Chinese characters with prose padding.
_MAX_OUTPUT_TOKENS = 24000

#: Where the rendered Markdown is parked on disk so the user can grab it
#: again from outside the dashboard. Mirrors the autobiography's
#: ``output/autobiography`` convention.
_OUTPUT_DIR = os.path.join("output", "life_prediction")

#: job id → record. One module-level dict, same shape as autobiography_api.
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 10

#: At most one prediction per agent at a time. A second click would race the
#: same job and burn two model calls; we refuse it with a 409 instead.
_RUN_LOCKS: dict[int, threading.Lock] = {}
_RUN_LOCKS_META = threading.Lock()

#: The two knobs are 0–100; these are the bands the prompt spells out, so
#: the model reads a number as a description rather than as a number.
_SCALE_MIN = 0
_SCALE_MAX = 100
_SCALE_DEFAULT = 50


# ---------------------------------------------------------------------------
# The three inputs
# ---------------------------------------------------------------------------


def _clamp_scale(value: Any, default: int = _SCALE_DEFAULT) -> int:
    """Coerce one knob into 0–100.

    A slider that sends ``"42"``, ``42`` and ``42.7`` must all mean the same
    thing to the prompt, and a body that omits the knob entirely must fall
    back to the neutral middle rather than to zero.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(_SCALE_MIN, min(_SCALE_MAX, round(number)))


def _band(value: int) -> tuple[str, str]:
    """Turn one 0–100 knob into (band label, what it means for the life).

    The bands are the point of the knob: the model has no intuition about
    "randomness 73", but it has plenty about "a life that keeps being
    rewritten by other people's decisions".
    """
    if value <= 20:
        return "极低", "几乎一条直线：计划大体兑现，人生按部就班，大的岔路极少出现"
    if value <= 40:
        return "偏低", "小幅偏转：偶有意外，但整体仍在掌控之中，几次偏差都能修正回来"
    if value <= 60:
        return "中等", "有明显的岔路：几个关键节点上出现难以预料的转折，方向被悄悄改过"
    if value <= 80:
        return "偏高", "高度不确定：人生方向多次被环境与他人改写，原来的打算反复失效"
    return "极高", "几乎不可预测：一生充满剧变，计划不断落空，关键处全凭临场应变"


def _describe_knobs(direction: str, randomness: int, turbulence: int) -> str:
    """The operator's three inputs, written out for the prompt."""
    rand_label, rand_meaning = _band(randomness)
    turb_label, turb_meaning = _band(turbulence)
    lines = ["## 预测参数（由使用者设定）", ""]
    if direction:
        lines.append(f"- 人生大致走向（使用者给出）：{dossier.safe_text(direction, limit=600)}")
    else:
        lines.append("- 人生大致走向：使用者未指定——请依据档案里的性格、目标与现状，自行推演一条合理的走向")
    lines.append(f"- 人生随机性：{randomness}/100（{rand_label}）——{rand_meaning}")
    lines.append(f"- 时代动荡性：{turbulence}/100（{turb_label}）——{turb_meaning}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """你是一位擅长写"未来自传"的人生叙事者。

你要写的不是计划书，也不是预言，而是一篇**站在人生终点回望**的第一人称长文：
叙述者就是这位居民本人，写作时他已经走完了自己的一生，正在回头讲。
因此：

- 用第一人称"我"，但时间是站在未来回望现在：常用"后来我才明白""那时我以为""我花了三十年才接受"这类事后视角；
- 语气贴合居民的年龄、性别、职业与性格特征（Big Five），不要写成另一个人；
- 既要写"我做了什么"，也要写"我原本想做什么、结果如何"——两者的落差就是这篇文字的力量；
- 从档案里的当下往前推，一直写到死亡：生老、病痛、离别、最后的时刻，以及身后留下的痕迹；
- 像一部可读的自传，不要空话套话，不要写成励志格言或剧情梗概；
- 不要输出 JSON、不要输出代码块、不要 Markdown 标题以外的结构性内容。

只输出 Markdown 正文（用 # ## 作为章节标题），长度约 2 万字（中文计字）。"""


def _build_prompt(materials_block: str, name: str, direction: str, randomness: int, turbulence: int) -> str:
    return f"""请为居民「{name}」撰写一篇「未来自传」——用第一人称，写他从今天起直到死亡的一生。

# 写作要求
1. 时间跨度：从档案里的「当下」起笔，一路写到生命终点；晚年与临终必须写到，不能在中途收束。
2. 章节安排建议（可增删，但需覆盖）：
   - # 写下这些字的时候（叙述者所处的未来时点）
   - # 我出发的那些年
   - # 中年
   - # 晚年
   - # 最后的日子
   - # 我留下的
3. 内容依据：把档案里的职业、性格特征（Big Five）、关键记忆、目标、生命事件、关系、财务画像，自然铺进各个人生阶段，不要逐条罗列。
4. 三个参数决定这篇预测的形状，请严格照办（参数说明见下）：
   - 人生大致走向：整条人生轨迹的大方向与落点；没有指定时，从档案里的人物与目标自行推演。
   - 人生随机性：决定人生偏离计划的程度——低则一路顺遂，高则屡次被改写。
   - 时代动荡性：决定外部环境对人生的冲击强度——低则时代温和，高则时代反复碾过这个人。
5. 字数约 2 万字（中文计字，浮动 ±10% 可接受）。少于此范围明显不够，多于此范围 30% 以上请裁剪。
6. 输出为 Markdown：第一行写标题「# {name} 的人生预测」，下面用 ## 二级章节，再往下可用段落与简短列表。
7. 不输出任何非 Markdown 文本，不要包夹「下面是」「好的」等多余说明。

# 居民档案（他此刻的全部已知）
{materials_block}

{_describe_knobs(direction, randomness, turbulence)}
"""


# ---------------------------------------------------------------------------
# Synchronous core — the part that actually talks to the LLM
# ---------------------------------------------------------------------------


def _output_dir() -> str:
    """Where the markdown lives for the request's active world.

    Falls back to the module-level base (``output/life_prediction``) when the
    dashboard has not entered a world, so the smoke tests and the default
    single-user mode still write to a known location.
    """
    base = _OUTPUT_DIR
    try:
        from gaworld.apps import world_paths

        if world_paths.current_world():
            base = os.path.join(world_paths.run_root(), "life_prediction")
    except Exception:
        _LOG.debug("life prediction: world_paths unavailable, using base", exc_info=True)
    return base


def _output_path(agent_id: int) -> str:
    return os.path.join(_output_dir(), f"agent_{int(agent_id)}.md")


def compose(
    agent_id: int,
    *,
    direction: str = "",
    randomness: int = _SCALE_DEFAULT,
    turbulence: int = _SCALE_DEFAULT,
    provider: str | None = None,
) -> dict[str, Any]:
    """Render and persist the predicted life for ``agent_id``.

    Returns ``{markdown, length, length_cjk, path, …}`` so the panel can
    render the body and surface the parameters the document was written with.

    Long-running by design — called from a background thread by ``enqueue``,
    never directly from a request handler.
    """
    from gaworld.llm.providers import call_llm

    randomness = _clamp_scale(randomness)
    turbulence = _clamp_scale(turbulence)
    direction = (direction or "").strip()

    materials = dossier.gather(agent_id)
    identity = materials["identity"] or {}
    name = identity.get("name") or f"居民{agent_id}"

    materials_block = dossier.format(materials)
    prompt = _build_prompt(materials_block, name, direction, randomness, turbulence)

    raw = call_llm(
        prompt,
        task="life_prediction",
        agent_id=agent_id,
        provider=provider,
        system=_SYSTEM_PROMPT,
        temperature=0.7,
        max_tokens=_MAX_OUTPUT_TOKENS,
    )
    markdown = _strip_code_fences(raw or "")
    if not markdown:
        raise RuntimeError("LLM 没有返回人生预测内容")

    # 兜底：若首行不是 # 标题，自动补上
    if not markdown.startswith("#"):
        markdown = f"# {name} 的人生预测\n\n{markdown}"

    path = _output_path(agent_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(markdown)

    # No memory write-back, deliberately: a prediction is a hypothesis about
    # the future, and a resident that reads its own forecast as fact would
    # simply act it out. The document stays on disk and in the panel.

    return {
        "agent_id": int(agent_id),
        "name": name,
        "markdown": markdown,
        "length": len(markdown),
        "length_cjk": _count_cjk_chars(markdown),
        "path": path,
        "profile_block_size": len(materials_block),
        "direction": direction,
        "randomness": randomness,
        "turbulence": turbulence,
    }


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
    """Chinese characters in the body — what the user's "字数 2 万" refers to."""
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


# ---------------------------------------------------------------------------
# Job plumbing — mirrors ``autobiography_api``
# ---------------------------------------------------------------------------


def _lock_for(agent_id: int) -> threading.Lock:
    """One lock per agent id; lazily created and kept forever.

    We never delete the entry because the dict is small (one per resident
    ever asked for a prediction) and ``Lock`` objects cannot be freed while
    held.
    """
    with _RUN_LOCKS_META:
        lock = _RUN_LOCKS.get(agent_id)
        if lock is None:
            lock = threading.Lock()
            _RUN_LOCKS[agent_id] = lock
        return lock


def _new_job(agent_id: int) -> str:
    job_id = f"predict-{agent_id}-{uuid.uuid4().hex[:8]}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "agent_id": int(agent_id),
            "kind": "life_prediction",
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


def enqueue(
    agent_id: int,
    *,
    direction: str = "",
    randomness: int = _SCALE_DEFAULT,
    turbulence: int = _SCALE_DEFAULT,
) -> dict[str, Any]:
    """Start a background compose. Returns ``{job_id, agent_id}``.

    Raises ``RuntimeError("BUSY")`` if another prediction for this same agent
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
            result = compose(
                agent_id,
                direction=direction,
                randomness=randomness,
                turbulence=turbulence,
            )
            _update_job(
                job_id,
                status="done",
                progress=1.0,
                message="完成",
                result=result,
                finished_at=time.time(),
            )
        except Exception as exc:
            _LOG.exception("life prediction job %s failed", job_id)
            _update_job(
                job_id,
                status="error",
                message=str(exc),
                error={"type": type(exc).__name__, "detail": traceback.format_exc(limit=5)},
                finished_at=time.time(),
            )
        finally:
            lock.release()

    ownership.spawn(work, name=f"life-prediction-{job_id}")
    return {"job_id": job_id, "agent_id": int(agent_id)}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_post(path: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """``POST /api/agents/<id>/life-prediction`` → enqueue a job."""
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != "api" or parts[1] != "agents" or parts[3] != "life-prediction":
        return {"error": "Unknown endpoint"}, 404
    try:
        agent_id = int(parts[2])
    except ValueError:
        return {"error": "Invalid agent id"}, 400
    body = payload or {}
    try:
        return (
            enqueue(
                agent_id,
                direction=str(body.get("direction") or ""),
                randomness=_clamp_scale(body.get("randomness")),
                turbulence=_clamp_scale(body.get("turbulence")),
            ),
            202,
        )
    except RuntimeError as exc:
        if str(exc) == "BUSY":
            return {"error": "已在为该居民生成人生预测，请等当前任务完成"}, 409
        _LOG.warning("life prediction enqueue failed for %s: %s", agent_id, exc)
        return {"error": str(exc)}, 502
    except Exception as exc:
        _LOG.exception("life prediction enqueue failed for %s", agent_id)
        return {"error": f"生成人生预测失败：{exc}"}, 500


def handle_get(path: str, _query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """Two read endpoints:

    * ``GET /api/agents/<id>/life-prediction`` → latest on-disk artefact, if any.
    * ``GET /api/agents/<id>/life-prediction/jobs/<job_id>`` → live job status.
    """
    parts = path.strip("/").split("/")
    if len(parts) not in (4, 6) or parts[0] != "api" or parts[1] != "agents" or parts[3] != "life-prediction":
        return {"error": "Unknown endpoint"}, 404
    try:
        agent_id = int(parts[2])
    except ValueError:
        return {"error": "Invalid agent id"}, 400

    # Job sub-snapshot — must come before the "latest artefact" branch so
    # the prefix ``/life-prediction/jobs/...`` is not shadowed.
    if len(parts) == 6 and parts[4] == "jobs":
        record = job_status(parts[5])
        if record is None:
            return {"error": "Unknown job"}, 404
        return record, 200

    # Latest artefact — handy for "上次算过的那份" so the user does not have
    # to keep a job id around. The on-disk file is the source of truth.
    path = _output_path(agent_id)
    if not os.path.exists(path):
        return {"error": "尚未生成人生预测"}, 404
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


def handle_download(path: str) -> tuple[str | None, str, str, int]:
    """``GET /api/agents/<id>/life-prediction/download`` — stream the saved file.

    Returns ``(filename, content_type, body, status)`` so the dashboard can
    answer with a real ``Content-Disposition: attachment`` header instead of
    a JSON wrapper. ``body`` is read straight off disk so it survives any
    re-render of the studio panel.

    Status ``200`` carries ``body``; status ``404`` returns ``body=None`` and
    the dashboard synthesises a small JSON error reply.
    """
    parts = path.strip("/").split("/")
    if (
        len(parts) != 5
        or parts[0] != "api"
        or parts[1] != "agents"
        or parts[3] != "life-prediction"
        or parts[4] != "download"
    ):
        return None, "application/json", "{}", 404
    try:
        agent_id = int(parts[2])
    except ValueError:
        return None, "application/json", '{"error": "Invalid agent id"}', 400
    output_path = _output_path(agent_id)
    if not os.path.exists(output_path):
        return None, "application/json", '{"error": "尚未生成人生预测"}', 404
    with open(output_path, encoding="utf-8") as handle:
        body = handle.read()
    filename = f"agent-{agent_id}-life-prediction.md"
    return filename, "text/markdown; charset=utf-8", body, 200


__all__ = [
    "compose",
    "enqueue",
    "handle_download",
    "handle_get",
    "handle_post",
    "job_status",
]
