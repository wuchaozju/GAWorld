import argparse
import random
import re
from typing import Dict, List, Optional


def _parse_population(description: str) -> Optional[int]:
    if not description:
        return None
    text = description.lower().replace(",", "")
    match = re.search(r"(\d+)(\s*)(k|m|million|thousand)?", text)
    if not match:
        return None
    number = int(match.group(1))
    suffix = match.group(3)
    if not suffix:
        return number
    if suffix in ("k", "thousand"):
        return number * 1000
    if suffix in ("m", "million"):
        return number * 1_000_000
    return number


def _size_from_description(description: str, population: Optional[int]) -> str:
    if population is not None:
        if population < 2_000:
            return "tiny"
        if population < 20_000:
            return "small"
        if population < 200_000:
            return "medium"
        if population < 1_000_000:
            return "large"
        return "metro"
    text = (description or "").lower()
    if "village" in text or "tiny" in text:
        return "tiny"
    if "small" in text:
        return "small"
    if "large" in text or "big" in text:
        return "large"
    if "metro" in text or "metropolitan" in text:
        return "metro"
    return "medium"


def _city_name_from_description(description: str, size: str, rng: random.Random) -> str:
    text = (description or "").lower()
    prefix_pool = ["Riverside", "Lakeside", "Willow", "Pine", "Stonebridge", "Maple", "Harbor"]
    if "east" in text:
        prefix_pool += ["Eastfield", "Eastbay", "Eastgate"]
    if "west" in text:
        prefix_pool += ["Westfield", "Westbay", "Westgate"]
    if "north" in text:
        prefix_pool += ["Northgate", "Northpoint"]
    if "south" in text:
        prefix_pool += ["Southgate", "Southport"]
    if "coast" in text or "sea" in text or "harbor" in text:
        prefix_pool += ["Seaside", "Harborview", "Bayview"]

    suffix = "Village" if size == "tiny" else "Town" if size in ("tiny", "small") else "City"
    return f"{rng.choice(prefix_pool)} {suffix}"


def _block_code(name: str) -> str:
    for word in name.split():
        if len(word) > 0:
            return word[0].upper()
    return "B"


def _make_residential_block(name: str, rng: random.Random) -> Dict:
    block_code = _block_code(name)
    buildings = rng.randint(2, 3)
    nearby = []
    for idx in range(1, buildings + 1):
        building_code = f"{block_code}-{idx:02d}"
        floors = rng.randint(2, 4)
        flats = rng.randint(2, 3)
        nearby.append({
            "building": f"Building {building_code}",
            "floors": floors,
            "flats": flats,
        })
    nearby.append("Neighborhood Clinic")
    nearby.append("Pocket Park")
    return {"hub": name, "nearby": nearby}


def _make_simple_hub(name: str, items: List[str]) -> Dict:
    return {"hub": name, "nearby": items}


def _public_pool(name: str, rng: random.Random) -> List[str]:
    pools = {
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
        "Financial District": [
            "Finance Plaza",
            "Riverside Tower",
            "Insurance Center",
            "Business Hotel",
        ],
        "Old Town": [
            "Old Town Market",
            "Heritage Street",
            "Temple Square",
            "Tea House Alley",
            "City Museum",
        ],
        "Waterfront": [
            "Riverside Port",
            "Marina Pier",
            "Riverfront Promenade",
            "Boathouse",
        ],
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
        "City Hall": [
            "Civic Square",
            "Public Services Center",
            "Archives Building",
            "Courthouse",
        ],
        "Medical Center": [
            "General Hospital",
            "Emergency Department",
            "Pediatrics Department",
            "Pharmacy",
        ],
        "Tech Park": [
            "R&D Center",
            "Innovation Hub",
            "Admin Office",
            "Startup Incubator",
        ],
        "Stadium": [
            "Stadium Plaza",
            "Aquatic Center",
            "Training Grounds",
            "Sports Clinic",
        ],
        "Logistics Hub": [
            "Freight Station",
            "Cold Storage Facility",
            "Sorting Center",
            "Truck Stop",
        ],
        "Greenbelt Corridor": [
            "Eco Trail",
            "Wetland Reserve",
            "Botanical Garden",
            "Outdoor Amphitheater",
        ],
        "Riverside Park": [
            "Riverwalk",
            "Playground",
            "Fitness Area",
            "Picnic Lawn",
        ],
        "Night Market": [
            "Food Street",
            "Open Air Bazaar",
            "Corner Mart",
            "Cinema Alley",
        ],
    }
    if name in pools:
        return pools[name]
    generic = [
        "Community Center",
        "Public Library",
        "Supermart",
        "Bus Station",
        "Cafe Street",
        "Police Station",
    ]
    rng.shuffle(generic)
    return generic[:4]


