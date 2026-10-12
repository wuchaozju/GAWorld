# RED-phase tests (TASK-1500) for the Appendix E measured-covariate stage
# machinery - RENDER format and real-dataset integration. A stage profile is
# ONE resampled Twin-2K-500 respondent row, kept whole so joint dependence
# survives; every rendered score and percentile is that row's measured value
# and the panel's empirical percentile - nothing model-invented, nothing
# invalid, ever. The block text follows Prompt 12 verbatim (RESULT-1474 §1):
# a "# Demographics:" bullet block first, then the measure block of every
# stage <= the requested stage in Table E.1 order, each "# ..." header with
# its "<note: ...>" scale/range line and, where the prompt prints them
# inline, the "{score} ({pct} percentile)" suffix.
#
# TestRenderPrompt12Format   - exact Prompt-12 line grammar on the fixture
#     panel (canonical stage-3 block pinned line by line), cumulative block
#     coverage, note scale/range texts, wave-1 conscientiousness, and
#     score/percentile consistency between profile and render.
# TestRealTwinDataset        - skip-guarded: loads the real 2,058-row panel
#     from /home/justin/work/datasets/Twin-2K-500, pins the documented pool
#     sizes after cleaning, and renders a 50-profile sample across all 12
#     stages with zero invalid values (RED until the loader exists).

import re
from pathlib import Path

from tests.appendix_e_spec import (
    DEMOGRAPHIC_DISPLAY_LABELS,
    MEASURE_WAVE,
    fixture_panel,
    _require_attr,
    _require_module,
)

DATASET_ROOT = Path("/home/justin/work/datasets/Twin-2K-500")
RAW_DATA = DATASET_ROOT / "raw_data"
DEMO_NUMERIC = (
    DATASET_ROOT / "question_catalog_and_human_response_csv" / "wave1_3_response.csv"
)
DEMO_LABEL = (
    DATASET_ROOT
    / "question_catalog_and_human_response_csv"
    / "wave1_3_response_label.csv"
)

# The header marker of each measure block, keyed by the stage that adds it.
STAGE_HEADERS = {
    2: "# Tightwad-Spendthrift:",
    3: "# Discount, Present Bias:",
    4: "# Risk aversion:",
    5: "# Loss aversion:",
    6: "# Financial Literacy:",
    7: "# Numeracy:",
    8: "# Mental Accounting:",
    9: "# Maximization:",
    10: "# Minimalism:",
    11: "# GREEN:",
    12: "# Big 5 Personality:",
}

# One scale/range phrase each Prompt-12 <note> must state (RESULT-1474 §1).
NOTE_FRAGMENTS = {
    2: ("ranges from 4 to 26", "difficulty spending"),
    3: (
        "implied rates computed from your time-value of money preferences",
        "departure from normative economic behavior",
    ),
    4: ("greater tendency for risk aversion", "sure-amount and lottery payout"),
    5: ("greater tendency for loss aversion", "sure-amount and a lottery payout"),
    6: ("ranges from 0 to 8", "general financial literacy"),
    7: ("ranges from 0 to 8", "numeracy"),
    8: ("ranges from 0 to 100 percent", "Thaler"),
    9: ("ranges from 1 to 5", "optimize rather than satisfice"),
    10: ("ranges from 1 to 5", "preference for minimalism"),
    11: ("ranges from 1 to 5", "affinity for environmentalism"),
    12: ("Openness reflects curiosity", "ranges from 1 to 5"),
}


# Expected text of row 103's stage-3 render, line by line (splitlines form):
# 14 demographics (Prompt 12 display labels, verbatim fixture texts), then
# the Tightwad-Spendthrift inline block and the Discount/Present-Bias
# header+note+bullets block, separated by single blank lines. Percentiles
# are the panel's midpoint-rank values: ST-TW 18 -> 79, discount 0.25 -> 40,
# present bias 0.3 -> 29.
_ST_103_NOTE = (
    "<note: The score ranges from 4 to 26. Lower scores (4-11) indicate "
    "difficulty spending money, while higher scores (19-26) indicate "
    "difficulty controlling spending.>"
)
_DISCOUNT_NOTE = (
    "<note: These are implied rates computed from your time-value of money "
    "preferences. Higher values of the discount rate imply greater "
    "impatience. Higher values of present bias imply greater departure from "
    "normative economic behavior.>"
)
EXPECTED_STAGE3_LINES_103 = [
    "# Demographics:",
    "- Geographic region: South (TX, OK, AR, LA, MS, AL, GA, FL, TN, KY, "
    "WV, VA, NC, SC)",
    "- Gender: Male",
    "- Age: 30-49",
    "- Education level: Bachelor's degree",
    "- Race: White",
    "- Citizen of the US: Yes",
    "- Marital status: Married",
    "- Religion: Catholic",
    "- Religious attendance: Once a week",
    "- Political affiliation: Democrat",
    "- Income: $75,000-$100,000",
    "- Political views: Liberal",
    "- Household size: 3",
    "- Employment status: Full-time employment",
    "",
    "# Tightwad-Spendthrift: 18 (79 percentile)",
    _ST_103_NOTE,
    "",
    "# Discount, Present Bias:",
    _DISCOUNT_NOTE,
    "- Discount: 0.25 (40 percentile)",
    "- Present Bias: 0.3 (29 percentile)",
]


