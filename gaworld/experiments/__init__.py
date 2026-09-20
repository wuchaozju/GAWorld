"""Prompt-design experiments run on GAWorld residents.

Implements the demand-estimation study of Gui & Toubia (2025),
*The Challenge of Using LLMs to Simulate Human Behavior: A Causal
Inference Perspective* (arXiv:2312.15524), plus two agent-based arms
that GAWorld can run and a stateless persona-prompting service cannot:
the pre-treatment covariates come from the resident's own world state,
so they are invariant to the randomized price by construction rather
than by asking the model to hold them fixed.

Entry point: ``python -m gaworld.experiments``.
"""

from __future__ import annotations

from gaworld.experiments.analysis import (  # noqa: F401 — re-export
    demand_curve,
    render_markdown,
    summarize,
)
from gaworld.experiments.arms import ARMS, build_prompt  # noqa: F401
from gaworld.experiments.runner import RunSpec, build_cells, run  # noqa: F401
from gaworld.experiments.stimulus import (  # noqa: F401
    RELATIVE_PRICE_GRID,
    Product,
    Treatment,
    load_catalog,
    price_grid,
)
from gaworld.experiments.subjects import Subject, WorldContext, load_subjects, world_context  # noqa: F401

__all__ = [
    "ARMS",
    "RELATIVE_PRICE_GRID",
    "Product",
    "RunSpec",
    "Subject",
    "Treatment",
    "WorldContext",
    "build_cells",
    "build_prompt",
    "demand_curve",
    "load_catalog",
    "load_subjects",
    "price_grid",
    "render_markdown",
    "run",
    "summarize",
    "world_context",
]
