# This file is the study's experiment register: it lists the six Twin2K
# survey experiments, and for each one the experimental versions (arms) in
# their pinned order, which Qualtrics question id belongs to each arm, how
# many answer letters (A, B, C, ...) the question shows, what each letter
# is worth on the scored scale, and which record field carries the scored
# outcome. It also loads the shipped survey-question file so prompts and
# scoring always read the exact same question texts. The one special case
# is the disease experiment, whose "safe" side pools the first three
# letters (Program A options).

import json
from dataclasses import dataclass

from twin2k6 import config


def _letters(count: int) -> tuple[str, ...]:
    """The first `count` uppercase letters, A onward (A, B, C, ...)."""
    return tuple(chr(ord("A") + i) for i in range(count))


@dataclass(frozen=True)
class ExperimentSpec:
    """One experiment's frozen description.

    Fields:
      name         — the experiment's short name (e.g. "disease");
      arms         — (arm_name, question_id) pairs in the pinned version
                     order (the order the unblinded prompt lists them);
      label_count  — how many answer letters the question shows;
      value_start  — what the first letter is worth on the scored scale
                     (disease A=1 ... F=6, but sunk cost A=0 ... U=20);
      outcome_field— the record key the expected value is written to;
      safe_letters — disease only: the letters pooled into the "safe"
                     probability; every other experiment leaves it None.

    Derived helpers:
      label_letters — the tuple of answer letters (A up to label_count);
      label_values  — each letter's worth on the scored scale.
    """

    name: str
    arms: tuple[tuple[str, str], ...]
    label_count: int
    value_start: int
    outcome_field: str
    safe_letters: tuple[str, ...] | None = None

    @property
    def label_letters(self) -> tuple[str, ...]:
        """The answer letters shown on the question, A onward."""
        return _letters(self.label_count)

    @property
    def label_values(self) -> dict[str, int]:
        """Each answer letter's worth on the experiment's scored scale."""
        return {
            letter: self.value_start + offset
            for offset, letter in enumerate(self.label_letters)
        }


def _spec(name: str, arms: tuple[tuple[str, str], ...], label_count: int,
          value_start: int, outcome_field: str,
          safe_letters: tuple[str, ...] | None = None) -> ExperimentSpec:
    """Build one ExperimentSpec with its name filled in (small helper)."""
    return ExperimentSpec(
        name=name, arms=arms, label_count=label_count,
        value_start=value_start, outcome_field=outcome_field,
        safe_letters=safe_letters,
    )


# The study's six experiments. Arm order is the unblinded version-list
# order and must never change — record counts, prompts and contrasts all
# depend on it.
EXPERIMENTS: dict[str, ExperimentSpec] = {
    "disease": _spec(
        "disease",
        arms=(("gain", "QID157"), ("loss", "QID158")),
        label_count=6, value_start=1, outcome_field="expected_1_6",
        safe_letters=("A", "B", "C"),  # Program A side = scale codes 1-3
    ),
    "less_is_more": _spec(
        "less_is_more",
        arms=(("A", "QID171"), ("B", "QID172"), ("C", "QID173")),
        label_count=5, value_start=1, outcome_field="expected_1_5",
    ),
    "fire_extinguisher": _spec(
        "fire_extinguisher",
        arms=(("all", "QID174"), ("98pct", "QID175"), ("95pct", "QID176")),
        label_count=5, value_start=1, outcome_field="expected_1_5",
    ),
    "seatbelt": _spec(
        "seatbelt",
        arms=(("all", "QID177"), ("98pct", "QID178"), ("95pct", "QID179")),
        label_count=6, value_start=1, outcome_field="expected_1_6",
    ),
    "sunk_cost": _spec(
        "sunk_cost",
        arms=(("no_card", "QID181"), ("card", "QID182")),
        label_count=21, value_start=0, outcome_field="expected_0_20",
    ),
    "wta_wtp": _spec(
        "wta_wtp",
        arms=(
            ("wtp_certainty", "QID189"),
            ("wta_certainty", "QID190"),
            ("wtp_noncertainty", "QID191"),
        ),
        label_count=10, value_start=1, outcome_field="expected_bracket_1_10",
    ),
}


def load_stimuli() -> dict[str, dict]:
    """Read the shipped survey-question file, keyed by question id.

    Returns a dict mapping each QID (e.g. "QID157") to its verbatim
    stimulus entry (question text, catalogue options, experiment/arm
    bookkeeping). Raises FileNotFoundError when the shipped file is
    missing and json.JSONDecodeError when it does not parse.
    """
    with open(config.STIMULI_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    return {stimulus["qid"]: stimulus for stimulus in data["stimuli"]}


def stimulus_for(experiment: str, arm: str, stimuli: dict[str, dict] | None = None
                 ) -> dict:
    """The verbatim survey-question entry for one experiment arm.

    Looks up the arm's question id in the registry, then its entry in the
    stimuli (loaded fresh when not supplied). Raises KeyError when the arm
    or question id is unknown.
    """
    spec = EXPERIMENTS[experiment]
    qid = dict(spec.arms)[arm]
    stimuli = stimuli if stimuli is not None else load_stimuli()
    return stimuli[qid]
