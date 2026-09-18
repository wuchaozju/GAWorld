"""Turn transcripts into counts, cross-tabs, and a written summary.

Three numbers per bucket, and the distinction is not pedantry:

``respondents``  how many respondents picked it.
``people``       how many *residents* they speak for — a cohort of 8 that
                 answers "支持" is 8 people, not 1. Mixing individuals and
                 group agents in one survey makes the unweighted count a
                 statement about the sample design rather than the
                 population, so both are always reported.
``share``        ``people`` over the answered total, so a reader is never
                 handed a percentage without knowing its denominator.

Unparsed answers are excluded from every count and reported separately.
Folding them into a bucket would invent an opinion; dropping them silently
would shrink the denominator without saying so, which is how a survey ends up
claiming 100% agreement from three usable answers out of forty.

Cross-tabs come from ``Respondent.demographics``, which is why that mapping
is carried on the respondent rather than re-derived here — by aggregation
time the per-city child process that knew the population is gone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gaworld.interview.schema import Question, Transcript

#: Axes offered as breakdowns. ``city`` is always present (the roster mirrors
#: it in); the rest exist when the roster supplied them.
BREAKDOWN_AXES: tuple[str, ...] = ("city", "age_band", "gender", "hukou", "district")

#: Open answers fed to the summarizer. A summary is one model call over many
#: answers, so the cap is about context, not cost: past this the earliest
#: answers fall out of a small model's window and the "summary" silently
#: describes a suffix of the sample.
SUMMARY_SAMPLE = 60


def _buckets(question: Question) -> list[str]:
    """The countable outcomes of ``question``, in report order."""
    if question.kind == "choice":
        return list(question.options)
    if question.kind == "boolean":
        return ["是", "否"]
    return []


def _picked(answer: Any, question: Question) -> list[str]:
    """Which buckets one answer lands in. Empty = not countable."""
    if answer is None or answer.unparsed or answer.error:
        return []
    if question.kind == "choice":
        return list(answer.choice)
    if question.kind == "boolean":
        if answer.boolean is None:
            return []
        return ["是" if answer.boolean else "否"]
    return []


def tally(question: Question, transcripts: list[Transcript]) -> dict[str, Any]:
    """Counts for one countable question over all transcripts."""
    buckets = _buckets(question)
    counts = {name: {"respondents": 0, "people": 0} for name in buckets}
    answered = 0
    answered_people = 0
    unparsed = 0
    missing = 0
    for transcript in transcripts:
        answer = transcript.by_question().get(question.id)
        if answer is None:
            missing += 1
            continue
        picks = _picked(answer, question)
        if not picks:
            # An answer with prose but no parsable pick is a different
            # failure from no answer at all, and the report says which.
            if answer.error:
                missing += 1
            else:
                unparsed += 1
            continue
        answered += 1
        answered_people += transcript.respondent.size
        for pick in picks:
            if pick not in counts:
                continue
            counts[pick]["respondents"] += 1
            counts[pick]["people"] += transcript.respondent.size
    rows = []
    for name in buckets:
        people = counts[name]["people"]
        rows.append(
            {
                "label": name,
                "respondents": counts[name]["respondents"],
                "people": people,
                "share": (people / answered_people) if answered_people else 0.0,
            }
        )
    return {
        "question_id": question.id,
        "kind": question.kind,
        "multi": question.multi,
        "rows": rows,
        "answered": answered,
        "answered_people": answered_people,
        "unparsed": unparsed,
        "missing": missing,
    }


def breakdown(
    question: Question, transcripts: list[Transcript], axes: list[str] | None = None
) -> dict[str, Any]:
    """Cross-tab one countable question against each demographic axis.

    An axis is only reported when it actually splits the sample: a survey of
    one city gains nothing from a "按城市" chart with a single bar, and
    showing it invites the reader to see a distribution where there is none.
    """
    chosen = list(axes or BREAKDOWN_AXES)
    buckets = _buckets(question)
    if not buckets:
        return {}
    result: dict[str, Any] = {}
    for axis in chosen:
        groups: dict[str, dict[str, Any]] = {}
        for transcript in transcripts:
            value = transcript.respondent.demographics.get(axis)
            if not value:
                continue
            answer = transcript.by_question().get(question.id)
            picks = _picked(answer, question)
            group = groups.setdefault(
                value,
                {
                    "value": value,
                    "counts": dict.fromkeys(buckets, 0),
                    "people": dict.fromkeys(buckets, 0),
                    "answered": 0,
                    "answered_people": 0,
                },
            )
            if not picks:
                continue
            group["answered"] += 1
            group["answered_people"] += transcript.respondent.size
            for pick in picks:
                if pick in group["counts"]:
                    group["counts"][pick] += 1
                    group["people"][pick] += transcript.respondent.size
        if len(groups) < 2:
            continue
        result[axis] = [
            groups[key] for key in sorted(groups, key=lambda name: (-groups[name]["answered_people"], name))
        ]
    return result


def _summary_prompt(question: Question, samples: list[tuple[str, str]], stats: dict[str, Any]) -> str:
    lines = [f"{label}：{text}" for label, text in samples]
    stat_line = ""
    if stats.get("rows"):
        parts = [
            f"{row['label']} {row['people']}人（{row['share']:.0%}）"
            for row in stats["rows"]
            if row["people"]
        ]
        if parts:
            stat_line = "已有的统计结果：" + "；".join(parts) + "\n"
    return (
        "下面是同一个问题在一次群体访谈里收到的回答。请写一段中文摘要。\n"
        f"问题：{question.text}\n"
        f"{stat_line}"
        "回答：\n" + "\n".join(lines) + "\n\n"
        "要求：\n"
        "1) 3-5 句话，先说主流看法，再说少数但值得注意的看法。\n"
        "2) 指出分歧所在，以及分歧看起来和什么有关（年龄、城市、户籍等），"
        "只在回答里真的能看出来时才说。\n"
        "3) 不要编造没有出现过的观点，不要写成条目列表。\n"
        "只输出摘要正文。"
    )


def summarize_question(
    question: Question,
    transcripts: list[Transcript],
    stats: dict[str, Any],
    ask: Callable[[str], str],
) -> str:
    """One-paragraph summary of what respondents said, or ``""``.

    ``ask`` is injected so aggregation stays testable without a model and so
    the caller controls routing (the same provider that ran the interview).
    """
    samples: list[tuple[str, str]] = []
    for transcript in transcripts:
        answer = transcript.by_question().get(question.id)
        if answer is None or answer.error:
            continue
        said = answer.text.strip() or answer.reason.strip()
        if answer.choice:
            said = f"[选了 {'、'.join(answer.choice)}] {said}".strip()
        elif answer.boolean is not None:
            said = f"[{'是' if answer.boolean else '否'}] {said}".strip()
        if not said:
            continue
        samples.append((transcript.respondent.label, said[:400]))
        if len(samples) >= SUMMARY_SAMPLE:
            break
    if not samples:
        return ""
    try:
        return str(ask(_summary_prompt(question, samples, stats)) or "").strip()
    except Exception:
        # A failed summary must not cost the counts and the transcripts,
        # which are the parts that cannot be regenerated for free.
        return ""


def _open_stats(question: Question, transcripts: list[Transcript]) -> dict[str, Any]:
    """Coverage for an open question: no buckets, but still a denominator.

    An open question has nothing to count, yet the report still needs to say
    how many people actually answered it — a summary written from four
    answers out of forty should not read like a summary of forty.
    """
    answered = 0
    answered_people = 0
    missing = 0
    for transcript in transcripts:
        answer = transcript.by_question().get(question.id)
        if answer is None:
            missing += 1
            continue
        if answer.unparsed or answer.error:
            missing += 1
            continue
        answered += 1
        answered_people += transcript.respondent.size
    return {
        "question_id": question.id,
        "kind": "open",
        "rows": [],
        "answered": answered,
        "answered_people": answered_people,
        "unparsed": 0,
        "missing": missing,
    }


def aggregate(
    questions: list[Question],
    transcripts: list[Transcript],
    *,
    axes: list[str] | None = None,
    ask: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Full analysis payload: per-question stats, cross-tabs and summaries."""
    per_question: list[dict[str, Any]] = []
    for question in questions:
        stats = (
            _open_stats(question, transcripts) if question.kind == "open" else tally(question, transcripts)
        )
        entry: dict[str, Any] = {
            "question": question.to_dict(),
            "stats": stats,
            "breakdown": breakdown(question, transcripts, axes),
            "summary": "",
        }
        if ask is not None:
            entry["summary"] = summarize_question(question, transcripts, stats, ask)
        per_question.append(entry)

    failed = [t for t in transcripts if t.error]
    return {
        "respondents": len(transcripts),
        "people": sum(t.respondent.size for t in transcripts),
        "cohorts": sum(1 for t in transcripts if t.respondent.kind == "cohort"),
        "individuals": sum(1 for t in transcripts if t.respondent.kind == "agent"),
        "cities": sorted({t.respondent.demographics.get("city", "") for t in transcripts}),
        "failed": [{"uid": t.respondent.uid, "label": t.respondent.label, "error": t.error} for t in failed],
        "questions": per_question,
    }


__all__ = ["BREAKDOWN_AXES", "aggregate", "breakdown", "summarize_question", "tally"]
