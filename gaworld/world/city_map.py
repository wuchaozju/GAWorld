import hashlib
import heapq
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

BASE_LAT = 30.2741
BASE_LNG = 120.1551
KM_PER_GRID_X = 0.85
KM_PER_GRID_Y = 0.72
LAT_PER_KM = 1.0 / 111.0
LNG_PER_KM = 1.0 / 96.0


def _origin_params(origin=None):
    """Resolve a projection anchor to ``(lat0, lng0, lat_per_km, lng_per_km)``.

    The module constants are calibrated for Hangzhou (~30°N), where a degree of
    longitude is ~96 km.  A city elsewhere ships its own anchor in its real-map
    bundle (``meta.origin``) so east-west distances stay true at its latitude;
    ``None`` keeps the historical Hangzhou projection."""
    if not origin:
        return BASE_LAT, BASE_LNG, LAT_PER_KM, LNG_PER_KM
    try:
        return (
            float(origin.get("lat", BASE_LAT)),
            float(origin.get("lng", BASE_LNG)),
            float(origin.get("lat_per_km") or LAT_PER_KM),
            float(origin.get("lng_per_km") or LNG_PER_KM),
        )
    except (AttributeError, TypeError, ValueError):
        return BASE_LAT, BASE_LNG, LAT_PER_KM, LNG_PER_KM

TRANSPORT_MODES = {
    "walk":  {"speed_kmh": 4.8,  "fixed_min": 0},
    "bike":  {"speed_kmh": 13.0, "fixed_min": 1},
    "e-bike":{"speed_kmh": 20.0, "fixed_min": 1},
    "bus":   {"speed_kmh": 18.0, "fixed_min": 6},
    "metro": {"speed_kmh": 32.0, "fixed_min": 7},
    "car":   {"speed_kmh": 27.0, "fixed_min": 4},
    "taxi":  {"speed_kmh": 30.0, "fixed_min": 3},
}

# --- Transport fare table (CNY, based on Hangzhou 2024-2025 typical fares) ---
TRANSPORT_FARES = {
    "walk":   {"base": 0.0,  "per_km": 0.0,  "free_km": 0},
    "bike":   {"base": 0.0,  "per_km": 0.0,  "free_km": 0},       # shared bikes ~1.5/30min but simplified
    "e-bike": {"base": 0.0,  "per_km": 0.1,  "free_km": 0},       # electricity cost
    "bus":    {"base": 2.0,  "per_km": 0.0,  "free_km": 0},       # flat fare
    "metro":  {"base": 2.0,  "per_km": 0.45, "free_km": 4},       # 2 CNY for first 4km, +1 per ~2.2km
    "car":    {"base": 0.0,  "per_km": 0.6,  "free_km": 0,        # fuel + wear
               "parking_per_hour": 6.0},
    "taxi":   {"base": 13.0, "per_km": 2.5,  "free_km": 3},       # 13 CNY base (includes 3km)
}

# --- Rush hour periods (minutes from midnight) ---
RUSH_HOUR_PERIODS = [
    (7 * 60, 9 * 60),       # morning rush 07:00–09:00
    (17 * 60, 19 * 60),     # evening rush 17:00–19:00
]
RUSH_HOUR_TIME_MULT = 1.45   # travel time multiplier during rush hour
RUSH_HOUR_TAXI_SURCHARGE = 1.30  # taxi fare surcharge during rush hour

# --- Area price level by category ---
# Multiplier for local consumption costs (food, leisure, etc.)
AREA_PRICE_LEVEL = {
    "commerce":    1.35,   # CBD / commercial districts are pricier
    "transit":     1.15,   # station areas have markup
    "leisure":     1.20,   # tourist/leisure zones
    "education":   0.85,   # campus areas are cheaper
    "residential": 1.00,   # baseline
    "medical":     1.00,
    "government":  0.95,
    "industry":    0.80,   # industrial areas are cheapest
    "mixed":       1.00,
}

# --- Weather impact on transport mode preference ---
WEATHER_MODE_ADJUSTMENTS = {
    "rain":  {"walk": 0.3, "bike": 0.2, "e-bike": 0.4, "bus": 1.5, "metro": 1.4, "car": 1.2, "taxi": 1.8},
    "snow":  {"walk": 0.2, "bike": 0.1, "e-bike": 0.2, "bus": 1.4, "metro": 1.5, "car": 1.0, "taxi": 2.0},
    "hot":   {"walk": 0.5, "bike": 0.6, "e-bike": 0.8, "bus": 1.3, "metro": 1.3, "car": 1.2, "taxi": 1.3},
    "cold":  {"walk": 0.5, "bike": 0.4, "e-bike": 0.6, "bus": 1.3, "metro": 1.3, "car": 1.1, "taxi": 1.4},
    "clear": {"walk": 1.0, "bike": 1.0, "e-bike": 1.0, "bus": 1.0, "metro": 1.0, "car": 1.0, "taxi": 1.0},
}

# --- Road-class speed multipliers (applied to a mode's base speed) ---
# Wider arterials flow faster than narrow local streets; bridges are neutral.
# Used by ``estimate_travel_minutes`` so travel time reflects the road classes
# actually traversed instead of a single flat mode speed.
ROAD_TYPE_SPEED_FACTOR = {
    "arterial":  1.15,
    "collector": 1.0,
    "road":      1.0,
    "local":     0.8,
    "bridge":    1.0,
}

# --- Per-category visual style hints for front-end rendering ---
# color: marker/fill hex; icon: lucide-style icon name; radius: marker weight.
# Surfaced on every node so the visualizer / web map need not hard-code a
# category→colour table.
CATEGORY_STYLE = {
    "residential": {"color": "#7bb37a", "icon": "home",            "radius": 3},
    "commerce":    {"color": "#e0a458", "icon": "shopping-bag",    "radius": 4},
    "education":   {"color": "#5a9bd4", "icon": "graduation-cap",  "radius": 3},
    "medical":     {"color": "#d96c6c", "icon": "cross",           "radius": 3},
    "industry":    {"color": "#8a8f98", "icon": "factory",         "radius": 4},
    "government":  {"color": "#b08ad4", "icon": "landmark",        "radius": 3},
    "leisure":     {"color": "#5cc2a8", "icon": "trees",           "radius": 3},
    "transit":     {"color": "#d4b95a", "icon": "train-front",     "radius": 4},
    "mixed":       {"color": "#a8a8a8", "icon": "map-pin",         "radius": 2},
}

# --- Per-category land-use defaults used to enrich nodes for simulation ---
# capacity:   rough simultaneous-occupancy ceiling (people)
# open/close: opening hours in minutes-from-midnight (None = always open)
# popularity: relative draw 0..1 (upper-layer destination sampling weight)
# density:    relative built density 0..1 (drives visualization gradients)
CATEGORY_LANDUSE = {
    "residential": {"capacity": 400,  "open": None,         "close": None,          "popularity": 0.35, "density": 0.60},
    "commerce":    {"capacity": 600,  "open": 9 * 60,       "close": 22 * 60,       "popularity": 0.90, "density": 0.85},
    "education":   {"capacity": 1200, "open": 7 * 60,       "close": 18 * 60,       "popularity": 0.50, "density": 0.55},
    "medical":     {"capacity": 500,  "open": None,         "close": None,          "popularity": 0.45, "density": 0.60},
    "industry":    {"capacity": 800,  "open": 6 * 60,       "close": 20 * 60,       "popularity": 0.25, "density": 0.40},
    "government":  {"capacity": 300,  "open": 8 * 60 + 30,  "close": 17 * 60 + 30,  "popularity": 0.30, "density": 0.50},
    "leisure":     {"capacity": 700,  "open": 6 * 60,       "close": 23 * 60,       "popularity": 0.70, "density": 0.35},
    "transit":     {"capacity": 2000, "open": 5 * 60,       "close": 24 * 60,       "popularity": 0.60, "density": 0.70},
    "mixed":       {"capacity": 300,  "open": None,         "close": None,          "popularity": 0.40, "density": 0.50},
}

CATEGORY_KEYWORDS = [
    ("residential", ["Block", "Building", "Dormitory", "Flat", "Family"]),
    ("education", ["School", "Library", "University", "Daycare", "Engineering", "Arts"]),
    ("medical", ["Hospital", "Clinic", "Pharmacy", "Department"]),
    ("transit", ["Station", "Metro", "Airport", "Bus", "Taxi", "Parking", "Loop", "Rd", "Ave", "Terminal"]),
    ("industry", ["Warehouse", "Logistics", "Manufacturing", "Depot", "Substation", "Cargo", "Yard"]),
    ("government", ["Police", "Fire", "City Hall", "Courthouse", "Archives", "Public Services"]),
    ("commerce", ["Market", "Mart", "Bank", "Plaza", "Finance", "Hotel", "Cinema", "Tower"]),
    ("leisure", ["Park", "Playground", "Fitness", "Picnic", "Promenade", "Museum", "Tea House", "Amphitheater", "Stadium", "Aquatic", "Training"]),
]

DEFAULT_RIVER = {
    "name": "Qiantang River",
    "path": [(0.2, 0.22), (0.35, 0.28), (0.52, 0.24), (0.7, 0.31), (0.92, 0.26)],
    "width": 0.085,
}

DEFAULT_METRO_LINES = [
    {"name": "M1", "color": "#8f5bd8", "stops": ["North Block", "Central Block", "Riverside Bus Station", "Financial District", "Central Station", "Airport District"]},
    {"name": "M2", "color": "#2b9ccf", "stops": ["University District", "Central Block", "City Hall", "Riverside Stadium", "Waterfront"]},
]

# Three levels up because this file lives at gaworld/world/city_map.py.
# Previously the file was at the project root, so a single ``.parent`` was
# enough; the S3 migration moved it, hence the explicit ``.parents[2]``.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_existing_path(path):
    """Resolve moved data files while accepting legacy root-level paths."""
    target = Path(str(path))
    if target.exists():
        return str(target)
    if not target.is_absolute():
        repo_target = PROJECT_ROOT / target
        if repo_target.exists():
            return str(repo_target)
        data_target = PROJECT_ROOT / "data" / target.name
        if data_target.exists():
            return str(data_target)
    return str(target)


def _slug(text):
    return re.sub(r"\s+", " ", str(text or "").strip())


