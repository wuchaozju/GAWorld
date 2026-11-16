"""
Ollama LLM provider implementation for local models.

Contains:
    - create_ollama_client: Create an httpx client for Ollama
    - ollama_chat: Chat completion with vision support
    - ollama_completion: Text completion
    - ollama_embedding: Text embedding generation
    - encode_images: Convert image URLs to base64

The Ollama provider supports:
- Local models via Ollama API (default: http://127.0.0.1:11434)
- Vision-capable models (llava, llama-3.2-vision, etc.)
- Custom base URLs for remote Ollama instances
- Environment variable configuration via OLLAMA_BASE_URL
"""

import base64
import httpx

from fos.i18n import T


def _normalize_ollama_base_url(base_url: str | None) -> str:
    """Choose the Ollama URL the client should connect to."""
    import os
    url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    if url == "http://localhost:11434":
        return "http://127.0.0.1:11434"
    return url


def create_ollama_client(base_url: str | None = None, timeout: float = 30) -> httpx.Client:
    """
    Create an httpx client for Ollama API.

    Args:
        base_url: Ollama server URL (defaults to http://127.0.0.1:11434)
        timeout: Request timeout in seconds

    Returns:
        Configured httpx client instance
    """
    base_url = _normalize_ollama_base_url(base_url)
    return httpx.Client(base_url=base_url, timeout=timeout)


def normalize_messages_for_ollama(
    messages: list,
    allow_vision: bool,
    safe_urls_func: callable
) -> list:
    """
    Normalize messages to Ollama chat format.

    Args:
        messages: List of message dicts with role, content, images, audio, video
        allow_vision: Whether to include image data
        safe_urls_func: Function to validate and filter media URLs

    Returns:
        List of Ollama-formatted message dicts
    """
    def _merge_with_placeholders(text, images, audio, video, include_image_placeholder):
        parts = []
        if text:
            parts.append(text)
        if include_image_placeholder and images:
            parts.append("\n".join([f"[image: {u}]" for u in images]))
        if audio:
            parts.append("\n".join([f"[audio: {u}]" for u in audio]))
        if video:
            parts.append("\n".join([f"[video: {u}]" for u in video]))
        return "\n".join([p for p in parts if p])

    def _safe_media_urls(urls):
        """Validate and filter media URLs for SSRF prevention."""
        safe = []
        for url in urls or []:
            if not isinstance(url, str):
                continue
            validation = safe_urls_func(url)
            if validation == "valid":
                safe.append(url)
            else:
                print(f"[Ollama] Skipping unsafe media URL ({validation}): {url[:50]}...")
        return safe

    norm = []
    for m in messages:
        role = m.get("role")
        if role not in ("system", "user", "assistant"):
            continue
        text = m.get("content") or ""
        images = _safe_media_urls(m.get("images"))
        audio = _safe_media_urls(m.get("audio"))
        video = _safe_media_urls(m.get("video"))

        entry = {
            "role": role,
            "content": _merge_with_placeholders(
                text,
                [] if allow_vision else images,
                audio,
                video,
                include_image_placeholder=not allow_vision,
            ),
        }
        if allow_vision and images:
            entry["images"] = images
        norm.append(entry)
    return norm


def encode_images(urls: list, client: httpx.Client, safe_urls_func: callable) -> list:
    """
    Convert image URLs to base64-encoded strings.

    Args:
        urls: List of image URLs
        client: httpx client for fetching URLs
        safe_urls_func: Function to validate media URLs

    Returns:
        List of base64-encoded image strings
    """
    from .validation import validate_media_url

    encoded = []
    for url in urls or []:
        if url.startswith("data:"):
            parts = url.split(",", 1)
            if len(parts) == 2:
                encoded.append(parts[1])
            continue
        # Validate URL before fetching (SSRF protection)
        validation = safe_urls_func(url) if safe_urls_func else validate_media_url(url)
        if validation != "valid":
            print(f"[Ollama] Skipping unsafe image URL ({validation}): {url[:50]}...")
            continue
        resp = client.get(url, timeout=10)
        resp.raise_for_status()
        encoded.append(base64.b64encode(resp.content).decode("utf-8"))
    return encoded


