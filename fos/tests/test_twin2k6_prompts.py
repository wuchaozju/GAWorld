# Locked tests for the twin2k6 study's prompt builders (TASK-2060 RED
# phase; tests ONLY — no implementation lives here yet).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The blinded system prompt is exactly one short line.
#   - The unblinded system prompt is the blinded line, then the pinned
#     randomization paragraph (which must never say "uniform" or "equal
#     probability"), then a numbered list of EVERY version of that
#     experiment with its complete verbatim question text.
#   - The user prompt is byte-identical to the R1 demographics format:
#     the EMBODY THIS PERSON block with exactly the 11 demographic fields,
#     a blank line, the verbatim question, a blank line, the lettered
#     options in display order, a blank line, and the pinned final
#     instruction. It never mentions QIDs, never leaks another
#     experiment's question, and never carries behavioural-measure keys.
#
# All offline: pure string building plus reads of the shipped data file.
import inspect
import json
import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import config, experiments, prompts  # noqa: E402

# Pinned exact strings (from the study spec — must appear verbatim).
BLINDED_SYSTEM = "You are a survey respondent."
UNBLINDING_PARAGRAPH = (
    "This question comes from a randomized experiment. Participants were "
    "randomly assigned to one of the experimental versions listed below, and "
    "each participant saw only the version assigned to them. The version "
    "shown to you below was randomly assigned. Because the experimental "
    "condition was randomly assigned, do not infer any other differences in "
    "the participant or surrounding situation from which version was shown."
)
VERSION_HEADER = "The experimental versions are:"
FINAL_INSTRUCTION = "Answer with only the corresponding uppercase letter."

# The persona block exactly as the R1 pricing run rendered it (11 fields,
# PERSONA_FIELDS order; taken from a real record in
# results/unblinding/R1-YESNO-NEWBATCH-20260918T000738/ibm_granite-4.1-8b/).
PERSONA = {
    "age": 28,
    "gender": "female",
    "education": "bachelor's degree",
    "household_income": 45000,
    "occupation": "marketing specialist",
    "ethnicity": "Latinx",
    "marital_status": "married",
    "household_size": 4,
    "number_of_children": 2,
    "state": "TX",
    "home_ownership": "rent",
}
EXPECTED_PERSONA_BLOCK = (
    "EMBODY THIS PERSON:\n"
    "age: 28\n"
    "gender: female\n"
    "education: bachelor's degree\n"
    "household_income: 45000\n"
    "occupation: marketing specialist\n"
    "ethnicity: Latinx\n"
    "marital_status: married\n"
    "household_size: 4\n"
    "number_of_children: 2\n"
    "state: TX\n"
    "home_ownership: rent"
)

# Behavioural measures that must NEVER reach a prompt (drift guard).
BEHAVIOURAL_MEASURES = [
    "tightwad_spendthrift", "discount_rate", "present_bias",
    "risk_aversion", "loss_aversion",
]


def _stimuli_by_qid():
    """Load the shipped stimuli file keyed by QID (helper)."""
    with open(config.STIMULI_PATH) as f:
        return {s["qid"]: s for s in json.load(f)["stimuli"]}


def _all_arm_pairs():
    """Every (experiment, arm) pair of the study (helper)."""
    return [
        (exp_name, arm_name)
        for exp_name, spec in experiments.EXPERIMENTS.items()
        for arm_name, _qid in spec.arms
    ]


def test_blinded_system_prompt_is_the_exact_one_line():
    """Blinded: exactly 'You are a survey respondent.' — for every experiment."""
    for exp_name, _arm in _all_arm_pairs():
        assert prompts.build_system_prompt(exp_name, blinded=True) == BLINDED_SYSTEM, exp_name


def test_unblinded_system_prompt_is_blinded_plus_paragraph_plus_versions():
    """Unblinded = blinded text + blank line + pinned paragraph + version list."""
    prompt = prompts.build_system_prompt("disease", blinded=False)
    assert prompt.startswith(
        BLINDED_SYSTEM + "\n\n" + UNBLINDING_PARAGRAPH + "\n\n" + VERSION_HEADER
    )
    version_block = prompt[len(BLINDED_SYSTEM) + 2 + len(UNBLINDING_PARAGRAPH) + 2:]
    assert prompt == (
        BLINDED_SYSTEM + "\n\n" + UNBLINDING_PARAGRAPH + "\n\n" + version_block
    )
    assert version_block.startswith(VERSION_HEADER)


