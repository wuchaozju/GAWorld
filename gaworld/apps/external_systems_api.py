"""Dashboard backend for the External Systems panel.

"External systems" are the parts of the world that exist *outside* the agents
and are not authored by them: the monetary/economic system, the external
environment generator (weather, macro news, policy, technology), and the
outward service connections the simulator dials into. Until now each was
observable only by opening a CSV in ``output/`` and editable only by hand-
patching ``dashboard_config.json``. This module makes both first-class.

Three design points, each of which was a trap worth naming:

**Path constants are read from ``world_paths`` at call time**, following
the precedent set by ``population_api``. The dashboard tests monkeypatch
``world_paths.REPO_ROOT`` onto a temp tree, and an import-time binding here would
capture the real repo path first and write into the user's ``output/``.

**Config edits are shape-coerced against the effective config, not
whitelisted field by field.** The economy subtree alone has ~120 leaves; a
hand-written validator for each would be longer than this file and would rot
the first time a knob is added. Instead an incoming patch is walked against
the current config: unknown keys are dropped and known ones are cast to the
type already there, so the panel can expose every knob without the backend
having to enumerate them.

**Runtime edits are queued, not written into the state artifacts.**
``output/economy/macro_state.json`` is an *output* of a run — the simulator
rebuilds macro state from config at ``on_simulation_start`` and never reads
that file back, so editing it would look like it worked and change nothing.
Real mid-run intervention goes through the queue in ``gaworld.economy.finance``
(``interventions.json``), which the running simulator consumes at each day
boundary.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from gaworld.apps import world_paths
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.dashboard.external")

#: Top-level config subtrees each panel may read and write. Anything outside
#: this map is rejected: the panel edits external systems, not the whole config.
CONFIG_SECTIONS: dict[str, tuple[str, ...]] = {
    "currency": ("economy",),
    "environment": ("external_environment", "environment", "policy_events"),
    "services": (
        "external_environment_service",
        "environment_server",
        "external_rag",
        "news",
        "distributed",
    ),
    "public": ("public_sector",),
}

#: Every editable subtree, flattened.
EDITABLE_KEYS: tuple[str, ...] = tuple(
    key for keys in CONFIG_SECTIONS.values() for key in keys
) + ("llm",)

#: How many rows of each history artifact the overview carries. The audit and
#: ledger files grow one row per agent per day; a 100-agent 365-day run is
#: 36,500 rows and the browser does not need them to draw a trend line.
_AUDIT_ROWS = 120
_LEDGER_DAYS = 120
_TIMELINE_DAYS = 8


# ---------------------------------------------------------------------------
# Repo / config access (late-bound; see module docstring)
# ---------------------------------------------------------------------------


def _effective_config() -> dict[str, Any]:
    return world_paths.effective_config()


def _repo_path(*parts: str) -> str:
    return os.path.join(world_paths.REPO_ROOT, *parts)


def _economy_cfg(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else _effective_config()
    economy = cfg.get("economy", {})
    return economy if isinstance(economy, dict) else {}


def _economy_dir(cfg: dict[str, Any] | None = None) -> str:
    return _repo_path(_economy_cfg(cfg).get("output_dir", "output/economy"))


def _environment_dir(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg if cfg is not None else _effective_config()
    return _repo_path(str(cfg.get("environment_output_dir", "output/environment")))


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _read_csv_tail(path: str, limit: int) -> list[dict[str, str]]:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []
    return rows[-limit:] if limit and len(rows) > limit else rows


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _wire_safe(value: Any) -> Any:
    """Make a payload survive ``JSON.parse``.

    ``json.dumps`` emits a bare ``Infinity`` token for ``float("inf")`` and the
    browser rejects the *entire* response — and the economy config genuinely
    contains one: the open-ended top tax bracket. Sending it as the string
    ``"Infinity"`` keeps it visible and round-trips losslessly, because
    ``float("Infinity")`` on the way back in is the same value.
    """
    if isinstance(value, float):
        if value != value:
            return None
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        return value
    if isinstance(value, dict):
        return {key: _wire_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire_safe(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Currency system — observe
# ---------------------------------------------------------------------------


def _gini(values: list[float]) -> float | None:
    """Gini over non-negative wealth. ``None`` when it is not defined."""
    items = sorted(max(0.0, v) for v in values)
    total = sum(items)
    if len(items) < 2 or total <= 0:
        return None
    weighted = sum((index + 1) * value for index, value in enumerate(items))
    n = len(items)
    return round((2.0 * weighted) / (n * total) - (n + 1.0) / n, 4)


def _wealth_summary(economy_dir: str) -> dict[str, Any]:
    rows = _read_csv_tail(os.path.join(economy_dir, "wealth_snapshot.csv"), 0)
    if not rows:
        return {"agents": 0}
    balances = [_num(row.get("balance")) for row in rows]
    debts = [_num(row.get("debt")) for row in rows]
    housing = [_num(row.get("housing_fund")) for row in rows]
    balances_sorted = sorted(balances)
    middle = len(balances_sorted) // 2
    median = (
        balances_sorted[middle]
        if len(balances_sorted) % 2
        else (balances_sorted[middle - 1] + balances_sorted[middle]) / 2.0
    )
    return {
        "agents": len(rows),
        "currency": (rows[0].get("currency") or "CNY"),
        "total_balance": round(sum(balances), 2),
        "total_debt": round(sum(debts), 2),
        "total_housing_fund": round(sum(housing), 2),
        "mean_balance": round(sum(balances) / len(balances), 2),
        "median_balance": round(median, 2),
        "min_balance": round(min(balances), 2),
        "max_balance": round(max(balances), 2),
        "gini": _gini(balances),
        "indebted_agents": sum(1 for value in debts if value > 0),
    }


def _ledger_by_day(economy_dir: str) -> list[dict[str, float]]:
    """Collapse the per-agent daily ledger into one row per day."""
    rows = _read_csv_tail(os.path.join(economy_dir, "daily_ledger.csv"), 0)
    days: dict[int, dict[str, float]] = {}
    for row in rows:
        try:
            day = int(_num(row.get("day")))
        except (TypeError, ValueError):
            continue
        bucket = days.setdefault(
            day, {"day": day, "income": 0.0, "expense": 0.0, "balance": 0.0, "agents": 0}
        )
        bucket["income"] += _num(row.get("income"))
        bucket["expense"] += _num(row.get("expense"))
        bucket["balance"] += _num(row.get("balance"))
        bucket["agents"] += 1
    ordered = [days[key] for key in sorted(days)][-_LEDGER_DAYS:]
    for bucket in ordered:
        bucket["income"] = round(bucket["income"], 2)
        bucket["expense"] = round(bucket["expense"], 2)
        bucket["balance"] = round(bucket["balance"], 2)
        bucket["net"] = round(bucket["income"] - bucket["expense"], 2)
    return ordered


def _conservation(economy_dir: str) -> dict[str, Any]:
    rows = _read_csv_tail(os.path.join(economy_dir, "conservation_audit.csv"), _AUDIT_ROWS)
    parsed = [
        {
            "day": int(_num(row.get("day"))),
            "agents_total": _num(row.get("agents_total")),
            "firms": _num(row.get("firms")),
            "government": _num(row.get("government")),
            "bank": _num(row.get("bank")),
            "system_total": _num(row.get("system_total")),
            "drift": _num(row.get("drift")),
        }
        for row in rows
    ]
    latest = parsed[-1] if parsed else None
    return {
        "rows": parsed,
        "latest": latest,
        "max_abs_drift": round(max((abs(row["drift"]) for row in parsed), default=0.0), 2),
        "ok": all(abs(row["drift"]) < 0.01 for row in parsed) if parsed else None,
    }


def currency_runtime() -> dict[str, Any]:
    """Everything observable about the money system after the latest run."""
    economy_dir = _economy_dir()
    sectors_payload = _read_json(os.path.join(economy_dir, "sectors.json"), {})
    sectors_payload = sectors_payload if isinstance(sectors_payload, dict) else {}
    macro = _read_json(os.path.join(economy_dir, "macro_state.json"), {})
    return {
        "macro": macro if isinstance(macro, dict) else {},
        "sectors": sectors_payload.get("sectors", {}) if isinstance(sectors_payload.get("sectors"), dict) else {},
        "money_stock": {
            "initial_system_total": sectors_payload.get("initial_system_total"),
            "final_system_total": sectors_payload.get("final_system_total"),
            "intervention_injected_total": sectors_payload.get("intervention_injected_total", 0.0),
        },
        "conservation": _conservation(economy_dir),
        "wealth": _wealth_summary(economy_dir),
        "ledger": _ledger_by_day(economy_dir),
        "output_dir": os.path.relpath(economy_dir, world_paths.REPO_ROOT),
        "interventions": interventions(),
    }


# ---------------------------------------------------------------------------
# Environment system — observe
# ---------------------------------------------------------------------------


_TRAFFIC_TICKS = 96


def traffic_runtime() -> dict[str, Any]:
    """Road congestion over the recent ticks, from ``traffic.tick.jsonl``.

    Written only while ``CONFIG["traffic"]["enabled"]`` is on, so an absent
    file means the layer is off — which is a different statement from "the
    roads were clear" and is reported as such.
    """
    records_dir = str(world_paths.records_dir())
    path = os.path.join(records_dir, "traffic.tick.jsonl")
    rows: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    rows.append(record)
    except OSError:
        return {"available": False, "ticks": []}

    recent = rows[-_TRAFFIC_TICKS:]
    peaks = [_num(row.get("congestion_max"), 1.0) for row in rows]
    congested = [row for row in rows if int(row.get("edges_congested", 0) or 0) > 0]
    return {
        "available": True,
        "ticks": recent,
        "tick_count": len(rows),
        "congested_ticks": len(congested),
        "peak_congestion": round(max(peaks), 3) if peaks else 1.0,
        "peak_flow_pcu": round(max(_num(r.get("flow_pcu")) for r in rows), 1) if rows else 0.0,
        # The reading that matters most on a small population: if this is 0,
        # the roads never filled up and every trip ran at free flow.
        "ever_congested": bool(congested),
        "records_path": os.path.relpath(path, world_paths.REPO_ROOT),
    }


def environment_runtime() -> dict[str, Any]:
    """Recent days of the generated external-environment timeline."""
    path = os.path.join(_environment_dir(), "timeline.jsonl")
    days: list[dict[str, Any]] = []
    ticks = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("scope") == "day":
                    days.append(record)
                else:
                    ticks += 1
    except OSError:
        return {"days": [], "tick_records": 0, "latest_day": None, "available": False}

    recent = days[-_TIMELINE_DAYS:]
    type_counts: dict[str, int] = {}
    severities: list[float] = []
    for record in days:
        for event in record.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            key = str(event.get("type", "other"))
            type_counts[key] = type_counts.get(key, 0) + 1
            severities.append(_num(event.get("severity")))
    return {
        "available": True,
        "days": recent,
        "day_count": len(days),
        "tick_records": ticks,
        "latest_day": days[-1].get("day") if days else None,
        "event_type_counts": type_counts,
        "mean_severity": round(sum(severities) / len(severities), 3) if severities else None,
        "timeline_path": os.path.relpath(path, world_paths.REPO_ROOT),
    }


# ---------------------------------------------------------------------------
# Outward services — observe
# ---------------------------------------------------------------------------


def _health_targets(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    service = cfg.get("external_environment_service", {})
    service = service if isinstance(service, dict) else {}
    distributed = cfg.get("distributed", {})
    distributed = distributed if isinstance(distributed, dict) else {}
    relay = distributed.get("relay", {})
    relay = relay if isinstance(relay, dict) else {}
    return [
        {
            "id": "external_environment_service",
            "label": "外部环境服务",
            "url": str(service.get("base_url", "")).rstrip("/") + "/health",
            "enabled": bool(service.get("enabled", False)),
            "timeout": _num(service.get("timeout", 6), 6),
        },
        {
            "id": "distributed_relay",
            "label": "分布式中继",
            "url": str(relay.get("base_url", "")).rstrip("/") + "/health",
            "enabled": bool(distributed.get("enabled", False)),
            "timeout": _num(relay.get("timeout", 3), 3),
        },
    ]


def service_health() -> dict[str, Any]:
    """Probe each configured outward endpoint. Never raises on a dead host."""
    results = []
    for target in _health_targets(_effective_config()):
        record = {key: target[key] for key in ("id", "label", "url", "enabled")}
        if not target["enabled"] or not target["url"].startswith("http"):
            record.update({
                "status": "disabled",
                "detail": "配置里没启用" if not target["enabled"] else "地址无效",
            })
            results.append(record)
            continue
        started = time.time()
        try:
            with urllib.request.urlopen(target["url"], timeout=max(1.0, target["timeout"])) as response:
                record.update(
                    {
                        "status": "ok" if 200 <= response.status < 300 else "error",
                        "detail": f"HTTP {response.status}",
                    }
                )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            record.update({"status": "down", "detail": str(exc)[:200]})
        record["latency_ms"] = int((time.time() - started) * 1000)
        results.append(record)
    return {"targets": results, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def _services_runtime(cfg: dict[str, Any]) -> dict[str, Any]:
    llm = cfg.get("llm", {})
    llm = llm if isinstance(llm, dict) else {}
    providers = llm.get("providers", {})
    news = cfg.get("news", {})
    news = news if isinstance(news, dict) else {}
    cache_path = _repo_path(str(news.get("cache_path", "data/news_cache.json")))
    cache = _read_json(cache_path, {})
    return {
        "llm_providers": sorted(providers.keys()) if isinstance(providers, dict) else [],
        "llm_routing": llm.get("routing", {}),
        "news_cache": {
            "path": os.path.relpath(cache_path, world_paths.REPO_ROOT),
            "entries": len(cache) if isinstance(cache, (dict, list)) else 0,
            "exists": os.path.exists(cache_path),
        },
        "targets": [
            {key: target[key] for key in ("id", "label", "url", "enabled")}
            for target in _health_targets(cfg)
        ],
    }


# ---------------------------------------------------------------------------
# Public sector — observe
# ---------------------------------------------------------------------------


_PUBLIC_DAYS = 120


def _read_records(table: str) -> list[dict[str, Any]]:
    path = os.path.join(str(world_paths.records_dir()), f"{table}.jsonl")
    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    rows.append(record)
    except OSError:
        return []
    return rows


def _live_run() -> dict[str, Any]:
    from gaworld.apps import kernel_api
    from gaworld.kernel import remote

    data = remote.read(kernel_api._queue_path())
    running = remote.is_running(data)
    return {
        "running": running,
        # Only a run started with the public sector on registers the switch.
        "can_switch": running and SWITCH_INTERVENTION in data.get("registered", []),
    }


def public_runtime(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """The configured governments side by side, and what the last run recorded."""
    from gaworld.public_sector import policy

    cfg = cfg if cfg is not None else _effective_config()
    section = cfg.get("public_sector") if isinstance(cfg.get("public_sector"), dict) else {}
    defaults = _default_governments()
    governments = [
        {
            "id": gid,
            "name": str(gov.get("name") or gid),
            "description": str(gov.get("description") or ""),
            "policies": policy.policies_of(gov),
            "summary": policy.policy_lines(policy.policies_of(gov)),
            "brief": policy.brief(gov),
            "builtin": gid in defaults,
        }
        for gid, gov in policy.governments(cfg).items()
    ]
    # Both tables are appended across runs; keep the latest run's rows.
    daily = _read_records("public_sector.daily")
    changes = _read_records("public_sector.change")
    latest = (changes or daily or [{}])[-1].get("run")
    if latest is not None:
        daily = [row for row in daily if row.get("run") == latest]
        changes = [row for row in changes if row.get("run") == latest]
    daily = daily[-_PUBLIC_DAYS:]
    totals: dict[str, float] = {}
    for row in daily:
        for key, value in (row.get("transfers") or {}).items():
            totals[key] = round(totals.get(key, 0.0) + _num(value), 2)
    return {
        "enabled": bool(section.get("enabled", False)),
        "government": str(section.get("government") or "baseline"),
        "schedule": section.get("schedule") or [],
        "governments": governments,
        "daily": daily,
        "changes": changes,
        "transfer_totals": totals,
        "latest_balance": daily[-1].get("government_balance") if daily else None,
        "live": _live_run(),
        "records_path": os.path.relpath(
            os.path.join(str(world_paths.records_dir()), "public_sector.daily.jsonl"), world_paths.REPO_ROOT
        ),
    }


def _default_governments() -> dict[str, Any]:
    from gaworld.settings.public_sector import public_sector_settings

    return public_sector_settings()["public_sector"]["governments"]


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _section_config(cfg: dict[str, Any], section: str) -> dict[str, Any]:
    return {key: cfg.get(key) for key in CONFIG_SECTIONS[section] if key in cfg}


def _field_labels(*trees: Any) -> dict[str, dict[str, str]]:
    """``key -> {zh, en}`` for every leaf and branch name in ``trees``.

    The labels come from :mod:`gaworld.settings.config_docs`, which is the same
    table the 配置 panel uses and is already bilingual. This page used to keep
    its own 195-entry copy, 182 of which were byte-identical to that table — a
    second source of truth for the same strings, and one that would silently
    miss any knob added after it was written. Both languages travel together so
    the browser can switch without refetching.
    """
    from gaworld.settings import config_docs

    labels: dict[str, dict[str, str]] = {}

    def visit(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            # A full-path label wins in the browser too: `schedule` is a model
            # task under llm.routing but a list of elections under public_sector.
            if path != name and path in config_docs.LABELS:
                labels[path] = {"zh": config_docs.label_for(path), "en": config_docs.label_en_for(path)}
            if name not in labels:
                zh = config_docs.label_for(name)
                en = config_docs.label_en_for(name)
                # label_for falls back to the raw key; nothing to send then.
                if zh != name or en:
                    labels[name] = {"zh": zh, "en": en or zh}
            visit(value, path)

    for tree in trees:
        visit(tree, "")
    return labels


def overview() -> dict[str, Any]:
    cfg = _effective_config()
    services_config = _section_config(cfg, "services")
    llm = cfg.get("llm", {})
    if isinstance(llm, dict) and isinstance(llm.get("routing"), dict):
        # Providers carry API keys; only the routing table is editable here.
        services_config["llm"] = {"routing": llm["routing"]}
    currency_config = _section_config(cfg, "currency")
    environment_config = _section_config(cfg, "environment")
    public_config = _section_config(cfg, "public")
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "labels": _field_labels(currency_config, environment_config, services_config, public_config),
        "currency": {
            "config": currency_config,
            "runtime": currency_runtime(),
        },
        "environment": {
            "config": environment_config,
            "runtime": environment_runtime(),
            "traffic": traffic_runtime(),
        },
        "services": {
            "config": services_config,
            "runtime": _services_runtime(cfg),
        },
        "public": {
            "config": public_config,
            "runtime": public_runtime(cfg),
        },
    }


# ---------------------------------------------------------------------------
# Config editing
# ---------------------------------------------------------------------------


def _coerce_like(current: Any, incoming: Any, path: str, dropped: list[str]) -> Any:
    """Cast ``incoming`` to the shape ``current`` already has.

    Unknown dict keys and un-castable scalars are dropped (and reported) rather
    than written through: a typo in the panel should not silently plant a key
    the simulator will never read.
    """
    if isinstance(current, dict):
        if not isinstance(incoming, dict):
            dropped.append(path)
            return None
        result = {}
        for key, value in incoming.items():
            child = f"{path}.{key}" if path else str(key)
            if key not in current:
                dropped.append(child)
                continue
            coerced = _coerce_like(current[key], value, child, dropped)
            if coerced is not None or current[key] is None:
                result[key] = coerced
        return result or None
    if isinstance(current, bool):
        if isinstance(incoming, bool):
            return incoming
        if isinstance(incoming, str) and incoming.lower() in ("true", "false"):
            return incoming.lower() == "true"
        dropped.append(path)
        return None
    if isinstance(current, (int, float)):
        try:
            value = float(incoming)
        except (TypeError, ValueError):
            dropped.append(path)
            return None
        if value != value:  # NaN is never a legitimate config value
            dropped.append(path)
            return None
        # Infinity is: the top tax bracket and the last engel-curve row use it
        # as "no upper bound". `float("Infinity")` accepts the wire form back.
        if value in (float("inf"), float("-inf")):
            return value
        return int(value) if isinstance(current, int) and float(value).is_integer() else value
    if isinstance(current, (list, tuple)):
        if not isinstance(incoming, list):
            dropped.append(path)
            return None
        return _json_safe(incoming, path, dropped)
    if isinstance(current, str):
        if isinstance(incoming, (str, int, float)):
            return str(incoming)
        dropped.append(path)
        return None
    if current is None:
        # A ``None`` default carries no type information; accept any JSON value.
        return _json_safe(incoming, path, dropped)
    dropped.append(path)
    return None


def _json_safe(value: Any, path: str, dropped: list[str]) -> Any:
    """Accept only plain JSON data, so nothing exotic reaches the config file."""
    if isinstance(value, str) and value in ("Infinity", "-Infinity"):
        # The wire form of an unbounded tax bracket / engel-curve row. Left as
        # a string it would silently break the numeric comparison that reads it.
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe(item, path, dropped) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item, path, dropped) for key, item in value.items()}
    dropped.append(path)
    return None


def sanitize_config_patch(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Shape-coerce an incoming patch against the effective config."""
    if not isinstance(payload, dict):
        raise ValueError("config patch must be an object")
    cfg = _effective_config()
    patch: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in payload.items():
        if key not in EDITABLE_KEYS:
            dropped.append(str(key))
            continue
        if key == "llm":
            # Only the routing table; provider credentials stay out of reach.
            routing = value.get("routing") if isinstance(value, dict) else None
            if isinstance(routing, dict):
                current = cfg.get("llm", {}).get("routing", {})
                coerced = _coerce_like(current, routing, "llm.routing", dropped)
                if coerced:
                    patch["llm"] = {"routing": coerced}
            else:
                dropped.append("llm")
            continue
        coerced = _coerce_like(cfg.get(key), value, str(key), dropped)
        if coerced is not None:
            patch[key] = coerced
    return patch, dropped


