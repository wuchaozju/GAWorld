"""Orchestrate a round: fan out across cities, merge, analyse, render.

The parent process owns everything that is not city-specific — the session
file, attachment resolution, the tallies, the summary calls and the Markdown
document. Each child owns exactly one city's respondents. The split follows
from where the constraint actually is: personas need the simulator's
city-bound globals, and nothing else does.

Attachments are resolved **here**, once, and shipped to the children already
fetched and decoded. Three reasons, in order of how much they would hurt:
a URL fetched per child would give each city a different snapshot of the
page; the same fetch repeated per child is needless load on somebody's
server; and the vision-capability check belongs with the config that routes
the model, which is the parent's.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from gaworld.interview import report as report_mod
from gaworld.interview import store
from gaworld.interview.aggregate import aggregate
from gaworld.interview.runner import resolve_session_material, serialize_material
from gaworld.interview.schema import (
    InterviewSpecError,
    Respondent,
    SessionSpec,
    Transcript,
    normalize_questions,
    normalize_respondents,
)
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interview.session")

PROJECT_ROOT = store.PROJECT_ROOT

#: Per-city child timeout: a fixed startup allowance plus a per-turn budget.
#: A local 9B model can take ~60s for one answer, and a round of 80×5 turns
#: run 4-wide is legitimately long — a flat timeout either kills real work or
#: lets a wedged child hang the panel forever.
CHILD_STARTUP_SECONDS = 180
CHILD_SECONDS_PER_TURN = 90

ReportFn = Callable[[float, str], None]


def _child_timeout(turns: int, concurrency: int) -> int:
    lanes = max(1, concurrency)
    return int(CHILD_STARTUP_SECONDS + (turns / lanes) * CHILD_SECONDS_PER_TURN)


def _child_env(slug: str) -> dict[str, str]:
    """Environment for a child pinned to ``slug``.

    Merges into any existing ``GAWORLD_CONFIG_OVERRIDES`` rather than
    replacing it: the parent may have been started with overrides of its own
    (the test suite always is), and dropping them would run the child against
    a different configuration than the session was planned under.
    """
    env = os.environ.copy()
    try:
        existing = json.loads(env.get("GAWORLD_CONFIG_OVERRIDES") or "{}")
    except json.JSONDecodeError:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing["city"] = slug
    env["GAWORLD_CONFIG_OVERRIDES"] = json.dumps(existing, ensure_ascii=False)
    return env


def _run_city(
    *,
    session_id: str,
    round_no: int,
    slug: str,
    spec: SessionSpec,
    material_payload: dict[str, Any],
    on_turn: Callable[[str], None],
    on_stage: Callable[[str], None] | None = None,
) -> list[Transcript]:
    """Spawn one child for ``slug`` and collect its transcripts."""
    work_dir = store.round_dir(session_id, round_no)
    safe = slug or "default"
    spec_path = work_dir / f"spec-{_slug_filename(safe)}.json"
    out_path = work_dir / f"answers-{_slug_filename(safe)}.json"
    payload = spec.to_dict()
    payload["material"] = material_payload
    payload["city"] = slug
    payload["round"] = round_no
    spec_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    command = [
        sys.executable,
        "-m",
        "gaworld.interview",
        "--spec",
        str(spec_path),
        "--out",
        str(out_path),
    ]
    turns = len(spec.respondents) * len(spec.questions)
    deadline = time.time() + _child_timeout(turns, spec.concurrency)
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=_child_env(slug),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    seen = 0
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Not ours — some import printed to stdout. Log it and move on;
            # this is exactly why the result goes to a file instead.
            _LOG.debug("interview child noise (%s): %s", safe, line[:200])
            continue
        if event.get("type") == "progress":
            done = int(event.get("done") or 0)
            # Children report their own cumulative count; the parent needs
            # increments to add across cities.
            while seen < done:
                seen += 1
                on_turn(str(event.get("message") or ""))
        elif event.get("type") == "stage" and on_stage:
            on_stage(str(event.get("message") or ""))
        if time.time() > deadline:
            process.kill()
            raise TimeoutError(f"城市 {safe} 的采访超时")
    stderr = (process.stderr.read() if process.stderr else "") or ""
    code = process.wait()
    if code != 0:
        tail = stderr.strip().splitlines()[-12:]
        raise RuntimeError(f"城市 {safe} 的采访进程失败（退出码 {code}）：\n" + "\n".join(tail))
    if not out_path.exists():
        raise RuntimeError(f"城市 {safe} 的采访没有产出结果文件")
    result = json.loads(out_path.read_text(encoding="utf-8"))
    transcripts = [Transcript.from_dict(item) for item in (result.get("transcripts") or [])]
    # Backstop the progress counter: a child that died mid-stream would
    # otherwise leave the bar short of where its results say it got to.
    while seen < turns:
        seen += 1
        on_turn("")
    return transcripts


def _slug_filename(text: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in text)[:40] or "city"


#: Filename-safe extension per image media type, for the payloads moved out of
#: ``session.json`` by :func:`_stored_questions`.
_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _stored_questions(session_id: str, round_no: int, questions: list[Any]) -> list[dict[str, Any]]:
    """Question records for ``session.json``, with image bytes moved to disk.

    A base64 photo is ~1.33x its file size, and ``session.json`` is read *in
    full* on every follow-up round and every panel fetch of the session. Left
    inline, one 3 MB upload becomes a 4 MB string in all of those reads — and
    the panel's session request would carry it back to the browser, which
    already has the picture.

    The attachment keeps a resolvable file path instead of the payload, so the
    stored question remains a faithful record of what was asked (and
    :func:`gaworld.interview.attachments.resolve_material` can still read it).
    A payload that cannot be decoded is left as-is rather than dropped: losing
    the record of *what* was attached would be worse than a large file.
    """
    import base64
    import binascii

    records: list[dict[str, Any]] = []
    image_dir = store.round_dir(session_id, round_no) / "images"
    for question in questions:
        payload = question.to_dict()
        for index, attachment in enumerate(payload.get("attachments") or []):
            if attachment.get("kind") != "image":
                continue
            raw = str(attachment.get("value") or "")
            body = raw.split(";base64,", 1)[-1] if ";base64," in raw else raw
            media = "image/png"
            if raw.startswith("data:"):
                media = raw[5:].split(";", 1)[0] or media
            try:
                data = base64.b64decode(body, validate=True)
            except (binascii.Error, ValueError):
                continue
            image_dir.mkdir(parents=True, exist_ok=True)
            target = image_dir / f"{question.id}-{index}.{_IMAGE_EXTENSIONS.get(media, 'png')}"
            try:
                target.write_bytes(data)
            except OSError as exc:
                _LOG.warning("interview: could not store image for %s (%s)", question.id, exc)
                continue
            attachment["value"] = str(target)
        records.append(payload)
    return records


def _new_session(payload: dict[str, Any], respondents: list[Respondent]) -> dict[str, Any]:
    return {
        "id": store.new_session_id(),
        "title": str(payload.get("title") or "").strip() or "群体采访",
        "context": str(payload.get("context") or "").strip(),
        "provider": str(payload.get("provider") or "").strip(),
        "created_at": time.time(),
        "updated_at": time.time(),
        "questions": [],
        "respondents": [item.to_dict() for item in respondents],
        "transcripts": {},
        "analysis": {},
        "cities": sorted({item.city for item in respondents}),
        "rounds": [],
    }


def plan_round(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a round without running it: what it will ask, and of whom.

    The panel calls this before spending anything, because "我要问 80 个人 5 个
    问题" is a 400-call commitment and the user should see that number first.
    """
    session = None
    session_id = str(payload.get("session_id") or "").strip()
    if session_id:
        session = store.load_session(session_id)
        if session is None:
            raise InterviewSpecError(f"找不到会话 {session_id}")
    if session:
        respondents = store.session_respondents(session)
        offset = len(session.get("questions") or [])
        round_no = len(session.get("rounds") or []) + 1
    else:
        respondents = normalize_respondents(payload.get("respondents"))
        offset = 0
        round_no = 1
    questions = normalize_questions(payload.get("questions"), start_index=offset, round_no=round_no)
    return {
        "session_id": session_id,
        "round": round_no,
        "questions": [item.to_dict() for item in questions],
        "respondents": len(respondents),
        "people": sum(item.size for item in respondents),
        "cities": sorted({item.city or "" for item in respondents}),
        "calls": len(questions) * len(respondents),
    }


