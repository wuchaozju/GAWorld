from types import SimpleNamespace

from fos.backend.services.simtree_runtime import (
    ExperimentRunnerAdapter,
    SimTreeRecord,
    SimTreeRegistry,
)
from fos.backend.services.environment_suggestion_service import _deliver_notice_only_event
from fos.core.event import PublicEvent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.simtree import SimTree


def _make_custom_scene() -> ExperimentScene:
    return ExperimentScene(
        ExperimentConfig(
            scenario_id="custom",
            agents=[
                {
                    "name": "Alice",
                    "role_prompt": "You are Alice.",
                    "documents": {"doc_a": {"id": "doc_a", "filename": "alice.txt"}},
                },
                {
                    "name": "Bob",
                    "role_prompt": "You are Bob.",
                },
            ],
            actions=[{"name": "speak"}],
            global_knowledge={"gk_1": {"id": "gk_1", "content": "Shared context"}},
        )
    )


def test_custom_scene_initializes_documents_and_serializes_global_knowledge():
    scene = _make_custom_scene()
    scene.initialize(object())

    assert scene.agents[0].documents["doc_a"]["filename"] == "alice.txt"

    snapshot = scene.serialize_config()
    assert snapshot["config"]["global_knowledge"]["gk_1"]["content"] == "Shared context"
    assert snapshot["config"]["agents"][0]["documents"]["doc_a"]["filename"] == "alice.txt"


def test_experiment_runner_adapter_broadcast_reaches_selected_custom_agents():
    scene = _make_custom_scene()
    adapter = ExperimentRunnerAdapter(scene, {"chat": object()})

    adapter.broadcast(PublicEvent("Incoming host message", prefix="SYSTEM BROADCAST"), receivers=["Alice"])

    agents = {agent.name: agent for agent in scene.agents}
    assert "Incoming host message" in agents["Alice"].get_feedback_text()
    assert agents["Bob"].get_feedback_text() == ""
    assert adapter.events[-1]["type"] == "system_broadcast"
    assert adapter.events[-1]["data"]["recipients"] == ["Alice"]


def test_registry_updates_custom_runtime_knowledge_documents_and_global_knowledge():
    scene = _make_custom_scene()
    adapter = ExperimentRunnerAdapter(scene, {"chat": object()})
    tree = SimpleNamespace(nodes={0: {"sim": adapter}})
    record = SimTreeRecord(tree)
    registry = SimTreeRegistry()
    registry._records["SIM1"] = record

    updated = registry.update_agent_knowledge(
        "sim1",
        {
            "agents": [
                {
                    "name": "Alice",
                    "knowledgeBase": [{"title": "KB", "content": "Fresh fact"}],
                    "documents": {"doc_new": {"id": "doc_new", "filename": "fresh.pdf"}},
                }
            ]
        },
    )
    assert updated is True
    alice = next(agent for agent in scene.agents if agent.name == "Alice")
    assert alice.knowledge_base[0]["title"] == "KB"
    assert alice.documents["doc_new"]["filename"] == "fresh.pdf"
    assert scene.config.agents[0]["documents"]["doc_new"]["filename"] == "fresh.pdf"

    updated_global = registry.update_global_knowledge(
        "sim1",
        {"gk_2": {"id": "gk_2", "content": "Updated shared context"}},
    )
    assert updated_global is True
    assert scene.global_knowledge["gk_2"]["content"] == "Updated shared context"
    assert scene.config.global_knowledge["gk_2"]["content"] == "Updated shared context"


def test_private_notice_only_event_targets_selected_custom_agents():
    scene = _make_custom_scene()
    adapter = ExperimentRunnerAdapter(scene, {"chat": object()})

    _deliver_notice_only_event(
        adapter,
        description="Private host nudge",
        mode="environment",
        is_policy_scene=False,
        receivers=["Bob"],
    )

    agents = {agent.name: agent for agent in scene.agents}
    assert agents["Alice"].get_feedback_text() == ""
    assert "Private host nudge" in agents["Bob"].get_feedback_text()


def test_apply_agent_overrides_updates_custom_agent_runtime_and_config():
    scene = _make_custom_scene()
    adapter = ExperimentRunnerAdapter(scene, {"chat": object(), "providers": {99: object()}})
    tree = SimTree(clients={})
    tree.nodes[0] = {"id": 0, "parent": None, "depth": 0, "edge_type": "root", "ops": [], "sim": adapter, "logs": [], "meta": {}}

    tree.apply_agent_overrides(
        0,
        [
            {
                "name": "Alice",
                "provider_id": 99,
                "llm_config": {"provider": "mock", "model": "custom-model"},
                "properties": {"stance": "updated"},
                "knowledge_base": [{"title": "Override KB", "content": "fresh"}],
                "documents": {"doc_z": {"id": "doc_z", "filename": "z.txt"}},
            }
        ],
    )

    alice = next(agent for agent in scene.agents if agent.name == "Alice")
    assert alice.provider_id == 99
    assert alice.properties["stance"] == "updated"
    assert alice.knowledge_base[0]["title"] == "Override KB"
    assert alice.documents["doc_z"]["filename"] == "z.txt"
    assert scene.config.agents[0]["properties"]["stance"] == "updated"
    assert scene.config.agents[0]["documents"]["doc_z"]["filename"] == "z.txt"
