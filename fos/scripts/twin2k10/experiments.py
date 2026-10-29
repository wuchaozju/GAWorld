# This file is the twin2k10 study's experiment register: it lists the ten
# Twin2K survey experiments, and for each one the experimental versions
# (arms) with the question ids that belong to each arm. Nine experiments
# are between-subjects with two arms; false_consensus is the one
# within-subject experiment (a single "all" arm whose question has 10
# rows). The two anchoring experiments are special: each of their arms
# carries TWO questions — the more/less anchor choice first, then the
# numeric estimate. The file also translates each arm into its FIRST-TOKEN
# ITEMS (arm_items): the exact list of single-answer calls the study makes
# — one letter item for a choice question, one digit item (0-9) for a
# numeric estimate, and one digit item PER ROW for a multi-row question,
# each on the row's own answer scale. The file also loads the shipped
# survey-question file so prompts and scoring always read the exact same
# question texts.

import json
from dataclasses import dataclass

from twin2k10 import config


@dataclass(frozen=True)
class ExperimentSpec:
    """One experiment's frozen description.

    Fields:
      name — the experiment's short name (e.g. "allais");
      arms — (arm_name, question_ids) pairs in pinned order; question_ids
             is a tuple holding ONE question id for every experiment
             except the two anchoring ones, whose arms each hold TWO ids
             in survey order (the anchor choice first, the numeric
             estimate second).

    Derived helper:
      qids — every question id of the experiment, arm by arm.
    """

    name: str
    arms: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def qids(self) -> tuple[str, ...]:
        """Every question id of the experiment, in arm order."""
        return tuple(qid for _arm, arm_qids in self.arms for qid in arm_qids)

    def arm_qids(self, arm: str) -> tuple[str, ...]:
        """One arm's question ids in survey order (KeyError on a bad arm)."""
        return dict(self.arms)[arm]


# The study's ten experiments. Arm order is the unblinded version-list
# order and must never change — record counts, prompts and contrasts all
# depend on it. Question ids inside an arm stay in survey file order (for
# anchoring arms that means the anchor choice, then the numeric estimate).
EXPERIMENTS: dict[str, ExperimentSpec] = {
    "allais": ExperimentSpec(
        "allais",
        arms=(("form1", ("QID192",)), ("form2", ("QID193",))),
    ),
    "linda": ExperimentSpec(
        "linda",
        arms=(("conjunction", ("QID160",)), ("no_conjunction", ("QID159",))),
    ),
    "base_rate": ExperimentSpec(
        "base_rate",
        arms=(("30_engineers", ("QID154",)), ("70_engineers", ("QID156",))),
    ),
    "anchoring_redwood": ExperimentSpec(
        "anchoring_redwood",
        arms=(
            ("low", ("QID167", "QID168")),
            ("high", ("QID169", "QID170")),
        ),
    ),
    "anchoring_african": ExperimentSpec(
        "anchoring_african",
        arms=(
            ("low", ("QID163", "QID164")),
            ("high", ("QID165", "QID166")),
        ),
    ),
    "outcome_bias": ExperimentSpec(
        "outcome_bias",
        arms=(("success", ("QID161",)), ("failure", ("QID162",))),
    ),
    "myside": ExperimentSpec(
        "myside",
        arms=(("ford", ("QID194",)), ("german", ("QID195",))),
    ),
    "prob_matching": ExperimentSpec(
        "prob_matching",
        arms=(("problem1", ("QID198",)), ("problem2", ("QID203",))),
    ),
    "abs_relative": ExperimentSpec(
        "abs_relative",
        arms=(("calculator", ("QID183",)), ("jacket", ("QID184",))),
    ),
    "false_consensus": ExperimentSpec(
        "false_consensus",
        arms=(("all", ("QID287",)),),
    ),
}


