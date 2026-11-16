# Locked RED tests for the twin2k10 figures "means" WRAPPER fix
# (TASK-2417; tests ONLY — the fix in scripts/twin2k10/figures_metrics.py
# does not exist yet, so every new test below must fail on the missing
# fix, never on a typo here).
#
# WHAT THIS FILE CHECKS, in plain words:
#   The REAL builder output (llm_arm_means.json) wraps each blinding
#   condition's arms inside a "means" key, with a sibling "n" key:
#     {model: {experiment: {"blinded": {"means": {arm: 0.81}, "n": {arm: 100}}}}}
#   Today compute_error_rows walks the blinding dict's items and sees
#   "means" and "n" as if they were ARM NAMES — so every model row comes
#   back all-None (zero usable model rows). The fix must unwrap the
#   "means" sub-dict when it is present, and then read each arm's value
#   in any already-supported shape (plain float, {"mean": x},
#   {"mean": x, "n": k}).
#
# Everything runs offline on a small hand-written registry subset plus
# fake arm means. No real run directory is read.
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import figures_metrics  # noqa: E402


# ---------------------------------------------------------------- fixtures
def _meanswrap_registry():
    """A tiny hand-written registry subset: one experiment (sunk_cost,
    raw 0-20 purchases) with float human arms — the human side never
    changes and never uses the wrapper."""
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


def _wrapped(means_by_arm, n_by_arm=None):
    """One blinding condition in the EXACT production builder shape:
    arms nested under "means", counts under a sibling "n"."""
    entry = {"means": means_by_arm}
    if n_by_arm is not None:
        entry["n"] = n_by_arm
    return entry


def _meanswrap_llm_means():
    """Fake model arm means in the REAL production wrapper shape, for
    every shape of arm value the fix must still support inside "means":
      - gpt-oss-20b: plain floats inside "means" (the true production
        shape), matching the humans exactly -> Profile 0.0, effect 0.0.
      - qwen3-32b: floats inside "means", card arm 1 raw point HIGHER
        -> model effect (9-12)/20 = -0.15 vs the humans' -0.2 ->
        effect error 5.0; profile gaps 0.0 and 0.05 -> Profile 2.5.
      - glm-4.7-flash: {"mean", "n"} dicts inside "means", matching the
        humans -> Profile 0.0, effect 0.0.
    Each blinding entry also carries the production "n" sibling dict —
    it must be ignored, never mistaken for an arm."""
    n = {"no_card": 100, "card": 100}
    return {
        "gpt-oss-20b": {
            "sunk_cost": {
                "blinded": _wrapped({"no_card": 12.0, "card": 8.0}, n),
                "unblinded": _wrapped({"no_card": 12.0, "card": 8.0}, n),
            },
        },
        "qwen3-32b": {
            "sunk_cost": {
                "blinded": _wrapped({"no_card": 12.0, "card": 9.0}, n),
                "unblinded": _wrapped({"no_card": 12.0, "card": 9.0}, n),
            },
        },
        "glm-4.7-flash": {
            "sunk_cost": {
                "blinded": _wrapped(
                    {
                        "no_card": {"mean": 12.0, "n": 100},
                        "card": {"mean": 8.0, "n": 100},
                    }
                ),
                "unblinded": _wrapped(
                    {
                        "no_card": {"mean": 12.0, "n": 100},
                        "card": {"mean": 8.0, "n": 100},
                    }
                ),
            },
        },
    }


def _rows(llm_means=None):
    return figures_metrics.compute_error_rows(
        _meanswrap_registry(), llm_means or _meanswrap_llm_means()
    )


# ------------------------------------------- production wrapper unwrapped
def test_production_means_wrapper_gives_row_for_every_model():
    """THE BUG: with the real builder shape (arms under "means", counts
    under "n"), every model must still get a row. Today "means" and "n"
    are walked as if they were arm names, so every model row comes back
    all-None."""
    by_model = {r.model: r for r in _rows()}
    for model in ("gpt-oss-20b", "qwen3-32b", "glm-4.7-flash"):
        row = by_model.get(model)
        assert row is not None, (
            f"{model} lost its row entirely under the production "
            'means-wrapper shape (the bug)'
        )
        assert row.profile_error_blinded is not None, (
            f"{model}'s row has no Profile Error because the means "
            'wrapper was read as pseudo-arms (the bug)'
        )


def test_means_wrapper_float_arms_hand_computable_errors():
    """Plain floats inside "means" (the exact production shape) give the
    same hand-computed numbers as the flat shape: a matching model gets
    Profile 0.0 / effect 0.0; a model with the card arm 1 raw point high
    gets Profile 2.5 / effect 5.0."""
    by_model = {r.model: r for r in _rows()}
    assert by_model["gpt-oss-20b"].profile_error_blinded == pytest.approx(0.0)
    assert by_model["gpt-oss-20b"].profile_error_unblinded == pytest.approx(0.0)
    assert by_model["gpt-oss-20b"].contrast_error == pytest.approx(0.0)
    assert by_model["qwen3-32b"].profile_error_blinded == pytest.approx(2.5)
    assert by_model["qwen3-32b"].contrast_error == pytest.approx(5.0)


def test_means_wrapper_dict_arms_still_supported():
    """Inside "means", each arm's value may still be a {"mean": x, "n": k}
    dict (TASK-2416 shape) — the unwrap must not break that support."""
    by_model = {r.model: r for r in _rows()}
    assert by_model["glm-4.7-flash"].profile_error_blinded == pytest.approx(0.0)
    assert by_model["glm-4.7-flash"].contrast_error == pytest.approx(0.0)


def test_means_wrapper_only_one_row_per_model():
    """The "means"/"n" keys must not spawn EXTRA rows (one row per model
    per experiment, as always)."""
    rows = _rows()
    assert len(rows) == 3
    assert len({(r.model, r.experiment) for r in rows}) == 3


# ------------------------------------------------- old shapes unchanged
def test_flat_blinding_shapes_behavior_unchanged():
    """REGRESSION GUARD: without the wrapper, the already-working shapes
    (float arms, {"mean": x} dicts, flat {arm: float}) keep their exact
    behaviour and numbers."""
    flat_llm_means = {
        "gpt-oss-20b": {
            "sunk_cost": {
                "blinded": {"no_card": 12.0, "card": 8.0},
                "unblinded": {"no_card": 12.0, "card": 8.0},
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
    }
    by_model = {r.model: r for r in _rows(flat_llm_means)}
    assert by_model["gpt-oss-20b"].profile_error_blinded == pytest.approx(0.0)
    assert by_model["gpt-oss-20b"].contrast_error == pytest.approx(0.0)
    assert by_model["qwen3-32b"].profile_error_blinded == pytest.approx(2.5)
    assert by_model["qwen3-32b"].contrast_error == pytest.approx(5.0)
    assert len(_rows(flat_llm_means)) == 2
