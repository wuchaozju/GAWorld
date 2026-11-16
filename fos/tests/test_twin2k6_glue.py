# Offline tests for the twin2k6 execution layer's glue code (TASK-2070):
# the model registry mapping, one-cell record building, the preflight
# examiner, and the figures selftest. These are NEW tests for NEW modules —
# the 79 locked core tests are untouched. Everything here runs with no
# model server, no manager, and no network: the cell transport is a fake
# scorer, and the figures test renders from synthetic fixtures.
#
# WHAT THIS FILE CHECKS, in plain words:
#   - Every study model resolves to a manager id, a GGUF path and a safe
#     folder name; gemma-4-26b-a4b carries its control-sequence override.
#   - One cell executed through a fake scorer produces the full spec-§11
#     record; a failing call is KEPT, marked succeeded=False, with the
#     error text and no fake 0.0 in the averaged outcome fields.
#   - A model with empty top-logprobs at the decision position is flagged
#     "STOP — technical failure" by the preflight examiner and written to
#     its skip list; a clean demographics-only pool passes the leak check.
#   - The figures selftest renders exactly three figures (PDF + PNG) with
#     their three tidy CSVs.

import json
import sys
from pathlib import Path

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from twin2k6 import (  # noqa: E402
    cells,
    config,
    experiments,
    legexec,
    preflight,
    registry,
)
import twin2k6.prompts as prompts  # noqa: E402


def _personas() -> list[dict]:
    """One demographics-only persona (the minimum the pool contract allows)."""
    return [{field: f"v{i}" for i, field in enumerate(prompts.PERSONA_FIELDS)}]


