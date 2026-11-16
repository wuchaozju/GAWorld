#!/usr/bin/env python3
"""The R1-5MODEL queue runner: loads, legs, unloads five models in one run.

The queue splits the R1 study's calls across five models back to back in
one invocation: model i answers as pool personas [20i, 20i+20) of every
product's 100-persona pool (demographics legs) and makes 10 plain draws
per (product x price level) (none legs) - 26,400 calls per model, 132,000
across the queue (the single-model R1 total). Every purchase call of every
model carries the same one-token llama-server GBNF grammar. The run's
layout and stratification are specified in launch_queue.py; the live state
files (per-model progress.json, the normalized results.csv) live in
launch_queue_outputs.py; one leg's cell-granular execution lives in
launch_queue_leg.py. This module only ORCHESTRATES: it drives the queue
through its phases (started marker, pools reuse or one deterministic
generation, per-model load -> four concurrent legs with cell-granular
durability and the 1525/1533 graceful/hard stop -> unload -> next model)
and writes the run-level manifest whose 20 legs merge exactly once, with
the persona partition and grammar recorded. --resume skips completed
(model, leg) pairs and, inside a pending leg, its durable cells.

The queue itself comes from the plan (plan_model_queue / the plans'
models list): the five-model R1 queue today, and the three-model
QWENEXT queue of launch_yesno_qwenext rides the exact same phases -
per-model load, legs, unload - with the plans' own persona slices.

What each function does (plain language):
    _make_log()               - A timestamped console logger.
    _pool_marker_matches(...) - Is the run dir's pools.json a matching
                                completed pool marker?
    _reuse_source_pools(...)  - Copy a --pools-from directory's pool files
                                into the run dir.
    ensure_queue_pools(...)   - Reuse / copy / generate the shared pool.
    write_queue_manifest(...) - The run-level manifest (20 legs merged
                                exactly once; persona partition + grammar).
    _run_model_phase(...)     - One model's four concurrent legs (load done
                                by the caller).
    _finalize_queue_stopped(...) - The stopped-run manifest + operator
                                summary.
    _report_queue_run(...)    - Completion or failure report.
    run_queue(...)            - The whole queue run (load, legs, unload per
                                model; stop/resume aware).
    _load_pools_summary(...)  - The pools.json payload for the manifest.
Importing this module never opens a socket; the network paths only run
inside run_queue / _run_model_phase / ensure_queue_pools.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for _dir in (_SCRIPT_DIR, _REPO_ROOT / "src"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from launch_cells import write_atomic_json  # noqa: E402
from launch_manifest import (  # noqa: E402
    _load_run_manifest,
    _run_dir_has_state,
)
from launch_queue import (  # noqa: E402
    DEFAULT_POOLS_FROM as DEFAULT_POOLS_FROM,
    QUEUE_GRAMMAR,
    QUEUE_PROFILE as QUEUE_PROFILE,
    _durable_calls,
    _regular_prices,
    _resolve_pools_from,
    build_queue_plan as build_queue_plan,
    pending_queue_targets,
    plan_model_queue,
    print_queue_dry_run as print_queue_dry_run,
    queue_leg_done,
)
from launch_queue_leg import _queue_leg_summary_from_disk, run_queue_leg  # noqa: E402
from launch_queue_outputs import (  # noqa: E402
    QueueProgress,
    QueueResultsCsv,
    rebuild_results_csv,
)
from launch_stop import StopFlag, _drive_legs  # noqa: E402
from launch_support import (  # noqa: E402
    Settings,
    _load_model,
    _load_pool_personas,
    _now,
    _pool_phase,
    _repo_sha,
    _safe_model_name,
    _unload_model,
)
from launch_sweep import (  # noqa: E402
    _make_chat,
    _make_logprob_scorer,
    _progress_line,
    _watchdog,
)


def _make_log() -> Callable[[str], None]:
    """A timestamped console logger that flushes every line."""

    def _write(text: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    return _write


def _pool_marker_matches(run_dir: Path, k: int, pool_seed: int) -> bool:
    """True when the run dir's pools.json marks a matching completed pool."""
    marker = run_dir / "pools.json"
    if not marker.exists():
        return False
    try:
        existing = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        existing.get("k") == k
        and existing.get("pool_seed") == pool_seed
        and existing.get("products") is not None
    )