def ollama_chat(
    client: httpx.Client,
    model: str,
    messages: list,
    temperature: float,
    top_p: float,
    max_tokens: int,
    timeout: float,
    allow_vision: bool,
    safe_urls_func: callable,
    json_mode: bool = False,
) -> str:
    """
    Perform Ollama chat completion.

    Args:
        client: httpx client for Ollama API
        model: Model name to use
        messages: List of message dicts
        temperature: Sampling temperature
        top_p: Nucleus sampling parameter
        max_tokens: Maximum tokens to generate
        timeout: Request timeout in seconds
        allow_vision: Whether to process image content
        safe_urls_func: Function to validate media URLs
        json_mode: If True, enforce JSON output

    Returns:
        Generated text response
    """
    msgs = normalize_messages_for_ollama(messages, allow_vision, safe_urls_func)

    for m in msgs:
        if allow_vision and m.get("images"):
            m["images"] = encode_images(m.get("images"), client, safe_urls_func)

    # For json_mode with Ollama, add prompt-based JSON instruction
    # Some models (Qwen3, Gemma 3) don't properly support "format": "json"
    # and return empty responses. Prompt-based instruction is more reliable.
    if json_mode and msgs:
        # Prepend JSON instruction to the last user message
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                original_content = msgs[i].get("content", "")
                msgs[i]["content"] = (
                    "IMPORTANT: You must respond with ONLY valid JSON, no markdown, no explanation.\n\n"
                    + original_content
                )
                break

    payload = {
        "model": model,
        "messages": msgs,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": max_tokens,
        },
        # Layer 1: unconditionally disable thinking mode.
        "think": False,
    }

    # Note: We don't use payload["format"] = "json" because some Ollama models
    # (Qwen3, Gemma 3) return empty responses with this setting.
    # Prompt-based JSON instruction is more reliable.

    def _post(body):
        resp = client.post("/api/chat", json=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValueError(T("Ollama error: {error}", error=data.get('error')))
        message = data.get("message") or {}
        content = message.get("content") or data.get("response") or ""
        return str(content).strip()

    content = _post(payload)

    # Fallback: some models still return empty content; try explicit JSON format once
    if not content:
        if json_mode:
            payload_with_format = dict(payload)
            payload_with_format["format"] = "json"
            content = _post(payload_with_format)

    if not content:
        raise ValueError(T("Ollama returned empty response"))

    return content


def ollama_completion(
    client: httpx.Client,
    model: str,
    prompt: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    timeout: float
) -> str:
    """
    Perform Ollama text completion.

    Args:
        client: httpx client for Ollama API
        model: Model name to use
        prompt: Text prompt to complete
        temperature: Sampling temperature
        top_p: Nucleus sampling parameter
        max_tokens: Maximum tokens to generate
        timeout: Request timeout in seconds

    Returns:
        Generated text completion
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": max_tokens,
        },
    }
    resp = client.post("/api/generate", json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("response") or "").strip()


def ollama_embedding(
    client: httpx.Client,
    model: str,
    text: str,
    timeout: float
) -> list:
    """
    Generate text embedding using Ollama.

    Args:
        client: httpx client for Ollama API
        model: Embedding model name
        text: Text to embed
        timeout: Request timeout in seconds

    Returns:
        List of embedding float values

    Raises:
        ValueError: If Ollama doesn't return an embedding
    """
    payload = {"model": model, "prompt": text}
    resp = client.post("/api/embeddings", json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    embedding = data.get("embedding")
    if embedding is None:
        raise ValueError(T("Ollama did not return embedding"))
    return embedding


def clone_ollama_client(base_url: str | None, timeout: float) -> httpx.Client:
    """
    Create a new independent Ollama client instance.

    Args:
        base_url: Ollama server URL
        timeout: Request timeout in seconds

    Returns:
        New httpx client instance
    """
    base_url = _normalize_ollama_base_url(base_url)
    return httpx.Client(base_url=base_url, timeout=timeout)