def _write_one_record(tmp_path, model: str, cell: tuple, scorer) -> dict:
    """Run ONE cell through the real write path and read its record back.

    Uses cells.run_cells exactly like a real leg (so the identity fields
    are stamped on write) with a fake scorer injected for offline running.
    """
    context = legexec.make_leg_context(model, "http://127.0.0.1:8080", _personas())
    transport = legexec.make_transport(context, lambda record: None, scorer=scorer)
    path = tmp_path / "records.jsonl"
    cells.run_cells([cell], transport, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_every_study_model_maps_to_manager_id_and_gguf():
    for model in config.MODELS:
        manager_id = registry.manager_model_id(model)
        assert manager_id  # the uncensored qwen's registry id has no "/"
        assert registry.gguf_path(model).endswith(".gguf")
        assert "/" not in registry.safe_model_name(model)


def test_unknown_model_id_is_refused_loudly():
    with pytest.raises(ValueError, match="unknown study model"):
        registry.manager_model_id("not-a-real-model")


def test_gemma_26b_carries_the_channel_control_sequence():
    sequences = registry.control_sequences("gemma-4-26b-a4b")
    assert (("<|channel>", "thought", "\n", "<channel|>"),) == sequences


def test_model_without_override_has_no_control_sequence():
    assert () == registry.control_sequences("gpt-oss-20b")


def _good_scorer(messages):
    """A fake first-token scorer: 'B' wins the decision position."""
    return {
        "top_logprobs": [
            {"token": "B", "logprob": -0.1},
            {"token": "A", "logprob": -3.0},
            {"token": "the", "logprob": -4.0},
        ],
        "decision_position": 1,
        "skipped_prefix": ["<|channel>"],
        "skipped_len": 1,
        "succeeded": True,
        "raw_logprob_response": "{}",
    }


def test_cell_record_carries_the_full_spec_field_set(tmp_path):
    cell = ("gpt-oss-20b", 0, "disease", "gain", "blinded")
    record = _write_one_record(tmp_path, "gpt-oss-20b", cell, _good_scorer)
    for key in (
        "model", "model_id", "persona_id", "experiment", "qid", "arm",
        "blind", "system_prompt", "user_prompt", "prompt_sha256",
        "options_original", "label_map", "top_logprobs",
        "decision_position", "skipped_prefix", "skipped_len", "p_raw",
        "branch_mass", "p_norm", "expected_response", "low_branch_mass",
        "elapsed_seconds", "timestamp", "inference", "succeeded", "error",
    ):
        assert key in record, f"missing record field {key}"
    assert record["succeeded"] is True and record["error"] is None
    assert record["expected_response"] == record["expected_1_6"]
    assert record["inference"]["logprob_mode"] == "first_token"
    assert record["inference"]["seed"] == config.SEED


def test_failing_call_is_kept_with_error_and_no_fake_zero(tmp_path):
    def broken_scorer(messages):
        raise OSError("connection refused")

    cell = ("gpt-oss-20b", 0, "disease", "gain", "blinded")
    record = _write_one_record(tmp_path, "gpt-oss-20b", cell, broken_scorer)
    assert record["succeeded"] is False
    assert "connection refused" in record["error"]
    assert record["expected_1_6"] is None
    assert record["expected_response"] is None
    assert record["p_safe_norm"] is None


def test_leg_cells_counts_personas_times_arms_for_one_blinding():
    cells = legexec.leg_cells("gpt-oss-20b", [0, 1, 2], "disease", "blinded")
    assert len(cells) == 6  # 3 personas x 2 arms, blinded only
    assert {cell[4] for cell in cells} == {"blinded"}


def test_preflight_flags_stop_on_empty_top_logprobs(tmp_path):
    stimuli = experiments.load_stimuli()

    def empty_scorer(messages):
        return {"top_logprobs": [], "decision_position": None,
                "skipped_prefix": [], "skipped_len": None,
                "succeeded": True, "raw_logprob_response": "{}"}

    cell = ("gemma-4-31b-it-qat", 0, "disease", "gain", "blinded")
    record = _write_one_record(
        tmp_path, "gemma-4-31b-it-qat", cell, empty_scorer)
    summary = preflight.summarize_model("gemma-4-31b-it-qat", [record], stimuli)
    assert summary["stop"] is True
    assert summary["empty_top_logprobs"] == 1


def test_preflight_clean_record_is_not_flagged(tmp_path):
    stimuli = experiments.load_stimuli()
    cell = ("gpt-oss-20b", 0, "disease", "gain", "blinded")
    record = _write_one_record(tmp_path, "gpt-oss-20b", cell, _good_scorer)
    summary = preflight.summarize_model("gpt-oss-20b", [record], stimuli)
    assert summary["stop"] is False


def test_leakage_check_accepts_demographics_only_pool():
    clean = _personas()
    assert preflight.leakage_check(clean)["ok"] is True
    dirty = [{**clean[0], "twin2k_risk_attitude": 7}]
    verdict = preflight.leakage_check(dirty)
    assert verdict["ok"] is False
    assert "twin2k_risk_attitude" in verdict["unexpected_fields"]


def test_stop_model_is_written_to_the_skip_list(tmp_path):
    def empty_scorer(messages):
        return {"top_logprobs": [], "decision_position": None,
                "skipped_prefix": [], "skipped_len": None,
                "succeeded": True, "raw_logprob_response": "{}"}

    cell = ("gemma-4-31b-it-qat", 0, "disease", "gain", "blinded")
    record = _write_one_record(
        tmp_path, "gemma-4-31b-it-qat", cell, empty_scorer)
    outcome = preflight.write_outputs(
        tmp_path, {"gemma-4-31b-it-qat": [record]}, _personas(),
        {"run_dir": str(tmp_path), "records": 1},
    )
    assert outcome["stopped"] == ["gemma-4-31b-it-qat"]
    skip_list = json.loads(
        (tmp_path / "skipped_models.json").read_text(encoding="utf-8")
    )
    assert skip_list["skipped_models"] == ["gemma-4-31b-it-qat"]
    report = (tmp_path / "PREFLIGHT_REPORT.md").read_text(encoding="utf-8")
    assert "STOP — technical failure" in report
    assert "does NOT auto-launch" in report


def test_figures_selftest_renders_exactly_three_figures(tmp_path):
    from twin2k6 import figures

    written = figures.selftest(tmp_path)
    names = {path.name for path in written}
    assert names == {
        "fig1_treatment_profiles.pdf", "fig1_treatment_profiles.png",
        "fig1_tidy.csv",
        "fig2_unblinding_gain_heatmap.pdf", "fig2_unblinding_gain_heatmap.png",
        "fig2_tidy.csv",
        "fig3_overall_error.pdf", "fig3_overall_error.png",
        "fig3_tidy.csv",
    }
    for path in written:
        assert path.stat().st_size > 0


def test_progress_file_is_written_at_least_every_50_records(tmp_path):
    from twin2k6 import runner

    progress = runner.new_progress(total=120)
    for _ in range(50):
        runner.note_record(tmp_path, progress, "full", "gpt-oss-20b")
    progress_file = tmp_path / "progress.json"
    assert progress_file.is_file()
    payload = json.loads(progress_file.read_text(encoding="utf-8"))
    assert payload["records_done"] == 50
    assert payload["records_total"] == 120


def test_records_per_model_matches_the_pinned_grid():
    from twin2k6 import runner

    assert runner.records_per_model("full") == 3200
    assert runner.records_per_model("preflight") == 32


# --- TASK-2080: ensure_model_loaded must load FIRST, then poll health ---
# After an explicit unload nothing listens on :8080, so a health probe made
# before the load decision used to crash the run. These tests fake the
# manager, the health endpoint and the clock so everything stays offline.


class _FakeHealthReply:
    """A stand-in for the reply urlopen gives: just a status number."""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeHealthReply":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _patch_manager(monkeypatch, status: dict, calls: list) -> None:
    """Fake the manager's status answer (and remember that it was asked)."""
    import launch_support

    def fake_status(manager_url: str) -> dict:
        calls.append(manager_url)
        if isinstance(status, Exception):
            raise status
        return status

    monkeypatch.setattr(launch_support, "_manager_status", fake_status)


def _patch_load(monkeypatch, calls: list, on_load=None) -> None:
    """Fake the model load so no real manager or GPU is ever touched."""
    import launch_support

    def fake_load(manager_url: str, model_id: str, port: int) -> None:
        calls.append((manager_url, model_id, port))
        if on_load is not None:
            on_load()

    monkeypatch.setattr(launch_support, "_load_model", fake_load)


def test_ensure_model_loaded_skips_load_when_manager_reports_model_healthy(monkeypatch):
    from twin2k6 import config, registry, runner

    model = config.MODELS[0]
    model_id = registry.manager_model_id(model)
    manager_calls: list = []
    load_calls: list = []
    health_calls: list = []
    _patch_manager(monkeypatch, {"8080": {"model": model_id}}, manager_calls)
    _patch_load(monkeypatch, load_calls)

    def fake_urlopen(url, timeout):
        health_calls.append(url)
        return _FakeHealthReply(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    runner.ensure_model_loaded("http://127.0.0.1:8081", "http://127.0.0.1:8080", model, 8080)
    assert load_calls == []
    assert len(health_calls) <= 1


def test_ensure_model_loaded_loads_model_when_nothing_listens_on_port(monkeypatch):
    import urllib.error

    from twin2k6 import config, registry, runner

    model = config.MODELS[0]
    model_id = registry.manager_model_id(model)
    load_calls: list = []
    _patch_manager(monkeypatch, {}, [])
    _patch_load(monkeypatch, load_calls, on_load=lambda: state.update(loaded=True))
    state = {"loaded": False}

    def fake_urlopen(url, timeout):
        if not state["loaded"]:
            raise urllib.error.URLError(ConnectionRefusedError("Connection refused"))
        return _FakeHealthReply(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    runner.ensure_model_loaded("http://127.0.0.1:8081", "http://127.0.0.1:8080", model, 8080)
    assert load_calls == [("http://127.0.0.1:8081", model_id, 8080)]


def test_ensure_model_loaded_retries_health_until_server_comes_up(monkeypatch):
    import urllib.error

    from twin2k6 import config, runner

    attempts: list = []
    load_calls: list = []
    _patch_manager(monkeypatch, {}, [])
    _patch_load(monkeypatch, load_calls)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    def fake_urlopen(url, timeout):
        attempts.append(url)
        if len(attempts) < 3:
            raise urllib.error.URLError(ConnectionRefusedError("Connection refused"))
        return _FakeHealthReply(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    runner.ensure_model_loaded("http://127.0.0.1:8081", "http://127.0.0.1:8080", config.MODELS[0], 8080)
    assert len(attempts) >= 3
    assert len(load_calls) == 1


def test_ensure_model_loaded_raises_after_health_poll_timeout(monkeypatch):
    import urllib.error

    from twin2k6 import config, runner

    load_calls: list = []
    _patch_manager(monkeypatch, {}, [])
    _patch_load(monkeypatch, load_calls)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        clock["now"] += 100.0
        return clock["now"]

    monkeypatch.setattr("time.monotonic", fake_monotonic)

    def fake_urlopen(url, timeout):
        raise urllib.error.URLError(ConnectionRefusedError("Connection refused"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="600s"):
        runner.ensure_model_loaded("http://127.0.0.1:8081", "http://127.0.0.1:8080", config.MODELS[0], 8080)
    assert len(load_calls) == 1


def test_ensure_model_loaded_still_fails_when_manager_is_down(monkeypatch):
    from twin2k6 import config, runner

    health_calls: list = []
    load_calls: list = []
    _patch_manager(monkeypatch, OSError("connection refused"), [])
    _patch_load(monkeypatch, load_calls)

    def fake_urlopen(url, timeout):
        health_calls.append(url)
        return _FakeHealthReply(200)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="8081"):
        runner.ensure_model_loaded("http://127.0.0.1:8081", "http://127.0.0.1:8080", config.MODELS[0], 8080)
    assert load_calls == []
    assert health_calls == []


# --- TASK-2083: a full run must skip cells the preflight already finished ---
# The preflight writes persona 0's records under <run_dir>/PREFLIGHT/...;
# a full launch right after must NOT measure those cells again (spec §10:
# never duplicate a completed record). A fake PREFLIGHT leg file is read
# by the planner exactly like a real one, and the fake scorer keeps both
# tests fully offline.


def _run_one_model_full(run_dir, monkeypatch) -> None:
    """Run gpt-oss-20b's whole full-mode leg block for persona 0, offline."""
    from twin2k6 import runner

    monkeypatch.setattr(legexec, "make_scorer", lambda context: _good_scorer)
    runner.run_model(
        "gpt-oss-20b", run_dir, "full", _personas(), [0],
        "http://127.0.0.1:8080", runner.new_progress(total=16),
    )


def _leg_records(run_dir, model: str, leg: str) -> list[dict]:
    """The records a full run wrote into one leg's file, in file order."""
    path = run_dir / registry.safe_model_name(model) / leg / "records.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_full_run_skips_the_cell_preflight_already_completed(tmp_path, monkeypatch, capsys):
    model = "gpt-oss-20b"
    run_dir = tmp_path / "run"
    cell = (model, 0, "disease", "gain", "blinded")
    preflight_dir = (
        run_dir / "PREFLIGHT" / registry.safe_model_name(model) / "disease_blinded"
    )
    preflight_dir.mkdir(parents=True)
    context = legexec.make_leg_context(model, "http://127.0.0.1:8080", _personas())
    cells.run_cells(
        [cell],
        legexec.make_transport(context, lambda record: None, scorer=_good_scorer),
        preflight_dir / "records.jsonl",
    )

    _run_one_model_full(run_dir, monkeypatch)

    full_records = _leg_records(run_dir, model, "disease_blinded")
    assert [(r["persona_id"], r["arm"]) for r in full_records] == [(0, "loss")]
    assert "1 skipped from preflight" in capsys.readouterr().out
    preflight_records = _leg_records(
        run_dir / "PREFLIGHT", model, "disease_blinded"
    )
    assert len(preflight_records) == 1  # the preflight file was only read


def test_full_run_without_preflight_records_runs_every_cell(tmp_path, monkeypatch):
    model = "gpt-oss-20b"
    run_dir = tmp_path / "run"  # no PREFLIGHT dir exists in a fresh run dir

    _run_one_model_full(run_dir, monkeypatch)

    full_records = _leg_records(run_dir, model, "disease_blinded")
    assert [(r["persona_id"], r["arm"]) for r in full_records] == [
        (0, "gain"), (0, "loss"),
    ]
