"""The post-run survey of a ``composite`` study: questions, measures, scores.

A composite study runs its worlds exactly like a parallel worlds study and
then interviews the residents of every world, each with that world's own
memories and end-of-run state (:mod:`gaworld.interview`). What the residents
*say* becomes a measure next to what their state variables *did* — which is
the result form social scientists actually work with: "the treated town
reports more trust in the city government than the control town".

Only answers that can be counted become measures, and every survey measure is
on the same 0–1 scale as the state metrics so a ``min_effect`` means the same
thing for both:

``scale``
    an ordered single choice (default five-point agreement). The score is the
    chosen option's position, 0 for the first option and 1 for the last,
    averaged over the residents whose answer parsed.
``boolean``
    yes / no. The score is the share answering yes.
``open``
    asked and reported, never scored.

Pure functions only; running the interviews lives in
:mod:`gaworld.research.backends`.
"""

from __future__ import annotations

import re
from typing import Any

from gaworld.research.measures import Measure

SURVEY_KINDS = ("scale", "boolean", "open")
MEASURED_KINDS = ("scale", "boolean")
MAX_SURVEY_QUESTIONS = 8
PREFIX = "survey."

DEFAULT_SCALE = {
    "zh-CN": ["非常不同意", "不同意", "说不清", "同意", "非常同意"],
    "en": ["Strongly disagree", "Disagree", "Not sure", "Agree", "Strongly agree"],
}

#: A survey measure is a 0–1 score; this is what the compile prompt and the
#: report say about it.
NOTE = "问卷，0–1：量表题按所选选项的位置归一（第一项 0、最后一项 1），是非题为答「是」的比例；跑完后在各世界里采访居民"

#: Provenance of every survey measure: the instrument is ours, the answers are
#: a model speaking as the resident from that world's memories and state.
BASIS = "模型扮演居民、按该世界的记忆与最后状态作答的自述；答案的倾向就是模型对这种处境的判断"

_ID_RE = re.compile(r"[^0-9A-Za-z_]+")


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_survey(raw: Any, *, language: str = "zh-CN", dropped: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Validate a model-written survey block. Returns ``{"questions", "context"}``.

    Unusable questions are recorded in ``dropped`` with the reason, the same
    way the protocol compiler records hypotheses it cannot run.
    """
    dropped = dropped if dropped is not None else []
    block = raw if isinstance(raw, dict) else {"questions": raw if isinstance(raw, list) else []}
    items = block.get("questions") if isinstance(block.get("questions"), list) else []
    if len(items) > MAX_SURVEY_QUESTIONS:
        dropped.append({"what": "survey", "where": f"{len(items)} 题",
                        "reason": f"问卷最多 {MAX_SURVEY_QUESTIONS} 题，多出的被丢弃"})
        items = items[:MAX_SURVEY_QUESTIONS]
    questions: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(items):
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text") or item.get("question"), 400)
        if not text:
            dropped.append({"what": "survey", "where": f"第 {index + 1} 题", "reason": "问题内容为空"})
            continue
        kind = _text(item.get("kind") or item.get("type"), 16).lower()
        if kind in ("likert", "choice", "rating", "量表"):
            kind = "scale"
        elif kind in ("yesno", "bool", "是非"):
            kind = "boolean"
        if kind not in SURVEY_KINDS:
            kind = "open"
        options = [_text(option, 60) for option in item.get("options") or [] if _text(option, 60)]
        if kind == "scale" and len(options) < 3:
            options = list(DEFAULT_SCALE.get(language, DEFAULT_SCALE["zh-CN"]))
        if kind != "scale":
            options = []
        qid = _ID_RE.sub("", _text(item.get("id"), 12)).upper() or f"Q{index + 1}"
        while qid in used:
            qid = f"{qid}X"
        used.add(qid)
        questions.append({"id": qid, "text": text, "kind": kind, "options": options})
    return {"questions": questions, "context": _text(block.get("context"), 1000)}


def measure_id(question: dict[str, Any]) -> str:
    return f"{PREFIX}{question['id']}"


def survey_measures(survey: dict[str, Any] | None) -> dict[str, Measure]:
    """Registry entries for the survey's countable questions."""
    out: dict[str, Measure] = {}
    for question in (survey or {}).get("questions") or []:
        if question.get("kind") not in MEASURED_KINDS:
            continue
        mid = measure_id(question)
        out[mid] = Measure(id=mid, label=f"问卷 {question['id']}：{question['text'][:24]}",
                           source="post-run survey", family="survey", note=NOTE, grade="c", basis=BASIS)
    return out


def interview_questions(survey: dict[str, Any]) -> list[dict[str, Any]]:
    """The survey as :mod:`gaworld.interview` questions."""
    out = []
    for question in survey.get("questions") or []:
        kind = {"scale": "choice", "boolean": "boolean"}.get(question["kind"], "open")
        payload = {"id": question["id"], "text": question["text"], "kind": kind}
        if kind == "choice":
            payload["options"] = list(question["options"])
        out.append(payload)
    return out


def score(survey: dict[str, Any], transcripts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``measure id -> {"value", "n", "unparsed", "asked", "by_resident"}`` for one world.

    ``value`` is ``None`` when no answer to that question could be counted —
    the evaluator then treats the world as unmeasured on it rather than as 0.
    ``by_resident`` maps each respondent's ref to their counted answer, so the
    same residents' answers in two worlds can be paired.
    """
    out: dict[str, dict[str, Any]] = {}
    for question in survey.get("questions") or []:
        if question.get("kind") not in MEASURED_KINDS:
            continue
        values: list[float] = []
        by_resident: dict[str, float] = {}
        unparsed = asked = 0
        for transcript in transcripts or []:
            ref = str((transcript.get("respondent") or {}).get("ref") or "")
            for answer in transcript.get("answers") or []:
                if answer.get("question_id") != question["id"]:
                    continue
                asked += 1
                if question["kind"] == "boolean":
                    if answer.get("boolean") is None or answer.get("unparsed"):
                        unparsed += 1
                        continue
                    values.append(1.0 if answer["boolean"] else 0.0)
                    by_resident[ref] = values[-1]
                else:
                    options = question["options"]
                    picked = [options.index(label) for label in answer.get("choice") or [] if label in options]
                    if not picked or answer.get("unparsed"):
                        unparsed += 1
                        continue
                    values.append(picked[0] / (len(options) - 1))
                    by_resident[ref] = values[-1]
        out[measure_id(question)] = {
            "value": round(sum(values) / len(values), 6) if values else None,
            "n": len(values),
            "unparsed": unparsed,
            "asked": asked,
            "by_resident": by_resident,
        }
    return out


__all__ = [
    "BASIS",
    "DEFAULT_SCALE",
    "MAX_SURVEY_QUESTIONS",
    "MEASURED_KINDS",
    "NOTE",
    "PREFIX",
    "SURVEY_KINDS",
    "interview_questions",
    "measure_id",
    "normalize_survey",
    "score",
    "survey_measures",
]
