"""The R1-YESNO-QWENEXT queue specification: three more Qwen models on
qwen3.8-27b's slice, planned and printed offline.

R1-YESNO-QWENEXT re-runs the R1-YESNO first-token yes/no logprob
experiment with three additional Qwen models. Every one of the three
answers the SAME persona slice that qwen/qwen3.8-27b (queue index 2 in
launch_queue.MODEL_QUEUE) answered in R1-YESNO - pool personas [40, 60)
of every product's 100-persona pool - so the new models are directly
comparable to qwen3.8-27b (a shared slice, NOT a partition of the pool).
The geometry is the R1-YESNO geometry exactly: one scoring pass per
prompt, so per model 2 x 40 x 11 x 1 = 880 bare + 2 x 40 x 20 x 11 =
17,600 demographics = 18,480 calls, and the three models together
55,440 across 12 legs. None of the three models has a top-k or
control-sequence override (qwen3.8-27b needed none; the record flags
surface any surprise at analysis time), and the pools are reused from
the same archived run as every other profile. Like launch_queue.py this
module is a pure specification: it opens no sockets and writes no files;
the network only runs inside the runner's run paths.

The GLM companion run (R1-YESNO-QWENEXT-GLM) is the same study for one
more model: glm/glm-4.7-flash answers the SAME shared [40, 60) slice
with the identical geometry, as its own run dir (own profile stamp) that
analysis merges with the 3-model run. It reuses everything here - only
the model queue and the profile stamp differ, chosen per plan build.

The local dense companion run (R1-YESNO-QWEN36D) is the same study again
for one more model: qwen/qwen3.6-27b-dense (the brand-new dense 27B GGUF
served by the local model manager) answers the SAME shared [40, 60)
slice with the identical geometry, as its own run dir (own profile
stamp) that analysis merges with the 3-model run and the GLM companion.
It reuses everything here - only the model queue and the profile stamp
differ, chosen per plan build.

The local Gemma companion run (R1-YESNO-GEMMA31B) is the same study once
more: google/gemma-4-31b-it-qat (the Gemma-4-31B-it QAT Q4_0 GGUF served
by the local model manager) answers the SAME shared [40, 60) slice with
the identical geometry, as its own run dir (own profile stamp) that
analysis merges with the 3-model run and the GLM / QWEN36D companions.
It reuses everything here - only the model queue and the profile stamp
differ, chosen per plan build.

The local four-model batch run (R1-YESNO-NEWBATCH) is the same study for
FOUR brand-new local GGUFs in one sequential queue, run SMALLEST→LARGEST
(a user requirement, so the 8B proves the queue plumbing before the
bigger models spend hours): ibm/granite-4.1-8b, google/gemma-4-12b-it-
qat, ibm/granite-4.1-30b, qwen/qwen3-32b. Each answers the SAME shared
[40, 60) slice with the identical geometry (4 x 18,480 = 73,920 calls
across 16 legs), as its own run dir (own profile stamp) that analysis
merges with the 3-model run and every one-model companion. It reuses
everything here - only the model queue and the profile stamp differ,
chosen per plan build.

What each function does (plain language):
    qwenext_persona_slice(index)  - The shared [40, 60) slice every
                                    QWENEXT model answers (the exact
                                    slice qwen3.8-27b answered in
                                    R1-YESNO); refuses an index outside
                                    the queue instead of silently
                                    slicing empty.
    _qwenext_model_meta(...)      - The plan's summary of one model: its
                                    calls and its shared persona slice.
    build_qwenext_plan(...)       - The queue plan: 12 legs for the
                                    3-model queue (18,480 x 3 calls) or
                                    4 legs for a one-model companion
                                    (18,480; GLM, the local dense
                                    Qwen3.6-27B, or the local Gemma-
                                    4-31B); pass model_queue to pick
                                    the queue.
    print_qwenext_dry_run(...)    - The printed plan (dry run) - no
                                    manager, no server, no grammar.
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

from launch_queue import (  # noqa: E402
    DEFAULT_POOLS_FROM,
    LOGP_NONE_DRAWS,
    MODEL_QUEUE,
    PERSONAS_PER_MODEL,
    POOL_PERSONAS_PER_PRODUCT,
    _resolve_pools_from,
    persona_slice,
)
from launch_support import BASE_DEPTHS, BLINDINGS, _safe_model_name  # noqa: E402

# The queue's run-level profile name (the YESNO_PROFILE naming pattern).
QWENEXT_PROFILE = "R1-YESNO-QWENEXT"
# Manager registry ids (~/fos-model-manager MODEL_REGISTRY), in the run
# order the queue loads and runs them back to back, then unloads each.
QWENEXT_MODEL_QUEUE = (
    "qwen/qwen3.6-35b-a3b",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive",
    "qwen3-4b",
)
# The R1-YESNO model whose persona slice every QWENEXT model shares:
# qwen/qwen3.8-27b answered pool personas [40, 60) in R1-YESNO, so all
# three new models answer exactly those personas of every product.
QWENEXT_SLICE_MODEL = "qwen/qwen3.8-27b"
_SLICE_INDEX = MODEL_QUEUE.index(QWENEXT_SLICE_MODEL)
# The GLM companion run's own profile stamp and one-model queue: clearly
# the same study (the name extends QWENEXT_PROFILE) but never colliding
# with the 3-model run's stamp, so the two run dirs merge unambiguously.
# glm/glm-4.7-flash is the manager registry id (~/fos-model-manager).
QWENEXT_GLM_PROFILE = "R1-YESNO-QWENEXT-GLM"
QWENEXT_GLM_MODEL_QUEUE = ("glm/glm-4.7-flash",)
# The local dense companion run's own profile stamp and one-model queue:
# clearly the same study (the name extends QWENEXT_PROFILE) but never
# colliding with the 3-model run's or the GLM companion's stamps, so the
# run dirs merge unambiguously. qwen/qwen3.6-27b-dense is the manager
# registry id (~/fos-model-manager) of the freshly downloaded dense 27B
# GGUF (Q4_K_M).
QWENEXT_QWEN36D_PROFILE = "R1-YESNO-QWEN36D"
QWENEXT_QWEN36D_MODEL_QUEUE = ("qwen/qwen3.6-27b-dense",)
# The local Gemma companion run's own profile stamp and one-model queue:
# clearly the same study (the name extends QWENEXT_PROFILE) but never
# colliding with the 3-model run's or the GLM / QWEN36D companions'
# stamps, so the run dirs merge unambiguously. google/gemma-4-31b-it-qat
# is the manager registry id (~/fos-model-manager) of the freshly
# downloaded Gemma-4-31B-it QAT GGUF (Q4_0).
QWENEXT_GEMMA31B_PROFILE = "R1-YESNO-GEMMA31B"
QWENEXT_GEMMA31B_MODEL_QUEUE = ("google/gemma-4-31b-it-qat",)
# The local four-model batch run's own profile stamp and queue: clearly
# the same study (the name extends QWENEXT_PROFILE) but never colliding
# with the 3-model run's or any companion's stamps, so the run dirs
# merge unambiguously. The queue is exactly the four freshly downloaded
# manager-registry GGUFs (Q4 quants) in SMALLEST→LARGEST order: the 8B
# runs first so the queue plumbing is proven cheaply before the 30B/32B
# spend hours.
QWENEXT_NEWBATCH_PROFILE = "R1-YESNO-NEWBATCH"
QWENEXT_NEWBATCH_MODEL_QUEUE = (
    "ibm/granite-4.1-8b",
    "google/gemma-4-12b-it-qat",
    "ibm/granite-4.1-30b",
    "qwen/qwen3-32b",
)


def qwenext_persona_slice(
    model_index: int, model_queue: tuple[str, ...] = QWENEXT_MODEL_QUEUE
) -> tuple[int, int]:
    """The pool index range every QWENEXT model answers: [40, 60).

    All models (the three Qwen models and the GLM companion alike) share
    qwen3.8-27b's R1-YESNO slice by design (a shared slice, not a
    partition), so their answers stay directly comparable. An index
    outside the queue raises instead of silently slicing empty - the
    same never-guess convention as launch_queue.persona_slice.
    """
    if not 0 <= model_index < len(model_queue):
        raise ValueError(
            f"model_index {model_index} is outside the QWENEXT queue "
            f"(0..{len(model_queue) - 1})"
        )
    return persona_slice(_SLICE_INDEX)


def _qwenext_model_meta(
    model_queue: tuple[str, ...],
    model_index: int,
    product_count: int,
    level_count: int,
) -> dict[str, Any]:
    """The plan's summary of one model: its calls and persona slice."""
    model = model_queue[model_index]
    start, stop = qwenext_persona_slice(model_index, model_queue)
    none_calls = 2 * product_count * level_count * LOGP_NONE_DRAWS
    demographics_calls = 2 * product_count * PERSONAS_PER_MODEL * level_count
    return {
        "model": model,
        "model_index": model_index,
        "safe_model": _safe_model_name(model),
        "persona_slice": [start, stop],
        "personas_per_product": PERSONAS_PER_MODEL,
        "none_calls": none_calls,
        "demographics_calls": demographics_calls,
        "total_calls": none_calls + demographics_calls,
    }


