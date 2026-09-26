"""Design a city from a description or a sketch, instead of from a map server.

The rest of the city layer answers "what is this real place like?" by going and
looking — Nominatim for coordinates, Overpass for the street network, the web
for the local economy.  This module answers a different question: "what would
*this* city be like?", where the only evidence is a paragraph the user wrote or
a topology sketch they drew.

    description / sketch image
      → LLM designs the city as JSON
      → validated and rendered to the same citymap.md directives
      → climate, background and the economic profile come out of the same pass

The LLM emits **JSON, not citymap.md**.  Asking for the directive format
directly trades one failure mode (a field we can coerce or drop) for a much
worse one (a spec that parses into half a city, silently).  Everything below
the parse is defensive for the same reason: a model that invents a category,
puts a district at x=7.3 on a 0–1 axis, or forgets the roads entirely should
cost the user a slightly plainer city, not a failed creation.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from gaworld.city.knowledge import CityProfile, _parse_json_object, _utcnow
from gaworld.city.procedural import render_citymap, seed_from_name
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.city.imagine")

#: Categories the map layer understands (``CATEGORY_LANDUSE`` in
#: :mod:`gaworld.world.city_map`). A district the model files under anything
#: else lands in ``mixed``, which is the map's own catch-all.
CATEGORIES = (
    "residential",
    "commerce",
    "leisure",
    "education",
    "medical",
    "government",
    "transit",
    "industry",
    "mixed",
)

#: Climate key → a representative latitude in that band. The environment layer
#: derives everything it knows about weather from ``place.lat``, so a described
#: "热带海岛" has to become a latitude before it can become a typhoon.
CLIMATE_LATITUDE = {
    "tropical": 15.0,
    "subtropical": 30.0,
    "temperate": 42.0,
    "continental": 58.0,
    "polar": 75.0,
}

SCALES = ("tiny", "small", "medium", "large", "metro")

#: How many districts to ask for, per scale. The lower bound matters more than
#: the upper: a city with three districts has nowhere for its residents to go.
SCALE_DISTRICTS = {
    "tiny": (4, 7),
    "small": (6, 10),
    "medium": (9, 14),
    "large": (13, 19),
    "metro": (17, 26),
}

#: Hard ceiling regardless of what the model returns — a 200-district answer is
#: a runaway generation, not a city, and it would take the preview canvas with it.
MAX_DISTRICTS = 40
MAX_PLACES_PER_DISTRICT = 8

#: Buildings-with-interiors synthesised per residential district. The model
#: names the district; the flats inside it are structure, not creative work.
RESIDENTIAL_BUILDINGS = (2, 3)


class ImagineError(RuntimeError):
    """Raised when no usable city could be designed from the input."""


@dataclass
class ImaginedCity:
    """What one design pass produced, ready for the bundle writer."""

    spec: str
    summary: str = ""
    scale: str = "medium"
    climate: str = "subtropical"
    profile: CityProfile | None = None
    districts: list[str] = field(default_factory=list)
    source: str = "description"

    @property
    def latitude(self) -> float:
        return CLIMATE_LATITUDE.get(self.climate, CLIMATE_LATITUDE["subtropical"])


_PROMPT = """你是一位城市规划师。请根据下面的材料，设计一座**虚构但可信**的城市，并只输出一个 JSON 对象。

城市名：{name}
{brief}

设计要求：
- 城市规模按 "{scale}" 来把握，给出 {low}–{high} 个城区（district）。
- 城区之间要有主干道连通，不能出现孤岛；有水系就画一条河。
- 每个城区给 3–6 个具体地点（学校、医院、市场、码头……），用与城市名同一种语言命名。
- 地理关系要和材料一致：材料说"北边是山"，山就该在北边。

坐标约定：x、y 都是 0 到 1 的小数。**x=0 是最西，x=1 是最东；y=0 是最南，y=1 是最北**。

只输出 JSON，不要解释，格式如下：
{{
  "summary": "一句话概括这座城市（40 字以内）",
  "scale": "tiny|small|medium|large|metro",
  "climate": "tropical|subtropical|temperate|continental|polar",
  "river": {{"name": "河流名（没有水系就填 null）", "path": [[0.05,0.3],[0.5,0.35],[0.95,0.3]], "width": 0.08}},
  "districts": [
    {{"name": "城区名", "category": "{categories}", "x": 0.3, "y": 0.6,
      "places": ["地点1", "地点2", "地点3"],
      "place_categories": ["commerce", "medical", "leisure"],
      "buildings": ["住宅楼名1", "住宅楼名2"]}}
  ],
  "roads": [["城区A", "城区B"], ["城区B", "城区C"]],
  "metro": {{"name": "1号线", "stops": ["城区A", "城区B", "城区C"]}},
  "industries": [{{"name": "支柱产业", "weight": 0.4, "trend": "growing|stable|declining", "note": "一句话"}}],
  "priorities": ["这座城市正在推进的事"],
  "labor_demand": ["本地缺的岗位或技能"]
}}

