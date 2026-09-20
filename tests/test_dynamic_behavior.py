"""Tests for the dynamic behavior system.

Covers:
- Activity commitment levels
- InterruptCandidate construction
- Interrupt evaluation (priority vs commitment)
- Spontaneous urge generation (mood-classified)
- Need-based interrupts (hunger, fatigue, time pressure)
- Inbox / social-message interrupts
- Co-located agent detection
- Social encounter generation
- Environment event classification and response
- Event cascade chains
- Schedule insertion with resumable support
- Full evaluate_step_dynamics pipeline
- Bridge API (dynamic_transient_thought)
"""

import random
import unittest

from gaworld.behavior.dynamic import (
    COMMITMENT_KEYWORDS,
    EVENT_CASCADES,
    SPONTANEOUS_POOLS,
    InterruptCandidate,
    activity_commitment,
    detect_co_located_agents,
    dynamic_transient_thought,
    evaluate_interrupts,
    evaluate_step_dynamics,
    generate_cascade_interrupts,
    generate_environment_interrupts,
    generate_inbox_interrupts,
    generate_need_interrupts,
    generate_social_interrupts,
    generate_spontaneous_urge,
    insert_activity_into_schedule,
)


def _agent(**overrides):
    base = {
        "id": 1,
        "name": "测试员",
        "personality": "外向开朗",
        "values": "社交",
        "daily_life": "朝九晚五",
        "job": "程序员",
        "state": {
            "energy": 0.7,
            "emotion": 0.5,
            "stress": 0.3,
            "mood": 0.5,
            "social_need": 0.5,
            "hunger": 0.3,
            "fatigue_debt": 0.2,
            "self_control": 0.6,
            "time_pressure": 0.25,
            "risk_preference": 0.5,
        },
        "locations": {"current": "Central Block"},
        "relationships": {},
    }
    for k, v in overrides.items():
        if k == "state" and isinstance(v, dict):
            base["state"].update(v)
        else:
            base[k] = v
    return base


# =========================================================================
# Activity Commitment
# =========================================================================
class TestActivityCommitment(unittest.TestCase):

    def test_high_commitment_exam(self):
        self.assertGreaterEqual(activity_commitment("考试"), 0.90)

    def test_high_commitment_surgery(self):
        self.assertGreaterEqual(activity_commitment("手术"), 0.90)

    def test_medium_commitment_work(self):
        c = activity_commitment("工作")
        self.assertGreaterEqual(c, 0.55)
        self.assertLessEqual(c, 0.80)

    def test_low_commitment_browse(self):
        self.assertLessEqual(activity_commitment("刷手机"), 0.20)

    def test_default_for_unknown(self):
        c = activity_commitment("做一件神秘的事")
        self.assertGreater(c, 0.0)
        self.assertLess(c, 1.0)

    def test_commitment_ordering(self):
        high = activity_commitment("面试")
        mid = activity_commitment("做饭")
        low = activity_commitment("散步")
        self.assertGreater(high, mid)
        self.assertGreater(mid, low)


# =========================================================================
# InterruptCandidate
# =========================================================================
class TestInterruptCandidate(unittest.TestCase):

    def test_construction(self):
        ic = InterruptCandidate("test", "kind", "活动", "原因", 0.5, 20)
        self.assertEqual(ic.source, "test")
        self.assertEqual(ic.priority, 0.5)
        self.assertTrue(ic.resumable)
        self.assertEqual(ic.mood_delta, 0.0)

    def test_priority_clipping(self):
        ic = InterruptCandidate("t", "k", "a", "r", 1.5, 10)
        self.assertEqual(ic.priority, 1.0)
        ic2 = InterruptCandidate("t", "k", "a", "r", -0.5, 10)
        self.assertEqual(ic2.priority, 0.0)

    def test_min_duration(self):
        ic = InterruptCandidate("t", "k", "a", "r", 0.5, 1)
        self.assertGreaterEqual(ic.duration_minutes, 5)

    def test_to_dict(self):
        ic = InterruptCandidate("env", "weather", "避雨", "下雨", 0.6, 15,
                                mood_delta=-0.05, extra={"severity": 0.7})
        d = ic.to_dict()
        self.assertEqual(d["source"], "env")
        self.assertEqual(d["extra"]["severity"], 0.7)
        self.assertAlmostEqual(d["mood_delta"], -0.05, places=3)


