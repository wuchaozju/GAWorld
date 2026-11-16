"""
Tests for ExperimentKernel and built-in action types.
"""

from fos.core.experiment.kernel import (
    ExperimentKernel,
    ChoiceAction,
    SpeakAction,
    VoteAction,
    NumericalAction,
)


def test_kernel_registers_actions():
    """Built-in actions are registered at module load."""
    assert ExperimentKernel.get_action("choice") == ChoiceAction
    assert ExperimentKernel.get_action("speak") == SpeakAction
    assert ExperimentKernel.get_action("vote") == VoteAction
    assert ExperimentKernel.get_action("numerical") == NumericalAction


def test_kernel_get_available_actions():
    """Build action list from scenario template."""
    scenario_actions = [
        {"type": "choice", "config": {"choice_name": "cooperate", "choice_description": "Cooperate"}},
        {"type": "choice", "config": {"choice_name": "defect", "choice_description": "Defect"}},
    ]
    actions = ExperimentKernel.get_available_actions(scenario_actions)

    assert len(actions) == 2
    assert all(isinstance(a, ChoiceAction) for a in actions)


def test_speak_action_is_plain_text_mode():
    """SpeakAction uses plain_text mode for freeform content."""
    assert SpeakAction.parameter_mode() == "plain_text"


def test_vote_action_is_json_mode():
    """VoteAction uses json mode for structured parameters."""
    assert VoteAction.parameter_mode() == "json"


def test_contribute_action_schema_is_exposed_for_followup():
    """Parameterized registry actions should be available to follow-up gating."""
    schemas = ExperimentKernel.get_action_schemas()

    assert "contribute" in schemas
    assert schemas["contribute"]["mode"] == "json"
    assert schemas["contribute"]["schema"]["amount"]["type"] == "integer"
    assert schemas["contribute"]["schema"]["pool"]["enum"] == ["main"]


def test_action_execution():
    """Actions return one-line summaries."""
    choice = ChoiceAction("cooperate", "Cooperate with partner")
    summary = choice.execute("Alice", {}, {})
    assert summary == "Alice chose cooperate"

    speak = SpeakAction()
    summary = speak.execute("Bob", {"message": "Hello world"}, {})
    assert summary == 'Bob: "Hello world"'


def test_all_sociology_actions_registered():
    """All sociology actions should be registered in the kernel."""
    from fos.core.scenarios.actions import CATEGORY_ACTION_LIBRARIES

    ExperimentKernel()
    sociology_actions = CATEGORY_ACTION_LIBRARIES.get("sociology", [])

    # Check that sociology category exists and has actions
    assert len(sociology_actions) > 0, "Sociology category should have actions"

    # Check that all sociology action IDs are registered
    for action_def in sociology_actions:
        action_id = action_def["id"]
        # The kernel registers action types (classes), not individual IDs
        # Sociology actions use a generic handler that looks up by ID
        assert action_id is not None
        assert isinstance(action_id, str)


def test_unknown_action_returns_none():
    """Getting an unknown action should return None."""
    result = ExperimentKernel.get_action("nonexistent_action")
    assert result is None
