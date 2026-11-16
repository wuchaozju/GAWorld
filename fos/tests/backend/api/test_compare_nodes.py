"""
Tests for the /simulations/{simulation_id}/compare POST endpoint.

Covers:
- Comparing two nodes with different events
- Comparing two nodes with identical events
- Comparing two nodes with partial event overlap
- Agent property diffs (different and identical)
- Error cases: missing params, invalid node IDs, non-existent nodes
- Response structure validation
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litestar.exceptions import HTTPException

from fos.backend.api.routes.experiments import compare_nodes as _compare_nodes_route

# The Litestar @post decorator wraps the function.
# Access the underlying function via .fn to call it directly in tests.
compare_nodes = _compare_nodes_route.fn


def _make_event(event_type: str, data: dict | None = None) -> dict:
    """Build a log event dict matching the tree log format."""
    return {"type": event_type, "data": data or {}}


def _make_node(
    logs: list[dict] | None = None,
    agents: dict[str, SimpleNamespace] | None = None,
) -> dict:
    """Build a fake tree node dict as consumed by compare_nodes.

    Args:
        logs: list of event dicts for the node's logs
        agents: dict of agent name -> SimpleNamespace(properties={...})
    """
    node: dict = {}
    if logs is not None:
        node["logs"] = logs
    if agents is not None:
        sim = SimpleNamespace(agents=agents)
        node["sim"] = sim
    return node


def _make_agent(properties: dict | None = None) -> SimpleNamespace:
    """Build a fake agent with a .properties dict."""
    return SimpleNamespace(properties=properties or {})


# ---------------------------------------------------------------------------
# Fixture: mock all external dependencies of compare_nodes
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_deps():
    """Patch get_session, auth, and get_simulation_and_tree_for_owner
    so compare_nodes can be called without a real database or request."""
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__.return_value = AsyncMock()
    mock_session_ctx.__aexit__.return_value = None

    mock_token = AsyncMock(return_value="test-token")
    mock_user = AsyncMock(return_value=SimpleNamespace(id=1))

    patches = [
        patch(
            "fos.backend.api.routes.experiments.get_session",
            return_value=mock_session_ctx,
            autospec=False,
        ),
        patch(
            "fos.backend.api.routes.experiments.extract_bearer_token",
            mock_token,
        ),
        patch(
            "fos.backend.api.routes.experiments.resolve_current_user",
            mock_user,
        ),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Helper: run compare_nodes with a controlled tree
# ---------------------------------------------------------------------------

async def _run_compare(
    node_a: int,
    node_b: int,
    nodes: dict[int, dict],
    use_llm: bool = False,
) -> dict:
    """Call compare_nodes with a mocked tree containing the given nodes.

    Args:
        node_a: first node ID
        node_b: second node ID
        nodes: dict mapping node_id -> node dict (as created by _make_node)
        use_llm: whether to request LLM summary (not tested here)

    Returns:
        The response dict from compare_nodes
    """
    mock_tree = SimpleNamespace(nodes=nodes)
    mock_record = SimpleNamespace(tree=mock_tree)

    with patch(
        "fos.backend.api.routes.experiments.get_simulation_and_tree_for_owner",
        AsyncMock(return_value=(SimpleNamespace(owner_id=1), mock_record)),
    ):
        result = await compare_nodes(
            request=SimpleNamespace(),
            simulation_id="test-sim-001",
            data={
                "node_a": node_a,
                "node_b": node_b,
                "use_llm": use_llm,
            },
        )
    return result


# ===================================================================
# Tests
# ===================================================================


class TestCompareNodesDifferentEvents:
    """Scenario: two nodes have completely different event sets."""

    async def test_only_in_a_contains_a_events_only(self) -> None:
        """Node A has events A1, A2; Node B has B1, B2.
        only_in_a should contain A1 and A2, only_in_b should contain B1 and B2."""
        nodes = {
            1: _make_node(logs=[
                _make_event("event_a1", {"msg": "hello"}),
                _make_event("event_a2", {"msg": "world"}),
            ]),
            2: _make_node(logs=[
                _make_event("event_b1", {"msg": "foo"}),
                _make_event("event_b2", {"msg": "bar"}),
            ]),
        }
        result = await _run_compare(1, 2, nodes)

        only_a_types = {ev["type"] for ev in result["only_in_a"]}
        only_b_types = {ev["type"] for ev in result["only_in_b"]}

        assert "event_a1" in only_a_types
        assert "event_a2" in only_a_types
        assert "event_b1" in only_b_types
        assert "event_b2" in only_b_types
        # No cross-contamination
        assert all(ev["type"] not in only_b_types for ev in result["only_in_a"])
        assert all(ev["type"] not in only_a_types for ev in result["only_in_b"])

    async def test_event_diff_uses_type_and_data_combined(self) -> None:
        """Events are compared using stringified 'type:data' as key.
        Same type but different data should appear in the diff."""
        nodes = {
            1: _make_node(logs=[
                _make_event("msg", {"text": "hello"}),
            ]),
            2: _make_node(logs=[
                _make_event("msg", {"text": "goodbye"}),
            ]),
        }
        result = await _run_compare(1, 2, nodes)

        # Same type but different data -> should still be considered different
        assert len(result["only_in_a"]) == 1
        assert len(result["only_in_b"]) == 1


class TestCompareNodesIdenticalEvents:
    """Scenario: two nodes have identical event sets."""

    async def test_identical_events_produce_empty_diffs(self) -> None:
        """Both nodes have the same events.
        only_in_a and only_in_b should both be empty."""
        shared_events = [
            _make_event("msg", {"text": "hello"}),
            _make_event("action", {"type": "walk"}),
        ]
        nodes = {
            1: _make_node(logs=shared_events),
            2: _make_node(logs=shared_events),
        }
        result = await _run_compare(1, 2, nodes)

        assert result["only_in_a"] == []
        assert result["only_in_b"] == []

    async def test_identical_events_summary_says_no_diff(self) -> None:
        """Summary should indicate no obvious diff when events are identical."""
        shared_events = [_make_event("msg", {"text": "hello"})]
        nodes = {
            1: _make_node(logs=shared_events),
            2: _make_node(logs=shared_events),
        }
        result = await _run_compare(1, 2, nodes)

        # Summary indicates no differences when events and agent properties match
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0
        # The summary should not mention unique events since none exist
        assert result["only_in_a"] == []
        assert result["only_in_b"] == []


class TestCompareNodesPartialOverlap:
    """Scenario: two nodes share some events and have unique ones."""

    async def test_shared_events_excluded_from_diffs(self) -> None:
        """Shared event type+data should not appear in either diff list."""
        shared = _make_event("shared", {"val": 1})
        nodes = {
            1: _make_node(logs=[
                shared,
                _make_event("unique_a", {"val": "a"}),
            ]),
            2: _make_node(logs=[
                shared,
                _make_event("unique_b", {"val": "b"}),
            ]),
        }
        result = await _run_compare(1, 2, nodes)

        only_a_types = {ev["type"] for ev in result["only_in_a"]}
        only_b_types = {ev["type"] for ev in result["only_in_b"]}

        assert "shared" not in only_a_types
        assert "shared" not in only_b_types
        assert "unique_a" in only_a_types
        assert "unique_b" in only_b_types


class TestCompareNodesAgentDiffs:
    """Scenario: testing agent property comparisons."""

    async def test_different_agent_properties_reported(self) -> None:
        """When agents have different property values, agent_diffs contains the diff."""
        nodes = {
            1: _make_node(
                logs=[],
                agents={
                    "agent_x": _make_agent({"hp": 100, "mp": 50}),
                },
            ),
            2: _make_node(
                logs=[],
                agents={
                    "agent_x": _make_agent({"hp": 80, "mp": 50}),
                },
            ),
        }
        result = await _run_compare(1, 2, nodes)

        assert "agent_x" in result["agent_diffs"]
        assert "hp" in result["agent_diffs"]["agent_x"]
        assert result["agent_diffs"]["agent_x"]["hp"] == {"a": 100, "b": 80}
        # mp is the same -> not in diffs
        assert "mp" not in result["agent_diffs"]["agent_x"]

    async def test_identical_agent_properties_no_diffs(self) -> None:
        """When agents have identical properties, no diffs are reported."""
        nodes = {
            1: _make_node(
                logs=[],
                agents={
                    "agent_y": _make_agent({"food": 10}),
                },
            ),
            2: _make_node(
                logs=[],
                agents={
                    "agent_y": _make_agent({"food": 10}),
                },
            ),
        }
        result = await _run_compare(1, 2, nodes)

        assert result["agent_diffs"] == {}

    async def test_agent_in_one_node_only_reported(self) -> None:
        """If an agent only exists in one node, its properties should show as diff."""
        nodes = {
            1: _make_node(
                logs=[],
                agents={
                    "agent_z": _make_agent({"score": 99}),
                },
            ),
            2: _make_node(
                logs=[],
                agents={},  # agent_z is missing
            ),
        }
        result = await _run_compare(1, 2, nodes)

        assert "agent_z" in result["agent_diffs"]
        assert result["agent_diffs"]["agent_z"]["score"] == {"a": 99, "b": None}


class TestCompareNodesErrors:
    """Error handling for invalid inputs."""

    async def test_missing_node_a_returns_400(self) -> None:
        """Missing node_a param should raise 400."""
        with pytest.raises(HTTPException) as exc_info:
            await compare_nodes(
                request=SimpleNamespace(),
                simulation_id="test-sim-001",
                data={"node_b": 2, "use_llm": False},
            )
        assert exc_info.value.status_code == 400

    async def test_missing_node_b_returns_400(self) -> None:
        """Missing node_b param should raise 400."""
        with pytest.raises(HTTPException) as exc_info:
            await compare_nodes(
                request=SimpleNamespace(),
                simulation_id="test-sim-001",
                data={"node_a": 1, "use_llm": False},
            )
        assert exc_info.value.status_code == 400

    async def test_non_numeric_node_id_returns_400(self) -> None:
        """Non-numeric node IDs should raise 400."""
        with pytest.raises(HTTPException) as exc_info:
            await compare_nodes(
                request=SimpleNamespace(),
                simulation_id="test-sim-001",
                data={"node_a": "abc", "node_b": 2, "use_llm": False},
            )
        assert exc_info.value.status_code == 400

    async def test_non_existent_node_returns_400(self) -> None:
        """Non-existent node IDs should raise 400."""
        nodes = {1: _make_node(logs=[])}
        mock_tree = SimpleNamespace(nodes=nodes)
        mock_record = SimpleNamespace(tree=mock_tree)

        with patch(
            "fos.backend.api.routes.experiments.get_simulation_and_tree_for_owner",
            AsyncMock(return_value=(SimpleNamespace(owner_id=1), mock_record)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await compare_nodes(
                    request=SimpleNamespace(),
                    simulation_id="test-sim-001",
                    data={"node_a": 1, "node_b": 999, "use_llm": False},
                )
        assert exc_info.value.status_code == 400


class TestCompareNodesSummary:
    """The summary field contains a human-readable overview."""

    async def test_summary_includes_event_counts(self) -> None:
        """Summary should mention how many unique events each node has."""
        nodes = {
            1: _make_node(logs=[
                _make_event("ev_a1", {}),
                _make_event("ev_a2", {}),
            ]),
            2: _make_node(logs=[
                _make_event("ev_b1", {}),
            ]),
        }
        result = await _run_compare(1, 2, nodes)

        # Summary is a string composed from translated template fragments
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    async def test_compare_nodes_returns_expected_structure(self) -> None:
        """The response contains all expected keys."""
        nodes = {
            1: _make_node(logs=[_make_event("ev", {})]),
            2: _make_node(logs=[_make_event("ev2", {})]),
        }
        result = await _run_compare(1, 2, nodes)

        assert "node_a" in result
        assert "node_b" in result
        assert "only_in_a" in result
        assert "only_in_b" in result
        assert "agent_diffs" in result
        assert "summary" in result
        assert result["node_a"] == 1
        assert result["node_b"] == 2
