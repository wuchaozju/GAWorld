# Locked tests for the launch wrapper's graceful stop (TASK-1525).
#
# WHY THESE TESTS EXIST: TASK-1522 proved leg-granular resume - a hard kill
# mid-leg loses that leg's in-memory progress and the leg is re-run from
# scratch on --resume. TASK-1525 closes the gap in the WRAPPER only: a
# graceful stop (first SIGINT/SIGTERM) lets the launcher finish the legs
# that are already running (zero loss, at the cost of letting the current
# leg finish), then records the run with state "stopped_gracefully"; a
# second signal escalates to an immediate hard stop (leg-granular resume
# applies, per 1522).
#
# THE CONTRACT THESE TESTS PIN (TASK-1525):
#   1. The stop-flag machine: the FIRST stop request is graceful, the second
#      is a hard stop (and --force makes even the first one hard).
#   2. The leg driver honours the flag: legs are only started while the flag
#      is still "running"; a graceful stop while legs run lets them finish
#      (nothing is lost) and starts no new leg; a hard stop raises the abort
#      event so in-flight legs stop before finishing.
#   3. A graceful stop writes state "stopped_gracefully" with every planned
#      leg listed exactly once (done legs ok, never-started legs marked not
#      ok), and --resume afterwards plans exactly the legs that never ran.
#
# Every test runs offline: legs are synthetic functions, no model server,
# no manager, no GPU. The leg driver under test is the same function the
# real launcher uses (launch_stop._drive_legs).
import json
import sys
import tempfile
import threading
import time
from argparse import Namespace
from pathlib import Path

# The launch scripts live in scripts/ and are not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from launch_stop import AbortSignal, StopFlag, _drive_legs  # noqa: E402
from launch_support import Settings  # noqa: E402

SAFE_MODEL = "vendor_model"
FIVE_TARGETS = [
    {"depth": depth, "blinding": blinding}
    for depth, blinding in [
        ("none", "blinded"),
        ("none", "unblinded"),
        ("demographics", "blinded"),
        ("demographics", "unblinded"),
        ("stage2", "blinded"),
    ]
]
FIVE_KEYS = [(t["depth"], t["blinding"]) for t in FIVE_TARGETS]


def _settings(tmp_path: Path) -> Settings:
    """One launch configuration pointed at a throwaway directory."""
    return Settings(
        model="vendor/model",
        port=8080,
        manager_url="http://127.0.0.1:9",  # nothing listens here; never called
        base_url="http://127.0.0.1:9",
        out=tmp_path,
        run_name="stop-probe",
        pool_seed=42,
        pool_overdraw=1.2,
        seed=7,
        draws=1,
        progress_every=10,
        products_path="data/configs/unblinding_products.json",
    )


def _plan(targets: list[dict[str, str]]) -> dict:
    """A plan object shaped like launch_grid._plan's output."""
    return {
        "profile": "R1",
        "k": 100,
        "levels": [0.0, 100.0],
        "legs": [{**target, "calls": 4} for target in targets],
        "sweep_calls": len(targets) * 4,
        "pool_draws": 20,
        "depths": ["none", "demographics"],
    }


