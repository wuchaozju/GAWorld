"""
LLM client wrappers and factories for the checkpointed runner.

Builds the clients dict the FOS adapter expects and, in the test path, wraps
the injected fake client in a TrackedClient that records every chat call so
the runner can later attribute prompts to agents and rounds.

Functions:
    TrackedClient      — records every chat call and splits calls by round
    _llm_enabled()     — whether real LLM calls are allowed (FOS_EXPERIMENT_LLM)
    _model_client()    — build (and cache) a real FOS LLMClient per model
    _agent_client()    — default chat client for a run (tests replace this)
    _build_clients()   — the clients dict passed to the FOS adapter
"""

from __future__ import annotations

import itertools
import os
from typing import Any

from fos.i18n import T

_seq_counter = itertools.count()

# Router model-name mapping (FOS name -> GGUF name) and model-to-port routing,
# mirrored from scripts/headless_council.py so agents reach the llama.cpp
# router exactly like the headless council runner does.
LLAMACPP_ROUTER_MAP: dict[str, str] = {
    "openai/gpt-oss-20b": "gpt-oss-20b",
    "gpt-oss-20b": "gpt-oss-20b",
    "google/gemma-4-26b-a4b": "gemma-4-26b-a4b",
    "gemma-4-26b-a4b": "gemma-4-26b-a4b",
    "qwen/qwen3.6-35b-a3b": "qwen3.6-35b-a3b",
    "gemma4-26b-a4b-uncensored-hauhaucs-balanced": "gemma4-26b-a4b-uncensored",
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive": "qwen3.6-35b-a3b-uncensored",
}

MODEL_PORT_MAP: dict[str, int] = {
    "openai/gpt-oss-20b": 8080,
    "gpt-oss-20b": 8080,
    "qwen/qwen3.6-35b-a3b": 8080,
    "qwen3.6-35b-a3b": 8080,
    "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive": 8082,
    "google/gemma-4-26b-a4b": 8082,
    "gemma-4-26b-a4b": 8082,
    "gemma4-26b-a4b-uncensored-hauhaucs-balanced": 8082,
}

_LLM_TIMEOUT_S = float(os.environ.get("FOS_LLM_TIMEOUT_S", "120"))
_CLIENTS: dict[str, Any] = {}


# ── Resident-model verification ────────────────────────────────────────────

import functools
import requests as _requests

_resident_cache: dict[str, str] = {}  # base_url -> resident model id

