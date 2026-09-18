"""Persona layer — turn a real person into a GAWorld resident.

Given a **name** or a **URL**, this package searches the open web, reads what
came back, and distils it into two artefacts:

1. a :class:`~gaworld.persona.distill.PersonaProfile` — the fields Agent Studio
   needs to seed a resident (identity, nine state variables, Big Five) *plus*
   the thinking framework behind the person (mental models, decision
   heuristics, expression DNA, anti-patterns, honest boundaries);
2. a ``SKILL.md`` in the shape the ``nuwa`` skill produces, so the same
   distillation can be loaded as a perspective outside GAWorld.

The method is borrowed from ``nuwa`` (research by facet → structured synthesis
→ explicit limits) and the sourcing discipline from
:mod:`gaworld.city.knowledge`: **the model may only use what the search
returned**. A confident invention about a real person is worse than an empty
field, because every downstream channel — prompts, interviews, reports — would
treat it as fact.

Entry points
------------

``gaworld.persona.research.research``   name or URL → :class:`Dossier`
``gaworld.persona.distill.distill``     dossier → :class:`PersonaProfile`
``save`` / ``load`` / ``list_personas``   the on-disk archive
``skill_markdown`` / ``profile_block`` / ``agent_payload``   renderers

The two pipeline functions are **not** re-exported here on purpose: they share
their names with their modules, so ``from gaworld.persona import research``
would hand a caller the function where it asked for the module. Import them
from their own module and the ambiguity disappears.
"""

from __future__ import annotations

from gaworld.persona.distill import Heuristic, MentalModel, PersonaProfile, VoiceDNA
from gaworld.persona.render import agent_payload, profile_block, skill_markdown
from gaworld.persona.research import Document, Dossier, is_url
from gaworld.persona.store import (
    install_skill,
    list_personas,
    load,
    persona_dir,
    persona_root,
    save,
)

__all__ = [
    "Document",
    "Dossier",
    "Heuristic",
    "MentalModel",
    "PersonaProfile",
    "VoiceDNA",
    "agent_payload",
    "install_skill",
    "is_url",
    "list_personas",
    "load",
    "persona_dir",
    "persona_root",
    "profile_block",
    "save",
    "skill_markdown",
]
