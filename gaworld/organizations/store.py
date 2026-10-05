"""Versioned SQLite state, durable queue, audit history and execution lease."""

from __future__ import annotations

import fcntl
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from gaworld.organizations.schemas import (
    OrganizationValidationError,
    identifier,
    identity_fingerprint,
    now,
    validate_command,
)

_TABLES = {
    "organizations",
    "members",
    "jobs",
    "applications",
    "rules",
    "decisions",
    "transactions",
    "batches",
    "proposals",
    "ballots",
}
SCHEMA_VERSION = 1


class OrganizationStore:
    def __init__(self, path, generation_id=None):
        self.read_generation = None
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self._lease = None
        self._db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for table in sorted(_TABLES):
            self._db.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (generation TEXT NOT NULL, id TEXT NOT NULL, organization_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(generation,id))"
            )
        self._db.execute("CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY AUTOINCREMENT, generation TEXT NOT NULL, organization_id TEXT NOT NULL, data TEXT NOT NULL)"
        )
        self._db.commit()
        version = self.get_meta("schema_version")
        if version not in (None, SCHEMA_VERSION):
            raise OrganizationValidationError("unsupported organization schema version")
        self.set_meta("schema_version", SCHEMA_VERSION)
        self.read_generation = identifier(generation_id) if generation_id is not None else None

    def generation(self):
        return self.read_generation or self.get_meta("generation_id", "unstarted")

    @contextmanager
    def atomic(self):
        if self.read_generation is not None:
            raise OrganizationValidationError("historical generation views are read-only")
        with self._lock:
            outer = self._depth == 0
            if outer:
                self._db.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
                self._depth -= 1
                if outer:
                    self._db.commit()
            except BaseException:
                self._depth -= 1
                if outer:
                    self._db.rollback()
                raise

    def get_meta(self, key, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        with self.atomic():
            self._db.execute(
                "INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value, allow_nan=False))
            )

    def new_generation(self):
        generation = uuid.uuid4().hex
        with self.atomic():
            previous = self.get_meta("generation_id")
            if previous:
                self.set_meta(f"generation_state:{previous}", self.generation_meta())
            for key, value in {
                "generation_id": generation,
                "last_processed_day": 0,
                "last_started_day": 0,
                "last_command_day": 0,
                "open_day": None,
                "identities": {},
                "recovery_required": False,
            }.items():
                self.set_meta(key, value)
        return generation

    def generation_meta(self):
        selected = self.generation()
        current = self.get_meta("generation_id", "unstarted")
        fields = ("last_processed_day", "recovery_required")
        if selected == current:
            return {"generation_id": selected, **{key: self.get_meta(key) for key in fields}}
        saved = self.get_meta(f"generation_state:{selected}")
        return saved or {"generation_id": selected, **dict.fromkeys(fields)}

    def validate_population(self, agents, source=None):
        identities = self.get_meta("identities", {})
        if source is not None and self.get_meta("population_source", source) != str(Path(source).resolve()):
            raise RuntimeError("organization population source identity mismatch")
        for agent in agents:
            old = identities.get(str(agent["id"]))
            if old is not None and old != identity_fingerprint(agent):
                raise RuntimeError(f"organization resident identity mismatch for {agent['id']}")

    def put(self, table, key, row):
        if table not in _TABLES:
            raise ValueError("unknown organization table")
        generation = self.get_meta("generation_id", "unstarted")
        payload = dict(row, generation_id=generation)
        oid = payload.get("organization_id", str(key) if table == "organizations" else "")
        with self.atomic():
            self._db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?,?,?,?)",
                (generation, str(key), oid, json.dumps(payload, ensure_ascii=False, allow_nan=False)),
            )
        return payload

    def get(self, table, key):
        if table not in _TABLES:
            raise ValueError("unknown organization table")
        with self._lock:
            row = self._db.execute(
                f"SELECT data FROM {table} WHERE generation=? AND id=?",
                (self.generation(), str(key)),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def rows(self, table, organization_id=None):
        if table not in _TABLES:
            raise ValueError("unknown organization table")
        sql = f"SELECT data FROM {table} WHERE generation=?"
        args = [self.generation()]
        if organization_id is not None:
            sql += " AND organization_id=?"
            args.append(organization_id)
        with self._lock:
            return [json.loads(r[0]) for r in self._db.execute(sql + " ORDER BY rowid", args)]

    def list_organizations(self):
        return self.rows("organizations")

    def detail(self, organization_id):
        row = self.get("organizations", organization_id)
        if row is None:
            return None
        for table in ("members", "jobs", "applications", "rules", "decisions", "transactions"):
            row[table] = self.rows(table, organization_id)
        if "governance" in row or self.rows("proposals", organization_id):
            row["proposals"] = self.rows("proposals", organization_id)
            row["ballots"] = self.rows("ballots", organization_id)
        return row

    def add_history(self, organization_id, kind, data):
        row = {
            "organization_id": organization_id,
            "type": kind,
            "created_at": now(),
            "generation_id": self.get_meta("generation_id"),
            **data,
        }
        with self.atomic():
            self._db.execute(
                "INSERT INTO history(generation,organization_id,data) VALUES (?,?,?)",
                (
                    self.generation(),
                    organization_id,
                    json.dumps(row, ensure_ascii=False, allow_nan=False),
                ),
            )
        return row

    def history(self, organization_id, limit=100):
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM history WHERE generation=? AND organization_id=? ORDER BY seq DESC LIMIT ?",
                (
                    self.generation(),
                    organization_id,
                    max(1, min(int(limit), 10000)),
                ),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def enqueue(self, payload, actor=None):
        row = validate_command(payload)
        command_id = row.get("command_id") or uuid.uuid4().hex
        row["command_id"] = command_id
        with self.atomic():
            existing = self.command(command_id)
            if existing:
                if existing["payload"] != row:
                    raise OrganizationValidationError("command_id reused with different payload")
                return existing
            command = {
                "command_id": command_id,
                "type": row["type"],
                "organization_id": row["organization_id"],
                "payload": row,
                "actor": actor,
                "status": "pending",
                "created_at": now(),
                "result": None,
            }
            if row["type"] in {"set_governance", "propose_rule", "cast_vote", "leader_decide"}:
                command["target_generation_id"] = self.get_meta("generation_id")
            self._db.execute(
                "INSERT INTO commands VALUES (?,?)",
                (command_id, json.dumps(command, ensure_ascii=False, allow_nan=False)),
            )
            return command

    def command(self, command_id):
        with self._lock:
            row = self._db.execute("SELECT data FROM commands WHERE id=?", (command_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def commands(self):
        with self._lock:
            return [
                json.loads(row[0]) for row in self._db.execute("SELECT data FROM commands ORDER BY rowid")
            ]

    def update_command(self, command, status, result, day):
        row = dict(
            command,
            status=status,
            result=result,
            applied_day=day,
            generation_id=self.get_meta("generation_id"),
        )
        with self.atomic():
            self._db.execute(
                "UPDATE commands SET data=? WHERE id=?",
                (json.dumps(row, ensure_ascii=False, allow_nan=False), row["command_id"]),
            )
        return row

    def acquire_writer(self):
        if self._lease is not None:
            return
        # Retained until release_writer(), including across daily transactions.
        lease = open(str(self.path) + ".writer.lock", "a+", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lease.close()
            raise RuntimeError("another organization writer owns this run directory") from exc
        self._lease = lease

    def release_writer(self):
        if self._lease is not None:
            fcntl.flock(self._lease, fcntl.LOCK_UN)
            self._lease.close()
            self._lease = None

    def close(self):
        self.release_writer()
        self._db.close()
