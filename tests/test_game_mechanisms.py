"""Behavioral regressions for the rumor/disaster measurement revision."""

import json

import pytest

from gaworld.apps import disaster_api as disaster
from gaworld.apps import rumor_api as rumor


def reaction(**fields):
    return disaster.parse_reaction(
        json.dumps(
            {
                "action": "求助求援",
                "panic": 4,
                "help": False,
                "detail": "联系社区",
                "say": "请帮忙",
                **fields,
            },
            ensure_ascii=False,
        )
    )


@pytest.mark.parametrize(
    "raw",
    [
        "{'action':'求助求援','panic':4,'help':false,'detail':'联系社区','say':'请帮忙'}",
        '{"action":"求助求援","panic":4,"help":false,}',
    ],
)
def test_repair_recovers_fields_without_showing_raw_as_speech(raw):
    got = disaster.parse_reaction(raw)
    assert got["action"] == "求助求援"
    assert got["panic"] == 4
    assert got["help"] is False
    assert got["parse_status"] == "repaired"
    assert not got["say"].startswith("{")


def test_false_string_is_not_help():
    assert reaction(help="false")["help"] is False


def test_missing_action_is_not_an_evacuation():
    got = disaster.parse_reaction('{"panic":4,"help":false}')
    assert got["action"] == disaster.OTHER_ACTION
    assert not got["valid_action"]


@pytest.mark.parametrize("score", [None, "高", float("nan"), float("inf"), 0, 6, True, 2.5])
def test_invalid_panic_is_missing(score):
    assert reaction(panic=score)["panic"] is None


def test_invalid_reply_does_not_fabricate_measurements():
    broken = disaster.parse_reaction("模型服务暂不可用")
    stats = disaster._aggregate([reaction(help=True), broken])
    assert stats["n"] == 2
    assert stats["panic_n"] == stats["help_n"] == stats["action_n"] == 1
    assert stats["helpers"] == 1
    assert stats["help_rate"] == 1
    assert stats["avg_panic"] == 4
    assert stats["invalid_n"] == 1
    assert broken["say"] == ""
    assert broken["raw"] == "模型服务暂不可用"
    assert disaster._aggregate([broken])["help_rate"] is None
    assert disaster._aggregate([broken])["avg_panic"] is None


def test_fields_have_independent_denominators():
    stats = disaster._aggregate([reaction(panic=None, help=True), reaction(help="unknown")])
    assert stats["panic_n"] == stats["help_n"] == 1
    assert stats["help_rate"] == 1


def test_expanded_actions_and_secondary_choices():
    for action in ("保护家人", "转移财产", "等待官方通知"):
        got = reaction(action=action, secondary_actions=["打探消息", action, "不存在"])
        assert got["action"] == action
        assert got["secondary_actions"] == ["打探消息"]


def test_entertainment_forward_reaches_next_person_as_a_joke():
    nodes = {i: rumor.Node(i, f"居民{i}", persona_text=f"你是居民{i}") for i in (1, 2, 3)}
    calls = []

    def answer(prompt):
        calls.append(prompt)
        return json.dumps(
            {"action": "转发", "belief": 2, "motive": "娱乐玩梗", "say": "零下32度，企鹅来上班了哈哈"},
            ensure_ascii=False,
        )

    run = rumor.run_rumor(
        city="",
        agent_ids=[],
        custom={"text": "明天零下32度", "title": "寒潮"},
        nodes=nodes,
        edges=[
            {"a": 1, "b": 2, "label": "邻居", "closeness": 0.5},
            {"a": 2, "b": 3, "label": "邻居", "closeness": 0.5},
        ],
        seeds=[1],
        rounds=3,
        answer_fn=answer,
        summary_fn=lambda p: "",
    )
    assert "企鹅来上班" in calls[1]
    assert "玩梗" in calls[0]
    assert run["stats"]["entertainment_forwarders"] == 3
    assert run["stats"]["believers"] == 0
    assert run["transmissions"][0]["motive"] == "娱乐玩梗"
    assert run["nodes"][0]["events"][0]["motive"] == "娱乐玩梗"
    assert "传播动机：娱乐玩梗" not in calls[1]  # Internal intent is not observable.


