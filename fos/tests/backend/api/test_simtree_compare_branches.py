"""FOS: POST /simulations/{id}/compare-branches — PW-equivalent branch reports.

Phase 7 STAGE A (RED). The SimTree topology explorer needs quantitative
comparison of COMPLETED GAWorld branches, reusing the existing Parallel
Worlds analysis in GAWorld (``POST /api/analysis/compare``) — no duplicate
FOS analysis implementation.

Contract specified here (the route does not exist yet — every test fails
with "not implemented" until it does):

* Validations, all 4xx: baseline/comparison node must exist in THIS
  simulation; the node must be a GAWorld node (has gaworld run metadata);
  the branch run must be completed; the run's state CSV must exist.
* Manifest synthesis: a PW-compatible manifest is built from node/scene
  metadata (never from frontend-supplied paths) — ``baseline`` world plus
  one world per comparison branch, with labels/events/config carrying branch
  provenance (fork day, interventions, LLM changes) and a state_csv mapping.
* GAWorld unavailable → a clean error body, never a raw stack trace.
* A lightweight comparison ref is persisted in the run's ``result_meta``.
* No secrets: anything that looks like a credential in node metadata must
  not leak into the response (sentinel test).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litestar.exceptions import HTTPException

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, REPO_ROOT)

import fos.backend.api.routes.experiments as experiments_routes  # noqa: E402

GOLDEN = os.path.join(REPO_ROOT, "tests", "fixtures", "pw_compare_golden")


@pytest.fixture()
def compare_branches():
    """The unwrapped route function; a named failure, not an ImportError."""
    fn = getattr(experiments_routes, "compare_branches", None)
    if fn is None:
        pytest.fail("POST /simulations/{id}/compare-branches is not implemented")
    return fn.fn if hasattr(fn, "fn") else fn


def _state_csv(tmp: str, name: str) -> str:
    dst = os.path.join(tmp, name, "state", "agent_state_history.csv")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(
        os.path.join(GOLDEN, name, "state", "agent_state_history.csv"), dst
    )
    return dst


def _node(node_id: int, *, run_dir: str | None = None, status: str = "completed",
          gaworld: bool = True, label: str = "", fork_day: int | None = None,
          interventions: list | None = None, llm_changes: list | None = None,
          extra_meta: dict | None = None) -> dict:
    meta: dict = {}
    if gaworld:
        meta["gaworld"] = {
            "run_dir": run_dir,
            "status": status,
            "label": label,
            "fork_day": fork_day,
            "interventions": interventions or [],
            "llm_changes": llm_changes or [],
        }
    if extra_meta:
        meta.update(extra_meta)
    return {"id": node_id, "meta": meta}


async def _run(compare_branches, nodes: dict, payload: dict):
    """Call the route with a mocked owned tree containing ``nodes``."""
    mock_tree = SimpleNamespace(nodes=nodes)
    mock_record = SimpleNamespace(tree=mock_tree, result_meta={}, id=9)
    return await _call(compare_branches, mock_record, payload)


async def _call(fn, mock_record, payload):
    """Invoke with whatever signature the route ends up having."""
    import inspect

    kwargs = {"data": payload, "simulation_id": "sim-1"}
    params = inspect.signature(fn).parameters
    if "session" in params:
        ctx = AsyncMock()
        ctx.__aenter__.return_value = AsyncMock()
        ctx.__aexit__.return_value = None
        kwargs["session"] = ctx
    if "run_record" in params:
        kwargs["run_record"] = mock_record
    if "request" in params:
        kwargs["request"] = SimpleNamespace()
    return await fn(**kwargs)


import json  # noqa: E402


def _completed_tree(tmp: str):
    base_csv = _state_csv(tmp, "base")
    treat_csv = _state_csv(tmp, "treat")
    nodes = {
        1: _node(1, run_dir=os.path.join(tmp, "base"), label="基准", fork_day=0),
        2: _node(
            2, run_dir=os.path.join(tmp, "treat"), label="干预", fork_day=3,
            interventions=[{"day": 3, "name": "限行"}],
            llm_changes=[{"agent_id": 2, "provider": "b"}],
        ),
    }
    csvs = {1: base_csv, 2: treat_csv}
    return nodes, csvs


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_branches_happy_path(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        body = await _run(compare_branches, nodes, {
            "baseline_node": 1, "branch_nodes": [2],
        })
        assert "report" in body or "manifest" in body


@pytest.mark.asyncio
async def test_unknown_baseline_node_is_rejected(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        with pytest.raises(HTTPException) as err:
            await _run(compare_branches, nodes, {
                "baseline_node": 99, "branch_nodes": [2],
            })
        assert 400 <= err.value.status_code < 500


@pytest.mark.asyncio
async def test_unknown_branch_node_is_rejected(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        with pytest.raises(HTTPException) as err:
            await _run(compare_branches, nodes, {
                "baseline_node": 1, "branch_nodes": [77],
            })
        assert 400 <= err.value.status_code < 500


@pytest.mark.asyncio
async def test_non_gaworld_node_is_rejected(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        nodes[3] = _node(3, gaworld=False)
        with pytest.raises(HTTPException) as err:
            await _run(compare_branches, nodes, {
                "baseline_node": 1, "branch_nodes": [3],
            })
        assert 400 <= err.value.status_code < 500


@pytest.mark.asyncio
async def test_unfinished_branch_is_rejected(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        nodes[2]["meta"]["gaworld"]["status"] = "running"
        with pytest.raises(HTTPException) as err:
            await _run(compare_branches, nodes, {
                "baseline_node": 1, "branch_nodes": [2],
            })
        assert 400 <= err.value.status_code < 500


@pytest.mark.asyncio
async def test_missing_state_csv_is_rejected(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        # Point the branch at a run dir that has no state history yet.
        nodes[2]["meta"]["gaworld"]["run_dir"] = os.path.join(tmp, "empty")
        with pytest.raises(HTTPException) as err:
            await _run(compare_branches, nodes, {
                "baseline_node": 1, "branch_nodes": [2],
            })
        assert 400 <= err.value.status_code < 500


# ---------------------------------------------------------------------------
# Manifest synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_synthesis_carries_baseline_worlds_and_provenance(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, csvs = _completed_tree(tmp)
        body = await _run(compare_branches, nodes, {
            "baseline_node": 1, "branch_nodes": [2],
        })
        manifest = body["manifest"] if "manifest" in body else body.get("request_manifest")
        assert manifest, f"no manifest in response: {sorted(body)}"
        spec = manifest["spec"]
        assert spec["baseline_id"] == "1"
        world_ids = {w["id"] for w in spec["worlds"]}
        assert world_ids == {"1", "2"}
        by_id = {w["id"]: w for w in spec["worlds"]}
        assert by_id["2"]["label"] == "干预"
        # Branch provenance rides in events/config, not in a new schema.
        provenance = json.dumps(by_id["2"], ensure_ascii=False, default=str)
        assert "限行" in provenance
        assert manifest["worlds"]["1"]["state_csv"].endswith(
            os.path.join("base", "state", "agent_state_history.csv")
        )
        assert manifest["worlds"]["2"]["state_csv"].endswith(
            os.path.join("treat", "state", "agent_state_history.csv")
        )


# ---------------------------------------------------------------------------
# GAWorld availability & persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gaworld_unavailable_is_a_clean_error(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        # Whatever availability seam the route uses, a missing GAWorld must
        # come back as a tidy 4xx/503 with a message — no traceback text.
        with patch.object(
            experiments_routes, "resolve_gaworld_path", return_value=None, create=True
        ), patch.dict(os.environ, {"GAWORLD_PATH": ""}):
            try:
                body, status = None, None
                result = await _run(compare_branches, nodes, {
                    "baseline_node": 1, "branch_nodes": [2],
                })
                body, status = (result if isinstance(result, tuple) else (result, 200))
            except HTTPException as err:
                status, body = err.status_code, {"detail": err.detail}
        assert status is not None and 400 <= status < 600
        assert "Traceback" not in json.dumps(body, default=str)


@pytest.mark.asyncio
async def test_comparison_ref_is_persisted_in_result_meta(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        record = SimpleNamespace(tree=SimpleNamespace(nodes=nodes),
                                 result_meta={}, id=9)
        async def _get(*a, **k):
            return (SimpleNamespace(owner_id=1), record)
        with patch.object(experiments_routes, "get_simulation_and_tree_for_owner", _get):
            await _call(compare_branches, record, {
                "baseline_node": 1, "branch_nodes": [2],
            })
        assert record.result_meta, "comparison ref not persisted in result_meta"
        blob = json.dumps(record.result_meta, default=str)
        assert "compare" in blob or "comparison" in blob
        # Lightweight reference only: the state CSVs' CONTENT must not be
        # inlined into the DB record.
        assert "agent_id,step,metric,value" not in blob


# ---------------------------------------------------------------------------
# Secrets sentinel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_secrets_leak_into_the_response(compare_branches):
    with tempfile.TemporaryDirectory() as tmp:
        nodes, _ = _completed_tree(tmp)
        nodes[2]["meta"]["gaworld"]["api_key"] = "Sk-SENTINEL-SECRET-000"
        nodes[2]["meta"]["llm_routing_secret"] = "Sk-SENTINEL-SECRET-111"
        body = await _run(compare_branches, nodes, {
            "baseline_node": 1, "branch_nodes": [2],
        })
        blob = json.dumps(body, default=str)
        assert "Sk-SENTINEL-SECRET-000" not in blob
        assert "Sk-SENTINEL-SECRET-111" not in blob
