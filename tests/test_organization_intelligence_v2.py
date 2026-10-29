"""Scientific boundaries and crash recovery for the zero-provider engine."""

import copy
import fcntl
import json
import py_compile
import subprocess
import sys
import time

import pytest

from gaworld.research.organization_intelligence.v2 import build, engine, environment, protocol, queue, report


def test_pilot_is_frozen_factorial_and_zero_calls():
    spec = protocol.freeze({})
    assert spec["budget"]["external_calls"] == 0
    assert spec["budget"]["episodes"] == 2000
    assert len(spec["cells"]) == 8
    assert len({(c["procedure"], c["memory"], c["turnover"]) for c in spec["cells"]}) == 8
    assert spec == protocol.freeze({})
    for values in ({"seeds": 0}, {"seeds": 101}, {"seed": True}, {"provider": "minimax"}):
        with pytest.raises(ValueError):
            protocol.freeze(values)


def test_views_have_no_oracle_and_noise_is_paired():
    task = environment.make_task(17, "test", 2)
    assert task == environment.make_task(17, "test", 2)
    views = environment.views(task)
    for role, view in enumerate(views):
        assert set(view) == {"role", "local", "common", "source", "check_cost", "task_id"}
        assert view["role"] == role
        assert "truth" not in json.dumps(view)
    assert len({v["common"]["id"] for v in views}) == 1


def test_turnover_erases_private_only_and_no_test_feedback():
    state = engine.initial_state()
    for n in range(10):
        _, state = engine.episode(environment.make_task(23, "train", n), state, 1, 1, True)
    assert any(p for p in state["private"])
    assert state["organization"]
    newcomer = engine.branch(state, True, True)
    assert newcomer["private"] == [{}, {}, {}]
    assert newcomer["organization"] == state["organization"]
    removed = engine.branch(state, False, False)
    assert removed["organization"] == {}
    original = copy.deepcopy(newcomer)
    _, next_state = engine.episode(environment.make_task(23, "test", 0), newcomer, 1, 1, False)
    assert next_state == original == newcomer


@pytest.mark.parametrize("procedure", [0, 1])
@pytest.mark.parametrize("memory", [0, 1])
def test_actions_and_costs_are_bounded_and_reproducible(procedure, memory):
    task = environment.make_task(100, "test", 0)
    state = engine.initial_state()
    result, nxt = engine.episode(task, state, procedure, memory, False)
    assert (result, nxt) == engine.episode(task, state, procedure, memory, False)
    assert result["checks"] <= 2 and result["messages"] <= 6
    assert result["net_reward"] == pytest.approx(result["reward"] - result["cost"])
    assert len({a["id"] for a in result["actions"]}) == len(result["actions"])
    assert result["budget_violations"] == 0
    assert result["oracle_reward"] >= result["reward"]
    if procedure:
        assert result["local_reports_shared"] == 3
        assert result["common_report_duplicates_removed"] == 2


def create_db(tmp_path, seeds=1):
    spec = protocol.freeze({"seeds": seeds})
    path = tmp_path / "tasks.sqlite"
    queue.create(path, spec, {"id": "fixture"})
    return path, spec


@pytest.mark.parametrize("interrupt_after", [7, 65, 107])
def test_resume_same_graph_without_repeating_committed_tasks(tmp_path, interrupt_after):
    path, spec = create_db(tmp_path)
    queue.run(path, max_commits=interrupt_after)
    before = queue.results(path)
    assert len(before) == interrupt_after
    queue.run(path)
    after = queue.results(path)
    assert len(after) == spec["budget"]["episodes"]
    assert after[:interrupt_after] == before
    assert len({r["task_id"] for r in after}) == len(after)
    assert report.evaluate(spec, after)["complete"]
    assert queue.snapshot(path)["status"] == "completed"


def test_crash_before_commit_reclaims_lease_and_does_not_advance_state(tmp_path):
    path, _ = create_db(tmp_path)
    claimed = queue.claim(path, "dead-worker", now=1, lease_seconds=1)
    assert claimed and queue.results(path) == []
    again = queue.claim(path, "new-worker", now=3)
    assert again["task_id"] == claimed["task_id"]
    with pytest.raises(ValueError, match="lease"):
        queue.commit(path, claimed, {"bad": True}, {}, "dead-worker")
    queue.release(path, again["task_id"], "new-worker")
    queue.run(path)
    assert queue.snapshot(path)["committed"] == 200


def test_no_contrasts_from_incomplete_or_duplicate_cells(tmp_path):
    path, spec = create_db(tmp_path)
    queue.run(path, max_commits=7)
    assert report.evaluate(spec, queue.results(path))["contrasts"] == []
    queue.run(path)
    rows = queue.results(path)
    assert not report.evaluate(spec, [*rows, rows[0]])["complete"]


def test_frozen_bundle_worker_isolated_and_tampering_rejected(tmp_path):
    bundle = tmp_path / "bundle"
    manifest = build.freeze(bundle)
    assert manifest["build_id"] == build.identity()["build_id"]
    path, _ = create_db(tmp_path)
    with queue.connect(path) as db:
        queue.set_meta(db, "status", "running")
    result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    snap = queue.snapshot(path)
    assert snap["committed"] == 200
    assert snap["worker_build"] == manifest["build_id"]
    (bundle / "engine" / "engine.py").write_text("raise RuntimeError('corrupt')")
    result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "build" in result.stderr.lower()


def test_import_graph_has_no_llm_dependency():
    # Isolated frozen workers must remain standard-library-only.
    for source in build.sources().values():
        assert b"gaworld.llm" not in source and b"call_llm" not in source


