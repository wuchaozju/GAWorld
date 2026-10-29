"""The R1-5MODEL queue specification: models, stratified plan, resume state.

The R1 study design is normally one model per invocation (132,000 calls).
The R1-5MODEL queue splits those calls across five models back to back in
one invocation so each model answers a deterministic slice of the same
design: model i answers as pool personas [20i, 20i+20) of every product's
100-persona pool (demographics legs) and makes 10 plain draws per (product
x price level) (none legs). Every purchase call of every model runs under
the same one-token llama-server GBNF grammar. Per model: 2 x 40 x 11 x 10
= 8,800 none calls + 2 x 40 x 20 x 11 = 17,600 demographics calls = 26,400;
the five models together make 132,000 - the same total as the single-model
R1 run. This module is the pure specification of that queue: the model
order, the stratification numbers, the persona partition, the per-leg call
counts, where each leg lives on disk and how a --resume recognises a
completed (model, leg), plus the per-model first_token top-k config. It
opens no sockets and writes no files.

What each function does (plain language):
    persona_slice(index)           - The pool index range [20i, 20i+20) of
                                     model i.
    slice_persona_map(map, index)  - One model's persona share of the pool
                                     map (the shared pool is untouched).
    build_queue_plan(...)          - The queue plan: 20 legs, per-model and
                                     total call counts (26,400 x 5).
    plan_model_queue(plan)         - The plan's model queue in run order
                                     (the 5-model queue when absent).
    plan_persona_slice(plan, i)    - The plan-recorded persona slice of
                                     queue slot i (fallback: partition).
    queue_leg_dir / queue_leg_jsonl - Where one leg lives on disk.
    queue_leg_done(...)            - Is this (model, leg) already complete?
    model_top_k(model)             - The model's first_token top-k: its
                                     profile override, else the historical
                                     20 (never a scoring-code branch).
    pending_queue_targets(...)     - The legs --resume still has to run.
    _durable_calls(...)            - Cells of one leg durably on disk.
    _regular_prices(products)      - Product name -> regular price map.
    _resolve_pools_from(value)     - Resolve --pools-from (also from the
                                     repository root); None when absent.
    print_queue_dry_run(...)       - The printed 5-model plan (dry run).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = _REPO_ROOT / "scripts"
_SRC = _REPO_ROOT / "src"
for _dir in (_SCRIPT_DIR, _SRC):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from launch_cells import durable_cells  # noqa: E402
from launch_support import BASE_DEPTHS, BLINDINGS, _safe_model_name  # noqa: E402
from logprob_scoring import TOP_LOGPROBS  # noqa: E402

# The queue's run-level profile name and its fixed design numbers.
QUEUE_PROFILE = "R1-5MODEL"
# The logprob twin of the queue (TASK-1545): same five models and
# stratification, but ONE scoring pass per prompt and no grammar.
LOGP_PROFILE = "R1LP"
# The yes/no twin of R1LP (TASK-1563): identical one-pass geometry, but the
# survey's answer words are "yes"/"no" and the honest first-token
# probabilities are read without any grammar.
YESNO_PROFILE = "R1-YESNO"
LOGP_NONE_DRAWS = 1
# Manager registry ids, in the run order the user confirmed (RESULT-1536
# CHECK 5): the queue loads and runs them back to back, then unloads each.
MODEL_QUEUE = (
    "openai/gpt-oss-20b",
    "google/gemma-4-26b-a4b",
    "qwen/qwen3.8-27b",
    "nvidia/nemotron-cascade-2-30b-a3b",
    "meta/muse-glimmer",
)
# One-token GBNF grammar sent on EVERY purchase call of EVERY model and leg
# (llama-server "grammar" request field) - the same decoding path for all
# five models, both blindings and both depths.
QUEUE_GRAMMAR = 'root ::= "purchase" | "not purchase"'
# The shared persona pool holds 100 personas per product; model i answers
# the [20i, 20i+20) slice, so the five models cover the pool exactly.
POOL_PERSONAS_PER_PRODUCT = 100
PERSONAS_PER_MODEL = 20
# Plain (none) legs draw this many times per (product x level) per model;
# five models x 10 = the original R1 design's 50 draws.
NONE_LEG_DRAWS = 10
# A queue leg's durable records file (the resume state of the leg).
LEG_FILE = "records.jsonl"
# Per-model first_token top-k overrides (payload top_logprobs), resolved
# through model_top_k: the profile config lives HERE in the queue spec -
# never as a model-name branch inside the scoring code. A model absent
# from the map keeps the historical TOP_LOGPROBS coverage.
MODEL_TOP_K_OVERRIDES: dict[str, int] = {"meta/muse-glimmer": 100}
# Per-model first_token control-SEQUENCE overrides (whole exact token
# sequences consumed as one block, e.g. a fixed channel header),
# resolved through model_control_sequences: the profile config lives
# HERE in the queue spec - never as a model-name branch inside the
# scoring code. A model absent from the map keeps the default-off empty
# tuple (identity: byte-identical behavior for every unlisted model).
MODEL_CONTROL_SEQUENCES: dict[str, tuple[tuple[str, ...], ...]] = {
    "google/gemma-4-26b-a4b": (("<|channel>", "thought", "\n", "<channel|>"),),
}
# The archived R1 run's pools (40/40 products, seed 42) reused by default.
DEFAULT_POOLS_FROM = (
    "results/unblinding/R1-nemotron-cascade-2-30b-a3b-20260909T004614/pools"
)


def persona_slice(
    model_index: int, per_model: int = PERSONAS_PER_MODEL
) -> tuple[int, int]:
    """The pool index range [20i, 20i+20) that model i answers.

    Model i of the queue (0-based, in MODEL_QUEUE order) answers the
    personas at pool indices [20i, 20i+20) of every product's 100-persona
    pool. The five slices are disjoint, deterministic and cover the pool
    exactly; an index outside the queue raises instead of silently slicing
    empty.
    """
    if not 0 <= model_index < len(MODEL_QUEUE):
        raise ValueError(
            f"model_index {model_index} is outside the 5-model queue "
            f"(0..{len(MODEL_QUEUE) - 1})"
        )
    start = model_index * per_model
    return start, start + per_model


def slice_persona_map(
    personas_by_product: dict[str, dict[str, Any]],
    model_index: int,
    *,
    bounds: tuple[int, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """One model's deterministic persona share of the shared pool map.

    Returns a new map of the same shape with each product's persona list
    trimmed to the model's [20i, 20i+20) slice; the input map is never
    mutated (all five models read from the same 100-persona pool). bounds
    overrides the queue partition with a plan-recorded slice (the QWENEXT
    plans share one slice across their models); the default keeps the
    partition. A pool shorter than the slice raises - the run would
    silently drop cells otherwise, so we never guess.
    """
    start, stop = bounds if bounds is not None else persona_slice(model_index)
    sliced: dict[str, dict[str, Any]] = {}
    for product, info in personas_by_product.items():
        personas = info["personas"]
        if len(personas) < stop:
            raise RuntimeError(
                f"{product[:60]!r} pool holds only {len(personas)} personas "
                f"(model {model_index} needs indices up to {stop - 1})"
            )
        sliced[product] = {**info, "personas": personas[start:stop]}
    return sliced


def plan_model_queue(plan: dict[str, Any]) -> tuple[str, ...]:
    """The plan's model queue in run order (the 5-model queue by default).

    Every plan builder stamps its model order on plan["models"], so the
    runner reads the queue from the plan instead of assuming the 5-model
    queue: a plan with a different queue (the three Qwen models of
    QWENEXT) then runs through the same runner unchanged. A plan without
    a models entry falls back to MODEL_QUEUE.
    """
    models = plan.get("models") or []
    if not models:
        return MODEL_QUEUE
    return tuple(meta["model"] for meta in models)


def plan_persona_slice(plan: dict[str, Any], model_index: int) -> tuple[int, int]:
    """The persona slice of queue slot model_index as the plan records it.

    Every plan builder stamps each model's persona_slice on its models
    list, so the runner reads the slice from the plan: the 5-model plans
    record the [20i, 20i+20) partition, the QWENEXT plans record the
    shared [40, 60) slice all three of their models answer. A plan
    without a models entry falls back to the queue partition.
    """
    models = plan.get("models") or []
    if 0 <= model_index < len(models):
        start, stop = models[model_index]["persona_slice"]
        return int(start), int(stop)
    return persona_slice(model_index)


def _model_meta(
    model_index: int, product_count: int, level_count: int, none_draws: int
) -> dict[str, Any]:
    """The plan's summary of one model: its calls and persona slice."""
    model = MODEL_QUEUE[model_index]
    safe = _safe_model_name(model)
    none_calls = 2 * product_count * level_count * none_draws
    persona_calls = 2 * product_count * PERSONAS_PER_MODEL * level_count
    start, stop = persona_slice(model_index)
    return {
        "model": model,
        "model_index": model_index,
        "safe_model": safe,
        "persona_slice": [start, stop],
        "personas_per_product": PERSONAS_PER_MODEL,
        "none_calls": none_calls,
        "demographics_calls": persona_calls,
        "total_calls": none_calls + persona_calls,
    }


