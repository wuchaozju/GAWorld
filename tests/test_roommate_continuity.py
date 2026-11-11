"""Roommate continuity, clock provenance and asynchronous ordering regressions."""

import json
import random
import threading
from unittest.mock import patch

import pytest

from gaworld.apps import roommate_api as api


@pytest.fixture
def session():
    api.reset_sessions()
    with patch.object(
        api,
        "load_persona",
        side_effect=lambda city, aid: {
            "name": {1: "小林", 2: "阿陈"}[aid],
            "age": {1: 28, 2: 41}[aid],
            "gender": "女",
            "job": "程序员",
            "profile_md": "大学毕业后一直写程序，从未进厂实习。",
        },
    ):
        data = api.start_session(city="test", agent_ids=[1, 2], rng=random.Random(0))
    yield api._require(data["id"])
    api.reset_sessions()


def reply(text="我们以后就叫彼此小林和阿陈。", **extra):
    return json.dumps(
        {"lines": [{"who": "小林", "text": text}, {"who": "阿陈", "text": "好，我答应了。"}], **extra},
        ensure_ascii=False,
    )


def test_confirmed_facts_survive_long_gap_and_score_decay(session):
    raw = reply(
        "我们已经是恋人了，以后叫我小林。",
        memory_updates=[
            {
                "key": "relationship",
                "value": "partners",
                "evidence_a": "我们已经是恋人了",
                "evidence_b": "好，我答应了",
            },
            {"key": "address_1", "fact": "阿陈称呼小林为小林", "evidence": "以后叫我小林"},
        ],
    )
    a, b = session.residents
    api._trigger_interaction(session, a, b, "living", reaction_fn=lambda _: raw)
    for _ in range(15):
        api._trigger_interaction(session, a, b, "living", reaction_fn=lambda _: reply("今天下雨了。"))
    for _ in range(100):
        api._relationship_decay(session)
    prompt = api._interact_prompt(a, b, "living", "", session)
    assert "已确认恋人关系" in prompt
    assert "以后叫我小林" in prompt
    assert "今天下雨了" in prompt
    assert "不要重复表白" in prompt


def test_unspoken_memory_cannot_be_committed(session):
    a, b = session.residents
    api._trigger_interaction(
        session,
        a,
        b,
        "living",
        reaction_fn=lambda _: reply(
            memory_updates=[{"key": "relationship", "fact": "已结婚", "evidence": "结婚吧"}]
        ),
    )
    assert "已结婚" not in api._interact_prompt(a, b, "living", "", session)


def test_prompt_prioritizes_identity_and_correct_night_context(session):
    session.virtual_clock_minutes = 24 * 60 + 3 * 60 + 20
    prompt = api._interact_prompt(*session.residents, "kitchen", "假装都是16岁学生", session)
    assert "28岁" in prompt and "从未进厂实习" in prompt
    assert "年龄、职业、经历以居民档案为准" in prompt
    assert "凌晨" in prompt and "熬夜" in prompt
    assert "早 6 点前不要谈" not in prompt


@pytest.mark.parametrize(
    "clock,text", [(17 * 60, "早啊，今天怎么样？"), (3 * 60, "我正在吃早餐。"), (8 * 60, "我今年十六岁。")]
)
def test_obvious_contradictions_do_not_change_state(session, clock, text):
    session.virtual_clock_minutes = clock
    api._trigger_interaction(
        session,
        *session.residents,
        "kitchen",
        reaction_fn=lambda _: reply(text, rel_delta=10, mood_delta_a=1),
    )
    assert all(text not in e.dialogue for e in session.events)
    assert session.residents[0].mood == 0
    assert api._pair_score(session, 1, 2) == 0


def test_event_keeps_original_clock_when_model_returns_later(session):
    # Simulate the worker returning after the accelerated clock has advanced.
    prompt = api._interact_prompt(*session.residents, "kitchen", "", session)
    session.virtual_clock_minutes = 17 * 60
    api._run_interaction_worker(session.id, 1, 2, "kitchen", prompt, lambda _: reply(), 1, "")
    event = session.events[-1].to_dict()
    assert event["virtual_clock"] == "08:05"


