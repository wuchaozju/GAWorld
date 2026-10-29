#!/usr/bin/env python3
"""Sweep-leg machinery for the study's launch wrapper: legs, watchdog, smoke.

The launch layer around the Gui & Toubia replication sweep is split into
scripts that never change what the study's existing tools do: launch_grid.py
(flags, plan, run order), launch_support.py (model-manager calls and
persona-pool generation/subsampling), launch_manifest.py (the run-level
manifest and its resume merge), launch_cells.py (per-cell durability:
append+flush record writing, the resume planner, the progress.json
writer) and launch_sweep.py (this module: the concurrent (depth x
blinding) sweep legs through the sweep tool's own helpers, the health
watchdog, and the smoke pre-flight).

Cell-level durability (TASK-1533): a leg no longer buffers its records in
memory until the leg finishes. Each completed chat call's record is
appended to the leg's jsonl and flushed the moment it is produced, so a
kill at any instant loses at most the ONE in-flight call. A leg's records
file IS its resume state: on resume the leg counts the cells already
durably on disk (launch_cells.durable_cells) and runs the sweep with
skip_first set to that count, executing only the missing cells; the CSV
and leg manifest are written only when the whole leg has completed.
Importing this module never opens a socket.

Function map: _leg_dir/_leg_is_done (output dir + resume check), _make_chat
(counting chat wrapper with progress, graceful stop and abort; the abort
carries a reason so a stopped leg records whether a hard operator stop or
a dead chat server ended it - launch_stop.AbortSignal), _run_one_leg
(one leg: per-cell durable record writes, then finalize csv+manifest),
_finalize_leg (csv + manifest + result summary, never rewrites the
jsonl), _watchdog (abort the run when the chat server dies), _progress_line
(live progress text), and the smoke pre-flight _smoke with its helpers
_smoke_direct_chat, _draw_smoke_persona, _run_smoke_purchase,
_write_smoke_manifest, _report_smoke.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = _REPO_ROOT / "scripts"
_SRC = _REPO_ROOT / "src"
for _dir in (_SCRIPT_DIR, _SRC):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from fos.experiments.sweep_kit import (  # noqa: E402
    parse_purchase,
    run_persona_sweep,
    run_sweep,
    split_response_format,
    write_manifest,
)
from launch_cells import (  # noqa: E402
    FSYNC_EVERY,
    durable_cells,
    scan_leg_jsonl,
    write_leg_csv,
)
from launch_support import (  # noqa: E402
    Settings,
    _SWEEP,
    _load_model,
    _manager_status,
    _now,
    _post_json,
    _repo_sha,
)
from launch_queue import model_control_sequences, model_top_k  # noqa: E402
from launch_stop import AbortSignal, StopFlag, WATCHDOG_REASON  # noqa: E402
from logprob_scoring import PostFn, make_scorer  # noqa: E402

HEALTH_POLL_SECONDS = 20.0
HEALTH_MISSES_ABORT = 4

# The reason a leg records when a GRACEFUL stop lands mid-leg: every cell
# completed before the signal is already on disk (cell-granular durability),
# so the leg can stop at its next cell boundary and a later --resume runs
# only the missing cells (TASK-1533).
GRACEFUL_CELL_REASON = (
    "graceful stop requested; leg paused at the next cell boundary "
    "(completed cells are durable - rerun with --resume to finish)"
)

GRACEFUL_STOP_LEVEL = "graceful"


def _leg_dir(run_dir: Path, leg: dict[str, str]) -> Path:
    """The output directory of one (depth x blinding) leg."""
    return run_dir / f"{leg['depth']}_{leg['blinding']}"


def _leg_is_done(run_dir: Path, safe_model: str, leg: dict[str, str]) -> bool:
    """Resume check: does this leg already have files and a manifest?"""
    leg_dir = _leg_dir(run_dir, leg)
    jsonl = leg_dir / f"{safe_model}_{leg['blinding']}.jsonl"
    csv = leg_dir / f"{safe_model}_{leg['blinding']}.csv"
    return (
        jsonl.exists()
        and jsonl.stat().st_size > 0
        and csv.exists()
        and (leg_dir / "manifest.json").exists()
    )


def _make_chat(
    settings: Settings,
    total_calls: int,
    progress: Callable[[int, int, int, float], None],
    stop: StopFlag | None = None,
    *,
    grammar: str | None = None,
) -> tuple[Callable[..., str], dict[str, int], AbortSignal]:
    """Counting chat wrapper shared by all legs (progress + stop/abort).

    state counts calls made and calls whose answer parsed; every
    progress_every-th call prints a live line. Once abort is set every new
    call raises so the legs stop immediately (dead chat server via the
    watchdog, or an operator's hard stop - the AbortSignal carries the
    reason the leg records). When a graceful stop level is reached (stop
    flag, TASK-1533 cell durability) every new call also raises with the
    graceful reason: every cell completed before the signal is already on
    disk, so stopping the leg at its next cell boundary loses nothing and a
    later --resume executes only the missing cells. grammar, when given, is
    sent on every request so the model can only answer the constrained
    output (the 5-model queue's one-token purchase grammar); without it the
    request is exactly the historical one.
    """
    state = {"done": 0, "parsed": 0}
    abort = AbortSignal(WATCHDOG_REASON)
    lock = threading.Lock()
    started = time.monotonic()
    inner = _SWEEP.build_sweep_chat_fn(
        settings.base_url, settings.model, 16, 120.0, grammar=grammar
    )

    def chat_fn(messages: list[dict[str, str]], temperature: float) -> str:
        if abort.is_set():
            raise RuntimeError(abort.reason)
        if stop is not None and stop.level() == GRACEFUL_STOP_LEVEL:
            raise RuntimeError(GRACEFUL_CELL_REASON)
        raw = inner(messages, temperature)
        with lock:
            state["done"] += 1
            if raw and parse_purchase(raw) is not None:
                state["parsed"] += 1
            done, parsed = state["done"], state["parsed"]
        if done % settings.progress_every == 0:
            progress(
                done, total_calls, parsed, done / max(1e-9, time.monotonic() - started)
            )
        return raw

    return chat_fn, state, abort


def _make_logprob_scorer(
    settings: Settings,
    total_calls: int,
    progress: Callable[[int, int, int, float], None],
    stop: StopFlag | None = None,
    *,
    ab_orders: bool = False,
    post: PostFn | None = None,
) -> tuple[Callable[..., dict[str, Any]], dict[str, int], AbortSignal]:
    """Counting R1LP scorer wrapper shared by all legs of one model.

    The logprob twin of _make_chat: it builds the scorer for the run's
    --logprob-mode and wraps it with the same cell-boundary stop checks
    (a graceful stop raises at the next prompt, a hard stop or dead-server
    abort does the same) and the same progress/counting state, so the
    queue's watchdog and stop driver treat logprob legs exactly like
    sampling legs. The scorer's result is returned unchanged; the wrapper
    only counts whether the scoring call succeeded.

    ab_orders=True (the R1LP A/B label-order switch) builds the both-
    orders executor: every cell is scored with BOTH label orders and the
    two halves are merged into ONE result (averaged p(buy), both raw
    order values stamped). post=None uses the real HTTP transport; tests
    inject a fake so no test ever opens a socket.
    """
    state = {"done": 0, "parsed": 0}
    abort = AbortSignal(WATCHDOG_REASON)
    lock = threading.Lock()
    started = time.monotonic()
    if post is None:
        inner = make_scorer(
            settings.logprob_mode or "first_token",
            settings.base_url,
            settings.model,
            ab_orders=ab_orders,
            labels=split_response_format(settings.response_format),
            scan_tokens=getattr(settings, "scan_tokens", 8),
            # The per-model top-k coverage and control sequences resolved
            # from the queue profile config (overrides live in
            # launch_queue, never here) - the same values the leg
            # manifest stamps.
            top_k=model_top_k(settings.model),
            control_sequences=model_control_sequences(settings.model),
        )
    else:
        inner = make_scorer(
            settings.logprob_mode or "first_token",
            settings.base_url,
            settings.model,
            post=post,
            ab_orders=ab_orders,
            labels=split_response_format(settings.response_format),
            scan_tokens=getattr(settings, "scan_tokens", 8),
            top_k=model_top_k(settings.model),
            control_sequences=model_control_sequences(settings.model),
        )

    def scorer_fn(messages: list[dict[str, str]]) -> dict[str, Any]:
        if abort.is_set():
            raise RuntimeError(abort.reason)
        if stop is not None and stop.level() == GRACEFUL_STOP_LEVEL:
            raise RuntimeError(GRACEFUL_CELL_REASON)
        result = inner(messages)
        with lock:
            state["done"] += 1
            if result.get("succeeded"):
                state["parsed"] += 1
            done, parsed = state["done"], state["parsed"]
        if done % settings.progress_every == 0:
            progress(
                done, total_calls, parsed, done / max(1e-9, time.monotonic() - started)
            )
        return result

    return scorer_fn, state, abort


def _planned_leg_calls(plan: dict[str, Any], leg: dict[str, str]) -> int:
    """The number of cells one leg is planned to execute (plan legs calls)."""
    for planned in plan.get("legs") or []:
        if (
            planned.get("depth") == leg["depth"]
            and planned.get("blinding") == leg["blinding"]
        ):
            return int(planned.get("calls") or 0)
    return 0


def _run_one_leg(
    settings: Settings,
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    personas_by_product: dict[str, Any] | None,
    run_dir: Path,
    chat_fn: Callable[..., str],
    leg: dict[str, str],
    results: list[dict[str, Any]],
    log: Callable[[str], None],
    progress: Any | None = None,
) -> None:
    """Run one (depth x blinding) leg and record its outcome.

    The leg reuses the sweep tool's own helpers unchanged (same design,
    prompts, record layout). Its output directory is
    <run>/<depth>_<blinding>/ so legs never collide while they run
    concurrently. Cell-granular durability (TASK-1533): each completed
    cell's record is appended to the leg's jsonl and flushed the moment it
    is produced (fsync every FSYNC_EVERY records and at leg end), and a
    resumed leg skips the cells already durable on disk (skip_first) so
    only missing cells execute. The CSV and leg manifest are written when
    the whole leg completes - a leg interrupted mid-run keeps its finished
    cells on disk and is continued by --resume.
    """
    leg_dir = _leg_dir(run_dir, leg)
    leg_dir.mkdir(parents=True, exist_ok=True)
    safe_model = _SWEEP._safe_model_name(settings.model)
    blinding = leg["blinding"]
    base = leg_dir / f"{safe_model}_{blinding}"
    jsonl_path = Path(f"{base}.jsonl")
    leg_key = f"{leg['depth']}_{blinding}"
    planned = _planned_leg_calls(plan, leg)
    # Resume planner: how many cells are durably on disk already (repairs a
    # torn tail in place). The records file IS the resume state.
    durable, durable_parsed = durable_cells(jsonl_path)
    if durable > planned:
        results.append(
            {
                **leg,
                "ok": False,
                "error": (
                    f"records file holds {durable} cells but this plan has "
                    f"{planned}; the run configuration changed - use a new "
                    "run-name or remove the leg directory"
                ),
            }
        )
        log(
            f"leg {leg_key} FAILED: records file exceeds the plan ({durable} > {planned})"
        )
        return
    if progress is not None:
        progress.set_leg(leg_key, done_at_start=durable)
    remaining = planned - durable
    if remaining <= 0 and durable:
        # Every cell is already durable (a crash after the last record but
        # before the leg's csv/manifest): finalize without any chat calls.
        log(f"leg {leg_key}: all {durable} cells already durable - finalizing")
        _finalize_leg(
            settings, plan, leg_dir, leg, base, products, run_dir.name, results, log
        )
        return
    design = _SWEEP._build_design(
        plan["levels"],
        [blinding],
        settings.seed,
        list(_SWEEP.COVARIATE_KINDS),
        leg["depth"],
    )
    handle = jsonl_path.open("a", encoding="utf-8")
    written = {"records": 0, "parsed": 0, "fsync": 0}

    def record_sink(record: dict[str, Any]) -> None:
        handle.write(json.dumps(record) + "\n")
        written["records"] += 1
        if record.get("succeeded"):
            written["parsed"] += 1
        handle.flush()
        written["fsync"] += 1
        if written["fsync"] % FSYNC_EVERY == 0:
            os.fsync(handle.fileno())
        if progress is not None:
            progress.note(leg_key, succeeded=bool(record.get("succeeded")), force=False)

    try:
        if leg["depth"] == "none":
            run_sweep(
                design,
                products,
                settings.model,
                chat_fn,
                draws=settings.draws,
                blinding=blinding,
                seed=settings.seed,
                persona_depth="none",
                skip_first=durable,
                on_record=record_sink,
            )
        else:
            if personas_by_product is None:
                raise RuntimeError("persona leg without persona pools")
            _records, _skipped = run_persona_sweep(
                design,
                personas_by_product,
                settings.model,
                chat_fn,
                blinding=blinding,
                persona_depth=leg["depth"],
                seed=settings.seed,
                skip_first=durable,
                on_record=record_sink,
            )
    except Exception as exc:  # never swallow a leg failure
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        cells_on_disk = written["records"] + durable
        results.append(
            {
                **leg,
                "ok": False,
                "error": f"{exc}",
                "cells_durable": cells_on_disk,
            }
        )
        log(f"leg {leg_key} FAILED: {exc} ({cells_on_disk} cells durable on disk)")
        return
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()
    if written["records"] + durable == 0:
        results.append({**leg, "ok": False, "error": "no records produced"})
        log(f"leg {leg_key} produced no records")
        return
    _finalize_leg(
        settings, plan, leg_dir, leg, base, products, run_dir.name, results, log
    )


def _finalize_leg(
    settings: Settings,
    plan: dict[str, Any],
    leg_dir: Path,
    leg: dict[str, str],
    base: Path,
    products: list[dict[str, Any]],
    run_name: str,
    results: list[dict[str, Any]],
    log: Callable[[str], None],
) -> None:
    """Write one COMPLETED leg's csv, manifest and result summary.

    The jsonl was already written record-by-record (append-only, cell
    durability); this only adds the derived csv and the leg manifest, then
    appends the leg's result entry computed from the full jsonl on disk.
    """
    records, torn = scan_leg_jsonl(Path(f"{base}.jsonl"))
    if not records or torn:
        results.append(
            {**leg, "ok": False, "error": f"leg records file torn/incomplete ({torn})"}
        )
        log(f"leg {leg['depth']}_{leg['blinding']} could not finalize (torn file)")
        return
    parsed = sum(1 for record in records if record.get("succeeded"))
    mean_elapsed = sum(
        float(record.get("elapsed_seconds") or 0.0) for record in records
    ) / len(records)
    blinding = leg["blinding"]
    write_leg_csv(base, records)
    design = _SWEEP._build_design(
        plan["levels"],
        [blinding],
        settings.seed,
        list(_SWEEP.COVARIATE_KINDS),
        leg["depth"],
    )
    write_manifest(
        leg_dir / "manifest.json",
        design,
        settings.model,
        settings.draws,
        blinding,
        products,
        settings.base_url,
        extra={
            "levels": plan["levels"],
            "temperature": 1.0,
            "seed": settings.seed,
            "argv": list(sys.argv),
            "started": _now(),
            "finished": _now(),
            "depth": leg["depth"],
            "run_name": run_name,
            "personas_per_product": plan["k"] if leg["depth"] != "none" else None,
            "pool_seed": settings.pool_seed,
            "commit_sha": _repo_sha(),
        },
    )
    results.append(
        {
            **leg,
            "ok": True,
            "records": len(records),
            "parsed": parsed,
            "parse_rate": parsed / len(records),
            "mean_elapsed": mean_elapsed,
            "files": [f"{base}.jsonl", f"{base}.csv", str(leg_dir / "manifest.json")],
        }
    )
    log(
        f"leg {leg['depth']}_{leg['blinding']} done: {len(records):,} "
        f"records, parse {100.0 * parsed / len(records):.1f}%"
    )


def _watchdog(
    settings: Settings,
    abort: AbortSignal,
    done_event: threading.Event,
    log: Callable[[str], None],
) -> None:
    """Abort the run when the chat server stops answering.

    A manager switch by another session (the known pilot risk) kills the
    llama-server mid-run; without this guard every remaining call would
    retry once and record a silent failure. After HEALTH_MISSES_ABORT
    consecutive failed polls the event trips and the counting chat wrapper
    raises so every leg stops.
    """
    misses = 0
    while not done_event.is_set():
        time.sleep(HEALTH_POLL_SECONDS)
        try:
            with urllib.request.urlopen(
                f"{settings.base_url}/health", timeout=5.0
            ) as reply:
                healthy = reply.status == 200
        except OSError:
            healthy = False
        if healthy:
            misses = 0
            continue
        misses += 1
        log(
            f"warning: {settings.base_url}/health unreachable "
            f"({misses}/{HEALTH_MISSES_ABORT})"
        )
        if misses >= HEALTH_MISSES_ABORT:
            log("aborting: chat server appears to have died (external model switch?)")
            abort.set()
            return


def _progress_line(done: int, total: int, parsed: int, rate: float) -> str:
    """One live progress line: done/total, parse rate so far, ETA."""
    remaining = max(1, total - done)
    return (
        f"progress {done:,}/{total:,} calls "
        f"({100.0 * done / total:.1f}%), parse "
        f"{100.0 * parsed / max(done, 1):.1f}% so far, "
        f"ETA ~{remaining / max(rate, 1e-9) / 3600.0:.1f} h"
    )


def _smoke(settings: Settings, products_path: Path, out: Path) -> int:
    """Pre-flight: model load + persona draw + purchase call + file checks.

    Model-call budget (<= 4): one manager model load, up to two persona
    draws (a second only when the first does not parse), one persona
    purchase call; the write-through checks make no model call. The model
    loaded before the smoke is restored afterwards.
    """
    run_dir = out / (
        settings.run_name or f"smoke-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    wall_started = time.monotonic()
    started = _now()

    def log(text: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    try:
        prior = _manager_status(settings.manager_url).get(str(settings.port), {})
    except OSError as exc:
        log(f"error: cannot reach model manager {settings.manager_url}: {exc}")
        return 2
    prior_model = prior.get("model")
    calls: list[dict[str, Any]] = []
    pool_file = run_dir / "smoke_persona.jsonl"
    try:
        log(
            f"smoke: loading {settings.model} on :{settings.port} "
            f"(previous: {prior_model or 'none'})"
        )
        _load_model(settings.manager_url, settings.model, settings.port)
        calls.append({"call": "model_load", "ok": True})
        products = json.loads(products_path.read_text(encoding="utf-8"))
        if isinstance(products, dict):
            products = products.get("products") or []
        item = products[0]
        persona = _draw_smoke_persona(settings, item, pool_file, calls, log)
        design = _SWEEP._build_design(
            [100.0], ["blinded"], settings.seed, [], "demographics"
        )
        records = _run_smoke_purchase(settings, item, persona, design, calls)
        if records:
            _SWEEP._write_records(run_dir / f"smoke_{settings.port}", records)
        _write_smoke_manifest(
            settings, run_dir, design, products, started, calls, persona, pool_file
        )
    finally:
        if prior_model and prior_model != settings.model:
            try:
                log(f"restoring {prior_model} on :{settings.port} (as-found state)...")
                _load_model(settings.manager_url, prior_model, settings.port)
            except RuntimeError as exc:
                log(f"warning: could not restore {prior_model}: {exc}")
    return _report_smoke(settings, run_dir, calls, pool_file, wall_started, log)


def _smoke_direct_chat(settings: Settings, messages: list[dict[str, str]]) -> str:
    """One raw chat POST with no max_tokens (like the persona pool draws)."""
    payload = {"model": settings.model, "messages": messages, "temperature": 1.0}
    url = f"{settings.base_url.rstrip('/')}/v1/chat/completions"
    try:
        status, body = _post_json(url, payload, 120.0)
    except OSError:
        return ""
    if status != 200:
        return ""
    try:
        content = json.loads(body)["choices"][0]["message"].get("content")
        return content if isinstance(content, str) else ""
    except (json.JSONDecodeError, KeyError, IndexError):
        return ""


def _draw_smoke_persona(
    settings: Settings,
    item: dict[str, Any],
    pool_file: Path,
    calls: list[dict[str, Any]],
    log: Callable[[str], None],
) -> dict[str, Any] | None:
    """Draw up to two personas for the smoke (second only if first fails).

    Every raw answer is saved next to the pool file
    (smoke_persona_raw_N.txt) so a failed pre-flight leaves direct evidence
    of what the model wrote.
    """
    from fos.experiments import personas  # noqa: PLC0415

    for attempt in range(2):
        messages = [
            {"role": "system", "content": personas.PERSONA_SYSTEM},
            {
                "role": "user",
                "content": personas.build_persona_elicitation_prompt(
                    item["category"], item["product"]
                ),
            },
        ]
        raw = _smoke_direct_chat(settings, messages)
        raw_file = pool_file.with_name(f"smoke_persona_raw_{attempt + 1}.txt")
        raw_file.write_text(raw or "", encoding="utf-8")
        persona = personas.parse_persona(raw)
        calls.append(
            {
                "call": "persona_draw",
                "attempt": attempt + 1,
                "ok": persona is not None,
                "chars": len(raw or ""),
                "raw_file": str(raw_file),
            }
        )
        if persona is not None:
            with pool_file.open("w", encoding="utf-8") as out_handle:
                out_handle.write(json.dumps(persona) + "\n")
            return persona
        log(
            f"smoke: persona draw {attempt + 1} did not parse "
            f"({len(raw or '')} chars; saved to {raw_file.name})"
        )
    return None


def _run_smoke_purchase(
    settings: Settings,
    item: dict[str, Any],
    persona: dict[str, Any] | None,
    design: Any,
    calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One purchase call (with the drawn persona, else the plain survey)."""
    chat = _SWEEP.build_sweep_chat_fn(settings.base_url, settings.model, 16, 120.0)
    if persona is not None:
        personas_by_product = {
            item["product"]: {
                "category": item["category"],
                "regular_price": item["regular_price"],
                "personas": [persona],
            }
        }
        records, _skipped = run_persona_sweep(
            design,
            personas_by_product,
            settings.model,
            chat,
            blinding="blinded",
            persona_depth="demographics",
            seed=settings.seed,
        )
    else:
        records = run_sweep(
            design,
            [item],
            settings.model,
            chat,
            draws=1,
            blinding="blinded",
            seed=settings.seed,
            persona_depth="none",
        )
    parsed = sum(1 for record in records if record.get("succeeded"))
    calls.append(
        {
            "call": "purchase",
            "records": len(records),
            "parsed": parsed,
            "parse_rate": parsed / max(1, len(records)),
        }
    )
    return records


