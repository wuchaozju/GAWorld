"""Parameterised synthetic-population generation for GAWorld.

Turns a small set of panel-level knobs (population size, age pyramid,
employment rate, income Gini, …) into a full cast of agents in exactly the
format the simulator already consumes: a state CSV shaped like
``data/hangzhou_agents_state_init.csv`` plus a profile Markdown file shaped
like ``data/hangzhou_profiles_with_names.md``. Nothing in ``build_agent``
has to change.

The pipeline is:

``schema``   normalise the spec, apply a preset, flag infeasible knob combos
``synth``    IPF-fit a joint attribute table to the requested marginals, then
             sample individuals and their downstream attributes from it
``network``  build households, workplaces and a homophily/geography social
             graph, emitted as ``relationships`` records
``report``   validate the result and produce the panel's review charts
``writer``   serialise to state CSV + profile Markdown + a run manifest

See ``docs/GROUP_AGENT_DESIGN.md`` §4 for the design rationale.
"""

from __future__ import annotations

from gaworld.population.schema import (
    AGE_BANDS,
    EDUCATION_LEVELS,
    EMPLOYMENT_STATUSES,
    INDUSTRIES,
    PRESETS,
    STATE_VAR_KEYS,
    Issue,
    PopulationSpec,
    check_feasibility,
    normalize_spec,
)

__all__ = [
    "AGE_BANDS",
    "EDUCATION_LEVELS",
    "EMPLOYMENT_STATUSES",
    "INDUSTRIES",
    "PRESETS",
    "STATE_VAR_KEYS",
    "Issue",
    "PopulationSpec",
    "check_feasibility",
    "normalize_spec",
]
