"""Offline profile calibration from accumulated twin reports (spec channel C).

Aggregates real location and activity history into a habits patch and prints a
human-readable diff. It writes NOTHING unless ``--approve`` is passed.

That gate is the point of the script. Letting collected data silently rewrite
an experimental subject's profile would make later results unattributable: a
run that changed could not be traced to a config change versus an unnoticed
profile drift.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gaworld.twin import store


def aggregate(agent_id, root=store.DEFAULT_ROOT):
    """Summarize an agent's full report history."""
    reports = store.load_reports(agent_id, root=root)
    locations = Counter()
    tags = Counter()
    for record in reports:
        node_id = record.get("node_id")
        if node_id:
            locations[str(node_id)] += 1
        tags[str(record.get("action_tag", "other"))] += 1
    timestamps = [float(r.get("ts", 0)) for r in reports]
    return {
        "agent_id": int(agent_id),
        "total_reports": len(reports),
        "frequent_locations": dict(locations),
        "action_tags": dict(tags),
        "first_ts": min(timestamps) if timestamps else None,
        "last_ts": max(timestamps) if timestamps else None,
    }


def build_patch(summary, min_occurrences=3):
    """Keep only signals seen often enough to be a habit rather than a one-off."""
    return {
        "agent_id": summary["agent_id"],
        "frequent_locations": {
            name: count
            for name, count in summary["frequent_locations"].items()
            if count >= int(min_occurrences)
        },
        "action_tags": {
            name: count
            for name, count in summary["action_tags"].items()
            if count >= int(min_occurrences)
        },
        "derived_from_reports": summary["total_reports"],
    }


def render_diff(agent_id, patch):
    """Render the patch for a human to read before approving it."""
    lines = [f"Agent {agent_id} — proposed calibration", ""]
    lines.append(f"  derived from {patch.get('derived_from_reports', 0)} reports")
    lines.append("")
    lines.append("  frequent locations:")
    for name, count in sorted(
        patch.get("frequent_locations", {}).items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"    {name}: {count}")
    lines.append("")
    lines.append("  activity tags:")
    for name, count in sorted(patch.get("action_tags", {}).items(), key=lambda kv: -kv[1]):
        lines.append(f"    {name}: {count}")
    return "\n".join(lines)


def apply_patch(agent_id, patch, out_path, approved=False):
    """Write the patch only when explicitly approved. Returns whether it wrote."""
    if not approved:
        return False
    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = dict(patch)
    payload["agent_id"] = int(agent_id)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_id", type=int)
    parser.add_argument("--root", default=store.DEFAULT_ROOT)
    parser.add_argument("--min-occurrences", type=int, default=3)
    parser.add_argument("--out", default="output/twin/calibration.json")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="actually write the patch; without this the script only prints the diff",
    )
    args = parser.parse_args(argv)

    summary = aggregate(args.agent_id, root=args.root)
    if not summary["total_reports"]:
        print(f"Agent {args.agent_id} has no reports; nothing to calibrate.")
        return 1

    patch = build_patch(summary, min_occurrences=args.min_occurrences)
    print(render_diff(args.agent_id, patch))
    print("")

    if apply_patch(args.agent_id, patch, args.out, approved=args.approve):
        print(f"Written to {args.out}")
    else:
        print("Dry run. Re-run with --approve to write this patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
