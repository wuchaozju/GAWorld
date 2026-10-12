# src/fos/backend/api/routes/llm.py
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from litestar import Router, post
from litestar.connection import Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_session
from ...dependencies import extract_bearer_token, resolve_current_user
from ...models.user import ProviderConfig
from ...services.default_providers import get_default_ollama_base_url
from ...services.provider_dialect import normalize_provider_runtime
from ...services.runtime_tasks import RUNTIME_TASKS
from ....i18n import T, get_request_locale

# 👇 关键：这里需要上升 3 层到 fos，然后再进入 core
from ....core.llm import create_llm_client, generate_agents_with_archetypes
from ....core.llm_config import LLMConfig, guess_supports_vision

# Import stratified distribution for balanced provider assignment across demographics
from ...services.stratified_distribution import stratified_provider_assignment

logger = logging.getLogger(__name__)


class GenerateAgentsRequest(BaseModel):
    count: int = Field(5, ge=1, le=50)
    description: str
    # 前端 generateAgentsWithAI 里传的 provider_id
    provider_id: Optional[int] = None
    language: str = "en"  # Default to English


class DemographicDimension(BaseModel):
    """A demographic dimension with categories (e.g., Age: [18-30, 31-50, 51+])."""
    name: str
    categories: List[str]


class TraitConfig(BaseModel):
    """Configuration for a trait with mean/std bounds."""
    name: str
    mean: int = 50
    std: int = 15


class GenerateAgentsDemographicsRequest(BaseModel):
    """Request model for demographic-based agent generation using AgentTorch."""
    total_agents: int = Field(10, ge=1, le=200)
    demographics: List[DemographicDimension]
    archetype_probabilities: Dict[str, float] = {}
    traits: List[TraitConfig] = []
    language: str = "en"  # Default to English; frontend sends explicit value
    provider_id: Optional[int] = None


class GeneratedAgent(BaseModel):
    id: Optional[str] = None
    name: str
    role: Optional[str] = None
    profile: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    provider_id: Optional[int] = None  # For stratified provider distribution
    properties: dict[str, Any] = {}
    history: dict[str, Any] = {}
    memory: list[Any] = []
    knowledgeBase: list[Any] = []


class RefineReportRequest(BaseModel):
    prompt: str
    provider_id: Optional[int] = None


async def _select_provider(
    session: AsyncSession,
    user_id: int,
    provider_id: Optional[int],
) -> ProviderConfig:
    # 优先用前端传入的 provider_id
    if provider_id is not None:
        result = await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.user_id == user_id,
                ProviderConfig.id == provider_id,
            )
        )
        provider = result.scalars().first()
        if provider is None:
            raise RuntimeError(T("api.errors.llm.provider_not_found"))
    else:
        # 否则找 config.active 的那个；都没标 active 就随便挑一个
        result = await session.execute(
            select(ProviderConfig).where(ProviderConfig.user_id == user_id)
        )
        items = result.scalars().all()
        active = [p for p in items if (p.config or {}).get("active")]
        provider = active[0] if len(active) == 1 else (items[0] if items else None)

    if provider is None:
            raise RuntimeError(T("api.errors.provider_not_configured"))

    dialect, _base_url = normalize_provider_runtime(provider.provider, provider.base_url)
    if dialect not in {"openai", "gemini", "mock", "ollama"}:
        raise RuntimeError(T("api.errors.provider_invalid"))
    if dialect in {"openai", "gemini"} and not provider.api_key:
        raise RuntimeError(T("api.errors.provider_api_key_required"))
    if not provider.model:
        raise RuntimeError(T("api.errors.provider_model_required"))

    return provider
