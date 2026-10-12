#!/usr/bin/env python3
"""
Headless council pilot runner — supports Ollama, OpenAI-compatible (LM Studio), and llama.cpp backends.

Usage:
    # LM Studio (default)
    python scripts/headless_council.py \
        --backend lmstudio \
        --base-url http://127.0.0.1:1234/v1 \
        --models "openai/gpt-oss-20b,qwen/qwen3.6-35b-a3b,google/gemma-4-26b-a4b" \
        --agents 15 --seed 7

    # Ollama
    python scripts/headless_council.py \
        --backend ollama \
        --base-url http://127.0.0.1:11434 \
        --models "ministral-3:3b,granite4:3b" \
        --agents 12 --seed 7

    # llama.cpp (local llama-server with GPU offload)
    python scripts/headless_council.py \
        --backend llamacpp \
        --base-url http://127.0.0.1:8080/v1 \
        --models "openai/gpt-oss-20b,google/gemma-4-26b-a4b" \
        --agents 9 --seed 42
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import os
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Ensure the fos package is importable without pip install
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

# Load .env so FOS_LLM_CONCURRENCY and other env vars are available
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from fos.backend.services.export_service import export_events
from fos.backend.services.simtree_runtime import ExperimentRunnerAdapter
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scenes.council_experiment import CouncilExperimentScene
from fos.core.llm.client import LLMClient
from fos.core.llm.generation import generate_agents_with_archetypes
from fos.core.llm_config import LLMConfig
from fos.core.simtree import SimTree
from fos.experiments.confederates import (
    ConfederateSpec,
    assign_confederates,
    build_adjacency_from_edges,
    build_confederate_lookup,
    compute_k_yes,
    confederate_neighbour_counts,
    confederate_system_prompt,
    confederate_vote_action,
    derive_placement_seed,
    permute_node_assignment,
    relabel_edges,
)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_DEMOGRAPHICS = [
    {"name": "Age", "categories": ["18-29", "30-49", "50+"]},
    {
        "name": "Political View",
        "categories": ["progressive", "moderate", "conservative"],
    },
    {
        "name": "Work Sector",
        "categories": ["public service", "private sector", "not in paid work"],
    },
]

DEFAULT_TRAITS = [
    {"name": "Openness", "mean": 50, "std": 20},
    {"name": "Conscientiousness", "mean": 50, "std": 20},
    {"name": "Extraversion", "mean": 50, "std": 20},
    {"name": "Agreeableness", "mean": 50, "std": 20},
    {"name": "Neuroticism", "mean": 50, "std": 20},
]


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProposalSpec:
    key: str
    label: str
    text: str


@dataclass(frozen=True)
class NetworkVariant:
    label: str
    network: dict[str, list[list[str]]]
    bloc_map: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BranchCsvExport:
    proposal_key: str
    proposal_label: str
    network_label: str
    csv_text: str


# ── Proposals ──────────────────────────────────────────────────────────────────


def default_proposals() -> list[ProposalSpec]:
    return [
        ProposalSpec(
            key="proposal_a",
            label="Proposal A — Solar Radiation Management Authorization",
            text=(
                "An international authority, acting under the United Nations "
                "Environment Programme, should be empowered to authorize and "
                "oversee a time-limited stratospheric aerosol injection program "
                "of up to 1 MtSO₂ per year for ten years, conditional on "
                "continuous monitoring and an emergency-halt authority."
            ),
        ),
        ProposalSpec(
            key="proposal_b",
            label="Proposal B — Global Wealth Tax and Sovereign Debt Relief",
            text=(
                "Signatory states should implement a coordinated 2% annual "
                "wealth tax on individual net assets above USD 50 million, "
                "with proceeds pooled into an International Sovereign Debt "
                "Relief Facility administered by the IMF, contingent on "
                "majority ratification by Global South debtor states."
            ),
        ),
        ProposalSpec(
            key="proposal_c",
            label="Proposal C — Lethal Autonomous Weapons Moratorium",
            text=(
                "A binding five-year international moratorium should be enacted "
                "on the development, deployment, and transfer of fully autonomous "
                "lethal weapons systems — defined as systems capable of selecting "
                "and engaging targets without human authorization — with a "
                "verification regime administered by a new UN body."
            ),
        ),
        ProposalSpec(
            key="proposal_d",
            label="Proposal D — UN Security Council Veto Abolition",
            text=(
                "The permanent veto power held by the five permanent members "
                "of the UN Security Council should be abolished and replaced by "
                "a binding 60% supermajority voting rule applicable to all "
                "member states represented on the Council."
            ),
        ),
        ProposalSpec(
            key="proposal_e",
            label="Proposal E — WHO Budget Reallocation: Pandemic vs. NCD Funding",
            text=(
                "The World Health Organization's pandemic preparedness budget "
                "should be doubled by reallocating 40% of existing member-state "
                "contributions currently designated for non-communicable disease "
                "programs, effective from the next WHO budget cycle."
            ),
        ),
        ProposalSpec(
            key="proposal_f",
            label="Proposal F — International AI Pre-Deployment Approval Body",
            text=(
                "All artificial intelligence systems exceeding a defined "
                "capability threshold should require pre-deployment approval "
                "from a new international regulatory body modeled on the "
                "International Atomic Energy Agency, with authority to mandate "
                "suspension of deployment pending review."
            ),
        ),
        ProposalSpec(
            key="proposal_g",
            label="Proposal G — Aesthetic Objectivity",
            text=(
                "The beauty or aesthetic value of an artwork is objective — "
                "some works are genuinely better than others, rather than "
                "purely a matter of individual taste."
            ),
        ),
        ProposalSpec(
            key="proposal_h",
            label="Proposal H — Personal Identity Continuity",
            text=(
                "If a machine painlessly destroyed a person's body and instantly "
                "built an exact atom-for-atom copy of them elsewhere, that copy "
                "would be the same person — the original would survive the process, "
                "rather than being replaced by a distinct copy."
            ),
        ),
        ProposalSpec(
            key="proposal_i",
            label="Proposal I — Objective Meaning of Life",
            text=(
                "Human life has an objective meaning that does not depend on "
                "what any individual believes or feels about it, rather than "
                "meaning being subjective or absent."
            ),
        ),
        ProposalSpec(
            key="proposal_j",
            label="Proposal J — Regifting Ethics",
            text=(
                "Giving an unwanted gift to someone else, without the original "
                "giver ever finding out, is ethically acceptable, rather than "
                "being a form of dishonesty toward the giver."
            ),
        ),
        ProposalSpec(
            key="proposal_k",
            label="Proposal K — Household Privacy Norms",
            text=(
                "Reading a partner's or family member's phone messages without "
                "asking is acceptable when there is no specific reason to suspect "
                "anything is wrong, rather than being a privacy violation "
                "regardless of suspicion."
            ),
        ),
        ProposalSpec(
            key="proposal_l",
            label="Proposal L — Public Space Noise Norms",
            text=(
                "Playing audio from a personal device without headphones in a "
                "shared public space, such as public transit or a park, is "
                "acceptable when kept at low volume, rather than being "
                "inconsiderate regardless of volume."
            ),
        ),
        ProposalSpec(
            key="proposal_m",
            label="Proposal M — Equal Bill-Splitting Fairness",
            text=(
                "When a group dines together, splitting the bill equally among "
                "all participants is fairer than each person paying for exactly "
                "what they ordered."
            ),
        ),
        ProposalSpec(
            key="proposal_n",
            label="Proposal N — Shared Workplace Mandate",
            text=(
                "Organizations should require employees to work together in a "
                "shared physical workplace rather than allowing full remote work."
            ),
        ),
    ]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def _write_progress(output_dir: Path, data: dict) -> None:
    """Write a progress JSON file to the output directory."""
    path = output_dir / ".progress.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _shuffle_agent_names(agent_names: list[str], seed: int) -> list[str]:
    rng = random.Random(seed + 999)
    shuffled = list(agent_names)
    rng.shuffle(shuffled)
    return shuffled


def _make_edge(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def _json_get(base_url: str, route: str) -> dict[str, Any]:
    """Fetch one JSON response from an HTTP endpoint."""
    url = base_url.rstrip("/") + route
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Model verification ────────────────────────────────────────────────────────


def ensure_models_available(
    backend: str, base_url: str, model_names: list[str]
) -> None:
    """Verify all requested models are available on the backend."""
    if backend == "ollama":
        _verify_ollama_models(base_url, model_names)
    elif backend == "llamacpp":
        _verify_llamacpp_models(base_url, model_names)
    elif backend in ("openai", "lmstudio"):
        _verify_openai_models(base_url, model_names)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def _warmup_models(
    backend: str, base_url: str, model_names: list[str], temperature: float
) -> None:
    # Warm both llama-server ports for dual-server operation
    _dual_warmup(backend, base_url, model_names, temperature)
    return

def _dual_warmup(
    backend: str, base_url: str, model_names: list[str], temperature: float
) -> None:
    """Warm the first model on each unique port."""
    if backend != "llamacpp":
        return
    warmed_ports: set[int] = set()
    for model in model_names:
        port = _MODEL_PORT_MAP.get(model, 8080)
        if port in warmed_ports:
            continue
        warmed_ports.add(port)
        # Build a per-port base_url
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(base_url)
        port_url = urlunparse((parsed.scheme, f"{parsed.hostname}:{port}", parsed.path, parsed.params, parsed.query, parsed.fragment))
        _warmup_single_model(backend, model, port_url, temperature)
    return

def _warmup_single_model(backend, model_name, base_url, temperature):
    """Warm a single model via the model_manager."""
    import time as _time
    import requests as _requests
    
    router_model = _LLAMACPP_ROUTER_MAP.get(model_name, model_name)
    router_base = "http://127.0.0.1:8081"  # model_manager control port
    load_url = f"{router_base}/models/load"
    
    from urllib.parse import urlparse
    port = urlparse(base_url).port
    print(f"   Warming {model_name} on port {port} ... ", end="", flush=True)
    
    try:
        resp = _requests.post(
            load_url,
            json={"model": router_model, "port": port},
            timeout=300,
        )
        if resp.status_code == 200:
            print("load accepted", end=" ... ", flush=True)
        elif resp.status_code == 400 and "already running" in resp.text:
            print("already running", end=" ... ", flush=True)
        else:
            print(f"load returned {resp.status_code}", end=" ... ", flush=True)
    except Exception as exc:
        print(f"load failed: {exc}", end=" ... ", flush=True)
    
    # Poll /models until loaded
    models_url = f"{router_base}/models"
    poll_interval = 2.0
    timeout = 300.0
    deadline = _time.time() + timeout
    loaded = False
    while _time.time() < deadline and not loaded:
        try:
            resp = _requests.get(models_url, timeout=10)
            if resp.status_code == 200:
                for m in resp.json().get("data", []):
                    m_name = m.get("id", "")
                    m_status = m.get("status", {})
                    status_val = m_status.get("value", "") if isinstance(m_status, dict) else str(m_status)
                    if m_name == router_model and status_val == "loaded":
                        loaded = True
                        break
            _time.sleep(poll_interval)
        except Exception:
            _time.sleep(poll_interval)
    
    if loaded:
        print(f"ready ({_time.time() - (deadline - timeout):.0f}s)")
    else:
        print("timed out")
    
    # Warmup chat
    client = make_client(backend, model_name, base_url, temperature)
    try:
        client.chat([{"role": "user", "content": "Say 'ready'."}], json_mode=False)
        print(f"   Warmup chat OK")
    except Exception as exc:
        print(f"   Warmup chat failed: {exc}")




# Router model name mapping (FOS name → GGUF filename without .gguf)
_LLAMACPP_ROUTER_MAP = {
    "openai/gpt-oss-20b": "gpt-oss-20b",
    "gpt-oss-20b": "gpt-oss-20b",
    "google/gemma-4-26b-a4b": "gemma-4-26b-a4b",
    "gemma-4-26b-a4b": "gemma-4-26b-a4b",
    "qwen/qwen3.6-35b-a3b": "qwen3.6-35b-a3b",
    "gemma4-26b-a4b-uncensored-hauhaucs-balanced": "gemma4-26b-a4b-uncensored",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive": "qwen3.6-35b-a3b-uncensored",
}

# Maps FOS model names to llama-server ports for dual-server operation.
# Server A (8080): gpt-oss + qwen (largest+smallest, 50 GB total)
# Server B (8082): qwen-unc + gemma + gemma-unc (59 GB total)
_MODEL_PORT_MAP: dict[str, int] = {
    "openai/gpt-oss-20b": 8080,
    "qwen/qwen3.6-35b-a3b": 8080,
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive": 8082,
    "google/gemma-4-26b-a4b": 8082,
    "gemma4-26b-a4b-uncensored-hauhaucs-balanced": 8082,
}

def _verify_llamacpp_models(base_url: str, model_names: list[str]) -> None:
    """Verify all requested models are available via the router's /models endpoint."""
    # The router serves /models (not /v1/models) on the same port as the API
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/v1"):
        clean_url = clean_url[:-3]
    try:
        payload = _json_get(clean_url, "/models")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"llama.cpp router unreachable at {clean_url}/models: {exc}"
        ) from exc
    # The router /models endpoint returns a list of model IDs
    models = payload if isinstance(payload, list) else payload.get("data", [])
    available = set()
    for m in models:
        if isinstance(m, str):
            available.add(m)
        elif isinstance(m, dict):
            available.add(str(m.get("id", "")))
    missing = [n for n in model_names if _LLAMACPP_ROUTER_MAP.get(n, n) not in available]
    if missing:
        # With model switching, not all models are pre-loaded — emit a warning
        # instead of a hard error. The runner loads models on demand via _preload_model.
        print(f"  ⚠ {len(missing)} of {len(model_names)} models not currently loaded "
              f"(runner will load on demand): {', '.join(missing)}")
        print(f"     Currently loaded: {', '.join(sorted(available))}")
    else:
        print(f"  ✓ All {len(model_names)} models present on llama.cpp router")


