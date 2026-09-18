"""Run one round of a group interview.

The shape of the work is fixed by three constraints pulling against each
other:

* **Sequential within a respondent** — question 4 must be answered by someone
  who remembers answering question 1, so one respondent's turns cannot run in
  parallel with each other.
* **Parallel across respondents** — 80 residents answering 5 questions is 400
  model calls, and nobody waits for that serially.
* **Persona building is not thread-safe.** Building a resident seeds the
  vector store, and ``gaworld.memory.store`` holds a *process-global* single
  SQLite connection — using it from a worker thread raises "SQLite objects
  created in a thread can only be used in that same thread".

So the round runs in two phases: personas are built **serially on the calling
thread**, then the question loops fan out over a thread pool. That puts the
parallelism where the time actually goes (every worker is blocked on an HTTP
call to the model) and keeps the file/SQLite work single-threaded. Making the
memory store thread-safe would be the other fix, and a much larger blast
radius than this feature deserves.

One respondent failing is not the round failing. A dead resident's transcript
carries its error and the other 79 still produce a survey — the alternative
(abort on first exception) throws away every answer already paid for.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gaworld.interview.attachments import ResolvedMaterial
from gaworld.interview.prompt import build_turn_prompt, parse_answer
from gaworld.interview.schema import Answer, Question, Respondent, SessionSpec, Transcript
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interview.runner")

#: ``(respondent, question, prompt, images) -> raw model text``
AskFn = Callable[[Respondent, Question, str, list[dict[str, str]]], str]
#: ``(respondent) -> persona block for the prompt``
PersonaFn = Callable[[Respondent], str]
#: ``(done, total, message) -> None``
ReportFn = Callable[[int, int, str], None]
#: ``(message) -> None`` — phase narration that is not a completed turn.
StageFn = Callable[[str], None]


def _history_pairs(spec: SessionSpec, respondent: Respondent) -> list[tuple[Question, Answer]]:
    """Prior rounds' Q&A for this respondent, in ask order."""
    stored = spec.history.get(respondent.uid) or []
    if not stored:
        return []
    by_id = {question.id: question for question in spec.history_questions}
    pairs: list[tuple[Question, Answer]] = []
    for payload in stored:
        answer = Answer.from_dict(payload)
        question = by_id.get(answer.question_id)
        if question is None:
            # A stored answer whose question is gone cannot be replayed as
            # Q&A; replaying the answer alone would read as the respondent
            # volunteering a non-sequitur.
            continue
        pairs.append((question, answer))
    return pairs


def _ask_one(
    ask_fn: AskFn,
    respondent: Respondent,
    question: Question,
    prompt: str,
    material: ResolvedMaterial | None,
) -> tuple[str, str]:
    """One model call. Returns ``(raw_text, degradation_note)``.

    A provider that rejects the images (a vision flag set on a text-only
    model, an endpoint that does not implement image parts) gets one retry
    without them. Losing the picture and saying so beats losing the entire
    session to a config mistake — and the note is what stops the answer from
    being read as if the model had seen it.
    """
    images = material.images if material else []
    note = material.degradation if material else ""
    if not images:
        return ask_fn(respondent, question, prompt, []), note
    try:
        return ask_fn(respondent, question, prompt, images), note
    except Exception as exc:
        _LOG.warning(
            "interview: image call failed for %s on %s (%s); retrying without images",
            respondent.uid,
            question.id,
            exc,
        )
        retry_note = "模型拒绝了图片输入，已改用文字说明重问"
        return ask_fn(respondent, question, prompt, []), "；".join(
            part for part in (note, retry_note) if part
        )


