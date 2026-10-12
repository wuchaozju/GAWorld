from __future__ import annotations

import asyncio
from pathlib import Path

from litestar import Litestar, Router, get
from litestar.config.cors import CORSConfig
from litestar.connection import Request
from litestar.enums import MediaType
from litestar.exceptions import HTTPException
from sqlalchemy.exc import NoResultFound
from litestar.openapi import OpenAPIConfig
from litestar.response import Response
from litestar.static_files import create_static_files_router

from .api.routes import router as api_router
from .core.config import get_settings
from .core.database import engine
from .db.base import Base
from .middleware import LocaleMiddleware
from .api.routes.health import set_app_start_time
from .static_assets import build_static_file_response, resolve_safe_dist_file

try:
    from .services.polling_service import PollingService
except ModuleNotFoundError:
    PollingService = None


_simtree_cleanup_task: asyncio.Task | None = None


async def _start_polling_service() -> None:
    """Start the PollingService to load enabled data sources and register poll jobs."""
    if PollingService is None:
        return
    polling_service = PollingService.get_instance()
    await polling_service.start()


async def _prepare_database() -> None:
    import fos.backend.models  # noqa: F401
    from .migrations.add_user_config_column import migrate as _migrate_user_config

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _migrate_user_config()


async def _initialize_vector_store() -> None:
    """Initialize the vector store on startup if ChromaDB is enabled."""
    from .core.config import get_settings
    from .services.vector_store import initialize_vector_store

    settings = get_settings()

    # Validate production secrets before starting
    errors = settings.validate_production_secrets()
    if errors:
        print("[FATAL] Production secret validation failed:")
        for err in errors:
            print(f"  - {err}")
        raise SystemExit(1)

    if settings.use_chromadb:
        initialize_vector_store(
            use_chromadb=True, persist_dir=settings.chromadb_persist_dir
        )
        print(f"[vector_store] ChromaDB initialized at {settings.chromadb_persist_dir}")
    else:
        # Initialize with JSON fallback
        initialize_vector_store(use_chromadb=False)
        print("[vector_store] Using JSON fallback mode")


async def _start_simtree_cleanup() -> None:
    """Start the periodic cleanup for idle in-memory simulation trees."""
    global _simtree_cleanup_task
    settings = get_settings()
    interval = int(settings.simtree_cleanup_interval_seconds or 0)
    idle_ttl = int(settings.simtree_idle_ttl_seconds or 0)
    if interval <= 0 or idle_ttl <= 0:
        return
    if _simtree_cleanup_task is not None and not _simtree_cleanup_task.done():
        return

    async def _cleanup_loop() -> None:
        from fos.backend.services.simtree_runtime import SIM_TREE_REGISTRY

        while True:
            await asyncio.sleep(interval)
            evicted = SIM_TREE_REGISTRY.evict_idle_records(
                idle_ttl_seconds=idle_ttl,
                max_records=settings.simtree_max_records,
            )
            if evicted:
                print(f"[simtree_cleanup] evicted idle records: {evicted}")

    _simtree_cleanup_task = asyncio.create_task(_cleanup_loop())


def _stop_simtree_cleanup() -> None:
    """Stop the periodic cleanup task during app shutdown."""
    global _simtree_cleanup_task
    if _simtree_cleanup_task is not None and not _simtree_cleanup_task.done():
        _simtree_cleanup_task.cancel()
    _simtree_cleanup_task = None


def internal_error_handler(request: Request, exc: Exception) -> Response:
    # Let HTTPExceptions (4xx auth errors, etc.) pass through with their own status code.
    if isinstance(exc, HTTPException):
        return Response(
            content={"detail": exc.detail},
            media_type=MediaType.JSON,
            status_code=exc.status_code,
        )
    # SQLAlchemy NoResultFound → 404 (e.g., ownership check fails).
    # Litestar normally handles this, but our Exception handler intercepts first.
    if isinstance(exc, NoResultFound):
        return Response(
            content={"detail": "Not found"},
            media_type=MediaType.JSON,
            status_code=404,
        )
    import logging

    logging.getLogger(__name__).error(f"Unhandled exception: {exc}", exc_info=True)
    return Response(
        content={"error": str(exc)}, media_type=MediaType.JSON, status_code=500
    )


