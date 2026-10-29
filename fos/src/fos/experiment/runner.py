"""
Checkpointed execution layer around the FOS council machinery.

This is the Phase 4 Step 2 checkpoint layer. It owns the run queue, the
state database, per-round checkpoints, resume, status, and result
collection — and delegates deliberation, prompts, neighbour context, and
voting to the real FOS council scene (src/fos/core/experiment/). It never
touches anything inside FOS; it calls tree.advance(turns=1) once per round
and reads the finished node afterwards.

For each run the layer: rebuilds and verifies the network, loads the
population, places agents and confederates deterministically (sha256 seeds,
never hash()), drives four FOS rounds one at a time with a checkpoint after
every round, extracts results from the finished node, applies the
empty-response gate (>5% empty LLM calls fails the run) and the validation
gates, and writes the result file atomically.

Functions:
    run()                 — execute pending runs (or one specific run)
    retry()               — reset failed runs back to pending
    request_interrupt()   — ask the current run to stop at the next round boundary
    _execute_one_run()    — full pipeline for one run, resuming when possible
    _check_interrupted()  — raise RunInterrupted when SIGINT arrived
    _matrix_row()         — one row of the run matrix CSV
    _load_population()    — load and sha256-verify a population file
    _proposal_statement() — statement text for a proposal id
    _write_checkpoint()   — persist the tree + placement + call history
    _load_checkpoint()    — read a checkpoint back for resume
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import signal
import sqlite3
import traceback
from typing import Any

from fos.experiment import baseline, network, store
from fos.experiment.clients import TrackedClient, _build_clients, _llm_enabled
from fos.experiment.results import (
    EMPTY_RATE_LIMIT,
    TOTAL_ROUNDS,
    _agent_degree_records,
    _build_result,
    _empty_stats,
    _extract_results,
    _validate_gates,
    _write_result_atomically,
)
from fos.experiment.scene_builder import (
    _build_tree,
    _deserialize_tree,
    derive_placement,
    placement_from_json,
    placement_to_json,
)
from fos.i18n import T
from fos.proposals import load_proposals

REPO_ROOT = store.REPO_ROOT
RUN_MATRIX_PATH = store.RUN_MATRIX_PATH
POPULATIONS_DIR = REPO_ROOT / "data" / "populations"


class RunInterrupted(Exception):
    """Raised at a round boundary when a SIGINT (or request_interrupt) arrived."""


# ── SIGINT handling ─────────────────────────────────────────────────────────

_interrupted = False


def _handle_sigint(signum: int, frame: Any) -> None:
    """Record the interrupt; the run loop stops at the next round boundary."""
    global _interrupted
    _interrupted = True


signal.signal(signal.SIGINT, _handle_sigint)


def request_interrupt() -> None:
    """Ask the current run to stop after the current round finishes.

    Exposed so tests (and tooling) can simulate Ctrl-C without a signal.
    """
    global _interrupted
    _interrupted = True


# ── Public commands ──────────────────────────────────────────────────────────


def run(
    limit: int | None = None,
    run_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Execute pending runs, or one specific run; returns how many completed.

    Recovers crashed 'running' runs first, then processes runs in execution
    order. A NetworkMismatchError aborts the whole batch; any other failure
    marks that run failed and moves on; an interrupt stops the batch with
    the current run still marked 'running'.
    """
    global _interrupted
    _interrupted = False
    store.reset_stale_runs(conn)
    if run_id is not None:
        run_row = store.get_run(run_id, conn)
        if run_row is None:
            print(f"Unknown run {run_id}")
            return 0
        if run_row["status"] == "complete":
            print(f"Run {run_id} already complete")
            return 0
        targets = [run_row]
    else:
        try:
            targets = store.list_runs(status="pending", conn=conn)
        except sqlite3.OperationalError:
            print("State store not initialised — run 'python -m fos.experiment init' first")
            return 0
        if limit is not None:
            targets = targets[:limit]
    if not targets:
        print("No runs to execute")
        return 0

    executed = 0
    previous_concurrency = os.environ.get("FOS_LLM_CONCURRENCY")
    os.environ["FOS_LLM_CONCURRENCY"] = "1"  # sequential calls => deterministic attribution
    try:
        for run_row in targets:
            if _interrupted:
                print("Interrupted — batch stopped (no run was in progress)")
                break
            try:
                _execute_one_run(run_row["run_id"], conn)
                executed += 1
            except network.NetworkMismatchError as exc:
                print(f"ABORT: {exc}")
                break
            except RunInterrupted as exc:
                print(f"{exc} — run left in 'running' state")
                break
            except Exception as exc:
                store.mark_failed(run_row["run_id"], traceback.format_exc(), conn)
                print(f"Run {run_row['run_id']} FAILED: {exc}")
                continue
    finally:
        if previous_concurrency is None:
            os.environ.pop("FOS_LLM_CONCURRENCY", None)
        else:
            os.environ["FOS_LLM_CONCURRENCY"] = previous_concurrency
    return executed


