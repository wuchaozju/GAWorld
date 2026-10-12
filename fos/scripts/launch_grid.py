#!/usr/bin/env python3
"""Launch the Gui & Toubia replication sweep with one command (pre-flight).

The entry point of the study's launch wrapper. It parses the flags, counts
every call the run will make (persona-pool draws + the sweep legs), prints
the plan in --dry-run, runs the <=4-call pre-flight in --smoke, and in a
real run loads the model through the manager, builds the persona pools,
then runs the (depth x blinding) sweep legs concurrently. All the machinery
it drives lives in sibling modules: launch_support.py (model manager +
persona pools), launch_sweep.py (sweep legs, watchdog, smoke),
launch_cells.py (per-cell durable record writes + progress.json) and
launch_manifest.py (run-level manifest + resume merge). All wrap the
study's existing tools (scripts/generate_personas.py and
scripts/unblinding_sweep.py) without changing what either tool does.

Cell-granular durability (TASK-1533): a leg's records are appended and
flushed per completed cell, so the leg's own jsonl is its resume state -
on --resume a leg counts its durable cells and executes only the missing
ones. The run-level progress.json reports cells done/total per leg while
legs run.

Profiles (from the measured pilot numbers in RESULT-1501):
    R1   (default) - K=100 personas/product, depths none+demographics,
                     40 products, 11 price levels, draws 50.
    FULL           - K=500 (the paper's n). Prints the measured full-grid
                     figure (pilot ~41-45 h for the 880k-call grid) and
                     only fires with --i-know-this-is-41h.
`--stages` names the Appendix E tiers stage2..stage12; those stages are not
wired into the product-sweep pipeline yet and refuse cleanly (their pools
come from the Twin-2K-500 panel, their renderer is not plumbed into the
sweep kit). They are reserved for later stage-sensitivity runs.

Function map: main (dispatch) -> _run (real launch) with helpers
_pending_legs, _launch_legs and _finalize_stopped (operator stop handling);
plan/ETA helpers _plan, _legs_from_depths, _eta_estimates, _build_run_name,
_print_dry_run, _print_eta_block; flag handling _parse_args, _usage_error,
_settings_from; utilities _start_thread and _make_log.
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from launch_support import (  # noqa: E402
    BASE_DEPTHS,
    BLINDINGS,
    DEFAULT_LEVELS,
    DEFAULT_MANAGER,
    DEFAULT_MODEL,
    PILOT_BATCH_SPEEDUP,
    PILOT_POOL_DRAW_SECONDS,
    PILOT_PERSONA_SWEEP_SECONDS,
    PILOT_SWEEP_SECONDS,
    PROFILES,
    STAGE_DEPTHS,
    Settings,
    _ensure_model,
    _load_pool_personas,
    _load_products,
    _pool_phase,
    _repo_sha,
    _resolve_products,
    _safe_model_name,
)
from launch_manifest import (  # noqa: E402
    _load_run_manifest,
    _run_dir_has_state,
    _write_run_manifest,
)
from launch_sweep import (  # noqa: E402
    _leg_dir,
    _leg_is_done,
    _make_chat,
    _progress_line,
    _run_one_leg,
    _smoke,
    _watchdog,
)
from launch_cells import RunProgress, durable_cells, leg_jsonl  # noqa: E402
from launch_stop import (  # noqa: E402
    StopFlag,
    _drive_legs,
    install_stop_handlers,
    restore_stop_handlers,
)
from launch_5model import (  # noqa: E402
    DEFAULT_POOLS_FROM,
    QUEUE_GRAMMAR,
    QUEUE_PROFILE,
    build_queue_plan,
    print_queue_dry_run,
    run_queue,
)
from launch_queue import (  # noqa: E402
    LOGP_PROFILE,
    YESNO_PROFILE,
    build_logprob_plan,
)
from launch_yesno_qwenext import (  # noqa: E402
    QWENEXT_GEMMA31B_MODEL_QUEUE,
    QWENEXT_GEMMA31B_PROFILE,
    QWENEXT_GLM_MODEL_QUEUE,
    QWENEXT_GLM_PROFILE,
    QWENEXT_MODEL_QUEUE,
    QWENEXT_NEWBATCH_MODEL_QUEUE,
    QWENEXT_NEWBATCH_PROFILE,
    QWENEXT_PROFILE,
    QWENEXT_QWEN36D_MODEL_QUEUE,
    QWENEXT_QWEN36D_PROFILE,
    build_qwenext_plan,
    print_qwenext_dry_run,
)

DEFAULT_PRODUCTS = "data/configs/unblinding_products.json"
DEFAULT_OUT = "results/unblinding"
DEFAULT_OVERDRAW = 1.2
PROGRESS_EVERY = 1000


def _make_log() -> Callable[[str], None]:
    """A timestamped console logger that flushes every line."""

    def _write(text: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    return _write


log = _make_log()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command-line flags into one settings object."""
    parser = argparse.ArgumentParser(
        prog="launch_grid",
        description=(
            "Launch the Gui & Toubia replication sweep (persona pools + "
            "price sweep) with one command; smoke and dry-run modes for "
            "pre-flight."
        ),
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="R1")
    parser.add_argument(
        "--k",
        type=int,
        default=None,
        help="personas per product (default R1=100, FULL=500)",
    )
    parser.add_argument(
        "--draws", type=int, default=50, help="plain-sweep draws per product and level"
    )
    parser.add_argument("--levels", default=DEFAULT_LEVELS)
    parser.add_argument("--products", default=DEFAULT_PRODUCTS)
    parser.add_argument("--pool-seed", type=int, default=42)
    parser.add_argument("--pool-overdraw", type=float, default=DEFAULT_OVERDRAW)
    parser.add_argument(
        "--stages",
        default="",
        help="comma list of Appendix "
        "E stage depths (stage2..stage12); reserved for "
        "later stage-sensitivity runs",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--port", type=int, default=8080, choices=(8080, 8082))
    parser.add_argument("--manager-url", default=DEFAULT_MANAGER)
    parser.add_argument(
        "--base-url",
        default="",
        help="chat server base url (default http://127.0.0.1:<port>)",
    )
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--run-name", default="")
    parser.add_argument("--seed", type=int, default=42, help="sweep design seed")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="make the FIRST stop signal an immediate hard stop instead of a "
        "graceful one (skip the graceful finish; the second signal always "
        "hard-stops)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--logprob-mode",
        choices=("first_token", "candidate_scoring"),
        default="candidate_scoring",
        help="R1LP logprob scoring: candidate_scoring (default, two "
        "teacher-forced calls per prompt) or first_token (one call per "
        "prompt)",
    )
    parser.add_argument(
        "--ab-labels",
        action="store_true",
        help="R1LP A/B label-order reversal: plan every cell with BOTH "
        "label orders (purchase|not purchase and the reversal) and "
        "aggregate the two p(buy) values by their mean (doubles the "
        "scoring calls)",
    )
    parser.add_argument("--i-know-this-is-41h", action="store_true")
    parser.add_argument(
        "--pools-from",
        default=DEFAULT_POOLS_FROM,
        help="persona-pool directory to reuse for the R1-5MODEL queue "
        "(default: the archived R1 run's pools; when the path is absent "
        "the queue regenerates a deterministic pool-seed-42 pool)",
    )
    parser.add_argument("--progress-every", type=int, default=PROGRESS_EVERY)
    return parser.parse_args(argv)