def _render_module():
    """Import fos.experiments.twin_covariates (RED when missing)."""
    return _require_module("fos.experiments.twin_covariates")


def _render(panel, respondent_id, stage):
    """Render one fixture row at one stage through the real loader API."""
    twin = _render_module()
    render_stage_block = _require_attr(twin, "render_stage_block")
    profile = panel.profile_for(respondent_id)
    return render_stage_block(profile, stage)


def _measure_line_numbers(text: str) -> dict:
    """Map every measure header to its line index in a rendered block."""
    lines = text.splitlines()
    return {
        stage: next(
            index for index, line in enumerate(lines) if line.startswith(header)
        )
        for stage, header in STAGE_HEADERS.items()
        if any(line.startswith(header) for line in lines)
    }


def _score_value_text(text: str) -> str:
    """The measured score tokens of a render, for invalid-value scanning.

    Only the value cell of each measure line is returned (the token right
    before its " (NN percentile)" suffix). Display labels and verbatim
    Prompt-12 note prose are skipped: "Financial Literacy" (the stage-6
    header) and "general financial literacy" (the stage-6 note, pinned by
    a sibling test) legitimately contain the substring "nan".
    """
    tokens = []
    for line in text.splitlines():
        if not line.rstrip().endswith("percentile)"):
            continue
        token = line.rsplit(" (", 1)[0].rsplit(": ", 1)[-1]
        tokens.append(token)
    return " ".join(tokens)


