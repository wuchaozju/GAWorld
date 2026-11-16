"""SimTree node ownership / lineage — TDD RED tests (task 2820).

Specifies the ownership fix from SPEC-simtree-ownership.md:

* Topology: ``branch(A)`` creates a CHILD of A (clone FROM A, depth A+1) —
  never an implicit sibling cloned from A's parent. Root branching is
  unchanged.
* ``fork_from_checkpoint(A, cp, count=2)`` → B and C are both children of A,
  with distinct ids, distinct simulator objects, and per-node deep-copied
  checkpoint refs in ``meta``.
* Simulator isolation: siblings share no agents/queue/logs/meta objects;
  mutating B leaves C untouched.
* Log ownership: ``node.logs`` contains only events produced by that node.
  Ancestry history is assembled at read time by walking the parent chain
  (root → … → selected); sibling events never cross into another sibling's
  stream (REST endpoint) or WS stream (per-node subscription).
* Run ownership: advancing from B creates a child of B.
* Experiment reruns: a second run must NOT reuse the variant's node —
  every execution attempt gets a fresh node; the completed run's node,
  logs and sim are immutable; run provenance is recorded in
  ``run.result_meta["variant_nodes"]``.
* GAWorld filesystem isolation: sibling branch dirs get distinct writable
  roots (run output, state/history, logs, checkpoints, interventions) via
  ``branch_runtime_overrides``; a marker written in B's runtime dirs never
  appears in C's.

Every test here must fail because the OWNERSHIP behaviour is missing, not
because of a syntax error. Mock LLM/runtime throughout — no live servers.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fos.core.simtree import SimTree


# ---------------------------------------------------------------------------
# Mock infrastructure (mirrors tests/core/test_simtree_operations.py)
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

    def on_event(self, sim, event_type, payload):
        pass

    def on_private_event(self, sim, event_type, payload, receivers):
        pass


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


def _emit(node, kind: str, payload: dict) -> dict:
    """Emit one event through the node's own log handler (as the sim would)."""
    entry_probe: list = []
    node["sim"].log_event(kind, payload)
    return node["logs"][-1]


# ===================================================================
# Group 1 — Topology: branch() child semantics
# ===================================================================


class TestBranchTopology:
    def test_branch_from_root_creates_child_with_depth_one(self):
        tree = _make_tree()
        a = tree.branch(0, [])
        assert tree.nodes[a]["parent"] == 0
        assert tree.nodes[a]["depth"] == tree.nodes[0]["depth"] + 1

    def test_branch_from_nonroot_creates_child_of_selected(self):
        """branch(A) → B.parent == A (Bug B: must NOT hop to A's parent)."""
        tree = _make_tree()
        a = tree.branch(0, [])
        b = tree.branch(a, [])
        assert tree.nodes[b]["parent"] == a, (
            "branch(A) must create a child of A, not a sibling of A"
        )
        assert tree.nodes[b]["depth"] == tree.nodes[a]["depth"] + 1

    def test_branch_clones_state_FROM_selected_node(self):
        """The clone must inherit the selected node's mutated state, not the
        grandparent's."""
        tree = _make_tree()
        a = tree.branch(0, [{"op": "agent_props_patch", "name": "Alice",
                             "updates": {"mood": "happy"}}])
        b = tree.branch(a, [])
        assert tree.nodes[b]["sim"].agents["Alice"].properties.get("mood") == "happy", (
            "branch(A) clone must carry A's ops-applied state"
        )

    def test_fork_from_checkpoint_children_are_children_of_source(self):
        tree = _make_tree()
        a = tree.branch(0, [])
        cp = {"checkpoint_id": "cp-1", "run_dir": "/tmp/run"}
        b, c = tree.fork_from_checkpoint(a, cp, count=2)
        assert tree.nodes[b]["parent"] == a
        assert tree.nodes[c]["parent"] == a
        assert b != c
        assert tree.nodes[b]["sim"] is not tree.nodes[c]["sim"]
        assert tree.nodes[b]["depth"] == tree.nodes[a]["depth"] + 1
        assert tree.nodes[c]["depth"] == tree.nodes[a]["depth"] + 1

    def test_fork_children_get_deep_copied_checkpoint_refs(self):
        tree = _make_tree()
        a = tree.branch(0, [])
        cp = {"checkpoint_id": "cp-1", "run_dir": "/tmp/run"}
        b, c = tree.fork_from_checkpoint(a, cp, count=2)
        ref_b = tree.nodes[b]["meta"]["checkpoint"]
        ref_c = tree.nodes[c]["meta"]["checkpoint"]
        assert ref_b == ref_c == cp
        ref_b["checkpoint_id"] = "mutated-by-b"
        assert ref_c["checkpoint_id"] == "cp-1", (
            "B's checkpoint update must never leak into C.meta"
        )


