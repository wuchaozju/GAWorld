"""
Tests for PolicyCascadeDistortionMixin — policy text distortion per tier.

Distortion alters policy as it cascades through organisational tiers.
Wrong output means corrupted research that looks plausible.

Tests cover: block tendency, policy signal profiles, line parsing,
softening, rewriting, priority/filtering, and the main distort function.

Contains: Groups A–H (29 tests)
"""

from unittest.mock import MagicMock


from fos.core.scenes.policy_cascade.distortion import PolicyCascadeDistortionMixin
from fos.core.scenes.policy_cascade.base import PolicyCascadeBaseMixin
from fos.core.scenes.policy_cascade.messages import PolicyCascadeMessageMixin
from fos.core.scenes.policy_cascade.state import PolicyCascadeStateMixin


# ---------------------------------------------------------------------------
# Test harness — combines mixins with minimal state, skips heavy init
# ---------------------------------------------------------------------------


class _Harness(
    PolicyCascadeDistortionMixin,
    PolicyCascadeStateMixin,
    PolicyCascadeMessageMixin,
    PolicyCascadeBaseMixin,
):
    """Lightweight test harness combining all distortion-relevant mixins."""

    def __init__(self, **kw):
        object.__init__(self)
        self.tier_order = kw.get("tier_order", ["high", "mid", "low"])
        self.state = {
            "tier_order": list(self.tier_order),
            "distortion_strength": kw.get("distortion_strength", 0.6),
            "conflict_sensitivity": kw.get("conflict_sensitivity", 0.5),
            "block_probability": kw.get("block_probability", 0.25),
            "source_policy": kw.get("source_policy", ""),
            "relayed_policy": kw.get("relayed_policy", ""),
            "latest_notice": kw.get("latest_notice", ""),
            "latest_policy": kw.get("source_policy", ""),
            "cascade_mode": kw.get("cascade_mode", "distortion_cascade"),
            "persistent_conditions": kw.get("persistent_conditions", {}),
        }
        self._tier_map = {}
        self._agents_by_tier = {t: [] for t in self.tier_order}


def _agent(name="Worker", role_prompt="", properties=None):
    """Create a mock agent with the attributes distortion methods expect."""
    a = MagicMock()
    a.name = name
    a.role_prompt = role_prompt
    a.user_profile = ""
    a.properties = properties or {}
    return a


# ===================================================================
# Group A: Distortion score calculation (5 tests)
# ===================================================================


class TestDistortionScore:
    """Tests for _conflict_pressure and _block_tendency scaling by tier."""

    def test_conflict_pressure_lowest_for_top_tier(self):
        """Top tier has the lowest conflict pressure of all tiers."""
        h = _Harness(source_policy="执行要求：必须完成 责任分工：考核问责")
        agent = _agent("Director")
        top = h._conflict_pressure(agent, "high")
        mid = h._conflict_pressure(agent, "mid")
        low = h._conflict_pressure(agent, "low")
        assert top < mid < low

    def test_conflict_pressure_increases_with_lower_tier(self):
        """Mid tier pressure is strictly less than low tier."""
        h = _Harness(source_policy="执行要求：排查整改")
        agent = _agent("Agent")
        mid = h._conflict_pressure(agent, "mid")
        low = h._conflict_pressure(agent, "low")
        assert mid < low

    def test_block_tendency_scales_with_distortion_strength(self):
        """Higher distortion_strength produces higher block tendency."""
        agent = _agent("Worker", "基层 执行 负担")
        h_low = _Harness(
            distortion_strength=0.2,
            source_policy="执行要求：必须完成",
        )
        h_high = _Harness(
            distortion_strength=0.9,
            source_policy="执行要求：必须完成",
        )
        low_tendency = h_low._block_tendency(agent, "low")
        high_tendency = h_high._block_tendency(agent, "low")
        assert high_tendency > low_tendency

    def test_block_tendency_bounded_between_zero_and_one(self):
        """Block tendency is always in [0, 1] regardless of inputs."""
        h = _Harness(
            distortion_strength=1.0,
            conflict_sensitivity=1.0,
            block_probability=1.0,
            source_policy="执行 考核 问责 报送 资源",
        )
        agent = _agent("Worker", "负担 压力 基层 执行难")
        for tier in ["high", "mid", "low"]:
            val = h._block_tendency(agent, tier)
            assert 0.0 <= val <= 1.0

    def test_block_tendency_deterministic_for_same_inputs(self):
        """Same agent, tier, and state always produces the same tendency."""
        h = _Harness(source_policy="执行要求：排查")
        agent = _agent("Worker")
        result1 = h._block_tendency(agent, "low")
        result2 = h._block_tendency(agent, "low")
        assert result1 == result2