def _write_smoke_manifest(
    settings: Settings,
    run_dir: Path,
    design: Any,
    products: list[dict[str, Any]],
    started: str,
    calls: list[dict[str, Any]],
    persona: dict[str, Any] | None,
    pool_file: Path,
) -> None:
    """Write the smoke run's small manifest.json."""
    write_manifest(
        run_dir / "manifest.json",
        design,
        settings.model,
        1,
        "blinded",
        products[:1],
        settings.base_url,
        extra={
            "smoke": True,
            "calls": calls,
            "started": started,
            "finished": _now(),
            "commit_sha": _repo_sha(),
            "persona_parsed": persona is not None,
            "pool_file": str(pool_file) if persona is not None else None,
        },
    )


def _report_smoke(
    settings: Settings,
    run_dir: Path,
    calls: list[dict[str, Any]],
    pool_file: Path,
    wall_started: float,
    log: Callable[[str], None],
) -> int:
    """Check the smoke outputs, print them, and return the exit code."""
    jsonl = run_dir / f"smoke_{settings.port}.jsonl"
    csv = run_dir / f"smoke_{settings.port}.csv"
    wall_s = time.monotonic() - wall_started
    checks = {
        "manager_load_ok": any(
            c.get("call") == "model_load" and c.get("ok") for c in calls
        ),
        "pool_file_written": pool_file.exists() and pool_file.stat().st_size > 0,
        "records_written": jsonl.exists()
        and csv.exists()
        and jsonl.stat().st_size > 0
        and csv.stat().st_size > 0,
        "manifest_written": (run_dir / "manifest.json").exists(),
    }
    purchase = next((c for c in calls if c.get("call") == "purchase"), {})
    log("smoke results:")
    for name, ok in checks.items():
        log(f"  {name}: {'OK' if ok else 'FAIL'}")
    log(
        f"  purchase parse: {purchase.get('parse_rate', 0.0):.3f} "
        f"({purchase.get('parsed', 0)}/{purchase.get('records', 0)} records)"
    )
    log(f"  model calls made: {len(calls)} (see manifest.json)")
    log(f"  output: {run_dir}")
    log(f"  smoke wall time: {wall_s:.1f} s")
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["smoke_checks"] = checks
        payload["smoke_wall_seconds"] = wall_s
        manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if all(checks.values()) else 1
