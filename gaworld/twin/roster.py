"""The list of agents a phone can choose to twin.

Reads the same seed CSV the simulator loads, so the picker always offers
exactly the residents that exist in the selected city — no second source of
truth to drift out of sync.
"""

from __future__ import annotations

import csv
import os


def load_roster(csv_path):
    """Return ``[{id, name, age, job}, ...]`` from the agent seed CSV.

    A missing or unreadable file yields an empty list rather than raising: the
    picker degrades to "no agents offered", which is visible and recoverable,
    while an exception here would take the whole endpoint down.
    """
    if not csv_path or not os.path.exists(csv_path):
        return []
    rows = []
    try:
        # utf-8-sig: the seed CSVs carry a BOM, which would otherwise end up
        # glued to the first column name and hide the id field.
        with open(csv_path, "r", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    agent_id = int(row["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                rows.append({
                    "id": agent_id,
                    "name": str(row.get("name") or f"agent_{agent_id}"),
                    "age": str(row.get("age") or ""),
                    "job": str(row.get("job") or row.get("occupation") or ""),
                })
    except OSError:
        return []
    return rows
