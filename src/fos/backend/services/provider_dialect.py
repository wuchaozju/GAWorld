from __future__ import annotations


# Dialects with OpenAI-compatible APIs — all normalize to "openai" for FOS internals.
_OPENAI_COMPATIBLE_NORMALIZED = {
    "openai-compatible",
    "deepseek",
    "lmstudio",
    "vllm",
    "llamacpp",
    "groq",
    "together",
    "fireworks",
    "openrouter",
}


def normalize_provider_dialect(raw: str | None) -> str:
    value = (raw or "").strip().lower().replace("_", "-")
    if value in _OPENAI_COMPATIBLE_NORMALIZED:
        return "openai"
    return value


def normalize_provider_runtime(raw: str | None, base_url: str | None = None) -> tuple[str, str | None]:
    """Normalize a stored provider for runtime client creation.

    Older records can store the local Ollama server as an OpenAI-compatible
    provider with base_url=http://...:11434. Running those through the OpenAI
    SDK is much slower and can time out behind the proxy, so runtime code should
    use Ollama's native API for the known Ollama endpoint.
    """
    dialect = normalize_provider_dialect(raw)
    normalized_base_url = (base_url or "").strip() or None
    lowered_base_url = (normalized_base_url or "").lower()
    is_known_ollama_url = bool(
        lowered_base_url
        and (
            "fos-ollama" in lowered_base_url
            or ":11434" in lowered_base_url
        )
    )

    if dialect == "ollama" or (dialect == "openai" and is_known_ollama_url):
        if normalized_base_url and normalized_base_url.rstrip("/").endswith("/v1"):
            normalized_base_url = normalized_base_url.rstrip("/")[:-3].rstrip("/")
        return "ollama", normalized_base_url

    return dialect, normalized_base_url
