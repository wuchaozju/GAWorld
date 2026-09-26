import json
import os
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

import requests

from gaworld.settings import CONFIG
from gaworld.logging_setup import get_logger
from gaworld.llm.stats import GLOBAL_STATS

_LOG = get_logger("gaworld.llm")


# ---------------------------------------------------------------------
# Image input
# ---------------------------------------------------------------------
#
# An image reaches a provider as ``{"media_type": "image/png", "data":
# "<base64>"}`` — the one shape all three wire formats can be built from,
# rather than each caller learning OpenAI's data URL, Anthropic's source
# block and Ollama's bare-base64 array.
#
# Whether the routed model can actually *see* it is a separate question, and
# one only the config knows: an OpenAI-compatible endpoint accepts image
# parts for any model and fails at inference time if the weights are
# text-only. So a provider entry may declare ``"vision": true|false``, and
# absent that declaration we fall back to the model-name heuristic below.
# Callers that need to degrade gracefully (the group interview does) ask
# :func:`provider_supports_images` *before* attaching anything.

#: Model-name fragments that indicate image input. Deliberately a heuristic
#: with an explicit override: new vision models appear faster than this list
#: can be maintained, and being wrong here should be fixable from config
#: rather than by editing code.
_VISION_MODEL_RE = re.compile(
    r"(gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-4-vision|gpt-5|o[34]\b|claude|gemini"
    r"|llava|bakllava|moondream|minicpm-v|pixtral|internvl|glm-4v|step-1v"
    r"|gemma3|gemma4|[-_]vl\b|vision)",
    re.IGNORECASE,
)


def _model_looks_multimodal(model: Any) -> bool:
    return bool(_VISION_MODEL_RE.search(str(model or "")))


def _data_url(image: dict[str, Any]) -> str:
    media_type = str(image.get("media_type") or "image/png")
    return f"data:{media_type};base64,{image.get('data') or ''}"


def _clean_images(images: Any) -> list[dict[str, Any]]:
    """Keep only well-formed ``{media_type, data}`` entries."""
    cleaned: list[dict[str, Any]] = []
    for item in images or []:
        if not isinstance(item, dict):
            continue
        data = str(item.get("data") or "").strip()
        if not data:
            continue
        cleaned.append({"media_type": str(item.get("media_type") or "image/png"), "data": data})
    return cleaned


# ---------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------
_RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class EmptyCompletionError(RuntimeError):
    """Raised when a provider answers successfully but carries no text.

    A blank completion is not a usable result: callers write it straight
    into artifacts, memories, or JSON parsers, where it silently degrades
    into empty files and bogus defaults. Surfacing it as an error lets the
    router try the fallback chain and lets callers fail loudly instead.
    """


def _empty_completion(
    provider: str,
    *,
    stop_reason: Any = None,
    block_types: Any = None,
    max_tokens: Any = None,
) -> EmptyCompletionError:
    detail = (
        f"provider={provider} stop_reason={stop_reason!r} "
        f"blocks={block_types!r} max_tokens={max_tokens!r}"
    )
    if stop_reason == "max_tokens":
        return EmptyCompletionError(
            "LLM returned no text: the max_tokens budget ran out before any "
            f"answer was emitted ({detail}). Reasoning models spend this budget "
            "on their thinking block first — raise max_tokens for this provider."
        )
    return EmptyCompletionError(f"LLM returned an empty completion ({detail}).")


# ---------------------------------------------------------------------------
# Truncation is information the API gives us and the old code threw away.
# ---------------------------------------------------------------------------

#: ``provider -> times the output cap cut a *non-empty* answer short``.
_TRUNCATED: dict[str, int] = {}


def truncation_counts() -> dict[str, int]:
    """How many completions were cut off by ``max_tokens``, per provider."""
    return dict(_TRUNCATED)


def reset_truncation_counts() -> None:
    _TRUNCATED.clear()


