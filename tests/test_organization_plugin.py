"""Organizations are opt-in participants of the shared runtime hooks."""

from __future__ import annotations

import importlib
import json
import random
import sqlite3

import pytest

from gaworld.kernel import EventBus, build_kernel


def _plugin_module():
    assert importlib.util.find_spec("gaworld.organizations.plugin") is not None
    return importlib.import_module("gaworld.organizations.plugin")


def _config(tmp_path, **updates):
    config = {
        "organizations": {"enabled": True, "seeds": []},
        "economy": {"enabled": True},
        "memory_dir": str(tmp_path / "memory"),
        "records": {"output_dir": str(tmp_path / "records")},
        "long_run": {"unit": "day"},
    }
    config.update(updates)
    return config


def test_critical_bus_handlers_propagate_failures_without_strict_mode():
    bus = EventBus()

    def broken(context):
        raise ValueError("recovery_required")

    bus.on("payment", broken, critical=True)
    with pytest.raises(ValueError, match="recovery_required"):
        bus.emit("payment")


@pytest.mark.parametrize("method", ["collect", "filter"])
def test_critical_bus_contribution_failures_propagate(method):
    bus = EventBus()

    def broken(*args):
        raise ValueError("invalid state")

    bus.on("critical", broken, critical=True)
    with pytest.raises(ValueError, match="invalid state"):
        getattr(bus, method)("critical", *([[]] if method == "filter" else []))


def test_default_organizations_disabled_and_built_in(tmp_path):
    from gaworld.plugins import builtin_plugins
    from gaworld.settings.defaults import build_default_config

    config = build_default_config()
    assert config.get("organizations", {}).get("enabled") is False
    assert "organizations" in [p.id for p in builtin_plugins()]
    module = _plugin_module()
    ctx = build_kernel(_config(tmp_path, organizations={"enabled": False}), load_entry_points=False)
    before = random.getstate()
    module.OrganizationsPlugin().setup(ctx)
    ctx.bus.emit("on_simulation_start", agents=[{"id": 1}], extension_state={})
    assert not ctx.plugin_state("organizations")
    assert not list(tmp_path.iterdir())
    assert random.getstate() == before


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"economy": {"enabled": False}}, "economy"),
        ({"long_run": {"unit": "month"}}, "month"),
        ({"long_run": {"unit": "year", "enabled": False}}, "year"),
        ({"distributed": {"enabled": True}}, "distributed"),
        ({"cluster": {"enabled": True}}, "distributed"),
    ],
)
def test_runtime_preflight_rejects_unsupported_organization_modes(tmp_path, patch, message):
    from gaworld import plugins

    assert hasattr(plugins, "validate_runtime_config")
    with pytest.raises(ValueError, match=message):
        plugins.validate_runtime_config(_config(tmp_path, **patch))
    assert not list(tmp_path.iterdir())


def test_disabled_organization_preflight_does_not_reject_legacy_modes(tmp_path):
    from gaworld import plugins

    assert hasattr(plugins, "validate_runtime_config")
    plugins.validate_runtime_config(
        _config(
            tmp_path,
            organizations={"enabled": False},
            economy={"enabled": False},
            long_run={"unit": "year"},
            distributed={"enabled": True},
        )
    )


