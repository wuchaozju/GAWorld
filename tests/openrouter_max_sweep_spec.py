# Shared fixtures for the OpenRouter Qwen3.8-Max grammar sweep tests
# (TASK-1653). This module holds ONLY the offline building blocks the two
# test files share - the pinned constants of the sweep contract, a fake
# persona pool in the shared-pool file shape, and a fake OpenRouter
# transport. It deliberately imports nothing from the harness itself, so
# it stays importable before scripts/openrouter_max_sweep.py exists.
#
# What each function does (plain language):
#   PRODUCTS / LEVELS / FULL_LEVELS - The mini geometry (2 products x 2
#                                     price levels) and the real 11-level
#                                     ladder used for the 7,040-call plan.
#   EXACT_RESPONSE_FORMAT           - The one strict JSON schema every API
#                                     request must carry (the GBNF
#                                     stand-in), copied verbatim from the
#                                     task design.
#   _forbid_sockets(...)            - Refuses every dial inside a guarded
#                                     block, proving a test run is offline.
#   _fake_pool(...)                 - Sixty personas in the same dict shape
#                                     as the shared pool JSONL files.
#   _write_pools_dir(...)           - Writes one JSONL persona file per
#                                     product, pool-file format.
#   FakeTransport                   - The injected OpenRouter seam: request
#                                     payload in, canned JSON response out;
#                                     records every payload it saw.
#   _demo_renderer(...)             - Renders a persona at the demographics
#                                     depth, exactly as the persona sweep
#                                     path does.
#   expected_design(...)            - The seeded design the harness must
#                                     build for one (blinding, depth) leg,
#                                     via the same builder the existing
#                                     runners use.
#   expected_none_users()           - The exact user prompts the none legs
#                                     must send (Prompt-2 surveys at
#                                     _price_for_level prices).
#   expected_persona_users()        - The exact user prompts the
#                                     demographics legs must send (the
#                                     persona path rendering of pool
#                                     personas 40, 46, 52 and 58).
import json
import socket
import sys
from pathlib import Path

# unblinding_sweep lives in scripts/, which is not on pytest's pythonpath.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import unblinding_sweep as sweep_cli  # noqa: E402
from fos.experiments import personas as personas_mod  # noqa: E402
from fos.experiments import sweep_kit  # noqa: E402

PRODUCTS = [
    {"category": "Soft Drinks", "product": "Cola 12 oz", "regular_price": 1.99},
    {"category": "Chips", "product": "Potato Chips", "regular_price": 2.99},
]
LEVELS = [0.0, 100.0]
FULL_LEVELS = [float(x) for x in range(0, 220, 20)]
PERSONA_INDICES = (40, 46, 52, 58)
EXACT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "purchase_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["purchase", "not purchase"]}
            },
            "required": ["decision"],
            "additionalProperties": False,
        },
    },
}


def forbid_sockets(monkeypatch, reason: str) -> None:
    """Refuse every dial for the guarded block (offline proof)."""

    def _refuse(*_args, **_kwargs):
        raise AssertionError(reason)

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


def fake_pool(size: int = 60) -> list[dict]:
    """A persona pool in the shared-pool dict shape; occupation marks the
    pool index so tests can tell which persona a prompt embodied."""
    return [
        {
            "age": 30 + i,
            "gender": "female",
            "education": "bachelor's degree",
            "household_income": 40000 + i,
            "occupation": f"worker-{i}",
            "ethnicity": "White",
            "marital_status": "single",
            "household_size": 2,
            "number_of_children": 0,
            "state": "TX",
            "home_ownership": "rent",
        }
        for i in range(size)
    ]


def write_pools_dir(pools_dir: Path, products: list[dict]) -> None:
    """Write one 60-persona JSONL file per product, pool-file format."""
    pools_dir.mkdir(parents=True, exist_ok=True)
    for product in products:
        stem = product["product"].lower().replace(" ", "_")
        with (pools_dir / f"{stem}.jsonl").open("w", encoding="utf-8") as handle:
            for persona in fake_pool():
                handle.write(json.dumps(persona) + "\n")


class FakeTransport:
    """The injected OpenRouter seam: a request payload dict in, a canned
    JSON response out. Records every payload it receives and cycles through
    `contents` for the reply bodies, so tests control exactly what the
    'API' answers. Usage is fixed at 120 prompt / 8 completion tokens."""

    def __init__(self, contents: list[str] | None = None):
        self.payloads: list[dict] = []
        self.contents = contents if contents is not None else []
        self.position = 0

    def __call__(self, payload: dict) -> dict:
        self.payloads.append(payload)
        content = self.contents[self.position % len(self.contents)]
        self.position += 1
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 8},
        }


def demo_renderer(persona: dict) -> str:
    """Render a persona at the demographics depth, as run_persona_sweep does."""
    return personas_mod.render_persona_fields(persona, "demographics")


def expected_design(blinding: str, depth: str):
    """The seeded design the harness must build for one (blinding, depth)
    leg - the same builder, seed (42) and covariate kinds the existing
    queue runner uses."""
    return sweep_cli._build_design(
        LEVELS, [blinding], 42, list(sweep_cli.COVARIATE_KINDS), depth
    )


def expected_none_users() -> list[str]:
    """The exact none-leg user prompts: a Prompt-2 survey per (product x
    level) at the _price_for_level price (each drawn once per draw)."""
    users = []
    for product in PRODUCTS:
        for level in LEVELS:
            price = sweep_kit._price_for_level(product["regular_price"], level)
            users.append(
                sweep_kit.build_purchase_user_prompt(
                    product["category"], product["product"], price
                )
            )
    return users


def expected_persona_users() -> list[str]:
    """The exact demographics-leg user prompts: the _persona_user_prompt
    rendering of pool personas 40, 46, 52 and 58 for every (product x
    level) cell."""
    users = []
    pool = fake_pool()
    for product in PRODUCTS:
        for level in LEVELS:
            price = sweep_kit._price_for_level(product["regular_price"], level)
            for index in PERSONA_INDICES:
                users.append(
                    sweep_kit._persona_user_prompt(
                        product["category"],
                        product["product"],
                        price,
                        demo_renderer,
                        pool[index],
                    )
                )
    return users