# ===================================================================
# Group 2 — Simulator isolation between siblings
# ===================================================================


class TestSiblingSimulatorIsolation:
    def _make_siblings(self):
        tree = _make_tree()
        a = tree.branch(0, [])
        b, c = tree.fork_from_checkpoint(a, {"checkpoint_id": "cp"}, count=2)
        return tree, a, b, c

    def test_sibling_sims_are_distinct_objects(self):
        tree, a, b, c = self._make_siblings()
        assert tree.nodes[b]["sim"] is not tree.nodes[c]["sim"]
        assert tree.nodes[b]["sim"] is not tree.nodes[a]["sim"]

    def test_sibling_runtime_state_distinct_objects(self):
        tree, a, b, c = self._make_siblings()
        nb, nc = tree.nodes[b], tree.nodes[c]
        assert nb["sim"].agents is not nc["sim"].agents
        assert nb["sim"].event_queue is not nc["sim"].event_queue
        assert nb["logs"] is not nc["logs"]
        assert nb["meta"] is not nc["meta"]
        assert nb["sim"].scene is not nc["sim"].scene

    def test_mutating_b_leaves_c_unchanged(self):
        tree, a, b, c = self._make_siblings()
        tree.nodes[b]["sim"].agents["Alice"].properties["mood"] = "b-mood"
        tree.nodes[b]["meta"]["marker"] = "from-b"
        tree.nodes[b]["logs"].append({"type": "test", "data": "only-b"})
        assert tree.nodes[c]["sim"].agents["Alice"].properties.get("mood") != "b-mood"
        assert "marker" not in tree.nodes[c]["meta"]
        assert all(e.get("data") != "only-b" for e in tree.nodes[c]["logs"])


# ===================================================================
# Group 3 — Log ownership: node-local logs + ancestry read model
# ===================================================================