def test_plugin_lifecycle_after_economy_and_actual_actions(tmp_path, monkeypatch):
    module = _plugin_module()
    calls = []

    class Service:
        def __init__(self, config, agents, context, recorder=None):
            assert context["extension_state"]["economy_module"] == {"enabled": True}
            self.context = context
            calls.append(("init", agents))

        def start(self, day):
            calls.append(("start", day))

        def prepare_day(self, day):
            calls.append(("prepare", day))

        def process_day(self, day):
            calls.append(("process", day))

        def finish_day(self, day):
            calls.append(("finish", day))

        def close(self):
            calls.append(("close",))

        def perception(self, agent):
            return "组织预算 12 元"

        def candidates(self, agent, activity):
            return ["org:apply_aid:club:100"]

        def handle_action(self, agent, action, day, time_str):
            calls.append(("action", action, day, time_str))
            return action.startswith("org:")

    monkeypatch.setattr(module, "OrganizationService", Service)
    ctx = build_kernel(_config(tmp_path), load_entry_points=False)
    agent = {"id": 1, "name": "甲"}
    ctx.set_agents([agent])
    plugin = module.OrganizationsPlugin()
    plugin.setup(ctx)
    ctx.bus.on("on_simulation_start", lambda c: c["extension_state"].update(economy_module={"enabled": True}))
    ctx.bus.on("on_day_start", lambda c: calls.append(("economy_reset", c["day"])))
    ctx.bus.on("on_day_end", lambda c: calls.append(("family", c["day"])), priority=-10)
    ctx.bus.emit("on_simulation_start", agents=[agent], day=4, extension_state={})
    assert ctx.plugin_state("organizations")["service"].context["sim"] is ctx
    ctx.bus.emit("on_day_start", day=4)
    assert calls[-3:] == [("prepare", 4), ("economy_reset", 4), ("process", 4)]
    assert ctx.bus.collect("perception.sections", agent=agent)
    assert ctx.bus.collect("action.candidates", agent=agent, activity="自由活动") == [
        "org:apply_aid:club:100"
    ]
    ctx.bus.emit(
        "on_agent_post_step",
        agent=agent,
        day=4,
        time_str="10:00",
        step={"action": "散步", "outcome": "已获资助100元"},
    )
    ctx.bus.emit(
        "on_agent_post_step", agent=agent, day=4, time_str="12:00", step={"action": "org:apply_aid:club:100"}
    )
    ctx.bus.emit("on_day_end", day=4)
    ctx.bus.emit("on_simulation_end")
    assert [c for c in calls if c[0] == "action"] == [("action", "org:apply_aid:club:100", 4, "12:00")]
    assert calls[-3:] == [("family", 4), ("finish", 4), ("close",)]


def test_plugin_recovery_failure_stops_run(tmp_path, monkeypatch):
    module = _plugin_module()

    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def start(self, day):
            raise ValueError("recovery_required")

    monkeypatch.setattr(module, "OrganizationService", Broken)
    ctx = build_kernel(_config(tmp_path), load_entry_points=False)
    module.OrganizationsPlugin().setup(ctx)
    with pytest.raises(ValueError, match="recovery_required"):
        ctx.bus.emit("on_simulation_start", agents=[], day=1, extension_state={})


def test_candidate_extension_is_actual_selection_and_does_not_mutate_space(monkeypatch):
    from gaworld.sim import _action

    agent = {"id": 1, "state": {"stress": 0.2, "emotion": 0.6, "econ_security": 0.5}}
    monkeypatch.setattr(_action, "_stateful", lambda: False)
    monkeypatch.setattr(_action, "_realism_enabled", lambda: False)
    choices = []
    monkeypatch.setattr(
        _action.random, "choices", lambda options, **kwargs: choices.extend(options) or [options[-1]]
    )
    space = {"自由活动": ["散步"]}
    chosen = _action.choose_action(
        agent,
        "自由活动",
        space,
        recall_context={"hits": []},
        candidate_provider=lambda *args: ["org:apply_aid:club:100"],
    )
    assert chosen == "org:apply_aid:club:100"
    assert choices == ["散步", "org:apply_aid:club:100"]
    assert space == {"自由活动": ["散步"]}


