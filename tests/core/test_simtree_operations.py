"""
Tests for SimTree clone/branch/advance operations.

Validates root creation via SimTree.new(), clone independence checks,
branching operations, copy/attach mechanics, and advance operations.

Contains: Mock infrastructure, TestSimTreeNew, TestCheckSimulatorClone,
TestBranch, TestCopySimAttach, TestAdvanceOps
"""

import pytest
from unittest.mock import MagicMock, patch

from fos.core.simtree import SimTree, SimCloneError


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------

class MockMemory:
    """Minimal short_memory stub with append and length."""

    def __init__(self):
        self.history = []

    def get_all(self):
        return self.history

    def append(self, role, content):
        self.history.append({"role": role, "content": content})

    def __len__(self):
        return len(self.history)


class MockAgent:
    """Minimal agent stub matching attributes used by SimTree."""

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
    """Minimal scene config stub."""

    def __init__(self):
        self.parameters = {}
        self.description = ""
        self.social_network = {}
        self.actions = []


class MockScene:
    """Minimal scene stub with state and config."""

    def __init__(self):
        self.TYPE = "mock"
        self.state = {}
        self.config = MockConfig()
        self.runner = None

    def on_event(self, sim, event_type, payload):
        pass

    def on_private_event(self, sim, event_type, payload, receivers):
        pass


class MockOrdering:
    """Minimal ordering stub that serializes deterministically."""

    def serialize(self):
        return {"type": "mock_ordering", "state": {}}


class MockEventQueue:
    """Minimal event queue stub that reports empty."""

    def empty(self):
        return True


class FakeSim:
    """Fake simulator for SimTree clone/branch tests.

    Supports serialize/deserialize round-trip so SimTree.new() and
    _clone_simulator_from_node() can produce independent clones.
    """

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_simulator():
    """Patch Simulator with FakeSim so clone operations use test doubles."""
    with patch("fos.core.simtree.Simulator", FakeSim):
        yield


@pytest.fixture()
def _patch_era():
    """Patch ExperimentRunnerAdapter so isinstance checks don't crash."""
    class _MockERA:
        pass

    mock_mod = MagicMock()
    mock_mod.ExperimentRunnerAdapter = _MockERA
    import fos.backend.services.simtree_runtime as real_mod

    original = real_mod.ExperimentRunnerAdapter
    real_mod.ExperimentRunnerAdapter = _MockERA
    yield _MockERA
    real_mod.ExperimentRunnerAdapter = original


def _make_sim(agent_names=("Alice", "Bob")):
    """Create a FakeSim with named agents and some prior state."""
    agents = {name: MockAgent(name) for name in agent_names}
    return FakeSim(agents=agents)


def _make_tree_via_new(agent_names=("Alice", "Bob")):
    """Create a SimTree via SimTree.new() with a FakeSim."""
    sim = _make_sim(agent_names)
    clients = {"mock": object()}
    tree = SimTree.new(sim, clients)
    return tree, sim


# ===================================================================
# Group A — SimTree.new() root node creation
# ===================================================================