def _stable_jitter(name, amp=0.9):
    """Deterministic (x, y) offset in [-amp, amp] derived from a name.

    Uses md5 (not Python's salted ``hash``) so auto-generated layouts get the
    same organic nudge every run, breaking up the rigid spawn grid."""
    digest = hashlib.md5(_slug(name).encode("utf-8")).hexdigest()
    a = int(digest[:8], 16) / 0xFFFFFFFF
    b = int(digest[8:16], 16) / 0xFFFFFFFF
    return ((a - 0.5) * 2 * amp, (b - 0.5) * 2 * amp)


def _parse_directive_parts(text):
    parts = [part.strip() for part in str(text or "").split("|")]
    head = parts[0] if parts else ""
    attrs = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        attrs[key.strip().lower()] = value.strip()
    return head, attrs


def _float_attr(attrs, key, default=None):
    value = attrs.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def infer_category(name):
    label = _slug(name)
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in label for keyword in keywords):
            return category
    return "mixed"


def _parse_map_file(map_path):
    map_path = _resolve_existing_path(map_path)
    parsed = {
        "hubs": [],
        "nodes": {},
        "roads": [],
        "metro_lines": [],
        "river": None,
        "interiors": {},
        # True once the file uses any "@" directive. Such a spec declares its
        # transit explicitly, so an absent @metro means "no metro" rather than
        # "fall back to the defaults" — see _build_city_map.
        "has_directives": False,
    }
    if not os.path.exists(map_path):
        return parsed

    current_hub = None
    current_place = None
    current_floor = None
    with open(map_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("@"):  # explicit city-spec directives
                parsed["has_directives"] = True
                if line.startswith("@node:"):
                    head, attrs = _parse_directive_parts(line[len("@node:"):].strip())
                    name = _slug(head)
                    parsed["nodes"][name] = {
                        "name": name,
                        "kind": attrs.get("kind", "hub"),
                        "district": attrs.get("district", name),
                        "category": attrs.get("category", infer_category(name)),
                        "x": _float_attr(attrs, "x"),
                        "y": _float_attr(attrs, "y"),
                        "parent": attrs.get("parent", ""),
                        "capacity": attrs.get("capacity"),
                        "open": attrs.get("open"),
                        "close": attrs.get("close"),
                        "popularity": attrs.get("popularity"),
                        "density": attrs.get("density"),
                    }
                elif line.startswith("@road:"):
                    head, attrs = _parse_directive_parts(line[len("@road:"):].strip())
                    if "->" in head:
                        source, target = [item.strip() for item in head.split("->", 1)]
                        parsed["roads"].append({
                            "source": _slug(source),
                            "target": _slug(target),
                            "road_type": attrs.get("type", "arterial"),
                            "bridge": attrs.get("bridge", "false").lower() == "true",
                        })
                elif line.startswith("@metro:"):
                    head, attrs = _parse_directive_parts(line[len("@metro:"):].strip())
                    stops = [ _slug(item) for item in attrs.get("stops", "").split(">") if _slug(item) ]
                    if stops:
                        parsed["metro_lines"].append({
                            "name": _slug(head) or f"M{len(parsed['metro_lines']) + 1}",
                            "color": attrs.get("color", "#8f5bd8"),
                            "stops": stops,
                        })
                elif line.startswith("@river:"):
                    head, attrs = _parse_directive_parts(line[len("@river:"):].strip())
                    raw_points = attrs.get("path", "")
                    points = []
                    for pair in raw_points.split(";"):
                        if not pair.strip() or "," not in pair:
                            continue
                        x_text, y_text = pair.split(",", 1)
                        try:
                            points.append((float(x_text.strip()), float(y_text.strip())))
                        except ValueError:
                            continue
                    parsed["river"] = {
                        "name": _slug(head) or DEFAULT_RIVER["name"],
                        "path": points or list(DEFAULT_RIVER["path"]),
                        "width": _float_attr(attrs, "width", DEFAULT_RIVER["width"]),
                    }
                continue

            hub_match = re.match(r"-\s*Hub:\s*(.+)", line)
            if hub_match:
                current_hub = {"name": _slug(hub_match.group(1).strip()), "nearby": []}
                parsed["hubs"].append(current_hub)
                current_place = None
                current_floor = None
                continue
            nearby_match = re.match(r"-\s*Nearby:\s*(.+)", line)
            if nearby_match and current_hub is not None:
                place_name = _slug(nearby_match.group(1).strip())
                current_hub["nearby"].append(place_name)
                current_place = place_name
                current_floor = None
                continue
            # Optional building-interior tree nested under a "- Nearby:" place.
            # Captured as structured metadata (parsed["interiors"]) — NOT added
            # to the routable graph, so it never bloats node count or routing.
            floor_match = re.match(r"-\s*Floor:\s*(.+)", line)
            if floor_match and current_place is not None:
                current_floor = _slug(floor_match.group(1).strip())
                interior = parsed["interiors"].setdefault(current_place, {"floors": []})
                interior["floors"].append({"name": current_floor, "units": []})
                continue
            unit_match = re.match(r"-\s*(?:Flat|Unit|Room|Apt):\s*(.+)", line)
            if unit_match and current_place is not None:
                interior = parsed["interiors"].setdefault(current_place, {"floors": []})
                if not interior["floors"]:
                    interior["floors"].append({"name": "", "units": []})
                interior["floors"][-1]["units"].append(_slug(unit_match.group(1).strip()))
                continue
    return parsed


def load_city_map(map_path):
    parsed = _parse_map_file(map_path)
    return _build_city_map(
        parsed.get("hubs", []),
        explicit_nodes=parsed.get("nodes", {}),
        explicit_roads=parsed.get("roads", []),
        explicit_metro=parsed.get("metro_lines", []),
        explicit_river=parsed.get("river"),
        explicit_interiors=parsed.get("interiors", {}),
        declares_directives=parsed.get("has_directives", False),
    )


def load_city_map_text(map_path):
    map_path = _resolve_existing_path(map_path)
    if not os.path.exists(map_path):
        return ""
    try:
        with open(map_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _build_city_map(hubs, explicit_nodes=None, explicit_roads=None, explicit_metro=None,
                    explicit_river=None, explicit_interiors=None, declares_directives=False):
    explicit_nodes = explicit_nodes or {}
    explicit_roads = explicit_roads or []
    explicit_metro = explicit_metro or []
    explicit_interiors = explicit_interiors or {}
    river = explicit_river or dict(DEFAULT_RIVER)
    nodes = {}
    hub_names = [item["name"] for item in hubs]
    cols = max(3, math.ceil(math.sqrt(max(len(hub_names), 1))))
    road_edges = []

    # First pass: materialize all hubs (with explicit or default positions) so
    # we can compute hub-to-nearest-hub distance for adaptive block sizing.
    hub_nodes = []
    for index, hub in enumerate(hubs):
        row = index // cols
        col = index % cols
        # Deterministic jitter gives auto-laid hubs an organic, non-grid feel.
        # Explicit @node x/y override the default entirely, so curated maps are
        # unaffected.
        jitter_x, jitter_y = _stable_jitter(hub["name"])
        default_x = 2.5 + col * 5.2 + jitter_x
        default_y = 3.6 + row * 4.4 + jitter_y
        node = _make_node_from_spec(
            hub["name"],
            explicit_nodes.get(hub["name"]),
            default_kind="hub",
            default_district=hub["name"],
            default_x=default_x,
            default_y=default_y,
        )
        nodes[node["id"]] = node
        hub_nodes.append((node, hub))

    def _nearest_hub_distance(target):
        best = float("inf")
        for other, _ in hub_nodes:
            if other["id"] == target["id"]:
                continue
            d = math.hypot(other["grid_x"] - target["grid_x"], other["grid_y"] - target["grid_y"])
            if d < best:
                best = d
        return best if best < float("inf") else 4.0

    # Second pass: lay each hub's "nearby" places into a square grid (a block).
    # Adjacent places get local street edges so the road network reads as a
    # real grid instead of radial spokes around the hub.
    for node, hub in hub_nodes:
        nearby = hub.get("nearby", [])
        if not nearby:
            continue
        n = len(nearby)
        grid_size = max(2, math.ceil(math.sqrt(n + 1)))  # +1 reserves a center cell for the hub
        # Adaptive spacing: keep the whole block under ~45% of the distance to
        # the nearest neighbor hub so blocks don't collide.
        block_room = _nearest_hub_distance(node) * 0.45
        spacing = max(0.35, min(0.75, block_room / max(grid_size, 2)))

        # Pre-compute all cell offsets, sorted by distance from center so that
        # the closest-to-hub cells get filled first.
        half = (grid_size - 1) / 2.0
        all_cells = []
        for r in range(grid_size):
            for c in range(grid_size):
                dx = (c - half) * spacing
                dy = (r - half) * spacing
                all_cells.append({"r": r, "c": c, "dx": dx, "dy": dy, "d": math.hypot(dx, dy)})
        all_cells.sort(key=lambda cell: cell["d"])
        # The hub occupies the center cell (dx≈dy≈0). Reserve it for the hub.
        center_cell = all_cells[0]
        place_cells = all_cells[1:1 + n]

        # Materialize place nodes and remember the (r,c) → place_id map for
        # generating local street edges between adjacent places.
        rc_to_place = {}
        for cell, place_name in zip(place_cells, nearby):
            place_node = _make_node_from_spec(
                place_name,
                explicit_nodes.get(place_name),
                default_kind="place",
                default_district=node["name"],
                default_x=node["grid_x"] + cell["dx"],
                default_y=node["grid_y"] + cell["dy"],
                default_parent=node["id"],
            )
            nodes[place_node["id"]] = place_node
            rc_to_place[(cell["r"], cell["c"])] = place_node["id"]
        rc_to_place[(center_cell["r"], center_cell["c"])] = node["id"]

        # Local streets: connect each cell to its orthogonal neighbors. The
        # hub appears at the center cell so this naturally radiates from the
        # hub but only along the 4 cardinal directions, producing the look of
        # a block.
        added_pairs = set()
        for (r, c), id_a in rc_to_place.items():
            for dr, dc in ((1, 0), (0, 1)):
                id_b = rc_to_place.get((r + dr, c + dc))
                if not id_b or id_a == id_b:
                    continue
                pair = tuple(sorted((id_a, id_b)))
                if pair in added_pairs:
                    continue
                added_pairs.add(pair)
                road_type = "collector" if node["id"] in pair else "local"
                road_edges.append(_make_edge(id_a, id_b, road_type))

    for name, spec in explicit_nodes.items():
        if _slug(name) in nodes:
            continue
        fallback_kind = spec.get("kind", "hub")
        district = spec.get("district", name)
        default_x = spec.get("x") if spec.get("x") is not None else 2.0
        default_y = spec.get("y") if spec.get("y") is not None else 2.0
        nodes[_slug(name)] = _make_node_from_spec(
            name,
            spec,
            default_kind=fallback_kind,
            default_district=district,
            default_x=default_x,
            default_y=default_y,
            default_parent=spec.get("parent", ""),
        )

    hub_ids = [node_id for node_id, node in nodes.items() if node["kind"] == "hub"]
    road_edges.extend(_connect_hubs(nodes, hub_ids))
    road_edges.extend(_normalize_explicit_roads(nodes, explicit_roads))
    road_edges = _dedupe_edges(road_edges)

    # A directive-based spec states its transit explicitly, so no @metro line
    # means the place genuinely has none — a generated village must not inherit
    # a subway, which would otherwise skew transport-mode choice and fares.
    # Legacy directive-free maps keep falling back to the defaults.
    if explicit_metro:
        metro_source = explicit_metro
    elif declares_directives:
        metro_source = []
    else:
        metro_source = DEFAULT_METRO_LINES
    metro_lines = _normalize_metro_lines(nodes, metro_source)
    bridges = _detect_bridges(nodes, road_edges, river)
    tile_map = _build_tile_map(nodes, road_edges, river=river, metro_lines=metro_lines, bridges=bridges)
    city_map = {
        "nodes": nodes,
        "edges": road_edges,
        "metro_lines": metro_lines,
        "river": river,
        "bridges": bridges,
        "tile_map": tile_map,
        "bounds": _compute_bounds(nodes),
        "scale": {"km_per_grid_x": KM_PER_GRID_X, "km_per_grid_y": KM_PER_GRID_Y},
        "interiors": explicit_interiors,
    }
    # adjacency, spatial / name indices, runtime state and viz overlays.
    _attach_derived(city_map)
    return city_map


def _parse_hours_to_min(value, default):
    """Parse an opening-hour spec (``"9:00"``, ``"540"`` or a number) to minutes
    from midnight.  Returns *default* when unset/blank/invalid; an explicit
    ``"none"``/``"24h"`` means always-open (None)."""
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in {"none", "24h", "always"}:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return default
    try:
        return int(round(float(text)))
    except (TypeError, ValueError):
        return default


def _make_node_from_spec(name, spec, default_kind, default_district, default_x, default_y, default_parent="",
                         origin=None):
    spec = spec or {}
    kind = spec.get("kind", default_kind)
    district = spec.get("district", default_district)
    grid_x = float(spec.get("x", default_x))
    grid_y = float(spec.get("y", default_y))
    parent = _slug(spec.get("parent", default_parent)) if spec.get("parent", default_parent) else ""
    base_lat, base_lng, lat_per_km, lng_per_km = _origin_params(origin)
    x_km = grid_x * KM_PER_GRID_X
    y_km = grid_y * KM_PER_GRID_Y
    lat = base_lat + y_km * lat_per_km
    lng = base_lng + x_km * lng_per_km
    label = _slug(name)
    category = spec.get("category", infer_category(label))

    # Enrich with land-use attributes the upper-layer simulation can consume
    # (capacity / opening hours / popularity / density) and a visual style.
    landuse = CATEGORY_LANDUSE.get(category, CATEGORY_LANDUSE["mixed"])
    capacity = _float_attr(spec, "capacity", landuse["capacity"])
    open_min = _parse_hours_to_min(spec.get("open"), landuse["open"])
    close_min = _parse_hours_to_min(spec.get("close"), landuse["close"])
    popularity = _float_attr(spec, "popularity", landuse["popularity"])
    density = _float_attr(spec, "density", landuse["density"])
    # Hubs are denser / larger than the small places that cluster around them.
    if kind == "hub":
        density = min(1.0, float(density) * 1.15)
        capacity = float(capacity) * 1.5
    return {
        "id": label,
        "name": label,
        "label": label,
        "kind": kind,
        "district": district,
        "category": category,
        "parent": parent,
        "grid_x": round(grid_x, 3),
        "grid_y": round(grid_y, 3),
        "x_km": round(x_km, 3),
        "y_km": round(y_km, 3),
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "capacity": int(round(float(capacity))),
        "open_min": open_min,
        "close_min": close_min,
        "popularity": round(float(popularity), 3),
        "density": round(float(density), 3),
        "style": dict(CATEGORY_STYLE.get(category, CATEGORY_STYLE["mixed"])),
    }


def _euclidean_distance_km(a, b):
    dx = float(a["x_km"]) - float(b["x_km"])
    dy = float(a["y_km"]) - float(b["y_km"])
    return math.sqrt(dx * dx + dy * dy)


def _make_edge(source_id, target_id, road_type, bridge=False):
    return {"source": _slug(source_id), "target": _slug(target_id), "road_type": road_type, "bridge": bool(bridge)}


def _dedupe_edges(edges):
    seen = {}
    for edge in edges:
        key = (tuple(sorted((_slug(edge["source"]), _slug(edge["target"])))), edge.get("road_type", "road"))
        if key not in seen:
            seen[key] = edge
        elif edge.get("bridge"):
            seen[key]["bridge"] = True
    return list(seen.values())


def _connect_hubs(nodes, hub_ids):
    """Build a realistic arterial road network connecting hubs.

    Strategy: MST as the backbone, then close 2-3 loops by adding the
    shortest cycle-forming edges. Real road networks have redundancy,
    a pure tree feels unnatural.
    """
    if not hub_ids:
        return []
    # Compute pairwise distances.
    hubs = list(hub_ids)
    dist_pair = []  # (dist, a, b)
    for i in range(len(hubs)):
        for j in range(i + 1, len(hubs)):
            d = _euclidean_distance_km(nodes[hubs[i]], nodes[hubs[j]])
            dist_pair.append((d, hubs[i], hubs[j]))
    dist_pair.sort(key=lambda t: t[0])

    # Prim-style MST via union-find on sorted edges (= Kruskal).
    parent = {h: h for h in hubs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    edges = []
    used = set()
    # Pass 1: MST
    for d, a, b in dist_pair:
        if union(a, b):
            pair = tuple(sorted((a, b)))
            used.add(pair)
            road_type = "arterial" if d > 2.4 else "collector"
            edges.append(_make_edge(a, b, road_type))
    # Pass 2: add ~25% extra short edges to form loops (realism: roads have
    # alternate routes, not a strict tree).
    target_loops = max(2, len(hubs) // 4)
    added = 0
    for d, a, b in dist_pair:
        if added >= target_loops:
            break
        pair = tuple(sorted((a, b)))
        if pair in used:
            continue
        used.add(pair)
        edges.append(_make_edge(a, b, "arterial" if d > 2.4 else "collector"))
        added += 1
    return edges


def _normalize_explicit_roads(nodes, roads):
    normalized = []
    for road in roads:
        source = _slug(road.get("source", ""))
        target = _slug(road.get("target", ""))
        if source in nodes and target in nodes and source != target:
            normalized.append(_make_edge(source, target, road.get("road_type", "arterial"), bridge=road.get("bridge", False)))
    return normalized


def _normalize_metro_lines(nodes, lines):
    normalized = []
    for idx, line in enumerate(lines or []):
        stops = []
        for stop in line.get("stops", []):
            stop_id = _slug(stop)
            if stop_id in nodes:
                stops.append(stop_id)
        if len(stops) >= 2:
            normalized.append({
                "name": _slug(line.get("name", f"M{idx + 1}")),
                "color": line.get("color", "#8f5bd8"),
                "stops": stops,
            })
    return normalized


def _build_adjacency(nodes, edges):
    adjacency = defaultdict(list)
    for edge in edges:
        source = nodes.get(edge["source"])
        target = nodes.get(edge["target"])
        if not source or not target:
            continue
        dist = _euclidean_distance_km(source, target)
        item = {"node": target["id"], "distance_km": round(dist, 3), "road_type": edge.get("road_type", "road"), "bridge": bool(edge.get("bridge", False))}
        adjacency[source["id"]].append(item)
        reverse = dict(item)
        reverse["node"] = source["id"]
        adjacency[target["id"]].append(reverse)
    return dict(adjacency)


# ===================================================================
# DERIVED STRUCTURES: adjacency, indices, runtime state, overlays
# ===================================================================

def _build_name_index(nodes):
    """Map lowercased name and id → canonical node id for O(1) lookup."""
    index = {}
    for node_id, node in nodes.items():
        index[node_id.lower()] = node_id
        index[str(node.get("name", "")).lower()] = node_id
    return index


def _build_spatial_index(nodes, cell_km=1.0):
    """Bucket nodes into a uniform km grid for fast radius queries.

    Bucket keys are ``"i,j"`` strings so the index survives JSON round-trips."""
    buckets = defaultdict(list)
    for node_id, node in nodes.items():
        ci = int(math.floor(float(node["x_km"]) / cell_km))
        cj = int(math.floor(float(node["y_km"]) / cell_km))
        buckets[f"{ci},{cj}"].append(node_id)
    return {"cell_km": cell_km, "buckets": dict(buckets)}


def _spatial_candidate_ids(city_map, origin, radius_km):
    """Candidate node ids whose bucket lies within *radius_km* of *origin*.

    Returns ``None`` when no usable index exists, signalling callers to fall
    back to a full scan.  Results are a superset filtered exactly by callers."""
    index = city_map.get("spatial_index")
    if not index or not index.get("buckets"):
        return None
    cell_km = float(index.get("cell_km", 1.0)) or 1.0
    buckets = index["buckets"]
    ci = int(math.floor(float(origin["x_km"]) / cell_km))
    cj = int(math.floor(float(origin["y_km"]) / cell_km))
    reach = int(math.ceil(float(radius_km) / cell_km)) + 1
    out = []
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            out.extend(buckets.get(f"{ci + di},{cj + dj}", ()))
    return out


def _attach_derived(city_map):
    """Attach (or rebuild) adjacency, indices, runtime state and overlays.

    Shared by ``_build_city_map`` and ``deserialize_city_map`` so a map loaded
    from JSON behaves identically to a freshly built one."""
    nodes = city_map.get("nodes", {})
    if not city_map.get("adjacency"):
        city_map["adjacency"] = _build_adjacency(nodes, city_map.get("edges", []))
    city_map.setdefault("runtime", {"edge_congestion": {}, "node_occupancy": {}, "time_min": None})
    city_map["name_index"] = _build_name_index(nodes)
    city_map["spatial_index"] = _build_spatial_index(nodes)
    if not city_map.get("overlays"):
        city_map["overlays"] = _build_overlays(nodes, city_map.get("bounds", {}))
    city_map.setdefault("interiors", {})
    return city_map


def _compute_bounds(nodes):
    if not nodes:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0}
    xs = [node["grid_x"] for node in nodes.values()]
    ys = [node["grid_y"] for node in nodes.values()]
    return {"min_x": min(xs) - 1.8, "min_y": min(ys) - 2.0, "max_x": max(xs) + 1.8, "max_y": max(ys) + 2.0}


def _river_polyline(bounds, river):
    points = river.get("path") or DEFAULT_RIVER["path"]
    out = []
    for px, py in points:
        x = bounds["min_x"] + float(px) * (bounds["max_x"] - bounds["min_x"])
        y = bounds["min_y"] + float(py) * (bounds["max_y"] - bounds["min_y"])
        out.append((x, y))
    return out


def _distance_point_to_segment(point, start, end):
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def _distance_to_polyline(point, polyline):
    if len(polyline) < 2:
        return 999.0
    distances = []
    for idx in range(len(polyline) - 1):
        distances.append(_distance_point_to_segment(point, polyline[idx], polyline[idx + 1]))
    return min(distances) if distances else 999.0


def _edge_crosses_river(nodes, edge, river_polyline, river_width_grid):
    source = nodes.get(edge["source"])
    target = nodes.get(edge["target"])
    if not source or not target:
        return False
    mid = ((source["grid_x"] + target["grid_x"]) / 2.0, (source["grid_y"] + target["grid_y"]) / 2.0)
    return _distance_to_polyline(mid, river_polyline) <= river_width_grid * 1.2


def _detect_bridges(nodes, edges, river):
    bounds = _compute_bounds(nodes)
    river_polyline = _river_polyline(bounds, river)
    river_width_grid = float(river.get("width", DEFAULT_RIVER["width"])) * max(1.0, bounds["max_y"] - bounds["min_y"])
    bridges = []
    for edge in edges:
        if edge.get("bridge") or _edge_crosses_river(nodes, edge, river_polyline, river_width_grid):
            source = nodes.get(edge["source"])
            target = nodes.get(edge["target"])
            if not source or not target:
                continue
            bridges.append({
                "source": source["id"],
                "target": target["id"],
                "mid_x": round((source["grid_x"] + target["grid_x"]) / 2.0, 3),
                "mid_y": round((source["grid_y"] + target["grid_y"]) / 2.0, 3),
            })
    return bridges


def _build_tile_map(nodes, edges, river, metro_lines, bridges, width=160, height=112):
    terrain = [["ground" for _ in range(width)] for _ in range(height)]
    bounds = _compute_bounds(nodes)
    river_polyline = _river_polyline(bounds, river)
    river_width_tiles = max(3.0, float(river.get("width", DEFAULT_RIVER["width"])) * height)

    for row in range(height):
        for col in range(width):
            grid_x = bounds["min_x"] + (col / max(1, width - 1)) * (bounds["max_x"] - bounds["min_x"])
            grid_y = bounds["min_y"] + (row / max(1, height - 1)) * (bounds["max_y"] - bounds["min_y"])
            if _distance_to_polyline((grid_x, grid_y), river_polyline) <= river_width_tiles / max(1, height / (bounds["max_y"] - bounds["min_y"] + 1e-6)):
                terrain[row][col] = "water"
            elif row > height - 14:
                terrain[row][col] = "forest"

    for node in nodes.values():
        tx, ty = project_to_tile(node["grid_x"], node["grid_y"], bounds, width, height)
        terrain_type = _category_to_terrain(node["category"])
        _paint_blob(terrain, tx, ty, terrain_type, radius=5 if node["kind"] == "hub" else 3)

    # Road tiles, in priority order so heavier roads win when they overlap.
    # Local first → collector overrides → arterial overrides → bridge wins.
    road_priority = {"local": 1, "collector": 2, "road": 2, "arterial": 3, "bridge": 4}
    edges_sorted = sorted(edges, key=lambda e: road_priority.get("bridge" if e.get("bridge") else e.get("road_type", "road"), 1))
    for edge in edges_sorted:
        source = nodes.get(edge["source"])
        target = nodes.get(edge["target"])
        if not source or not target:
            continue
        start = project_to_tile(source["grid_x"], source["grid_y"], bounds, width, height)
        end = project_to_tile(target["grid_x"], target["grid_y"], bounds, width, height)
        if edge.get("bridge"):
            symbol = "bridge"
        else:
            symbol = edge.get("road_type", "road") if edge.get("road_type") in {"arterial", "collector", "local"} else "road"
        for col, row in _bresenham(start[0], start[1], end[0], end[1]):
            if 0 <= row < height and 0 <= col < width:
                if terrain[row][col] == "water" and not edge.get("bridge"):
                    continue
                # Don't downgrade an already-painted heavier road.
                cur = terrain[row][col]
                if road_priority.get(cur, 0) > road_priority.get(symbol, 0):
                    continue
                terrain[row][col] = symbol

    metro_segments = []
    for line in metro_lines:
        for idx in range(len(line["stops"]) - 1):
            source = nodes.get(line["stops"][idx])
            target = nodes.get(line["stops"][idx + 1])
            if not source or not target:
                continue
            start = project_to_tile(source["grid_x"], source["grid_y"], bounds, width, height)
            end = project_to_tile(target["grid_x"], target["grid_y"], bounds, width, height)
            points = _bresenham(start[0], start[1], end[0], end[1])
            metro_segments.append({
                "line": line["name"],
                "color": line["color"],
                "points": points,
            })
            for col, row in points:
                if 0 <= row < height and 0 <= col < width and terrain[row][col] not in {"water", "bridge"}:
                    terrain[row][col] = "metro"

    bridge_tiles = []
    for bridge in bridges:
        tx, ty = project_to_tile(bridge["mid_x"], bridge["mid_y"], bounds, width, height)
        bridge_tiles.append({"x": tx, "y": ty, "source": bridge["source"], "target": bridge["target"]})

    return {
        "width": width,
        "height": height,
        "terrain": ["".join(_terrain_symbol(cell) for cell in row) for row in terrain],
        "bounds": bounds,
        "river_path": [project_to_tile(x, y, bounds, width, height) for x, y in river_polyline],
        "metro_segments": metro_segments,
        "bridge_tiles": bridge_tiles,
    }


def _terrain_symbol(value):
    return {
        "ground": ".",
        "road": "#",       # generic road (legacy)
        "arterial": "A",   # widest, asphalt
        "collector": "C",  # medium
        "local": "L",      # narrow, sand/dirt
        "bridge": "=",
        "water": "~",
        "forest": "*",
        "residential": "r",
        "commerce": "c",
        "education": "e",
        "medical": "m",
        "industry": "i",
        "government": "g",
        "leisure": "l",  # note: clashes with "local"; but in terrain a tile
        # is either road OR landuse, never both, so this is OK as long as
        # the road pass runs after the landuse paint (which it does).
        "transit": "t",
        "metro": "+",
        "mixed": "d",
    }.get(value, ".")


def _category_to_terrain(category):
    return {
        "residential": "residential",
        "commerce": "commerce",
        "education": "education",
        "medical": "medical",
        "industry": "industry",
        "government": "government",
        "leisure": "leisure",
        "transit": "transit",
    }.get(category, "mixed")


def _paint_blob(terrain, center_x, center_y, terrain_type, radius):
    height = len(terrain)
    width = len(terrain[0]) if height else 0
    for row in range(center_y - radius, center_y + radius + 1):
        for col in range(center_x - radius, center_x + radius + 1):
            if not (0 <= row < height and 0 <= col < width):
                continue
            dist = abs(col - center_x) + abs(row - center_y)
            if dist <= radius and terrain[row][col] not in {"road", "bridge", "water", "metro"}:
                terrain[row][col] = terrain_type


def _bresenham(x0, y0, x1, y1):
    points = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return points


def project_to_tile(grid_x, grid_y, bounds, width, height):
    span_x = max(0.001, bounds["max_x"] - bounds["min_x"])
    span_y = max(0.001, bounds["max_y"] - bounds["min_y"])
    px = int(round((float(grid_x) - bounds["min_x"]) / span_x * (width - 1)))
    py = int(round((float(grid_y) - bounds["min_y"]) / span_y * (height - 1)))
    return px, py


def all_locations(city_map):
    return list(city_map.get("nodes", {}).keys())


def node_by_name(city_map, name):
    if not name:
        return None
    nodes = city_map.get("nodes", {})
    key = _slug(name)
    if key in nodes:
        return nodes[key]
    # O(1) via the name index when available; fall back to a scan otherwise.
    index = city_map.get("name_index")
    if index:
        node_id = index.get(key.lower())
        if node_id and node_id in nodes:
            return nodes[node_id]
        return None
    for node in nodes.values():
        if node["name"] == key:
            return node
    return None


def map_center_name(city_map):
    """Return the name of the node nearest the map's geometric centre.

    A map-agnostic origin fallback for inference that would otherwise anchor on
    a hardcoded landmark (e.g. "Central Block") — which never exists on a real
    map.  Returns None only for an empty map."""
    nodes = city_map.get("nodes", {})
    if not nodes:
        return None
    bounds = city_map.get("bounds") or _compute_bounds(nodes)
    cx = (float(bounds["min_x"]) + float(bounds["max_x"])) / 2.0
    cy = (float(bounds["min_y"]) + float(bounds["max_y"])) / 2.0
    best_name, best_d = None, float("inf")
    for node in nodes.values():
        d = (float(node["grid_x"]) - cx) ** 2 + (float(node["grid_y"]) - cy) ** 2
        if d < best_d:
            best_d, best_name = d, node["name"]
    return best_name


def distance_between(city_map, origin, target):
    source = node_by_name(city_map, origin)
    dest = node_by_name(city_map, target)
    if not source or not dest:
        return 0.0
    return round(_euclidean_distance_km(source, dest), 3)


def shortest_path(city_map, origin, target):
    """Return the route (list of node names) along the road network."""
    return shortest_path_with_distance(city_map, origin, target)[0]


def shortest_path_with_distance(city_map, origin, target):
    """Dijkstra over the road graph.

    Returns ``(route_names, network_distance_km)`` where the distance is the
    sum of the *actual* edge lengths traversed (not the straight-line
    distance).  Arterials get a mild preference and local streets a mild
    penalty for ranking, but the returned distance reflects true road length.
    """
    nodes = city_map.get("nodes", {})
    adjacency = city_map.get("adjacency", {})
    start = node_by_name(city_map, origin)
    goal = node_by_name(city_map, target)
    if not start or not goal:
        return [], 0.0
    if start["id"] == goal["id"]:
        return [start["name"]], 0.0
    # Heap entries carry both the ranking cost (with road-class penalties) and
    # the true accumulated distance, plus a counter for stable ordering.
    counter = 0
    pq = [(0.0, 0.0, counter, start["id"], [])]
    visited = set()
    while pq:
        cost, real_dist, _, node_id, trail = heapq.heappop(pq)
        if node_id in visited:
            continue
        visited.add(node_id)
        next_trail = trail + [nodes[node_id]["name"]]
        if node_id == goal["id"]:
            return next_trail, round(real_dist, 3)
        for edge in adjacency.get(node_id, []):
            if edge["node"] in visited:
                continue
            dist = float(edge["distance_km"])
            penalty = 0.0
            if edge.get("road_type") == "arterial":
                penalty = -0.03
            elif edge.get("road_type") == "local":
                penalty = 0.05
            counter += 1
            heapq.heappush(
                pq,
                (cost + dist + penalty, real_dist + dist, counter, edge["node"], next_trail),
            )
    # Disconnected: fall back to a direct hop and straight-line distance.
    return [start["name"], goal["name"]], round(_euclidean_distance_km(start, goal), 3)


def path_distance_km(city_map, route):
    """Sum the road-network length (km) of a route given as a list of names.

    Falls back to straight-line distance for any consecutive pair that has no
    direct edge (e.g. a synthesised origin→destination fallback route)."""
    if not route or len(route) < 2:
        return 0.0
    adjacency = city_map.get("adjacency", {})
    total = 0.0
    for a_name, b_name in zip(route, route[1:]):
        a = node_by_name(city_map, a_name)
        b = node_by_name(city_map, b_name)
        if not a or not b:
            continue
        leg = None
        for edge in adjacency.get(a["id"], []):
            if edge["node"] == b["id"]:
                leg = float(edge["distance_km"])
                break
        total += leg if leg is not None else _euclidean_distance_km(a, b)
    return round(total, 3)


def _route_road_factor(city_map, route):
    """Average road-class speed factor over the edges of *route* (default 1.0)."""
    if not route or len(route) < 2:
        return 1.0
    adjacency = city_map.get("adjacency", {})
    factors = []
    for a_name, b_name in zip(route, route[1:]):
        a = node_by_name(city_map, a_name)
        b = node_by_name(city_map, b_name)
        if not a or not b:
            continue
        for edge in adjacency.get(a["id"], []):
            if edge["node"] == b["id"]:
                factors.append(ROAD_TYPE_SPEED_FACTOR.get(edge.get("road_type", "road"), 1.0))
                break
    return sum(factors) / len(factors) if factors else 1.0


def _route_congestion(city_map, route):
    """Average runtime congestion multiplier over the edges of *route*.

    Returns 1.0 when no congestion has been set (the common, free-flow case)."""
    if not route or len(route) < 2:
        return 1.0
    congestion = city_map.get("runtime", {}).get("edge_congestion", {})
    if not congestion:
        return 1.0
    factors = [get_edge_congestion(city_map, a, b) for a, b in zip(route, route[1:])]
    return sum(factors) / len(factors) if factors else 1.0


def choose_transport_mode(agent, city_map, origin, target, activity=None,
                          weather=None):
    """Choose the best transport mode considering distance, profile, route,
    and weather conditions.

    Parameters
    ----------
    weather : str or None
        Weather key (rain/snow/hot/cold/clear).  When set, the initial
        rule-based mode choice is re-evaluated against weather-adjusted
        preference weights — if a sheltered alternative (bus/metro/taxi)
        scores significantly higher, the mode is upgraded.
    """
    distance_km = distance_between(city_map, origin, target)
    origin_node = node_by_name(city_map, origin)
    target_node = node_by_name(city_map, target)
    categories = {origin_node["category"] if origin_node else "",
                  target_node["category"] if target_node else ""}
    profile = " ".join([str(agent.get("job", "")),
                        str(agent.get("daily_life", "")),
                        str(agent.get("personality", ""))])
    route = shortest_path(city_map, origin, target)
    metro_stop_set = {stop for line in city_map.get("metro_lines", [])
                      for stop in line.get("stops", [])}
    route_uses_metro = (len(route) >= 2
                        and any(_slug(stop) in metro_stop_set for stop in route))

    # --- distance-based rule selection (baseline) ---
    if distance_km <= 0.35:
        mode = "walk"
    elif distance_km <= 1.2:
        mode = "walk" if any(k in profile for k in ["散步", "步行", "慢生活"]) else "bike"
    elif distance_km <= 3.2:
        mode = "e-bike"
    elif route_uses_metro and distance_km >= 3.0:
        mode = "metro"
    elif distance_km <= 6.0:
        mode = "bus" if "transit" in categories or "通勤" in str(activity or "") else "e-bike"
    elif distance_km <= 10.0:
        mode = "metro" if route_uses_metro or "transit" in categories else "car"
    else:
        mode = "taxi" if any(k in str(target or "") for k in ["Airport", "Rail", "Station"]) else "metro"

    # --- weather adjustment ---
    # If bad weather significantly penalises the chosen open-air mode,
    # upgrade to the best sheltered alternative that is feasible for the
    # distance.
    if weather and weather in WEATHER_MODE_ADJUSTMENTS:
        adj = WEATHER_MODE_ADJUSTMENTS[weather]
        mode_weight = adj.get(mode, 1.0)
        if mode_weight < 0.6:
            # Current mode is heavily penalised — find a better one.
            # Build a small candidate set appropriate for the distance.
            candidates = []
            if distance_km <= 6.0:
                candidates = ["bus", "metro", "taxi"]
            elif distance_km <= 15.0:
                candidates = ["metro", "car", "taxi"]
            else:
                candidates = ["metro", "taxi"]
            # Pick the candidate with the highest weather-adjusted weight
            # that is also reachable (metro needs stops on route).
            best_mode, best_w = mode, mode_weight
            for c in candidates:
                if c == "metro" and not route_uses_metro:
                    continue
                cw = adj.get(c, 1.0)
                if cw > best_w:
                    best_mode, best_w = c, cw
            mode = best_mode

    return mode, distance_km


def estimate_travel_minutes(mode, distance_km, road_factor=1.0):
    """Estimate trip duration in minutes.

    *road_factor* scales the mode's base speed to reflect the road classes
    traversed (>1 = faster arterials, <1 = slower local streets).  Defaults to
    1.0 so existing callers are unaffected."""
    spec = TRANSPORT_MODES.get(mode, TRANSPORT_MODES["walk"])
    speed = float(spec["speed_kmh"]) * max(0.3, float(road_factor))
    travel = (max(0.05, float(distance_km)) / speed) * 60.0
    return max(1, int(round(travel + float(spec["fixed_min"]))))


def travel_plan(agent, city_map, origin, target, activity=None,
                 time_str=None, weather=None):
    """Build a complete travel plan with cost, time, and route.

    Parameters
    ----------
    time_str : str or None
        Current time as "HH:MM" — used for rush-hour detection.
    weather : str or None
        Current weather condition key (rain/snow/hot/cold/clear).
    """
    mode, straight_km = choose_transport_mode(
        agent, city_map, origin, target, activity=activity, weather=weather)
    route, network_km = shortest_path_with_distance(city_map, origin, target)
    # Prefer the real road-network distance; fall back to straight-line only if
    # the graph yields nothing usable.
    distance_km = network_km if network_km > 0 else straight_km
    road_factor = _route_road_factor(city_map, route)
    minutes = estimate_travel_minutes(mode, distance_km, road_factor=road_factor)
    is_rush = is_rush_hour(time_str) if time_str else False
    if is_rush:
        minutes = max(1, int(round(minutes * RUSH_HOUR_TIME_MULT)))
    # Apply any dynamic per-edge congestion the upper layer has set.
    congestion = _route_congestion(city_map, route)
    if congestion and congestion != 1.0:
        minutes = max(1, int(round(minutes * congestion)))
    cost = calc_transport_cost(mode, distance_km, rush_hour=is_rush)
    return {
        "origin": _slug(origin),
        "destination": _slug(target),
        "distance_km": round(distance_km, 3),
        "straight_distance_km": round(straight_km, 3),
        "network_distance_km": round(network_km, 3),
        "mode": mode,
        "travel_minutes": minutes,
        "travel_cost": round(cost, 2),
        "rush_hour": is_rush,
        "congestion": round(congestion, 3),
        "road_factor": round(road_factor, 3),
        "route": route,
    }


# ===================================================================
# TRANSPORT COST CALCULATION
# ===================================================================

def calc_transport_cost(mode, distance_km, rush_hour=False, parking_hours=0.0):
    """Calculate the fare for a single trip in CNY.

    Parameters
    ----------
    mode : str
        Transport mode key (walk, bike, bus, metro, car, taxi, etc.).
    distance_km : float
        Trip distance in kilometres.
    rush_hour : bool
        Whether the trip occurs during rush hour (taxi surcharge).
    parking_hours : float
        For car mode, how many hours of parking to include.

    Returns
    -------
    float
        Total fare in CNY.
    """
    fare_spec = TRANSPORT_FARES.get(mode, TRANSPORT_FARES.get("walk", {}))
    base = float(fare_spec.get("base", 0.0))
    per_km = float(fare_spec.get("per_km", 0.0))
    free_km = float(fare_spec.get("free_km", 0.0))
    chargeable_km = max(0.0, float(distance_km) - free_km)
    cost = base + chargeable_km * per_km

    # Taxi rush-hour surcharge
    if mode == "taxi" and rush_hour:
        cost *= RUSH_HOUR_TAXI_SURCHARGE

    # Car parking cost
    if mode == "car" and parking_hours > 0:
        parking_rate = float(fare_spec.get("parking_per_hour", 6.0))
        cost += parking_hours * parking_rate

    return max(0.0, round(cost, 2))


def is_rush_hour(time_str):
    """Check if a HH:MM time string falls in a rush-hour period."""
    if not time_str or not isinstance(time_str, str):
        return False
    parts = time_str.strip().split(":")
    if len(parts) < 2:
        return False
    try:
        minutes = int(parts[0]) * 60 + int(parts[1])
    except (ValueError, TypeError):
        return False
    for start, end in RUSH_HOUR_PERIODS:
        if start <= minutes < end:
            return True
    return False


# ===================================================================
# SPATIAL QUERIES
# ===================================================================

def _candidate_nodes(city_map, origin, radius_km):
    """(nid, node) pairs to test for a radius query.

    Uses the spatial index to prune when present; otherwise yields all nodes.
    Callers still apply the exact distance filter, so results are unchanged."""
    nodes = city_map.get("nodes", {})
    ids = _spatial_candidate_ids(city_map, origin, radius_km)
    if ids is None:
        return list(nodes.items())
    out, seen = [], set()
    for nid in ids:
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes.get(nid)
        if node is not None:
            out.append((nid, node))
    return out


def nearby_nodes(city_map, node_id, radius_km=2.0):
    """Return all nodes within *radius_km* of *node_id*, sorted by distance.

    Each result is a dict: {node, distance_km}.
    """
    nodes = city_map.get("nodes", {})
    origin = nodes.get(_slug(node_id))
    if not origin:
        return []
    results = []
    for nid, node in _candidate_nodes(city_map, origin, radius_km):
        if nid == origin["id"]:
            continue
        dist = _euclidean_distance_km(origin, node)
        if dist <= radius_km:
            results.append({"node": nid, "distance_km": round(dist, 3)})
    results.sort(key=lambda x: x["distance_km"])
    return results


def nodes_by_category(city_map, category):
    """Return all node IDs matching a given category."""
    nodes = city_map.get("nodes", {})
    cat = category.lower().strip()
    return [nid for nid, node in nodes.items() if node.get("category", "").lower() == cat]


def nearest_by_category(city_map, node_id, category, top_k=3):
    """Find the closest *top_k* nodes of a given category to *node_id*.

    Returns list of (node_id, distance_km) tuples, sorted by distance.
    """
    nodes = city_map.get("nodes", {})
    origin = nodes.get(_slug(node_id))
    if not origin:
        return []
    cat = category.lower().strip()
    candidates = []
    # 50 km radius comfortably covers any single-city map while still letting
    # the spatial index prune; falls back to full scan when no index.
    for nid, node in _candidate_nodes(city_map, origin, 50.0):
        if nid == origin["id"]:
            continue
        if node.get("category", "").lower() != cat:
            continue
        dist = _euclidean_distance_km(origin, node)
        candidates.append((nid, round(dist, 3)))
    candidates.sort(key=lambda x: x[1])
    return candidates[:top_k]


def area_price_level(city_map, node_id):
    """Return the consumption price-level multiplier for the area around *node_id*.

    Commerce / transit zones are pricier; industrial / education zones cheaper.
    """
    nodes = city_map.get("nodes", {})
    node = nodes.get(_slug(node_id))
    if not node:
        return 1.0
    category = node.get("category", "mixed")
    return AREA_PRICE_LEVEL.get(category, 1.0)


def area_price_level_by_name(city_map, location_name):
    """Convenience wrapper — look up price level by location name string."""
    node = node_by_name(city_map, location_name)
    if not node:
        return 1.0
    return AREA_PRICE_LEVEL.get(node.get("category", "mixed"), 1.0)


# ===================================================================
# ACTIVITY → CATEGORY MAPPING (for generic location resolution)
# ===================================================================

ACTIVITY_CATEGORY_MAP = {
    # activity keywords → preferred location categories, ordered by priority
    "工作":      ["commerce", "industry", "government"],
    "上班":      ["commerce", "industry", "government"],
    "加班":      ["commerce", "industry"],
    "开会":      ["commerce", "government"],
    "学习":      ["education"],
    "上课":      ["education"],
    "实验":      ["education", "industry"],
    "看病":      ["medical"],
    "医院":      ["medical"],
    "诊所":      ["medical"],
    "体检":      ["medical"],
    "健身":      ["leisure"],
    "锻炼":      ["leisure"],
    "晨练":      ["leisure"],
    "散步":      ["leisure", "residential"],
    "运动":      ["leisure"],
    "买菜":      ["commerce"],
    "购物":      ["commerce"],
    "逛街":      ["commerce"],
    "市场":      ["commerce"],
    "外卖":      ["commerce", "residential"],
    "电影":      ["leisure", "commerce"],
    "娱乐":      ["leisure", "commerce"],
    "休闲":      ["leisure"],
    "聚会":      ["leisure", "commerce"],
    "旅行":      ["leisure", "transit"],
    "通勤":      ["transit"],
    "出行":      ["transit"],
    "吃饭":      ["commerce", "residential"],
    "午饭":      ["commerce", "residential"],
    "晚饭":      ["commerce", "residential"],
    "咖啡":      ["commerce", "leisure"],
    "阅读":      ["education", "leisure"],
    "图书馆":    ["education"],
    "接送":      ["education", "residential"],
}

# Job keywords → workplace category preferences
JOB_WORKPLACE_CATEGORIES = {
    "学生":  ["education"],
    "硕士":  ["education"],
    "博士":  ["education"],
    "教师":  ["education"],
    "教授":  ["education"],
    "医生":  ["medical"],
    "护士":  ["medical"],
    "医疗":  ["medical"],
    "程序":  ["commerce", "industry"],
    "研发":  ["industry", "commerce"],
    "工程":  ["industry", "commerce"],
    "算法":  ["commerce", "industry"],
    "产品":  ["commerce"],
    "设计":  ["commerce"],
    "金融":  ["commerce"],
    "银行":  ["commerce"],
    "证券":  ["commerce"],
    "财务":  ["commerce"],
    "律师":  ["commerce", "government"],
    "公务":  ["government"],
    "警察":  ["government"],
    "消防":  ["government"],
    "物流":  ["industry"],
    "仓储":  ["industry"],
    "配送":  ["industry", "commerce"],
    "快递":  ["industry", "commerce"],
    "销售":  ["commerce"],
    "客服":  ["commerce"],
    "运营":  ["commerce"],
    "行政":  ["commerce", "government"],
    "退休":  ["residential", "leisure"],
    "无业":  ["residential"],
    "待业":  ["residential"],
    "失业":  ["residential"],
    "自由":  ["residential", "commerce"],
}


def activity_to_categories(activity_text):
    """Map an activity description to a list of preferred location categories."""
    text = str(activity_text or "")
    categories = []
    for keyword, cats in ACTIVITY_CATEGORY_MAP.items():
        if keyword in text:
            for c in cats:
                if c not in categories:
                    categories.append(c)
    return categories if categories else ["mixed"]


def job_to_workplace_categories(job_text):
    """Map a job description to workplace category preferences."""
    text = str(job_text or "")
    categories = []
    for keyword, cats in JOB_WORKPLACE_CATEGORIES.items():
        if keyword in text:
            for c in cats:
                if c not in categories:
                    categories.append(c)
    return categories if categories else ["commerce"]


def resolve_best_location(city_map, current_node_id, categories, top_k=5,
                          max_radius_km=15.0, prefer_closer=True, rng=None):
    """Find the best location matching any of the given categories.

    Searches outward from *current_node_id*, preferring closer nodes.
    Returns a list of (node_id, distance_km) candidates.

    *rng* may be a ``random.Random`` (or seed-bearing object) to make the
    non-``prefer_closer`` weighted sampling reproducible; defaults to the
    module ``random`` for backward compatibility.
    """
    nodes = city_map.get("nodes", {})
    origin = nodes.get(_slug(current_node_id)) or node_by_name(city_map, current_node_id)
    if not origin:
        return []

    candidates = []
    cat_set = set(c.lower().strip() for c in categories)
    for nid, node in _candidate_nodes(city_map, origin, max_radius_km):
        if nid == origin["id"]:
            continue
        if node.get("category", "").lower() not in cat_set:
            continue
        dist = _euclidean_distance_km(origin, node)
        if dist <= max_radius_km:
            candidates.append((nid, round(dist, 3)))

    if prefer_closer:
        candidates.sort(key=lambda x: x[1])
    else:
        # Weighted random: closer nodes have higher weight
        import random as _rnd
        rng = rng or _rnd
        rng.shuffle(candidates)
        candidates.sort(key=lambda x: x[1] + rng.uniform(0, x[1] * 0.5))

    return candidates[:top_k]


# ===================================================================
# DYNAMIC RUNTIME STATE (for the upper-layer simulation)
# ===================================================================

def _time_to_min(time_str):
    """Parse ``"HH:MM"`` to minutes-from-midnight, or None."""
    if not isinstance(time_str, str):
        return None
    parts = time_str.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, TypeError):
        return None


def _edge_key(a, b):
    return "||".join(sorted([_slug(a), _slug(b)]))


def _runtime(city_map):
    return city_map.setdefault(
        "runtime", {"edge_congestion": {}, "node_occupancy": {}, "time_min": None}
    )


def set_edge_congestion(city_map, a, b, factor):
    """Set a travel-time multiplier on the edge between two nodes (>=0.1)."""
    _runtime(city_map)["edge_congestion"][_edge_key(a, b)] = max(0.1, float(factor))


def get_edge_congestion(city_map, a, b):
    return float(_runtime(city_map)["edge_congestion"].get(_edge_key(a, b), 1.0))


def clear_congestion(city_map):
    _runtime(city_map)["edge_congestion"] = {}


def set_node_occupancy(city_map, node_id, count):
    _runtime(city_map)["node_occupancy"][_slug(node_id)] = max(0, int(count))


def add_node_occupancy(city_map, node_id, delta=1):
    """Increment (or decrement) a node's occupancy, clamped at 0. Returns new value."""
    occ = _runtime(city_map)["node_occupancy"]
    key = _slug(node_id)
    occ[key] = max(0, occ.get(key, 0) + int(delta))
    return occ[key]


def get_node_occupancy(city_map, node_id):
    return int(_runtime(city_map)["node_occupancy"].get(_slug(node_id), 0))


def occupancy_ratio(city_map, node_id):
    """Current occupancy / capacity for a node (0.0 when unknown)."""
    node = node_by_name(city_map, node_id)
    if not node:
        return 0.0
    cap = max(1, int(node.get("capacity", 1) or 1))
    return round(get_node_occupancy(city_map, node_id) / cap, 3)


def set_sim_time(city_map, time_str):
    _runtime(city_map)["time_min"] = _time_to_min(time_str)


def is_open(city_map, node_id, time_str):
    """Whether a place is open at ``HH:MM``. Always-open when hours unset."""
    node = node_by_name(city_map, node_id)
    if not node:
        return False
    open_min = node.get("open_min")
    close_min = node.get("close_min")
    if open_min is None and close_min is None:
        return True
    t = _time_to_min(time_str)
    if t is None:
        return True
    lo = 0 if open_min is None else int(open_min)
    hi = 24 * 60 if close_min is None else int(close_min)
    if hi <= lo:  # overnight window, e.g. 22:00–06:00
        return t >= lo or t < hi
    return lo <= t < hi


# ===================================================================
# VISUALIZATION OVERLAYS & EXPORTS
# ===================================================================

# Land-use symbol per category for the zone overlay (single chars, uppercase
# so they never collide with the lowercase land-use marks in tile_map terrain).
ZONE_SYMBOL = {
    "residential": "R", "commerce": "C", "education": "E", "medical": "M",
    "industry": "I", "government": "G", "leisure": "L", "transit": "T", "mixed": "X",
}

# Human-readable meaning of every tile_map terrain symbol, for legends.
TERRAIN_LEGEND = {
    ".": "ground", "#": "road", "A": "arterial", "C": "collector", "L": "local",
    "=": "bridge", "~": "water", "*": "forest", "r": "residential", "c": "commerce",
    "e": "education", "m": "medical", "i": "industry", "g": "government",
    "l": "leisure", "t": "transit", "+": "metro", "d": "mixed",
}


def _grid_to_lnglat(grid_x, grid_y):
    x_km = float(grid_x) * KM_PER_GRID_X
    y_km = float(grid_y) * KM_PER_GRID_Y
    return (round(BASE_LNG + x_km * LNG_PER_KM, 6), round(BASE_LAT + y_km * LAT_PER_KM, 6))


def _build_overlays(nodes, bounds, width=72, height=48):
    """Structured land-use + density rasters for richer visualization.

    zone:    nearest-node category per tile → contiguous land-use regions
             (a coarse Voronoi partition that reads like real districts).
    density: built-density gradient mapped to 0..9 per tile, combining each
             tile's nearest-node density (with distance fall-off) and a radial
             lift toward the populated centroid.
    Stored OUTSIDE tile_map so it never bloats the per-frame visualizer output.
    """
    if not nodes or not bounds:
        return {"width": 0, "height": 0, "zone": [], "density": [], "bounds": bounds or {}}
    node_list = list(nodes.values())
    gxs = [float(n["grid_x"]) for n in node_list]
    gys = [float(n["grid_y"]) for n in node_list]
    cats = [ZONE_SYMBOL.get(n["category"], "X") for n in node_list]
    dens = [float(n.get("density", 0.5)) for n in node_list]
    min_x, max_x = bounds["min_x"], bounds["max_x"]
    min_y, max_y = bounds["min_y"], bounds["max_y"]
    span_x = max(1e-6, max_x - min_x)
    span_y = max(1e-6, max_y - min_y)
    cx = sum(gxs) / len(gxs)
    cy = sum(gys) / len(gys)
    max_r = (math.hypot(span_x, span_y) / 2.0) or 1.0
    n = len(node_list)
    zone_rows, density_rows = [], []
    for row in range(height):
        gy = min_y + (row / max(1, height - 1)) * span_y
        zrow, drow = [], []
        for col in range(width):
            gx = min_x + (col / max(1, width - 1)) * span_x
            best_i, best_d = 0, float("inf")
            for i in range(n):
                d = (gxs[i] - gx) ** 2 + (gys[i] - gy) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            zrow.append(cats[best_i])
            falloff = math.exp(-math.sqrt(best_d) / 1.2)
            radial = 1.0 - min(1.0, math.hypot(gx - cx, gy - cy) / max_r)
            val = (dens[best_i] * 0.75 + 0.25) * falloff + 0.15 * radial
            drow.append(str(max(0, min(9, int(round(val * 9))))))
        zone_rows.append("".join(zrow))
        density_rows.append("".join(drow))
    return {
        "width": width, "height": height,
        "zone": zone_rows, "density": density_rows,
        "legend": dict(ZONE_SYMBOL), "bounds": dict(bounds),
    }


def export_geojson(city_map):
    """Export nodes / roads / metro / river as a GeoJSON FeatureCollection (WGS84)."""
    features = []
    nodes = city_map.get("nodes", {})
    for node in nodes.values():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [node.get("lng"), node.get("lat")]},
            "properties": {
                "id": node["id"], "name": node["name"], "kind": node.get("kind"),
                "category": node.get("category"), "district": node.get("district"),
                "popularity": node.get("popularity"), "capacity": node.get("capacity"),
                "style": node.get("style", {}),
            },
        })
    for edge in city_map.get("edges", []):
        a = nodes.get(edge["source"])
        b = nodes.get(edge["target"])
        if not a or not b:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[a["lng"], a["lat"]], [b["lng"], b["lat"]]]},
            "properties": {"kind": "road", "road_type": edge.get("road_type"),
                           "bridge": bool(edge.get("bridge"))},
        })
    for line in city_map.get("metro_lines", []):
        coords = [[n["lng"], n["lat"]] for n in
                  (nodes.get(s) for s in line.get("stops", [])) if n]
        if len(coords) >= 2:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"kind": "metro", "line": line.get("name"),
                               "color": line.get("color")},
            })
    river = city_map.get("river") or {}
    bounds = city_map.get("bounds") or {}
    if river.get("path") and bounds:
        coords = [list(_grid_to_lnglat(gx, gy)) for gx, gy in _river_polyline(bounds, river)]
        if len(coords) >= 2:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"kind": "river", "name": river.get("name"),
                               "width": river.get("width")},
            })
    return {"type": "FeatureCollection", "features": features}


