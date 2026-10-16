"""Immutable per-attempt input copies; private provider configs stay in memory."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any


def freeze_inputs(
    config: dict[str, Any], repo_root: str, directory: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = copy.deepcopy(config)
    evidence = {}
    for key in ("csv_path", "md_path", "map_path"):
        if not config.get(key):
            continue
        source = (Path(repo_root) / str(config[key])).resolve()
        if not source.is_file():
            if key == "csv_path":
                raise ValueError("居民样本文件不存在")
            continue
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        target = directory / "inputs" / f"{key}-{digest[:16]}{source.suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("运行输入快照已被修改")
        frozen[key] = str(target)
        evidence[key] = {"source": str(source), "sha256": digest, "snapshot": str(target)}
    return frozen, evidence