def _usage_error(message: str) -> None:
    """Print a usage error to stderr and exit with code 2."""
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _depths_for(stages_spec: str) -> list[str]:
    """The depth ladder to run; stage tiers refuse with the reason."""
    stages = [piece.strip() for piece in stages_spec.split(",") if piece.strip()]
    for stage in stages:
        if stage not in STAGE_DEPTHS:
            _usage_error(
                f"error: unknown stage depth {stage!r} (choose "
                f"from {', '.join(STAGE_DEPTHS)})"
            )
    if stages:
        _usage_error(
            "error: stage depths are not runnable yet: their pools come from "
            "the Appendix E Twin-2K-500 panel and their renderer is not "
            "plumbed into unblinding_sweep. Tonight's launch is depths "
            "none+demographics; --stages is reserved for the later "
            "stage-sensitivity pipeline."
        )
    return list(BASE_DEPTHS)


def _legs_from_depths(
    depths: list[str],
    product_count: int,
    level_count: int,
    k: int,
    draws: int,
) -> list[dict[str, Any]]:
    """The (depth x blinding) legs of the run with their call counts."""
    legs: list[dict[str, Any]] = []
    for depth in depths:
        per_blinding = (
            product_count * level_count * draws
            if depth == "none"
            else product_count * k * level_count
        )
        for blinding in BLINDINGS:
            legs.append({"depth": depth, "blinding": blinding, "calls": per_blinding})
    return legs


