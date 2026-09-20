"""Tests for the family / household subsystem."""

from __future__ import annotations

import unittest

from gaworld.family.assign import assign_households, pair_roommates, sample_marital_status
from gaworld.family.duties import care_load, daily_duties, duty_hint
from gaworld.family.events import contagion_effects, sample_family_event
from gaworld.family.finance import (
    charge_dependants,
    dependant_cost_monthly,
    household_state_effects,
    settle_couple,
)
from gaworld.family.narrative import family_brief, family_section
from gaworld.family.schema import HOUSEHOLD_TYPES, family_config
from gaworld.family.ties import apply_family_ties, reconcile_ghost_kin
from gaworld.settings.family import family_settings


def make_agent(agent_id, name, age, gender, hukou="本地", residence="西湖·文新", home="H1"):
    return {
        "id": agent_id,
        "name": name,
        "age": age,
        "gender": gender,
        "hukou": hukou,
        "residence": residence,
        "job": "职员",
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5},
        "locations": {"home": home, "current": home, "destination": home, "travel_route": [home]},
    }


def make_roster(n=40):
    agents = []
    for i in range(n):
        age = 22 + (i * 37) % 45
        gender = "男" if i % 2 == 0 else "女"
        hukou = "本地" if i % 3 else "外省"
        district = ["西湖·文新", "余杭·未来科技城", "滨江·白马湖"][i % 3]
        agents.append(
            make_agent(i + 1, f"测试{i + 1}", age, gender, hukou, district, home=f"H{i + 1}")
        )
    return agents


class TestMaritalSampling(unittest.TestCase):
    def test_status_is_deterministic_for_the_same_seed(self):
        cfg = family_config(None)
        agent = make_agent(7, "甲", 34, "女")
        first = [sample_marital_status(agent, cfg) for _ in range(5)]
        self.assertEqual(len(set(first)), 1, "same agent + seed must give one answer")

    def test_minors_are_never_married(self):
        cfg = family_config(None)
        for age in (6, 12, 17):
            agent = make_agent(age, "少年", age, "男")
            self.assertEqual(sample_marital_status(agent, cfg), "never")

    def test_marriage_rate_rises_with_age(self):
        """The whole point of the band table: 25-year-olds are mostly single,
        40-year-olds mostly are not."""
        cfg = family_config(None)
        young = [make_agent(1000 + i, f"y{i}", 24, "男" if i % 2 else "女") for i in range(200)]
        older = [make_agent(2000 + i, f"o{i}", 44, "男" if i % 2 else "女") for i in range(200)]
        young_married = sum(1 for a in young if sample_marital_status(a, cfg) != "never")
        older_married = sum(1 for a in older if sample_marital_status(a, cfg) != "never")
        self.assertLess(young_married, 40)
        self.assertGreater(older_married, 160)

    def test_config_override_reaches_the_sampler(self):
        cfg = family_config(
            {
                "family": {
                    "marital_status_bands": [
                        {"age": [0, 200], "male": {"married": 1.0}, "female": {"married": 1.0}}
                    ]
                }
            }
        )
        self.assertEqual(sample_marital_status(make_agent(1, "甲", 20, "男"), cfg), "married")


