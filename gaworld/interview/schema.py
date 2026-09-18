"""The data model of a group interview, and the normalizers that guard it.

Everything crossing a boundary — the HTTP payload from the panel, the JSON
spec handed to a per-city child process, the session file on disk — is one of
these dataclasses. The normalizers are the only place that trusts raw input,
so a malformed question from the browser fails here with a message rather
than three layers down inside a prompt.

Two invariants are worth stating because the aggregation depends on them:

* **Question ids are stable and unique across rounds.** A follow-up round
  numbers from ``len(existing) + 1``, so ``q3`` means the same question in
  round 2's tallies as it did when it was asked. Reusing ``q1`` for a new
  question would silently merge two different questions' counts.
* **``choice`` options are a closed set.** A choice answer is only counted
  when it matches one of the declared options, because "统计这些结果" is
  meaningless over free text that happens to resemble an option.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: What a question asks for, and therefore how its answer is parsed.
#:
#: ``open``     prose; summarized, never counted.
#: ``choice``   one (or several) of ``options``; counted per option.
#: ``boolean``  yes/no; counted as two buckets.
QUESTION_KINDS: tuple[str, ...] = ("open", "choice", "boolean")

#: What a respondent is. ``agent`` is one resident at individual fidelity;
#: ``cohort`` is a group agent answering once on behalf of its members.
RESPONDENT_KINDS: tuple[str, ...] = ("agent", "cohort")

#: Attachment kinds. ``url`` is fetched and reduced to article text;
#: ``image`` is passed to the model as an image when the provider can take
#: one, and degraded to its caption when it cannot.
ATTACHMENT_KINDS: tuple[str, ...] = ("url", "image")

#: Hard ceiling on respondents in one session. Not a cost model — just a
#: guard against a mis-click turning into ten thousand LLM calls. The panel
#: shows the number it is about to ask before it asks.
MAX_RESPONDENTS = 500

#: Hard ceiling on questions per round. Each question is its own LLM call per
#: respondent, so this multiplies :data:`MAX_RESPONDENTS`.
MAX_QUESTIONS_PER_ROUND = 20

#: Options per choice question. Past ~12 the model stops discriminating and
#: the tally stops meaning anything.
MAX_OPTIONS = 12


class InterviewSpecError(ValueError):
    """Raised for input that cannot be turned into a runnable session."""


def _text(value: Any, limit: int = 2000) -> str:
    cleaned = re.sub(r"[ \t]+", " ", str(value or "")).strip()
    return cleaned[:limit]


@dataclass
class Attachment:
    """Material shown alongside a question — a URL or an image.

    ``caption`` is not decoration: it is the degradation path. When the
    routed provider has no vision capability, the caption is what reaches the
    model, and an answer produced that way is flagged in the transcript
    rather than passed off as if the model had seen the picture.
    """

    kind: str
    value: str
    caption: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value, "caption": self.caption}

    @classmethod
    def from_dict(cls, payload: Any) -> Attachment:
        if not isinstance(payload, dict):
            raise InterviewSpecError("附件必须是对象")
        kind = _text(payload.get("kind"), 16).lower()
        if kind not in ATTACHMENT_KINDS:
            raise InterviewSpecError(f"附件类型只能是 {'/'.join(ATTACHMENT_KINDS)}，收到 {kind!r}")
        # Images arrive as data URLs, which are long; URLs are short. One
        # limit for both would either truncate a PNG or let a 5 MB "url"
        # through.
        limit = 8_000_000 if kind == "image" else 2000
        value = str(payload.get("value") or "").strip()[:limit]
        if not value:
            raise InterviewSpecError("附件缺少内容")
        return cls(kind=kind, value=value, caption=_text(payload.get("caption"), 500))


@dataclass
class Question:
    """One question, with the answer shape it expects."""

    id: str
    text: str
    kind: str = "open"
    options: list[str] = field(default_factory=list)
    #: ``choice`` only: whether more than one option may be picked.
    multi: bool = False
    attachments: list[Attachment] = field(default_factory=list)
    #: Which round asked it. 1-based; used by the report's section headings.
    round: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "options": list(self.options),
            "multi": self.multi,
            "attachments": [item.to_dict() for item in self.attachments],
            "round": self.round,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> Question:
        if not isinstance(payload, dict):
            raise InterviewSpecError("问题必须是对象")
        kind = _text(payload.get("kind"), 16).lower() or "open"
        if kind not in QUESTION_KINDS:
            raise InterviewSpecError(f"问题类型只能是 {'/'.join(QUESTION_KINDS)}，收到 {kind!r}")
        text = _text(payload.get("text"))
        if not text:
            raise InterviewSpecError("问题内容不能为空")
        options = [_text(item, 120) for item in (payload.get("options") or [])]
        options = [item for item in options if item]
        # Deduplicate while keeping the author's order: two identical labels
        # make the tally ambiguous about which bucket an answer landed in.
        seen: set[str] = set()
        options = [item for item in options if not (item in seen or seen.add(item))]
        if kind == "choice":
            if len(options) < 2:
                raise InterviewSpecError(f"选择题「{text[:20]}」至少需要 2 个选项")
            if len(options) > MAX_OPTIONS:
                raise InterviewSpecError(f"选择题选项最多 {MAX_OPTIONS} 个")
        else:
            options = []
        return cls(
            id=_text(payload.get("id"), 32),
            text=text,
            kind=kind,
            options=options,
            multi=bool(payload.get("multi")) and kind == "choice",
            attachments=[Attachment.from_dict(item) for item in (payload.get("attachments") or [])],
            round=max(1, int(payload.get("round") or 1)),
        )


@dataclass
class Respondent:
    """Who is being asked.

    ``demographics`` is the breakdown axis set — the whole point of asking a
    crowd rather than a person is being able to cut the answers by city, age
    band, gender, industry or hukou afterwards, so it is carried with the
    respondent instead of re-derived from the population at report time (by
    which point the child process that knew the city is gone).
    """

    kind: str
    city: str
    ref: str
    label: str
    demographics: dict[str, str] = field(default_factory=dict)
    #: Members represented. 1 for an individual, the member count for a
    #: cohort — a cohort's answer stands for this many people, and weighted
    #: tallies say so.
    size: int = 1
    #: Cohort only: the member ids this cohort speaks for. Carried rather
    #: than re-derived because cohort ids are positional within a partition
    #: (``c001``, ``c002``…), so a child process that re-partitioned with a
    #: different axis set or population size would rebuild ``c003`` as a
    #: different group of people than the one the user picked.
    members: list[int] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable key across processes: ``kind:city:ref``."""
        return f"{self.kind}:{self.city}:{self.ref}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "city": self.city,
            "ref": self.ref,
            "label": self.label,
            "demographics": dict(self.demographics),
            "size": self.size,
            "members": list(self.members),
            "uid": self.uid,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> Respondent:
        if not isinstance(payload, dict):
            raise InterviewSpecError("受访者必须是对象")
        kind = _text(payload.get("kind"), 16).lower() or "agent"
        if kind not in RESPONDENT_KINDS:
            raise InterviewSpecError(f"受访者类型只能是 {'/'.join(RESPONDENT_KINDS)}，收到 {kind!r}")
        ref = _text(payload.get("ref"), 64)
        if not ref:
            raise InterviewSpecError("受访者缺少 ref")
        demographics = {
            _text(key, 32): _text(value, 64)
            for key, value in (payload.get("demographics") or {}).items()
            if _text(value, 64)
        }
        city = _text(payload.get("city"), 64)
        # City is a breakdown axis like any other, and the panel's "按城市"
        # chart reads it from here — so it is mirrored in rather than being a
        # special case downstream.
        demographics.setdefault("city", city or "default")
        members: list[int] = []
        for item in payload.get("members") or []:
            try:
                members.append(int(item))
            except (TypeError, ValueError):
                continue
        return cls(
            kind=kind,
            city=city,
            ref=ref,
            label=_text(payload.get("label"), 120) or ref,
            demographics=demographics,
            size=max(1, int(payload.get("size") or len(members) or 1)),
            members=members,
        )