def create_app() -> Litestar:
    settings = get_settings()

    cors_config = None
    if settings.allowed_origins:
        cors_config = CORSConfig(
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    api_prefix = settings.api_prefix or "/api"
    api_routes = Router(path=api_prefix, route_handlers=[api_router])
    api_routes_css = Router(path="/css/fos/api", route_handlers=[api_router])

    # Static uploads
    root_dir = Path(__file__).resolve().parents[3]
    upload_dir = (root_dir / settings.upload_dir).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_router = create_static_files_router(
        path=settings.upload_base_url,
        directories=[str(upload_dir)],
        name="uploads",
    )

    route_handlers = [api_routes, api_routes_css, upload_router]

    # 只在生产模式（有 dist 目录）时服务静态文件
    dist_dir = Path(
        settings.frontend_dist_path or root_dir / "frontend" / "dist"
    ).resolve()
    index_file = dist_dir / "index.html"

    if dist_dir.is_dir() and index_file.is_file():
        immutable_cache_control = "public, max-age=31536000, immutable"
        html_cache_control = "no-cache"
        static_cache_control = "public, max-age=3600"

        async def _serve_dist_file(
            request: Request, relative_path: str, cache_control: str
        ) -> Response[bytes] | None:
            resolved_file = resolve_safe_dist_file(dist_dir, relative_path)
            if resolved_file is None:
                return None
            return await build_static_file_response(
                request, resolved_file, cache_control
            )

        async def _spa_response(request: Request) -> Response[bytes]:
            return await build_static_file_response(
                request, index_file, html_cache_control
            )

        @get("/assets/{file_path:path}")
        async def assets(request: Request, file_path: str) -> Response[bytes]:
            response = await _serve_dist_file(
                request, f"assets/{file_path}", immutable_cache_control
            )
            if response is None:
                return Response(content=b"", status_code=404)
            return response

        @get("/css/fos/assets/{file_path:path}")
        async def assets_css(request: Request, file_path: str) -> Response[bytes]:
            response = await _serve_dist_file(
                request, f"assets/{file_path}", immutable_cache_control
            )
            if response is None:
                return Response(content=b"", status_code=404)
            return response

        @get("/{path:path}")
        async def spa_fallback(request: Request, path: str = "") -> Response[bytes]:
            if path:
                response = await _serve_dist_file(request, path, static_cache_control)
                if response is not None:
                    return response
            return await _spa_response(request)

        @get("/")
        async def home_page(request: Request) -> Response[bytes]:
            return await _spa_response(request)

        @get("/css/fos/{path:path}")
        async def spa_fallback_css(request: Request, path: str = "") -> Response[bytes]:
            if path:
                response = await _serve_dist_file(request, path, static_cache_control)
                if response is not None:
                    return response
            return await _spa_response(request)

        @get("/css/fos")
        async def home_page_css(request: Request) -> Response[bytes]:
            return await _spa_response(request)

        spa_router = Router(path="/", route_handlers=[home_page, spa_fallback, assets])
        spa_router_css = Router(
            path="/",
            route_handlers=[home_page_css, spa_fallback_css, assets_css],
        )
        route_handlers.extend([spa_router, spa_router_css])

    base_router = Router(path=settings.backend_root_path, route_handlers=route_handlers)

    def _log_routes(app: Litestar) -> None:
        for route in sorted(app.routes, key=lambda r: r.path):
            methods = route.methods or ["WS"]
            print(f"[litestar] {sorted(methods)} {route.path}")

    on_startup = [
        set_app_start_time,
        _prepare_database,
        _initialize_vector_store,
        _start_polling_service,
        _start_simtree_cleanup,
        _log_routes,
    ]
    on_shutdown = [_stop_simtree_cleanup]
    if PollingService is not None:
        on_shutdown.append(PollingService.get_instance().shutdown)

    app_kwargs: dict = {
        "route_handlers": [base_router],
        "on_startup": on_startup,
        "on_shutdown": on_shutdown,
        "cors_config": cors_config,
        "debug": settings.debug,
        "openapi_config": OpenAPIConfig(title=settings.app_name, version="1.0.0"),
        "middleware": [LocaleMiddleware],
        "exception_handlers": {Exception: internal_error_handler},
    }

    return Litestar(**app_kwargs)


app = create_app()
