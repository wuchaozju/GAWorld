"""Pilot one chat model on the unblinding study's tasks and write a report.

This script checks how well a model handles the Gui & Toubia (2025) survey
tasks before a long overnight run. It asks the model three kinds of questions
through a local chat server, in this order:

  depth1      - The blinded buy/no-buy survey at eleven prices, from 0% to
                200% of the fixed reference price.
  depth2      - The same survey, but with one fixed demographics persona
                (the 11 Appendix D fields of the paper's depth level 2)
                rendered above the question so the model shops as that
                person.
  persona_gen - The full persona-elicitation template (paper Prompt 10,
                the 11 demographic fields) for the same product.

Every answer is counted: buy/no-buy replies parse as purchase or not
purchase, persona replies count only when all eleven demographic fields are
filled in.
The script times every chat call and saves one JSON report per phase with the
call count, the parse rate, latency in seconds (mean, median, p95) and the
first twenty distinct raw answers, plus a short table on the terminal.

Importing this module never opens a socket. The chat transport is built by
_build_chat_fn, which is only called from main and can be swapped out in
tests. A chat call that raises ends the run with exit code 2 after an error
note on stderr; unparseable answers never fail the run.

What each function does:
    main(argv)             - The entry point behind a __main__ guard.
    _parse_args(argv)      - Turn command-line flags into a settings object.
    _normalize_flags(argv) - Accept underscores in long flags (both spellings).
    _server_root(base)     - Normalize a server address for joining.
    _post_json(url, ...)   - POST one JSON object and return (status, body).
    _build_chat_fn(...)    - Build the chat function used during the run.
    _run_all_phases(...)   - Run depth1, depth2, persona-gen in that order.
    _run_phase(...)        - Run one phase's chat calls and summarize them.
    _blinded_user(index)   - User prompt of the depth1 buy/no-buy survey.
    _persona_user(index)   - User prompt that embeds the fixed persona.
    _elicitation_user(...) - User prompt that asks for one complete persona.
    _is_purchase_answer()  - True when an answer says buy or not buy.
    _is_full_persona(raw)  - True when all eleven persona fields are filled.
    _price_at(level)       - Turn one price-grid level into dollars.
    _latency_stats(secs)   - Mean/median/p95 of a phase's per-call times.
    _build_report(...)     - Assemble the report payload from the phases.
    _safe_name(text)       - Turn any text into a safe folder name.
    _write_json(path, ...) - Save one JSON payload to disk.
    _print_summary(report) - Print the human-readable summary table.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
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
    PERSONA_FIELDS,
    PERSONA_SYSTEM,
    build_persona_elicitation_prompt,
    render_persona_fields,
)
from fos.experiments.sweep_kit import (  # noqa: E402
    _SPECIAL_TOKEN,
    _strip_channel_wrappers,
    build_blinded_system_prompt,
    build_purchase_user_prompt,
    parse_purchase,
)

# The chat server we talk to and the default folder for the report.
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_OUT = "results/pilots"

# The paper fixes temperature at 1.0; buy/no-buy replies only need a few
# tokens, while the persona template needs room for all eleven fields.
_TEMPERATURE = 1.0
_DEPTH_MAX_TOKENS = 16
_PERSONA_GEN_MAX_TOKENS = 128

# How many distinct raw answers one phase keeps in its report.
_DISTINCT_RAW_CAP = 20

# The price levels shown to the model: 0% to 200% of the reference price in
# 20% steps, cycled from 0% independently by every phase.
PRICE_GRID = list(range(0, 201, 20))

# The fixed product every phase surveys; its regular_price is the reference
# price that the 0..200% grid is a percentage of.
PILOT_PRODUCT = {
    "category": "Soft Drinks - Carbonated",
    "product": "Coca-Cola Soda Pop, 12 fl oz, 12 Pack Cans",
    "regular_price": 5.0,
}

# A fixed synthetic shopper: all eleven demographic fields of the paper's
# Appendix D depth level 2. Every depth2 call embeds this same persona so
# model behavior is compared on equal ground. Model-invented behavioural
# measures are gone with the drift fix.
PILOT_PERSONA = {
    "age": 35,
    "gender": "female",
    "education": "college",
    "household_income": 86500,
    "occupation": "teacher",
    "ethnicity": "white",
    "marital_status": "married",
    "household_size": 4,
    "number_of_children": 2,
    "state": "CA",
    "home_ownership": "own",
}

# Every field a complete persona answer must name, in one set for the
# eleven-field check (the Appendix D demographics of the two-level ladder).
_ALL_PERSONA_FIELD_NAMES = frozenset(PERSONA_FIELDS)

# System prompt of the persona-elicitation phase: the paper's Prompt 2/10
# customer line (the same line the purchase phases use).
_PERSONA_GEN_SYSTEM = PERSONA_SYSTEM

# A chat function: message list and token budget in, raw model text out.
ChatFn = Callable[[list[dict[str, str]], int], str]


def main(argv: list[str] | None = None) -> int:
    """Run the three pilot phases and write the report; return the exit code.

    Parses the flags, builds the chat transport, runs the depth1, depth2 and
    persona-gen phases in that order, and saves a JSON report plus a readable
    summary table. When the transport raises (any exception from the chat
    function) an error note goes to stderr and the exit code is 2. Answers
    that do not parse are never an error: the run still exits 0.
    """
    args = _parse_args(argv)
    chat_fn = _build_chat_fn(args.base_url, args.model, args.timeout)
    try:
        phases = _run_all_phases(chat_fn, args)
    except Exception as exc:  # any chat transport failure ends the pilot
        print(f"error: chat transport failed: {exc}", file=sys.stderr)
        return 2
    report = _build_report(args, phases)
    out_dir = Path(args.out) if args.out else Path(DEFAULT_OUT) / _safe_name(args.model)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "pilot_report.json", report)
    _print_summary(report)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Read the command-line flags into one settings object."""
    parser = argparse.ArgumentParser(
        prog="pilot_model",
        description=(
            "Pilot one chat model on the unblinding survey tasks and write a "
            "per-phase report to results/pilots/<safe model>/pilot_report.json."
        ),
    )
    parser.add_argument(
        "--model",
        required=True,
        help="model id sent to the chat server verbatim",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="chat server base url (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(f"directory for the report (default: {DEFAULT_OUT}/<safe model>)"),
    )
    parser.add_argument(
        "--depth1-calls",
        type=int,
        default=20,
        help="blinded buy/no-buy calls (default: %(default)s)",
    )
    parser.add_argument(
        "--depth2-calls",
        type=int,
        default=20,
        help="same survey with the fixed demographics persona embedded "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--persona-gen-calls",
        type=int,
        default=5,
        help="persona-elicitation calls (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120,
        help="seconds one chat call may take (default: %(default)s)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help=(
            "accepted for a uniform call signature; the pilot is "
            "deterministic (default: %(default)s)"
        ),
    )
    return parser.parse_args(_normalize_flags(argv))