def build_qwenext_plan(
    product_count: int,
    level_count: int,
    *,
    levels: list[float] | None = None,
    seed: int = 42,
    pool_seed: int = 42,
    profile: str = QWENEXT_PROFILE,
    model_queue: tuple[str, ...] = QWENEXT_MODEL_QUEUE,
) -> dict[str, Any]:
    """The whole QWENEXT plan: 12 legs, per-model and total call counts.

    legs holds the (model x depth x blinding) targets in queue order:
    for each model, none_blinded, none_unblinded, demographics_blinded,
    demographics_unblinded. None legs carry 40 x levels x 1 calls each,
    demographics legs 40 x 20 x levels each; per model that is the
    R1-YESNO 880 + 17,600 = 18,480 one-pass scoring calls, and the three
    models together 55,440. Every model answers the SAME shared [40, 60)
    slice, the pools are reused by default (pool_draws 0), and none of
    the models holds a top-k or control-sequence override (the
    launch_queue maps stay authoritative; qwen3.8-27b needed none).

    model_queue picks the queue to plan: the default 3-model QWENEXT
    queue, or a one-model companion queue (pass it together with the
    companion's profile stamp - 4 legs, 18,480 calls; GLM, the local
    dense Qwen3.6-27B, or the local Gemma-4-31B). Building without the
    parameter yields exactly the live run's plan.
    """
    levels = list(levels) if levels is not None else []
    targets: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for index in range(len(model_queue)):
        meta = _qwenext_model_meta(model_queue, index, product_count, level_count)
        models.append(meta)
        for depth in BASE_DEPTHS:
            for blinding in BLINDINGS:
                calls = (
                    product_count * level_count * LOGP_NONE_DRAWS
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
        "draws": LOGP_NONE_DRAWS,
        "per_model_personas": PERSONAS_PER_MODEL,
        "seed": seed,
        "pool_seed": pool_seed,
        "pool_draws": 0,  # pools are reused (no persona draws) by default
    }


