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

#: Built map payloads, keyed by (path, mtime). Building one costs ~0.3s — cheap
#: once, wasteful on every pan of the preview or every re-select of the same
#: city. Keyed on mtime so regenerating a city invalidates it automatically.
_MAP_CACHE: dict[tuple[str, float], dict[str, Any]] = {}
_MAP_CACHE_LIMIT = 8


def _selected_city() -> str:
    if not DASHBOARD_CONFIG.exists():
        return ""
    try:
        config = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(config.get("city") or "") if isinstance(config, dict) else ""


def _default_summary() -> dict[str, Any] | None:
    """Bundle-shaped summary for the default world (``data/`` originals).

    It has no ``city.json`` manifest — it predates the bundle format — so it
    is synthesised from the roster and the running config rather than loaded
    from disk like a real bundle. Returns ``None`` when the default dataset
    itself is missing, the same condition ``city_catalogue`` checks.
    """
    from gaworld.interview.roster import DEFAULT_CITY_LABEL, city_catalogue
    from gaworld.settings import CONFIG

    row = next((item for item in city_catalogue() if not item["slug"]), None)
    if row is None:
        return None
    return {
        "slug": "",
        "name": DEFAULT_CITY_LABEL,
        "display_name": DEFAULT_CITY_LABEL,
        "scale": None,
        "map_mode": str(CONFIG.get("map_mode") or "virtual"),
        "population": row["count"],
        "place": {},
        "created_at": None,
        "updated_at": None,
        "directory": None,
    }


def overview() -> dict[str, Any]:
    """Every city plus which one the simulator is currently pointed at."""
    selected = _selected_city()
    cities = [bundle.summary() for bundle in list_cities()]
    default_summary = _default_summary()
    if default_summary is not None:
        cities.insert(0, default_summary)
    return {
        "selected": selected,
        "cities": cities,
        "scales": sorted(SCALE_BBOX_HALF_DEG),
        "presets": sorted(PRESETS),
        "max_population_per_request": MAX_POPULATION_PER_REQUEST,
    }


def detail(ref: str) -> dict[str, Any]:
    if not ref:
        from gaworld.settings import CONFIG

        summary = _default_summary()
        if summary is None:
            raise CityNotFoundError("默认世界没有可用的居民数据")
        return {
            **summary,
            "districts": [],
            "history": [],
            "paths": {
                "map_mode": summary["map_mode"],
                "map_path": CONFIG.get("map_path", "data/citymap.md"),
                "real_map_path": CONFIG.get("real_map_path", "data/hangzhou_real.geojson"),
                "csv_path": CONFIG.get("csv_path", "data/hangzhou_agents_state_init.csv"),
                "md_path": CONFIG.get("md_path", "data/hangzhou_profiles_with_names.md"),
            },
        }
    bundle = resolve_city(ref)
    return {
        **bundle.summary(),
        "districts": city_districts(bundle),
        "history": bundle.manifest.get("history", []),
        "paths": bundle.paths_for_config(),
    }


# ---------------------------------------------------------------------------
# Residents, per city
#
# Read-only, and read from the *bundle* rather than through the simulator's
# globals: ``dashboard_server`` resolves its CSV and Markdown paths once at
# import, so everything it serves is the one city the config points at. These
# two endpoints are what let the city panel list a city's residents and Agent
# Studio look at another city's without a restart.
#
# The population reader lives in ``gaworld.interview.roster`` because the group
# interview panel needed cross-city reads first; it handles bundles and the
# default world (slug ``""``) alike. Importing it here keeps one parser for the
# population files rather than a second copy that drifts.
# ---------------------------------------------------------------------------

#: A page of residents. Large enough that most cities arrive in one request,
#: small enough that a 5000-person city does not ship a megabyte of JSON to
#: render a list nobody will scroll to the end of.
AGENT_PAGE_SIZE = 200


#: Pickers and stamps use the bundle's short ``name``, not ``display_name``:
#: a geocoded place arrives as "乌镇镇, 桐乡市, 嘉兴市, 浙江省, 314501, 中国",
#: which is the right thing on the city card and unreadable in a dropdown.
def _city_label(slug: str) -> str:
    if not slug:
        from gaworld.interview.roster import DEFAULT_CITY_LABEL

        return DEFAULT_CITY_LABEL
    return resolve_city(slug).name


