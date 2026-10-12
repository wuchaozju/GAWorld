#!/usr/bin/env python3
"""OpenRouter Qwen3.8-Max grammar sweep: the R1 purchase sweep re-run
through the OpenRouter API instead of a local GPU server (TASK-1654).

The R1 sweep normally asks a locally-hosted model to answer the paper's
forced-purchase survey. This harness asks the hosted model
qwen/qwen3.8-max-0902 the exact same questions, at reduced draws (4 per
price level per product), paying per token. The survey prompts are NOT
re-written here: every call goes through the existing sweep kit builders
(the same code path the local runners use), so prompt parity holds by
construction. The "grammar" that forced one-word answers locally becomes a
strict JSON schema attached to every request; answers that do not parse
are recorded as unclassified, never dropped.

This file is the plan + command-line face of the harness. The API mechanics
(payloads, retries, cost math) live in openrouter_max_sweep_api.py and the
run mechanics (legs, durability, resume, cost guard) in
openrouter_max_sweep_run.py; everything is re-exported here so callers and
tests reach every knob as openrouter_max_sweep.X.

What each function does (plain language):
    build_max_sweep_plan(...) - The run's shopping list: which legs
                              (depth x blinding) run, how many API calls
                              each needs, the seed, draws and personas.
    _cost_estimate_usd(...)   - The plan's estimated dollar cost at the
                              pinned per-million token prices.
    _print_dry_run(...)       - Print the plan and the cost estimate
                              without calling anything or writing anything.
    _parse_args(...)          - Read the command-line flags.
    main(...)                 - The command line: --dry-run prints the plan
                              and a cost estimate and touches nothing; a
                              real run reads OPENROUTER_API_KEY from the
                              environment (never written to disk), runs
                              the plan, and prints where results landed.

Run layout: results/unblinding/R1-API-QWEN38MAX-<ts>/qwen_qwen3.8-max-0902/
{none,demographics}_{blinded,unblinded}/records.jsonl plus manifest.json
and progress.json beside the leg folders.

Importing this module never opens a socket; the API is dialed only by the
transport built for a real run.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for _dir in (_SCRIPT_DIR, _REPO_ROOT / "src"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import unblinding_sweep as sweep_cli  # noqa: E402 - scripts/ import order

# Everything imported below is re-exported on purpose: the pinned harness
# contract surface. Tests and callers reach every knob as
# openrouter_max_sweep.X, so the module presents one flat, stable face even
# though the mechanics live in the api and run modules (the names marked
# noqa F401 are re-exported without further use in this file).
from openrouter_max_sweep_api import (  # noqa: E402
    COMPLETION_USD_PER_M,
    DEFAULT_CONCURRENCY,
    DEFAULT_DRAWS,
    DEFAULT_LEVELS,
    DEFAULT_MAX_COST_USD,
    DEFAULT_MODEL,
    DEFAULT_POOLS_FROM,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TRIES,  # noqa: F401 - re-exported contract surface
    NONE_LEG_TEMPERATURE,  # noqa: F401 - re-exported contract surface
    OPENROUTER_URL,
    PERSONA_INDICES,
    PERSONA_LEG_TEMPERATURE,  # noqa: F401 - re-exported contract surface
    PROMPT_USD_PER_M,
    SWEEP_PROFILE,
    OpenRouterError,  # noqa: F401 - re-exported contract surface
    build_response_format,  # noqa: F401 - re-exported contract surface
    call_cost_usd,  # noqa: F401 - re-exported contract surface
    decision_text,  # noqa: F401 - re-exported contract surface
    make_http_transport,
    make_openrouter_chat_fn,  # noqa: F401 - re-exported contract surface
    parse_decision,  # noqa: F401 - re-exported contract surface
    subsample_personas,  # noqa: F401 - re-exported contract surface
)
from openrouter_max_sweep_run import (  # noqa: E402
    PROGRESS_EVERY_CALLS,  # noqa: F401 - re-exported contract surface
    run_plan,
)

# The default persona pool size to load per product (the archived pools
# hold 100; loading the full pool keeps the pinned indices 40..58 intact).
PERSONAS_PER_PRODUCT = 100

# The cost estimate's assumed tokens per call (used by --dry-run only):
# the survey prompts run a few hundred tokens, the schema-capped answer a
# handful - ~$8.9 across the full 7,040-call plan at the pinned prices.
_EST_PROMPT_TOKENS = 600
_EST_COMPLETION_TOKENS = 10


def build_max_sweep_plan(
    product_count: int,
    level_count: int,
    levels: list[float] | None = None,
    seed: int = 42,
    draws: int = DEFAULT_DRAWS,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Build the run's plan: four legs and their API-call counts.

    The two plain (none) legs draw `draws` answers per (product x level);
    the two demographics legs always answer with the four pinned personas,
    once per (product x level). The full study (40 products x 11 levels x
    4 draws) is 7,040 calls; the tests shrink the geometry for offline
    runs through the same builder.
    """
    levels = list(DEFAULT_LEVELS if levels is None else levels)
    none_calls = product_count * level_count * draws
    persona_calls = product_count * level_count * len(PERSONA_INDICES)
    legs = [
        {
            "depth": depth,
            "blinding": blinding,
            "calls": none_calls if depth == "none" else persona_calls,
        }
        for blinding in ("blinded", "unblinded")
        for depth in ("none", "demographics")
    ]
    return {
        "profile": SWEEP_PROFILE,
        "model": model,
        "seed": seed,
        "draws": draws,
        "persona_indices": tuple(PERSONA_INDICES),
        "levels": levels,
        "product_count": product_count,
        "level_count": level_count,
        "sweep_calls": none_calls * 2 + persona_calls * 2,
        "legs": legs,
    }