def _reuse_source_pools(
    run_dir: Path,
    source: Path,
    k: int,
    pool_seed: int,
    products: list[dict[str, Any]],
    log: Callable[[str], None],
) -> None:
    """Copy a --pools-from directory's flat pool files into the run dir."""
    pools_dir = run_dir / "pools"
    pools_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pool_file in sorted(source.glob("*.jsonl")):
        shutil.copy2(pool_file, pools_dir / pool_file.name)
        copied += 1
    if copied == 0:
        raise RuntimeError(
            f"--pools-from {source} holds no *.jsonl pool files; cannot reuse"
        )
    write_atomic_json(
        run_dir / "pools.json",
        {
            "k": k,
            "pool_seed": pool_seed,
            "model": None,
            "products": len(products),
            "source": str(source),
            "files": copied,
            "generated_at": _now(),
        },
    )
    log(f"pools: reused {copied} pool files from {source}")


def ensure_queue_pools(
    settings: Settings,
    products: list[dict[str, Any]],
    products_path: Path,
    run_dir: Path,
    plan: dict[str, Any],
    pools_from: str,
    log: Callable[[str], None],
    loaded: str | None,
) -> str | None:
    """Make sure the run dir has its shared 100-persona pool; load model 0.

    Order of preference: an existing matching pools.json (a resumed run)
    wins and nothing happens; else the --pools-from directory (default: the
    archived R1 run's pools) is copied in; else the pool is generated once
    (pool-seed 42, as the single-model launcher does) by the first queue
    model, which this function loads through the manager when needed.
    Returns the manager model id now loaded (None when no model is loaded),
    so the caller does not load the same model twice.
    """
    k = int(plan["k"])
    pool_seed = int(plan["pool_seed"])
    marker = run_dir / "pools.json"
    if _pool_marker_matches(run_dir, k, pool_seed):
        log("pools: already complete (pools.json matches) - skipping")
        return loaded
    source = _resolve_pools_from(pools_from)
    if source is not None:
        _reuse_source_pools(run_dir, source, k, pool_seed, products, log)
        return loaded
    if marker.exists():
        marker.unlink()  # stale marker from an interrupted copy: regenerate
    drawing_model = plan_model_queue(plan)[0]
    if loaded != drawing_model:
        log(
            f"loading {drawing_model} on :{settings.port} to draw the "
            f"shared persona pool (pool-seed {pool_seed})..."
        )
        _load_model(settings.manager_url, drawing_model, settings.port)
        loaded = drawing_model
    log(
        f"persona pools: generating one shared 100-persona pool "
        f"(pool-seed {pool_seed}) with {drawing_model}..."
    )
    _pool_phase(
        replace(settings, model=drawing_model), products, products_path, run_dir, k, log
    )
    return loaded