@dataclass
class Answer:
    """One respondent's answer to one question, parsed into countable form."""

    question_id: str
    text: str = ""
    #: ``choice``: the matched option labels. Empty when nothing matched.
    choice: list[str] = field(default_factory=list)
    #: ``boolean``: True/False, or None when the model did not commit.
    boolean: bool | None = None
    #: The model's stated reason, when it gave one separately from ``text``.
    reason: str = ""
    #: Set when the answer could not be parsed into the question's shape.
    #: Such an answer still appears in the Markdown document (the prose is
    #: real) but is excluded from tallies, and the report says how many.
    unparsed: bool = False
    #: Set when material was degraded — e.g. an image reduced to its caption
    #: because the routed provider has no vision. Surfaced in the report so a
    #: reader never assumes the model saw a picture it did not see.
    degraded: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "choice": list(self.choice),
            "boolean": self.boolean,
            "reason": self.reason,
            "unparsed": self.unparsed,
            "degraded": self.degraded,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> Answer:
        payload = payload if isinstance(payload, dict) else {}
        raw_bool = payload.get("boolean")
        return cls(
            question_id=str(payload.get("question_id") or ""),
            text=str(payload.get("text") or ""),
            choice=[str(item) for item in (payload.get("choice") or [])],
            boolean=None if raw_bool is None else bool(raw_bool),
            reason=str(payload.get("reason") or ""),
            unparsed=bool(payload.get("unparsed")),
            degraded=str(payload.get("degraded") or ""),
            error=str(payload.get("error") or ""),
        )


