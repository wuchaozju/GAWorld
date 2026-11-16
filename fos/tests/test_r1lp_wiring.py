# Locked tests for the R1LP launcher wiring (TASK-1550, RED phase).
#
# WHY THESE TESTS EXIST: the R1LP logprob scoring module
# (scripts/logprob_scoring.py) works offline, but the launcher must be the
# one place that reaches it. These tests lock three queued changes to the
# launcher wiring, all offline (no network, no model loads):
#
#   (1) REACHABLE: --profile R1LP goes through launch_grid's profile
#       dispatch and resolves to logprob scoring with NO grammar.
#   (2) DEFAULT MODE = candidate_scoring (USER DIRECTIVE, binding): the
#       R1LP profile's DEFAULT scoring mode is the full-string
#       candidate comparison; first_token only when explicitly requested.
#       (This deliberately overrides LOGPROB-DESIGN.md, which still calls
#       first_token the default - the DIRECTIVE wins; see RESULT-1550.)
#   (3) A/B LABEL-ORDER REVERSAL + AVERAGING (USER DIRECTIVE, binding):
#       when A/B is enabled every cell is planned with BOTH label orders
#       ("purchase" | "not purchase" and the reversal), and the two
#       p(buy) values are aggregated by their mean - mean(0.8, 0.2) == 0.5.
#
# Interface choices where LOGPROB-DESIGN.md is silent (minimal natural
# extension of what exists; see RESULT-1550 notes):
#   - launch_grid grows an --ab-labels switch (default off) for R1LP;
#   - build_logprob_plan grows ab_orders: bool = False; True doubles every
#     leg's scoring passes (both orders per cell) and stamps the plan;
#   - logprob_scoring grows AB_LABEL_ORDERS (the forward/reversed pair)
#     and average_ab_p_buy (the mean of the two p(buy) values);
#   - make_candidate_scorer grows label_order=(...) and stamps the order
#     it scored on every result.
#
# The 14 locked tests in tests/test_logprob_profile.py must stay green.
# No test here touches a real server: the injected fake poster IS the
# transport, and dry-run/settings paths never open a socket.
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

PRODUCTS_COUNT = 40
LEVELS = [float(x) for x in range(0, 220, 20)]


# ---------------------------------------------------------------------------
# (1) Reachable: --profile R1LP dispatches to logprob scoring, not grammar
# ---------------------------------------------------------------------------


