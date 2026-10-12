# TASK-2215 RED tests for the two defects RESULT-2214 found in the
# twin2k10 digit path (tests ONLY — every test here must fail on main
# for the right reason until the implement agent lands the fix).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - Defect 1 (degenerate digit fold): when a model answers a numeric
#     question with multi-digit number tokens ("379", " 289"), the
#     record must still carry a real leading-digit distribution — the
#     all-None p_raw of today (only exact single-digit spellings fold)
#     must become impossible, and the found digits' probabilities must
#     add up to the item's digit_mass.
#   - Defect 2 (anchor-blind anchoring estimates): the anchoring digit
#     estimate call must SEE the arm's anchor (the low arm's "85 feet"
#     question, the high arm's "1000 feet" question), so the low/high
#     digit prompts differ (different audit hashes) while the estimate
#     QUESTION text itself stays verbatim.
#   - Preflight sanity gate: a stored digit item whose distribution is
#     all-None must fail preflight even when its digit_mass looks
#     healthy, and a healthy item must still pass.
#
# All offline: pure functions plus a fake scorer over synthetic top-k
# lists. No network, no models, no file writes.

import math
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import config, experiments, legexec, preflight  # noqa: E402


def _entry(token: str, prob: float) -> dict:
    """Build one top-k entry {token, logprob} from a probability (helper)."""
    return {"token": token, "logprob": math.log(prob)}


def _offline_context() -> legexec.LegContext:
    """The study context one offline cell run needs (helper)."""
    return legexec.LegContext(
        model=config.MODELS[0],
        model_id=f"offline-{config.MODELS[0]}",
        base_url="http://127.0.0.1:8080",
        personas=[{"persona_id": 0}],
        stimuli=experiments.load_stimuli(),
        inference=legexec.inference_settings("http://127.0.0.1:8080"),
    )


def _run_cell(experiment: str, arm: str, answer_tokens: list[str]) -> tuple:
    """One real cell's record with a fake scorer (helper).

    The fake scorer answers each call with the next token in the list,
    so every stored distribution is attributable to exactly one item
    call. Returns (record, messages_of_each_call_in_order).
    """
    tokens = iter(answer_tokens)
    calls: list[list] = []

    def fake_scorer(messages: list) -> dict:
        calls.append(messages)
        try:
            token = next(tokens)
        except StopIteration:
            raise AssertionError(
                f"unexpected extra scorer call #{len(calls)}"
            ) from None
        return {"top_logprobs": [_entry(token, 0.9)],
                "decision_position": 0, "skipped_prefix": [],
                "skipped_len": 0, "succeeded": True}

    cell = (config.MODELS[0], 0, experiment, arm, "blinded")
    return legexec.execute_cell(
        _offline_context(), fake_scorer, cell
    ), calls


# ---------------------------------------------------------------------------
# Defect 1 — the degenerate digit fold (locked spec 2)
# ---------------------------------------------------------------------------


def test_number_token_answers_fill_digit_probabilities() -> None:
    """Multi-digit number tokens must fill the item's digit distribution.

    A top-k of "379" and " 289" credits the LEADING digits "3" and "2":
    the item's p_raw carries those two digits with their probabilities,
    every other digit label stays None, and the found labels' values sum
    to the item's digit_mass (the same scan mass the preflight gates on).
    Today the fold only accepts the exact single-character spellings
    "0"…"9", so the same answer produces an all-None distribution.
    """
    # The real multi-digit case: number-emitting models answer "379"/" 289".
    top_k = [_entry("379", 0.6), _entry(" 289", 0.3)]
    record, _calls = _run_cell_with_top_k(
        "base_rate", "30_engineers", top_k
    )
    item = record["digit_items"][0]
    assert item["p_raw"]["3"] == pytest.approx(0.6), (
        "the leading digit of the multi-digit token '379' must be credited"
    )
    assert item["p_raw"]["2"] == pytest.approx(0.3), (
        "the leading digit of the space-glued number token ' 289' must be "
        "credited"
    )
    found = [value for value in item["p_raw"].values() if value is not None]
    assert found, "an all-None p_raw must be impossible for a digit answer"
    assert sum(found) == pytest.approx(item["digit_mass"])


def _run_cell_with_top_k(experiment: str, arm: str, top_k: list) -> tuple:
    """One cell whose digit call returns a given top-k list (helper)."""

    def fake_scorer(messages: list) -> dict:
        return {"top_logprobs": list(top_k),
                "decision_position": 0, "skipped_prefix": [],
                "skipped_len": 0, "succeeded": True}

    cell = (config.MODELS[0], 0, experiment, arm, "blinded")
    return legexec.execute_cell(_offline_context(), fake_scorer, cell), None


