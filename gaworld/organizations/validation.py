"""Read-only organization startup checks, before runtime assembly or spawn."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def validate_config(config: Mapping[str, Any]) -> None:
    """Reject unsupported combinations; a disabled feature remains inert."""
    block = config.get("organizations") or {}
    if not isinstance(block, Mapping):
        raise ValueError("organizations must be a configuration object")
    if not block.get("enabled", False):
        return
    governance = block.get("governance", {})
    if not isinstance(governance, Mapping) or type(governance.get("enabled", False)) is not bool:
        raise ValueError("organizations.governance must be an object with boolean enabled")
    if governance.get("enabled", False):
        from gaworld.organizations.governance import validate_policy

        validate_policy({k: v for k, v in governance.items() if k != "enabled"})
    economy = config.get("economy") or {}
    if not isinstance(economy, Mapping) or not economy.get("enabled", True):
        raise ValueError("organizations requires economy.enabled=true")
    long_run = config.get("long_run") or {}
    unit = str(long_run.get("unit", "day")).strip().lower() if isinstance(long_run, Mapping) else "day"
    if unit != "day":
        raise ValueError(f"organizations does not support long_run.unit={unit}; use day")
    for key in ("distributed", "cluster"):
        mode = config.get(key) or {}
        if isinstance(mode, Mapping) and mode.get("enabled", False):
            raise ValueError("organizations does not support distributed worlds")
    seeds = block.get("seeds", [])
    if not isinstance(seeds, list) or any(not isinstance(seed, Mapping) for seed in seeds):
        raise ValueError("organizations.seeds must be a list of organization definitions")
    for seed in seeds:
        from gaworld.organizations.schemas import validate_command

        validate_command({**seed, "type": "create"})
    if config.get("stateful", False):
        _validate_persisted(config)


def _validate_persisted(config: Mapping[str, Any]) -> None:
    from gaworld.organizations.schemas import identity_fingerprint
    from gaworld.organizations.store import SCHEMA_VERSION

    memory = Path(config.get("memory_dir", "output/memory"))
    database = memory / "organizations.sqlite"
    if not database.exists():
        return
    try:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            meta = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM meta")}
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported organization schema version")
        if meta.get("recovery_required") or meta.get("open_day") is not None:
            raise ValueError("organizations recovery_required: incomplete prior settlement")
        source = config.get("csv_path")
        if source and meta.get("population_source") not in (None, str(Path(source).resolve())):
            raise ValueError("organization population source changed")
        state_file = memory / "sim_state.json"
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        ids = config.get("agent_ids") or []
        per_agent = state.get("agent_last_day", {})
        if ids and per_agent:
            start_day = max((per_agent.get(str(number), 0) for number in ids), default=0) + 1
        else:
            start_day = int(state.get("last_day", 0)) + 1
        if start_day <= meta.get("last_processed_day", 0):
            raise ValueError("resident clock precedes completed organization day")
        identities = meta.get("identities", {})
        if source and identities and Path(source).exists():
            with Path(source).open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    number = row.get("id", row.get("agent_id", ""))
                    if ids and str(number) not in {str(i) for i in ids}:
                        continue
                    if str(number) in identities:
                        row["id"] = int(number)
                        if identities[str(number)] != identity_fingerprint(row):
                            raise ValueError(f"organization resident identity mismatch for {number}")
    except (OSError, sqlite3.Error, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"organizations recovery_required: unreadable state: {exc}") from exc