def run_round(
    spec: SessionSpec,
    *,
    persona_fn: PersonaFn,
    ask_fn: AskFn,
    material: dict[str, ResolvedMaterial] | None = None,
    report: ReportFn | None = None,
    stage: StageFn | None = None,
) -> list[Transcript]:
    """Ask every question in ``spec`` to every respondent in ``spec``.

    ``persona_fn`` and ``ask_fn`` are injected so this module has no
    dependency on the simulator: the tests pass pure functions, and
    :mod:`gaworld.interview.local` passes the ones that build a real resident
    and call the configured model.

    ``persona_fn`` is always called on the calling thread — see the module
    docstring; it touches a process-global SQLite connection.
    """
    material = material or {}
    total = len(spec.respondents) * len(spec.questions)
    done = 0
    lock = threading.Lock()

    def tick(label: str) -> None:
        nonlocal done
        with lock:
            done += 1
            current = done
        if report:
            report(current, total, label)

    # -- phase 1: personas, serially, on this thread ------------------------
    personas: dict[str, str] = {}
    failures: dict[str, str] = {}
    for index, respondent in enumerate(spec.respondents, start=1):
        if stage:
            stage(f"正在准备受访者 {index}/{len(spec.respondents)}：{respondent.label}")
        try:
            personas[respondent.uid] = persona_fn(respondent)
        except Exception as exc:
            _LOG.exception("interview: persona build failed for %s", respondent.uid)
            failures[respondent.uid] = f"构建受访者失败：{exc}"

    # -- phase 2: the question loops, in parallel ---------------------------
    def work(respondent: Respondent) -> Transcript:
        transcript = Transcript(respondent=respondent)
        persona = personas.get(respondent.uid)
        if persona is None:
            transcript.error = failures.get(respondent.uid, "构建受访者失败")
            # Still advance the counter for every question this respondent
            # will not answer, or the progress bar stalls short of 100%.
            for question in spec.questions:
                tick(f"{respondent.label} · {question.id} 跳过")
            return transcript

        history = _history_pairs(spec, respondent)
        for index, question in enumerate(spec.questions, start=1):
            prompt = build_turn_prompt(
                persona=persona,
                context=spec.context,
                question=question,
                material=material.get(question.id),
                history=history,
                turn_no=len(history) + 1,
                total=len(history) + len(spec.questions),
            )
            try:
                raw, note = _ask_one(ask_fn, respondent, question, prompt, material.get(question.id))
                answer = parse_answer(raw, question)
                answer.degraded = note
            except Exception as exc:
                _LOG.warning("interview: %s failed on %s: %s", respondent.uid, question.id, exc)
                answer = Answer(question_id=question.id, error=str(exc), unparsed=True)
            transcript.answers.append(answer)
            # The answer just given is part of the next question's context —
            # this is the continuity, and it must be appended before the
            # next iteration builds its prompt.
            history.append((question, answer))
            tick(f"{respondent.label} · 第{index}问")
        return transcript

    if not spec.respondents:
        return []
    workers = max(1, min(spec.concurrency, len(spec.respondents)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="interview") as pool:
        transcripts = list(pool.map(work, spec.respondents))
    return transcripts


def resolve_session_material(spec: SessionSpec, *, vision: bool) -> dict[str, ResolvedMaterial]:
    """Fetch and decode every question's material once, keyed by question id."""
    from gaworld.interview.attachments import resolve_material

    return {
        question.id: resolve_material(question.attachments, vision=vision)
        for question in spec.questions
        if question.attachments
    }


def serialize_material(material: dict[str, ResolvedMaterial]) -> dict[str, Any]:
    from gaworld.interview.attachments import material_to_dict

    return {key: material_to_dict(value) for key, value in material.items()}


def deserialize_material(payload: Any) -> dict[str, ResolvedMaterial]:
    from gaworld.interview.attachments import material_from_dict

    payload = payload if isinstance(payload, dict) else {}
    return {str(key): material_from_dict(value) for key, value in payload.items()}


__all__ = [
    "AskFn",
    "PersonaFn",
    "ReportFn",
    "deserialize_material",
    "resolve_session_material",
    "run_round",
    "serialize_material",
]
