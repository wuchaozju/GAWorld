# Locked tests for the twin2k6 study's experiment registry (TASK-2060 RED
# phase; tests ONLY — no implementation lives here yet).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - Exactly six Twin2K experiments are registered, under these names.
#   - Each experiment pins its arms (in the exact version-list order), the
#     Qualtrics question id per arm, the answer letters (A, B, C, ...) and
#     what each letter is worth on the scored scale (disease: A=1..F=6;
#     sunk cost: A=0..U=20; WTA/WTP brackets: A=1..J=10; and so on).
#   - The scored outcome field name per experiment (expected_1_6 etc.) and
#     disease's "safe" side (letters A, B, C = codes 1-3) are pinned.
#   - The registry agrees with the shipped stimuli file: every arm's QID
#     exists there, and multiple-choice options match the label count.
#
# All offline: pure registry checks plus reads of the shipped data file.
import sys
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import config, experiments  # noqa: E402

EXPECTED_EXPERIMENT_NAMES = {
    "disease", "less_is_more", "fire_extinguisher",
    "seatbelt", "sunk_cost", "wta_wtp",
}

# experiment -> [(arm, QID), ...] in the pinned version-list order.
EXPECTED_ARMS = {
    "disease": [("gain", "QID157"), ("loss", "QID158")],
    "less_is_more": [("A", "QID171"), ("B", "QID172"), ("C", "QID173")],
    "fire_extinguisher": [("all", "QID174"), ("98pct", "QID175"), ("95pct", "QID176")],
    "seatbelt": [("all", "QID177"), ("98pct", "QID178"), ("95pct", "QID179")],
    "sunk_cost": [("no_card", "QID181"), ("card", "QID182")],
    "wta_wtp": [
        ("wtp_certainty", "QID189"),
        ("wta_certainty", "QID190"),
        ("wtp_noncertainty", "QID191"),
    ],
}

# experiment -> scored-outcome field name written into every record.
EXPECTED_OUTCOME_FIELDS = {
    "disease": "expected_1_6",
    "less_is_more": "expected_1_5",
    "fire_extinguisher": "expected_1_5",
    "seatbelt": "expected_1_6",
    "sunk_cost": "expected_0_20",
    "wta_wtp": "expected_bracket_1_10",
}

# experiment -> how many answer letters each question shows.
EXPECTED_LABEL_COUNTS = {
    "disease": 6, "less_is_more": 5, "fire_extinguisher": 5,
    "seatbelt": 6, "sunk_cost": 21, "wta_wtp": 10,
}

# experiment -> (first letter, first value, last value) of the letter scale.
EXPECTED_SCALE_EDGES = {
    "disease": ("A", 1, 6),
    "less_is_more": ("A", 1, 5),
    "fire_extinguisher": ("A", 1, 5),
    "seatbelt": ("A", 1, 6),
    "sunk_cost": ("A", 0, 20),
    "wta_wtp": ("A", 1, 10),
}


def _letters(count):
    """The first `count` uppercase letters, A onward (helper)."""
    return [chr(ord("A") + i) for i in range(count)]


def test_exactly_six_experiments_are_registered():
    """The registry holds the six Twin2K experiments and nothing else."""
    assert set(experiments.EXPERIMENTS.keys()) == EXPECTED_EXPERIMENT_NAMES


def test_every_experiment_pins_its_arms_and_qids_in_version_order():
    """Arm order matters (it is the unblinded version-list order)."""
    for exp_name, expected_arms in EXPECTED_ARMS.items():
        spec = experiments.EXPERIMENTS[exp_name]
        got = [(arm_name, qid) for arm_name, qid in spec.arms]
        assert got == expected_arms, f"{exp_name} arms/qids/order are pinned"


def test_sixteen_arms_across_all_experiments():
    """2+3+3+3+2+3 = 16 arms (per-model total math depends on this)."""
    total = sum(len(spec.arms) for spec in experiments.EXPERIMENTS.values())
    assert total == 16


def test_label_letters_are_plain_uppercase_letters():
    """Answers are lettered A, B, C, ... with the pinned counts."""
    for exp_name, count in EXPECTED_LABEL_COUNTS.items():
        spec = experiments.EXPERIMENTS[exp_name]
        assert list(spec.label_letters) == _letters(count), exp_name


def test_label_values_map_letters_to_the_pinned_scale():
    """Letter worth: disease A=1..F=6, sunk cost A=0..U=20, brackets A=1..J=10."""
    for exp_name, (first_letter, first_value, last_value) in EXPECTED_SCALE_EDGES.items():
        spec = experiments.EXPERIMENTS[exp_name]
        values = [spec.label_values[letter] for letter in spec.label_letters]
        assert values[0] == first_value, f"{exp_name}: first letter must be worth {first_value}"
        assert values[-1] == last_value, f"{exp_name}: last letter must be worth {last_value}"
        assert values == list(range(first_value, last_value + 1)), (
            f"{exp_name}: letter values must step by 1 across the scale"
        )


def test_scored_outcome_field_names_are_pinned():
    """Records carry the study's named outcome fields (expected_1_6 etc.)."""
    for exp_name, field in EXPECTED_OUTCOME_FIELDS.items():
        assert experiments.EXPERIMENTS[exp_name].outcome_field == field, exp_name


def test_disease_safe_side_is_letters_A_B_C():
    """p_safe pools the Program-A side: letters A, B, C (codes 1-3)."""
    spec = experiments.EXPERIMENTS["disease"]
    assert tuple(spec.safe_letters) == ("A", "B", "C")


def test_only_disease_declares_a_safe_side():
    """The p_safe split is a disease-specific concept; no one else has it."""
    for exp_name in EXPECTED_EXPERIMENT_NAMES - {"disease"}:
        spec = experiments.EXPERIMENTS[exp_name]
        assert not hasattr(spec, "safe_letters") or spec.safe_letters is None, exp_name


def test_every_registered_arm_exists_in_the_shipped_stimuli():
    """Each arm's QID must exist in the repo stimuli copy (no dangling arms)."""
    import json

    with open(config.STIMULI_PATH) as f:
        stimuli = json.load(f)
    by_qid = {s["qid"]: s for s in stimuli["stimuli"]}
    for exp_name, expected_arms in EXPECTED_ARMS.items():
        for _arm, qid in expected_arms:
            assert qid in by_qid, f"{exp_name}: {qid} missing from stimuli copy"
            entry = by_qid[qid]
            assert entry["experiment"] == exp_name, (
                f"{qid} registered under {exp_name} but stimuli says {entry['experiment']}"
            )


def test_multiple_choice_options_match_the_label_count():
    """Lettered questions need exactly one catalogue option per letter."""
    import json

    with open(config.STIMULI_PATH) as f:
        stimuli = json.load(f)
    by_qid = {s["qid"]: s for s in stimuli["stimuli"]}
    for exp_name, expected_arms in EXPECTED_ARMS.items():
        count = EXPECTED_LABEL_COUNTS[exp_name]
        for _arm, qid in expected_arms:
            options = by_qid[qid]["options"]
            if exp_name == "sunk_cost":
                assert options is None, "sunk cost is text-entry; no catalogue options"
            else:
                assert options is not None and len(options) == count, (
                    f"{qid}: expected {count} options, found {options!r}"
                )
