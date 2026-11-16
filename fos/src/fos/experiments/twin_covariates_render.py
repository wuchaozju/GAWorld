"""Prompt-12 renderer for the Appendix E measured-covariate stage blocks.

Gui & Toubia (2025) Prompt 12 (Web Appendix E) renders a respondent's
measured profile as a "# Demographics:" bullet block followed by one measure
block per covariate stage. This module turns ONE whole-row profile dict
(respondent demographics text + measured scores + their panel percentiles)
into that verbatim text. It is a private helper of fos.experiments.
twin_covariates, which owns the panel and profile definitions and re-exports
the demographic label lists below.

What each function does:
    _score_text(value)            - "18" for 18.0, "0.25" for 0.25, etc.
    _demographics_block(profile)  - The 14-bullet Prompt-12 demographics.
    _score_and_percentile(...)    - One "18 (79 percentile)" measure cell.
    _measure_block(stage, ...)    - One stage's header + note + bullets.
    render_stage_block(...)       - Demographics plus every measure block of
                                    stages 2..stage, blank-line separated.
"""

from __future__ import annotations

from typing import Any

from fos.i18n import T

# Prompt 12's "# Demographics:" block - 14 bullet display labels verbatim
# (RESULT-1474 §1). They map 1:1 onto the QID11-24 answers in this order.
DEMOGRAPHIC_DISPLAY_LABELS: list[str] = [
    "Geographic region",
    "Gender",
    "Age",
    "Education level",
    "Race",
    "Citizen of the US",
    "Marital status",
    "Religion",
    "Religious attendance",
    "Political affiliation",
    "Income",
    "Political views",
    "Household size",
    "Employment status",
]