class TestAssignment(unittest.TestCase):
    def setUp(self):
        self.agents = make_roster()
        self.assignment = assign_households(self.agents)

    def test_every_agent_gets_exactly_one_household(self):
        self.assertEqual(len(self.assignment.by_agent), len(self.agents))
        seen = []
        for household in self.assignment.households:
            seen.extend(household.agent_ids)
        self.assertEqual(sorted(seen), sorted(a["id"] for a in self.agents))

    def test_household_types_are_known(self):
        for household in self.assignment.households:
            self.assertIn(household.type, HOUSEHOLD_TYPES)

    def test_not_everyone_is_single_and_not_everyone_is_married(self):
        """The bug this feature exists to fix, asserted directly."""
        statuses = self.assignment.summary()["marital_statuses"]
        never = statuses.get("never", 0)
        self.assertGreater(never, 0, "some agents must still be single")
        self.assertLess(never, len(self.agents), "not everyone can be single")
        partnered = sum(
            1
            for record in self.assignment.by_agent.values()
            if any(m["role"] in ("spouse", "partner") for m in record["members"])
        )
        self.assertGreater(partnered, 0)

    def test_assignment_is_reproducible(self):
        again = assign_households(make_roster())
        self.assertEqual(
            [(h.id, h.type, tuple(h.agent_ids)) for h in self.assignment.households],
            [(h.id, h.type, tuple(h.agent_ids)) for h in again.households],
        )

    def test_in_sim_spouses_are_mutual_and_share_a_home(self):
        by_id = {a["id"]: a for a in self.agents}
        pairs = 0
        for agent_id, record in self.assignment.by_agent.items():
            for member in record["members"]:
                if member["kind"] != "agent" or member["role"] not in ("spouse", "partner"):
                    continue
                pairs += 1
                partner_id = member["agent_id"]
                mirror = self.assignment.by_agent[partner_id]["members"]
                self.assertTrue(
                    any(m.get("agent_id") == agent_id for m in mirror),
                    "spouse ties must be symmetric",
                )
                self.assertEqual(
                    by_id[agent_id]["locations"]["home"],
                    by_id[partner_id]["locations"]["home"],
                    "co-resident partners must share a home node",
                )
        self.assertGreater(pairs, 0)

    def test_spouse_age_gap_stays_within_config(self):
        by_id = {a["id"]: a for a in self.agents}
        max_gap = family_config(None)["pairing"]["max_age_gap"]
        for agent_id, record in self.assignment.by_agent.items():
            for member in record["members"]:
                if member["kind"] == "agent" and member["role"] in ("spouse", "partner"):
                    gap = abs(by_id[agent_id]["age"] - by_id[member["agent_id"]]["age"])
                    self.assertLessEqual(gap, max_gap)

    def test_children_are_younger_than_their_parent(self):
        by_id = {a["id"]: a for a in self.agents}
        for agent_id, record in self.assignment.by_agent.items():
            for member in record["members"]:
                if member["role"] == "child":
                    self.assertLess(member["age"], by_id[agent_id]["age"])

    def test_pair_share_zero_means_no_in_sim_couples(self):
        assignment = assign_households(
            make_roster(), {"family": {"pairing": {"in_sim_pair_share": 0.0}}}
        )
        in_sim = [
            m
            for record in assignment.by_agent.values()
            for m in record["members"]
            if m["kind"] == "agent" and m["role"] in ("spouse", "partner")
        ]
        self.assertEqual(in_sim, [])

    def test_roommates_only_appear_in_shared_households(self):
        agents = make_roster()
        assignment = assign_households(agents)
        pair_roommates(assignment, agents)
        by_household = {h.id: h for h in assignment.households}
        for record in assignment.by_agent.values():
            roommates = [m for m in record["members"] if m["role"] == "roommate"]
            if roommates:
                self.assertEqual(by_household[record["household_id"]].type, "shared")
                self.assertFalse(
                    [m for m in record["members"] if m["role"] in ("spouse", "partner")],
                    "a flatmate household must not also hold a spouse",
                )