# 1. Prompt-12 verbatim render grammar.
class TestRenderPrompt12Format:
    def test_canonical_stage3_render_is_prompt12_verbatim(self, tmp_path):
        """Row 103 at stage 3 renders EXACTLY the pinned line list."""
        panel = fixture_panel(tmp_path)
        text = _render(panel, 103, 3)
        assert text.splitlines() == EXPECTED_STAGE3_LINES_103, (
            f"stage-3 render of row 103 must match Prompt 12 verbatim:\n{text}"
        )

    def test_stage1_renders_the_demographic_block_only(self, tmp_path):
        """A stage-1 profile renders the 14 demographics and nothing else."""
        panel = fixture_panel(tmp_path)
        text = _render(panel, 103, 1)
        assert text.splitlines()[0] == "# Demographics:"
        assert len(text.splitlines()) == 15, (
            "stage 1 must render the demographics header plus 14 bullet "
            f"lines, got {len(text.splitlines())} lines"
        )
        for stage in STAGE_HEADERS:
            assert STAGE_HEADERS[stage] not in text, (
                f"stage-1 render must not contain the stage-{stage} block"
            )

    def test_demographic_bullets_cover_prompt12_labels_with_values(self, tmp_path):
        """The demographics block has 14 '- Display label: value' bullets in
        Prompt 12's order, with the values of the drawn row."""
        panel = fixture_panel(tmp_path)
        for rid in (101, 102, 104):
            text = _render(panel, rid, 1)
            lines = [line for line in text.splitlines() if line.startswith("- ")]
            assert len(lines) == 14, (
                f"row {rid}: demographics block must have 14 bullets, got {len(lines)}"
            )
            labels = [line[2:].split(":")[0] for line in lines]
            assert labels == DEMOGRAPHIC_DISPLAY_LABELS, (
                f"row {rid}: demographic labels must follow Prompt 12, got {labels}"
            )
            assert all(len(line[2:].split(":", 1)[1].strip()) > 0 for line in lines), (
                f"row {rid}: every demographic bullet must carry a value"
            )
            assert "percentile" not in "\n".join(lines[:14]), (
                "demographics never carry percentiles"
            )

    def test_blocks_accumulate_cumulatively_by_stage(self, tmp_path):
        """Stage s renders exactly the blocks of stages <= s, in E.1 order."""
        panel = fixture_panel(tmp_path)
        for stage in range(1, 13):
            text = _render(panel, 101, stage)
            present = set(_measure_line_numbers(text))
            expected = {s for s in STAGE_HEADERS if s <= stage}
            assert present == expected, (
                f"stage {stage} must show blocks {sorted(expected)} only, "
                f"got {sorted(present)}"
            )
            numbers = _measure_line_numbers(text)
            ordered = [numbers[s] for s in sorted(numbers)]
            assert ordered == sorted(ordered), (
                "measure blocks must follow Table E.1 order inside the text"
            )

    def test_each_measure_note_states_its_scale_range_and_direction(self, tmp_path):
        """Every Prompt-12 <note> carries its range/direction phrases."""
        panel = fixture_panel(tmp_path)
        text = _render(panel, 101, 12)
        for stage, fragments in NOTE_FRAGMENTS.items():
            assert STAGE_HEADERS[stage] in text, (
                f"stage-12 render missing the stage-{stage} block"
            )
        for stage, fragments in NOTE_FRAGMENTS.items():
            for fragment in fragments:
                assert fragment in text, f"stage-{stage} note must state {fragment!r}"

    def test_rendered_scores_and_percentiles_match_profile_and_panel(self, tmp_path):
        """Parse every measure line back: the score equals the profile's and
        the percentile equals panel.percentile(column, score)."""
        panel = fixture_panel(tmp_path)
        pattern = re.compile(
            r"^(?:# |\- )([\w\-]+(?: [\w\-]+)*): ([0-9.]+) \(([0-9]+) "
            r"percentile\)$"
        )
        for rid in (101, 102, 103, 104):
            profile = panel.profile_for(rid)
            text = _render(panel, rid, 12)
            parsed = 0
            for line in text.splitlines():
                match = pattern.match(line)
                if not match:
                    continue
                display, score_text, percentile_text = match.groups()
                if display not in _COLUMN_FOR_DISPLAY:
                    continue  # a demographics line whose value looks numeric
                parsed += 1
                column = _COLUMN_FOR_DISPLAY[display]
                assert float(score_text) == profile[column], (
                    f"row {rid}: rendered {column} score {score_text!r} must "
                    f"equal the profile's {profile[column]!r}"
                )
                assert int(percentile_text) == panel.percentile(
                    column, profile[column]
                ), (
                    f"row {rid}: rendered percentile of {column} must match "
                    f"the panel percentile"
                )
            assert parsed == len(MEASURE_WAVE), (
                f"row {rid}: expected {len(MEASURE_WAVE)} measure lines, "
                f"parsed {parsed}"
            )

    def test_conscientiousness_line_uses_wave_one_not_the_wave_two_decoy(
        self, tmp_path
    ):
        """Prompt 12's conscientiousness is the wave-1 Big Five score. Row
        103's wave-1 value is 3 (wave-2 decoy is 6), so the render must show
        'Conscientiousness: 3', never 6."""
        panel = fixture_panel(tmp_path)
        profile = panel.profile_for(103)
        assert profile["score_conscientiousness"] == 3.0, (
            f"wave-1 conscientiousness must be loaded (3.0), got "
            f"{profile['score_conscientiousness']}"
        )
        text = _render(panel, 103, 12)
        line = next(
            line
            for line in text.splitlines()
            if line.startswith("- Conscientiousness:")
        )
        assert line.startswith("- Conscientiousness: 3 ("), (
            f"conscientiousness must render the wave-1 value 3, got {line!r}"
        )

    def test_no_invalid_value_or_invented_number_ever_renders(self, tmp_path):
        """No rendered score/percentile VALUE is a no-switch/overflow/
        out-of-scale marker, for any stage and every pool row. Only the
        score tokens of the value cells are scanned (see
        _score_value_text): display labels and note prose are prose, and
        "Financial Literacy" / "general financial literacy" are mandated
        verbatim by the stage-6 pins."""
        panel = fixture_panel(tmp_path)
        for stage in range(1, 13):
            for rid in panel.stage_pool(stage):
                text = _render(panel, rid, stage)
                value_text = _score_value_text(text)
                for forbidden in ("no switch", "nan", "inf", "1e+", "4503599627370495"):
                    assert forbidden not in value_text, (
                        f"stage {stage} row {rid} renders invalid token {forbidden!r}"
                    )


# Which measure display label maps to which profile key.
_COLUMN_FOR_DISPLAY = {
    "Tightwad-Spendthrift": "score_ST-TW",
    "Discount": "score_discount",
    "Present Bias": "score_presentbias",
    "Risk aversion": "score_riskaversion",
    "Loss aversion": "score_lossaversion",
    "Financial Literacy": "score_finliteracy",
    "Numeracy": "score_numeracy",
    "Mental Accounting": "score_mentalaccounting",
    "Maximization": "score_maximization",
    "Minimalism": "score_minimalism",
    "GREEN": "score_GREEN",
    "Extraversion": "score_extraversion",
    "Agreeableness": "score_agreeableness",
    "Conscientiousness": "score_conscientiousness",
    "Openness": "score_openness",
    "Neuroticism": "score_neuroticism",
}