def test_remote_spreaders_do_not_become_local_social_proof():
    nodes = {i: rumor.Node(i, f"居民{i}") for i in (1, 2, 3)}
    calls = []

    def answer(prompt):
        calls.append(prompt)
        return '{"action":"转发","belief":90,"say":"快看"}'

    rumor.run_rumor(
        city="",
        agent_ids=[],
        rumor_id="water",
        nodes=nodes,
        edges=[],
        seeds=[1, 2],
        rounds=1,
        answer_fn=answer,
        summary_fn=lambda p: "",
    )
    assert "1 个人在传这条" not in calls[1]


def disaster_run(**kwargs):
    people = [disaster.Participant(i, f"居民{i}", persona_text=f"你是居民{i}") for i in (1, 2, 3)]
    calls = []

    def answer(prompt):
        calls.append(prompt)
        return '{"action":"救助他人","panic":2,"help":true,"detail":"扶老人撤离","say":"我来帮你"}'

    run = disaster.run_disaster(
        city="",
        agent_ids=[],
        participants=people,
        disaster_id="flood",
        stages=2,
        answer_fn=answer,
        summary_fn=lambda p: "",
        **kwargs,
    )
    return run, calls


def test_local_stages_differ_and_custom_script_is_preserved():
    mountain, _ = disaster_run(region={"terrain": "山区", "source": "web"}, edges=[])
    coast, _ = disaster_run(region={"terrain": "沿海平原", "source": "web"}, edges=[])
    water, _ = disaster_run(region={"terrain": "平原水乡", "water": "河网密布", "source": "web"}, edges=[])
    assert "山洪" in mountain["stages"][0]
    assert "沿海" in coast["stages"][0]
    assert "河网" in water["stages"][0]
    assert len({tuple(x["stages"]) for x in (mountain, coast, water)}) == 3
    assert "地铁" not in mountain["stages"][0]
    custom, _ = disaster_run(
        region={"terrain": "山区"},
        edges=[],
        custom={"name": "测试", "stages": ["用户的第一幕", "用户的第二幕"]},
    )
    assert custom["stages"] == ["用户的第一幕", "用户的第二幕"]


def test_disaster_observations_follow_edges_and_previous_stage():
    edges = [{"a": 1, "b": 2, "label": "邻居", "channel": "face_to_face", "source": "explicit"}]
    run, calls = disaster_run(region={}, edges=edges)
    assert all("扶老人撤离" not in prompt for prompt in calls[:3])
    assert "居民2" in calls[3]
    assert "我来帮你" in calls[3]
    assert "居民3" not in calls[3]
    assert "居民1" not in calls[5]
    assert len(run["transmissions"]) == 2
    assert all(event["from"] != event["to"] for event in run["transmissions"])
    assert run["agents"][2]["reactions"][1]["observations"] == []


def test_network_failure_blocks_remote_but_not_visible_neighbors():
    edges = [
        {"a": 1, "b": 2, "label": "同事", "channel": "remote", "source": "explicit"},
        {"a": 2, "b": 3, "label": "邻居", "channel": "face_to_face", "source": "inferred"},
    ]
    run, _ = disaster_run(region={}, edges=edges)
    # Flood stage 2 explicitly disconnects electricity and network.
    assert {(e["from"], e["to"]) for e in run["transmissions"]} == {(2, 3), (3, 2)}
    assert len(run["blocked_transmissions"]) == 2


def test_inferred_same_surname_is_not_claimed_as_a_family():
    from gaworld.apps import disaster_context

    rows = [
        {"id": 1, "name": "李一", "age": 30, "job": "教师", "residence": "A小区"},
        {"id": 2, "name": "李二", "age": 32, "job": "教师", "residence": "A小区"},
    ]
    edges = disaster_context.relationship_edges(rows)
    assert edges[0]["label"] == "邻居"
    assert edges[0]["source"] == "inferred"
    rows[0]["relationships"] = {"2": {"relation": "sibling", "closeness": 0.9}}
    edges = disaster_context.relationship_edges(rows)
    assert edges[0]["source"] == "explicit"
    assert edges[0]["label"] == "兄弟姐妹"