class TestTies(unittest.TestCase):
    def test_ties_land_in_the_relationship_dict_with_kin_config(self):
        agent = make_agent(1, "甲", 36, "男")
        members = [
            {"key": "2", "name": "乙", "role": "spouse", "kind": "agent", "age": 34,
             "gender": "女", "coresident": True, "agent_id": 2},
            {"key": "g_child_1", "name": "小丙", "role": "child", "kind": "ghost", "age": 6,
             "gender": "女", "coresident": True, "agent_id": None},
        ]
        written = apply_family_ties(agent, members, current_day=3)
        self.assertEqual(written, 2)
        spouse = agent["relationships"]["2"]
        self.assertEqual(spouse["role"], "spouse")
        self.assertEqual(spouse["kind"], "agent")
        self.assertTrue(spouse["family"])
        self.assertEqual(spouse["decay_rate"], 0.0)
        self.assertGreaterEqual(spouse["obligation"], 0.85)

    def test_existing_closeness_is_not_downgraded(self):
        agent = make_agent(1, "甲", 36, "男")
        agent["relationships"] = {"2": {"closeness": 0.95, "trust": 0.9, "obligation": 0.2}}
        apply_family_ties(
            agent,
            [{"key": "2", "name": "乙", "role": "spouse", "kind": "agent", "age": 34,
              "gender": "女", "coresident": True, "agent_id": 2}],
        )
        self.assertEqual(agent["relationships"]["2"]["closeness"], 0.95)
        self.assertGreaterEqual(agent["relationships"]["2"]["obligation"], 0.85)

    def test_contradicting_llm_spouse_is_pruned(self):
        agent = make_agent(1, "甲", 30, "男")
        agent["relationships"] = {
            "g_spouse_llm": {"kind": "ghost", "role": "spouse", "closeness": 0.8},
            "g_mother": {"kind": "ghost", "role": "mother", "closeness": 0.8},
            "5": {"kind": "agent", "role": "coworker", "closeness": 0.4},
        }
        removed = reconcile_ghost_kin(agent, [])
        self.assertEqual(removed, ["g_spouse_llm"])
        self.assertIn("g_mother", agent["relationships"])
        self.assertIn("5", agent["relationships"])

    def test_our_own_members_survive_reconciliation(self):
        agent = make_agent(1, "甲", 30, "男")
        agent["relationships"] = {"g_spouse": {"kind": "ghost", "role": "spouse"}}
        removed = reconcile_ghost_kin(agent, [{"key": "g_spouse"}])
        self.assertEqual(removed, [])

    def test_roster_name_wins_and_is_mirrored_back(self):
        agent = make_agent(1, "甲", 30, "男")
        agent["relationships"] = {"g_mother": {"kind": "ghost", "role": "mother",
                                               "profile": {"name": "王秀兰"}}}
        members = [{"key": "g_mother", "name": "李某", "role": "mother", "kind": "ghost",
                    "age": 58, "gender": "女", "coresident": False, "agent_id": None}]
        apply_family_ties(agent, members)
        self.assertEqual(members[0]["name"], "王秀兰")

    def test_placeholder_roster_name_loses_to_the_generated_one(self):
        """The roster's deterministic fallback names people "甲的母亲" — a
        label, not a name. It must not end up in the household brief."""
        agent = make_agent(1, "甲", 30, "男")
        agent["relationships"] = {"g_mother": {"kind": "ghost", "role": "mother",
                                               "profile": {"name": "甲的母亲"}}}
        members = [{"key": "g_mother", "name": "周淑芬", "role": "mother", "kind": "ghost",
                    "age": 58, "gender": "女", "coresident": False, "agent_id": None}]
        apply_family_ties(agent, members)
        self.assertEqual(members[0]["name"], "周淑芬")
        self.assertEqual(agent["relationships"]["g_mother"]["profile"]["name"], "周淑芬")


class TestDuties(unittest.TestCase):
    def setUp(self):
        self.record = {
            "household_id": "hh_001",
            "household_type": "nuclear",
            "marital_status": "married",
            "members": [
                {"key": "2", "name": "乙", "role": "spouse", "kind": "agent", "age": 34,
                 "gender": "女", "coresident": True, "agent_id": 2},
                {"key": "g_child_1", "name": "小丙", "role": "child", "kind": "ghost", "age": 4,
                 "gender": "女", "coresident": True, "agent_id": None},
            ],
        }

    def test_a_young_child_produces_duties(self):
        duties = daily_duties(self.record, day=2, is_weekend=False)
        self.assertTrue(duties)
        self.assertTrue(any("幼儿园" in d or "看着" in d for d in duties))

    def test_weekday_and_weekend_differ(self):
        weekday = daily_duties(self.record, day=2, is_weekend=False)
        weekend = daily_duties(self.record, day=6, is_weekend=True)
        self.assertNotEqual(weekday, weekend)

    def test_no_family_means_no_duties(self):
        self.assertEqual(daily_duties({"members": []}, day=1), [])
        self.assertEqual(duty_hint(None, day=1), "")

    def test_duties_respect_the_cap(self):
        record = dict(self.record)
        record["members"] = self.record["members"] + [
            {"key": f"g_child_{i}", "name": f"娃{i}", "role": "child", "kind": "ghost",
             "age": 3 + i, "gender": "男", "coresident": True, "agent_id": None}
            for i in range(2, 6)
        ]
        self.assertLessEqual(len(daily_duties(record, day=1)), 3)

    def test_a_partner_lightens_the_load(self):
        solo = dict(self.record)
        solo["members"] = [m for m in self.record["members"] if m["role"] != "spouse"]
        self.assertGreater(care_load(solo), care_load(self.record))

    def test_disabled_duties_produce_nothing(self):
        self.assertEqual(
            daily_duties(self.record, day=1, config={"family": {"duties": {"enabled": False}}}), []
        )