def test_r1lp_profile_is_reachable_and_resolves_to_logprob_not_grammar(capsys):
    """launch_grid --profile R1LP --dry-run is accepted and plans logprob
    scoring: no grammar (none) and a logprob mode in the printed plan."""
    from launch_grid import main

    assert main(["--profile", "R1LP", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "R1LP launch plan (dry run)" in out
    assert "logprob" in out.lower()
    assert "none" in out.lower()  # grammar none, never the GBNF one-token
    assert 'root ::=' not in out  # the R1-5MODEL grammar must not appear


def test_r1lp_settings_carry_the_chosen_logprob_mode():
    """The settings the real run would use carry the requested logprob
    mode for R1LP (and no grammar) - the scorer the legs actually get."""
    from launch_grid import _parse_args, _settings_from

    settings = _settings_from(
        _parse_args(["--profile", "R1LP", "--logprob-mode", "candidate_scoring"]),
        "wiring-probe",
    )
    assert settings.logprob_mode == "candidate_scoring"
    assert settings.grammar is None


# ---------------------------------------------------------------------------
# (2) DEFAULT mode = candidate_scoring; first_token only when asked
# ---------------------------------------------------------------------------


def test_r1lp_default_scoring_mode_is_candidate_scoring():
    """USER DIRECTIVE (binding): with no --logprob-mode given, the R1LP
    profile's default scoring mode is candidate_scoring (the full-string
    comparison), not first_token."""
    from launch_grid import _parse_args, _settings_from

    settings = _settings_from(_parse_args(["--profile", "R1LP"]), "wiring-probe")
    assert settings.logprob_mode == "candidate_scoring", (
        "the R1LP profile must default to candidate_scoring; "
        f"got {settings.logprob_mode!r}"
    )


def test_r1lp_dry_run_reports_candidate_scoring_by_default(capsys):
    """The dry run of a bare --profile R1LP invocation shows the mode the
    run would actually use: candidate_scoring."""
    from launch_grid import main

    assert main(["--profile", "R1LP", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "candidate_scoring" in out, (
        "the R1LP dry run must report the candidate_scoring default "
        "(this is what the run would use)"
    )


def test_first_token_is_used_only_when_explicitly_requested(capsys):
    """USER DIRECTIVE (binding): first_token is not gone - an explicit
    --logprob-mode first_token is honoured by the dry run and the settings."""
    from launch_grid import _parse_args, _settings_from, main

    assert main(["--profile", "R1LP", "--dry-run", "--logprob-mode", "first_token"]) == 0
    assert "first_token" in capsys.readouterr().out
    settings = _settings_from(
        _parse_args(["--profile", "R1LP", "--logprob-mode", "first_token"]),
        "wiring-probe",
    )
    assert settings.logprob_mode == "first_token"


# ---------------------------------------------------------------------------
# (3) A/B label-order reversal + averaging (USER DIRECTIVE, binding)
# ---------------------------------------------------------------------------


def test_ab_label_orders_are_the_forward_and_reversed_pair():
    """The two A/B label orders are the forward order ("purchase" first)
    and its reversal ("not purchase" first) - both must be defined."""
    from logprob_scoring import AB_LABEL_ORDERS

    assert len(AB_LABEL_ORDERS) == 2
    forward, reversed_ = (tuple(order) for order in AB_LABEL_ORDERS)
    assert forward == ("purchase", "not purchase")
    assert reversed_ == ("not purchase", "purchase")


def test_ab_plan_plans_every_cell_with_both_label_orders():
    """USER DIRECTIVE (binding): with A/B enabled, every leg is planned
    with BOTH label orders - each leg's scoring passes double and the plan
    is stamped ab_orders=True (92,400 x 2 = 184,800 total)."""
    from launch_queue import build_logprob_plan

    default = build_logprob_plan(PRODUCTS_COUNT, len(LEVELS), levels=LEVELS)
    ab = build_logprob_plan(PRODUCTS_COUNT, len(LEVELS), levels=LEVELS, ab_orders=True)
    assert ab["ab_orders"] is True
    assert ab["sweep_calls"] == 2 * default["sweep_calls"] == 184_800, (
        "A/B plans both label orders per cell, so the total must double"
    )
    by_key = {
        (leg["model"], leg["depth"], leg["blinding"]): leg["calls"]
        for leg in default["legs"]
    }
    for leg in ab["legs"]:
        key = (leg["model"], leg["depth"], leg["blinding"])
        assert leg["calls"] == 2 * by_key[key], (
            f"leg {key} must plan both label orders (2x its passes)"
        )
    for meta in ab["models"]:
        assert meta["total_calls"] == 36_960  # 18,480 x 2 orders


def test_ab_is_off_by_default_in_the_plan():
    """Without the A/B switch the plan is unchanged: no ab_orders stamp
    (falsy) and the locked 92,400 one-pass-per-prompt total."""
    from launch_queue import build_logprob_plan

    plan = build_logprob_plan(PRODUCTS_COUNT, len(LEVELS), levels=LEVELS)
    assert not plan.get("ab_orders")
    assert plan["sweep_calls"] == 92_400


def test_ab_averaging_takes_the_mean_of_the_two_pbuy_values():
    """USER DIRECTIVE (binding): the A/B aggregation is the plain mean of
    the two p(buy) values - mean(0.8, 0.2) == 0.5, and an identical pair
    stays that value."""
    from logprob_scoring import average_ab_p_buy

    assert average_ab_p_buy(0.8, 0.2) == pytest.approx(0.5), (
        "the A/B aggregate of the two p(buy) values is their mean"
    )
    assert average_ab_p_buy(0.6, 0.6) == pytest.approx(0.6)
    assert average_ab_p_buy(0.0, 1.0) == pytest.approx(0.5)


def test_candidate_scorer_stamps_the_label_order_it_scored():
    """The candidate scorer accepts a label_order: the default result
    stamps the forward order, a reversed-order scorer stamps the reversal,
    and both still make exactly one call per candidate."""
    from logprob_scoring import make_candidate_scorer

    class _FakePost:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def __call__(self, url: str, payload: dict, timeout: float) -> tuple[int, str]:
            self.calls.append((url, payload))
            return 200, '{"completion_probabilities": [{"token": "x", "logprob": -0.1}]}'

    default_post = _FakePost()
    default = make_candidate_scorer(
        "http://127.0.0.1:9", "vendor/model", post=default_post
    )
    default_result = default([{"role": "user", "content": "buy?"}])
    assert list(default_result["label_order"]) == ["purchase", "not purchase"]
    assert len(default_post.calls) == 2

    reversed_post = _FakePost()
    reversed_scorer = make_candidate_scorer(
        "http://127.0.0.1:9",
        "vendor/model",
        post=reversed_post,
        label_order=("not purchase", "purchase"),
    )
    reversed_result = reversed_scorer([{"role": "user", "content": "buy?"}])
    assert list(reversed_result["label_order"]) == ["not purchase", "purchase"], (
        "a reversed-order A/B pass must stamp the order it scored"
    )
    assert len(reversed_post.calls) == 2
    prompts = [payload["prompt"] for _url, payload in reversed_post.calls]
    assert any(p.endswith("purchase") for p in prompts)
    assert any(p.endswith("not purchase") for p in prompts)


def test_launcher_accepts_the_ab_flag_for_r1lp(capsys):
    """launch_grid --profile R1LP --dry-run --ab-labels must be accepted
    (the A/B switch is reachable from the launcher), planning offline."""
    from launch_grid import main

    try:
        code = main(["--profile", "R1LP", "--dry-run", "--ab-labels"])
    except SystemExit as exc:
        pytest.fail(
            "launch_grid refused --ab-labels (exit "
            f"{exc.code}): the A/B label-order switch is not wired yet"
        )
    assert code == 0
    assert "R1LP launch plan (dry run)" in capsys.readouterr().out