def _verify_ollama_models(base_url: str, model_names: list[str]) -> None:
    """Check Ollama /api/tags for model availability."""
    try:
        payload = _json_get(base_url, "/api/tags")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama unreachable at {base_url}: {exc}") from exc

    installed = {str(m["name"]) for m in payload.get("models", [])}
    missing = [n for n in model_names if n not in installed]
    if missing:
        raise RuntimeError(f"Missing Ollama models: {', '.join(missing)}")
    print(f"  ✓ All {len(model_names)} Ollama models present")


def _verify_openai_models(base_url: str, model_names: list[str]) -> None:
    """Check OpenAI-compatible /v1/models for model availability."""
    # Strip /v1 from base_url if present to avoid double /v1/v1/models
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/v1"):
        clean_url = clean_url[:-3]
    try:
        payload = _json_get(clean_url, "/v1/models")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"OpenAI-compatible endpoint unreachable at {base_url}: {exc}"
        ) from exc

    installed = {str(m.get("id", "")) for m in payload.get("data", [])}
    missing = [n for n in model_names if n not in installed]
    if missing:
        raise RuntimeError(
            f"Missing models: {', '.join(missing)}\n"
            f"Available: {', '.join(sorted(installed))}"
        )
    print(f"  ✓ All {len(model_names)} models present")


