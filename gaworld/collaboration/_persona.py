from __future__ import annotations

from collections.abc import Iterable
from typing import Any


_PROFILE_TEXT_LIMIT = 600
_EXPERTISE_LIMIT = 6
# `job_label` falls back to "other" for most residents, and a bare
# placeholder must not be treated as a real area of expertise.
_GENERIC_TERMS = {"other", "未知", "无", "none"}


def _unique(values: Iterable[Any]) -> list[str]:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def persona(detail: dict[str, Any] | None) -> dict[str, Any]:
    """The traits that should make this member act unlike the others.

    Collaboration prompts used to carry only the task and an assigned
    role, so an economics teacher and a courier produced interchangeable
    deliverables — the individual profile never reached the model. This
    block is what every collaboration call attaches to give the member a
    professional lens of their own.
    """
    detail = detail or {}
    capabilities = detail.get("capabilities") or {}
    growth = detail.get("growth") or {}
    private_skills = detail.get("private_skills") or []
    growth_items = growth.get("items") or []
    expertise = sorted(
        (item for item in growth_items if isinstance(item, dict) and item.get("name")),
        key=lambda item: float(item.get("level") or 0.0),
        reverse=True,
    )[:_EXPERTISE_LIMIT]
    return {
        "identity": detail.get("identity", detail),
        "job_label": str(capabilities.get("job_label") or ""),
        "skills": _unique(
            [
                *(capabilities.get("skills") or []),
                *(
                    item.get("title")
                    for item in private_skills
                    if isinstance(item, dict)
                ),
            ]
        ),
        "interests": _unique(capabilities.get("interests") or []),
        "deliverables": _unique(capabilities.get("deliverables") or []),
        "expertise": [
            {
                "name": str(item.get("name")),
                "level": round(float(item.get("level") or 0.0), 2),
            }
            for item in expertise
        ],
        "profile_text": str(detail.get("profile_text") or "")[:_PROFILE_TEXT_LIMIT],
    }


def expertise_terms(detail: dict[str, Any] | None) -> list[str]:
    """Vocabulary describing what this member is actually good at."""
    block = persona(detail)
    terms = _unique(
        [
            block["job_label"],
            *block["skills"],
            *block["interests"],
            *block["deliverables"],
            *(item["name"] for item in block["expertise"]),
        ]
    )
    return [term for term in terms if len(term) >= 2 and term.lower() not in _GENERIC_TERMS]


def _grams(text: Any) -> set[str]:
    clean = "".join(char for char in str(text or "").lower() if char.isalnum())
    return {clean[index : index + 2] for index in range(len(clean) - 1)}


def match_score(title: str, terms: Iterable[str]) -> int:
    """Count expertise terms overlapping ``title`` by at least two characters.

    Chinese skill names rarely appear verbatim in a step title — a member
    skilled in "经济学分析" is the right author for "分析房价走势" — so exact
    substring matching finds almost nothing and every step would look like
    a mismatch.
    """
    target = _grams(title)
    if not target:
        return 0
    return sum(1 for term in terms if _grams(term) & target)