@post("/generate_agents")
async def generate_agents(
    request: Request,
    data: GenerateAgentsRequest,
) -> List[GeneratedAgent]:
    """
    POST /llm/generate_agents

    前端的 generateAgentsWithAI() 就是调的这个接口。
    """
    token = extract_bearer_token(request)

    async with get_session() as session:
        current_user = await resolve_current_user(session, token)

        provider = await _select_provider(
            session, current_user.id, data.provider_id
        )
        dialect, base_url = normalize_provider_runtime(provider.provider, provider.base_url)

        cfg = LLMConfig(
            dialect=dialect,
            api_key=provider.api_key or "",
            model=provider.model,
            base_url=base_url or (get_default_ollama_base_url() if dialect == "ollama" else None),
            temperature=0.7,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_tokens=1024,
            supports_vision=guess_supports_vision(provider.model),
        )
        llm = create_llm_client(cfg)

        # Language-aware prompts via i18n
        locale = data.language or get_request_locale()

        system_prompt = T("prompts.llm.generate_agents.system", locale=locale)
        user_prompt = T("prompts.llm.generate_agents.user", locale=locale,
                        count=data.count, description=data.description)
        fallback_role = T("prompts.llm.generate_agents.fallback_role", locale=locale)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw_text = llm.chat(messages)
   # 打印原始输出用于调试
        logger.debug(f"LLM raw output (first 500 chars): {raw_text[:500]}")
        
        # 清理 LLM 输出：去除 markdown 代码块标记
        cleaned_text = raw_text.strip()

        # 移除markdown代码块标记
        if cleaned_text.startswith("```"):
            # 匹配 ```json 或 ``` 开头的代码块
            match = re.search(r'```(?:json)?\s*\n(.*?)\n```', cleaned_text, re.DOTALL)
            if match:
                cleaned_text = match.group(1).strip()
            else:
                # 简单移除```标记
                cleaned_text = re.sub(r'^```(?:json)?|```$', '', cleaned_text, flags=re.MULTILINE).strip()
        
        # 尝试找到第一个[或{
        json_start = min(
            (cleaned_text.find('[') if '[' in cleaned_text else len(cleaned_text)),
            (cleaned_text.find('{') if '{' in cleaned_text else len(cleaned_text))
        )
        if json_start < len(cleaned_text):
            cleaned_text = cleaned_text[json_start:]

        try:
            parsed = json.loads(cleaned_text)
        except Exception as e:
            logger.error(f"JSON parse failed: {e}")
            logger.error(f"Cleaned text (first 300 chars): {cleaned_text[:300]}")
            # LLM 没按要求返回 JSON 时的兜底，前端依然能跑
            agent_name_template = T("prompts.llm.generate_agents.agent_name", locale=locale)
            parsed = [
                {
                    "name": agent_name_template.format(index=i + 1),
                    "role": fallback_role,
                    "profile": T("prompts.llm.generate_agents.agent_name_raw", locale=locale,
                                 raw_text=raw_text[:100]),
                    "properties": {},
                }
                for i in range(data.count)
            ]

        # 处理不同的返回格式
        if isinstance(parsed, dict) and "agents" in parsed:
            items = parsed["agents"]
        elif isinstance(parsed, list):
            items = parsed
        else:
            # 如果解析出来不是列表也不是包含 agents 的字典，创建占位角色
            items = []

        if not isinstance(items, list):
            items = []

        agents: List[GeneratedAgent] = []
        for i, a in enumerate(items):
            if not isinstance(a, dict):
                continue
            agents.append(
                GeneratedAgent(
                    id=a.get("id") or None,
                    name=a.get("name") or T("prompts.llm.generate_agents.agent_name", locale=locale).format(index=i+1),
                    role=a.get("role"),
                    profile=a.get("profile"),
                    provider=provider.provider or "backend",
                    model=provider.model or "default",
                    properties=a.get("properties") or {},
                    history=a.get("history") or {},
                    memory=a.get("memory") or [],
                    knowledgeBase=a.get("knowledgeBase") or [],
                )
            )

        # 如果模型返回的不足 count 个，简单补齐
        while len(agents) < data.count:
            idx = len(agents)
            agents.append(
                GeneratedAgent(
                    name=T("prompts.llm.generate_agents.agent_name", locale=locale).format(index=idx + 1),
                    role=fallback_role,
                    profile=data.description,
                    provider=provider.provider or "backend",
                    model=provider.model or "default",
                )
            )

        return agents


