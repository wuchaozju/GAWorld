"""This file checks that the old policy cascade scene can be copied safely.

The tests make sure saved scene data comes back as the same kind of scene.
"""

from fos.core.scenes.policy_cascade import PolicyCascadeScene


class FakeAgent:
    """A small agent used to test scene tier movement."""

    def __init__(self, name: str, tier: str = "", properties: dict | None = None) -> None:
        self.name = name
        self.properties = properties if properties is not None else {"tier": tier}
        self.role_prompt = ""
        self.user_profile = ""
        self.feedback: list[str] = []

    def add_env_feedback(self, message: str) -> None:
        self.feedback.append(message)


class FakeSimulator:
    """A small simulator used to capture scene events."""

    def __init__(self, agents: list[FakeAgent]) -> None:
        self.agents = {agent.name: agent for agent in agents}
        self.events: list[tuple[str, dict]] = []

    def emit_event(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))

    def emit_event_later(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))


def test_policy_cascade_scene_deserialize_keeps_scene_type() -> None:
    """A copied policy cascade scene is still a policy cascade scene."""
    scene = PolicyCascadeScene(
        name="policy erosion",
        initial_event="Share the new policy carefully.",
        tier_order=["top", "middle", "street"],
    )
    scene.state["latest_policy"] = "Protect the original policy meaning."

    cloned = PolicyCascadeScene.deserialize(scene.serialize())

    assert isinstance(cloned, PolicyCascadeScene)
    assert cloned.TYPE == "policy_cascade_scene"
    assert cloned.name == scene.name
    assert cloned.initial_event == scene.initial_event
    assert cloned.state == scene.state
    assert cloned.tier_order == ["top", "middle", "street"]
    assert cloned._tier_map == {}
    assert cloned._agents_by_tier == {"top": [], "middle": [], "street": []}


def test_notice_phase_does_not_call_full_network_a_dead_end() -> None:
    """A notice can move to the next tier without being a cascade dead end."""
    agents = [
        FakeAgent("Agent 1", "top"),
        FakeAgent("Agent 2", "mid"),
        FakeAgent("Agent 3", "low"),
    ]
    simulator = FakeSimulator(agents)
    scene = PolicyCascadeScene(
        name="policy erosion",
        initial_event="Initial policy background.",
        tier_order=["top", "mid", "low"],
    )
    scene.state["social_network"] = {
        "Agent 1": ["Agent 2", "Agent 3"],
        "Agent 2": ["Agent 1", "Agent 3"],
        "Agent 3": ["Agent 1", "Agent 2"],
    }
    scene.set_simulator(simulator)

    scene.post_turn(agents[0], simulator)

    event_types = [event_type for event_type, _data in simulator.events]
    assert "cascade_network_dead_end" not in event_types
    assert scene.state["current_tier_idx"] == 1
    assert scene.state["complete"] is False


def test_policy_cascade_recognizes_tier_level_property() -> None:
    """Saved agents from older or generated paths can use tier_level."""
    agents = [
        FakeAgent("Agent 1", properties={"tier_level": "top"}),
        FakeAgent("Agent 2", properties={"tier_level": "mid"}),
    ]
    simulator = FakeSimulator(agents)
    scene = PolicyCascadeScene(
        name="policy erosion",
        initial_event="Initial policy background.",
        tier_order=["top", "mid", "low"],
    )

    scene.set_simulator(simulator)

    assert scene._tier_map["Agent 1"] == "top"
    assert scene._tier_map["Agent 2"] == "mid"


def test_policy_cascade_send_message_emits_log_event_with_explicit_tier() -> None:
    """A valid tiered policy action must reach the UI event stream."""
    agents = [
        FakeAgent("Agent 1", "top"),
        FakeAgent("Agent 2", "mid"),
        FakeAgent("Agent 3", "low"),
    ]
    simulator = FakeSimulator(agents)
    scene = PolicyCascadeScene(
        name="policy erosion",
        initial_event="Initial policy background.",
        tier_order=["top", "mid", "low"],
    )
    scene.set_simulator(simulator)

    success, result, summary, _meta, _yielded = scene.parse_and_handle_action(
        {"action": "send_message", "message": "Please relay the policy."},
        agents[0],
        simulator,
    )

    assert success is True
    assert isinstance(result.get("message"), str)
    assert result["message"]
    assert "Agent 1" in str(summary)
    event_types = [event_type for event_type, _data in simulator.events]
    assert "system_broadcast" in event_types
