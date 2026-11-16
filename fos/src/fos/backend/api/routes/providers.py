"""
LLM provider configuration API routes.

Handles CRUD operations for user LLM provider configurations including
OpenAI, Gemini, Ollama, and mock providers. Supports provider testing,
activation, and credential management.

Contains:
    - list_providers: GET all providers for current user
    - create_provider: POST create new provider
    - update_provider: PATCH update provider
    - delete_provider: DELETE provider
    - test_provider: POST test provider connectivity
    - activate_provider: POST set provider as active
"""
from datetime import datetime, timezone

import httpx
from litestar import Router, delete, get, patch, post
from litestar.exceptions import HTTPException
from fos.i18n import T
from litestar.connection import Request
from sqlalchemy import select

import re

from fos.core.llm import create_llm_client
from fos.core.llm_config import LLMConfig, guess_supports_vision
from fos.i18n import T

from ...core.database import get_session
from ...dependencies import extract_bearer_token, resolve_current_user
from ...models.user import ProviderConfig, User
from ...schemas.common import Message
from ...schemas.provider import ProviderBase, ProviderCreate, ProviderUpdate
from ...services.default_providers import get_default_ollama_base_url
from ...services.provider_dialect import normalize_provider_dialect


def _redact_secret(value: str) -> str:
    """Redact potential API keys and secrets from error messages.

    Replaces long alphanumeric strings (likely API keys) with [REDACTED].
    """
    # Redact common API key patterns: 20+ consecutive hex/base64 chars
    value = re.sub(r'[A-Za-z0-9+/=_-]{20,}', '[REDACTED]', value)
    return value


def _normalize_dialect(raw: str, base_url: str | None) -> tuple[str, str | None]:
    """
    Normalize provider dialect and base_url.

    For OpenAI-compatible APIs on localhost:
    - If the provider is explicitly a local OpenAI-compatible server (lmstudio,
      llamacpp, vllm, etc.), keep the "openai" dialect and preserve /v1 path.
    - Otherwise (e.g., user typed "openai" pointing at localhost), fall back
      to Ollama dialect for backward compatibility.

    Args:
        raw: Provider type string (e.g., "openai", "ollama", "lmstudio", "gemini")
        base_url: Optional base URL for the provider

    Returns:
        Tuple of (normalized_dialect, normalized_base_url)
    """
    raw_lower = (raw or "").strip().lower().replace("_", "-")
    val = normalize_provider_dialect(raw)

    if val == "ollama":
        # Strip /v1 suffix if present (native Ollama API doesn't use it)
        if base_url and "/v1" in base_url:
            base_url = base_url.replace("/v1", "").rstrip("/")
        return "ollama", base_url

    # Don't apply the localhost heuristic for explicitly configured
    # local OpenAI-compatible providers like LM Studio, llama.cpp, vLLM.
    # These serve the standard OpenAI API at /v1/chat/completions.
    if raw_lower in {"lmstudio", "llamacpp", "vllm"}:
        return "openai", base_url

    # Heuristic: "openai" provider + the canonical Ollama port 11434 ⇒ treat
    # as ollama. The localhost hostname alone is NOT an Ollama signal: LM Studio,
    # llama.cpp, vLLM, TGI and LocalAI all run on localhost and speak the OpenAI
    # dialect, so only the port is a reliable Ollama fingerprint here.
    if val == "openai" and base_url and ":11434" in base_url:
        if "/v1" in base_url:
            base_url = base_url.replace("/v1", "").rstrip("/")
        return "ollama", base_url

    return val, base_url


def _serialize_provider(provider: ProviderConfig) -> ProviderBase:
    serialized_provider = provider.provider
    if normalize_provider_dialect(provider.provider) == "openai":
        serialized_provider = "openai-compatible"

    return ProviderBase(
        id=provider.id,
        name=provider.name,
        provider=serialized_provider,
        model=provider.model,
        base_url=provider.base_url,
        has_api_key=bool(provider.api_key),
        is_active=bool((provider.config or {}).get("active")),
        is_default=bool((provider.config or {}).get("active")),
        last_test_status=provider.last_test_status,
        last_tested_at=provider.last_tested_at,
        last_error=provider.last_error,
        config=provider.config,
    )


async def _test_ollama_connection(
    provider: ProviderConfig,
    normalized_base_url: str | None,
) -> None:
    base_url = (normalized_base_url or get_default_ollama_base_url()).rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3].rstrip("/")

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{base_url}/api/tags")
        response.raise_for_status()
        payload = response.json()

    model_name = (provider.model or "").strip()
    if not model_name:
        return

    available_models = set()
    for item in payload.get("models", []) or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            model = str(item.get("model") or "").strip()
            if name:
                available_models.add(name)
            if model:
                available_models.add(model)

    if model_name not in available_models:
        raise ValueError(T("api.providers.ollama_model_not_found", model_name=model_name))


@get("/")
async def list_providers(request: Request) -> list[ProviderBase]:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        result = await session.execute(
            select(ProviderConfig).where(ProviderConfig.user_id == current_user.id)
        )
        providers = result.scalars().all()
        return [_serialize_provider(p) for p in providers]