# ===================================================================
# Group B: Policy signal profile (4 tests)
# ===================================================================


class TestPolicySignalProfile:
    """Tests for _policy_signal_profile extraction from policy text."""

    def test_profile_returns_dict_with_expected_keys(self):
        """Profile dict contains all marker categories plus computed keys."""
        h = _Harness()
        profile = h._policy_signal_profile()
        for key in [
            "goal", "scope", "standard", "support",
            "execution", "report", "resource", "accountability",
            "invariant", "burden", "resource_gap",
        ]:
            assert key in profile, f"Missing key: {key}"

    def test_profile_extracts_from_source_policy(self):
        """Policy containing execution keywords produces non-zero execution score."""
        h = _Harness(source_policy="执行要求：必须立即完成排查整改")
        profile = h._policy_signal_profile()
        assert profile["execution"] > 0.0

    def test_profile_values_between_zero_and_one(self):
        """All profile values are clamped to [0, 1]."""
        h = _Harness(
            source_policy="执行 考核 问责 报送 资源 目标 范围 标准 配套 严禁",
        )
        profile = h._policy_signal_profile()
        for key, value in profile.items():
            assert 0.0 <= value <= 1.0, f"{key}={value} out of range"

    def test_profile_modifies_by_condition(self):
        """Conditions like resource_shortage boost burden and resource_gap."""
        h_base = _Harness(source_policy="执行要求：完成排查")
        h_boosted = _Harness(
            source_policy="执行要求：完成排查",
            persistent_conditions={"resource_shortage": 0.8},
        )
        base = h_base._policy_signal_profile()
        boosted = h_boosted._policy_signal_profile()
        assert boosted["burden"] > base["burden"]
        assert boosted["resource_gap"] > base["resource_gap"]


# ===================================================================
# Group C: Block tendency (3 tests)
# ===================================================================


class TestBlockTendency:
    """Tests for _block_tendency tier and strength behaviour."""

    def test_higher_for_low_tier_than_high(self):
        """Low-tier agent has higher block tendency than high-tier."""
        h = _Harness(
            distortion_strength=0.7,
            source_policy="执行要求：立即完成 责任分工：考核问责",
        )
        agent = _agent("Agent")
        high_t = h._block_tendency(agent, "high")
        low_t = h._block_tendency(agent, "low")
        assert low_t > high_t

    def test_increases_with_distortion_strength(self):
        """Block tendency grows as distortion_strength increases."""
        agent = _agent("Worker")
        results = []
        for strength in [0.1, 0.5, 0.9]:
            h = _Harness(
                distortion_strength=strength,
                source_policy="执行要求：整改",
            )
            results.append(h._block_tendency(agent, "low"))
        assert results[0] < results[1] < results[2]

    def test_includes_deterministic_seed(self):
        """Same agent+state always yields the same block tendency."""
        h = _Harness(source_policy="执行要求：整改")
        agent = _agent("Worker")
        # Call multiple times to verify no randomness
        values = [h._block_tendency(agent, "mid") for _ in range(5)]
        assert len(set(values)) == 1


# ===================================================================
# Group D: Policy line parsing (4 tests)
# ===================================================================


class TestPolicyLineParsing:
    """Tests for _split_policy_line and _line_kind."""

    def test_split_on_colon(self):
        """English colon splits header from body."""
        h = _Harness()
        header, body = h._split_policy_line("Goal: Reduce emissions")
        assert header == "Goal"
        assert body == "Reduce emissions"

    def test_split_on_chinese_colon(self):
        """Chinese full-width colon also splits header from body."""
        h = _Harness()
        header, body = h._split_policy_line("目标：减排")
        assert header == "目标"
        assert body == "减排"

    def test_split_no_colin_returns_empty_header(self):
        """Line with no colon returns empty header and full line as body."""
        h = _Harness()
        header, body = h._split_policy_line("No colon here")
        assert header == ""
        assert body == "No colon here"

    def test_line_kind_classifies_by_header_markers(self):
        """Lines whose header matches POLICY_LINE_MARKERS get the right kind."""
        h = _Harness()
        assert h._line_kind("执行要求：完成排查") == "execution"
        assert h._line_kind("报告要求：报送台账") == "report"
        assert h._line_kind("政策目标：提高效率") == "goal"
        assert h._line_kind("责任分工：考核问责") == "accountability"


# ===================================================================
# Group E: Policy softening (3 tests)
# ===================================================================