# 2. Real Twin-2K-500 dataset integration (skip-guarded).
class TestRealTwinDataset:
    def test_real_panel_loads_all_2058_respondents(self):
        """The loader reads the full 2,058-row panel from raw_data."""
        _skip_if_dataset_missing()
        panel = _load_real_panel()
        assert len(panel.respondent_ids) == 2058, (
            f"the Twin-2K-500 panel must hold 2,058 respondents, got "
            f"{len(panel.respondent_ids)}"
        )

    def test_real_stage_pools_match_the_documented_cleaning_counts(self):
        """After cleaning, pool sizes are 2058 (stages 1-2), 1767 (3), 1724
        (4) and 649 (stages 5-12): loss-aversion 'no switch' (~68% of rows)
        is the binding constraint from stage 5 on (RESULT-1496 §3)."""
        _skip_if_dataset_missing()
        panel = _load_real_panel()
        expected = {
            1: 2058,
            2: 2058,
            3: 1767,
            4: 1724,
            5: 649,
            6: 649,
            7: 649,
            8: 649,
            9: 649,
            10: 649,
            11: 649,
            12: 649,
        }
        for stage, pool_size in expected.items():
            assert len(panel.stage_pool(stage)) == pool_size, (
                f"real stage {stage} pool must hold {pool_size} respondents "
                f"after cleaning, got {len(panel.stage_pool(stage))}"
            )

    def test_fifty_profiles_render_across_all_stages_with_zero_invalid(self):
        """A 50-profile sample (5 draws at stages 1-2, 4 at stages 3-12)
        renders without a single invalid value or missing demographic."""
        _skip_if_dataset_missing()
        panel = _load_real_panel()
        twin = _render_module()
        render_stage_block = _require_attr(twin, "render_stage_block")
        draws: list[tuple[int, int]] = []
        for stage in range(1, 13):
            per_stage = 5 if stage <= 2 else 4
            draws.extend((stage, seed) for seed in range(per_stage))
        assert len(draws) == 50, f"sample must be 50 profiles, got {len(draws)}"
        for stage, seed in draws:
            profile = panel.draw_profile(stage, seed=seed)
            text = render_stage_block(profile, stage)
            # Scan the measured score tokens only (see _score_value_text):
            # the stage-6 header/note prose ("Financial Literacy", "general
            # financial literacy") is mandated verbatim and contains "nan".
            value_text = _score_value_text(text)
            for forbidden in ("no switch", "nan", "inf", "1e+", "4503599627370495"):
                assert forbidden not in value_text, (
                    f"stage {stage} seed {seed} renders invalid token {forbidden!r}"
                )
            # Count the 14 demographic bullets only: the demographics block is
            # the render's first block, before the first blank-line separator.
            # Later stages add their own "- " measure bullets (stage 3: +2,
            # stage 12: +5) that must not be mistaken for demographics.
            demo_lines = [
                line
                for line in text.split("\n\n", 1)[0].splitlines()
                if line.startswith("- ")
            ]
            assert len(demo_lines) == 14, (
                f"stage {stage} seed {seed}: 14 demographic bullets required, "
                f"got {len(demo_lines)}"
            )
            assert all(
                len(line[2:].split(":", 1)[1].strip()) > 0 for line in demo_lines
            ), f"stage {stage} seed {seed}: a demographic value is empty"

    def test_each_real_stage_renders_exactly_its_cumulative_blocks(self):
        """Stage coverage on the real panel: stage s shows blocks <= s only."""
        _skip_if_dataset_missing()
        panel = _load_real_panel()
        twin = _render_module()
        render_stage_block = _require_attr(twin, "render_stage_block")
        for stage in range(1, 13):
            profile = panel.draw_profile(stage, seed=7)
            text = render_stage_block(profile, stage)
            present = {s for s in STAGE_HEADERS if STAGE_HEADERS[s] in text}
            expected = {s for s in STAGE_HEADERS if s <= stage}
            assert present == expected, (
                f"real stage {stage} must show blocks {sorted(expected)} "
                f"only, got {sorted(present)}"
            )


def _skip_if_dataset_missing() -> None:
    """Skip the real-dataset tests when the panel has not been downloaded."""
    import pytest

    if not (RAW_DATA / "wave 1 scores.csv").exists():
        pytest.skip(f"Twin-2K-500 dataset not present at {DATASET_ROOT}")


def _load_real_panel():
    """Load the real Twin-2K-500 panel through the (missing) loader."""
    twin = _render_module()
    load_panel = _require_attr(twin, "load_panel")
    return load_panel(RAW_DATA, DEMO_NUMERIC, DEMO_LABEL)
