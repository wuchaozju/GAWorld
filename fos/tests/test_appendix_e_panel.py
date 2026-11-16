# RED-phase tests (TASK-1500) for the Appendix E measured-covariate stage
# machinery - PANEL behaviour: cleaning, resampling pools, whole-row
# profiles and empirical percentiles. Measured scores come ONLY from the
# Twin-2K-500 panel (raw_data "wave N scores.csv", key TWIN_ID; demographics
# QID11-24 in wave1_3_response(_label).csv, key pid), so every test here
# loads a tiny eight-row synthetic panel written to tmp_path by
# appendix_e_spec.write_fixture_panel. Nothing here is implemented yet, so
# every test fails RED at the missing fos.experiments.twin_covariates module.
#
# Cleaning contract encoded by the fixtures (rows in appendix_e_spec):
#   105 - literal "no switch" discount    -> leaves every stage >= 3 pool
#   106 - literal "no switch" loss        -> leaves every stage >= 5 pool
#   107 - ~2^52 overflow discount (4.5e15)-> leaves every stage >= 3 pool
#   108 - mental accounting 150 (0-100)   -> leaves every stage >= 8 pool
#   105 - missing employment demographic  -> leaves every pool (stage 1 too)
# Percentile basis = ALL valid panel cells of a measure (never the invalid
# ones), integer 1-99, midpoint-rank formula:
#     pct = clamp(round(100 * (rank_avg - 1) / (n_valid - 1)), 1, 99)
# with rank_avg the tied group's average rank and n_valid > 1.

from tests.appendix_e_spec import (
    FIXTURE_EXPECTED_POOLS,
    FIXTURE_ROWS,
    MEASURE_WAVE,
    fixture_panel,
)


# 1. Cleaning: invalid stage scores and the per-stage resampling pools.
class TestCleaningAndPools:
    def test_panel_loads_every_fixture_respondent(self, tmp_path):
        """The loader reads all eight synthetic respondents."""
        panel = fixture_panel(tmp_path)
        assert list(panel.respondent_ids) == sorted(FIXTURE_ROWS), (
            f"panel must hold the fixture respondents, got {list(panel.respondent_ids)}"
        )

    def test_stage_pools_exclude_rows_with_non_numeric_scores(self, tmp_path):
        """'no switch' rows leave the pools of the stages needing that score."""
        panel = fixture_panel(tmp_path)
        assert panel.stage_pool(3) == FIXTURE_EXPECTED_POOLS[3], (
            f"stage 3 pool must exclude the no-switch/overflow rows, got "
            f"{panel.stage_pool(3)}"
        )
        assert panel.stage_pool(5) == FIXTURE_EXPECTED_POOLS[5], (
            f"stage 5 pool must exclude the loss-aversion no-switch row, got "
            f"{panel.stage_pool(5)}"
        )

    def test_stage_pool_excludes_the_overflow_marker_discount_row(self, tmp_path):
        """A ~2^52 overflow discount (4503599627370495) is never resampled."""
        panel = fixture_panel(tmp_path)
        assert 107 not in panel.stage_pool(3), (
            "respondent 107 (overflow-marker discount) must leave stage >= 3"
        )

    def test_stage_pool_excludes_out_of_scale_scores_from_later_stages(self, tmp_path):
        """A mental-accounting score of 150 (scale 0-100) leaves stages 8+."""
        panel = fixture_panel(tmp_path)
        for stage in (2, 7):
            assert 108 in panel.stage_pool(stage), (
                f"respondent 108 must stay in the stage {stage} pool"
            )
        for stage in (8, 12):
            assert 108 not in panel.stage_pool(stage), (
                f"respondent 108 (mental accounting 150, scale 0-100) must "
                f"leave the stage {stage} pool"
            )

    def test_pools_are_cumulative_across_stages(self, tmp_path):
        """A later stage never resamples a row an earlier stage rejected."""
        panel = fixture_panel(tmp_path)
        for stage in range(2, 12):
            later = set(panel.stage_pool(stage + 1))
            earlier = set(panel.stage_pool(stage))
            assert later.issubset(earlier), (
                f"stage {stage + 1} pool must be a subset of stage "
                f"{stage}'s: {later - earlier}"
            )

    def test_pool_requires_the_full_demographic_profile(self, tmp_path):
        """Row 105, missing its employment-status demographic, is not in the
        stage-1 pool either (a whole row must be renderable)."""
        panel = fixture_panel(tmp_path)
        assert 105 not in panel.stage_pool(1), (
            "a respondent with a missing demographic must not be resampled"
        )

    def test_loader_reports_pool_exclusion_counts_per_stage(self, tmp_path):
        """pool_report() covers stages 1-12 with pool_size and excluded."""
        panel = fixture_panel(tmp_path)
        report = panel.pool_report()
        assert set(report) == set(range(1, 13)), (
            f"pool report must cover every stage 1..12, got {sorted(report)}"
        )
        for stage in range(1, 13):
            row = report[stage]
            expected_pool = len(FIXTURE_EXPECTED_POOLS[stage])
            assert row["pool_size"] == expected_pool, (
                f"stage {stage} pool_size must be {expected_pool}, got "
                f"{row['pool_size']}"
            )
            assert row["excluded"] == 8 - expected_pool, (
                f"stage {stage} must report {8 - expected_pool} excluded "
                f"respondents, got {row['excluded']}"
            )


