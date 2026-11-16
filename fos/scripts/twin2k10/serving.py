# This file holds everything in the twin2k10 study that talks to the model
# manager: generating the shared persona pool through the proven pool
# machinery, and loading / unloading one model at a time on the local
# llama-server (with a health wait, because a port is often dark right
# after an unload). Nothing here scores answers or writes records — those
# live in legexec and cells; this is purely the serving plumbing the
# runner drives between model blocks. Every function takes the runner's
# log callable as an argument, so this module stays free of any import
# from the runner itself.

import json
from pathlib import Path
from typing import Callable

from twin2k10 import config, prompts, registry

# The synthetic single-product persona pool: one neutral product name, the
# study's pool seed and size (the same cleanest path the twin2k6 study used).
POOL_PRODUCT = "twin2k_respondent"
POOL_CATEGORY = "grocery item"
POOL_K = config.PERSONA_COUNT
POOL_SEED = config.SEED
# The pool must be DRAWN by one declared model; pin it to the study's first
# model so a resumed/subset run never disagrees with the pools.json marker.
GENERATOR_MODEL = registry.manager_model_id(config.MODELS[0])


def write_products_file(run_dir: Path) -> Path:
    """The one-product products file the persona pool phase is driven with."""
    path = Path(run_dir) / "twin2k10_pool_products.json"
    payload = {"products": [{
        "category": POOL_CATEGORY, "product": POOL_PRODUCT,
        "regular_price": 1.0,
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
            f"error: {pool_path} holds {len(personas)} personas, "
            f"expected {POOL_K}"
        )
    for index, persona in enumerate(personas):
        extra = set(persona) - set(prompts.PERSONA_FIELDS)
        if extra:
            raise SystemExit(
                f"error: persona {index} carries non-demographic fields "
                f"{sorted(extra)} — refusing a leaking pool"
            )
    return personas


def ensure_pool(run_dir: Path, manager_url: str, base_url: str,
                log: Callable[[str], None]) -> list[dict]:
    """The pool phase: generate + subsample via the existing machinery.

    Reuses launch_support._pool_phase verbatim with the synthetic single
    product (idempotent: a matching pools.json marker skips
    regeneration), then reads the finished pool back with its 0-99
    line-order ids.
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


def port_healthy(base_url: str) -> bool:
    """Whether the llama-server on base_url answers /health right now."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=10.0) as r:
            return r.status == 200
    except OSError:
        return False


def wait_healthy(base_url: str, model: str, log: Callable[[str], None],
                 deadline_seconds: float = 600.0) -> None:
    """Poll the server's health endpoint until it answers (max ~10 min).

    Raises RuntimeError when the model never becomes healthy — a stuck
    load must stop the run, not hang it forever.
    """
    import time

    started = time.monotonic()
    deadline = started + deadline_seconds
    poll = 0
    while time.monotonic() < deadline:
        poll += 1
        if port_healthy(base_url):
            return
        if poll % 5 == 0:
            log(f"waiting for {model} on {base_url} "
                f"({time.monotonic() - started:.0f}s)")
        time.sleep(3.0)
    raise RuntimeError(
        f"model {model} not healthy on {base_url} within "
        f"{deadline_seconds:.0f}s"
    )


def ensure_model_loaded(manager_url: str, base_url: str, model: str,
                        port: int, log: Callable[[str], None]) -> None:
    """Load one model through the manager and wait until it answers.

    The manager is asked first: if it already reports this model on the
    port we only double-check that the server really answers. Otherwise
    we load FIRST (the port may be dark after an unload) and poll the
    health endpoint afterwards, instead of failing just because nothing
    listens yet.
    """
    from launch_support import _load_model, _manager_status

    model_id = registry.manager_model_id(model)
    try:
        loaded = (_manager_status(manager_url).get(str(port)) or {}).get(
            "model"
        )
    except OSError as exc:
        raise RuntimeError(
            f"cannot reach model manager {manager_url}: {exc}"
        ) from exc
    if loaded == model_id and port_healthy(base_url):
        log(f"model {model} already loaded and healthy on :{port}")
        return
    if loaded == model_id:
        log(f"manager says {model} is loaded but the port is dark; reloading")
    log(f"loading {model} ({model_id}) on :{port} via the manager...")
    _load_model(manager_url, model_id, port)
    wait_healthy(base_url, model, log)
    log(f"model {model} healthy on :{port}")


def unload_model(manager_url: str, port: int, model: str,
                 log: Callable[[str], None]) -> None:
    """Release one finished model's GPU slot through the manager."""
    from launch_support import _unload_model

    _unload_model(manager_url, port)
    log(f"unloaded {model} from :{port}")