# =========================================================================
# Interrupt Evaluation
# =========================================================================
class TestEvaluateInterrupts(unittest.TestCase):

    def test_empty_candidates(self):
        self.assertIsNone(evaluate_interrupts([], "工作", _agent()))

    def test_high_priority_beats_commitment(self):
        """A very high-priority interrupt should beat even moderate work."""
        random.seed(42)
        cands = [InterruptCandidate("env", "emergency", "撤离", "火灾", 0.95, 30)]
        winner = evaluate_interrupts(cands, "散步", _agent())
        # With 散步 (low commitment) and 0.95 priority, should almost always win
        self.assertIsNotNone(winner)
        self.assertEqual(winner.activity, "撤离")

    def test_low_priority_rejected_by_high_commitment(self):
        """A low-priority interrupt should fail against high-commitment activity."""
        random.seed(42)
        rejected_count = 0
        for seed in range(50):
            random.seed(seed)
            cands = [InterruptCandidate("social", "chat", "聊天", "偶遇", 0.20, 10)]
            winner = evaluate_interrupts(cands, "考试", _agent())
            if winner is None:
                rejected_count += 1
        # Should be rejected most of the time
        self.assertGreater(rejected_count, 35)

    def test_best_of_multiple_candidates(self):
        random.seed(42)
        cands = [
            InterruptCandidate("env", "weather", "避雨", "暴雨", 0.85, 20),
            InterruptCandidate("social", "chat", "聊天", "偶遇", 0.25, 10),
        ]
        winner = evaluate_interrupts(cands, "散步", _agent())
        if winner:
            self.assertEqual(winner.activity, "避雨")

    def test_social_need_boosts_social_interrupts(self):
        random.seed(42)
        agent_lonely = _agent(state={"social_need": 0.9})
        cands = [InterruptCandidate("social", "encounter", "聊天", "偶遇", 0.40, 15)]
        wins = sum(1 for s in range(50)
                   if (random.seed(s), evaluate_interrupts(cands, "散步", agent_lonely))[1] is not None)
        agent_social = _agent(state={"social_need": 0.2})
        wins2 = sum(1 for s in range(50)
                    if (random.seed(s), evaluate_interrupts(cands, "散步", agent_social))[1] is not None)
        self.assertGreaterEqual(wins, wins2)


# =========================================================================
# Spontaneous Urge Generation
# =========================================================================
class TestSpontaneousUrge(unittest.TestCase):

    def test_stressed_agent_gets_urge(self):
        """Highly stressed agent should sometimes generate an urge."""
        agent = _agent(state={"stress": 0.85, "energy": 0.5, "emotion": 0.3, "self_control": 0.3})
        got_urge = False
        for seed in range(50):
            random.seed(seed)
            urge = generate_spontaneous_urge(agent, "14:00", "工作")
            if urge is not None:
                got_urge = True
                self.assertEqual(urge.source, "spontaneous")
                self.assertIn("mood_", urge.kind)
                break
        self.assertTrue(got_urge, "Stressed agent should generate at least one urge in 50 tries")

    def test_time_blocking(self):
        """Shopping urges should be blocked at 23:00."""
        agent = _agent(state={"stress": 0.8, "emotion": 0.8, "self_control": 0.2})
        for seed in range(100):
            random.seed(seed)
            urge = generate_spontaneous_urge(agent, "23:30", "休息")
            if urge:
                self.assertNotIn(urge.activity, ["逛街购物", "约朋友出去", "唱歌", "去咖啡店"])

    def test_no_urge_for_same_activity(self):
        """Should not suggest the exact same activity the agent is doing."""
        for seed in range(100):
            random.seed(seed)
            urge = generate_spontaneous_urge(_agent(), "14:00", "刷手机")
            if urge:
                self.assertNotEqual(urge.activity, "刷手机")

    def test_all_mood_pools_have_entries(self):
        for mood in ["happy", "stressed", "tired", "bored", "anxious", "lonely"]:
            self.assertIn(mood, SPONTANEOUS_POOLS)
            self.assertGreater(len(SPONTANEOUS_POOLS[mood]), 0)


