"""
OpenAI LLM provider implementation.

Contains:
    - create_openai_client: Create an OpenAI SDK client instance
    - openai_chat: Chat completion with vision support
    - openai_completion: Text completion
    - openai_embedding: Text embedding generation

The OpenAI provider supports:
- GPT models for chat and completion
- Vision models (gpt-4o, gpt-4-vision) for multimodal inputs
- Embedding models for vector generation
- Configurable temperature, max_tokens, penalties
"""

from unittest.mock import MagicMock

from openai import OpenAI

from fos.i18n import T


def create_openai_client(api_key: str, base_url: str | None = None) -> OpenAI:
    """
    Create an OpenAI SDK client instance.

    Args:
        api_key: OpenAI API key
        base_url: Optional custom base URL for compatible APIs

    Returns:
        Configured OpenAI client instance
    """
    return OpenAI(api_key=api_key, base_url=base_url)


def normalize_messages_for_openai(
    messages: list, allow_vision: bool, safe_urls_func: callable
) -> list:
    """
    Normalize messages to OpenAI chat format.

    Args:
        messages: List of message dicts with role, content, images, audio, video
        allow_vision: Whether to include image data
        safe_urls_func: Function to validate and filter media URLs

    Returns:
        List of OpenAI-formatted message dicts
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
                print(
                    f"[OpenAI] Skipping unsafe media URL ({validation}): {url[:50]}..."
                )
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

        if allow_vision and images:
            merged_text = _merge_with_placeholders(
                text, [], audio, video, include_image_placeholder=False
            )
            parts = []
            if merged_text:
                parts.append({"type": "text", "text": merged_text})
            for url in images:
                if not url:
                    continue
                parts.append({"type": "image_url", "image_url": {"url": url}})
            norm.append({"role": role, "content": parts})
        else:
            content = _merge_with_placeholders(
                text, images, audio, video, include_image_placeholder=True
            )
            norm.append({"role": role, "content": content})
    return norm



def _extract_timings(resp):
    """Pull llama.cpp server-side timings (prompt_ms/predicted_ms) if present."""
    if resp is None:
        return None
    candidates = []
    me = getattr(resp, "model_extra", None)
    if isinstance(me, dict):
        candidates.append(me.get("timings"))
    candidates.append(getattr(resp, "timings", None))
    try:
        if hasattr(resp, "model_dump"):
            candidates.append(resp.model_dump().get("timings"))
    except Exception:
        pass
    if isinstance(resp, dict):
        candidates.append(resp.get("timings"))
    for t in candidates:
        if not t:
            continue
        if isinstance(t, dict):
            return t
        if hasattr(t, "model_dump"):
            try:
                return t.model_dump()
            except Exception:
                pass
        try:
            return dict(t)
        except Exception:
            pass
    return None

def openai_chat(
    client: OpenAI,
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    frequency_penalty: float,
    presence_penalty: float,
    timeout: float,
    allow_vision: bool,
    safe_urls_func: callable,
    json_mode: bool = False,
) -> str:
    """
    Perform OpenAI chat completion.

    Args:
        client: OpenAI SDK client instance
        model: Model name to use
        messages: List of message dicts
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        frequency_penalty: Frequency penalty (-2.0 to 2.0)
        presence_penalty: Presence penalty (-2.0 to 2.0)
        timeout: Request timeout in seconds
        allow_vision: Whether to process image content
        safe_urls_func: Function to validate media URLs
        json_mode: If True, enforce JSON output

    Returns:
        Generated text response
    """
    normalized_messages = normalize_messages_for_openai(
        messages, allow_vision, safe_urls_func
    )

    kwargs = {
        "model": model,
        "messages": normalized_messages,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }

    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Layer 1: unconditionally disable thinking/reasoning mode.
    # Non-thinking models silently ignore this parameter.
    kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    def _safe_content(msg):
        """Extract content from message, detecting MagicMock on reasoning_content."""
        text = msg.content
        if text and not isinstance(text, MagicMock):
            return text.strip()
        # Try reasoning_content, but be careful not to get a MagicMock
        rc = getattr(msg, "reasoning_content", None)
        if rc is not None and not isinstance(rc, MagicMock):
            return rc.strip()
        return ""

    try:
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        content = _safe_content(msg)
        if content:
            return content
    except Exception as exc:
        # lms / llama.cpp servers reject "json_object" type and require
        # "json_schema" or "text". Their error messages mention either
        # "json_schema" or "json_object" — catch both variants.
        msg = str(exc)
        if not json_mode or not ("json_object" in msg or "json_schema" in msg):
            raise
        content = ""

    used_fallback = False

    # Fallback for providers (e.g., Ollama OpenAI-compatible, lms) that
    # return empty content or reject json_object when response_format is set.
    # Retry once without response_format and prepend an explicit JSON-only
    # instruction to the last user message.
    if json_mode and not content:
        fallback_messages = list(normalized_messages)

        for i in range(len(fallback_messages) - 1, -1, -1):
            if fallback_messages[i].get("role") == "user":
                existing = fallback_messages[i].get("content") or ""
                if isinstance(existing, list):
                    text_parts = []
                    for part in existing:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text") or "")
                    existing = "\n".join([p for p in text_parts if p])
                fallback_messages[i] = {
                    "role": "user",
                    "content": (
                        "IMPORTANT: You must respond with ONLY valid JSON, no markdown, no explanation.\n\n"
                        + str(existing)
                    ),
                }
                break

        used_fallback = True

        fallback_kwargs = {k: v for k, v in kwargs.items() if k != "response_format"}
        fallback_kwargs["messages"] = fallback_messages
        # Bump max_tokens for the fallback — the added "IMPORTANT" prefix
        # consumes some token budget, and models like Gemma need more room.
        if fallback_kwargs.get("max_tokens", 0) < 1024:
            fallback_kwargs["max_tokens"] = 1024

        try:
            resp = client.chat.completions.create(**fallback_kwargs)
            msg = resp.choices[0].message
            content = _safe_content(msg)
        except Exception:
            content = ""

    # Retry once for non-JSON empty responses (transient provider issues)
    if not content and not json_mode:
        resp = client.chat.completions.create(**kwargs)
        content = (resp.choices[0].message.content or "").strip()

    if not content:
        raise ValueError(T("OpenAI-compatible provider returned empty response"))

    return content


def openai_completion(
    client: OpenAI,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    """
    Perform OpenAI text completion.

    Args:
        client: OpenAI SDK client instance
        model: Model name to use
        prompt: Text prompt to complete
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        timeout: Request timeout in seconds

    Returns:
        Generated text completion
    """
    resp = client.completions.create(
        model=model,
        prompt=prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return resp.choices[0].text.strip()


def openai_embedding(client: OpenAI, model: str, text: str, timeout: float) -> list:
    """
    Generate text embedding using OpenAI.

    Args:
        client: OpenAI SDK client instance
        model: Embedding model name
        text: Text to embed
        timeout: Request timeout in seconds

    Returns:
        List of embedding float values
    """
    resp = client.embeddings.create(
        model=model,
        input=text,
        timeout=timeout,
    )
    return resp.data[0].embedding


def clone_openai_client(original_provider, timeout_s: float) -> OpenAI:
    """
    Create a new independent OpenAI client instance.

    Args:
        original_provider: LLMConfig with OpenAI settings
        timeout_s: Timeout in seconds

    Returns:
        New OpenAI client instance
    """
    return OpenAI(
        api_key=original_provider.api_key,
        base_url=original_provider.base_url,
    )
