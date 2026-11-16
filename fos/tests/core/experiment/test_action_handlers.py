"""
Tests for council, talk, and move action handlers in experiment.

Covers handle_move, handle_talk, handle_council_speak,
handle_start_voting, handle_vote, handle_vote_yes/no/abstain,
handle_conclude — the non-PGG handlers from handlers.py.

Contains: TestHandleMove, TestHandleTalk, TestHandleCouncilSpeak,
          TestHandleStartVoting, TestHandleVote, TestHandleConclude
"""

from fos.core.experiment.actions.handlers import (
    handle_abstain,
    handle_conclude,
    handle_council_speak,
    handle_move,
    handle_start_voting,
    handle_talk,
    handle_vote,
    handle_vote_no,
    handle_vote_yes,
)
from fos.core.experiment.state import ExperimentState


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_state(agent_names: list[str] | None = None) -> ExperimentState:
    """Create a minimal ExperimentState for handler tests."""
    state = ExperimentState()
    if agent_names:
        for name in agent_names:
            state.agents[name] = type("Agent", (), {
                "resources": {"deduction_budget": 5},
                "position": None,
            })()
    return state


def _make_scene(**attrs):
    """Create a mock scene object with given attributes."""
    return type("MockScene", (), attrs)()


# ── handle_move ───────────────────────────────────────────────────────────

class TestHandleMove:
    def test_move_north(self):
        state = _make_state(["Alice"])
        state.update_agent_position("Alice", (2, 2))
        result = handle_move("Alice", {"direction": "north"}, state)
        assert result["success"] is True
        assert result["new_position"] == (2, 1)

    def test_move_south(self):
        state = _make_state(["Alice"])
        state.update_agent_position("Alice", (0, 0))
        result = handle_move("Alice", {"direction": "south"}, state)
        assert result["new_position"] == (0, 1)

    def test_move_east(self):
        state = _make_state(["Alice"])
        state.update_agent_position("Alice", (3, 3))
        result = handle_move("Alice", {"direction": "east"}, state)
        assert result["new_position"] == (4, 3)

    def test_move_west(self):
        state = _make_state(["Alice"])
        state.update_agent_position("Alice", (3, 3))
        result = handle_move("Alice", {"direction": "west"}, state)
        assert result["new_position"] == (2, 3)

    def test_move_unknown_direction_gives_no_movement(self):
        state = _make_state(["Alice"])
        state.update_agent_position("Alice", (1, 1))
        result = handle_move("Alice", {"direction": "diagonal"}, state)
        assert result["success"] is True
        assert result["new_position"] == (1, 1)

    def test_move_fails_when_agent_has_no_position(self):
        state = _make_state(["Alice"])
        result = handle_move("Alice", {"direction": "north"}, state)
        assert result["success"] is False
        assert "no position" in result["error"].lower()


# ── handle_talk ───────────────────────────────────────────────────────────

class TestHandleTalk:
    def test_successful_talk(self):
        state = _make_state()
        result = handle_talk("Alice", {"target": "Bob", "message": "Hello"}, state)
        assert result["success"] is True
        assert result["from"] == "Alice"
        assert result["to"] == "Bob"
        assert result["message"] == "Hello"

    def test_talk_fails_without_target(self):
        state = _make_state()
        result = handle_talk("Alice", {"message": "Hello"}, state)
        assert result["success"] is False

    def test_talk_fails_without_message(self):
        state = _make_state()
        result = handle_talk("Alice", {"target": "Bob"}, state)
        assert result["success"] is False

    def test_talk_fails_with_empty_strings(self):
        state = _make_state()
        result = handle_talk("Alice", {"target": "", "message": ""}, state)
        assert result["success"] is False


# ── handle_council_speak ──────────────────────────────────────────────────

class TestHandleCouncilSpeak:
    def test_basic_speak(self):
        state = _make_state(["Alice", "Bob"])
        scene = _make_scene()
        result = handle_council_speak({"message": "I agree"}, "Alice", state, scene)
        assert result["success"] is True
        assert "Alice spoke: I agree" in result["summary"]

    def test_long_message_is_truncated_in_summary(self):
        state = _make_state(["Alice"])
        scene = _make_scene()
        long_msg = "x" * 200
        result = handle_council_speak({"message": long_msg}, "Alice", state, scene)
        assert result["success"] is True
        assert "..." in result["summary"]

    def test_speak_records_to_round_context_manager(self):
        state = _make_state(["Alice", "Bob"])
        recorded = {}
        rcm = type("RCM", (), {
            "record_action": lambda self, **kw: recorded.update(kw),
        })()
        scene = _make_scene(round_context_manager=rcm, round_num=3)
        handle_council_speak({"message": "Hi"}, "Alice", state, scene)
        assert recorded["agent_name"] == "Alice"
        assert recorded["round_num"] == 3

    def test_speak_records_only_neighbour_observers(self):
        state = _make_state(["Alice", "Bob", "Cara"])
        recorded = {}
        rcm = type("RCM", (), {
            "record_action": lambda self, **kw: recorded.update(kw),
        })()
        scene = _make_scene(
            round_context_manager=rcm,
            round_num=3,
            config=_make_scene(social_network={"edges": [("Alice", "Bob")]}),
        )
        handle_council_speak({"message": "Hi"}, "Alice", state, scene)
        assert sorted(recorded["observed_by"]) == ["Alice", "Bob"]


# ── handle_start_voting ──────────────────────────────────────────────────

