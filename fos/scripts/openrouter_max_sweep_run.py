"""Run machinery for the OpenRouter Qwen3.8-Max grammar sweep (TASK-1654).

This module executes a sweep plan against OpenRouter: it runs the plan's
four legs (depth x blinding), writes every answer to disk the moment it
arrives, keeps a running money total with a hard stop, and lets an
interrupted run pick up where it left off. The prompts themselves are NOT
built here - every call goes through the existing sweep kit builders via
the chat-fn adapter, so the questions are byte-identical to the local
runs. The plan builder and the command line live in
openrouter_max_sweep.py, which re-exports run_plan from here.

What each function does (plain language):
    _seeded_draw_counts(...) - Each cell's next draw number, counted from
                              the records already on disk, so a resumed leg
                              keeps numbering its draws correctly.
    _make_sink(...)          - The per-record writer for one leg: stamps
                              the harness fields onto each record (which
                              leg, price, absolute persona index, draw
                              number, token usage, cost, timestamp,
                              classified/unclassified), appends it to the
                              leg's records.jsonl and fsyncs it, updates
                              the shared money/progress counters, and
                              prints a progress line every N calls.
    _run_manifest(...)       - The run's self-description for
                              manifest.json (never contains the API key).
    _run_leg(...)            - Run one (depth x blinding) leg to
                              completion: skip the cells already durable on
                              disk, run the missing ones through the
                              cost-guarded chat adapter, refuse a file
                              that contradicts the plan.
    run_plan(...)            - Run a whole plan: legs in parallel up to the
                              concurrency limit, manifest.json up front,
                              progress.json (calls done/total, cost so
                              far) at the end, and any hard failure
                              (cost cap, rejected model) raised to the
                              caller.

Importing this module never opens a socket; the API is dialed only through
the transport the caller passes in.
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import unblinding_sweep as sweep_cli  # noqa: E402 - scripts/ import order
from fos.experiments.sweep_kit import (  # noqa: E402
    _price_for_level,
    run_persona_sweep,
    run_sweep,
)
from launch_cells import scan_leg_jsonl, write_atomic_json  # noqa: E402

from openrouter_max_sweep_api import (  # noqa: E402
    COMPLETION_USD_PER_M,
    DEFAULT_CONCURRENCY,
    DEFAULT_MAX_COST_USD,
    NONE_LEG_TEMPERATURE,
    OPENROUTER_URL,
    PERSONA_INDICES,
    PERSONA_LEG_TEMPERATURE,
    PROMPT_USD_PER_M,
    build_response_format,
    call_cost_usd,
    decision_text,
    make_openrouter_chat_fn,
    parse_decision,
    subsample_personas,
)

# How often the run prints a one-line progress note (calls, spend, ETA).
PROGRESS_EVERY_CALLS = 100


def _seeded_draw_counts(durable_records: list[dict[str, Any]]) -> dict[tuple, int]:
    """Each cell's next draw number, counted from the records on disk.

    A resumed leg must keep numbering its draws where the durable records
    left off (a repaired cell is draw 2, not a fresh draw 1), so the
    counters start from how many records each (product x level) cell
    already has.
    """
    counts: dict[tuple, int] = {}
    for record in durable_records:
        cell = (record.get("product"), record.get("treatment_value"))
        counts[cell] = counts.get(cell, 0) + 1
    return counts


def _make_sink(
    leg_name: str,
    depth: str,
    price_of: dict[str, float],
    handle: Any,
    usage_slot: dict[str, Any],
    draw_counts: dict[tuple, int],
    state: dict[str, Any],
    lock: threading.Lock,
    progress_every: int,
    log: Callable[[str], None],
) -> Callable[[dict[str, Any]], None]:
    """Build the per-record writer for one leg (the durability seam).

    Every completed call's record lands here the instant sweep_kit builds
    it: the harness stamps its own fields (condition, price, the absolute
    persona index, the draw number, the usage block, the cost, the
    timestamp, the classified/unclassified flag), appends the record to the
    leg's records.jsonl, and fsyncs - so a kill mid-run loses at most the
    one call in flight. The counters also feed the cost guard and the
    every-N-calls progress line.
    """
    start = time.monotonic()

    def sink(record: dict[str, Any]) -> None:
        usage = usage_slot.get("last") or {}
        counted = {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
        }
        parsed = parse_decision(record["raw_content"])
        cell = (record["product"], record["treatment_value"])
        with lock:
            draw_index = draw_counts.get(cell, 0)
            draw_counts[cell] = draw_index + 1
            record["condition"] = leg_name
            record["price"] = _price_for_level(
                price_of[record["product"]], record["treatment_value"]
            )
            record["draw_index"] = draw_index
            record["persona_index"] = (
                PERSONA_INDICES[record["persona_index"]]
                if depth != "none" and isinstance(record.get("persona_index"), int)
                else None
            )
            record["decision"] = decision_text(record["raw_content"])
            record["parsed_purchase"] = parsed
            record["unclassified"] = parsed is None
            record["usage"] = counted
            record["cost_usd"] = call_cost_usd(counted)
            record["timestamp"] = datetime.now(timezone.utc).isoformat()
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            state["calls_done"] += 1
            state["cost_usd"] += record["cost_usd"]
            if state["calls_done"] % progress_every == 0:
                elapsed = time.monotonic() - start
                rate = state["calls_done"] / elapsed if elapsed > 0 else 0.0
                remaining = state["calls_total"] - state["calls_done"]
                eta = remaining / rate if rate > 0 else 0.0
                log(
                    f"[progress] {state['calls_done']}/{state['calls_total']} "
                    f"calls, ${state['cost_usd']:.4f} spent, "
                    f"eta ~{eta / 60:.0f} min"
                )

    return sink


def _run_manifest(
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    pools_from: str,
    max_cost_usd: float,
    concurrency: int,
) -> dict[str, Any]:
    """The run's self-description, written to manifest.json (never a key)."""
    return {
        "profile": plan["profile"],
        "model": plan["model"],
        "seed": plan["seed"],
        "draws": plan["draws"],
        "persona_indices": list(plan["persona_indices"]),
        "levels": plan["levels"],
        "products": products,
        "legs": plan["legs"],
        "sweep_calls": plan["sweep_calls"],
        "pools_from": pools_from,
        "api_url": OPENROUTER_URL,
        "response_format": build_response_format(),
        "temperature_none": NONE_LEG_TEMPERATURE,
        "temperature_personas": PERSONA_LEG_TEMPERATURE,
        "cost_usd_per_m": {
            "prompt": PROMPT_USD_PER_M,
            "completion": COMPLETION_USD_PER_M,
        },
        "max_cost_usd": max_cost_usd,
        "concurrency": concurrency,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }


