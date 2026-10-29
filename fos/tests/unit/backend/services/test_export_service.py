"""Tests for export service."""
from datetime import datetime
from fos.backend.services.export_service import generate_export_filename


def test_generate_export_filename_csv():
    """Test filename generation for CSV format."""
    result = generate_export_filename("public_goods", "csv")
    # Pattern: Scenario_public_goods_YYYY_MM_DD_HH_MM.csv
    assert result.startswith("Scenario_public_goods_")
    assert result.endswith(".csv")
    assert len(result.split("_")) >= 7  # At least: Scenario, id, YYYY, MM, DD, HH, MM


def test_simplify_log_type_agent_action():
    """Test type simplification for agent actions."""
    from fos.backend.services.export_service import simplify_log_type

    assert simplify_log_type("AGENT_SAY") == "AGENT_ACTION"
    assert simplify_log_type("AGENT_ACTION") == "AGENT_ACTION"


def test_simplify_log_type_system():
    """Test type simplification for system events."""
    from fos.backend.services.export_service import simplify_log_type

    assert simplify_log_type("ENVIRONMENT") == "SYSTEM"
    assert simplify_log_type("SYSTEM") == "SYSTEM"
    assert simplify_log_type("AGENT_METADATA") == "SYSTEM"


def test_extract_action_and_follow_up_allocate():
    """Test extracting action and follow-up from allocate action."""
    from fos.backend.services.export_service import extract_action_and_follow_up

    event = {
        "event_type": "action_end",
        "data": {
            "action": {"name": "allocate", "parameters": {"amount": 12}}
        }
    }
    action, follow_up = extract_action_and_follow_up(event)
    assert action == "allocate"
    assert follow_up == "12"


def test_extract_action_and_follow_up_deduct():
    """Test extracting action and follow-up with multiple parameters."""
    from fos.backend.services.export_service import extract_action_and_follow_up

    event = {
        "event_type": "action_end",
        "data": {
            "action": {"name": "deduct", "parameters": {"target": "Agent 2", "amount": 3}}
        }
    }
    action, follow_up = extract_action_and_follow_up(event)
    assert action == "deduct"
    assert follow_up == "Agent 2; 3"


def test_transform_event_for_export():
    """Test transforming a log event into export format."""
    from fos.backend.services.export_service import transform_event_for_export

    event = {
        "sequence": 1,
        "tree_node_id": 5,
        "event_type": "AGENT_ACTION",
        "payload": {
            "action": {"name": "allocate", "parameters": {"amount": 12}},
            "agent": "Agent 1"
        },
        "created_at": datetime(2026, 3, 30, 14, 30, 0)
    }

    scenario_params = {
        "tokens_per_round": 10,
        "multiplier": 1.3
    }

    result = transform_event_for_export(event, scenario_params)

    assert result["sequence"] == 1
    assert result["node_id"] == "5"
    assert result["agent_id"] == "agent_1"
    assert result["type"] == "AGENT_ACTION"
    assert result["action"] == "allocate"
    assert result["follow_up"] == "12"
    assert result["tokens_per_round"] == 10
    assert result["multiplier"] == 1.3


def test_export_events_to_csv():
    """Test exporting events to CSV format."""
    from fos.backend.services.export_service import export_events

    events = [
        {
            "sequence": 1,
            "tree_node_id": 1,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 12}},
                "agent": "Agent 1"
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0)
        }
    ]

    scenario_params = {"tokens_per_round": 10, "multiplier": 1.3}

    csv_content = export_events(events, scenario_params, "csv")

    assert "timestamp" in csv_content
    assert "agent_1" in csv_content
    assert "allocate" in csv_content
    assert "12" in csv_content
    assert "tokens_per_round" in csv_content


def test_export_events_to_csv_does_not_add_blank_rows() -> None:
    """Test CSV export keeps one physical line per row on Windows."""
    from fos.backend.services.export_service import export_events

    events = [
        {
            "sequence": 1,
            "tree_node_id": 1,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 12}},
                "agent": "Agent 1",
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0),
        }
    ]

    csv_content = export_events(events, {"tokens_per_round": 10}, "csv")

    assert "\r\r\n" not in csv_content
    assert csv_content.count("\n") == 2


def test_export_events_to_csv_header_only_does_not_add_blank_rows() -> None:
    """Test header-only CSV export does not insert spacer rows."""
    from fos.backend.services.export_service import export_events

    csv_content = export_events([], {"tokens_per_round": 10}, "csv")

    assert "\r\r\n" not in csv_content
    assert csv_content.count("\n") == 1