def _fetch_resident_model(base_url: str) -> str:
    """Query GET {base_url}/models and return the id of the first model."""
    try:
        resp = _requests.get(f"{base_url.rstrip('/')}/models", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            if models:
                return models[0].get("id", "")
    except Exception:
        pass
    return ""

def _verify_resident_model(base_url: str, expected_router_name: str) -> str:
    """Check the resident model on base_url matches expected_router_name.

    Matching is case-insensitive substring: the router name must appear
    in the resident GGUF filename.  Results are cached per base_url so we
    only query once per model swap, not once per agent call.

    Returns the resident model id.  Raises RuntimeError on mismatch.
    """
    resident = _resident_cache.get(base_url)
    if resident is None:
        resident = _fetch_resident_model(base_url)
        _resident_cache[base_url] = resident
    if resident and expected_router_name.lower() not in resident.lower():
        raise RuntimeError(
            T(
                "error.clients.resident_model_mismatch",
                base_url=base_url,
                expected_router_name=expected_router_name,
                resident=resident,
            )
        )
    return resident



class TrackedClient:
    """Wraps an LLM client and records every chat call for result extraction.

    Records the prompt text, the response text, any usage metadata the
    wrapped client exposes, and splits the calls by round so the runner can
    attribute prompts to agents and rounds afterwards.
    """

    def __init__(self, inner: Any, model: str = ""):
        """Store the wrapped client and reset the call history."""
        self._inner = inner
        self._model = model
        self.calls: list[dict[str, Any]] = []
        self.round_calls: dict[int, list[dict[str, Any]]] = {}
        self._round_start = 0

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to the wrapped client."""
        return getattr(self._inner, name)

    def chat(self, messages: list[dict[str, Any]], json_mode: bool = False, max_tokens: int | None = None) -> Any:
        """Record one call, then delegate to the wrapped client."""
        prompt = "".join(str(m.get("content", "")) for m in messages)
        if prompt.strip() == "Hi":
            return self._inner.chat(messages, json_mode=json_mode, max_tokens=max_tokens)
        entry: dict[str, Any] = {"prompt": prompt, "response": "", "error": None, "usage": None}
        entry["seq"] = next(_seq_counter)
        entry["model"] = self._model
        # ── resident-model verification ──
        if self._model:
            base_url = getattr(getattr(self._inner, "_config", None), "base_url", "")
            if base_url:
                router_name = LLAMACPP_ROUTER_MAP.get(self._model, self._model)
                try:
                    resident = _verify_resident_model(base_url, router_name)
                    entry["resident_model"] = resident
                    entry["port"] = base_url.split(":")[-1].split("/")[0] if ":" in base_url else ""
                except RuntimeError:
                    raise
                except Exception:
                    entry["resident_model"] = "unknown"
                    entry["port"] = ""
        try:
            response = self._inner.chat(messages, json_mode=json_mode, max_tokens=max_tokens)
            entry["response"] = str(response or "")
            entry["usage"] = getattr(self._inner, "last_usage", None)
            return response
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.calls.append(entry)

    def begin_round(self, round_idx: int) -> None:
        """Mark the start of a round's calls."""
        self._round_start = len(self.calls)

    def end_round(self, round_idx: int) -> None:
        """Record the slice of calls that happened during one round."""
        self.round_calls[round_idx] = self.calls[self._round_start:]

    def preload_rounds(self, round_calls: dict[int, list[dict[str, Any]]]) -> None:
        """Restore previously completed rounds' calls (resume path).

        JSON checkpoint round-trips dict keys to strings; every consumer keys
        round_calls by int round number, so normalize here at the boundary.
        """
        normalized: dict[int, list[dict[str, Any]]] = {}
        for key, value in (round_calls or {}).items():
            try:
                normalized[int(key)] = value
            except (TypeError, ValueError):
                normalized[key] = value  # type: ignore[index]
        self.round_calls.update(normalized)



class ProviderTracker:
    """Aggregates per-model TrackedClients so round_calls is merged in call order."""

    def __init__(self, providers: dict[str, TrackedClient]):
        self._providers = providers

    @property
    def round_calls(self) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = {}
        for tc in self._providers.values():
            for round_idx, calls in tc.round_calls.items():
                result.setdefault(round_idx, []).extend(calls)
        for calls in result.values():
            calls.sort(key=lambda e: e.get("seq", 0))
        return result

    def begin_round(self, round_idx: int) -> None:
        for tc in self._providers.values():
            tc.begin_round(round_idx)

    def end_round(self, round_idx: int) -> None:
        for tc in self._providers.values():
            tc.end_round(round_idx)

    def preload_rounds(self, round_calls: dict[int, list[dict[str, Any]]]) -> None:
        for tc in self._providers.values():
            tc.preload_rounds(round_calls)


# ── Client factory ───────────────────────────────────────────────────────────



def _llm_enabled() -> bool:
    """Return True when the runner is allowed to make real LLM calls.

    Live calls are off by default (FOS_EXPERIMENT_LLM=1 turns them on) so
    CI and the test gate never contact a live model server. Tests replace
    _agent_client with a fake.
    """
    return os.environ.get("FOS_EXPERIMENT_LLM", "0") == "1"


def _model_client(model: str) -> Any:
    """Build (and cache) a real FOS LLMClient for a voting model."""
    from fos.core.llm.client import LLMClient
    from fos.core.llm_config import LLMConfig

    if model not in _CLIENTS:
        router_name = LLAMACPP_ROUTER_MAP.get(model, model)
        port = MODEL_PORT_MAP.get(router_name, MODEL_PORT_MAP.get(model, 8080))
        base_url = f"http://{os.environ.get('FOS_LLM_HOST', 'localhost')}:{port}/v1"
        config = LLMConfig(
            dialect="openai",
            model=LLAMACPP_ROUTER_MAP.get(model, model),
            api_key="not-needed",
            base_url=base_url,
            temperature=0.7,
        )
        _CLIENTS[model] = LLMClient(config)
    return _CLIENTS[model]


def _agent_client(agent_config: dict[str, Any] | None = None) -> Any:
    """Return the LLM client used as the run's default chat client.

    Tests monkeypatch this function to inject a FakeLLMClient.
    """
    if not _llm_enabled():
        return None
    model = (agent_config or {}).get("voting_model") or "openai/gpt-oss-20b"
    return _model_client(model)


def _build_clients(run_agents: list[dict[str, Any]]) -> tuple[dict[str, Any], TrackedClient | None]:
    """Build the clients dict passed to the FOS adapter.

    Real path (FOS_EXPERIMENT_LLM=1): the default client is untracked and
    each agent gets its own tracked per-model client via provider_id, so the
    per-agent model distribution is preserved while every call is recorded.
    Test path: the injected fake is wrapped in one shared tracked client.
    """
    default = _agent_client(run_agents[0] if run_agents else None)
    if default is None:
        raise RuntimeError(T("error.clients.no_llm_client"))
    from fos.core.llm.client import LLMClient

    if isinstance(default, LLMClient):
        providers: dict[str, TrackedClient] = {}
        models = sorted({a.get("voting_model", "openai/gpt-oss-20b") for a in run_agents})
        for idx, model in enumerate(models):
            providers[f"provider_{idx}"] = TrackedClient(_model_client(model), model=model)
        model_to_pid = {model: f"provider_{idx}" for idx, model in enumerate(models)}
        for agent in run_agents:
            agent["provider_id"] = model_to_pid[agent.get("voting_model", "openai/gpt-oss-20b")]
        return {"chat": default, "default": default, "providers": providers}, ProviderTracker(providers)

    tracker = TrackedClient(default)
    return {"chat": tracker, "default": tracker, "providers": {}}, tracker
