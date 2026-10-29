from __future__ import annotations

import pytest

from gaworld.crowdsourcing.models import CrowdStatus
from gaworld.crowdsourcing.service import CrowdsourcingService
from gaworld.crowdsourcing.strategies import STRATEGIES, strategy_catalog


def _agents() -> dict[int, dict]:
    return {
        agent_id: {
            "id": agent_id,
            "name": f"居民{agent_id}",
            "capabilities": {"job_label": f"职业{agent_id}", "skills": ["分析"]},
            "growth": {"items": []},
            "private_skills": [],
            "profile_text": "",
        }
        for agent_id in range(1, 9)
    }


def _service(tmp_path, **overrides) -> CrowdsourcingService:
    agents = _agents()
    values = {
        "config": {
            "sessions_dir": str(tmp_path / "sessions"),
            "max_pool_size": 20,
            "max_rounds": 6,
            "max_participants_per_round": 8,
            "background": False,
        },
        "sessions_dir": tmp_path / "sessions",
        "agent_loader": agents.get,
        "llm": lambda *args, **kwargs: '{"bid": 0.5, "confidence": 0.5, "reason": "r"}',
        "background": False,
    }
    values.update(overrides)
    return CrowdsourcingService(**values)


def test_strategy_catalog_exposes_the_four_mechanisms():
    catalog = strategy_catalog()

    assert [item["id"] for item in catalog] == ["market", "vote", "elite", "debate"]
    market = next(item for item in catalog if item["id"] == "market")
    assert market["source"] == "https://arxiv.org/abs/2610.22322"
    assert market["bids"] is True
    assert "clear" in market["mechanics"]
    assert STRATEGIES["debate"].critique is True
    assert STRATEGIES["vote"].bids is False


def test_service_reports_strategy_defaults_and_limits(tmp_path):
    service = _service(tmp_path)

    catalog = service.strategies()

    assert catalog["defaults"]["strategy"] == "market"
    assert catalog["limits"]["max_pool_size"] == 20
    assert catalog["limits"]["max_rounds"] == 6
    assert catalog["limits"]["max_participants_per_round"] == 8


def test_service_creates_a_queued_session(tmp_path):
    service = _service(tmp_path)

    created = service.create_crowd(
        [1, 2, 3],
        task="设计夜间照明方案",
        strategy="vote",
        rounds=2,
        participants_per_round=2,
    )

    assert created.status is CrowdStatus.QUEUED
    assert created.agent_ids == [1, 2, 3]
    assert created.strategy == "vote"
    assert created.participants_per_round == 2
    assert service.get_session(created.id)["task"] == "设计夜间照明方案"
    assert service._executor is None
    assert service._futures == {}


def test_service_deduplicates_the_pool(tmp_path):
    service = _service(tmp_path)

    created = service.create_crowd([1, 2, 2, 3], task="t")

    assert created.agent_ids == [1, 2, 3]


@pytest.mark.parametrize(
    ("agent_ids", "message"),
    [
        ([1], "at least two"),
        ([1, 0], "positive"),
        ([1, 99], "not found"),
    ],
)
def test_service_rejects_an_invalid_pool(tmp_path, agent_ids, message):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match=message):
        service.create_crowd(agent_ids, task="t")

    assert service.list_sessions() == []


def test_service_rejects_a_pool_over_the_cap(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="limited to 20"):
        service.create_crowd(list(range(1, 30)), task="t")


def test_service_rejects_invalid_session_options(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="task is required"):
        service.create_crowd([1, 2], task="   ")
    with pytest.raises(ValueError, match="unknown strategy"):
        service.create_crowd([1, 2], task="t", strategy="telepathy")
    with pytest.raises(ValueError, match="rounds must be between"):
        service.create_crowd([1, 2], task="t", rounds=99)
    with pytest.raises(ValueError, match="participants_per_round must be between"):
        service.create_crowd([1, 2], task="t", participants_per_round=99)
    with pytest.raises(ValueError, match="prune must be an object"):
        service.create_crowd([1, 2], task="t", prune="narrow")
    with pytest.raises(ValueError, match="explore_ratio must be between"):
        service.create_crowd([1, 2], task="t", prune={"enabled": True, "keep": 2, "explore_ratio": 4})


def test_service_caps_participants_at_the_pool_size(tmp_path):
    service = _service(tmp_path)

    created = service.create_crowd([1, 2], task="t", participants_per_round=8)

    assert created.participants_per_round == 2


def test_service_defaults_the_keep_count_when_pruning_is_on(tmp_path):
    service = _service(tmp_path)

    created = service.create_crowd([1, 2, 3, 4], task="t", prune={"enabled": True, "keep": 0})

    assert created.prune["keep"] == 4
    assert created.prune["enabled"] is True


def test_pause_resume_and_cancel_move_the_status(tmp_path):
    service = _service(tmp_path)
    created = service.create_crowd([1, 2], task="t")
    session_id = created.id

    assert service.pause(session_id)["status"] == "paused"
    assert service.resume(session_id)["status"] == "running"
    assert service.cancel(session_id)["status"] == "cancelled"

    events = service.events(session_id)
    assert [event["type"] for event in events] == [
        "created",
        "paused",
        "resumed",
        "cancelled",
    ]


def test_events_are_filtered_by_sequence(tmp_path):
    service = _service(tmp_path)
    created = service.create_crowd([1, 2], task="t")

    everything = service.events(created.id)
    tail = service.events(created.id, after=everything[0]["seq"])

    assert len(everything) == 1
    assert tail == []


def test_a_cancelled_session_cannot_be_resumed(tmp_path):
    service = _service(tmp_path)
    created = service.create_crowd([1, 2], task="t")
    service.cancel(created.id)

    with pytest.raises(ValueError, match="invalid session transition"):
        service.resume(created.id)


def test_list_sessions_filters_by_status(tmp_path):
    service = _service(tmp_path)
    first = service.create_crowd([1, 2], task="a")
    second = service.create_crowd([1, 2, 3], task="b")
    service.cancel(second.id)

    queued = service.list_sessions(status="queued")
    cancelled = service.list_sessions(status="cancelled")

    assert [item["id"] for item in queued] == [first.id]
    assert [item["id"] for item in cancelled] == [second.id]


def test_health_reports_malformed_sessions(tmp_path):
    service = _service(tmp_path)
    service.create_crowd([1, 2], task="t")
    broken = tmp_path / "sessions" / "cw_broken"
    broken.mkdir(parents=True)
    (broken / "session.json").write_text("{not json", encoding="utf-8")

    assert service.health()["malformed_sessions"] == ["cw_broken"]