def _cost_estimate_usd(sweep_calls: int) -> float:
    """The plan's estimated cost at the pinned prices (dry-run display)."""
    per_call = (
        _EST_PROMPT_TOKENS * PROMPT_USD_PER_M
        + _EST_COMPLETION_TOKENS * COMPLETION_USD_PER_M
    ) / 1_000_000
    return sweep_calls * per_call


def _print_dry_run(args: argparse.Namespace) -> None:
    """Print the plan and cost estimate offline (no key, no network)."""
    products = sweep_cli._load_products(sweep_cli._resolve_products_path(args.products))
    levels = sweep_cli._parse_levels(args.levels)
    plan = build_max_sweep_plan(
        len(products),
        len(levels),
        levels=levels,
        seed=args.seed,
        draws=args.draws,
        model=args.model,
    )
    estimate = _cost_estimate_usd(plan["sweep_calls"])
    print(f"profile: {plan['profile']} (dry run - nothing is called or written)")
    print(f"model: {plan['model']} @ {OPENROUTER_URL}")
    print(
        f"geometry: {plan['product_count']} products x "
        f"{plan['level_count']} levels x 2 blindings x "
        f"({plan['draws']} draws + {len(PERSONA_INDICES)} personas)"
    )
    for leg in plan["legs"]:
        print(f"  leg {leg['depth']}_{leg['blinding']}: {leg['calls']:,} calls")
    print(f"total: {plan['sweep_calls']:,} API calls")
    print(
        f"cost estimate: ~${estimate:.2f} (assumes ~{_EST_PROMPT_TOKENS} "
        f"prompt + {_EST_COMPLETION_TOKENS} completion tokens per call at "
        f"${PROMPT_USD_PER_M:.2f}/M + ${COMPLETION_USD_PER_M:.2f}/M); "
        f"hard cap --max-cost ${args.max_cost:.2f}"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command-line flags into one settings object."""
    parser = argparse.ArgumentParser(
        prog="openrouter_max_sweep",
        description=(
            "Re-run the R1 grammar-forced purchase sweep against the "
            "OpenRouter model qwen/qwen3.8-max-0902 at reduced draws, with "
            "a strict JSON schema standing in for the local grammar."
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="OpenRouter model id (default: %(default)s)",
    )
    parser.add_argument(
        "--products",
        default=sweep_cli.DEFAULT_PRODUCTS,
        help="path to the products JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--levels",
        default=sweep_cli.DEFAULT_LEVELS,
        help="comma list of price levels, percent of regular price",
    )
    parser.add_argument(
        "--pools-from",
        default=DEFAULT_POOLS_FROM,
        help="archived persona pools to reuse (default: %(default)s)",
    )
    parser.add_argument(
        "--draws", type=int, default=DEFAULT_DRAWS, help="draws per product and level"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="legs run at once (default: %(default)s)",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=DEFAULT_MAX_COST_USD,
        dest="max_cost",
        help="abort before any call that pushes spend past this many USD "
        "(default: %(default)s)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out-root",
        default=sweep_cli.DEFAULT_OUT,
        help="directory the run folder is created in (default: %(default)s)",
    )
    parser.add_argument(
        "--run-name",
        default="",
        help="run folder name (default: R1-API-QWEN38MAX-<timestamp>)",
    )
    parser.add_argument(
        "--resume",
        default="",
        help="path to an existing run dir to resume (skips durable cells)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="seconds one API call may take (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and cost estimate; call nothing, write nothing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """The command line: dry-run plan, or a real (paid) run. Returns 0.

    A real run reads OPENROUTER_API_KEY from the environment - before any
    network activity - and fails fast with a clear message when it is
    missing. The key is used only in the Authorization header and is never
    printed, logged, or written to any artifact.
    """
    args = _parse_args(argv)
    if args.dry_run:
        _print_dry_run(args)
        return 0
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print(
            "OPENROUTER_API_KEY is not set; export it before running this "
            "harness (the key is read from the environment and never "
            "written to disk or logs).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    products = sweep_cli._load_products(sweep_cli._resolve_products_path(args.products))
    levels = sweep_cli._parse_levels(args.levels)
    plan = build_max_sweep_plan(
        len(products),
        len(levels),
        levels=levels,
        seed=args.seed,
        draws=args.draws,
        model=args.model,
    )
    if args.resume:
        run_dir = Path(args.resume)
        if not run_dir.is_dir():
            raise SystemExit(f"--resume: {run_dir} is not an existing run directory")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_dir = Path(args.out_root) / (args.run_name or f"{SWEEP_PROFILE}-{stamp}")
    personas_by_product = None
    if any(leg["depth"] == "demographics" for leg in plan["legs"]):
        personas_by_product = sweep_cli._load_personas_by_product(
            args.pools_from, products, PERSONAS_PER_PRODUCT
        )
        if not personas_by_product:
            raise SystemExit(
                f"--pools-from {args.pools_from} yielded no persona pools "
                "for the demographics legs"
            )
    transport = make_http_transport(api_key, timeout=args.timeout)
    print(f"profile {plan['profile']}: {plan['sweep_calls']:,} planned calls")
    run_plan(
        plan,
        products,
        personas_by_product,
        run_dir,
        transport,
        concurrency=args.concurrency,
        max_cost_usd=args.max_cost,
        pools_from=args.pools_from,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