def _run_leg(
    leg: dict[str, Any],
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    personas_by_product: dict[str, dict[str, Any]] | None,
    model_dir: Path,
    transport: Callable[[dict[str, Any]], dict[str, Any]],
    state: dict[str, Any],
    lock: threading.Lock,
    max_cost_usd: float,
    progress_every: int,
    log: Callable[[str], None],
) -> None:
    """Run one (depth x blinding) leg to completion, resume-aware.

    The leg's own records.jsonl is its resume state: records already on
    disk are skipped (sweep_kit's skip_first) and only the missing cells
    are executed. A file with more records than the plan (or a torn line)
    refuses to run - the configuration changed and we never guess. Each
    call goes through the cost-guarded chat function, so a breach stops
    the run before the next call is dialed.
    """
    depth, blinding = leg["depth"], leg["blinding"]
    leg_name = f"{depth}_{blinding}"
    leg_dir = model_dir / leg_name
    leg_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = leg_dir / "records.jsonl"
    durable_records, torn = scan_leg_jsonl(jsonl_path)
    if torn:
        raise RuntimeError(
            f"{jsonl_path} holds {torn} torn record line(s); repair or "
            "remove the leg directory before resuming"
        )
    planned = int(leg["calls"])
    durable = len(durable_records)
    if durable > planned:
        raise RuntimeError(
            f"{jsonl_path} holds {durable} records but the plan has "
            f"{planned}; the run configuration changed - use a new run dir"
        )
    if durable:
        with lock:
            state["calls_done"] += durable
            state["cost_usd"] += sum(
                float(record.get("cost_usd") or 0.0) for record in durable_records
            )
    if durable >= planned:
        log(f"leg {leg_name}: all {durable} records already durable - skipped")
        return
    draw_counts = _seeded_draw_counts(durable_records)
    design = sweep_cli._build_design(
        plan["levels"], [blinding], plan["seed"], list(sweep_cli.COVARIATE_KINDS), depth
    )
    price_of = {product["product"]: product["regular_price"] for product in products}
    usage_slot: dict[str, Any] = {}
    handle = jsonl_path.open("a", encoding="utf-8")
    try:
        base_chat = make_openrouter_chat_fn(
            transport,
            model=plan["model"],
            on_usage=lambda usage: usage_slot.__setitem__("last", usage),
        )

        def guarded_chat(messages: list[dict[str, str]], temperature: float) -> str:
            with lock:
                if state["cost_usd"] > max_cost_usd:
                    raise RuntimeError(
                        f"cost guard: accumulated ${state['cost_usd']:.4f} "
                        f"exceeds the --max-cost cap ${max_cost_usd:.2f}; "
                        "aborting before any further API calls"
                    )
            return base_chat(messages, temperature)

        sink = _make_sink(
            leg_name,
            depth,
            price_of,
            handle,
            usage_slot,
            draw_counts,
            state,
            lock,
            progress_every,
            log,
        )
        if depth == "none":
            run_sweep(
                design,
                products,
                plan["model"],
                guarded_chat,
                draws=plan["draws"],
                blinding=blinding,
                seed=plan["seed"],
                persona_depth="none",
                skip_first=durable,
                on_record=sink,
            )
        else:
            if personas_by_product is None:
                raise RuntimeError("demographics leg without persona pools")
            sliced = {
                name: {**info, "personas": subsample_personas(info["personas"])}
                for name, info in personas_by_product.items()
            }
            run_persona_sweep(
                design,
                sliced,
                plan["model"],
                guarded_chat,
                blinding=blinding,
                persona_depth="demographics",
                seed=plan["seed"],
                skip_first=durable,
                on_record=sink,
            )
    finally:
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()


