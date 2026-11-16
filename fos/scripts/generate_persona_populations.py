#!/usr/bin/env python3
"""
Generate the six Phase-3 persona populations (pop_a1 .. pop_c2).

This script creates six independent populations of 100 simulated people each.
All six populations share the exact same frozen blueprint — a deterministic
27-cell archetype quota and a fixed voting-model assignment — defined in
persona_blueprint.py. What differs per population is only the persona bios
(written by the generating LLM) and the Big Five scores (sampled from a
per-population seed).

Functions:
- sample_big_five: draw the Big Five scores for one agent
- make_provider_clients: build the LLM clients for the three providers
- build_bio_prompt: assemble the persona prompt for one archetype slot
- parse_bio: turn one model response into a bio string
- generate_bio: make the LLM call and return a unique bio
- build_population: generate one full population of 100 agents
- population_to_dict: assemble the population JSON with meta and sha256
- write_population: write one population file
- main: run everything

The shared blueprint helpers (compute_quota, build_frozen_spec, ...) are
imported from persona_blueprint.py. Outputs land in data/populations/:
pop_*.json (plus balance_table.md and leakage_screen.md, written by
scripts/population_reports.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure the fos package is importable without pip install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from fos.core.llm.client import LLMClient  # noqa: E402
from fos.core.llm_config import LLMConfig  # noqa: E402
from fos.i18n import T  # noqa: E402

# Ensure persona_blueprint.py (in this scripts/ directory) is importable.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from persona_blueprint import (  # noqa: E402
    AGENTS_PER_MODEL,
    AGENTS_PER_POPULATION,
    VOTING_MODELS,
    build_frozen_spec,
    cell_attrs,
    compute_quota,
    frozen_spec_sha256,
    print_quota,
)

# Provider definitions: generating model name, OpenAI-compatible base URL,
# API key env var, worker count, and whether to try json_mode first.
PROVIDERS = {
    "a": {
        "label": "DeepSeek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "workers": 6,
        "json_mode": True,
    },
    "b": {
        "label": "GLM-5.2 (ZAI)",
        "model": "glm-5.2",
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "key_env": "GLM_API_KEY",
        "workers": 6,
        "json_mode": True,
    },
    "c": {
        "label": "local llama.cpp gpt-oss-20b",
        "model": "gpt-oss-20b",
        "base_url": "http://localhost:8080",
        "key_env": None,
        "workers": 3,
        "json_mode": False,
    },
}
POPULATION_IDS = ("pop_a1", "pop_a2", "pop_b1", "pop_b2", "pop_c1", "pop_c2")
POPULATION_SEEDS = {
    "pop_a1": 709101, "pop_a2": 709102,
    "pop_b1": 709201, "pop_b2": 709202,
    "pop_c1": 709301, "pop_c2": 709302,
}
PROMPT_TEMPLATE_VERSION = "fos:prompts.archetype.prompt@en (v1)"

BIO_MAX_RETRIES = 3


@dataclass
class Agent:
    """One simulated person: bio, Big Five, grid cell, and voting model."""

    agent_id: str
    bio: str
    big_five: dict[str, int]
    archetype_cell: dict[str, str]
    voting_model: str


@dataclass
class Population:
    """One population of 100 agents plus generation metadata."""

    population_id: str
    generating_model: str
    provider_label: str
    seed: int
    timestamp: str
    frozen_spec_sha256: str
    agents: list[Agent] = field(default_factory=list)


def sample_big_five(rng: random.Random) -> dict[str, int]:
    """Draw one Big Five profile: gaussian mean 50, sd 20, clamped to 0-100."""
    return {
        trait: int(round(max(0.0, min(100.0, rng.gauss(50.0, 20.0)))))
        for trait in ("o", "c", "e", "a", "n")
    }


def make_provider_clients() -> dict[str, LLMClient]:
    """Build one LLM client per provider. Raises if a required key is missing."""
    clients: dict[str, LLMClient] = {}
    for letter, spec in PROVIDERS.items():
        api_key = "not-needed"
        if spec["key_env"]:
            api_key = os.getenv(spec["key_env"], "")
            if not api_key:
                raise RuntimeError(
                    f"Provider '{letter}' ({spec['label']}) needs env var "
                    f"{spec['key_env']} to be set."
                )
        clients[letter] = LLMClient(
            LLMConfig(
                dialect="openai",
                model=spec["model"],
                base_url=spec["base_url"],
                api_key=api_key,
                temperature=0.7,
            )
        )
    return clients


def build_bio_prompt(cell: dict[str, str]) -> str:
    """Assemble the persona-generation prompt for one archetype cell.

    Uses the repo's own archetype prompt template (en locale) so all six
    populations share the exact same wording.
    """
    return T("prompts.archetype.prompt", locale="en", attrs=cell_attrs(cell))


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences around a model response."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_bio(response: str) -> str:
    """Extract a bio string from one model response.

    Tries JSON (the template asks for a {"description": ...} object) and falls
    back to the raw text when it already looks like a first-person bio.
    Returns an empty string when nothing usable was found.
    """
    if not response or not response.strip():
        return ""
    cleaned = _strip_code_fences(response)
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(cleaned)
        if isinstance(parsed, dict) and isinstance(parsed.get("description"), str):
            bio = parsed["description"].strip()
            if bio:
                return bio
    except json.JSONDecodeError:
        pass
    # Some models return only the sentence itself.
    if cleaned.startswith("I am") or cleaned.startswith("I'm"):
        return cleaned
    return ""


class BioRegistry:
    """Tracks every bio written so far so the six populations stay unique."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def claim(self, bio: str) -> bool:
        """Try to claim a bio; returns False when it is empty or a duplicate."""
        if not bio:
            return False
        with self._lock:
            if bio in self._seen:
                return False
            self._seen.add(bio)
            return True


