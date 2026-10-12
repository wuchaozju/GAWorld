# This file is the twin2k10 study's runner: the single command that
# executes the 57,000-cell measurement grid against the local llama.cpp
# models. One launch does everything in order: it makes the run folder
# (results/unblinding/T2K10-<stamp>/), generates the shared persona pool,
# runs the AUTO-PREFLIGHT (every model answers persona 0 once per
# experiment arm and blinding), judges each model with the pure
# preflight.decide() verdict, writes PREFLIGHT_REPORT.md and the
# skipped_models.json list, and — unless every model failed — continues
# into the full grid for the surviving models, unloading each model when
# its block is done. --preflight-only stops right there: the persona-0
# preflight cells run exactly as in a full launch (through the same
# durable leg files, report and verdict written) and the process exits 0
# BEFORE the grid — the owner's per-model live test
# (`--models <one model> --preflight-only`). Every finished record is
# appended to its leg's records file the moment it exists (flush per
# record, force-sync every 50), so a killed run restarts with --run-dir
# <same folder> and skips every cell already on disk — preflight cells
# included, so a full launch after a preflight never duplicates a
# completed record. --dry-run needs no server: it prints the cell counts
# and checks the rendered per-item prompts, writing nothing. --smoke runs
# the live pre-launch check instead of the production grid: the smallest
# model answers one persona on all 19 arms x 2 blinding arms, in its own
# T2K10-SMOKE-<stamp> run folder, so production folders are never touched
# by a smoke run.

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
_SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS = _SCRIPT_DIR.parent
_REPO_ROOT = _SCRIPTS.parent
for _dir in (str(_SCRIPTS), str(_REPO_ROOT / "src")):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

from launch_cells import (  # noqa: E402
    durable_cells,
    scan_leg_jsonl,
    write_atomic_json,
)
from twin2k10 import (  # noqa: E402
    cells,
    config,
    experiments,
    legexec,
    preflight,
    registry,
    serving,
)
from twin2k10 import dryrun  # noqa: E402

PREFLIGHT_PERSONA = 0
VERDICT_FILE = "preflight_verdict.json"


def _now() -> str:
    """The current UTC time as an ISO-8601 string (logs and manifests)."""
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    """One timestamped progress line on stdout (the runner's only output)."""
    print(f"[{_now()}] {message}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """The runner's command-line interface (see --help)."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.twin2k10.runner",
        description="Run the twin2k10 grid (auto-preflight, then full) "
                    "on the 15 local models.",
    )
    parser.add_argument(
        "--run-dir", default=None, type=Path,
        help="existing run folder to (re)use — pass it to resume after a "
             "crash; omitted, a fresh results/unblinding/T2K10-<stamp> is "
             "created",
    )
    parser.add_argument(
        "--models", default=None,
        help="comma-separated subset of study model ids (default: all 15)",
    )
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True,
        help="skip cells already durable in the run dir (default: yes)",
    )
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="run the auto-preflight (persona 0 on every arm, both "
             "blinding arms, per requested model), write the preflight "
             "report and verdict, then STOP with exit 0 before the grid",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print cell counts and check rendered prompts; write nothing",
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help="live pre-launch smoke test: the smallest model (%s) answers "
             "one persona on all 19 arms x 2 blinding arms (%d cells) into "
             "its own T2K10-SMOKE-<stamp> run dir — a production run dir is "
             "never touched"
             % (config.SMOKE_MODEL, 19 * len(config.BLINDINGS)),
    )
    parser.add_argument("--manager-url", default=config.DEFAULT_MANAGER_URL)
    parser.add_argument("--base-url", default=config.DEFAULT_BASE_URL)
    parser.add_argument("--port", type=int, default=8080)
    return parser.parse_args(argv)


def resolve_models(requested: str | None) -> list[str]:
    """The run's model list: all 15 study models, or the validated subset."""
    if requested is None:
        return list(config.MODELS)
    models = [name.strip() for name in requested.split(",") if name.strip()]
    if not models:
        raise SystemExit("error: --models given but no model id could be read")
    for model in models:
        registry.manager_model_id(model)  # raises ValueError on a typo
    return models


def new_run_dir(smoke: bool = False) -> Path:
    """A fresh run folder: results/unblinding/T2K10-<UTC stamp>/, or the
    smoke test's own T2K10-SMOKE-<stamp>/ so the two can never mix."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    prefix = (config.SMOKE_RUN_NAME_PREFIX if smoke
              else config.RUN_NAME_PREFIX)
    return config.RUNS_ROOT / f"{prefix}{stamp}"


def file_sha256(path: Path) -> str:
    """The hex sha256 of a file (stimuli provenance in the manifest)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repo_sha() -> str:
    """The repository commit at run time ("" when not a git checkout)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10.0,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def write_start_manifest(run_dir: Path, models: list[str]) -> None:
    """The run manifest's start state (facts fixed before the first call)."""
    payload = {
        "study": config.STUDY_NAME,
        "models": registry.model_manifest_entries(models),
        "pool": {
            "product": serving.POOL_PRODUCT, "k": serving.POOL_K,
            "pool_seed": serving.POOL_SEED,
            "generator_model": serving.GENERATOR_MODEL,
        },
        "inference": legexec.inference_settings(config.DEFAULT_BASE_URL),
        "stimuli_sha256": file_sha256(config.STIMULI_PATH),
        "git_sha": repo_sha(),
        "started": _now(),
        "run_dir": str(run_dir),
    }
    write_atomic_json(Path(run_dir) / "manifest.json", payload)


