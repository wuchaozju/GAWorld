# Locked tests for the R1-YESNO-QWENEXT RUNNER WIRING - launcher entry and
# queue execution (TASK-1631, RED phase; tests ONLY - no implementation
# lives here). Resume-at-cell-granularity lives in
# tests/test_launch_qwenext_resume.py.
#
# WHY THESE TESTS EXIST: scripts/launch_yesno_qwenext.py is a merged pure
# specification (profile constants, 3-model queue, shared [40, 60) slice,
# build_qwenext_plan, offline print_qwenext_dry_run; locked green by
# tests/test_launch_yesno_qwenext.py). What does not exist yet is the
# WIRING: a way to actually EXECUTE the QWENEXT plan through the existing
# queue runner machinery (load/run/unload per model, durability artifacts,
# manifest). These tests pin that wiring contract, all offline (no
# manager, no GPU, no server):
#
#   (1) REACHABLE: --profile R1-YESNO-QWENEXT goes through launch_grid's
#       established --profile dispatch (the same mechanism that starts
#       R1-5MODEL / R1LP / R1-YESNO today) and dry-runs the QWENEXT plan.
#   (2) SETTINGS: the profile's settings mirror R1-YESNO exactly -
#       first_token scoring, the yes/no response words, no grammar.
#   (3) EXECUTION: the real run executes the QWENEXT plan through the
#       EXISTING runner (launch_5model.run_queue, reuse not fork):
#       iterating QWENEXT_MODEL_QUEUE, loading each model through the
#       model manager on the run's port, running its 4 legs, unloading,
#       and writing the same durability artifacts (per-leg records.jsonl,
#       results.csv, progress.json, run manifest).
#   (4) STAMPING: the run manifest stamps profile "R1-YESNO-QWENEXT"
#       (not R1-YESNO / R1LP) and the per-model persona range [40, 60).
#   (5) RESUME through the launcher: a fully completed run resumes as a
#       safe no-op that never loads a model.
#   (6) NO NEW NETWORK PATHS: the dry-run and the full offline run work
#       with the socket constructor refused; the run only touches the
#       existing manager/chat seams (which the tests fake).
#
# The locked tests in test_launch_yesno_qwenext.py (the spec) and
# test_launch_queue.py / test_r1lp_wiring.py / test_r1_yesno.py (the
# existing profiles) stay green. No test here touches a real server: the
# injected fakes ARE the transport, and the dry-run paths never dial.
import csv
import json
import socket
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import launch_5model as queue_module  # noqa: E402
from launch_cells import results_csv_path  # noqa: E402
from launch_queue import queue_leg_dir, queue_leg_jsonl  # noqa: E402
from launch_support import Settings  # noqa: E402
from launch_sweep import AbortSignal  # noqa: E402
from launch_yesno_qwenext import (  # noqa: E402
    QWENEXT_MODEL_QUEUE,
    QWENEXT_PROFILE,
    build_qwenext_plan,
)

# The three Qwen models of the QWENEXT queue, in run order (the manager's
# registry ids; locked character-for-character by the spec tests).
EXPECTED_MODELS = (
    "qwen/qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive",
    "qwen3-4b",
)
PRODUCTS = [
    {"category": "Soft Drinks", "product": "Cola 12 oz", "regular_price": 1.99},
    {"category": "Chips", "product": "Potato Chips", "regular_price": 2.99},
]
LEVELS = [0.0, 100.0]
POOL_SIZE = 100  # every product's shared pool holds 100 personas


def _forbid_sockets(monkeypatch, reason: str) -> None:
    """Refuse every dial for the guarded block (offline proof)."""
    def _refuse(*_args, **_kwargs):
        raise AssertionError(reason)

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def _offline_scorer_result() -> dict:
    """A minimal first_token scorer result in the yes/no record shape."""
    return {
        "succeeded": True,
        "parsed_purchase": True,
        "raw_content": " yes",
        "p_yes": 0.9,
        "p_no": 0.1,
    }