def generate_citymap(description: str, seed: Optional[int] = None) -> str:
    rng = random.Random(seed)
    population = _parse_population(description)
    size = _size_from_description(description, population)
    city_name = _city_name_from_description(description, size, rng)

    size_to_total = {"tiny": 6, "small": 9, "medium": 13, "large": 18, "metro": 24}
    size_to_blocks = {"tiny": 3, "small": 4, "medium": 5, "large": 6, "metro": 7}
    total_hubs = size_to_total[size]
    block_count = size_to_blocks[size]

    residential_blocks = [
        "Central Block",
        "North Block",
        "South Block",
        "East Block",
        "West Block",
        "Lake Block",
        "Hill Block",
    ]
    rng.shuffle(residential_blocks)
    residential_blocks = residential_blocks[:block_count]

    hub_pool = [
        "Old Town",
        "Riverside Park",
        "Night Market",
        "University District",
        "Industrial Park",
        "Financial District",
        "City Hall",
        "Central Station",
        "Waterfront",
        "Medical Center",
        "Tech Park",
        "Stadium",
        "Logistics Hub",
        "Greenbelt Corridor",
        "Airport District",
    ]
    rng.shuffle(hub_pool)
    other_hubs = hub_pool[: max(0, total_hubs - len(residential_blocks))]

    hubs = []
    for name in residential_blocks:
        hubs.append(_make_residential_block(name, rng))
    for name in other_hubs:
        hubs.append(_make_simple_hub(name, _public_pool(name, rng)))

    lines = ["# City Map", ""]
    river_points = ["0.05,0.24", "0.18,0.30", "0.38,0.27", "0.56,0.33", "0.78,0.28", "0.95,0.35"]
    lines.append(f"@river: {city_name} River | path={';'.join(river_points)} | width=0.08")
    total = len(hubs)
    cols = max(3, int(total ** 0.5) + 1)
    hub_positions = {}
    for idx, hub in enumerate(hubs):
        row = idx // cols
        col = idx % cols
        x = 2.5 + col * 3.1
        y = 3.2 + row * 2.6
        hub_positions[hub["hub"]] = (x, y)
        category = "residential" if "Block" in hub["hub"] else "transit" if "Station" in hub["hub"] or "Airport" in hub["hub"] else "mixed"
        lines.append(f"@node: {hub['hub']} | kind=hub | district={hub['hub']} | category={category} | x={x:.1f} | y={y:.1f}")
    ordered_hubs = [hub["hub"] for hub in hubs]
    for idx in range(len(ordered_hubs) - 1):
        lines.append(f"@road: {ordered_hubs[idx]} -> {ordered_hubs[idx + 1]} | type=arterial")
    if len(ordered_hubs) >= 5:
        metro_stops = ">".join(ordered_hubs[: min(6, len(ordered_hubs))])
        lines.append(f"@metro: M1 | color=#8f5bd8 | stops={metro_stops}")
    lines.extend(["", f"- City: {city_name}"])
    for hub in hubs:
        lines.append(f"  - Hub: {hub['hub']}")
        for item in hub["nearby"]:
            if isinstance(item, dict) and "building" in item:
                lines.append(f"    - Nearby: {item['building']}")
                floors = int(item.get("floors", 2))
                flats = int(item.get("flats", 2))
                for floor in range(1, floors + 1):
                    lines.append(f"      - Floor: {floor}F")
                    for idx in range(flats):
                        flat_letter = chr(ord("A") + idx)
                        lines.append(f"        - Flat: {floor}{flat_letter}")
            else:
                lines.append(f"    - Nearby: {item}")

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a citymap.md from a text description.")
    parser.add_argument("--description", "-d", required=True, help="Text description of the city.")
    parser.add_argument("--output", "-o", default="data/citymap.md", help="Output path for citymap.md")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--dry-run", action="store_true", help="Print map to stdout instead of writing file")
    args = parser.parse_args()

    content = generate_citymap(args.description, seed=args.seed)
    if args.dry_run:
        print(content)
        return
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    main()
