"""
Tests for the Phase 4 Step 2 checkpointed runner: a checkpoint layer that
drives the real FOS council machinery (SimTree + CouncilExperimentScene) with
an injected FakeLLMClient — never a real API call.

The layer under test owns the run queue, the state DB, per-round checkpoints,
resume, and result collection; deliberation, prompts, neighbour context, and
voting all happen inside FOS. All tests use an in-memory SQLite database and
redirect result/checkpoint files to pytest tmp dirs.

Tests:
    test_init_is_idempotent                      — seeding twice keeps one row per CSV run
    test_status_on_empty_db                      — status works before tables exist
    test_verify_detects_missing_file             — verify reports a missing result file
    test_resume_determinism                      — placement identical across subprocesses
                                                  with different PYTHONHASHSEED
    test_identity_stability                      — same agent keeps persona + model
    test_no_cross_run_contamination              — confederate prompt does not leak
    test_neighbour_context_present               — round-3 prompts > round-1 prompts
                                                  for agents with degree > 2
    test_empty_response_gate                     — >5% empty calls fails the run
    test_failed_run_does_not_block_subsequent_runs
    test_network_mismatch_aborts_batch           — corrupt stats abort the batch
    test_kill_mid_round_and_resume               — interrupt between rounds resumes
"""

import csv
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from fos.experiment import commands, network, runner, store  # noqa: E402
from fos.experiment import clients as client_module  # noqa: E402


class FakeLLMClient:
    """Canned-responses LLM client that never makes a network call.

    Speaks in deliberation rounds (JSON with a message), replies with plain
    text to follow-up prompts, and votes in the voting round — confederates
    vote their assigned stance because the confederate role prompt says
    "genuinely support" or "genuinely oppose" and the fake follows it. Can
    return empty text for the first N calls, raise on a specific call, or
    request an interrupt on a specific call.
    """

    def __init__(self, empty_first_n_calls=0, interrupt_on_call=0, fail_on_call=0):
        self.empty_first_n_calls = empty_first_n_calls
        self.interrupt_on_call = interrupt_on_call
        self.fail_on_call = fail_on_call
        self.call_count = 0
        self.last_usage = None

    def chat(self, messages, json_mode=False, max_tokens=None):
        """Return a canned response, recording usage metadata per call."""
        self.call_count += 1
        prompt = messages[0]["content"] if messages else ""
        if self.call_count == self.interrupt_on_call:
            runner.request_interrupt()
        if self.call_count == self.fail_on_call:
            raise RuntimeError("FakeLLMClient injected failure")
        if self.call_count <= self.empty_first_n_calls:
            self.last_usage = {"prompt_tokens": 4, "completion_tokens": 0}
            return ""
        if "=== FOLLOW-UP PROMPT" in prompt:
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 8}
            return "I support this proposal."
        if '"vote_yes"' in prompt:
            if "genuinely support" in prompt:
                self.last_usage = {"prompt_tokens": 10, "completion_tokens": 4}
                return '{"action": "vote_yes"}'
            if "genuinely oppose" in prompt:
                self.last_usage = {"prompt_tokens": 10, "completion_tokens": 4}
                return '{"action": "vote_no"}'
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 4}
            return '{"action": "vote_yes"}'
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 6}
        return '{"action": "speak", "message": "I support this proposal."}'


