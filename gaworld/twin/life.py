"""Read-only views of what the bound agent is actually living.

The phone was write-only: you fed it your life and got back an avatar and a
dotted line. Everything the simulation produces — the diary it writes, the
mood it carries, the goals it holds — existed on disk but was invisible on
mobile. This module surfaces those four artifacts.

Every artifact is optional. A fresh install has none of them, and a simulation
that has never run produces none, so each reader returns an empty structure
rather than raising.
"""

from __future__ import annotations

import csv
import json
import os
import re


DEFAULT_DIARY_DIR = "output/diaries"
DEFAULT_STATE_DIR = "output/state"
DEFAULT_MEMORY_DIR = "output/memory"

GOAL_TIERS = ("life_goals", "long_term_goals", "short_term_goals")

_DAY_FILE = re.compile(r"^day_(\d+)\.md$")


def latest_diary(agent_id, diary_dir=DEFAULT_DIARY_DIR):
    """The most recent daily diary, by day number rather than mtime."""
    directory = os.path.join(str(diary_dir), f"agent_{int(agent_id)}")
    best_day = None
    best_name = None
    try:
        names = os.listdir(directory)
    except OSError:
        return {"day": None, "text": ""}
    for name in names:
        match = _DAY_FILE.match(name)
        if not match:
            continue
        day = int(match.group(1))
        if best_day is None or day > best_day:
            best_day = day
            best_name = name
    if best_name is None:
        return {"day": None, "text": ""}
    try:
        with open(os.path.join(directory, best_name), "r", encoding="utf-8") as handle:
            return {"day": best_day, "text": handle.read().strip()}
    except OSError:
        return {"day": None, "text": ""}


def latest_state(agent_id, state_dir=DEFAULT_STATE_DIR):
    """Current value of each state metric.

    ``agent_state_history.csv`` is long-format (agent_id, step, metric, value),
    so the current value is the highest-step row per metric.
    """
    path = os.path.join(str(state_dir), "agent_state_history.csv")
    if not os.path.exists(path):
        return {}
    best_step = {}
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    if int(row["agent_id"]) != int(agent_id):
                        continue
                    step = int(row["step"])
                    value = float(row["value"])
                except (KeyError, TypeError, ValueError):
                    # One malformed row should not cost the whole card.
                    continue
                metric = str(row.get("metric", "")).strip()
                if not metric:
                    continue
                if metric not in best_step or step >= best_step[metric]:
                    best_step[metric] = step
                    values[metric] = value
    except OSError:
        return {}
    return values


def active_goals(agent_id, memory_dir=DEFAULT_MEMORY_DIR):
    """Live goals per tier. Completed and abandoned goals are dropped."""
    empty = {tier: [] for tier in GOAL_TIERS}
    path = os.path.join(str(memory_dir), f"agent_{int(agent_id)}_goals.json")
    if not os.path.exists(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(payload, dict):
        return empty
    result = {}
    for tier in GOAL_TIERS:
        items = payload.get(tier)
        result[tier] = [
            {
                "id": item.get("id"),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "domain": item.get("domain", ""),
            }
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and str(item.get("status", "active")) == "active"
        ]
    return result