class TestPolicySoftening:
    """Tests for _soften_body at different strength thresholds."""

    def test_replaces_mandatory_words_at_moderate_strength(self):
        """At strength >= 0.35, 必须 is replaced with 优先."""
        h = _Harness()
        result = h._soften_body("必须立即完成", 0.5)
        assert "必须" not in result
        assert "优先" in result

    def test_replaces_time_expressions_at_high_strength(self):
        """At strength >= 0.65, time expressions like 当天 are replaced."""
        h = _Harness()
        result = h._soften_body("当天内完成整改", 0.7)
        assert "当天" not in result
        assert "条件具备后再统一推进" in result

    def test_returns_original_at_low_strength(self):
        """At strength < 0.35, the body is returned unchanged."""
        h = _Harness()
        original = "必须立即完成全部整改"
        result = h._soften_body(original, 0.2)
        assert result == original


# ===================================================================
# Group F: Line rewriting by kind and tier (4 tests)
# ===================================================================


class TestLineRewriting:
    """Tests for _rewrite_line_for_distortion at different kinds/tiers."""

    def test_title_line_unchanged(self):
        """Title lines are never rewritten."""
        h = _Harness()
        line = "关于调整薪酬标准的通知"
        result = h._rewrite_line_for_distortion("title", "low", line, 0.8, 0.5)
        assert result == line

    def test_meta_line_unchanged(self):
        """Meta lines (like 原文：) are never rewritten."""
        h = _Harness()
        line = "原文："
        result = h._rewrite_line_for_distortion("meta", "low", line, 0.8, 0.5)
        assert result == line

    def test_goal_line_prefixed_at_moderate_strength(self):
        """Goal lines at moderate strength (0.35–0.55) get a policy-goal prefix."""
        h = _Harness()
        result = h._rewrite_line_for_distortion(
            "goal", "mid", "政策目标：提高效率", 0.45, 0.3,
        )
        assert "政策目标" in result

    def test_execution_line_simplified_at_high_strength(self):
        """Execution lines at high strength (>0.55) for low tier get simplified."""
        h = _Harness()
        result = h._rewrite_line_for_distortion(
            "execution", "low", "执行要求：完成排查整改", 0.8, 0.6,
        )
        # Low tier at high strength should mention "基层" or "最小动作"
        assert "基层" in result or "最小动作" in result


# ===================================================================
# Group G: Line priority and filtering (3 tests)
# ===================================================================


class TestLinePriority:
    """Tests for _line_priority and _must_keep_line."""

    def test_line_priority_varies_by_tier(self):
        """Goal priority is higher for top tier than for low tier."""
        h = _Harness()
        top_goal = h._line_priority("goal", "high")
        low_goal = h._line_priority("goal", "low")
        assert top_goal < low_goal  # lower index = higher priority

    def test_must_keep_true_for_title_and_meta(self):
        """Title and meta lines are always kept."""
        h = _Harness()
        assert h._must_keep_line("title", "any", 0.8, "low") is True
        assert h._must_keep_line("meta", "any", 0.8, "low") is True

    def test_must_keep_varies_by_strength(self):
        """At low strength, most lines are kept; at high strength, fewer."""
        h = _Harness()
        # Low strength: goal is kept
        assert h._must_keep_line("goal", "x", 0.3, "mid") is True
        # High strength: goal may not be kept for mid tier
        high_strength_keep = h._must_keep_line("goal", "x", 0.8, "mid")
        # At high strength for mid tier, goal is NOT in {"standard", "execution", "report"}
        assert high_strength_keep is False


# ===================================================================
# Group H: Main distortion function (3 tests)
# ===================================================================


class TestDistortMessage:
    """Tests for _distort_message end-to-end."""

    def test_returns_original_at_zero_strength(self):
        """With strength=0, the message is returned unchanged."""
        h = _Harness(distortion_strength=0.0, source_policy="执行要求：完成")
        agent = _agent("Worker")
        msg = "执行要求：完成排查"
        result = h._distort_message(agent, "low", msg)
        assert result == msg

    def test_returns_original_for_empty_message(self):
        """Empty or whitespace-only message returns empty string."""
        h = _Harness(distortion_strength=0.8, source_policy="执行要求：完成")
        agent = _agent("Worker")
        assert h._distort_message(agent, "low", "") == ""
        assert h._distort_message(agent, "low", "   ") == ""

    def test_adds_prefix_and_constraint_label(self):
        """Distorted message includes a tier-appropriate prefix."""
        h = _Harness(
            distortion_strength=0.7,
            source_policy="执行要求：完成排查\n报告要求：报送台账",
        )
        agent = _agent("Worker")
        result = h._distort_message(agent, "low", "执行要求：完成排查")
        # Should contain more than just the original message
        assert len(result) > len("执行要求：完成排查")