def _city_stamp(slug: str) -> dict[str, Any]:
    """Which city this payload is about, and whether it is the running one.

    Every resident payload carries it because agent ids are only unique
    *within* a city: #1 exists in every one of them. A panel that showed a
    resident without saying which city it came from would invite exactly the
    confusion this stamp prevents.
    """
    return {"slug": slug, "name": _city_label(slug), "selected": _selected_city() == slug}


def catalogue() -> dict[str, Any]:
    """Every city that has residents to show, default world first."""
    from gaworld.interview.roster import city_catalogue

    short = {bundle.slug: bundle.name for bundle in list_cities()}
    cities = [
        {**entry, "name": short.get(entry["slug"], entry["name"]), "display_name": entry["name"]}
        for entry in city_catalogue()
    ]
    return {"cities": cities, "selected": _selected_city()}


def agents(
    ref: str = "",
    *,
    query: str = "",
    limit: int = AGENT_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Residents of *ref* — ``""`` is the default world, not an error."""
    from gaworld.interview.roster import load_population

    if ref:
        ref = resolve_city(ref).slug  # 404s here rather than returning an empty list
    people = load_population(ref)
    needle = str(query or "").strip().lower()
    if needle:
        people = [
            person
            for person in people
            if needle in str(person.get("name", "")).lower()
            or needle in str(person.get("job", "")).lower()
            or needle in str(person.get("residence", "")).lower()
            or needle == str(person.get("id"))
        ]
    try:
        limit = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        limit = AGENT_PAGE_SIZE
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    return {
        "city": _city_stamp(ref),
        "matched": len(people),
        "offset": offset,
        "limit": limit,
        "agents": people[offset : offset + limit],
    }


def agent(ref: str, agent_id: Any) -> dict[str, Any]:
    """One resident: identity, the nine state seeds, and the profile text."""
    from gaworld.interview.roster import load_population, profile_block

    if ref:
        ref = resolve_city(ref).slug
    try:
        wanted = int(str(agent_id).strip())
    except (TypeError, ValueError):
        raise ValueError(f"agent id 无效：{agent_id!r}") from None
    person = next((row for row in load_population(ref) if row["id"] == wanted), None)
    if person is None:
        raise CityNotFoundError(f"城市「{_city_label(ref)}」里没有 #{wanted} 这位居民")
    return {
        "city": _city_stamp(ref),
        "agent": {**person, "profile_text": profile_block(ref, wanted)},
    }


def city_map(ref: str) -> dict[str, Any]:
    """The rendered map payload for one city, for the panel's preview canvas.

    Returns whichever map the bundle actually runs on — the real OSM one when
    it has it, the procedural spec otherwise — so the preview never shows a
    different city than the simulation would use.
    """
    from gaworld.world.city_map import (
        build_visualization_payload,
        load_city_map,
        load_real_city_map,
    )

    bundle = resolve_city(ref)
    mode = bundle.map_mode
    source = bundle.real_map_path if mode == "real" else bundle.virtual_map_path
    if not source.exists():
        raise CityNotFoundError(f"城市「{bundle.display_name}」没有地图文件（{source.name}）")

    key = (str(source), source.stat().st_mtime)
    payload = _MAP_CACHE.get(key)
    if payload is None:
        built = load_real_city_map(str(source)) if mode == "real" else load_city_map(str(source))
        payload = build_visualization_payload(built)
        # The GeoJSON export roughly doubles the response and the canvas
        # renderer does not read it — the panel is a preview, not an export.
        payload.pop("geojson", None)
        if len(_MAP_CACHE) >= _MAP_CACHE_LIMIT:
            _MAP_CACHE.clear()
        _MAP_CACHE[key] = payload

    nodes = payload.get("nodes") or []
    return {
        "city": bundle.summary(),
        "map": payload,
        "meta": {
            "mode": mode,
            # Both an imagined and a name-seeded city run on a virtual map, but
            # calling a described one "procedurally generated" in the panel
            # misattributes the work the user's description actually did.
            "imagined": bool(bundle.manifest.get("imagined")),
            "source": source.name,
            "nodes": len(nodes),
            "edges": len(payload.get("edges") or []),
            "metro_lines": [line.get("name") for line in payload.get("metro_lines") or []],
            "river": (payload.get("river") or {}).get("name", ""),
        },
    }


def knowledge(ref: str) -> dict[str, Any]:
    """The city's economic profile plus the four channels it drives."""
    from gaworld.city.context import CityContext
    from gaworld.city.knowledge import CityProfile

    bundle = resolve_city(ref)
    raw: dict[str, Any] = {}
    if bundle.knowledge_path.exists():
        try:
            raw = json.loads(bundle.knowledge_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
    profile = CityProfile.from_dict(raw)
    context = CityContext(slug=bundle.slug, name=profile.name or bundle.name, profile=profile)
    return {
        "city": bundle.summary(),
        "profile": profile.to_dict(),
        "empty": profile.is_empty,
        # What the profile actually does, so the panel can show effect not just data.
        "channels": {
            "prompt": context.prompt_block(),
            "growth": context.growth_hint(),
            "economy": profile.industry_conditions(),
            "rag": context.rag_chunks(),
        },
    }


def rebuild_knowledge(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.city.create import build_knowledge
    from gaworld.city.context import clear_cache
    from gaworld.city.geocode import Place

    bundle = resolve_city(str(payload.get("city") or ""))
    place_raw = dict(bundle.manifest.get("place") or {})
    place_raw["bbox"] = tuple(place_raw.get("bbox") or (0.0, 0.0, 0.0, 0.0))
    try:
        place = Place(**place_raw)
    except TypeError as exc:
        raise CityCreationError(f"城市清单缺少地点信息：{exc}") from exc

    profile = build_knowledge(bundle, place, offline=bool(payload.get("offline", False)))
    bundle.knowledge_path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle.record(
        "knowledge", source=profile.source, industries=[i.name for i in profile.top_industries()]
    )
    bundle.save()
    clear_cache()
    return knowledge(bundle.slug)


def city_news(ref: str) -> dict[str, Any]:
    from gaworld.city.news import load as news_load

    bundle = resolve_city(ref)
    cache = news_load(bundle.news_path)
    return {
        "city": bundle.summary(),
        "last_fetch": cache.last_fetch,
        "items": [
            {"title": i.title, "excerpt": i.excerpt, "url": i.url, "fetched_at": i.fetched_at}
            for i in reversed(cache.items)
        ][:30],
    }


def refresh_news(payload: dict[str, Any]) -> dict[str, Any]:
    from gaworld.city.context import clear_cache
    from gaworld.city.create import default_search
    from gaworld.city.news import DEFAULT_TTL_HOURS, refresh

    bundle = resolve_city(str(payload.get("city") or ""))
    refresh(
        bundle.news_path,
        bundle.name,
        search_fn=default_search,
        ttl_hours=float(payload.get("ttl_hours") or DEFAULT_TTL_HOURS),
        force=bool(payload.get("force", False)),
    )
    clear_cache()
    return city_news(bundle.slug)


#: Largest sketch we will forward to a model, as base64 characters (~6 MB of
#: image). Past this the request is a screenshot of a whole desktop, not a city
#: diagram, and it would cost a long upload to get a worse answer than a crop.
MAX_SKETCH_B64 = 8_000_000


def _sketch_images(payload: dict[str, Any]) -> list[dict[str, str]]:
    """The uploaded sketch as ``call_llm`` wants it, or an empty list.

    The browser hands over a data URL; everything else here is a guard against
    it being something other than an image.
    """
    raw = str(payload.get("image") or "").strip()
    if not raw:
        return []
    media_type = "image/png"
    if raw.startswith("data:"):
        header, _, data = raw.partition(",")
        if not data:
            raise CityCreationError("图片数据不完整，请重新上传")
        declared = header[5:].split(";")[0].strip()
        if declared:
            media_type = declared
        raw = data
    if not media_type.startswith("image/"):
        raise CityCreationError(f"只支持图片文件，收到的是 {media_type}")
    if len(raw) > MAX_SKETCH_B64:
        raise CityCreationError("图片太大了，请压缩到 6MB 以内再上传")
    return [{"media_type": media_type, "data": raw}]


def create(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise CityCreationError("地名不能为空")
    size = int(payload.get("size") or 0)
    if size > MAX_POPULATION_PER_REQUEST:
        raise AgentError(f"单次最多生成 {MAX_POPULATION_PER_REQUEST} 人")

    description = str(payload.get("description") or "").strip()
    images = _sketch_images(payload)
    bundle = create_city(
        name,
        slug=str(payload.get("slug") or "") or None,
        scale=str(payload.get("scale") or "") or None,
        offline=bool(payload.get("offline", False)),
        force=bool(payload.get("force", False)),
        seed=payload.get("seed"),
        description=description,
        images=images or None,
    )
    result: dict[str, Any] = {"city": bundle.summary()}
    if size > 0:
        result["population"] = add_population(
            bundle,
            size=size,
            preset=str(payload.get("preset") or "") or None,
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
        preset=str(payload.get("preset") or "") or None,
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


def _one(query: Any, key: str, default: str = "") -> str:
    """First value of a repeatable query parameter, or *default*."""
    if not isinstance(query, dict):
        return default
    raw = query.get(key)
    if isinstance(raw, list):
        return str(raw[0]).strip() if raw else default
    return str(raw).strip() if raw is not None else default


def handle_get(path: str, query: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Route ``/api/city/*`` GETs. Returns ``(payload, status)``."""
    try:
        if path in ("/api/city", "/api/city/", "/api/city/overview"):
            return overview(), 200
        if path in ("/api/city/detail", "/api/city/detail/"):
            # No `city` means the default world, same as `/api/city/agents`
            # below — it is a real population, not a missing argument.
            return detail(_one(query, "city")), 200
        if path in ("/api/city/catalogue", "/api/city/catalogue/"):
            return catalogue(), 200
        # No `city` means the default world here, not a missing argument: it is
        # a real population and the panels have to be able to ask for it.
        if path in ("/api/city/agents", "/api/city/agents/"):
            return agents(
                _one(query, "city"),
                query=_one(query, "q"),
                limit=_one(query, "limit") or AGENT_PAGE_SIZE,
                offset=_one(query, "offset") or 0,
            ), 200
        if path in ("/api/city/agent", "/api/city/agent/"):
            agent_id = _one(query, "id")
            if not agent_id:
                return {"error": "id is required"}, 400
            return agent(_one(query, "city"), agent_id), 200
        if path in ("/api/city/map", "/api/city/map/"):
            ref = (query.get("city") or [""])[0] if isinstance(query, dict) else ""
            if not ref:
                return {"error": "city is required"}, 400
            return city_map(ref), 200
        if path in ("/api/city/knowledge", "/api/city/knowledge/"):
            ref = (query.get("city") or [""])[0] if isinstance(query, dict) else ""
            if not ref:
                return {"error": "city is required"}, 400
            return knowledge(ref), 200
        if path in ("/api/city/news", "/api/city/news/"):
            ref = (query.get("city") or [""])[0] if isinstance(query, dict) else ""
            if not ref:
                return {"error": "city is required"}, 400
            return city_news(ref), 200
    except CityNotFoundError as exc:
        return {"error": str(exc)}, 404
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except Exception as exc:  # a panel read must never take the dashboard down
        _LOG.warning("city GET %s failed: %s", path, exc)
        return {"error": f"读取失败：{exc}"}, 500
    return {"error": f"unknown city endpoint: {path}"}, 404


_POST_ROUTES = {
    "/api/city/create": create,
    "/api/city/population": populate,
    "/api/city/agent": add_one,
    "/api/city/migrate": migrate,
    "/api/city/knowledge": rebuild_knowledge,
    "/api/city/news": refresh_news,
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


__all__ = [
    "agent",
    "agents",
    "catalogue",
    "city_map",
    "city_news",
    "handle_get",
    "handle_post",
    "knowledge",
    "overview",
]