def generate_bio(
    client: LLMClient,
    cell: dict[str, str],
    agent_id: str,
    registry: BioRegistry,
    json_mode_first: bool,
) -> str:
    """Generate one unique bio for an agent via the LLM.

    Retries up to BIO_MAX_RETRIES times when the response is empty or a
    duplicate of an earlier bio. Raises RuntimeError when it cannot produce
    a unique bio — the run must not silently fabricate or duplicate.
    """
    prompt = build_bio_prompt(cell)
    messages = [
        {"role": "system", "content": "Return only valid JSON."},
        {"role": "user", "content": prompt},
    ]
    last_bio = ""
    for attempt in range(BIO_MAX_RETRIES + 1):
        response = ""
        try:
            response = client.chat(messages, json_mode=json_mode_first)
        except Exception:
            try:
                response = client.chat(messages, json_mode=False)
            except Exception as exc:
                if attempt == BIO_MAX_RETRIES:
                    raise RuntimeError(
                        f"{agent_id}: LLM call failed {BIO_MAX_RETRIES + 1} times: {exc!r}"
                    ) from exc
                continue
        last_bio = parse_bio(response)
        if registry.claim(last_bio):
            return last_bio
    raise RuntimeError(
        f"{agent_id}: could not produce a unique non-empty bio after "
        f"{BIO_MAX_RETRIES + 1} attempts (last raw response: {last_bio[:120]!r})"
    )


def _build_population_agents(
    population_id: str,
    clients: dict[str, LLMClient],
    registry: BioRegistry,
    frozen_spec: list[dict[str, Any]],
) -> list[Agent]:
    """Generate the 100 agents of one population (concurrent LLM calls)."""
    letter = population_id[4]  # "pop_a1" -> "a"
    spec = PROVIDERS[letter]
    rng = random.Random(POPULATION_SEEDS[population_id])
    big_fives = [sample_big_five(rng) for _ in range(AGENTS_PER_POPULATION)]
    cells = [slot["archetype_cell"] for slot in frozen_spec]
    voting_models = [slot["voting_model"] for slot in frozen_spec]
    client = clients[letter]

    agents: list[Agent] = [None] * AGENTS_PER_POPULATION  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=spec["workers"]) as pool:
        futures = {}
        for idx in range(AGENTS_PER_POPULATION):
            agent_id = f"{population_id}_agent_{idx + 1:03d}"
            futures[pool.submit(
                generate_bio, client, cells[idx], agent_id, registry,
                spec["json_mode"],
            )] = idx
        for future in as_completed(futures):
            idx = futures[future]
            bio = future.result()  # raises on failure — never swallowed
            agents[idx] = Agent(
                agent_id=f"{population_id}_agent_{idx + 1:03d}",
                bio=bio,
                big_five=big_fives[idx],
                archetype_cell=cells[idx],
                voting_model=voting_models[idx],
            )
    return agents


