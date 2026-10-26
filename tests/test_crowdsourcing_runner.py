from __future__ import annotations

import json

import pytest

from gaworld.crowdsourcing.runner import CrowdsourcingRunner
from gaworld.crowdsourcing.service import CrowdsourcingService
from gaworld.crowdsourcing.store import CrowdStore


def _agents(count: int = 8) -> dict[int, dict]:
    return {
        agent_id: {
            "id": agent_id,
            "name": f"居民{agent_id}",
            "capabilities": {"job_label": f"职业{agent_id}", "skills": ["分析"]},
            "growth": {"items": []},
            "private_skills": [],
            "profile_text": "",
        }
        for agent_id in range(1, count + 1)
    }


def _judge_payload(agent_id: int, score: float) -> dict:
    return {
        "scores": [{"agent_id": agent_id, "score": score, "rationale": "理由"}],
        "best_agent_id": agent_id,
    }


def _make_service(tmp_path, llm, **overrides) -> CrowdsourcingService:
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
        "llm": llm,
        "background": False,
    }
    values.update(overrides)
    return CrowdsourcingService(**values)


def _run(service, **kwargs):
    session = service.create_crowd(
        kwargs.pop("agent_ids", [1, 2, 3, 4, 5, 6]),
        task=kwargs.pop("task", "为社区商业街设计夜间照明方案"),
        **kwargs,
    )
    service.run_session(session.id)
    return session.id, service.get_session(session.id), service.rounds(session.id)