def _note_truncated(provider: str, reason: Any, max_tokens: Any) -> None:
    """Warn when the provider says it stopped because it ran out of budget.

    Both API shapes already report this -- Anthropic as ``stop_reason ==
    "max_tokens"``, OpenAI as ``finish_reason == "length"`` -- and the old code
    consulted it only when the answer came back *empty*. A truncated answer
    with text in it was returned as though it were complete, so every
    downstream parser saw a malformed response and could not tell "the model
    said something unparseable" from "the model was cut off mid-sentence".

    Measured on 848 real ``actions`` completions, that was 318 of them (37.5%),
    silently. Hence the escalating log: at a rate like that, one line per call
    is unreadable and one line per run is too easy to miss.

    This does not raise. A truncated answer is often still usable -- the action
    space parser salvages the activities that closed -- and turning a degraded
    result into a hard failure would be a worse trade.
    """
    if str(reason) not in ("max_tokens", "length"):
        return
    count = _TRUNCATED.get(provider, 0) + 1
    _TRUNCATED[provider] = count
    if count in (1, 10, 100) or count % 500 == 0:
        _LOG.warning(
            "LLM output was truncated by max_tokens=%s (%s, %s time(s) so far). "
            "Downstream parsers see this as malformed input; raise max_tokens "
            "for this provider, or ask for less per call.",
            max_tokens, provider, count,
        )


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        if resp is not None and resp.status_code in _RETRYABLE_HTTP:
            return True
        return False
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


def _retrying(
    call: Callable[[], Any], *, attempts: int = 3, backoff: float = 1.5, provider: str = "", task: str = ""
) -> Any:
    """Run ``call`` with bounded exponential backoff on transient errors."""
    delay = 0.6
    last_exc: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return call()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_retryable(exc):
                raise
            _LOG.warning(
                "LLM call failed (attempt %d/%d, provider=%s, task=%s): %s — retrying in %.1fs",
                attempt,
                attempts,
                provider,
                task,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= backoff
    # Unreachable, but keep mypy happy.
    if last_exc is not None:  # pragma: no cover
        raise last_exc
    raise RuntimeError("retrying() failed without exception")


class OllamaProvider:
    """Simple wrapper for Ollama-compatible text generation."""

    def __init__(self, url, model, timeout=600, attempts=3, vision=None):
        self.url = url
        self.model = model
        self.timeout = timeout
        self.attempts = attempts
        self.vision = vision

    @property
    def supports_images(self) -> bool:
        if self.vision is not None:
            return bool(self.vision)
        return _model_looks_multimodal(self.model)

    def call(self, prompt, system=None, temperature=None, images=None, max_tokens=None):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
        }
        # Ollama's /api/generate takes bare base64 strings, no data URL.
        cleaned = _clean_images(images)
        if cleaned:
            payload["images"] = [item["data"] for item in cleaned]
        if system:
            payload["system"] = system
        options = {}
        if temperature is not None:
            options["temperature"] = float(temperature)
        if max_tokens is not None:
            options["num_predict"] = int(max_tokens)
        if options:
            payload["options"] = options

        def _do() -> str:
            try:
                with requests.post(
                    self.url,
                    json=payload,
                    timeout=(10, self.timeout),
                    stream=True,
                ) as r:
                    r.raise_for_status()
                    parts: list[str] = []
                    for line in r.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        # Use stdlib json instead of requests' private complexjson alias.
                        try:
                            data = json.loads(line)
                        except (json.JSONDecodeError, TypeError):
                            continue
                        chunk = data.get("response", "")
                        if chunk:
                            parts.append(chunk)
                        if data.get("done"):
                            break
                    return "".join(parts)
            except requests.exceptions.ReadTimeout as exc:
                raise requests.exceptions.ReadTimeout(
                    f"Ollama provider timed out while calling model '{self.model}'. "
                    f"Current timeout={self.timeout}s. "
                    f"If this model is slow locally, raise the provider's timeout "
                    f"(配置面板 -> 模型后端, or llm.providers in dashboard_config.json)."
                ) from exc

        return _retrying(_do, attempts=self.attempts, provider=f"ollama:{self.model}", task="")


