"""Purge fallback-only entries from cached agent action spaces.

An LLM failure during action-space generation used to be silently
absorbed: every activity got the four generic behavioural filler actions
(推进/维持/回避/社交), the result was written to
``output/memory/agent_<id>_actions.json``, and the cache was honoured on
every later run — so the agent stayed stuck with four meaningless actions
forever, and habits accumulated on top of them.

The simulator no longer caches such entries. This script cleans archives
written before that fix: fallback-only activities are dropped, so the next
run regenerates them. Habit entries keyed on a dropped activity are removed
too (their preferred_action no longer exists in the action space).

Usage:
    python scripts/dev/clean_fallback_action_cache.py --dry-run
    python scripts/dev/clean_fallback_action_cache.py --memory-dir output/memory
"""

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gaworld.sim._memory_recall import is_fallback_only_action_list  # noqa: E402


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_agent(actions_path, dry_run=False):
    """Return (agent_id, dropped_activities) for one *_actions.json file."""
    actions = _load(actions_path)
    if actions is None:
        return None, []
    match = re.search(r"agent_(\w+)_actions\.json$", os.path.basename(actions_path))
    agent_id = match.group(1) if match else ""
    dropped = [a for a, acts in actions.items() if is_fallback_only_action_list(a, acts)]
    if not dropped:
        return agent_id, []
    if not dry_run:
        _save(actions_path, {a: acts for a, acts in actions.items() if a not in dropped})
        _clean_habits(os.path.join(os.path.dirname(actions_path), f"agent_{agent_id}_habits.json"), dropped)
    return agent_id, dropped


def _clean_habits(habits_path, dropped_activities):
    habits = _load(habits_path)
    if not habits:
        return
    # Habit keys are "<time_bucket>|<location_bucket>|<activity>".
    kept = {
        key: item
        for key, item in habits.items()
        if key.split("|")[-1] not in set(dropped_activities)
    }
    if len(kept) != len(habits):
        _save(habits_path, kept)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", default="output/memory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.memory_dir, "agent_*_actions.json")))
    if not paths:
        print(f"no action caches under {args.memory_dir}")
        return
    total = 0
    for path in paths:
        agent_id, dropped = clean_agent(path, dry_run=args.dry_run)
        if dropped:
            total += len(dropped)
            print(f"agent {agent_id}: {len(dropped)} 个仅含兜底动作的活动 -> {'、'.join(dropped)}")
    verb = "would drop" if args.dry_run else "dropped"
    print(f"{verb} {total} activity entries across {len(paths)} agents")


if __name__ == "__main__":
    main()
