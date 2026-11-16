# RED-phase tests for the twin2k10 runner's launch flags (TASK-2182).
#
# WHAT THIS FILE CHECKS, in plain words:
#   - --models takes a comma-separated subset of the study's model ids and
#     runs ONLY those models (a typo must stop the run, never invent a
#     model). Default: all 15 models, pinned order.
#   - --preflight-only runs the auto-preflight cells (persona 0 on every
#     arm, both blinding arms, for each requested model), writes the
#     preflight report and verdict — and then STOPS: the 3,800-cell grid
#     never starts. This is the owner's live per-model test workflow:
#     `--models <one model> --preflight-only` answers persona 0 once and
#     exits 0, touching no production grid cells.
#
# All offline: the model server, the manager and the pool generator are
# replaced by fakes; the only files written live in a temp run dir.
import json
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k10 import config, legexec, runner, serving  # noqa: E402


# ---------------------------------------------------------------------------
# --models — the subset filter (flag ships today; tests pin its contract).
# ---------------------------------------------------------------------------


def test_models_flag_accepts_a_comma_separated_subset() -> None:
    """Only the requested models run, in the order they were given."""
    assert runner.resolve_models("qwen3-4b, gpt-oss-20b") \
        == ["qwen3-4b", "gpt-oss-20b"]


def test_models_flag_defaults_to_all_fifteen_models_in_pinned_order() -> None:
    """No --models means the full 15-model study queue."""
    assert runner.resolve_models(None) == list(config.MODELS)
    assert len(config.MODELS) == 15


def test_an_unknown_model_id_in_models_is_rejected() -> None:
    """A typo stops the run with an error — it never invents a model."""
    with pytest.raises(ValueError):
        runner.resolve_models("qwen3-4b,not-a-study-model")


# ---------------------------------------------------------------------------
# --preflight-only — preflight cells, then STOP before the grid.
# ---------------------------------------------------------------------------


def test_preflight_only_flag_parses_and_defaults_to_off() -> None:
    """The flag exists on the CLI and is off unless requested."""
    args = runner.parse_args([])
    assert args.preflight_only is False
    args = runner.parse_args(["--preflight-only"])
    assert args.preflight_only is True


def _healthy_record() -> dict:
    """A record every preflight check passes (helper)."""
    return {
        "succeeded": True,
        "top_logprobs": [{"token": "A", "logprob": -0.357}],
        "p_raw": {"A": 0.7, "B": 0.2},
    }


def test_preflight_only_runs_preflight_cells_then_stops_before_the_grid(
    tmp_path, monkeypatch,
) -> None:
    """`--models qwen3-4b --preflight-only`: 38 cells, then a clean stop.

    The one requested model answers persona 0 on every arm in both
    blinding arms through the REAL durable leg-file loop (only the model
    server, manager and pool are faked); the preflight verdict and
    report are written, the process exits 0 — and not a single grid
    persona (1-99) is ever executed.
    """
    run_dir = tmp_path / "preflight-only-run"
    calls: list[tuple] = []

    def fake_make_transport(context, on_record, scorer=None):
        def transport(cell) -> dict:
            calls.append(cell)
            record = _healthy_record()
            on_record(record)
            return record

        return transport

    monkeypatch.setattr(serving, "ensure_pool",
                        lambda *args, **kwargs: [{"persona_id": 0}])
    monkeypatch.setattr(serving, "ensure_model_loaded",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(serving, "unload_model",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(legexec, "make_transport", fake_make_transport)

    exit_code = runner.main([
        "--preflight-only", "--models", "qwen3-4b",
        "--run-dir", str(run_dir),
    ])

    assert exit_code == 0
    # Exactly the preflight grid: persona 0 x 19 arms x 2 blindings.
    assert len(calls) == 38, (
        f"preflight-only must run exactly the 38 persona-0 cells, ran "
        f"{len(calls)}"
    )
    assert {cell[1] for cell in calls} == {0}, (
        "preflight-only must never execute a grid persona (1-99)"
    )
    # The preflight outputs exist where the operator reads them.
    assert (run_dir / "PREFLIGHT_REPORT.md").is_file()
    assert (run_dir / runner.VERDICT_FILE).is_file()
    # The manifest pins the requested subset (the owner's per-model test).
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert [entry["model"] for entry in manifest["models"]] == ["qwen3-4b"]
    # Every durable record on disk is a preflight record of persona 0.
    on_disk = [
        json.loads(line)
        for path in run_dir.rglob("records.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(on_disk) == 38
    assert {record["persona_id"] for record in on_disk} == {0}
