"""
Multi-round integration tests for PolicyCascadeExperimentScene.

Tests four behavioral gaps in the Pipeline A port:
1. Tier progression across rounds
2. Distortion detection with crafted agent/policy profiles
3. Thread management via _SimulatorAdapter
4. _reset_agents_for_new_policy with ExperimentAgent

All tests use mock LLM and unittest.mock — no real Ollama.

Contains: TestTierProgression, TestDistortionDetection,
          TestThreadManagementViaAdapter, TestResetAgentsForNewPolicy
"""

from unittest.mock import MagicMock


from fos.core.experiment.config import ExperimentConfig
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig
from fos.core.scenes.policy_cascade_experiment import (
    PolicyCascadeExperimentScene,
    _SimulatorAdapter,
)


def _make_config(**overrides):
    """Create an ExperimentConfig with 3-tier agents for cascade testing."""
    defaults = {
        "agents": [
            {
                "name": "Director",
                "properties": {"tier": "high"},
                "llm_config": {"dialect": "mock"},
            },
            {
                "name": "Manager",
                "properties": {"tier": "mid"},
                "llm_config": {"dialect": "mock"},
            },
            {
                "name": "Worker",
                "properties": {"tier": "low"},
                "llm_config": {"dialect": "mock"},
            },
        ],
        "actions": [
            {"name": "send_message", "description": "Send a message"},
            {"name": "yield", "description": "End your turn"},
        ],
        "parameters": {"tier_order": ["high", "mid", "low"]},
    }
    defaults.update(overrides)
    return ExperimentConfig(**defaults)


def _make_scene(**config_overrides):
    """Create and initialize a PolicyCascadeExperimentScene."""
    config = _make_config(**config_overrides)
    scene = PolicyCascadeExperimentScene(config)
    scene.initialize(LLMClient(LLMConfig(dialect="mock")))
    return scene


def _setup_cascade_state(scene):
    """Put scene into cascade mode with a policy ready for transmission."""
    scene.state["task_mode"] = "cascade"
    scene.state["latest_policy"] = "Test policy: execute immediately"
    scene.state["source_policy"] = "Test policy: execute immediately"
    scene.state["relayed_policy"] = "Test policy: execute immediately"
    scene.state["tier_seen"] = {t: [] for t in scene.tier_order}
    scene.state["tier_transmitted"] = {t: False for t in scene.tier_order}
    scene.state["policy_version"] = 1
    scene.state["force_complete_current_cascade"] = True
    scene._rebuild_tiers()
    scene._normalize_active_tier()


# ======================================================================
# Gap 1: Tier progression across rounds
# ======================================================================


class TestTierProgression:
    """Assert that tier state advances through high -> mid -> low."""

    def test_tier_starts_at_first_tier(self):
        """Initial current_tier_idx should be 0 (first tier)."""
        scene = _make_scene()
        _setup_cascade_state(scene)
        assert scene.state["current_tier_idx"] == 0

    def test_tier_advances_after_all_agents_in_first_tier_act(self):
        """After Director acts, current_tier_idx should advance to mid (1)."""
        scene = _make_scene()
        _setup_cascade_state(scene)
        sim = scene.simulator

        director = scene._agents_dict["Director"]
        scene.post_turn(director, sim)

        assert scene.state["current_tier_idx"] == 1

    def test_tier_advances_through_three_tiers(self):
        """Tier advances high -> mid -> low across three post_turn calls."""
        scene = _make_scene()
        _setup_cascade_state(scene)
        sim = scene.simulator

        director = scene._agents_dict["Director"]
        manager = scene._agents_dict["Manager"]
        worker = scene._agents_dict["Worker"]

        # Round 1: Director (high tier) acts
        scene.post_turn(director, sim)
        assert scene.state["current_tier_idx"] == 1

        # Round 2: Manager (mid tier) acts
        scene.post_turn(manager, sim)
        assert scene.state["current_tier_idx"] == 2

        # Round 3: Worker (low tier) acts — cascade completes
        scene.post_turn(worker, sim)
        assert scene.state["current_tier_idx"] >= 2
        assert scene.state["complete"] is True

    def test_tier_transmitted_marks_tier_after_agent_acts(self):
        """After an agent in a tier transmits, tier_transmitted should be set."""
        scene = _make_scene()
        _setup_cascade_state(scene)
        sim = scene.simulator

        director = scene._agents_dict["Director"]
        # Mark tier as transmitted (normally done by deliver_message)
        scene.state.setdefault("tier_transmitted", {t: False for t in scene.tier_order})
        scene.state["tier_transmitted"]["high"] = True

        scene.post_turn(director, sim)

        # After Director acts and tier completes, we should have advanced
        assert scene.state["current_tier_idx"] == 1


