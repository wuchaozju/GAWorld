"""
Unit tests for scenario registry.

Tests scenario metadata and parameter definitions.
"""

from fos.core.scenarios.registry import (
    ALL_SCENARIOS,
    BATTLE_OF_THE_SEXES,
    CUSTOM,
    PUBLIC_GOODS,
    STAG_HUNT,
)


class TestBattleOfTheSexesParameters:
    """Tests for Battle of the Sexes scenario parameters."""

    def test_has_action_name_parameters(self):
        """Should have action_1_name and action_2_name parameters."""
        param_keys = [p["key"] for p in BATTLE_OF_THE_SEXES["parameters"]]
        assert "action_1_name" in param_keys
        assert "action_2_name" in param_keys

    def test_has_action_description_parameters(self):
        """Should have action description parameters."""
        param_keys = [p["key"] for p in BATTLE_OF_THE_SEXES["parameters"]]
        assert "action_1_description" in param_keys
        assert "action_2_description" in param_keys

    def test_action_defaults_match_hardcoded_actions(self):
        """Action parameter defaults should match the actions array."""
        params = {p["key"]: p["default"] for p in BATTLE_OF_THE_SEXES["parameters"]}
        assert params["action_1_name"] == "Opera"
        assert params["action_2_name"] == "Football"


class TestStagHuntParameters:
    """Tests for Stag Hunt scenario parameters."""

    def test_has_action_name_parameters(self):
        """Should have action_1_name and action_2_name parameters."""
        param_keys = [p["key"] for p in STAG_HUNT["parameters"]]
        assert "action_1_name" in param_keys
        assert "action_2_name" in param_keys

    def test_has_action_description_parameters(self):
        """Should have action description parameters."""
        param_keys = [p["key"] for p in STAG_HUNT["parameters"]]
        assert "action_1_description" in param_keys
        assert "action_2_description" in param_keys

    def test_action_defaults_match_hardcoded_actions(self):
        """Action parameter defaults should match the actions array."""
        params = {p["key"]: p["default"] for p in STAG_HUNT["parameters"]}
        assert params["action_1_name"] == "Stag"
        assert params["action_2_name"] == "Hare"


class TestPublicGoodsParameters:
    """Tests for Public Goods scenario parameters."""

    def test_has_resource_name_parameter(self):
        """Should have resource_name parameter."""
        param_keys = [p["key"] for p in PUBLIC_GOODS["parameters"]]
        assert "resource_name" in param_keys

    def test_has_deduction_params(self):
        """Should have all three deduction parameters."""
        param_keys = [p["key"] for p in PUBLIC_GOODS["parameters"]]
        assert "deduction_budget_per_phase" in param_keys
        assert "deduction_cost_ratio" in param_keys
        assert "deduction_anonymous" in param_keys

    def test_deduction_cost_ratio_default(self):
        """Should have deduction_cost_ratio default to 3.0."""
        params = {p["key"]: p["default"] for p in PUBLIC_GOODS["parameters"]}
        assert params["deduction_cost_ratio"] == 3.0

    def test_deduction_budget_param(self):
        """Should have deduction_budget_per_phase default to 0."""
        params = {p["key"]: p["default"] for p in PUBLIC_GOODS["parameters"]}
        assert params["deduction_budget_per_phase"] == 0

    def test_deduction_anonymous_param(self):
        """Should have deduction_anonymous default to False."""
        params = {p["key"]: p["default"] for p in PUBLIC_GOODS["parameters"]}
        assert params["deduction_anonymous"] is False

    def test_deduction_category(self):
        """All deduction parameters should have category='deduction'."""
        deduction_params = [
            p for p in PUBLIC_GOODS["parameters"]
            if p["key"].startswith("deduction_")
        ]
        assert len(deduction_params) == 3, "Should have exactly 3 deduction params"
        for param in deduction_params:
            assert param.get("category") == "deduction", (
                f"{param['key']} should have category='deduction'"
            )


class TestCustomScenario:
    """Tests for Custom Scenario v1 metadata."""

    def test_custom_has_prompt_and_turn_ordering_parameters(self):
        param_keys = [p["key"] for p in CUSTOM["parameters"]]
        assert param_keys == ["custom_prompt", "turn_ordering"]

    def test_custom_turn_ordering_options_are_v1_set(self):
        params = {p["key"]: p for p in CUSTOM["parameters"]}
        assert params["turn_ordering"]["options"] == [
            "sequential",
            "random_sequential",
            "simultaneous",
        ]

    def test_custom_actions_are_speak_and_skip_only(self):
        assert [a["id"] for a in CUSTOM["actions"]] == ["speak", "skip"]

    def test_custom_uses_neighbor_grouping(self):
        assert CUSTOM["grouping_mode"] == "neighbor"


class TestScenarioList:
    """Tests for the user-visible scenario list."""

    def test_policy_meaning_erosion_appears_once(self):
        policy_like = [
            scenario["id"]
            for scenario in ALL_SCENARIOS
            if scenario["id"] in {"policy_erosion", "policy_cascade_experiment"}
        ]

        assert policy_like == ["policy_erosion"]
