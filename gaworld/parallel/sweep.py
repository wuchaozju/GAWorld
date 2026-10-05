"""Parameter sweep: one numeric config value, several settings, one world each.

A sweep is an ordinary parallel-worlds experiment whose worlds differ in a
single config value and nothing else. The baseline world keeps the value the
city is configured with; every other world patches it to one of the swept
values and carries that value as its ``dose``, so the dose–response fit the
report already does (:func:`gaworld.parallel.causal.dose_response`) reads the
sweep directly — effect against parameter value, per metric.

What this module adds is only the expansion and its guard rails:

* the path must name a number that exists in the base config — a typo
  would otherwise run N identical worlds and report "no effect";
* experiment-level keys (seed, horizon, cohort, paths) cannot be swept —
  they are what the worlds hold fixed;
* an integer setting only takes integers, so a world never runs with a value
  the setting's reader would truncate or reject;
* a value equal to the current one is the baseline, not another world.

An optional placebo world is an exact copy of the baseline (same config, same
events): with the seed shared, whatever separates it from the baseline is the
simulator's own run-to-run noise, which is the floor every swept effect is
judged against.
"""

from __future__ import annotations

import math
from typing import Any

from gaworld.parallel.spec import RESERVED_CONFIG_KEYS

#: ``normalize_experiment`` accepts at most this many worlds.
MAX_WORLDS = 8


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _label(path: str) -> str:
    from gaworld.settings.config_docs import label_for

    return label_for(path) or path


def fmt(value: float | int) -> str:
    """A value as a person would type it: ``0.02``, ``3``, ``1e-05``."""
    return f"{value:g}" if isinstance(value, float) else str(value)


def tunables(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Every numeric setting a sweep may vary, as ``{path, value, label}``."""
    out: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                walk(value, path)
            elif _is_number(value):
                out.append({"path": path, "value": value, "label": _label(path)})

    walk({k: v for k, v in (config or {}).items() if k not in RESERVED_CONFIG_KEYS}, "")
    return sorted(out, key=lambda item: item["path"])


def current_value(config: dict[str, Any], path: str) -> int | float:
    """The configured value at ``path``; ``ValueError`` when it cannot be swept."""
    path = str(path or "").strip()
    if not path:
        raise ValueError("缺少要扫描的参数")
    parts = path.split(".")
    if parts[0] in RESERVED_CONFIG_KEYS:
        raise ValueError(f"{parts[0]} 是实验级设置（各世界之间的对照基准），不能扫描")
    node: Any = config or {}
    for depth, part in enumerate(parts):
        if not isinstance(node, dict) or part not in node:
            where = ".".join(parts[:depth]) or "配置"
            raise ValueError(f"配置里没有 {path}（{where} 下找不到 {part}）")
        node = node[part]
    if not _is_number(node):
        raise ValueError(f"{path} 不是数值（当前是 {type(node).__name__}），只能扫描数值参数")
    return node


def parse_values(raw: Any) -> list[float]:
    """``[0.01, 0.02]`` or ``"0.01, 0.02"`` → floats, in the order given."""
    items = raw if isinstance(raw, list) else str(raw or "").replace("，", ",").split(",")
    values: list[float] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"取值 {text} 不是数字") from None
        if not math.isfinite(number):
            raise ValueError(f"取值 {text} 不是有限的数")
        values.append(number)
    return values


def patch_for(path: str, value: Any) -> dict[str, Any]:
    """``"a.b.c", 1`` → ``{"a": {"b": {"c": 1}}}`` — the per-world config patch."""
    patch: Any = value
    for part in reversed(path.split(".")):
        patch = {part: patch}
    return patch


def describe_patch(patch: dict[str, Any], prefix: str = "") -> list[str]:
    """``{"a": {"b": 1}}`` → ``["a.b = 1"]``, for plans and logs."""
    lines: list[str] = []
    for key, value in (patch or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            lines += describe_patch(value, path)
        else:
            lines.append(f"{path} = {fmt(value) if _is_number(value) else value}")
    return lines


def sweep_worlds(
    config: dict[str, Any],
    path: str,
    values: Any,
    *,
    events: list[dict[str, Any]] | None = None,
    placebo: bool = False,
) -> dict[str, Any]:
    """Expand a sweep into the ``worlds`` of an experiment payload.

    ``events`` are copied into every world (a sweep under a shared shock);
    they are validated later by ``normalize_experiment`` like any others.
    Returns ``{"worlds", "baseline_id", "path", "label", "current",
    "values", "dropped"}``.
    """
    path = str(path or "").strip()
    current = current_value(config, path)
    integral = isinstance(current, int)
    label = _label(path)
    shared = [dict(item) for item in events or [] if isinstance(item, dict)]

    kept: list[int | float] = []
    dropped: list[dict[str, str]] = []
    for number in parse_values(values):
        if integral:
            if number != int(number):
                raise ValueError(f"{path} 是整数参数，取值 {fmt(number)} 不是整数")
            number = int(number)
        if number == current:
            dropped.append({"value": fmt(number), "reason": "与当前值相同，就是基准世界"})
        elif number in kept:
            dropped.append({"value": fmt(number), "reason": "重复"})
        else:
            kept.append(number)

    room = MAX_WORLDS - 1 - (1 if placebo else 0)
    if len(kept) > room:
        extra = "、安慰剂" if placebo else ""
        raise ValueError(f"最多 {room} 个取值（加上基准{extra}一共 {MAX_WORLDS} 个世界），现在有 {len(kept)} 个")
    if len(kept) < 2:
        raise ValueError("至少要两个与当前值不同的取值，才能看出剂量反应")

    def world(world_id: str, title: str, value: int | float, role: str, patch: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": world_id,
            "label": f"{title}{label} = {fmt(value)}",
            "role": role,
            "dose": value,
            "config": patch,
            "events": [dict(item) for item in shared],
            "note": f"参数扫描：{path} = {fmt(value)}",
        }

    worlds = [world("baseline", "基准：", current, "baseline", {})]
    worlds += [
        world(f"v{index}", "", value, "treatment", patch_for(path, value))
        for index, value in enumerate(sorted(kept), start=1)
    ]
    if placebo:
        worlds.append(world("placebo", "安慰剂：", current, "placebo", {}))
    return {
        "worlds": worlds,
        "baseline_id": "baseline",
        "path": path,
        "label": label,
        "current": current,
        "values": sorted(kept),
        "dropped": dropped,
    }


def parse_sweep_arg(text: str) -> tuple[str, list[float]]:
    """The CLI's ``PATH=V1,V2,…`` → ``(path, values)``."""
    path, sep, values = str(text or "").partition("=")
    if not sep or not path.strip():
        raise ValueError("--sweep 的格式是 参数路径=取值1,取值2,…，例如 economy.shocks.layoff_base_prob=0.01,0.02,0.04")
    return path.strip(), parse_values(values)


__all__ = [
    "MAX_WORLDS",
    "current_value",
    "describe_patch",
    "fmt",
    "parse_sweep_arg",
    "parse_values",
    "patch_for",
    "sweep_worlds",
    "tunables",
]
