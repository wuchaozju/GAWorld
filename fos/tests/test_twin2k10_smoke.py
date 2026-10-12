# This file checks the twin2k10 study's smoke-test grid: the tiny live
# pre-launch run (--smoke) must put exactly one model and one persona on
# every one of the 19 experiment arms in both blinding arms — enough to
# exercise every question kind through the real execution pipeline, yet
# small enough to finish in minutes, and always in its own T2K10-SMOKE-
# <stamp> run folder so the production grid is never polluted.
#
# TASK-2152 (implement role): one added test for the pure smoke filter
# in cells.py. All offline: pure enumeration, no network, no models.

import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import cells, config  # noqa: E402


def test_smoke_grid_is_one_model_one_persona_all_19_arms_both_blindings() -> None:
    """The --smoke filter: 1 model x 1 persona x 19 arms x 2 blindings."""
    grid = cells.smoke_cells()
    models = {cell[0] for cell in grid}
    personas = {cell[1] for cell in grid}
    arms = {(cell[2], cell[3]) for cell in grid}
    blindings = {cell[4] for cell in grid}
    assert models == {config.SMOKE_MODEL}, (
        "the smoke run must use exactly the one smallest study model"
    )
    assert personas == {config.SMOKE_PERSONA_ID}, (
        "the smoke run must answer exactly one persona"
    )
    assert len(arms) == 19, "the smoke run must cover all 19 experiment arms"
    assert blindings == {"blinded", "unblinded"}, (
        "the smoke run must cover both blinding arms"
    )