def build_queue_plan(
    product_count: int,
    level_count: int,
    *,
    levels: list[float] | None = None,
    seed: int = 42,
    pool_seed: int = 42,
    none_draws: int = NONE_LEG_DRAWS,
    profile: str = QUEUE_PROFILE,
) -> dict[str, Any]:
    """The whole queue plan: 20 legs, per-model and total call counts.

    legs holds the 20 (model x depth x blinding) targets in queue order:
    for each model, none_blinded, none_unblinded, demographics_blinded,
    demographics_unblinded. none legs carry 40 x levels x none_draws calls
    each, demographics legs 40 x 20 x levels each; per model that is the
    R1LP 880 + 17,600 = 18,480 (none_draws=1) or the R1-5MODEL 8,800 +
    17,600 = 26,400 (none_draws=10) calls, and the five models together
    92,400 or 132,000 respectively.
    """
    levels = list(levels) if levels is not None else []
    targets: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for index in range(len(MODEL_QUEUE)):
        meta = _model_meta(index, product_count, level_count, none_draws)
        models.append(meta)
        for depth in BASE_DEPTHS:
            for blinding in BLINDINGS:
                calls = (
                    product_count * level_count * none_draws
                    if depth == "none"
                    else product_count * PERSONAS_PER_MODEL * level_count
                )
                targets.append(
                    {
                        "model": meta["model"],
                        "model_index": index,
                        "safe_model": meta["safe_model"],
                        "depth": depth,
                        "blinding": blinding,
                        "calls": calls,
                    }
                )
    return {
        "profile": profile,
        "models": models,
        "legs": targets,
        "sweep_calls": sum(int(leg["calls"]) for leg in targets),
        "levels": levels,
        "k": POOL_PERSONAS_PER_PRODUCT,
        "draws": none_draws,
        "per_model_personas": PERSONAS_PER_MODEL,
        "seed": seed,
        "pool_seed": pool_seed,
        "pool_draws": 0,  # pools are reused (no persona draws) by default
    }


