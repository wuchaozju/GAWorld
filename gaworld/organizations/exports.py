"""Read completed metric archives without opening a writable organization store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from gaworld.organizations.comparison import SCOPE
from gaworld.organizations.schemas import identifier, positive_int


class ExportUnavailable(ValueError):
    """No completed archive matches the requested generation/day."""


class ExportInvalid(ValueError):
    """Persisted metadata or an archive cannot be safely exported."""


def _metadata(memory_dir: Path, generation_id: str | None) -> tuple[str, int | None]:
    database = memory_dir / "organizations.sqlite"
    if not database.is_file():
        raise ExportUnavailable("尚无已完成的组织指标")
    state_key = f"generation_state:{generation_id}"
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute(
                "SELECT key,value FROM meta WHERE key IN (?,?,?)",
                ("generation_id", "last_processed_day", state_key),
            ).fetchall()
        meta = {key: json.loads(value) for key, value in rows}
        current = meta.get("generation_id")
        if current is None:
            raise ExportUnavailable("组织尚未开始运行")
        identifier(current)
        selected = generation_id or current
        if selected == current:
            completed = meta.get("last_processed_day")
            if completed is None:
                raise ExportInvalid("当前世代缺少完成日记录")
        else:
            saved = meta.get(state_key)
            completed = saved.get("last_processed_day") if saved is not None else None
        if completed is not None and (type(completed) is not int or completed < 0):
            raise ExportInvalid("组织完成日记录无效")
        return selected, completed
    except ExportUnavailable:
        raise
    except (OSError, sqlite3.Error, ValueError, AttributeError) as exc:
        raise ExportInvalid("无法读取组织完成日记录") from exc


def _invalid_constant(value: str) -> None:
    raise ExportInvalid("组织指标包含非有限数值")


def read_metrics(
    output_dir: str | Path,
    memory_dir: str | Path,
    *,
    generation_id: str | None = None,
    day: int | None = None,
) -> dict[str, Any]:
    """Return the original UTF-8 document and its byte hash, within one world."""
    if generation_id is not None:
        identifier(generation_id)
    if day is not None:
        positive_int(day, "day")
    generation, completed = _metadata(Path(memory_dir), generation_id)
    selected_day = day if day is not None else completed
    if not selected_day:
        raise ExportUnavailable("尚无已完成指标；旧世代缺少完成日记录时请指定 day")
    if completed is not None and selected_day > completed:
        raise ExportUnavailable("请求的组织日尚未完成")
    output = Path(output_dir)
    target = output / "generations" / generation / f"day-{selected_day}" / "metrics.json"
    try:
        escaped = output.is_symlink() or not target.resolve().is_relative_to(output.resolve())
    except (OSError, RuntimeError) as exc:
        raise ExportInvalid("无法解析组织指标路径") from exc
    if escaped:
        raise ExportInvalid("组织指标路径超出当前导出目录")
    try:
        raw = target.read_bytes()
    except FileNotFoundError as exc:
        raise ExportUnavailable("该世代和完成日没有指标档案") from exc
    except OSError as exc:
        raise ExportInvalid("无法读取组织指标档案") from exc
    try:
        content = raw.decode("utf-8")
        payload = json.loads(content, parse_constant=_invalid_constant)
    except ExportInvalid:
        raise
    except (UnicodeError, ValueError) as exc:
        raise ExportInvalid("组织指标档案不是有效 UTF-8 JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("generation_id") != generation
        or type(payload.get("day")) is not int
        or payload["day"] != selected_day
        or payload.get("scope") != SCOPE
        or not isinstance(payload.get("organizations"), list)
    ):
        raise ExportInvalid("指标世代、完成日或累计范围与请求不一致")
    return {
        "filename": f"organizations-{generation}-day-{selected_day}-metrics.json",
        "content_type": "application/json",
        "content": content,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "generation_id": generation,
        "day": selected_day,
        "scope": SCOPE,
    }
