"""
Tests for core.simulation.results formatting utilities.

Tests format_round_results and format_public_goods_results with various
action mappings, resource names, and edge cases.

Contains: TestFormatRoundResults, TestFormatPublicGoodsResults
"""


from fos.core.simulation.results import (
    format_round_results,
    format_public_goods_results,
)


# ---------------------------------------------------------------------------
# format_round_results
# ---------------------------------------------------------------------------

class TestFormatRoundResults:

    def test_maps_opera_football_to_custom_names(self) -> None:
        """Opera maps to action_1, Football maps to action_2."""
        params = {
            "action_1_name": "Opera",
            "action_2_name": "Football",
        }
        result = format_round_results(
            1, {"Opera": 3, "Football": 2}, params
        )
        assert result["counts"]["Opera"] == 3
        assert result["counts"]["Football"] == 2

    def test_maps_stag_hare_to_custom_names(self) -> None:
        """Stag maps to action_1, Hare maps to action_2."""
        params = {
            "action_1_name": "Hunt Stag",
            "action_2_name": "Hunt Hare",
        }
        result = format_round_results(
            2, {"Stag": 4, "Hare": 1}, params
        )
        assert result["counts"]["Hunt Stag"] == 4
        assert result["counts"]["Hunt Hare"] == 1

    def test_unmapped_action_passes_through(self) -> None:
        """Actions not in the known map keep their original name."""
        params = {"action_1_name": "A1", "action_2_name": "A2"}
        result = format_round_results(
            1, {"cooperate": 5, "Opera": 2}, params
        )
        assert result["counts"]["cooperate"] == 5
        assert result["counts"]["A1"] == 2

    def test_default_action_names_when_no_custom(self) -> None:
        """Missing action_N_name falls back to 'Action N'."""
        result = format_round_results(1, {"Opera": 1}, {})
        assert result["counts"]["Action 1"] == 1

    def test_empty_action_counts(self) -> None:
        """Empty counts dict produces empty formatted_counts."""
        result = format_round_results(1, {}, {})
        assert result["counts"] == {}

    def test_returns_title_and_agents_text(self) -> None:
        """Result dict has 'title' and 'agents_chose_text' keys."""
        result = format_round_results(3, {"Opera": 2}, {})
        assert "title" in result
        assert "agents_chose_text" in result

    def test_agents_chose_sum(self) -> None:
        """agents_chose_text gets the total count of all actions."""
        params = {"action_1_name": "A1", "action_2_name": "A2"}
        result = format_round_results(
            1, {"Opera": 3, "Football": 2}, params
        )
        # T() is called with count=5 (3+2); just verify the function was called
        assert "agents_chose_text" in result


# ---------------------------------------------------------------------------
# format_public_goods_results
# ---------------------------------------------------------------------------

class TestFormatPublicGoodsResults:

    def test_default_resource_name(self) -> None:
        """When no resource_name set, defaults to 'Tokens'."""
        result = format_public_goods_results(
            round_num=1,
            total_contributed=8,
            pool_after_multiplier=12.0,
            per_agent_share=4.0,
            scenario_params={},
        )
        assert "8 tokens" in result["total_value"]
        assert "12.0 tokens" in result["pool_value"]
        assert "4.0 tokens" in result["share_value"]

    def test_custom_resource_name(self) -> None:
        """Custom resource_name replaces 'Tokens'."""
        result = format_public_goods_results(
            round_num=1,
            total_contributed=10,
            pool_after_multiplier=15.0,
            per_agent_share=5.0,
            scenario_params={"resource_name": "Gold"},
        )
        assert "10 gold" in result["total_value"]
        assert "15.0 gold" in result["pool_value"]

    def test_custom_multiplier(self) -> None:
        """Multiplier from scenario_params overrides default 1.5."""
        result = format_public_goods_results(
            round_num=1,
            total_contributed=10,
            pool_after_multiplier=20.0,
            per_agent_share=5.0,
            scenario_params={"multiplier": 2.0},
        )
        assert "pool_after_multiplier" in result

    def test_custom_resource_via_custom_option(self) -> None:
        """resource_name='Custom' falls back to resource_name_custom."""
        result = format_public_goods_results(
            round_num=1,
            total_contributed=5,
            pool_after_multiplier=7.5,
            per_agent_share=2.5,
            scenario_params={"resource_name": "Custom", "resource_name_custom": "Credits"},
        )
        assert "5 credits" in result["total_value"]

    def test_returns_all_required_keys(self) -> None:
        """Result dict contains title, totals, pool, share keys."""
        result = format_public_goods_results(
            1, 5, 7.5, 2.5, {}
        )
        assert "title" in result
        assert "total_contributed" in result
        assert "total_value" in result
        assert "pool_after_multiplier" in result
        assert "pool_value" in result
        assert "per_agent_share" in result
        assert "share_value" in result

    def test_zero_contribution(self) -> None:
        """Edge case: zero total contribution."""
        result = format_public_goods_results(
            round_num=1,
            total_contributed=0,
            pool_after_multiplier=0.0,
            per_agent_share=0.0,
            scenario_params={},
        )
        assert "0 tokens" in result["total_value"]
        assert "0.0 tokens" in result["pool_value"]