class TestNarrative(unittest.TestCase):
    def test_brief_mentions_partner_and_child(self):
        record = {
            "household_type": "nuclear",
            "marital_status": "married",
            "members": [
                {"key": "2", "name": "李梅", "role": "spouse", "kind": "agent", "age": 34,
                 "gender": "女", "coresident": True, "agent_id": 2},
                {"key": "g_child_1", "name": "李小满", "role": "child", "kind": "ghost", "age": 8,
                 "gender": "女", "coresident": True, "agent_id": None},
            ],
        }
        brief = family_brief(record)
        self.assertIn("李梅", brief)
        self.assertIn("李小满", brief)
        self.assertIn("已婚", brief)

    def test_empty_record_renders_empty(self):
        self.assertEqual(family_brief(None), "")
        self.assertEqual(family_section(None), "")

    def test_at_home_lists_who_is_there(self):
        record = {
            "household_type": "couple",
            "marital_status": "married",
            "members": [
                {"key": "2", "name": "李梅", "role": "spouse", "kind": "agent", "age": 34,
                 "gender": "女", "coresident": True, "agent_id": 2}
            ],
        }
        self.assertIn("此刻在家里", family_section(record, at_home=True))
        self.assertNotIn("此刻在家里", family_section(record, at_home=False))


class TestFinance(unittest.TestCase):
    def setUp(self):
        self.record = {
            "household_id": "hh_1",
            "members": [
                {"key": "g_child_1", "name": "娃", "role": "child", "kind": "ghost", "age": 4,
                 "gender": "男", "coresident": True, "agent_id": None},
                {"key": "g_father", "name": "爹", "role": "father", "kind": "ghost", "age": 72,
                 "gender": "男", "coresident": False, "agent_id": None},
            ],
        }

    def test_costs_scale_with_dependants(self):
        costs = dependant_cost_monthly(self.record)
        self.assertGreater(costs["children"], 0)
        self.assertGreater(costs["preschool"], 0)
        self.assertGreater(costs["elder_support"], 0)
        self.assertEqual(dependant_cost_monthly(None), {})

    def test_shared_children_are_not_double_counted(self):
        """Both partners hold the same child records; the school fee is one."""
        other = {"household_id": "hh_1", "members": list(self.record["members"])}
        single = dependant_cost_monthly(self.record)["children"]
        joint = dependant_cost_monthly([self.record, other])["children"]
        self.assertEqual(single, joint)

    def test_each_partner_supports_their_own_parents(self):
        other = {
            "household_id": "hh_1",
            "members": [
                {"key": "g_father", "name": "岳父", "role": "father", "kind": "ghost", "age": 74,
                 "gender": "男", "coresident": False, "agent_id": None}
            ],
        }
        single = dependant_cost_monthly(self.record)["elder_support"]
        joint = dependant_cost_monthly([self.record, other])["elder_support"]
        self.assertEqual(joint, single * 2)

    def test_charging_splits_by_income(self):
        charges = []

        def charge(agent, category, amount):
            charges.append((agent["id"], category, amount))
            return amount

        rich = make_agent(1, "甲", 36, "男")
        rich["economy"] = {"net_monthly_salary": 30000.0, "accounts": {"checking": 100.0}}
        poor = make_agent(2, "乙", 34, "女")
        poor["economy"] = {"net_monthly_salary": 10000.0, "accounts": {"checking": 100.0}}
        total = charge_dependants([rich, poor], self.record, charge_fn=charge)
        self.assertGreater(total, 0)
        paid = dict.fromkeys((1, 2), 0.0)
        for aid, _category, amount in charges:
            paid[aid] += amount
        self.assertGreater(paid[1], paid[2])

    def test_partner_covers_a_shortfall_without_creating_money(self):
        short = make_agent(1, "甲", 36, "男")
        short["economy"] = {"monthly_expense_estimate": 6000.0, "accounts": {"checking": 100.0}}
        rich = make_agent(2, "乙", 34, "女")
        rich["economy"] = {"monthly_expense_estimate": 6000.0, "accounts": {"checking": 20000.0}}
        before = 100.0 + 20000.0
        moved = settle_couple(short, rich)
        after = (
            short["economy"]["accounts"]["checking"] + rich["economy"]["accounts"]["checking"]
        )
        self.assertGreater(moved, 0)
        self.assertAlmostEqual(before, after, places=2)
        self.assertGreater(short["economy"]["accounts"]["checking"], 100.0)

    def test_no_transfer_when_both_are_fine(self):
        left = make_agent(1, "甲", 36, "男")
        left["economy"] = {"monthly_expense_estimate": 100.0, "accounts": {"checking": 9000.0}}
        right = make_agent(2, "乙", 34, "女")
        right["economy"] = {"monthly_expense_estimate": 100.0, "accounts": {"checking": 9000.0}}
        self.assertEqual(settle_couple(left, right), 0.0)

    def test_dual_income_buys_security_sole_earner_pays_in_stress(self):
        dual = household_state_effects(self.record, partner_earns=True)
        sole = household_state_effects(self.record, partner_earns=False)
        self.assertGreater(dual.get("econ_security", 0), 0)
        self.assertGreater(sole.get("stress", 0), 0)