class TestLogOwnership:
    def _make_family(self):
        """root → A → {B, C}; each node emits one distinguishable event."""
        tree = _make_tree()
        a = tree.branch(0, [])
        b, c = tree.fork_from_checkpoint(a, {"checkpoint_id": "cp"}, count=2)
        _emit(tree.nodes[0], "info", {"text": "e-root"})
        _emit(tree.nodes[a], "info", {"text": "e-a"})
        _emit(tree.nodes[b], "info", {"text": "ONLY_B"})
        _emit(tree.nodes[c], "info", {"text": "ONLY_C"})
        return tree, a, b, c

    def test_copy_sim_child_starts_with_empty_logs(self):
        """node.logs holds only that node's own events — no inherited copies."""
        tree = _make_tree()
        _emit(tree.nodes[0], "info", {"text": "e-root"})
        cid = tree.copy_sim(0)
        assert tree.nodes[cid]["logs"] == [], (
            "child node must start with EMPTY logs; history is assembled at read time"
        )

    def test_events_stay_node_local_in_storage(self):
        tree, a, b, c = self._make_family()
        assert [e["data"]["text"] for e in tree.nodes[a]["logs"]] == ["e-a"]
        assert [e["data"]["text"] for e in tree.nodes[b]["logs"]] == ["ONLY_B"]
        assert [e["data"]["text"] for e in tree.nodes[c]["logs"]] == ["ONLY_C"]

    def test_every_log_entry_stamps_owning_node(self):
        tree, a, b, c = self._make_family()
        for nid in (a, b, c):
            for entry in tree.nodes[nid]["logs"]:
                assert entry["node"] == nid

    # -- REST endpoint: ancestry assembly (root → … → selected), no siblings --

    def _endpoint(self, tree, node_id):
        from fos.backend.api.routes.simulations import tree_operations as to_mod

        record = SimpleNamespace(tree=tree, running=set())

        @contextlib.asynccontextmanager
        async def fake_session():
            yield object()

        async def fake_user(session, token):
            return SimpleNamespace(id="u1")

        async def fake_lookup(session, user_id, simulation_id):
            return SimpleNamespace(id=simulation_id), record

        monkey = pytest.MonkeyPatch()
        monkey.setattr(to_mod, "get_session", fake_session)
        monkey.setattr(to_mod, "resolve_current_user", fake_user)
        monkey.setattr(to_mod, "get_simulation_and_tree_for_owner", fake_lookup)
        monkey.setattr(to_mod, "extract_bearer_token", lambda request: "t")
        handler = to_mod.simulation_tree_events
        raw = getattr(handler, "fn", handler)  # unwrap the Litestar route decorator
        try:
            return asyncio.run(
                raw(
                    request=MagicMock(), simulation_id="SIM", node_id=int(node_id)
                )
            )
        finally:
            monkey.undo()

    def test_endpoint_node_events_are_node_local_not_descendant_union(self):
        """events(A) must NOT include descendants' (B/C) logs — Bug C."""
        tree, a, b, c = self._make_family()
        events_a = self._endpoint(tree, a)
        texts = {e["data"]["text"] for e in events_a}
        assert "ONLY_B" not in texts, "sibling/descendant B events leaked into A"
        assert "ONLY_C" not in texts, "sibling/descendant C events leaked into A"

    def test_endpoint_history_walks_parent_chain(self):
        tree, a, b, c = self._make_family()
        history_b = self._endpoint(tree, b)
        history_c = self._endpoint(tree, c)
        texts_b = {e["data"]["text"] for e in history_b}
        texts_c = {e["data"]["text"] for e in history_c}
        assert "ONLY_B" in texts_b and "e-a" in texts_b and "e-root" in texts_b
        assert "ONLY_C" in texts_c and "e-a" in texts_c
        assert "ONLY_C" not in texts_b, "cross-sibling contamination in B's history"
        assert "ONLY_B" not in texts_c, "cross-sibling contamination in C's history"

    def test_ws_node_subscription_never_delivers_sibling_events(self):
        tree, a, b, c = self._make_family()
        qb, qc = asyncio.Queue(), asyncio.Queue()
        tree.add_node_sub(b, qb)
        tree.add_node_sub(c, qc)
        _emit(tree.nodes[b], "info", {"text": "LIVE_ONLY_B"})
        _emit(tree.nodes[c], "info", {"text": "LIVE_ONLY_C"})
        got_b = [qb.get_nowait()["data"]["text"]]
        got_c = [qc.get_nowait()["data"]["text"]]
        assert got_b == ["LIVE_ONLY_B"]
        assert got_c == ["LIVE_ONLY_C"]
        assert "LIVE_ONLY_C" not in got_b and "LIVE_ONLY_B" not in got_c


# ===================================================================
# Group 4 — Run ownership: advance from B creates a child of B
# ===================================================================