def build_population(
    population_id: str,
    clients: dict[str, LLMClient],
    registry: BioRegistry,
    frozen_spec: list[dict[str, Any]],
) -> Population:
    """Generate one full population of 100 agents."""
    letter = population_id[4]
    spec = PROVIDERS[letter]
    agents = _build_population_agents(population_id, clients, registry, frozen_spec)
    return Population(
        population_id=population_id,
        generating_model=spec["model"],
        provider_label=spec["label"],
        seed=POPULATION_SEEDS[population_id],
        timestamp=datetime.now(timezone.utc).isoformat(),
        frozen_spec_sha256=frozen_spec_sha256(frozen_spec),
        agents=agents,
    )


def population_to_dict(population: Population) -> dict[str, Any]:
    """Assemble the full population dict (without the sha256 field)."""
    return {
        "generation_meta": {
            "population_id": population.population_id,
            "generating_model": population.generating_model,
            "provider": population.provider_label,
            "timestamp": population.timestamp,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "seed": population.seed,
            "agents_per_population": AGENTS_PER_POPULATION,
            "voting_models": list(VOTING_MODELS),
            "agents_per_voting_model": AGENTS_PER_MODEL,
            "frozen_spec_sha256": population.frozen_spec_sha256,
            "big_five_sampling": {
                "distribution": "gaussian",
                "mean": 50,
                "sd": 20,
                "clamp": [0, 100],
            },
        },
        "agents": [
            {
                "agent_id": agent.agent_id,
                "bio": agent.bio,
                "big_five": agent.big_five,
                "archetype_cell": agent.archetype_cell,
                "voting_model": agent.voting_model,
            }
            for agent in population.agents
        ],
    }


def sha256_of(data: dict[str, Any]) -> str:
    """Hex digest of the deterministic JSON (sorted keys, no sha256 field)."""
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_population(population: Population, out_dir: Path) -> Path:
    """Write one population file and return its path."""
    data = population_to_dict(population)
    data["sha256"] = sha256_of(data)
    path = out_dir / f"{population.population_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def main() -> None:
    """Entry point: generate all six populations."""
    parser = argparse.ArgumentParser(description="Generate Phase-3 persona populations.")
    parser.add_argument(
        "--populations",
        nargs="*",
        default=list(POPULATION_IDS),
        help="Population ids to generate (default: all six).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO_ROOT / "data" / "populations",
        help="Output directory (default: data/populations).",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    clients = make_provider_clients()
    registry = BioRegistry()
    quota = compute_quota()
    print_quota(quota)
    frozen_spec = build_frozen_spec(quota)
    written: list[Path] = []
    for population_id in args.populations:
        if population_id not in POPULATION_IDS:
            raise ValueError(f"Unknown population id: {population_id}")
        print(f"[generate] {population_id} (model {PROVIDERS[population_id[4]]['model']})...", flush=True)
        population = build_population(population_id, clients, registry, frozen_spec)
        path = write_population(population, args.out_dir)
        written.append(path)
        print(f"[generate] {population_id}: wrote {path} ({len(population.agents)} agents)", flush=True)

    print(f"[generate] Done. {len(written)} files written to {args.out_dir}", flush=True)
    for path in written:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        stored = data.pop("sha256")
        recomputed = sha256_of(data)
        status = "OK" if stored == recomputed else "MISMATCH"
        print(f"[sha256] {path.name}: {status}", flush=True)


if __name__ == "__main__":
    main()
