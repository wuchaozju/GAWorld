import json
from unittest.mock import patch

import pytest

from gaworld.apps.distributed_comm_server import DistributedRelayBackend


def test_atomic_snapshot_roundtrip_preserves_relay_state(tmp_path):
    path = tmp_path / "state.json"
    backend = DistributedRelayBackend(str(path))
    backend.register_agents("demo", "node", [{"id": 1, "name": "Resident"}])
    backend.send_message("demo", "node", {"from_agent": 1, "to_agent": 2, "text": "hello"})
    restored = DistributedRelayBackend(str(path))
    for name in ("next_message_id", "messages", "directory", "interaction_edges", "recent_social_events"):
        assert getattr(restored, name) == getattr(backend, name)
    assert not list(tmp_path.glob(".relay-state-*"))


def test_partial_write_does_not_replace_previous_snapshot(tmp_path):
    path = tmp_path / "state.json"
    backend = DistributedRelayBackend(str(path))
    backend._persist()
    previous = path.read_bytes()

    def interrupted_write(payload, handle, **kwargs):
        handle.write('{"messages": [')
        raise OSError("interrupted write")

    with patch("gaworld.apps.distributed_comm_server.json.dump", side_effect=interrupted_write):
        with pytest.raises(OSError, match="interrupted write"):
            backend._persist()
    assert path.read_bytes() == previous
    assert json.loads(path.read_text())["messages"] == []
    assert not list(tmp_path.glob(".relay-state-*"))


def test_failed_replace_preserves_snapshot_and_removes_temporary_file(tmp_path):
    path = tmp_path / "state.json"
    backend = DistributedRelayBackend(str(path))
    backend._persist()
    previous = path.read_bytes()
    with patch("gaworld.apps.distributed_comm_server.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            backend._persist()
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".relay-state-*"))


@pytest.mark.parametrize("contents", ['{"messages": [', "[]", "\xff"])
def test_invalid_existing_snapshot_is_not_silently_reset(tmp_path, contents):
    path = tmp_path / "state.json"
    path.write_bytes(contents.encode("latin1"))
    previous = path.read_bytes()
    with pytest.raises(ValueError, match="relay state"):
        DistributedRelayBackend(str(path))
    assert path.read_bytes() == previous