class TestEvents(unittest.TestCase):
    def setUp(self):
        self.record = {
            "household_id": "hh_1",
            "members": [
                {"key": "2", "name": "李梅", "role": "spouse", "kind": "agent", "age": 34,
                 "gender": "女", "coresident": True, "agent_id": 2},
                {"key": "g_child_1", "name": "小满", "role": "child", "kind": "ghost", "age": 8,
                 "gender": "女", "coresident": True, "agent_id": None},
            ],
        }

    def test_events_only_reference_people_who_exist(self):
        childless = {"household_id": "hh_2", "members": []}
        for day in range(200):
            self.assertIsNone(sample_family_event(childless, day=day))

    def test_some_days_produce_an_event(self):
        drawn = [sample_family_event(self.record, day=day) for day in range(200)]
        events = [e for e in drawn if e]
        self.assertTrue(events)
        self.assertLess(len(events), 200)
        for event in events:
            self.assertTrue(event["title"])
            self.assertTrue(event["description"])
            self.assertIn("family_", event["template_key"])

    def test_event_sampling_is_deterministic(self):
        first = sample_family_event(self.record, day=17)
        second = sample_family_event(self.record, day=17)
        self.assertEqual(first, second)

    def test_events_can_be_disabled(self):
        for day in range(50):
            self.assertIsNone(
                sample_family_event(
                    self.record, day=day, config={"family": {"events": {"enabled": False}}}
                )
            )

    def test_contagion_pulls_towards_a_coresident_partner(self):
        agent = make_agent(1, "甲", 36, "男")
        agent["state"] = {"emotion": 0.3, "stress": 0.3}
        peer = make_agent(2, "乙", 34, "女")
        peer["state"] = {"emotion": 0.9, "stress": 0.9}
        deltas = contagion_effects(agent, [peer], coresident_ids={2})
        self.assertGreater(deltas["emotion"], 0)
        self.assertGreater(deltas["stress"], 0)

    def test_identical_households_do_not_drift(self):
        agent = make_agent(1, "甲", 36, "男")
        agent["state"] = {"emotion": 0.5, "stress": 0.5}
        peer = make_agent(2, "乙", 34, "女")
        peer["state"] = {"emotion": 0.5, "stress": 0.5}
        self.assertEqual(contagion_effects(agent, [peer], coresident_ids={2}), {})

    def test_remote_family_pulls_less_than_coresident(self):
        agent = make_agent(1, "甲", 36, "男")
        agent["state"] = {"emotion": 0.3}
        peer = make_agent(2, "乙", 34, "女")
        peer["state"] = {"emotion": 0.9}
        near = contagion_effects(agent, [peer], coresident_ids={2})["emotion"]
        far = contagion_effects(agent, [peer], coresident_ids=set())["emotion"]
        self.assertGreater(near, far)


