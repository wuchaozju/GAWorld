import json


def test_frozen_inputs_are_independent_of_later_source_edits(tmp_path):
    from gaworld.research.runtime_inputs import freeze_inputs

    source = tmp_path / "agents.csv"
    source.write_text("agent_id,name\n1,A\n")
    config, evidence = freeze_inputs(
        {"csv_path": str(source), "agent_ids": [1]}, str(tmp_path), tmp_path / "attempt"
    )
    source.write_text("agent_id,name\n1,B\n")
    assert "1,A" in __import__("pathlib").Path(config["csv_path"]).read_text()
    assert evidence["csv_path"]["source"] == str(source)
    assert config["agent_ids"] == [1]


def test_research_provider_snapshot_only_enters_environment_not_manifest(tmp_path):
    from gaworld.parallel.runner import ExperimentRunner

    manifest = {
        "worlds": {"baseline": {"dir": "world", "overrides": {}}},
        "spec": {"worlds": []},
        "research": {
            "ledger": str(tmp_path / "state.sqlite"),
            "execution_mode": "tick",
            "actual_provider": "chosen",
        },
    }
    runner = ExperimentRunner(manifest, str(tmp_path))
    runner.research_provider_config = {
        "type": "openai",
        "model": "fixed-model",
        "api_key": "secret-fixture-key",
    }
    override = json.loads(runner._env("baseline")["GAWORLD_CONFIG_OVERRIDES"])
    assert override["llm"]["providers"]["chosen"]["model"] == "fixed-model"
    assert "secret-fixture-key" not in json.dumps(manifest)