def build_visualization_payload(city_map):
    """A single rich, load-once bundle for front-ends / web maps.

    Deliberately heavier than the per-frame layout the live visualizer writes;
    call once to drive a static or interactive map view."""
    nodes = []
    for node in city_map.get("nodes", {}).values():
        nodes.append({
            "id": node["id"], "name": node["name"], "kind": node.get("kind"),
            "category": node.get("category"), "district": node.get("district"),
            "grid_x": node.get("grid_x"), "grid_y": node.get("grid_y"),
            "lat": node.get("lat"), "lng": node.get("lng"),
            "popularity": node.get("popularity"), "density": node.get("density"),
            "capacity": node.get("capacity"), "style": node.get("style", {}),
        })
    return {
        "nodes": nodes,
        "edges": city_map.get("edges", []),
        "metro_lines": city_map.get("metro_lines", []),
        "river": city_map.get("river", {}),
        "bridges": city_map.get("bridges", []),
        "tile_map": city_map.get("tile_map", {}),
        "overlays": city_map.get("overlays", {}),
        "terrain_legend": TERRAIN_LEGEND,
        "category_style": CATEGORY_STYLE,
        "bounds": city_map.get("bounds", {}),
        "scale": city_map.get("scale", {}),
        "geojson": export_geojson(city_map),
    }


