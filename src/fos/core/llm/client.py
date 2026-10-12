"""
LLM client implementation with timeout, retry, and concurrency control.

Contains:
    - LLMClient: Main client class supporting multiple providers
    - create_llm_client: Factory function for creating LLM clients

The LLMClient provides:
- Multiple provider support (OpenAI, Gemini, Ollama, Mock)
- Concurrent request limiting per client
- Timeout control for all providers
- Automatic retry with exponential backoff
- Vision/multimodal support with SSRF prevention
- Chat, completion, and embedding APIs

Environment variables:
    LLM_TIMEOUT_S: Request timeout in seconds (default: 30)
    LLM_MAX_RETRIES: Maximum retry attempts (default: 2)
    LLM_RETRY_BACKOFF_S: Initial retry backoff in seconds (default: 1.0)
    LLM_MAX_CONCURRENT_PER_CLIENT: Max concurrent requests (default: 8)
    FOS_LLM_LOG: Traffic-log path override; "off" (any casing) disables it;
        empty/unset means default to $FOS_DATA_DIR/llm_traffic.jsonl
        (or ~/work/fos-data/llm_traffic.jsonl when FOS_DATA_DIR is unset too)
    FOS_DATA_DIR: Data-repo directory holding the default traffic log
"""

import os
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from copy import deepcopy
from threading import BoundedSemaphore
from typing import List, Dict, Any

from fos.backend.core.timing import log_time
from fos.i18n import T

from fos.core.agent.parsing import strip_thinking_tokens

from .llm_config import LLMConfig
from .validation import validate_media_url
from .providers import _MockModel, _import_openai, _import_gemini, _import_ollama


logger = logging.getLogger(__name__)


# Lazy-loaded provider modules
_openai = None
_gemini = None
_ollama = None


def _default_llm_traffic_log_path() -> str:
    """Default traffic-log path: the data repo, never the working directory.

    Uses $FOS_DATA_DIR when set, otherwise ~/work/fos-data (the local data
    repo). The returned path is absolute so the log can never land in a
    source checkout or the current working directory by accident.
    """
    data_dir = os.environ.get("FOS_DATA_DIR") or os.path.expanduser("~/work/fos-data")
    return os.path.join(data_dir, "llm_traffic.jsonl")