def run_plan(
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    personas_by_product: dict[str, dict[str, Any]] | None,
    run_dir: Path,
    transport: Callable[[dict[str, Any]], dict[str, Any]],
    concurrency: int = DEFAULT_CONCURRENCY,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
    progress_every: int = PROGRESS_EVERY_CALLS,
    log: Callable[[str], None] = print,
    pools_from: str = "",
) -> None:
    """Run a plan's legs (in parallel up to `concurrency`) into run_dir.

    The legs run as independent workers, each writing its own records.jsonl
    (fsync per record) so resume is cell-granular; the shared state tracks
    total calls and spend for the cost guard and progress.json. A cost
    breach or a rejected model id raises, after the in-flight call is
    recorded; the other legs hit the same shared guard (or the same model
    rejection) on their next call, so no leg keeps spending after a hard
    stop. manifest.json is written up front (a killed run still
    self-describes) and progress.json at the end (calls done / total, cost
    so far).
    """
    run_dir = Path(run_dir)
    model_dir = run_dir / sweep_cli._safe_model_name(plan["model"])
    model_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "calls_done": 0,
        "calls_total": plan["sweep_calls"],
        "cost_usd": 0.0,
    }
    lock = threading.Lock()
    write_atomic_json(
        run_dir / "manifest.json",
        _run_manifest(plan, products, pools_from, max_cost_usd, concurrency),
    )
    workers = max(1, min(concurrency, len(plan["legs"])))
    failure: BaseException | None = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _run_leg,
                leg,
                plan,
                products,
                personas_by_product,
                model_dir,
                transport,
                state,
                lock,
                max_cost_usd,
                progress_every,
                log,
            )
            for leg in plan["legs"]
        ]
        for future in as_completed(futures):
            error = future.exception()
            if error is not None and failure is None:
                failure = error
    if failure is not None:
        raise failure
    progress = {
        "profile": plan["profile"],
        "model": plan["model"],
        "calls_done": state["calls_done"],
        "calls_total": plan["sweep_calls"],
        "cost_usd": state["cost_usd"],
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    write_atomic_json(run_dir / "progress.json", progress)
    log(
        f"run complete: {state['calls_done']}/{plan['sweep_calls']} calls, "
        f"${state['cost_usd']:.4f} spent -> {run_dir}"
    )
