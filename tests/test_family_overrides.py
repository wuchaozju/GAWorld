"""Operator-pinned families: the override layer and its effect on assignment.

The thing worth testing hardest is not that a pin is stored — it is that the
pin survives *re-assignment*. Households are re-derived from scratch every
run, so an override that the assigner does not consult is an edit the
operator would watch disappear the next morning.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from gaworld.family.assign import assign_households
from gaworld.family.overrides import (
    OverrideError,
    cross_check,
    forced_pairs,
    load_overrides,
    normalize_override,
    save_overrides,
)


def make_agent(agent_id, name, age, gender, hukou="本地", residence="西湖·文新"):
    return {
        "id": agent_id,
        "name": name,
        "age": age,
        "gender": gender,
        "hukou": hukou,
        "residence": residence,
        "locations": {"home": f"H{agent_id}", "current": f"H{agent_id}"},
    }


def make_roster(n=30):
    return [
        make_agent(
            i + 1,
            f"测试{i + 1}",
            24 + (i * 31) % 40,
            "男" if i % 2 == 0 else "女",
            "本地" if i % 3 else "外省",
            ["西湖·文新", "余杭·未来科技城", "滨江·白马湖"][i % 3],
        )
        for i in range(n)
    ]


def record_for(agents, overrides, agent_id):
    return assign_households(agents, None, overrides).by_agent[agent_id]


def members_of(record, role):
    return [m for m in record["members"] if m["role"] == role]


class NormalizeTests(unittest.TestCase):
    def test_an_empty_edit_is_not_an_override(self):
        self.assertEqual(normalize_override({}, agent_id=1), {})
        self.assertEqual(normalize_override({"note": ""}, agent_id=1), {})

    def test_marital_status_is_validated(self):
        self.assertEqual(
            normalize_override({"marital_status": "married"}, agent_id=1)["marital_status"],
            "married",
        )
        with self.assertRaises(OverrideError):
            normalize_override({"marital_status": "engaged"}, agent_id=1)

    def test_a_person_needs_a_name_and_a_sane_age(self):
        with self.assertRaises(OverrideError):
            normalize_override({"children": [{"name": "", "age": 5}]}, agent_id=1)
        with self.assertRaises(OverrideError):
            normalize_override({"children": [{"name": "小满", "age": 500}]}, agent_id=1)
        with self.assertRaises(OverrideError):
            normalize_override({"children": [{"name": "小满", "age": "五"}]}, agent_id=1)

    def test_you_cannot_marry_yourself(self):
        with self.assertRaises(OverrideError):
            normalize_override(
                {"partner": {"kind": "agent", "agent_id": 7}}, agent_id=7
            )

    def test_explicit_null_partner_is_preserved(self):
        """`None` here means "pinned to no partner" — it must survive
        normalization, or the operator cannot say "this person is single"."""
        out = normalize_override({"partner": None}, agent_id=1)
        self.assertIn("partner", out)
        self.assertIsNone(out["partner"])

    def test_pinned_none_children_differs_from_unpinned(self):
        self.assertEqual(normalize_override({"children": []}, agent_id=1)["children"], [])
        self.assertNotIn("children", normalize_override({"children": None}, agent_id=1))

    def test_elder_roles_are_coerced_to_something_the_model_knows(self):
        out = normalize_override(
            {"elders": [{"name": "王秀", "age": 70, "gender": "女", "role": "银行家"}]},
            agent_id=1,
        )
        self.assertEqual(out["elders"][0]["role"], "mother")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "family_overrides.json")
        self.cfg = {"family": {"overrides_path": self.path}}

    def test_round_trip(self):
        save_overrides({3: {"marital_status": "married"}}, self.cfg)
        self.assertEqual(load_overrides(self.cfg), {3: {"marital_status": "married"}})

    def test_missing_file_is_empty(self):
        self.assertEqual(load_overrides(self.cfg), {})

    def test_a_corrupt_file_does_not_stop_a_simulation(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.assertEqual(load_overrides(self.cfg), {})

    def test_empty_records_are_not_persisted(self):
        save_overrides({3: {}, 4: {"marital_status": "never"}}, self.cfg)
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(list(json.load(fh)), ["4"])


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.agents = make_roster()

    def test_marital_status_is_pinned(self):
        base = record_for(self.agents, {}, 1)
        pinned = record_for(self.agents, {1: {"marital_status": "widowed"}}, 1)
        self.assertEqual(pinned["marital_status"], "widowed")
        self.assertNotEqual(base["marital_status"], "widowed")

    def test_a_pinned_in_sim_couple_is_mutual_and_shares_a_home(self):
        agents = make_roster()
        overrides = {1: {"marital_status": "married",
                         "partner": {"kind": "agent", "agent_id": 4, "role": "spouse"}}}
        assignment = assign_households(agents, None, overrides)
        left, right = assignment.by_agent[1], assignment.by_agent[4]
        self.assertEqual(
            [m["agent_id"] for m in members_of(left, "spouse")], [4]
        )
        self.assertEqual(
            [m["agent_id"] for m in members_of(right, "spouse")], [1]
        )
        self.assertEqual(left["household_id"], right["household_id"])
        by_id = {a["id"]: a for a in agents}
        self.assertEqual(by_id[1]["locations"]["home"], by_id[4]["locations"]["home"])

    def test_a_pin_beats_the_age_gap_rule(self):
        """Pinning is an operator overriding the demographics on purpose; the
        matcher's age-gap limit must not quietly veto it."""
        agents = [make_agent(1, "甲", 24, "男"), make_agent(2, "乙", 61, "女")]
        overrides = {1: {"marital_status": "married",
                         "partner": {"kind": "agent", "agent_id": 2, "role": "spouse"}}}
        record = record_for(agents, overrides, 1)
        self.assertEqual([m["agent_id"] for m in members_of(record, "spouse")], [2])

    def test_whoever_loses_a_partner_to_a_pin_still_gets_one(self):
        """A pin is a claim on another agent. The displaced agent must fall
        back to an off-screen spouse, not silently become single."""
        agents = make_roster()
        baseline = assign_households(agents, None, {})
        # Find a married agent the greedy matched in-sim, and steal its partner.
        victim = None
        for aid, record in sorted(baseline.by_agent.items()):
            spouses = [m for m in members_of(record, "spouse") if m["kind"] == "agent"]
            if spouses:
                victim, stolen = aid, spouses[0]["agent_id"]
                break
        self.assertIsNotNone(victim, "the roster should produce an in-sim couple")
        thief = next(
            aid for aid in sorted(baseline.by_agent) if aid not in (victim, stolen)
        )
        overrides = {
            thief: {
                "marital_status": "married",
                "partner": {"kind": "agent", "agent_id": stolen, "role": "spouse"},
            }
        }
        after = assign_households(make_roster(), None, overrides)
        self.assertEqual(
            [m["agent_id"] for m in members_of(after.by_agent[thief], "spouse")], [stolen]
        )
        victim_record = after.by_agent[victim]
        if victim_record["marital_status"] == "married":
            self.assertTrue(
                members_of(victim_record, "spouse"),
                "the displaced agent must still have a spouse (off-screen is fine)",
            )

    def test_pinned_children_are_used_verbatim_and_drive_the_household_type(self):
        overrides = {
            2: {
                "marital_status": "married",
                "children": [
                    {"name": "小满", "gender": "女", "age": 4, "coresident": True, "role": "child"}
                ],
            }
        }
        record = record_for(self.agents, overrides, 2)
        children = members_of(record, "child")
        self.assertEqual([c["name"] for c in children], ["小满"])
        self.assertEqual(children[0]["age"], 4)
        # The type is a read-out, never a dropdown: a couple with a resident
        # child *is* a nuclear family (or multigen if an elder moved in).
        self.assertIn(record["household_type"], ("nuclear", "multigen"))

    def test_pinning_no_children_is_different_from_not_pinning(self):
        overrides = {2: {"marital_status": "married", "children": []}}
        record = record_for(self.agents, overrides, 2)
        self.assertEqual(members_of(record, "child"), [])

    def test_pinned_elders_replace_the_sampled_ones_and_suppress_remote_parents(self):
        """Otherwise a pinned co-resident mother plus the automatic
        "parents living elsewhere" pass would give the agent four parents."""
        overrides = {
            5: {
                "elders": [
                    {"name": "刘桂英", "gender": "女", "age": 70, "coresident": True,
                     "role": "mother"}
                ]
            }
        }
        record = record_for(self.agents, overrides, 5)
        parents = [m for m in record["members"] if m["role"] in ("mother", "father", "parent")]
        self.assertEqual([p["name"] for p in parents], ["刘桂英"])

    def test_pinning_no_partner_beats_a_married_status(self):
        overrides = {3: {"marital_status": "married", "partner": None}}
        record = record_for(self.agents, overrides, 3)
        self.assertEqual(record["marital_status"], "married")
        self.assertEqual(members_of(record, "spouse"), [])
        self.assertEqual(members_of(record, "partner"), [])

    def test_an_override_for_an_absent_agent_is_ignored(self):
        """Studio can pin agent 99 while a run only includes 1-30."""
        overrides = {99: {"marital_status": "married",
                          "partner": {"kind": "agent", "agent_id": 1, "role": "spouse"}}}
        assignment = assign_households(self.agents, None, overrides)
        self.assertNotIn(99, assignment.by_agent)
        self.assertEqual(
            [m["agent_id"] for m in members_of(assignment.by_agent[1], "spouse") if m["agent_id"]],
            [m["agent_id"] for m in members_of(record_for(self.agents, {}, 1), "spouse") if m["agent_id"]],
        )

    def test_a_ghost_partner_is_used_verbatim(self):
        overrides = {
            6: {
                "marital_status": "married",
                "partner": {"kind": "ghost", "name": "周敏", "gender": "女", "age": 41,
                            "role": "spouse", "coresident": True},
            }
        }
        record = record_for(self.agents, overrides, 6)
        spouse = members_of(record, "spouse")[0]
        self.assertEqual(spouse["name"], "周敏")
        self.assertEqual(spouse["age"], 41)
        self.assertEqual(spouse["kind"], "ghost")

    def test_overrides_are_still_deterministic(self):
        overrides = {2: {"marital_status": "married", "children": []}}
        first = assign_households(make_roster(), None, overrides)
        second = assign_households(make_roster(), None, overrides)
        self.assertEqual(
            [(h.id, h.type, tuple(h.agent_ids)) for h in first.households],
            [(h.id, h.type, tuple(h.agent_ids)) for h in second.households],
        )

    def test_a_ghost_only_pin_leaves_everyone_else_alone(self):
        """Pinning a household that claims nobody else must not re-roll the
        rest of the town — that is the whole point of the per-agent streams."""
        base = assign_households(make_roster(), None, {})
        # Pick someone the sampler did *not* marry, so the pin is a real change
        # rather than a no-op that would pass this test for the wrong reason.
        target = next(
            aid
            for aid in sorted(base.by_agent)
            if base.by_agent[aid]["marital_status"] != "married"
        )
        overrides = {
            target: {
                "marital_status": "married",
                "partner": {"kind": "ghost", "name": "周敏", "gender": "女", "age": 41,
                            "role": "spouse"},
            }
        }
        after = assign_households(make_roster(), None, overrides)
        self.assertEqual(after.by_agent[target]["marital_status"], "married")
        self.assertEqual(
            [m["name"] for m in members_of(after.by_agent[target], "spouse")], ["周敏"]
        )
        changed = [
            aid
            for aid in base.by_agent
            if base.by_agent[aid]["marital_status"] != after.by_agent[aid]["marital_status"]
        ]
        self.assertEqual(changed, [target])


class ConflictTests(unittest.TestCase):
    def test_conflicting_claims_resolve_by_lowest_id_and_are_reported(self):
        overrides = {
            1: {"partner": {"kind": "agent", "agent_id": 2, "role": "spouse"}},
            2: {"partner": {"kind": "agent", "agent_id": 3, "role": "spouse"}},
        }
        pairs = forced_pairs(overrides)
        self.assertEqual(pairs[1], 2)
        self.assertEqual(pairs[2], 1)
        self.assertNotIn(3, pairs)
        warnings = cross_check(overrides)
        self.assertTrue(warnings)
        self.assertIn("2", warnings[0])

    def test_a_mutual_pair_is_not_a_conflict(self):
        overrides = {
            1: {"partner": {"kind": "agent", "agent_id": 2, "role": "spouse"}},
            2: {"partner": {"kind": "agent", "agent_id": 1, "role": "spouse"}},
        }
        self.assertEqual(cross_check(overrides), [])
        self.assertEqual(forced_pairs(overrides), {1: 2, 2: 1})


if __name__ == "__main__":
    unittest.main()
