"""
Helper functions for simulation route handlers.

This module contains shared utility functions used across multiple
simulation route modules. Includes database access, authentication,
tree record management, and event broadcasting.

Contains:
    - get_simulation_for_owner: Fetch simulation with ownership check
    - get_tree_record: Get or create SimTreeRecord for a simulation
    - get_simulation_and_tree: Get both simulation and tree record
    - get_simulation_and_tree_for_owner: Get simulation/tree with ownership check
    - get_simulation_and_tree_any: Get simulation/tree without owner check (INTERNAL ONLY)
    - resolve_user_from_token: Resolve user from JWT token
    - broadcast_tree_event: Broadcast event to all tree subscribers
"""

import logging

from jose import JWTError, jwt
from litestar.exceptions import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fos.core.llm_config import LLMConfig, guess_supports_vision
from fos.core.search_config import SearchConfig
from fos.core.llm import create_llm_client
from fos.core.tools.web.search import create_search_client
from fos.backend.dependencies import settings

from fos.backend.models.simulation import Simulation
from fos.backend.models.user import ProviderConfig, SearchProviderConfig, User
from fos.backend.services.default_providers import get_default_ollama_base_url
from fos.backend.services.provider_dialect import normalize_provider_runtime
from fos.backend.services.simtree_broadcast import broadcast_tree_event  # noqa: F401
from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY, SimTreeRecord
from fos.i18n import T


logger = logging.getLogger(__name__)


async def get_simulation_for_owner(
    session: AsyncSession,
    owner_id: int,
    simulation_id: str,
) -> Simulation:
    """
    Fetch a simulation by ID and owner.

    Args:
        session: Database session
        owner_id: User ID who owns the simulation
        simulation_id: Simulation identifier

    Returns:
        The Simulation object

    Raises:
        sqlalchemy.exc.NoResultFound: If simulation not found
    """
    result = await session.execute(
        select(Simulation).where(
            Simulation.owner_id == owner_id,
            Simulation.id == simulation_id.upper()
        )
    )
    return result.scalar_one()


async def get_tree_record(
    sim: Simulation,
    session: AsyncSession,
    user_id: int,
) -> SimTreeRecord:
    """
    Get or create a SimTreeRecord for a simulation.

    Loads the user's LLM and Search provider configurations,
    creates the appropriate clients, and gets or creates a
    SimTreeRecord from the registry.

    Args:
        sim: The simulation object
        session: Database session
        user_id: User ID for loading provider configs

    Returns:
        SimTreeRecord with tree and client instances

    Raises:
        HTTPException: If provider configuration is invalid or missing
    """
    # Load LLM Provider configuration
    # Find active provider, or fall back to first provider (consistent with create_simulation)
    result = await session.execute(
        select(ProviderConfig).where(ProviderConfig.user_id == user_id)
    )
    items = result.scalars().all()
    active = [p for p in items if (p.config or {}).get("active")]

    if len(active) == 1:
        provider = active[0]
    elif len(items) >= 1:
        # Fall back to first provider if no active flag is set
        provider = items[0]
    else:
        raise HTTPException(
            status_code=400,
            detail=T("api.errors.provider_not_configured")
        )
    dialect, normalized_base_url = normalize_provider_runtime(provider.provider, provider.base_url)
    base_url = normalized_base_url or (get_default_ollama_base_url() if dialect == "ollama" else None)

    if dialect not in {"openai", "gemini", "mock", "ollama"}:
        raise HTTPException(status_code=400, detail=T("api.errors.provider_invalid"))

    # Skip API key check for local OpenAI-compatible providers (LM Studio, llama.cpp, etc.)
    if dialect in {"openai", "gemini"} and not provider.api_key:
        if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
            pass  # Local server, no API key needed
        else:
            raise HTTPException(status_code=400, detail=T("api.errors.provider_api_key_required"))

    if not provider.model:
        raise HTTPException(status_code=400, detail=T("api.errors.provider_model_required"))

    # Create LLM client
    cfg = LLMConfig(
        dialect=dialect,
        api_key=provider.api_key or "",
        model=provider.model,
        base_url=base_url,
        temperature=0.7,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        max_tokens=1024,
        supports_vision=guess_supports_vision(provider.model),
    )
    llm_client = create_llm_client(cfg)

    # Load Search Provider configuration
    result_s = await session.execute(
        select(SearchProviderConfig).where(SearchProviderConfig.user_id == user_id)
    )
    sprov = result_s.scalars().first()

    if sprov is None:
        s_cfg = SearchConfig(dialect="ddg", api_key="", base_url=None, params={})
    else:
        s_cfg = SearchConfig(
            dialect=(sprov.provider or "ddg"),
            api_key=sprov.api_key or "",
            base_url=sprov.base_url,
            params=sprov.config or {},
        )

    search_client = create_search_client(s_cfg)

    # Build per-provider client map for LLM distribution across agents
    provider_clients: dict[int, object] = {}
    for p in items:
        p_dialect, p_normalized_base_url = normalize_provider_runtime(p.provider, p.base_url)
        if p_dialect not in {"openai", "gemini", "mock", "ollama"}:
            continue
        # Skip API key check for local OpenAI-compatible providers
        if p_dialect in {"openai", "gemini"} and not p.api_key:
            if p.base_url and ("localhost" in p.base_url or "127.0.0.1" in p.base_url):
                pass  # Local server, no API key needed
            else:
                continue
        if not p.model:
            continue
        try:
            p_base_url = p_normalized_base_url or (get_default_ollama_base_url() if p_dialect == "ollama" else None)
            p_cfg = LLMConfig(
                dialect=p_dialect,
                api_key=p.api_key or "",
                model=p.model,
                base_url=p_base_url,
                temperature=0.7,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=1024,
                supports_vision=guess_supports_vision(p.model),
            )
            provider_clients[p.id] = create_llm_client(p_cfg)
        except Exception:
            logger.warning(f"Failed to create LLM client for provider {p.id}")

    clients = {"chat": llm_client, "default": llm_client, "search": search_client, "providers": provider_clients}

    return await SIM_TREE_REGISTRY.get_or_create_from_sim(sim, clients)


