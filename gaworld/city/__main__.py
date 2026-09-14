"""CLI: ``python -m gaworld.city``.

Examples::

    # create a city from a place name (geocode + real OSM map when reachable)
    python -m gaworld.city create "绍兴柯桥"

    # no network / fictional place: build everything procedurally
    python -m gaworld.city create "Willow Hollow" --offline --scale tiny

    # fill it with people, then add one named resident
    python -m gaworld.city add-agents 绍兴柯桥 --size 200 --preset cn_county_town
    python -m gaworld.city add-agent 绍兴柯桥 --name 林素 --age 34 --job "社区医生"

    # move agent 31 out of the default corpus and into the new city
    python -m gaworld.city migrate 绍兴柯桥 --agent-id 31

    # inspect, then point the simulator at it
    python -m gaworld.city list
    python -m gaworld.city use 绍兴柯桥
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gaworld.city.agents import AgentError, add_agent, add_population, migrate_agent
from gaworld.city.bundle import CityNotFoundError, delete_city, list_cities, resolve_city
from gaworld.city.create import CityCreationError, create_city
from gaworld.city.geocode import SCALE_BBOX_HALF_DEG
from gaworld.population.schema import PRESETS

DEFAULT_SOURCE_CSV = "data/hangzhou_agents_state_init.csv"
DEFAULT_SOURCE_MD = "data/hangzhou_profiles_with_names.md"
DASHBOARD_CONFIG = Path(__file__).resolve().parents[2] / "dashboard_config.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gaworld.city",
        description="Create cities from place names and populate them with agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a city bundle from a place name")
    create.add_argument("name", help="Place name, e.g. '绍兴柯桥' or 'Kyoto'")
    create.add_argument("--slug", help="Directory name to use (defaults to a slug of the place name)")
    create.add_argument("--scale", choices=sorted(SCALE_BBOX_HALF_DEG), help="Override the inferred size")
    create.add_argument("--offline", action="store_true", help="Skip geocoding and OSM; build procedurally")
    create.add_argument("--force", action="store_true", help="Overwrite an existing city with this slug")
    create.add_argument("--seed", type=int, help="Seed for the procedural layout")
    create.add_argument("--size", type=int, help="Also generate this many residents")
    create.add_argument("--preset", choices=sorted(PRESETS), default="cn_county_town")

    listing = sub.add_parser("list", help="List every city bundle")
    listing.add_argument("--json", action="store_true", help="Emit JSON instead of a table")

    show = sub.add_parser("show", help="Show one city's manifest")
    show.add_argument("city")

    population = sub.add_parser("add-agents", help="Bulk-synthesise residents into a city")
    population.add_argument("city")
    population.add_argument("--size", type=int, default=100)
    population.add_argument("--preset", choices=sorted(PRESETS), default="cn_county_town")
    population.add_argument("--seed", type=int)
    population.add_argument("--replace", action="store_true", help="Replace rather than append")

    one = sub.add_parser("add-agent", help="Append a single agent to a city")
    one.add_argument("city")
    one.add_argument("--name", required=True)
    one.add_argument("--age", type=int, required=True)
    one.add_argument("--gender", default="女")
    one.add_argument("--job", default="自由职业")
    one.add_argument("--hukou", default="本地")
    one.add_argument("--education", default="本科")
    one.add_argument("--income", type=float, default=0.0)
    one.add_argument("--residence", help="Defaults to a random district of this city")

    move = sub.add_parser("migrate", help="Move an existing agent into a city")
    move.add_argument("city")
    move.add_argument("--agent-id", type=int, required=True)
    move.add_argument("--from-csv", default=DEFAULT_SOURCE_CSV)
    move.add_argument("--from-md", default=DEFAULT_SOURCE_MD)
    move.add_argument("--from-city", help="Source city slug; overrides --from-csv/--from-md")
    move.add_argument("--keep-residence", action="store_true", help="Do not re-home onto this city")

    use = sub.add_parser("use", help="Point dashboard_config.json at a city")
    use.add_argument("city")
    use.add_argument("--clear", action="store_true", help="Unset the city instead")

    remove = sub.add_parser("delete", help="Delete a city bundle")
    remove.add_argument("city")
    remove.add_argument("--yes", action="store_true", help="Required: confirms the deletion")

    return parser


def _cmd_create(args: argparse.Namespace) -> int:
    city = create_city(
        args.name,
        slug=args.slug,
        scale=args.scale,
        offline=args.offline,
        force=args.force,
        seed=args.seed,
    )
    print(f"✓ created {city.slug} at {city.directory}")
    print(f"  map: {city.map_mode}  scale: {city.manifest.get('scale')}")
    place = city.manifest.get("place") or {}
    print(f"  place: {place.get('display_name')} ({place.get('source')})")
    if args.size:
        result = add_population(city, size=args.size, preset=args.preset, seed=args.seed)
        print(f"  population: {result['total']} residents (seed={result['seed']})")
        if result["added"] != result["requested"]:
            print(f"  note: asked for {result['requested']}; the sampler's range is 20–5000")
    else:
        print(f"  next: python -m gaworld.city add-agents {city.slug} --size 200")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    bundles = list_cities()
    if args.json:
        print(json.dumps([b.summary() for b in bundles], ensure_ascii=False, indent=2))
        return 0
    if not bundles:
        print("no cities yet — create one with: python -m gaworld.city create \"<place name>\"")
        return 0
    print(f"{'SLUG':<24} {'SCALE':<8} {'MAP':<8} {'AGENTS':>6}  NAME")
    for bundle in bundles:
        print(
            f"{bundle.slug:<24} {bundle.manifest.get('scale', '')!s:<8} "
            f"{bundle.map_mode:<8} {bundle.population_count:>6}  {bundle.display_name}"
        )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    print(json.dumps(resolve_city(args.city).manifest, ensure_ascii=False, indent=2))
    return 0


def _cmd_add_agents(args: argparse.Namespace) -> int:
    city = resolve_city(args.city)
    result = add_population(
        city, size=args.size, preset=args.preset, seed=args.seed, replace=args.replace
    )
    print(f"✓ {result['added']} residents added to {city.slug} (total {result['total']})")
    if result["added"] != result["requested"]:
        print(f"  note: asked for {result['requested']}; the sampler's range is 20–5000")
    warnings = [f for f in result["findings"] if f.get("level") in {"warn", "warning"}]
    for finding in warnings[:5]:
        print(f"  ! {finding.get('code')}: {finding.get('message')}")
    return 0


def _cmd_add_agent(args: argparse.Namespace) -> int:
    city = resolve_city(args.city)
    result = add_agent(
        city,
        name=args.name,
        age=args.age,
        gender=args.gender,
        job=args.job,
        hukou=args.hukou,
        education=args.education,
        income_monthly=args.income,
        residence=args.residence,
    )
    print(f"✓ {result['name']} is agent #{result['id']} in {city.slug}, living at {result['residence']}")
    print(f"  {result['total']} agents total")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    city = resolve_city(args.city)
    if args.from_city:
        source = resolve_city(args.from_city)
        source_csv, source_md = source.state_csv_path, source.profiles_md_path
    else:
        source_csv, source_md = Path(args.from_csv), Path(args.from_md)
    result = migrate_agent(
        city,
        args.agent_id,
        source_csv=source_csv,
        source_md=source_md,
        rehome=not args.keep_residence,
    )
    print(f"✓ agent {result['source_id']} ({result['name']}) → #{result['id']} in {city.slug}")
    print(f"  {result['total']} agents total")
    return 0


def _cmd_use(args: argparse.Namespace) -> int:
    config: dict = {}
    if DASHBOARD_CONFIG.exists():
        config = json.loads(DASHBOARD_CONFIG.read_text(encoding="utf-8"))
    if args.clear:
        config.pop("city", None)
        message = "cleared; the simulator will use the default world"
    else:
        bundle = resolve_city(args.city)
        config["city"] = bundle.slug
        message = f"set to {bundle.slug} ({bundle.display_name})"
    DASHBOARD_CONFIG.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"✓ {DASHBOARD_CONFIG.name}: city {message}")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        print("refusing to delete without --yes", file=sys.stderr)
        return 2
    print(f"✓ removed {delete_city(args.city)}")
    return 0


_COMMANDS = {
    "create": _cmd_create,
    "list": _cmd_list,
    "show": _cmd_show,
    "add-agents": _cmd_add_agents,
    "add-agent": _cmd_add_agent,
    "migrate": _cmd_migrate,
    "use": _cmd_use,
    "delete": _cmd_delete,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args)
    except (CityCreationError, CityNotFoundError, AgentError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
