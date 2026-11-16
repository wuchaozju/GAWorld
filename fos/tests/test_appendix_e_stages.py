# RED-phase tests (TASK-1500) for the Appendix E measured-covariate stage
# machinery of the Gui & Toubia (2025) unblinding study - stage TABLES and
# their integration into the depth/CLI layers. The paper's Table E.1 adds
# covariates to the Prompt 12 profile in 12 cumulative stages (stage 1 = the
# 14 demographics, then one behavioural/psychological measure chunk per
# stage up to the Big Five at stage 12; cumulative covariate counts 14, 15,
# 17, ... 30). Nothing here is implemented yet, so every test fails RED
# unless the ground-truth constants below already exist.
#
# Ground-truth tables and the tiny synthetic panel live in appendix_e_spec.py
# (locked with these tests). This file's classes:
#   TestStageCovariateCounts    - Table E.1's 12 counts in the randomization
#       module, covariate_count_for_depth accepting stage depth names, with
#       depths 1-2 unchanged (none -> 0, demographics -> 11).
#   TestStageMeasureColumns     - which measured score column each stage adds
#       and which wave file it lives in (wave-1 conscientiousness!).
#   TestSweepIntegration        - the sweep CLI and RandomizationDesign accept
#       the new stage depth names stage2..stage12 alongside none/demographics.

from pathlib import Path

import pytest

from fos.experiments import personas as personas_mod
from fos.experiments import randomization as randomization_mod

