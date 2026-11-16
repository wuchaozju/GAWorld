import os
from pathlib import Path


def get_runtime_debug_dir(*parts: str) -> Path:
    configured = os.getenv("FOS_DEBUG_LOG_DIR")
    if configured:
        root = Path(configured)
    elif Path("/app/test_results").exists():
        root = Path("/app/test_results")
    elif Path("test_results").exists():
        root = Path("test_results")
    else:
        root = Path("/tmp/fos_debug")
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
