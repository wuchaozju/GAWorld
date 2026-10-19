"""Freeze city definitions and safe simulation parameters without credentials."""

from __future__ import annotations

import copy
import csv
import hashlib
import random
import re
from pathlib import Path
from typing import Any

from gaworld.accounts import policy
from gaworld.city.config import AGENT_FILES, RUN_PATHS
from gaworld.research import batches
from gaworld.settings.overrides import deep_update

FILES = {
    "csv_path",
    "md_path",
    "map_path",
    "real_map_path",
    "personality.profile_path",
    "family.overrides_path",
}
PUBLIC_MODEL_KEYS = {
    "type",
    "model",
    "temperature",
    "top_p",
    "top_k",
    "seed",
    "max_tokens",
    "num_ctx",
    "num_predict",
    "repeat_penalty",
    "think",
    "thinking",
    "reasoning_effort",
}
EXTRA_PARAMS = {
    "background",
    "environment",
    "map_mode",
    "sim_start_time",
    "tick_minutes",
    "steps_per_day",
    "public_sector",
    "calendar",
    "long_run",
    "group",
    "skills",
    "collaboration",
    "simulation_mode",
    "time_step_minutes",
    "time_grid_snap",
    "seconds_per_day",
    "memory_model_version",
    "policy_events",
    "vector_db_dim",
    "vector_db_top_k",
    "vector_db_max_chars",
    "vector_db_embedding_provider",
}
PARAM_ROOTS = policy.CONFIG_PARAM_SECTIONS | EXTRA_PARAMS
SECRET = re.compile(r"password|credential|authorization|api[_-]?key|auth[_-]?token|secret|^headers$", re.I)


def _blocked(part: str) -> bool:
    if part in {"max_tokens", "budget_tokens", "max_completion_tokens", "max_output_tokens"}:
        return False
    return bool(
        policy._PLACE_OR_SECRET.search(part)
        or SECRET.search(part)
        or re.search(
            r"^(commands?|executable|python_bin|scripts?|adapters?|callbacks?|callable|module)$", part, re.I
        )
    )


def local_only(config: dict[str, Any]) -> dict[str, Any]:
    portable = parameters(config)

    def remainder(value: Any, saved: Any) -> Any:
        if isinstance(value, dict) and isinstance(saved, dict):
            return {
                key: remainder(item, saved[key]) if key in saved else copy.deepcopy(item)
                for key, item in value.items()
                if key not in saved or isinstance(item, dict)
            }
        return {}

    result = copy.deepcopy(config)
    for key in PARAM_ROOTS:
        if key in result:
            result[key] = remainder(result[key], portable.get(key, {}))
    return result


