"""Portable experiment ZIPs with allowlisted inputs, integrity and no credentials."""

from __future__ import annotations

import base64
import copy
import csv
import hashlib
import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from gaworld.core.comparability import CURRENT_EPOCH
from gaworld.research import batch_inputs, batches
from gaworld.research.editing import protocol_edit
from gaworld.research.protocol import Protocol

MAX_TOTAL = 40_000_000
ASSET_NAME = re.compile(r"^inputs/[0-9]+/[a-z_]+(?:\.[a-z_]+)?\.(csv|md|json|geojson)$")
SUFFIX = {
    "csv_path": ".csv",
    "md_path": ".md",
    "map_path": ".md",
    "real_map_path": ".geojson",
    "personality.profile_path": ".csv",
    "family.overrides_path": ".json",
}


def export_zip(record: dict[str, Any]) -> dict[str, Any]:
    batch_inputs.validate_portable_protocol(record["protocol"])
    manifest = {
        key: copy.deepcopy(record[key])
        for key in (
            "title",
            "protocol",
            "protocol_hash",
            "matrix",
            "models",
            "model_fingerprints",
            "epoch",
            "sample_size",
        )
    }
    manifest.update(schema=1, inputs={})
    # Machine-local identity is not portable; selected residents live in input entries.
    manifest["protocol"]["sample"] = {"agent_ids": [], "note": "样本以每城冻结输入为准"}
    files = {}
    for index, (city, entry) in enumerate(record["inputs"].items()):
        portable = {
            key: copy.deepcopy(entry[key])
            for key in ("city", "agent_ids", "parameters", "sample_hash", "nonportable_hash")
        }
        portable["assets"] = {}
        for key, asset in entry["assets"].items():
            data = Path(asset["path"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise ValueError("冻结输入被修改，不能导出")
            name = f"inputs/{index}/{key}{SUFFIX[key]}"
            files[name] = data
            portable["assets"][key] = {"name": name, "sha256": asset["sha256"]}
        manifest["inputs"][city] = portable
    if sum(map(len, files.values())) > MAX_TOTAL:
        raise ValueError("实验包输入超过 40 MB")
    manifest["integrity"] = batches.digest(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("experiment.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(
            "run_experiment.py", Path(__file__).with_name("batch_runner.py").read_text(encoding="utf-8")
        )
        archive.writestr(
            "gaworld_client.py", Path(__file__).parents[1].joinpath("client.py").read_text(encoding="utf-8")
        )
        archive.writestr("README.md", README)
        for name, data in files.items():
            archive.writestr(name, data)
    return {
        "filename": record["id"] + "-python.zip",
        "mime": "application/zip",
        "data": base64.b64encode(output.getvalue()).decode("ascii"),
    }


def import_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.apps import research_batches_api as api

    manifest = copy.deepcopy(payload.get("bundle"))
    files = payload.get("files")
    if not isinstance(manifest, dict) or not isinstance(files, dict):
        raise ValueError("需要实验包 manifest 和 files")
    if (
        any(not isinstance(value, str) for value in files.values())
        or sum(len(value) for value in files.values()) > 56_000_000
    ):
        raise ValueError("实验包输入超过总大小上限")
    if manifest.get("schema") != 1 or manifest.get("epoch") != CURRENT_EPOCH:
        raise ValueError("实验包格式或代码可比性版本与本机不一致")
    integrity = manifest.pop("integrity", None)
    if integrity != batches.digest(manifest):
        raise ValueError("实验包 manifest 校验失败")
    protocol = protocol_edit(Protocol.from_dict(manifest.get("protocol") or {}).to_dict(), {}).to_dict()
    batch_inputs.validate_portable_protocol(protocol)
    if batches.protocol_hash(protocol) != manifest.get("protocol_hash"):
        raise ValueError("实验协议指纹不一致")
    record = batches.new(protocol, manifest["matrix"])
    record.update(
        epoch=CURRENT_EPOCH,
        models=manifest["models"],
        model_fingerprints=manifest["model_fingerprints"],
        sample_size=manifest["sample_size"],
        imported=True,
    )
    if set(manifest["inputs"]) != set(record["matrix"]["cities"]):
        raise ValueError("城市矩阵与输入不一致")
    if set(record["models"]) != set(record["matrix"]["providers"]):
        raise ValueError("模型矩阵与配置不一致")
    for model in record["models"].values():
        if not isinstance(model, dict) or batch_inputs.public_model(model) != model:
            raise ValueError("便携模型配置包含非公开参数")
    total = 0
    expected_names = set()
    try:
        for index, (city, entry) in enumerate(manifest["inputs"].items()):
            params = entry.get("parameters")
            if not isinstance(params, dict) or batch_inputs.parameters(params) != params:
                raise ValueError("便携输入包含不允许的配置、路径或凭据")
            ids = entry.get("agent_ids")
            if (
                not isinstance(ids, list)
                or not ids
                or any(type(i) is not int or i < 1 for i in ids)
                or len(ids) != len(set(ids))
            ):
                raise ValueError("样本居民 ID 无效")
            frozen = {
                key: copy.deepcopy(entry[key])
                for key in ("city", "agent_ids", "parameters", "sample_hash", "nonportable_hash")
            }
            frozen["assets"] = {}
            for key, asset in entry["assets"].items():
                name = asset.get("name", "")
                if key not in batch_inputs.FILES or not ASSET_NAME.fullmatch(name) or name not in files:
                    raise ValueError("输入文件名、类型或内容不合法")
                expected_names.add(name)
                encoded = files[name]
                if not isinstance(encoded, str) or len(encoded) > 28_000_000:
                    raise ValueError("输入文件过大")
                try:
                    data = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ValueError("输入不是有效的 base64") from exc
                total += len(data)
                if (
                    len(data) > 20_000_000
                    or total > MAX_TOTAL
                    or hashlib.sha256(data).hexdigest() != asset["sha256"]
                ):
                    raise ValueError("输入文件完整性或大小校验失败")
                target = (
                    batches.directory(record["id"])
                    / "inputs"
                    / str(index)
                    / (key.replace(".", "-") + SUFFIX[key])
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                frozen["assets"][key] = {"path": str(target), "sha256": asset["sha256"]}
            if "csv_path" not in frozen["assets"]:
                raise ValueError("缺少居民 CSV")
            with open(frozen["assets"]["csv_path"]["path"], encoding="utf-8-sig", newline="") as handle:
                existing = {int(row.get("agent_id") or row.get("id") or 0) for row in csv.DictReader(handle)}
            if not set(ids) <= existing:
                raise ValueError("样本不属于输入居民 CSV")
            actual_hash = batches.digest(
                {"csv": frozen["assets"]["csv_path"]["sha256"], "agent_ids": sorted(ids)}
            )
            if actual_hash != frozen["sample_hash"]:
                raise ValueError("样本指纹不一致")
            record["inputs"][city] = frozen
        if expected_names != set(files):
            raise ValueError("实验包包含未声明的文件")
        record["preflight"] = api.preflight(record)
        batches.save(record)
    except Exception:
        shutil.rmtree(batches.directory(record["id"]), ignore_errors=True)
        raise
    return record


README = """# GAWorld 本机实验包

1. 安装与来源相同版本的 GAWorld 及 requirements.txt 中的依赖。
2. 在本机配置 experiment.json 所列模型（相同 provider 名、模型和公开生成参数）；密钥只在本机设置。
3. 启动本机服务：`python -m gaworld.apps.dashboard_server --port 8766`。
4. 解压本包，运行 `python run_experiment.py --check-only`，导入冻结协议、城市和人口并检查预算；不调用模型。
5. 运行 `python run_experiment.py`。可用 `--batch-id <上一步批次ID>` 复用已导入批次。

脚本默认调用 http://127.0.0.1:8766，通过 GAWorldClient 访问公开 HTTP API；包内附带仅依赖标准库的客户端副本。
需要账号时设置 GAWORLD_USER、GAWORLD_PASSWORD，或 GAWORLD_DASHBOARD_TOKEN；用 --world 选择有权限的世界。
Ctrl-C 会请求停止，保留产物；重新运行配合 --batch-id 继续剩余任务，--retry-failed 明确重试失败任务。
结果保存至 results/<批次ID>/（batch.json、report.md 及各子研究 JSON/报告）；网页中也可查看日志。

实验协议与输入均带 SHA-256；导入不会替换本机当前城市或全局模型配置。manifest 校验用于完整性，不是来源认证。
缺少模型或本机版本不符会阻止启动，不能静默换模型。代码、默认参数和依赖版本仍应与来源保持一致；
固定种子不能保证外部模型完全确定。多次运行比较是仿真稳健性分析，不能直接证明现实效力。
"""