def test_fast_forward_selects_only_whitelisted_controlled_actions():
    from gaworld.sim import _fastforward as ff

    prompts = []
    action = "org:apply_aid:club:100"

    def llm(prompt, **kwargs):
        prompts.append(prompt)
        return json.dumps({"brief": "今天提交了申请", "selected_action": action})

    digest = ff.simulate_agent_day(
        {"id": 1, "name": "甲", "state": {}},
        day=1,
        day_desc="周一",
        base_schedule=[],
        config={"long_run": {"randomness": 0}},
        llm_fn=llm,
        perception_sections=["社区组织 club 正在接受申请"],
        action_candidates=[action],
    )
    assert digest["selected_action"] == action
    assert "社区组织 club" in prompts[0] and action in prompts[0]
    forged = ff.simulate_agent_day(
        {"id": 1, "state": {}},
        day=1,
        day_desc="周一",
        base_schedule=[],
        config={"long_run": {"randomness": 0}},
        llm_fn=llm,
        action_candidates=["org:apply_aid:other:100"],
    )
    assert forged["selected_action"] == ""
    narrative = ff.simulate_agent_day(
        {"id": 1, "state": {}},
        day=1,
        day_desc="周一",
        base_schedule=[],
        config={"long_run": {"randomness": 0}},
        llm_fn=lambda *args, **kw: json.dumps({"brief": action}),
        action_candidates=[action],
    )
    assert narrative["selected_action"] == ""


def test_organization_output_path_and_manifest_configuration(tmp_path):
    from gaworld.city.config import run_overrides
    from gaworld.core.run_manifest import _curate_config

    assert (
        run_overrides("sample").get("organizations", {}).get("output_dir")
        == "output/cities/sample/organizations"
    )
    config = {
        "organizations": {
            "enabled": True,
            "seeds": [{"name": "一", "rule": "equal"}],
            "output_dir": str(tmp_path),
        }
    }
    assert _curate_config(config).get("organizations") == config["organizations"]


def test_dashboard_launch_rejects_before_opening_log_or_spawning(tmp_path, monkeypatch):
    from gaworld.apps import runs

    monkeypatch.setattr(runs.paths, "effective_config", lambda: _config(tmp_path, economy={"enabled": False}))
    monkeypatch.setattr(runs.paths, "run_log_path", lambda: str(tmp_path / "run.log"))
    monkeypatch.setattr(runs, "simulation_env", dict)
    spawned = []
    monkeypatch.setattr(runs.subprocess, "Popen", lambda *args, **kw: spawned.append(args))
    with pytest.raises(ValueError, match="economy"):
        runs.launch({}, {})
    assert not spawned and not list(tmp_path.iterdir())


def _stored_meta(tmp_path, entries):
    directory = tmp_path / "memory"
    directory.mkdir()
    with sqlite3.connect(directory / "organizations.sqlite") as db:
        db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)")
        db.executemany("INSERT INTO meta VALUES(?,?)", [(k, json.dumps(v)) for k, v in entries.items()])


def test_dashboard_reset_can_discard_incomplete_prior_organization_state(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from gaworld.apps import runs

    _stored_meta(tmp_path, {"schema_version": 1, "recovery_required": True})
    monkeypatch.setattr(runs.paths, "effective_config", lambda: _config(tmp_path, stateful=True))
    monkeypatch.setattr(runs.paths, "run_log_path", lambda: str(tmp_path / "run.log"))
    monkeypatch.setattr(runs, "simulation_env", dict)
    monkeypatch.setattr(runs, "limited_user_id", lambda: None)
    commands = []

    def reset(cmd, **kwargs):
        commands.append(cmd[-1])
        (tmp_path / "memory" / "organizations.sqlite").unlink()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runs.subprocess, "run", reset)
    monkeypatch.setattr(
        runs.subprocess, "Popen", lambda cmd, **kw: commands.append(cmd[-1]) or SimpleNamespace()
    )
    runs.launch({}, {"reset": True})
    assert commands == ["reset", "run"]


