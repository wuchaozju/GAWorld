from fos.core.experiment.scenes.gaworld.translator import GAWorldOutputTranslator


def test_translate_day_returns_event_per_agent_action() -> None:
    translator = GAWorldOutputTranslator({1: "Alice", 2: "Bob"})
    day_data = {
        "round": 3,
        "agents": [
            {
                "id": 1,
                "actions": [
                    {"type": "work", "hours": 8, "description": "Worked all day"},
                    {"type": "dance", "description": "Did a dance"},
                ],
            },
            {
                "id": 2,
                "actions": [
                    {"type": "rest", "hours": 7, "description": "Slept well"},
                ],
            },
        ],
    }

    events = translator.translate_day(day_data)

    assert len(events) == 3


def test_event_has_required_keys_and_success_true() -> None:
    translator = GAWorldOutputTranslator({1: "Alice"})
    day_data = {
        "round": 1,
        "agents": [{"id": 1, "actions": [{"type": "work", "hours": 8, "description": "Worked"}]}],
    }

    events = translator.translate_day(day_data)

    event = events[0]
    assert event["agent"] == "Alice"
    assert event["action"] == "work"
    assert event["parameters"]["hours"] == 8
    assert event["summary"] == "Worked"
    assert event["round"] == 1
    assert event["success"] is True


def test_unknown_action_maps_to_custom_and_records_warning() -> None:
    translator = GAWorldOutputTranslator({1: "Alice"})
    day_data = {
        "round": 1,
        "agents": [{"id": 1, "actions": [{"type": "mystery", "description": "Unknown move"}]}],
    }

    events = translator.translate_day(day_data)

    assert events[0]["action"] == "custom"
    assert events[0]["parameters"] == {"raw_action": "mystery"}
    assert "mystery" in translator.warnings


def test_translate_day_accepts_gaworld_action_map_shape() -> None:
    translator = GAWorldOutputTranslator({50: "Xu Zhixia"})
    day_data = {
        "round": 1,
        "agents": [
            {
                "id": 50,
                "actions": {
                    "晨间散步，观察社区公共设施使用情况": [
                        "沿社区步道慢走，注意设施使用频率与人群流动",
                        "保持距离观察，避免干扰居民正常活动",
                    ],
                    "睡觉": [
                        "在床头放置一张手写便签，记录明日策展会议的议题要点",
                    ],
                },
            }
        ],
    }

    events = translator.translate_day(day_data)

    assert len(events) == 2
    assert events[0]["agent"] == "Xu Zhixia"
    assert events[0]["action"] == "custom"
    assert events[0]["parameters"] == {"raw_action": "晨间散步，观察社区公共设施使用情况"}
    assert events[0]["summary"] == "晨间散步，观察社区公共设施使用情况"
    assert events[1]["parameters"] == {"raw_action": "睡觉"}


def test_translate_state_updates_returns_state_values_by_agent_name() -> None:
    translator = GAWorldOutputTranslator({1: "Alice"})
    day_data = {
        "agents": [
            {
                "id": 1,
                "emotion": 0.6,
                "stress": 0.2,
                "econ_security": 0.7,
                "city_identity": 0.9,
            }
        ]
    }

    state_updates = translator.translate_state_updates(day_data)

    assert state_updates == {
        "Alice": {
            "emotion": 0.6,
            "stress": 0.2,
            "econ_security": 0.7,
            "city_identity": 0.9,
        }
    }
