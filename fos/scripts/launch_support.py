#!/usr/bin/env python3
"""Support machinery for the study's launch wrapper: manager + persona pools.

The launch layer around the Gui & Toubia replication sweep is split into
three scripts that never change what the study's existing tools do:
launch_grid.py (flags, plan, run order), launch_support.py (this module:
model-manager calls and persona-pool generation/subsampling), and
launch_sweep.py (the concurrent sweep legs, the watchdog, the manifests and
the smoke pre-flight). This module imports no network-open code on import.

What each function does:
    _load_unblinding_sweep()   - Load scripts/unblinding_sweep.py as a
                                 module so its helpers can be reused.
    _post_json(url, payload, timeout) - POST JSON, return (status, body).
    _get_json(url, timeout)    - GET a url and return its JSON body.
    _manager_status(manager_url) - Ask the manager which model is on each
                                 port.
    _load_model(manager_url, model, port) - POST /models/load; the reply
                                 only comes once the server is healthy.
    _unload_model(manager_url, port) - POST /models/unload (stop the server
                                 on a port after its legs finish).
    _ensure_model(settings, log) - Load the run's model unless it is already
                                 loaded and healthy.
    _repo_sha()                - The repository commit at launch time.
    _now()                     - Current UTC time as ISO-8601.
    _resolve_products(path)    - Find the products file (also from repo
                                 root).
    _load_products(path)       - Read the products JSON (bare list/object).
    _product_folder(product)   - The pool folder name generate_personas uses
                                 (must match its _safe_product_name).
    _count_accepted(folder)    - Accepted personas in one product folder.
    _short_products(...)       - Products whose pool is still below K.
    _short_product_names(...)  - Plain names for the short-products warning
                                 (dicts contribute their "product" field).
    _generate_pools(...)       - Run the persona pool batch tool and top up
                                 any product that came up short.
    _accepted_so_far(...)      - Accepted personas already on disk across
                                 every product (a partial pool phase).
    _subsample_pools(...)      - Seed-subsample to exactly K per product
                                 and write the flat pool files.
    _pool_phase(...)           - Generate + subsample the pools (resumable).
    _load_pool_personas(...)   - Read the flat pool files into the sweep's
                                 persona shape.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Defaults shared with the other launch scripts.
DEFAULT_MODEL = "nvidia/nemotron-cascade-2-30b-a3b"
DEFAULT_MANAGER = "http://127.0.0.1:8081"
DEFAULT_PRODUCTS = "data/configs/unblinding_products.json"
DEFAULT_OUT = "results/unblinding"
DEFAULT_LEVELS = "0,20,40,60,80,100,120,140,160,180,200"
BLINDINGS = ("blinded", "unblinded")
BASE_DEPTHS = ("none", "demographics")
STAGE_DEPTHS = tuple(f"stage{i}" for i in range(2, 13))
# Profile -> pool personas per product. R1-5MODEL is the 5-model stratified
# queue (one invocation, five models back to back): its pool holds 100
# personas per product and every model answers a deterministic 20-persona
# slice of it (see launch_5model). R1LP is the logprob twin of that queue:
# same five models and stratification, but one scoring pass per prompt with
# no grammar (see logprob_scoring / LOGPROB-DESIGN.md). R1-YESNO is the
# R1LP twin that asks the same question with the answer words "yes"/"no"
# and reads the honest first-token probabilities (no grammar either).
# R1-YESNO-QWENEXT re-runs the R1-YESNO experiment with three more Qwen
# models, all sharing qwen3.8-27b's [40, 60) persona slice (see
# launch_yesno_qwenext).
PROFILES = {
    "R1": 100,
    "FULL": 500,
    "R1-5MODEL": 100,
    "R1LP": 100,
    "R1-YESNO": 100,
    "R1-YESNO-QWENEXT": 100,
    "R1-YESNO-QWENEXT-GLM": 100,
    "R1-YESNO-QWEN36D": 100,
    "R1-YESNO-GEMMA31B": 100,
    "R1-YESNO-NEWBATCH": 100,
}

# Measured pilot numbers (RESULT-1501): nemotron Q8 per-call latency, the
# persona-draw estimate, and the speedup of four concurrent clients on the
# llama-server's four slots.
PILOT_SWEEP_SECONDS = 0.65
PILOT_PERSONA_SWEEP_SECONDS = 0.8  # longer prompts than the pilot's plain ones
PILOT_POOL_DRAW_SECONDS = 2.0
PILOT_BATCH_SPEEDUP = 3.7

MODEL_LOAD_TIMEOUT = 360.0  # manager loads synchronously; 33 GB can take long


@dataclass(frozen=True)
class Settings:
    """One resolved launch configuration (see launch_grid's flags)."""

    model: str
    port: int
    manager_url: str
    base_url: str
    out: Path
    run_name: str
    pool_seed: int
    pool_overdraw: float
    seed: int
    draws: int
    progress_every: int
    products_path: str
    # llama-server GBNF grammar sent on every purchase call (R1-5MODEL
    # queue); None keeps the historical grammar-free request (and is what
    # the R1LP logprob profile always uses).
    grammar: str | None = None
    # R1LP logprob scoring mechanism ("first_token" or
    # "candidate_scoring"); None is the historical sampling path.
    logprob_mode: str | None = None
    # The survey's two answer words as one "<positive>/<negative>" value
    # ("yes/no" for R1-YESNO); None keeps the historical "purchase"/
    # "not purchase" prompt. One source of truth: it feeds BOTH the prompt
    # slots and the scorer's branch labels (see sweep_kit's
    # split_response_format).
    response_format: str | None = None
    # How many tokens one first_token call generates for the decision
    # scan (the request's max_tokens): the window must reach past any
    # control/channel prefix (e.g. "<|channel>") to the first substantive
    # answer token. candidate_scoring ignores it (it generates no
    # tokens; it scores the two appended candidates).
    scan_tokens: int = 8


def _load_unblinding_sweep() -> Any:
    """Load scripts/unblinding_sweep.py fresh and return it as a module."""
    script = _REPO_ROOT / "scripts" / "unblinding_sweep.py"
    spec = importlib.util.spec_from_file_location("unblinding_sweep", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    spec.loader.exec_module(module)
    return module


_SWEEP = _load_unblinding_sweep()
_normalize_name = _SWEEP._normalize_name
_safe_model_name = _SWEEP._safe_model_name
_load_personas_by_product = _SWEEP._load_personas_by_product
_covariate_kinds = _SWEEP.COVARIATE_KINDS


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, str]:
    """POST one JSON object and return the (status, body) pair."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def _get_json(url: str, timeout: float) -> Any:
    """GET a url and return its decoded JSON body."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _manager_status(manager_url: str) -> dict[str, dict[str, Any]]:
    """Ask the manager which model is loaded on each port."""
    return _get_json(f"{manager_url.rstrip('/')}/status", timeout=10.0)


def _load_model(manager_url: str, model: str, port: int) -> None:
    """POST /models/load and raise on any failure.

    The manager loads synchronously: the reply arrives only once the new
    llama-server reports healthy (up to ~300 s for a 33 GB model), so no
    extra health polling is needed here.
    """
    url = f"{manager_url.rstrip('/')}/models/load"
    try:
        status, body = _post_json(
            url, {"model": model, "port": port}, timeout=MODEL_LOAD_TIMEOUT
        )
    except OSError as exc:
        raise RuntimeError(f"cannot reach model manager {url}: {exc}") from exc
    if status != 200:
        raise RuntimeError(f"model manager {url} answered HTTP {status}: {body[:200]}")


def _unload_model(manager_url: str, port: int) -> None:
    """POST /models/unload so the queue can release a finished model.

    The manager stops the llama-server on the port and replies when the
    stop is done; the 5-model queue unloads each model before loading the
    next one so only one model ever holds the GPU slot. Raises on any
    failure so a broken unload surfaces instead of silently leaving the
    next model without its slot.
    """
    url = f"{manager_url.rstrip('/')}/models/unload"
    try:
        status, body = _post_json(url, {"port": port}, timeout=MODEL_LOAD_TIMEOUT)
    except OSError as exc:
        raise RuntimeError(f"cannot reach model manager {url}: {exc}") from exc
    if status != 200:
        raise RuntimeError(f"model manager {url} answered HTTP {status}: {body[:200]}")


def _ensure_model(settings: Settings, log: Callable[[str], None]) -> None:
    """Load the run's model on its port unless it is already there.

    A resumed run keeps whatever model the manager already serves, so it
    does not bounce the model mid-night; only a missing or different model
    triggers a load.
    """
    try:
        status = _manager_status(settings.manager_url)
    except OSError as exc:
        raise RuntimeError(
            f"cannot reach model manager {settings.manager_url}: {exc}"
        ) from exc
    loaded = (status.get(str(settings.port)) or {}).get("model")
    try:
        with urllib.request.urlopen(
            f"{settings.base_url}/health", timeout=10.0
        ) as reply:
            healthy = reply.status == 200
    except OSError:
        healthy = False
    if loaded == settings.model and healthy:
        log(f"model {settings.model} already loaded and healthy on :{settings.port}")
        return
    log(
        f"loading {settings.model} on :{settings.port} through the manager "
        f"(previous: {loaded or 'none'})..."
    )
    _load_model(settings.manager_url, settings.model, settings.port)
    log(f"model {settings.model} healthy on :{settings.port}")


def _repo_sha() -> str:
    """The repository commit at launch time ("" when not a git checkout)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _now() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_products(path: str) -> Path:
    """Find the products file, also when relative to the repository root."""
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    from_repo = _REPO_ROOT / path
    return from_repo if from_repo.exists() else candidate


def _load_products(path: Path) -> list[dict[str, Any]]:
    """Read the products JSON: a bare list or {"products": [...]}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    products = data.get("products")
    if not isinstance(products, list):
        raise ValueError(f"{path} has no bare product list and no 'products' key")
    return products


def _product_folder(product: str) -> str:
    """The pool folder name generate_personas uses for one product.

    Must match scripts/generate_personas.py's _safe_product_name: every run
    of non-alphanumeric characters becomes one underscore, case kept.
    """
    return re.sub(r"[^0-9A-Za-z]+", "_", product)


def _count_accepted(folder: Path) -> int:
    """Accepted personas in one generate_personas product folder."""
    persona_file = folder / "personas.jsonl"
    if not persona_file.exists():
        return 0
    with persona_file.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _short_products(
    products: list[dict[str, Any]], pools_work: Path, k: int
) -> list[dict[str, Any]]:
    """The products whose pool folder holds fewer than K accepted personas."""
    return [
        item
        for item in products
        if _count_accepted(pools_work / _product_folder(item["product"])) < k
    ]


def _short_product_names(entries: list[Any]) -> list[str]:
    """Plain names for the short-products warning, one per entry.

    Product entries are dicts whose name lives in the "product" field
    (falling back to the whole entry if the field is missing); anything
    else contributes its string form. Every name is cut to 50 characters
    exactly like the warning always did, so the message stays one line.
    """
    names = []
    for entry in entries:
        name = entry.get("product", entry) if isinstance(entry, dict) else entry
        names.append(str(name)[:50])
    return names


def _read_personas(folder: Path) -> list[dict[str, Any]]:
    """Read every accepted persona dict from one product pool folder."""
    personas: list[dict[str, Any]] = []
    with (folder / "personas.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                personas.append(parsed)
    return personas


def _generator_cmd(
    settings: Settings,
    products_path: Path,
    out_dir: Path,
    n: int,
    minimum: int,
    category: str | None = None,
    product: str | None = None,
) -> list[str]:
    """The generate_personas command for one batch or single-product run."""
    generator = _REPO_ROOT / "scripts" / "generate_personas.py"
    cmd = [
        sys.executable,
        str(generator),
        "--n",
        str(n),
        "--min-personas",
        str(minimum),
        "--model",
        settings.model,
        "--base-url",
        settings.base_url,
        "--out",
        str(out_dir),
        "--timeout",
        "300",
    ]
    if category is None:
        return cmd + ["--products-file", str(products_path)]
    return cmd + ["--category", category, "--product", product or ""]


def _top_up_product(
    settings: Settings,
    item: dict[str, Any],
    pools_work: Path,
    k: int,
    log: Callable[[str], None],
) -> int:
    """Append persona draws for one short product; return draws requested.

    generate_personas appends every accepted persona to the product's
    personas.jsonl (never overwrites), so a top-up only ever adds.
    """
    folder = pools_work / _product_folder(item["product"])
    got = _count_accepted(folder)
    extra = math.ceil((k - got + 2) * settings.pool_overdraw)
    log(
        f"persona pools: top-up {item['product'][:40]!r} "
        f"(got {got}, need {k}, drawing {extra} more)"
    )
    subprocess.run(
        _generator_cmd(
            settings,
            _resolve_products(settings.products_path),
            folder,
            extra,
            1,
            category=item["category"],
            product=item["product"],
        ),
        text=True,
    )
    return extra


def _accepted_so_far(products: list[dict[str, Any]], pools_work: Path) -> int:
    """Total accepted personas already on disk across every product.

    The number of persona lines already drawn into the product folders
    under pools_work; used to tell a fresh pool phase (nothing on disk)
    from a resumed one (an interrupted run kept its accepted draws).
    """
    return sum(
        _count_accepted(pools_work / _product_folder(item["product"]))
        for item in products
    )


def _generate_pools(
    settings: Settings,
    products: list[dict[str, Any]],
    products_path: Path,
    pools_work: Path,
    k: int,
    log: Callable[[str], None],
) -> int:
    """Run the persona-pool batch tool; top up any short product.

    generate_personas draws --n requests per product and keeps only the
    answers that parse, appending each accepted persona to the product's
    personas.jsonl immediately (a killed run keeps what it drew). The batch
    exits 3 when some product parsed fewer than --min-personas (= K here),
    so short products get single-product top-up rounds (append mode) until
    every product holds >= K accepted personas. When a partial pool already
    exists on disk (a resumed run interrupted mid-generation), the full
    batch is NOT re-drawn: only products still short of K get top-up
    rounds, so no GPU calls are spent regenerating finished products.
    Returns the total number of persona requests made in this invocation.
    """
    pools_work.mkdir(parents=True, exist_ok=True)
    per_product = math.ceil(k * settings.pool_overdraw)
    already = _accepted_so_far(products, pools_work)
    if already:
        log(
            f"persona pools: {already} personas already drawn on disk "
            f"(interrupted run) - topping up only the short products"
        )
    else:
        log(f"persona pools: drawing {per_product} per product (min {k} accepted)...")
        subprocess.run(
            _generator_cmd(settings, products_path, pools_work, per_product, k),
            text=True,
        )
    requested = 0 if already else len(products) * per_product
    for _round in range(4):
        short = _short_products(products, pools_work, k)
        if not short:
            break
        for item in short:
            requested += _top_up_product(settings, item, pools_work, k, log)
        if not _short_products(products, pools_work, k):
            break
        log("persona pools: some products still short - drawing another batch")
        subprocess.run(
            _generator_cmd(settings, products_path, pools_work, per_product, k),
            text=True,
        )
        requested += len(products) * per_product
    short = _short_products(products, pools_work, k)
    if short:
        raise SystemExit(
            "error: persona pools still incomplete after retries; short "
            "products: " + ", ".join(_short_product_names(short))
        )
    log(f"persona pools: complete ({requested:,} requests across rounds)")
    return requested


def _subsample_pools(
    settings: Settings,
    products: list[dict[str, Any]],
    pools_work: Path,
    pools_dir: Path,
    k: int,
    log: Callable[[str], None],
) -> dict[str, int]:
    """Uniform-random subsample of exactly K personas per product.

    generate_personas keeps every parseable answer, so a product folder can
    hold more than K accepted personas. The subsample picks K of them with a
    fixed pool-seed RNG, making the pool handed to the sweep deterministic
    and reproducible. The flat files use the normalized product stems the
    sweep's persona loader expects.
    """
    pools_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(settings.pool_seed)
    accepted_total = 0
    accepted_min: int | None = None
    for item in products:
        personas = _read_personas(pools_work / _product_folder(item["product"]))
        accepted_total += len(personas)
        accepted_min = (
            len(personas) if accepted_min is None else min(accepted_min, len(personas))
        )
        if len(personas) < k:
            raise RuntimeError(
                f"{item['product'][:60]} holds only {len(personas)} personas (need {k})"
            )
        chosen = rng.sample(personas, k)
        with (pools_dir / f"{_normalize_name(item['product'])}.jsonl").open(
            "w", encoding="utf-8"
        ) as out:
            for persona in chosen:
                out.write(json.dumps(persona) + "\n")
    log(
        f"pools: subsampled {len(products)} products to {k} each "
        f"(pool-seed {settings.pool_seed}, accepted min {accepted_min})"
    )
    return {
        "accepted_min": int(accepted_min or 0),
        "accepted_total": accepted_total,
        "products": len(products),
    }


def _pool_phase(
    settings: Settings,
    products: list[dict[str, Any]],
    products_path: Path,
    run_dir: Path,
    k: int,
    log: Callable[[str], None],
) -> dict[str, Any]:
    """Generate + subsample the persona pools (skipped when already done).

    A pools.json carrying the same K, pool-seed, model and product count is
    the completed-pool marker used by the resume path.
    """
    pools_work = run_dir / "pools_work"
    pools_dir = run_dir / "pools"
    marker = run_dir / "pools.json"
    if marker.exists():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if (
            existing.get("k") == k
            and existing.get("pool_seed") == settings.pool_seed
            and existing.get("model") == settings.model
            and existing.get("products") == len(products)
        ):
            log("pools: already complete (pools.json matches) - skipping")
            return existing
    requested = _generate_pools(settings, products, products_path, pools_work, k, log)
    summary = _subsample_pools(settings, products, pools_work, pools_dir, k, log)
    payload = {
        "k": k,
        "pool_seed": settings.pool_seed,
        "pool_overdraw": settings.pool_overdraw,
        "model": settings.model,
        "products": len(products),
        "requested": requested,
        "generated_at": _now(),
        **summary,
    }
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _load_pool_personas(
    run_dir: Path, products: list[dict[str, Any]], k: int
) -> dict[str, Any]:
    """Read the flat pool files into the sweep's persona map."""
    return _load_personas_by_product(str(run_dir / "pools"), products, k)