def test_unpurchased_truth_does_not_change_policy_and_test_never_reads_feedback(monkeypatch):
    task = environment.make_task(100, "test", 1)  # Costly: no paid verification.
    monkeypatch.setattr(environment, "feedback", lambda *_: pytest.fail("test feedback leaked"))
    alternate = copy.deepcopy(task)
    alternate["truth"] = [[1000, 0, 0, 0]] * 3
    for procedure in (0, 1):
        first, _ = engine.episode(task, engine.initial_state(), procedure, 1, False)
        second, _ = engine.episode(alternate, engine.initial_state(), procedure, 1, False)
        assert first["choice"] == second["choice"]
        assert first["actions"] == second["actions"]


def test_check_capability_enforces_budget_even_if_policy_lies(monkeypatch):
    def bad_policy(views, state, procedure, memory, check):
        for _ in range(3):
            check(0, 0)

    monkeypatch.setattr(engine, "decide", bad_policy)
    with pytest.raises(ValueError, match="预算"):
        engine.episode(environment.make_task(1, "test", 0), engine.initial_state(), 1, 1, False)


def test_duplicate_commit_and_transaction_rollback(tmp_path):
    path, _ = create_db(tmp_path)
    task = queue.claim(path, "worker")
    p = task["payload"]
    result, state = engine.episode(
        environment.make_task(p["seed"], p["phase"], p["index"]), task["state"], 0, 0, True
    )
    with queue.connect(path) as db:
        db.execute(
            "CREATE TRIGGER fault BEFORE INSERT ON actions WHEN NEW.action_id LIKE '%feedback' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(Exception, match="injected"):
        queue.commit(path, task, result, state, "worker")
    with queue.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 0
        assert db.execute("SELECT state FROM tasks WHERE task_id=?", (task["task_id"],)).fetchone()[0] is None
        db.execute("DROP TRIGGER fault")
    assert queue.commit(path, task, result, state, "worker")
    assert not queue.commit(path, task, result, state, "worker")
    with pytest.raises(ValueError, match="different result"):
        queue.commit(path, task, {**result, "choice": 3}, state, "worker")


def test_frozen_source_loader_ignores_unverified_bytecode(tmp_path):
    bundle = tmp_path / "bundle"
    build.freeze(bundle)
    marker = tmp_path / "bad-marker"
    source = tmp_path / "injected.py"
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('unverified bytecode')"
    )
    cache = bundle / "engine" / "__pycache__" / f"engine.{sys.implementation.cache_tag}.pyc"
    cache.parent.mkdir()
    py_compile.compile(
        str(source), cfile=str(cache), invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH
    )
    path, _ = create_db(tmp_path)
    with queue.connect(path) as db:
        queue.set_meta(db, "status", "running")
    result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert queue.snapshot(path)["committed"] == 200


def test_paused_before_worker_start_and_duplicate_worker_cannot_publish(tmp_path):
    bundle = tmp_path / "bundle"
    build.freeze(bundle)
    path, _ = create_db(tmp_path)
    queue.pause(path)
    result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and queue.snapshot(path)["committed"] == 0
    assert queue.snapshot(path)["status"] == "paused"
    with queue.connect(path) as db:
        queue.set_meta(db, "status", "running")
    with path.with_suffix(".worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert not (path.parent / "results.json").exists()
        assert "worker_pid" not in queue.snapshot(path)


def test_real_process_death_reclaims_uncommitted_lease(tmp_path):
    path, _ = create_db(tmp_path)
    ready = tmp_path / "ready"
    code = "from gaworld.research.organization_intelligence.v2 import queue; from pathlib import Path; import time; queue.claim(Path(__import__('sys').argv[1]), 'doomed'); Path(__import__('sys').argv[2]).touch(); time.sleep(30)"
    child = subprocess.Popen([sys.executable, "-c", code, str(path), str(ready)])
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        child.kill()
        child.wait(timeout=5)
        assert queue.snapshot(path)["counts"]["leased"] == 1
        queue.run(path)
        assert queue.snapshot(path)["committed"] == 200
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_completed_episodes_can_finalize_after_export_crash(tmp_path):
    bundle = tmp_path / "bundle"
    build.freeze(bundle)
    path, _ = create_db(tmp_path)
    queue.run(path)  # Equivalent to dying after the last commit but before publishing exports.
    assert not (tmp_path / "results.json").exists()
    result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "results.json").read_text())["analysis"]["complete"]
    assert queue.snapshot(path)["artifacts_published"]


def test_workspace_change_does_not_change_existing_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    manifest = build.freeze(bundle)
    workspace = tmp_path / "changed-workspace"
    workspace.mkdir()
    for name, source in build.sources().items():
        (workspace / name).write_bytes(source)
    (workspace / "engine.py").write_text("raise RuntimeError('changed workspace')")
    monkeypatch.setattr(build, "_ROOT", workspace)
    assert not build.identity()["workspace_matches"]
    assert build.identity()["build_id"] == manifest["build_id"]
    path, _ = create_db(tmp_path)
    with queue.connect(path) as db:
        queue.set_meta(db, "status", "running")
    completed = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert queue.snapshot(path)["worker_build"] == manifest["build_id"]


def test_partial_export_is_not_final_publication_on_resume(tmp_path):
    bundle = tmp_path / "bundle"
    build.freeze(bundle)
    path, _ = create_db(tmp_path)
    queue.run(path, max_commits=7)
    with queue.connect(path) as db:
        queue.set_meta(db, "artifacts_published", True)  # Simulate an old partial artifact marker.
    queue.run(path)
    assert queue.snapshot(path)["status"] == "completed"
    assert not queue.snapshot(path)["artifacts_published"]
    result = subprocess.run(build.command(bundle, path), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "results.json").read_text())["analysis"]["episodes"] == 200
