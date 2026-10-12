from litestar import Router, delete, get, patch, post
from litestar.connection import Request
from litestar.exceptions import HTTPException
from sqlalchemy import select

from ...core.database import get_session
from ...dependencies import extract_bearer_token, resolve_current_user
from fos.i18n import T
from ...models.user import SearchProviderConfig
from ...schemas.search_provider import SearchProviderBase, SearchProviderCreate, SearchProviderUpdate


def _serialize(provider: SearchProviderConfig) -> SearchProviderBase:
    return SearchProviderBase(
        id=provider.id,
        provider=provider.provider,
        base_url=provider.base_url,
        has_api_key=bool(provider.api_key),
        config=provider.config,
    )


@get("/")
async def list_search_providers(request: Request) -> list[SearchProviderBase]:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        result = await session.execute(select(SearchProviderConfig).where(SearchProviderConfig.user_id == current_user.id))
        providers = result.scalars().all()
        return [_serialize(p) for p in providers]


@post("/", status_code=201)
async def create_search_provider(request: Request, data: SearchProviderCreate) -> SearchProviderBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = SearchProviderConfig(
            user_id=current_user.id,
            provider=data.provider,
            base_url=data.base_url,
            api_key=data.api_key,
            config=data.config or {},
        )
        session.add(provider)
        await session.commit()
        await session.refresh(provider)
        return _serialize(provider)


@patch("/{provider_id:int}")
async def update_search_provider(request: Request, provider_id: int, data: SearchProviderUpdate) -> SearchProviderBase:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = await session.get(SearchProviderConfig, provider_id)
        if provider is None or provider.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=T("api.errors.provider_not_authorized"))

        if data.provider is not None:
            provider.provider = data.provider
        if data.base_url is not None:
            provider.base_url = data.base_url
        if data.api_key is not None:
            provider.api_key = data.api_key
        if data.config is not None:
            provider.config = data.config

        await session.commit()
        await session.refresh(provider)
        return _serialize(provider)


@delete("/{provider_id:int}", status_code=204)
async def delete_search_provider(request: Request, provider_id: int) -> None:
    token = extract_bearer_token(request)
    async with get_session() as session:
        current_user = await resolve_current_user(session, token)
        provider = await session.get(SearchProviderConfig, provider_id)
        if provider is None or provider.user_id != current_user.id:
            raise HTTPException(status_code=403, detail=T("api.errors.provider_not_authorized"))
        await session.delete(provider)
        await session.commit()


router = Router(
    path="/search-providers",
    route_handlers=[
        list_search_providers,
        create_search_provider,
        update_search_provider,
        delete_search_provider,
    ],
)
