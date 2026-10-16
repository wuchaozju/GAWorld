"""Read-only route inspection and an explicit bounded generation probe."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


def inspect_provider(
    config: dict[str, Any], selected: str = "", *, local: bool = False, probe: bool = False
) -> dict[str, Any]:
    llm = config.get("llm") or {}
    routing = llm.get("routing") or {}
    providers = llm.get("providers") or {}
    primary = selected or str(routing.get("default") or next(iter(providers), ""))
    fallback = routing.get("fallback") or []
    if isinstance(fallback, str):
        fallback = [fallback]
    cfg = (llm.get("providers") or {}).get(primary)
    result: dict[str, Any] = {
        "primary": primary,
        "fallback": fallback if not selected else [],
        "status": "unconfigured",
        "generation_tested": False,
    }
    if not isinstance(cfg, dict):
        return result
    result.update(type=cfg.get("type"), model=cfg.get("model"), status="configuration_only")
    provider_type = str(cfg.get("type") or "")
    default_env = "ANTHROPIC_API_KEY" if provider_type in ("anthropic", "claude") else "OPENAI_API_KEY"
    envs = [cfg.get("api_key_env") or default_env, *(cfg.get("api_key_envs") or [])]
    key_present = bool(
        cfg.get("api_key")
        or cfg.get("ANTHROPIC_AUTH_TOKEN")
        or any(os.environ.get(str(name)) for name in envs if name)
    )
    if provider_type in ("anthropic", "claude", "openai"):
        result["key_present"] = key_present
        if provider_type in ("anthropic", "claude") and not key_present:
            result["status"] = "missing_key"
    if local and cfg.get("type") == "ollama":
        url = urlsplit(str(cfg.get("url") or "http://localhost:11434/api/generate"))
        tags_url = urlunsplit((url.scheme, url.netloc, "/api/tags", "", ""))
        try:
            response = requests.get(tags_url, timeout=3)
            response.raise_for_status()
            models = [str(m.get("name")) for m in response.json().get("models", [])]
            result["models"] = models
            model = str(cfg.get("model") or "")
            installed = model in models or (":" not in model and model + ":latest" in models)
            result["status"] = "model_installed" if installed else "model_missing"
        except (requests.RequestException, ValueError):
            result["status"] = "connection_failed"
    if probe:
        from gaworld.accounts import usage
        from gaworld.llm.providers import probe_provider

        bounded = dict(cfg, timeout=min(15, float(cfg.get("timeout") or 15)))
        usage.record("research_provider_probe")
        checked = probe_provider(bounded)
        result.update(
            generation_tested=True, probe=checked, status="ready" if checked.get("ok") else "probe_failed"
        )
    return result
