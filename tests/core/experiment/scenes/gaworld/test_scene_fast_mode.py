"""This file tests the low-fidelity GAWorld launch mode for faster FOS runs.

- _make_config builds a small GAWorld config for launch tests.
- _make_profile builds one fake GAWorld profile row.
- test_launch_subprocess_disables_heavy_gaworld_features_for_fast_mode checks
  that FOS turns off expensive optional GAWorld systems by default.
- test_launch_subprocess_uses_coarse_time_steps_for_fast_mode checks that FOS
  asks GAWorld to simulate with larger day steps to reduce total work.
- test_launch_subprocess_enables_deterministic_fast_mode_shortcuts checks that
  FOS asks GAWorld to skip the slowest optional cognition and diary work.
- test_launch_subprocess_uses_balanced_execution_profile checks that the
  middle profile keeps the run hermetic without enabling the most aggressive
  fast-mode shortcuts.
- test_launch_subprocess_uses_full_fidelity_execution_profile checks that the
  most faithful profile avoids fast-mode behavior overrides.
- test_launch_subprocess_maps_information_mode_to_runtime_overrides checks the
  beginner-friendly information control feeds GAWorld settings.
- test_launch_subprocess_maps_memory_mode_to_runtime_overrides checks the
  beginner-friendly memory control feeds GAWorld settings.
- test_launch_subprocess_explicit_city_system_modes_override_preset_defaults
  checks explicit city-system choices win over the starter preset.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fos.core.experiment.scenes.gaworld.scene as scene_module
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scenes.gaworld.profiles import GAWorldAgentProfile
from fos.core.experiment.scenes.gaworld.scene import GAWorldScene


def _make_config() -> ExperimentConfig:
    return ExperimentConfig(
        scenario_id="gaworld_scene",
        agents=[{"id": "1", "name": "Alice"}],
        actions=[],
        parameters={"seed": 7},
    )


def _make_profile() -> GAWorldAgentProfile:
    return GAWorldAgentProfile(
        id="1",
        name="Lin",
        gender="female",
        age=29,
        hukou="urban",
        residence="Hangzhou",
        occupation="designer",
        income="medium",
        education="college",
        personality_traits="kind and careful",
        daily_routine="works and exercises",
        social_network="close friends",
        values="family and growth",
        policy_sensitivity=0.8,
        platform_dependence=0.5,
        risk_preference=0.3,
        voice_propensity=0.7,
        mobility_intent=0.4,
        emotion=0.6,
        stress=0.2,
        econ_security=0.7,
        city_identity=0.9,
    )


def test_launch_subprocess_disables_heavy_gaworld_features_for_fast_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(
        scene_module,
        "export_profiles_csv",
        lambda _profiles, _path: None,
    )
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["external_rag"]["bootstrap"]["enabled"] is False
    assert overrides["news"]["enabled"] is False
    assert overrides["news"]["info_seek"]["enabled"] is False
    assert overrides["dynamic_behavior"]["enabled"] is False
    assert overrides["human_realism"]["enabled"] is False


def test_launch_subprocess_uses_coarse_time_steps_for_fast_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(
        scene_module,
        "export_profiles_csv",
        lambda _profiles, _path: None,
    )
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    assert captured["config_overrides"]["time_step_minutes"] == 120


def test_launch_subprocess_enables_deterministic_fast_mode_shortcuts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(
        scene_module,
        "export_profiles_csv",
        lambda _profiles, _path: None,
    )
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["routine_change"]["enabled"] is False
    assert overrides["spontaneity"]["enabled"] is False
    assert overrides["interests"]["enabled"] is False
    assert overrides["visualization"]["enabled"] is False
    assert overrides["vector_db_top_k"] == 1
    assert overrides["memory"]["consolidation"]["enabled"] is False
    assert overrides["memory"]["decay"]["enabled"] is False
    assert overrides["memory"]["skill_consolidation"]["enabled"] is False
    assert overrides["daily_planning"]["flexible"]["max_items"] == 4
    assert overrides["daily_planning"]["flexible"]["allow_insertions"] is False
    assert overrides["fos_fast_mode"] == {
        "deterministic_cognition": True,
        "skip_daily_summary": True,
        "skip_daily_diary": True,
    }


def test_launch_subprocess_uses_balanced_execution_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["execution_profile"] = "balanced"
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["external_rag"]["bootstrap"]["enabled"] is False
    assert overrides["news"]["enabled"] is False
    assert overrides["news"]["info_seek"]["enabled"] is False
    assert overrides["dynamic_behavior"]["enabled"] is False
    assert overrides["human_realism"]["enabled"] is False
    assert overrides["fos_fast_mode"] == {}
    assert "routine_change" not in overrides
    assert "spontaneity" not in overrides
    assert "interests" not in overrides
    assert overrides["time_step_minutes"] == 120


def test_launch_subprocess_uses_full_fidelity_execution_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["execution_profile"] = "full_fidelity"
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert "time_step_minutes" not in overrides
    assert "external_rag" not in overrides
    assert "news" not in overrides
    assert "dynamic_behavior" not in overrides
    assert "human_realism" not in overrides
    assert "fos_fast_mode" not in overrides


def test_launch_subprocess_maps_information_mode_to_runtime_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["information_mode"] = "active_flow"
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["news"]["enabled"] is True
    assert overrides["news"]["info_seek"]["enabled"] is True
    assert overrides["external_rag"]["bootstrap"]["enabled"] is True


def test_launch_subprocess_maps_memory_mode_to_runtime_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["memory_mode"] = "in_the_moment"
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["vector_db_top_k"] == 1
    assert overrides["memory"]["consolidation"]["enabled"] is False
    assert overrides["memory"]["decay"]["enabled"] is False
    assert overrides["memory"]["skill_consolidation"]["enabled"] is False
    assert overrides["fos_fast_mode"]["skip_daily_summary"] is True
    assert overrides["fos_fast_mode"]["skip_daily_diary"] is True


def test_launch_subprocess_explicit_city_system_modes_override_preset_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["execution_profile"] = "fast"
    config.parameters["information_mode"] = "active_flow"
    config.parameters["people_mode"] = "rich_human_behavior"
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile()])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["news"]["enabled"] is True
    assert overrides["news"]["info_seek"]["enabled"] is True
    assert overrides["external_rag"]["bootstrap"]["enabled"] is True
    assert overrides["interests"]["enabled"] is True
    assert overrides["dynamic_behavior"]["enabled"] is True
    assert overrides["human_realism"]["enabled"] is True
