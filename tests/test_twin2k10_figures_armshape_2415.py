# Locked RED tests for the twin2k10 figures arm-value SHAPE fix (TASK-2415;
# tests ONLY — the fix in scripts/twin2k10/figures_metrics.py does not
# exist yet, so every test below must fail on the missing fix, never on a
# typo here).
#
# WHAT THIS FILE CHECKS, in plain words:
#   The figure code (compute_error_rows and everything that reads one
#   arm's value) must accept arm values in BOTH shapes:
#     - a plain number (the old shape: {arm: 0.75}), and
#     - the builder's dict shape ({arm: {"mean": 0.75}} or
#       {arm: {"mean": 0.75, "n": 100}}), where the comparable number
#       lives under the "mean" key.
#   Today the dict shape yields ZERO model rows (only HUMAN rows reach
#   the CSVs), because a dict arm value is read as "no comparable
#   number" and the whole model row is silently dropped. The fix must
#   make model rows appear for every model with valid means, with the
#   same hand-computable numbers the float shape would give.
#
# Everything runs offline on a small synthetic registry subset plus fake
# arm means. No real run directory is read.
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import figures_metrics  # noqa: E402


# ---------------------------------------------------------------- fixtures
def _armshape_registry():
    """A tiny hand-written registry subset: one experiment (sunk_cost,
    raw 0-20 purchases) whose human effect is a plain raw-scale number.
    The human arms are floats — the human side never changes."""
    return {
        "sunk_cost": {
            "normalization_0_1": {"min": 0, "max": 20},
            "human": {
                "wave1_3": {
                    "arms": {"no_card": 12.0, "card": 8.0},
                    "contrasts": {
                        "card_minus_no_card": {"computable": True, "value": -4.0},
                    },
                },
                "wave4": {
                    "arms": {"no_card": 12.0, "card": 8.0},
                    "contrasts": {
                        "card_minus_no_card": {"computable": True, "value": -4.0},
                    },
                },
            },
        },
    }


def _armshape_llm_means():
    """Fake model arm means in the BUILDER's dict shape:
    {model: {experiment: {blinding: {arm: {"mean": x, "n": k}}}}}.
    Hand arithmetic:
      - gpt-oss-20b: matches the humans exactly on the 0-1 scale
        (effect (8-12)/20 = -0.2) -> Profile 0.0, effect 0.0.
      - qwen3-32b: card arm 1 raw point HIGHER -> model effect
        (9-12)/20 = -0.15 vs the humans' -0.2 -> effect error 5.0;
        profile gaps 0.0 and 0.05 -> Profile 2.5.
      - glm-4.7-flash: OLD float shape — must keep working unchanged.
    """
    return {
        "gpt-oss-20b": {
            "sunk_cost": {
                "blinded": {
                    "no_card": {"mean": 12.0, "n": 100},
                    "card": {"mean": 8.0, "n": 100},
                },
                "unblinded": {
                    "no_card": {"mean": 12.0, "n": 100},
                    "card": {"mean": 8.0, "n": 100},
                },
            },
        },
        "qwen3-32b": {
            "sunk_cost": {
                "blinded": {
                    "no_card": {"mean": 12.0},
                    "card": {"mean": 9.0},
                },
                "unblinded": {
                    "no_card": {"mean": 12.0},
                    "card": {"mean": 9.0},
                },
            },
        },
        "glm-4.7-flash": {
            "sunk_cost": {
                "blinded": {"no_card": 12.0, "card": 8.0},
                "unblinded": {"no_card": 12.0, "card": 8.0},
            },
        },
    }


def _rows():
    return figures_metrics.compute_error_rows(
        _armshape_registry(), _armshape_llm_means()
    )


# --------------------------------------------- builder dict shape accepted
def test_model_rows_appear_for_builder_dict_shape():
    """THE BUG: with the builder's {mean, n} arm dicts, every model must
    still get a row (today the dict arms are read as 'no comparable
    number' and ALL model rows vanish — only HUMAN rows survive)."""
    seen = {(r.model, r.experiment) for r in _rows()}
    for model in ("gpt-oss-20b", "qwen3-32b"):
        assert (model, "sunk_cost") in seen, (
            f"{model} lost its row because its dict-shaped arm values "
            "were treated as incomparable (the bug)"
        )


def test_mean_and_n_dict_arms_give_hand_computable_profile_error():
    """A model whose dict-shaped arms match the humans exactly gets a
    Profile Error of 0.0 — the 'mean' key is read, not the whole dict
    thrown away."""
    row = next(
        r for r in _rows() if r.model == "gpt-oss-20b"
    )
    assert row.profile_error_blinded is not None, (
        "dict-shaped arms yielded no Profile Error (the bug)"
    )
    assert row.profile_error_blinded == pytest.approx(0.0)
    assert row.profile_error_unblinded == pytest.approx(0.0)


def test_mean_only_dict_arms_give_hand_computable_errors():
    """A model using {"mean": x} without "n" is also accepted, and the
    numbers are hand-computable: card arm 1 raw point high -> normalized
    effect off by 0.05 -> effect error 5.0; profile gaps 0.0 and 0.05 ->
    Profile 2.5."""
    row = next(r for r in _rows() if r.model == "qwen3-32b")
    assert row.profile_error_blinded == pytest.approx(2.5)
    assert row.contrast_error == pytest.approx(5.0)


def test_mixed_float_and_dict_arms_in_one_experiment():
    """One experiment may mix shapes across models (some models still on
    floats, some on dicts). All three models must produce rows, and the
    float model's numbers must be exactly what they always were."""
    by_model = {r.model: r for r in _rows()}
    assert by_model["gpt-oss-20b"].profile_error_blinded == pytest.approx(0.0)
    assert by_model["gpt-oss-20b"].contrast_error == pytest.approx(0.0)
    assert by_model["qwen3-32b"].profile_error_blinded == pytest.approx(2.5)
    assert by_model["qwen3-32b"].contrast_error == pytest.approx(5.0)
    # The float-shape model keeps its old, unchanged numbers:
    assert by_model["glm-4.7-flash"].profile_error_blinded == pytest.approx(0.0)
    assert by_model["glm-4.7-flash"].contrast_error == pytest.approx(0.0)


def test_float_arm_values_behavior_unchanged():
    """REGRESSION GUARD: the old float shape keeps its exact behaviour —
    a matching model still gets Profile 0.0 / effect 0.0 and no row is
    added, dropped, or renumbered."""
    rows = [r for r in _rows() if r.model == "glm-4.7-flash"]
    assert len(rows) == 1
    assert rows[0].method == "arm_mean"
    assert rows[0].profile_error_blinded == pytest.approx(0.0)
    assert rows[0].contrast_error == pytest.approx(0.0)
