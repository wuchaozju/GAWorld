# Locked tests for the R1LP RUN MANIFEST + resume safety (TASK-1555, RED
# phase; review findings F1 HIGH).
#
# WHY THESE TESTS EXIST: an R1LP run can be launched with the A/B
# label-order switch (--ab-labels), but the run's manifest.json does not
# record that choice, and a --resume validates nothing against it. A
# mis-typed resume (with the flag when the run was plain, or without the
# flag when the run was A/B) therefore silently mixes single-order and
# merged cells in one run - the science is biased and nothing complains.
# These tests lock the fix, all offline (no network, no model loads; every
# run directory here is fully durable, so the ONLY things a correct
# implementation does are refuse or finalize):
#
#   (1) PERSISTED (F1a): a run planned with A/B stamps ab_orders: true
#       into its manifest payload, next to logprob_mode; a plain R1LP run
#       records no truthy ab_orders stamp.
#   (2) RESUME REFUSED (F1b): a resume whose flags disagree with the
#       manifest's ab_orders is refused loudly (exit 2, error message
#       naming ab_orders) BEFORE any model load or scoring call:
#         - resume with --ab-labels against a non-A/B manifest -> refused;
#         - resume without --ab-labels against an ab_orders=true manifest
#           -> refused.
#   (3) MATCHING RESUME PROCEEDS: a resume whose plan agrees with the
#       manifest's ab_orders=true still runs to completion (the guard must
#       never block an honest 3 a.m. resume).
#
# The refusal contract follows the launcher's existing hard-error shape:
# print the error and exit 2 (the same code used when a run dir already
# holds a run without --resume).
#
# The 33 locked offline tests in test_logprob_profile.py /
# test_r1lp_wiring.py / test_r1lp_ab_executor.py must stay green.
# No test here touches a real server: nothing is pending, so no leg ever
# executes; the model loader is replaced by a recorder that must stay
# empty.
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

PRODUCTS = [
    {"category": "Soft Drinks", "product": "Cola 12 oz", "regular_price": 1.99},
    {"category": "Chips", "product": "Potato Chips", "regular_price": 2.99},
]
LEVELS = [0.0, 100.0]
RUN_NAME = "manifest-probe"


def _r1lp_settings(tmp_path: Path, extra_args: list[str]):
    """The settings of a real R1LP resume invocation (candidate_scoring),
    pointed at a throwaway directory."""
    from launch_grid import _parse_args, _settings_from

    argv = ["--profile", "R1LP", "--run-name", RUN_NAME, "--resume", *extra_args]
    args = _parse_args(argv)
    return args, replace(_settings_from(args, RUN_NAME), out=tmp_path)