# =========================================================================
# Need-Based Interrupts
# =========================================================================
class TestNeedInterrupts(unittest.TestCase):

    def test_hungry_agent(self):
        agent = _agent(state={"hunger": 0.75})
        cands = generate_need_interrupts(agent, "12:30")
        hunger_cands = [c for c in cands if c.kind == "hunger"]
        self.assertEqual(len(hunger_cands), 1)
        self.assertEqual(hunger_cands[0].activity, "找点吃的")

    def test_not_hungry(self):
        agent = _agent(state={"hunger": 0.3})
        cands = generate_need_interrupts(agent, "12:30")
        hunger_cands = [c for c in cands if c.kind == "hunger"]
        self.assertEqual(len(hunger_cands), 0)

    def test_fatigued_agent(self):
        agent = _agent(state={"energy": 0.2, "fatigue_debt": 0.7})
        cands = generate_need_interrupts(agent, "15:00")
        recovery = [c for c in cands if c.kind == "recovery"]
        self.assertEqual(len(recovery), 1)

    def test_time_pressure(self):
        agent = _agent(state={"time_pressure": 0.8})
        cands = generate_need_interrupts(agent, "10:00")
        tp = [c for c in cands if c.kind == "time_pressure"]
        self.assertEqual(len(tp), 1)
        self.assertEqual(tp[0].activity, "处理待办")

    def test_meal_time_bonus(self):
        agent = _agent(state={"hunger": 0.65})
        cands_meal = generate_need_interrupts(agent, "12:00")
        cands_off = generate_need_interrupts(agent, "15:00")
        meal_pri = [c for c in cands_meal if c.kind == "hunger"]
        off_pri = [c for c in cands_off if c.kind == "hunger"]
        if meal_pri and off_pri:
            self.assertGreater(meal_pri[0].priority, off_pri[0].priority)


# =========================================================================
# Inbox / Social Message Interrupts
# =========================================================================
class TestInboxInterrupts(unittest.TestCase):

    def test_inbox_with_messages(self):
        cands = generate_inbox_interrupts(
            _agent(), inbox_messages=[{"from": "张三", "text": "你好"}])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].kind, "inbox_message")

    def test_social_context_trigger(self):
        cands = generate_inbox_interrupts(
            _agent(), social_context="李四@你 想约吃饭")
        self.assertEqual(len(cands), 1)

    def test_no_trigger(self):
        cands = generate_inbox_interrupts(
            _agent(), social_context="天气晴朗")
        self.assertEqual(len(cands), 0)

    def test_high_social_need_higher_priority(self):
        cands_high = generate_inbox_interrupts(
            _agent(state={"social_need": 0.9}),
            inbox_messages=[{"from": "x"}])
        cands_low = generate_inbox_interrupts(
            _agent(state={"social_need": 0.2}),
            inbox_messages=[{"from": "x"}])
        self.assertGreater(cands_high[0].priority, cands_low[0].priority)


# =========================================================================
# Co-Located Agent Detection
# =========================================================================
class TestCoLocatedAgents(unittest.TestCase):

    def test_same_location(self):
        agents = [
            {"id": 1, "locations": {"current": "Park"}},
            {"id": 2, "locations": {"current": "Park"}},
            {"id": 3, "locations": {"current": "Office"}},
        ]
        by_id = {a["id"]: a for a in agents}
        co = detect_co_located_agents(agents[0], agents, by_id)
        self.assertEqual(len(co), 1)
        self.assertEqual(co[0]["id"], 2)

    def test_no_co_located(self):
        agents = [
            {"id": 1, "locations": {"current": "A"}},
            {"id": 2, "locations": {"current": "B"}},
        ]
        by_id = {a["id"]: a for a in agents}
        co = detect_co_located_agents(agents[0], agents, by_id)
        self.assertEqual(len(co), 0)

    def test_in_transit_excluded(self):
        agents = [
            {"id": 1, "locations": {"current": "Park"}},
            {"id": 2, "locations": {"current": "Park", "in_transit": True}},
        ]
        by_id = {a["id"]: a for a in agents}
        co = detect_co_located_agents(agents[0], agents, by_id)
        self.assertEqual(len(co), 0)

    def test_empty_location(self):
        agents = [
            {"id": 1, "locations": {"current": ""}},
            {"id": 2, "locations": {"current": ""}},
        ]
        by_id = {a["id"]: a for a in agents}
        co = detect_co_located_agents(agents[0], agents, by_id)
        self.assertEqual(len(co), 0)


# =========================================================================
# Social Encounter Generation
# =========================================================================
class TestSocialInterrupts(unittest.TestCase):

    def test_close_friend_encounter(self):
        random.seed(42)
        agent = _agent(state={"social_need": 0.8})
        agent["relationships"] = {"2": {"closeness": 0.8}}
        other = {"id": 2, "name": "好友", "_current_activity": "散步"}
        cands = generate_social_interrupts(agent, [other], "12:30")
        # With high closeness and social need, should sometimes produce candidates
        if cands:
            self.assertEqual(cands[0].source, "social")
            self.assertIn("好友", cands[0].activity)

    def test_stranger_contagion(self):
        random.seed(42)
        agent = _agent()
        other = {"id": 2, "name": "路人", "_current_activity": "排队买奶茶"}
        # Run multiple seeds to find a contagion event
        for seed in range(100):
            random.seed(seed)
            cands = generate_social_interrupts(agent, [other], "14:00")
            contagion = [c for c in cands if c.kind == "contagion"]
            if contagion:
                self.assertIn("排队", contagion[0].activity)
                break

    def test_empty_co_located(self):
        cands = generate_social_interrupts(_agent(), [], "12:00")
        self.assertEqual(len(cands), 0)