def test_existing_relationship_files_are_read_with_world_paths(tmp_path, monkeypatch):
    from gaworld.apps import disaster_context, world_paths
    from gaworld.interview import roster

    rows = [{"id": i, "name": f"居民{i}", "age": 30, "job": "教师", "residence": "A小区"} for i in (1, 2)]
    seed = tmp_path / "agents.csv"
    seed.write_text("id,name\n1,居民1\n2,居民2\n")
    (tmp_path / "agent_1_relationships.json").write_text('{"2":{"role":"spouse","kind":"agent"}}')
    monkeypatch.setattr(world_paths, "effective_config", lambda: {"city": ""})
    monkeypatch.setattr(world_paths, "state_csv_path", lambda: str(seed))
    monkeypatch.setattr(world_paths, "memory_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(roster, "recruitment_population", lambda city: rows)
    _, edges = disaster_context.load_context("", [1, 2])
    assert edges[0]["source"] == "explicit"
    assert edges[0]["label"] == "配偶"


def test_parser_never_executes_expressions_or_replaces_string_literals(tmp_path):
    path = tmp_path / "must-not-exist"
    got = disaster.parse_reaction('{"action":__import__("os").system("touch ' + str(path) + '")}')
    assert got["parse_status"] == "invalid"
    assert not path.exists()
    got = disaster.parse_reaction("{'action':'求助求援','panic':2,'help':false,'say':'true false null }'}")
    assert got["say"] == "true false null }"


def test_excessively_nested_reply_does_not_crash_round():
    got = disaster.parse_reaction('{"detail":' + "[" * 2000 + "0" + "]" * 2000 + "}")
    assert got["parse_status"] == "invalid"


def test_structured_speech_is_not_displayed_as_a_quote():
    got = reaction(say={"action": "求助求援"}, detail=["联系社区"])
    assert got["say"] == ""
    assert got["detail"] == ""
    assert "say" in got["issues"] and "detail" in got["issues"]


def test_outage_persists_until_explicit_restoration():
    from gaworld.apps import disaster_context

    people = [disaster.Participant(i, f"居民{i}", reactions=[reaction()]) for i in (1, 2)]
    edges = [{"a": 1, "b": 2, "channel": "remote"}]
    inbox, blocked = disaster_context.stage_messages(people, edges, 1, "第二天断网。第五天水退了。")
    assert inbox[1] == [] and len(blocked) == 2
    inbox, blocked = disaster_context.stage_messages(people, edges, 1, "第二天断网。第五天网络恢复。")
    assert len(inbox[1]) == 1 and not blocked


def test_benchmark_does_not_pool_different_mechanisms(tmp_path):
    from benchmark import gaworld_bench as bench

    folder = tmp_path / "disaster"
    folder.mkdir()
    for i, version in enumerate((None, "disaster-2")):
        run = {"agents": [{"reactions": [{"action": "救助他人", "panic": 2, "help": True}]}]}
        if version:
            run["mechanism_version"] = version
        (folder / f"{i}.json").write_text(json.dumps({"result": run}))
    result = bench.track_b_games(tmp_path)
    fact = next(f for f in result["facts"] if f["id"] == "disaster_panic_rare")
    assert fact["reproduced"] is None
    assert "机制版本" in fact["abstain"]
    assert fact["units"] == 0


def test_benchmark_uses_valid_field_denominators():
    from benchmark import gaworld_bench as bench

    records = [
        {
            "result": {
                "agents": [
                    {
                        "reactions": [
                            {"action": "救助他人", "panic": 2, "help": True},
                            {"action": "打探消息", "panic": None, "help": None},
                            {"action": "等待官方通知", "panic": 5, "help": None},
                        ]
                    }
                ]
            }
        }
    ]
    _, _, values, _ = bench._fact_panic(records)
    assert values["extreme_share"] == 0.5
    assert values["help_rate"] == 1
    assert values["panic_n"] == 2
    assert values["help_n"] == 1
