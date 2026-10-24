"""Durable episode graph; action results and organization state commit together."""

import fcntl
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import engine, environment
from .protocol import canonical, digest


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def graph(spec):
    for seed in spec["seeds"]:
        for p in (0, 1):
            for m in (0, 1):
                previous = None
                prefix = f"{seed}:P{p}M{m}"
                for index in range(spec["training_tasks"]):
                    identifier = f"{prefix}:train:{index}"
                    yield (
                        identifier,
                        previous,
                        {
                            "seed": seed,
                            "procedure": p,
                            "memory": m,
                            "turnover": 0,
                            "phase": "train",
                            "index": index,
                        },
                    )
                    previous = identifier
                trained = previous
                for t in (0, 1):
                    previous = trained
                    for index in range(spec["test_tasks"]):
                        identifier = f"{prefix}T{t}:test:{index}"
                        yield (
                            identifier,
                            previous,
                            {
                                "seed": seed,
                                "procedure": p,
                                "memory": m,
                                "turnover": t,
                                "phase": "test",
                                "index": index,
                            },
                        )
                        previous = identifier


def set_meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?)", (key, canonical(value)))


def metadata(db):
    return {r["key"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM metadata")}


def create(path, spec, record):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if Path(path).exists():
        raise ValueError("研究数据库已存在")
    with connect(path) as db:
        db.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tasks (
                seq INTEGER PRIMARY KEY, task_id TEXT UNIQUE NOT NULL,
                dependency TEXT REFERENCES tasks(task_id), input TEXT NOT NULL,
                input_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                lease_owner TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                result TEXT, state TEXT
            );
            CREATE TABLE actions (
                task_id TEXT REFERENCES tasks(task_id), action_id TEXT,
                input_hash TEXT NOT NULL, output TEXT NOT NULL,
                PRIMARY KEY (task_id, action_id)
            );
        """)
        for key, value in {
            **record,
            "protocol": spec,
            "protocol_hash": digest(spec),
            "status": "draft",
            "created_at": time.time(),
            "external_calls": 0,
        }.items():
            set_meta(db, key, value)
        db.executemany(
            "INSERT INTO tasks(task_id,dependency,input,input_hash) VALUES (?,?,?,?)",
            [
                (identifier, dep, canonical(payload), digest(payload))
                for identifier, dep, payload in graph(spec)
            ],
        )


def claim(path, owner, now=None, lease_seconds=30):
    now = time.time() if now is None else now
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if metadata(db)["status"] in {"paused", "completed", "blocked"}:
            return None
        db.execute(
            "UPDATE tasks SET status='pending', lease_owner=NULL WHERE status='leased' AND lease_until<=?",
            (now,),
        )
        row = db.execute("""SELECT t.* FROM tasks t LEFT JOIN tasks d ON t.dependency=d.task_id
            WHERE t.status='pending' AND (t.dependency IS NULL OR d.status='committed') ORDER BY t.seq LIMIT 1""").fetchone()
        if row is None:
            return None
        payload = json.loads(row["input"])
        if digest(payload) != row["input_hash"]:
            raise ValueError("task input hash mismatch")
        prior = db.execute("SELECT state FROM tasks WHERE task_id=?", (row["dependency"],)).fetchone()
        state = json.loads(prior["state"]) if prior else engine.initial_state()
        if payload["phase"] == "test" and payload["index"] == 0:
            state = engine.branch(state, payload["turnover"], payload["memory"])
        db.execute(
            "UPDATE tasks SET status='leased',lease_owner=?,lease_until=?,attempts=attempts+1 WHERE task_id=?",
            (owner, now + lease_seconds, row["task_id"]),
        )
        return {
            "task_id": row["task_id"],
            "payload": payload,
            "state": state,
            "input_hash": row["input_hash"],
        }


def release(path, identifier, owner):
    with connect(path) as db:
        db.execute(
            "UPDATE tasks SET status='pending',lease_owner=NULL WHERE task_id=? AND status='leased' AND lease_owner=?",
            (identifier, owner),
        )


def commit(path, task, result, state, owner):
    packed = canonical({**task["payload"], **result, "task_id": task["task_id"]})
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task["task_id"],)).fetchone()
        if row["status"] == "committed":
            if row["result"] != packed or row["state"] != canonical(state):
                raise ValueError("different result for committed task")
            return False
        if row["status"] != "leased" or row["lease_owner"] != owner:
            raise ValueError("lease no longer owned")
        if (
            digest(task["payload"]) != row["input_hash"]
            or digest(task["state"]) != result["state_before_hash"]
            or digest(state) != result["state_after_hash"]
        ):
            raise ValueError("task or state hash mismatch")
        if result["messages"] > 6 or result["checks"] > 2 or result["budget_violations"]:
            raise ValueError("action budget exceeded")
        for action in result["actions"]:
            if action["kind"] not in {"REPORT", "CHECK", "VOTE", "DECIDE", "FEEDBACK"}:
                raise ValueError("invalid action")
            db.execute(
                "INSERT INTO actions VALUES (?,?,?,?)",
                (
                    task["task_id"],
                    action["id"],
                    digest([task["input_hash"], action["depends_on"]]),
                    canonical(action),
                ),
            )
        db.execute(
            "UPDATE tasks SET status='committed',result=?,state=?,lease_owner=NULL,lease_until=NULL WHERE task_id=?",
            (packed, canonical(state), task["task_id"]),
        )
    return True


def results(path):
    with connect(path) as db:
        return [
            json.loads(row[0])
            for row in db.execute("SELECT result FROM tasks WHERE status='committed' ORDER BY seq")
        ]


def snapshot(path):
    with connect(path) as db:
        record = metadata(db)
        counts = {r[0]: r[1] for r in db.execute("SELECT status,COUNT(*) FROM tasks GROUP BY status")}
    record.update(counts=counts, committed=counts.get("committed", 0), total=sum(counts.values()))
    return record


def pause(path):
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if metadata(db)["status"] != "completed":
            set_meta(db, "status", "paused")


def run(path, max_commits=None, worker_build=None, respect_intent=False):
    """One exclusive local worker. Process death releases flock; next run reclaims leases."""
    lock_path = Path(path).with_suffix(".lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        owner = uuid.uuid4().hex
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            status = metadata(db)["status"]
            if status == "completed":
                return True
            if respect_intent and status != "running":
                return False
            db.execute("UPDATE tasks SET status='pending',lease_owner=NULL WHERE status='leased'")
            set_meta(db, "status", "running")
            set_meta(db, "artifacts_published", False)
            if worker_build:
                set_meta(db, "worker_build", worker_build)
            set_meta(db, "error", None)
        committed = 0
        try:
            while task := claim(path, owner):
                p = task["payload"]
                result, state = engine.episode(
                    environment.make_task(p["seed"], p["phase"], p["index"]),
                    task["state"],
                    p["procedure"],
                    p["memory"],
                    p["phase"] == "train",
                )
                commit(path, task, result, state, owner)
                committed += 1
                if max_commits is not None and committed >= max_commits:
                    pause(path)
                    break
            with connect(path) as db:
                missing = db.execute("SELECT COUNT(*) FROM tasks WHERE status!='committed'").fetchone()[0]
                if not missing:
                    set_meta(db, "status", "completed")
                    set_meta(db, "finished_at", time.time())
        except Exception as exc:
            with connect(path) as db:
                set_meta(db, "status", "blocked")
                set_meta(db, "error", f"{type(exc).__name__}: {exc}")
            raise
    return True