def save_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge a sanitized patch into ``dashboard_config.json``."""
    patch, dropped = sanitize_config_patch(payload)
    _check_public_patch(patch)
    if not patch:
        return {"saved": False, "dropped": dropped, "config": _panel_configs()}
    current = world_paths.dashboard_config()
    world_paths.deep_update(current, patch)
    world_paths.atomic_write_json(world_paths.DASHBOARD_CONFIG_PATH, current)
    _LOG.info("external-systems config patch applied: %s", sorted(patch))
    return {"saved": True, "dropped": dropped, "applied": sorted(patch), "config": _panel_configs()}


def _check_public_patch(patch: dict[str, Any]) -> None:
    """A government the config does not define would stop the next run."""
    from gaworld.public_sector import policy

    section = patch.get("public_sector")
    if not isinstance(section, dict):
        return
    merged = _effective_config()
    world_paths.deep_update(merged, {"public_sector": section})
    known = policy.governments(merged)
    wanted = [section["government"]] if "government" in section else []
    wanted += [e.get("government") for e in section.get("schedule") or [] if isinstance(e, dict)]
    unknown = sorted({str(gid) for gid in wanted if str(gid) not in known})
    if unknown:
        raise ValueError(f"没有这个政府：{'、'.join(unknown)}")


# ---------------------------------------------------------------------------
# Public sector — governments and the live switch
# ---------------------------------------------------------------------------

SWITCH_INTERVENTION = "public_sector.set_government"
_GOVERNMENT_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def create_government(payload: dict[str, Any]) -> dict[str, Any]:
    """Add a government, starting from a copy of an existing one's policies."""
    from gaworld.public_sector import policy

    gid = str(payload.get("id") or "").strip().lower()
    name = str(payload.get("name") or "").strip()[:40]
    if not _GOVERNMENT_ID.match(gid):
        raise ValueError("政府的键名用小写字母开头，只含小写字母、数字和下划线（2–40 个字符）")
    if not name:
        raise ValueError("政府需要一个名称")
    cfg = _effective_config()
    known = policy.governments(cfg)
    if gid in known:
        raise ValueError(f"已经有键名为 {gid} 的政府")
    base_id = str(payload.get("base") or "baseline")
    if base_id not in known:
        raise ValueError(f"没有这个政府：{base_id}")
    government = {
        "name": name,
        "description": str(payload.get("description") or known[base_id].get("description") or "")[:300],
        "policies": dict(policy.policies_of(known[base_id])),
    }
    current = world_paths.dashboard_config()
    world_paths.deep_update(current, {"public_sector": {"governments": {gid: government}}})
    world_paths.atomic_write_json(world_paths.DASHBOARD_CONFIG_PATH, current)
    _LOG.info("public sector: government %s created from %s", gid, base_id)
    return {"created": gid, "public": public_runtime()}


