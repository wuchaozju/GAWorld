"""Dashboard backend for the External Systems panel.

"External systems" are the parts of the world that exist *outside* the agents
and are not authored by them: the monetary/economic system, the external
environment generator (weather, macro news, policy, technology), and the
outward service connections the simulator dials into. Until now each was
observable only by opening a CSV in ``output/`` and editable only by hand-
patching ``dashboard_config.json``. This module makes both first-class.

Three design points, each of which was a trap worth naming:

**Path constants are read from ``dashboard_server`` at call time**, following
the precedent set by ``population_api``. The dashboard tests monkeypatch
``ds.REPO_ROOT`` onto a temp tree, and an import-time binding here would
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
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

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


def _ds():
    from gaworld.apps import dashboard_server

    return dashboard_server


def _effective_config() -> dict[str, Any]:
    return _ds()._effective_config()


def _repo_path(*parts: str) -> str:
    return os.path.join(_ds().REPO_ROOT, *parts)


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
        "output_dir": os.path.relpath(economy_dir, _ds().REPO_ROOT),
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
    records_dir = str(getattr(_ds(), "RECORDS_DIR", os.path.join("output", "records")))
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
        "records_path": os.path.relpath(path, _ds().REPO_ROOT),
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
        "timeline_path": os.path.relpath(path, _ds().REPO_ROOT),
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
            "path": os.path.relpath(cache_path, _ds().REPO_ROOT),
            "entries": len(cache) if isinstance(cache, (dict, list)) else 0,
            "exists": os.path.exists(cache_path),
        },
        "targets": [
            {key: target[key] for key in ("id", "label", "url", "enabled")}
            for target in _health_targets(cfg)
        ],
    }


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

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            name = str(key)
            if name not in labels:
                zh = config_docs.label_for(name)
                en = config_docs.label_en_for(name)
                # label_for falls back to the raw key; nothing to send then.
                if zh != name or en:
                    labels[name] = {"zh": zh, "en": en or zh}
            visit(value)

    for tree in trees:
        visit(tree)
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
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "labels": _field_labels(currency_config, environment_config, services_config),
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
    ds = _ds()
    patch, dropped = sanitize_config_patch(payload)
    if not patch:
        return {"saved": False, "dropped": dropped, "config": _panel_configs()}
    current = ds._dashboard_config()
    ds._deep_update(current, patch)
    ds._atomic_write_json(ds.DASHBOARD_CONFIG_PATH, current)
    _LOG.info("external-systems config patch applied: %s", sorted(patch))
    return {"saved": True, "dropped": dropped, "applied": sorted(patch), "config": _panel_configs()}


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
        "path": os.path.relpath(_intervention_path(), _ds().REPO_ROOT),
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
    return {"error": "Unknown external-systems endpoint"}, 404


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = payload if isinstance(payload, dict) else {}
    try:
        if path == "/api/external-systems/config":
            return _wire_safe(save_config(payload.get("config", payload))), 200
        if path == "/api/external-systems/interventions":
            return _wire_safe(queue_intervention(payload)), 200
        if path == "/api/external-systems/interventions/cancel":
            return _wire_safe(cancel_intervention(payload)), 200
    except ValueError as exc:
        return {"error": str(exc)}, 400
    return {"error": "Unknown external-systems endpoint"}, 404


__all__ = [
    "CONFIG_SECTIONS",
    "cancel_intervention",
    "currency_runtime",
    "environment_runtime",
    "handle_get",
    "handle_post",
    "interventions",
    "overview",
    "queue_intervention",
    "sanitize_config_patch",
    "save_config",
    "service_health",
]