# =========================================================================
# Environment Event Response
# =========================================================================
class TestEnvironmentInterrupts(unittest.TestCase):

    def test_rain_event(self):
        agent = _agent()
        events = [{"type": "weather", "description": "开始下雨", "severity": 0.5}]
        cands = generate_environment_interrupts(agent, events)
        self.assertGreater(len(cands), 0)
        self.assertEqual(cands[0].extra["event_type"], "weather")

    def test_emergency_event_high_priority(self):
        agent = _agent()
        events = [{"type": "emergency", "description": "发生地震", "severity": 0.9}]
        cands = generate_environment_interrupts(agent, events)
        self.assertGreater(len(cands), 0)
        self.assertGreater(cands[0].priority, 0.7)
        self.assertFalse(cands[0].resumable)

    def test_commercial_event(self):
        agent = _agent(personality="好奇 探索")
        events = [{"type": "commercial", "description": "附近新开了一家奶茶店", "severity": 0.2}]
        cands = generate_environment_interrupts(agent, events)
        self.assertGreater(len(cands), 0)

    def test_empty_events(self):
        cands = generate_environment_interrupts(_agent(), [])
        self.assertEqual(len(cands), 0)

    def test_personality_modifier_cautious(self):
        cautious = _agent(personality="谨慎 保守")
        bold = _agent(personality="大胆 冒险")
        events = [{"type": "weather", "description": "暴风预警", "severity": 0.6}]
        c_cautious = generate_environment_interrupts(cautious, events)
        c_bold = generate_environment_interrupts(bold, events)
        if c_cautious and c_bold:
            self.assertGreater(c_cautious[0].priority, c_bold[0].priority)


# =========================================================================
# Event Cascade Chains
# =========================================================================
class TestCascadeChains(unittest.TestCase):

    def test_rain_cascade(self):
        random.seed(42)
        rain = InterruptCandidate("env", "weather_rain", "避雨", "雨",
                                  0.55, 15, extra={"event_type": "weather", "sub_type": "rain"})
        cascades = generate_cascade_interrupts(rain, _agent())
        # Should sometimes produce cascades
        for seed in range(20):
            random.seed(seed)
            cascades = generate_cascade_interrupts(rain, _agent())
            if cascades:
                self.assertEqual(cascades[0].kind, "cascade")
                self.assertLess(cascades[0].priority, rain.priority)
                break

    def test_no_cascade_for_unknown_event(self):
        ic = InterruptCandidate("env", "x", "a", "r", 0.5, 10,
                                extra={"event_type": "unknown", "sub_type": "x"})
        cascades = generate_cascade_interrupts(ic, _agent())
        self.assertEqual(len(cascades), 0)

    def test_cascade_keys_exist(self):
        self.assertIn("weather_rain", EVENT_CASCADES)
        self.assertIn("weather_storm", EVENT_CASCADES)
        self.assertIn("traffic_congestion", EVENT_CASCADES)


# =========================================================================
# Schedule Insertion
# =========================================================================
class TestScheduleInsertion(unittest.TestCase):

    def test_basic_insert(self):
        schedule = [("08:00", "工作"), ("10:00", "休息"), ("10:30", "工作")]
        result = insert_activity_into_schedule(schedule, "09:00", "接电话", 20,
                                               resumable=True, original_activity="工作")
        times = [t for t, _ in result]
        self.assertIn("09:00", times)
        self.assertIn("09:20", times)

    def test_insert_at_end(self):
        schedule = [("08:00", "工作"), ("10:00", "休息")]
        result = insert_activity_into_schedule(schedule, "11:00", "散步", 30)
        self.assertEqual(result[-1], ("11:00", "散步"))

    def test_insert_preserves_order(self):
        schedule = [("08:00", "A"), ("10:00", "B"), ("12:00", "C")]
        result = insert_activity_into_schedule(schedule, "09:00", "X", 30)
        times = [t for t, _ in result]
        for i in range(len(times) - 1):
            self.assertLessEqual(times[i], times[i + 1])

    def test_no_insert_invalid_time(self):
        schedule = [("08:00", "工作")]
        result = insert_activity_into_schedule(schedule, "invalid", "X", 30)
        self.assertEqual(result, schedule)