def _eta_estimates(plain_calls: int, persona_calls: int) -> tuple[float, float]:
    """Batched sweep hours (low/high) from the measured pilot latencies."""
    low = (
        (plain_calls + persona_calls)
        * PILOT_SWEEP_SECONDS
        / PILOT_BATCH_SPEEDUP
        / 3600.0
    )
    high = (
        (
            plain_calls * PILOT_SWEEP_SECONDS
            + persona_calls * PILOT_PERSONA_SWEEP_SECONDS
        )
        / PILOT_BATCH_SPEEDUP
        / 3600.0
    )
    return low, high


def _plan(args: argparse.Namespace, products: list[dict[str, Any]]) -> dict[str, Any]:
    """Count every call the run will make and estimate its wall time.

    Plain (none) legs draw once per product x level x draw; persona legs
    draw once per product x persona x level at temperature 0. Pool draws
    are the persona requests generate_personas makes (overdrawn). ETA uses
    the measured pilot latencies and pool-draw estimate (see
    _eta_estimates).
    """
    k = PROFILES[args.profile] if args.k is None else args.k
    levels = [float(p) for p in args.levels.split(",") if p.strip()]
    if not levels:
        _usage_error("error: no price levels parsed from --levels")
    depths = _depths_for(args.stages)
    legs = _legs_from_depths(depths, len(products), len(levels), k, args.draws)
    sweep_calls = sum(leg["calls"] for leg in legs)
    plain = sum(leg["calls"] for leg in legs if leg["depth"] == "none")
    pool_draws = (
        len(products) * math.ceil(k * args.pool_overdraw)
        if any(depth != "none" for depth in depths)
        else 0
    )
    return {
        "profile": args.profile,
        "k": k,
        "levels": levels,
        "depths": depths,
        "legs": legs,
        "sweep_calls": sweep_calls,
        "pool_draws": pool_draws,
        "sweep_hours": _eta_estimates(plain, sweep_calls - plain),
        "pools_hours": pool_draws * PILOT_POOL_DRAW_SECONDS / 3600.0,
        "sequential_hours": sweep_calls * PILOT_SWEEP_SECONDS / 3600.0,
    }


def _build_run_name(args: argparse.Namespace) -> str:
    """Default run name: profile, model stem and local time.

    The R1-5MODEL queue has no single model to name itself after, so its
    default run name is just the profile and the local time (the logprob
    twins and the QWENEXT queues, 3-model and the one-model companions
    alike, follow the same pattern).
    """
    if args.run_name:
        return args.run_name
    if args.profile in (
        QUEUE_PROFILE,
        LOGP_PROFILE,
        YESNO_PROFILE,
        QWENEXT_PROFILE,
        QWENEXT_GLM_PROFILE,
        QWENEXT_QWEN36D_PROFILE,
        QWENEXT_GEMMA31B_PROFILE,
        QWENEXT_NEWBATCH_PROFILE,
    ):
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        return f"{args.profile}-{stamp}"
    stem = _safe_model_name(args.model).replace("nvidia_", "")
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{args.profile}-{stem}-{stamp}"


def _print_eta_block(plan: dict[str, Any], leg_count: int) -> None:
    """Print the ETA section of the dry run."""
    print("  ETA from measured pilot latencies (RESULT-1501)")
    print(
        f"    pools       ~{plan['pools_hours']:.1f} h sequential "
        f"(~{PILOT_POOL_DRAW_SECONDS:g} s/draw)"
    )
    print(
        f"    sweep       ~{plan['sweep_hours'][0]:.1f} - "
        f"{plan['sweep_hours'][1]:.1f} h with {leg_count} legs concurrent "
        f"(measured ~{PILOT_BATCH_SPEEDUP:g}x on 4 slots)"
    )
    print(
        f"    total       ~{plan['pools_hours'] + plan['sweep_hours'][0]:.1f} - "
        f"{plan['pools_hours'] + plan['sweep_hours'][1]:.1f} h "
        f"(sequential single slot: ~{plan['sequential_hours']:.1f} h)"
    )