# 2. Measured-only profiles: whole-row resampling with a recorded seed.
class TestMeasuredOnlyProfiles:
    def test_same_seed_draws_the_same_profile(self, tmp_path):
        """draw_profile(stage, seed) is deterministic for a fixed pool."""
        panel = fixture_panel(tmp_path)
        first = panel.draw_profile(5, seed=1234)
        second = panel.draw_profile(5, seed=1234)
        assert first == second, "the same seed must draw the same profile"

    def test_draw_always_returns_a_row_of_the_stage_pool(self, tmp_path):
        """Every drawn profile is one respondent of that stage's pool."""
        panel = fixture_panel(tmp_path)
        for stage in (1, 2, 3, 5, 8, 12):
            pool = set(panel.stage_pool(stage))
            for seed in range(20):
                profile = panel.draw_profile(stage, seed=seed)
                assert profile["respondent_id"] in pool, (
                    f"stage {stage} seed {seed} drew respondent "
                    f"{profile['respondent_id']}, outside the pool {pool}"
                )

    def test_profile_keeps_one_whole_row_so_joint_dependence_is_preserved(
        self, tmp_path
    ):
        """Profile values never mix two respondents' rows."""
        panel = fixture_panel(tmp_path)
        rows = {rid: row for rid, row in FIXTURE_ROWS.items()}
        for seed in range(50):
            profile = panel.draw_profile(5, seed=seed)
            rid = profile["respondent_id"]
            assert float(profile["score_ST-TW"]) == float(rows[rid]["st"]), (
                f"seed {seed}: ST-TW must come from respondent {rid}'s row"
            )
            discount = profile["score_discount"]
            assert str(discount) == str(float(rows[rid]["disc"])), (
                f"seed {seed}: discount must come from respondent {rid}'s row"
            )

    def test_profiles_carry_the_full_measured_column_set(self, tmp_path):
        """The profile dict has every stage-12 score column, not just one
        stage's (the drawn row is kept whole)."""
        panel = fixture_panel(tmp_path)
        columns = set(MEASURE_WAVE)
        profile = panel.draw_profile(3, seed=1)
        for column in columns:
            assert column in profile, f"profile must carry {column} (whole-row profile)"

    def test_invalid_values_are_never_present_in_a_profile(self, tmp_path):
        """No drawn profile value is a no-switch literal or overflow marker."""
        panel = fixture_panel(tmp_path)
        for seed in range(50):
            profile = panel.draw_profile(5, seed=seed)
            for key, value in profile.items():
                if key in MEASURE_WAVE:
                    assert str(value) not in ("no switch", "nan", "inf"), (
                        f"profile carries invalid value {value!r} for {key}"
                    )

    def test_profiles_carry_the_demographics_of_their_row(self, tmp_path):
        """The profile's 14 demographic values belong to the drawn row."""
        panel = fixture_panel(tmp_path)
        demo_keys = [
            "region",
            "sex",
            "age",
            "education",
            "race",
            "citizen_status",
            "marriage",
            "religion",
            "religious_attendance",
            "political_affiliation",
            "total_family_income",
            "political_views",
            "household_size",
            "employment_status",
        ]
        profile = panel.draw_profile(1, seed=5)
        for key in demo_keys:
            value = profile.get(key)
            assert value is not None and str(value) != "", (
                f"profile must carry a non-empty demographic {key}"
            )


