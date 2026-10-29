"""One R1-5MODEL queue leg: cell-granular writes, resume, results rows.

A queue leg is one (model x depth x blinding) cell stream: every product
(and persona, for the demographics legs) at every price level. This module
runs ONE such leg with the single-model wrapper's cell-granular durability
(TASK-1533): each completed cell's record is appended to the leg's
records.jsonl and flushed the moment it is produced (fsync every
FSYNC_EVERY records and at leg end), a resumed leg skips the cells already
durable on disk (skip_first), and each completed cell also appends its
normalized row to the run's results.csv. The leg's records.csv and its
manifest.json are written only when the whole leg completes; a leg
interrupted mid-run keeps every completed cell and is continued by
--resume at the cell level. The demographics legs slice the shared
100-persona pool to the plan-recorded persona slice of the leg's model
(the 5-model partition [20i, 20i+20); the QWENEXT plans record the
shared [40, 60) slice instead).

What each function does (plain language):
    run_queue_leg(...)        - Run one leg to completion (or to a stop /
                                failure), writing each cell as it finishes.
    _finalize_queue_leg(...)  - Write a COMPLETED leg's records.csv +
                                manifest + result entry (never rewrites the
                                records.jsonl).
    _queue_leg_summary_from_disk(...) - A finished leg's summary rebuilt
                                from its own records (manifest merge).
Importing this module never opens a socket; the chat calls happen only
through the chat_fn the caller passes in.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for _dir in (_SCRIPT_DIR, _REPO_ROOT / "src"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from fos.experiments.sweep_kit import (  # noqa: E402
    run_logprob_persona_sweep,
    run_logprob_sweep,
    run_persona_sweep,
    run_sweep,
    write_manifest,
)

from launch_cells import (  # noqa: E402
    FSYNC_EVERY,
    durable_cells,
    scan_leg_jsonl,
    write_leg_csv,
)
from launch_queue import (  # noqa: E402
    PERSONAS_PER_MODEL,
    model_control_sequences,
    model_top_k,
    plan_persona_slice,
    queue_leg_dir,
    queue_leg_done,
    queue_leg_jsonl,
    slice_persona_map,
)
from launch_queue_outputs import QueueProgress, QueueResultsCsv  # noqa: E402
from launch_support import Settings, _SWEEP, _now, _repo_sha  # noqa: E402
from logprob_scoring import FIRST_TOKEN  # noqa: E402


def _finalize_queue_leg(
    settings: Settings,
    plan: dict[str, Any],
    run_dir: Path,
    leg_dir: Path,
    target: dict[str, Any],
    products: list[dict[str, Any]],
    results: list[dict[str, Any]],
    log: Callable[[str], None],
) -> None:
    """Write one COMPLETED queue leg's records.csv + manifest and result.

    The records.jsonl was already written record-by-record (per-cell
    durability); this only adds the derived csv and the leg manifest, then
    appends the leg's result entry computed from the full jsonl on disk.
    The manifest records the model's persona slice and the grammar used.
    """
    records, torn = scan_leg_jsonl(queue_leg_jsonl(leg_dir))
    if not records or torn:
        results.append(
            {
                **target,
                "ok": False,
                "error": f"leg records file torn/incomplete ({torn})",
            }
        )
        log(
            f"leg {target['safe_model']}/{target['depth']}_{target['blinding']} "
            "could not finalize (torn file)"
        )
        return
    parsed = sum(1 for record in records if record.get("succeeded"))
    mean_elapsed = sum(
        float(record.get("elapsed_seconds") or 0.0) for record in records
    ) / len(records)
    blinding = target["blinding"]
    write_leg_csv(leg_dir / "records", records)
    design = _SWEEP._build_design(
        plan["levels"],
        [blinding],
        settings.seed,
        list(_SWEEP.COVARIATE_KINDS),
        target["depth"],
    )
    start, stop = plan_persona_slice(plan, target["model_index"])
    manifest_extra: dict[str, Any] = {
        "levels": plan["levels"],
        "temperature": 1.0,
        "seed": settings.seed,
        "argv": list(sys.argv),
        "started": _now(),
        "finished": _now(),
        "depth": target["depth"],
        "run_name": run_dir.name,
        "model_index": target["model_index"],
        "persona_slice": [start, stop],
        "personas_per_product": PERSONAS_PER_MODEL
        if target["depth"] != "none"
        else None,
        "pool_seed": settings.pool_seed,
        "grammar": settings.grammar,
        "logprob_mode": settings.logprob_mode,
        "response_format": settings.response_format,
        "commit_sha": _repo_sha(),
    }
    if settings.logprob_mode == FIRST_TOKEN:
        # Stamp the top-k coverage that was in force on this leg's
        # first_token requests, so a reader knows how wide the recorded
        # top-k lists are (the profile's per-model override, else 20).
        manifest_extra["top_k"] = model_top_k(target["model"])
        # Stamp the control sequences that were in force too (the
        # profile's per-model header override, else the default-off
        # empty list), so a reader always knows which header config a
        # leg's recorded replies were scored with.
        manifest_extra["control_sequences"] = [
            list(sequence) for sequence in model_control_sequences(target["model"])
        ]
    write_manifest(
        leg_dir / "manifest.json",
        design,
        settings.model,
        settings.draws,
        blinding,
        products,
        settings.base_url,
        extra=manifest_extra,
    )
    results.append(
        {
            **target,
            "ok": True,
            "records": len(records),
            "parsed": parsed,
            "parse_rate": parsed / len(records),
            "mean_elapsed": mean_elapsed,
            "files": [
                str(queue_leg_jsonl(leg_dir)),
                str(leg_dir / "records.csv"),
                str(leg_dir / "manifest.json"),
            ],
        }
    )
    log(
        f"leg {target['model']} {target['depth']}_{target['blinding']} done: "
        f"{len(records):,} records, parse "
        f"{100.0 * parsed / len(records):.1f}%"
    )


def run_queue_leg(
    settings: Settings,
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    personas_by_product: dict[str, dict[str, Any]] | None,
    run_dir: Path,
    chat_fn: Callable[..., str],
    target: dict[str, Any],
    results: list[dict[str, Any]],
    log: Callable[[str], None],
    progress: QueueProgress | None,
    results_csv: QueueResultsCsv | None,
    *,
    scorer_fn: Callable[..., dict[str, Any]] | None = None,
) -> None:
    """Run one (model x depth x blinding) leg and record its outcome.

    Mirrors the single-model wrapper's cell-granular leg (TASK-1533): each
    completed cell's record is appended to the leg's records.jsonl and
    flushed the moment it is produced (fsync every FSYNC_EVERY records and
    at leg end), a resumed leg skips the cells already durable on disk
    (skip_first), and each completed cell also appends its normalized row
    to the run's results.csv. The records.csv and the leg manifest are
    written only when the whole leg completes.

    When settings.logprob_mode is set (R1LP), the leg scores each prompt
    once through scorer_fn instead of sampling draws through chat_fn; the
    cell enumeration, durability and resume semantics are unchanged (one
    cell = one prompt).
    """
    leg_dir = queue_leg_dir(run_dir, target)
    leg_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = queue_leg_jsonl(leg_dir)
    leg_key = f"{target['model']} {target['depth']}_{target['blinding']}"
    planned = int(target.get("calls") or 0)
    durable, _durable_parsed = durable_cells(jsonl_path)
    if durable > planned:
        results.append(
            {
                **target,
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
        progress.set_leg(target, done_at_start=durable)
    remaining = planned - durable
    if remaining <= 0 and durable:
        # Every cell is already durable (crash after the last record but
        # before the leg's csv/manifest): finalize without any chat calls.
        log(f"leg {leg_key}: all {durable} cells already durable - finalizing")
        _finalize_queue_leg(
            settings, plan, run_dir, leg_dir, target, products, results, log
        )
        return
    personas_by_model: dict[str, dict[str, Any]] | None = None
    if target["depth"] != "none":
        if personas_by_product is None:
            raise RuntimeError("persona leg without persona pools")
        personas_by_model = slice_persona_map(
            personas_by_product,
            target["model_index"],
            bounds=plan_persona_slice(plan, target["model_index"]),
        )
    design = _SWEEP._build_design(
        plan["levels"],
        [target["blinding"]],
        settings.seed,
        list(_SWEEP.COVARIATE_KINDS),
        target["depth"],
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
            progress.note(target, succeeded=bool(record.get("succeeded")), force=False)
        if results_csv is not None:
            results_csv.append(record, target=target)

    try:
        if settings.logprob_mode:
            if scorer_fn is None:
                raise RuntimeError("logprob mode without a scorer function")
            if target["depth"] == "none":
                run_logprob_sweep(
                    design,
                    products,
                    settings.model,
                    scorer_fn,
                    draws=settings.draws,
                    blinding=target["blinding"],
                    seed=settings.seed,
                    persona_depth="none",
                    skip_first=durable,
                    on_record=record_sink,
                    response_format=settings.response_format,
                )
            else:
                run_logprob_persona_sweep(
                    design,
                    personas_by_model or {},
                    settings.model,
                    scorer_fn,
                    blinding=target["blinding"],
                    persona_depth="demographics",
                    seed=settings.seed,
                    skip_first=durable,
                    on_record=record_sink,
                    response_format=settings.response_format,
                )
        elif target["depth"] == "none":
            run_sweep(
                design,
                products,
                settings.model,
                chat_fn,
                draws=settings.draws,
                blinding=target["blinding"],
                seed=settings.seed,
                persona_depth="none",
                skip_first=durable,
                on_record=record_sink,
            )
        else:
            run_persona_sweep(
                design,
                personas_by_model or {},
                settings.model,
                chat_fn,
                blinding=target["blinding"],
                persona_depth="demographics",
                seed=settings.seed,
                skip_first=durable,
                on_record=record_sink,
            )
    except Exception as exc:  # never swallow a leg failure (1533 semantics)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        cells_on_disk = written["records"] + durable
        results.append(
            {
                **target,
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
        results.append({**target, "ok": False, "error": "no records produced"})
        log(f"leg {leg_key} produced no records")
        return
    _finalize_queue_leg(
        settings, plan, run_dir, leg_dir, target, products, results, log
    )


def _queue_leg_summary_from_disk(
    run_dir: Path, target: dict[str, Any]
) -> dict[str, Any] | None:
    """A finished queue leg's summary rebuilt from its own records.

    A leg that finished in an earlier invocation but was never recorded in
    the run-level manifest is reconstructed here from its own records.jsonl
    (record count, parsed count, parse rate, mean elapsed) so the final
    merged manifest lists every planned leg exactly once. Returns None when
    the leg is not durably done.
    """
    if not queue_leg_done(run_dir, target):
        return None
    leg_dir = queue_leg_dir(run_dir, target)
    records, _torn = scan_leg_jsonl(queue_leg_jsonl(leg_dir))
    if not records:
        return None
    parsed = sum(1 for record in records if record.get("succeeded"))
    mean_elapsed = sum(
        float(record.get("elapsed_seconds") or 0.0) for record in records
    ) / len(records)
    return {
        **target,
        "ok": True,
        "records": len(records),
        "parsed": parsed,
        "parse_rate": parsed / len(records),
        "mean_elapsed": mean_elapsed,
        "files": [
            str(queue_leg_jsonl(leg_dir)),
            str(leg_dir / "records.csv"),
            str(leg_dir / "manifest.json"),
        ],
    }