class TestConfig(unittest.TestCase):
    def test_defaults_are_registered_in_the_global_config(self):
        from gaworld.settings import build_config

        self.assertIn("family", build_config())

    def test_partial_override_keeps_the_rest_of_the_defaults(self):
        cfg = family_config({"family": {"finance": {"child_cost_monthly": 1.0}}})
        self.assertEqual(cfg["finance"]["child_cost_monthly"], 1.0)
        self.assertIn("marital_status_bands", cfg)
        self.assertEqual(
            cfg["fertility"]["p_second_child"],
            family_settings()["family"]["fertility"]["p_second_child"],
        )


class TestPluginWiring(unittest.TestCase):
    def test_plugin_is_assembled_by_default(self):
        from gaworld.plugins import builtin_plugins

        self.assertIn("family", [p.id for p in builtin_plugins()])

    def test_disabled_plugin_registers_nothing(self):
        from gaworld.family.plugin import FamilyPlugin
        from gaworld.kernel import build_kernel

        ctx = build_kernel({"family": {"enabled": False}})
        plugin = FamilyPlugin()
        plugin.setup(ctx)
        self.assertEqual(ctx.bus._handlers.get("agents.built", []), [])

    def test_end_to_end_build_writes_family_onto_agents(self):
        from gaworld.family.plugin import FamilyPlugin
        from gaworld.kernel import build_kernel

        agents = make_roster(20)
        ctx = build_kernel({})
        ctx.set_agents(agents)
        plugin = FamilyPlugin()
        plugin.setup(ctx)
        ctx.bus.emit("agents.built", agents=agents, config=ctx.config)
        ctx.bus.emit("on_simulation_start", agents=agents, config=ctx.config, day=1)
        self.assertTrue(all("family" in a for a in agents))
        self.assertTrue(any(a["family"] for a in agents))
        with_relationships = [a for a in agents if a.get("relationships")]
        self.assertTrue(with_relationships)

    def test_contagion_hook_moves_state_towards_the_household(self):
        from gaworld.family.plugin import FamilyPlugin
        from gaworld.kernel import build_kernel

        agents = make_roster(20)
        ctx = build_kernel({})
        ctx.set_agents(agents)
        plugin = FamilyPlugin()
        plugin.setup(ctx)
        ctx.bus.emit("agents.built", agents=agents, config=ctx.config)
        paired = None
        for agent in agents:
            record = ctx.agent_ext(agent, "family")
            partner = [
                m for m in record.get("members", []) if m["kind"] == "agent" and m["coresident"]
            ]
            if partner:
                paired = (agent, {a["id"]: a for a in agents}[partner[0]["agent_id"]])
                break
        self.assertIsNotNone(paired, "the roster should produce at least one in-sim couple")
        agent, partner = paired
        agent["state"]["emotion"] = 0.2
        partner["state"]["emotion"] = 0.9
        before = agent["state"]["emotion"]
        ctx.bus.emit("state.effects", agent=agent, step={}, day=1, time_str="09:00")
        self.assertGreater(agent["state"]["emotion"], before)


if __name__ == "__main__":
    unittest.main()
