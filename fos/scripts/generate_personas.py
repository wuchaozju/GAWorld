"""Generate step-A personas for one product or for a whole product list
through a local chat server.

This script draws personas for a product (Gui & Toubia Web Appendix D step
A): it asks an LLM chat server to fill the eleven-field persona template
once per draw, parses each answer, and appends each accepted persona to a
JSON Lines file immediately, plus a summary JSON with diversity, coherence,
and census-gap reports. Given --products-file it repeats that for every
product in the file — one folder per product — and exits 3 when any product
came up short of --min-personas (which defaults to --n). All of the persona
logic lives in fos.experiments.personas; this script only talks to the
network, saves the results, and prints the reports. Importing the module
never opens a socket.

What each function does:
    main(argv)                 - The entry point: parse flags, then either
                                 loop over every product of --products-file
                                 (batch mode) or draw personas for the one
                                 --category/--product pair (legacy mode).
    _parse_args(argv)          - Turn command-line flags into a settings
                                 object.
    _build_chat_fn(...)        - Build the chat function the persona loop
                                 calls; one retry, "" on final failure.
    _post_json(url, ...)       - POST one JSON object and return (status,
                                 body).
    _server_root(base)         - Normalize a server address for joining.
    _run_product_batch(...)    - Run one product at a time over the products
                                 file and apply the completion gate.
    _run_one_product_dir(...)  - Generate and report one product into its own
                                 folder; returns its shortfall, if any.
    _load_products_file(path)  - Read the products JSON (list or object).
    _safe_product_name(name)   - Fold a product name into a file-safe folder
                                 name (letters and digits kept, case kept).
    _generate_for_product(...) - Draw n personas for one product, appending
                                 each parsed persona to personas.jsonl at
                                 once; returns (personas, skipped).
    _build_summary(...)        - Combine the diversity, coherence and census
                                 reports into the single-product summary.
    _product_summary(...)      - Build the per-product summary for batch
                                 mode (adds the regular price).
    _census_gap(...)           - Census gap report for a batch, ignoring
                                 the file's plain-text metadata keys.
    _write_summary(...)        - Save a summary payload as pretty JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Make this worktree's `src` importable when the script runs directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from fos.experiments.personas import (  # noqa: E402
    PERSONA_SYSTEM,
    build_persona_elicitation_prompt,
    check_persona_coherence,
    check_persona_diversity,
    compare_to_census,
    load_census_marginals,
    parse_persona,
)

# Command-line defaults (see the task spec).
DEFAULT_N = 500
DEFAULT_OUT = "results/personas"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TIMEOUT = 120

# A chat function: message list and temperature in, raw model text out.
ChatFn = Callable[[list[dict[str, str]], float], str]


def main(argv: list[str] | None = None) -> int:
    """Run one persona generation; return the process exit code.

    Parses the flags and requires a model id. With --products-file it loops
    over every product in the file, writing each product's accepted personas
    to {out}/{safe product}/personas.jsonl plus a summary.json, and returns
    3 when any product parsed fewer personas than --min-personas. Without a
    products file it draws args.n personas for the single --category/
    --product pair into the --out directory directly.
    """
    args = _parse_args(argv)
    if not args.model:
        print("error: --model is required", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    chat_fn = _build_chat_fn(args.base_url, args.model, args.timeout)
    if args.products_file:
        return _run_product_batch(args, chat_fn, out_dir, started)
    if not args.category or not args.product:
        print(
            "error: give --category and --product, or a --products-file",
            file=sys.stderr,
        )
        return 2
    personas, skipped = _generate_for_product(
        args.category,
        args.product,
        args.n,
        chat_fn,
        out_dir=out_dir,
        temperature=args.temperature,
        seed=args.seed,
    )
    summary_file = _write_summary(
        out_dir / "summary.json",
        _build_summary(args, personas, skipped, started),
    )
    print(
        f"generated {len(personas)} personas ({skipped} skipped) -> "
        f"{out_dir / 'personas.jsonl'}"
    )
    print(f"wrote {summary_file}")
    return 0


def _add_batch_flags(parser: argparse.ArgumentParser) -> None:
    """Add the batch-mode and safety flags to an argument parser."""
    parser.add_argument(
        "--products-file",
        default=None,
        help='JSON file with {"products": [{category, product, '
        "regular_price}]} to generate personas for every product in one run",
    )
    parser.add_argument(
        "--min-personas",
        type=int,
        default=None,
        help="fewest parsed personas each product must reach before the run "
        "is complete (default: same as --n)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="seconds before one chat request is retried (default: %(default)s)",
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command-line flags into one settings object."""
    parser = argparse.ArgumentParser(
        prog="generate_personas",
        description=(
            "Draw step-A personas through a local chat server and write "
            "persona JSONL plus a summary report, for one product or for "
            "every product in a products file."
        ),
    )
    parser.add_argument(
        "--category",
        default=None,
        help="product category, e.g. Soft Drinks (used when no "
        "--products-file is given)",
    )
    parser.add_argument(
        "--product",
        default=None,
        help="product name shown to the model (used when no --products-file is given)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=DEFAULT_N,
        help="personas to draw per product (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="directory to write results into (default: %(default)s)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="model id sent to the chat server verbatim",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="chat server base url (default: %(default)s)",
    )
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--seed", type=int, default=None)
    _add_batch_flags(parser)
    return parser.parse_args(argv)