class OpenAIProvider:
    """OpenAI Chat Completions wrapper (single-turn)."""

    def __init__(
        self,
        base_url,
        model,
        api_key=None,
        api_key_env="OPENAI_API_KEY",
        timeout=120,
        stream=False,
        max_tokens=None,
        temperature=None,
        attempts=3,
        vision=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        self.api_key = api_key or os.getenv(api_key_env)
        self.timeout = timeout
        self.stream = bool(stream)
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.attempts = attempts
        self.vision = vision

    @property
    def supports_images(self) -> bool:
        if self.vision is not None:
            return bool(self.vision)
        return _model_looks_multimodal(self.model)

    def call(self, prompt, system=None, temperature=None, images=None, max_tokens=None):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        cleaned = _clean_images(images)
        if cleaned:
            # Multi-part content. The text part stays first: the prompt is
            # what carries the persona and the answer-format contract, and
            # models weight the leading part of the turn more heavily.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *(
                            {"type": "image_url", "image_url": {"url": _data_url(item)}}
                            for item in cleaned
                        ),
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
        }
        effective_max_tokens = self.max_tokens if max_tokens is None else int(max_tokens)
        if effective_max_tokens is not None:
            payload["max_tokens"] = effective_max_tokens
        # A per-call temperature wins over the provider default: an experiment
        # that needs T=1 sampling must not be silently pinned to the config's
        # T=0.2, which would collapse the draw-to-draw variation it measures.
        effective_temperature = self.temperature if temperature is None else temperature
        if effective_temperature is not None:
            payload["temperature"] = float(effective_temperature)

        def _do_streaming() -> str:
            stream_payload = dict(payload, stream=True)
            with requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=stream_payload,
                timeout=(10, self.timeout),
                stream=True,
            ) as r:
                r.raise_for_status()
                parts: list[str] = []
                for raw_line in r.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    # Skip SSE metadata / keep-alive lines such as:
                    # `event: message`, `: keep-alive`, or empty chunks.
                    if not line or line.startswith(":") or line.startswith("event:"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    line = line[5:].strip()
                    if not line:
                        continue
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        # Some OpenAI-compatible backends emit non-JSON
                        # heartbeat payloads in `data:` frames.
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    chunk = delta.get("content")
                    if isinstance(chunk, str) and chunk:
                        parts.append(chunk)
                        continue
                    if isinstance(chunk, list):
                        for item in chunk:
                            if isinstance(item, dict):
                                text = item.get("text")
                                if isinstance(text, str) and text:
                                    parts.append(text)
                        continue
                    message = choices[0].get("message") or {}
                    chunk = message.get("content")
                    if isinstance(chunk, str) and chunk:
                        parts.append(chunk)
                        continue
                    if isinstance(chunk, list):
                        for item in chunk:
                            if isinstance(item, dict):
                                text = item.get("text")
                                if isinstance(text, str) and text:
                                    parts.append(text)
                return "".join(parts)

        def _do_blocking() -> str:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            _note_truncated(
                f"openai:{self.model}", choice.get("finish_reason"), effective_max_tokens
            )
            return data["choices"][0]["message"]["content"]

        if self.stream:
            return _retrying(
                _do_streaming, attempts=self.attempts, provider=f"openai:{self.model}", task=""
            )
        return _retrying(
            _do_blocking, attempts=self.attempts, provider=f"openai:{self.model}", task=""
        )

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Call OpenAI-compatible /embeddings endpoint.

        ``model`` overrides ``self.model`` for the call (the chat model
        is rarely an embeddings model). Returns a list of float vectors
        aligned with ``texts``. Raises on transport errors so the caller
        can fall back to the hash embedding.
        """
        if not texts:
            return []
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self.model,
            "input": list(texts),
        }

        def _do() -> list[list[float]]:
            r = requests.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("data") or []
            # OpenAI returns items in index order; sort defensively.
            items = sorted(items, key=lambda x: x.get("index", 0))
            return [list(map(float, item.get("embedding", []))) for item in items]

        return _retrying(_do, provider=f"openai:{payload['model']}", task="embed")


class AnthropicProvider:
    """Anthropic/Claude message API wrapper."""

    def __init__(
        self,
        base_url,
        model,
        api_key=None,
        api_key_env="ANTHROPIC_API_KEY",
        api_key_envs=None,
        anthropic_version="2023-06-01",
        timeout=120,
        max_tokens=512,
        system=None,
        beta=None,
        authorization_bearer=False,
        authorization_scheme=None,
        include_x_api_key=True,
        authorization_retry_schemes=None,
        attempts=3,
        vision=None,
    ):
        self.attempts = attempts
        self.vision = vision
        self.base_url = base_url.rstrip("/")
        self.model = model
        env_names = list(api_key_envs or [])
        if api_key_env and api_key_env not in env_names:
            env_names.insert(0, api_key_env)
        self.api_key = api_key
        self.api_key_source = "config.api_key" if api_key else ""
        if not self.api_key:
            for env_name in env_names:
                self.api_key = os.getenv(env_name)
                if self.api_key:
                    self.api_key_source = env_name
                    break
        self.api_key_envs = env_names
        self.anthropic_version = anthropic_version
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.system = system
        self.beta = beta
        if authorization_scheme is None and authorization_bearer:
            authorization_scheme = "bearer"
        self.authorization_scheme = str(authorization_scheme or "").strip().lower()
        self.authorization_bearer = self.authorization_scheme == "bearer"
        self.include_x_api_key = bool(include_x_api_key)
        self.authorization_retry_schemes = [
            str(item or "").strip().lower()
            for item in (authorization_retry_schemes or [])
            if str(item or "").strip()
        ]

    @property
    def supports_images(self) -> bool:
        if self.vision is not None:
            return bool(self.vision)
        return _model_looks_multimodal(self.model)

    def call(self, prompt, system=None, temperature=None, images=None, max_tokens=None):
        if not self.api_key:
            env_names = ", ".join(self.api_key_envs) or "ANTHROPIC_API_KEY"
            raise ValueError(f"Anthropic provider API key not found. Set one of: {env_names}")
        cleaned = _clean_images(images)
        if cleaned:
            # Anthropic puts images *before* the text that asks about them;
            # the API docs call this out as measurably better for
            # image-question turns.
            content: Any = [
                *(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": item["media_type"],
                            "data": item["data"],
                        },
                    }
                    for item in cleaned
                ),
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens if max_tokens is None else int(max_tokens),
            "messages": [{"role": "user", "content": content}],
        }
        effective_system = system or self.system
        if effective_system:
            payload["system"] = effective_system
        if temperature is not None:
            payload["temperature"] = float(temperature)

        return _retrying(
            lambda: self._call_once(payload),
            attempts=self.attempts,
            provider=f"anthropic:{self.model}",
            task="",
        )

    def _call_once(self, payload):
        schemes = [self.authorization_scheme]
        for scheme in self.authorization_retry_schemes:
            if scheme not in schemes:
                schemes.append(scheme)
        attempts = []
        last_response = None
        last_exc = None
        for scheme in schemes:
            headers = {
                "anthropic-version": self.anthropic_version,
                "Content-Type": "application/json",
            }
            if self.include_x_api_key:
                headers["x-api-key"] = self.api_key
            if scheme == "bearer":
                headers["Authorization"] = f"Bearer {self.api_key}"
            elif scheme == "raw":
                headers["Authorization"] = self.api_key
            if self.beta:
                headers["anthropic-beta"] = self.beta
            r = requests.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            try:
                r.raise_for_status()
                data = r.json()
                parts = []
                for block in data.get("content", []):
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        parts.append(block["text"])
                text = "".join(parts)
                if not text.strip():
                    raise _empty_completion(
                        f"anthropic:{self.model}",
                        stop_reason=data.get("stop_reason"),
                        block_types=[
                            block.get("type") for block in data.get("content", []) if isinstance(block, dict)
                        ],
                        max_tokens=payload["max_tokens"],
                    )
                _note_truncated(
                    f"anthropic:{self.model}", data.get("stop_reason"), payload["max_tokens"]
                )
                return text
            except requests.exceptions.HTTPError as exc:
                last_response = r
                last_exc = exc
                attempts.append(
                    {
                        "scheme": scheme or "none",
                        "status": r.status_code,
                        "authorization_sent": "Authorization" in headers,
                        "x_api_key_sent": "x-api-key" in headers,
                    }
                )
                if r.status_code != 401:
                    break
                continue

        body = last_response.text.strip() if last_response is not None else ""
        if len(body) > 800:
            body = body[:800] + "..."
        env_names = ", ".join(self.api_key_envs) or "ANTHROPIC_API_KEY"
        status = last_response.status_code if last_response is not None else "unknown"
        raise requests.exceptions.HTTPError(
            f"Anthropic provider request failed with HTTP {status}. "
            f"base_url={self.base_url!r}, model={self.model!r}, "
            f"api_key_present={bool(self.api_key)}, api_key_envs=[{env_names}], "
            f"api_key_source={self.api_key_source!r}, attempts={attempts!r}, "
            f"response={body!r}"
        ) from last_exc


def build_provider(cfg: dict[str, Any], *, attempts: int = 3):
    """Instantiate one backend from its ``llm.providers`` block, or ``None``.

    Factored out of :meth:`LLMRouter._init_providers` so the 配置 panel's
    connectivity check builds the *same* object the simulator will use. A probe
    that talked to the endpoint through its own hand-rolled request would go on
    passing after the router's construction drifted — which is precisely the
    failure a "测试连通性" button is supposed to catch.

    ``attempts`` is threaded through so the probe can ask for a single shot:
    the router's three-with-backoff turns an unreachable endpoint into a
    minute of silence in a UI that promised an answer.
    """
    p_type = cfg.get("type")
    if p_type == "ollama":
        return OllamaProvider(
            cfg.get("url", "http://localhost:11434/api/generate"),
            cfg["model"],
            # Local models are slow: a 12B answer takes ~75s on this machine and
            # long agent prompts run several times that, so a low default only
            # produces ReadTimeout mid-run.
            timeout=cfg.get("timeout", 600),
            attempts=attempts,
            vision=cfg.get("vision"),
        )
    if p_type == "openai":
        return OpenAIProvider(
            cfg.get("base_url", "https://api.openai.com/v1"),
            cfg["model"],
            api_key=cfg.get("api_key"),
            api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
            timeout=cfg.get("timeout", 120),
            stream=cfg.get("stream", False),
            max_tokens=cfg.get("max_tokens"),
            temperature=cfg.get("temperature"),
            attempts=attempts,
            vision=cfg.get("vision"),
        )
    if p_type in ("claude", "anthropic"):
        return AnthropicProvider(
            cfg.get("base_url", "https://api.anthropic.com"),
            cfg["model"],
            api_key=cfg.get("api_key") or cfg.get("ANTHROPIC_AUTH_TOKEN"),
            api_key_env=cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
            api_key_envs=cfg.get("api_key_envs"),
            anthropic_version=cfg.get("anthropic_version", "2023-06-01"),
            timeout=cfg.get("timeout", 120),
            max_tokens=cfg.get("max_tokens", 512),
            system=cfg.get("system"),
            beta=cfg.get("anthropic_beta"),
            authorization_bearer=cfg.get("authorization_bearer", False),
            authorization_scheme=cfg.get("authorization_scheme"),
            include_x_api_key=cfg.get("include_x_api_key", True),
            authorization_retry_schemes=cfg.get("authorization_retry_schemes"),
            attempts=attempts,
            vision=cfg.get("vision"),
        )
    return None


#: Prompt for :func:`probe_provider`. Short enough to cost nothing, explicit
#: enough that a backend answering *anything* proves the round trip works.
_PROBE_PROMPT = "Reply with the single word: OK"


def probe_provider(cfg: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
    """One real generation against ``cfg``. Never raises — the verdict is data.

    Deliberately a *real* call rather than a socket/HTTP-200 check: the ways an
    LLM backend is "reachable but useless" (model name not pulled, key rejected,
    reasoning budget consumed before any text) all return a healthy connection
    and would pass any cheaper test.

    ``timeout`` caps the configured one rather than replacing it, so a provider
    deliberately set to 10s is not probed for 30.
    """
    name = str(cfg.get("model") or "")
    p_type = str(cfg.get("type") or "")
    if not p_type:
        return {"ok": False, "error": "没有填 type（后端类型）。"}
    probe_cfg = dict(cfg)
    probe_cfg["timeout"] = min(int(cfg.get("timeout") or timeout), timeout)
    try:
        provider = build_provider(probe_cfg, attempts=1)
    except KeyError:
        return {"ok": False, "error": "没有填 model（模型名）。"}
    if provider is None:
        return {"ok": False, "error": f"不支持的后端类型：{p_type}"}
    # Checked before the call so a missing key reads as "set this env var"
    # rather than as the backend's own 401.
    if isinstance(provider, (OpenAIProvider, AnthropicProvider)) and not provider.api_key:
        envs = getattr(provider, "api_key_envs", None) or [getattr(provider, "api_key_env", "")]
        return {
            "ok": False,
            "error": "没有拿到密钥：环境变量 " + "、".join(n for n in envs if n) + " 没有设置。"
            "请在仓库根目录的 .env 里配好，然后重启仿真进程。",
        }
    started = time.perf_counter()
    try:
        reply = provider.call(_PROBE_PROMPT)
    except Exception as exc:  # every transport/auth/shape failure is a verdict
        detail = str(exc)
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": detail if len(detail) <= 600 else detail[:600] + "…",
        }
    text = str(reply or "").strip()
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "model": name,
        "sample": text if len(text) <= 200 else text[:200] + "…",
    }


class LLMRouter:
    """Lightweight router for selecting providers by task or agent."""

    def __init__(self, config):
        self.config = config
        self.providers = self._init_providers()
        self.routing = config.get("llm", {}).get("routing", {})

    def _init_providers(self):
        providers = {}
        llm_cfg = self.config.get("llm", {})
        for name, cfg in llm_cfg.get("providers", {}).items():
            provider = build_provider(cfg)
            if provider is None:
                print(f"⚠️ 跳过不支持的 LLM provider 类型: {name} ({cfg.get('type')})")
                continue
            providers[name] = provider
        if not providers:
            raise ValueError("No LLM providers configured.")
        return providers

    def _select_provider(self, task=None, agent_id=None):
        tasks = self.routing.get("tasks", {})
        if task and task in tasks:
            return tasks[task]
        agents = self.routing.get("agents", {})
        if agent_id is not None and str(agent_id) in agents:
            return agents[str(agent_id)]
        return self.routing.get("default") or next(iter(self.providers))

    def _resolve_chain(self, task=None, agent_id=None, provider=None):
        """Return an ordered list of provider names to try for a single call.

        Resolution order:

        1. Primary provider chosen by :meth:`_select_provider`.
        2. Optional ``llm.routing.fallback`` list (global) — these are
           appended after the primary, deduplicated, and any unknown
           name is silently skipped.

        The returned list is never empty (the primary is always
        included), so callers don't have to special-case fallback being
        absent.
        """
        # An explicit provider wins over task/agent routing. Used by callers
        # that let a human pick the backend for one run (the Population Studio
        # panel), where silently honouring the config's routing instead would
        # make the UI's model selector a lie.
        primary = provider or self._select_provider(task=task, agent_id=agent_id)
        chain: list[str] = [primary]
        fallback = self.routing.get("fallback", [])
        if isinstance(fallback, str):
            fallback = [fallback]
        if isinstance(fallback, (list, tuple)):
            for name in fallback:
                name = str(name).strip()
                if not name or name == primary or name in chain:
                    continue
                if name in self.providers:
                    chain.append(name)
        return chain

    def call(
        self,
        prompt,
        task=None,
        agent_id=None,
        provider=None,
        system=None,
        temperature=None,
        allow_fallback=True,
        images=None,
        max_tokens=None,
    ):
        chain = self._resolve_chain(task=task, agent_id=agent_id, provider=provider)
        if not allow_fallback:
            # Falling back to a different model is the right default for a
            # simulation — a finished run beats a crashed one. It is the
            # wrong default for an experiment: cells answered by different
            # models turn a between-arm comparison into a between-model
            # one, silently, and nothing downstream can detect it.
            chain = chain[:1]
        if not chain or chain[0] not in self.providers:
            raise ValueError(f"Provider '{chain[0] if chain else ''}' not found in config.")

        # Only forward the overrides the caller actually set. Passing
        # ``system=None`` unconditionally would break any provider-shaped
        # object whose ``call`` still takes the prompt alone.
        overrides: dict[str, Any] = {}
        if system is not None:
            overrides["system"] = system
        if temperature is not None:
            overrides["temperature"] = temperature
        if max_tokens is not None:
            overrides["max_tokens"] = max_tokens
        cleaned_images = _clean_images(images)
        if cleaned_images:
            overrides["images"] = cleaned_images

        call_id = uuid.uuid4().hex[:8]
        prompt_chars = len(prompt or "")
        log = _LOG
        last_exc: BaseException | None = None
        for index, provider_name in enumerate(chain):
            started = time.perf_counter()
            try:
                result = self.providers[provider_name].call(prompt, **overrides)
                if not str(result or "").strip():
                    raise _empty_completion(provider_name)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                GLOBAL_STATS.record(
                    task=task or "",
                    provider=provider_name,
                    latency_ms=elapsed_ms,
                    ok=True,
                )
                log.debug(
                    "llm.call ok id=%s provider=%s fallback_index=%d task=%s agent=%s "
                    "prompt_chars=%d completion_chars=%d latency_ms=%d",
                    call_id,
                    provider_name,
                    index,
                    task or "",
                    agent_id if agent_id is not None else "",
                    prompt_chars,
                    len(result or ""),
                    elapsed_ms,
                )
                return result
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                # Record the failure attempt. A subsequent fallback
                # provider will record its own outcome; we still want
                # the failing attempt to show up in the failure count
                # so that operators see the true rate.
                GLOBAL_STATS.record(
                    task=task or "",
                    provider=provider_name,
                    latency_ms=elapsed_ms,
                    ok=False,
                )
                log.warning(
                    "llm.call err id=%s provider=%s fallback_index=%d task=%s agent=%s "
                    "prompt_chars=%d latency_ms=%d error=%s",
                    call_id,
                    provider_name,
                    index,
                    task or "",
                    agent_id if agent_id is not None else "",
                    prompt_chars,
                    elapsed_ms,
                    exc,
                )
                last_exc = exc
                # Only fall through to the next provider if there is one
                # AND the failure looks transient (or auth/config).
                # Auth errors on the primary may indicate misconfig;
                # the fallback might still succeed if it has a different
                # credential, so we attempt it.
                if index + 1 >= len(chain):
                    break
                continue

        log.error(
            "llm.call failed across %d providers id=%s task=%s agent=%s",
            len(chain),
            call_id,
            task or "",
            agent_id if agent_id is not None else "",
        )
        assert last_exc is not None
        raise last_exc


LLM_ROUTER = LLMRouter(CONFIG)


def available_providers():
    """Configured provider names with their type and model, for UI pickers."""
    llm_cfg = CONFIG.get("llm", {}) if isinstance(CONFIG, dict) else {}
    out = []
    for name, cfg in (llm_cfg.get("providers", {}) or {}).items():
        if not isinstance(cfg, dict):
            continue
        out.append(
            {
                "name": name,
                "type": str(cfg.get("type", "")),
                "model": str(cfg.get("model", "")),
                "base_url": str(cfg.get("base_url") or cfg.get("url") or ""),
                "is_default": name == (llm_cfg.get("routing", {}) or {}).get("default"),
            }
        )
    return out


def resolve_provider(task=None, agent_id=None, provider=None) -> str:
    """Name of the provider a call with these arguments would hit first.

    Lets a caller record *which model actually answered* alongside the
    answer, so model provenance survives into the artifact.
    """
    return LLM_ROUTER._resolve_chain(task=task, agent_id=agent_id, provider=provider)[0]


def provider_supports_images(task=None, agent_id=None, provider=None) -> bool:
    """Whether the provider this call would route to accepts image input.

    Asked *before* attaching an image so a caller can degrade deliberately —
    swapping the picture for its caption and saying so — instead of sending
    an image part to a text-only model and getting an opaque 400 back, or
    worse, an answer that quietly ignored it.
    """
    name = resolve_provider(task=task, agent_id=agent_id, provider=provider)
    backend = LLM_ROUTER.providers.get(name)
    return bool(getattr(backend, "supports_images", False))


def call_llm(
    prompt,
    task=None,
    agent_id=None,
    provider=None,
    system=None,
    temperature=None,
    allow_fallback=True,
    images=None,
    max_tokens=None,
):
    """Public helper for model calls used across the simulator.

    Each invocation:

    * runs through retry / backoff for transient errors,
    * is logged with provider, task, agent, prompt size, and latency,
    * raises the original :class:`requests` exception on hard failure.

    ``system`` and ``temperature`` are per-call overrides. Both default to
    ``None`` = "use the provider's configured behaviour", so existing
    callsites are unaffected. They exist for prompt-design experiments,
    where the system message *is* the treatment and the sampling
    temperature is part of the protocol rather than a deployment setting.

    ``allow_fallback=False`` pins the call to a single model: an
    experiment would rather lose a cell than have it answered by a
    different model than its neighbours.

    ``images`` is a list of ``{"media_type": ..., "data": "<base64>"}``
    entries, forwarded only when non-empty so provider-shaped test doubles
    whose ``call`` takes the prompt alone keep working. Check
    :func:`provider_supports_images` first — this function does not.

    ``max_tokens`` raises (or lowers) the output cap for one call. The
    configured default suits this simulator's usual turn — one event, one
    decision, a short profile — so a caller that needs a whole structured
    document has to say so, or the provider truncates it mid-JSON and every
    parser downstream sees malformed input rather than a budget problem.
    """
    return LLM_ROUTER.call(
        prompt,
        task=task,
        agent_id=agent_id,
        provider=provider,
        system=system,
        temperature=temperature,
        allow_fallback=allow_fallback,
        images=images,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------
# Embedding helper (D2 of the RAG enhancement plan)
# ---------------------------------------------------------------------
#
# The memory store calls :func:`embed_text` to turn a piece of text into
# a vector. It expects ``list[float] | None``; ``None`` means "fall
# back to the hash bag-of-words" so the memory store stays usable when
# no embedding provider is configured (or the embeddings endpoint is
# unreachable). This keeps the existing zero-dep test suite green.
#
# Configuration shape:
#   llm.embedding = {
#       "provider": "<name of an OpenAI-compatible provider in
#                     llm.providers>",
#       "model":    "text-embedding-3-small",   # OpenAI-style
#   }
# Plus the global toggle ``vector_db_embedding_provider`` in
# runtime settings selects "hash" (default) or "llm".


def _embedding_provider_name() -> str | None:
    return (CONFIG.get("llm", {}).get("embedding", {}) or {}).get("provider")


def _embedding_model_name() -> str | None:
    return (CONFIG.get("llm", {}).get("embedding", {}) or {}).get("model")


def embed_text(text, task: str | None = None) -> list[float] | None:
    """Return an embedding vector for ``text``, or ``None`` on failure.

    The function never raises: callers depend on a clean fallback to
    the hash embedding when LLM-side embeddings are unavailable.
    """
    if CONFIG.get("vector_db_embedding_provider", "hash") != "llm":
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    provider_name = _embedding_provider_name()
    if not provider_name or provider_name not in LLM_ROUTER.providers:
        return None
    provider = LLM_ROUTER.providers[provider_name]
    if not hasattr(provider, "embed"):
        return None
    try:
        vecs = provider.embed([text], model=_embedding_model_name())
    except Exception as exc:
        _LOG.warning("embed_text failed via %s (task=%s): %s", provider_name, task or "", exc)
        return None
    if not vecs or not vecs[0]:
        return None
    return [float(x) for x in vecs[0]]
