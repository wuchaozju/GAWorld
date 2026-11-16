# Locked tests for the twin2k10 study's prompt builder (TASK-2139 RED
# phase; tests ONLY — no implementation lives yet, so every test here
# errors at collection until scripts/twin2k10/prompts.py exists).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The persona block renders the same 11 demographic fields as twin2k6,
#     and extra persona keys never leak into a prompt.
#   - The blinded system prompt is the same single line as twin2k6's; the
#     unblinded one adds twin2k6's exact randomization note plus every
#     version of that experiment. The banned words ("uniform", "equal
#     probability") appear in no prompt, ever.
#   - Every user prompt carries the verbatim question text of each of the
#     arm's questions. Choice questions render "A. <option>" lines;
#     numeric questions ask for a single number; multi-row questions ask
#     for one numbered answer per row (false_consensus: 10 answers).
#   - TASK-2182 pivot: every numeric answer is measured with ONE
#     deterministic first-token call on its OWN prompt, so multi-item arms
#     build one prompt PER ITEM via build_user_prompt(..., item=...): a
#     single-policy rating prompt (statement + 1–5 scale), or an anchoring
#     digit prompt (verbatim estimate question only). The old "numbered
#     list of exactly 10 numbers" instruction is banned: an arm with
#     digit items refuses whole-arm rendering outright.
#
# All offline: pure string building; no network, no models.
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import experiments, prompts  # noqa: E402

# A complete 11-field persona, the same fields twin2k6 renders.
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

ARMS = [
    ("allais", "form1"), ("linda", "conjunction"),
    ("base_rate", "30_engineers"), ("anchoring_redwood", "low"),
    ("anchoring_african", "high"), ("outcome_bias", "success"),
    ("myside", "ford"), ("prob_matching", "problem1"),
    ("abs_relative", "calculator"), ("false_consensus", "all"),
]


def _stimuli() -> dict[str, dict]:
    """The study's loaded stimuli, keyed by question id (helper)."""
    return experiments.load_stimuli()


def _arm_qids(experiment: str, arm: str) -> list[str]:
    """The question ids of one arm, in file order (helper)."""
    stimuli = _stimuli()
    return [
        qid for qid, entry in sorted(stimuli.items())
        if entry["experiment"] == experiment and entry["arm"] == arm
    ]


def _last_paragraph(prompt: str) -> str:
    """The final instruction block of a prompt (helper)."""
    return prompt.split("\n\n")[-1]


def test_persona_block_renders_the_same_11_fields_as_twin2k6() -> None:
    """The demographic fields equal twin2k6's, in the same order."""
    from twin2k6 import prompts as k6_prompts

    assert prompts.PERSONA_FIELDS == k6_prompts.PERSONA_FIELDS
    block = prompts.render_persona_block(PERSONA)
    assert block.startswith("EMBODY THIS PERSON:")
    assert "age: 41" in block and "state: Ohio" in block


def test_extra_persona_keys_never_leak_into_the_block() -> None:
    """Behavioural or bookkeeping keys are silently excluded, never shown."""
    noisy = {**PERSONA, "product_favourites": ["coke"], "twin2k_item": 7}
    block = prompts.render_persona_block(noisy)
    assert "coke" not in block and "twin2k_item" not in block


def test_blinded_system_prompt_is_the_same_one_liner_as_twin2k6() -> None:
    """Every blinded arm sees exactly twin2k6's short line, nothing else."""
    from twin2k6 import prompts as k6_prompts

    for experiment in experiments.EXPERIMENTS:
        assert prompts.build_system_prompt(experiment, blinded=True) \
            == k6_prompts.BLINDED_SYSTEM_LINE


def test_unblinded_system_prompt_adds_the_note_and_all_versions() -> None:
    """Unblinded = blinded line + twin2k6's note + every version's text."""
    from twin2k6 import prompts as k6_prompts

    for experiment, arm in ARMS:
        unblinded = prompts.build_system_prompt(experiment, blinded=False)
        assert k6_prompts.BLINDED_SYSTEM_LINE in unblinded, experiment
        assert k6_prompts.UNBLINDING_PARAGRAPH in unblinded, experiment
        spec = experiments.EXPERIMENTS[experiment]
        for other_arm, _ in spec.arms:
            for qid in _arm_qids(experiment, other_arm):
                assert _stimuli()[qid]["question_text"] in unblinded, \
                    (experiment, other_arm, qid)
        assert unblinded != prompts.build_system_prompt(experiment,
                                                        blinded=True)


def test_banned_words_never_appear_in_any_prompt() -> None:
    """'uniform' and 'equal probability' are banned by the research design."""
    for experiment, arm in ARMS:
        items = experiments.arm_items(experiment, arm)
        users = [prompts.build_user_prompt(PERSONA, experiment, arm,
                                           item=item) for item in items]
        for blinded in (True, False):
            system = prompts.build_system_prompt(experiment, blinded=blinded)
            for text in users + [system]:
                assert "uniform" not in text.lower(), experiment
                assert "equal probability" not in text.lower(), experiment


def test_user_prompt_carries_every_verbatim_question_of_the_arm() -> None:
    """Each arm's question texts appear word for word, item by item.

    After the pivot a multi-item arm is asked one item per call, so the
    verbatim guarantee is per item prompt: every item's prompt carries
    its own question text (and, for split rows, its own statement).
    """
    for experiment, arm in ARMS:
        items = experiments.arm_items(experiment, arm)
        for item in items:
            user = prompts.build_user_prompt(PERSONA, experiment, arm,
                                             item=item)
            assert item["question_text"] in user, (experiment, arm, item)
            assert "EMBODY THIS PERSON:" in user


