"""Per-parent Advance in-flight idempotency — task 2913.

Pins the duplicate-submit fix for tree advance endpoints:

* A duplicate ``advance_chain`` on the same parent while one is in flight
  gets an immediate 409 (it must NOT silently queue on ``_advance_lock``
  and then create a duplicate sibling child — the "empty node 2" defect).
* ``steps=2`` chains still yield 0→1→2, not siblings.
* Independent parents advance concurrently with no false 409.
* Failure releases the claim so a retry is accepted.
* A 409 must not mutate persisted tree state.

Mock LLM/runtime throughout — no live servers, no DB (route dependencies
are monkeypatched in-process, mirroring tests/core/test_simtree_ownership.py).
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
# Mock infrastructure (mirrors tests/core/test_simtree_ownership.py)
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
    def __init__(self, agents=None):
        self.agents = agents or {}
        self.scene = MockScene()
        self.event_queue = MockEventQueue()
        self.ordering = MockOrdering()
        self.turns = 0
        self.log_event = None

    def serialize(self):
        return {
            "agents": {n: {"name": n} for n in self.agents},
            "scene": {"TYPE": "mock"},
            "turns": self.turns,
        }

    @classmethod
    def deserialize(cls, data, clients, log_handler=None):
        sim = cls()
        sim.agents = {n: MockAgent(n) for n in data.get("agents", {})}
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


def _make_tree(agent_names=("Alice", "Bob")):
    sim = FakeSim(agents={name: MockAgent(name) for name in agent_names})
    return SimTree.new(sim, {"mock": object()})


def _make_record(tree=None):
    return SimTreeRecord(tree or _make_tree())


# ---------------------------------------------------------------------------
# Route-invocation harness (monkeypatched dependencies, no HTTP server)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _fake_session():
    yield SimpleNamespace(
        commit=lambda: asyncio.sleep(0),
        get=lambda *a, **k: _async_none(),
    )


async def _async_none():
    return None


def _patch_route_deps(monkeypatch, record):
    from fos.backend.api.routes.simulations import tree_operations as to_mod

    async def fake_user(session, token):
        return SimpleNamespace(id="u1")

    async def fake_lookup(session, user_id, simulation_id):
        return SimpleNamespace(id=simulation_id, latest_state=None), record

    monkeypatch.setattr(to_mod, "get_session", _fake_session)
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


# ---------------------------------------------------------------------------
# Case 1 — concurrent duplicate on the same parent → 409, exactly one child
# ---------------------------------------------------------------------------


class TestConcurrentDuplicate:
    @pytest.mark.asyncio
    async def test_second_request_409s_immediately_one_child(self, monkeypatch):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            entered.set()
            await release.wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        record = _make_record()
        first = asyncio.create_task(_call_advance_chain(monkeypatch, record, 0))

        await asyncio.wait_for(entered.wait(), timeout=2)

        # The duplicate must fail fast — BEFORE the first run finishes.
        with pytest.raises(HTTPException) as excinfo:
            await asyncio.wait_for(_call_advance_chain(monkeypatch, record, 0), timeout=2)
        assert excinfo.value.status_code == 409
        assert "already advancing" in str(excinfo.value.detail)

        release.set()
        result = await asyncio.wait_for(first, timeout=2)

        children = [nid for nid, n in record.tree.nodes.items() if n["parent"] == 0 and nid != 0]
        assert children == [result["child"]], "duplicate submit must not create a second sibling"
        assert result["child"] == 1
        assert record.advancing_parents == set(), "claim must be released after success"

    @pytest.mark.asyncio
    async def test_same_parent_after_terminal_is_allowed(self, monkeypatch):
        """After the in-flight advance completes, a new advance on the same
        parent is a deliberate new branch and must be accepted."""
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        async def fast_runner(simulator, max_turns=1):
            simulator.run(max_turns)
            return None

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", fast_runner)
        record = _make_record()
        await _call_advance_chain(monkeypatch, record, 0)
        result = await _call_advance_chain(monkeypatch, record, 0)
        assert result["child"] == 2


# ---------------------------------------------------------------------------
# Case 2 — steps=2 chain still yields 0→1→2, not siblings
# ---------------------------------------------------------------------------


class TestChainSemantics:
    @pytest.mark.asyncio
    async def test_steps2_chains_under_first_child(self, monkeypatch):
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        async def fast_runner(simulator, max_turns=1):
            simulator.run(max_turns)
            return None

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", fast_runner)
        record = _make_record()
        result = await _call_advance_chain(monkeypatch, record, 0, turns=2)
        assert result["child"] == 2
        assert record.tree.nodes[1]["parent"] == 0
        assert record.tree.nodes[2]["parent"] == 1, "steps=2 must chain, not fan out siblings"


# ---------------------------------------------------------------------------
# Case 3 — independent parents: no false 409
# ---------------------------------------------------------------------------


class TestIndependentParents:
    @pytest.mark.asyncio
    async def test_concurrent_advances_on_different_parents_both_accepted(self, monkeypatch):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            entered.set()
            await release.wait()
            simulator.run(max_turns)
            return None

        from fos.backend.api.routes.simulations import tree_operations as to_mod

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)

        record = _make_record()
        tree = record.tree
        one = tree.branch(0, [])
        two = tree.branch(0, [])

        t1 = asyncio.create_task(_call_advance_chain(monkeypatch, record, one))
        await asyncio.wait_for(entered.wait(), timeout=2)
        release.set()
        entered.clear()

        t2 = asyncio.create_task(_call_advance_chain(monkeypatch, record, two))
        await asyncio.wait_for(entered.wait(), timeout=2)
        release.set()

        r1 = await asyncio.wait_for(t1, timeout=2)
        r2 = await asyncio.wait_for(t2, timeout=2)
        assert tree.nodes[r1["child"]]["parent"] == one
        assert tree.nodes[r2["child"]]["parent"] == two
        assert r1["child"] != r2["child"]


# ---------------------------------------------------------------------------
# Case 4 — failure (and cancel) release the claim
# ---------------------------------------------------------------------------


class TestFailureReleasesClaim:
    @pytest.mark.asyncio
    async def test_runner_exception_releases_claim(self, monkeypatch):
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        async def failing_runner(simulator, max_turns=1):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", failing_runner)
        record = _make_record()

        with pytest.raises(RuntimeError):
            await _call_advance_chain(monkeypatch, record, 0)
        assert 0 not in record.advancing_parents

        # Retry after failure is accepted.
        async def ok_runner(simulator, max_turns=1):
            simulator.run(max_turns)
            return None

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", ok_runner)
        result = await _call_advance_chain(monkeypatch, record, 0)
        assert tree_child_of(record.tree, 0) is not None
        assert result["child"] >= 1

    @pytest.mark.asyncio
    async def test_cancelled_run_releases_claim(self, monkeypatch):
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        async def hanging_runner(simulator, max_turns=1):
            await asyncio.sleep(60)

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", hanging_runner)
        record = _make_record()

        task = asyncio.create_task(_call_advance_chain(monkeypatch, record, 0))
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert 0 not in record.advancing_parents


def tree_child_of(tree, parent):
    for nid, node in tree.nodes.items():
        if node["parent"] == parent and nid != parent:
            return nid
    return None


# ---------------------------------------------------------------------------
# Case 5 — 409 must not mutate tree state
# ---------------------------------------------------------------------------


class TestNoStateMutationOn409:
    @pytest.mark.asyncio
    async def test_duplicate_leaves_tree_untouched(self, monkeypatch):
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_runner(simulator, max_turns=1):
            entered.set()
            await release.wait()
            simulator.run(max_turns)
            return None

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)
        record = _make_record()
        tree = record.tree
        first = asyncio.create_task(_call_advance_chain(monkeypatch, record, 0))
        await asyncio.wait_for(entered.wait(), timeout=2)

        snapshot = tree.serialize()
        with pytest.raises(HTTPException):
            await asyncio.wait_for(_call_advance_chain(monkeypatch, record, 0), timeout=2)
        after_snapshot = tree.serialize()

        assert snapshot == after_snapshot, "409 must not add nodes or edges"
        release.set()
        await asyncio.wait_for(first, timeout=2)

    @pytest.mark.asyncio
    async def test_multi_and_chain_claims_are_per_parent(self, monkeypatch):
        """advance_multi(parent=0) blocks a duplicate advance_chain(0) — and
        vice versa: the claim is per (simulation, parent), not per endpoint."""
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        async def blocked_runner(simulator, max_turns=1):
            await asyncio.sleep(60)

        monkeypatch.setattr(to_mod, "run_simulator_for_advance", blocked_runner)
        record = _make_record()
        mod = _patch_route_deps(monkeypatch, record)

        task = asyncio.create_task(
            _handler(mod, "simulation_tree_advance_multi")(
                request=MagicMock(),
                simulation_id="SIM",
                data=SimpleNamespace(parent=0, count=2, turns=1),
            )
        )
        await asyncio.sleep(0)

        with pytest.raises(HTTPException) as excinfo:
            await asyncio.wait_for(_call_advance_chain(monkeypatch, record, 0), timeout=2)
        assert excinfo.value.status_code == 409

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert record.advancing_parents == set()