# ── Client creation ────────────────────────────────────────────────────────────


def make_client(
    backend: str, model_name: str, base_url: str, temperature: float
) -> LLMClient:
    """Create an LLMClient for the given backend and model."""
    from fos.core.llm_config import LLMConfig
    # Translate FOS model identifiers to GGUF filenames for llama.cpp router
    if backend == "llamacpp":
        model_name = _LLAMACPP_ROUTER_MAP.get(model_name, model_name)
    
    config = LLMConfig(
        dialect="ollama" if backend == "ollama" else "openai",
        model=model_name,
        base_url=base_url,
        api_key=os.getenv("OPENAI_API_KEY", "not-needed"),
        temperature=temperature,
    )
    return LLMClient(config)


def make_deepseek_client() -> LLMClient:
    """Create a DeepSeek API client for profile generation only."""
    from fos.core.llm_config import LLMConfig

    config = LLMConfig(
        dialect="openai",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        temperature=0.7,
    )
    return LLMClient(config)


# ── Agent building ─────────────────────────────────────────────────────────────


def _generated_agent_to_config(agent: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(agent["name"]),
        "role_prompt": str(agent.get("profile") or ""),
        "properties": dict(agent.get("properties") or {}),
    }


def build_agents(
    backend: str,
    base_url: str,
    model_names: list[str],
    temperature: float,
    total_agents: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Generate demographic agents and distribute models across them."""
    # Use DeepSeek API for profile generation, NOT a local decision-making model
    generator_client = make_deepseek_client()
    print(f"   Profile generator: DeepSeek API (deepseek-v4-flash)")

    random_state = random.getstate()
    random.seed(seed)
    try:
        generated = generate_agents_with_archetypes(
            total_agents=total_agents,
            demographics=DEFAULT_DEMOGRAPHICS,
            archetype_probabilities={},
            traits=DEFAULT_TRAITS,
            llm_client=generator_client,
            language="en",
            timeout=120,
        )
    finally:
        random.setstate(random_state)

    agents: list[dict[str, Any]] = []
    agents_per_model = total_agents // len(model_names)
    for idx, agent in enumerate(generated):
        config_agent = _generated_agent_to_config(agent)
        # Block assignment: consecutive agents share the same model,
        # so LM Studio only switches models every N agents, not every agent.
        model_idx = idx // agents_per_model
        if model_idx >= len(model_names):
            model_idx = len(model_names) - 1
        model_name = model_names[model_idx]
        config_agent["provider_id"] = f"provider_{model_idx}"
        config_agent["llm_config"] = _make_agent_llm_config(
            backend, model_name, base_url, temperature
        )
        agents.append(config_agent)
    return agents


def _make_agent_llm_config(
    backend: str, model_name: str, base_url: str, temperature: float
) -> dict[str, Any]:
    """Build the per-agent llm_config dict.
    For llamacpp backend, uses _MODEL_PORT_MAP to route agents to the
    correct llama-server port (8080 or 8082) for dual-server operation.
    """
    if backend == "llamacpp":
        # Map to router model name and correct port
        port = _MODEL_PORT_MAP.get(model_name, 8080)
        router_model = _LLAMACPP_ROUTER_MAP.get(model_name, model_name)
        # Rewrite base_url to point to the correct port
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(base_url)
        ported_base = urlunparse((parsed.scheme, f"{parsed.hostname}:{port}", parsed.path, parsed.params, parsed.query, parsed.fragment))
        return {
            "dialect": "openai",
            "model": router_model,
            "base_url": ported_base,
            "api_key": os.getenv("OPENAI_API_KEY", "lm-studio"),
            "temperature": temperature,
        }
    if backend == "ollama":
        return {
            "dialect": "ollama",
            "model": model_name,
            "base_url": base_url,
            "temperature": temperature,
        }
    else:
        return {
            "dialect": "openai",
            "model": model_name,
            "base_url": base_url,
            "api_key": os.getenv("OPENAI_API_KEY", "lm-studio"),
            "temperature": temperature,
        }


# ── Network generation ────────────────────────────────────────────────────────


def _build_watts_strogatz_edges(
    agent_names: list[str], seed: int, k: int = 6, p: float = 0.1
) -> tuple[list[list[str]], dict[str, int]]:
    """Build edges with the Watts-Strogatz small-world model.

    Each node starts on a ring connected to its k nearest neighbours (k/2 on
    each side), then every lattice edge is rewired to a random other node
    with probability p. Self-loops and duplicate edges are dropped. k should
    be even so the lattice is regular; the configs in Phase 3 use k=6 or 8.
    """
    shuffled = _shuffle_agent_names(agent_names, seed)
    rng = random.Random(seed)
    n = len(shuffled)
    half = k // 2
    edges: set[tuple[str, str]] = set()
    # Ring lattice: connect each node to the next `half` nodes on each side.
    for idx in range(n):
        for step in range(1, half + 1):
            edges.add(_make_edge(shuffled[idx], shuffled[(idx + step) % n]))
    # Rewire each lattice edge with probability p.
    # Iterate in sorted order so the result is identical across runs
    # (set iteration order depends on string hashes).
    for left, right in sorted(edges):
        if rng.random() < p:
            edges.discard(_make_edge(left, right))
            candidates = [
                x
                for x in shuffled
                if x != left and x != right and _make_edge(left, x) not in edges
            ]
            if candidates:
                edges.add(_make_edge(left, rng.choice(candidates)))
            else:
                edges.add(_make_edge(left, right))
    return [list(e) for e in sorted(edges)], {}


def _build_small_world_edges(agent_names: list[str], seed: int) -> tuple[list[list[str]], dict[str, int]]:
    shuffled = _shuffle_agent_names(agent_names, seed)
    rng = random.Random(seed)
    edges: set[tuple[str, str]] = set()
    count = len(shuffled)
    for idx, name in enumerate(shuffled):
        for step in (1,):  # k=2: one neighbour each direction
            neighbor = shuffled[(idx + step) % count]
            edges.add(_make_edge(name, neighbor))
    for _ in range(max(1, count // 2)):
        left, right = rng.sample(shuffled, 2)
        edges.add(_make_edge(left, right))

    # Minimum 1-edge guarantee
    degree = Counter(n for pair in edges for n in pair)
    for agent in agent_names:
        if degree.get(agent, 0) == 0:
            partner = rng.choice([n for n in agent_names if n != agent])
            edges.add(_make_edge(agent, partner))

    return [list(e) for e in sorted(edges)], {}


def _pick_weighted_name(
    rng: random.Random,
    agent_names: list[str],
    degree_map: dict[str, int],
    blocked: set[str],
) -> str:
    choices = [n for n in agent_names if n not in blocked]
    weights = [degree_map.get(n, 0) + 1 for n in choices]
    return rng.choices(choices, weights=weights, k=1)[0]


def _neighbours_of(node: str, edges: set[tuple[str, str]], blocked: set[str]) -> list[str]:
    """Return the names directly connected to node, skipping blocked names."""
    found: list[str] = []
    for left, right in edges:
        if left == node and right not in blocked:
            found.append(right)
        elif right == node and left not in blocked:
            found.append(left)
    return sorted(found)


def _build_holme_kim_edges(
    agent_names: list[str], seed: int, m: int = 3, p_triad: float = 0.5
) -> tuple[list[list[str]], dict[str, int]]:
    """Build edges with the Holme-Kim growing network model.

    The first three nodes form a triangle, then every new node adds exactly
    m edges. The first target is picked by preferential attachment (weight =
    degree + 1). Each later target is picked uniformly from the neighbours of
    the previous target with probability p_triad, otherwise by preferential
    attachment (falling back to preferential attachment when the previous
    target has no eligible neighbours). No extra edges are ever added, so the
    mean degree stays close to 2*m no matter what p_triad is.
    """
    shuffled = _shuffle_agent_names(agent_names, seed)
    rng = random.Random(seed)
    edges: set[tuple[str, str]] = set()
    degree_map = dict.fromkeys(agent_names, 0)

    # Seed triangle on the first three nodes.
    for left, right in (
        (shuffled[0], shuffled[1]),
        (shuffled[1], shuffled[2]),
        (shuffled[0], shuffled[2]),
    ):
        edges.add(_make_edge(left, right))
        degree_map[left] += 1
        degree_map[right] += 1

    for idx in range(3, len(shuffled)):
        new_name = shuffled[idx]
        placed = shuffled[:idx]
        chosen: list[str] = []
        while len(chosen) < m:
            if chosen and rng.random() < p_triad:
                neighbours = _neighbours_of(chosen[-1], edges, set(chosen))
                if neighbours:
                    chosen.append(rng.choice(neighbours))
                    continue
            available = [n for n in placed if n not in chosen]
            if not available:
                # Every placed node is already chosen (early on, when there
                # are fewer placed nodes than m). Connect to any placed node;
                # duplicate edges are dropped by the edge set.
                chosen.append(rng.choice(placed))
                continue
            chosen.append(_pick_weighted_name(rng, placed, degree_map, set(chosen)))
        for target in chosen:
            edges.add(_make_edge(new_name, target))
            degree_map[new_name] += 1
            degree_map[target] += 1

    return [list(e) for e in sorted(edges)], {}


def _build_sbm_edges(
    agent_names: list[str],
    seed: int,
    n_blocks: int | None = None,
    block_sizes: list[int] | None = None,
    p_in: float | None = None,
    p_out: float | None = None,
) -> tuple[list[list[str]], dict[str, int]]:
    """Stochastic block model with caller-chosen or random blocs.

    With no block arguments this keeps the original behaviour: bloc count
    max(3, N // 5), sizes drawn from a Gaussian, within-bloc edge
    probability 40% and cross-bloc 5%. When n_blocks/block_sizes/p_in/p_out
    are given (as in the Phase 3 config grid), those values are used
    instead. Agents are randomly assigned to blocs in both cases.
    Returns (edges, bloc_map).
    """
    rng = random.Random(seed)
    n = len(agent_names)

    shuffled = list(agent_names)
    rng.shuffle(shuffled)
    if block_sizes is None:
        target_blocs = max(3, n // 5)
        # Generate uneven bloc sizes summing to n
        sizes: list[int] = []
        remaining = n
        for b in range(target_blocs, 0, -1):
            if b == 1:
                sizes.append(remaining)
            else:
                mean = remaining / b
                size = max(
                    1,
                    min(remaining - (b - 1), round(rng.gauss(mean, max(1, mean * 0.3)))),
                )
                sizes.append(size)
                remaining -= size
    else:
        if sum(block_sizes) != n or (n_blocks is not None and len(block_sizes) != n_blocks):
            raise ValueError(
                f"block_sizes must sum to {n} and match n_blocks: "
                f"sum={sum(block_sizes)} n_blocks={n_blocks} len={len(block_sizes)}"
            )
        sizes = list(block_sizes)
    if p_in is None:
        p_in = 0.40
    if p_out is None:
        p_out = 0.05

    # Assign agents to blocs
    bloc_of: dict[str, int] = {}
    idx = 0
    for b_idx, size in enumerate(sizes):
        for _ in range(size):
            bloc_of[shuffled[idx]] = b_idx
            idx += 1

    # Generate edges
    edges: set[tuple[str, str]] = set()
    all_agents = list(agent_names)
    for i, a in enumerate(all_agents):
        for b in all_agents[i + 1:]:
            if bloc_of[a] == bloc_of[b]:
                if rng.random() <= p_in:
                    edges.add(_make_edge(a, b))
            else:
                if rng.random() <= p_out:
                    edges.add(_make_edge(a, b))

    # Minimum 1-edge guarantee
    degree = Counter(n for pair in edges for n in pair)
    for agent in agent_names:
        if degree.get(agent, 0) == 0:
            # Prefer connecting within own bloc first
            same = [n for n in agent_names if n != agent and bloc_of.get(n) == bloc_of.get(agent)]
            if same:
                partner = rng.choice(same)
            else:
                partner = rng.choice([n for n in agent_names if n != agent])
            edges.add(_make_edge(agent, partner))

    edge_list = [list(e) for e in sorted(edges)]
    return edge_list, bloc_of


def build_network_variants(agent_names: list[str], seed: int) -> list[NetworkVariant]:
    sw_edges, _ = _build_small_world_edges(agent_names, seed)
    hk_edges, _ = _build_holme_kim_edges(agent_names, seed + 1)
    sbm_edges, sbm_bloc_map = _build_sbm_edges(agent_names, seed + 2)
    return [
        NetworkVariant(
            "small_world",
            {"edges": sw_edges},
        ),
        NetworkVariant(
            "holme_kim",
            {"edges": hk_edges},
        ),
        NetworkVariant(
            "sbm",
            {"edges": sbm_edges, "bloc_map": sbm_bloc_map},
        ),
    ]


# ── Scene builder ──────────────────────────────────────────────────────────────


def _build_council_scene(
    agents: list[dict[str, Any]],
    proposal: ProposalSpec,
    network: dict[str, list[list[str]]],
) -> CouncilExperimentScene:
    return CouncilExperimentScene(
        ExperimentConfig(
            scenario_id="council_chamber",
            agents=agents,
            actions=[],
            parameters={
                "proposal_text": proposal.text,
                "deliberation_rounds": 3,
                "voting_threshold": 0.5,
            },
            description=proposal.label,
            social_network=network,
            locale="en",
        )
    )


def _node_logs_to_export_events(
    node_id: int, node_logs: list[dict[str, Any]],
    agent_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for seq, log in enumerate(node_logs):
        log_data = dict(log.get("data") or {})
        # Enrich with per-agent metadata (model, archetype, Big Five, degree)
        if agent_meta is not None:
            agent_name = log_data.get("agent", "")
            if agent_name and agent_name in agent_meta:
                log_data.update(agent_meta[agent_name])
        events.append(
            {
                "sequence": seq,
                "tree_node_id": node_id,
                "event_type": log.get("type"),
                "payload": log_data,
                "created_at": log.get("timestamp") or log_data.get("created_at") or "",
            }
        )
    return events


def combine_branch_csv_exports(exports: list[BranchCsvExport]) -> str:
    combined_rows: list[dict[str, str]] = []
    base_fieldnames: list[str] = []
    for exp in exports:
        reader = csv.DictReader(io.StringIO(exp.csv_text))
        if reader.fieldnames and not base_fieldnames:
            base_fieldnames = list(reader.fieldnames)
        for row in reader:
            combined_rows.append(
                {
                    "proposal_key": exp.proposal_key,
                    "proposal_label": exp.proposal_label,
                    "network_label": exp.network_label,
                    **{k: str(v or "") for k, v in row.items()},
                }
            )

    fieldnames = ["proposal_key", "proposal_label", "network_label", *base_fieldnames]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(combined_rows)
    return output.getvalue()


# ── Main pilot runner ─────────────────────────────────────────────────────────


def run_headless_council(
    output_dir: Path,
    backend: str,
    base_url: str,
    model_names: list[str],
    total_agents: int = 15,
    seed: int = 7,
    temperature: float = 0.7,
    proposals: list[ProposalSpec] | None = None,
    network_name: str = "small_world",
    placement_seed: int | None = None,
    confederate_speech: str = "llm",
) -> dict[str, Any]:
    """Run the full council pilot with the specified backend."""
    print(f"\n{'=' * 60}")
    print("  Headless Council Pilot")
    print(f"  Backend:    {backend}")
    print(f"  Base URL:   {base_url}")
    print(f"  Models:     {', '.join(model_names)}")
    print(
        f"  Agents:     {total_agents} ({total_agents // len(model_names)} per model)"
    )
    print(f"  Seed:       {seed}")
    print(f"  Output:     {output_dir.resolve()}")
    print(f"{'=' * 60}\n")

    from profiling import start_profiler
    start_profiler(output_dir / "council_timing.txt")

    # 1. Verify models
    print("1. Checking model availability...")
    ensure_models_available(backend, base_url, model_names)

    # 1.5 Pre-warm first model (runner handles subsequent model switches)
    if len(model_names) > 1:
        print("1.5. Pre-warming first model (runner handles switches)...")
        _warmup_models(backend, base_url, model_names, temperature)

    # 2. Generate agents
    print("2. Generating agent profiles...")
    agents = build_agents(
        backend=backend,
        base_url=base_url,
        model_names=model_names,
        temperature=temperature,
        total_agents=total_agents,
        seed=seed,
    )
    agent_names = [str(a["name"]) for a in agents]
    print(f"   ✓ Generated {len(agents)} agents")

    # 3. Build networks
    print("3. Building network variants...")
    networks = build_network_variants(agent_names, seed)
    networks = [n for n in networks if n.label == network_name]
    if not networks:
        raise ValueError(f"Network '{network_name}' not found")

    # DeepSeek API client for profile generation only.
    # Decision-making models are the 5 local models from agent_llm_clients,
    # built via _make_agent_llm_config() which uses _LLAMACPP_ROUTER_MAP.
    # DeepSeek is NOT in MODEL_NAMES or _LLAMACPP_ROUTER_MAP — it is
    # only used for _generate_agents profile creation, never for voting.
    generator_client = make_deepseek_client()
    print(f"   Profile generator: DeepSeek API (deepseek-v4-flash)")

    selected_proposals = proposals or default_proposals()

    combined_exports: list[BranchCsvExport] = []
    summary: dict[str, Any] = {
        "backend": backend,
        "base_url": base_url,
        "seed": seed,
        "temperature": temperature,
        "agent_count": total_agents,
        "models": model_names,
        "runs": [],
    }
    summary["networks"] = {
        nw.label: nw.network.get("edges", []) for nw in networks
    }

    total_branches = len(selected_proposals) * len(networks)
    branch_num = 0

    _write_progress(output_dir, {
        "status": "initialized",
        "total_branches": total_branches,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    # Base seed for per-run placement derivation
    _base_placement_seed = placement_seed if placement_seed is not None else seed + 1000

    for proposal in selected_proposals:
        print(f"\n4. Running: {proposal.label}")
        scene = _build_council_scene(agents, proposal, {"edges": []})
        adapter = ExperimentRunnerAdapter(
            scene, {"chat": generator_client, "default": generator_client}
        )
        tree = SimTree.new(adapter, adapter.clients)
        root_id = tree.root
        if root_id is None:
            raise RuntimeError("SimTree root is None — cannot proceed")

        for network in networks:
            branch_num += 1

            # ── PER-RUN PLACEMENT ──
            # Derive seed, permute node positions, relabel network edges.
            # Agent identity (persona + model) is PERMANENT across runs.
            run_placement_seed = derive_placement_seed(
                _base_placement_seed, proposal.key, network.label, branch_num
            )
            placement_rng = random.Random(run_placement_seed)

            # 1. Permute agent → node assignment
            agent_names = [str(a["name"]) for a in agents]
            permuted = permute_node_assignment(agent_names, placement_rng)
            # node_of[agent] = position index in this run
            node_of: dict[str, int] = {name: idx for idx, name in enumerate(permuted)}

            # 2. Relabel network edges through the permutation
            original_edges = network.network.get("edges", [])
            relabeled_edges = relabel_edges(original_edges, agent_names, permuted)

            # 3. Confederate assignment (on canonical agent ids)
            conf_specs = assign_confederates(
                agent_names,
                n_yes=3,
                n_no=3,
                rng=placement_rng,
                speech_mode=confederate_speech,
            )
            conf_lookup = build_confederate_lookup(conf_specs)
            conf_yes_ids = [s.agent_id for s in conf_specs if s.stance == "yes"]
            conf_no_ids = [s.agent_id for s in conf_specs if s.stance == "no"]
            print(
                f"   [{branch_num}/{total_branches}] Network: {network.label} ... ",
                end="",
                flush=True,
            )
            print(f'confederates yes={conf_yes_ids} no={conf_no_ids} placement_seed={run_placement_seed}', end="", flush=True)

            # 4. Build per-run agent configs — deepcopy to preserve originals (Bug 2 fix)
            run_agents = copy.deepcopy(agents)

            # 5. Inject confederate system prompts (on per-run copy)
            for agent_config in run_agents:
                agent_name = agent_config.get("name", "")
                if agent_name in conf_lookup:
                    spec = conf_lookup[agent_name]
                    if spec.speech_mode == "llm":
                        conf_prompt = confederate_system_prompt(spec, proposal.text)
                        existing_role = agent_config.get("role_prompt", "")
                        agent_config["role_prompt"] = conf_prompt + ("\n\n" + existing_role if existing_role else "")

            # 5. Build agent_meta_base — agent identity is STABLE across runs
            agent_meta_base = {}
            for agent_config in agents:
                name = agent_config["name"]
                props = agent_config.get("properties") or {}
                model_name = (agent_config.get("llm_config") or {}).get("model", "unknown")
                agent_meta_base[name] = {
                    "model": model_name,
                    "archetype_id": props.get("archetype_id", ""),
                    "archetype_label": props.get("archetype_label", ""),
                    "Openness": int(round(props.get("Openness", 0))),
                    "Conscientiousness": int(round(props.get("Conscientiousness", 0))),
                    "Extraversion": int(round(props.get("Extraversion", 0))),
                    "Agreeableness": int(round(props.get("Agreeableness", 0))),
                    "Neuroticism": int(round(props.get("Neuroticism", 0))),
                }

            # 6. Register confederates with the scene
            scene.set_confederates(conf_specs)

            # Build relabeled network dict for this run
            run_network = dict(network.network)
            run_network["edges"] = relabeled_edges
            branch_id = tree.branch(
                root_id,
                [{"op": "network_replace", "network": run_network}],
            )

            _write_progress(output_dir, {
                "status": "running",
                "branch": branch_num,
                "total_branches": total_branches,
                "proposal": proposal.label,
                "network": network.label,
                "branch_started_at": datetime.now(timezone.utc).isoformat(),
            })

            finished_id = tree.advance(branch_id, turns=4)

            node = tree.nodes[finished_id]
            node_logs = list(node.get("logs") or [])
            scenario_params = {
                "scenario_id": "council_chamber",
                "proposal_text": proposal.text,
                "deliberation_rounds": 3,
                "voting_threshold": 0.5,
            }
            # Compute per-agent degree from RELABELED edges (the node they occupied)
            edge_flat: list[str] = [n for pair in relabeled_edges for n in pair]
            degree_counter = Counter(edge_flat)
            bloc_map = network.network.get("bloc_map", {})
            branch_meta: dict[str, dict[str, Any]] = {}
            for agent_name, base in agent_meta_base.items():
                entry = dict(base)
                entry["agent_uid"] = agent_name  # stable identity
                entry["node_label"] = node_of.get(agent_name, -1)  # position in this run
                entry["degree"] = degree_counter.get(agent_name, 0)  # degree at occupied node
                entry["network_label"] = network.label
                entry["bloc_id"] = bloc_map.get(agent_name, -1)
                # Confederate columns
                entry["is_confederate"] = agent_name in conf_lookup
                entry["confederate_stance"] = conf_lookup[agent_name].stance if agent_name in conf_lookup else ""
                entry["placement_seed"] = run_placement_seed
                branch_meta[agent_name] = entry

            # Compute confederate neighbour counts from network edges
            adjacency = build_adjacency_from_edges(relabeled_edges)
            conf_neighbour_counts = confederate_neighbour_counts(adjacency, conf_specs)
            for agent_name in agent_names:
                if agent_name in branch_meta:
                    cnts = conf_neighbour_counts.get(agent_name, {"conf_yes": 0, "conf_no": 0, "conf_total": 0})
                    branch_meta[agent_name]["conf_yes_neighbours"] = cnts["conf_yes"]
                    branch_meta[agent_name]["conf_no_neighbours"] = cnts["conf_no"]

            # Compute k_yes_incl_conf / k_yes_excl_conf from final votes
            final_votes = scene.state.extensions.get("votes", {})
            conf_ids = {s.agent_id for s in conf_specs}
            k_yes_counts = compute_k_yes(adjacency, final_votes, conf_ids)
            for agent_name in agent_names:
                if agent_name in branch_meta:
                    kc = k_yes_counts.get(agent_name, {"k_yes_incl_conf": 0, "k_yes_excl_conf": 0})
                    branch_meta[agent_name]["k_yes_incl_conf"] = kc["k_yes_incl_conf"]
                    branch_meta[agent_name]["k_yes_excl_conf"] = kc["k_yes_excl_conf"]

            csv_text = export_events(
                _node_logs_to_export_events(finished_id, node_logs, agent_meta=branch_meta),
                scenario_params,
                "csv",
            )
            branch_export = BranchCsvExport(
                proposal_key=proposal.key,
                proposal_label=proposal.label,
                network_label=network.label,
                csv_text=csv_text,
            )
            combined_exports.append(branch_export)
            summary["runs"].append(
                {
                    "proposal_key": proposal.key,
                    "proposal_label": proposal.label,
                    "network_label": network.label,
                    "node_id": finished_id,
                    "log_count": len(node_logs),
                    "edges": relabeled_edges,
                    "placement_seed": run_placement_seed,
                    "node_permutation": permuted,  # permuted[i] = agent at node i
                    "confederates": [
                        {"agent_id": s.agent_id, "stance": s.stance}
                        for s in conf_specs
                    ],
                }
            )
            print(f"done ({len(node_logs)} events)")

            _write_progress(output_dir, {
                "status": "branch_complete",
                "branch": branch_num,
                "total_branches": total_branches,
                "proposal": proposal.label,
                "network": network.label,
                "events": len(node_logs),
            })

    _write_progress(output_dir, {
        "status": "complete",
        "total_branches": total_branches,
        "branches_completed": branch_num,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })

    # 5. Export
    print("\n5. Exporting results...")
    summary["confederates"] = {
        "specs": [{"agent_id": s.agent_id, "stance": s.stance, "speech_mode": s.speech_mode} for s in conf_specs],
        "confederate_speech": confederate_speech,
        "note": "per-run placement_seed recorded in summary.runs[].placement_seed",
    }
    combined_csv = combine_branch_csv_exports(combined_exports)
    _write_text(output_dir / "combined_results.csv", combined_csv)
    _write_text(output_dir / "summary.json", json.dumps(summary, indent=2))
    print(f"   ✓ {output_dir / 'combined_results.csv'}")
    print(f"   ✓ {output_dir / 'summary.json'}")

    print(f"\n{'=' * 60}")
    print(f"  Complete! {len(summary['runs'])} branches run.")
    print(f"  Results: {output_dir.resolve()}")
    print(f"{'=' * 60}\n")

    return summary


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Headless council pilot — Ollama & OpenAI-compatible backends"
    )
    parser.add_argument(
        "--backend",
        choices=["ollama", "openai", "lmstudio", "llamacpp"],
        default="lmstudio",
        help="LLM backend type (default: lmstudio)",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:1234/v1",
        help="Backend base URL (default: http://127.0.0.1:1234/v1)",
    )
    parser.add_argument(
        "--models",
        default="openai/gpt-oss-20b,qwen/qwen3.6-35b-a3b,"
        "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive,"
        "google/gemma-4-26b-a4b,"
        "gemma4-26b-a4b-uncensored-hauhaucs-balanced",
        help="Comma-separated model names",
    )
    parser.add_argument(
        "--agents", type=int, default=15, help="Total agents (default: 15)"
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed (default: 7)")
    parser.add_argument(
        "--temperature", type=float, default=0.7, help="LLM temperature (default: 0.7)"
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/headless_council_run",
        help="Output directory (default: artifacts/headless_council_run)",
    )
    parser.add_argument(
        "--proposals",
        nargs="+",
        choices=["all", "srma", "wealth-tax", "laws", "un-veto", "who-budget", "ai-approval", "aesthetic-objectivity", "identity-continuity", "meaning-of-life", "regifting", "privacy-norms", "public-noise", "bill-splitting", "remote-work"],
        default=["all"],
        help="Which proposals to run. Pass multiple names to run specific ones, e.g. --proposals srma wealth-tax un-veto (default: all)",
    )
    parser.add_argument(
        "--network",
        choices=["small_world", "holme_kim", "sbm"],
        default="small_world",
        help="Network topology (default: small_world)",
    )
    parser.add_argument(
        "--confederate-speech",
        choices=["llm", "scripted"],
        default="llm",
        help="How confederates produce deliberation messages (default: llm)",
    )
    parser.add_argument(
        "--placement-seed",
        type=int,
        default=None,
        help="Seed for confederate placement randomisation (default: seed+1000)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Max concurrent LLM calls (overrides FOS_LLM_CONCURRENCY env var). Set to 1 to force sequential model loading.",
    )
    args = parser.parse_args()

    model_names = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_names:
        parser.error("At least one model required (--models)")

    # Apply backend-specific default base_url
    if args.backend == "llamacpp" and args.base_url == "http://127.0.0.1:1234/v1":
        args.base_url = "http://127.0.0.1:8080/v1"

    # Apply concurrency setting before the runner creates its semaphore
    if args.concurrency is not None:
        os.environ["FOS_LLM_CONCURRENCY"] = str(args.concurrency)

    output_dir = Path(args.output_dir)

    # Keep the per-run LLM traffic log under the local data repo (artifacts/<run-name>/)
    # unless the caller already exported FOS_LLM_LOG explicitly.
    os.environ.setdefault(
        "FOS_LLM_LOG",
        str(
            Path(os.environ.get("FOS_DATA_DIR") or os.path.expanduser("~/work/fos-data"))
            / "artifacts"
            / output_dir.name
            / "llm_traffic.jsonl"
        ),
    )

    # Select proposals
    all_props = default_proposals()
    proposal_map = {
        "srma": [all_props[0]],
        "wealth-tax": [all_props[1]],
        "laws": [all_props[2]],
        "un-veto": [all_props[3]],
        "who-budget": [all_props[4]],
        "ai-approval": [all_props[5]],
        "aesthetic-objectivity": [all_props[6]],
        "identity-continuity": [all_props[7]],
        "meaning-of-life": [all_props[8]],
        "regifting": [all_props[9]],
        "privacy-norms": [all_props[10]],
        "public-noise": [all_props[11]],
        "bill-splitting": [all_props[12]],
        "remote-work": [all_props[13]],
    }
    if "all" in args.proposals:
        proposals = all_props
    else:
        proposals = []
        for name in args.proposals:
            proposals.extend(proposal_map.get(name, []))

    run_headless_council(
        output_dir=output_dir,
        backend=args.backend,
        base_url=args.base_url,
        model_names=model_names,
        total_agents=args.agents,
        seed=args.seed,
        temperature=args.temperature,
        proposals=proposals,
        network_name=args.network,
        placement_seed=args.placement_seed,
        confederate_speech=args.confederate_speech,
    )


if __name__ == "__main__":
    main()
