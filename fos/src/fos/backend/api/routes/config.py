from ...core.config import get_settings
from litestar import Router, get


@get("/")
async def read_config() -> dict:
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "debug": settings.debug,
        "allowed_origins": settings.allowed_origins,
    }


router = Router(path="/config", route_handlers=[read_config])