def _server_root(base_url: str) -> str:
    """Normalize a server address: no trailing slash, no doubled /v1."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, str]:
    """POST one JSON object and return the (status, body) pair."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def _build_chat_fn(
    base_url: str, model: str, timeout: float = DEFAULT_TIMEOUT
) -> ChatFn:
    """Build the chat function the persona loop calls during a run.

    The returned function posts one /v1/chat/completions request per call
    and retries once when the request fails or times out; the --timeout
    value bounds every request. On a final failure it logs the problem and
    returns "" so the draw is counted as skipped instead of the whole run
    crashing.
    """

    def chat_fn(messages: list[dict[str, str]], temperature: float) -> str:
        url = f"{_server_root(base_url)}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        last_error = ""
        for _attempt in range(2):
            try:
                _status, body = _post_json(url, payload, timeout)
                data = json.loads(body)
                content = data["choices"][0]["message"].get("content")
                return content if isinstance(content, str) else ""
            except OSError as exc:
                last_error = str(exc)
            except (json.JSONDecodeError, KeyError, IndexError) as exc:
                last_error = f"unexpected reply: {exc}"
        print(
            f"warning: chat request to {url} failed ({last_error}); "
            "recording this draw as skipped",
            file=sys.stderr,
        )
        return ""

    return chat_fn


def _run_product_batch(
    args: argparse.Namespace,
    chat_fn: ChatFn,
    out_dir: Path,
    started: str,
) -> int:
    """Generate personas for every product of --products-file.

    Each product gets its own folder (named from a safe fold of the product
    name) holding a personas.jsonl file and a summary.json. After the loop
    any product that parsed fewer personas than --min-personas (the same as
    --n when omitted) is called out on stderr with its got/expected counts
    and the run exits 3; a fully supplied run exits 0.
    """
    try:
        products = _load_products_file(args.products_file)
    except (OSError, ValueError) as exc:
        print(
            f"error: cannot read --products-file {args.products_file}: {exc}",
            file=sys.stderr,
        )
        return 2
    if not products:
        print(f"error: no products listed in {args.products_file}", file=sys.stderr)
        return 2
    expected = args.n if args.min_personas is None else args.min_personas
    short_products: list[tuple[str, int, int]] = []
    for item in products:
        shortfall = _run_one_product_dir(
            item, args, chat_fn, out_dir, started, expected
        )
        if shortfall is not None:
            short_products.append(shortfall)
    for product_name, got, want in short_products:
        print(
            f"shortfall: {product_name} parsed {got} of {want} requested personas",
            file=sys.stderr,
        )
    return 3 if short_products else 0


def _run_one_product_dir(
    item: dict[str, Any],
    args: argparse.Namespace,
    chat_fn: ChatFn,
    out_dir: Path,
    started: str,
    expected: int,
) -> tuple[str, int, int] | None:
    """Generate one product's personas and report them.

    Writes the product's personas.jsonl (appended per parsed persona) and
    summary.json into its own folder under out_dir and prints the one-line
    report. Returns the (product, got, expected) shortfall tuple when the
    product parsed fewer than expected personas, else None.
    """
    product_name = item["product"]
    folder = out_dir / _safe_product_name(product_name)
    personas, skipped = _generate_for_product(
        item["category"],
        product_name,
        args.n,
        chat_fn,
        out_dir=folder,
        temperature=args.temperature,
        seed=args.seed,
    )
    summary_file = _write_summary(
        folder / "summary.json",
        _product_summary(
            item,
            args.model,
            args.n,
            personas,
            skipped,
            args.temperature,
            args.seed,
            started,
        ),
    )
    print(
        f"generated {len(personas)} personas ({skipped} skipped) -> "
        f"{folder / 'personas.jsonl'}"
    )
    print(f"wrote {summary_file}")
    if len(personas) < expected:
        return (product_name, len(personas), expected)
    return None