class TestRunOwnership:
    def test_advance_from_b_creates_child_of_b(self):
        tree = _make_tree()
        a = tree.branch(0, [])
        b = tree.branch(a, [])
        c = tree.advance(b, turns=1)
        assert tree.nodes[c]["parent"] == b, (
            "advancing from B must create a child of B (not of A)"
        )
        assert tree.nodes[c]["sim"].turns == 1

    def test_advance_from_b_does_not_disturb_sibling_c(self):
        tree = _make_tree()
        a = tree.branch(0, [])
        b, c = tree.fork_from_checkpoint(a, {"checkpoint_id": "cp"}, count=2)
        tree.advance(b, turns=3)
        assert tree.nodes[c]["sim"].turns == 0
        assert tree.nodes[c]["sim"] is not tree.nodes[b]["sim"]


# ===================================================================
# Group 5 — Experiment rerun: fresh attempt node, immutable completed run
# ===================================================================


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _FakeSession:
    """Minimal async session: execute(Experiment select) → exp;
    get(Model, id) → run / sim_record / exp."""

    def __init__(self, exp, run, sim_record):
        self._exp = exp
        self._run = run
        self._sim_record = sim_record

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, obj):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt):
        return _FakeResult(self._exp)

    async def get(self, model, key):
        from fos.backend.models.experiment import Experiment, ExperimentRun
        from fos.backend.models.simulation import Simulation

        if model is ExperimentRun:
            return self._run
        if model is Simulation:
            return self._sim_record
        if model is Experiment:
            return self._exp
        return None


class TestExperimentRerunOwnership:
    def _run_worker(self, monkeypatch, tree, variant_node_id, run_id):
        from fos.backend.services import experiment_runner as er

        exp = SimpleNamespace(
            id="exp-1",
            name="exp",
            base_node=0,
            variants=[SimpleNamespace(id=1, name="v1", ops=[], node_id=variant_node_id)],
        )
        run = SimpleNamespace(id=run_id, status=None, result_meta=None, task_id=None)
        sim_record = SimpleNamespace(latest_state=None)
        record = SimpleNamespace(tree=tree, running=set())

        @contextlib.asynccontextmanager
        async def fake_session():
            yield _FakeSession(exp, run, sim_record)

        monkeypatch.setattr(er, "get_session", fake_session)
        monkeypatch.setattr(er, "SIM_TREE_REGISTRY", {"SIM": record})
        monkeypatch.setattr(er, "RUNTIME_TASKS", MagicMock())
        monkeypatch.setattr(er, "_USE_CELERY_EXPERIMENTS", False)
        asyncio.run(er._run_experiment_worker("SIM", "exp-1", run_id, turns=2))
        return exp, run, tree

    def test_rerun_gets_a_fresh_node_not_the_completed_one(self):
        tree = _make_tree()
        monkeypatch = pytest.MonkeyPatch()
        try:
            _, _, tree = self._run_worker(monkeypatch, tree, None, run_id=1)
            run1_node = tree.nodes[1]["meta"]["variant_id"] and next(
                nid
                for nid, n in tree.nodes.items()
                if n["meta"].get("variant_id") == 1
            )
            run1_sim_turns = tree.nodes[run1_node]["sim"].turns
            run1_logs = list(tree.nodes[run1_node]["logs"])

            # Second run with the persisted v.node_id — must NOT reuse it.
            _, run2, tree = self._run_worker(
                monkeypatch, tree, int(run1_node), run_id=2
            )
            run2_nodes = [
                nid
                for nid, n in tree.nodes.items()
                if n["meta"].get("variant_id") == 1
            ]
            assert len(run2_nodes) >= 2, "rerun must create a fresh attempt node"
            assert run1_node not in run2_nodes[1:], None
            latest = tree.nodes[run2_nodes[-1]]
            assert latest["meta"].get("variant_id") == 1
            # Completed run1 node immutable after run2
            assert tree.nodes[run1_node]["sim"].turns == run1_sim_turns
            assert tree.nodes[run1_node]["logs"] == run1_logs
            assert run2 is not None
        finally:
            monkeypatch.undo()

    def test_completed_run_node_is_immutable_after_rerun(self):
        tree = _make_tree()
        monkeypatch = pytest.MonkeyPatch()
        try:
            _, _, tree = self._run_worker(monkeypatch, tree, None, run_id=1)
            run1_node = next(
                nid for nid, n in tree.nodes.items() if n["meta"].get("variant_id") == 1
            )
            snapshot_logs = [dict(e) for e in tree.nodes[run1_node]["logs"]]
            snapshot_turns = tree.nodes[run1_node]["sim"].turns

            self._run_worker(monkeypatch, tree, int(run1_node), run_id=2)

            assert tree.nodes[run1_node]["sim"].turns == snapshot_turns, (
                "run2 must never sim.run() on run1's completed node"
            )
            assert [dict(e) for e in tree.nodes[run1_node]["logs"]] == snapshot_logs, (
                "run1's logs must be unchanged after run2"
            )
        finally:
            monkeypatch.undo()

    def test_run_records_variant_node_provenance_in_result_meta(self):
        tree = _make_tree()
        monkeypatch = pytest.MonkeyPatch()
        try:
            _, run, _ = self._run_worker(monkeypatch, tree, None, run_id=1)
            meta = run.result_meta or {}
            assert meta.get("variant_nodes"), (
                "run.result_meta must record {variant_id: node_id} attempt provenance"
            )
            assert set(meta["variant_nodes"].keys()) == {"1"}
            node = tree.nodes[int(meta["variant_nodes"]["1"])]
            assert node["meta"].get("experiment_id") == "exp-1"
            assert node["meta"].get("run_id") == 1 or node["meta"].get("attempt") == 1, (
                "attempt/run provenance must be stamped on the attempt node meta"
            )
        finally:
            monkeypatch.undo()


