# This file is the twin2k6 study's runner: the command-line program that
# executes the 48,000-cell measurement grid (or its small preflight cousin)
# against the local llama.cpp models. For each of the 15 models it loads the
# model through the model manager, answers every (persona, question version,
# blinding) cell through the proven first-token logprob scorer, writes each
# finished record to its leg's records file the moment it exists (flush per
# record, force-sync every 50, torn-line repair on resume), and unloads the
# model. A killed run restarts with --resume and skips every cell already on
# disk — including the persona-0 cells the preflight subtree finished, so a
# full launch after a preflight never duplicates a completed record (spec
# §10). --mode preflight runs just persona 0 on every model into a PREFLIGHT
# folder and writes the technical PREFLIGHT_REPORT.md; it never starts the
# full run. --dry-run needs no server: it prints the cell counts and checks
# the rendered prompts, writing nothing.

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
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
from twin2k6 import (  # noqa: E402
    cells,
    config,
    experiments,
    legexec,
    preflight,
    prompts,
    registry,
)

# The synthetic single-product persona pool: one neutral product name, the
# study's pool seed and size (PIPELINE_MAP §6's recommended cleanest path).
POOL_PRODUCT = "twin2k_respondent"
POOL_CATEGORY = "grocery item"
POOL_K = config.PERSONA_COUNT
POOL_SEED = config.SEED
# The pool must be DRAWN by one declared model; pin it to the study's first
# model so a resumed/subset run never disagrees with the pools.json marker.
GENERATOR_MODEL = registry.manager_model_id(config.MODELS[0])
PREFLIGHT_DIRNAME = "PREFLIGHT"

# A clearly-synthetic persona so --dry-run can render real prompts with no
# model server and no pool on disk (never used for actual measurements).
PLACEHOLDER_PERSONA = {
    "age": 34, "gender": "woman", "education": "bachelor's degree",
    "household_income": 50000, "occupation": "teacher", "ethnicity": "white",
    "marital_status": "married", "household_size": 3, "number_of_children": 1,
    "state": "CA", "home_ownership": "own",
}


def _now() -> str:
    """The current UTC time as an ISO-8601 string (logs and manifests)."""
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    """One timestamped progress line on stdout (the runner's only output)."""
    print(f"[{_now()}] {message}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """The runner's command-line interface (see --help)."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.twin2k6.runner",
        description="Run the twin2k6 grid (full or preflight) on local models.",
    )
    parser.add_argument("--mode", required=True, choices=("preflight", "full"))
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--models", default=None,
        help="comma-separated subset of study model ids (default: all 15)",
    )
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True,
        help="skip cells already durable in the run dir (default: yes)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print cell counts and check persona-0 prompts; write nothing",
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


def mode_root(run_dir: Path, mode: str) -> Path:
    """Where a mode's legs and manifest live (full: the run dir itself)."""
    return Path(run_dir) if mode == "full" else Path(run_dir) / PREFLIGHT_DIRNAME


def persona_ids_for(mode: str) -> list[int]:
    """The persona ids a mode answers: preflight only persona 0."""
    return [0] if mode == "preflight" else list(range(config.PERSONA_COUNT))


def records_per_model(mode: str) -> int:
    """How many records one model produces in a mode (3200 full, 32 pre)."""
    return len(persona_ids_for(mode)) * 16 * len(config.BLINDINGS)


def file_sha256(path: Path) -> str:
    """The hex sha256 of a file (stimuli/benchmarks provenance in manifests)."""
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