def build_logprob_plan(
    product_count: int,
    level_count: int,
    *,
    levels: list[float] | None = None,
    seed: int = 42,
    pool_seed: int = 42,
    ab_orders: bool = False,
    profile: str = LOGP_PROFILE,
) -> dict[str, Any]:
    """The R1LP-plan geometry under the given profile id (default R1LP).

    Identical stratification to R1-5MODEL (five models, 20-persona slices,
    bare legs) but none_draws=1, so per model the call count is
    40 x 11 x 2 = 880 bare + 20 x 40 x 11 x 2 = 17,600 persona scoring
    passes = 18,480, and the five models together 92,400. profile stamps
    the plan with its own id ("R1-YESNO" rides the exact same geometry);
    the default leaves the plain R1LP plan untouched.

    With ab_orders=True (the A/B label-order switch, USER DIRECTIVE)
    every cell is planned with BOTH label orders, so every count doubles:
    36,960 per model, 184,800 total, and the plan is stamped
    ab_orders=True. Without it the plan carries no ab_orders stamp.
    """
    plan = build_queue_plan(
        product_count,
        level_count,
        levels=levels,
        seed=seed,
        pool_seed=pool_seed,
        none_draws=LOGP_NONE_DRAWS,
        profile=profile,
    )
    return _double_plan_for_ab(plan) if ab_orders else plan