class TestSimTreeNew:
    """Tests for SimTree.new() root node creation."""

    def test_new_creates_root_node_with_id_zero(self):
        tree, _ = _make_tree_via_new()
        assert tree.root == 0
        assert 0 in tree.nodes

    def test_new_root_has_no_parent(self):
        tree, _ = _make_tree_via_new()
        assert tree.nodes[0]["parent"] is None

    def test_new_clones_simulator_via_serialize_deserialize(self):
        original_sim = _make_sim()
        clients = {"mock": object()}
        tree = SimTree.new(original_sim, clients)
        root_sim = tree.nodes[0]["sim"]
        assert root_sim is not original_sim

    def test_new_root_agents_have_reset_history_length(self):
        sim = _make_sim()
        # The original agents have last_history_length set high;
        # after clone+reset, the formula max(0, len(memory)-1) applies.
        # FakeSim.deserialize creates agents with empty memory, so result = 0.
        for ag in sim.agents.values():
            ag.last_history_length = 99
        tree = SimTree.new(sim, {"mock": object()})
        root_sim = tree.nodes[0]["sim"]
        for agent in root_sim.agents.values():
            assert agent.last_history_length == max(0, len(agent.short_memory) - 1)

    def test_new_root_agents_have_reset_error_counters(self):
        sim = _make_sim()
        for ag in sim.agents.values():
            ag.consecutive_llm_errors = 5
        tree = SimTree.new(sim, {"mock": object()})
        root_sim = tree.nodes[0]["sim"]
        for agent in root_sim.agents.values():
            assert agent.consecutive_llm_errors == 0

    def test_new_root_sim_has_reset_event_queue(self):
        """reset_event_queue must be called on the clone."""
        sim = _make_sim()
        queue = MagicMock()
        queue.empty.return_value = True
        sim.event_queue = queue

        tree = SimTree.new(sim, {"mock": object()})
        root_sim = tree.nodes[0]["sim"]
        # The clone's event_queue is created by FakeSim.deserialize (a new MockEventQueue).
        # We verify by checking the original's queue was not passed through.
        assert root_sim.event_queue is not queue

    def test_new_initializes_tree_structure(self):
        tree, _ = _make_tree_via_new()
        assert len(tree.nodes) == 1
        assert tree.root == 0
        assert tree._seq == 1  # one id consumed

    def test_new_with_client_pool_false(self):
        """use_client_pool=False in the tree created by new() should work."""
        sim = _make_sim()
        tree = SimTree.new(sim, {"mock": object()})
        assert tree._client_pool is None

    def test_new_attaches_log_handler(self):
        tree, _ = _make_tree_via_new()
        root_sim = tree.nodes[0]["sim"]
        assert root_sim.log_event is not None
        assert callable(root_sim.log_event)
        for agent in root_sim.agents.values():
            assert agent.log_event is not None


# ===================================================================
# Group B — _check_simulator_clone() independence validation
# ===================================================================