# ======================================================================
# Gap 2: Distortion detection
# ======================================================================


class TestDistortionDetection:
    """Assert distortion methods produce correct results with ExperimentAgent."""

    def test_should_block_true_for_burdened_low_tier_agent(self):
        """Low-tier agent with heavy burden should block in distortion_cascade."""
        scene = _make_scene(
            parameters={
                "tier_order": ["high", "mid", "low"],
                "cascade_mode": "distortion_cascade",
                "distortion_strength": 0.8,
                "conflict_sensitivity": 0.7,
                "block_probability": 0.4,
            }
        )

        policy = (
            "执行要求：必须立即完成排查\n"
            "报告要求：报送台账签到表\n"
            "责任分工：考核问责压实责任\n"
        )
        scene.state["source_policy"] = policy
        scene.state["relayed_policy"] = policy
        scene.state["latest_notice"] = policy

        worker = scene._agents_dict["Worker"]
        worker.role_prompt = "基层执行人员 负担 压力 繁琐 一线 基层"
        worker.properties["workload"] = "负担重 压力大"

        result = scene._should_block(worker, "low")
        assert result is True

    def test_conflict_pressure_nonzero_for_low_tier(self):
        """Low-tier agent should have non-zero conflict pressure."""
        scene = _make_scene(
            parameters={"cascade_mode": "distortion_cascade"}
        )

        policy = "执行要求：必须完成 责任分工：考核问责"
        scene.state["source_policy"] = policy
        scene.state["relayed_policy"] = policy
        scene.state["latest_notice"] = policy

        worker = scene._agents_dict["Worker"]
        pressure = scene._conflict_pressure(worker, "low")
        assert pressure > 0.0

    def test_conflict_pressure_higher_for_low_than_top(self):
        """Low-tier agent should have higher conflict pressure than top-tier."""
        scene = _make_scene(
            parameters={"cascade_mode": "distortion_cascade"}
        )

        policy = "执行要求：必须完成 责任分工：考核问责"
        scene.state["source_policy"] = policy
        scene.state["relayed_policy"] = policy
        scene.state["latest_notice"] = policy

        worker = scene._agents_dict["Worker"]
        director = scene._agents_dict["Director"]

        low_pressure = scene._conflict_pressure(worker, "low")
        top_pressure = scene._conflict_pressure(director, "high")
        assert low_pressure > top_pressure

    def test_distort_message_changes_output_at_high_strength(self):
        """_distort_message should alter the message at high distortion_strength."""
        scene = _make_scene(
            parameters={
                "cascade_mode": "distortion_cascade",
                "distortion_strength": 0.8,
            }
        )

        policy = "执行要求：必须完成排查整改\n报告要求：报送台账签到表\n"
        scene.state["source_policy"] = policy
        scene.state["relayed_policy"] = policy

        worker = scene._agents_dict["Worker"]
        original = policy
        distorted = scene._distort_message(worker, "low", original)
        assert distorted != original


# ======================================================================
# Gap 3: Thread management via _SimulatorAdapter
# ======================================================================


