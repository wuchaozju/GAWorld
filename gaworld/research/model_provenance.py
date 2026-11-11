"""Which model answered, how it was asked, and what every call did.

An experiment is reproducible only if three things travel with it:

* **the model version** — the provider's model id, its backend type, the
  endpoint it was reached at and the generation settings it was configured
  with. A model *name* is not a version: the same name may serve a different
  build tomorrow, so the endpoint is fingerprinted too.
* **the generation parameters** — the sampling temperature and the token
  budget. They are part of the protocol, not of the deployment, so the
  dashboard lets a researcher set them and the run records the values that
  were actually used.
* **the call log** — one row per model call: which stage asked, with which
  prompt fingerprint, which seed, how long it took and whether it failed.

The dashboard reads the first two; all three end up in the exported data
package, where they are what lets somebody check a number instead of taking
it on trust.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from gaworld.research import result_checks as rc

#: The stages of an experiment that call a model, in the order they happen.
STAGES: tuple[str, ...] = ("extract", "answer", "interpret")

#: Label of each stage, for the interface.
STAGE_LABELS: dict[str, str] = {
    "extract": "读取文献",
    "answer": "居民作答",
    "interpret": "解读偏差",
}

#: Bounds a researcher may not leave, whatever the interface sends.
TEMPERATURE_RANGE = (0.0, 2.0)
MAX_TOKENS_RANGE = (32, 32_000)


class GenerationError(ValueError):
    """The requested generation parameters cannot be used."""


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_temperature(value: Any, default: float) -> float:
    """A temperature in range, or the default when none was given."""
    if value is None or value == "":
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GenerationError(f"温度不是数字：{value!r}") from exc
    low, high = TEMPERATURE_RANGE
    if not low <= number <= high:
        raise GenerationError(f"温度要在 {low}–{high} 之间，收到 {number}")
    return number


def normalize_max_tokens(value: Any, default: int) -> int:
    """A token budget in range, or the default when none was given."""
    if value is None or value == "":
        return int(default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise GenerationError(f"max tokens 不是整数：{value!r}") from exc
    low, high = MAX_TOKENS_RANGE
    if not low <= number <= high:
        raise GenerationError(f"max tokens 要在 {low}–{high} 之间，收到 {number}")
    return number


def normalize_generation(
    payload: Any,
    defaults: dict[str, dict[str, float | int]],
) -> dict[str, dict[str, float | int]]:
    """The generation parameters of every stage, checked and filled in.

    *payload* is whatever the interface sent — a stage may be missing, and
    then the default stands. A stage the interface sends with a wrong value
    is an error, not something to be silently ignored: a temperature of 9
    that never reaches the model is worse than one that is refused.
    """
    given = payload if isinstance(payload, dict) else {}
    out: dict[str, dict[str, float | int]] = {}
    for stage, fallback in defaults.items():
        raw = given.get(stage) if isinstance(given.get(stage), dict) else {}
        out[stage] = {
            "temperature": normalize_temperature(raw.get("temperature"), fallback.get("temperature", 0.7)),
            "max_tokens": normalize_max_tokens(raw.get("max_tokens"), fallback.get("max_tokens", 1024)),
        }
    return out


def describe_providers() -> list[dict[str, Any]]:
    """The configured providers with the model each one answers with.

    Read from the running configuration, so the interface shows the model
    that would actually answer — not a name typed in a form.
    """
    try:
        from gaworld.llm import providers
    except Exception:  # pragma: no cover - the interface degrades, the run does not
        return []
    try:
        return providers.available_providers()
    except Exception:  # pragma: no cover - a broken config must not break the page
        return []


def provider_details(provider: str) -> dict[str, Any]:
    """Everything worth recording about one provider's model version.

    Returns the provider's model id, its backend type, a fingerprint of the
    endpoint and the generation settings it was configured with. A missing
    provider yields a record that says so rather than an empty one.
    """
    details: dict[str, Any] = {
        "provider": provider or "",
        "model": "",
        "backend_type": "",
        "endpoint_hash": "",
        "generation_settings": {},
        "config_hash": "",
    }
    try:
        from gaworld.llm import providers

        router = providers.LLM_ROUTER
        cfg = (router.config.get("llm", {}) or {}).get("providers", {}) or {}
        entry = cfg.get(provider) or {}
        backend = router.providers.get(provider)
        details["model"] = str(getattr(backend, "model", "") or entry.get("model", "") or "")
        details["backend_type"] = type(backend).__name__ if backend is not None else ""
        endpoint = str(getattr(backend, "base_url", getattr(backend, "url", "")) or entry.get("base_url", ""))
        details["endpoint_hash"] = _hash_text(endpoint)[:16] if endpoint else ""
        details["generation_settings"] = {
            key: entry[key]
            for key in (
                "top_p",
                "top_k",
                "seed",
                "repeat_penalty",
                "frequency_penalty",
                "presence_penalty",
                "reasoning_effort",
            )
            if key in entry
        }
        details["config_hash"] = _hash_text(json.dumps(entry, sort_keys=True, default=str))[:16]
    except Exception:  # pragma: no cover - a broken config must not break a run
        pass
    return details


class CallJournal:
    """One row per model call, written while the experiment runs.

    The journal is written from several worker threads at once, so the lock
    is not optional: without it the rows interleave and the sequence
    numbers lie.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []

    def record(self, **fields: Any) -> None:
        with self._lock:
            self._entries.append({"seq": len(self._entries) + 1, **fields})

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._entries]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def link_calls(entries: list[dict[str, Any]], run: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach *who asked* to every logged call.

    The journal knows which prompt was sent; the run knows which resident
    answered which condition. The prompt fingerprint joins the two, so the
    log can say "agent 31, condition C1, stability probe" instead of an
    anonymous sequence number.
    """
    index: dict[str, dict[str, Any]] = {}
    for response in run.get("responses") or []:
        agent_id = response.get("agent_id")
        condition = response.get("condition")
        if response.get("prompt_hash"):
            index[str(response["prompt_hash"])] = {
                "agent_id": agent_id,
                "condition": condition,
                "variant": "main",
            }
        for name, probe in (response.get("probes") or {}).items():
            if isinstance(probe, dict) and probe.get("prompt_hash"):
                index[str(probe["prompt_hash"])] = {
                    "agent_id": agent_id,
                    "condition": condition,
                    "variant": name,
                }
    sampling = run.get("sampling_run") or run.get("sampling") or {}
    for cell in sampling.values() if isinstance(sampling, dict) else []:
        if isinstance(cell, dict) and cell.get("prompt_hash"):
            index.setdefault(
                str(cell["prompt_hash"]),
                {"agent_id": cell.get("agent_id"), "condition": cell.get("condition"), "variant": "sampling"},
            )
    linked = []
    for entry in entries:
        context = index.get(str(entry.get("prompt_hash") or ""))
        linked.append(
            {
                **entry,
                "agent_id": (context or {}).get("agent_id"),
                "condition": (context or {}).get("condition"),
                "variant": (context or {}).get("variant"),
            }
        )
    return linked


def journal_entry(
    *,
    task: str,
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    seed: int | None,
    prompt: str,
    started: float,
    ok: bool,
    error: str = "",
    answer: str = "",
) -> dict[str, Any]:
    """One row of the call log."""
    return {
        "task": task,
        "provider": provider,
        "model": model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "seed": int(seed) if seed is not None else None,
        # The same fingerprint the run record keeps for every answer, so a
        # logged call can be joined to the resident who asked.
        "prompt_hash": rc.fingerprint(prompt),
        "latency_ms": int(max(0, (time.monotonic() - started) * 1000)),
        "ok": bool(ok),
        "error": error,
        "chars": len(answer),
        "at": time.time(),
    }


__all__ = [
    "MAX_TOKENS_RANGE",
    "STAGES",
    "STAGE_LABELS",
    "TEMPERATURE_RANGE",
    "CallJournal",
    "GenerationError",
    "describe_providers",
    "journal_entry",
    "link_calls",
    "normalize_generation",
    "normalize_max_tokens",
    "normalize_temperature",
    "provider_details",
]