def test_dashboard_reset_request_can_enter_queue_with_incomplete_prior_state(tmp_path, monkeypatch):
    from gaworld.apps import runs

    _stored_meta(tmp_path, {"schema_version": 1, "open_day": 1})
    monkeypatch.setattr(runs.paths, "effective_config", lambda: _config(tmp_path, stateful=True))
    monkeypatch.setattr(runs, "run_state", dict)
    monkeypatch.setattr(runs, "foreign_simulator_pid", lambda: None)
    monkeypatch.setattr(runs, "queue_position", lambda: None)
    monkeypatch.setattr(runs, "check_agent_ids_against_city", lambda: None)
    monkeypatch.setattr(runs, "limited_user_id", lambda: None)
    monkeypatch.setattr(runs, "queue_key", lambda: "world")
    monkeypatch.setattr(runs, "gate_open", lambda *args: False)
    monkeypatch.setattr(runs.accounts, "enabled_store", lambda *args: None)
    monkeypatch.setattr(runs, "RUN_QUEUE", [])
    monkeypatch.setattr(runs, "ensure_dispatcher", lambda: None)
    monkeypatch.setattr(runs, "run_status", lambda: {"queued": len(runs.RUN_QUEUE)})
    assert runs.start_simulation({"reset": True})["queued"] == 1
    assert runs.RUN_QUEUE[0]["payload"] == {"reset": True}


@pytest.mark.parametrize("seeds", ["invalid", [None], [1], {"organization_id": "wrong"}])
def test_preflight_rejects_malformed_seed_containers(tmp_path, seeds):
    from gaworld.plugins import validate_runtime_config

    with pytest.raises(ValueError, match="seeds"):
        validate_runtime_config(_config(tmp_path, organizations={"enabled": True, "seeds": seeds}))


@pytest.mark.parametrize(
    "entries, message",
    [
        ({"schema_version": 999}, "schema"),
        ({"schema_version": 1, "recovery_required": True}, "recovery_required"),
        ({"schema_version": 1, "last_processed_day": 2}, "clock"),
        ({"schema_version": 1, "population_source": "/different/city.csv"}, "population"),
    ],
)
def test_preflight_checks_existing_state_without_writing(tmp_path, entries, message):
    from gaworld.plugins import validate_runtime_config

    _stored_meta(tmp_path, entries)
    before = (tmp_path / "memory" / "organizations.sqlite").read_bytes()
    with pytest.raises(ValueError, match=message):
        validate_runtime_config(_config(tmp_path, stateful=True, csv_path=str(tmp_path / "people.csv")))
    assert (tmp_path / "memory" / "organizations.sqlite").read_bytes() == before
    assert not (tmp_path / "memory" / "organizations.sqlite-wal").exists()


def test_preflight_rejects_reused_population_identity(tmp_path):
    from gaworld.organizations.schemas import identity_fingerprint
    from gaworld.plugins import validate_runtime_config

    _stored_meta(
        tmp_path,
        {
            "schema_version": 1,
            "identities": {"1": identity_fingerprint({"id": 1, "name": "旧人", "gender": "男"})},
        },
    )
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("id,name,gender\n1,新人,男\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        validate_runtime_config(_config(tmp_path, stateful=True, csv_path=str(csv_path), agent_ids=[1]))


def test_reset_clears_organization_output_without_removing_seed_definition(tmp_path, monkeypatch):
    import generative_city_sim as sim

    output = tmp_path / "organizations"
    output.mkdir()
    (output / "snapshot.json").write_text("{}")
    config = _config(tmp_path)
    config["organizations"]["output_dir"] = str(output)
    monkeypatch.setattr(sim, "CONFIG", config)
    monkeypatch.setattr(sim, "save_sim_state", lambda state: None)
    monkeypatch.setattr(sim, "life_event_dir", lambda config: str(tmp_path / "events"))
    for name in (
        "STATE_OUTPUT_DIR",
        "NETWORK_OUTPUT_DIR",
        "ENV_OUTPUT_DIR",
        "DIARY_OUTPUT_DIR",
        "VISUALIZATION_OUTPUT_DIR",
        "INTERVENTION_OUTPUT_DIR",
    ):
        monkeypatch.setattr(sim, name, str(tmp_path / name))
    sim.reset_simulation()
    assert list(output.iterdir()) == []
    assert config["organizations"]["seeds"] == []