def leg_stats(run_dir: Path, models: list[str]) -> dict[str, dict]:
    """Per-leg record counts rebuilt from the leg files (manifest finalize)."""
    stats: dict[str, dict] = {}
    for model in models:
        for experiment in experiments.EXPERIMENTS:
            for blind in config.BLINDINGS:
                directory = legexec.leg_dir(run_dir, model, experiment, blind)
                records, torn = scan_leg_jsonl(directory / "records.jsonl")
                if not records:
                    continue
                succeeded = sum(1 for r in records if r.get("succeeded"))
                stats[f"{model}/{experiment}_{blind}"] = {
                    "records": len(records),
                    "succeeded": succeeded,
                    "failed": len(records) - succeeded,
                    "torn": torn,
                }
    return stats


def finalize_manifest(run_dir: Path, models: list[str]) -> None:
    """Merge the per-leg stats into the run manifest at the run's end."""
    path = Path(run_dir) / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["legs"] = leg_stats(run_dir, models)
    payload["finished"] = _now()
    write_atomic_json(path, payload)


def refuse_started(run_dir: Path) -> None:
    """--no-resume guard: refuse to append to a run that already has data."""
    for path in Path(run_dir).glob("**/records.jsonl"):
        if path.stat().st_size > 0:
            raise SystemExit(
                f"error: --no-resume refuses to append to existing records "
                f"({path}); use --resume or a fresh --run-dir"
            )


def new_progress(total: int) -> dict:
    """A fresh progress state (records_done / per-model counters)."""
    return {"records_done": 0, "records_total": total, "per_model": {}}


def write_progress(run_dir: Path, progress: dict) -> None:
    """The run's progress.json snapshot (atomic; the operator can tail it)."""
    write_atomic_json(Path(run_dir) / "progress.json", {
        "records_done": progress["records_done"],
        "records_total": progress["records_total"],
        "per_model": progress["per_model"],
        "updated_at": _now(),
    })


def note_record(run_dir: Path, progress: dict, model: str) -> None:
    """Count one finished record; rewrite progress.json at least every 50."""
    progress["records_done"] += 1
    progress["per_model"][model] = progress.get("per_model", {}).get(model, 0) + 1
    if progress["records_done"] % config.FSYNC_EVERY == 0:
        write_progress(run_dir, progress)


def run_legs(run_dir: Path, model: str, personas: list[dict], ids: list[int],
             base_url: str, progress: dict) -> None:
    """One model's 38-leg block (19 arms x 2 blinding arms), with resume.

    Each leg's records file is repaired for a torn tail, then run_cells
    scores only the cells not yet durable — a resumed run (or the full
    phase after the preflight) calls the model only for missing cells.
    """
    context = legexec.make_leg_context(model, base_url, personas)
    transport = legexec.make_transport(
        context,
        lambda record: note_record(run_dir, progress, model),
    )
    for experiment in experiments.EXPERIMENTS:
        for blind in config.BLINDINGS:
            planned = legexec.leg_cells(model, ids, experiment, blind)
            directory = legexec.leg_dir(run_dir, model, experiment, blind)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "records.jsonl"
            durable, _parsed = durable_cells(path)  # repairs a torn tail
            if durable:
                log(f"  leg {experiment}_{blind}: {durable} records durable")
            cells.run_cells(planned, transport, path)
            log(f"  leg {experiment}_{blind}: {len(planned)} cells planned "
                f"({durable} were already durable)")


def collect_persona_records(run_dir: Path, model: str,
                            persona_id: int) -> list[dict]:
    """Every kept record of one model whose persona_id matches (preflight)."""
    records: list[dict] = []
    for experiment in experiments.EXPERIMENTS:
        for blind in config.BLINDINGS:
            directory = legexec.leg_dir(run_dir, model, experiment, blind)
            leg_records, _torn = scan_leg_jsonl(directory / "records.jsonl")
            records.extend(r for r in leg_records
                           if r.get("persona_id") == persona_id)
    return records


