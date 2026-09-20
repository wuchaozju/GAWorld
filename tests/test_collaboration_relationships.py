import json
from pathlib import Path

import pytest

from gaworld.collaboration.relationships import (
    RelationshipService,
    merge_persisted_agent_edges,
)


def _agent(agent_id):
    return {"identity": {"id": agent_id, "name": f"居民{agent_id}"}}


def test_make_friends_creates_every_reciprocal_pair(tmp_path):
    service = RelationshipService(
        memory_dir=tmp_path,
        agent_loader=lambda agent_id: _agent(agent_id),
    )
    result = service.make_friends([1, 2, 3])

    assert result["created_pairs"] == [[1, 2], [1, 3], [2, 3]]
    for left, right in result["created_pairs"]:
        left_rels = json.loads((tmp_path / f"agent_{left}_relationships.json").read_text())
        right_rels = json.loads((tmp_path / f"agent_{right}_relationships.json").read_text())
        assert left_rels[str(right)]["role"] == "friend"
        assert right_rels[str(left)]["role"] == "friend"
        assert left_rels[str(right)]["closeness"] == 0.65


def test_make_friends_is_idempotent_and_preserves_stronger_role(tmp_path):
    (tmp_path / "agent_1_relationships.json").write_text(
        json.dumps({"2": {"role": "mentor", "closeness": 0.9, "trust": 0.8, "friction": 0.0}}),
        encoding="utf-8",
    )
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))
    service.make_friends([1, 2])
    second = service.make_friends([1, 2])
    rel = json.loads((tmp_path / "agent_1_relationships.json").read_text())["2"]

    assert rel["role"] == "mentor"
    assert rel["closeness"] == 0.9
    assert second["existing_pairs"] == [[1, 2]]


def test_make_friends_rejects_missing_agent_without_writes(tmp_path):
    service = RelationshipService(
        memory_dir=tmp_path,
        agent_loader=lambda agent_id: _agent(agent_id) if agent_id != 9 else None,
    )
    try:
        service.make_friends([1, 9])
    except ValueError as exc:
        assert "9" in str(exc)
    else:
        raise AssertionError("missing agent was accepted")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("invalid_payload", ["{malformed", "[]"])
def test_make_friends_rejects_invalid_relationship_files_without_modifying_any_file(
    tmp_path,
    invalid_payload,
):
    paths = {
        1: tmp_path / "agent_1_relationships.json",
        2: tmp_path / "agent_2_relationships.json",
    }
    paths[1].write_text('{"7": {"role": "friend"}}', encoding="utf-8")
    paths[2].write_text(invalid_payload, encoding="utf-8")
    originals = {agent_id: path.read_bytes() for agent_id, path in paths.items()}
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))

    with pytest.raises(ValueError, match="relationship file"):
        service.make_friends([1, 2])

    assert {agent_id: path.read_bytes() for agent_id, path in paths.items()} == originals


def test_make_friends_rejects_unreadable_relationship_file_without_modifying_any_file(
    tmp_path,
    monkeypatch,
):
    paths = {
        1: tmp_path / "agent_1_relationships.json",
        2: tmp_path / "agent_2_relationships.json",
    }
    for agent_id, path in paths.items():
        path.write_text(json.dumps({"7": {"role": f"friend-{agent_id}"}}), encoding="utf-8")
    originals = {agent_id: path.read_bytes() for agent_id, path in paths.items()}
    original_read_text = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == paths[2]:
            raise PermissionError("denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))

    with pytest.raises(ValueError, match="relationship file"):
        service.make_friends([1, 2])

    assert {agent_id: path.read_bytes() for agent_id, path in paths.items()} == originals


@pytest.mark.parametrize("fail_on_call", [1, 3])
def test_make_friends_rolls_back_every_path_when_write_replaces_then_raises(
    tmp_path,
    monkeypatch,
    fail_on_call,
):
    paths = {agent_id: tmp_path / f"agent_{agent_id}_relationships.json" for agent_id in (1, 2, 3)}
    paths[1].write_text('{"9": {"role": "mentor"}}\n', encoding="utf-8")
    paths[2].write_text('{"8": {"role": "friend"}}\n', encoding="utf-8")
    originals = {
        agent_id: path.read_bytes() if path.exists() else None
        for agent_id, path in paths.items()
    }
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))
    atomic_write = service._atomic_write
    calls = 0

    def replace_then_maybe_raise(path, payload):
        nonlocal calls
        calls += 1
        atomic_write(path, payload)
        if calls == fail_on_call:
            raise OSError("failure after replace")

    monkeypatch.setattr(service, "_atomic_write", replace_then_maybe_raise)

    with pytest.raises(OSError, match="failure after replace"):
        service.make_friends([1, 2, 3])

    for agent_id, path in paths.items():
        original = originals[agent_id]
        if original is None:
            assert not path.exists()
        else:
            assert path.read_bytes() == original


def test_make_friends_promotes_reciprocal_strong_acquaintances_with_friend_defaults(tmp_path):
    acquaintance = {
        "role": "acquaintance",
        "closeness": 0.9,
        "trust": 0.8,
        "obligation": 0.7,
        "friction": 0.0,
        "channels": ["chat", "face"],
        "decay_rate": 0.018,
        "obligation_base": 0.18,
    }
    (tmp_path / "agent_1_relationships.json").write_text(
        json.dumps({"2": acquaintance}),
        encoding="utf-8",
    )
    (tmp_path / "agent_2_relationships.json").write_text(
        json.dumps({"1": acquaintance}),
        encoding="utf-8",
    )
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))

    result = service.make_friends([1, 2])

    assert result["updated_pairs"] == [[1, 2]]
    for left, right in ((1, 2), (2, 1)):
        relationships = json.loads(
            (tmp_path / f"agent_{left}_relationships.json").read_text(encoding="utf-8")
        )
        record = relationships[str(right)]
        assert record["role"] == "friend"
        assert record["channels"] == ["chat", "visit"]
        assert record["decay_rate"] == 0.008
        assert record["obligation_base"] == 0.40


def test_merge_persisted_edges_updates_runtime_neighbors():
    agents = [
        {
            "id": 1,
            "social_neighbors": [],
            "relationships": {"2": {"kind": "agent", "role": "friend"}},
        },
        {"id": 2, "social_neighbors": [], "relationships": {}},
    ]
    merge_persisted_agent_edges(agents)
    assert agents[0]["social_neighbors"] == [2]
    assert agents[1]["social_neighbors"] == [1]


def test_merge_persisted_edges_normalizes_invalid_runtime_neighbor_containers():
    agents = [
        {
            "id": 1,
            "social_neighbors": None,
            "relationships": {"2": {"kind": "agent", "role": "friend"}},
        },
        {"id": 2, "social_neighbors": "invalid", "relationships": {}},
    ]

    merge_persisted_agent_edges(agents)

    assert agents[0]["social_neighbors"] == [2]
    assert agents[1]["social_neighbors"] == [1]


def test_touch_interaction_updates_existing_edges_without_creating_new_ones(tmp_path):
    service = RelationshipService(memory_dir=tmp_path, agent_loader=lambda agent_id: _agent(agent_id))
    service.make_friends([1, 2])
    service.touch_interaction([1, 2, 3])
    rels_1 = json.loads((tmp_path / "agent_1_relationships.json").read_text())
    assert rels_1["2"]["last_dashboard_interaction_at"]
    assert "3" not in rels_1
    assert not (tmp_path / "agent_3_relationships.json").exists()
