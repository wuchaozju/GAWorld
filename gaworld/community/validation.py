"""Small bounded inputs and stable content digests shared by publishing adapters."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from typing import Any

LICENSES = ("read_only", "CC-BY-4.0", "CC0-1.0")
KINDS = ("plan", "study", "simulation")
STATUSES = ("plan", "completed", "partial", "failed")


def identifier() -> str:
    return secrets.token_hex(12)


def text(data: dict, key: str, limit: int, *, required: bool = False) -> str:
    value = str(data.get(key) or "").strip()
    if len(value) > limit or (required and not value):
        raise ValueError(f"{key} 不能为空且最多 {limit} 字符" if required else f"{key} 最多 {limit} 字符")
    return value


def digest(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def content(data: dict) -> dict:
    result = {
        key: text(data, key, limit, required=key in {"title", "body"})
        for key, limit in (
            ("title", 160),
            ("summary", 1000),
            ("body", 100000),
            ("methods", 20000),
            ("limitations", 10000),
            ("references", 10000),
        )
    }
    result.update(
        kind=data.get("kind", "plan"),
        license=data.get("license", "read_only"),
        result_status=data.get("result_status", "plan"),
    )
    if (
        result["kind"] not in KINDS
        or result["license"] not in LICENSES
        or result["result_status"] not in STATUSES
    ):
        raise ValueError("无效的成果类型、许可或结果状态")
    tags = data.get("tags") or []
    if (
        not isinstance(tags, list)
        or len(tags) > 12
        or any(not isinstance(t, str) or len(t) > 30 for t in tags)
    ):
        raise ValueError("标签最多 12 个，每个最多 30 字符")
    result["tags"] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    attachments = data.get("attachments") or []
    if not isinstance(attachments, list) or len(attachments) > 8:
        raise ValueError("附件最多 8 个")
    result["attachments"] = []
    total = 0
    for item in attachments:
        if not isinstance(item, dict) or set(item) - {"name", "text", "mime"}:
            raise ValueError("附件只接受明确选择的内容，不接受文件路径")
        name = text(item, "name", 100, required=True)
        body = text(item, "text", 200000, required=True)
        mime = item.get("mime", "text/plain")
        if (
            not re.fullmatch(r"[\w .\-]+\.(md|txt|csv|json)", name)
            or ".." in name
            or mime not in {"text/plain", "text/markdown", "text/csv", "application/json"}
        ):
            raise ValueError("附件名称或类型不受支持")
        total += len(body.encode())
        result["attachments"].append(
            {
                "id": identifier(),
                "name": name,
                "text": body,
                "mime": mime,
                "checksum": hashlib.sha256(body.encode()).hexdigest(),
            }
        )
    if total > 1000000:
        raise ValueError("附件总大小最多 1 MB")
    return result