def preflight_phase(run_dir: Path, models: list[str], personas: list[dict],
                    base_url: str, manager_url: str, port: int,
                    progress: dict) -> set[str]:
    """The AUTO-PREFLIGHT: persona 0 on every model, then the verdict.

    Runs the persona-0 cells of every model through the same durable leg
    files the full grid uses, then judges each model with the pure
    preflight.decide(): a model whose decide() verdict says stop goes
    into the returned skip set and skipped_models.json, and the report
    is written either way. Raises SystemExit when EVERY model failed —
    the study must not start on an all-broken queue.
    """
    per_model: dict[str, list[dict]] = {}
    for model in models:
        log(f"=== preflight {model} ({registry.manager_model_id(model)}) ===")
        serving.ensure_model_loaded(manager_url, base_url, model, port, log)
        run_legs(run_dir, model, personas, [PREFLIGHT_PERSONA], base_url,
                 progress)
        serving.unload_model(manager_url, port, model, log)
        per_model[model] = collect_persona_records(run_dir, model,
                                                   PREFLIGHT_PERSONA)
    verdict: dict[str, list[str]] = {}
    for model, records in per_model.items():
        outcome = preflight.decide(records)
        if outcome["stop"]:
            verdict[model] = outcome["reasons"]
    preflight.write_outputs(run_dir, per_model, verdict)
    write_atomic_json(Path(run_dir) / VERDICT_FILE, {
        "stopped": sorted(verdict), "models": models, "finished": _now(),
    })
    for model, reasons in verdict.items():
        log(f"preflight STOP {model}: {len(reasons)} reason(s)")
    if len(verdict) == len(models):
        raise SystemExit(
            "STOP — every model failed the technical preflight; see "
            f"{run_dir / 'PREFLIGHT_REPORT.md'}"
        )
    return set(verdict)


def _run_shape(args: argparse.Namespace) -> tuple[list[str], list[int], int]:
    """The run's model list, persona ids, and record total (smoke-aware).

    A smoke run is exactly the smoke filter's grid (1 model x 1 persona
    x 19 arms x 2 blindings); a production run is the requested models
    over the full 100-persona pool. Either way the auto-preflight runs
    persona 0 first, through the same durable leg files.
    """
    if args.smoke:
        return ([config.SMOKE_MODEL], [config.SMOKE_PERSONA_ID],
                len(cells.smoke_cells()))
    models = resolve_models(args.models)
    return models, list(range(config.PERSONA_COUNT)), \
        len(models) * cells.EXPECTED_RECORDS_PER_MODEL


def run_all(args: argparse.Namespace) -> int:
    """The full flow: run folder, pool, auto-preflight, grid, finalize."""
    models, persona_ids, total = _run_shape(args)
    run_dir = Path(args.run_dir) if args.run_dir else new_run_dir(args.smoke)
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"run dir: {run_dir}")
    if args.smoke:
        log(f"smoke run: {models[0]} answers persona "
            f"{config.SMOKE_PERSONA_ID} on all 19 arms x 2 blindings "
            f"({total} cells) — a T2K10-SMOKE- folder; production run "
            f"dirs are never touched")
    if not args.resume:
        refuse_started(run_dir)
    write_start_manifest(run_dir, models)
    progress = new_progress(total)
    write_progress(run_dir, progress)
    personas = serving.ensure_pool(run_dir, args.manager_url, args.base_url,
                                   log)
    log(f"pool ready: {len(personas)} personas (ids 0-{len(personas) - 1})")
    if (Path(run_dir) / VERDICT_FILE).is_file():
        log("preflight verdict already present — skipping the preflight "
            "phase (resume)")
        skipped = skip_set(run_dir)
    else:
        skipped = preflight_phase(run_dir, models, personas, args.base_url,
                                  args.manager_url, args.port, progress)
    if args.preflight_only:
        write_progress(run_dir, progress)
        log("preflight-only: preflight phase finished — stopping before "
            "the grid as requested (--preflight-only)")
        return 0
    if skipped:
        log(f"preflight skip list active — excluding: {sorted(skipped)}")
    running = [model for model in models if model not in skipped]
    for model in running:
        log(f"=== model {model} ({registry.manager_model_id(model)}) ===")
        serving.ensure_model_loaded(args.manager_url, args.base_url, model,
                                    args.port, log)
        run_legs(run_dir, model, personas, persona_ids,
                 args.base_url, progress)
        serving.unload_model(args.manager_url, args.port, model, log)
    write_progress(run_dir, progress)
    finalize_manifest(run_dir, models)
    log(f"run complete: {progress['records_done']} records written by this "
        f"process into {run_dir}")
    return 0


def skip_set(run_dir: Path) -> set[str]:
    """The models a finished preflight STOP-flagged (the grid leaves out)."""
    path = Path(run_dir) / "skipped_models.json"
    if not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return set(payload.get("skipped_models", []))


def main(argv: list[str] | None = None) -> int:
    """The CLI entry point (module execution starts here)."""
    args = parse_args(argv)
    models = ([config.SMOKE_MODEL] if args.smoke
              else resolve_models(args.models))
    if args.dry_run:
        return dryrun.dry_run(models, smoke=args.smoke,
                              preflight_only=args.preflight_only,
                              preflight_persona=PREFLIGHT_PERSONA)
    return run_all(args)


if __name__ == "__main__":
    sys.exit(main())