@pytest.fixture
def db():
    """An in-memory SQLite database with the tables created and seeded."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store.init_db(conn)
    store.seed_from_csv(conn)
    yield conn
    conn.close()


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the state DB, results, and checkpoints at a tmp dir."""
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(store, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(store, "STATE_DB_PATH", runs_dir / "state.db")
    monkeypatch.setattr(store, "RESULTS_DIR", runs_dir / "results")
    return runs_dir


@pytest.fixture
def fake_client(monkeypatch):
    """Inject a working FakeLLMClient into the runner's client factory."""
    fake = FakeLLMClient()
    monkeypatch.setattr(client_module, "_agent_client", lambda agent_config=None: fake)
    return fake


def _read_result(run_id):
    """Load a run's result file from the (redirected) results dir."""
    path = store.RESULTS_DIR / f"{run_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _matrix_row_count():
    """How many runs the run-matrix CSV defines (what seeding must produce)."""
    with store.RUN_MATRIX_PATH.open(encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


# ── Part 1 tests (kept) ─────────────────────────────────────────────────────


def test_init_is_idempotent(db):
    """Initialising and seeding twice must keep one row per CSV run, not two."""
    store.init_db(db)
    store.seed_from_csv(db)
    count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert count == _matrix_row_count()


def test_status_on_empty_db():
    """The status command must work before any tables exist."""
    conn = sqlite3.connect(":memory:")
    try:
        summary = commands.status(conn)
        assert summary["total"] == _matrix_row_count()
        assert summary["complete"] == 0
        assert summary["empty_pct"] == 0.0
        assert summary["max_empty_run"] is None
    finally:
        conn.close()


def test_verify_detects_missing_file(db, paths):
    """A run marked complete with no result file on disk must be reported.

    Self-contained: the paths fixture redirects the results dir to a pytest
    tmp dir, so this never depends on the repository's own runs/results/.
    Every run except run_079 gets a valid result artifact; run_079 is marked
    complete without one, and verify must report it as the single missing run.
    """
    results_dir = store.RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)
    for run in store.list_runs(conn=db):
        if run["run_id"] == "run_079":
            continue  # deliberately left without a result artifact
        payload = {
            "run_id": run["run_id"],
            "schema_version": 1,
            "config_id": run["config_id"],
            "proposal_id": run["proposal_id"],
            "population_id": run["population_id"],
            "agents": [],
            "deliberation": [],
        }
        (results_dir / f"{run['run_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    store.mark_complete("run_079", str(results_dir / "run_079.json"), db)
    report = commands.verify_runs(db)
    assert report["missing"] == ["run_079"]
    assert report["verified"] == report["total"] - 1


# ── Phase 4 Step 2 tests ────────────────────────────────────────────────────


_SUBPROCESS_SCRIPT = """
import json, os, sys

sys.path.insert(0, {repo!r})
sys.path.insert(0, {repo!r} + "/src")

from fos.experiment import commands, runner, store
from fos.experiment.clients import _agent_client


class Fake:
    def __init__(self):
        self.call_count = 0
        self.last_usage = None

    def chat(self, messages, json_mode=False, max_tokens=None):
        self.call_count += 1
        if os.environ.get("FAKE_MODE") == "interrupt" and self.call_count == 1:
            runner.request_interrupt()
        prompt = messages[0]["content"] if messages else ""
        if "=== FOLLOW-UP PROMPT" in prompt:
            self.last_usage = {{"prompt_tokens": 10, "completion_tokens": 8}}
            return "I support this proposal."
        if '"vote_yes"' in prompt:
            if "genuinely support" in prompt:
                self.last_usage = {{"prompt_tokens": 10, "completion_tokens": 4}}
                return '{{"action": "vote_yes"}}'
            if "genuinely oppose" in prompt:
                self.last_usage = {{"prompt_tokens": 10, "completion_tokens": 4}}
                return '{{"action": "vote_no"}}'
            self.last_usage = {{"prompt_tokens": 10, "completion_tokens": 4}}
            return '{{"action": "vote_yes"}}'
        self.last_usage = {{"prompt_tokens": 10, "completion_tokens": 6}}
        return '{{"action": "speak", "message": "I support this proposal."}}'


_agent_client.__globals__["_agent_client"] = lambda agent_config=None: Fake()

store.init_db()
store.seed_from_csv()
n = commands.run(limit=1)
if os.environ.get("FAKE_MODE") == "interrupt":
    checkpoint = json.loads(store.get_checkpoint_path("run_079").read_text(encoding="utf-8"))
    payload = checkpoint["placement"]
else:
    result = json.loads((store.RESULTS_DIR / "run_079.json").read_text(encoding="utf-8"))
    payload = {{
        "placement_seed": result["placement_seed"],
        "permuted": result["node_permutation"],
        "confederates": result["confederates"],
    }}
print(json.dumps({{
    "placement_seed": payload["placement_seed"],
    "permuted": payload["permuted"],
    "confederates": sorted((c["agent_id"], c["stance"]) for c in payload["confederates"]),
}}))
"""


def _run_subprocess(env_extra):
    """Run the resume-determinism script in a fresh interpreter."""
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{_REPO_ROOT}{os.pathsep}{_REPO_ROOT / 'src'}"
        f"{os.pathsep}{env.get('PYTHONPATH', '')}"
    )
    env.update(env_extra)
    result = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SCRIPT.format(repo=str(_REPO_ROOT))],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
        timeout=600,
    )
    assert result.returncode == 0, f"subprocess failed:\n{result.stderr[-3000:]}"
    return result.stdout.strip().splitlines()[-1]