# =========================================================================
# Full Pipeline: evaluate_step_dynamics
# =========================================================================
class TestEvaluateStepDynamics(unittest.TestCase):

    def test_no_change_when_disabled(self):
        result = evaluate_step_dynamics(
            _agent(), "14:00", "工作",
            env_events=[], all_agents=[], agents_by_id={},
            config={"dynamic_behavior": {"enabled": False}},
        )
        self.assertFalse(result["changed"])
        self.assertEqual(result["activity"], "工作")

    def test_returns_required_keys(self):
        result = evaluate_step_dynamics(
            _agent(), "14:00", "工作",
            env_events=[], all_agents=[_agent()], agents_by_id={1: _agent()},
        )
        for key in ["activity", "changed", "reason", "interrupt",
                     "social_encounters", "mood_delta", "schedule_insert",
                     "all_candidates", "cascade_events"]:
            self.assertIn(key, result)

    def test_emergency_triggers_change(self):
        random.seed(42)
        agent = _agent()
        result = evaluate_step_dynamics(
            agent, "14:00", "散步",
            env_events=[{"type": "emergency", "description": "发生火灾", "severity": 0.95}],
            all_agents=[agent], agents_by_id={1: agent},
        )
        # Emergency should almost always trigger
        self.assertTrue(result["changed"])

    def test_social_encounters_populated(self):
        random.seed(42)
        agent1 = _agent()
        agent1["relationships"] = {"2": {"closeness": 0.9}}
        agent2 = {"id": 2, "name": "好友", "locations": {"current": "Central Block"},
                  "_current_activity": "散步", "state": {"energy": 0.8}}
        all_agents = [agent1, agent2]
        by_id = {1: agent1, 2: agent2}
        # Run several seeds to check encounters are generated
        found_encounter = False
        for seed in range(30):
            random.seed(seed)
            result = evaluate_step_dynamics(
                agent1, "12:30", "散步",
                env_events=[], all_agents=all_agents, agents_by_id=by_id,
            )
            if result["social_encounters"]:
                found_encounter = True
                break
        self.assertTrue(found_encounter)

    def test_need_based_with_hunger(self):
        random.seed(42)
        agent = _agent(state={"hunger": 0.8, "energy": 0.3, "self_control": 0.3})
        # Run several seeds — hunger+fatigue should sometimes win
        changed_count = 0
        for seed in range(30):
            random.seed(seed)
            result = evaluate_step_dynamics(
                agent, "12:30", "散步",
                env_events=[], all_agents=[agent], agents_by_id={1: agent},
            )
            if result["changed"]:
                changed_count += 1
        self.assertGreater(changed_count, 0)


# =========================================================================
# Bridge API: dynamic_transient_thought
# =========================================================================
class TestBridgeAPI(unittest.TestCase):

    def test_empty_result_when_no_change(self):
        random.seed(42)
        agent = _agent(state={"self_control": 0.9, "stress": 0.1, "emotion": 0.8})
        result = dynamic_transient_thought(
            agent, "14:00", "考试",
            all_agents=[agent], agents_by_id={1: agent},
        )
        # For a high-commitment exam with calm agent, usually no change
        # Result should be empty dict or have dynamic_result with changed=False
        if result:
            dr = result.get("dynamic_result", {})
            if dr:
                self.assertFalse(dr.get("changed", False))

    def test_bridge_returns_legacy_format(self):
        random.seed(42)
        agent = _agent(state={"stress": 0.8, "energy": 0.3, "self_control": 0.2})
        result = dynamic_transient_thought(
            agent, "14:00", "散步",
            env_events=[{"type": "weather", "description": "暴风", "severity": 0.8}],
            all_agents=[agent], agents_by_id={1: agent},
        )
        if result:
            # Should have legacy keys
            for key in ["source", "kind", "time", "scheduled_activity"]:
                self.assertIn(key, result)
            self.assertIn("dynamic_result", result)

    def test_bridge_with_inbox(self):
        random.seed(42)
        agent = _agent(state={"social_need": 0.8})
        result = dynamic_transient_thought(
            agent, "14:00", "工作",
            inbox_messages=[{"from": "同事", "text": "急事"}],
            all_agents=[agent], agents_by_id={1: agent},
        )
        # Should at least detect social awareness
        if result:
            self.assertIn("dynamic_result", result)


if __name__ == "__main__":
    unittest.main()
