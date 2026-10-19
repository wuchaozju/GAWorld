"""Bounded, line-safe reading of authorized research logs."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

MAX_BYTES = 64 * 1024


def redact(text: str, secrets: list[str] | None = None) -> str:
    for secret in sorted(set(secrets or []), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\r\n]+", r"\1[REDACTED]", text)
    text = re.sub(
        r"(?i)((?:x-api-key|api[_-]?key|access[_-]?token|password)\s*['\"]?\s*[:=]\s*)['\"]?[^\s,}\r\n]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    return text


def safe_path(path: Path, root: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    try:
        path.relative_to(root)
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("日志路径不属于当前运行目录") from exc
    cursor = path
    while True:
        if cursor.is_symlink():
            raise ValueError("日志路径不能包含符号链接")
        if cursor == root:
            break
        cursor = cursor.parent
    return path


def read_chunk(
    path: Path,
    root: Path,
    *,
    offset: int = 0,
    file_id: str = "",
    secrets: list[str] | None = None,
    limit: int = MAX_BYTES,
    terminal: bool = False,
) -> dict[str, Any]:
    path = safe_path(path, root)
    if offset < 0:
        raise ValueError("offset 必须是非负整数")
    limit = max(16, min(MAX_BYTES, int(limit)))
    result: dict[str, Any] = {
        "text": "",
        "next_offset": offset,
        "file_id": "",
        "reset": False,
        "has_more": False,
        "missing": False,
    }
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return {**result, "missing": True, "next_offset": 0}
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        identity = hashlib.sha256(f"{path}:{info.st_dev}:{info.st_ino}".encode()).hexdigest()[:24]
        reset = bool((file_id and file_id != identity) or offset > info.st_size)
        if reset:
            offset = 0
        # A cursor within an oversized line discards its continuation. Never
        # emit part of a credential just because it crosses the chunk limit.
        continuation = False
        if offset:
            handle.seek(offset - 1)
            continuation = handle.read(1) != b"\n"
        handle.seek(offset)
        raw = handle.read(limit)
        read_end = offset + len(raw)
        if continuation:
            end = raw.find(b"\n")
            if end < 0:
                return {
                    **result,
                    "next_offset": read_end,
                    "file_id": identity,
                    "reset": reset,
                    "has_more": read_end < info.st_size,
                }
            offset += end + 1
            raw = raw[end + 1 :]
        last = raw.rfind(b"\n")
        if last >= 0:
            ready = raw[: last + 1]
            next_offset = offset + len(ready)
        elif len(raw) == limit:
            ready = b"[oversized log line omitted]\n"
            next_offset = read_end
        elif terminal and read_end == info.st_size:
            ready = raw
            next_offset = read_end
        else:
            ready = b""
            next_offset = offset
        result.update(
            text=redact(ready.decode("utf-8", errors="replace"), secrets),
            next_offset=next_offset,
            file_id=identity,
            reset=reset,
            has_more=next_offset < info.st_size and bool(ready or continuation),
        )
    return result


def configured_secrets(config: dict[str, Any]) -> list[str]:
    secrets: list[str] = []
    for provider in (config.get("llm") or {}).get("providers", {}).values():
        if not isinstance(provider, dict):
            continue
        if provider.get("api_key"):
            secrets.append(str(provider["api_key"]))
        if provider.get("ANTHROPIC_AUTH_TOKEN"):
            secrets.append(str(provider["ANTHROPIC_AUTH_TOKEN"]))
        envs = [provider.get("api_key_env"), *(provider.get("api_key_envs") or [])]
        secrets.extend(os.environ.get(str(name), "") for name in envs if name)
    secrets.extend(os.environ.get(name, "") for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
    return [value for value in secrets if value]