def _normalize_flags(argv: list[str] | None) -> list[str]:
    """Accept underscores in long flags: --depth1_calls means --depth1-calls.

    The pilot can be driven with either spelling; argparse itself only knows
    the documented dash form, so every long-option token is normalized before
    parsing. Plain values (paths, urls, numbers) never start with "--" and
    are left untouched.
    """
    raw = sys.argv[1:] if argv is None else argv
    return [arg.replace("_", "-") if arg.startswith("--") else arg for arg in raw]


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


def _build_chat_fn(base_url: str, model: str, timeout: float) -> ChatFn:
    """Build the chat transport used during the run; call it only from main.

    The returned function posts one /v1/chat/completions request per call at
    the paper's fixed temperature and hands back the model's raw text.
    Failures are deliberately not retried or swallowed here: the exception
    travels up to main, which reports it on stderr and exits 2.
    """
    url = f"{_server_root(base_url)}/v1/chat/completions"

    def chat_fn(messages: list[dict[str, str]], max_tokens: int) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": _TEMPERATURE,
            "max_tokens": max_tokens,
        }
        _status, body = _post_json(url, payload, timeout)
        data = json.loads(body)
        content = data["choices"][0]["message"].get("content")
        return content if isinstance(content, str) else ""

    return chat_fn


def _run_all_phases(chat_fn: ChatFn, args: argparse.Namespace) -> dict[str, Any]:
    """Run the three pilot phases in order; return one summary per phase.

    Depth1 asks the blinded buy/no-buy survey, depth2 asks the same survey
    with the fixed demographics persona embedded, and persona-gen asks for
    one complete persona. Every phase cycles the price grid from 0% on its
    own.
    """
    blinded = build_blinded_system_prompt()
    return {
        "depth1": _run_phase(
            chat_fn,
            args.depth1_calls,
            _DEPTH_MAX_TOKENS,
            blinded,
            _blinded_user,
            _is_purchase_answer,
        ),
        "depth2": _run_phase(
            chat_fn,
            args.depth2_calls,
            _DEPTH_MAX_TOKENS,
            blinded,
            _persona_user,
            _is_purchase_answer,
        ),
        "persona_gen": _run_phase(
            chat_fn,
            args.persona_gen_calls,
            _PERSONA_GEN_MAX_TOKENS,
            _PERSONA_GEN_SYSTEM,
            _elicitation_user,
            _is_full_persona,
        ),
    }