def _write_leg(run_dir: Path, depth: str, blinding: str, records: int = 3) -> None:
    """Write one finished leg's files exactly as the wrapper leaves them."""
    leg_dir = run_dir / f"{depth}_{blinding}"
    leg_dir.mkdir(parents=True, exist_ok=True)
    with (leg_dir / f"{SAFE_MODEL}_{blinding}.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for index in range(records):
            handle.write(
                json.dumps({"succeeded": True, "elapsed_seconds": 0.5, "draw": index})
                + "\n"
            )
    (leg_dir / f"{SAFE_MODEL}_{blinding}.csv").write_text("", encoding="utf-8")
    (leg_dir / "manifest.json").write_text(
        json.dumps({"depth": depth, "blinding": blinding}), encoding="utf-8"
    )


def _leg_result(depth: str, blinding: str) -> dict:
    """A leg result exactly as launch_sweep._save_leg_outputs records it."""
    return {
        "depth": depth,
        "blinding": blinding,
        "ok": True,
        "records": 3,
        "parsed": 3,
        "parse_rate": 1.0,
        "mean_elapsed": 0.5,
        "files": ["x.jsonl", "x.csv", "manifest.json"],
    }


def _read_manifest(run_dir: Path) -> dict:
    """Read the run-level manifest on disk."""
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


# Synthetic legs ------------------------------------------------------------
# A synthetic leg is a function that runs on its own thread. It ticks until
# it has done `ticks` units, unless the abort event fires first (that is how
# the real legs stop: chat_fn raises when abort is set). A release event can
# hold the leg open so the test controls when it finishes.


def _synthetic_leg(
    results: list[dict],
    name: str,
    *,
    abort: AbortSignal,
    release: threading.Event | None = None,
    ticks: int = 1000,
) -> None:
    """One synthetic leg body: ticks, or stops when abort fires."""
    for _ in range(ticks):
        if abort.is_set():
            results.append({"name": name, "ok": False, "early": True})
            return
        if release is not None and release.is_set():
            break
        time.sleep(0.001)
    results.append({"name": name, "ok": True, "early": False})


def _start_synthetic(target) -> threading.Thread:
    """Start one synthetic leg on a daemon thread."""
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


# --- 1. The stop-flag machine ----------------------------------------------


def test_first_stop_request_is_graceful_second_is_hard():
    """The stop flag: request 1 is graceful, request 2 escalates to hard."""
    stop = StopFlag()
    assert stop.level() == "running"
    assert stop.request() == "graceful"
    assert stop.level() == "graceful"
    assert stop.request() == "hard"
    assert stop.level() == "hard"
    assert stop.request() == "hard"  # stays hard


def test_force_first_flag_makes_even_the_first_signal_hard():
    """--force (force_first) turns the first request into a hard stop."""
    stop = StopFlag(force_first=True)
    assert stop.request() == "hard"
    assert stop.level() == "hard"


# --- 2. The leg driver honours the stop flag -------------------------------


def test_driver_starts_no_leg_once_a_stop_is_already_requested():
    """If a graceful stop was requested before the sweep launched, no leg is
    started at all; they stay for a later --resume."""
    stop = StopFlag()
    stop.request()  # graceful, before launch
    started: list[str] = []
    lines: list[str] = []

    def start_one(leg: dict) -> threading.Thread:
        started.append(leg["blinding"])
        return _start_synthetic(lambda: None)

    level = _drive_legs(
        FIVE_TARGETS,
        stop,
        AbortSignal("watchdog"),
        lines.append,
        start_one,
        planned_calls=0,
        calls_done=lambda: 0,
    )
    assert started == []
    assert level == "graceful"
    assert any("not starting" in line for line in lines)


def test_driver_starts_no_new_leg_after_a_graceful_stop_mid_launch():
    """Legs are only started while the flag is "running": a graceful stop that
    lands between launches leaves the remaining legs unstarted (they run on a
    later --resume), while the started leg is allowed to finish."""
    stop = StopFlag()
    started: list[str] = []
    results: list[dict] = []
    abort = AbortSignal("watchdog")
    release = threading.Event()
    lines: list[str] = []

    def start_one(leg: dict) -> threading.Thread:
        started.append(leg["blinding"])
        # Simulate the operator's first signal arriving right after the first
        # leg launches (before the driver would start the next one).
        if len(started) == 1:
            stop.request()
        return _start_synthetic(
            lambda: _synthetic_leg(
                results, leg["blinding"], abort=abort, release=release
            )
        )

    release.set()  # let the started leg finish once it ticks
    level = _drive_legs(
        FIVE_TARGETS,
        stop,
        abort,
        lines.append,
        start_one,
        planned_calls=5,
        calls_done=lambda: 0,
    )
    # The stop landed mid-launch: only the first leg started; it ran to
    # completion (nothing lost) and no further leg was started.
    assert started == ["blinded"]
    assert len(results) == 1 and results[0]["ok"] is True
    assert level == "graceful"
    assert not abort.is_set()
    assert any("graceful stop requested" in line for line in lines)


def test_graceful_stop_mid_run_loses_nothing():
    """A graceful stop while legs are running: every in-flight leg finishes
    (no results are lost) and the abort event is never raised."""
    stop = StopFlag()
    abort = AbortSignal("watchdog")
    release = threading.Event()
    results: list[dict] = []
    lines: list[str] = []
    targets = [
        {"depth": "none", "blinding": "blinded"},
        {"depth": "none", "blinding": "unblinded"},
    ]

    def start_one(leg: dict) -> threading.Thread:
        return _start_synthetic(
            lambda: _synthetic_leg(
                results, leg["blinding"], abort=abort, release=release
            )
        )

    driver = threading.Thread(
        target=lambda: _drive_legs(
            targets,
            stop,
            abort,
            lines.append,
            start_one,
            planned_calls=2,
            calls_done=lambda: len(results),
        ),
        daemon=True,
    )
    driver.start()
    time.sleep(0.05)  # both legs running
    assert stop.request() == "graceful"
    release.set()  # let the in-flight legs finish (graceful never aborts)
    driver.join(timeout=5)
    assert stop.level() == "graceful"
    assert not abort.is_set()
    assert {r["name"] for r in results} == {"blinded", "unblinded"}
    assert all(r["ok"] for r in results)
    assert any(
        "graceful stop requested" in line and "calls remaining in flight" in line
        for line in lines
    )


def test_double_signal_hard_stops_inflight_legs():
    """A second signal escalates: the abort event fires, in-flight legs stop
    before completing (so they are re-run by --resume), and the driver
    reports the hard stop."""
    stop = StopFlag()
    abort = AbortSignal("watchdog")
    results: list[dict] = []
    lines: list[str] = []
    targets = [
        {"depth": "none", "blinding": "blinded"},
        {"depth": "none", "blinding": "unblinded"},
    ]

    def start_one(leg: dict) -> threading.Thread:
        return _start_synthetic(
            lambda: _synthetic_leg(results, leg["blinding"], abort=abort, ticks=100000)
        )

    driver = threading.Thread(
        target=lambda: _drive_legs(
            targets,
            stop,
            abort,
            lines.append,
            start_one,
            planned_calls=2,
            calls_done=lambda: 0,
        ),
        daemon=True,
    )
    driver.start()
    time.sleep(0.05)
    assert stop.request() == "graceful"
    assert stop.request() == "hard"  # second signal escalates
    driver.join(timeout=5)
    assert stop.level() == "hard"
    assert abort.is_set()
    assert {r["name"] for r in results} == {"blinded", "unblinded"}
    assert all(r["early"] for r in results)  # stopped before finishing
    assert any("hard stop" in line for line in lines)


# --- 3. Run-level graceful stop: manifest marker + resume -------------------


def test_graceful_stop_manifest_marks_state_and_leg_statuses():
    """A stopped run's manifest lists every planned leg exactly once with its
    completion status (done legs ok, never-started legs marked not ok) under
    state stopped_gracefully."""
    from launch_manifest import _write_run_manifest

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _settings(tmp_path)
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        _write_run_manifest(
            settings,
            _plan(FIVE_TARGETS),
            Path("products.json"),
            run_dir,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T01:00:00+00:00",
            [_leg_result("none", "blinded"), _leg_result("none", "unblinded")],
            None,
            targets=FIVE_TARGETS,
            safe_model=SAFE_MODEL,
            prior=None,
            resume_invocation=False,
            state="stopped_gracefully",
        )
        payload = _read_manifest(run_dir)
        assert payload["state"] == "stopped_gracefully"
        merged = [(leg["depth"], leg["blinding"]) for leg in payload["legs"]]
        assert merged == FIVE_KEYS
        by_key = {(leg["depth"], leg["blinding"]): leg for leg in payload["legs"]}
        assert by_key[("none", "blinded")]["ok"] is True
        assert by_key[("none", "unblinded")]["ok"] is True
        # The three never-started legs are visible, not silently dropped.
        for depth, blinding in FIVE_KEYS[2:]:
            assert by_key[(depth, blinding)]["ok"] is False


def test_run_graceful_stop_before_any_leg_starts_exits_clean():
    """The real launcher honours a graceful stop that arrives before the sweep
    legs launch: no model/pool/leg work happens, the manifest gets the
    stopped_gracefully marker, and the exit code is clean (0)."""
    from launch_grid import _run

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _settings(tmp_path)
        stop = StopFlag()
        stop.request()
        code = _run(
            Namespace(resume=False),
            _plan(FIVE_TARGETS),
            [{"category": "c", "product": "p", "regular_price": 10.0}],
            Path("products.json"),
            settings,
            stop=stop,
        )
        run_dir = settings.out / settings.run_name
        assert code == 0
        payload = _read_manifest(run_dir)
        assert payload["state"] == "stopped_gracefully"
        merged = [(leg["depth"], leg["blinding"]) for leg in payload["legs"]]
        assert merged == FIVE_KEYS
        assert all(not leg["ok"] for leg in payload["legs"])


def test_resume_after_graceful_stop_plans_only_the_legs_never_started():
    """--resume after a graceful stop plans exactly the legs that never ran,
    never the completed ones (a stopped_gracefully marker must not confuse
    the resume planner)."""
    from launch_grid import _pending_legs

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        for depth, blinding in FIVE_KEYS[:3]:
            _write_leg(run_dir, depth, blinding, records=3)
        pending = _pending_legs(
            Namespace(resume=True), run_dir, SAFE_MODEL, FIVE_TARGETS
        )
        pending_keys = {(leg["depth"], leg["blinding"]) for leg in pending}
        assert pending_keys == set(FIVE_KEYS[3:])


def test_resume_of_stopped_gracefully_run_with_no_pending_is_safe():
    """Resuming a gracefully-stopped run where every leg already finished is
    a safe no-op: the manifest stays coherent and reaches state complete."""
    from launch_grid import _run

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = _settings(tmp_path)
        run_dir = settings.out / settings.run_name
        run_dir.mkdir(parents=True)
        for depth, blinding in FIVE_KEYS:
            _write_leg(run_dir, depth, blinding, records=3)
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "state": "stopped_gracefully",
                    "started": "2026-01-01T00:00:00+00:00",
                    "legs": [_leg_result(d, b) for d, b in FIVE_KEYS],
                    "ok": False,
                }
            ),
            encoding="utf-8",
        )
        code = _run(
            Namespace(resume=True),
            _plan(FIVE_TARGETS),
            [],
            Path("products.json"),
            settings,
            stop=StopFlag(),
        )
        assert code == 0
        payload = _read_manifest(run_dir)
        merged = [(leg["depth"], leg["blinding"]) for leg in payload["legs"]]
        assert merged == FIVE_KEYS
        assert payload["state"] == "complete"