def _write_done_queue_leg(run_dir: Path, target: dict) -> None:
    """Write one FINISHED queue leg's files (records.jsonl + csv + manifest)
    - exactly the triple the resume check treats as done."""
    from launch_queue import queue_leg_dir, queue_leg_jsonl

    leg_dir = queue_leg_dir(run_dir, target)
    leg_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in range(int(target["calls"])):
        record = {
            "model": target["model"],
            "product": PRODUCTS[index % len(PRODUCTS)]["product"],
            "treatment_value": LEVELS[index % len(LEVELS)],
            "blinding": target["blinding"],
            "persona_depth": target["depth"],
            "succeeded": True,
            "parsed_purchase": True,
            "elapsed_seconds": 0.1,
        }
        if target["depth"] != "none":
            record["persona_index"] = index
        lines.append(json.dumps(record))
    (leg_dir / "records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (leg_dir / "records.csv").write_text("", encoding="utf-8")
    (leg_dir / "manifest.json").write_text(
        json.dumps({"depth": target["depth"], "blinding": target["blinding"]}),
        encoding="utf-8",
    )


def _write_prior_manifest(run_dir: Path, payload: dict) -> None:
    """Write the run-level manifest an earlier invocation left behind."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )


def _resume_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    ab_labels_flag: bool,
    prior_payload: dict,
):
    """Build a fully durable R1LP run dir + prior manifest, then run one
    --resume invocation against it. Returns (exit_code, model_loads, output)
    where model_loads records every model-load attempt (the refusal must
    leave it empty) and output is the combined stdout+stderr."""
    from launch_5model import run_queue
    from launch_queue import build_logprob_plan

    plan_extra = ["--ab-labels"] if ab_labels_flag else []
    args, settings = _r1lp_settings(tmp_path, plan_extra)
    plan = build_logprob_plan(
        len(PRODUCTS), len(LEVELS), levels=LEVELS, ab_orders=ab_labels_flag
    )
    run_dir = settings.out / settings.run_name
    for target in plan["legs"]:
        _write_done_queue_leg(run_dir, target)
    _write_prior_manifest(run_dir, prior_payload)

    import launch_5model as queue_module

    loads: list[str] = []

    def _record_load(manager_url: str, model: str, port: int) -> None:
        loads.append(model)

    monkeypatch.setattr(queue_module, "_load_model", _record_load)
    exit_code = run_queue(args, plan, [], Path("products.json"), settings)
    captured = capsys.readouterr()
    return exit_code, loads, captured.out + captured.err


# ---------------------------------------------------------------------------
# (1) F1a: the manifest records the A/B state beside logprob_mode
# ---------------------------------------------------------------------------


def test_manifest_of_an_ab_run_stamps_ab_orders_true_beside_logprob_mode(tmp_path):
    """A run launched with the A/B switch must write ab_orders: true into
    its manifest payload next to logprob_mode - otherwise no resume can
    ever know the run was A/B."""
    from launch_5model import write_queue_manifest
    from launch_grid import _parse_args, _settings_from
    from launch_queue import build_logprob_plan
    from launch_support import _now

    args = _parse_args(["--profile", "R1LP", "--run-name", RUN_NAME, "--ab-labels"])
    settings = replace(_settings_from(args, RUN_NAME), out=tmp_path)
    plan = build_logprob_plan(
        len(PRODUCTS), len(LEVELS), levels=LEVELS, ab_orders=True
    )
    run_dir = tmp_path / RUN_NAME
    run_dir.mkdir(parents=True)

    manifest_path = write_queue_manifest(
        settings=settings,
        plan=plan,
        products_path=Path("products.json"),
        run_dir=run_dir,
        started=_now(),
        finished=_now(),
        leg_results=[],
        pools=None,
        prior=None,
        resume_invocation=False,
        state="running",
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload.get("ab_orders") is True, (
        "a run planned with A/B must stamp ab_orders: true into its "
        "manifest payload next to logprob_mode; got "
        f"{payload.get('ab_orders')!r} - the A/B state is not persisted, "
        "so no resume can validate its flags against the run"
    )
    assert payload["logprob_mode"] == "candidate_scoring", (
        "the A/B stamp must sit beside the recorded logprob_mode"
    )


def test_manifest_of_a_plain_run_records_no_ab_orders_stamp(tmp_path):
    """Without the A/B switch the manifest records no truthy ab_orders
    stamp - the plain R1LP manifest shape is unchanged apart from the
    explicit falsy stamp."""
    from launch_5model import write_queue_manifest
    from launch_grid import _parse_args, _settings_from
    from launch_queue import build_logprob_plan
    from launch_support import _now

    args = _parse_args(["--profile", "R1LP", "--run-name", RUN_NAME])
    settings = replace(_settings_from(args, RUN_NAME), out=tmp_path)
    plan = build_logprob_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS)
    assert not plan.get("ab_orders"), "precondition: the plain plan is not A/B"
    run_dir = tmp_path / RUN_NAME
    run_dir.mkdir(parents=True)

    manifest_path = write_queue_manifest(
        settings=settings,
        plan=plan,
        products_path=Path("products.json"),
        run_dir=run_dir,
        started=_now(),
        finished=_now(),
        leg_results=[],
        pools=None,
        prior=None,
        resume_invocation=False,
        state="running",
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert not payload.get("ab_orders"), (
        "a plain (non-A/B) run must not carry a truthy ab_orders stamp"
    )
    assert payload["logprob_mode"] == "candidate_scoring"


# ---------------------------------------------------------------------------
# (2) F1b: a resume that contradicts the manifest's ab_orders is refused
# ---------------------------------------------------------------------------


def test_resume_with_ab_flag_against_a_non_ab_manifest_is_refused(
    tmp_path, monkeypatch, capsys
):
    """Adding --ab-labels on a resume of a run whose manifest records no
    ab_orders must be refused loudly (exit 2, message naming ab_orders)
    BEFORE any model load or scoring call."""
    prior = {"state": "running", "started": "2026-01-01T00:00:00"}
    exit_code, loads, output = _resume_world(
        tmp_path,
        monkeypatch,
        capsys,
        ab_labels_flag=True,
        prior_payload=prior,
    )
    assert exit_code == 2, (
        "a --resume that adds --ab-labels to a run whose manifest records "
        "no ab_orders must be refused loudly (exit 2, error naming "
        f"ab_orders); got exit {exit_code} - the resume silently mixes "
        "single-order and A/B-merged cells in one run"
    )
    assert "ab_orders" in output, (
        f"the refusal must name the ab_orders mismatch; got: {output[-400:]!r}"
    )
    assert loads == [], (
        "the ab_orders refusal must fire before any model load or call"
    )


def test_resume_without_ab_flag_against_an_ab_manifest_is_refused(
    tmp_path, monkeypatch, capsys
):
    """Dropping --ab-labels on a resume of an ab_orders=true run must be
    refused just as loudly (exit 2, message naming ab_orders) - the plain
    resume would re-plan every remaining cell with one order only."""
    prior = {
        "state": "running",
        "started": "2026-01-01T00:00:00",
        "logprob_mode": "candidate_scoring",
        "ab_orders": True,
    }
    exit_code, loads, output = _resume_world(
        tmp_path,
        monkeypatch,
        capsys,
        ab_labels_flag=False,
        prior_payload=prior,
    )
    assert exit_code == 2, (
        "a --resume that drops --ab-labels from a run whose manifest "
        "records ab_orders=true must be refused loudly (exit 2, error "
        f"naming ab_orders); got exit {exit_code} - the resume silently "
        "re-plans the remaining cells single-order"
    )
    assert "ab_orders" in output, (
        f"the refusal must name the ab_orders mismatch; got: {output[-400:]!r}"
    )
    assert loads == [], (
        "the ab_orders refusal must fire before any model load or call"
    )


# ---------------------------------------------------------------------------
# (3) Control: a matching resume still proceeds
# ---------------------------------------------------------------------------


def test_resume_matching_the_ab_manifest_proceeds(tmp_path, monkeypatch, capsys):
    """The guard must only refuse MISMATCHED resumes: a resume whose plan
    agrees with the manifest's ab_orders=true completes normally (exit 0,
    manifest complete, no model load - every leg is already durable)."""
    prior = {
        "state": "running",
        "started": "2026-01-01T00:00:00",
        "logprob_mode": "candidate_scoring",
        "ab_orders": True,
    }
    exit_code, loads, _output = _resume_world(
        tmp_path,
        monkeypatch,
        capsys,
        ab_labels_flag=True,
        prior_payload=prior,
    )
    assert exit_code == 0, (
        "a resume whose flags match the manifest's ab_orders=true must "
        f"proceed; got exit {exit_code}"
    )
    assert loads == [], "a fully durable matching resume must not load a model"
    run_dir = tmp_path / RUN_NAME
    payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["state"] == "complete"
    assert payload["ok"] is True
