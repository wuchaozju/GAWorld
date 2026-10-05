"""Both real simulator time paths execute controlled organization actions."""

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from gaworld.organizations.store import OrganizationStore
from tests.fixtures.mock_llm import install


@pytest.mark.parametrize("fast_forward", [False, True])
@pytest.mark.parametrize("governance", [False, True])
def test_resident_application_executes_in_real_simulation(tmp_path, monkeypatch, fast_forward, governance):
    import generative_city_sim as sim

    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "data", tmp_path / "data")
    monkeypatch.chdir(tmp_path)
    config = copy.deepcopy(sim.CONFIG)
    days = 4 if governance else 2
    config.update(agent_ids=[4], sim_days=days, stateful=False, simulate_realtime=False, seconds_per_day=1)
    for section in (
        "news",
        "intervention",
        "distributed",
        "cluster",
        "visualization",
        "life_events",
        "infosources",
        "moltbook",
        "real_work",
        "travel",
    ):
        config[section] = {**config.get(section, {}), "enabled": False}
    config["news"]["info_seek"] = {"enabled": False}
    config["external_rag"] = {"bootstrap": {"enabled": False}}
    config["organizations"] = {
        "enabled": True,
        "output_dir": "output/organizations",
        "governance": {"enabled": governance},
        "seeds": [
            {
                "organization_id": "care",
                "name": "测试互助会",
                "kind": "community",
                "leader_id": 4,
                "initial_balance_cents": 30000,
                "rule": "equal_split",
                "rule_params": {"max_award_cents": 15000},
            }
        ],
    }
    config["long_run"] = {**config.get("long_run", {}), "enabled": fast_forward, "unit": "day"}
    monkeypatch.setattr(sim, "CONFIG", config)
    for name, value in {
        "AGENT_IDS": [4],
        "SIM_DAYS": days,
        "STATEFUL": False,
        "SIMULATE_REALTIME": False,
        "SECONDS_PER_DAY": 1,
        "NEWS_ENABLED": False,
        "INTERVENTION_ENABLED": False,
        "HUMAN_REALISM_ENABLED": False,
        "VISUALIZATION_ENABLED": False,
        "LIFE_EVENTS_ENABLED": False,
        "LONG_RUN_ENABLED": fast_forward,
    }.items():
        monkeypatch.setattr(sim, name, value, raising=False)
    original_choose = sim.choose_action

    def choose(agent, activity, actions, **kwargs):
        provider = kwargs.get("candidate_provider")
        choices = provider(agent, activity) if provider else []
        if governance:
            choices = [a for a in choices if a.startswith("org:")]
        if choices:
            return choices[0], {"decision_driver": "test-controlled-choice", "scores": {}}
        return original_choose(agent, activity, actions, **kwargs)

    monkeypatch.setattr(sim, "choose_action", choose)
    with install() as mock:
        if fast_forward:

            def day_response(prompt, _agent_id):
                match = re.search(r"【可执行动作】\n(\[[^\n]+\])", prompt)
                actions = json.loads(match.group(1)) if match else []
                return json.dumps(
                    {
                        "brief": "参与组织行动",
                        "memory": "组织行动",
                        "selected_action": actions[0] if actions else "",
                        "state_changes": {},
                    }
                )

            if governance:
                mock.set_handler("fast_forward_day", day_response)
            else:
                mock.set_response(
                    "fast_forward_day",
                    json.dumps(
                        {
                            "brief": "申请资助",
                            "memory": "提出申请",
                            "selected_action": "org:apply_aid:care:15000",
                            "state_changes": {},
                        }
                    ),
                )
        sim.run_simulation()
        if fast_forward:
            assert len([call for call in mock.calls if call["task"] == "fast_forward_day"]) == days
    store = OrganizationStore(tmp_path / config.get("memory_dir", "output/memory") / "organizations.sqlite")
    try:
        org = store.detail("care")
        assert org["applications"][0]["source"]["source"] == "resident"
        assert org["applications"][0]["paid_cents"] == 15000
        if governance:
            p = org["proposals"][0]
            assert p["status"] == "executed" and p["execution_day"] == 4
            assert org["rule"] == "need_first" and org["rule_version"] == 2
            assert org["ballots"][0]["choice"] == "yes"
            assert org["ballots"][0]["actor"]["source"] == "resident"
            assert p["resolved_day"] == 3 and p["opened_day"] == 2
        else:
            assert org["balance_cents"] == 15000
        assert store.get_meta("last_processed_day") == days
    finally:
        store.close()