def load_stimuli() -> dict[str, dict]:
    """Read the shipped survey-question file, keyed by question id.

    Accepts either a bare JSON list of entries or a dict carrying them
    under a "stimuli" key (the two shapes the research deliveries use).
    Returns a dict mapping each QID (e.g. "QID192") to its verbatim
    stimulus entry. Raises FileNotFoundError when the shipped file is
    missing and json.JSONDecodeError when it does not parse.
    """
    with open(config.STIMULI_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    entries = data["stimuli"] if isinstance(data, dict) else data
    return {stimulus["qid"]: stimulus for stimulus in entries}


def stimulus_for(experiment: str, arm: str,
                 stimuli: dict[str, dict] | None = None) -> dict:
    """The first question entry of one experiment arm (anchor choice first).

    Looks up the arm's first question id in the registry, then its entry
    in the stimuli (loaded fresh when not supplied). Raises KeyError when
    the experiment or arm is unknown.
    """
    first_qid = EXPERIMENTS[experiment].arm_qids(arm)[0]
    stimuli = stimuli if stimuli is not None else load_stimuli()
    return stimuli[first_qid]


def label_letters(experiment: str,
                  stimuli: dict[str, dict] | None = None) -> tuple[str, ...]:
    """The answer letters (A, B, ...) of an experiment's choice questions.

    Read from the experiment's first choice-kind question entry's own
    "labels" list, so the letters always match the shipped survey file.
    Raises ValueError when the experiment has no choice question at all
    (its records carry no letter scoring to look up).
    """
    stimuli = stimuli if stimuli is not None else load_stimuli()
    for qid in EXPERIMENTS[experiment].qids:
        if stimuli[qid]["response_kind"] == "choice":
            return tuple(stimuli[qid]["labels"])
    raise ValueError(
        f"experiment {experiment!r} has no choice question, so it has no "
        "answer letters to score"
    )


def arm_items(experiment: str, arm: str,
              stimuli: dict[str, dict] | None = None) -> list[dict]:
    """One first-token item descriptor per single-answer call of an arm.

    The study measures every question with deterministic first-token
    calls, so an arm becomes a list of items in survey order: a choice
    question is ONE item scored on its letter labels; a numeric question
    is ONE digit item scored on "0".."9" (the first significant digit);
    a multi-row question splits into one digit item PER ROW, each on the
    row's own answer scale (the scale's positions as text). Each
    descriptor carries: qid, kind ("choice" or "digit"), labels (the
    answer tokens that fold), the verbatim question_text, and — for a
    split row — the 1-based row number and that row's verbatim
    statement. The shipped stimuli file is only ever READ: the split is
    derived here, never by editing the data. Raises KeyError for an
    unknown experiment or arm.
    """
    stimuli = stimuli if stimuli is not None else load_stimuli()
    items: list[dict] = []
    for qid in EXPERIMENTS[experiment].arm_qids(arm):
        stimulus = stimuli[qid]
        kind = stimulus["response_kind"]
        if kind == "choice":
            items.append({
                "qid": qid, "kind": "choice",
                "labels": tuple(stimulus["labels"]),
                "question_text": stimulus["question_text"],
                "row": None, "statement": None,
            })
        elif kind == "numeric":
            items.append({
                "qid": qid, "kind": "digit",
                "labels": tuple("0123456789"),
                "question_text": stimulus["question_text"],
                "row": None, "statement": None,
            })
        else:
            items.extend(_row_items(qid, stimulus))
    return items


def _row_items(qid: str, stimulus: dict) -> list[dict]:
    """One digit item per row of a multi-row question (helper for arm_items).

    The labels are the answer-scale positions as text ("1", "2", ... one
    per column), the row number is 1-based in file order, and the
    statement is that row's verbatim text.
    """
    labels = tuple(str(number)
                   for number in range(1, len(stimulus["columns"]) + 1))
    return [
        {
            "qid": qid, "kind": "digit", "labels": labels,
            "question_text": stimulus["question_text"],
            "row": number, "statement": statement,
        }
        for number, statement in enumerate(stimulus["rows"], start=1)
    ]
