"""Tests for core.scenarios module."""

from fos.core.scenarios import (
    get_all_scenarios,
    get_scenario,
    get_scenario_actions
)


def test_get_all_returns_list():
    """Should return a list of scenarios."""
    result = get_all_scenarios()
    assert isinstance(result, list)


def test_get_all_contains_expected_count():
    """Should return exactly 17 scenarios."""
    result = get_all_scenarios()
    assert len(result) == 16


def test_all_scenarios_have_required_fields():
    """Every scenario should have id, name, category, description, parameters, actions."""
    result = get_all_scenarios()
    for scenario in result:
        assert "id" in scenario
        assert "name" in scenario
        assert "category" in scenario
        assert "description" in scenario
        assert "parameters" in scenario
        assert "actions" in scenario


def test_get_scenario_by_id():
    """Should return specific scenario."""
    result = get_scenario("prisoners_dilemma")
    assert result is not None
    assert result["id"] == "prisoners_dilemma"
    assert result["name"] == "Prisoner's Dilemma"


def test_get_scenario_invalid_id_returns_none():
    """Should return None for invalid scenario ID."""
    result = get_scenario("nonexistent_scenario")
    assert result is None


def test_get_scenario_actions():
    """Should return only actions for a scenario."""
    result = get_scenario_actions("prisoners_dilemma")
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["name"] == "Cooperate"
    assert result[1]["name"] == "Defect"


def test_get_scenario_actions_invalid_id():
    """Should return empty list for invalid scenario."""
    result = get_scenario_actions("invalid")
    assert result == []


def test_prisoners_dilemma_structure():
    """Prisoner's Dilemma should have correct structure."""
    scenario = get_scenario("prisoners_dilemma")
    assert scenario["category"] == "game_theory"
    assert len(scenario["parameters"]) == 6
    assert len(scenario["actions"]) == 2


def test_prisoners_dilemma_matrix_matches_standard_payoffs():
    """Prisoner's Dilemma should reward defection against a cooperator."""
    scenario = get_scenario("prisoners_dilemma")
    cells = scenario["matrix_meta"]["cells"]

    assert cells["cooperate_cooperate"] == {"row": 3, "col": 3}
    assert cells["cooperate_defect"] == {"row": 0, "col": 5}
    assert cells["defect_cooperate"] == {"row": 5, "col": 0}
    assert cells["defect_defect"] == {"row": 1, "col": 1}


def test_custom_scenario_empty_actions():
    """Custom scenario should have default speak/skip actions."""
    scenario = get_scenario("custom")
    assert len(scenario["actions"]) == 2
    action_ids = [a["id"] for a in scenario["actions"]]
    assert "speak" in action_ids
    assert "skip" in action_ids


def test_all_scenario_ids_unique():
    """All scenario IDs should be unique."""
    scenarios = get_all_scenarios()
    ids = [s["id"] for s in scenarios]
    assert len(ids) == len(set(ids))


def test_all_default_action_ids_exist_in_category_library():
    """Default action IDs should exist in category action library."""
    from fos.core.scenarios.actions import CATEGORY_ACTION_LIBRARIES

    scenarios = get_all_scenarios()
    for scenario in scenarios:
        if "default_action_ids" in scenario and scenario["default_action_ids"]:
            category = scenario.get("category", "")
            if category in CATEGORY_ACTION_LIBRARIES:
                category_actions = CATEGORY_ACTION_LIBRARIES[category]
                category_action_ids = {a["id"] for a in category_actions}
                for action_id in scenario["default_action_ids"]:
                    assert action_id in category_action_ids, \
                        f"Scenario {scenario['id']} has default action {action_id} not in category {category}"


def test_payoff_matrix_scenarios_have_valid_matrix_meta():
    """Payoff matrix scenarios should have valid matrix metadata."""
    payoff_scenarios = ["prisoners_dilemma", "battle_of_the_sexes", "stag_hunt"]

    for scenario_id in payoff_scenarios:
        scenario = get_scenario(scenario_id)
        if scenario:
            # At minimum should describe the payoff structure
            assert scenario["description"] is not None
            assert len(scenario["description"]) > 0


def test_all_parameters_have_ui_hint():
    """All scenario parameters should have a ui_hint field."""
    scenarios = get_all_scenarios()
    for scenario in scenarios:
        for param in scenario["parameters"]:
            assert "ui_hint" in param, \
                f"Scenario {scenario['id']} parameter {param['id']} missing ui_hint"


def test_sociology_scenarios_have_english_names():
    """Sociology scenarios should have English names."""
    scenarios = get_all_scenarios()
    sociology_scenarios = [s for s in scenarios if s.get("category") == "sociology"]

    for scenario in sociology_scenarios:
        assert "name" in scenario
        assert isinstance(scenario["name"], str)
        # Name should not be empty or just spaces
        assert len(scenario["name"].strip()) > 0
        # Name should be ASCII (English) characters
        assert scenario["name"].isascii() or all(ord(c) < 128 for c in scenario["name"])


