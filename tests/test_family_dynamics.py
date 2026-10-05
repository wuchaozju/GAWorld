"""Households that change during a run, and family members as residents.

* **Transitions actually apply.** The plugin called the lifecycle with
  ``self._rng``, which was never set, so every marriage, birth and
  bereavement raised inside the bus and changed nothing.
* **The whole household sees a change.** A baby born to one partner of an
  in-sim couple is the other partner's child too.
* **Divorce and separation change the household**, and an in-sim couple
  stops sharing a home.
* **Co-resident children and elders can be residents** (off by default),
  and they stay dependants in the ledger.
See docs/proposals/2026-10-03-family-dynamics.md.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

import pytest

from gaworld.economy import finance as eco
from gaworld.family import lifecycle
from gaworld.family.plugin import FamilyPlugin
from gaworld.family.promote import PROMOTED_ID_BASE
from gaworld.kernel import build_kernel
from gaworld.world import city_map as cm
from tests.test_family import make_roster


def _map(n=40):
    nodes = [f"@node: H{i} | kind=hub | category=residential | x={i * 0.4} | y=0.0 | capacity=100"
             for i in range(1, n + 1)]
    nodes.append("@node: School | kind=hub | category=education | x=2.0 | y=0.5 | capacity=100")
    roads = [f"@road: H{i} -> H{i + 1} | type=local" for i in range(1, n)]
    roads.append("@road: H5 -> School | type=local")
    tree = "\n".join(f"  - Hub: H{i}" for i in range(1, n + 1))
    content = "# City Map\n" + "\n".join(nodes + roads) + f"\n\n- City: Demo\n{tree}\n  - Hub: School\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return cm.load_city_map(path)


def _world(promote=False, n=40, **promote_cfg):
    agents = make_roster(n)
    family = {"enabled": True}
    if promote:
        family["members_as_agents"] = {"enabled": True, **promote_cfg}
    ctx = build_kernel({"family": family}, load_entry_points=False)
    ctx.extras["city_map"] = _map(n)
    ctx.set_agents(agents)
    FamilyPlugin().setup(ctx)
    ctx.bus.emit("agents.built", agents=agents, config=ctx.config)
    ctx.bus.emit("on_simulation_start", agents=agents, config=ctx.config, day=1)
    return ctx, agents


def _rec(agent):
    return agent["ext"]["family"]


def _fire(ctx, agents, agent, key, day):
    ctx.bus.emit("life.event.applied", agent=agent, life_event={"template_key": key}, day=day,
                 daily_logs={a["id"]: "" for a in agents})


def _in_sim_couple(agents):
    by_id = {a["id"]: a for a in agents}
    for agent in agents:
        partner = lifecycle.partner_of(_rec(agent))
        if partner and partner.get("kind") == "agent" and partner.get("role") == "spouse":
            return agent, by_id[int(partner["agent_id"])]
    raise AssertionError("roster has no in-sim couple")


class TransitionsApplyTest(unittest.TestCase):
    def test_a_marriage_event_gives_a_single_resident_a_spouse(self):
        ctx, agents = _world()
        single = next(a for a in agents if lifecycle.can_marry(a, _rec(a)))
        _fire(ctx, agents, single, "marriage", 30)
        self.assertEqual(_rec(single)["marital_status"], "married")
        self.assertIsNotNone(lifecycle.partner_of(_rec(single)))
        self.assertIn("配偶", single["family"])

    def test_a_birth_lands_in_both_partners_records(self):
        ctx, agents = _world()
        for agent in agents:  # make a couple young enough
            agent["age"] = min(int(agent["age"]), 35)
        first, second = _in_sim_couple(agents)
        _fire(ctx, agents, first, "childbirth", 40)
        mine = [m for m in _rec(first)["members"] if m["key"] == "g_child_40"]
        theirs = [m for m in _rec(second)["members"] if m["key"] == "g_child_40"]
        self.assertEqual(len(mine), 1)
        self.assertEqual([(m["name"], m["role"]) for m in theirs], [(mine[0]["name"], "child")])
        self.assertIn("g_child_40", second.get("relationships", {}))

    def test_bereavement_never_marks_an_in_sim_resident_dead(self):
        record = {"members": [
            {"key": "7", "role": "spouse", "kind": "agent", "agent_id": 7, "age": 88, "coresident": True},
        ]}
        self.assertIsNone(lifecycle.bereavable_member(record))


class DivorceTest(unittest.TestCase):
    def test_an_off_screen_spouse_leaves(self):
        ctx, agents = _world()
        agent = next(a for a in agents
                     if (lifecycle.partner_of(_rec(a)) or {}).get("kind") == "ghost"
                     and lifecycle.partner_of(_rec(a))["role"] == "spouse")
        key = lifecycle.partner_of(_rec(agent))["key"]
        _fire(ctx, agents, agent, "divorce", 90)
        record = _rec(agent)
        self.assertEqual(record["marital_status"], "divorced")
        self.assertIsNone(lifecycle.partner_of(record))
        ex = next(m for m in record["members"] if m["key"] == key)
        self.assertEqual((ex["role"], ex["coresident"]), ("ex", False))
        self.assertEqual(agent["relationships"][key]["role"], "ex")
        self.assertIn("离异", agent["family"])

    def test_an_in_sim_couple_stops_sharing_a_home(self):
        ctx, agents = _world()
        first, second = _in_sim_couple(agents)
        home = first["locations"]["home"]
        self.assertEqual(second["locations"]["home"], home)
        _fire(ctx, agents, first, "divorce", 120)
        homes = {first["locations"]["home"], second["locations"]["home"]}
        self.assertEqual(len(homes), 2, homes)
        self.assertIn(home, homes)
        for person, other in ((first, second), (second, first)):
            self.assertEqual(_rec(person)["marital_status"], "divorced")
            self.assertEqual(person["relationships"][str(other["id"])]["role"], "ex")
        households = ctx.plugin_state("family")["assignment"].households
        self.assertFalse(any({first["id"], second["id"]} <= set(h.agent_ids) for h in households))
        mover = first if first["locations"]["home"] != home else second
        self.assertFalse([m for m in _rec(mover)["members"] if m.get("coresident")])

    def test_divorce_needs_a_spouse_and_separation_a_partner(self):
        record = {"members": [{"key": "g", "role": "partner", "coresident": True}]}
        self.assertFalse(lifecycle.can_divorce({}, record))
        self.assertTrue(lifecycle.can_separate({}, record))
        change = lifecycle.split(record, {}, keeps_children=True)
        self.assertEqual(change["type"], "separation")
        self.assertEqual(record["marital_status"], "never")


class PromotionTest(unittest.TestCase):
    def test_off_by_default(self):
        _, agents = _world()
        self.assertEqual(len(agents), 40)
        self.assertFalse(any(a.get("family_dependant") for a in agents))

    def test_school_age_children_and_older_elders_become_residents(self):
        ctx, agents = _world(promote=True, max_new_agents=50)
        new = [a for a in agents if a.get("family_dependant")]
        self.assertTrue(new)
        for resident in new:
            self.assertGreaterEqual(resident["id"], PROMOTED_ID_BASE)
            record = _rec(resident)
            holders = [m for m in record["members"] if m["kind"] == "agent"
                       and m["role"] in ("father", "mother", "child", "child_in_law")]
            self.assertTrue(holders, resident["name"])
            holder = ctx.agents_by_id[holders[0]["agent_id"]]
            self.assertEqual(resident["locations"]["home"], holder["locations"]["home"])
            listed = [m for m in _rec(holder)["members"] if m.get("agent_id") == resident["id"]]
            self.assertEqual(len(listed), 1)
            if resident["job"] in ("小学生", "初中生", "高中生"):
                self.assertTrue(6 <= resident["age"] <= 17)
            else:
                self.assertGreaterEqual(resident["age"], 60)
            self.assertIn("和家人同住", resident["family"])
            self.assertEqual(resident.get("family_today", ""), "")

    def test_the_same_seed_promotes_the_same_people_under_the_same_ids(self):
        _, first = _world(promote=True)
        _, second = _world(promote=True)
        pick = lambda agents: [(a["id"], a["name"]) for a in agents if a.get("family_dependant")]  # noqa: E731
        self.assertEqual(pick(first), pick(second))

    def test_the_cap_holds(self):
        _, agents = _world(promote=True, max_new_agents=1)
        self.assertEqual(sum(1 for a in agents if a.get("family_dependant")), 1)


class DependantsInTheLedgerTest(unittest.TestCase):
    def test_no_account_no_income_seeking_and_the_day_still_runs(self):
        ctx, agents = _world(promote=True)
        with tempfile.TemporaryDirectory() as tmp:
            config = {"economy": {"enabled": True, "output_dir": os.path.join(tmp, "e")},
                      "memory_dir": os.path.join(tmp, "m"), "log_dir": os.path.join(tmp, "l")}
            ext = {}
            eco.on_simulation_start({"config": config, "agents": agents, "extension_state": ext})
            child = next(a for a in agents if a.get("family_dependant"))
            self.assertNotIn("economy", child)
            step = {"activity": "在家写作业前发呆"}
            eco.on_agent_pre_step({"config": config, "agent": child, "step": step,
                                   "extension_state": ext, "actions": {}})
            self.assertEqual(step["activity"], "在家写作业前发呆")
            day = {"config": config, "day": 1, "agents": agents, "extension_state": ext,
                   "daily_logs": {a["id"]: "" for a in agents}}
            eco.on_day_start(day)
            eco.on_agent_post_step({**day, "agent": child, "time_str": "10:00",
                                    "step": {"activity": "上课", "action": "上课"}})
            eco.on_day_end(day)
            self.assertNotIn("economy", child)

    def test_dependants_do_not_set_off_on_their_own(self):
        from gaworld.travel.plugin import TravelPlugin

        ctx, agents = _world(promote=True)
        travel_ctx = build_kernel({"travel": {"enabled": True, "max_away_share": 1.0,
                                              "business": {"base_daily_prob": 1000.0}}},
                                  load_entry_points=False)
        travel_ctx.extras["city_map"] = ctx.extras["city_map"]
        TravelPlugin().setup(travel_ctx)
        dependants = [a for a in agents if a.get("family_dependant")]
        schedule = {a["id"]: [] for a in dependants}
        for day in range(1, 8):
            travel_ctx.bus.emit("on_day_start", day=day, agents=dependants, schedule_map=schedule,
                                city_map=ctx.extras["city_map"],
                                daily_logs={a["id"]: "" for a in dependants}, extension_state={})
        self.assertFalse(any((a.get("ext") or {}).get("travel") for a in dependants))


@pytest.mark.slow
class MainLoopTest(unittest.TestCase):
    """A real day with a pinned nine-year-old promoted to a resident."""

    def test_the_child_lives_a_day_of_their_own(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG
        from tests.fixtures import scratch_cwd
        from tests.fixtures.mock_llm import install

        scratch_cwd.enter(self)
        records = tempfile.mkdtemp()
        overrides = os.path.join(records, "family_overrides.json")
        with open(overrides, "w", encoding="utf-8") as fh:
            json.dump({"4": {"marital_status": "married",
                             "partner": {"kind": "ghost", "name": "王磊", "age": 31, "gender": "男"},
                             "children": [{"name": "小宇", "age": 9, "gender": "男"}]}}, fh,
                      ensure_ascii=False)
        touched = ("agent_ids", "sim_days", "stateful", "simulate_realtime", "seconds_per_day",
                   "news", "intervention", "external_environment_service", "distributed",
                   "visualization", "life_events", "external_rag", "records", "family")
        originals = {key: copy.deepcopy(CONFIG[key]) for key in touched if key in CONFIG}

        def restore():
            for key in touched:
                if key in originals:
                    CONFIG[key] = originals[key]
                else:
                    CONFIG.pop(key, None)

        self.addCleanup(restore)
        CONFIG.update(agent_ids=[4, 5], sim_days=1, stateful=False, simulate_realtime=False,
                      seconds_per_day=1)
        CONFIG["records"] = {"output_dir": records}
        CONFIG["family"] = {**CONFIG.get("family", {}), "overrides_path": overrides,
                            "members_as_agents": {"enabled": True, "elders": False}}
        for key in ("news", "intervention", "external_environment_service", "distributed",
                    "visualization", "life_events"):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = {**CONFIG[key], "enabled": False}
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = {**CONFIG["news"].get("info_seek", {}), "enabled": False}
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = {**CONFIG["external_rag"],
                                      "bootstrap": {**CONFIG["external_rag"].get("bootstrap", {}),
                                                    "enabled": False}}
        for name, value in (("AGENT_IDS", [4, 5]), ("SIM_DAYS", 1), ("STATEFUL", False),
                            ("SIMULATE_REALTIME", False), ("SECONDS_PER_DAY", 1),
                            ("NEWS_ENABLED", False), ("INTERVENTION_ENABLED", False),
                            ("HUMAN_REALISM_ENABLED", False), ("VISUALIZATION_ENABLED", False),
                            ("LIFE_EVENTS_ENABLED", False), ("LONG_RUN_ENABLED", False)):
            patcher = mock.patch.object(sim, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        with install() as llm:
            sim.run_simulation()

        child_calls = [c for c in llm.calls if c["agent_id"] == PROMOTED_ID_BASE]
        tasks = {c["task"] for c in child_calls}
        self.assertTrue({"perception", "planning", "reflection"} <= tasks, tasks)
        self.assertTrue(any("小宇" in c["prompt"] for c in child_calls))
        with open(os.path.join(records, "family.agent.jsonl"), encoding="utf-8") as fh:
            rows = {json.loads(line)["agent_id"]: json.loads(line) for line in fh if line.strip()}
        self.assertIn(PROMOTED_ID_BASE, rows)
        # Resident 4 is the mother; the pinned off-screen husband is the father.
        self.assertIn("父亲王磊", rows[PROMOTED_ID_BASE]["brief"])
        self.assertIn("母亲", rows[PROMOTED_ID_BASE]["brief"])


if __name__ == "__main__":
    unittest.main()