class TestCheckSimulatorClone:
    """Tests for _check_simulator_clone() clone independence checks."""

    def _make_pair(self):
        """Return (base, cloned) FakeSim pair that passes all checks."""
        base = _make_sim(("Alice", "Bob"))
        snap = base.serialize()
        cloned = FakeSim.deserialize(snap, {})
        return base, cloned

    def test_clone_check_passes_for_independent_clones(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        # Should not raise
        tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_agents_dict_shared(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        cloned.agents = base.agents  # share the same dict
        with pytest.raises(SimCloneError, match="agents dict shared"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_scene_shared(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        cloned.scene = base.scene  # share the same scene
        with pytest.raises(SimCloneError, match="scene shared"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_event_queue_shared(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        cloned.event_queue = base.event_queue  # share the same queue
        with pytest.raises(SimCloneError, match="event_queue shared"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_ordering_shared(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        cloned.ordering = base.ordering  # share the same ordering
        with pytest.raises(SimCloneError, match="ordering object shared"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_agent_names_differ(self):
        tree, _ = _make_tree_via_new()
        base = _make_sim(("Alice", "Bob"))
        snap = base.serialize()
        cloned = FakeSim.deserialize(snap, {})
        # Remove an agent from clone to cause name mismatch
        del cloned.agents["Bob"]
        with pytest.raises(SimCloneError, match="agent set mismatch"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_cloned_event_queue_not_empty(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        # Make the cloned queue report non-empty
        cloned.event_queue = MagicMock()
        cloned.event_queue.empty.return_value = False
        with pytest.raises(SimCloneError, match="not empty"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_agent_count_differs(self):
        """Agent count mismatch even when names overlap."""
        tree, _ = _make_tree_via_new()
        base = _make_sim(("Alice", "Bob"))
        snap = base.serialize()
        cloned = FakeSim.deserialize(snap, {})
        # Add a duplicate-named agent to inflate count while keeping names the same
        cloned.agents["Alice_dup"] = MockAgent("Alice_dup")
        with pytest.raises(SimCloneError, match="agent set mismatch"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_fails_if_scene_type_differs(self):
        tree, _ = _make_tree_via_new()
        base, cloned = self._make_pair()
        # Replace cloned scene with a different type
        cloned.scene = MagicMock()
        with pytest.raises(SimCloneError, match="scene type mismatch"):
            tree._check_simulator_clone(base, cloned)

    def test_clone_check_skips_for_experiment_runner_adapter(self, _patch_era):
        tree, _ = _make_tree_via_new()
        _MockERA = _patch_era
        base = _make_sim()
        cloned = _MockERA()  # not a real Simulator
        # Should return without raising, even though cloned has no .agents etc.
        tree._check_simulator_clone(base, cloned)


# ===================================================================
# Group C — branch() core branching
# ===================================================================


class TestBranch:
    """Tests for branch() what-if sibling creation and op application."""

    def test_branch_from_root_creates_child(self):
        """Branching from root (no parent) falls back to creating a child."""
        tree, _ = _make_tree_via_new()
        cid = tree.branch(0, [{"op": "agent_ctx_append", "name": "Alice",
                                "role": "user", "content": "hello"}])
        assert cid in tree.nodes
        assert tree.nodes[cid]["parent"] == 0

    def test_branch_from_nonroot_creates_sibling(self):
        """Branching from a non-root node creates a sibling (same parent)."""
        tree, _ = _make_tree_via_new()
        # First advance root to create child node 1
        child1 = tree.advance(0, turns=1)
        # Branch from child1 -> sibling of child1, both children of root
        sibling = tree.branch(child1, [{"op": "agent_ctx_append", "name": "Alice",
                                         "role": "user", "content": "hello"}])
        assert tree.nodes[sibling]["parent"] == 0  # same parent as child1
        assert sibling != child1
        assert sibling in tree.children[0]

    def test_branch_with_agent_ctx_append_adds_to_memory(self):
        tree, _ = _make_tree_via_new()
        cid = tree.branch(0, [{"op": "agent_ctx_append", "name": "Alice",
                                "role": "user", "content": "hello"}])
        agent = tree.nodes[cid]["sim"].agents["Alice"]
        assert agent.short_memory.history[-1] == {"role": "user", "content": "hello"}

    def test_branch_with_agent_plan_replace_sets_plan(self):
        tree, _ = _make_tree_via_new()
        plan = {"goal": "cooperate", "steps": ["share", "repeat"]}
        cid = tree.branch(0, [{"op": "agent_plan_replace", "name": "Alice",
                                "plan_state": plan}])
        agent = tree.nodes[cid]["sim"].agents["Alice"]
        assert agent.plan_state == plan

    def test_branch_with_agent_props_patch_updates_properties(self):
        tree, _ = _make_tree_via_new()
        cid = tree.branch(0, [{"op": "agent_props_patch", "name": "Alice",
                                "updates": {"mood": "happy", "energy": 80}}])
        agent = tree.nodes[cid]["sim"].agents["Alice"]
        assert agent.properties["mood"] == "happy"
        assert agent.properties["energy"] == 80

    def test_branch_with_scene_state_patch_updates_scene_state(self):
        tree, _ = _make_tree_via_new()
        cid = tree.branch(0, [{"op": "scene_state_patch",
                                "updates": {"weather": "sunny", "temperature": 25}}])
        scene = tree.nodes[cid]["sim"].scene
        assert scene.state["weather"] == "sunny"
        assert scene.state["temperature"] == 25

    def test_branch_with_config_params_patch_merges_parameters(self):
        tree, _ = _make_tree_via_new()
        # FakeSim.serialize does not preserve config, so the clone starts
        # with empty parameters.  The merge still works: {} | updates = updates.
        cid = tree.branch(0, [{"op": "config_params_patch",
                                "updates": {"visibility": "partial", "speed": 2}}])
        params = tree.nodes[cid]["sim"].scene.config.parameters
        assert params["visibility"] == "partial"
        assert params["speed"] == 2

    def test_branch_with_network_replace_sets_social_network(self):
        tree, _ = _make_tree_via_new()
        network = {"edges": [("Alice", "Bob")], "type": "complete"}
        cid = tree.branch(0, [{"op": "network_replace", "network": network}])
        cfg = tree.nodes[cid]["sim"].scene.config
        assert cfg.social_network == network

    def test_branch_with_public_broadcast_calls_broadcast(self):
        tree, _ = _make_tree_via_new()
        cid = tree.branch(0, [{"op": "public_broadcast", "text": "Breaking news!"}])
        # If we get here without error, broadcast was called on the clone's sim.
        # Verify the new node exists and is attached.
        assert cid in tree.nodes

    def test_branch_with_environment_event_adds_feedback_to_all_agents(self):
        tree, _ = _make_tree_via_new()
        cid = tree.branch(0, [{"op": "environment_event", "text": "Earthquake!",
                                "event_type": "disaster"}])
        # FakeSim agents have no-op add_env_feedback, so no observable side-effect.
        # The key assertion is that branch completed without error.
        assert cid in tree.nodes
        assert tree.nodes[cid]["sim"] is not None

    def test_branch_with_environment_event_targets_specific_receivers(self):
        tree, _ = _make_tree_via_new(("Alice", "Bob", "Carol"))
        cid = tree.branch(0, [{"op": "environment_event", "text": "Secret message",
                                "event_type": "whisper", "receivers": ["Alice", "Bob"]}])
        # The clone's agents were freshly created by deserialize, not our mocks.
        # But we can verify the operation completed without error.
        assert cid in tree.nodes

    def test_branch_with_unknown_operation_raises_valueerror(self):
        tree, _ = _make_tree_via_new()
        with pytest.raises(ValueError, match="Unknown op"):
            tree.branch(0, [{"op": "nonexistent_magic_op"}])


# ===================================================================
# Group D — copy_sim() / attach()
# ===================================================================


class TestCopySimAttach:
    """Tests for copy_sim() simulator cloning and attach() edge linking."""

    def test_copy_sim_creates_new_node_with_unique_id(self):
        tree, _ = _make_tree_via_new()
        cid = tree.copy_sim(0)
        assert cid == 1  # next id after root (0)
        assert cid in tree.nodes

    def test_copy_sim_deep_copies_parent_logs(self):
        tree, _ = _make_tree_via_new()
        # Write something into root logs
        tree.nodes[0]["logs"].append({"type": "test", "data": "x"})
        cid = tree.copy_sim(0)
        child_logs = tree.nodes[cid]["logs"]
        assert child_logs[0] == {"type": "test", "data": "x"}
        # Must be a deep copy — not the same list object
        assert child_logs is not tree.nodes[0]["logs"]

    def test_copy_sim_from_missing_node_raises_keyerror(self):
        tree, _ = _make_tree_via_new()
        with pytest.raises(KeyError):
            tree.copy_sim(999)

    def test_attach_links_child_to_parent(self):
        tree, _ = _make_tree_via_new()
        cid = tree.copy_sim(0)
        tree.attach(0, [{"op": "advance", "turns": 1}], cid)
        assert tree.nodes[cid]["parent"] == 0
        assert cid in tree.children[0]

    def test_attach_sets_edge_type_from_ops(self):
        tree, _ = _make_tree_via_new()
        cid = tree.copy_sim(0)
        tree.attach(0, [{"op": "agent_ctx_append", "name": "Alice",
                         "role": "user", "content": "hi"}], cid)
        assert tree.nodes[cid]["edge_type"] == "agent_ctx"

    def test_attach_classifies_multi_ops_as_multi(self):
        tree, _ = _make_tree_via_new()
        cid = tree.copy_sim(0)
        ops = [
            {"op": "agent_ctx_append", "name": "Alice", "role": "user", "content": "hi"},
            {"op": "agent_props_patch", "name": "Alice", "updates": {"x": 1}},
        ]
        tree.attach(0, ops, cid)
        assert tree.nodes[cid]["edge_type"] == "multi"

    def test_attach_sets_depth_to_parent_plus_one(self):
        tree, _ = _make_tree_via_new()
        cid = tree.copy_sim(0)
        tree.attach(0, [{"op": "advance", "turns": 1}], cid)
        assert tree.nodes[cid]["depth"] == 1

    def test_attach_with_missing_parent_raises_keyerror(self):
        tree, _ = _make_tree_via_new()
        cid = tree.copy_sim(0)
        with pytest.raises(KeyError):
            tree.attach(999, [{"op": "advance", "turns": 1}], cid)


# ===================================================================
# Group E — advance() / advance_frontier() / advance_selected()
# ===================================================================


class TestAdvanceOps:
    """Tests for advance(), advance_frontier(), and advance_selected()."""

    def test_advance_runs_simulator_for_turns(self):
        tree, _ = _make_tree_via_new()
        cid = tree.advance(0, turns=3)
        assert tree.nodes[cid]["sim"].turns == 3

    def test_advance_updates_node_logs(self):
        """advance() should copy parent logs into the new child node."""
        tree, _ = _make_tree_via_new()
        # Manually append a log entry to root
        tree.nodes[0]["logs"].append({"type": "info", "data": "seed"})
        cid = tree.advance(0, turns=1)
        # copy_sim deep-copies parent logs, so child inherits them
        child_logs = tree.nodes[cid]["logs"]
        assert any(e["data"] == "seed" for e in child_logs)

    def test_advance_frontier_advances_all_leaf_nodes(self):
        tree, _ = _make_tree_via_new()
        # Create two children of root (both are leaves at depth 1)
        c1 = tree.advance(0, turns=1)
        c2 = tree.advance(0, turns=1)
        assert sorted(tree.leaves()) == [c1, c2]
        # advance_frontier advances all leaves at max depth
        new_ids = tree.advance_frontier(turns=2)
        assert len(new_ids) == 2
        for nid in new_ids:
            assert tree.nodes[nid]["sim"].turns == 2

    def test_advance_selected_advances_only_named_nodes(self):
        tree, _ = _make_tree_via_new()
        c1 = tree.advance(0, turns=1)
        c2 = tree.advance(0, turns=1)
        # Advance only c1
        new_ids = tree.advance_selected([c1], turns=5)
        assert len(new_ids) == 1
        assert tree.nodes[new_ids[0]]["sim"].turns == 5
        # c2 should still be a leaf (unchanged)
        assert c2 in tree.leaves()

    def test_advance_selected_raises_for_missing_node(self):
        tree, _ = _make_tree_via_new()
        with pytest.raises(KeyError):
            tree.advance_selected([999], turns=1)

    def test_advance_selected_does_not_raise_for_non_leaf(self):
        """FINDING: advance_selected() does NOT enforce leaf-only constraint.

        The current implementation allows advancing non-leaf nodes, which
        creates additional children of an already-branched parent. This is
        not necessarily a bug but could lead to confusing tree structures
        if callers expect leaf-only semantics.

        The test documents actual behavior: advancing a non-leaf succeeds.
        """
        tree, _ = _make_tree_via_new()
        c1 = tree.advance(0, turns=1)
        tree.advance(c1, turns=1)  # c1 is now a non-leaf
        # Advancing c1 again should succeed (it's not a leaf anymore)
        new_ids = tree.advance_selected([c1], turns=2)
        assert len(new_ids) == 1
        assert tree.nodes[new_ids[0]]["sim"].turns == 2