# ===================================================================
# SERIALIZATION (save / load without re-parsing the source spec)
# ===================================================================

_SERIALIZABLE_KEYS = (
    "nodes", "edges", "metro_lines", "river", "bridges",
    "tile_map", "bounds", "scale", "interiors", "runtime",
)


def serialize_city_map(city_map):
    """Return a JSON-safe dict of the map's persistent state.

    Derived structures (adjacency / indices / overlays) are omitted and rebuilt
    on load; runtime congestion & occupancy ARE preserved."""
    core = {k: city_map.get(k) for k in _SERIALIZABLE_KEYS if k in city_map}
    return json.loads(json.dumps(core, ensure_ascii=False))


def deserialize_city_map(data):
    """Rebuild a fully-functional city_map from ``serialize_city_map`` output."""
    city_map = dict(data or {})
    city_map.pop("adjacency", None)  # force a clean rebuild
    _attach_derived(city_map)
    return city_map


def save_city_map(city_map, path):
    """Write a city_map to JSON. Returns the path."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialize_city_map(city_map), f, ensure_ascii=False, indent=2)
    return path


def load_city_map_json(path):
    """Load a city_map previously written with ``save_city_map``."""
    path = _resolve_existing_path(path)
    with open(path, "r", encoding="utf-8") as f:
        return deserialize_city_map(json.load(f))


def load_city_map_cached(map_path, cache_path=None):
    """Load a map, using a JSON cache beside the source when it is fresh.

    Rebuilds from the source spec when no cache exists or the source is newer,
    then refreshes the cache — speeds up repeated runs over the same map."""
    src = _resolve_existing_path(map_path)
    if cache_path is None:
        cache_path = str(Path(src).with_suffix(".citymap.json"))
    try:
        if os.path.exists(cache_path) and os.path.getmtime(cache_path) >= os.path.getmtime(src):
            return load_city_map_json(cache_path)
    except OSError:
        pass
    city_map = load_city_map(src)
    try:
        save_city_map(city_map, cache_path)
    except OSError:
        pass
    return city_map


# ===================================================================
# REAL MAP MODE (OpenStreetMap-derived, grounded on real geography)
# ===================================================================
#
# The virtual map above lays nodes on a synthetic grid and *projects* them onto
# fake lat/lng around Hangzhou's centre.  The real-map loader does the inverse:
# it takes real POIs / metro / river with true lat/lng (an offline OSM bundle,
# see ``scripts/dev/fetch_hangzhou_osm.py``) and materialises the SAME
# ``city_map`` structure — so routing, distance, transport, spatial queries and
# the visualizer all work unchanged, but on true geography.

# Chinese labels for the category summary surfaced to LLM prompts.
CATEGORY_LABEL_ZH = {
    "residential": "居住区", "commerce": "商业区", "education": "教育区",
    "medical": "医疗区", "industry": "产业区", "government": "行政区",
    "leisure": "休闲区", "transit": "交通枢纽", "mixed": "综合区",
}


def _lnglat_to_grid(lng, lat, origin=None):
    """Inverse of the grid→lat/lng projection: map real WGS84 to grid units.

    The forward projection lives in ``_make_node_from_spec`` /
    ``_grid_to_lnglat``; keeping this its exact inverse means a real node's
    recomputed lat/lng round-trips back to (within rounding) its true value."""
    base_lat, base_lng, lat_per_km, lng_per_km = _origin_params(origin)
    x_km = (float(lng) - base_lng) / lng_per_km
    y_km = (float(lat) - base_lat) / lat_per_km
    return x_km / KM_PER_GRID_X, y_km / KM_PER_GRID_Y


def _real_road_network(nodes):
    """Synthesize a hierarchical road network over real node coordinates.

    Real POIs are not themselves a routable street graph, so we build a
    plausible one grounded on their true positions: an arterial backbone
    (MST + a few loops) between the designated hubs, then each smaller place
    linked to its nearest hub (collector) and nearest neighbour (short local
    street).  Mirrors the virtual map's hub/place hierarchy."""
    ids = list(nodes.keys())
    hub_ids = [nid for nid in ids if nodes[nid].get("kind") == "hub"]
    if len(hub_ids) < 2:
        # No usable hub set — fall back to an MST over every node so the graph
        # is at least fully connected and routable.
        return _dedupe_edges(_connect_hubs(nodes, ids))
    edges = list(_connect_hubs(nodes, hub_ids))
    for nid in ids:
        if nodes[nid].get("kind") == "hub":
            continue
        nearest_hub = min(hub_ids, key=lambda h: _euclidean_distance_km(nodes[nid], nodes[h]))
        edges.append(_make_edge(nid, nearest_hub, "collector"))
        others = [o for o in ids if o != nid]
        if others:
            neighbor = min(others, key=lambda o: _euclidean_distance_km(nodes[nid], nodes[o]))
            if _euclidean_distance_km(nodes[nid], nodes[neighbor]) <= 1.2:
                edges.append(_make_edge(nid, neighbor, "local"))
    return _dedupe_edges(edges)