def print_qwenext_dry_run(
    args: Any,
    products: list[dict[str, Any]],
    plan: dict[str, Any],
    run_dir: Path,
) -> None:
    """Print the whole QWENEXT plan and exit (dry run, fully offline).

    Mirrors the other queues' plan printer: profile header, the three
    models with their SHARED persona slice, per-leg and total call
    counts, the pool source and the output layout. The purchase grammar
    never appears - this profile is grammar-free yes/no first-token
    logprob scoring, like R1-YESNO.
    """
    profile = plan.get("profile", QWENEXT_PROFILE)
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
            f"pool personas {start}-{stop - 1} (shared qwen3.8-27b slice), "
            f"{plan['draws']} scoring pass/cell"
        )
    print("  grammar       none (grammar-free yes/no first-token logprobs)")
    print(
        f"  products      {len(products)} from "
        f"{Path(args.products).name if Path(args.products).exists() else args.products}"
    )
    print(
        f"  levels        {len(plan['levels'])} price levels; "
        "depths none, demographics x blinded, unblinded"
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
    print(f"  legs ({len(plan['legs'])}, per model)")
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
        f"({len(plan['models'])} models x {per_model:,})"
    )
    print(
        f"  prompts       {per_model:,} scoring prompts per model "
        f"({plan['sweep_calls']:,} total, first_token yes/no logprobs)"
    )
    print(
        f"  outputs       {run_dir}/  (per-model leg dirs, results.csv "
        "appended continuously, progress.json, manifest.json)"
    )