def write_products_file(run_dir: Path) -> Path:
    """The one-product products file the persona pool phase is driven with."""
    path = Path(run_dir) / "twin2k_pool_products.json"
    payload = {"products": [{
        "category": POOL_CATEGORY, "product": POOL_PRODUCT, "regular_price": 1.0,
    }]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_pool(run_dir: Path) -> list[dict]:
    """The shared persona pool: 100 demographics-only personas, ids 0-99.

    Persona ids are the pool file's line order. Refuses (loudly) a pool
    with the wrong size or any non-demographic field — a polluted pool
    would leak into every prompt of every model.
    """
    pool_path = registry.pool_file(run_dir)
    personas = [
        json.loads(line) for line in
        pool_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(personas) != POOL_K:
        raise SystemExit(
            f"error: {pool_path} holds {len(personas)} personas, expected {POOL_K}"
        )
    for index, persona in enumerate(personas):
        extra = set(persona) - set(prompts.PERSONA_FIELDS)
        if extra:
            raise SystemExit(
                f"error: persona {index} carries non-demographic fields "
                f"{sorted(extra)} — refusing a leaking pool"
            )
    return personas


def ensure_pool(run_dir: Path, manager_url: str, base_url: str) -> list[dict]:
    """The pool phase: generate + subsample via the existing machinery.

    Reuses launch_support._pool_phase verbatim with the synthetic single
    product (idempotent: a matching pools.json marker skips regeneration),
    then reads the finished pool back with its 0-99 line-order ids.
    """
    from launch_support import Settings, _pool_phase  # lazy: heavy import

    settings = Settings(
        model=GENERATOR_MODEL, port=8080, manager_url=manager_url,
        base_url=base_url, out=Path(run_dir), run_name=Path(run_dir).name,
        pool_seed=POOL_SEED, pool_overdraw=1.2, seed=config.SEED, draws=1,
        progress_every=1000, products_path=str(write_products_file(run_dir)),
    )
    products = json.loads(
        Path(settings.products_path).read_text(encoding="utf-8")
    )["products"]
    _pool_phase(settings, products, Path(settings.products_path),
                Path(run_dir), POOL_K, log)
    return load_pool(run_dir)


def skip_set(run_dir: Path) -> set[str]:
    """The models a preflight STOP-flagged (the full run leaves them out)."""
    path = Path(run_dir) / PREFLIGHT_DIRNAME / "skipped_models.json"
    if not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return set(payload.get("skipped_models", []))


def write_start_manifest(root: Path, mode: str, models: list[str],
                         run_dir: Path) -> None:
    """The run manifest's start state (facts fixed before the first call)."""
    payload = {
        "study": config.STUDY_NAME,
        "mode": mode,
        "models": registry.model_manifest_entries(models),
        "pool": {
            "product": POOL_PRODUCT, "k": POOL_K, "pool_seed": POOL_SEED,
            "generator_model": GENERATOR_MODEL,
        },
        "inference": legexec.inference_settings(config.DEFAULT_BASE_URL),
        "stimuli_sha256": file_sha256(config.STIMULI_PATH),
        "benchmarks_sha256": file_sha256(config.BENCHMARKS_PATH),
        "git_sha": repo_sha(),
        "started": _now(),
        "run_dir": str(run_dir),
    }
    write_atomic_json(root / "manifest.json", payload)


def leg_stats(root: Path, models: list[str]) -> dict[str, dict]:
    """Per-leg record counts rebuilt from the leg files (manifest finalize)."""
    stats: dict[str, dict] = {}
    for model in models:
        for experiment in experiments.EXPERIMENTS:
            for blind in config.BLINDINGS:
                directory = legexec.leg_dir(root, model, experiment, blind)
                records, torn = scan_leg_jsonl(directory / "records.jsonl")
                if not records:
                    continue
                succeeded = sum(1 for r in records if r.get("succeeded"))
                elapsed = [
                    float(r.get("elapsed_seconds") or 0.0) for r in records
                ]
                stats[f"{model}/{experiment}_{blind}"] = {
                    "records": len(records),
                    "succeeded": succeeded,
                    "failed": len(records) - succeeded,
                    "mean_elapsed": sum(elapsed) / len(elapsed),
                    "torn": torn,
                }
    return stats


def collect_records(root: Path, models: list[str]) -> dict[str, list[dict]]:
    """Every kept record of a finished run, grouped per model (preflight)."""
    grouped: dict[str, list[dict]] = {model: [] for model in models}
    for model in models:
        for experiment in experiments.EXPERIMENTS:
            for blind in config.BLINDINGS:
                directory = legexec.leg_dir(root, model, experiment, blind)
                records, _torn = scan_leg_jsonl(directory / "records.jsonl")
                grouped[model].extend(records)
    return grouped


def finalize_manifest(root: Path, mode: str, models: list[str]) -> None:
    """Merge the per-leg stats into the run manifest at the run's end."""
    path = root / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["legs"] = leg_stats(root, models)
    payload["finished"] = _now()
    write_atomic_json(path, payload)


def refuse_started(root: Path) -> None:
    """--no-resume guard: refuse to append to a run that already has data."""
    for path in root.glob("**/records.jsonl"):
        if path.stat().st_size > 0:
            raise SystemExit(
                f"error: --no-resume refuses to append to existing records "
                f"({path}); use --resume or a fresh --run-dir"
            )


def new_progress(total: int) -> dict:
    """A fresh progress state (records_done / per-model counters)."""
    return {"records_done": 0, "records_total": total, "per_model": {}}


def progress_path(root: Path, mode: str) -> Path:
    """The run's progress file: always <run_dir>/progress.json, both modes."""
    root = Path(root)
    return root / "progress.json" if mode == "full" else root.parent / "progress.json"


def write_progress(root: Path, progress: dict, mode: str) -> None:
    """The run's progress.json snapshot (atomic; the operator can tail it)."""
    payload = {
        "mode": mode,
        "records_done": progress["records_done"],
        "records_total": progress["records_total"],
        "per_model": progress["per_model"],
        "updated_at": _now(),
    }
    write_atomic_json(progress_path(root, mode), payload)


def note_record(root: Path, progress: dict, mode: str, model: str) -> None:
    """Count one finished record; rewrite progress.json at least every 50."""
    progress["records_done"] += 1
    progress["per_model"][model] = progress["per_model"].get(model, 0) + 1
    if progress["records_done"] % config.FSYNC_EVERY == 0:
        write_progress(root, progress, mode)


def run_model(model: str, root: Path, mode: str, personas: list[dict],
              ids: list[int], base_url: str, progress: dict) -> None:
    """One model's 12-leg block; full mode skips preflight-finished cells."""
    context = legexec.make_leg_context(model, base_url, personas)
    transport = legexec.make_transport(
        context,
        lambda record: note_record(root, progress, mode, model),
    )
    for experiment in experiments.EXPERIMENTS:
        for blind in config.BLINDINGS:
            planned = legexec.leg_cells(model, ids, experiment, blind)
            # Full mode must also skip cells the preflight leg already
            # finished (spec §10: never duplicate a completed record).
            preflight_keys: set[tuple] = set()
            if mode == "full":
                preflight_keys = cells.load_existing_keys(legexec.leg_dir(
                    Path(root) / PREFLIGHT_DIRNAME, model, experiment, blind,
                ) / "records.jsonl")
            preflight_skipped = len(planned)
            planned = [cell for cell in planned
                       if cells.record_key(cell) not in preflight_keys]
            preflight_skipped -= len(planned)
            directory = legexec.leg_dir(root, model, experiment, blind)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "records.jsonl"
            durable, _parsed = durable_cells(path)  # repairs a torn tail
            if durable:
                log(f"  leg {experiment}_{blind}: {durable} records durable")
            cells.run_cells(planned, transport, path)
            extra = (f"; {preflight_skipped} skipped from preflight"
                     if preflight_skipped else "")
            log(f"  leg {experiment}_{blind}: "
                f"{len(planned) + preflight_skipped} cells planned "
                f"({durable} were already durable{extra})")


def ensure_model_loaded(manager_url: str, base_url: str, model: str,
                        port: int) -> None:
    """Load one model through the manager and wait until it answers.

    The manager is asked first: if it already reports this model on the
    port we only double-check that the server really answers. Otherwise
    we load FIRST (the port may be dark after an unload) and poll the
    health endpoint afterwards, for up to ten minutes, instead of
    failing just because nothing listens yet.
    """
    import urllib.request

    from launch_support import _load_model, _manager_status
    model_id = registry.manager_model_id(model)
    try:
        loaded = (_manager_status(manager_url).get(str(port)) or {}).get("model")
    except OSError as exc:
        raise RuntimeError(
            f"cannot reach model manager {manager_url}: {exc}"
        ) from exc
    if loaded == model_id:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=10.0) as reply:
                if reply.status == 200:
                    log(f"model {model} already loaded and healthy on :{port}")
                    return
        except OSError:
            log(f"manager says {model} is loaded but :{port} is not answering; reloading")
    log(f"loading {model} ({model_id}) on :{port} via the manager...")
    _load_model(manager_url, model_id, port)
    started = time.monotonic()
    deadline = started + 600.0
    poll = 0
    while time.monotonic() < deadline:
        poll += 1
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=10.0) as reply:
                if reply.status == 200:
                    log(f"model {model} healthy on :{port}")
                    return
        except OSError:
            pass
        if poll % 5 == 0:
            elapsed = time.monotonic() - started
            log(f"waiting for {model} on :{port} ({elapsed:.0f}s)")
        time.sleep(3.0)
    raise RuntimeError(f"model {model} not healthy on :{port} within 600s of load")