@post("/refine_report")
async def refine_report(request: Request, data: RefineReportRequest) -> dict:
    token = extract_bearer_token(request)
    runtime_task = RUNTIME_TASKS.start(
        "ai_report_refine",
        "AI report refinement",
        metadata={"provider_id": data.provider_id},
    )

    try:
        async with get_session() as session:
            current_user = await resolve_current_user(session, token)
            provider = await _select_provider(session, current_user.id, data.provider_id)
            cfg = LLMConfig(
                dialect=normalize_provider_runtime(provider.provider, provider.base_url)[0],
                api_key=provider.api_key or "",
                model=provider.model,
                base_url=normalize_provider_runtime(provider.provider, provider.base_url)[1],
                temperature=0.4,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=512,
            )
            llm = create_llm_client(cfg)

            locale = get_request_locale()
            messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": T("prompts.llm.refine_report.system", locale=locale),
                },
                {"role": "user", "content": data.prompt},
            ]
            text = llm.chat(messages)
            RUNTIME_TASKS.finish(
                runtime_task.id,
                metadata={
                    "provider_id": provider.id,
                    "provider": provider.provider,
                    "model": provider.model,
                },
            )
            return {"text": text}
    except Exception as exc:
        RUNTIME_TASKS.fail(runtime_task.id, exc)
        raise


