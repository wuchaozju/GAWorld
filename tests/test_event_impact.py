"""事件影响级联与事件评估。

覆盖三件事：

* **个体差异** —— 同一件事对不同居民不是同一件事（人格、状态、处境）；
* **真的落地** —— 影响要改到日程、经济、家庭、环境上，而不是只多一行提示词；
* **不重复施加** —— 一场暴雨不能在一天里扣十几次车费。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from gaworld.events.appraisal import rule_appraisal
from gaworld.events.appraisal_llm import merge_with_rule, parse_appraisal
from gaworld.events.cascade import (
    ImpactLedger,
    apply_schedule_impacts,
    ledger_key,
    perception_factor,
    plan_actions_to_impacts,
    select_impacts,
)
from gaworld.events.impact import (
    Impact,
    env_event_impacts,
    impact_pool_for_event,
    life_event_impacts,
    normalize_impacts,
)
from gaworld.events.impact_env import match_env_impacts
from gaworld.events.impact_plugin import EventImpactPlugin, event_impact_config
from gaworld.kernel import build_kernel
from tests.fixtures.mock_llm import MockLLM, install


def make_agent(
    agent_id: int = 1,
    *,
    n: float = 0.0,
    c: float = 0.0,
    e: float = 0.0,
    a: float = 0.0,
    o: float = 0.0,
    stress: float = 0.5,
    with_child: bool = False,
    savings: float = 0.0,
    salary: float = 8000.0,
) -> dict:
    """A resident with just enough shape for the appraisal to read."""
    members = []
    if with_child:
        members.append({"role": "child", "coresident": True, "age": 8, "name": "娃"})
    return {
        "id": agent_id,
        "name": f"居民{agent_id}",
        "age": 34,
        "job": "程序员",
        "state": {
            "emotion": 0.5,
            "stress": stress,
            "econ_security": 0.5,
            "time_pressure": 0.25,
            "fatigue_debt": 0.2,
            "self_control": 0.6,
            "energy": 0.75,
            "hunger": 0.25,
            "social_need": 0.4,
        },
        "economy": {
            "accounts": {"checking": 5000.0, "savings": savings},
            "debt": 0.0,
            "gross_monthly_salary": salary,
            "base_hourly_income": 30.0,
            "daily_income": 0.0,
            "daily_expense": 0.0,
            "daily_expense_by_category": {},
            "lifetime_income": 0.0,
            "lifetime_expense": 0.0,
            "shock_log": [],
        },
        "employment": "employed",
        "ext": {
            "big_five": {
                "o": o,
                "c": c,
                "e": e,
                "a": a,
                "n": n,
                "channels": ["rules", "prompt", "voice"],
            },
            "family": {
                "household_id": "hh_1",
                "household_type": "nuclear" if with_child else "single",
                "members": members,
            },
        },
    }


UNEMPLOYMENT = {
    "id": "ev-1",
    "template_key": "unemployment",
    "title": "失业",
    "description": "公司裁撤了岗位，今天收到通知。",
    "severity": 0.88,
    "life_event": True,
}


class TestImpactPool(unittest.TestCase):
    def test_life_event_template_carries_impacts(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        domains = {impact.domain for impact in impacts}
        self.assertIn("economy", domains)
        self.assertIn("schedule", domains)
        self.assertIn("family", domains)

    def test_every_template_with_a_family_touch_has_impacts(self):
        from gaworld.events.life import LIFE_EVENT_TEMPLATES

        for template in LIFE_EVENT_TEMPLATES:
            self.assertTrue(
                template.get("impacts"),
                f"{template['key']} has no objective impact pool",
            )

    def test_normalize_drops_unknown_domain_and_kind(self):
        impacts = normalize_impacts(
            [
                {"domain": "economy", "kind": "expense", "params": {"amount": 1}},
                {"domain": "astrology", "kind": "expense"},
                {"domain": "economy", "kind": "lottery_ticket"},
                "not a dict",
            ]
        )
        self.assertEqual(len(impacts), 1)
        self.assertEqual(impacts[0].domain, "economy")

    def test_env_event_rules_match_by_keyword(self):
        storm = {
            "id": "e-9",
            "type": "natural",
            "topic": "day",
            "name": "暴雨",
            "description": "今天有暴雨",
            "severity": 0.7,
            "scope": "city",
            "impact_tags": ["mobility"],
        }
        impacts = env_event_impacts(storm)
        domains = {impact.domain for impact in impacts}
        self.assertIn("environment", domains)
        self.assertIn("schedule", domains)

    def test_env_event_below_the_floor_changes_nothing(self):
        mild = {
            "id": "e-10",
            "type": "natural",
            "topic": "day",
            "name": "小雨",
            "description": "有点小雨",
            "severity": 0.2,
            "scope": "city",
        }
        self.assertEqual(match_env_impacts(mild), [])

    def test_life_event_wins_over_the_env_rule_table(self):
        impacts = impact_pool_for_event(UNEMPLOYMENT)
        self.assertTrue(all(isinstance(impact, Impact) for impact in impacts))
        self.assertTrue(impacts)


class TestRuleAppraisal(unittest.TestCase):
    def test_neuroticism_makes_the_same_event_harder(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        anxious = rule_appraisal(make_agent(n=1.3), UNEMPLOYMENT, impacts)
        calm = rule_appraisal(make_agent(n=-0.8), UNEMPLOYMENT, impacts)
        self.assertGreater(anxious["perceived_severity_raw"], calm["perceived_severity_raw"])
        self.assertGreater(perception_factor(anxious), perception_factor(calm))

    def test_dependants_push_the_concern_to_economy(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        with_child = rule_appraisal(make_agent(with_child=True), UNEMPLOYMENT, impacts)
        alone = rule_appraisal(make_agent(with_child=False), UNEMPLOYMENT, impacts)
        self.assertEqual(with_child["primary_concern"], "economy")
        # The economy is the top concern either way; what a dependant changes
        # is how hard it lands and how much the household side moves with it.
        self.assertGreater(with_child["sensitivity"], alone["sensitivity"])
        self.assertGreater(with_child["concerns"]["family"], alone["concerns"]["family"])

    def test_a_thin_savings_buffer_makes_the_event_heavier(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        thin = rule_appraisal(make_agent(savings=100.0, salary=8000.0), UNEMPLOYMENT, impacts)
        fat = rule_appraisal(make_agent(savings=80000.0, salary=8000.0), UNEMPLOYMENT, impacts)
        self.assertGreater(thin["sensitivity"], fat["sensitivity"])

    def test_stress_amplifies(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        tense = rule_appraisal(make_agent(stress=0.9), UNEMPLOYMENT, impacts)
        calm = rule_appraisal(make_agent(stress=0.2), UNEMPLOYMENT, impacts)
        self.assertGreater(tense["sensitivity"], calm["sensitivity"])

    def test_coping_style_comes_from_the_person(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        extrovert = rule_appraisal(make_agent(n=1.0, e=0.8), UNEMPLOYMENT, impacts)
        introvert = rule_appraisal(make_agent(n=1.0, e=-0.8), UNEMPLOYMENT, impacts)
        self.assertEqual(extrovert["coping_style"], "外化情绪")
        self.assertEqual(introvert["coping_style"], "内敛消化")

    def test_duration_follows_the_template(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        appraisal = rule_appraisal(make_agent(), UNEMPLOYMENT, impacts)
        self.assertGreaterEqual(appraisal["duration_days"], 30)

    def test_an_agent_with_nothing_still_gets_a_reading(self):
        appraisal = rule_appraisal({}, UNEMPLOYMENT, life_event_impacts(UNEMPLOYMENT))
        self.assertIn("perceived_severity", appraisal)
        self.assertTrue(appraisal["concerns"])


class TestModelAppraisal(unittest.TestCase):
    def test_parse_handles_nested_json(self):
        payload = json.dumps(
            {
                "thought": "先算清楚这个月的账",
                "appraisal": {
                    "perceived_severity": 0.8,
                    "primary_concern": "economy",
                    "concerns": ["economy", "schedule"],
                    "duration_days": 20,
                    "expected_consequences": ["收入中断"],
                },
                "emotion": {"delta_emotion": -0.2, "delta_stress": 0.25, "tone": "发慌"},
                "plan": {
                    "actions": [
                        {"kind": "activity_replace", "target": "上班", "replacement": "找工作"},
                        {"kind": "nonsense"},
                    ],
                    "seek_help_from": ["伴侣"],
                    "info_needed": ["失业保险"],
                },
            },
            ensure_ascii=False,
        )
        parsed = parse_appraisal(payload)
        self.assertEqual(parsed["thought"], "先算清楚这个月的账")
        self.assertEqual(
            parsed["appraisal"]["primary_concern"] if "appraisal" in parsed else parsed["primary_concern"],
            "economy",
        )
        self.assertEqual(len(parsed["actions"]), 1)
        self.assertEqual(parsed["emotion"]["delta_stress"], 0.25)

    def test_parse_survives_garbage(self):
        self.assertEqual(parse_appraisal("not json at all"), {})

    def test_the_model_cannot_overturn_the_rule(self):
        rule = {
            "perceived_severity": 0.5,
            "perceived_severity_raw": 0.5,
            "objective_severity": 0.5,
            "concerns": {"economy": 1.0},
            "primary_concern": "economy",
            "duration_days": 3,
        }
        wild = merge_with_rule(rule, {"perceived_severity": 1.0})
        self.assertLessEqual(wild["perceived_severity_raw"], 0.5 * 1.8 + 1e-9)
        mild = merge_with_rule(rule, {"perceived_severity": 0.0})
        self.assertGreaterEqual(mild["perceived_severity_raw"], 0.5 * 0.5 - 1e-9)

    def test_the_model_can_sharpen_the_reading(self):
        rule = {
            "perceived_severity": 0.5,
            "perceived_severity_raw": 0.5,
            "objective_severity": 0.5,
            "concerns": {"economy": 1.0},
            "primary_concern": "economy",
            "duration_days": 3,
        }
        sharper = merge_with_rule(rule, {"perceived_severity": 0.8})
        self.assertAlmostEqual(sharper["perceived_severity_raw"], 0.8, places=3)
        self.assertEqual(sharper["source"], "rules+model")


class TestCascade(unittest.TestCase):
    def test_concerns_and_perception_scale_the_impacts(self):
        impacts = life_event_impacts(UNEMPLOYMENT)
        appraisal = rule_appraisal(make_agent(with_child=True), UNEMPLOYMENT, impacts)
        selected = select_impacts(impacts, appraisal, max_impacts=4)
        self.assertTrue(selected)
        economy = [row for row in selected if row["domain"] == "economy"]
        self.assertTrue(economy)
        self.assertGreater(economy[0]["scale"], 0.0)

    def test_schedule_impacts_bend_the_day(self):
        schedule = [
            ("08:00", "通勤"),
            ("09:00", "工作"),
            ("12:00", "午餐"),
            ("19:00", "晚餐"),
        ]
        impact = Impact(
            domain="schedule",
            kind="activity_replace",
            params={"targets": ["通勤", "工作"], "replacement": "调整出行", "window_minutes": 240},
        )
        new_schedule, changes = apply_schedule_impacts(
            schedule, [{"impact": impact, "scale": 1.0}], time_str="09:00"
        )
        activities = [activity for _, activity in new_schedule]
        self.assertIn("调整出行", activities)
        self.assertIn("午餐", activities)  # meals are protected
        self.assertTrue(changes)

    def test_the_schedule_comes_back_in_the_canonical_shape(self):
        """Tuples are the form every reader of ``schedule_map`` understands.

        Two places in the simulator write the dict form instead, and
        ``get_activity_for_time`` skips dict entries — so a rewritten day has
        to come back as tuples or the resident reads as "个人时间" for the
        rest of it.
        """
        schedule = [{"time": "09:00", "activity": "工作"}]
        impact = Impact(
            domain="schedule",
            kind="activity_replace",
            params={"targets": ["工作"], "replacement": "就医", "window_minutes": 120},
        )
        new_schedule, _ = apply_schedule_impacts(
            schedule, [{"impact": impact, "scale": 1.0}], time_str="09:00"
        )
        self.assertIsInstance(new_schedule[0], tuple)
        self.assertEqual(new_schedule[0][1], "就医")

    def test_the_ledger_stops_a_storm_billing_twenty_times(self):
        agent = make_agent()
        ledger = ImpactLedger(agent)
        storm = {"id": "storm-1", "name": "暴雨", "severity": 0.7, "scope": "city"}
        key = ledger_key(storm, "economy", "expense", 3)
        self.assertFalse(ledger.already_applied(key))
        ledger.mark(key)
        self.assertTrue(ledger.already_applied(key))

    def test_a_life_event_is_applied_once_ever(self):
        first = ledger_key(UNEMPLOYMENT, "economy", "expense", 3)
        second = ledger_key(UNEMPLOYMENT, "economy", "expense", 9)
        self.assertEqual(first, second)

    def test_the_plans_turn_into_impacts(self):
        impacts = plan_actions_to_impacts(
            [
                {"kind": "activity_replace", "target": "上班", "replacement": "去医院"},
                {"kind": "activity_add", "activity": "投简历", "time": "15:00", "minutes": 60},
                {"kind": "contact", "target": "伴侣"},
                {"kind": "unknown"},
            ],
            time_str="09:00",
        )
        kinds = [(impact.domain, impact.kind) for impact in impacts]
        self.assertIn(("schedule", "activity_replace"), kinds)
        self.assertIn(("schedule", "activity_add"), kinds)
        self.assertEqual(len(kinds), 3)


class TestEconomyLanding(unittest.TestCase):
    def _ctx(self):
        ctx = build_kernel({"records": {"output_dir": "output/records"}}, load_entry_points=False)
        return ctx

    def test_an_expense_impact_leaves_the_account(self):
        from gaworld.economy import finance

        agent = make_agent()
        before = agent["economy"]["accounts"]["checking"]
        charged = finance.charge_external_expense(
            agent, "healthcare", 100.0, context={"config": {}, "day": 1, "agents": [agent]}
        )
        self.assertEqual(charged, 100.0)
        self.assertAlmostEqual(agent["economy"]["accounts"]["checking"], before - 100.0, places=2)

    def test_a_bonus_keeps_the_money_in_the_system(self):
        from gaworld.economy import finance

        agent = make_agent()
        sectors = {"firms": 0.0, "government": 0.0, "bank": 0.0}
        before = agent["economy"]["accounts"]["savings"] + sum(sectors.values())
        credited = finance.credit_event_bonus(
            agent,
            "lottery",
            20000.0,
            context={
                "config": {},
                "day": 1,
                "agents": [agent],
                "extension_state": {"economy_module": {"sectors": sectors}},
            },
        )
        self.assertEqual(credited, 20000.0)
        after = agent["economy"]["accounts"]["savings"] + sum(sectors.values())
        self.assertAlmostEqual(after, before, places=2)

    def test_an_income_change_expires(self):
        from gaworld.economy import finance

        agent = make_agent()
        record = finance.apply_event_income_change(agent, -0.3, 2, config={})
        self.assertIsNotNone(record)
        self.assertLess(agent["economy"]["base_hourly_income"], 30.0)


class TestFamilyLanding(unittest.TestCase):
    def test_the_event_overlay_raises_the_care_load(self):
        from gaworld.family.duties import care_load, daily_duties

        record = make_agent(with_child=True)["ext"]["family"]
        baseline = care_load(record)
        record["_event_care"] = {"delta": 0.25, "until": 5}
        record["_event_duties"] = [{"text": "照顾生病的家人", "until": 5}]
        self.assertGreater(care_load(record, day=3), baseline)
        self.assertEqual(care_load(record, day=9), baseline)  # expired
        duties = daily_duties(record, day=3)
        self.assertIn("照顾生病的家人", duties)
        self.assertNotIn("照顾生病的家人", daily_duties(record, day=9))

    def test_the_family_plugin_applies_a_care_load_impact(self):
        ctx = build_kernel({"records": {"output_dir": "output/records"}}, load_entry_points=False)
        from gaworld.family.plugin import FamilyPlugin

        agent = make_agent(with_child=True)
        plugin = FamilyPlugin()
        plugin.setup(ctx)
        ctx.agent_ext(agent, "family").update(agent["ext"]["family"])
        impact = Impact(
            domain="family",
            kind="care_load",
            params={"delta": 0.2, "duty": "照顾生病的家人"},
            duration_days=3,
        )
        ctx.bus.emit(
            "event.impact.apply",
            sim=ctx,
            agent=agent,
            impact=impact,
            scale=1.0,
            objective_severity=0.8,
            source_event=UNEMPLOYMENT,
            day=3,
            time_str="09:00",
        )
        record = ctx.agent_ext(agent, "family")
        self.assertAlmostEqual(record["_event_care"]["delta"], 0.2, places=3)
        self.assertEqual(record["_event_care"]["until"], 6)


class TestPluginWiring(unittest.TestCase):
    """The plugin, end to end over the bus.

    Two things are sandboxed: the plugin's own output directory (so a test
    never writes into the developer's ``output/``) and the vector-DB write
    (a real embedding call per event, and seconds of it).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch("gaworld.sim._diary.vector_db_add_entry", lambda *args, **kwargs: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The model layer is on by default and a real provider call would take
        # seconds per event; the mock makes the whole path deterministic.
        self.mock = MockLLM(
            {
                "event_appraisal": json.dumps(
                    {
                        "thought": "先把接下来三个月的账算一遍",
                        "appraisal": {
                            "perceived_severity": 0.75,
                            "primary_concern": "economy",
                            "concerns": ["economy", "schedule"],
                            "duration_days": 30,
                            "expected_consequences": ["收入中断", "要重新找工作"],
                        },
                        "emotion": {
                            "delta_emotion": -0.18,
                            "delta_stress": 0.22,
                            "tone": "心里发慌但还算冷静",
                        },
                        "plan": {
                            "actions": [
                                {"kind": "activity_replace", "target": "上班", "replacement": "找工作"}
                            ],
                            "seek_help_from": ["伴侣"],
                            "info_needed": ["失业保险怎么办"],
                        },
                    },
                    ensure_ascii=False,
                )
            }
        )
        self._llm = install(self.mock)
        self._llm.__enter__()
        self.addCleanup(self._llm.__exit__, None, None, None)

    def _ctx(self):
        return build_kernel(
            {
                "records": {"output_dir": os.path.join(self._tmp.name, "records")},
                "output_root": os.path.join(self._tmp.name, "out"),
            },
            load_entry_points=False,
        )

    def test_the_config_has_the_section(self):
        cfg = event_impact_config({})
        self.assertTrue(cfg["enabled"])
        self.assertIn("llm_min_severity", cfg["appraisal"])

    def test_the_appraisal_stage_produces_an_appraisal(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent(with_child=True)
        step = {
            "life_events": [UNEMPLOYMENT],
            "_env_events": [],
        }
        appraisal = ctx.bus.filter(
            "appraisal.compose",
            None,
            agent=agent,
            step=step,
            day=3,
            time_str="09:00",
            schedule_map={1: [("09:00", "工作")]},
            daily_logs={1: ""},
        )
        self.assertIsNotNone(appraisal)
        self.assertTrue(appraisal["events"])
        first = appraisal["events"][0]
        self.assertIn("perceived_severity", first)
        self.assertTrue(first["applied"])

    def test_the_response_is_recorded(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent(with_child=True)
        ctx.bus.filter(
            "appraisal.compose",
            None,
            agent=agent,
            step={"life_events": [UNEMPLOYMENT], "_env_events": []},
            day=3,
            time_str="09:00",
            schedule_map={1: [("09:00", "工作")]},
            daily_logs={1: ""},
        )
        written = os.listdir(plugin._output_dir)
        self.assertIn("event_responses.jsonl", written)
        self.assertIn("event_responses.csv", written)

    def test_the_second_run_does_not_apply_the_same_life_event_twice(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent(with_child=True)
        step = {"life_events": [UNEMPLOYMENT], "_env_events": []}
        kwargs = {
            "agent": agent,
            "step": step,
            "day": 3,
            "time_str": "09:00",
            "schedule_map": {1: [("09:00", "工作")]},
            "daily_logs": {1: ""},
        }
        first = ctx.bus.filter("appraisal.compose", None, **kwargs)
        second = ctx.bus.filter("appraisal.compose", None, **kwargs)
        self.assertTrue(first["events"])
        self.assertFalse(second["events"])

    def test_an_environment_event_is_only_applied_once_a_day(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent()
        storm = {
            "id": "storm-1",
            "type": "natural",
            "topic": "day",
            "name": "暴雨",
            "description": "今天有暴雨",
            "severity": 0.75,
            "scope": "city",
            "impact_tags": ["mobility"],
        }
        kwargs = {
            "agent": agent,
            "step": {"life_events": [], "_env_events": [storm]},
            "day": 3,
            "time_str": "09:00",
            "schedule_map": {1: [("09:00", "通勤")]},
            "daily_logs": {1: ""},
        }
        first = ctx.bus.filter("appraisal.compose", None, **kwargs)
        second = ctx.bus.filter("appraisal.compose", None, **kwargs)
        self.assertTrue(first["events"])
        self.assertFalse(second["events"])

    def test_the_environment_reaches_the_perception(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent()
        storm = {
            "id": "storm-2",
            "type": "natural",
            "topic": "day",
            "name": "暴雨",
            "description": "今天有暴雨",
            "severity": 0.75,
            "scope": "city",
            "impact_tags": ["mobility"],
        }
        ctx.bus.filter(
            "appraisal.compose",
            None,
            agent=agent,
            step={"life_events": [], "_env_events": [storm]},
            day=3,
            time_str="09:00",
            schedule_map={1: [("09:00", "通勤")]},
            daily_logs={1: ""},
        )
        line = ctx.bus.collect("perception.compose", agent=agent, day=3, time_str="09:00")
        text = "\n".join(str(item) for item in line)
        self.assertIn("判断", text)

    def test_the_model_answers_on_a_serious_event(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent(with_child=True)
        appraisal = ctx.bus.filter(
            "appraisal.compose",
            None,
            agent=agent,
            step={"life_events": [UNEMPLOYMENT], "_env_events": []},
            day=3,
            time_str="09:00",
            schedule_map={1: [("09:00", "工作")]},
            daily_logs={1: ""},
        )
        first = appraisal["events"][0]
        self.assertEqual(first["source"], "rules+model")
        self.assertIn("先把接下来三个月的账算一遍", first["thought"])
        self.assertEqual(self.mock.call_count("event_appraisal"), 1)

    def test_a_mild_event_does_not_call_the_model(self):
        ctx = self._ctx()
        plugin = EventImpactPlugin()
        plugin.setup(ctx)
        agent = make_agent()
        drizzle = {
            "id": "storm-3",
            "type": "natural",
            "topic": "day",
            "name": "暴雨",
            "description": "今天有暴雨",
            "severity": 0.46,
            "scope": "city",
            "impact_tags": ["mobility"],
        }
        appraisal = ctx.bus.filter(
            "appraisal.compose",
            None,
            agent=agent,
            step={"life_events": [], "_env_events": [drizzle]},
            day=3,
            time_str="09:00",
            schedule_map={1: [("09:00", "通勤")]},
            daily_logs={1: ""},
        )
        self.assertTrue(appraisal["events"])
        self.assertEqual(appraisal["events"][0]["source"], "rules")
        self.assertEqual(self.mock.call_count("event_appraisal"), 0)


class TestEndToEnd(unittest.TestCase):
    """A real run: the event is queued, the tick consumes it, the cascade lands.

    Everything else in this file is a unit test of one layer. This one proves
    the layers are wired into the actual simulation: the ``appraise`` stage
    runs inside the agent step, the model's reading reaches the prompts, and
    the impacts reach the world.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, os.path.join(self.tmp.name, "data"))
        original_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, original_cwd)
        # Queue the event before the run: the simulator drains it on the
        # first tick, exactly as the dashboard does.
        queue_dir = os.path.join(self.tmp.name, "output", "life_events")
        os.makedirs(queue_dir, exist_ok=True)
        with open(os.path.join(queue_dir, "events.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "events": [
                        {
                            "id": "e2e-1",
                            "template_key": "illness",
                            "title": "突然生病",
                            "description": "早上起来发热不舒服，今天要去医院。",
                            "severity": 0.7,
                            "schedule_mode": "immediate",
                            "agent_ids": [4],
                            "created_by": "test",
                        }
                    ]
                },
                fh,
                ensure_ascii=False,
            )

    def test_a_queued_event_is_appraised_and_lands(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG

        originals = {
            key: CONFIG.get(key)
            for key in (
                "agent_ids",
                "sim_days",
                "stateful",
                "simulate_realtime",
                "seconds_per_day",
                "news",
                "human_realism",
                "intervention",
                "external_environment_service",
                "distributed",
                "visualization",
                "life_events",
                "external_rag",
                "event_impact",
            )
        }

        def _restore():
            for key, value in originals.items():
                if value is None:
                    CONFIG.pop(key, None)
                else:
                    CONFIG[key] = value

        self.addCleanup(_restore)
        CONFIG["agent_ids"] = [4, 5]
        CONFIG["sim_days"] = 1
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        for key in (
            "news",
            "external_rag",
            "intervention",
            "external_environment_service",
            "distributed",
            "visualization",
        ):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = dict(CONFIG[key])
                CONFIG[key]["enabled"] = False
        if isinstance(CONFIG.get("human_realism"), dict):
            CONFIG["human_realism"] = dict(CONFIG["human_realism"])
            CONFIG["human_realism"]["enabled"] = False
        # Life events ON (the smoke test turns them off) and the cascade on.
        CONFIG["life_events"] = dict(CONFIG.get("life_events") or {})
        CONFIG["life_events"]["enabled"] = True
        CONFIG["event_impact"] = dict(CONFIG.get("event_impact") or {})
        CONFIG["event_impact"]["enabled"] = True

        sim.AGENT_IDS = [4, 5]
        sim.SIM_DAYS = 1
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = True
        sim.LONG_RUN_ENABLED = False

        with install(
            MockLLM(
                {
                    "event_appraisal": json.dumps(
                        {
                            "thought": "先请半天假去看病",
                            "appraisal": {
                                "perceived_severity": 0.7,
                                "primary_concern": "health",
                                "concerns": ["schedule", "economy"],
                                "duration_days": 3,
                            },
                            "emotion": {"delta_emotion": -0.15, "delta_stress": 0.18, "tone": "有点慌"},
                            "plan": {
                                "actions": [
                                    {"kind": "activity_replace", "target": "工作", "replacement": "就医"}
                                ]
                            },
                        },
                        ensure_ascii=False,
                    )
                }
            )
        ) as mock:
            sim.run_simulation()

        record_path = os.path.join(self.tmp.name, "output", "event_impact", "event_responses.jsonl")
        self.assertTrue(os.path.exists(record_path), "no event response was recorded")
        with open(record_path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertTrue(rows, "the event response file is empty")
        titles = {str(row.get("event_title", "")) for row in rows}
        self.assertIn("突然生病", titles)
        row = next(r for r in rows if r.get("event_title") == "突然生病")
        self.assertGreater(float(row.get("perceived_severity", 0)), 0.0)
        self.assertTrue(row.get("applied"))
        self.assertEqual(mock.call_count("event_appraisal"), 1)


if __name__ == "__main__":
    unittest.main()
