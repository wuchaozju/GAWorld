"""
This file checks that council CSV export stays readable for the pilot run.

It calls the current export route with fake council logs and makes sure the
CSV shows both deliberation actions and final votes without changing the
existing export schema.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fos.backend.api.routes.simulations import export as export_module


class _FakeSessionContext:
    """Provide a minimal async session context for route tests."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_council_export_route_returns_readable_csv_for_speech_and_votes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_user(session: object, token: str) -> SimpleNamespace:
        _ = session, token
        return SimpleNamespace(id=1)

    async def _fake_sim_and_tree(
        session: object,
        owner_id: int,
        simulation_id: str,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        _ = session, owner_id, simulation_id
        logs = [
            {
                "type": "experiment_action",
                "node": 0,
                "timestamp": "2026-06-09T10:00:00",
                "data": {
                    "agent": "Alice",
                    "action": "speak",
                    "parameters": {"message": "We should fund the tool library."},
                    "round": 1,
                },
            },
            {
                "type": "experiment_action",
                "node": 0,
                "timestamp": "2026-06-09T10:00:01",
                "data": {
                    "agent": "Bob",
                    "action": "skip",
                    "parameters": {},
                    "round": 1,
                },
            },
            {
                "type": "experiment_action",
                "node": 0,
                "timestamp": "2026-06-09T10:00:02",
                "data": {
                    "agent": "Alice",
                    "action": "vote_yes",
                    "parameters": {},
                    "round": 2,
                },
            },
            {
                "type": "experiment_action",
                "node": 0,
                "timestamp": "2026-06-09T10:00:03",
                "data": {
                    "agent": "Bob",
                    "action": "abstain",
                    "parameters": {},
                    "round": 2,
                },
            },
        ]
        sim = SimpleNamespace(
            id="SIM1",
            owner_id=1,
            scene_config={
                "scenario_id": "council_chamber",
                "proposal_text": "Should the town fund a shared tool library?",
                "voting_threshold": 0.5,
                "max_rounds": 2,
            },
        )
        record = SimpleNamespace(
            tree=SimpleNamespace(
                nodes={
                    0: {
                        "logs": logs,
                        "parent": None,
                        "ops": [],
                    }
                }
            )
        )
        return sim, record

    monkeypatch.setattr(export_module, "extract_bearer_token", lambda request: "token")
    monkeypatch.setattr(export_module, "resolve_current_user", _fake_user)
    monkeypatch.setattr(export_module, "get_session", lambda: _FakeSessionContext())
    monkeypatch.setattr(export_module, "get_simulation_and_tree_for_owner", _fake_sim_and_tree)

    request = SimpleNamespace(headers={})
    response = await export_module.export_simulation.fn(request, "SIM1", format="csv")

    content = str(response.content)
    assert response.media_type == "text/csv"
    assert "timestamp,node_id,round,agent_id,type,action,follow_up" in content
    assert "alice,AGENT_ACTION,speak,We should fund the tool library." in content
    assert "bob,AGENT_ACTION,skip," in content
    assert "alice,AGENT_ACTION,vote_yes," in content
    assert "bob,AGENT_ACTION,abstain," in content