def unload_model(manager_url: str, port: int, model: str) -> None:
    """Release one finished model's GPU slot through the manager."""
    from launch_support import _unload_model
    _unload_model(manager_url, port)
    log(f"unloaded {model} from :{port}")


def run_all(args: argparse.Namespace) -> int:
    """The non-dry-run flow: pool, manifest, model loop, finalize/report."""
    root = mode_root(args.run_dir, args.mode)
    root.mkdir(parents=True, exist_ok=True)
    models = resolve_models(args.models)
    if not args.resume:
        refuse_started(root)
    skipped = skip_set(args.run_dir)
    if skipped & set(models):
        log(f"preflight STOP list active — skipping models: {sorted(skipped & set(models))}")
        models = [model for model in models if model not in skipped]
    ids = persona_ids_for(args.mode)
    write_start_manifest(root, args.mode, models, args.run_dir)
    progress = new_progress(len(models) * records_per_model(args.mode))
    write_progress(root, progress, args.mode)
    personas = ensure_pool(args.run_dir, args.manager_url, args.base_url)
    log(f"pool ready: {len(personas)} personas (ids 0-{len(personas) - 1})")
    for model in models:
        log(f"=== model {model} ({registry.manager_model_id(model)}) ===")
        ensure_model_loaded(args.manager_url, args.base_url, model, args.port)
        run_model(model, root, args.mode, personas, ids, args.base_url, progress)
        unload_model(args.manager_url, args.port, model)
    write_progress(root, progress, args.mode)
    finalize_manifest(root, args.mode, models)
    log(f"run complete: {progress['records_done']} records in {root}")
    if args.mode == "preflight":
        header = {"run_dir": str(args.run_dir), "records": progress["records_done"]}
        outcome = preflight.write_outputs(root, collect_records(root, models),
                                          personas, header)
        log(f"preflight report written; STOP-flagged: {outcome['stopped'] or 'none'}")
    return 0