def nonportable_hash(config: dict[str, Any]) -> str:
    """Bind non-transferred server services/code settings without exporting their values."""
    ignored = {
        "llm",
        "agent_ids",
        "city",
        "sim_days",
        "simulate_realtime",
        "stateful",
        "research_workbench",
    }

    residual = local_only(config)
    for path in FILES | set(AGENT_FILES) | set(RUN_PATHS):
        parts = path.split(".")
        node = residual
        for part in parts[:-1]:
            node = node.get(part, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict):
            node.pop(parts[-1], None)

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            result = {k: clean(v) for k, v in value.items() if not SECRET.search(str(k))}
            return {k: v for k, v in result.items() if v != {}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return batches.digest(clean({k: v for k, v in residual.items() if k not in ignored}))


def validate_portable_protocol(protocol: dict[str, Any]) -> None:
    """Reject credential/service/code overrides rather than changing the protocol."""

    def inspect(value: Any, path: str) -> None:
        if path.split(".")[0] not in PARAM_ROOTS or any(_blocked(p) for p in path.split(".")):
            raise ValueError(f"便携协议包含不允许的路径、凭据或服务配置：{path}")
        if isinstance(value, dict) and value:
            for key, item in value.items():
                inspect(item, path + "." + str(key))
        elif isinstance(value, list):
            for item in value:
                inspect(item, path)
        elif value is not None and not isinstance(value, (str, int, float, bool, dict)):
            raise ValueError(f"便携协议包含不允许的路径、凭据或服务配置：{path}")

    for condition in protocol["conditions"]:
        for key, value in (condition.get("config") or {}).items():
            inspect(value, str(key))


def get(config: dict[str, Any], path: str) -> Any:
    value: Any = config
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def put(config: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = config
    for key in parts[:-1]:
        node = node.setdefault(key, {})
    node[parts[-1]] = value


def parameters(config: dict[str, Any]) -> dict[str, Any]:
    """Only parameter leaves; HTTP imports cannot replace code, paths or services."""
    dropped = object()

    def scrub(value: Any, path: str) -> Any:
        if any(_blocked(p) for p in path.split(".")):
            return dropped
        if isinstance(value, dict):
            output = {}
            for key, item in value.items():
                cleaned = scrub(item, path + "." + str(key))
                if cleaned is not dropped:
                    output[key] = cleaned
            return output
        if isinstance(value, list):
            cleaned = [scrub(item, path) for item in value]
            return [item for item in cleaned if item is not dropped]
        if (value is None or isinstance(value, (str, int, float, bool))) and (
            path.split(".")[0] in PARAM_ROOTS
        ):
            return value
        return dropped

    output: dict[str, Any] = {}
    for key in PARAM_ROOTS:
        if key in config:
            cleaned = scrub(config[key], key)
            if cleaned is not dropped:
                output[key] = cleaned
    return output


def public_model(config: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in config.items()
        if key in PUBLIC_MODEL_KEYS and (value is None or isinstance(value, (str, int, float, bool)))
    }
    if isinstance(config.get("thinking"), dict):
        result["thinking"] = {
            k: v
            for k, v in config["thinking"].items()
            if k in {"type", "budget_tokens"} and isinstance(v, (str, int, float, bool))
        }
    options = config.get("options")
    if isinstance(options, dict):
        result["options"] = {
            key: value
            for key, value in options.items()
            if key in PUBLIC_MODEL_KEYS and (value is None or isinstance(value, (str, int, float, bool)))
        }
    return result


def model_fingerprint(config: dict[str, Any]) -> str:
    """Bind all generation settings, including provider-specific options, not credentials."""
    transport = {
        "url",
        "base_url",
        "endpoint",
        "api_key_env",
        "api_key_envs",
        "timeout",
        "max_retries",
        "retries",
    }

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if key not in transport and not SECRET.search(str(key)) and "header" not in str(key).lower()
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return batches.digest(clean(config))


def snapshot(
    config: dict[str, Any],
    batch_id: str,
    city: str,
    index: int,
    repo_root: str,
    *,
    agent_ids: list[int] | None = None,
    sample_size: int = 0,
    seed: int = 42,
) -> dict[str, Any]:
    directory = batches.directory(batch_id) / "inputs" / str(index)
    assets = {}
    for key in sorted(FILES):
        value = get(config, key)
        if not value:
            if key == "csv_path":
                raise ValueError("城市没有居民 CSV")
            continue
        path = (Path(repo_root) / str(value)).resolve()
        if not path.is_file():
            if key == "csv_path":
                raise ValueError("城市居民 CSV 不存在")
            continue
        data = path.read_bytes()
        if len(data) > 20_000_000:
            raise ValueError("输入文件超过 20 MB，无法形成便携实验包")
        sha = hashlib.sha256(data).hexdigest()
        directory.mkdir(parents=True, exist_ok=True)
        filename = key.replace(".", "-") + "-" + sha[:16] + path.suffix
        (directory / filename).write_bytes(data)
        assets[key] = {"sha256": sha, "path": str(directory / filename)}
    with open(assets["csv_path"]["path"], encoding="utf-8-sig", newline="") as handle:
        existing = sorted(
            {int(row.get("agent_id") or row.get("id") or 0) for row in csv.DictReader(handle)} - {0}
        )
    if not existing:
        raise ValueError("城市没有可运行的居民")
    if agent_ids:
        selected = sorted(set(agent_ids))
        if not set(selected) <= set(existing):
            raise ValueError("所选居民不属于目标城市")
    elif sample_size:
        if sample_size > len(existing):
            raise ValueError(
                f"城市 {city or '当前世界'} 只有 {len(existing)} 位居民，少于请求的 {sample_size}"
            )
        selected = sorted(random.Random(seed).sample(existing, sample_size))
    else:
        selected = existing
    return {
        "city": str(config.get("city") or city or "当前世界"),
        "agent_ids": selected,
        "assets": assets,
        "parameters": parameters(config),
        "sample_hash": batches.digest({"csv": assets["csv_path"]["sha256"], "agent_ids": selected}),
        "nonportable_hash": nonportable_hash(config),
    }


def materialize(base_config: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(base_config)
    if nonportable_hash(config) != entry["nonportable_hash"]:
        raise ValueError("未随包传输的服务或插件配置与来源不同，请恢复相同配置后运行")
    private = local_only(config)
    for key in PARAM_ROOTS:
        config.pop(key, None)
        if key in entry["parameters"]:
            config[key] = copy.deepcopy(entry["parameters"][key])
        if isinstance(private.get(key), dict):
            deep_update(config.setdefault(key, {}), private[key])
    config["city"] = entry["city"]
    config["agent_ids"] = list(entry["agent_ids"])
    # Clear population-specific inherited paths; absent snapshots must not read another city.
    for key in FILES | set(AGENT_FILES):
        absent = Path(entry["assets"]["csv_path"]["path"]).parent / ("absent-" + key.replace(".", "-"))
        put(config, key, str(absent))
    for key, asset in entry["assets"].items():
        if key not in FILES:
            raise ValueError("未知输入文件类型")
        path = Path(asset["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("冻结输入被修改，请重新生成批次")
        put(config, key, str(path))
    return config


def apply_world_inputs(manifest: dict[str, Any], config: dict[str, Any]) -> None:
    """Persist public frozen settings, then condition patches and isolated outputs."""
    for world in manifest["worlds"].values():
        frozen = parameters(config)
        deep_update(frozen, world["overrides"])
        for key in FILES:
            put(frozen, key, get(config, key))
        frozen["city"] = config.get("city", "")
        world["overrides"] = frozen