def _real_river_from_lnglat(nodes, river_spec, origin=None):
    """Build a normalized river dict from real (lng, lat) points.

    ``city_map`` stores ``river.path`` as 0..1 fractions of the map bounds (see
    ``_river_polyline``); we convert real coordinates to grid units, then to
    those fractions using the same bounds every other builder derives."""
    if not river_spec or not river_spec.get("lnglat"):
        return dict(DEFAULT_RIVER)
    bounds = _compute_bounds(nodes)
    span_x = max(1e-6, bounds["max_x"] - bounds["min_x"])
    span_y = max(1e-6, bounds["max_y"] - bounds["min_y"])
    path = []
    for lng, lat in river_spec["lnglat"]:
        gx, gy = _lnglat_to_grid(lng, lat, origin)
        path.append((
            round((gx - bounds["min_x"]) / span_x, 4),
            round((gy - bounds["min_y"]) / span_y, 4),
        ))
    width_km = river_spec.get("width_km")
    if width_km:
        width = float(width_km) / (span_y * KM_PER_GRID_Y)
    else:
        width = DEFAULT_RIVER["width"]
    return {
        "name": river_spec.get("name") or DEFAULT_RIVER["name"],
        "path": path or list(DEFAULT_RIVER["path"]),
        "width": round(max(0.02, min(0.2, width)), 4),
    }


