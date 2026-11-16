"""Personal tokens may vary simulation parameters, not server paths or executable plugins."""

from .context import USER
from .policy import config_update_refusal


def validate_parallel(path, payload):
    if not (USER.get() or {}).get("api_token_id"):
        return

    def check_patch(patch, prefix=""):
        if not isinstance(patch, dict):
            raise ValueError("World config must be an object")
        for key, value in patch.items():
            dotted = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and value:
                check_patch(value, dotted)
            else:
                refusal = config_update_refusal(dotted, value)
                if refusal:
                    raise ValueError(refusal)

    if path.endswith(("/preview", "/start")):
        worlds = payload.get("worlds")
        if not isinstance(worlds, list):
            raise ValueError("worlds must be a list")
        for world in worlds:
            if not isinstance(world, dict):
                raise ValueError("Each world must be an object")
            if world.get("seed_from_checkpoint"):
                raise ValueError("Personal API tokens cannot import server checkpoints")
            check_patch(world.get("config") or {})
    if path.endswith("/sweep"):
        refusal = config_update_refusal(payload.get("path"), 0)
        if refusal:
            raise ValueError(refusal)
