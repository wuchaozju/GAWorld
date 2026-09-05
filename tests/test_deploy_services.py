from __future__ import annotations

from types import SimpleNamespace

from gaworld.apps import deploy_services


def _args(**overrides):
    values = {
        "host": "0.0.0.0",
        "dashboard_port": 8766,
        "relay_port": 8877,
        "relay_state_path": "output/distributed/relay_state.json",
        "relay_max_messages": 20000,
        "dashboard_unit": "gaworld-dashboard.service",
        "relay_unit": "gaworld-agent-relay.service",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_service_specs_build_dashboard_and_relay_commands():
    specs = deploy_services.service_specs(_args(), "/repo/.venv/bin/python")

    assert [spec.name for spec in specs] == ["dashboard", "relay"]
    assert specs[0].command == [
        "/repo/.venv/bin/python",
        "generative_city_sim.py",
        "dashboard",
        "--host",
        "0.0.0.0",
        "--port",
        "8766",
    ]
    assert specs[0].health_url == "http://127.0.0.1:8766/api/config"
    assert specs[0].systemd_unit == "gaworld-dashboard.service"
    assert specs[1].command[:3] == ["/repo/.venv/bin/python", "generative_city_sim.py", "serve-distributed"]
    assert specs[1].health_url == "http://127.0.0.1:8877/health"
    assert specs[1].systemd_unit == "gaworld-agent-relay.service"


def test_host_for_health_preserves_specific_hosts():
    assert deploy_services._host_for_health("10.72.74.13") == "10.72.74.13"
    assert deploy_services._host_for_health("0.0.0.0") == "127.0.0.1"


def test_parser_supports_systemd_user_manager():
    args = deploy_services.build_parser().parse_args(
        [
            "deploy",
            "--process-manager",
            "systemd-user",
            "--dashboard-unit",
            "custom-dashboard.service",
            "--relay-unit",
            "custom-relay.service",
        ]
    )

    assert args.process_manager == "systemd-user"
    assert args.dashboard_unit == "custom-dashboard.service"
    assert args.relay_unit == "custom-relay.service"
