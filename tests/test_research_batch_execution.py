import threading
import time

from gaworld.apps import research_api
from gaworld.apps import research_batches_api as api
from gaworld.core.comparability import CURRENT_EPOCH
from gaworld.research import batches, study
from tests.test_research_batch_api import create
from tests.test_research_batch_api import env as batch_env

env = batch_env


def await_finished(batch_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body, status = api.handle_get("/api/research/batches/" + batch_id)
        assert status == 200, body
        if body["status"] not in {"running", "paused", "stopping"}:
            return body
        time.sleep(0.01)
    raise AssertionError("batch failed to finish")


def install_runner(monkeypatch, block=None, started=None):
    # Exercise the existing real study lifecycle; replace only simulation/model IO.
    from gaworld.research import interpret

    monkeypatch.setattr(
        "gaworld.research.provider_check.inspect_provider",
        lambda cfg, selected, **kw: {"primary": selected, "status": "configuration_only"},
    )
    monkeypatch.setattr(interpret, "interpret", lambda *a, **kw: {})
    monkeypatch.setattr(research_api, "_llm", lambda *args: lambda text: "unused")

    def seed_runner(child):
        def run(spec, seed, report):
            if started:
                started.set()
            active = research_api._active(child.id)
            while block and not block.is_set() and not active["stop"].is_set():
                time.sleep(0.01)
            return {
                "seed": seed,
                "root": "fixture",
                "status": "done",
                "world_status": {"base": "done", "treat": "done"},
                "actual_provider": spec.llm_provider,
                "actual_model": "test-" + spec.llm_provider,
                "execution_mode": "daily_brief",
                "report": {
                    "comparability_epoch": CURRENT_EPOCH,
                    "baseline": "base",
                    "worlds": [{"id": "base", "has_data": True}, {"id": "treat", "has_data": True}],
                    "metrics": {
                        "stress": {"base": {"final": 0.8, "mean": 0.8}, "treat": {"final": 0.3, "mean": 0.3}}
                    },
                    "deltas": {"treat": {"stress": {"final": -0.5, "mean": -0.5}}},
                    "trajectories": {"stress": {"base": [0.8, 0.8], "treat": [0.3, 0.3]}},
                },
            }

        return run

    monkeypatch.setattr(research_api, "_seed_runner", seed_runner)


def test_coordinator_creates_independent_studies_and_uses_real_lifecycle(env, monkeypatch):
    _, source, _ = env
    install_runner(monkeypatch)
    batch = create(source)
    body, status = api.handle_post(f"/api/research/batches/{batch['id']}/run", {})
    assert status == 202, body
    result = await_finished(batch["id"])
    assert result["status"] == "done", result
    assert len({cell["study_id"] for cell in result["cells"]}) == 4
    assert len(result["comparison"]["groups"]) == 2
    assert all(group["n"] == 2 for group in result["comparison"]["groups"])
    assert study.load_study(source.id).runs == []


def test_pause_stop_preserves_evidence_and_prevents_next_cell(env, monkeypatch):
    _, source, _ = env
    release, started = threading.Event(), threading.Event()
    install_runner(monkeypatch, release, started)
    batch = create(source)
    assert api.handle_post(f"/api/research/batches/{batch['id']}/run", {})[1] == 202
    assert started.wait(2)
    assert api.handle_post(f"/api/research/batches/{batch['id']}/pause", {})[1] == 200
    paused = api.handle_get(f"/api/research/batches/{batch['id']}")[0]
    assert paused["status"] == "paused"
    assert api.handle_post(f"/api/research/batches/{batch['id']}/stop", {})[1] == 200
    release.set()
    result = await_finished(batch["id"])
    assert result["status"] == "stopped"
    assert sum(bool(c.get("study_id")) for c in result["cells"]) == 1
    assert any(c["status"] == "cancelled" for c in result["cells"])
    assert result["progress"] < 1


def test_restart_marks_inflight_interrupted_instead_of_success(env):
    _, source, _ = env
    batch = create(source)
    batch["status"] = "running"
    batch["cells"][0]["status"] = "running"
    batches.save(batch)
    actual = api.handle_get(f"/api/research/batches/{batch['id']}")[0]
    assert actual["status"] == "interrupted"
    assert actual["cells"][0]["status"] == "interrupted"
    assert actual["comparison"]["counts"]["done"] == 0


def test_frozen_inputs_and_parameters_reach_actual_world_manifests(env, monkeypatch):
    from gaworld.parallel import runner
    from gaworld.research import backends

    root, source, config = env
    config["economy"] = {"enabled": True, "macro": {"inflation_rate": 0.03}}
    config["environment"] = {"events": [{"day": 2, "description": "Rain"}]}
    traits = root / "traits.csv"
    traits.write_text("agent_id,openness\n1,0.9\n")
    config["personality"] = {"enabled": True, "profile_path": str(traits)}
    batch = create(source)
    cell = batch["cells"][0]
    frozen = api.cell_config(batch, cell)
    protocol = api.cell_protocol(batch, cell)
    protocol.conditions[1]["config"] = {"economy": {"macro": {"inflation_rate": 0.08}}}

    class FakeRunner:
        def __init__(self, manifest, *a, **kw):
            self.manifest = manifest

        def run(self, report):
            self.manifest["status"] = "done"
            return {}

    monkeypatch.setattr(runner, "ExperimentRunner", FakeRunner)
    run = backends.default_seed_runner(
        repo_root=str(root),
        base_config=frozen,
        experiment_prefix="frozen",
        active={"actual_provider": "a", "ledger": str(root / "ledger.sqlite"), "frozen_batch": True},
    )
    result = run(backends.experiment_spec(protocol, cell["seed"]), cell["seed"], lambda *a: None)
    manifest = runner.load_manifest(str(root), result["root"])
    baseline = manifest["worlds"]["base"]["overrides"]
    treatment = manifest["worlds"]["treat"]["overrides"]
    assert baseline["personality"]["profile_path"] == frozen["personality"]["profile_path"]
    assert baseline["environment"]["events"][0]["description"] == "Rain"
    assert baseline["economy"]["macro"]["inflation_rate"] == 0.03
    assert treatment["economy"]["macro"]["inflation_rate"] == 0.08
    assert baseline["economy"]["output_dir"].startswith(manifest["worlds"]["base"]["dir"])
    assert "SECRET_A" not in str(manifest)


def test_subprocess_configuration_ignores_live_dashboard_and_default_keys(tmp_path, monkeypatch):
    import json

    from gaworld.parallel.runner import ExperimentRunner
    from gaworld.settings import overrides

    manifest = {
        "spec": {},
        "worlds": {"base": {"overrides": {"economy": {"enabled": True}, "random_seed": 42}}},
    }
    engine = ExperimentRunner(manifest, str(tmp_path))
    engine.research_frozen_config = {"economy": {"enabled": True}, "llm": {}, "agent_ids": [1]}
    child_env = engine._env("base")
    assert child_env["GAWORLD_RESEARCH_FROZEN_CONFIG"] == "1"
    monkeypatch.setenv("GAWORLD_CONFIG_OVERRIDES", child_env["GAWORLD_CONFIG_OVERRIDES"])
    monkeypatch.setenv("GAWORLD_RESEARCH_FROZEN_CONFIG", "1")
    monkeypatch.setattr(
        overrides,
        "load_json_override",
        lambda *args: (_ for _ in ()).throw(AssertionError("live dashboard read")),
    )
    loaded = overrides.apply_runtime_overrides({"economy": {"live_only_key": True}})
    assert loaded == json.loads(child_env["GAWORLD_CONFIG_OVERRIDES"])
    assert "live_only_key" not in loaded["economy"]


def test_capture_rejects_a_missing_condition_even_if_study_reported(env):
    from gaworld.research.batch_execution import capture

    _, source, _ = env
    batch = create(source)
    cell = batch["cells"][0]
    child = study.new_study({}, api.cell_protocol(batch, cell).to_dict(), {})
    child.stage = "reported"
    child.runtime = {
        "seed_identity": {"sha256": batch["inputs"][""]["assets"]["csv_path"]["sha256"]},
        "actual_agent_ids": [1],
    }
    child.runs = [{"status": "done", "world_status": {"base": "done"}}]
    assert capture(batch, cell, child)["valid"] is False


def test_capture_rejects_failed_required_questionnaire(env):
    from gaworld.research.batch_execution import capture

    _, source, _ = env
    batch = create(source)
    cell = batch["cells"][0]
    child = study.new_study({}, api.cell_protocol(batch, cell).to_dict(), {})
    child.protocol["kind"] = "composite"
    child.stage = "reported"
    child.runtime = {
        "seed_identity": {"sha256": batch["inputs"][""]["assets"]["csv_path"]["sha256"]},
        "actual_agent_ids": [1],
    }
    child.runs = [
        {
            "status": "done",
            "world_status": {"base": "done", "treat": "done"},
            "survey": {"base": {"error": "survey failed"}, "treat": {"scores": {}}},
        }
    ]
    assert capture(batch, cell, child)["valid"] is False


def test_post_run_survey_uses_full_frozen_config_in_child_environment(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from gaworld.research import backends
    from gaworld.research.protocol import Protocol

    protocol = Protocol.from_dict(
        {"title": "Survey", "conditions": [{"id": "base", "label": "Base"}], "survey": {"questions": []}}
    )
    world = tmp_path / "worlds" / "base"
    world.mkdir(parents=True)
    monkeypatch.setattr(
        backends.prunner,
        "load_manifest",
        lambda *a: {
            "worlds": {"base": {"dir": "worlds/base", "overrides": {"memory_dir": "worlds/base/memory"}}},
            "spec": {"agent_ids": [1]},
        },
    )
    monkeypatch.setattr(backends, "_respondent_ids", lambda *a: [1])
    seen = []

    def fake_run(command, **kwargs):
        seen.append(kwargs["env"])
        (world / "survey_answers.json").write_text('{"transcripts": []}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backends.subprocess, "run", fake_run)
    runner = backends.default_survey_runner(
        repo_root=str(tmp_path), frozen_config={"economy": {"frozen": True}, "llm": {}}
    )
    runner(protocol, {"root": "fixture"}, lambda *a: None)
    assert seen[0]["GAWORLD_RESEARCH_FROZEN_CONFIG"] == "1"
    config = json.loads(seen[0]["GAWORLD_CONFIG_OVERRIDES"])
    assert config["economy"] == {"frozen": True}
    assert config["memory_dir"] == "worlds/base/memory"
