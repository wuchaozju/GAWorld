"""Generate a ``citymap.md`` spec from a place name, without a network.

The fallback path for :func:`gaworld.city.create.create_city`: when OSM has
nothing usable (a hamlet, a fictional name, or simply no connectivity) we still
have to produce a believable city.  The layout is derived deterministically
from the place name, so the same name always yields the same city.

Hub and place names stay in English structural form ("Central Block",
"Riverside Park") because :func:`gaworld.world.city_map.infer_category` keys
off English keywords to classify any node whose category is not declared — the
committed ``data/citymap.md`` follows the same convention.  Only the city
itself and its river carry the real place name.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

#: Total hubs and residential blocks per scale.
SCALE_LAYOUT = {
    "tiny": {"hubs": 6, "blocks": 3, "metro": False},
    "small": {"hubs": 9, "blocks": 4, "metro": False},
    "medium": {"hubs": 13, "blocks": 5, "metro": True},
    "large": {"hubs": 18, "blocks": 6, "metro": True},
    "metro": {"hubs": 24, "blocks": 7, "metro": True},
}

RESIDENTIAL_BLOCKS = (
    "Central Block",
    "North Block",
    "South Block",
    "East Block",
    "West Block",
    "Lake Block",
    "Hill Block",
)

#: Non-residential hubs, each with the category the map layer should use.
HUB_CATALOG: dict[str, str] = {
    "Old Town": "commerce",
    "Night Market": "commerce",
    "Financial District": "commerce",
    "Riverside Park": "leisure",
    "Greenbelt Corridor": "leisure",
    "Stadium": "leisure",
    "Waterfront": "leisure",
    "University District": "education",
    "Medical Center": "medical",
    "City Hall": "government",
    "Central Station": "transit",
    "Airport District": "transit",
    "Industrial Park": "industry",
    "Logistics Hub": "industry",
    "Tech Park": "commerce",
}

#: Small places clustered around each non-residential hub.
PLACE_POOL: dict[str, list[str]] = {
    "University District": [
        "Main Library",
        "Engineering Building",
        "Arts Building",
        "Dormitory A",
        "Dormitory B",
        "Student Canteen",
    ],
    "Industrial Park": [
        "Manufacturing Zone A",
        "Manufacturing Zone B",
        "Logistics Yard",
        "Power Substation",
        "Freight Depot",
    ],
    "Financial District": ["Finance Plaza", "Riverside Tower", "Insurance Center", "Business Hotel"],
    "Old Town": ["Old Town Market", "Heritage Street", "Temple Square", "Tea House Alley", "City Museum"],
    "Waterfront": ["Riverside Port", "Marina Pier", "Riverfront Promenade", "Boathouse"],
    "Central Station": [
        "High Speed Rail Terminal",
        "Metro Concourse",
        "Taxi Loop",
        "Intercity Bus Terminal",
    ],
    "Airport District": [
        "International Airport",
        "Airport Cargo Terminal",
        "Airport Hotel",
        "Air Traffic Control",
    ],
    "City Hall": ["Civic Square", "Public Services Center", "Archives Building", "Courthouse"],
    "Medical Center": ["General Hospital", "Emergency Department", "Pediatrics Department", "Pharmacy"],
    "Tech Park": ["R&D Center", "Innovation Hub", "Admin Office", "Startup Incubator"],
    "Stadium": ["Stadium Plaza", "Aquatic Center", "Training Grounds", "Sports Clinic"],
    "Logistics Hub": ["Freight Station", "Cold Storage Facility", "Sorting Center", "Truck Stop"],
    "Greenbelt Corridor": ["Eco Trail", "Wetland Reserve", "Botanical Garden", "Outdoor Amphitheater"],
    "Riverside Park": ["Riverwalk", "Playground", "Fitness Area", "Picnic Lawn"],
    "Night Market": ["Food Street", "Open Air Bazaar", "Corner Mart", "Cinema Alley"],
}

GENERIC_PLACES = (
    "Community Center",
    "Public Library",
    "Supermart",
    "Bus Station",
    "Cafe Street",
    "Police Station",
)


def seed_from_name(name: str) -> int:
    """A stable seed for *name* — Python's ``hash`` is salted per process."""
    digest = hashlib.md5(str(name).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _block_code(name: str) -> str:
    for word in str(name).split():
        if word:
            return word[0].upper()
    return "B"


def _residential_places(hub: str, rng: random.Random) -> list[Any]:
    """Buildings (with interiors) plus two everyday amenities."""
    code = _block_code(hub)
    places: list[Any] = []
    for index in range(1, rng.randint(2, 3) + 1):
        places.append(
            {
                "building": f"Building {code}-{index:02d}",
                "floors": rng.randint(2, 4),
                "flats": rng.randint(2, 3),
            }
        )
    places.append("Neighborhood Clinic")
    places.append("Pocket Park")
    return places


def _hub_places(hub: str, rng: random.Random) -> list[str]:
    if hub in PLACE_POOL:
        return list(PLACE_POOL[hub])
    generic = list(GENERIC_PLACES)
    rng.shuffle(generic)
    return generic[:4]


def generate_citymap(
    place_name: str,
    *,
    scale: str = "medium",
    seed: int | None = None,
    river_name: str | None = None,
) -> str:
    """Render a ``citymap.md`` spec for *place_name*.

    The output is the directive format ``gaworld.world.city_map.load_city_map``
    parses: ``@river`` / ``@node`` / ``@road`` / ``@metro`` header lines, then
    the ``- City: / - Hub: / - Nearby:`` tree.
    """
    name = str(place_name or "").strip() or "Unnamed City"
    rng = random.Random(seed if seed is not None else seed_from_name(name))
    layout = SCALE_LAYOUT.get(scale, SCALE_LAYOUT["medium"])

    blocks = list(RESIDENTIAL_BLOCKS)
    rng.shuffle(blocks)
    blocks = blocks[: layout["blocks"]]

    others = list(HUB_CATALOG)
    rng.shuffle(others)
    others = others[: max(0, layout["hubs"] - len(blocks))]

    hubs: list[dict[str, Any]] = [
        {"name": hub, "category": "residential", "places": _residential_places(hub, rng)}
        for hub in blocks
    ]
    hubs += [
        {"name": hub, "category": HUB_CATALOG[hub], "places": _hub_places(hub, rng)} for hub in others
    ]

    # Lay hubs on a loose grid; the map builder adds its own organic jitter and
    # fills each hub's block, so a regular spacing here is enough.
    cols = max(3, int(len(hubs) ** 0.5) + 1)
    for index, hub in enumerate(hubs):
        hub["x"] = 2.5 + (index % cols) * 3.1
        hub["y"] = 3.2 + (index // cols) * 2.6

    ordered = [hub["name"] for hub in hubs]
    roads = [(source, target, "arterial") for source, target in zip(ordered, ordered[1:])]
    # Close one loop so the arterial network is not a bare chain.
    if len(ordered) >= 4:
        roads.append((ordered[-1], ordered[0], "collector"))

    metro = None
    if layout["metro"] and len(ordered) >= 5:
        metro = {"name": "M1", "stops": ordered[: min(6, len(ordered))]}

    return render_citymap(
        name,
        hubs,
        river={
            "name": river_name or f"{name} River",
            "path": [(0.05, 0.24), (0.18, 0.30), (0.38, 0.27), (0.56, 0.33), (0.78, 0.28), (0.95, 0.35)],
            "width": 0.08,
        },
        roads=roads,
        metro=metro,
    )


def render_citymap(
    city_name: str,
    hubs: list[dict[str, Any]],
    *,
    river: dict[str, Any] | None = None,
    roads: list[tuple[str, str, str]] | None = None,
    metro: dict[str, Any] | None = None,
    place_categories: dict[str, str] | None = None,
) -> str:
    """Render the ``citymap.md`` directive format from an explicit layout.

    Shared by this module's name-seeded generator and by
    :mod:`gaworld.city.imagine`, which builds the same ``hubs`` shape from a
    description instead of from a dice roll — one writer, so a spec an LLM
    designed and a spec the fallback produced can never drift in format.

    ``hubs`` entries are ``{"name", "category", "x", "y", "places"}``; a place
    is either a plain name or ``{"building", "floors", "flats"}`` for one with
    an interior. ``place_categories`` declares what the small places *are*,
    which matters for any spec whose names are not English: the map layer's
    :func:`~gaworld.world.city_map.infer_category` keys off English keywords
    and would otherwise file every 鱼市 and 卫生院 under ``mixed``.
    """
    name = str(city_name or "").strip() or "Unnamed City"
    lines = ["# City Map", ""]

    if river and river.get("path"):
        path = ";".join(f"{float(x):.2f},{float(y):.2f}" for x, y in river["path"])
        width = float(river.get("width") or 0.08)
        lines.append(f"@river: {river.get('name') or f'{name} River'} | path={path} | width={width:g}")

    for hub in hubs:
        lines.append(
            f"@node: {hub['name']} | kind=hub | district={hub['name']} "
            f"| category={hub['category']} | x={float(hub['x']):.1f} | y={float(hub['y']):.1f}"
        )

    # Places carry a category but deliberately no x/y: the loader lays each
    # hub's block itself, and pinning them here would flatten that layout.
    for place_name, category in (place_categories or {}).items():
        lines.append(f"@node: {place_name} | kind=place | category={category}")

    for source, target, road_type in roads or []:
        lines.append(f"@road: {source} -> {target} | type={road_type}")

    if metro and metro.get("stops"):
        stops = ">".join(metro["stops"])
        color = metro.get("color") or "#8f5bd8"
        lines.append(f"@metro: {metro.get('name') or 'M1'} | color={color} | stops={stops}")

    lines += ["", f"- City: {name}"]
    for hub in hubs:
        lines.append(f"  - Hub: {hub['name']}")
        for place in hub["places"]:
            if isinstance(place, dict):
                lines.append(f"    - Nearby: {place['building']}")
                for floor in range(1, int(place["floors"]) + 1):
                    lines.append(f"      - Floor: {floor}F")
                    for flat in range(int(place["flats"])):
                        lines.append(f"        - Flat: {floor}{chr(ord('A') + flat)}")
            else:
                lines.append(f"    - Nearby: {place}")

    return "\n".join(lines).strip() + "\n"


def districts_from_spec(spec: str) -> list[str]:
    """Hub district names declared in a ``citymap.md`` spec, in file order.

    Used to seed the population generator's district weights so residents live
    in districts the city actually has.
    """
    districts: list[str] = []
    for line in spec.splitlines():
        line = line.strip()
        if not line.startswith("@node:") or "kind=hub" not in line:
            continue
        for part in line[len("@node:") :].split("|"):
            key, _, value = part.partition("=")
            if key.strip().lower() == "district" and value.strip():
                districts.append(value.strip())
                break
    return districts


__all__ = [
    "HUB_CATALOG",
    "SCALE_LAYOUT",
    "districts_from_spec",
    "generate_citymap",
    "render_citymap",
    "seed_from_name",
]