def _print_dry_run(
    args: argparse.Namespace,
    products: list[dict[str, Any]],
    plan: dict[str, Any],
) -> None:
    """Show the full plan and its ETA, then exit."""
    base = args.base_url or f"http://127.0.0.1:{args.port}"
    run_name = _build_run_name(args)
    print(f"{args.profile} launch plan (dry run)")
    print(f"  model        {args.model} on {base} (manager {args.manager_url})")
    print(f"  products     {len(products)} from {_resolve_products(args.products)}")
    print(f"  depths       {', '.join(plan['depths'])} x {', '.join(BLINDINGS)}")
    print(
        f"  K            {plan['k']} personas/product (pool-seed "
        f"{args.pool_seed}, overdraw {args.pool_overdraw})"
    )
    print("  legs")
    for leg in plan["legs"]:
        kind = "plain" if leg["depth"] == "none" else f"personas K={plan['k']}"
        print(
            f"    {leg['depth']}_{leg['blinding']:<16} {kind:<16} "
            f"{leg['calls']:,} calls"
        )
    print(
        f"  sweep calls  {plan['sweep_calls']:,} total; pool draws ~"
        f"{plan['pool_draws']:,}"
    )
    _print_eta_block(plan, len(plan["legs"]))
    print(
        f"  outputs      {Path(args.out) / run_name}/  (manifest.json, "
        f"pools/, one directory per leg)"
    )
    if args.profile == "FULL":
        print(
            "  FULL note   K=500 is the paper's n; the pilot's measured "
            "full-grid figure is"
        )
        print(
            "              ~41-45 h for the 880,000-call grid at 4-slot "
            "batching. Running FULL"
        )
        print("              requires --i-know-this-is-41h.")


def _settings_from(args: argparse.Namespace, run_name: str) -> Settings:
    """Map parsed flags onto the support module's settings object.

    The R1-5MODEL queue stamps its one-token grammar on the settings so
    every purchase call of every model is constrained the same way. R1LP is
    the opposite: it sets logprob_mode and leaves the grammar None (no
    constrained decoding). R1-YESNO is the yes/no twin of R1LP: it pins
    first_token logprobs, no grammar at all, and stamps the response words
    (response_format="yes/no") that feed both the prompt and the scorer.
    R1-YESNO-QWENEXT mirrors R1-YESNO exactly (first_token, yes/no words,
    no grammar) - only its model queue and shared persona slice differ.
    R1-YESNO-QWENEXT-GLM is that same yes/no shape again for the one-model
    GLM companion run, R1-YESNO-QWEN36D for the one-model local dense
    Qwen3.6-27B companion, R1-YESNO-GEMMA31B for the one-model local
    Gemma-4-31B companion, and R1-YESNO-NEWBATCH for the four-model local
    batch of brand-new GGUFs.
    """
    is_logprob = args.profile in (
        LOGP_PROFILE,
        YESNO_PROFILE,
        QWENEXT_PROFILE,
        QWENEXT_GLM_PROFILE,
        QWENEXT_QWEN36D_PROFILE,
        QWENEXT_GEMMA31B_PROFILE,
        QWENEXT_NEWBATCH_PROFILE,
    )
    is_yesno = args.profile in (
        YESNO_PROFILE,
        QWENEXT_PROFILE,
        QWENEXT_GLM_PROFILE,
        QWENEXT_QWEN36D_PROFILE,
        QWENEXT_GEMMA31B_PROFILE,
        QWENEXT_NEWBATCH_PROFILE,
    )
    return Settings(
        model=args.model,
        port=args.port,
        manager_url=args.manager_url,
        base_url=args.base_url or f"http://127.0.0.1:{args.port}",
        out=Path(args.out),
        run_name=run_name,
        pool_seed=args.pool_seed,
        pool_overdraw=args.pool_overdraw,
        seed=args.seed,
        draws=args.draws,
        progress_every=args.progress_every,
        products_path=args.products,
        grammar=QUEUE_GRAMMAR if args.profile == QUEUE_PROFILE else None,
        logprob_mode=(
            "first_token" if is_yesno else args.logprob_mode if is_logprob else None
        ),
        response_format="yes/no" if is_yesno else None,
    )