def _settings(tmp_path: Path, run_name: str) -> Settings:
    """One QWENEXT launch configuration pointed at a throwaway directory."""
    return Settings(
        model="vendor/model",
        port=8080,
        manager_url="http://127.0.0.1:9",  # nothing listens here; faked anyway
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name=run_name,
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="products.json",
        grammar=None,
        logprob_mode="first_token",
        response_format="yes/no",
    )


def _plan() -> dict:
    """The QWENEXT plan for 2 products x 2 levels (offline-sized)."""
    return build_qwenext_plan(len(PRODUCTS), len(LEVELS), levels=LEVELS)


def _write_shared_pool(run_dir: Path, products: list[dict]) -> None:
    """A completed shared pool: 100 pids per product + the matching marker."""
    pools_dir = run_dir / "pools"
    pools_dir.mkdir(parents=True, exist_ok=True)
    for product in products:
        stem = product["product"].lower().replace(" ", "_")
        with (pools_dir / f"{stem}.jsonl").open("w", encoding="utf-8") as handle:
            for pid in range(POOL_SIZE):
                handle.write(json.dumps({"pid": pid}) + "\n")
    (run_dir / "pools.json").write_text(
        json.dumps({"k": POOL_SIZE, "pool_seed": 42, "products": len(products)}),
        encoding="utf-8",
    )


def _write_done_leg(run_dir: Path, leg: dict, records: int = 2) -> None:
    """Write one FINISHED queue leg's files (records.jsonl + csv + manifest)."""
    leg_dir = queue_leg_dir(run_dir, leg)
    leg_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "model": leg["model"],
                "product": PRODUCTS[0]["product"],
                "treatment_value": 0.0,
                "blinding": leg["blinding"],
                "persona_depth": leg["depth"],
                "persona": {"pid": 40 + index},
                "persona_index": index,
                "succeeded": True,
                "elapsed_seconds": 0.1,
            }
        )
        for index in range(records)
    ]
    queue_leg_jsonl(leg_dir).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (leg_dir / "records.csv").write_text("", encoding="utf-8")
    (leg_dir / "manifest.json").write_text(
        json.dumps({"depth": leg["depth"], "blinding": leg["blinding"]}),
        encoding="utf-8",
    )


