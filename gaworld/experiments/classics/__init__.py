"""Classic experiment library: textbook paradigms with residents as subjects.

Six paradigms, each a two-condition contrast with a direction the
literature agrees on — framing (Tversky & Kahneman 1981), anchoring
(Jacowitz & Kahneman 1995), dictator vs ultimatum proposers (Forsythe et
al. 1994), ultimatum responders (Güth et al. 1982), the trust game with an
in-group partner (Berg et al. 1995; Balliet et al. 2014) and the public
goods game across returns (Isaac & Walker 1988). Every resident answers
every condition in separate stateless calls, so each contrast is paired
by person; the verdict reads its direction only (grade (c)).

Entry point: ``python -m gaworld.experiments.classics``. See
``docs/CLASSIC_EXPERIMENTS.md``.
"""

from __future__ import annotations

from gaworld.experiments.classics.analysis import (
    MIN_PAIRS,
    VERDICT_LABELS,
    analyze_paradigm,
    load_rows,
    render_markdown,
    summarize,
)
from gaworld.experiments.classics.paradigms import PARADIGMS, Item, Paradigm, build_prompt
from gaworld.experiments.classics.runner import ClassicSpec, build_cells, run

__all__ = [
    "MIN_PAIRS",
    "PARADIGMS",
    "VERDICT_LABELS",
    "ClassicSpec",
    "Item",
    "Paradigm",
    "analyze_paradigm",
    "build_cells",
    "build_prompt",
    "load_rows",
    "render_markdown",
    "run",
    "summarize",
]