@post("/generate_agents_demographics")
async def generate_agents_demographics(
    request: Request,
    data: GenerateAgentsDemographicsRequest,
) -> List[GeneratedAgent]:
    """
    POST /llm/generate_agents_demographics

    Demographic-based agent generation using AgentTorch framework.
    Frontend's generateAgentsWithDemographics() calls this endpoint.

    Process:
    1. Generate archetypes from demographic cross-product
    2. For each archetype, ONE LLM call to get description, roles, and trait distributions
    3. Generate agents with Gaussian-sampled traits
    4. Return agents with demographic properties
    """
    token = extract_bearer_token(request)

    try:
        async with get_session() as session:
            current_user = await resolve_current_user(session, token)

            provider = None
            llm = None
            try:
                provider = await _select_provider(
                    session, current_user.id, data.provider_id
                )
                dialect, base_url = normalize_provider_runtime(provider.provider, provider.base_url)
                cfg = LLMConfig(
                    dialect=dialect,
                    api_key=provider.api_key or "",
                    model=provider.model,
                    base_url=base_url or (get_default_ollama_base_url() if dialect == "ollama" else None),
                    temperature=0.7,
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                    max_tokens=1024,
                    supports_vision=guess_supports_vision(provider.model),
                )
                llm = create_llm_client(cfg)
                llm.timeout_s = min(float(getattr(llm, "timeout_s", 30.0) or 30.0), 30.0)
                llm.max_retries = 0
            except RuntimeError as provider_error:
                logger.warning(
                    "Demographic agent generation falling back to local templates: %s",
                    provider_error,
                )

            locale = data.language or get_request_locale()

            # Traits are required
            if not data.traits:
                raise ValueError(T("prompts.llm.errors.traits_required", locale=locale))

            # Demographics are required
            if not data.demographics:
                raise ValueError(T("prompts.llm.errors.demographics_required", locale=locale))

            # Validate each demographic has categories
            for demo in data.demographics:
                if not demo.categories or len(demo.categories) == 0:
                    raise ValueError(T("prompts.llm.errors.demographic_needs_categories",
                                       locale=locale, name=demo.name))

            # Validate trait ranges before passing to generation
            for trait in data.traits:
                mean_val = trait.mean if trait.mean is not None else 0
                std_val = trait.std if trait.std is not None else 0

                if not (0 <= mean_val <= 100):
                    raise ValueError(T("prompts.llm.errors.trait_mean_out_of_range",
                                       locale=locale, name=trait.name, value=mean_val))

                if not (0 <= std_val <= 50):
                    raise ValueError(T("prompts.llm.errors.trait_std_out_of_range",
                                       locale=locale, name=trait.name, value=std_val))

            # Check probability sum and warn if not normalized
            if data.archetype_probabilities:
                prob_sum = sum(data.archetype_probabilities.values())
                tolerance = 0.01
                if abs(prob_sum - 1.0) > tolerance:
                    logger.warning(
                        f"Archetype probabilities sum to {prob_sum:.3f}, not 1.0. "
                        f"Probabilities will be automatically normalized."
                    )

            # Convert Pydantic models to dicts for llm.py function
            demographics_dicts = [
                {"name": d.name, "categories": d.categories}
                for d in data.demographics
            ]

            traits_dicts = [
                {"name": t.name, "mean": t.mean, "std": t.std}
                for t in data.traits
            ]

            # 🎯 Call the integrated AgentTorch function from llm.py
            # Note: provider_id is NOT passed here to avoid confounding
            # Providers are distributed AFTER generation using stratified distribution
            try:
                agents_data = generate_agents_with_archetypes(
                    total_agents=data.total_agents,
                    demographics=demographics_dicts,
                    archetype_probabilities=data.archetype_probabilities,
                    traits=traits_dicts,
                    llm_client=llm,
                    language=data.language,
                    timeout=30,
                )
            except ValueError as ve:
                # Re-raise ValueError with more context
                raise ValueError(T("api.errors.llm.agent_generation_validation_failed", error=str(ve)))
            except RuntimeError as re:
                # LLM or JSON parsing error
                raise RuntimeError(T("api.errors.llm.llm_agent_generation_failed", error=str(re)))
            except Exception as e:
                # Unexpected error during generation
                raise RuntimeError(T("api.errors.llm.unexpected_agent_generation_error", error=str(e)))

            provider_assignment = {}
            assigned_provider = provider

            if provider is not None and data.provider_id is not None and provider.id is not None:
                provider_assignment = {
                    agent.get("name", "Agent"): provider.id
                    for agent in agents_data
                }
                provider_map = {provider.id: provider}
                logger.info(f"🎯 SINGLE PROVIDER DISTRIBUTION: {len(agents_data)} agents -> provider {provider.id}")
            elif provider is not None:
                all_providers_result = await session.execute(
                    select(ProviderConfig).where(ProviderConfig.user_id == current_user.id)
                )
                all_providers = all_providers_result.scalars().all()
                active_providers = [p for p in all_providers if bool((p.config or {}).get("active"))]
                selected_providers = active_providers or [provider]
                provider_ids = [p.id for p in selected_providers if p.id is not None]
                provider_map = {p.id: p for p in selected_providers if p.id is not None}

                if provider_ids:
                    assignment = stratified_provider_assignment(
                        agents_data,
                        provider_ids,
                        ["Age", "Income"],
                    )
                    provider_assignment = dict(assignment)
                    logger.info(f"🎯 ACTIVE PROVIDER DISTRIBUTION: {len(agents_data)} agents, providers={provider_ids}")
            else:
                provider_map = {}

            # Convert to GeneratedAgent response models with stratified provider assignment
            agents: List[GeneratedAgent] = []
            for agent_dict in agents_data:
                agent_name = agent_dict.get("name", "Agent")
                assigned_provider_id = provider_assignment.get(agent_name)

                # Get provider info from the assigned provider
                # Handle case where assigned_provider_id might be None
                if assigned_provider_id is not None and assigned_provider_id in provider_map:
                    assigned_provider = provider_map[assigned_provider_id]
                else:
                    assigned_provider = provider

                agents.append(
                    GeneratedAgent(
                        id=agent_dict.get("id"),
                        name=agent_name,
                        role=agent_dict.get("role"),
                        profile=agent_dict.get("profile", ""),
                        provider=(assigned_provider.provider or "backend") if assigned_provider else "backend",
                        model=(assigned_provider.model or "default") if assigned_provider else "default",
                        provider_id=assigned_provider_id,
                        properties=agent_dict.get("properties", {}),
                        history=agent_dict.get("history", {}),
                        memory=agent_dict.get("memory", []),
                        knowledgeBase=agent_dict.get("knowledgeBase", []),
                    )
                )

            logger.info(f"Generated {len(agents)} agents using demographic modeling")
            return agents
    except ValueError as e:
        # Validation errors - return 400 with clear message
        logger.warning(f"Validation error in generate_agents_demographics: {e}")
        raise
    except RuntimeError as e:
        # LLM errors - return 500 with error message
        logger.error(f"LLM error in generate_agents_demographics: {e}")
        raise
    except Exception as e:
        # Unexpected errors
        logger.error(f"Unexpected error in generate_agents_demographics: {e}", exc_info=True)
        raise RuntimeError(T("api.errors.llm.failed_to_generate_agents", error=str(e)))


# 暴露 /llm 前缀的 Router
router = Router(
    path="/llm",
    route_handlers=[generate_agents, refine_report, generate_agents_demographics],
)