def _double_plan_for_ab(plan: dict[str, Any]) -> dict[str, Any]:
    """The A/B copy of a plan: both label orders per cell, so 2x counts.

    Every leg's scoring passes double (one pass per label order) and the
    plan is stamped ab_orders=True; the input plan is never mutated.
    """
    return {
        **plan,
        "ab_orders": True,
        "legs": [{**leg, "calls": 2 * int(leg["calls"])} for leg in plan["legs"]],
        "models": [
            {
                **meta,
                "none_calls": 2 * int(meta["none_calls"]),
                "demographics_calls": 2 * int(meta["demographics_calls"]),
                "total_calls": 2 * int(meta["total_calls"]),
            }
            for meta in plan["models"]
        ],
        "sweep_calls": 2 * int(plan["sweep_calls"]),
    }


def model_top_k(model: str) -> int:
    """The first_token request's top-k for one model: override or 20.

    The per-model override map (MODEL_TOP_K_OVERRIDES) is queue-profile
    config: a model whose useful answer candidates only appear in a wider
    candidate list gets a bigger k, every other model (known or unknown)
    keeps the historical TOP_LOGPROBS coverage. The resolved value is
    stamped on each leg's manifest and applied on every first_token
    request, so the records always say which coverage they hold.
    """
    return MODEL_TOP_K_OVERRIDES.get(model, TOP_LOGPROBS)


def model_control_sequences(model: str) -> tuple[tuple[str, ...], ...]:
    """One model's control sequences: its profile override, or none.

    The per-model override map (MODEL_CONTROL_SEQUENCES) is queue-profile
    config: a model whose replies open with a fixed channel header gets
    that exact token sequence consumed as one block, every other model
    (known or unknown) keeps the default-off empty tuple - the identity
    that leaves scoring byte-identical. The resolved value is stamped on
    each leg's manifest and threaded into the scorer, so the records
    always say which header config they hold. A malformed override
    (empty or non-string) is refused at scorer construction.
    """
    return MODEL_CONTROL_SEQUENCES.get(model, ())


def queue_leg_dir(run_dir: Path, target: dict[str, Any]) -> Path:
    """One model leg's output directory: <run>/<model>/<depth>_<blinding>."""
    return run_dir / target["safe_model"] / f"{target['depth']}_{target['blinding']}"


def queue_leg_jsonl(leg_dir: Path) -> Path:
    """A queue leg's durable records file (its resume state)."""
    return leg_dir / LEG_FILE


def queue_leg_done(run_dir: Path, target: dict[str, Any]) -> bool:
    """Resume check for one (model, leg): does it have its final files?

    A leg is done only when its records.jsonl holds cells, its derived
    records.csv exists and its manifest.json exists - the same triple the
    single-model wrapper uses, with records.jsonl as the durable file.
    """
    leg_dir = queue_leg_dir(run_dir, target)
    jsonl = queue_leg_jsonl(leg_dir)
    return (
        jsonl.exists()
        and jsonl.stat().st_size > 0
        and (leg_dir / "records.csv").exists()
        and (leg_dir / "manifest.json").exists()
    )


def pending_queue_targets(
    run_dir: Path, targets: list[dict[str, Any]], resume: bool
) -> list[dict[str, Any]]:
    """The legs still to run: all of them, or only the unfinished on resume.

    A fresh invocation plans every leg; a --resume invocation plans exactly
    the (model, leg) pairs that are not durably done, so completed model
    legs are skipped as whole units (their cells never re-run).
    """
    if not resume:
        return list(targets)
    return [leg for leg in targets if not queue_leg_done(run_dir, leg)]