# Profile keys for the same 14 demographics, in the same order.
DEMOGRAPHIC_KEYS: list[str] = [
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

# The measure display lines of each stage, in render order. A single-measure
# stage renders its value inline on the "# ..." header line; the two
# multi-measure stages (3 and 12) render one "- Label: ..." bullet per
# measure under their header.
_MEASURE_LINES: dict[int, tuple[tuple[str, str], ...]] = {
    2: (("Tightwad-Spendthrift", "score_ST-TW"),),
    3: (("Discount", "score_discount"), ("Present Bias", "score_presentbias")),
    4: (("Risk aversion", "score_riskaversion"),),
    5: (("Loss aversion", "score_lossaversion"),),
    6: (("Financial Literacy", "score_finliteracy"),),
    7: (("Numeracy", "score_numeracy"),),
    8: (("Mental Accounting", "score_mentalaccounting"),),
    9: (("Maximization", "score_maximization"),),
    10: (("Minimalism", "score_minimalism"),),
    11: (("GREEN", "score_GREEN"),),
    12: (
        ("Extraversion", "score_extraversion"),
        ("Agreeableness", "score_agreeableness"),
        ("Conscientiousness", "score_conscientiousness"),
        ("Openness", "score_openness"),
        ("Neuroticism", "score_neuroticism"),
    ),
}

# Each stage's "# ..." header (verbatim from Prompt 12). For the
# header-only single-measure stages the header carries the inline score and
# percentile.
_MEASURE_HEADERS: dict[int, str] = {
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

# The verbatim Prompt-12 "<note: ...>" line of every measure stage
# (RESULT-1474 §1 Prompt 12 Parts I and II).
_MEASURE_NOTES: dict[int, str] = {
    2: (
        "<note: The score ranges from 4 to 26. Lower scores (4-11) indicate "
        "difficulty spending money, while higher scores (19-26) indicate "
        "difficulty controlling spending.>"
    ),
    3: (
        "<note: These are implied rates computed from your time-value of "
        "money preferences. Higher values of the discount rate imply greater "
        "impatience. Higher values of present bias imply greater departure "
        "from normative economic behavior.>"
    ),
    4: (
        "<note: Higher scores indicate a greater tendency for risk aversion "
        "in a choice between a sure-amount and lottery payout.>"
    ),
    5: (
        "<note: Higher scores indicate a greater tendency for loss aversion "
        "in a choice between a sure-amount and a lottery payout.>"
    ),
    6: (
        "<note: The score ranges from 0 to 8, and a higher score indicates "
        "you correctly answered more questions related to general financial "
        "literacy.>"
    ),
    7: (
        "<note: The score ranges from 0 to 8, and a higher score indicates "
        "you correctly answered more questions related to numeracy.>"
    ),
    8: (
        "<note: The score ranges from 0 to 100 percent, and higher scores "
        "indicate a greater adherence to the principles of mental accounting "
        "proposed by Thaler: segregate gains, integrate losses, segregate a "
        "small gain from a large loss, and integrate a small loss with a "
        "large gain.>"
    ),
    9: (
        "<note: The score ranges from 1 to 5, and higher scores indicate a "
        "tendency to optimize rather than satisfice when making decisions.>"
    ),
    10: (
        "<note: The score ranges from 1 to 5, and a higher score indicates a "
        "higher preference for minimalism.>"
    ),
    11: (
        "<note: The score ranges from 1 to 5, and higher scores indicate a "
        "higher affinity for environmentalism.>"
    ),
    12: (
        "<note: Openness reflects curiosity and receptiveness to new "
        "experiences, Conscientiousness indicates self-discipline and "
        "goal-directed behavior, Extraversion measures sociability and "
        "assertiveness, Agreeableness reflects compassion and "
        "cooperativeness, and Neuroticism captures emotional instability and "
        "susceptibility to negative emotions. Each score ranges from 1 to 5, "
        "and a higher score indicates a greater display of the associated "
        "traits.>"
    ),
}

# The stages whose measures render as "- Label: ..." bullets (3 and 12 are
# the multi-measure Prompt-12 blocks); every other stage's single measure is
# inline on its header line.
_BULLET_STAGES = frozenset({3, 12})

# Stages of the Table E.1 ladder.
_STAGE_MIN = 1
_STAGE_MAX = 12


def _score_text(value: float) -> str:
    """Render one score as the Prompt-12 text: "18" for 18.0, "0.25", etc.

    Integral values print without a decimal point; every other float prints
    in plain decimal (no exponent notation), e.g. "0.3" and "2.125".
    """
    if value.is_integer():
        return str(int(value))
    text = str(value)
    return text


def _demographics_block(profile: dict[str, Any]) -> str:
    """Render the Prompt-12 "# Demographics:" block of one profile.

    The block holds one "- {Prompt-12 label}: {label text}" bullet per
    demographic, in the verbatim Prompt-12 order, with no percentiles.
    """
    lines = ["# Demographics:"]
    for label, key in zip(DEMOGRAPHIC_DISPLAY_LABELS, DEMOGRAPHIC_KEYS):
        lines.append(f"- {label}: {profile.get(key, '')}")
    return "\n".join(lines)


def _score_and_percentile(profile: dict[str, Any], column: str) -> str:
    """Format one measure as "18 (79 percentile)" from a profile.

    The score prints as the profile's float ("18" for 18.0) followed by the
    panel's integer percentile for that score in parentheses. A profile whose
    cell is invalid renders nothing usable; callers only render valid cells.
    """
    value = profile.get(column)
    percentile = profile.get("percentiles", {}).get(column)
    if value is None or percentile is None:
        return "missing"
    return f"{_score_text(value)} ({percentile} percentile)"


def _measure_block(stage: int, profile: dict[str, Any]) -> str:
    """Render one stage's measure block (Prompt-12 verbatim grammar).

    A single-measure stage puts the score inline on its "# ..." header line
    and the note right under it; the multi-measure stages 3 and 12 put the
    note under the header and one "- Label: ..." bullet per measure.
    """
    header = _MEASURE_HEADERS[stage]
    note = _MEASURE_NOTES[stage]
    lines = _MEASURE_LINES[stage]
    if stage not in _BULLET_STAGES:
        label, column = lines[0]
        return f"{header} {_score_and_percentile(profile, column)}\n{note}"
    body = [header, note]
    body.extend(
        f"- {label}: {_score_and_percentile(profile, column)}"
        for label, column in lines
    )
    return "\n".join(body)


def render_stage_block(profile: dict[str, Any], stage: int) -> str:
    """Render one profile at one Appendix E stage into Prompt-12 text.

    The text opens with the 14-demographic block, then the measure block of
    every stage from 2 up to the requested stage in Table E.1 order, blocks
    separated by single blank lines. Stages outside 1..12 raise ValueError.
    """
    if stage < _STAGE_MIN or stage > _STAGE_MAX:
        raise ValueError(
            T("error.twin_covariates.unsupported_stage", stage=repr(stage))
        )
    blocks = [_demographics_block(profile)]
    blocks.extend(_measure_block(s, profile) for s in range(2, stage + 1))
    return "\n\n".join(blocks)