async def get_simulation_and_tree(
    session: AsyncSession,
    owner_id: int,
    simulation_id: str,
) -> tuple[Simulation, SimTreeRecord]:
    """
    Get both simulation and tree record for an owner.

    Convenience function that combines get_simulation_for_owner
    and get_tree_record.

    Args:
        session: Database session
        owner_id: User ID who owns the simulation
        simulation_id: Simulation identifier

    Returns:
        Tuple of (Simulation, SimTreeRecord)
    """
    sim = await get_simulation_for_owner(session, owner_id, simulation_id)
    record = await get_tree_record(sim, session, owner_id)
    return sim, record


async def get_simulation_and_tree_for_owner(
    session: AsyncSession,
    owner_id: int,
    simulation_id: str,
) -> tuple[Simulation, SimTreeRecord]:
    """
    Get simulation and tree with ownership check.

    Fetches the simulation by ID and verifies the requesting user
    is the owner. Use this in all request handlers that access
    simulation trees.

    Args:
        session: Database session
        owner_id: User ID who must own the simulation
        simulation_id: Simulation identifier

    Returns:
        Tuple of (Simulation, SimTreeRecord)

    Raises:
        HTTPException: 404 if simulation not found or not owned by user
    """
    sim = await get_simulation_for_owner(session, owner_id, simulation_id)
    record = await get_tree_record(sim, session, owner_id)
    return sim, record


async def get_simulation_and_tree_any(
    session: AsyncSession,
    simulation_id: str,
) -> tuple[Simulation, SimTreeRecord]:
    """
    Get simulation and tree WITHOUT ownership check.

    WARNING: Does not enforce ownership. Do NOT use in request handlers
    that serve external API requests. Use get_simulation_and_tree_for_owner()
    instead. This function exists only for internal/trusted paths where
    ownership has already been verified.

    Args:
        session: Database session
        simulation_id: Simulation identifier

    Returns:
        Tuple of (Simulation, SimTreeRecord)

    Raises:
        HTTPException: If simulation not found
    """
    sim = await session.get(Simulation, simulation_id.upper())
    if sim is None:
        raise HTTPException(status_code=404, detail=T("api.errors.simulation_not_found"))
    record = await get_tree_record(sim, session, sim.owner_id)
    return sim, record


async def resolve_user_from_token(
    token: str,
    session: AsyncSession,
) -> User | None:
    """
    Resolve a user from a JWT bearer token.

    Args:
        token: JWT token string
        session: Database session

    Returns:
        User object if valid token, None otherwise
    """
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.jwt_signing_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None

    subject = payload.get("sub")
    if subject is None:
        return None

    user = await session.get(User, int(subject))
    if user is None or not user.is_active:
        return None

    return user
