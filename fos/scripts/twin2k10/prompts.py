# This file builds the exact texts the models are shown. The system prompt
# is one short line normally, or that line plus a fixed note plus the full
# list of every version of the experiment when the model is told the setup
# was randomized ("unblinded"). Every ANSWER is measured with one
# deterministic first-token call, so each item gets its OWN user prompt
# (build_user_prompt with item=): the "EMBODY THIS PERSON" block with the
# 11 demographic fields, then that one item — a choice question with its
# lettered options, or one rating statement (or one numeric estimate
# question) with its "N = label" answer scale — then one closing
# instruction: a letter answer, or a single number. Whole-arm rendering
# (item=None) still exists for the choice-only arms whose single item IS
# the arm; an arm holding digit items has no single prompt and refuses to
# render one. Nothing here ever mentions question ids or the banned words
# "uniform" / "equal probability"; blinding lives only in the system
# prompt.

from twin2k10 import experiments

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

# The last line of a choice question's user prompt.
FINAL_INSTRUCTION = "Answer with only the corresponding uppercase letter."

# The last line of every digit item's user prompt: the model answers one
# number, whose first token the study folds over the item's digit labels.
NUMERIC_INSTRUCTION = "Answer with a single number."


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
    """The numbered list of every version with its full question text(s).

    Each arm of the experiment appears as "Version {i}:" followed by that
    arm's complete verbatim question text(s) in survey order (an anchoring
    version shows both its questions). Only this experiment's own
    questions are ever included.
    """
    lines = [VERSIONS_HEADER]
    for number, (arm_name, arm_qids) in enumerate(spec.arms, start=1):
        lines.append(f"Version {number}:")
        for qid in arm_qids:
            lines.append(stimuli[qid]["question_text"])
    return "\n".join(lines)


def build_system_prompt(experiment: str, blinded: bool) -> str:
    """The system prompt for one experiment, blinded or unblinded.

    Blinded: exactly the one short line, with no hint of randomization.
    Unblinded: the blinded line, a blank line, the pinned randomization
    note, a blank line, then every version of this experiment with its
    full verbatim question text(s). Raises KeyError for an unknown
    experiment.
    """
    if blinded:
        return BLINDED_SYSTEM_LINE
    spec = experiments.EXPERIMENTS[experiment]
    head = (
        f"{BLINDED_SYSTEM_LINE}\n\n{UNBLINDING_PARAGRAPH}\n\n"
        f"{_version_block(spec, experiments.load_stimuli())}"
    )
    return head


def _option_lines(stimulus: dict) -> str:
    """The lettered answer options of a choice question, one per line.

    Renders the catalogue options verbatim ("A. more", "B. less", ...).
    Raises ValueError when the catalogue option count does not match the
    question's own label list (a broken survey file must stop the run,
    never render a wrong option table).
    """
    options = stimulus.get("options")
    labels = stimulus.get("labels")
    if options is None or labels is None:
        raise ValueError(
            f"{stimulus['qid']} is a choice question but carries no "
            "options/labels — refusing to render a made-up option table"
        )
    if len(options) != len(labels):
        raise ValueError(
            f"{stimulus['qid']} has {len(options)} options but "
            f"{len(labels)} labels — the survey file is inconsistent"
        )
    return "\n".join(
        f"{letter}. {option}" for letter, option in zip(labels, options)
    )


def _scale_lines(stimulus: dict) -> str | None:
    """The numbered answer scale of a digit item, one per line.

    Renders "1 = <label>", "2 = <label>", ... from the survey's own
    columns list (the number is the label's position, starting at 1), so
    the model knows what each answer number means instead of guessing.
    Returns None when the item carries no columns (a 0-9 estimate item),
    so the block is simply left out (never an error, never a made-up
    scale).
    """
    columns = stimulus.get("columns")
    if not columns:
        return None
    return "\n".join(
        f"{number} = {label}"
        for number, label in enumerate(columns, start=1)
    )


def _anchor_question_text(experiment: str, arm: str, item: dict,
                          stimuli: dict[str, dict]) -> str | None:
    """The arm's anchor question when a digit item must see it, else None.

    An anchoring arm asks a choice anchor question FIRST and the numeric
    estimate second; the estimate call must see that anchor (otherwise
    the low/high contrast is never measured), so its verbatim question
    text is returned for any digit item whose arm STARTS with a choice
    question. Arms that begin with the digit item itself (base_rate,
    false_consensus, ...) get None — their prompts stay unchanged.
    Only the question text is used; the anchor's letter options never
    render here (a digit item must be answered with a number).
    """
    if item["kind"] != "digit":
        return None
    items = experiments.arm_items(experiment, arm, stimuli)
    if not items or items[0]["kind"] != "choice":
        return None
    return stimuli[items[0]["qid"]]["question_text"]


def _item_user_prompt(persona: dict, experiment: str, arm: str,
                      item: dict, stimuli: dict[str, dict]) -> str:
    """The full user prompt for ONE first-token item of an arm.

    Shape: the EMBODY persona block, then (for a digit item whose arm
    starts with a choice anchor) that anchor's verbatim question as
    context, then the item itself — a choice item shows its verbatim
    question plus its lettered option lines and ends with the letter
    instruction; a digit item shows its verbatim question (and, for a
    split row, that row's statement), then the item's "N = label"
    answer scale when it has one, and ends with the single-number
    instruction. Each call therefore sees exactly one question to
    ANSWER — never another row's statement and never another item's
    option lines.
    """
    parts = [render_persona_block(persona)]
    anchor = _anchor_question_text(experiment, arm, item, stimuli)
    if anchor is not None:
        parts.append(anchor)
    parts.append(item["question_text"])
    if item["kind"] == "choice":
        parts.append(_option_lines(stimuli[item["qid"]]))
        parts.append(FINAL_INSTRUCTION)
        return "\n\n".join(parts)
    if item["statement"] is not None:
        parts.append(item["statement"])
    scale = _scale_lines(stimuli[item["qid"]])
    if scale is not None:
        parts.append(scale)
    parts.append(NUMERIC_INSTRUCTION)
    return "\n\n".join(parts)


def build_user_prompt(persona: dict, experiment: str, arm: str,
                      item: dict | None = None) -> str:
    """The user prompt for one persona answering one experiment arm.

    With item= (the normal path since every answer is one first-token
    call): that single item's prompt — see _item_user_prompt. With
    item=None: the arm's whole-question rendering, which only exists
    for arms whose every item is the same single choice question; an
    arm holding digit items has NO single prompt (asking for one would
    rebuild the banned answer-everything-at-once shape), so it raises
    ValueError instead of rendering a made-up prompt. Raises KeyError
    for an unknown experiment or arm.
    """
    stimuli = experiments.load_stimuli()
    if item is not None:
        return _item_user_prompt(persona, experiment, arm, item, stimuli)
    items = experiments.arm_items(experiment, arm, stimuli)
    if any(one["kind"] == "digit" for one in items):
        raise ValueError(
            f"experiment {experiment!r} arm {arm!r} has digit items, "
            "which are asked one per call on their own prompts — render "
            "each item with build_user_prompt(..., item=item)"
        )
    parts = [render_persona_block(persona)]
    for one in items:
        parts.append(one["question_text"])
        parts.append(_option_lines(stimuli[one["qid"]]))
    parts.append(FINAL_INSTRUCTION)
    return "\n\n".join(parts)