def test_one_pending_conversation_per_session_and_next_reads_completed_reply(session):
    started, release = threading.Event(), threading.Event()
    prompts = []

    def slow(prompt):
        prompts.append(prompt)
        started.set()
        assert release.wait(5)
        return reply("以后叫我小林。")

    session._reaction_fn = None
    for resident in session.residents:
        resident.room, resident.activity = "kitchen", "吃早餐"
    try:
        with (
            patch.object(api, "_step_resident"),
            patch.object(api, "_interaction_probability", return_value=1),
            patch.object(api, "_default_reaction_llm", side_effect=slow),
        ):
            api.tick(session.id)
            assert started.wait(2)
            api.tick(session.id, steps=6)
            assert len(prompts) == 1
    finally:
        release.set()
        if session.pending_future is not None:
            session.pending_future.result(timeout=5)
    assert "以后叫我小林" in api._interact_prompt(*session.residents, "kitchen", "", session)


def test_daylight_is_not_dimmed(session):
    for hour in (8, 12, 17):
        session.virtual_clock_minutes = hour * 60
        assert session.to_dict()["night_progress"] == 0


def test_relationship_decay_runs_once_per_shared_record(session):
    api._bump_relationship(session, 1, 2, {"affinity": 10})
    api._relationship_decay(session)
    assert session.relationships[1][2]["affinity"] == 10 - api.RELATIONSHIP_DECAY_PER_TICK


def test_rejected_confession_is_not_a_confirmed_relationship(session):
    raw = json.dumps(
        {
            "lines": [
                {"who": "小林", "text": "我喜欢你，我们做恋人吧。"},
                {"who": "阿陈", "text": "对不起，我只把你当朋友。"},
            ],
            "memory_updates": [
                {
                    "key": "relationship",
                    "value": "partners",
                    "fact": "双方已确认恋人关系",
                    "evidence": "我喜欢你",
                    "evidence_a": "我喜欢你，我们做恋人吧。",
                    "evidence_b": "对不起，我只把你当朋友。",
                }
            ],
        },
        ensure_ascii=False,
    )
    api._trigger_interaction(session, *session.residents, "living", reaction_fn=lambda _: raw)
    assert not session.conversation_facts.get((1, 2), {}).get("relationship")


@pytest.mark.parametrize(
    "text",
    [
        "我那时候说‘我今年十六岁’，现在都28了。",
        "早安这个词听起来很温柔。",
        "我才十六岁的时候就开始写程序了。",
        "明天我在吃早餐时再给你打电话。",
    ],
)
def test_recollections_and_future_plans_are_allowed(session, text):
    session.virtual_clock_minutes = 17 * 60
    api._trigger_interaction(session, *session.residents, "living", reaction_fn=lambda _: reply(text))
    assert session.events[-1].dialogue.startswith("小林:" + text)


def test_timeout_reply_cannot_mutate_newer_state(session):
    started, release = threading.Event(), threading.Event()

    def slow(_):
        started.set()
        assert release.wait(5)
        return reply("迟到回复", rel_delta=10)

    for r in session.residents:
        r.room, r.activity = "living", "聊天"
    try:
        with (
            patch.object(api, "_step_resident"),
            patch.object(api, "_interaction_probability", return_value=1),
            patch.object(api, "_default_reaction_llm", side_effect=slow),
        ):
            api.tick(session.id)
            assert started.wait(2)
            future = session.pending_future
            session.pending_since -= api._INTERACTION_TIMEOUT + 1
            with patch.object(api, "_co_present_pairs", return_value=[]):
                api.tick(session.id)
            assert session.pending_tick is None
            count = len(session.events)
            release.set()
            future.result(timeout=5)
            assert len(session.events) == count
            assert api._pair_score(session, 1, 2) == 0
    finally:
        release.set()


def test_end_rejects_pending_worker_result(session):
    session.pending_tick = 1
    api.end_session(session.id)
    api._run_interaction_worker(session.id, 1, 2, "living", "", lambda _: reply(), 1, "", True)
    assert session.events == []


