"""
This file serves built frontend files in a browser-friendly way.

- choose_static_variant picks the best file version for the browser, including precompressed copies.
- resolve_safe_dist_file makes sure a requested file stays inside the built frontend folder.
- build_static_file_response reads the chosen file and returns the right headers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import mimetypes
from pathlib import Path

from litestar.connection import Request
from litestar.response import Response


@dataclass(frozen=True)
class StaticVariant:
    path: Path
    content_encoding: str | None


def choose_static_variant(file_path: Path, accept_encoding: str) -> StaticVariant:
    accepted = accept_encoding.lower()
    if "br" in accepted:
        brotli_path = Path(f"{file_path}.br")
        if brotli_path.is_file():
            return StaticVariant(path=brotli_path, content_encoding="br")
    if "gzip" in accepted or "gz" in accepted:
        gzip_path = Path(f"{file_path}.gz")
        if gzip_path.is_file():
            return StaticVariant(path=gzip_path, content_encoding="gzip")
    return StaticVariant(path=file_path, content_encoding=None)


def resolve_safe_dist_file(dist_dir: Path, relative_path: str) -> Path | None:
    requested_path = relative_path.lstrip("/").strip()
    if not requested_path:
        return None
    resolved_path = (dist_dir / requested_path).resolve()
    if dist_dir not in resolved_path.parents:
        return None
    if not resolved_path.is_file():
        return None
    return resolved_path


async def build_static_file_response(
    request: Request,
    file_path: Path,
    cache_control: str,
) -> Response[bytes]:
    accept_encoding = request.headers.get("accept-encoding", "")
    variant = choose_static_variant(file_path, accept_encoding)
    media_type, _ = mimetypes.guess_type(file_path.name)
    headers = {
        "Cache-Control": cache_control,
        "Vary": "Accept-Encoding",
    }
    if variant.content_encoding is not None:
        headers["Content-Encoding"] = variant.content_encoding
    content = await asyncio.to_thread(variant.path.read_bytes)
    return Response(
        content=content,
        media_type=media_type or "application/octet-stream",
        headers=headers,
    )