@dataclass
class Transcript:
    """Everything one respondent said, in ask order."""

    respondent: Respondent
    answers: list[Answer] = field(default_factory=list)
    error: str = ""

    def by_question(self) -> dict[str, Answer]:
        return {answer.question_id: answer for answer in self.answers}

    def to_dict(self) -> dict[str, Any]:
        return {
            "respondent": self.respondent.to_dict(),
            "answers": [item.to_dict() for item in self.answers],
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> Transcript:
        payload = payload if isinstance(payload, dict) else {}
        return cls(
            respondent=Respondent.from_dict(payload.get("respondent")),
            answers=[Answer.from_dict(item) for item in (payload.get("answers") or [])],
            error=str(payload.get("error") or ""),
        )


@dataclass
class SessionSpec:
    """A runnable round: who to ask, what to ask, and how to route it."""

    questions: list[Question] = field(default_factory=list)
    respondents: list[Respondent] = field(default_factory=list)
    title: str = ""
    #: Shared background prepended to every prompt — the survey's framing.
    context: str = ""
    provider: str = ""
    concurrency: int = 4
    #: Prior rounds' transcripts, keyed by respondent uid. This is what makes
    #: the series continuous: round 2's prompt replays round 1's Q&A.
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Questions from prior rounds, so the replayed history reads as Q&A
    #: rather than as answers with no questions.
    history_questions: list[Question] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "context": self.context,
            "provider": self.provider,
            "concurrency": self.concurrency,
            "questions": [item.to_dict() for item in self.questions],
            "respondents": [item.to_dict() for item in self.respondents],
            "history": {key: list(value) for key, value in self.history.items()},
            "history_questions": [item.to_dict() for item in self.history_questions],
        }


def normalize_questions(payload: Any, *, start_index: int = 0, round_no: int = 1) -> list[Question]:
    """Validate questions and assign stable ids.

    ``start_index`` continues the numbering of an existing session so a
    follow-up round cannot collide with a question already asked.
    """
    if isinstance(payload, str):
        payload = [{"text": line} for line in payload.splitlines() if line.strip()]
    if not isinstance(payload, (list, tuple)):
        raise InterviewSpecError("questions 必须是数组")
    questions = [Question.from_dict(item) for item in payload]
    if not questions:
        raise InterviewSpecError("至少需要一个问题")
    if len(questions) > MAX_QUESTIONS_PER_ROUND:
        raise InterviewSpecError(f"一轮最多 {MAX_QUESTIONS_PER_ROUND} 个问题")
    used: set[str] = set()
    for offset, question in enumerate(questions):
        question.round = round_no
        # An id supplied by the caller is honoured only when it does not
        # collide; otherwise positional numbering wins, because a duplicate
        # id corrupts the tally rather than merely looking untidy.
        if not question.id or question.id in used:
            question.id = f"q{start_index + offset + 1}"
        used.add(question.id)
    return questions


def normalize_respondents(payload: Any) -> list[Respondent]:
    """Validate respondents and drop duplicates by :attr:`Respondent.uid`."""
    if not isinstance(payload, (list, tuple)):
        raise InterviewSpecError("respondents 必须是数组")
    respondents: list[Respondent] = []
    seen: set[str] = set()
    for item in payload:
        respondent = Respondent.from_dict(item)
        if respondent.uid in seen:
            continue
        seen.add(respondent.uid)
        respondents.append(respondent)
    if not respondents:
        raise InterviewSpecError("至少需要一位受访者")
    if len(respondents) > MAX_RESPONDENTS:
        raise InterviewSpecError(f"一次最多采访 {MAX_RESPONDENTS} 位受访者，当前 {len(respondents)}")
    return respondents


def normalize_spec(payload: Any) -> SessionSpec:
    """Build a :class:`SessionSpec` from a raw payload, or raise."""
    payload = payload if isinstance(payload, dict) else {}
    spec = SessionSpec(
        questions=normalize_questions(
            payload.get("questions"),
            start_index=int(payload.get("question_offset") or 0),
            round_no=max(1, int(payload.get("round") or 1)),
        ),
        respondents=normalize_respondents(payload.get("respondents")),
        title=_text(payload.get("title"), 200),
        context=_text(payload.get("context"), 4000),
        provider=_text(payload.get("provider"), 64),
        concurrency=max(1, min(16, int(payload.get("concurrency") or 4))),
    )
    history = payload.get("history")
    if isinstance(history, dict):
        spec.history = {
            str(key): [item for item in value if isinstance(item, dict)]
            for key, value in history.items()
            if isinstance(value, list)
        }
    prior = payload.get("history_questions")
    if isinstance(prior, list):
        spec.history_questions = [Question.from_dict(item) for item in prior]
    return spec


__all__ = [
    "ATTACHMENT_KINDS",
    "MAX_OPTIONS",
    "MAX_QUESTIONS_PER_ROUND",
    "MAX_RESPONDENTS",
    "QUESTION_KINDS",
    "RESPONDENT_KINDS",
    "Answer",
    "Attachment",
    "InterviewSpecError",
    "Question",
    "Respondent",
    "SessionSpec",
    "Transcript",
    "normalize_questions",
    "normalize_respondents",
    "normalize_spec",
]