def _durable_calls(run_dir: Path, target: dict[str, Any]) -> int:
    """Cells of one leg already durable on disk (0 when it never started)."""
    jsonl = queue_leg_jsonl(queue_leg_dir(run_dir, target))
    return durable_cells(jsonl)[0] if jsonl.exists() else 0


def _regular_prices(products: list[dict[str, Any]]) -> dict[str, float | None]:
    """Map each product name to its regular price (for the csv price column)."""
    return {product["product"]: product.get("regular_price") for product in products}


def _resolve_pools_from(pools_from: str) -> Path | None:
    """Resolve --pools-from relative to the repository root; None if absent."""
    if not pools_from:
        return None
    path = Path(pools_from)
    if path.exists():
        return path
    from_repo = _REPO_ROOT / pools_from
    return from_repo if from_repo.exists() else None


def print_queue_dry_run(
    args: Any,
    products: list[dict[str, Any]],
    plan: dict[str, Any],
    run_dir: Path,
    *,
    logprob_mode: str | None = None,
    scan_tokens: int | None = None,
) -> None:
    """Print the whole queue plan (sampling or R1LP logprob) and exit.

    scan_tokens (first_token runs only) names the decision-scan window
    the run's requests will carry, so the request shape is visible
    before any call is made.
    """
    profile = plan.get("profile", QUEUE_PROFILE)
    draws = int(plan.get("draws", NONE_LEG_DRAWS))
    per_model = int(plan["sweep_calls"] / len(plan["models"]))
    source = _resolve_pools_from(getattr(args, "pools_from", ""))
    print(f"{profile} launch plan (dry run)")
    print(
        f"  queue         {len(plan['models'])} models, one invocation "
        f"(manager {args.manager_url})"
    )
    for meta in plan["models"]:
        start, stop = meta["persona_slice"]
        print(
            f"    [{meta['model_index']}] {meta['model']:<36} "
            f"pool personas {start}-{stop - 1} ({meta['personas_per_product']} "
            f"per product), {draws} plain draws/cell"
        )
    if logprob_mode:
        window = f"; decision scan max_tokens={scan_tokens}" if scan_tokens else ""
        print(
            f"  grammar       none (no constrained decoding; "
            f"logprob mode {logprob_mode}{window})"
        )
    else:
        print(
            f"  grammar       {QUEUE_GRAMMAR!r} on every purchase call, every model and leg"
        )
    print(
        f"  products      {len(products)} from "
        f"{Path(args.products).name if Path(args.products).exists() else args.products}"
    )
    print(
        f"  levels        {len(plan['levels'])} price levels; depths none, demographics x blinded, unblinded"
    )
    print(f"  persona pool  {plan['k']} personas/product, seed {plan['pool_seed']}")
    if source is not None:
        print(f"    reused from {source}  (pools from --pools-from)")
    else:
        given = getattr(args, "pools_from", "")
        label = "default" if given == DEFAULT_POOLS_FROM else "--pools-from"
        print(
            f"    {label} pool source {given or '(none)'} not found in this "
            "checkout; the run will regenerate a deterministic pool-seed-42 "
            f"pool ({plan['k']} personas/product) as today"
        )
    print("  legs (20, per model)")
    for meta in plan["models"]:
        print(
            f"    {meta['model']:<36} "
            f"none {meta['none_calls']:,} calls (2 x "
            f"{int(meta['none_calls'] / 2):,}) + demographics "
            f"{meta['demographics_calls']:,} calls (2 x "
            f"{int(meta['demographics_calls'] / 2):,})"
        )
    print(
        f"  queue calls   {plan['sweep_calls']:,} total "
        f"({len(plan['models'])} models x "
        f"{per_model:,})"
    )
    if logprob_mode:
        print(
            f"  prompts       {per_model:,} scoring prompts per model "
            f"({plan['sweep_calls']:,} total, mode {logprob_mode})"
        )
    print(
        f"  outputs       {run_dir}/  (per-model leg dirs, results.csv "
        "appended continuously, progress.json, manifest.json)"
    )