def _csv_rows(path: Path) -> list[dict]:
    """Read the results.csv rows (minus the header)."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _run_qwenext_queue(monkeypatch, tmp_path: Path, plan: dict, run_name: str):
    """Drive launch_5model.run_queue over the QWENEXT plan fully offline.

    Fakes ONLY the existing network seams (manager load/unload, the
    logprob scorer builder, the health watchdog) and refuses sockets, so
    the test proves the run goes through the existing machinery. Returns
    (exit_code, calls, run_dir) with calls = {"loads", "unloads"}.
    """
    calls: dict[str, list] = {"loads": [], "unloads": []}
    settings = _settings(tmp_path, run_name)
    run_dir = settings.out / settings.run_name
    _write_shared_pool(run_dir, PRODUCTS)

    def fake_load(manager_url: str, model: str, port: int) -> None:
        calls["loads"].append((model, port))

    def fake_unload(manager_url: str, port: int) -> None:
        calls["unloads"].append(port)

    def fake_scorer_factory(model_settings, total, progress, stop=None, **_kwargs):
        state = {"done": 0, "parsed": 0}
        lock = threading.Lock()
        abort = AbortSignal("offline probe")

        def scorer(_messages):
            with lock:
                state["done"] += 1
                state["parsed"] += 1
            return _offline_scorer_result()

        return scorer, state, abort

    def fake_watchdog(_settings, _abort, _done_event, _log) -> None:
        return None

    monkeypatch.setattr(queue_module, "_load_model", fake_load)
    monkeypatch.setattr(queue_module, "_unload_model", fake_unload)
    monkeypatch.setattr(queue_module, "_make_logprob_scorer", fake_scorer_factory)
    monkeypatch.setattr(queue_module, "_watchdog", fake_watchdog)
    _forbid_sockets(monkeypatch, "the offline qwenext run must not dial out")
    # resume=True: the run dir legitimately holds the pre-existing shared
    # pool fixture, so this invocation continues it (the same --resume
    # semantics a real pool-reusing run has).
    args = SimpleNamespace(resume=True, force=False, pools_from="")
    code = queue_module.run_queue(args, plan, PRODUCTS, Path("products.json"), settings)
    return code, calls, run_dir


# ---------------------------------------------------------------------------
# (1) Reachable: --profile R1-YESNO-QWENEXT through launch_grid's dispatch
# ---------------------------------------------------------------------------


def test_qwenext_profile_is_reachable_from_the_launcher_dry_run(monkeypatch, capsys):
    """launch_grid --profile R1-YESNO-QWENEXT --dry-run is accepted through
    the SAME --profile dispatch that starts R1-5MODEL / R1LP / R1-YESNO,
    prints the QWENEXT plan (all three models on their shared slice), and
    never dials (the socket constructor is refused for the whole call)."""
    _forbid_sockets(monkeypatch, "the qwenext dry run must not contact anything")
    from launch_grid import main

    try:
        code = main(["--profile", QWENEXT_PROFILE, "--dry-run"])
    except SystemExit as exc:
        pytest.fail(
            "launch_grid refused --profile R1-YESNO-QWENEXT (exit "
            f"{exc.code}): the QWENEXT profile is not registered in the "
            "launcher's --profile dispatch yet"
        )
    assert code == 0
    out = capsys.readouterr().out
    assert f"{QWENEXT_PROFILE} launch plan (dry run)" in out, (
        f"the dry run must announce the QWENEXT profile; got:\n{out}"
    )
    for model in EXPECTED_MODELS:
        assert model in out, f"the dry run must list {model}; got:\n{out}"
    assert "pool personas 40-59" in out, (
        f"the dry run must show the shared [40, 60) slice; got:\n{out}"
    )
    assert "55,440" in out, f"the queue total must be visible; got:\n{out}"
    assert "root ::=" not in out, "the purchase grammar must never appear"


def test_qwenext_settings_score_first_token_yes_no_without_grammar():
    """The settings the real QWENEXT run would use mirror R1-YESNO exactly:
    first_token scoring, the yes/no response words, and no grammar."""
    from launch_grid import _parse_args, _settings_from

    try:
        args = _parse_args(["--profile", QWENEXT_PROFILE])
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {QWENEXT_PROFILE} (exit {exc.code}): "
            "the QWENEXT profile is not registered yet"
        )
    settings = _settings_from(args, "wiring-probe")
    assert settings.logprob_mode == "first_token", (
        f"QWENEXT must score first_token like R1-YESNO; got "
        f"{settings.logprob_mode!r}"
    )
    assert settings.response_format == "yes/no", (
        f"QWENEXT must ask the yes/no response words like R1-YESNO; got "
        f"{settings.response_format!r}"
    )
    assert settings.grammar is None, "QWENEXT is grammar-free like R1-YESNO"


# ---------------------------------------------------------------------------
# (3)+(4) Execution: the EXISTING runner drives the QWENEXT plan
# ---------------------------------------------------------------------------


def test_qwenext_run_executes_all_twelve_legs_through_the_queue_runner(
    monkeypatch, tmp_path
):
    """A real QWENEXT run executes the plan through the existing queue
    runner: the three models are loaded through the manager in queue order
    (each on the run's port) and unloaded, their 12 legs run, and the usual
    durability artifacts appear with the run stamped R1-YESNO-QWENEXT."""
    plan = _plan()
    code, calls, run_dir = _run_qwenext_queue(
        monkeypatch, tmp_path, plan, "qwenext-runner-probe"
    )
    assert code == 0, (
        f"the QWENEXT run must complete through the queue runner (exit "
        f"{code} - today's runner never dispatches the plan's legs)"
    )
    # Each of the three models was loaded ONCE through the manager seam,
    # in queue order, on the run's port - then unloaded.
    assert [model for model, _port in calls["loads"]] == list(EXPECTED_MODELS)
    assert {port for _model, port in calls["loads"]} == {8080}
    assert len(calls["unloads"]) == 3
    # The run manifest stamps the QWENEXT profile and the R1-YESNO
    # response shape, and self-describes the shared per-model slice.
    payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["profile"] == QWENEXT_PROFILE
    assert payload["state"] == "complete" and payload["ok"] is True
    assert payload["logprob_mode"] == "first_token"
    assert payload["response_format"] == "yes/no"
    assert payload["grammar"] is None
    assert [m["model"] for m in payload["models"]] == list(EXPECTED_MODELS)
    for meta in payload["models"]:
        assert meta["persona_slice"] == [40, 60]
    # All 12 planned legs merged exactly once, in plan order, all ok.
    merged = [
        (leg["model_index"], leg["depth"], leg["blinding"]) for leg in payload["legs"]
    ]
    expected = [(t["model_index"], t["depth"], t["blinding"]) for t in plan["legs"]]
    assert merged == expected and len(merged) == len(set(merged))
    assert all(leg["ok"] for leg in payload["legs"])
    # Every leg durably wrote exactly its planned cells.
    for leg in plan["legs"]:
        jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, leg))
        records = [line for line in jsonl.read_text().splitlines() if line]
        assert len(records) == leg["calls"]
    # results.csv holds exactly one row per executed cell; progress finished.
    assert len(_csv_rows(results_csv_path(run_dir))) == plan["sweep_calls"]
    assert (run_dir / "progress.json").exists()


# ---------------------------------------------------------------------------
# (5b) Resume through the launcher: a completed run is a safe no-op
# ---------------------------------------------------------------------------


def test_completed_qwenext_run_resumes_through_the_launcher_without_loading_models(
    monkeypatch, tmp_path
):
    """launch_grid --profile R1-YESNO-QWENEXT --resume against a fully
    completed QWENEXT run is a safe no-op: exit 0, no model ever loaded,
    and the final manifest keeps the run's profile stamp and every leg
    exactly once."""
    _forbid_sockets(monkeypatch, "a resumed no-op run must not dial out")
    from launch_grid import main

    plan = build_qwenext_plan(40, 11, levels=[float(x) for x in range(0, 220, 20)])
    run_name = "qwenext-noop-probe"
    run_dir = tmp_path / run_name
    run_dir.mkdir(parents=True)
    for leg in plan["legs"]:
        _write_done_leg(run_dir, leg, records=2)
    (run_dir / "pools.json").write_text(
        json.dumps({"k": POOL_SIZE, "pool_seed": 42, "products": 40}),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps({"state": "running", "started": "2026-01-01T00:00:00"}),
        encoding="utf-8",
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a fully resumed QWENEXT run must not load a model")

    monkeypatch.setattr(queue_module, "_load_model", forbidden)
    try:
        code = main(
            [
                "--profile",
                QWENEXT_PROFILE,
                "--run-name",
                run_name,
                "--out",
                str(tmp_path),
                "--resume",
            ]
        )
    except SystemExit as exc:
        pytest.fail(
            f"launch_grid refused --profile {QWENEXT_PROFILE} (exit {exc.code}): "
            "the QWENEXT profile is not registered yet"
        )
    assert code == 0
    payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert payload["state"] == "complete" and payload["ok"] is True
    assert payload["profile"] == QWENEXT_PROFILE
    merged = [
        (leg["model_index"], leg["depth"], leg["blinding"]) for leg in payload["legs"]
    ]
    expected = [(t["model_index"], t["depth"], t["blinding"]) for t in plan["legs"]]
    assert merged == expected and len(merged) == len(set(merged))
    assert [m["model"] for m in payload["models"]] == list(EXPECTED_MODELS)