def delete_government(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove a government added in the panel. Built-in ones stay."""
    gid = str(payload.get("id") or "")
    if gid in _default_governments():
        raise ValueError("内置政府不能删除，可以直接改它的政策")
    cfg = _effective_config()
    section = cfg.get("public_sector") if isinstance(cfg.get("public_sector"), dict) else {}
    in_use = [str(section.get("government") or "baseline")]
    in_use += [str(e.get("government")) for e in section.get("schedule") or [] if isinstance(e, dict)]
    if gid in in_use:
        raise ValueError(f"{gid} 正在被选用或排在换届安排里，先换掉再删")
    current = world_paths.dashboard_config()
    stored = ((current.get("public_sector") or {}).get("governments") or {})
    if gid not in stored:
        raise ValueError(f"没有这个政府：{gid}")
    del stored[gid]
    world_paths.atomic_write_json(world_paths.DASHBOARD_CONFIG_PATH, current)
    return {"deleted": gid, "public": public_runtime()}


def switch_government(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Change the government of the running simulation at its next tick."""
    from gaworld.apps import kernel_api
    from gaworld.kernel import remote
    from gaworld.public_sector import policy

    gid = str(payload.get("government") or "")
    if gid not in policy.governments(_effective_config()):
        return {"error": f"没有这个政府：{gid}"}, 400
    kwargs = {"government": gid, "note": str(payload.get("note") or "")[:200]}
    try:
        item = remote.enqueue(kernel_api._queue_path(), SWITCH_INTERVENTION, kwargs)
    except KeyError:
        return {"error": "正在运行的仿真没有打开公共部门，无法换届；打开后重新开始一轮"}, 409
    except LookupError:
        return {"error": "现在没有正在运行的仿真；要改下一次运行的政府，用「设为执政政府」"}, 409
    return {"queued": item}, 202


def _panel_configs() -> dict[str, Any]:
    cfg = _effective_config()
    return {section: _section_config(cfg, section) for section in CONFIG_SECTIONS}


# ---------------------------------------------------------------------------
# Runtime interventions
# ---------------------------------------------------------------------------


def _intervention_path() -> str:
    from gaworld.economy import finance

    return os.path.join(_economy_dir(), finance.INTERVENTION_FILE)


def interventions() -> dict[str, Any]:
    from gaworld.economy import finance

    queue = finance.read_interventions(_intervention_path())
    return {
        "pending": queue["pending"],
        "applied": queue["applied"][-20:],
        "path": os.path.relpath(_intervention_path(), world_paths.REPO_ROOT),
    }


def queue_intervention(payload: dict[str, Any]) -> dict[str, Any]:
    """Queue a macro / sector change for the running simulator to apply.

    Applied at the next simulated day boundary — or at ``day`` if given. When
    no simulation is running the entry simply waits for the next one.
    """
    from gaworld.economy import finance

    macro_raw = payload.get("macro") if isinstance(payload.get("macro"), dict) else {}
    sector_raw = payload.get("sector_delta") if isinstance(payload.get("sector_delta"), dict) else {}

    macro: dict[str, Any] = {}
    for field, cast in finance.MACRO_INTERVENTION_FIELDS.items():
        if field not in macro_raw or macro_raw[field] in ("", None):
            continue
        try:
            macro[field] = cast(macro_raw[field])
        except (TypeError, ValueError):
            raise ValueError(f"macro.{field} 不是合法数值")
    conditions = macro_raw.get("industry_conditions")
    if isinstance(conditions, dict):
        cleaned = {}
        for industry, value in conditions.items():
            if value in ("", None):
                continue
            cleaned[str(industry)] = _num(value, 1.0)
        if cleaned:
            macro["industry_conditions"] = cleaned

    sector_delta: dict[str, float] = {}
    for name in finance.SECTOR_NAMES:
        if name not in sector_raw or sector_raw[name] in ("", None):
            continue
        amount = round(_num(sector_raw[name]), 2)
        if amount:
            sector_delta[name] = amount

    if not macro and not sector_delta:
        raise ValueError("干预内容为空：至少要改一个宏观字段或部门余额")

    day = payload.get("day")
    if day in ("", None):
        day = None
    else:
        try:
            day = int(day)
        except (TypeError, ValueError):
            raise ValueError("day 必须是整数或留空")

    entry = {
        "id": f"iv-{uuid.uuid4().hex[:8]}",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "day": day,
        "note": str(payload.get("note", ""))[:200],
        "macro": macro,
        "sector_delta": sector_delta,
    }
    path = _intervention_path()
    queue = finance.read_interventions(path)
    queue["pending"].append(entry)
    finance.write_interventions(path, queue)
    _LOG.info("queued economy intervention %s", entry["id"])
    return {"queued": entry, "interventions": interventions()}


def cancel_intervention(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop one pending entry by id, or every pending entry when ``all``."""
    from gaworld.economy import finance

    path = _intervention_path()
    queue = finance.read_interventions(path)
    if payload.get("all"):
        removed = len(queue["pending"])
        queue["pending"] = []
    else:
        target = str(payload.get("id", ""))
        if not target:
            raise ValueError("需要 id，或者 all=true")
        before = len(queue["pending"])
        queue["pending"] = [item for item in queue["pending"] if item.get("id") != target]
        removed = before - len(queue["pending"])
    finance.write_interventions(path, queue)
    return {"removed": removed, "interventions": interventions()}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def handle_get(path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    del query
    if path == "/api/external-systems/overview":
        return _wire_safe(overview()), 200
    if path == "/api/external-systems/health":
        return service_health(), 200
    if path == "/api/external-systems/interventions":
        return _wire_safe(interventions()), 200
    return {"error": "Unknown endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/external-systems/config":
            return _wire_safe(save_config(payload.get("config", payload))), 200
        if path == "/api/external-systems/interventions":
            return _wire_safe(queue_intervention(payload)), 200
        if path == "/api/external-systems/interventions/cancel":
            return _wire_safe(cancel_intervention(payload)), 200
        if path == "/api/external-systems/public/governments":
            return _wire_safe(create_government(payload)), 200
        if path == "/api/external-systems/public/governments/delete":
            return _wire_safe(delete_government(payload)), 200
        if path == "/api/external-systems/public/switch":
            body, status = switch_government(payload)
            return _wire_safe(body), status
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown endpoint"}, 404


__all__ = [
    "CONFIG_SECTIONS",
    "cancel_intervention",
    "create_government",
    "currency_runtime",
    "delete_government",
    "environment_runtime",
    "handle_get",
    "handle_post",
    "interventions",
    "overview",
    "public_runtime",
    "queue_intervention",
    "sanitize_config_patch",
    "save_config",
    "service_health",
    "switch_government",
]