def _run_phase(
    chat_fn: ChatFn,
    count: int,
    max_tokens: int,
    system: str,
    make_user: Callable[[int], str],
    is_parsed: Callable[[str], bool],
) -> dict[str, Any]:
    """Run one phase's chat calls and summarize them.

    Each call builds the user message from the next price-grid level (make_user
    receives the 0-based call index) under one system prompt, times the chat
    call, and remembers the raw answer. The summary carries the call count,
    the share of answers that parsed, the mean/median/p95 latency in seconds,
    and the first twenty distinct raw answers in first-seen order.
    """
    parsed = 0
    latency_s: list[float] = []
    seen: set[str] = set()
    distinct_raw: list[str] = []
    for index in range(count):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": make_user(index)},
        ]
        started = time.perf_counter()
        raw = chat_fn(messages, max_tokens)
        latency_s.append(time.perf_counter() - started)
        if is_parsed(raw):
            parsed += 1
        if raw not in seen and len(distinct_raw) < _DISTINCT_RAW_CAP:
            seen.add(raw)
            distinct_raw.append(raw)
    return {
        "calls": count,
        "parse_rate": parsed / count if count else 0.0,
        "latency": _latency_stats(latency_s),
        "distinct_raw": distinct_raw,
    }


def _blinded_user(index: int) -> str:
    """User prompt of the depth1 buy/no-buy survey at one grid level."""
    price = _price_at(PRICE_GRID[index % len(PRICE_GRID)])
    return build_purchase_user_prompt(
        PILOT_PRODUCT["category"], PILOT_PRODUCT["product"], price
    )


def _persona_user(index: int) -> str:
    """User prompt that embeds the fixed persona above the same survey."""
    price = _price_at(PRICE_GRID[index % len(PRICE_GRID)])
    survey = build_purchase_user_prompt(
        PILOT_PRODUCT["category"], PILOT_PRODUCT["product"], price
    )
    block = render_persona_fields(PILOT_PERSONA, "demographics")
    return f"{block}\n\n{survey}"


def _elicitation_user(_index: int) -> str:
    """User prompt asking the model to write one complete persona."""
    return build_persona_elicitation_prompt(
        PILOT_PRODUCT["category"], PILOT_PRODUCT["product"]
    )


def _is_purchase_answer(raw: str) -> bool:
    """True when the answer is a clear buy or a clear not-buy reply."""
    return parse_purchase(raw) is not None


def _is_full_persona(raw: str) -> bool:
    """True when the answer fills in all eleven persona fields.

    A persona answer must name every demographic field at the start of a
    "field: value" line and give it a real value; blank placeholders such as
    "[a whole number]" do not count. Wrapper text the chat server adds
    around the answer is stripped first.
    """
    if not isinstance(raw, str):
        return False
    cleaned = _SPECIAL_TOKEN.sub("", _strip_channel_wrappers(raw))
    filled: set[str] = set()
    for line in cleaned.splitlines():
        name, separator, value = line.partition(":")
        value = value.strip()
        if not separator or not value or "[" in value:
            continue
        name = name.strip().lower()
        if name in _ALL_PERSONA_FIELD_NAMES:
            filled.add(name)
    return filled >= _ALL_PERSONA_FIELD_NAMES


def _price_at(level: int) -> float:
    """Turn one price-grid level (percent of the reference price) into dollars."""
    return round(PILOT_PRODUCT["regular_price"] * level / 100.0, 2)


def _latency_stats(seconds: list[float]) -> dict[str, float]:
    """Turn one phase's per-call latencies into mean/median/p95 seconds."""
    if not seconds:
        return {"mean_s": 0.0, "median_s": 0.0, "p95_s": 0.0}
    ordered = sorted(seconds)
    p95_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "mean_s": sum(seconds) / len(seconds),
        "median_s": statistics.median(ordered),
        "p95_s": ordered[p95_index],
    }


def _build_report(args: argparse.Namespace, phases: dict[str, Any]) -> dict[str, Any]:
    """Assemble the report payload: run metadata plus one entry per phase."""
    return {
        "model": args.model,
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "depth1": phases["depth1"],
        "depth2": phases["depth2"],
        "persona_gen": phases["persona_gen"],
    }


def _safe_name(text: str) -> str:
    """Turn any text into a safe folder name: non-alphanumerics become _."""
    return re.sub(r"[^0-9A-Za-z]+", "_", text)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Save one JSON payload to disk as readable text."""
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _print_summary(report: dict[str, Any]) -> None:
    """Print a short human-readable summary of the run to stdout."""
    print(f"model: {report['model']}")
    print(f"base_url: {report['base_url']}")
    print("phase        calls  parse_rate  mean_s  median_s   p95_s")
    for phase in ("depth1", "depth2", "persona_gen"):
        entry = report[phase]
        latency = entry["latency"]
        print(
            f"{phase:<12} {entry['calls']:>5}  {entry['parse_rate']:.2f}  "
            f"{latency['mean_s']:.3f}  {latency['median_s']:.3f}  "
            f"{latency['p95_s']:.3f}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