def _start_thread(target: Any, args: tuple) -> threading.Thread:
    """Start one daemon thread running target(*args) and return it."""
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse flags, then smoke, dry-run, or the full run.

    Real runs install SIGINT/SIGTERM handlers that ask the shared stop flag
    for a graceful stop (first signal) or a hard stop (second signal; or
    --force makes even the first one hard). Handlers are restored before
    returning so in-process callers are not left with changed handlers.
    """
    args = _parse_args(argv)
    products_path = _resolve_products(args.products)
    if args.profile in (
        QUEUE_PROFILE,
        LOGP_PROFILE,
        YESNO_PROFILE,
        QWENEXT_PROFILE,
        QWENEXT_GLM_PROFILE,
        QWENEXT_QWEN36D_PROFILE,
        QWENEXT_GEMMA31B_PROFILE,
        QWENEXT_NEWBATCH_PROFILE,
    ):
        # The five-model queue (R1-5MODEL) and its logprob twins (R1LP,
        # R1-YESNO): five models in one invocation, stratified allocation;
        # R1-5MODEL constrains every call with the one-token grammar, R1LP
        # and R1-YESNO score logprobs instead (no grammar). R1-YESNO-QWENEXT
        # is the three-Qwen-model queue that re-runs the R1-YESNO
        # experiment on the shared qwen3.8-27b persona slice,
        # R1-YESNO-QWENEXT-GLM is its one-model GLM companion (identical
        # geometry, its own run dir), R1-YESNO-QWEN36D is its one-model
        # local dense Qwen3.6-27B companion (identical geometry, own dir),
        # R1-YESNO-GEMMA31B is its one-model local Gemma-4-31B
        # companion (identical geometry, own dir), and
        # R1-YESNO-NEWBATCH is its four-model local batch of brand-new
        # GGUFs (identical geometry, own dir).
        if args.smoke:
            print(
                f"error: --smoke is not wired for the {args.profile} queue "
                "yet; smoke the models individually with the R1 profile first",
                file=sys.stderr,
            )
            return 2
        if (
            args.profile in (
                YESNO_PROFILE,
                QWENEXT_PROFILE,
                QWENEXT_GLM_PROFILE,
                QWENEXT_QWEN36D_PROFILE,
                QWENEXT_GEMMA31B_PROFILE,
                QWENEXT_NEWBATCH_PROFILE,
            )
            and args.ab_labels
        ):
            print(
                f"error: --ab-labels has no A/B form for the {args.profile} "
                "profile (first_token scoring, like R1LP's)",
                file=sys.stderr,
            )
            return 2
        products = _load_products(products_path)
        if not products:
            print("error: the products file lists no products", file=sys.stderr)
            return 2
        levels = [float(piece) for piece in args.levels.split(",") if piece.strip()]
        if not levels:
            _usage_error("error: no price levels parsed from --levels")
        if args.profile in (LOGP_PROFILE, YESNO_PROFILE):
            plan = build_logprob_plan(
                len(products),
                len(levels),
                levels=levels,
                ab_orders=args.ab_labels,
                profile=YESNO_PROFILE
                if args.profile == YESNO_PROFILE
                else LOGP_PROFILE,
            )
            logprob_mode = (
                "first_token" if args.profile == YESNO_PROFILE else args.logprob_mode
            )
        elif args.profile in (
            QWENEXT_PROFILE,
            QWENEXT_GLM_PROFILE,
            QWENEXT_QWEN36D_PROFILE,
            QWENEXT_GEMMA31B_PROFILE,
            QWENEXT_NEWBATCH_PROFILE,
        ):
            if args.profile == QWENEXT_GLM_PROFILE:
                queue = QWENEXT_GLM_MODEL_QUEUE
            elif args.profile == QWENEXT_QWEN36D_PROFILE:
                queue = QWENEXT_QWEN36D_MODEL_QUEUE
            elif args.profile == QWENEXT_GEMMA31B_PROFILE:
                queue = QWENEXT_GEMMA31B_MODEL_QUEUE
            elif args.profile == QWENEXT_NEWBATCH_PROFILE:
                queue = QWENEXT_NEWBATCH_MODEL_QUEUE
            else:
                queue = QWENEXT_MODEL_QUEUE
            plan = build_qwenext_plan(
                len(products),
                len(levels),
                levels=levels,
                profile=args.profile,
                model_queue=queue,
            )
            logprob_mode = "first_token"
        else:
            plan = build_queue_plan(len(products), len(levels), levels=levels)
            logprob_mode = None
        if args.dry_run:
            run_name = _build_run_name(args)
            run_dir = Path(args.out) / run_name
            if args.profile in (
                QWENEXT_PROFILE,
                QWENEXT_GLM_PROFILE,
                QWENEXT_QWEN36D_PROFILE,
                QWENEXT_GEMMA31B_PROFILE,
                QWENEXT_NEWBATCH_PROFILE,
            ):
                print_qwenext_dry_run(args, products, plan, run_dir)
                return 0
            dry_scan = (
                _settings_from(args, run_name).scan_tokens if logprob_mode else None
            )
            print_queue_dry_run(
                args,
                products,
                plan,
                run_dir,
                logprob_mode=logprob_mode,
                scan_tokens=dry_scan,
            )
            return 0
        stop = StopFlag(force_first=args.force)
        previous = install_stop_handlers(stop)
        try:
            return run_queue(
                args,
                plan,
                products,
                products_path,
                _settings_from(args, _build_run_name(args)),
                stop=stop,
            )
        finally:
            restore_stop_handlers(previous)
    if args.smoke:
        return _smoke(
            _settings_from(args, args.run_name), products_path, Path(args.out)
        )
    if args.profile == "FULL" and not args.i_know_this_is_41h and not args.dry_run:
        print(
            "error: profile FULL is the paper-scale run (measured ~41-45 h "
            "for the 880k-call grid at 4-slot batching); pass "
            "--i-know-this-is-41h to fire it",
            file=sys.stderr,
        )
        return 2
    products = _load_products(products_path)
    if not products:
        print("error: the products file lists no products", file=sys.stderr)
        return 2
    plan = _plan(args, products)
    if args.dry_run:
        _print_dry_run(args, products, plan)
        return 0
    stop = StopFlag(force_first=args.force)
    previous = install_stop_handlers(stop)
    try:
        return _run(
            args,
            plan,
            products,
            products_path,
            _settings_from(args, _build_run_name(args)),
            stop=stop,
        )
    finally:
        restore_stop_handlers(previous)


def _run(
    args: argparse.Namespace,
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    products_path: Path,
    settings: Settings,
    stop: StopFlag | None = None,
) -> int:
    """Run the real launch: model load, pools, concurrent legs, manifest.

    The run-level manifest doubles as the started marker: the first
    invocation writes it (state "running", no legs yet) as soon as the run
    begins, so an interrupted run is recognised by the guard and its true
    start time survives; a --resume invocation finishes with a final
    manifest (state "complete") that merges its legs with the earlier
    invocations' finished legs - read from the leg files - so every planned
    leg appears exactly once (see launch_manifest).

    The shared stop flag (SIGINT/SIGTERM, or the tests' stop object) is
    honoured between phases and during the legs: a graceful stop before any
    leg starts writes a stopped_gracefully manifest with no work done; a
    graceful stop while legs run stops each leg at its next cell boundary
    (every completed cell is already durable on disk - cell-granular
    checkpointing, TASK-1533 - so a later --resume executes only the
    missing cells); a hard stop (second signal or --force) aborts in-flight
    legs the same way. The run-level progress.json is written while legs
    run.
    """
    if stop is None:
        stop = StopFlag(force_first=getattr(args, "force", False))
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
    run_dir.mkdir(parents=True, exist_ok=True)
    started_wall = time.monotonic()
    started = datetime.now().astimezone().isoformat()
    log(f"run {settings.run_name} starting (commit {_repo_sha() or 'unknown'})")
    k = plan["k"]
    safe_model = _safe_model_name(settings.model)
    targets = [
        {"depth": leg["depth"], "blinding": leg["blinding"]} for leg in plan["legs"]
    ]
    pending = _pending_legs(args, run_dir, safe_model, targets)
    if prior is not None:
        log(f"resume: continuing a run started {prior.get('started') or '?'}")
    if len(pending) < len(targets):
        log(
            f"resume: {len(targets) - len(pending)}/{len(targets)} legs "
            f"already complete - skipping"
        )
    if not pending:
        log("nothing to run (all legs complete)")
        _write_run_manifest(
            settings,
            plan,
            products_path,
            run_dir,
            started,
            datetime.now().astimezone().isoformat(),
            [],
            None,
            targets=targets,
            safe_model=safe_model,
            prior=prior,
            resume_invocation=prior is not None,
            state="complete",
        )
        return 0
    # A stop that arrived before any model/pool/leg work: record it and stop.
    if stop.level() != "running":
        log(
            f"{stop.level()} stop requested before the sweep started - "
            "writing the stopped manifest and exiting cleanly"
        )
        return _finalize_stopped(
            stop,
            settings,
            plan,
            products_path,
            run_dir,
            started,
            targets,
            safe_model,
            prior,
            [],
            None,
        )
    if prior is None:
        _write_run_manifest(
            settings,
            plan,
            products_path,
            run_dir,
            started,
            started,
            [],
            None,
            targets=targets,
            safe_model=safe_model,
            prior=None,
            resume_invocation=False,
            state="running",
        )
        log(f"run marked started: {run_dir / 'manifest.json'}")
    _ensure_model(settings, log)
    if stop.level() != "running":  # stop requested during the model load
        return _finalize_stopped(
            stop,
            settings,
            plan,
            products_path,
            run_dir,
            started,
            targets,
            safe_model,
            prior,
            [],
            None,
        )
    pool_summary = None
    personas_by_product = None
    if any(leg["depth"] != "none" for leg in pending):
        pool_summary = _pool_phase(settings, products, products_path, run_dir, k, log)
        if stop.level() != "running":  # stop requested during pool generation
            return _finalize_stopped(
                stop,
                settings,
                plan,
                products_path,
                run_dir,
                started,
                targets,
                safe_model,
                prior,
                [],
                pool_summary,
            )
        personas_by_product = _load_pool_personas(run_dir, products, k)
        if not personas_by_product:
            print(
                f"error: no pool files matched any product under {run_dir / 'pools'!r}",
                file=sys.stderr,
            )
            return 2
    results, level = _launch_legs(
        settings,
        plan,
        products,
        personas_by_product,
        run_dir,
        safe_model,
        pending,
        stop,
    )
    if level != "running":
        return _finalize_stopped(
            stop,
            settings,
            plan,
            products_path,
            run_dir,
            started,
            targets,
            safe_model,
            prior,
            results,
            pool_summary,
        )
    _write_run_manifest(
        settings,
        plan,
        products_path,
        run_dir,
        started,
        datetime.now().astimezone().isoformat(),
        results,
        pool_summary,
        targets=targets,
        safe_model=safe_model,
        prior=prior,
        resume_invocation=prior is not None,
        state="complete",
    )
    return _report_run(results, settings, run_dir, started_wall)


def _pending_legs(
    args: argparse.Namespace,
    run_dir: Path,
    safe_model: str,
    targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    """The legs still to run: all of them, or only the unfinished on resume."""
    if not args.resume:
        return targets
    return [leg for leg in targets if not _leg_is_done(run_dir, safe_model, leg)]


def _launch_legs(
    settings: Settings,
    plan: dict[str, Any],
    products: list[dict[str, Any]],
    personas_by_product: dict[str, Any] | None,
    run_dir: Path,
    safe_model: str,
    pending: list[dict[str, str]],
    stop: StopFlag,
) -> tuple[list[dict[str, Any]], str]:
    """Start the pending legs concurrently and wait for every one of them.

    Runs under the shared stop flag: a graceful stop lets every in-flight
    leg pause at its next cell boundary (cell-granular durability, TASK-
    1533: every completed cell is already on disk, so nothing is lost and a
    later --resume executes only the missing cells), a hard stop sets the
    chat abort so each leg stops immediately. The run's progress.json is
    written while the legs run (seeded with the cells already durable on
    disk when this is a resume) and finished when the sweep phase ends.
    Returns (results, final stop level) so the caller can choose the run
    manifest's final state.
    """
    planned_by_key = {
        (leg["depth"], leg["blinding"]): int(leg["calls"]) for leg in plan["legs"]
    }
    remaining_calls = 0
    for leg in pending:
        calls = planned_by_key.get((leg["depth"], leg["blinding"]), 0)
        jsonl = leg_jsonl(_leg_dir(run_dir, leg), safe_model, leg["blinding"])
        durable = durable_cells(jsonl)[0] if jsonl.exists() else 0
        remaining_calls += max(0, calls - durable)
    chat_fn, state, abort = _make_chat(
        settings,
        remaining_calls,
        lambda d, t, p, r: log(_progress_line(d, t, p, r)),
        stop=stop,
    )
    progress = RunProgress(run_dir, plan["legs"], log)
    # Seed every planned leg's done count so a resumed run's progress file
    # starts where the last invocation stopped. A fully-complete leg needs no
    # file scan (its done == planned); a pending leg's durable records file
    # is scanned (0 when the leg never started).
    for leg in plan["legs"]:
        key = f"{leg['depth']}_{leg['blinding']}"
        planned = int(leg.get("calls") or 0)
        if _leg_is_done(run_dir, safe_model, leg):
            progress.set_leg(key, done_at_start=planned)
        else:
            jsonl = leg_jsonl(_leg_dir(run_dir, leg), safe_model, leg["blinding"])
            durable = durable_cells(jsonl)[0] if jsonl.exists() else 0
            progress.set_leg(key, done_at_start=durable)
    done_event = threading.Event()
    _start_thread(_watchdog, (settings, abort, done_event, log))
    results: list[dict[str, Any]] = []
    log(
        f"launching {len(pending)} legs concurrently on {settings.base_url} "
        f"({remaining_calls:,} calls remaining)"
    )

    def start_one(leg: dict[str, Any]) -> threading.Thread:
        return _start_thread(
            _run_one_leg,
            (
                settings,
                plan,
                products,
                personas_by_product,
                run_dir,
                chat_fn,
                leg,
                results,
                log,
                progress,
            ),
        )

    level = _drive_legs(
        pending,
        stop,
        abort,
        log,
        start_one,
        planned_calls=remaining_calls,
        calls_done=lambda: state["done"],
    )
    done_event.set()
    log(
        f"finished: {state['done']:,} calls, "
        f"parse {100.0 * state['parsed'] / max(1, state['done']):.1f}%"
    )
    progress.finish()
    return results, level


def _finalize_stopped(
    stop: StopFlag,
    settings: Settings,
    plan: dict[str, Any],
    products_path: Path,
    run_dir: Path,
    started: str,
    targets: list[dict[str, str]],
    safe_model: str,
    prior: dict[str, Any] | None,
    results: list[dict[str, Any]],
    pool_summary: dict[str, Any] | None,
) -> int:
    """Write the final manifest for a stopped run and print the summary.

    A graceful stop records state "stopped_gracefully" (per-leg completion
    status merged like a completed run, so the operator sees exactly which
    legs finished); a hard stop records state "stopped". Either way a leg
    interrupted mid-run keeps every completed cell on disk (cell-granular
    checkpointing), so rerun with --resume to execute only the missing
    cells. Returns the exit code: 0 for a graceful stop, 1 for a hard stop.
    """
    level = stop.level()
    state = "stopped_gracefully" if level == "graceful" else "stopped"
    _write_run_manifest(
        settings,
        plan,
        products_path,
        run_dir,
        started,
        datetime.now().astimezone().isoformat(),
        results,
        pool_summary,
        targets=targets,
        safe_model=safe_model,
        prior=prior,
        resume_invocation=prior is not None,
        state=state,
    )
    if level == "graceful":
        log(
            f"run {settings.run_name} stopped gracefully "
            f"({len(results)} leg result(s) recorded); "
            "rerun with --resume --run-name "
            f"{settings.run_name} to finish any legs that did not complete"
        )
        return 0
    log(
        f"run {settings.run_name} hard-stopped; in-flight legs aborted at a "
        "cell boundary (completed cells are kept); rerun with --resume "
        f"--run-name {settings.run_name} to finish the remaining cells"
    )
    return 1


def _report_run(
    results: list[dict[str, Any]],
    settings: Settings,
    run_dir: Path,
    started_wall: float,
) -> int:
    """Print failures or the completion line and return the exit code."""
    failed = [r for r in results if not r.get("ok")]
    if failed:
        for result in failed:
            print(
                f"leg {result['depth']}_{result['blinding']} failed: "
                f"{result.get('error')}",
                file=sys.stderr,
            )
        print(
            f"run {settings.run_name} finished with {len(failed)} failed "
            f"leg(s); rerun with --resume --run-name {settings.run_name} "
            f"to retry them",
            file=sys.stderr,
        )
        return 1
    log(
        f"run {settings.run_name} complete in "
        f"{(time.monotonic() - started_wall) / 3600.0:.2f} h"
    )
    log(f"results: {run_dir}/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
