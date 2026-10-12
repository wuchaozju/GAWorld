"""
Tests for simulation log formatting with i18n support.

Covers format_action_log and format_public_goods_log with all
formatting branches: matrix game mapping, pass-through, custom names.
"""

from fos.core.simulation.logs import format_action_log, format_public_goods_log


class TestFormatActionLog:
    """Tests for format_action_log covering matrix game and pass-through paths."""

    def test_opera_maps_to_action_1_name(self):
        """Opera action maps to action_1_name from scenario params."""
        params = {"action_1_name": "Ballet", "action_2_name": "Soccer"}
        result = format_action_log("Alice", "Opera", params)
        assert "Alice" in result
        assert "Ballet" in result

    def test_stag_maps_to_action_1_name(self):
        """Stag action maps to action_1_name from scenario params."""
        params = {"action_1_name": "Hunt", "action_2_name": "Gather"}
        result = format_action_log("Bob", "Stag", params)
        assert "Bob" in result
        assert "Hunt" in result

    def test_football_maps_to_action_2_name(self):
        """Football action maps to action_2_name from scenario params."""
        params = {"action_1_name": "Ballet", "action_2_name": "Soccer"}
        result = format_action_log("Alice", "Football", params)
        assert "Soccer" in result

    def test_hare_maps_to_action_2_name(self):
        """Hare action maps to action_2_name from scenario params."""
        params = {"action_1_name": "Hunt", "action_2_name": "Gather"}
        result = format_action_log("Bob", "Hare", params)
        assert "Gather" in result

    def test_non_matrix_action_passes_through(self):
        """Non-matrix game action uses the action name as-is."""
        result = format_action_log("Alice", "Cooperate", {})
        assert "Alice" in result
        assert "Cooperate" in result

    def test_missing_action_name_uses_default(self):
        """When scenario params lack action names, defaults are used."""
        params = {}  # No action names configured
        result = format_action_log("Eve", "Opera", params)
        assert "Eve" in result
        # get_action_config falls back to "Action 1"
        assert "Action 1" in result


class TestFormatPublicGoodsLog:
    """Tests for format_public_goods_log covering resource and action name branches."""

    def test_basic_contribution_with_tokens(self):
        """Standard contribution log with default resource name."""
        result = format_public_goods_log("Alice", 50, {"resource_name": "Tokens"})
        assert "Alice" in result
        assert "50" in result
        assert "tokens" in result.lower()

    def test_custom_action_name(self):
        """Custom action_name from scenario params is used and lowercased."""
        params = {"resource_name": "Gold", "action_name": "Donate"}
        result = format_public_goods_log("Bob", 100, params)
        assert "Bob" in result
        assert "100" in result
        assert "donate" in result.lower()

    def test_default_action_name_is_contribute(self):
        """When no action_name in params, defaults to 'Contribute'."""
        result = format_public_goods_log("Carol", 25, {"resource_name": "Tokens"})
        assert "Carol" in result
        assert "25" in result
        assert "contribute" in result.lower()

    def test_chinese_locale(self):
        """Chinese locale still includes agent name and amount."""
        result = format_public_goods_log("李四", 30, {"resource_name": "Tokens"}, language="zh")
        assert "李四" in result
        assert "30" in result
