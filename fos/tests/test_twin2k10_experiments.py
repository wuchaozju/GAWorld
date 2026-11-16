# Locked tests for the twin2k10 study's experiment register (TASK-2139 RED
# phase; item-mix contract amended by the TASK-2182 design pivot).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - The study registers exactly its 10 experiments, and every one of the
#     23 survey questions is registered under the right experiment.
#   - The experimental versions (arms) of every experiment match the
#     authoritative stimuli file, including each arm's question ids in file
#     order — the two anchoring arms each carry TWO questions (the
#     more/less anchor choice and the numeric estimate).
#   - Choice questions show exactly as many A, B, C... letters as they have
#     answer options.
#   - false_consensus is the one within-subject experiment: a single arm
#     whose question has 10 rows.
#   - TASK-2182 pivot: arm_items(experiment, arm) describes WHAT one cell
#     measures as first-token items — choice items keep the letter table,
#     every numeric-kind question becomes ONE digit item over "0".."9"
#     (the first significant digit), and every multi-row item splits into
#     one single-policy digit item per row on the item's own scale. No arm
#     ever samples free text again.
#
# All offline: reads the study's own loaded stimuli; no network, no models.
import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import experiments  # noqa: E402

# The 10 experiment names, pinned by the task.
EXPECTED_EXPERIMENT_NAMES = {
    "allais", "linda", "base_rate", "anchoring_redwood",
    "anchoring_african", "outcome_bias", "myside", "prob_matching",
    "abs_relative", "false_consensus",
}


def _stimuli() -> dict[str, dict]:
    """The study's own loaded stimuli, keyed by question id (helper)."""
    return experiments.load_stimuli()


def _stimulus_arm_qids() -> dict[tuple[str, str], list[str]]:
    """Every (experiment, arm) with its question ids in file order (helper)."""
    entries = _stimuli().values()
    pairs: dict[tuple[str, str], list[str]] = {}
    for entry in sorted(entries, key=lambda e: e["qid"]):
        pairs.setdefault(
            (entry["experiment"], entry["arm"]), []
        ).append(entry["qid"])
    return pairs


def _spec_arm_qids(spec) -> dict[str, tuple[str, ...]]:
    """An experiment's arm -> question-ids mapping, normalized (helper).

    The registry may store an arm's questions as one id or a tuple; both
    normalize to a tuple here so the tests stay about behaviour, not shape.
    """
    arms: dict[str, tuple[str, ...]] = {}
    for arm_name, qids in spec.arms:
        if isinstance(qids, str):
            arms[arm_name] = (qids,)
        else:
            arms[arm_name] = tuple(qids)
    return arms


def test_the_study_registers_exactly_its_ten_experiments() -> None:
    """EXPERIMENTS holds exactly the 10 study experiments, none else."""
    assert set(experiments.EXPERIMENTS) == EXPECTED_EXPERIMENT_NAMES
    assert len(experiments.EXPERIMENTS) == 10


def test_loading_stimuli_returns_exactly_the_23_questions() -> None:
    """load_stimuli reads the shipped file and indexes it by question id."""
    stimuli = _stimuli()
    assert len(stimuli) == 23
    assert all(qid.startswith("QID") for qid in stimuli)


def test_every_question_is_registered_under_its_experiment() -> None:
    """All 23 question ids appear across the registry, each exactly once."""
    registered: list[str] = []
    for spec in experiments.EXPERIMENTS.values():
        for qids in _spec_arm_qids(spec).values():
            registered.extend(qids)
    assert len(registered) == 23
    assert set(registered) == set(_stimuli())


def test_arms_match_the_stimuli_file_exactly() -> None:
    """Every experiment's arms and their question ids match the file."""
    file_arms = _stimulus_arm_qids()
    for exp_name, spec in experiments.EXPERIMENTS.items():
        spec_arms = _spec_arm_qids(spec)
        file_qids = {
            arm: tuple(qids) for (experiment, arm), qids in file_arms.items()
            if experiment == exp_name
        }
        assert spec_arms == file_qids, exp_name


def test_anchoring_arms_carry_both_the_anchor_choice_and_the_estimate() -> None:
    """Each anchoring arm holds TWO questions: the MC anchor, then the TE."""
    for exp_name in ("anchoring_redwood", "anchoring_african"):
        spec = experiments.EXPERIMENTS[exp_name]
        arms = _spec_arm_qids(spec)
        assert set(arms) == {"low", "high"}, exp_name
        for arm in ("low", "high"):
            qids = arms[arm]
            assert len(qids) == 2, (exp_name, arm)
            kinds = [_stimuli()[qid]["response_kind"] for qid in qids]
            assert kinds == ["choice", "numeric"], (exp_name, arm)


def test_choice_letters_match_the_number_of_answer_options() -> None:
    """Every choice question shows A, B, ... up to its option count."""
    stimuli = _stimuli()
    for entry in stimuli.values():
        if entry["response_kind"] != "choice":
            continue
        options = entry["options"]
        letters = entry["labels"]
        expected = [chr(ord("A") + i) for i in range(len(options))]
        assert letters == expected, entry["qid"]
        assert len(options) == len(entry["labels"]), entry["qid"]


