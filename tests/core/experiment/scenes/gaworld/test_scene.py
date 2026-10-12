"""This file tests the GAWorld scene orchestration behavior.

- test_type_identifier_matches_expected_value checks the scene type value.
- test_constructor_starts_with_empty_skipped_days checks skipped days starts empty.
- test_initialize_sets_translator_without_starting_subprocess checks initialize avoids starting GAWorld.
- test_initialize_populates_display_agents_and_name_map checks real GAWorld profiles feed the UI and output mapping.
- test_read_day_data_uses_config_agent_ids checks GAWorld output reads selected profile agent files.
- test_read_day_data_scans_memory_when_name_map_is_empty checks output loading still works without config IDs.
- test_run_round_launches_subprocess_on_first_round checks first run_round lazily starts GAWorld.
- test_run_round_launches_gaworld_for_one_day checks the first advance only asks GAWorld for day one.
- test_run_round_launches_gaworld_through_target_day checks later advances only ask GAWorld for the target day.
- test_run_round_stops_subprocess_after_reading_day checks each advance stops GAWorld after hydration.
- test_run_round_emits_one_event_per_translated_event checks run_round emits translated events.
- test_run_round_logs_gaworld_diagnostics checks run_round logs the GAWorld handoff path.
- test_run_round_skips_day_when_translation_key_missing checks key errors skip a day without crashing.
- test_launch_subprocess_passes_gaworld_output_paths checks GAWorld writes under the FOS output folder.
- test_launch_subprocess_passes_profiles_as_gaworld_csv_path checks GAWorld reads FOS profiles.
- test_launch_subprocess_omits_empty_agent_ids_override checks blank agent selection keeps GAWorld defaults.
- test_launch_subprocess_omits_empty_profiles_csv_override checks GAWorld default data is kept when no profiles exist.
- test_launch_subprocess_uses_fos_ollama_provider_config checks GAWorld routes through FOS Ollama.
- test_launch_subprocess_uses_ollama_environment_config checks GAWorld reads Ollama env config.
- test_launch_subprocess_does_not_inject_provider_api_key checks FOS keys stay out of GAWorld.
- test_launch_subprocess_injects_dedicated_gaworld_api_key checks GAWorld's own key is passed through.
- test_launch_subprocess_warns_when_no_gaworld_llm_key_exists checks missing GAWorld keys are reported.
- test_serialize_config_includes_skipped_days checks skipped days are returned in config serialization.
- test_gaworld_scene_is_not_complete_without_a_setup_day_cap checks GAWorld no
  longer stops because of a removed setup duration parameter.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import fos.core.experiment.scenes.gaworld.scene as scene_module
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scenes.gaworld.profiles import GAWorldAgentProfile
from fos.core.experiment.scenes.gaworld.scene import GAWorldScene


def _make_config() -> ExperimentConfig:
    return ExperimentConfig(
        scenario_id="gaworld_scene",
        agents=[
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ],
        actions=[],
        parameters={"seed": 7},
    )


def _make_profile(profile_id: str = "1") -> GAWorldAgentProfile:
    return GAWorldAgentProfile(
        id=profile_id,
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


def test_type_identifier_matches_expected_value() -> None:
    assert GAWorldScene.TYPE == "gaworld_scene"


def test_constructor_starts_with_empty_skipped_days() -> None:
    scene = GAWorldScene(_make_config())
    assert scene.skipped_days == []


def test_gaworld_scene_is_not_complete_without_a_setup_day_cap() -> None:
    scene = GAWorldScene(_make_config())
    scene.current_round = 100

    assert scene.is_complete() is False


def test_initialize_sets_translator_without_starting_subprocess(monkeypatch) -> None:
    scene = GAWorldScene(_make_config())
    launch_calls: list[str] = []

    def _fake_launch() -> None:
        launch_calls.append("called")
        scene._subprocess_manager = SimpleNamespace(wait_for_day=lambda *args, **kwargs: {"last_day": 1})

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)

    scene.initialize(llm_client=object())

    assert launch_calls == []
    assert scene._subprocess_manager is None
    assert scene._translator is not None


def test_initialize_populates_display_agents_and_name_map(monkeypatch) -> None:
    config = _make_config()
    scene = GAWorldScene(config)
    monkeypatch.setattr(scene_module, "write_scenario_header", lambda **_kwargs: None, raising=False)

    scene.initialize(llm_client=object())

    assert [agent.name for agent in scene.agents] == ["Alice", "Bob"]
    assert scene._agent_name_map == {1: "Alice", 2: "Bob"}


def test_read_day_data_uses_config_agent_ids(tmp_path: Path) -> None:
    scene = GAWorldScene(_make_config())
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "agent_1_actions.json").write_text('[{"type": "work", "hours": 8}]', encoding="utf-8")
    (memory_dir / "agent_1.json").write_text('{"emotion": 0.8}', encoding="utf-8")
    (memory_dir / "agent_99_actions.json").write_text('[{"type": "rest", "hours": 2}]', encoding="utf-8")
    scene._subprocess_manager = SimpleNamespace(output_dir=tmp_path)
    scene._agent_name_map = {1: "Alice"}

    day_data = scene._read_day_data(1)

    assert day_data["agents"] == [
        {
            "id": 1,
            "actions": [{"type": "work", "hours": 8}],
            "state": {"emotion": 0.8},
            "emotion": 0.8,
        }
    ]


def test_read_day_data_scans_memory_when_name_map_is_empty(tmp_path: Path) -> None:
    scene = GAWorldScene(_make_config())
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "agent_34_actions.json").write_text('[{"type": "move"}]', encoding="utf-8")
    scene._subprocess_manager = SimpleNamespace(output_dir=tmp_path)
    scene._agent_name_map = {}

    day_data = scene._read_day_data(1)

    assert day_data["agents"][0]["id"] == 34


def test_run_round_launches_subprocess_on_first_round(monkeypatch) -> None:
    scene = GAWorldScene(_make_config())
    launch_calls: list[str] = []

    def _fake_launch(target_day: int) -> None:
        launch_calls.append(f"day-{target_day}")
        scene._subprocess_manager = SimpleNamespace(
            wait_for_day=lambda *args, **kwargs: {"last_day": 1},
            output_dir=Path("."),
            kill=lambda: None,
        )

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})

    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [],
        translate_state_updates=lambda _day_data: {},
    )

    asyncio.run(scene.run_round(lambda _event_type, _payload: None))

    assert launch_calls == ["day-1"]


def test_run_round_launches_gaworld_for_one_day(tmp_path: Path, monkeypatch) -> None:
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

        def wait_for_day(self, day: int, **_kwargs: Any) -> dict[str, Any]:
            return {"last_day": day}

        def kill(self) -> None:
            captured["killed"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})
    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [],
        translate_state_updates=lambda _day_data: {},
    )

    asyncio.run(scene.run_round(lambda _event_type, _payload: None))

    assert captured["config_overrides"]["sim_days"] == 1


def test_run_round_launches_gaworld_through_target_day(tmp_path: Path, monkeypatch) -> None:
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

        def wait_for_day(self, day: int, **_kwargs: Any) -> dict[str, Any]:
            return {"last_day": day}

        def kill(self) -> None:
            captured["killed"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene.current_round = 4
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})
    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [],
        translate_state_updates=lambda _day_data: {},
    )

    asyncio.run(scene.run_round(lambda _event_type, _payload: None))

    assert captured["config_overrides"]["sim_days"] == 5


def test_run_round_stops_subprocess_after_reading_day(monkeypatch) -> None:
    scene = GAWorldScene(_make_config())
    calls: list[str] = []

    class FakeManager:
        output_dir = Path(".")

        def wait_for_day(self, day: int, **_kwargs: Any) -> dict[str, Any]:
            calls.append(f"wait-{day}")
            return {"last_day": day}

        def kill(self) -> None:
            calls.append("kill")

    def _fake_launch(_target_day: int) -> None:
        scene._subprocess_manager = FakeManager()

    def _fake_read(day_num: int) -> dict[str, Any]:
        calls.append(f"read-{day_num}")
        return {"day": day_num, "agents": []}

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)
    monkeypatch.setattr(scene, "_read_day_data", _fake_read)

    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [],
        translate_state_updates=lambda _day_data: {},
    )

    asyncio.run(scene.run_round(lambda _event_type, _payload: None))

    assert calls == ["wait-1", "read-1", "kill"]
    assert scene._subprocess_manager is None


def test_run_round_emits_one_event_per_translated_event(monkeypatch) -> None:
    scene = GAWorldScene(_make_config())

    def _fake_launch(_target_day: int) -> None:
        scene._subprocess_manager = SimpleNamespace(
            wait_for_day=lambda *args, **kwargs: {"last_day": 1},
            output_dir=Path("."),
            kill=lambda: None,
        )

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})

    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [{"agent": "Alice", "action": "work"}],
        translate_state_updates=lambda _day_data: {},
    )

    emitted: list[tuple[str, dict[str, Any]]] = []

    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    asyncio.run(scene.run_round(_emit))

    assert len(emitted) == 1
    assert emitted[0][0] == "experiment_action"


def test_run_round_uses_extended_gaworld_timeout(monkeypatch) -> None:
    scene = GAWorldScene(_make_config())
    captured: dict[str, Any] = {}

    def _fake_launch(_target_day: int) -> None:
        def _wait_for_day(day: int, timeout: float = 0, **_kwargs: Any) -> dict[str, Any]:
            captured["day"] = day
            captured["timeout"] = timeout
            return {"last_day": day}

        scene._subprocess_manager = SimpleNamespace(
            wait_for_day=_wait_for_day,
            output_dir=Path("."),
            kill=lambda: None,
        )

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})

    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [],
        translate_state_updates=lambda _day_data: {},
    )

    asyncio.run(scene.run_round(lambda _event_type, _payload: None))

    assert captured == {"day": 1, "timeout": 1800}


def test_run_round_logs_gaworld_diagnostics(monkeypatch, caplog) -> None:
    scene = GAWorldScene(_make_config())
    caplog.set_level("INFO", logger=scene_module.__name__)

    def _fake_launch(_target_day: int) -> None:
        scene._subprocess_manager = SimpleNamespace(
            wait_for_day=lambda *args, **kwargs: {"last_day": 1},
            output_dir=Path("."),
            kill=lambda: None,
        )

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})

    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: [{"agent": "Alice", "action": "work"}],
        translate_state_updates=lambda _day_data: {},
    )

    asyncio.run(scene.run_round(lambda _event_type, _payload: None))

    assert "GAWorld day 1 sim_state: {'last_day': 1}" in caplog.messages
    assert "GAWorld day 1 agents_data: {'day': 1, 'agents': []}" in caplog.messages
    assert "GAWorld day 1 translated 1 events" in caplog.messages
    assert "GAWorld emitted event: Alice work" in caplog.messages
    assert any("GAWorld diagnostic snapshot file:" in message for message in caplog.messages)


def test_run_round_skips_day_when_translation_key_missing(monkeypatch) -> None:
    scene = GAWorldScene(_make_config())

    def _fake_launch(_target_day: int) -> None:
        scene._subprocess_manager = SimpleNamespace(
            wait_for_day=lambda *args, **kwargs: {"last_day": 1},
            output_dir=Path("."),
            kill=lambda: None,
        )

    monkeypatch.setattr(scene, "_launch_subprocess", _fake_launch)
    monkeypatch.setattr(scene, "_read_day_data", lambda day_num: {"day": day_num, "agents": []})

    scene.initialize(llm_client=object())
    scene._translator = SimpleNamespace(
        translate_day=lambda _day_data: (_ for _ in ()).throw(KeyError("missing")),
        translate_state_updates=lambda _day_data: {},
    )

    emitted: list[tuple[str, dict[str, Any]]] = []

    asyncio.run(scene.run_round(lambda event_type, payload: emitted.append((event_type, payload))))

    assert scene.skipped_days == [1]
    assert emitted == []


def test_launch_subprocess_passes_gaworld_output_paths(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "gaworld-output"
    config = _make_config()
    config.parameters["output_dir"] = output_dir
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile("1")])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["memory_dir"] == str(output_dir / "memory")
    assert overrides["log_dir"] == str(output_dir / "logs")
    assert overrides["diary_output_dir"] == str(output_dir / "diaries")
    assert overrides["environment_output_dir"] == str(output_dir / "environment")
    assert overrides["state_output_dir"] == str(output_dir / "state")
    assert overrides["network_output_dir"] == str(output_dir / "network")
    assert overrides["vector_db_path"] == str(output_dir / "memory" / "vector_db.sqlite")
    assert overrides["visualization"]["output_dir"] == str(output_dir / "visualization")
    assert overrides["intervention"]["output_dir"] == str(output_dir / "intervention")
    assert captured["output_dir"] == output_dir
    assert captured["launched"] is True


def test_launch_subprocess_passes_profiles_as_gaworld_csv_path(tmp_path: Path, monkeypatch) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}
    exported_paths: list[Path] = []

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    def fake_export_profiles_csv(_profiles: list[Any], path: Path) -> None:
        exported_paths.append(path)

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile("1")])
    monkeypatch.setattr(scene_module, "export_profiles_csv", fake_export_profiles_csv)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert len(exported_paths) == 1
    assert overrides["csv_path"] == str(exported_paths[0])
    assert "profiles_csv" not in overrides


def test_launch_subprocess_uses_config_agent_ids_when_text_field_is_blank(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.parameters["agent_ids"] = ""
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    assert captured["config_overrides"]["agent_ids"] == ["1", "2"]


def test_launch_subprocess_uses_explicit_agent_ids_when_text_field_is_blank(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    config.agents = [
        {"id": "34", "name": "Xu Guilan"},
        {"id": "35", "name": "Cai Derong"},
    ]
    config.parameters["agent_ids"] = ""
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}
    exported_profiles: list[list[str]] = []

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    def fake_export_profiles_csv(profiles: list[Any], _path: Path) -> None:
        exported_profiles.append([profile.id for profile in profiles])

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile("34"), _make_profile("35"), _make_profile("99")])
    monkeypatch.setattr(scene_module, "export_profiles_csv", fake_export_profiles_csv)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene.initialize(llm_client=object())
    scene._launch_subprocess(1)

    assert captured["config_overrides"]["agent_ids"] == ["34", "35"]
    assert exported_profiles == [["34", "35"]]


def test_launch_subprocess_disables_local_environment_and_distributed_services(
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

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile("1")])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["environment_config_path"] == ""
    assert overrides["external_environment_service"]["enabled"] is False
    assert overrides["distributed"]["enabled"] is False


def test_launch_subprocess_disables_optional_gaworld_extensions_and_real_work(
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

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile("1")])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    overrides = captured["config_overrides"]
    assert overrides["real_work"]["enabled"] is False
    assert overrides["extensions"]["strict"] is False
    assert overrides["extensions"]["hooks"] == {
        "on_simulation_start": [],
        "on_day_start": [],
        "on_time_tick": [],
        "on_agent_pre_step": [],
        "on_agent_post_step": [],
        "on_day_end": [],
        "on_simulation_end": [],
    }


def test_launch_subprocess_routes_real_work_paths_under_fos_output_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _make_config()
    output_dir = tmp_path / "gaworld-output"
    config.parameters["output_dir"] = output_dir
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    config.parameters["enable_gaworld_real_work"] = True
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [_make_profile("1")])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    real_work = captured["config_overrides"]["real_work"]
    assert real_work["enabled"] is True
    assert real_work["queue_path"] == str(output_dir / "work" / "queue.jsonl")
    assert real_work["artifacts_dir"] == str(output_dir / "work")
    assert real_work["capabilities_cache"] == str(output_dir / "work" / "capabilities.json")
    assert real_work["market"]["store_path"] == str(output_dir / "work" / "market.jsonl")


def test_launch_subprocess_omits_empty_profiles_csv_override(tmp_path: Path, monkeypatch) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}
    exported_paths: list[Path] = []

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    def fake_export_profiles_csv(_profiles: list[Any], path: Path) -> None:
        exported_paths.append(path)

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", fake_export_profiles_csv)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    assert exported_paths == []
    assert "csv_path" not in captured["config_overrides"]


def test_launch_subprocess_uses_fos_ollama_provider_config(tmp_path: Path, monkeypatch) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}
    provider_client = SimpleNamespace(
        provider=SimpleNamespace(
            dialect="ollama",
            base_url="http://localhost:11434",
            model="qwen3:4b-instruct-2507-q4_K_M",
        )
    )

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene.initialize(llm_client=object(), provider_clients={1: provider_client})
    scene._launch_subprocess(1)

    llm = captured["config_overrides"]["llm"]
    assert llm["providers"]["fos_provider"]["type"] == "ollama"
    assert llm["providers"]["fos_provider"]["url"] == "http://localhost:11434/api/generate"
    assert llm["providers"]["fos_provider"]["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert llm["routing"]["default"] == "fos_provider"
    assert llm["routing"]["tasks"]["schedule"] == "fos_provider"


def test_launch_subprocess_uses_ollama_environment_config(tmp_path: Path, monkeypatch) -> None:
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

    monkeypatch.setenv("LLM_DIALECT", "ollama")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/")
    monkeypatch.setenv("LLM_MODEL", "gemma3:12b")
    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene.initialize(llm_client=object())
    scene._launch_subprocess(1)

    llm = captured["config_overrides"]["llm"]
    assert llm["providers"]["fos_provider"]["url"] == "http://127.0.0.1:11434/api/generate"
    assert llm["providers"]["fos_provider"]["model"] == "gemma3:12b"


def test_launch_subprocess_does_not_inject_provider_api_key(tmp_path: Path, monkeypatch) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}
    provider_client = SimpleNamespace(
        provider=SimpleNamespace(api_key="stored-key", model="claude-3-5-sonnet")
    )

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            captured["launched"] = True

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GAWORLD_LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_DIALECT", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene.initialize(llm_client=object(), provider_clients={1: provider_client})
    scene._launch_subprocess(1)

    assert captured["env_overrides"] == {}


def test_launch_subprocess_ignores_gaworld_api_key_and_uses_default_fos_ollama(
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

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("LLM_DIALECT", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("GAWORLD_LLM_API_KEY", "gaworld-key")
    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    llm = captured["config_overrides"]["llm"]
    assert llm["providers"]["fos_provider"]["type"] == "ollama"
    assert llm["providers"]["fos_provider"]["url"] == "http://127.0.0.1:11434/api/generate"
    assert llm["providers"]["fos_provider"]["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert captured["env_overrides"] == {}
    assert set(captured["env_removals"]) >= {
        "GAWORLD_LLM_API_KEY",
        "MINIMAX_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    }


def test_launch_subprocess_defaults_to_fos_ollama_without_warning(tmp_path: Path, monkeypatch, caplog) -> None:
    config = _make_config()
    config.parameters["output_dir"] = tmp_path / "gaworld-output"
    config.parameters["gaworld_path"] = tmp_path / "GAWorld"
    captured: dict[str, Any] = {}

    class FakeManager:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.output_dir = kwargs["output_dir"]

        def launch(self) -> None:
            return None

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GAWORLD_LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_DIALECT", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(scene_module, "load_profiles", lambda: [])
    monkeypatch.setattr(scene_module, "export_profiles_csv", lambda _profiles, _path: None)
    monkeypatch.setattr(scene_module, "GAWorldSubprocessManager", FakeManager)

    scene = GAWorldScene(config)
    scene._launch_subprocess(1)

    llm = captured["config_overrides"]["llm"]
    assert llm["routing"]["default"] == "fos_provider"
    assert "gaworld.warning.no_llm_key" not in caplog.messages


def test_serialize_config_includes_skipped_days() -> None:
    scene = GAWorldScene(_make_config())
    scene.skipped_days.extend([1, 2])

    data = scene.serialize_config()

    assert "skipped_days" in data
    assert data["skipped_days"] == [1, 2]
