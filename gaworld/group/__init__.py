"""Group-level ("cohort") simulation — the coarse tier of GAWorld.

The individual pipeline runs a full 12-stage cognition step per agent per
tick, which is the right fidelity for tens of agents and hopeless for
hundreds. This package adds a second, coarser tier so a 500-person town can
be simulated at a cost that does not scale with the population.

The design (see ``docs/GROUP_AGENT_DESIGN.md`` §2-3, path **B+**) is *not*
"average everyone into a representative agent" — that approach has two
independent published failure results against it (Kirman 1992 on aggregation,
Bisbee et al. 2024 on tail collapse in LLM survey simulation). Instead:

* the population is partitioned into **cohorts** — cells in attribute space
  that carry their own state, dispersion, memory and decisions;
* a cohort's day costs **one LLM call**, reusing the shape of
  ``gaworld.sim._fastforward.simulate_agent_day``;
* dispersion travels *with* the decision, so a cohort prompt says "about 30%
  of this group is under real stress", never just the mean;
* a budgeted set of individuals is **materialised** each day and run at full
  individual fidelity — focal agents the researcher named, tail agents the
  cohort mean cannot represent, and a random audit sample whose residual
  measures how wrong the approximation currently is.

Layering, and the one rule that matters: **the individual tier is not
touched.** Group mode is a parallel driver, not a modification of
``run_simulation``. The 12 stages are closures over ``run_simulation``'s
locals and cannot be reused from outside, so trying to thread cohorts through
the tick loop would mean rewriting it; going through the fast-forward channel
instead keeps individual runs bit-identical.
"""

from __future__ import annotations

from gaworld.group.cohort import (
    Cohort,
    CohortKey,
    apply_cohort_state_changes,
    cohort_summary,
    partition_cohorts,
    refresh_cohort_statistics,
)
from gaworld.group.materialize import (
    MaterializationPlan,
    apply_individual_deltas_to_cohort,
    select_materialized,
)

__all__ = [
    "Cohort",
    "CohortKey",
    "MaterializationPlan",
    "apply_cohort_state_changes",
    "apply_individual_deltas_to_cohort",
    "cohort_summary",
    "partition_cohorts",
    "refresh_cohort_statistics",
    "select_materialized",
]