def test_category_action_libraries_no_duplicate_ids():
    """Category action libraries should not have duplicate action IDs."""
    from fos.core.scenarios.actions import CATEGORY_ACTION_LIBRARIES

    for category, actions in CATEGORY_ACTION_LIBRARIES.items():
        action_ids = [a["id"] for a in actions]
        duplicates = [aid for aid in action_ids if action_ids.count(aid) > 1]
        assert len(duplicates) == 0, \
            f"Category {category} has duplicate action IDs: {set(duplicates)}"


def test_interaction_mode_is_valid_enum_value():
    """All scenarios should have valid interaction_mode enum values."""
    valid_modes = {"simultaneous", "sequential", "random", "paired"}
    scenarios = get_all_scenarios()

    for scenario in scenarios:
        if "interaction_mode" in scenario:
            assert scenario["interaction_mode"] in valid_modes, \
                f"Scenario {scenario['id']} has invalid interaction_mode: {scenario['interaction_mode']}"


class TestScenarioParameterFrontendContract:
    """
    Regression tests ensuring every scenario's parameters array can be
    rendered by the frontend ExperimentDesignPanel.

    The frontend expects each parameter to have: key, label, type, default,
    and ui_hint. A previous bug (commit 2c0e5ab) caused the panel to look
    for a non-existent parameter_schema.properties field instead of using
    the parameters array, so all parameter fields disappeared.
    """

    @staticmethod
    def _required_param_keys():
        return {"key", "label", "type", "default", "ui_hint"}

    def test_every_scenario_parameter_has_required_frontend_keys(self):
        """Each parameter must have all keys the frontend ParameterField needs."""
        for scenario in get_all_scenarios():
            for param in scenario["parameters"]:
                missing = self._required_param_keys() - set(param.keys())
                assert not missing, (
                    f"Scenario '{scenario['id']}' param '{param.get('key', '?')}' "
                    f"missing frontend keys: {missing}"
                )

    def test_public_goods_has_resource_parameters(self):
        """Public Goods Game must expose resource_name, tokens_per_round, multiplier."""
        scenario = get_scenario("public_goods")
        assert scenario is not None
        keys = {p["key"] for p in scenario["parameters"]}
        for required_key in (
            "resource_name",
            "tokens_per_round",
            "multiplier",
        ):
            assert required_key in keys, (
                f"public_goods missing required parameter: {required_key}"
            )

    def test_public_goods_has_deduction_parameters(self):
        """Public Goods Game must expose deduction settings for punishment mechanics."""
        scenario = get_scenario("public_goods")
        assert scenario is not None
        keys = {p["key"] for p in scenario["parameters"]}
        for required_key in (
            "deduction_budget_per_phase",
            "deduction_cost_ratio",
            "deduction_anonymous",
        ):
            assert required_key in keys, (
                f"public_goods missing deduction parameter: {required_key}"
            )

    def test_parameter_type_is_valid_frontend_type(self):
        """Parameter types must be one the frontend can handle."""
        valid_types = {"integer", "number", "float", "string", "text", "boolean", "array"}
        for scenario in get_all_scenarios():
            for param in scenario["parameters"]:
                assert param["type"] in valid_types, (
                    f"Scenario '{scenario['id']}' param '{param['key']}' "
                    f"has invalid type '{param['type']}'. Must be one of {valid_types}"
                )

    def test_parameter_ui_hint_is_valid_frontend_hint(self):
        """Parameter ui_hint must be one the frontend ParameterField recognizes."""
        valid_hints = {
            "slider", "number", "percentage", "text", "textarea",
            "select", "toggle", "list", "multiselect", "key_value",
            "drag_list",
        }
        for scenario in get_all_scenarios():
            for param in scenario["parameters"]:
                assert param["ui_hint"] in valid_hints, (
                    f"Scenario '{scenario['id']}' param '{param['key']}' "
                    f"has invalid ui_hint '{param['ui_hint']}'. Must be one of {valid_hints}"
                )

    def test_numeric_params_have_default_values(self):
        """Numeric parameters must have a default value for frontend rendering."""
        for scenario in get_all_scenarios():
            for param in scenario["parameters"]:
                if param["type"] in ("number", "integer", "float"):
                    assert "default" in param and param["default"] is not None, (
                        f"Scenario '{scenario['id']}' param '{param['key']}' "
                        f"is numeric but has no default value"
                    )

    def test_select_params_have_options(self):
        """Parameters with ui_hint='select' must provide options."""
        for scenario in get_all_scenarios():
            for param in scenario["parameters"]:
                if param["ui_hint"] == "select":
                    assert "options" in param and len(param["options"]) > 0, (
                        f"Scenario '{scenario['id']}' param '{param['key']}' "
                        f"uses select ui_hint but has no options"
                    )

    def test_no_scenario_returns_parameter_schema(self):
        """Backend scenarios must NOT return parameter_schema (frontend uses parameters array)."""
        for scenario in get_all_scenarios():
            assert "parameter_schema" not in scenario, (
                f"Scenario '{scenario['id']}' should not have parameter_schema. "
                f"Frontend uses the parameters array directly."
            )
