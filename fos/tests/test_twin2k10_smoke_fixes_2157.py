# Locked tests born from the three defects the twin2k10 smoke run exposed
# (TASK-2157; diagnosis in crew debug RESULT-2155). Amended by the
# TASK-2182 design pivot: F1's free-text multi-row parser and F3's
# parse-failure counters described the DELETED sampling path, so their
# tests were replaced — F1's "first value per row number" semantics dies
# with the parser (each rating is now its own first-token call), and F3's
# honest-failure principle lives on as
# test_a_failed_item_call_blocks_record_success in test_twin2k10_cells.py
# (see the amendment log in RESULT-2182). The surviving surface is F2's
# scale rendering — now one scale PER ITEM prompt — plus the
# choice-prompt byte snapshot guard.
#
# WHAT THIS FILE CHECKS, in plain words:
#   - F2, prompts: a multi-row question's answer scale (the survey's own
#     column labels with their numbers, "1 = Strongly oppose" ...) is
#     rendered on every single-item rating prompt, so the model answers
#     digits the first-token scan can fold — never words. The choice
#     prompt must not change at all (byte-identical snapshot guard).
#
# All offline: pure string building — no network, no models.
import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import experiments, prompts  # noqa: E402

# A complete 11-field persona, the same fields the locked prompt tests use.
PERSONA = {
    "age": 41,
    "gender": "female",
    "education": "bachelor's degree",
    "household_income": "$60,000-$79,999",
    "occupation": "teacher",
    "ethnicity": "White",
    "marital_status": "married",
    "household_size": 4,
    "number_of_children": 2,
    "state": "Ohio",
    "home_ownership": "own",
}

# The current allais form1 user prompt, captured byte for byte before any
# scale rendering exists. If F2 accidentally touches choice questions,
# this guard fails; stimuli.json is sha-pinned so this stays stable.
ALLAIS_FORM1_PROMPT_SNAPSHOT = (
    "EMBODY THIS PERSON:\n"
    "age: 41\n"
    "gender: female\n"
    "education: bachelor's degree\n"
    "household_income: $60,000-$79,999\n"
    "occupation: teacher\n"
    "ethnicity: White\n"
    "marital_status: married\n"
    "household_size: 4\n"
    "number_of_children: 2\n"
    "state: Ohio\n"
    "home_ownership: own\n"
    "\n"
    "Choose between:\n"
    "\n"
    "A. One million dollars for sure\n"
    "B. 89% probability of one million dollars 10% probablity of five "
    "miillion dollars 1% probability of nothing\n"
    "\n"
    "Answer with only the corresponding uppercase letter."
)


def _columns(experiment: str, arm: str) -> list[str]:
    """The survey's own answer-scale labels of one arm's item (helper)."""
    stimuli = experiments.load_stimuli()
    entry = next(
        e for e in stimuli.values()
        if e["experiment"] == experiment and e["arm"] == arm
    )
    return list(entry["columns"])


# ---------------------------------------------------------------------------
# F2 — prompt scale rendering: every rating prompt must define the digits.
# ---------------------------------------------------------------------------


def test_false_consensus_prompt_shows_the_numbered_response_scale() -> None:
    """Every oppose/support label appears with its number in the prompt.

    The item's columns are the survey's 5-point scale, so the single-
    policy rating prompt must map each position ("1 = Strongly oppose"
    ... "5 = Strongly support") — the digits the first-token scan folds.
    """
    items = experiments.arm_items("false_consensus", "all")
    user = prompts.build_user_prompt(PERSONA, "false_consensus", "all",
                                     item=items[0])
    for number, label in enumerate(_columns("false_consensus", "all"),
                                   start=1):
        assert f"{number} = {label}" in user, (number, label)


def test_linda_prompt_shows_the_numbered_response_scale() -> None:
    """Every probability label appears with its number in the prompt.

    Linda's 6-point scale ("1 = Extremely improbable" ... "6 = Extremely
    probable") must be rendered on each per-statement prompt so its
    three first-token distributions mean something.
    """
    items = experiments.arm_items("linda", "conjunction")
    user = prompts.build_user_prompt(PERSONA, "linda", "conjunction",
                                     item=items[0])
    for number, label in enumerate(_columns("linda", "conjunction"),
                                   start=1):
        assert f"{number} = {label}" in user, (number, label)


def test_choice_prompt_is_unchanged_by_scale_rendering() -> None:
    """The allais form1 prompt stays byte-identical (green-today guard).

    F2 may only touch rating-item rendering; a choice prompt must be
    exactly what it was before, so this snapshot must keep passing.
    """
    user = prompts.build_user_prompt(PERSONA, "allais", "form1")
    assert user == ALLAIS_FORM1_PROMPT_SNAPSHOT