def retry(conn: sqlite3.Connection | None = None) -> int:
    """Reset every failed run back to pending; prints and returns the count."""
    count = store.reset_failed_runs(conn)
    if count:
        print(f"Reset {count} failed run(s) to pending")
    else:
        print("No failed runs to reset")
    return count


# ── Per-run pipeline ─────────────────────────────────────────────────────────


def _execute_one_run(run_id: str, conn: sqlite3.Connection | None = None) -> None:
    """Run the full pipeline for one run id (see module docstring for steps)."""
    run_row = store.get_run(run_id, conn)

    # ── Startup assertion: model manager must be reachable ──────────
    # Real runs (FOS_EXPERIMENT_LLM=1) reach the model manager for model
    # preload and resident-model verification, so the manager must be up.
    # Deterministic test runs inject a fake client and never make a network
    # call, so they must not require a live manager on 127.0.0.1:8081.
    if _llm_enabled():
        import requests as _requests
        _mm_url = os.environ.get("FOS_MODEL_MANAGER_URL")
        if not _mm_url:
            raise RuntimeError(T("error.runner.manager_url_not_set"))
        try:
            _resp = _requests.get(f"{_mm_url.rstrip('/')}/status", timeout=5)
            if _resp.status_code != 200:
                raise RuntimeError(
                    T(
                        "error.runner.manager_status_http",
                        mm_url=_mm_url,
                        status_code=_resp.status_code,
                    )
                )
        except _requests.RequestException as exc:
            raise RuntimeError(
                T("error.runner.manager_unreachable", mm_url=_mm_url, error=exc)
            )

    store.mark_running(run_id, conn)

    if run_row is None:
        raise ValueError(T("error.runner.unknown_run", run_id=run_id))
    matrix = _matrix_row(run_id)
    if baseline.is_baseline(run_row["config_id"]):
        config = baseline.baseline_config()
    else:
        config = network._load_network_config(int(run_row["config_id"]))
    proposal_id = run_row["proposal_id"]
    network_seed = int(matrix["network_seed"])

    # If this run previously failed, discard its checkpoint so we start fresh
    if run_row.get("status") == "failed":
        ckpt_path = store.get_checkpoint_path(run_id)
        ckpt_path.unlink(missing_ok=True)
        print(f"Run {run_id}: discarded stale checkpoint from failed run")

    # Resume path: a checkpoint from a previous attempt already has the tree,
    # placement, network stats, and completed rounds' LLM calls.
    checkpoint_path = store.get_checkpoint_path(run_id)
    progress = {p["stage"] for p in store.get_progress(run_id, conn)}
    start_round = 0
    if "placement_done" in progress and checkpoint_path.exists():
        cp = _load_checkpoint(checkpoint_path)
        placement = placement_from_json(cp["placement"])
        clients, tracker = _build_clients(placement["run_agents"])
        if tracker is not None:
            tracker.preload_rounds(cp["round_calls"])
        tree = _deserialize_tree(cp["tree"], clients)
        current_node = cp["current_node"]
        start_round = cp["round"] + 1
        network_stats = cp["network_stats"]
    else:
        # Step 2 — rebuild the network and verify it against the expected stats.
        if baseline.is_baseline(run_row["config_id"]):
            edges = []
            network_stats = baseline.baseline_network_stats()
        else:
            edges = network._build_network(config, network_seed)
            expected = network._load_expected_stats(int(run_row["config_id"]), proposal_id, network_seed)
            network_stats = network._verify_network(edges, expected)
        store.record_progress(run_id, "network_built", conn)
        _check_interrupted(run_id, "network_built")

        # Step 3 — load the population and check its sha256.
        agents = _load_population(run_row["population_id"])
        proposal_statement = _proposal_statement(proposal_id)

        # Step 4 — placement: permutation, confederates, per-run agent copies.
        _bl = baseline.is_baseline(run_row["config_id"])
        placement = derive_placement(
            matrix, config, agents, proposal_statement, edges,
            n_yes=0 if _bl else 3,
            n_no=0 if _bl else 3,
        )
        store.record_progress(run_id, "placement_done", conn)

        # Step 5 — build the FOS scene and tree around it.
        clients, tracker = _build_clients(placement["run_agents"])
        tree, current_node = _build_tree(placement, proposal_statement, clients)
        _write_checkpoint(run_id, current_node, 0, placement, tracker, network_stats, tree)
        _check_interrupted(run_id, "placement_done")

    # Step 6 — rounds 1-4 one at a time (per-round resume).
    round_start = max(start_round, 1)
    if _interrupted:
        raise RunInterrupted(f"Interrupted before round {round_start} for run {run_id}")
    for round_idx in range(round_start, TOTAL_ROUNDS + 1):
        if tracker is not None:
            tracker.begin_round(round_idx)
        current_node = tree.advance(current_node, turns=1)
        if tracker is not None:
            tracker.end_round(round_idx)
        store.record_progress(run_id, f"round_{round_idx}", conn)
        _write_checkpoint(run_id, current_node, round_idx, placement, tracker, network_stats, tree)
        if _interrupted:
            raise RunInterrupted(f"Interrupted after round {round_idx} for run {run_id}")

    # Step 7 — extract results from the finished node.
    _, deliberation, votes = _extract_results(tree, current_node, placement, tracker)

    # Step 8 — empty-response detection (post-retry: FOS retries inside its client).
    empty_count, total_calls = _empty_stats(tracker)
    store.record_empty_stats(run_id, empty_count, total_calls, conn)
    if total_calls and empty_count / total_calls > EMPTY_RATE_LIMIT:
        pct = 100.0 * empty_count / total_calls
        store.mark_failed(
            run_id,
            f"empty-response gate: {empty_count}/{total_calls} calls empty ({pct:.1f}%)",
            conn,
        )
        print(f"Run {run_id} FAILED: empty-response gate ({pct:.1f}% empty)")
        return

    # Step 8.5 — resident-model audit (before gate checks)
    _resident_audit = {}
    for entry in deliberation:
        prompt_text = entry.get("prompt", "")
        # Extract model info from the prompt (not available in deliberation entries directly)
        # Instead, collect from tracker
    if tracker is not None:
        from collections import defaultdict as _dd
        _model_stats = _dd(lambda: {"count": 0, "residents": set()})
        for round_idx in range(1, TOTAL_ROUNDS + 1):
            for call in tracker.round_calls.get(round_idx, []):
                model = call.get("model", "unknown")
                resident = call.get("resident_model", "unknown")
                _model_stats[model]["count"] += 1
                _model_stats[model]["residents"].add(resident)
        print("\n=== Resident-Model Audit ===")
        for model, stats in sorted(_model_stats.items()):
            residents = stats["residents"]
            status = "OK" if len(residents) <= 1 else "FAIL"
            print(f"  {model}: {stats['count']} calls, residents={residents} {status}")
        print()

    # Step 9 — validation gates before marking complete.
    agent_records = _agent_degree_records(placement)
    _validate_gates(
        deliberation, agent_records, votes, placement["confederates"],
        bios={a["agent_id"]: a.get("bio", "") for a in placement.get("run_agents", [])},
    )

    # Step 10 — write the result file atomically.
    result = _build_result(
        run_id, run_row, matrix, config, placement, network_stats,
        votes, deliberation, empty_count, total_calls,
    )
    output_path = _write_result_atomically(run_id, result)
    store.record_progress(run_id, "written", conn)

    # Step 11 — mark the run complete.
    store.mark_complete(run_id, output_path, conn)
    print(f"Run {run_id} complete -> {output_path}")