def test_a_crowd_session_completes_and_writes_its_trajectory(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_bid":
            return json.dumps({"bid": 0.6, "confidence": 0.7, "reason": "有把握"})
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案，包含三点具体建议。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.8, "rationale": "完整"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _session_id, final, rounds = _run(service, strategy="vote", rounds=2, participants_per_round=3)

    assert final["status"] == "completed"
    assert final["current_round"] == 2
    assert len(rounds) == 2
    assert final["final_answer"]
    assert final["artifacts"][0]["filename"] == "final.md"
    assert final["stats"]["calls"] > 0


def test_the_market_clears_to_the_highest_bidders(tmp_path):
    bids = {1: 0.10, 2: 0.90, 3: 0.50, 4: 0.20, 5: 0.30, 6: 0.40}

    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_bid":
            return json.dumps({"bid": bids[agent_id], "confidence": 0.5, "reason": "r"})
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.5, "rationale": "ok"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, final, rounds = _run(service, strategy="market", rounds=1, participants_per_round=2)

    # Everyone in the pool bids, and the two highest bids get to work.
    assert len(rounds[0]["bids"]) == 6
    assert rounds[0]["selected"] == [2, 3]
    assert rounds[0]["clearing_price"] == pytest.approx(0.50)
    assert final["final_method"] == "market"


def test_the_market_turns_credit_into_the_next_bid(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_bid":
            return json.dumps({"bid": 0.5, "confidence": 0.5, "reason": "r"})
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            # Resident 3 lands well above the round's average; resident 1 below.
            scores = {item: (0.9 if item == 3 else 0.1 if item == 1 else 0.5) for item in ids}
            return json.dumps(
                {
                    "scores": [
                        {"agent_id": item, "score": score, "rationale": "r"} for item, score in scores.items()
                    ],
                    "best_agent_id": 3,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, final, rounds = _run(service, strategy="market", rounds=2, participants_per_round=6)

    adjustments = {row["agent_id"]: row["bid_adjust"] for row in final["leaderboard"]}
    assert adjustments[3] > 0
    assert adjustments[1] < 0
    # The feedback is visible on the bids themselves in the second round.
    second_round_bids = {bid["agent_id"]: bid for bid in rounds[1]["bids"]}
    assert second_round_bids[3]["effective_bid"] > second_round_bids[1]["effective_bid"]


def test_pruning_narrows_the_pool_towards_the_strongest(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            # Resident 3 lands well above the round's average; resident 1 below.
            scores = {item: (0.9 if item == 3 else 0.1 if item == 1 else 0.5) for item in ids}
            return json.dumps(
                {
                    "scores": [
                        {"agent_id": item, "score": score, "rationale": "r"} for item, score in scores.items()
                    ],
                    "best_agent_id": 3,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, _final, rounds = _run(
        service,
        strategy="elite",
        rounds=2,
        participants_per_round=3,
        prune={"enabled": True, "keep": 2, "explore_ratio": 0.0},
    )

    assert len(rounds[0]["selected"]) == 3
    # The weakest resident is gone after the first round, and the strongest
    # one is still in.
    assert 1 not in rounds[1]["survivors"]
    assert 3 in rounds[1]["survivors"]
    assert len(rounds[1]["survivors"]) == 2


def test_pruning_can_be_switched_off(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.5, "rationale": "r"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, _, rounds = _run(
        service,
        strategy="elite",
        rounds=2,
        participants_per_round=3,
        prune={"enabled": False, "keep": 2, "explore_ratio": 0.0},
    )

    assert len(rounds[1]["survivors"]) == 6


def test_pruning_keeps_an_exploration_slot(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.5, "rationale": "r"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, _, rounds = _run(
        service,
        strategy="elite",
        rounds=1,
        participants_per_round=3,
        prune={"enabled": True, "keep": 4, "explore_ratio": 0.25},
    )

    # keep=4 with a quarter of the slots reserved for exploration: three
    # strong residents and one drawn from the rest.
    assert len(rounds[0]["survivors"]) == 4


def test_voting_picks_the_majority_cluster(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            if agent_id in {1, 2, 3}:
                return "社区商业街夜间照明改造：加装地灯，延长照明时段，调整色温。"
            return "另一份完全不同的方案：关于公交线路调整与站点合并的建议。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.7, "rationale": "r"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, _final, rounds = _run(
        service,
        agent_ids=[1, 2, 3, 4],
        strategy="vote",
        rounds=1,
        participants_per_round=4,
    )

    aggregate = rounds[0]["aggregate"]
    assert aggregate["method"] == "vote"
    assert aggregate["cluster"] == 3
    assert aggregate["agreement"] == pytest.approx(0.75)
    assert aggregate["agent_id"] in {1, 2, 3}


def test_the_debate_strategy_critiques_and_decides(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案正文，包含可行性与成本说明。"
        if task == "crowdsourcing_critique":
            return "对方的方案没有考虑夜间噪声。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.6, "rationale": "r"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        if task == "crowdsourcing_final":
            return json.dumps(
                {
                    "best_agent_id": 2,
                    "score": 0.85,
                    "rationale": "更完整",
                    "final_answer": "最终成果：兼顾成本与噪声的夜间照明方案。",
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, final, rounds = _run(service, strategy="debate", rounds=1, participants_per_round=3)

    assert len(rounds[0]["critiques"]) == 2
    assert rounds[0]["final"]["best_agent_id"] == 2
    assert final["final_answer"] == "最终成果：兼顾成本与噪声的夜间照明方案。"
    assert final["final_method"] == "debate"


def test_a_failed_judge_falls_back_to_agreement_and_says_so(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            raise RuntimeError("judge is down")
        return "{}"

    service = _make_service(tmp_path, llm)
    _, final, rounds = _run(service, strategy="vote", rounds=1, participants_per_round=3)

    assert final["stats"]["judge_fallback"] is True
    assert rounds[0]["judged"] is False
    assert all(score["score"] for score in rounds[0]["scores"])


def test_a_failed_attempt_does_not_take_the_round_down(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt" and agent_id == 2:
            raise RuntimeError("this resident is unreachable")
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.5, "rationale": "r"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    # The pool is exactly as large as the round's participant count: the
    # ``vote`` strategy draws a rotating sample, and its draw is seeded
    # from the session id, so a bigger pool would leave resident 2 out of
    # the round about half the time.
    _, final, rounds = _run(
        service,
        agent_ids=[1, 2, 3],
        strategy="vote",
        rounds=1,
        participants_per_round=3,
    )

    assert final["status"] == "completed"
    failed = [item for item in rounds[0]["attempts"] if item.get("error")]
    assert len(failed) == 1
    assert failed[0]["agent_id"] == 2


def test_a_cancelled_session_stops_running(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        return "{}"

    service = _make_service(tmp_path, llm)
    session = service.create_crowd([1, 2, 3], task="t", strategy="vote", rounds=3)
    service.cancel(session.id)

    service.run_session(session.id)

    assert service.get_session(session.id)["status"] == "cancelled"
    assert service.rounds(session.id) == []


def test_the_leaderboard_marks_the_eliminated(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            scores = {item: (0.9 if item == 3 else 0.1 if item == 1 else 0.5) for item in ids}
            return json.dumps(
                {
                    "scores": [
                        {"agent_id": item, "score": score, "rationale": "r"} for item, score in scores.items()
                    ],
                    "best_agent_id": 3,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, final, _ = _run(
        service,
        strategy="elite",
        rounds=2,
        participants_per_round=3,
        prune={"enabled": True, "keep": 2, "explore_ratio": 0.0},
    )

    rows = {row["agent_id"]: row for row in final["leaderboard"]}
    assert rows[3]["eliminated"] is False
    assert rows[1]["eliminated"] is True
    assert final["leaderboard"][0]["rank"] == 1
    assert final["leaderboard"][0]["agent_id"] == 3


def test_only_the_bid_strategy_reports_a_bid_adjustment(tmp_path):
    def llm(prompt, task=None, agent_id=None):
        if task == "crowdsourcing_attempt":
            return f"居民{agent_id}的方案。"
        if task == "crowdsourcing_judge":
            payload = json.loads(prompt)
            ids = [item["agent_id"] for item in payload["candidates"]]
            return json.dumps(
                {
                    "scores": [{"agent_id": item, "score": 0.5, "rationale": "r"} for item in ids],
                    "best_agent_id": ids[0] if ids else None,
                }
            )
        return "{}"

    service = _make_service(tmp_path, llm)
    _, vote_final, _ = _run(service, strategy="vote", rounds=1, participants_per_round=3)
    _, market_final, _ = _run(service, strategy="market", rounds=1, participants_per_round=3)

    assert all("bid_adjust" not in row for row in vote_final["leaderboard"])
    assert all("bid_adjust" in row for row in market_final["leaderboard"])


def test_the_runner_refuses_a_session_that_is_not_runnable(tmp_path):
    store = CrowdStore(tmp_path / "sessions")
    runner = CrowdsourcingRunner(
        store=store,
        agent_loader=lambda agent_id: None,
        llm=lambda *args, **kwargs: "{}",
    )

    with pytest.raises(KeyError):
        runner.run("cw_missing")