def write_queue_manifest(
    *,
    settings: Settings,
    plan: dict[str, Any],
    products_path: Path,
    run_dir: Path,
    started: str,
    finished: str,
    leg_results: list[dict[str, Any]],
    pools: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    resume_invocation: bool,
    state: str,
) -> Path:
    """Write the queue's run-level manifest.json.

    state "running" writes the started marker of the first invocation (no
    legs yet); a terminal state ("complete", "stopped_gracefully",
    "stopped") merges every planned (model x depth x blinding) leg exactly
    once in queue order - this invocation's result, else the earlier
    manifest's ok entry, else the leg's own durable files, else a visible
    "never completed" entry. The payload records the five-model queue with
    its deterministic persona partition and the grammar used on every call.
    """
    earlier = {
        (leg.get("model"), leg.get("depth"), leg.get("blinding")): leg
        for leg in (prior or {}).get("legs") or []
        if leg.get("ok")
    }
    this = {
        (result.get("model"), result.get("depth"), result.get("blinding")): result
        for result in leg_results
    }
    terminal = state in ("complete", "stopped_gracefully", "stopped")
    merged_legs: list[dict[str, Any]] = []
    if terminal:
        for target in plan["legs"]:
            key = (target["model"], target["depth"], target["blinding"])
            if key in this:
                merged_legs.append(this[key])
            elif key in earlier:
                merged_legs.append(earlier[key])
            else:
                from_disk = _queue_leg_summary_from_disk(run_dir, target)
                merged_legs.append(
                    from_disk
                    if from_disk is not None
                    else {**target, "ok": False, "error": "leg never completed"}
                )
    pools_payload = pools if pools is not None else (prior or {}).get("pools")
    resumed = list((prior or {}).get("resumed") or [])
    if terminal and resume_invocation:
        resumed.append(
            {
                "at": finished,
                "legs": [
                    f"{r.get('model')} {r['depth']}_{r['blinding']}"
                    for r in leg_results
                ],
                "argv": list(sys.argv),
            }
        )
    ok = all(leg.get("ok", False) for leg in merged_legs) if terminal else None
    payload = {
        "run_name": run_dir.name,
        "profile": plan.get("profile", QUEUE_PROFILE),
        "models": plan["models"],
        "grammar": settings.grammar,
        "logprob_mode": settings.logprob_mode,
        # The answer words this run asked with (e.g. "yes/no" for
        # R1-YESNO; None = the historical "purchase"/"not purchase"), so
        # a later audit can never mistake the run for an R1 rerun.
        "response_format": settings.response_format,
        # The first_token decision-scan window this run used (the
        # request's max_tokens), so the request shape stays auditable.
        "scan_tokens": settings.scan_tokens,
        # Whether this run plans the A/B label-order switch: recorded so a
        # later --resume can refuse flags that disagree with the run.
        "ab_orders": bool(plan.get("ab_orders")),
        "port": settings.port,
        "base_url": settings.base_url,
        "manager_url": settings.manager_url,
        "commit_sha": _repo_sha(),
        "products_file": str(products_path),
        "levels": plan["levels"],
        "draws": settings.draws,
        "seed": settings.seed,
        "k": plan["k"],
        "per_model_personas": plan["per_model_personas"],
        "pool_seed": settings.pool_seed,
        "planned_sweep_calls": plan["sweep_calls"],
        "state": state,
        "started": (prior or {}).get("started") or started,
        "finished": finished,
        "ok": ok,
        "legs": merged_legs,
        "pools": pools_payload,
        "resumed": resumed or None,
        "argv": list(sys.argv),
    }
    target = run_dir / "manifest.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _start_thread(
    target: Callable[..., Any], args: tuple, kwargs: dict[str, Any] | None = None
) -> threading.Thread:
    """Start one daemon thread running target(*args, **kwargs) and return it."""
    thread = threading.Thread(
        target=target, args=args, kwargs=kwargs or {}, daemon=True
    )
    thread.start()
    return thread


def _run_model_phase(
    settings: Settings,
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    personas_by_product: dict[str, dict[str, Any]] | None,
    run_dir: Path,
    model_targets: list[dict[str, Any]],
    results: list[dict[str, Any]],
    log: Callable[[str], None],
    stop: StopFlag,
    progress: QueueProgress,
    results_csv: QueueResultsCsv,
) -> None:
    """Run one model's pending legs concurrently (load done by the caller).

    The model's four legs share one counting chat wrapper (built with the
    queue's grammar) and one health watchdog, and are driven under the
    shared stop flag exactly like the single-model wrapper: a graceful stop
    lets every in-flight leg pause at its next cell boundary (its completed
    cells are already durable), a hard stop aborts them at the next call.
    """
    model_settings = replace(settings, model=model_targets[0]["model"])
    remaining_calls = 0
    for target in model_targets:
        planned = int(target.get("calls") or 0)
        remaining_calls += max(0, planned - _durable_calls(run_dir, target))
    scorer_fn = None
    chat_fn = None
    if model_settings.logprob_mode:
        # R1LP: one scoring pass per prompt, no grammar and no sampling;
        # the wrapper still enforces the stop/abort and progress contract.
        scorer_fn, state, abort = _make_logprob_scorer(
            model_settings,
            remaining_calls,
            lambda d, t, p, r: log(_progress_line(d, t, p, r)),
            stop=stop,
            ab_orders=bool(plan.get("ab_orders")),
        )
    else:
        chat_fn, state, abort = _make_chat(
            model_settings,
            remaining_calls,
            lambda d, t, p, r: log(_progress_line(d, t, p, r)),
            stop=stop,
            grammar=model_settings.grammar,
        )
    done_event = threading.Event()
    _start_thread(_watchdog, (model_settings, abort, done_event, log))
    model_queue = plan_model_queue(plan)
    log(
        f"queue [{model_queue.index(model_settings.model) + 1}/"
        f"{len(model_queue)}] {model_settings.model}: launching "
        f"{len(model_targets)} legs concurrently "
        f"({remaining_calls:,} calls remaining)"
    )

    def start_one(target: dict[str, Any]) -> threading.Thread:
        return _start_thread(
            run_queue_leg,
            (
                model_settings,
                plan,
                products,
                personas_by_product,
                run_dir,
                chat_fn,
                target,
                results,
                log,
                progress,
                results_csv,
            ),
            {"scorer_fn": scorer_fn},
        )

    level = _drive_legs(
        model_targets,
        stop,
        abort,
        log,
        start_one,
        planned_calls=remaining_calls,
        calls_done=lambda: state["done"],
    )
    done_event.set()
    log(
        f"queue [{model_queue.index(model_settings.model) + 1}/"
        f"{len(model_queue)}] {model_settings.model}: phase finished "
        f"({state['done']:,} calls this phase, parse "
        f"{100.0 * state['parsed'] / max(1, state['done']):.1f}%), "
        f"level {level}"
    )