def test_choice_options_render_as_letter_lines_matching_option_count() -> None:
    """A choice question shows 'A. <text>', 'B. <text>', ... for all options."""
    user = prompts.build_user_prompt(PERSONA, "allais", "form1")
    stimulus = _stimuli()["QID192"]
    for letter, option in zip(stimulus["labels"], stimulus["options"]):
        assert f"{letter}. {option}" in user, letter
    assert _last_paragraph(user) == prompts.FINAL_INSTRUCTION


def test_base_rate_digit_prompt_is_the_verbatim_question_asking_a_number() -> None:
    """base_rate asks for one number on its own deterministic prompt.

    The item prompt carries the verbatim question text, no letter options,
    and ends with the pinned single-number instruction.
    """
    item = next(i for i in experiments.arm_items("base_rate", "30_engineers")
                if i["kind"] == "digit")
    user = prompts.build_user_prompt(PERSONA, "base_rate", "30_engineers",
                                     item=item)
    assert item["question_text"] in user
    assert _last_paragraph(user) == prompts.NUMERIC_INSTRUCTION
    assert "A." not in user


def test_anchoring_mc_item_prompt_is_the_choice_question_alone() -> None:
    """The anchor choice call sees the anchor question and its options."""
    items = experiments.arm_items("anchoring_redwood", "low")
    mc = next(item for item in items if item["kind"] == "choice")
    user = prompts.build_user_prompt(PERSONA, "anchoring_redwood", "low",
                                     item=mc)
    assert "A. more" in user and "B. less" in user
    assert _last_paragraph(user) == prompts.FINAL_INSTRUCTION


def test_anchoring_digit_item_prompt_is_the_verbatim_estimate_only() -> None:
    """The estimate call sees the verbatim estimate question, asked as a number.

    Amended by TASK-2215 per RESULT-2214 Fix 2: the arm's anchor context
    MAY now appear above the estimate question (it must — the anchor was
    never reaching the estimate call), but the lettered option lines must
    still never render (the first-token digit scan must read a digit, not
    an anchor letter) and the estimate question stays the last question
    before the pinned single-number instruction.
    """
    items = experiments.arm_items("anchoring_redwood", "low")
    digit = next(item for item in items if item["kind"] == "digit")
    user = prompts.build_user_prompt(PERSONA, "anchoring_redwood", "low",
                                     item=digit)
    assert digit["question_text"] in user
    assert _last_paragraph(user) == prompts.NUMERIC_INSTRUCTION
    assert "A. more" not in user and "B. less" not in user, (
        "the anchor choice question's letter options must never render in "
        "the digit item's prompt — the first-token digit scan would read "
        "the letter"
    )


def test_false_consensus_item_prompt_shows_one_policy_and_the_scale() -> None:
    """One rating call sees ONE policy statement plus its 1–5 scale.

    The columns render exactly as before ("1 = Strongly oppose" ...),
    no other policy's statement leaks in, and the prompt asks for a
    single number — never a numbered list.
    """
    items = experiments.arm_items("false_consensus", "all")
    rows = _stimuli()["QID287"]["rows"]
    columns = _stimuli()["QID287"]["columns"]
    user = prompts.build_user_prompt(PERSONA, "false_consensus", "all",
                                     item=items[2])
    assert rows[2] in user
    for number, label in enumerate(columns, start=1):
        assert f"{number} = {label}" in user
    for other in (rows[0], rows[1], rows[9]):
        assert other not in user, other
    assert _last_paragraph(user) == prompts.NUMERIC_INSTRUCTION


def test_linda_item_prompt_shows_one_statement_and_the_six_point_scale() -> None:
    """Linda's per-statement prompt maps its 6-point probability scale."""
    items = experiments.arm_items("linda", "conjunction")
    columns = _stimuli()["QID160"]["columns"]
    user = prompts.build_user_prompt(PERSONA, "linda", "conjunction",
                                     item=items[0])
    assert items[0]["statement"] in user
    for number, label in enumerate(columns, start=1):
        assert f"{number} = {label}" in user
    assert _last_paragraph(user) == prompts.NUMERIC_INSTRUCTION


def test_no_prompt_ever_asks_for_a_numbered_list_of_answers() -> None:
    """The sampling-era numbered-list instruction is banned everywhere.

    Every item prompt of every arm asks for a letter or a single number
    — never "a numbered list of exactly N numbers".
    """
    for experiment, spec in experiments.EXPERIMENTS.items():
        for arm, _qids in spec.arms:
            for item in experiments.arm_items(experiment, arm):
                user = prompts.build_user_prompt(PERSONA, experiment, arm,
                                                 item=item)
                assert "numbered list" not in user, (experiment, arm)


def test_whole_arm_prompt_refuses_arms_with_digit_items() -> None:
    """A multi-item arm has no single prompt — asking for one is an error.

    The pivot's arms with digit items are measured one item per call, so
    a whole-arm render would silently rebuild the banned numbered-list
    prompt; it must raise instead of rendering a made-up shape.
    """
    for experiment, arm in (("false_consensus", "all"),
                            ("linda", "conjunction"),
                            ("prob_matching", "problem1"),
                            ("base_rate", "30_engineers"),
                            ("anchoring_redwood", "low"),
                            ("anchoring_african", "high")):
        with pytest.raises(ValueError):
            prompts.build_user_prompt(PERSONA, experiment, arm)