# ===================================================================
# Group 6 — GAWorld filesystem isolation between sibling branches
# ===================================================================


class TestGAWorldFilesystemIsolation:
    def _overrides(self, branch_dir: str) -> dict:
        from fos.backend.services.simtree_gaworld import branch_runtime_overrides
        from fos.core.experiment.scenes.gaworld.runtime_modes import (
            merge_nested_overrides,
        )

        return merge_nested_overrides({}, branch_runtime_overrides(branch_dir))

    def test_sibling_branch_dirs_get_distinct_runtime_roots(self, tmp_path):
        dir_b = tmp_path / "branch-b"
        dir_c = tmp_path / "branch-c"
        patch_b = self._overrides(str(dir_b))
        patch_c = self._overrides(str(dir_c))
        for key in ("run_output_dir", "state_output_dir", "log_dir"):
            assert patch_b[key] != patch_c[key], key
            assert str(dir_b) in patch_b[key]
            assert str(dir_c) in patch_c[key]
        assert patch_b["gaworld"]["checkpoint"]["restore_dir"] != patch_c["gaworld"][
            "checkpoint"
        ]["restore_dir"]
        assert patch_b["kernel"]["interventions_path"] != patch_c["kernel"][
            "interventions_path"
        ]

    def test_marker_in_b_runtime_dirs_absent_in_c(self, tmp_path):
        dir_b = tmp_path / "branch-b"
        dir_c = tmp_path / "branch-c"
        patch_b = self._overrides(str(dir_b))
        patch_c = self._overrides(str(dir_c))

        from pathlib import Path as _Path

        b_state = _Path(patch_b["state_output_dir"])
        c_state = _Path(patch_c["state_output_dir"])
        b_state.mkdir(parents=True, exist_ok=True)
        c_state.mkdir(parents=True, exist_ok=True)
        (b_state / "marker.txt").write_text("written-by-B")

        assert (b_state / "marker.txt").exists()
        assert not (c_state / "marker.txt").exists(), (
            "B's runtime marker must never appear in C's isolated dirs"
        )
        assert b_state.resolve() != c_state.resolve()