def _append_traffic_log(log_path: str, record: dict) -> None:
    """Append one traffic-log line, creating parent dirs first.

    Failures (unwritable path, missing parents, disk errors) are logged as
    warnings instead of being swallowed, so a misconfigured log location is
    visible; callers keep working either way.
    """
    try:
        parent = os.path.dirname(log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as err:
        logger.warning("Failed to write LLM traffic log to %s: %s", log_path, err)


def _get_openai():
    """Get OpenAI provider functions (lazy loaded)."""
    global _openai
    if _openai is None:
        _openai = _import_openai()
    return _openai


def _get_gemini():
    """Get Gemini provider functions (lazy loaded)."""
    global _gemini
    if _gemini is None:
        _gemini = _import_gemini()
    return _gemini


def _get_ollama():
    """Get Ollama provider functions (lazy loaded)."""
    global _ollama
    if _ollama is None:
        _ollama = _import_ollama()
    return _ollama


class PromptOverflowError(Exception):
    """Raised when a prompt exceeds the server context window."""
    def __init__(self, token_count: int, ctx_size: int):
        self.token_count = token_count
        self.ctx_size = ctx_size
        super().__init__(f"Prompt ({token_count} tokens) exceeds context size ({ctx_size})")


class LLMClient:
    """
    LLM client with support for multiple providers and automatic retry.

    The LLMClient provides a unified interface for interacting with various
    LLM providers including OpenAI, Google Gemini, Ollama (local), and a
    mock provider for testing.

    Attributes:
        provider: LLMConfig with provider settings
        timeout_s: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        retry_backoff_s: Initial backoff delay between retries
        _sem: BoundedSemaphore for concurrent request limiting
    """

    def __init__(self, provider: LLMConfig):
        """
        Initialize LLM client with provider configuration.

        Args:
            provider: LLMConfig with dialect, api_key, model, and other settings

        Raises:
            ValueError: If provider dialect is unknown
        """
        self.provider = provider
        self.server_ctx_size = int(os.environ.get("FOS_SERVER_CTX_SIZE", "32768"))

        # Timeout and retry settings (environment-driven defaults)
        self.timeout_s = float(os.getenv("LLM_TIMEOUT_S", "300"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        self.retry_backoff_s = float(os.getenv("LLM_RETRY_BACKOFF_S", "1.0"))

        # Concurrent request limiting per client
        max_concurrent = int(os.getenv("LLM_MAX_CONCURRENT_PER_CLIENT", "8"))
        if max_concurrent < 1:
            max_concurrent = 1
        self._sem = BoundedSemaphore(max_concurrent)

        # Initialize provider-specific client
        base_url = provider.base_url
        if provider.dialect == "openai" and base_url and "/v1" not in base_url and ("localhost" in base_url or ":11434" in base_url):
            base_url = base_url.rstrip("/") + "/v1"
            provider.base_url = base_url

        if provider.dialect == "openai":
            openai = _get_openai()
            self.client = openai["create_openai_client"](provider.api_key, base_url)
        elif provider.dialect == "gemini":
            gemini = _get_gemini()
            self.client = gemini["create_gemini_client"](provider.model, provider.api_key)
        elif provider.dialect == "mock":
            self.client = _MockModel()
        elif provider.dialect == "ollama":
            ollama = _get_ollama()
            self.client = ollama["create_ollama_client"](provider.base_url, self.timeout_s)
        else:
            raise ValueError(T("Unknown LLM provider dialect: {dialect}", dialect=provider.dialect))

    def clone(self) -> "LLMClient":
        """
        Create an independent clone of this LLM client.

        For "strong isolation" mode in connection pools, creates a
        functionally equivalent but completely independent LLMClient
        instance with:
        - Deep-copied provider configuration
        - Freshly initialized underlying client (new connection)
        - Inherited timeout/retry/backoff settings
        - Independent semaphore for concurrency control

        Returns:
            New LLMClient instance
        """
        # Deep copy provider configuration
        cloned_provider = deepcopy(self.provider)

        # Create empty instance (bypass __init__)
        cloned = LLMClient.__new__(LLMClient)
        cloned.provider = cloned_provider

        # Reinitialize underlying client
        if cloned_provider.dialect == "openai":
            openai = _get_openai()
            cloned.client = openai["clone_openai_client"](cloned_provider, self.timeout_s)
        elif cloned_provider.dialect == "gemini":
            gemini = _get_gemini()
            cloned.client = gemini["clone_gemini_client"](cloned_provider)
        elif cloned_provider.dialect == "mock":
            cloned.client = _MockModel()
        elif cloned_provider.dialect == "ollama":
            ollama = _get_ollama()
            cloned.client = ollama["clone_ollama_client"](cloned_provider.base_url, self.timeout_s)
        else:
            raise ValueError(T("Unknown LLM provider dialect: {dialect}", dialect=cloned_provider.dialect))

        # Inherit configuration
        cloned.timeout_s = self.timeout_s
        cloned.max_retries = self.max_retries
        cloned.retry_backoff_s = self.retry_backoff_s

        # Independent semaphore
        max_concurrent = int(os.getenv("LLM_MAX_CONCURRENT_PER_CLIENT", "8"))
        if max_concurrent < 1:
            max_concurrent = 1
        cloned._sem = BoundedSemaphore(max_concurrent)

        return cloned

    def _with_timeout_and_retry(self, fn):
        """
        Wrap an LLM call with concurrency limiting, timeout, and retry.

        Provides:
        - Concurrent request limiting (per-client semaphore)
        - Timeout control (via thread executor for non-OpenAI providers)
        - Retry with exponential backoff

        Args:
            fn: Callable that performs the actual LLM request

        Returns:
            Result of fn() on success

        Raises:
            Exception: The last exception if all retries exhausted
        """
        last_err = None
        delay = self.retry_backoff_s

        for attempt in range(self.max_retries + 1):
            try:
                with log_time(
                    "LLM",
                    provider=self.provider.dialect,
                    model=self.provider.model,
                    attempt=attempt,
                ):
                    with self._sem:
                        if self.provider.dialect == "openai":
                            # OpenAI: direct call, timeout via SDK parameter
                            result = fn()
                        else:
                            # Others: use thread executor for timeout
                            with ThreadPoolExecutor(max_workers=1) as ex:
                                fut = ex.submit(fn)
                                result = fut.result(timeout=self.timeout_s)
                return result
            except (FutTimeout, Exception) as e:
                last_err = e
                if attempt < self.max_retries:
                    print(
                        f"[LLMClient] call failed (attempt {attempt + 1}/{self.max_retries + 1}): "
                        f"{repr(e)}; sleep {delay:.2f}s then retry..."
                    )
                    time.sleep(max(0.0, delay))
                    delay *= 2
                    continue
                raise last_err

    # -------------------------------------------------------------------------
    # Chat API
    # -------------------------------------------------------------------------

    def chat(self, messages: List[Dict[str, Any]], json_mode: bool = False, max_tokens: int | None = None) -> str:
        """
        Generate chat completion with vision support.

        Supports text, images, audio, and video content. Media URLs are
        validated for SSRF prevention. For providers without vision support,
        media content is converted to text placeholders.

        Args:
            messages: List of message dicts with role, content, and optional
                     images/audio/video lists
            json_mode: If True, enforce JSON output via:
                       - OpenAI/Ollama: response_format={"type": "json_object"}
                       - Gemini: generation_config={"response_mime_type": "application/json"}

        Returns:
            Generated text response

        Raises:
            ValueError: If provider dialect is unknown
        """
        _max_tokens = max_tokens if max_tokens is not None else self.provider.max_tokens
        _last_llm_meta = {}
        supports_vision = bool(getattr(self.provider, "supports_vision", False))

        # -- LLM traffic log: dispatch capture --
        _log_path = None
        _raw_log = {}
        try:
            _log_env = os.environ.get("FOS_LLM_LOG")
            if _log_env is not None and _log_env.lower() == "off":
                # FOS_LLM_LOG=off (any casing) disables traffic logging.
                _log_path = None
            elif _log_env:
                # An explicit FOS_LLM_LOG path wins as-is.
                _log_path = _log_env
            else:
                # Unset or empty: default under the data repo (never cwd).
                _log_path = _default_llm_traffic_log_path()
            if _log_path is not None:
                _prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
                _raw_log = {
                    "ts": time.time(),
                    "model": self.provider.model,
                    "max_tokens_sent": _max_tokens,
                    "approx_prompt_tokens": _prompt_chars // 4,
                    "messages": messages,
                }
        except Exception:
            _log_path = None
        # -- end dispatch log prep --

        # ── Pre-flight tokenize check ──
        _prompt_text = "\n".join(str(m.get("content", "")) for m in messages)
        _measured_tokens = 0
        try:
            _base = self.provider.base_url or ""
            if _base:
                _tok_url = _base.rstrip("/") + "/tokenize"
                import urllib.request as _ur
                import json as _j
                _req = _ur.Request(_tok_url, data=_j.dumps({"content": _prompt_text}).encode(),
                                   headers={"Content-Type": "application/json"})
                _resp = _ur.urlopen(_req, timeout=10)
                _data = _j.loads(_resp.read())
                _measured_tokens = len(_data.get("tokens", []))
        except Exception:
            _measured_tokens = len(_prompt_text) // 4  # fallback

        _raw_log["measured_prompt_tokens"] = _measured_tokens

        _limit = self.server_ctx_size - _max_tokens - 100
        if _measured_tokens > _limit:
            raise PromptOverflowError(_measured_tokens, self.server_ctx_size)
        # ── end pre-flight ──

        def _call_openai():
            openai = _get_openai()
            raw_result = openai["openai_chat"](
                client=self.client,
                model=self.provider.model,
                messages=messages,
                temperature=self.provider.temperature,
                max_tokens=_max_tokens,
                frequency_penalty=self.provider.frequency_penalty,
                presence_penalty=self.provider.presence_penalty,
                timeout=self.timeout_s,
                allow_vision=supports_vision,
                safe_urls_func=validate_media_url,
                json_mode=json_mode,
            )
            if isinstance(raw_result, dict):
                nonlocal _last_llm_meta
                _last_llm_meta = raw_result
                return raw_result.get("content", "")
            return raw_result

        def _call_gemini():
            gemini = _get_gemini()
            return gemini["gemini_chat"](
                client=self.client,
                model=self.provider.model,
                messages=messages,
                temperature=self.provider.temperature,
                max_tokens=_max_tokens,
                top_p=self.provider.top_p,
                frequency_penalty=self.provider.frequency_penalty,
                presence_penalty=self.provider.presence_penalty,
                safe_urls_func=validate_media_url,
                allow_vision=supports_vision,
                json_mode=json_mode,
            )

        def _call_mock():
            openai = _get_openai()
            msgs = openai["normalize_messages_for_openai"](messages, False, validate_media_url)
            return self.client.chat(msgs, json_mode=json_mode)

        def _call_ollama():
            ollama = _get_ollama()
            return ollama["ollama_chat"](
                client=self.client,
                model=self.provider.model,
                messages=messages,
                temperature=self.provider.temperature,
                top_p=self.provider.top_p,
                max_tokens=_max_tokens,
                timeout=self.timeout_s,
                allow_vision=supports_vision,
                safe_urls_func=validate_media_url,
                json_mode=json_mode,
            )

        import time as _time2
        _llm_start = _time2.perf_counter()
        try:
            if self.provider.dialect == "openai":
                result = self._with_timeout_and_retry(_call_openai)
            elif self.provider.dialect == "gemini":
                result = self._with_timeout_and_retry(_call_gemini)
            elif self.provider.dialect == "mock":
                result = self._with_timeout_and_retry(_call_mock)
            elif self.provider.dialect == "ollama":
                result = self._with_timeout_and_retry(_call_ollama)
            else:
                raise ValueError(T("Unknown LLM dialect: {dialect}", dialect=self.provider.dialect))
        except Exception as _llm_err:
            # -- LLM traffic log: error --
            if _log_path is not None:
                _raw_log["raw_result"] = None
                _raw_log["error"] = str(_llm_err)
                _append_traffic_log(_log_path, _raw_log)
            raise
        _elapsed = _time2.perf_counter() - _llm_start

        try:
            from profiling import prof
            p = prof()
        except Exception:
            p = None
        if p:
            resp_meta = _last_llm_meta if _last_llm_meta else None
            p.record_llm(model=self.provider.model, phase=None,
                         seconds=_elapsed, response=resp_meta)

        # -- LLM traffic log: capture raw result (before harmony stripping) --
        if _log_path is not None:
            _raw_log["raw_result"] = str(result) if result is not None else ""
            _raw_log["error"] = None
            _append_traffic_log(_log_path, _raw_log)
        # -- end log write --

        # Layer 2: strip any thinking/reasoning tokens that leaked through
        text = str(result or "")
        # Harmony-aware: extract only the final assistant message from gpt-oss channels
        import re as _re
        def _extract_harmony_final(t: str) -> str:
            blocks = _re.findall(
                r'<\|start\|>assistant(\w*)<\|message\|>(.*?)(?:<\|end\|>|$)',
                t, _re.DOTALL)
            finals = [c for (ch, c) in blocks if ch in ("final", "")]
            if finals:
                return finals[-1].strip()
            if blocks:  # channels present but no final => reasoning only
                return ""
            return t  # no harmony markers: pass through
        text = _extract_harmony_final(text)
        # Fallback: if text still contains bare "assistantfinal" (structure variant regex missed)
        if "assistantfinal" in text:
            # Split on LAST occurrence, keep what follows
            parts = text.rsplit("assistantfinal", 1)
            if len(parts) == 2:
                text = parts[1]
                # Strip leading delimiters: <|message|>, |response=, response=, or bare |
                text = _re.sub(r'^\s*(?:<\|message\|>|\|response=|response=|\|)\s*', '', text)
        # Safety net: remove any remaining harmony tokens
        text = _re.sub(r'<\|[^|]*\|>', '', text)
        # (strip_thinking_tokens handles None/falsy by returning empty string)
        return strip_thinking_tokens(text)

    # -------------------------------------------------------------------------
    # Completion API
    # -------------------------------------------------------------------------

    def completion(self, prompt: str) -> str:
        """
        Generate text completion from a prompt.

        Args:
            prompt: Text prompt to complete

        Returns:
            Generated text completion

        Raises:
            ValueError: If provider dialect is unknown
        """
        if self.provider.dialect == "openai":
            openai = _get_openai()
            def _do():
                return openai["openai_completion"](
                    client=self.client,
                    model=self.provider.model,
                    prompt=prompt,
                    temperature=self.provider.temperature,
                    max_tokens=self.provider.max_tokens,
                    timeout=self.timeout_s,
                )
            return self._with_timeout_and_retry(_do)

        if self.provider.dialect == "gemini":
            gemini = _get_gemini()
            def _do():
                return gemini["gemini_completion"](self.client, prompt)
            return self._with_timeout_and_retry(_do)

        if self.provider.dialect == "mock":
            return ""

        if self.provider.dialect == "ollama":
            ollama = _get_ollama()
            def _do():
                return ollama["ollama_completion"](
                    client=self.client,
                    model=self.provider.model,
                    prompt=prompt,
                    temperature=self.provider.temperature,
                    top_p=self.provider.top_p,
                    max_tokens=self.provider.max_tokens,
                    timeout=self.timeout_s,
                )
            return self._with_timeout_and_retry(_do)

        raise ValueError(T("Unknown LLM dialect: {dialect}", dialect=self.provider.dialect))

    # -------------------------------------------------------------------------
    # Embedding API
    # -------------------------------------------------------------------------

    def embedding(self, text: str) -> List[float]:
        """
        Generate text embedding vector.

        Args:
            text: Text to embed

        Returns:
            List of embedding float values

        Raises:
            ValueError: If provider dialect is unknown
        """
        if self.provider.dialect == "openai":
            openai = _get_openai()
            def _do():
                return openai["openai_embedding"](
                    client=self.client,
                    model=self.provider.model,
                    text=text,
                    timeout=self.timeout_s,
                )
            return self._with_timeout_and_retry(_do)

        if self.provider.dialect == "gemini":
            gemini = _get_gemini()
            def _do():
                return gemini["gemini_embedding"](self.provider.model, text)
            return self._with_timeout_and_retry(_do)

        if self.provider.dialect == "mock":
            return []

        if self.provider.dialect == "ollama":
            ollama = _get_ollama()
            def _do():
                return ollama["ollama_embedding"](
                    client=self.client,
                    model=self.provider.model,
                    text=text,
                    timeout=self.timeout_s,
                )
            return self._with_timeout_and_retry(_do)

        raise ValueError(T("Unknown LLM dialect: {dialect}", dialect=self.provider.dialect))


def create_llm_client(provider: LLMConfig) -> LLMClient:
    """
    Factory function to create an LLM client.

    Args:
        provider: LLMConfig with provider settings

    Returns:
        Configured LLMClient instance
    """
    return LLMClient(provider)
