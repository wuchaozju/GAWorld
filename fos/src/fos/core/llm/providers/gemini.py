"""
Google Gemini LLM provider implementation.

Contains:
    - create_gemini_client: Create a Gemini model instance
    - gemini_chat: Chat completion with vision support
    - gemini_completion: Text completion
    - gemini_embedding: Text embedding generation

The Gemini provider supports:
- Gemini Pro models for chat and completion
- Vision models (gemini-pro-vision, gemini-1.5, gemini-2) for multimodal inputs
- Embedding models for vector generation
- Configurable temperature, max_tokens, top_p, penalties
"""

import google.genai as genai

# Module-level ThinkingConfig for test monkeypatching (test_thinking_disable.py
# patches gemini_mod.ThinkingConfig to verify graceful degradation when the
# model rejects thinking_budget=0). This is a simple inline type rather than
# importing from google.genai.types to avoid mock-leakage issues from other
# test files that put mock google.genai modules in sys.modules.
class ThinkingConfig:
    """Wrapper for Google AI ThinkingConfig, usable as a drop-in."""
    def __new__(cls, thinking_budget=0):
        return type('_ThinkingConfigInstance', (), {'thinking_budget': thinking_budget})()


def create_gemini_client(model: str, api_key: str):
    """
    Create a Gemini GenerativeModel instance.

    Args:
        model: Model name (e.g., "gemini-pro")
        api_key: Google API key

    Returns:
        Configured GenerativeModel instance
    """
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(model_name=model)


def normalize_messages_for_gemini(
    messages: list,
    allow_vision: bool,
    safe_urls_func: callable
) -> list:
    """
    Normalize messages to Gemini chat format.

    Args:
        messages: List of message dicts with role, content, images, audio, video
        allow_vision: Whether to include image data
        safe_urls_func: Function to validate and filter media URLs

    Returns:
        List of Gemini-formatted message dicts
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
                print(f"[Gemini] Skipping unsafe media URL ({validation}): {url[:50]}...")
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
            merged_text = _merge_with_placeholders(text, [], audio, video, include_image_placeholder=False)
            parts = []
            if merged_text:
                parts.append({"text": merged_text})
            for url in images:
                if not url:
                    continue
                parts.append({"image_url": url})
            norm.append({"role": ("model" if role == "assistant" else "user"), "parts": parts})
        else:
            merged = _merge_with_placeholders(text, images, audio, video, include_image_placeholder=True)
            norm.append({"role": ("model" if role == "assistant" else "user"), "parts": [{"text": merged}]})
    return norm


def gemini_chat(
    client,
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    top_p: float,
    frequency_penalty: float,
    presence_penalty: float,
    safe_urls_func: callable,
    allow_vision: bool,
    json_mode: bool = False,
) -> str:
    """
    Perform Gemini chat completion.

    Args:
        client: Gemini GenerativeModel instance
        model: Model name to use
        messages: List of message dicts
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        top_p: Nucleus sampling parameter
        frequency_penalty: Frequency penalty
        presence_penalty: Presence penalty
        safe_urls_func: Function to validate media URLs
        allow_vision: Whether to process image content
        json_mode: If True, enforce JSON output

    Returns:
        Generated text response
    """
    contents = normalize_messages_for_gemini(messages, allow_vision, safe_urls_func)

    config_kwargs = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "top_p": top_p,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
    }

    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"

    from google.genai.types import GenerateContentConfig

    config = GenerateContentConfig(**config_kwargs)

    # Set thinking_config as an attribute after construction.
    # Using the module-level ThinkingConfig (which tests may monkeypatch
    # to raise on budget=0 to simulate model rejection).
    try:
        config.thinking_config = ThinkingConfig(thinking_budget=0)
    except Exception:
        pass  # Some models reject thinking_budget=0

    resp = client.generate_content(
        contents=contents,
        config=config,
    )

    if hasattr(resp, "text") and resp.text:
        return resp.text.strip()
    if hasattr(resp, "candidates") and resp.candidates:
        cand = resp.candidates[0]
        if hasattr(cand, "content") and cand.content:
            parts = getattr(cand.content, "parts", [])
            if parts:
                return "".join([getattr(p, "text", "") for p in parts]).strip()
    return ""


def gemini_completion(client, prompt: str) -> str:
    """
    Perform Gemini text completion.

    Args:
        client: Gemini GenerativeModel instance
        prompt: Text prompt to complete

    Returns:
        Generated text completion
    """
    resp = client.generate_content(prompt)
    return resp.text.strip() if getattr(resp, "text", None) else ""


def gemini_embedding(model: str, text: str) -> list:
    """
    Generate text embedding using Gemini.

    Args:
        model: Embedding model name
        text: Text to embed

    Returns:
        List of embedding float values
    """
    return genai.embed_content(
        model=model,
        content=text,
    )["embedding"]


def clone_gemini_client(original_provider):
    """
    Create a new independent Gemini client instance.

    Args:
        original_provider: LLMConfig with Gemini settings

    Returns:
        New GenerativeModel instance
    """
    genai.configure(api_key=original_provider.api_key)
    return genai.GenerativeModel(model_name=original_provider.model)