说明：
- "category" 只能取：{categories}。
- "place_categories" 与 "places" 一一对应，长度相同；不确定就填 "mixed"。
- "buildings" 只有居住区（residential）需要填，其他城区留空数组。
- "metro" 只有大城市才需要；没有地铁就填 null。
- 产业、优先事项、用工需求要和城市设定吻合——渔村不该主打半导体。
"""

_IMAGE_BRIEF = "材料：用户提供了一张城市拓扑草图（见图）。请按图上的分区位置、相对方位和连接关系来还原这座城市的骨架。"


def _clamp01(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return min(1.0, max(0.0, number))


def _category(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in CATEGORIES else "mixed"


def _clean_name(value: Any, limit: int = 40) -> str:
    # Pipes and newlines are the directive format's own separators, so a name
    # carrying one would silently split into fields that mean something else.
    text = str(value or "").replace("|", "/").replace("\n", " ").strip()
    return text[:limit]


def _grid_extent(count: int) -> float:
    """The grid span an imagined city is laid out across.

    Mirrors the procedural generator's spacing (``3.1`` per column over
    ``max(3, √n + 1)`` columns) so a fifteen-district city is the same physical
    size whether a model designed it or a dice roll did.
    """
    cols = max(3, int(count**0.5) + 1)
    return 3.1 * cols


def _districts_from_design(design: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    """Validated districts in ``render_citymap`` shape, plus their places."""
    raw = design.get("districts")
    if not isinstance(raw, list):
        return []

    hubs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw[:MAX_DISTRICTS]:
        if not isinstance(entry, dict):
            continue
        name = _clean_name(entry.get("name"))
        # Duplicate district names would collapse into one node in the map
        # layer (which keys on the slug), taking their places with them.
        if not name or name in seen:
            continue
        seen.add(name)
        hubs.append(
            {
                "name": name,
                "category": _category(entry.get("category")),
                # Filled in once the whole set is known — the grid extent
                # depends on how many districts survived validation.
                "rel_x": _clamp01(entry.get("x"), 0.5),
                "rel_y": _clamp01(entry.get("y"), 0.5),
                "places": _places_from_entry(entry, seen, rng),
            }
        )
    return hubs


def _places_from_entry(
    entry: dict[str, Any], seen: set[str], rng: random.Random
) -> list[Any]:
    """Small places for one district: named amenities, then any housing."""
    names = entry.get("places") if isinstance(entry.get("places"), list) else []
    categories = entry.get("place_categories")
    if not isinstance(categories, list):
        categories = []

    places: list[Any] = []
    for index, raw_name in enumerate(names[:MAX_PLACES_PER_DISTRICT]):
        name = _clean_name(raw_name)
        if not name or name in seen:
            continue
        seen.add(name)
        category = _category(categories[index]) if index < len(categories) else "mixed"
        places.append({"name": name, "category": category})

    buildings = entry.get("buildings") if isinstance(entry.get("buildings"), list) else []
    if not buildings and _category(entry.get("category")) == "residential":
        # A residential district with no housing is the one case worth filling
        # in ourselves: it is where the simulator puts people to sleep. Named
        # off the district so the result reads the same in any language.
        stem = _clean_name(entry.get("name"), limit=12) or "Residence"
        buildings = [f"{stem}-{i:02d}" for i in range(1, rng.randint(*RESIDENTIAL_BUILDINGS) + 1)]
    for raw_name in buildings[:MAX_PLACES_PER_DISTRICT]:
        name = _clean_name(raw_name)
        if not name or name in seen:
            continue
        seen.add(name)
        places.append(
            {"building": name, "floors": rng.randint(2, 6), "flats": rng.randint(2, 4)}
        )
    return places


def _roads_from_design(
    design: dict[str, Any], names: list[str]
) -> list[tuple[str, str, str]]:
    """Declared roads, filtered to real districts, then made connected.

    An unreachable district is worse than an inelegant one: agents route over
    this graph, so a model that forgot to link its airport would strand anyone
    who works there.
    """
    roads: list[tuple[str, str, str]] = []
    known = set(names)
    linked: set[str] = set()
    for pair in design.get("roads") or []:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        source, target = _clean_name(pair[0]), _clean_name(pair[1])
        if source not in known or target not in known or source == target:
            continue
        if (source, target) in {(s, t) for s, t, _ in roads}:
            continue
        roads.append((source, target, "arterial"))
        linked.update((source, target))

    # Chain anything the model left unconnected onto the network.
    for name in names:
        if name in linked:
            continue
        anchor = next((other for other in names if other in linked), None)
        if anchor is None:
            linked.add(name)
            continue
        roads.append((anchor, name, "collector"))
        linked.add(name)
    return roads


def _metro_from_design(design: dict[str, Any], names: list[str]) -> dict[str, Any] | None:
    metro = design.get("metro")
    if not isinstance(metro, dict):
        return None
    stops = [_clean_name(stop) for stop in metro.get("stops") or []]
    stops = [stop for stop in stops if stop in set(names)]
    # Two stops is a shuttle, not a metro line; the map layer would draw it as
    # a single segment across the city.
    if len(stops) < 3:
        return None
    return {"name": _clean_name(metro.get("name")) or "M1", "stops": stops}


def _river_from_design(design: dict[str, Any]) -> dict[str, Any] | None:
    river = design.get("river")
    if not isinstance(river, dict):
        return None
    name = _clean_name(river.get("name"))
    if not name:
        return None
    path = []
    for point in river.get("path") or []:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            path.append((_clamp01(point[0], 0.5), _clamp01(point[1], 0.5)))
    if len(path) < 2:
        return None
    return {"name": name, "path": path, "width": _clamp01(river.get("width"), 0.08) or 0.08}


def _profile_from_design(design: dict[str, Any], name: str, summary: str) -> CityProfile:
    return CityProfile.from_dict(
        {
            "name": name,
            "summary": summary,
            "industries": design.get("industries") or [],
            "priorities": [
                str(item).strip() for item in (design.get("priorities") or []) if str(item).strip()
            ][:5],
            "labor_demand": [
                str(item).strip() for item in (design.get("labor_demand") or []) if str(item).strip()
            ][:6],
            # Not "web": nothing here was looked up. Every downstream channel
            # can tell an invented city's economy from a researched one.
            "source": "imagined",
            "built_at": _utcnow(),
        }
    )


def build_from_design(design: dict[str, Any], name: str, *, seed: int | None = None) -> ImaginedCity:
    """Turn a parsed design object into a rendered city. Raises on an empty one."""
    rng = random.Random(seed if seed is not None else seed_from_name(name))

    hubs = _districts_from_design(design, rng)
    if len(hubs) < 2:
        raise ImagineError("模型没有给出足够的城区")

    extent = _grid_extent(len(hubs))
    place_categories: dict[str, str] = {}
    for hub in hubs:
        hub["x"] = 2.5 + hub.pop("rel_x") * extent
        hub["y"] = 2.5 + hub.pop("rel_y") * extent
        places: list[Any] = []
        for place in hub["places"]:
            if "building" in place:
                places.append(place)
                # Housing has to say so: "翡翠花园" carries no English keyword
                # for infer_category, and a home filed under `mixed` gets the
                # wrong opening hours and density from CATEGORY_LANDUSE.
                place_categories[place["building"]] = "residential"
                continue
            places.append(place["name"])
            place_categories[place["name"]] = place["category"]
        hub["places"] = places

    names = [hub["name"] for hub in hubs]
    summary = _clean_name(design.get("summary"), limit=120)
    scale = str(design.get("scale") or "").strip().lower()
    climate = str(design.get("climate") or "").strip().lower()

    return ImaginedCity(
        spec=render_citymap(
            name,
            hubs,
            river=_river_from_design(design),
            roads=_roads_from_design(design, names),
            metro=_metro_from_design(design, names),
            place_categories=place_categories,
        ),
        summary=summary,
        scale=scale if scale in SCALES else "medium",
        climate=climate if climate in CLIMATE_LATITUDE else "subtropical",
        profile=_profile_from_design(design, name, summary),
        districts=names,
    )


def imagine_city(
    name: str,
    *,
    description: str = "",
    images: list[dict[str, str]] | None = None,
    scale: str | None = None,
    seed: int | None = None,
    llm_fn: Callable[..., str],
) -> ImaginedCity:
    """Design a city called *name* from a description, a sketch, or both.

    ``llm_fn`` takes the prompt and an optional ``images`` keyword (the
    ``{"media_type", "data"}`` shape :func:`gaworld.llm.providers.call_llm`
    wants), so the caller owns provider selection and the vision check.
    """
    brief = ""
    if description.strip():
        brief = f"材料：{description.strip()}"
    if images:
        brief = f"{brief}\n{_IMAGE_BRIEF}" if brief else _IMAGE_BRIEF
    if not brief:
        raise ImagineError("需要一段描述或一张草图")

    wanted = scale if scale in SCALES else "medium"
    low, high = SCALE_DISTRICTS[wanted]
    prompt = _PROMPT.format(
        name=name,
        brief=brief,
        scale=wanted,
        low=low,
        high=high,
        categories=" | ".join(CATEGORIES),
    )

    try:
        raw = llm_fn(prompt, images=images) if images else llm_fn(prompt)
    except Exception as exc:  # noqa: BLE001 - the caller degrades to procedural
        raise ImagineError(f"生成城市时模型调用失败：{exc}") from exc

    design = _parse_json_object(raw)
    if not design:
        raise ImagineError("模型没有返回可解析的城市设计")

    city = build_from_design(design, name, seed=seed)
    if scale in SCALES:
        # An explicit scale is the operator's call, as it is in resolve_place.
        city.scale = scale
    city.source = "image" if images and not description.strip() else (
        "description+image" if images else "description"
    )
    _LOG.info(
        "imagined %s: %d districts, scale=%s, climate=%s", name, len(city.districts), city.scale, city.climate
    )
    return city


__all__ = [
    "CATEGORIES",
    "CLIMATE_LATITUDE",
    "ImagineError",
    "ImaginedCity",
    "build_from_design",
    "imagine_city",
]
