"""Opt-in, user- and endpoint-bound credentials outside the checkout.

Authenticated users write only their own entries. Workers read on demand, so a
rotation reaches existing provider objects without copying secrets into CONFIG
or process environments. This is a private local file, not encryption at rest.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from gaworld.accounts.context import USER

ENV_PATH = "GAWORLD_LLM_SECRETS_PATH"


def enabled() -> bool:
    return bool(os.environ.get(ENV_PATH))


def user_id() -> int | None:
    user = USER.get()
    value = user.get("id") if user is not None else os.environ.get("GAWORLD_USER_ID")
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _entry(cfg: dict) -> str:
    owner = user_id()
    if owner is None:
        raise PermissionError("Sign in with a personal account to configure an API Key.")
    return f"{owner}:{_binding(cfg)}"


def _path() -> Path:
    raw = os.environ.get(ENV_PATH, "")
    path = Path(raw).expanduser()
    if not raw or not path.is_absolute():
        raise ValueError("Configure an absolute GAWORLD_LLM_SECRETS_PATH outside the repository.")
    resolved = path.resolve()
    repo = Path(__file__).resolve().parents[2]
    if resolved.is_relative_to(repo) or any((p / ".git").exists() for p in resolved.parents):
        raise ValueError("The credential store must be outside every Git checkout.")
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("The credential store must not use symbolic links.")
    return path


def _binding(cfg: dict) -> str:
    kind = str(cfg.get("type") or "").lower()
    if kind == "claude":
        kind = "anthropic"
    defaults = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com"}
    if kind not in defaults:
        raise ValueError("Only OpenAI-compatible and Anthropic-compatible providers accept credentials.")
    endpoint = str(cfg.get("base_url", defaults[kind])).rstrip("/")
    url = urlsplit(endpoint)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError(
            "Managed credentials require an HTTPS endpoint without credentials, query or fragment."
        )
    # The full path matters: two tenants behind the same host must not share keys.
    return hashlib.sha256(json.dumps([kind, endpoint]).encode()).hexdigest()


def _private(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Credential storage requires an owner-only directory (0700) and files (0600).")


def supported(cfg: dict) -> bool:
    try:
        _binding(cfg)
        return True
    except ValueError:
        return False


def _read(path: Path) -> dict[str, str]:
    if path.parent.exists():
        _private(path.parent, directory=True)
    if not path.exists():
        return {}
    _private(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid credential store; ask the administrator to repair it.") from None
    if not isinstance(data, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError("Invalid credential store; ask the administrator to repair it.")
    return data


def lookup(cfg: dict) -> str | None:
    if not enabled() or user_id() is None:
        return None
    try:
        binding = _entry(cfg)
    except ValueError:
        return None  # local HTTP providers cannot receive managed credentials
    return _read(_path()).get(binding)


def save(cfg: dict, key: str | None) -> None:
    """Save/replace a key, or delete only the managed key when key is None."""
    import fcntl

    binding = _entry(cfg)
    if key is not None and (
        not isinstance(key, str)
        or not 1 <= len(key) <= 4096
        or any(ord(ch) < 33 or ord(ch) > 126 for ch in key)
    ):
        raise ValueError("API Key must contain 1-4096 printable ASCII characters without whitespace.")
    path = _path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private(path.parent, directory=True)
    lock_path = path.with_name(path.name + ".lock")
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "a") as lock:
        _private(lock_path)
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read(path)
        if key is None:
            data.pop(binding, None)
        else:
            data[binding] = key
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, delete=False, encoding="utf-8"
            ) as out:
                temporary = out.name
                json.dump(data, out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def key_ready(cfg: dict) -> bool:
    if enabled():
        return bool(lookup(cfg))
    if cfg.get("api_key") or cfg.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    kind = cfg.get("type")
    default = "OPENAI_API_KEY" if kind == "openai" else "ANTHROPIC_API_KEY"
    names = [cfg.get("api_key_env", default), *(cfg.get("api_key_envs") or [])]
    return any(os.environ.get(name) for name in names if isinstance(name, str))


def validate_launch(config: dict) -> None:
    """Fail before reset/feeds when a selected route has no credential-ready backend.

    Personal-key mode requires the selected paid provider's own key; it must
    not silently replace the chosen experimental model with a free fallback.
    Legacy CLI routing retains its fallback behavior. No network calls here.
    """
    llm = config.get("llm") or {}
    providers = llm.get("providers") or {}
    if not providers:
        return
    routing = llm.get("routing") or {}
    selected = {routing.get("default") or next(iter(providers))}
    selected.update((routing.get("tasks") or {}).values())
    agents = routing.get("agents") or {}
    ids = config.get("agent_ids") or []
    selected.update(agents[str(i)] for i in ids if str(i) in agents)
    fallback = routing.get("fallback") or []
    if isinstance(fallback, str):
        fallback = [fallback]

    def ready(name):
        cfg = providers.get(name) or {}
        return cfg.get("type") == "ollama" or (
            cfg.get("type") in ("openai", "anthropic", "claude") and key_ready(cfg)
        )

    for name in sorted(selected):
        if name not in providers:
            raise ValueError(f"Provider '{name}' not found in config.")
        candidates = [name] if enabled() else [name, *fallback]
        if not any(ready(n) for n in candidates):
            raise ValueError(
                f"Model '{name}' has no personal API Key. "
                "Open Settings > Models to save your API Key and test the connection."
            )