def test_simple_digit_answer_still_scores_exactly() -> None:
    """A bare single-digit token still folds to its digit label."""
    record, _calls = _run_cell("base_rate", "30_engineers", ["4"])
    item = record["digit_items"][0]
    assert item["p_raw"]["4"] == pytest.approx(0.9)
    assert item["digit_mass"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Defect 1 support — preflight sanity gate (locked spec 3 + Fix 3)
# ---------------------------------------------------------------------------


def test_all_none_digit_distribution_fails_preflight() -> None:
    """A stored all-None digit distribution must trip preflight.

    The item looks healthy to today's only gate (digit_mass 1.0 clears
    the 0.5 dominance gate), yet its p_raw reads no digit anywhere —
    exactly the degenerate fold RESULT-2214 measured 85 times. Preflight
    must flag it independent of digit_mass; the 0.5 mass gate stays.
    """
    record = {
        "model": "granite-4.1-30b", "experiment": "anchoring_redwood",
        "arm": "low", "blind": "blinded", "persona_id": 0,
        "top_logprobs": [_entry("379", 0.6)],
        "digit_items": [{
            "qid": "QID168", "row": None, "statement": None,
            "top_logprobs": [_entry("379", 0.6)],
            "p_raw": {digit: None for digit in "0123456789"},
            "p_norm": {digit: None for digit in "0123456789"},
            "branch_mass": 0.0, "low_branch_mass": True,
            "digit_mass": 1.0, "decision_position": 1,
        }],
    }
    verdict = preflight.decide([record])
    assert verdict["stop"], (
        "an all-None digit p_raw must be a preflight failure even with a "
        "healthy digit_mass"
    )
    assert any("QID168" in reason for reason in verdict["reasons"])


def test_healthy_digit_item_still_passes_preflight() -> None:
    """A digit item with found digits and solid mass is not flagged."""
    record = {
        "model": "granite-4.1-30b", "experiment": "anchoring_redwood",
        "arm": "low", "blind": "blinded", "persona_id": 0,
        "top_logprobs": [_entry("379", 0.6)],
        "digit_items": [{
            "qid": "QID168", "row": None, "statement": None,
            "top_logprobs": [_entry("379", 0.6)],
            "p_raw": {**{digit: None for digit in "0123456789"},
                      "3": 0.6},
            "p_norm": {**{digit: None for digit in "0123456789"},
                       "3": 1.0},
            "branch_mass": 0.6, "low_branch_mass": True,
            "digit_mass": 1.0, "decision_position": 1,
        }],
    }
    verdict = preflight.decide([record])
    assert not verdict["stop"], verdict["reasons"]


# ---------------------------------------------------------------------------
# Defect 2 — the anchor-blind anchoring estimate (locked spec 1)
# ---------------------------------------------------------------------------


def test_different_anchor_numbers_produce_different_digit_prompts() -> None:
    """Low and high anchoring digit estimates must see their own anchor.

    The digit estimate call of the low arm must receive the low arm's
    anchor context and the high arm's the high arm's, so the two digit
    prompts (and their audit hashes) differ. The estimate QUESTION text
    itself stays verbatim in both arms — only the anchor context around
    it changes. Today both arms send byte-identical estimate prompts
    (RESULT-2214: identical prompt_sha256 across arms), so the low/high
    contrast is structurally unmeasured.
    """
    stimuli = experiments.load_stimuli()
    low_items = experiments.arm_items("anchoring_redwood", "low")
    high_items = experiments.arm_items("anchoring_redwood", "high")
    low_digit = next(i for i in low_items if i["kind"] == "digit")
    high_digit = next(i for i in high_items if i["kind"] == "digit")
    low_record, _ = _run_cell("anchoring_redwood", "low", ["A", "7"])
    high_record, _ = _run_cell("anchoring_redwood", "high", ["B", "7"])
    low_entry = low_record["digit_items"][0]
    high_entry = high_record["digit_items"][0]
    # The estimate question stays verbatim in both arms.
    assert low_digit["question_text"] in low_entry["user_prompt"]
    assert high_digit["question_text"] in high_entry["user_prompt"]
    # The prompts must differ because the anchors differ.
    assert low_entry["prompt_sha256"] != high_entry["prompt_sha256"], (
        "the low and high anchoring digit estimates must not be "
        "byte-identical prompts — the arm's anchor must reach the call"
    )
    # And each arm's own anchor question must be part of its call.
    for arm_name, entry in (("low", low_entry), ("high", high_entry)):
        anchor_qids = experiments.EXPERIMENTS["anchoring_redwood"] \
            .arm_qids(arm_name)
        anchor_text = stimuli[anchor_qids[0]]["question_text"]
        assert anchor_text in entry["user_prompt"], (
            f"the {arm_name} arm's anchor question must reach the "
            "digit estimate call"
        )


def test_non_anchoring_digit_prompts_keep_their_single_question_shape() -> None:
    """The anchor fix must not leak into non-anchoring experiments.

    base_rate's digit call keeps its own single-question prompt: the
    question verbatim, nothing from another question, ending with the
    pinned single-number instruction.
    """
    from twin2k10 import prompts

    record, _calls = _run_cell("base_rate", "30_engineers", ["4"])
    item = record["digit_items"][0]
    items = experiments.arm_items("base_rate", "30_engineers")
    assert items[0]["question_text"] in item["user_prompt"]
    assert item["user_prompt"].split("\n\n")[-1] == prompts.NUMERIC_INSTRUCTION


# ---------------------------------------------------------------------------
# Choice path stays untouched (locked spec 4)
# ---------------------------------------------------------------------------


def test_choice_fold_is_untouched_by_both_fixes() -> None:
    """The letter fold keeps its exact single-spelling behaviour."""
    from twin2k10 import scoring

    assert scoring.fold_label_tokens("A") == frozenset(
        {"A", " A", "a", " a"}
    )
    scored = scoring.score_labels(
        [_entry("A", 0.7), _entry("B", 0.2)], "allais",
        decision_position=1, skipped_prefix=[], skipped_len=0,
    )
    assert scored["p_raw"]["A"] == pytest.approx(0.7)
    assert scored["p_raw"]["B"] == pytest.approx(0.2)
    assert scored["p_norm"]["A"] == pytest.approx(0.7 / 0.9)
    assert scored["branch_mass"] == pytest.approx(0.9)