def _check_interrupted(run_id: str, stage: str) -> None:
    """Raise RunInterrupted when SIGINT arrived since the last check."""
    if _interrupted:
        raise RunInterrupted(f"Interrupted during {stage} for run {run_id}")


# ── Data loading ─────────────────────────────────────────────────────────────


def _matrix_row(run_id: str) -> dict[str, str]:
    """Return the run matrix CSV row for a run id."""
    with RUN_MATRIX_PATH.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["run_id"] == run_id:
                return row
    raise ValueError(T("error.runner.run_id_not_in_matrix", run_id=run_id))


def _load_population(population_id: str) -> list[dict[str, Any]]:
    """Load a population file, verify its sha256, and return its agents."""
    path = POPULATIONS_DIR / f"{population_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    stored = data.pop("sha256", None)
    if stored is None:
        raise ValueError(
            T("error.runner.population_no_sha256", population_id=population_id)
        )
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False)
    recomputed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if stored != recomputed:
        raise ValueError(
            T(
                "error.runner.population_sha256_mismatch",
                population_id=population_id,
                stored=stored,
                recomputed=recomputed,
            )
        )
    return data["agents"]


def _proposal_statement(proposal_id: str) -> str:
    """Return the statement text for a proposal id."""
    for proposal in load_proposals():
        if proposal.id == proposal_id:
            return proposal.statement
    raise ValueError(T("error.runner.unknown_proposal_id", proposal_id=proposal_id))


# ── Checkpoints ──────────────────────────────────────────────────────────────


def _write_checkpoint(
    run_id: str,
    current_node: int,
    round_idx: int,
    placement: dict[str, Any],
    tracker: TrackedClient | None,
    network_stats: dict[str, Any],
    tree: Any,
) -> None:
    """Persist the tree, placement, network stats, and completed rounds' calls."""
    path = store.get_checkpoint_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "round": round_idx,
        "current_node": current_node,
        "placement": placement_to_json(placement),
        "round_calls": dict(tracker.round_calls) if tracker is not None else {},
        "network_stats": network_stats,
        "tree": tree.serialize(),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())


def _load_checkpoint(path) -> dict[str, Any]:
    """Read a checkpoint file back for resume."""
    return json.loads(path.read_text(encoding="utf-8"))