def test_resume_determinism(tmp_path):
    """Placement must be identical after an interrupt and a fresh subprocess.

    A broken implementation that derived the placement from hash() (which
    changes with PYTHONHASHSEED) would produce a different confederate set,
    permutation, or placement seed when the second subprocess resumes. The
    first subprocess interrupts right after placement and persists the
    placement in the checkpoint; the second (different PYTHONHASHSEED)
    resumes and completes the run.
    """
    runs_dir = tmp_path / "subprocess_runs"
    env_a = {
        "FOS_EXPERIMENT_RUNS_DIR": str(runs_dir),
        "PYTHONHASHSEED": "1",
        "FAKE_MODE": "interrupt",
    }
    placement_first = json.loads(_run_subprocess(env_a))
    assert os.path.exists(runs_dir / "checkpoints" / "run_079.json")

    env_b = {
        "FOS_EXPERIMENT_RUNS_DIR": str(runs_dir),
        "PYTHONHASHSEED": "2",
        "FAKE_MODE": "normal",
    }
    placement_second = json.loads(_run_subprocess(env_b))

    assert placement_first["placement_seed"] == placement_second["placement_seed"]
    assert placement_first["permuted"] == placement_second["permuted"]
    assert placement_first["confederates"] == placement_second["confederates"]


def test_identity_stability(db, paths, fake_client):
    """The same agent keeps its persona and model; its degree changes.

    run_079 and run_048 both use pop_b1 but different holme_kim configs
    (m=4 vs m=3). A broken implementation that regenerated personas per run
    would show different big_five values for the same agent_uid.
    """
    commands.run(run_id="run_079", conn=db)
    commands.run(run_id="run_048", conn=db)
    first = _read_result("run_079")
    second = _read_result("run_048")
    agents_first = {a["agent_uid"]: a for a in first["agents"]}
    agents_second = {a["agent_uid"]: a for a in second["agents"]}
    assert set(agents_first) == set(agents_second)
    for uid, record in agents_first.items():
        assert record["big_five"] == agents_second[uid]["big_five"]
        assert record["voting_model"] == agents_second[uid]["voting_model"]
    changed = [
        uid
        for uid in agents_first
        if agents_first[uid]["degree"] != agents_second[uid]["degree"]
    ]
    assert changed, "degree should differ between configs (holme_kim m=4 vs m=3)"


def test_no_cross_run_contamination(db, paths, fake_client):
    """Confederate prompts in run 1 must not leak into run 2's prompts.

    An agent that is a confederate in run_079 but not run_048 must have the
    confederate role prompt ("genuinely support/oppose") in its round-1
    prompt in the first run and a clean prompt in the second. A broken
    implementation that mutated the shared population configs instead of
    deep-copying them would inject confederate text into the later run.
    """
    commands.run(run_id="run_079", conn=db)
    commands.run(run_id="run_048", conn=db)
    first = _read_result("run_079")
    second = _read_result("run_048")
    conf_first = {c["agent_id"] for c in first["confederates"]}
    conf_second = {c["agent_id"] for c in second["confederates"]}
    only_first = sorted(conf_first - conf_second)
    assert only_first, "need an agent that is a confederate in run 1 but not run 2"
    agent_x = only_first[0]

    prompt_first = next(
        d["prompt"]
        for d in first["deliberation"]
        if d["agent_uid"] == agent_x and d["round"] == 1
    )
    prompt_second = next(
        d["prompt"]
        for d in second["deliberation"]
        if d["agent_uid"] == agent_x and d["round"] == 1
    )
    # Run 1 injected the confederate prompt; run 2 must be clean.
    assert any(
        phrase in prompt_first for phrase in ("genuinely support", "genuinely oppose")
    )
    assert "genuinely support" not in prompt_second
    assert "genuinely oppose" not in prompt_second


def test_neighbour_context_present(db, paths, fake_client):
    """Round-3 prompts must be strictly larger than round-1 prompts for
    agents with degree > 2.

    FOS injects prior-round (neighbour-visible) context into later prompts,
    so round 3 is longer than round 1. This must fail against the deleted
    parallel deliberation system, which never injected neighbour context.
    """
    commands.run(run_id="run_079", conn=db)
    result = _read_result("run_079")
    degree = {a["agent_uid"]: a["degree"] for a in result["agents"]}
    high_degree = [uid for uid, deg in degree.items() if deg > 2]
    assert high_degree, "network must contain agents with degree > 2"
    prompts = {
        (d["agent_uid"], d["round"]): d["prompt"] for d in result["deliberation"]
    }
    for uid in high_degree:
        assert len(prompts[(uid, 3)]) > len(prompts[(uid, 1)]), (
            f"round-3 prompt for {uid} (degree {degree[uid]}) is not larger"
        )