def test_export_events_to_json():
    """Test exporting events to JSON format."""
    import json
    from fos.backend.services.export_service import export_events

    events = [
        {
            "sequence": 1,
            "tree_node_id": 1,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 12}},
                "agent": "Agent 1"
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0)
        }
    ]

    scenario_params = {"tokens_per_round": 10, "multiplier": 1.3}

    json_content = export_events(events, scenario_params, "json")
    data = json.loads(json_content)

    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["agent_id"] == "agent_1"
    assert data[0]["action"] == "allocate"


def test_export_events_deduplication():
    """Test that duplicate events from inherited logs are deduplicated.

    This tests the scenario where:
    - Node 1 has Round 1 logs
    - Node 2 (child of 1) inherits Round 1 logs + has Round 2 logs
    - Node 3 (child of 2) inherits Round 1+2 logs + has Round 3 logs

    Without deduplication, Round 1 would appear 3x, Round 2 would appear 2x.
    With deduplication, each round should appear exactly once.
    """
    from fos.backend.services.export_service import export_events

    # Simulate logs from 3 nodes where child inherits parent logs
    # This mimics the actual SimTree behavior
    events = [
        # Round 1 - Agent 1 (appears in all 3 nodes due to inheritance)
        {
            "sequence": 0,
            "tree_node_id": 1,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 6}},
                "agent": "Agent 1",
                "round": 1
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0)
        },
        {
            "sequence": 0,
            "tree_node_id": 2,  # Duplicate from node 2
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 6}},
                "agent": "Agent 1",
                "round": 1
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0)
        },
        {
            "sequence": 0,
            "tree_node_id": 3,  # Duplicate from node 3
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 6}},
                "agent": "Agent 1",
                "round": 1
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0)
        },
        # Round 2 - Agent 1 (appears in nodes 2 and 3)
        {
            "sequence": 5,
            "tree_node_id": 2,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 5}},
                "agent": "Agent 1",
                "round": 2
            },
            "created_at": datetime(2026, 3, 30, 14, 31, 0)
        },
        {
            "sequence": 5,
            "tree_node_id": 3,  # Duplicate from node 3
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 5}},
                "agent": "Agent 1",
                "round": 2
            },
            "created_at": datetime(2026, 3, 30, 14, 31, 0)
        },
        # Round 3 - Agent 1 (only in node 3)
        {
            "sequence": 10,
            "tree_node_id": 3,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 4}},
                "agent": "Agent 1",
                "round": 3
            },
            "created_at": datetime(2026, 3, 30, 14, 32, 0)
        },
    ]

    scenario_params = {"tokens_per_round": 10}

    # Export to JSON for easier assertion
    json_content = export_events(events, scenario_params, "json")
    import json
    data = json.loads(json_content)

    # Should have exactly 3 events (one per round), not 6
    assert len(data) == 3, f"Expected 3 unique events, got {len(data)}"

    # Verify we have one event per round
    rounds = [e["round"] for e in data]
    assert rounds == [1, 2, 3], f"Expected rounds [1, 2, 3], got {rounds}"

    # Verify amounts are correct (6, 5, 4)
    amounts = [e["follow_up"] for e in data]
    assert amounts == ["6", "5", "4"], f"Expected amounts ['6', '5', '4'], got {amounts}"


def test_export_events_keeps_distinct_sibling_branch_logs():
    """Sibling branch events with identical content should not be collapsed."""
    from fos.backend.services.export_service import export_events

    events = [
        {
            "sequence": 0,
            "tree_node_id": 1,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 6}},
                "agent": "Agent 1",
                "round": 1,
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0),
        },
        {
            "sequence": 1,
            "tree_node_id": 2,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 5}},
                "agent": "Agent 1",
                "round": 2,
            },
            "created_at": datetime(2026, 3, 30, 14, 31, 0),
        },
        {
            "sequence": 0,
            "tree_node_id": 1,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 6}},
                "agent": "Agent 1",
                "round": 1,
            },
            "created_at": datetime(2026, 3, 30, 14, 30, 0),
        },
        {
            "sequence": 1,
            "tree_node_id": 3,
            "event_type": "AGENT_ACTION",
            "payload": {
                "action": {"name": "allocate", "parameters": {"amount": 5}},
                "agent": "Agent 1",
                "round": 2,
            },
            "created_at": datetime(2026, 3, 30, 14, 31, 5),
        },
    ]

    scenario_params = {"tokens_per_round": 10}

    json_content = export_events(events, scenario_params, "json")
    import json
    data = json.loads(json_content)

    assert len(data) == 3, f"Expected 3 exported events, got {len(data)}"
    assert [item["node_id"] for item in data] == ["1", "2", "3"]
    assert [item["follow_up"] for item in data] == ["6", "5", "5"]
