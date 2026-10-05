"""Inspect organizations, queue a command, or compare completed metric exports.

No command executes here. Use a subsequent organizations-enabled simulation
to apply the queue at its next day boundary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from gaworld import worlds
from gaworld.accounts import context, ownership
from gaworld.apps import world_paths
from gaworld.organizations.store import OrganizationStore


def _print(payload: Any, *, error: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr if error else sys.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--world", help="Existing local world id (omitted: the configured default city/world)"
    )
    parser.add_argument("--generation", help="Read a historical generation (list/detail/history only)")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("list", help="List persisted organizations")
    detail = commands.add_parser("detail", help="Read identity, account, members, jobs, and applications")
    detail.add_argument("organization_id")
    history = commands.add_parser("history", help="Read applied history")
    history.add_argument("organization_id")
    history.add_argument("--limit", type=int, default=100)
    status = commands.add_parser("status", help="Read a queued command's current status")
    status.add_argument("command_id")
    commands.add_parser("commands", help="List pending and completed commands")
    command = commands.add_parser("command", help="Queue JSON; no direct execution")
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--json-file", help="UTF-8 file containing one command object")
    source.add_argument("--json", help="One JSON command object")
    compare = commands.add_parser("compare", help="Compare two completed local metrics.json exports")
    compare.add_argument("left")
    compare.add_argument("right")
    compare.add_argument("--output-dir", required=True, help="Directory for JSON, CSV and Markdown reports")
    compare.add_argument("--organization-id", help="Select one organization present in both files")
    compare.add_argument("--left-label", default="A")
    compare.add_argument("--right-label", default="B")
    args = parser.parse_args(argv)
    token = None
    store = None
    try:
        if args.action == "compare":
            from gaworld.organizations.comparison import compare_files

            if args.world or args.generation:
                raise ValueError("compare uses explicit file inputs; omit --world and --generation")
            result = compare_files(
                args.left,
                args.right,
                args.output_dir,
                organization_id=args.organization_id,
                left_label=args.left_label,
                right_label=args.right_label,
            )
            _print(result)
            return 0
        if args.world:
            config_path = worlds.config_path(world_paths.REPO_ROOT, args.world)
            if not os.path.isfile(config_path):
                raise ValueError(f"Unknown local world: {args.world}")
            token = context.WORLD.set({"id": args.world})
        if args.generation and args.action not in {"list", "detail", "history"}:
            raise ValueError("--generation is only available for list/detail/history")
        store = OrganizationStore(
            os.path.join(world_paths.memory_base_dir(), "organizations.sqlite"), generation_id=args.generation
        )
        if args.action == "list":
            result = store.list_organizations()
        elif args.action == "commands":
            result = store.commands()
        elif args.action == "status":
            result = store.command(args.command_id)
            if result is None:
                raise ValueError(f"Unknown command: {args.command_id}")
        elif args.action in ("detail", "history"):
            result = store.detail(args.organization_id)
            if result is None:
                raise ValueError(f"Unknown organization: {args.organization_id}")
            if args.action == "history":
                if not 1 <= args.limit <= 1000:
                    raise ValueError("limit must be an integer from 1 to 1000")
                result = store.history(args.organization_id, limit=args.limit)
        else:
            if args.json_file:
                with open(args.json_file, encoding="utf-8") as handle:
                    payload = json.load(handle)
            else:
                payload = json.loads(args.json)
            result = store.enqueue(payload, actor={**ownership.stamp(), "source": "cli"})
        _print(result)
        return 0
    except (ValueError, OSError) as exc:
        _print({"error": str(exc)}, error=True)
        return 2
    finally:
        if store is not None:
            store.close()
        if token is not None:
            context.WORLD.reset(token)


if __name__ == "__main__":
    raise SystemExit(main())