def _build_real_city_map(node_specs, roads=None, metro_lines=None, river_spec=None, origin=None,
                         city=None):
    """Assemble a full ``city_map`` from real-geo node/road/metro/river specs.

    Each node spec carries real grid coords (from ``_lnglat_to_grid``) plus an
    explicit category/kind; everything else reuses the virtual-map builders so
    the output is byte-for-byte the same shape as ``_build_city_map``."""
    nodes = {}
    for spec in node_specs:
        node = _make_node_from_spec(
            spec.get("name"), spec,
            default_kind=spec.get("kind", "place"),
            default_district=spec.get("district", spec.get("name")),
            default_x=spec.get("x", 0.0),
            default_y=spec.get("y", 0.0),
            default_parent=spec.get("parent", ""),
            origin=origin,
        )
        nodes.setdefault(node["id"], node)  # first occurrence wins (OSM dupes)

    road_edges = _normalize_explicit_roads(nodes, roads or [])
    if not road_edges:
        road_edges = _real_road_network(nodes)
    road_edges = _dedupe_edges(road_edges)

    metro = _normalize_metro_lines(nodes, metro_lines or [])
    river = _real_river_from_lnglat(nodes, river_spec, origin)
    bridges = _detect_bridges(nodes, road_edges, river)
    tile_map = _build_tile_map(nodes, road_edges, river=river, metro_lines=metro, bridges=bridges)
    city_map = {
        "nodes": nodes,
        "edges": road_edges,
        "metro_lines": metro,
        "river": river,
        "bridges": bridges,
        "tile_map": tile_map,
        "bounds": _compute_bounds(nodes),
        "scale": {"km_per_grid_x": KM_PER_GRID_X, "km_per_grid_y": KM_PER_GRID_Y},
        "interiors": {},
        "meta": {"mode": "real", "source": "OpenStreetMap", "city": city or "",
                 "origin": dict(origin) if origin else None},
    }
    _attach_derived(city_map)
    return city_map