def test_false_consensus_is_within_subject_with_one_arm_and_ten_rows() -> None:
    """The one within-subject experiment: single arm, 10-row question."""
    spec = experiments.EXPERIMENTS["false_consensus"]
    arms = _spec_arm_qids(spec)
    assert list(arms) == ["all"]
    qid = arms["all"][0]
    assert len(_stimuli()[qid]["rows"]) == 10


def test_stimulus_for_returns_the_right_question_for_an_arm() -> None:
    """stimulus_for(experiment, arm) lands on one of that arm's questions."""
    stimulus = experiments.stimulus_for("allais", "form1")
    assert stimulus["qid"] in {"QID192", "QID193"}
    assert stimulus["experiment"] == "allais"


# ---------------------------------------------------------------------------
# TASK-2182 design pivot — the first-token item mix of every arm.
# arm_items(experiment, arm) returns one descriptor per first-token item
# of the arm, in survey order. Each descriptor carries: qid, kind
# ("choice" or "digit"), labels (the answer tokens that fold), the
# verbatim question_text, and — for items split out of a multi-row
# question — the 1-based row number and that row's verbatim statement.
# ---------------------------------------------------------------------------


def test_false_consensus_arm_is_ten_single_policy_digit_items() -> None:
    """The 10 policies are 10 separate one-rating-per-call items.

    Each call asks the rating for ONE policy on its 1–5 scale, so every
    item carries its own row number and verbatim statement, and the
    labels are exactly the scale positions "1".."5".
    """
    items = experiments.arm_items("false_consensus", "all")
    assert len(items) == 10
    rows = _stimuli()["QID287"]["rows"]
    for number, item in enumerate(items, start=1):
        assert item["kind"] == "digit", number
        assert item["qid"] == "QID287"
        assert item["row"] == number
        assert item["statement"] == rows[number - 1], number
        assert item["labels"] == ("1", "2", "3", "4", "5")


def test_multi_row_items_split_with_their_own_scales() -> None:
    """Linda and prob_matching rows become digit items on their scales.

    Sampling is deleted, so EVERY multi-row item splits per row: linda's
    three statements on its 6-point scale, prob_matching's shuffle rows
    on the two-answer "1"/"2" scale.
    """
    linda = experiments.arm_items("linda", "conjunction")
    assert [item["kind"] for item in linda] == ["digit"] * 3
    assert [item["labels"] for item in linda] == [tuple("123456")] * 3
    assert [item["statement"] for item in linda] \
        == _stimuli()["QID160"]["rows"]
    problem1 = experiments.arm_items("prob_matching", "problem1")
    problem2 = experiments.arm_items("prob_matching", "problem2")
    assert len(problem1) == 10 and len(problem2) == 6
    for item in problem1 + problem2:
        assert item["kind"] == "digit"
        assert item["labels"] == ("1", "2"), item


def test_numeric_questions_become_one_digit_item_over_zero_to_nine() -> None:
    """A numeric question keeps its verbatim text, answered 0-9.

    The estimate question is asked once, deterministically, and scored by
    the first significant digit — no sampling, no free-text parse.
    """
    cases = [
        ("base_rate", "30_engineers", "QID154"),
        ("base_rate", "70_engineers", "QID156"),
        ("anchoring_redwood", "low", "QID168"),
        ("anchoring_redwood", "high", "QID170"),
        ("anchoring_african", "low", "QID164"),
        ("anchoring_african", "high", "QID166"),
    ]
    for experiment, arm, qid in cases:
        digit_items = [item for item in experiments.arm_items(experiment, arm)
                       if item["kind"] == "digit" and item["qid"] == qid]
        assert len(digit_items) == 1, (experiment, arm)
        item = digit_items[0]
        assert item["labels"] == tuple("0123456789"), (experiment, arm)
        assert item["row"] is None and item["statement"] is None
        assert item["question_text"] == _stimuli()[qid]["question_text"]


def test_anchoring_arms_are_one_mc_item_plus_one_digit_item() -> None:
    """Each anchoring arm measures the anchor choice, then the estimate."""
    for experiment in ("anchoring_redwood", "anchoring_african"):
        for arm in ("low", "high"):
            items = experiments.arm_items(experiment, arm)
            assert [item["kind"] for item in items] == ["choice", "digit"], \
                (experiment, arm)


def test_choice_only_arms_keep_exactly_one_choice_item() -> None:
    """The pure-choice experiments are unchanged: one letter item each."""
    for experiment in ("allais", "outcome_bias", "myside", "abs_relative"):
        for arm, _qids in experiments.EXPERIMENTS[experiment].arms:
            items = experiments.arm_items(experiment, arm)
            assert len(items) == 1, (experiment, arm)
            assert items[0]["kind"] == "choice"
            qid = experiments.EXPERIMENTS[experiment].arm_qids(arm)[0]
            assert items[0]["labels"] == tuple(_stimuli()[qid]["labels"])
            assert items[0]["row"] is None and items[0]["statement"] is None


def test_every_arm_of_the_study_has_at_least_one_first_token_item() -> None:
    """No arm is left unmeasured by the pivot."""
    for experiment, spec in experiments.EXPERIMENTS.items():
        for arm, _qids in spec.arms:
            items = experiments.arm_items(experiment, arm)
            assert items, (experiment, arm)
            assert all(item["kind"] in ("choice", "digit")
                       for item in items), (experiment, arm)