def run_round(payload: dict[str, Any], *, report: ReportFn | None = None) -> dict[str, Any]:
    """Ask one round and return the updated session.

    Creates the session when ``session_id`` is absent, appends to it when
    present. ``report`` receives ``(fraction, message)``.
    """

    def note(fraction: float, message: str) -> None:
        if report:
            report(max(0.0, min(1.0, fraction)), message)

    session_id = str(payload.get("session_id") or "").strip()
    session = store.load_session(session_id) if session_id else None
    if session_id and session is None:
        raise InterviewSpecError(f"找不到会话 {session_id}")

    if session is None:
        respondents = normalize_respondents(payload.get("respondents"))
        session = _new_session(payload, respondents)
    else:
        respondents = store.session_respondents(session)
        for key in ("title", "context", "provider"):
            value = str(payload.get(key) or "").strip()
            if value:
                session[key] = value

    prior_questions = store.session_questions(session)
    round_no = len(session.get("rounds") or []) + 1
    questions = normalize_questions(
        payload.get("questions"), start_index=len(prior_questions), round_no=round_no
    )

    provider = str(session.get("provider") or "")
    concurrency = max(1, min(16, int(payload.get("concurrency") or 4)))

    note(0.02, "正在准备材料…")
    from gaworld.llm.providers import provider_supports_images

    try:
        vision = provider_supports_images(task="interview", provider=provider or None)
    except Exception:  # a misconfigured router must not block a text-only run
        vision = False
    base_spec = SessionSpec(
        questions=questions,
        respondents=[],
        title=str(session.get("title") or ""),
        context=str(session.get("context") or ""),
        provider=provider,
        concurrency=concurrency,
        history_questions=prior_questions,
    )
    material = resolve_session_material(base_spec, vision=vision)
    material_payload = serialize_material(material)

    stored_transcripts = dict(session.get("transcripts") or {})
    history = {uid: list((entry or {}).get("answers") or []) for uid, entry in stored_transcripts.items()}

    by_city: dict[str, list[Respondent]] = {}
    for respondent in respondents:
        by_city.setdefault(respondent.city, []).append(respondent)

    total_turns = len(respondents) * len(questions)
    done = 0
    started = time.time()

    def fraction_now() -> float:
        # 0.05..0.90 is the asking phase; the tail is analysis and rendering.
        return 0.05 + 0.85 * (done / total_turns if total_turns else 1)

    def on_turn(message: str) -> None:
        nonlocal done
        done += 1
        note(fraction_now(), message or f"已完成 {done}/{total_turns} 次提问")

    def on_stage(message: str) -> None:
        # Narration without progress: the bar holds where it is, the label
        # says what is happening. Persona building for 80 residents is not
        # instant and a frozen, silent bar reads as a hang.
        note(fraction_now(), message)

    collected: list[Transcript] = []
    failures: list[str] = []
    for slug, city_respondents in by_city.items():
        spec = SessionSpec(
            questions=questions,
            respondents=city_respondents,
            title=base_spec.title,
            context=base_spec.context,
            provider=provider,
            concurrency=concurrency,
            history={r.uid: history.get(r.uid, []) for r in city_respondents},
            history_questions=prior_questions,
        )
        label = slug or "默认世界"
        note(fraction_now(), f"正在采访 {label}…")
        try:
            collected.extend(
                _run_city(
                    session_id=str(session["id"]),
                    round_no=round_no,
                    slug=slug,
                    spec=spec,
                    material_payload=material_payload,
                    on_turn=on_turn,
                    on_stage=on_stage,
                )
            )
        except (RuntimeError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            # One city failing must not discard the cities that succeeded.
            # Their respondents get an error transcript so the report can say
            # who was not reached instead of quietly shrinking the sample.
            _LOG.exception("interview: city %s failed", label)
            failures.append(f"{label}：{exc}")
            for respondent in city_respondents:
                collected.append(Transcript(respondent=respondent, error=str(exc)))

    # Merge this round's answers onto whatever the respondent already said.
    for transcript in collected:
        uid = transcript.respondent.uid
        entry = stored_transcripts.get(uid)
        if not isinstance(entry, dict):
            entry = {"respondent": transcript.respondent.to_dict(), "answers": [], "error": ""}
        answers = list(entry.get("answers") or [])
        answers.extend(item.to_dict() for item in transcript.answers)
        entry["answers"] = answers
        entry["respondent"] = transcript.respondent.to_dict()
        entry["error"] = transcript.error or ""
        stored_transcripts[uid] = entry

    session["transcripts"] = stored_transcripts
    session["questions"] = [item.to_dict() for item in prior_questions] + _stored_questions(
        str(session["id"]), round_no, questions
    )
    session.setdefault("rounds", []).append(
        {
            "round": round_no,
            "questions": [item.id for item in questions],
            "started_at": started,
            "finished_at": time.time(),
            "failures": failures,
        }
    )

    note(0.92, "正在汇总与统计…")
    all_questions = store.session_questions(session)
    all_transcripts = store.session_transcripts(session)
    summarize = _summarizer(provider) if payload.get("summarize", True) else None
    analysis = aggregate(all_questions, all_transcripts, ask=summarize)
    analysis["failures"] = failures
    session["analysis"] = analysis

    note(0.97, "正在生成文档…")
    markdown = report_mod.render_markdown(
        title=str(session.get("title") or "群体采访结果"),
        context=str(session.get("context") or ""),
        questions=all_questions,
        transcripts=all_transcripts,
        analysis=analysis,
        meta={
            "provider": provider,
            "started_at": session.get("created_at"),
            "finished_at": time.time(),
        },
    )
    store.save_report(str(session["id"]), markdown)
    store.save_session(session)
    note(1.0, "完成")
    return session


def _summarizer(provider: str) -> Callable[[str], str]:
    from gaworld.llm.providers import call_llm

    def ask(prompt: str) -> str:
        return call_llm(prompt, task="interview_summary", provider=provider or None)

    return ask


__all__ = ["plan_round", "run_round"]