@post("/", status_code=201)
async def create_provider(request: Request, data: ProviderCreate) -> ProviderBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        # Determine if this will be the first provider for this user
        existing = await session.execute(
            select(ProviderConfig.id)
            .where(ProviderConfig.user_id == current_user.id)
            .limit(1)
        )
        has_any = existing.scalars().first() is not None

        cfg = dict(data.config or {})
        if not has_any:
            # First provider: mark as active by default
            cfg["active"] = True

        provider = ProviderConfig(
            user_id=current_user.id,
            name=data.name,
            provider=normalize_provider_dialect(data.provider),
            model=data.model,
            base_url=data.base_url,
            api_key=data.api_key,
            config=cfg,
        )
        session.add(provider)
        await session.commit()
        await session.refresh(provider)
        return _serialize_provider(provider)


@patch("/{provider_id:int}")
async def update_provider(
    request: Request, provider_id: int, data: ProviderUpdate
) -> ProviderBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = await session.get(ProviderConfig, provider_id)
        if provider is None or provider.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=T("api.errors.provider_not_authorized"))

        if data.name is not None:
            provider.name = data.name
        if data.provider is not None:
            provider.provider = normalize_provider_dialect(data.provider)
        if data.model is not None:
            provider.model = data.model
        if data.base_url is not None:
            provider.base_url = data.base_url
        if data.api_key is not None:
            provider.api_key = data.api_key
        if data.config is not None:
            provider.config = data.config

        await session.commit()
        await session.refresh(provider)
        return _serialize_provider(provider)


@delete("/{provider_id:int}", status_code=204)
async def delete_provider(request: Request, provider_id: int) -> None:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = await session.get(ProviderConfig, provider_id)
        if provider is None or provider.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=T("api.errors.provider_not_authorized"))

        is_ollama = normalize_provider_dialect(provider.provider) == "ollama"
        model_name = (provider.model or "").strip()

        await session.delete(provider)
        await session.commit()

        if is_ollama and model_name:
            try:
                user_row = await session.get(User, current_user.id)
                user_config = dict(user_row.config or {}) if user_row else {}
                excluded = list(user_config.get("excluded_ollama_models", []))
                if model_name not in excluded:
                    excluded.append(model_name)
                    user_config["excluded_ollama_models"] = excluded
                    if user_row:
                        user_row.config = user_config
                        await session.commit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to update excluded_ollama_models: {e}")


@post("/{provider_id:int}/test")
async def test_provider(request: Request, provider_id: int) -> Message:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = await session.get(ProviderConfig, provider_id)
        if provider is None or provider.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=T("api.errors.provider_not_authorized"))

        dialect, normalized_base_url = _normalize_dialect(provider.provider, provider.base_url)
        cfg = LLMConfig(
            dialect=dialect,
            api_key=provider.api_key or "",
            model=provider.model,
            base_url=normalized_base_url,
            temperature=0.7,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=4096,
            supports_vision=guess_supports_vision(provider.model),
        )

        provider.last_tested_at = datetime.now(timezone.utc)
        try:
            if dialect == "ollama":
                await _test_ollama_connection(provider, normalized_base_url)
                provider.last_test_status = "success"
                provider.last_error = None
                await session.commit()
                return Message(message=T('api.providers.connectivity_verified'))

            client = create_llm_client(cfg)
            client.chat([{"role": "user", "content": "ping"}])
            provider.last_test_status = "success"
            provider.last_error = None
            await session.commit()
            return Message(message=T('api.providers.connectivity_verified'))
        except Exception as exc:  # Surface connectivity/auth errors
            # Ollama JSON format can return empty content with 200; treat as connectivity OK
            if "Ollama returned empty response" in str(exc):
                provider.last_test_status = "success"
                provider.last_error = None
                await session.commit()
                return Message(message=T('api.providers.connectivity_verified'))

            provider.last_test_status = "failed"
            provider.last_error = _redact_secret(str(exc))
            await session.commit()
            raise HTTPException(status_code=502, detail=T("api.errors.provider_test_failed"))


@post("/{provider_id:int}/activate")
async def activate_provider(request: Request, provider_id: int) -> Message:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = await session.get(ProviderConfig, provider_id)
        if provider is None or provider.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=T("api.errors.provider_not_authorized"))

        result = await session.execute(
            select(ProviderConfig).where(ProviderConfig.user_id == current_user.id)
        )
        providers = result.scalars().all()
        for p in providers:
            # Preserve existing config when toggling active status
            cfg = dict(p.config or {})
            if p.id == provider.id:
                cfg["active"] = True
            else:
                cfg["active"] = False
            p.config = cfg
        await session.commit()
        return Message(message=T('api.providers.activated'))


router = Router(
    path="/providers",
    route_handlers=[
        list_providers,
        create_provider,
        update_provider,
        delete_provider,
        test_provider,
        activate_provider,
    ],
)
