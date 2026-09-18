"""The persona archive on disk.

``output/personas/<slug>/``
    ``persona.json``  the structured profile (what the panel re-opens)
    ``research.md``   the raw material, verbatim, with every source URL
    ``SKILL.md``      the ``nuwa``-shaped perspective skill

The research file is kept because the persona is a *claim about a real person*:
when somebody later asks "where did 'risk_preference 0.8' come from", the
answer has to be a URL, not a model's recollection. It is also what makes a
re-distillation auditable — same sources, different summary, visible diff.

Nothing here is loaded by the simulator. The archive is authoring state; what
the simulation reads is the resident that was deployed out of it.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.persona.distill import PersonaProfile
from gaworld.persona.render import skill_markdown
from gaworld.persona.research import Dossier

_LOG = get_logger("gaworld.persona.store")

#: Overridable so tests (and a relocated output dir) do not write into the repo.
PERSONA_DIRNAME = os.path.join("output", "personas")


def persona_root() -> Path:
    """``<repo>/output/personas``, honouring ``GAWORLD_PERSONA_DIR``."""
    override = os.environ.get("GAWORLD_PERSONA_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    return here.parents[2] / PERSONA_DIRNAME


def persona_dir(slug: str) -> Path:
    slug = str(slug or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise ValueError(f"invalid persona slug: {slug!r}")
    return persona_root() / slug


def save(profile: PersonaProfile, dossier: Dossier | None = None) -> Path:
    """Write the three files and return the directory."""
    target = persona_dir(profile.slug)
    target.mkdir(parents=True, exist_ok=True)
    (target / "persona.json").write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (target / "SKILL.md").write_text(skill_markdown(profile), encoding="utf-8")
    if dossier is not None:
        (target / "research.md").write_text(dossier.to_markdown(), encoding="utf-8")
    _LOG.info("persona saved: %s", target)
    return target


def load(slug: str) -> PersonaProfile | None:
    path = persona_dir(slug) / "persona.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning("unreadable persona at %s: %s", path, exc)
        return None
    return PersonaProfile.from_dict(data)


def list_personas() -> list[dict[str, Any]]:
    """Index rows for the panel, newest first."""
    root = persona_root()
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        profile = load(child.name)
        if profile is None:
            continue
        rows.append(
            {
                "slug": child.name,
                "name": profile.name,
                "summary": profile.summary,
                "confidence": profile.confidence,
                "mental_models": len(profile.mental_models),
                "built_at": profile.built_at,
                "agent_id": profile.agent_id,
            }
        )
    rows.sort(key=lambda row: row.get("built_at") or "", reverse=True)
    return rows


def delete(slug: str) -> bool:
    target = persona_dir(slug)
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def skills_root() -> Path:
    """Where an installed perspective skill goes — ``~/.claude/skills``."""
    override = os.environ.get("GAWORLD_SKILLS_DIR")
    return Path(override) if override else Path.home() / ".claude" / "skills"


def install_skill(slug: str, *, overwrite: bool = False) -> dict[str, Any]:
    """Copy this persona's ``SKILL.md`` into the user's skills directory.

    Deliberately a separate, explicitly-triggered step rather than part of
    :func:`save`: distilling writes inside the repo's ``output/``, while this
    writes into the user's home and changes what their assistant loads in every
    other project. Refuses to overwrite unless asked.
    """
    source = persona_dir(slug) / "SKILL.md"
    if not source.exists():
        raise FileNotFoundError(f"persona {slug!r} has no SKILL.md")
    target_dir = skills_root() / f"{slug}-perspective"
    target = target_dir / "SKILL.md"
    if target.exists() and not overwrite:
        return {"installed": False, "path": str(target), "reason": "exists"}
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    _LOG.info("persona skill installed: %s", target)
    return {"installed": True, "path": str(target)}
