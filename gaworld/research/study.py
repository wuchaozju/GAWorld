"""A study: one plan carried through protocol, run, verdicts and report.

The object the copilot loop is built around. A plan is a document that can
be analysed any number of times; a study is one attempt to *do* it, with a
stage, a fixed protocol, the runs it produced and what they showed. Stages
are linear and every transition is written to disk before the next step
starts, so a study that dies mid-run is found at ``running`` with its
protocol intact rather than lost.

    protocol → approved → running → evaluated → reported
                                  ↘ error

``protocol`` is where copilot mode waits for a person. Autopilot skips the
wait only when the preflight passed; it never skips the preflight.

Studies live under ``output/research/studies/<id>/``: ``study.json`` for
the record and ``report.md`` for the document, beside the plan store rather
than inside any city's run root — same reasoning as plans.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gaworld.city.knowledge import _utcnow
from gaworld.logging_setup import get_logger
from gaworld.research import workbench
from gaworld.research.workbench import ResearchError

_LOG = get_logger("gaworld.research.study")

STAGES = ("protocol", "approved", "running", "evaluated", "reported", "error")
STUDIES_DIRNAME = "studies"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


@dataclass
class Study:
    id: str
    plan_id: str
    title: str
    language: str = "zh-CN"
    provider: str = ""
    created_at: str = ""
    updated_at: str = ""
    stage: str = "protocol"
    autopilot: bool = False
    #: Bumped by a reset, so a re-run writes a fresh experiment tree instead
    #: of overwriting the one the previous attempt left behind.
    attempt: int = 1
    protocol: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    interpretation: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    #: Rendered on the way to ``reported``; stored as ``report.md``, not in
    #: the JSON record.
    report_markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Study:
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in (data or {}).items() if key in known})

    def set_stage(self, stage: str, *, error: str = "") -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        self.stage = stage
        self.error = error
        self.updated_at = _utcnow()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def studies_root() -> Path:
    return workbench.plans_root() / STUDIES_DIRNAME


def new_study_id() -> str:
    return f"S{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def study_dir(study_id: str) -> Path:
    if not _SAFE_ID_RE.match(str(study_id or "")):
        raise ResearchError(f"非法的研究 id：{study_id!r}")
    return studies_root() / study_id


def new_study(
    plan: dict[str, Any],
    protocol: dict[str, Any],
    preflight: dict[str, Any],
    *,
    provider: str = "",
    autopilot: bool = False,
) -> Study:
    now = _utcnow()
    return Study(
        id=new_study_id(),
        plan_id=str(plan.get("id") or ""),
        title=str(protocol.get("title") or plan.get("title") or "研究"),
        language=str(plan.get("language") or "zh-CN"),
        provider=provider,
        created_at=now,
        updated_at=now,
        autopilot=bool(autopilot),
        protocol=protocol,
        preflight=preflight,
    )


def save_study(study: Study) -> Path:
    directory = study_dir(study.id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = study.to_dict()
    markdown = payload.pop("report_markdown", "")
    temp = directory / "study.json.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(directory / "study.json")
    report = directory / "report.md"
    if markdown:
        report.write_text(markdown, encoding="utf-8")
    elif report.exists():
        # A reset cleared the report; leaving the old file would resurrect it
        # on the next load.
        report.unlink()
    return directory


def load_study(study_id: str) -> Study | None:
    directory = study_dir(study_id)
    path = directory / "study.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _LOG.warning("unreadable study %s", path, exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    study = Study.from_dict(data)
    report = directory / "report.md"
    if report.exists():
        try:
            study.report_markdown = report.read_text(encoding="utf-8")
        except OSError:
            study.report_markdown = ""
    return study


def _summary(study: Study) -> dict[str, Any]:
    evaluation = study.evaluation or {}
    return {
        "id": study.id,
        "plan_id": study.plan_id,
        "title": study.title,
        "stage": study.stage,
        "autopilot": study.autopilot,
        "attempt": study.attempt,
        "created_at": study.created_at,
        "updated_at": study.updated_at,
        "hypotheses": len(study.protocol.get("hypotheses") or []),
        "conditions": len(study.protocol.get("conditions") or []),
        "seeds": len((study.protocol.get("validity") or {}).get("seeds") or []),
        "preflight_ok": bool((study.preflight or {}).get("ok")),
        "summary": evaluation.get("summary") or {},
        "error": study.error,
    }


def list_studies() -> list[dict[str, Any]]:
    """Newest first, without the bodies."""
    root = studies_root()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for directory in root.iterdir():
        if not directory.is_dir() or not _SAFE_ID_RE.match(directory.name):
            continue
        study = load_study(directory.name)
        if study is not None:
            out.append(_summary(study))
    out.sort(key=lambda item: item["created_at"], reverse=True)
    return out


def delete_study(study_id: str) -> bool:
    directory = study_dir(study_id)
    if not directory.exists():
        return False
    shutil.rmtree(directory)
    return True


__all__ = [
    "STAGES",
    "Study",
    "delete_study",
    "list_studies",
    "load_study",
    "new_study",
    "new_study_id",
    "save_study",
    "studies_root",
    "study_dir",
]