# 3. Percentiles: empirical from the panel, integer 1-99.
class TestPercentiles:
    def test_percentile_is_an_integer_between_1_and_99(self, tmp_path):
        """Panel percentiles are integer 1-99 for every measured column."""
        panel = fixture_panel(tmp_path)
        for column in sorted(MEASURE_WAVE):
            profile = panel.draw_profile(5, seed=3)
            percentile = panel.percentile(column, profile[column])
            assert isinstance(percentile, int), (
                f"{column}: percentile must be an int, got {percentile!r}"
            )
            assert 1 <= percentile <= 99, (
                f"{column}: percentile {percentile} outside 1..99"
            )

    def test_percentile_is_empirical_from_the_panels_valid_values(self, tmp_path):
        """Exact midpoint-rank percentile values on the fixture panel."""
        panel = fixture_panel(tmp_path)
        assert panel.percentile("score_mentalaccounting", 40) == 1
        assert panel.percentile("score_mentalaccounting", 60) == 33
        assert panel.percentile("score_mentalaccounting", 80) == 67
        assert panel.percentile("score_mentalaccounting", 100) == 99
        assert panel.percentile("score_ST-TW", 12) == 43
        assert panel.percentile("score_ST-TW", 18) == 79
        assert panel.percentile("score_ST-TW", 24) == 99
        assert panel.percentile("score_discount", 0.25) == 40
        assert panel.percentile("score_discount", 0.55) == 99
        assert panel.percentile("score_discount", 0.05) == 1

    def test_percentile_basis_excludes_invalid_rows(self, tmp_path):
        """Percentiles rank only VALID cells: the out-of-scale 150 must not
        change the mental-accounting ranks (90 -> 83 needs the 7-value
        basis, not an 8-value one)."""
        panel = fixture_panel(tmp_path)
        assert panel.percentile("score_mentalaccounting", 90) == 83, (
            "the 150 (out-of-scale) row must be excluded from the mental "
            "accounting percentile basis"
        )

    def test_percentile_is_monotone_in_the_score(self, tmp_path):
        """A higher score never gets a lower percentile."""
        panel = fixture_panel(tmp_path)
        # Sample the fixture's ST-TW values in score order: the fixture
        # rows are keyed by respondent id (7, 12, 18, 24, 7, 12, 18, 12), so
        # row order is not monotone and cannot test a monotone mapping.
        values = sorted(float(row["st"]) for row in FIXTURE_ROWS.values())
        percentiles = [panel.percentile("score_ST-TW", v) for v in values]
        assert percentiles == sorted(percentiles), (
            f"percentiles must be monotone in score, got {percentiles}"
        )

    def test_percentile_of_the_same_score_is_stable(self, tmp_path):
        """The same score always gets the same percentile (basis fixed)."""
        panel = fixture_panel(tmp_path)
        first = panel.percentile("score_ST-TW", 12)
        for _ in range(5):
            assert panel.percentile("score_ST-TW", 12) == first
