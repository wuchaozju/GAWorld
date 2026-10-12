"""
Unit tests for SimTree data-structure operations.

Tests the pure graph methods (lca, leaves, max_depth, frontier, summaries)
by injecting minimal fake node data, avoiding the need for a live Simulator.

Contains: TestSimTreeStructure
"""
from fos.core.simtree import SimTree


class FakeSim:
    """Minimal simulator stub for SimTree node structure tests."""
    def __init__(self, turns=0):
        self.turns = turns


def _make_tree_with_nodes() -> SimTree:
    """Build a SimTree with manually injected nodes for structural tests.

    Tree shape:
        root (id=0, depth=0)
        ├── child1 (id=1, depth=1)
        │   └── grandchild (id=3, depth=2)
        └── child2 (id=2, depth=1)
    """
    tree = SimTree(clients={})

    def _node(nid, parent, depth, turns=0):
        return {
            "id": nid,
            "parent": parent,
            "depth": depth,
            "edge_type": "root" if parent is None else "advance",
            "ops": [],
            "sim": FakeSim(turns=turns),
            "logs": [],
            "meta": {},
        }

    tree.nodes = {
        0: _node(0, None, 0, turns=0),
        1: _node(1, 0, 1, turns=1),
        2: _node(2, 0, 1, turns=1),
        3: _node(3, 1, 2, turns=2),
    }
    tree.children = {0: [1, 2], 1: [3], 2: [], 3: []}
    tree.root = 0
    return tree


class TestSimTreeStructure:

    def test_leaves_returns_nodes_with_no_children(self):
        tree = _make_tree_with_nodes()
        assert sorted(tree.leaves()) == [2, 3]

    def test_max_depth_returns_deepest_level(self):
        tree = _make_tree_with_nodes()
        assert tree.max_depth() == 2

    def test_frontier_returns_leaves_at_max_depth(self):
        tree = _make_tree_with_nodes()
        assert tree.frontier() == [3]

    def test_frontier_all_leaves_when_not_max_depth_only(self):
        tree = _make_tree_with_nodes()
        assert sorted(tree.frontier(only_max_depth=False)) == [2, 3]

    def test_lca_of_siblings_is_parent(self):
        tree = _make_tree_with_nodes()
        assert tree.lca(1, 2) == 0

    def test_lca_of_node_with_itself(self):
        tree = _make_tree_with_nodes()
        assert tree.lca(3, 3) == 3

    def test_lca_of_child_and_grandchild(self):
        tree = _make_tree_with_nodes()
        # lca(3, 2): 3 is at depth 2, 2 is at depth 1 → ancestor of 3 at depth 1 is node 1 → lca=0? no
        # 3's parent chain: 3 → 1 → 0; 2's parent chain: 2 → 0
        # Walk 3 up one step to depth 1: lands at node 1 (not same as 2), walk both to depth 0: both at 0
        assert tree.lca(3, 2) == 0

    def test_summaries_contains_all_nodes(self):
        tree = _make_tree_with_nodes()
        summaries = tree.summaries()
        assert len(summaries) == 4
        ids = {s["id"] for s in summaries}
        assert ids == {0, 1, 2, 3}

    def test_summaries_sorted_by_id(self):
        tree = _make_tree_with_nodes()
        summaries = tree.summaries()
        assert [s["id"] for s in summaries] == [0, 1, 2, 3]

    def test_summaries_root_has_no_parent(self):
        tree = _make_tree_with_nodes()
        root_summary = tree.summaries()[0]
        assert root_summary["parent"] is None

    def test_summaries_edges_connect_children(self):
        tree = _make_tree_with_nodes()
        root_summary = next(s for s in tree.summaries() if s["id"] == 0)
        child_ids = {e["to"] for e in root_summary["edges"]}
        assert child_ids == {1, 2}

    def test_single_node_tree_has_depth_zero(self):
        tree = SimTree(clients={})
        tree.nodes = {0: {
            "id": 0, "parent": None, "depth": 0,
            "edge_type": "root", "ops": [], "sim": FakeSim(), "logs": [], "meta": {},
        }}
        tree.children = {0: []}
        tree.root = 0
        assert tree.max_depth() == 0
        assert tree.leaves() == [0]