class TestHandleStartVoting:
    def test_starts_voting_successfully(self):
        state = _make_state(["Alice"])
        scene = _make_scene()
        result = handle_start_voting({"title": "Budget proposal"}, "Alice", state, scene)
        assert result["success"] is True
        assert state.extensions["voting_started"] is True
        assert state.extensions["vote_title"] == "Budget proposal"

    def test_cannot_start_voting_twice(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        scene = _make_scene()
        result = handle_start_voting({"title": "Again"}, "Alice", state, scene)
        assert result["success"] is False

    def test_default_title_when_missing(self):
        state = _make_state(["Alice"])
        scene = _make_scene()
        handle_start_voting({}, "Alice", state, scene)
        assert state.extensions["vote_title"] == "the proposal"

    def test_transitions_facilitator(self):
        state = _make_state(["Alice"])
        transitions = []
        fac = type("Fac", (), {"transition_to_voting": lambda self, t: transitions.append(t)})()
        scene = _make_scene(facilitator=fac)
        handle_start_voting({"title": "Test"}, "Alice", state, scene)
        assert transitions == ["Test"]


# ── handle_vote ───────────────────────────────────────────────────────────

class TestHandleVote:
    def test_vote_yes(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        scene = _make_scene()
        result = handle_vote({"choice": "yes"}, "Alice", state, scene)
        assert result["success"] is True
        assert state.extensions["votes"]["Alice"] == "yes"

    def test_vote_no(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        scene = _make_scene()
        result = handle_vote({"choice": "no"}, "Alice", state, scene)
        assert result["success"] is True
        assert state.extensions["votes"]["Alice"] == "no"

    def test_vote_abstain(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        scene = _make_scene()
        result = handle_vote({"choice": "abstain"}, "Alice", state, scene)
        assert result["success"] is True

    def test_invalid_choice_rejected(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        scene = _make_scene()
        result = handle_vote({"choice": "maybe"}, "Alice", state, scene)
        assert result["success"] is False

    def test_vote_before_voting_started_rejected(self):
        state = _make_state(["Alice"])
        scene = _make_scene()
        result = handle_vote({"choice": "yes"}, "Alice", state, scene)
        assert result["success"] is False

    def test_vote_yes_handler(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        result = handle_vote_yes({}, "Alice", state, _make_scene())
        assert result["success"] is True
        assert state.extensions["votes"]["Alice"] == "yes"

    def test_vote_no_handler(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        handle_vote_no({}, "Alice", state, _make_scene())
        assert state.extensions["votes"]["Alice"] == "no"

    def test_abstain_handler(self):
        state = _make_state(["Alice"])
        state.extensions["voting_started"] = True
        handle_abstain({}, "Alice", state, _make_scene())
        assert state.extensions["votes"]["Alice"] == "abstain"

    def test_vote_records_only_neighbour_observers(self):
        state = _make_state(["Alice", "Bob", "Cara"])
        state.extensions["voting_started"] = True
        recorded = {}
        rcm = type("RCM", (), {
            "record_action": lambda self, **kw: recorded.update(kw),
        })()
        scene = _make_scene(
            round_context_manager=rcm,
            round_num=2,
            config=_make_scene(social_network={"edges": [("Alice", "Bob")]}),
        )
        handle_vote({"choice": "yes"}, "Alice", state, scene)
        assert sorted(recorded["observed_by"]) == ["Alice", "Bob"]


# ── handle_conclude ───────────────────────────────────────────────────────

class TestHandleConclude:
    def test_conclude_passes_with_majority(self):
        state = _make_state(["A", "B", "C"])
        state.extensions["voting_started"] = True
        state.extensions["votes"] = {"A": "yes", "B": "yes", "C": "no"}
        scene = _make_scene()
        result = handle_conclude({}, "A", state, scene)
        assert result["success"] is True
        assert result["passed"] is True
        assert state.extensions["proposal_passed"] is True

    def test_conclude_fails_without_majority(self):
        state = _make_state(["A", "B", "C"])
        state.extensions["voting_started"] = True
        state.extensions["votes"] = {"A": "no", "B": "no", "C": "yes"}
        result = handle_conclude({}, "A", state, _make_scene())
        assert result["passed"] is False

    def test_conclude_fails_before_voting(self):
        state = _make_state()
        result = handle_conclude({}, "A", state, _make_scene())
        assert result["success"] is False

    def test_conclude_with_zero_votes_fails(self):
        state = _make_state(["A"])
        state.extensions["voting_started"] = True
        state.extensions["votes"] = {}
        result = handle_conclude({}, "A", state, _make_scene())
        assert result["passed"] is False

    def test_conclude_uses_custom_threshold_from_game_config(self):
        state = _make_state(["A", "B"])
        state.extensions["voting_started"] = True
        state.extensions["votes"] = {"A": "yes", "B": "no"}
        config = type("Config", (), {"voting_threshold": 1.0})()
        scene = _make_scene(game_config=config)
        result = handle_conclude({}, "A", state, scene)
        assert result["passed"] is False  # 50% < 100%

    def test_conclude_uses_threshold_from_scene(self):
        state = _make_state(["A", "B"])
        state.extensions["voting_started"] = True
        state.extensions["votes"] = {"A": "yes", "B": "no"}
        scene = _make_scene(voting_threshold=1.0)
        result = handle_conclude({}, "A", state, scene)
        assert result["passed"] is False