from tests.appendix_e_spec import (
    DEMOGRAPHIC_DISPLAY_LABELS,
    MEASURE_WAVE,
    STAGE_ADDED_COLUMNS,
    TABLE_E1_COUNTS,
    _require_attr,
    _require_module,
    load_script,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SWEEP_SCRIPT_PATH = REPO_ROOT / "scripts" / "unblinding_sweep.py"


def _stage_counts() -> dict:
    """Probe randomization.STAGE_COVARIATE_COUNTS or fail RED."""
    return _require_attr(randomization_mod, "STAGE_COVARIATE_COUNTS")


# 1. Table E.1's 12 cumulative covariate counts.
class TestStageCovariateCounts:
    def test_stage_count_table_has_the_12_table_e1_cumulative_counts(self):
        """STAGE_COVARIATE_COUNTS pins Table E.1's counts 14, 15, 17 .. 30."""
        counts = _stage_counts()
        assert counts == TABLE_E1_COUNTS, (
            f"Table E.1 counts must be {TABLE_E1_COUNTS}, got {counts}"
        )

    def test_stage_covariate_count_function_reports_each_table_e1_count(self):
        """stage_covariate_count(1..12) returns the cumulative counts."""
        fn = _require_attr(randomization_mod, "stage_covariate_count")
        for stage, expected in TABLE_E1_COUNTS.items():
            assert fn(stage) == expected, (
                f"stage {stage} must pin {expected} covariates, got {fn(stage)}"
            )

    def test_stage_covariate_count_rejects_unknown_stages(self):
        """Stages outside 1..12 must raise, never guess a budget."""
        fn = _require_attr(randomization_mod, "stage_covariate_count")
        for bad in (0, 13, -1, "3", None):
            with pytest.raises(ValueError):
                fn(bad)

    def test_stage_increments_match_the_prompt12_block_list(self):
        """Consecutive counts grow by Prompt 12's block sizes: 1, 2, then 1s."""
        increments = [TABLE_E1_COUNTS[s + 1] - TABLE_E1_COUNTS[s] for s in range(1, 12)]
        assert increments == [1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 5], (
            f"stage increments must match Prompt 12's block sizes, got {increments}"
        )

    def test_covariate_count_for_depth_accepts_the_stage_depth_names(self):
        """covariate_count_for_depth("stageN") returns Table E.1's count."""
        fn = randomization_mod.covariate_count_for_depth
        for stage in range(2, 13):
            try:
                actual = fn(f"stage{stage}")
            except ValueError as exc:
                pytest.fail(f"depth name stage{stage} not accepted: {exc}")
            assert actual == TABLE_E1_COUNTS[stage], (
                f"stage{stage} must pin {TABLE_E1_COUNTS[stage]} covariates, "
                f"got {actual}"
            )

    def test_covariate_count_for_depth_rejects_names_outside_the_ladder(self):
        """stage1 is not a depth name; stage13/stage0/stage are not in Table
        E.1 and must raise."""
        fn = randomization_mod.covariate_count_for_depth
        for bad in ("stage1", "stage13", "stage0", "stage"):
            with pytest.raises(ValueError):
                fn(bad)

    def test_depth_one_and_two_behaviour_is_unchanged(self):
        """none/demographics still count 0/11 (regression guard, green)."""
        assert randomization_mod.covariate_count_for_depth("none") == 0
        assert randomization_mod.covariate_count_for_depth("demographics") == 11

    def test_depth_two_renderer_is_unchanged(self):
        """render_persona_fields keeps the two-level behaviour: demographics
        renders the 11 canonical fields, none renders nothing (regression
        guard, green)."""
        persona = {
            field: index for index, field in enumerate(personas_mod.PERSONA_FIELDS)
        }
        rendered = personas_mod.render_persona_fields(persona, "demographics")
        assert len(rendered.splitlines()) == 11, (
            f"demographics tier must render the 11 fields, got {rendered!r}"
        )
        assert personas_mod.render_persona_fields(persona, "none") == ""


# 2. Which measured score columns each stage adds, and where they live.
class TestStageMeasureColumns:
    def test_twin_module_lists_the_score_column_each_stage_adds(self):
        """twin_covariates.STAGE_ADDED_COLUMNS matches Prompt 12's blocks."""
        twin = _require_module("fos.experiments.twin_covariates")
        columns = _require_attr(twin, "STAGE_ADDED_COLUMNS")
        assert columns == STAGE_ADDED_COLUMNS, (
            f"per-stage added columns must match Prompt 12's blocks, got {columns}"
        )

    def test_cumulative_column_count_matches_the_table_e1_covariate_count(self):
        """14 demographics + cumulative added columns == Table E.1's count."""
        twin = _require_module("fos.experiments.twin_covariates")
        columns = _require_attr(twin, "STAGE_ADDED_COLUMNS")
        for stage in range(2, 13):
            cumulative = sum(len(columns[s]) for s in range(2, stage + 1))
            assert 14 + cumulative == TABLE_E1_COUNTS[stage], (
                f"stage {stage}: 14 demographics + {cumulative} measured "
                f"columns must equal {TABLE_E1_COUNTS[stage]}"
            )

    def test_every_score_column_ships_in_the_wave_file_research_verified(self):
        """MEASURE_WAVE pins each column to its real wave file."""
        twin = _require_module("fos.experiments.twin_covariates")
        wave = _require_attr(twin, "MEASURE_WAVE")
        assert wave == MEASURE_WAVE, (
            f"measure->wave map must match RESULT-1496, got {wave}"
        )

    def test_conscientiousness_comes_from_wave_one_not_wave_two(self):
        """Prompt 12 uses the wave-1 Big Five conscientiousness, never the
        wave-2 0-8 'score_conscientiousness' column."""
        twin = _require_module("fos.experiments.twin_covariates")
        wave = _require_attr(twin, "MEASURE_WAVE")
        assert wave["score_conscientiousness"] == "wave 1 scores.csv", (
            f"conscientiousness must come from wave 1 (Prompt 12 'wave1 "
            f"score conscientiousness'), got {wave['score_conscientiousness']}"
        )

    def test_demographic_display_labels_match_prompt12_verbatim_order(self):
        """The renderer's 14 demographic bullets use Prompt 12's labels."""
        twin = _require_module("fos.experiments.twin_covariates")
        labels = _require_attr(twin, "DEMOGRAPHIC_DISPLAY_LABELS")
        assert labels == DEMOGRAPHIC_DISPLAY_LABELS, (
            f"demographic labels must match Prompt 12's verbatim order, got {labels}"
        )


# 3. Integration: sweep depth/CLI layers accept the stage levels.
class TestSweepIntegration:
    def test_sweep_cli_expands_single_stage_depths(self):
        """expand_depths accepts stage2..stage12 next to none/demographics."""
        script = load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        for stage in range(2, 13):
            try:
                names = script.expand_depths(f"stage{stage}")
            except ValueError as exc:
                pytest.fail(f"--persona-depth stage{stage} rejected: {exc}")
            assert names == [f"stage{stage}"], (
                f"expand_depths('stage{stage}') must return one depth name, got {names}"
            )

    def test_sweep_cli_expands_comma_lists_of_stage_depths(self):
        """Comma lists mix the new stage names with the existing two."""
        script = load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        try:
            names = script.expand_depths("none,stage3,demographics,stage12")
        except ValueError as exc:
            pytest.fail(f"comma list of stage depths rejected: {exc}")
        assert names == ["none", "stage3", "demographics", "stage12"], (
            f"comma list must keep its order, got {names}"
        )

    def test_sweep_cli_all_expands_to_the_full_stage_ladder(self):
        """'all' runs none, demographics and every stage2..stage12."""
        script = load_script(SWEEP_SCRIPT_PATH, "unblinding_sweep")
        try:
            names = script.expand_depths("all")
        except ValueError as exc:
            pytest.fail(f"--persona-depth all rejected: {exc}")
        assert names[:2] == ["none", "demographics"], (
            f"depths 1-2 must keep their places, got {names[:2]}"
        )
        expected_tail = [f"stage{s}" for s in range(2, 13)]
        assert names[2:] == expected_tail, (
            f"'all' must run the appendix stages in Table E.1 order, got {names[2:]}"
        )

    def test_design_accepts_stage_depths_and_round_trips_them(self):
        """RandomizationDesign stores stage depths and their counts."""
        counts = _stage_counts()
        design = randomization_mod.RandomizationDesign(
            variable="price",
            label="the price of the product",
            min_value=0.0,
            max_value=200.0,
            persona_depth="stage5",
            covariate_count=counts[5],
        )
        assert design.persona_depth == "stage5"
        rebuilt = randomization_mod.RandomizationDesign.from_json(design.to_json())
        assert rebuilt.persona_depth == "stage5"
        assert rebuilt.covariate_count == counts[5]

    def test_design_rejects_unknown_stage_depths(self):
        """Unknown stage names still raise at construction time."""
        for bad in ("stage1", "stage13", "stage0"):
            with pytest.raises(ValueError):
                randomization_mod.RandomizationDesign(
                    variable="price",
                    label="the price of the product",
                    min_value=0.0,
                    max_value=200.0,
                    persona_depth=bad,
                )
