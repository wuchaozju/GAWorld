# This file builds the exact texts the models are shown. The system prompt
# is one short line normally, or that line plus a fixed note plus the full
# list of every version of the question when the model is told the setup
# was randomized ("unblinded"). The user prompt is always the same shape:
# an "EMBODY THIS PERSON" block with the 11 demographic fields, the
# question itself, the lettered answer options, and the instruction to
# answer with one uppercase letter. Nothing here ever mentions question
# ids, other experiments' questions, or the words "uniform" / "equal
# probability"; blinding lives only in the system prompt.

from twin2k6 import experiments

# The 11 demographic fields every persona shows, in this exact order.
# Mirrors PERSONA_FIELDS in src/fos/experiments/personas.py — kept local so
# the study package needs nothing from src/. Extra persona keys (behavioural
# measures, product favourites, ...) are never rendered.
PERSONA_FIELDS = [
    "age",
    "gender",
    "education",
    "household_income",
    "occupation",
    "ethnicity",
    "marital_status",
    "household_size",
    "number_of_children",
    "state",
    "home_ownership",
]

# The one-line system prompt the blinded arm sees.
BLINDED_SYSTEM_LINE = "You are a survey respondent."

# The unblinding note: says the version was randomly assigned and must not
# be read as information. Pinned wording — research banned "uniform" and
# "equal probability", so those words must never be added.
UNBLINDING_PARAGRAPH = (
    "This question comes from a randomized experiment. Participants were "
    "randomly assigned to one of the experimental versions listed below, and "
    "each participant saw only the version assigned to them. The version "
    "shown to you below was randomly assigned. Because the experimental "
    "condition was randomly assigned, do not infer any other differences in "
    "the participant or surrounding situation from which version was shown."
)

# Header of the version list in the unblinded system prompt.
VERSIONS_HEADER = "The experimental versions are:"

# The last line of every user prompt.
FINAL_INSTRUCTION = "Answer with only the corresponding uppercase letter."


def render_persona_block(persona: dict) -> str:
    """The "EMBODY THIS PERSON" block: one "field: value" line per field.

    Renders the 11 demographic fields in PERSONA_FIELDS order, skipping any
    field the persona dict does not carry (never a crash, never an invented
    value). Extra persona keys are ignored so behavioural-measure names and
    other bookkeeping can never leak into a prompt.
    """
    lines = [
        f"{field}: {persona[field]}" for field in PERSONA_FIELDS
        if field in persona
    ]
    return "EMBODY THIS PERSON:\n" + "\n".join(lines)


def _version_block(spec, stimuli: dict[str, dict]) -> str:
    """The numbered list of every version with its full question text.

    Each arm of the experiment appears as "Version {i}:" followed by that
    arm's complete verbatim question text, in the registry's pinned arm
    order. Only this experiment's own questions are ever included.
    """
    lines = [VERSIONS_HEADER]
    for number, (_arm_name, qid) in enumerate(spec.arms, start=1):
        lines.append(f"Version {number}:")
        lines.append(stimuli[qid]["question_text"])
    return "\n".join(lines)


def build_system_prompt(experiment: str, blinded: bool) -> str:
    """The system prompt for one experiment, blinded or unblinded.

    Blinded: exactly the one short line, with no hint of randomization.
    Unblinded: the blinded line, a blank line, the pinned randomization
    note, a blank line, then every version of this experiment with its
    full verbatim question text. Raises KeyError for an unknown experiment.
    """
    if blinded:
        return BLINDED_SYSTEM_LINE
    spec = experiments.EXPERIMENTS[experiment]
    head = (
        f"{BLINDED_SYSTEM_LINE}\n\n{UNBLINDING_PARAGRAPH}\n\n"
        f"{_version_block(spec, experiments.load_stimuli())}"
    )
    return head


def _option_lines(spec, stimulus: dict) -> list[str]:
    """The lettered answer options in display order, one per line.

    Multiple-choice questions render their catalogue options ("A. I strongly
    favor program A", ...). The sunk-cost question has no catalogue options —
    participants type a number 0-20 — so its lines render each letter's
    scored value ("A. 0" up to "U. 20"). Raises ValueError when a catalogue
    option count does not match the experiment's letter count.
    """
    options = stimulus.get("options")
    if options is None:
        return [
            f"{letter}. {spec.label_values[letter]}"
            for letter in spec.label_letters
        ]
    if len(options) != spec.label_count:
        raise ValueError(
            f"{spec.name}: {stimulus['qid']} has {len(options)} catalogue "
            f"options but the experiment shows {spec.label_count} letters"
        )
    return [
        f"{letter}. {option}"
        for letter, option in zip(spec.label_letters, options)
    ]


def build_user_prompt(persona: dict, experiment: str, arm: str) -> str:
    """The full user prompt for one persona answering one experiment arm.

    Shape (exactly the R1 demographics format): the EMBODY persona block,
    a blank line, the arm's verbatim question text, a blank line, the
    lettered options in display order, a blank line, and the final
    instruction. Takes no blinding argument — blinding lives only in the
    system prompt. Raises KeyError for an unknown experiment or arm.
    """
    spec = experiments.EXPERIMENTS[experiment]
    stimulus = experiments.stimulus_for(experiment, arm)
    parts = [
        render_persona_block(persona),
        stimulus["question_text"],
        "\n".join(_option_lines(spec, stimulus)),
        FINAL_INSTRUCTION,
    ]
    return "\n\n".join(parts)