def test_unblinded_system_prompt_lists_every_version_in_arm_order():
    """Each arm appears as 'Version {i}:' followed by its FULL question text."""
    stimuli = _stimuli_by_qid()
    for exp_name, spec in experiments.EXPERIMENTS.items():
        prompt = prompts.build_system_prompt(exp_name, blinded=False)
        cursor = -1
        for i, (arm_name, qid) in enumerate(spec.arms, start=1):
            marker = f"Version {i}:"
            assert marker in prompt, f"{exp_name}: missing '{marker}'"
            text = stimuli[qid]["question_text"]
            assert text in prompt, f"{exp_name}/{arm_name}: verbatim question text missing"
            position = prompt.index(marker)
            assert position < prompt.index(text), (
                f"{exp_name}: question text must follow {marker}"
            )
            assert position > cursor, f"{exp_name}: versions must appear in arm order"
            cursor = position


def test_uniform_and_equal_probability_never_appear_anywhere():
    """Research ban: no prompt may say 'uniform' or 'equal probability'."""
    persona = dict(PERSONA)
    for exp_name, arm in _all_arm_pairs():
        for blinded in (True, False):
            system = prompts.build_system_prompt(exp_name, blinded=blinded)
            user = prompts.build_user_prompt(persona, exp_name, arm)
            for prompt in (system, user):
                assert "uniform" not in prompt.lower(), f"{exp_name}/{arm}"
                assert "equal probability" not in prompt.lower(), f"{exp_name}/{arm}"


def test_blinded_prompts_never_say_randomi():
    """In the blinded arm neither prompt may hint at randomization."""
    persona = dict(PERSONA)
    for exp_name, arm in _all_arm_pairs():
        system = prompts.build_system_prompt(exp_name, blinded=True)
        user = prompts.build_user_prompt(persona, exp_name, arm)
        assert "randomi" not in system.lower(), f"{exp_name}/{arm} system"
        assert "randomi" not in user.lower(), f"{exp_name}/{arm} user"


def test_user_prompt_is_byte_identical_to_the_r1_demographics_format():
    """Full byte-exact user prompt for disease/gain with the R1 persona."""
    expected = (
        EXPECTED_PERSONA_BLOCK
        + "\n\n"
        + "Imagine that the U.S. is preparing for the outbreak of an unusual "
        + "disease, which is expected to kill 600 people. Two alternative "
        + "programs to combat the disease have been proposed. Assume that the "
        + "exact scientific estimate of the consequences of the programs are "
        + "as follows: If Program A is adopted, 200 people will be saved. If "
        + "Program B is adopted, there is 1/3 probability that 600 people "
        + "will be saved, and 2/3 probability that no people will be saved. "
        + "Which of the two programs would you favor?"
        + "\n\n"
        + "A. I strongly favor program A\n"
        + "B. I favor program A\n"
        + "C. I slightly favor program A\n"
        + "D. I slightly favor program B\n"
        + "E. I favor program B\n"
        + "F. I strongly favor program B"
        + "\n\n"
        + FINAL_INSTRUCTION
    )
    assert prompts.build_user_prompt(dict(PERSONA), "disease", "gain") == expected


def test_user_prompt_starts_with_the_r1_persona_block():
    """Every user prompt opens with the exact 11-field EMBODY block."""
    for exp_name, arm in _all_arm_pairs():
        user = prompts.build_user_prompt(dict(PERSONA), exp_name, arm)
        assert user.startswith(EXPECTED_PERSONA_BLOCK + "\n\n"), f"{exp_name}/{arm}"


def test_user_prompt_ends_with_the_exact_final_instruction():
    """The last line of every user prompt is the pinned instruction."""
    for exp_name, arm in _all_arm_pairs():
        user = prompts.build_user_prompt(dict(PERSONA), exp_name, arm)
        assert user.endswith("\n\n" + FINAL_INSTRUCTION), f"{exp_name}/{arm}"


def test_user_prompt_takes_no_blinding_argument():
    """Blinding lives only in the system prompt — the signature proves it."""
    parameters = inspect.signature(prompts.build_user_prompt).parameters
    assert "blinded" not in parameters and "blind" not in parameters


