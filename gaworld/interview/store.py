"""Where a group-interview session lives on disk.

    output/interviews/<session_id>/
        session.json     questions, respondents, transcripts, analysis
        report.md        the rendered document, regenerated each round
        round-<n>/       the spec and raw reply payload handed to each city

Deliberately **not** under a city's run root. Every other runtime artifact is
repointed into ``output/cities/<slug>/`` because it belongs to one city's
history, but a cross-city session belongs to no single city — filing it under
one of them would make it invisible the moment the user selected another, and
filing a copy under each would fork the transcript.

``session.json`` is the whole session, rewritten atomically. Sessions are
small (a few hundred KB for 80 respondents × 10 questions) and always read in
full for a follow-up round, so an append log would buy nothing and cost the
ability to just open the file and read it.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from gaworld.interview.schema import Question, Respondent, Transcript
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.interview.store")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Root for every session, relative to the project root.
INTERVIEWS_DIRNAME = "output/interviews"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def interviews_root() -> Path:
    return PROJECT_ROOT / INTERVIEWS_DIRNAME


def new_session_id() -> str:
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def session_dir(session_id: str) -> Path:
    """Directory for ``session_id``, validated against path traversal.

    The id reaches here from a URL path segment, so a caller could otherwise
    ask for ``../../../etc`` and have us read or write it.
    """
    if not _SAFE_ID_RE.match(str(session_id or "")):
        raise ValueError(f"非法的会话 id：{session_id!r}")
    return interviews_root() / session_id


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def save_session(session: dict[str, Any]) -> Path:
    """Write ``session.json``, returning its path."""
    session_id = str(session.get("id") or "")
    target = session_dir(session_id) / "session.json"
    session["updated_at"] = time.time()
    _atomic_write(target, json.dumps(session, ensure_ascii=False, indent=1))
    return target


def load_session(session_id: str) -> dict[str, Any] | None:
    path = session_dir(session_id) / "session.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("interview: unreadable session %s (%s)", session_id, exc)
        return None
    return payload if isinstance(payload, dict) else None


def save_report(session_id: str, markdown: str) -> Path:
    path = session_dir(session_id) / "report.md"
    _atomic_write(path, markdown)
    return path


def load_report(session_id: str) -> str:
    path = session_dir(session_id) / "report.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def round_dir(session_id: str, round_no: int) -> Path:
    path = session_dir(session_id) / f"round-{int(round_no)}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """Newest sessions first, as summary rows for the panel's history list."""
    root = interviews_root()
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            session = load_session(entry.name)
        except ValueError:
            continue
        if not session:
            continue
        questions = session.get("questions") or []
        rows.append(
            {
                "id": session.get("id") or entry.name,
                "title": session.get("title") or "",
                "created_at": session.get("created_at") or 0,
                "updated_at": session.get("updated_at") or 0,
                "respondents": len(session.get("respondents") or []),
                "questions": len(questions),
                "rounds": max((int(q.get("round") or 1) for q in questions), default=1),
                "cities": session.get("cities") or [],
            }
        )
    rows.sort(key=lambda row: row.get("updated_at") or 0, reverse=True)
    return rows[: max(1, int(limit))]


def delete_session(session_id: str) -> bool:
    import shutil

    target = session_dir(session_id)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


# ---------------------------------------------------------------------------
# Session <-> dataclass conversion
# ---------------------------------------------------------------------------


def session_questions(session: dict[str, Any]) -> list[Question]:
    return [Question.from_dict(item) for item in (session.get("questions") or [])]


def session_respondents(session: dict[str, Any]) -> list[Respondent]:
    return [Respondent.from_dict(item) for item in (session.get("respondents") or [])]


def session_transcripts(session: dict[str, Any]) -> list[Transcript]:
    """Transcripts in the respondents' declared order.

    Order matters for the document: the answers section should read in the
    order the user picked people, not in whatever order the dict happens to
    iterate or the threads happened to finish.
    """
    stored = session.get("transcripts") or {}
    out: list[Transcript] = []
    for respondent in session_respondents(session):
        payload = stored.get(respondent.uid)
        if payload is None:
            continue
        out.append(Transcript.from_dict(payload))
    return out


__all__ = [
    "INTERVIEWS_DIRNAME",
    "delete_session",
    "interviews_root",
    "list_sessions",
    "load_report",
    "load_session",
    "new_session_id",
    "round_dir",
    "save_report",
    "save_session",
    "session_dir",
    "session_questions",
    "session_respondents",
    "session_transcripts",
]