def check_prompt_pair(system: str, user: str, spec, stimulus: dict) -> None:
    """One rendered prompt pair's exactness checks (raises SystemExit)."""
    if not system or not user:
        raise SystemExit(f"error: empty prompt for {spec.name}")
    if stimulus["question_text"] not in user:
        raise SystemExit(
            f"error: exact stimulus wording missing for {spec.name}/{spec.arms[0][0]}"
        )
    missing = [
        letter for letter, text in legexec.label_map(spec, stimulus).items()
        if f"{letter}. {text}" not in user
    ]
    if missing:
        raise SystemExit(
            f"error: option lines missing for letters {missing} in {spec.name}"
        )


def dry_run(models: list[str]) -> int:
    """The offline rehearsal: cell counts + persona-0 prompt exactness.

    Renders every (experiment, arm, blinding) prompt pair for persona 0
    with a clearly-synthetic placeholder persona, checks the exact Twin2K
    stimulus wording and every lettered option line, prints the per-model
    cell counts, and writes nothing anywhere.
    """
    stimuli = experiments.load_stimuli()
    total = len(cells.enumerate_cells())
    log(f"dry run: {len(models)} models × {records_per_model('full')} = {total} cells total")
    for model in models:
        count = len(cells.enumerate_cells(models=[model]))
        log(f"dry run: model {model}: {count} cells")
    checked = 0
    for experiment, spec in experiments.EXPERIMENTS.items():
        for arm, _qid in spec.arms:
            for blinded in (True, False):
                system = prompts.build_system_prompt(experiment, blinded)
                user = prompts.build_user_prompt(PLACEHOLDER_PERSONA, experiment, arm)
                check_prompt_pair(system, user, spec, stimuli[dict(spec.arms)[arm]])
                checked += 1
    log(f"dry run: {checked} prompt pairs checked — exact stimuli and "
        f"option lines present in all")
    sample = experiments.stimulus_for("disease", "gain", stimuli)
    log(f"dry run: sample stimulus prefix: {sample['question_text'][:60]!r}...")
    return 0


def main(argv: list[str] | None = None) -> int:
    """The CLI entry point (module execution starts here)."""
    args = parse_args(argv)
    models = resolve_models(args.models)
    if args.dry_run:
        return dry_run(models)
    return run_all(args)


if __name__ == "__main__":
    sys.exit(main())