def test_sunk_cost_options_run_from_A_dot_0_to_U_dot_20():
    """Sunk cost has no catalogue options: render A. 0 up to U. 20."""
    user = prompts.build_user_prompt(dict(PERSONA), "sunk_cost", "card")
    lines = user.split("\n")
    option_lines = [line for line in lines if len(line) > 2 and line[1] == "." and line[0].isupper()]
    expected = [f"{chr(ord('A') + i)}. {i}" for i in range(21)]
    assert option_lines == expected, "options must be exactly 'A. 0' .. 'U. 20'"


def test_wta_wtp_options_are_the_ten_dollar_brackets_in_order():
    """WTA/WTP renders the catalogue brackets A. $10 .. J. $5,000,000 or more."""
    user = prompts.build_user_prompt(dict(PERSONA), "wta_wtp", "wta_certainty")
    assert "A. $10" in user
    assert "J. $5,000,000 or more" in user
    letters = [chr(ord("A") + i) for i in range(10)]
    positions = [user.index(f"{letter}. ") for letter in letters]
    assert positions == sorted(positions), "brackets must stay in display order"


def test_extra_persona_keys_never_leak_into_the_prompt():
    """Only the 11 demographic fields may render — extras are dropped."""
    persona = dict(PERSONA)
    persona["tightwad_spendthrift"] = "3"
    persona["favorite_product"] = "Capri Sun"
    user = prompts.build_user_prompt(persona, "disease", "gain")
    assert "tightwad_spendthrift" not in user
    assert "favorite_product" not in user
    assert "Capri Sun" not in user


def test_behavioural_measure_names_never_appear_in_any_prompt():
    """No behavioural-answer field name may surface in any prompt."""
    persona = dict(PERSONA)
    for measure in BEHAVIOURAL_MEASURES:
        persona[measure] = "9"
    for exp_name, arm in _all_arm_pairs():
        user = prompts.build_user_prompt(persona, exp_name, arm)
        system = prompts.build_system_prompt(exp_name, blinded=False)
        for measure in BEHAVIOURAL_MEASURES:
            assert measure not in user, f"{exp_name}/{arm}: {measure} leaked"
            assert measure not in system, f"{exp_name}/{arm}: {measure} leaked"


def test_no_qid_string_ever_appears_in_a_user_prompt():
    """Question ids are bookkeeping, not survey content — never render them."""
    for exp_name, arm in _all_arm_pairs():
        user = prompts.build_user_prompt(dict(PERSONA), exp_name, arm)
        assert "QID" not in user, f"{exp_name}/{arm}"


def test_no_other_experiments_question_text_leaks_into_a_prompt():
    """Each prompt shows ONLY its own arm's text — never a sibling arm's
    text, never another experiment's question. (Amended, TASK-2069: a
    participant sees one arm, so the user prompt must contain that arm's
    verbatim question and none of the experiment's other arms. The
    unblinded system prompt lists every version on purpose, so it is only
    checked against OTHER experiments' text; the blinded system prompt
    keeps that check too.)"""
    stimuli = _stimuli_by_qid()
    for exp_name, arm in _all_arm_pairs():
        spec = experiments.EXPERIMENTS[exp_name]
        own_qid = dict(spec.arms)[arm]
        own_text = stimuli[own_qid]["question_text"]
        sibling_texts = [
            stimuli[qid]["question_text"]
            for _a, qid in spec.arms
            if qid != own_qid
        ]
        user = prompts.build_user_prompt(dict(PERSONA), exp_name, arm)
        blinded = prompts.build_system_prompt(exp_name, blinded=True)
        unblinded = prompts.build_system_prompt(exp_name, blinded=False)
        assert own_text in user, f"{exp_name}/{arm}: own question text missing"
        for text in sibling_texts:
            assert text not in user, f"{exp_name}/{arm} leaks a sibling arm's text"
        for other_name, other_spec in experiments.EXPERIMENTS.items():
            if other_name == exp_name:
                continue
            for _o_arm, oqid in other_spec.arms:
                text = stimuli[oqid]["question_text"]
                assert text not in user, f"{exp_name}/{arm} leaks {other_name} text"
                assert text not in blinded, f"{exp_name} blinded system leaks {other_name}"
                assert text not in unblinded, f"{exp_name} unblinded system leaks {other_name}"
