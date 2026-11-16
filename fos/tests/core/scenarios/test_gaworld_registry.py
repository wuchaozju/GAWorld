"""This file checks the public GAWorld scenario parameter contract.

- test_gaworld_scenario_exposes_execution_profile_parameter checks the
  scenario schema includes a user-facing execution profile control.
- test_gaworld_scenario_exposes_beginner_city_system_parameters checks the
  beginner-friendly city system controls are public.
- test_gaworld_scenario_hides_legacy_runtime_and_intervention_parameters checks
  setup-only plumbing and unfinished intervention fields stay hidden.
"""

from __future__ import annotations

from fos.core.scenarios.registry import get_scenario


def test_gaworld_scenario_exposes_execution_profile_parameter() -> None:
    scenario = get_scenario("gaworld")

    assert scenario is not None
    parameters = {item["key"]: item for item in scenario["parameters"]}
    assert "execution_profile" in parameters
    assert parameters["execution_profile"]["type"] == "string"
    assert parameters["execution_profile"]["ui_hint"] == "select"
    assert parameters["execution_profile"]["default"] == "fast"
    assert parameters["execution_profile"]["options"] == [
        "fast",
        "balanced",
        "full_fidelity",
    ]


def test_gaworld_scenario_exposes_beginner_city_system_parameters() -> None:
    scenario = get_scenario("gaworld")

    assert scenario is not None
    parameters = {item["key"]: item for item in scenario["parameters"]}

    assert parameters["information_mode"]["default"] == "city_news"
    assert parameters["information_mode"]["options"] == [
        "off",
        "city_news",
        "active_flow",
    ]
    assert parameters["daily_life_mode"]["default"] == "some_variation"
    assert parameters["daily_life_mode"]["options"] == [
        "stable_routines",
        "some_variation",
        "flexible_daily_life",
    ]
    assert parameters["people_mode"]["default"] == "adaptive_behavior"
    assert parameters["people_mode"]["options"] == [
        "simple_behavior",
        "adaptive_behavior",
        "rich_human_behavior",
    ]
    assert parameters["memory_mode"]["default"] == "some_continuity"
    assert parameters["memory_mode"]["options"] == [
        "in_the_moment",
        "some_continuity",
        "rich_memory",
    ]
    assert parameters["seed"]["type"] == "integer"


def test_gaworld_scenario_hides_legacy_runtime_and_intervention_parameters() -> None:
    scenario = get_scenario("gaworld")

    assert scenario is not None
    parameter_keys = {item["key"] for item in scenario["parameters"]}

    assert "sim_days" not in parameter_keys
    assert "agent_ids" not in parameter_keys
    assert "intervention_enabled" not in parameter_keys
    assert "intervention_event_name" not in parameter_keys
    assert "intervention_event_description" not in parameter_keys
    assert "intervention_day" not in parameter_keys