def _finalize_queue_stopped(
    stop: StopFlag,
    settings: Settings,
    plan: dict[str, Any],
    products_path: Path,
    run_dir: Path,
    started: str,
    leg_results: list[dict[str, Any]],
    pools: dict[str, Any] | None,
    prior: dict[str, Any] | None,
    log: Callable[[str], None],
) -> int:
    """Write the final manifest of a stopped queue run and print the hint.

    A graceful stop records state "stopped_gracefully" (per-leg status
    merged like a completed run); a hard stop records state "stopped".
    Either way a leg interrupted mid-run keeps every completed cell on
    disk, so rerunning with --resume executes only the missing cells.
    Returns the exit code: 0 for a graceful stop, 1 for a hard stop.
    """
    level = stop.level()
    state = "stopped_gracefully" if level == "graceful" else "stopped"
    write_queue_manifest(
        settings=settings,
        plan=plan,
        products_path=products_path,
        run_dir=run_dir,
        started=started,
        finished=_now(),
        leg_results=leg_results,
        pools=pools,
        prior=prior,
        resume_invocation=prior is not None,
        state=state,
    )
    if level == "graceful":
        log(
            f"run {settings.run_name} stopped gracefully "
            f"({len(leg_results)} leg result(s) recorded); rerun with "
            f"--resume --run-name {settings.run_name} to finish any "
            "legs that did not complete"
        )
        return 0
    log(
        f"run {settings.run_name} hard-stopped; in-flight legs aborted at a "
        "cell boundary (completed cells are kept); rerun with --resume "
        f"--run-name {settings.run_name} to finish the remaining cells"
    )
    return 1


def _report_queue_run(
    results: list[dict[str, Any]],
    settings: Settings,
    run_dir: Path,
    started_wall: float,
) -> int:
    """Print failures or the completion line and return the exit code."""
    log = _make_log()
    failed = [r for r in results if not r.get("ok")]
    if failed:
        for result in failed:
            print(
                f"leg {result.get('model')} "
                f"{result['depth']}_{result['blinding']} failed: "
                f"{result.get('error')}",
                file=sys.stderr,
            )
        print(
            f"run {settings.run_name} finished with {len(failed)} failed "
            f"leg(s); rerun with --resume --run-name {settings.run_name} "
            "to retry them",
            file=sys.stderr,
        )
        return 1
    log(
        f"run {settings.run_name} complete in {(time.monotonic() - started_wall) / 3600.0:.2f} h"
    )
    log(f"results: {run_dir}/manifest.json (results.csv, progress.json)")
    return 0