def _parse_real_bundle(data):
    """Parse a real-map bundle into (node_specs, roads, metro_lines, river_spec, origin).

    Accepts a GeoJSON ``FeatureCollection`` (same schema as ``export_geojson``,
    with a few extra properties) or a plain ``{"nodes", "metro_lines",
    "river"}`` dict.  Point features become nodes; ``kind=metro/river/road``
    LineStrings become the respective overlays."""
    node_specs, roads, metro_lines, river_spec = [], [], [], None

    origin = (data.get("meta") or {}).get("origin") if isinstance(data, dict) else None

    def _node_from_lnglat(lng, lat, props):
        name = _slug(props.get("name") or props.get("id"))
        if not name or lng is None or lat is None:
            return None
        gx, gy = _lnglat_to_grid(lng, lat, origin)
        return {
            "name": name, "x": gx, "y": gy,
            "kind": props.get("kind", "place"),
            "category": props.get("category") or infer_category(name),
            "district": props.get("district", name),
            "capacity": props.get("capacity"),
            "open": props.get("open"), "close": props.get("close"),
            "popularity": props.get("popularity"), "density": props.get("density"),
        }

    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        for feat in data.get("features", []):
            geom = feat.get("geometry") or {}
            props = feat.get("properties") or {}
            gtype = geom.get("type")
            coords = geom.get("coordinates") or []
            if gtype == "Point" and len(coords) >= 2:
                spec = _node_from_lnglat(coords[0], coords[1], props)
                if spec:
                    node_specs.append(spec)
            elif gtype == "LineString":
                kind = props.get("kind")
                if kind == "metro":
                    metro_lines.append({
                        "name": _slug(props.get("line") or props.get("name")),
                        "color": props.get("color", "#8f5bd8"),
                        "stops": [_slug(s) for s in (props.get("stops") or [])],
                    })
                elif kind == "river":
                    river_spec = {
                        "name": _slug(props.get("name") or DEFAULT_RIVER["name"]),
                        "lnglat": [(c[0], c[1]) for c in coords if len(c) >= 2],
                        "width_km": props.get("width_km"),
                    }
                elif kind == "road":
                    src, tgt = _slug(props.get("source", "")), _slug(props.get("target", ""))
                    if src and tgt:
                        roads.append({"source": src, "target": tgt,
                                      "road_type": props.get("road_type", "arterial"),
                                      "bridge": bool(props.get("bridge", False))})
    else:
        for n in (data.get("nodes") or []):
            spec = _node_from_lnglat(n.get("lng"), n.get("lat"), n)
            if spec:
                node_specs.append(spec)
        for line in (data.get("metro_lines") or []):
            metro_lines.append({
                "name": _slug(line.get("name")),
                "color": line.get("color", "#8f5bd8"),
                "stops": [_slug(s) for s in (line.get("stops") or [])],
            })
        river = data.get("river")
        if river and river.get("lnglat"):
            river_spec = {"name": _slug(river.get("name") or DEFAULT_RIVER["name"]),
                          "lnglat": [(c[0], c[1]) for c in river["lnglat"] if len(c) >= 2],
                          "width_km": river.get("width_km")}
    return node_specs, roads, metro_lines, river_spec, origin


