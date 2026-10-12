"""
Tests for core.scenarios.registry coverage gaps.

Tests _translate_scenario, supported-scenario filtering, category_actions
resolution, and mutation safety. Complements existing test_scenarios.py.

Contains: TestTranslateScenario, TestSupportedFilter, TestCategoryActions,
          TestMutationSafety, TestRegistryCompleteness
"""

from fos.core.scenarios.registry import (
    ALL_SCENARIOS,
    _translate_scenario,
    get_all_scenarios,
    get_scenario,
    get_scenario_actions,
)


# ---------------------------------------------------------------------------
# _translate_scenario
# ---------------------------------------------------------------------------

class TestTranslateScenario:
    """Tests for the internal _translate_scenario function."""

    def test_returns_copy_not_reference(self) -> None:
        template = {"id": "test", "name": "Test", "parameters": [], "actions": []}
        result = _translate_scenario(template, "en")
        assert result is not template
        assert result["id"] == "test"

    def test_preserves_id_and_category(self) -> None:
        template = {
            "id": "pd", "name": "PD", "category": "game_theory",
            "parameters": [], "actions": [],
        }
        result = _translate_scenario(template, "en")
        assert result["category"] == "game_theory"

    def test_keeps_original_name_when_no_translation(self) -> None:
        """If i18n key has no translation, original name is kept."""
        template = {"id": "nonexistent_xyz", "name": "Original", "actions": []}
        result = _translate_scenario(template, "en")
        assert result["name"] == "Original"

    def test_parameters_list_preserved(self) -> None:
        template = {
            "id": "test", "parameters": [{"id": "p1", "key": "p1"}], "actions": [],
        }
        result = _translate_scenario(template, "en")
        assert len(result["parameters"]) == 1


# ---------------------------------------------------------------------------
# Supported-scenario filter
# ---------------------------------------------------------------------------

class TestSupportedFilter:
    """get_all_scenarios should skip scenarios with supported=False."""

    def test_werewolf_excluded_from_all(self) -> None:
        ids = [s["id"] for s in get_all_scenarios()]
        assert "werewolf" not in ids

    def test_werewolf_still_gettable_by_id(self) -> None:
        """get_scenario bypasses the supported filter."""
        result = get_scenario("werewolf")
        assert result is not None
        assert result["id"] == "werewolf"

    def test_werewolf_actions_returned(self) -> None:
        actions = get_scenario_actions("werewolf")
        assert len(actions) > 0


# ---------------------------------------------------------------------------
# Category actions resolution
# ---------------------------------------------------------------------------

class TestCategoryActions:

    def test_sociology_scenarios_resolve_category_actions(self) -> None:
        """Sociology scenarios with category_actions string get resolved to list."""
        for s in get_all_scenarios():
            if s.get("category") == "sociology" and "category_actions" in s:
                assert isinstance(s["category_actions"], list), (
                    f"Scenario {s['id']} has unresolved category_actions"
                )

    def test_get_scenario_actions_with_category_actions(self) -> None:
        """Scenarios using category_actions return actions from the library."""
        # social_norm_disruption uses category_actions
        actions = get_scenario_actions("social_norm_disruption")
        assert isinstance(actions, list)
        assert len(actions) > 0
        assert all("id" in a and "name" in a for a in actions)

    def test_get_scenario_actions_with_direct_actions(self) -> None:
        """Scenarios with direct actions return them correctly."""
        actions = get_scenario_actions("prisoners_dilemma")
        assert len(actions) == 2
        ids = {a["id"] for a in actions}
        assert "cooperate" in ids
        assert "defect" in ids


# ---------------------------------------------------------------------------
# Mutation safety
# ---------------------------------------------------------------------------

class TestMutationSafety:

    def test_get_scenario_returns_copy(self) -> None:
        scenario = get_scenario("prisoners_dilemma")
        assert scenario is not None
        scenario["name"] = "MUTATED"
        fresh = get_scenario("prisoners_dilemma")
        assert fresh is not None
        assert fresh["name"] != "MUTATED"

    def test_all_scenarios_twice_consistent(self) -> None:
        first = get_all_scenarios()
        second = get_all_scenarios()
        assert len(first) == len(second)
        assert {s["id"] for s in first} == {s["id"] for s in second}


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------

class TestRegistryCompleteness:

    ALL_IDS = {s["id"] for s in ALL_SCENARIOS}

    def test_known_ids_present(self) -> None:
        expected = {
            "prisoners_dilemma", "battle_of_the_sexes", "stag_hunt",
            "public_goods", "open_discussion", "council_chamber",
            "werewolf", "custom", "contagion",
        }
        assert expected.issubset(self.ALL_IDS)

    def test_each_id_lookupable(self) -> None:
        for sid in self.ALL_IDS:
            assert get_scenario(sid) is not None