def run_queue(
    args: Any,
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    products_path: Path,
    settings: Settings,
    stop: StopFlag | None = None,
) -> int:
    """Run the real 5-model queue: per model load, legs, unload.

    The queue reuses the single-model wrapper's guarantees: the run-level
    manifest doubles as the started marker (an interrupted run is
    recognised and needs --resume), pools are generated once or reused,
    each model's pending legs run concurrently with cell-granular
    durability and 1525's graceful/hard stop, completed (model, leg) pairs
    and durable cells are skipped on --resume, and the final manifest
    merges every planned leg exactly once. Every purchase call of every
    model carries the queue's one-token grammar.
    """
    if stop is None:
        stop = StopFlag(force_first=getattr(args, "force", False))
    # The queue fixes the stratified allocation: R1LP makes one scoring pass
    # per prompt, R1-5MODEL makes 10 plain draws; grammar is only sent by the
    # sampling queue (R1LP is grammar-free by design).
    grammar = None if settings.logprob_mode else QUEUE_GRAMMAR
    settings = replace(settings, draws=int(plan["draws"]), grammar=grammar)
    run_dir = settings.out / settings.run_name
    prior = _load_run_manifest(run_dir) if run_dir.exists() else None
    if (
        prior is not None or (run_dir.exists() and _run_dir_has_state(run_dir))
    ) and not args.resume:
        print(
            f"error: run dir {run_dir} already holds a run "
            "(manifest.json, pools.json, or leg files); pass --resume to "
            "continue it, choose a new --run-name, or delete the directory "
            "to start over",
            file=sys.stderr,
        )
        return 2
    if (
        args.resume
        and prior is not None
        and bool(prior.get("ab_orders")) != bool(plan.get("ab_orders"))
    ):
        # A resume whose A/B switch disagrees with the run's recorded
        # manifest would silently mix single-order and A/B-merged cells;
        # refuse before any model load or scoring call.
        print(
            f"error: run dir {run_dir} manifest records ab_orders="
            f"{bool(prior.get('ab_orders'))} but this resume plans "
            f"ab_orders={bool(plan.get('ab_orders'))} - refusing to mix "
            "single-order and A/B-merged cells in one run; re-run with the "
            "flags matching the original launch (--ab-labels)",
            file=sys.stderr,
        )
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    started_wall = time.monotonic()
    started = _now()
    log = _make_log()
    log(f"run {settings.run_name} starting (commit {_repo_sha() or 'unknown'})")
    targets = plan["legs"]
    pending = pending_queue_targets(run_dir, targets, args.resume)
    if prior is not None:
        log(f"resume: continuing a run started {prior.get('started') or '?'}")
    if len(pending) < len(targets):
        log(
            f"resume: {len(targets) - len(pending)}/{len(targets)} legs "
            "already complete - skipping"
        )
    if not pending:
        log(f"nothing to run (all {len(targets)} legs complete)")
        write_queue_manifest(
            settings=settings,
            plan=plan,
            products_path=products_path,
            run_dir=run_dir,
            started=started,
            finished=_now(),
            leg_results=[],
            pools=None,
            prior=prior,
            resume_invocation=prior is not None,
            state="complete",
        )
        return 0
    if stop.level() != "running":
        log(
            f"{stop.level()} stop requested before the queue started - "
            "writing the stopped manifest and exiting cleanly"
        )
        return _finalize_queue_stopped(
            stop, settings, plan, products_path, run_dir, started, [], None, prior, log
        )
    if prior is None:
        write_queue_manifest(
            settings=settings,
            plan=plan,
            products_path=products_path,
            run_dir=run_dir,
            started=started,
            finished=started,
            leg_results=[],
            pools=None,
            prior=None,
            resume_invocation=False,
            state="running",
        )
        log(f"run marked started: {run_dir / 'manifest.json'}")
    # Pools: only needed when a pending leg runs personas.
    personas_by_product: dict[str, dict[str, Any]] | None = None
    loaded: str | None = None
    needs_personas = any(t["depth"] != "none" for t in pending)
    if needs_personas:
        loaded = ensure_queue_pools(
            settings,
            products,
            products_path,
            run_dir,
            plan,
            getattr(args, "pools_from", ""),
            log,
            loaded,
        )
        if stop.level() != "running":  # stop requested during the pool phase
            return _finalize_queue_stopped(
                stop,
                settings,
                plan,
                products_path,
                run_dir,
                started,
                [],
                _load_pools_summary(run_dir),
                prior,
                log,
            )
        personas_by_product = _load_pool_personas(run_dir, products, int(plan["k"]))
        if not personas_by_product:
            print(
                f"error: no pool files matched any product under {run_dir / 'pools'!r}",
                file=sys.stderr,
            )
            return 2
        # The last queue model answers pool personas [80, 100), so every
        # product's shared pool must hold the full 100 personas - fail before
        # any GPU leg instead of mid-run. A missing product pool file is the
        # same error.
        need = int(plan["k"])
        short = [
            name
            for name, info in personas_by_product.items()
            if len(info.get("personas") or []) < need
        ]
        absent = [
            item["product"]
            for item in products
            if item["product"] not in personas_by_product
        ]
        if short or absent:
            print(
                "error: the shared pool cannot feed the 5-model queue: "
                + (f"short pools {[name[:50] for name in short]}; " if short else "")
                + (
                    f"missing products {[name[:50] for name in absent]}"
                    if absent
                    else ""
                )
                + f" (every product needs {need} personas)",
                file=sys.stderr,
            )
            return 2
        log(f"pools: {len(personas_by_product)} products loaded from the shared pool")
    # Progress + the normalized results.csv (rebuilt from the leg files so
    # a resumed run's rows stay exactly-once per durable cell).
    progress = QueueProgress(run_dir, targets, log)
    for target in targets:
        if queue_leg_done(run_dir, target):
            progress.set_leg(target, done_at_start=int(target["calls"]))
        else:
            progress.set_leg(target, done_at_start=_durable_calls(run_dir, target))
    regular_prices = _regular_prices(products)
    plain_seed = rebuild_results_csv(run_dir, targets, regular_prices, log)
    results_csv = QueueResultsCsv(run_dir, regular_prices, plain_seed)
    results: list[dict[str, Any]] = []
    try:
        # Process the models in the plan's queue order; only models with a
        # pending leg get loaded at all (a resumed run skips its completed
        # models).
        model_queue = plan_model_queue(plan)
        for model_index, model in enumerate(model_queue):
            safe = _safe_model_name(model)
            model_targets = [t for t in pending if t["safe_model"] == safe]
            if not model_targets:
                continue
            if stop.level() != "running":
                log(
                    f"queue: {stop.level()} stop requested before "
                    f"{model}'s phase - finishing the run"
                )
                break
            if loaded != model:
                log(
                    f"queue [{model_index + 1}/{len(model_queue)}] loading "
                    f"{model} on :{settings.port} through the manager..."
                )
                _load_model(settings.manager_url, model, settings.port)
                loaded = model
            if stop.level() != "running":  # stop requested during the load
                log(
                    f"queue: {stop.level()} stop requested during the "
                    f"{model} load - finishing the run"
                )
                break
            _run_model_phase(
                settings,
                plan,
                products,
                personas_by_product,
                run_dir,
                model_targets,
                results,
                log,
                stop,
                progress,
                results_csv,
            )
            if loaded is not None:
                try:
                    _unload_model(settings.manager_url, settings.port)
                    log(f"queue: unloaded {loaded} from :{settings.port}")
                except RuntimeError as exc:
                    log(f"warning: could not unload {loaded}: {exc}")
                loaded = None
    finally:
        results_csv.close()
        progress.finish()
    level = stop.level()
    if level != "running":
        return _finalize_queue_stopped(
            stop,
            settings,
            plan,
            products_path,
            run_dir,
            started,
            results,
            _load_pools_summary(run_dir),
            prior,
            log,
        )
    write_queue_manifest(
        settings=settings,
        plan=plan,
        products_path=products_path,
        run_dir=run_dir,
        started=started,
        finished=_now(),
        leg_results=results,
        pools=_load_pools_summary(run_dir),
        prior=prior,
        resume_invocation=prior is not None,
        state="complete",
    )
    return _report_queue_run(results, settings, run_dir, started_wall)


def _load_pools_summary(run_dir: Path) -> dict[str, Any] | None:
    """The run dir's pools.json payload, if any (for the run manifest)."""
    marker = run_dir / "pools.json"
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