def test_empty_response_gate(db, paths, monkeypatch):
    """A run with >5% empty LLM responses must be marked failed with no
    result file, and the empty counts must be stored in the database.

    The fake returns empty text for the first 394 calls — exactly run 1's
    calls (rounds 1-3 have one main call per agent; round 4 votes once).
    6 confederate round-4 votes are intercepted (no chat call) since
    1dbde1c, so run 1 makes 394 calls, not 400.
    A broken implementation that wrote results regardless of the empty rate
    would leave a result file on disk.
    """
    fake = FakeLLMClient(empty_first_n_calls=394)
    monkeypatch.setattr(client_module, "_agent_client", lambda agent_config=None: fake)
    commands.run(run_id="run_079", conn=db)

    row = store.get_run("run_079", conn=db)
    assert row["status"] == "failed"
    assert "empty" in row["last_error"].lower()
    assert row["empty_response_count"] == 394
    assert row["total_llm_calls"] == 394
    assert not (store.RESULTS_DIR / "run_079.json").exists()


def test_failed_run_does_not_block_subsequent_runs(db, paths, monkeypatch):
    """A run that fails the empty-response gate must not stop the runs after it.

    run_079 is first in execution order; the fake returns empty text for the
    first 400 calls (run 1 only), so run_079 fails while run_123 and run_048
    complete and write result files. A broken implementation that aborted
    the whole batch on any failure would leave them pending with no results.
    """
    fake = FakeLLMClient(empty_first_n_calls=400)
    monkeypatch.setattr(client_module, "_agent_client", lambda agent_config=None: fake)
    commands.run(limit=3, conn=db)

    by_id = {r["run_id"]: r for r in store.list_runs(conn=db)}
    assert by_id["run_079"]["status"] == "failed"
    assert by_id["run_123"]["status"] == "complete"
    assert by_id["run_048"]["status"] == "complete"
    assert (store.RESULTS_DIR / "run_123.json").exists()
    assert (store.RESULTS_DIR / "run_048.json").exists()
    assert not (store.RESULTS_DIR / "run_079.json").exists()


def test_network_mismatch_aborts_batch(db, tmp_path, monkeypatch):
    """A network that fails verification must abort the whole batch.

    The first pending run (run_079, config 11 / un_veto) is checked against
    corrupted statistics. A broken implementation that kept going would
    execute run_123 and run_048 despite the corrupted stats.
    """
    lines = network.NETWORK_STATS_PATH.read_text(encoding="utf-8").splitlines()
    header, rows = lines[0], lines[1:]
    corrupted = [header]
    for line in rows:
        if line.startswith("11,un_veto,"):
            parts = line.split(",")
            parts[5] = "999.0"  # mean_degree
            line = ",".join(parts)
        corrupted.append(line)
    bad = tmp_path / "network_stats.csv"
    bad.write_text("\n".join(corrupted) + "\n", encoding="utf-8")
    monkeypatch.setattr(network, "NETWORK_STATS_PATH", bad)

    commands.run(limit=3, conn=db)
    by_id = {r["run_id"]: r for r in store.list_runs(conn=db)}
    assert by_id["run_079"]["status"] == "running"  # aborted mid-run, not failed
    assert by_id["run_123"]["status"] == "pending"  # never reached
    assert by_id["run_048"]["status"] == "pending"


def test_kill_mid_round_and_resume(db, paths, monkeypatch):
    """A run interrupted mid-round must resume at the correct round.

    The fake requests an interrupt on call 201 (the first call of round 2),
    so round 1 and round 2 complete (400 calls) before the run is left
    'running' with a round-2 checkpoint. A fresh fake resumes from round 3:
    exactly 294 more calls (200 round-3 + 94 round-4), never re-running
    rounds 1-2, and the result contains a full 100-agent round-1.
    """
    fake = FakeLLMClient(interrupt_on_call=201)
    monkeypatch.setattr(client_module, "_agent_client", lambda agent_config=None: fake)
    commands.run(limit=1, conn=db)  # attempt 1: interrupted mid-round-2

    row = store.get_run("run_079", conn=db)
    assert row["status"] == "running"  # left running, not failed
    assert fake.call_count == 400  # rounds 1-2 completed
    progress = {p["stage"] for p in store.get_progress("run_079", conn=db)}
    assert "round_1" in progress and "round_2" in progress
    checkpoint = json.loads(store.get_checkpoint_path("run_079").read_text())
    assert checkpoint["round"] == 2

    fresh = FakeLLMClient()  # no interrupt on resume
    monkeypatch.setattr(client_module, "_agent_client", lambda agent_config=None: fresh)
    commands.run(limit=1, conn=db)  # attempt 2: resumes and completes

    assert store.get_run("run_079", conn=db)["status"] == "complete"
    assert fresh.call_count == 294  # rounds 3-4 only (200 round-3 + 94 round-4; 6 confederate round-4 votes intercepted)
    result = _read_result("run_079")
    round1 = [d for d in result["deliberation"] if d["round"] == 1]
    assert len(round1) == 100  # round 1 survived from the checkpoint