def load_real_city_map(path):
    """Load a real (OSM-derived) offline bundle and build a full ``city_map``.

    The bundle is produced by ``scripts/dev/fetch_hangzhou_osm.py`` and committed
    for offline / reproducible runs.  Raises ``FileNotFoundError`` with guidance
    when the bundle is missing so a mis-set ``map_mode`` fails loudly."""
    resolved = _resolve_existing_path(path)
    if not os.path.exists(resolved):
        raise FileNotFoundError(
            f"Real-map bundle not found at {path!r}. Generate it with "
            "`python3 scripts/dev/fetch_hangzhou_osm.py`, or set map_mode='virtual'."
        )
    with open(resolved, "r", encoding="utf-8") as f:
        data = json.load(f)
    node_specs, roads, metro_lines, river_spec, origin = _parse_real_bundle(data)
    return _build_real_city_map(node_specs, roads=roads, metro_lines=metro_lines,
                                river_spec=river_spec, origin=origin,
                                city=(data.get("meta") or {}).get("city"))


def real_city_map_text(city_map):
    """A concise, human-readable summary of a real map for LLM prompt context.

    The virtual map ships a hand-written ``.md`` spec; a real map has none, so
    we synthesize an equivalent overview (landmarks by category + metro lines)."""
    nodes = city_map.get("nodes", {})
    by_cat = defaultdict(list)
    for node in nodes.values():
        by_cat[node.get("category", "mixed")].append(node.get("name"))
    city_label = str((city_map.get("meta") or {}).get("city") or "").strip()
    lines = [f"# 真实{city_label}地图 (OpenStreetMap)" if city_label else "# 真实地图 (OpenStreetMap)"]
    for cat, names in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        label = CATEGORY_LABEL_ZH.get(cat, cat)
        sample = "、".join(names[:8])
        extra = f" 等{len(names)}处" if len(names) > 8 else ""
        lines.append(f"- {label}: {sample}{extra}")
    for line in city_map.get("metro_lines", []):
        stops = " → ".join(line.get("stops", [])[:12])
        lines.append(f"- 地铁{line.get('name')}: {stops}")
    river = city_map.get("river") or {}
    if river.get("name"):
        lines.append(f"- 河流: {river['name']}")
    return "\n".join(lines)