def _load_products_file(path: str) -> list[dict[str, Any]]:
    """Read the products file, accepting either a bare list or an object.

    The object shape carries the products under a "products" key; both
    shapes return a list of {"category", "product", "regular_price"} dicts.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    products = data.get("products")
    if not isinstance(products, list):
        raise ValueError(f"{path} has neither a bare product list nor a 'products' key")
    return products


def _safe_product_name(product: str) -> str:
    """Fold a product name into a file-safe folder name.

    Every run of characters that is not a letter or digit becomes one
    underscore; case is kept, so "Coca-Cola Soda Pop, 12 fl oz" becomes
    "Coca_Cola_Soda_Pop_12_fl_oz".
    """
    return re.sub(r"[^0-9A-Za-z]+", "_", product)


def _generate_for_product(
    category: str,
    product: str,
    n: int,
    chat_fn: ChatFn,
    out_dir: Path | str,
    temperature: float = 1.0,
    seed: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Draw n personas for one product; return (personas, skipped).

    One chat call per persona: the step-A prompt goes in the user message
    and the model's raw answer is parsed. Answers that do not parse to a
    full persona are counted in skipped, never in personas. Every parsed
    persona is appended to {out_dir}/personas.jsonl and flushed to disk
    right away, so a run killed halfway never loses what it already drew.
    Exceptions from chat_fn are never swallowed.
    """
    del seed  # chat_fn is the only source of randomness.
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    personas: list[dict[str, Any]] = []
    skipped = 0
    user_prompt = build_persona_elicitation_prompt(category, product)
    messages = [
        {"role": "system", "content": PERSONA_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    with (out / "personas.jsonl").open("a", encoding="utf-8") as handle:
        for _ in range(n):
            raw = chat_fn(messages, temperature)
            persona = parse_persona(raw)
            if persona is None:
                skipped += 1
            else:
                personas.append(persona)
                handle.write(json.dumps(persona) + "\n")
                handle.flush()
    return personas, skipped


def _census_gap(personas: list[dict[str, Any]]) -> dict[str, Any]:
    """Gap report for a batch, ignoring the census file's metadata keys.

    The bundled census file starts with plain-text "_label" and "_source"
    entries next to the per-field dicts, and compare_to_census only knows
    the per-field shape, so only the dict-valued marginals are passed on.
    """
    marginals = load_census_marginals()
    fields = {
        name: value for name, value in marginals.items() if isinstance(value, dict)
    }
    return compare_to_census(personas, fields)


def _summary_body(
    category: str,
    product: str,
    model: str,
    n_requested: int,
    personas: list[dict[str, Any]],
    skipped: int,
    temperature: float,
    seed: int | None,
    started: str,
) -> dict[str, Any]:
    """Combine the diversity, coherence and census reports into one payload."""
    return {
        "category": category,
        "product": product,
        "model": model,
        "n_requested": n_requested,
        "n_personas": len(personas),
        "n_skipped": skipped,
        "temperature": temperature,
        "seed": seed,
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "diversity": check_persona_diversity(personas),
        "coherence": check_persona_coherence(personas),
        "census_gap": _census_gap(personas),
    }


def _build_summary(
    args: argparse.Namespace,
    personas: list[dict[str, Any]],
    skipped: int,
    started: str,
) -> dict[str, Any]:
    """Build the summary payload for a single-product (legacy) run."""
    return _summary_body(
        args.category,
        args.product,
        args.model,
        args.n,
        personas,
        skipped,
        args.temperature,
        args.seed,
        started,
    )


def _product_summary(
    item: dict[str, Any],
    model: str,
    n_requested: int,
    personas: list[dict[str, Any]],
    skipped: int,
    temperature: float,
    seed: int | None,
    started: str,
) -> dict[str, Any]:
    """Build the per-product summary payload for a batch run.

    The payload is the regular summary plus the product's regular price, so
    a batch run's summaries stand on their own without the products file.
    """
    summary = _summary_body(
        item["category"],
        item["product"],
        model,
        n_requested,
        personas,
        skipped,
        temperature,
        seed,
        started,
    )
    summary["regular_price"] = item.get("regular_price")
    return summary


def _write_summary(path: Path, summary: dict[str, Any]) -> Path:
    """Save the summary payload as pretty JSON; return the file path."""
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
