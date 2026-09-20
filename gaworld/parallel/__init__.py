"""Parallel worlds: run the same population under N different event histories.

The simulator has always been able to answer "what if this event had not
happened?" through the ``compare-event`` CLI, which forks exactly two runs —
one with an event, one without — and diffs their final state. That is the
degenerate case of a more useful question: *given the same city, the same
residents and the same seed, how far apart do histories drift when you change
what happens to them?*

This package generalises the fork:

* **N worlds, not two.** Every world carries its own list of events, so a
  single experiment can hold a baseline, a mild intervention, a severe one and
  a placebo, all sharing one trunk.
* **Worlds may differ by config, not only by events.** A world can also patch
  the simulation config (tax rates, environment knobs), which is how you model
  a policy rather than an incident.
* **Divergence over time, not only at the end.** ``analysis`` reconstructs the
  per-step metric trajectory of each world and measures the distance from the
  baseline at every step, so the answer to "when did these histories split?"
  is a number, not an impression.

Layout: :mod:`spec` normalises and validates an experiment; :mod:`runner`
forks the worlds as subprocesses and tracks their progress; :mod:`analysis`
turns the finished state artifacts into a comparison report. The dashboard
delegate in ``gaworld.apps.parallel_worlds_api`` wraps all three in a job so
the console can drive them.
"""

from gaworld.parallel.analysis import (
    build_report,
    read_state_series,
)
from gaworld.parallel.runner import (
    ExperimentRunner,
    load_manifest,
    prepare_experiment,
)
from gaworld.parallel.spec import (
    ExperimentSpec,
    WorldSpec,
    normalize_experiment,
    world_overrides,
)

__all__ = [
    "ExperimentRunner",
    "ExperimentSpec",
    "WorldSpec",
    "build_report",
    "load_manifest",
    "normalize_experiment",
    "prepare_experiment",
    "read_state_series",
    "world_overrides",
]