class TestThreadManagementViaAdapter:
    """Assert thread methods work correctly through the _SimulatorAdapter."""

    def test_open_thread_stores_thread_and_emits_event(self):
        """_open_thread should store thread and emit via adapter."""
        scene = _make_scene()
        scene._current_round = 1
        events = []
        scene._event_emitter = lambda t, d: events.append((t, d))
        scene._rebuild_tiers()

        sim = scene.simulator
        sender = scene._agents_dict["Director"]

        thread = scene._open_thread(
            "upward_feedback",
            sender,
            "Manager",
            "Resource shortage at branch level",
            sim,
            {"auto_generated": True, "policy_version": 1},
        )

        assert thread is not None
        assert thread["kind"] == "upward_feedback"
        assert thread["root_sender"] == "Director"
        assert thread["id"] in scene.state.get("conversation_threads", {})

        emitted_types = [t for t, d in events]
        assert "policy_thread_opened" in emitted_types

    def test_reply_to_thread_updates_history_via_adapter(self):
        """_reply_to_thread should add to thread history through adapter."""
        scene = _make_scene()
        scene._current_round = 1
        events = []
        scene._event_emitter = lambda t, d: events.append((t, d))
        scene._rebuild_tiers()

        sim = scene.simulator
        sender = scene._agents_dict["Director"]

        thread = scene._open_thread(
            "peer_consult",
            sender,
            "Manager",
            "Should we adjust the timeline?",
            sim,
            {},
        )

        # Reply from Manager
        scene._current_round = 2
        manager = scene._agents_dict["Manager"]
        scene._reply_to_thread(thread, manager, "Yes adjust to Q2", sim)

        updated = scene._thread_for_id(thread["id"])
        assert len(updated.get("history", [])) >= 2
        assert updated["status"] == "responded"

        emitted_types = [t for t, d in events]
        assert "policy_thread_reply" in emitted_types

    def test_ignore_thread_marks_status_via_adapter(self):
        """_ignore_thread should set status to 'ignored' through adapter."""
        scene = _make_scene()
        scene._current_round = 1
        events = []
        scene._event_emitter = lambda t, d: events.append((t, d))
        scene._rebuild_tiers()

        sim = scene.simulator
        sender = scene._agents_dict["Manager"]

        thread = scene._open_thread(
            "upward_feedback",
            sender,
            "Director",
            "Staffing shortage",
            sim,
            {},
        )

        scene._ignore_thread(thread, sender, sim)

        updated = scene._thread_for_id(thread["id"])
        assert updated.get("status") == "ignored"

        emitted_types = [t for t, d in events]
        assert "policy_thread_ignored" in emitted_types

    def test_adapter_emit_event_delegates_to_scene_emit(self):
        """_SimulatorAdapter.emit_event should call scene._emit."""
        scene = _make_scene()
        events = []
        scene._event_emitter = lambda t, d: events.append((t, d))

        adapter = _SimulatorAdapter(scene)
        adapter.emit_event("test_event", {"key": "value"})

        assert len(events) == 1
        assert events[0] == ("test_event", {"key": "value"})

    def test_adapter_broadcast_adds_to_feedback_buffer(self):
        """_SimulatorAdapter.broadcast should inject into feedback buffers."""
        scene = _make_scene()
        adapter = _SimulatorAdapter(scene)

        event = MagicMock()
        event.content = "Policy update received"

        adapter.broadcast(event, receivers=["Director", "Manager"])

        director = scene._agents_dict["Director"]
        manager = scene._agents_dict["Manager"]
        worker = scene._agents_dict["Worker"]

        assert "Policy update received" in director.feedback_buffer
        assert "Policy update received" in manager.feedback_buffer
        assert worker.feedback_buffer == []


# ======================================================================
# Gap 4: _reset_agents_for_new_policy with ExperimentAgent
# ======================================================================


class TestResetAgentsForNewPolicy:
    """Assert _reset_agents_for_new_policy works with ExperimentAgent.

    ExperimentAgent has feedback_buffer, not short_memory.
    The reset method must handle this difference gracefully.
    """

    def test_reset_clears_feedback_buffer(self):
        """After reset, agent feedback_buffer should be cleared."""
        scene = _make_scene()
        sim = scene.simulator

        for agent in scene._agents_dict.values():
            agent.add_env_feedback("pending feedback")
            assert len(agent.feedback_buffer) > 0

        scene._reset_agents_for_new_policy(sim)

        for agent in scene._agents_dict.values():
            assert agent.feedback_buffer == []

    def test_reset_handles_experiment_agent_without_errors(self):
        """_reset_agents_for_new_policy must not crash on ExperimentAgent.

        ExperimentAgent lacks consecutive_llm_errors, is_offline,
        and short_memory. The reset must handle these gracefully.
        """
        scene = _make_scene()
        sim = scene.simulator

        scene._reset_agents_for_new_policy(sim)
        # If we reach here without exception, the method handled it

    def test_reset_on_event_triggers_without_crash(self):
        """on_event with a broadcast should trigger reset without crashing."""
        scene = _make_scene()
        scene._rebuild_tiers()
        events = []
        scene._event_emitter = lambda t, d: events.append((t, d))

        data = {
            "description": "New policy directive for all departments",
            "content": "New policy directive for all departments",
        }

        scene.on_event(scene.simulator, "broadcast", data)
        # Should not crash — _reset_agents_for_new_policy is called inside
