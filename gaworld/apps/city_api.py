"""Dashboard backend for the 城市 panel — create cities, populate, switch.

A *delegate* module following the ``population_api`` / ``family_api``
precedent: ``dashboard_server.py`` gains four lines of forwarding rather than
another branch of subsystem logic.

Creating a city can take tens of seconds when the OSM fetch is reachable, so
``POST /api/city/create`` accepts ``offline`` and the caller is expected to
show a spinner.  Selecting a city writes ``{"city": slug}`` into
``dashboard_config.json``, which is the same switch the CLI's ``use`` command
throws — there is exactly one mechanism, not two.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gaworld.city.agents import AgentError, add_agent, add_population, city_districts, migrate_agent
from gaworld.city.bundle import CityNotFoundError, delete_city, list_cities, resolve_city
from gaworld.city.create import CityCreationError, create_city
from gaworld.city.geocode import SCALE_BBOX_HALF_DEG
from gaworld.logging_setup import get_logger
from gaworld.population.schema import PRESETS

_LOG = get_logger("gaworld.dashboard.city")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_CONFIG = PROJECT_ROOT / "dashboard_config.json"

#: Hard ceiling on a single bulk-synthesis request. The panel is not the place
#: to kick off a 50k-person generation that will wedge the server for minutes.
MAX_POPULATION_PER_REQUEST = 5000


def _selected_city() -> str:
    if not DASHBOARD_CONFIG.exists():
        return ""
    try:
        config = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(config.get("city") or "") if isinstance(config, dict) else ""


def overview() -> dict[str, Any]:
    """Every city plus which one the simulator is currently pointed at."""
    selected = _selected_city()
    return {
        "selected": selected,
        "cities": [bundle.summary() for bundle in list_cities()],
        "scales": sorted(SCALE_BBOX_HALF_DEG),
        "presets": sorted(PRESETS),
        "max_population_per_request": MAX_POPULATION_PER_REQUEST,
    }


def detail(ref: str) -> dict[str, Any]:
    bundle = resolve_city(ref)
    return {
        **bundle.summary(),
        "districts": city_districts(bundle),
        "history": bundle.manifest.get("history", []),
        "paths": bundle.paths_for_config(),
    }


def create(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise CityCreationError("地名不能为空")
    size = int(payload.get("size") or 0)
    if size > MAX_POPULATION_PER_REQUEST:
        raise AgentError(f"单次最多生成 {MAX_POPULATION_PER_REQUEST} 人")

    bundle = create_city(
        name,
        slug=str(payload.get("slug") or "") or None,
        scale=str(payload.get("scale") or "") or None,
        offline=bool(payload.get("offline", False)),
        force=bool(payload.get("force", False)),
        seed=payload.get("seed"),
    )
    result: dict[str, Any] = {"city": bundle.summary()}
    if size > 0:
        result["population"] = add_population(
            bundle,
            size=size,
            preset=str(payload.get("preset") or "cn_county_town"),
            seed=payload.get("seed"),
        )
        result["city"] = bundle.summary()
    return result


def populate(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = resolve_city(str(payload.get("city") or ""))
    size = int(payload.get("size") or 0)
    if size <= 0:
        raise AgentError("人数必须大于 0")
    if size > MAX_POPULATION_PER_REQUEST:
        raise AgentError(f"单次最多生成 {MAX_POPULATION_PER_REQUEST} 人")
    result = add_population(
        bundle,
        size=size,
        preset=str(payload.get("preset") or "cn_county_town"),
        seed=payload.get("seed"),
        replace=bool(payload.get("replace", False)),
    )
    return {"city": bundle.summary(), "population": result}


def add_one(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = resolve_city(str(payload.get("city") or ""))
    name = str(payload.get("name") or "").strip()
    if not name:
        raise AgentError("姓名不能为空")
    try:
        age = int(payload.get("age"))
    except (TypeError, ValueError) as exc:
        raise AgentError("年龄必须是整数") from exc
    result = add_agent(
        bundle,
        name=name,
        age=age,
        gender=str(payload.get("gender") or "女"),
        job=str(payload.get("job") or "自由职业"),
        hukou=str(payload.get("hukou") or "本地"),
        education=str(payload.get("education") or "本科"),
        income_monthly=float(payload.get("income") or 0.0),
        residence=str(payload.get("residence") or "") or None,
    )
    return {"city": bundle.summary(), "agent": result}


def migrate(payload: dict[str, Any]) -> dict[str, Any]:
    bundle = resolve_city(str(payload.get("city") or ""))
    try:
        agent_id = int(payload.get("agent_id"))
    except (TypeError, ValueError) as exc:
        raise AgentError("agent_id 必须是整数") from exc

    source_ref = str(payload.get("from_city") or "").strip()
    if source_ref:
        source = resolve_city(source_ref)
        source_csv, source_md = source.state_csv_path, source.profiles_md_path
    else:
        from gaworld.apps import dashboard_server

        config = dashboard_server.CONFIG
        source_csv = PROJECT_ROOT / config.get("csv_path", "data/hangzhou_agents_state_init.csv")
        source_md = PROJECT_ROOT / config.get("md_path", "data/hangzhou_profiles_with_names.md")

    result = migrate_agent(
        bundle,
        agent_id,
        source_csv=source_csv,
        source_md=source_md,
        rehome=bool(payload.get("rehome", True)),
    )
    return {"city": bundle.summary(), "agent": result}


def select(payload: dict[str, Any]) -> dict[str, Any]:
    """Write the selected city into ``dashboard_config.json``.

    Takes effect on the next run: ``apply_runtime_overrides`` resolves the
    bundle when the simulator loads its config.
    """
    config: dict[str, Any] = {}
    if DASHBOARD_CONFIG.exists():
        try:
            loaded = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
            config = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            config = {}

    ref = str(payload.get("city") or "").strip()
    if not ref or payload.get("clear"):
        config.pop("city", None)
        selected = ""
    else:
        selected = resolve_city(ref).slug
        config["city"] = selected
    DASHBOARD_CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"selected": selected, "restart_required": True}


def remove(payload: dict[str, Any]) -> dict[str, Any]:
    ref = str(payload.get("city") or "").strip()
    bundle = resolve_city(ref)
    was_selected = _selected_city() == bundle.slug
    removed = delete_city(ref)
    if was_selected:
        # Never leave the config pointing at a directory that no longer exists.
        select({"clear": True})
    return {"removed": str(removed), "cleared_selection": was_selected}


def handle_get(path: str, query: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Route ``/api/city/*`` GETs. Returns ``(payload, status)``."""
    try:
        if path in ("/api/city", "/api/city/", "/api/city/overview"):
            return overview(), 200
        if path in ("/api/city/detail", "/api/city/detail/"):
            ref = (query.get("city") or [""])[0] if isinstance(query, dict) else ""
            if not ref:
                return {"error": "city is required"}, 400
            return detail(ref), 200
    except CityNotFoundError as exc:
        return {"error": str(exc)}, 404
    except Exception as exc:  # a panel read must never take the dashboard down
        _LOG.warning("city GET %s failed: %s", path, exc)
        return {"error": f"读取失败：{exc}"}, 500
    return {"error": f"unknown city endpoint: {path}"}, 404


_POST_ROUTES = {
    "/api/city/create": create,
    "/api/city/population": populate,
    "/api/city/agent": add_one,
    "/api/city/migrate": migrate,
    "/api/city/select": select,
    "/api/city/delete": remove,
}


def handle_post(path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Route ``/api/city/*`` POSTs. Returns ``(payload, status)``."""
    handler = _POST_ROUTES.get(path.rstrip("/") or path)
    if handler is None:
        return {"error": f"unknown city endpoint: {path}"}, 404
    try:
        return handler(payload if isinstance(payload, dict) else {}), 200
    except CityNotFoundError as exc:
        return {"error": str(exc)}, 404
    except (CityCreationError, AgentError, ValueError) as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:
        _LOG.exception("city POST %s failed", path)
        return {"error": f"操作失败：{exc}"}, 500


__all__ = ["handle_get", "handle_post", "overview"]