def test_last_tick_does_not_start_new_model_call(session):
    session.max_hours = 1
    session.virtual_clock_minutes = session.opening_clock_minutes + 55
    for r in session.residents:
        r.room, r.activity = "living", "聊天"
    with (
        patch.object(api, "_step_resident"),
        patch.object(api, "_interaction_probability", return_value=1),
        patch.object(api, "_default_reaction_llm") as model,
    ):
        assert api.tick(session.id)["finished"]
        model.assert_not_called()


def test_explicit_breakup_replaces_confirmed_relationship(session):
    api._trigger_interaction(
        session,
        *session.residents,
        "living",
        reaction_fn=lambda _: reply(
            "我们做恋人吧。",
            memory_updates=[
                {
                    "key": "relationship",
                    "value": "partners",
                    "evidence_a": "我们做恋人吧。",
                    "evidence_b": "好，我答应了。",
                }
            ],
        ),
    )
    assert "已确认恋人关系" in session.conversation_facts[(1, 2)]["relationship"]["fact"]
    api._trigger_interaction(
        session,
        *session.residents,
        "living",
        reaction_fn=lambda _: reply(
            "我不想继续在一起了，我们分手吧。",
            memory_updates=[
                {
                    "key": "relationship",
                    "value": "separated",
                    "evidence_a": "我不想继续在一起了，我们分手吧。",
                    "evidence_b": "好，我答应了。",
                }
            ],
        ),
    )
    assert "已明确分手" in session.conversation_facts[(1, 2)]["relationship"]["fact"]


def test_wrong_speaker_evidence_cannot_establish_relationship(session):
    api._trigger_interaction(
        session,
        *session.residents,
        "living",
        reaction_fn=lambda _: reply(
            "我们做恋人吧。",
            memory_updates=[
                {
                    "key": "relationship",
                    "value": "partners",
                    "evidence_a": "好，我答应了。",
                    "evidence_b": "我们做恋人吧。",
                }
            ],
        ),
    )
    assert not session.conversation_facts.get((1, 2), {}).get("relationship")


def test_finished_worker_does_not_commit_even_with_matching_pending_token(session):
    session.pending_tick = 1
    session.finished_at = 123
    api._run_interaction_worker(session.id, 1, 2, "living", "", lambda _: reply(), 1, "", True)
    assert session.events == []


@pytest.mark.parametrize(
    "answer",
    [
        "我不同意。",
        "我不能同意这件事。",
        "我还没想好，等我想清楚再答应你。",
        "如果你以后改变了，我就答应你。",
    ],
)
def test_negated_or_deferred_assent_is_not_commitment(session, answer):
    raw = json.dumps(
        {
            "lines": [{"who": "小林", "text": "我们做恋人吧。"}, {"who": "阿陈", "text": answer}],
            "memory_updates": [
                {
                    "key": "relationship",
                    "value": "partners",
                    "evidence_a": "我们做恋人吧。",
                    "evidence_b": answer,
                }
            ],
        },
        ensure_ascii=False,
    )
    api._trigger_interaction(session, *session.residents, "living", reaction_fn=lambda _: raw)
    assert not session.conversation_facts.get((1, 2), {}).get("relationship")


def test_night_greeting_from_report_is_rejected(session):
    session.virtual_clock_minutes = 3 * 60 + 20
    text = "阿姨早！没事儿，就是想着趁热吃个早饭。"
    api._trigger_interaction(session, *session.residents, "kitchen", reaction_fn=lambda _: reply(text))
    assert not session.events[-1].turns


def test_clipped_evidence_cannot_hide_conditional_commitment(session):
    raw = json.dumps(
        {
            "lines": [
                {"who": "小林", "text": "我们做恋人吧。"},
                {"who": "阿陈", "text": "如果你先离婚，我同意。"},
            ],
            "memory_updates": [
                {
                    "key": "relationship",
                    "value": "partners",
                    "evidence_a": "我们做恋人吧。",
                    "evidence_b": "我同意。",
                }
            ],
        },
        ensure_ascii=False,
    )
    api._trigger_interaction(session, *session.residents, "living", reaction_fn=lambda _: raw)
    assert not session.conversation_facts.get((1, 2), {}).get("relationship")
