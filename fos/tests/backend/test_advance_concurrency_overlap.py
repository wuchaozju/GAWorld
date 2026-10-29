"""Concurrency of independent SimTree advances — task 2925 (RED tests).

Pins the target semantics for narrowing ``record._advance_lock`` in
``advance_chain`` (see research RESULT-2924):

* TRUE OVERLAP: two ``advance_chain`` requests on *different* parents must
  both start their simulator runs before either is released. Today the
  record-global ``_advance_lock`` (tree_operations.py:572) serializes them,
  so that test FAILS on current code — it guards the future fix.
* The fix keeps: per-parent 409, short persist lock (serialize+commit,
  no lost update), cancel/failure isolation, intervention isolation,
  per-node task isolation, and sequential steps inside one chain request.

Mock LLM/runtime throughout — no live servers, no DB (route dependencies
are monkeypatched in-process, mirroring tests/backend/test_advance_idempotency.py).
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fos.backend.services.simtree_registry_lifecycle import SimTreeRecord
from fos.core.simtree import SimTree
from litestar.exceptions import HTTPException

# ---------------------------------------------------------------------------
# Mock infrastructure (mirrors test_advance_idempotency.py, plus: sims carry
# a ``label`` through serialize/deserialize so runners can identify which
# branch they belong to, preserve ``turns`` for chain-sequencing assertions,
# and own a private ``intervention_queue`` per instance)
# ---------------------------------------------------------------------------


class MockMemory:
    def __init__(self):
        self.history = []

    def get_all(self):
        return self.history

    def append(self, role, content):
        self.history.append({"role": role, "content": content})

    def __len__(self):
        return len(self.history)


class MockAgent:
    def __init__(self, name):
        self.name = name
        self.short_memory = MockMemory()
        self.plan_state = None
        self.properties = {}
        self.knowledge_base = []
        self.documents = {}
        self.language = "en"
        self.last_history_length = 1
        self.consecutive_llm_errors = 0
        self.is_offline = False
        self.log_event = None
        self.role_prompt = ""
        self.user_profile = ""

    def add_env_feedback(self, msg, images=None):
        pass


class MockConfig:
    def __init__(self):
        self.parameters = {}
        self.description = ""
        self.social_network = {}
        self.actions = []


class MockScene:
    TYPE = "mock"

    def __init__(self):
        self.state = {}
        self.config = MockConfig()
        self.runner = None


class MockOrdering:
    def serialize(self):
        return {"type": "mock_ordering", "state": {}}


class MockEventQueue:
    def empty(self):
        return True


class FakeSim:
    def __init__(self, agents=None, label=""):
        self.agents = agents or {}
        self.label = label
        self.scene = MockScene()
        self.event_queue = MockEventQueue()
        self.ordering = MockOrdering()
        self.turns = 0
        self.log_event = None
        # Per-simulator (hence per-node) private state — in production these
        # live inside the branch's private scene/output dir (RESULT-2924 §3).
        self.intervention_queue: list[str] = []

    def serialize(self):
        return {
            "agents": {n: {"name": n} for n in self.agents},
            "scene": {"TYPE": "mock"},
            "turns": self.turns,
            "label": self.label,
        }

    @classmethod
    def deserialize(cls, data, clients, log_handler=None):
        sim = cls()
        sim.agents = {n: MockAgent(n) for n in data.get("agents", {})}
        sim.turns = int(data.get("turns", 0))
        sim.label = data.get("label", "")
        return sim

    def run(self, max_turns):
        self.turns += max_turns

    def reset_event_queue(self):
        pass

    def broadcast(self, event):
        pass

    def emit_remaining_events(self):
        pass


@pytest.fixture(autouse=True)
def _patch_simulator():
    with patch("fos.core.simtree.Simulator", FakeSim):
        yield


@pytest.fixture(autouse=True)
def _clear_runtime_tasks():
    from fos.backend.api.routes.simulations import tree_operations as to_mod

    to_mod.RUNTIME_TASKS.clear()
    yield
    to_mod.RUNTIME_TASKS.clear()


def _make_tree(agent_names=("Alice", "Bob")):
    sim = FakeSim(agents={name: MockAgent(name) for name in agent_names})
    return SimTree.new(sim, {"mock": object()})


def _make_record(tree=None):
    return SimTreeRecord(tree or _make_tree())


# ---------------------------------------------------------------------------
# Route-invocation harness (monkeypatched dependencies, no HTTP server)
# ---------------------------------------------------------------------------


class FakeSimRow:
    """Stand-in for the DB ``Simulation`` row, capturing persisted state."""

    def __init__(self):
        self.latest_state = None


def _make_fake_session(row: FakeSimRow):
    @contextlib.asynccontextmanager
    async def fake_session():
        async def _get(*a, **k):
            return row

        yield SimpleNamespace(commit=lambda: asyncio.sleep(0), get=_get)

    return fake_session


def _patch_route_deps(monkeypatch, record, row=None):
    from fos.backend.api.routes.simulations import tree_operations as to_mod

    async def fake_user(session, token):
        return SimpleNamespace(id="u1")

    async def fake_lookup(session, user_id, simulation_id):
        return SimpleNamespace(id=simulation_id, latest_state=None), record

    monkeypatch.setattr(to_mod, "get_session", _make_fake_session(row or FakeSimRow()))
    monkeypatch.setattr(to_mod, "resolve_current_user", fake_user)
    monkeypatch.setattr(to_mod, "get_simulation_and_tree_for_owner", fake_lookup)
    monkeypatch.setattr(to_mod, "extract_bearer_token", lambda request: "t")
    monkeypatch.setattr(
        to_mod,
        "get_settings",
        lambda: SimpleNamespace(
            max_advance_turns_per_request=100,
            max_advance_multi_count=10,
            max_frontier_nodes_per_request=50,
        ),
    )
    return to_mod


def _handler(mod, name):
    raw = getattr(getattr(mod, name), "fn", getattr(mod, name))
    return raw


async def _call_advance_chain(monkeypatch, record, parent, turns=1):
    mod = _patch_route_deps(monkeypatch, record)
    payload = SimpleNamespace(parent=parent, turns=turns)
    return await _handler(mod, "simulation_tree_advance_chain")(
        request=MagicMock(), simulation_id="SIM", data=payload
    )


def _children_of(tree, parent):
    return [
        nid
        for nid, n in tree.nodes.items()
        if n["parent"] == parent and nid != parent
    ]


# ---------------------------------------------------------------------------
# Test 1 — TRUE OVERLAP on different parents (RED today: _advance_lock
# serializes the whole run, so the second runner never starts first)
# ---------------------------------------------------------------------------


class TestTrueOverlapOnDifferentParents:
    async def test_different_parent_advances_both_start_before_any_release(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"
        tree.nodes[b]["sim"].label = "B"

        started = {"A": asyncio.Event(), "B": asyncio.Event()}
        release = {"A": asyncio.Event(), "B": asyncio.Event()}

        async def blocked_runner(simulator, max_turns=1):
            started[simulator.label].set()
            await release[simulator.label].wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        t1 = asyncio.create_task(_call_advance_chain(monkeypatch, record, a))
        t2 = asyncio.create_task(_call_advance_chain(monkeypatch, record, b))

        # Neither runner may be released before BOTH have started.
        await asyncio.wait_for(started["A"].wait(), timeout=2)
        await asyncio.wait_for(started["B"].wait(), timeout=2)

        release["A"].set()
        release["B"].set()
        r1 = await asyncio.wait_for(t1, timeout=2)
        r2 = await asyncio.wait_for(t2, timeout=2)
        assert tree.nodes[r1["child"]]["parent"] == a
        assert tree.nodes[r2["child"]]["parent"] == b


# ---------------------------------------------------------------------------
# Test 2 — SAME-PARENT 409 while a different-parent advance still starts
# (must pass before AND after the lock fix)
# ---------------------------------------------------------------------------


class TestSameParentConflict:
    async def test_same_parent_409_other_parent_starts(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[b]["sim"].label = "B"

        started_a = asyncio.Event()
        started_b = asyncio.Event()
        release_a = asyncio.Event()
        release_b = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            if simulator.label == "B":
                started_b.set()
                await release_b.wait()
            else:
                started_a.set()
                await release_a.wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        first = asyncio.create_task(_call_advance_chain(monkeypatch, record, a))
        await asyncio.wait_for(started_a.wait(), timeout=2)
        assert a in record.advancing_parents

        # Duplicate on the SAME parent → immediate 409, no queuing — the
        # duplicate must fail fast while A is still running.
        with pytest.raises(HTTPException) as excinfo:
            await asyncio.wait_for(_call_advance_chain(monkeypatch, record, a), timeout=2)
        assert excinfo.value.status_code == 409

        # A DIFFERENT parent is accepted (no 409) and its runner does start —
        # strictly-before-A finishes is pinned by TestTrueOverlap above; here
        # we pin acceptance + eventual start, valid before AND after the fix.
        second = asyncio.create_task(_call_advance_chain(monkeypatch, record, b))
        release_a.set()
        await asyncio.wait_for(started_b.wait(), timeout=2)

        release_b.set()
        await asyncio.wait_for(first, timeout=2)
        await asyncio.wait_for(second, timeout=2)
        assert record.advancing_parents == set()


# ---------------------------------------------------------------------------
# Test 3 — PERSISTENCE: near-simultaneous finishes must not lose updates
# ---------------------------------------------------------------------------


class TestPersistenceNoLostUpdate:
    async def test_concurrent_finishes_persist_both_children(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"
        tree.nodes[b]["sim"].label = "B"

        started = {"A": asyncio.Event(), "B": asyncio.Event()}
        release = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            started[simulator.label].set()
            await release.wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        row = FakeSimRow()

        async def call(parent):
            mod = _patch_route_deps(monkeypatch, record, row)
            payload = SimpleNamespace(parent=parent, turns=1)
            return await _handler(mod, "simulation_tree_advance_chain")(
                request=MagicMock(), simulation_id="SIM", data=payload
            )

        t1 = asyncio.create_task(call(a))
        t2 = asyncio.create_task(call(b))
        # If overlap is impossible today this still passes (serialized); the
        # test pins that WHEN they finish nearly simultaneously, no update is lost.
        await asyncio.wait_for(started["A"].wait(), timeout=2)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(started["B"].wait(), timeout=0.2)

        release.set()
        r1 = await asyncio.wait_for(t1, timeout=2)
        r2 = await asyncio.wait_for(t2, timeout=2)

        # Both requests completed.
        assert record.advancing_parents == set()
        assert record.running == set()

        # The last committed snapshot holds BOTH completed children.
        persisted = row.latest_state
        assert persisted is not None, "both advances finished — state must be persisted"
        reloaded = SimTree.deserialize(persisted, {"mock": object()})
        assert r1["child"] in reloaded.nodes, "first child lost from persisted snapshot"
        assert r2["child"] in reloaded.nodes, "second child lost from persisted snapshot (lost update)"
        assert reloaded.nodes[r1["child"]]["parent"] == a
        assert reloaded.nodes[r2["child"]]["parent"] == b
        # Terminal metadata: the live tree marks no pending runtime failure.
        for nid in (r1["child"], r2["child"]):
            assert tree.nodes[nid]["meta"].get("runtime_status") != "failed"

        # serialize → reload → deserialize round trip preserves both.
        again = SimTree.deserialize(tree.serialize(), {"mock": object()})
        assert r1["child"] in again.nodes and r2["child"] in again.nodes


# ---------------------------------------------------------------------------
# Test 4 — CANCEL ISOLATION: cancelling one branch leaves the other intact
# ---------------------------------------------------------------------------


class TestCancelIsolation:
    async def test_cancel_one_parent_other_completes(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"
        tree.nodes[b]["sim"].label = "B"

        started = {"A": asyncio.Event(), "B": asyncio.Event()}
        release = {"A": asyncio.Event(), "B": asyncio.Event()}

        async def blocked_runner(simulator, max_turns=1):
            started[simulator.label].set()
            await release[simulator.label].wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        t1 = asyncio.create_task(_call_advance_chain(monkeypatch, record, a))
        t2 = asyncio.create_task(_call_advance_chain(monkeypatch, record, b))
        await asyncio.wait_for(started["A"].wait(), timeout=2)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(started["B"].wait(), timeout=0.2)

        t1.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t1

        # A's parent claim is released.
        assert a not in record.advancing_parents, "cancel must release the claim"

        # B continues and completes.
        release["B"].set()
        r2 = await asyncio.wait_for(t2, timeout=2)
        assert tree.nodes[r2["child"]]["parent"] == b
        assert record.advancing_parents == set()


# ---------------------------------------------------------------------------
# Test 5 — PROVIDER FAILURE: one branch failing must not skip the other
# ---------------------------------------------------------------------------


class TestProviderFailureIsolation:
    async def test_one_branch_fails_other_completes_and_failure_recorded(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"
        tree.nodes[b]["sim"].label = "B"

        started = {"A": asyncio.Event(), "B": asyncio.Event()}
        release = {"A": asyncio.Event(), "B": asyncio.Event()}

        async def blocked_runner(simulator, max_turns=1):
            started[simulator.label].set()
            if simulator.label == "A":
                # Real run_simulator_for_advance surfaces provider errors as
                # RuntimeError returns, not exceptions — fail fast.
                return RuntimeError("provider exploded")
            await release[simulator.label].wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        r1 = await asyncio.wait_for(_call_advance_chain(monkeypatch, record, a), timeout=2)
        # The chain route returns the failed node (with recorded runtime_status)
        # instead of raising — the failure is visible on the node.

        # B is still accepted and starts while A's failure is recorded.
        t2 = asyncio.create_task(_call_advance_chain(monkeypatch, record, b))
        await asyncio.wait_for(started["B"].wait(), timeout=2)
        release["B"].set()
        r2 = await asyncio.wait_for(t2, timeout=2)

        # A's failure is semantically a FAILED node — not a silently skipped agent.
        failed_child = r1["child"]
        failed_meta = tree.nodes[failed_child]["meta"]
        assert failed_meta.get("runtime_status") == "failed"
        assert "provider exploded" in failed_meta.get("runtime_error", "")

        # B completed normally.
        assert tree.nodes[r2["child"]]["parent"] == b
        assert tree.nodes[r2["child"]]["meta"].get("runtime_status") != "failed"
        assert a not in record.advancing_parents
        assert record.advancing_parents == set()


# ---------------------------------------------------------------------------
# Test 6 — INTERVENTION ISOLATION: concurrent branches never share queues
# ---------------------------------------------------------------------------


class TestInterventionIsolation:
    async def test_intervention_reaches_only_its_branch(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"
        tree.nodes[b]["sim"].label = "B"

        started = {"A": asyncio.Event(), "B": asyncio.Event()}
        release = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            started[simulator.label].set()
            if simulator.label == "A":
                # Intervention X is queued for branch A while both run.
                simulator.intervention_queue.append("X")
            await release.wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        t1 = asyncio.create_task(_call_advance_chain(monkeypatch, record, a))
        t2 = asyncio.create_task(_call_advance_chain(monkeypatch, record, b))
        await asyncio.wait_for(started["A"].wait(), timeout=2)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(started["B"].wait(), timeout=0.2)

        release.set()
        await asyncio.wait_for(t1, timeout=2)
        await asyncio.wait_for(t2, timeout=2)

        child_a = _children_of(tree, a)[0]
        child_b = _children_of(tree, b)[0]
        assert tree.nodes[child_a]["sim"].intervention_queue == ["X"]
        assert tree.nodes[child_b]["sim"].intervention_queue == [], (
            "control branch must not see branch A's intervention"
        )
        # Structural isolation: the two queues are distinct objects.
        assert (
            tree.nodes[child_a]["sim"].intervention_queue
            is not tree.nodes[child_b]["sim"].intervention_queue
        )


# ---------------------------------------------------------------------------
# Test 7 — TASK ISOLATION: distinct task ids, running nodes, sims
# ---------------------------------------------------------------------------


class TestTaskIsolation:
    async def test_concurrent_advances_register_distinct_tasks_and_nodes(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        b = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"
        tree.nodes[b]["sim"].label = "B"

        started = {"A": asyncio.Event(), "B": asyncio.Event()}
        release = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            started[simulator.label].set()
            await release.wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        t1 = asyncio.create_task(_call_advance_chain(monkeypatch, record, a))
        t2 = asyncio.create_task(_call_advance_chain(monkeypatch, record, b))
        await asyncio.wait_for(started["A"].wait(), timeout=2)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(started["B"].wait(), timeout=0.2)
        release.set()
        r1 = await asyncio.wait_for(t1, timeout=2)
        r2 = await asyncio.wait_for(t2, timeout=2)

        child_a, child_b = r1["child"], r2["child"]
        assert child_a != child_b

        # Distinct simulator instances (deep-copy isolation).
        assert tree.nodes[child_a]["sim"] is not tree.nodes[child_b]["sim"]

        # Distinct task registrations — one node_advance task id per node.
        snapshot = to_mod.RUNTIME_TASKS.snapshot(limit=50)
        tasks = snapshot.get("tasks", snapshot.get("recent", []))
        node_tasks = {
            t["id"] for t in tasks if str(t.get("id", "")).startswith("node_advance:SIM:")
        }
        assert node_tasks >= {
            f"node_advance:SIM:{child_a}",
            f"node_advance:SIM:{child_b}",
        }, f"expected one node_advance task id per node, got {sorted(node_tasks)}"

        # All runs finished — running set must be empty.
        assert record.running == set()


# ---------------------------------------------------------------------------
# Test 8 — CHAIN: turns=2 steps sequentially within one request
# ---------------------------------------------------------------------------


class TestChainSequentialSteps:
    async def test_chain_two_turns_run_sequentially_under_parent(self, monkeypatch):
        tree = _make_tree()
        record = _make_record(tree)
        a = tree.branch(0, [])
        tree.nodes[a]["sim"].label = "A"

        calls = []

        async def recording_runner(simulator, max_turns=1):
            calls.append({"turns_before": simulator.turns, "max_turns": max_turns})
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", recording_runner)

        result = await _call_advance_chain(monkeypatch, record, a, turns=2)

        assert len(calls) == 2, "turns=2 must run the simulator exactly twice"
        # Sequential: the second step starts from the first step's output sim.
        assert calls[1]["turns_before"] == calls[0]["turns_before"] + calls[0]["max_turns"], (
            "step 2 must consume step 1's simulator state (sequential, not parallel)"
        )
        final_child = result["child"]
        chain = _children_of(tree, a)
        assert len(chain) == 1, "the chain head is the only direct child of A"
        assert tree.nodes[chain[0]]["parent"] == a
        grandchildren = _children_of(tree, chain[0])
        assert grandchildren == [final_child], "step 2 must chain under step 1, not fan out"
        assert record.advancing_parents == set()
