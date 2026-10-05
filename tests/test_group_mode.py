"""Group mode inside a normal run (gaworld/group/plugin.py, roadmap P3-16).

What we defend:

* the switch: ``simulation_mode`` is individual or group, and group refuses
  to start without day-step fast-forward;
* the adaptive audit: an alarm doubles that cohort's audit share (capped),
  quiet days bring it back down, and no boost leaves the sampler unchanged;
* a group day: cohorts move only their non-materialised members, only on the
  state variables the fast-forward brief can move; the brief runs for the
  materialised few; the audit compares their own change with the cohort's;
* industry falls back to the job text when the corpus has no column;
* end to end: a real fast-forward run in group mode briefs only the
  materialised residents, still records every resident's state history and
  writes ``group.day`` records.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

from gaworld.group.cohort import partition_cohorts
from gaworld.group.materialize import adapt_audit_boost, select_materialized
from gaworld.group.plugin import GroupPlugin, validate_config
from gaworld.population.generate import generate_population
from gaworld.population.schema import normalize_spec
from gaworld.sim._fastforward import LONG_RUN_STATE_KEYS
from tests.fixtures.mock_llm import install


def _agents(size: int = 120, seed: int = 5) -> list[dict]:
    result = generate_population(normalize_spec({"size": size, "seed": seed}))
    return [
        {
            "id": p.id,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "hukou": p.hukou,
            "industry": p.industry,
            "residence": p.residence,
            "state": dict(p.state),
        }
        for p in result.people
    ]


_COHORT_DIGEST = json.dumps(
    {
        "brief": "这群人照常上班。",
        "divergence": "",
        "memory": "菜价涨了",
        "state_changes": {"stress": 0.05, "voice_propensity": 0.1},
        "share_affected": 1.0,
    },
    ensure_ascii=False,
)


class _Bus:
    def __init__(self):
        self.handlers: dict[str, list] = {}

    def on(self, event, handler, **_kw):
        self.handlers.setdefault(event, []).append(handler)


class _Recorder:
    def __init__(self):
        self.rows: list[tuple[str, dict]] = []

    def record(self, table, data):
        self.rows.append((table, data))

    def table(self, name):
        return [row for table, row in self.rows if table == name]


class _Ctx:
    def __init__(self, config, llm):
        self.config = config
        self.bus = _Bus()
        self.recorder = _Recorder()
        self.llm = llm


def _group_config(**group):
    return {
        "simulation_mode": "group",
        "random_seed": 3,
        "long_run": {"enabled": True, "unit": "day", "brief_llm": True},
        "group": {"materialization_budget": 10, "audit_fraction": 0.05, **group},
    }


class SwitchTests(unittest.TestCase):
    def test_individual_is_the_default_and_unknown_modes_are_refused(self):
        validate_config({})
        validate_config({"simulation_mode": "individual"})
        with self.assertRaisesRegex(ValueError, "simulation_mode"):
            validate_config({"simulation_mode": "cohort"})

    def test_group_mode_needs_day_step_fast_forward(self):
        validate_config(_group_config())
        with self.assertRaisesRegex(ValueError, "--fast-forward"):
            validate_config({"simulation_mode": "group"})
        with self.assertRaisesRegex(ValueError, "按天快进"):
            validate_config({**_group_config(), "long_run": {"enabled": True, "unit": "month"}})

    def test_individual_run_registers_nothing(self):
        ctx = _Ctx({}, llm=None)
        GroupPlugin().setup(ctx)
        self.assertEqual({}, ctx.bus.handlers)


class AuditBoostTests(unittest.TestCase):
    def test_no_boost_leaves_the_sample_unchanged(self):
        agents = _agents()
        by_id = {a["id"]: a for a in agents}
        cohorts = partition_cohorts(agents)
        kwargs = {"day": 1, "budget": 10, "audit_fraction": 0.05}
        plain = select_materialized(cohorts, by_id, rng=np.random.default_rng(1), **kwargs)
        empty = select_materialized(cohorts, by_id, rng=np.random.default_rng(1), audit_boost={}, **kwargs)
        self.assertEqual(plain.to_dict(), empty.to_dict())

    def test_a_boosted_cohort_gets_more_audit_on_top_of_the_others(self):
        agents = _agents()
        by_id = {a["id"]: a for a in agents}
        cohorts = partition_cohorts(agents)
        big = max(cohorts, key=lambda c: c.size)
        kwargs = {"day": 1, "budget": 10, "audit_fraction": 0.05}
        plain = select_materialized(cohorts, by_id, rng=np.random.default_rng(1), **kwargs)
        boosted = select_materialized(
            cohorts, by_id, rng=np.random.default_rng(1), audit_boost={big.id: 4}, **kwargs
        )

        def in_big(plan):
            return sum(1 for m in plan.audit if m in set(big.members))

        self.assertGreater(in_big(boosted), in_big(plain))
        others = [m for m in plain.audit if m not in set(big.members)]
        self.assertEqual(len(others), sum(1 for m in boosted.audit if m not in set(big.members)))

    def test_alarms_double_up_to_the_cap_and_quiet_days_step_down(self):
        boost, quiet = {}, {}
        hot = [{"cohort_id": "c001", "sample_size": 2, "residual_l1": 0.3}]
        calm = [{"cohort_id": "c001", "sample_size": 2, "residual_l1": 0.01}]
        seen = []
        for residuals in [hot, hot, hot, hot, calm, calm, calm, calm, calm, calm]:
            adapt_audit_boost(
                boost, quiet, residuals, alarm=0.08, factor=2, max_multiplier=8, cooldown_days=3
            )
            seen.append(boost.get("c001", 1))
        self.assertEqual(seen, [2, 4, 8, 8, 8, 8, 4, 4, 4, 2])
        changes = adapt_audit_boost({}, {}, hot, alarm=0.08)
        self.assertEqual(changes, [{"cohort_id": "c001", "from": 1, "to": 2, "residual_l1": 0.3}])
        self.assertEqual(
            adapt_audit_boost({}, {}, [{"cohort_id": "c", "sample_size": 0, "residual_l1": 9}], alarm=0.08),
            [],
        )


class GroupDayTests(unittest.TestCase):
    def _day(self, plugin, ctx, agents, day, individual=lambda agent: None):
        hook = {"agents": agents, "day": day, "env_context": "台风预警"}
        for handler in ctx.bus.handlers["on_day_start"]:
            handler(hook)
        (digest_filter,) = ctx.bus.handlers["fast_forward.digest_agents"]
        briefed = digest_filter(agents, hook)
        for agent in briefed:
            individual(agent)
        for handler in ctx.bus.handlers["on_day_end"]:
            handler(hook)
        return briefed

    def test_cohorts_move_the_rest_and_the_brief_runs_for_the_materialised(self):
        calls = []
        ctx = _Ctx(_group_config(), llm=lambda prompt, **kw: calls.append(kw) or _COHORT_DIGEST)
        plugin = GroupPlugin()
        plugin.setup(ctx)
        agents = _agents()
        before = {a["id"]: dict(a["state"]) for a in agents}
        briefed = self._day(plugin, ctx, agents, 1)

        briefed_ids = {a["id"] for a in briefed}
        (day_row,) = ctx.recorder.table("group.day")
        self.assertEqual(
            briefed_ids, set(day_row["plan"]["focal"] + day_row["plan"]["tail"] + day_row["plan"]["audit"])
        )
        self.assertTrue(0 < len(briefed) < len(agents))
        self.assertEqual(len(calls), day_row["cohorts"])
        self.assertTrue(all(kw["task"] == "group_cohort_day" for kw in calls))
        for agent in agents:
            moved = agent["state"]["stress"] - before[agent["id"]]["stress"]
            if agent["id"] in briefed_ids:
                self.assertEqual(agent["state"], before[agent["id"]])
            elif before[agent["id"]]["stress"] < 0.9:
                self.assertAlmostEqual(moved, 0.05, places=6)
            # The brief cannot move voice_propensity, so neither may the cohort.
            self.assertEqual(agent["state"]["voice_propensity"], before[agent["id"]]["voice_propensity"])
        self.assertIn("voice_propensity", set(before[agents[0]["id"]]) - set(LONG_RUN_STATE_KEYS))
        self.assertEqual(day_row["full_individual_calls"], len(agents))
        self.assertEqual(day_row["cohort_calls"] + day_row["individual_calls"], len(calls) + len(briefed))
        self.assertEqual(len(ctx.recorder.table("group.partition")), 1)

    def test_individuals_that_disagree_with_their_cohort_raise_its_audit(self):
        ctx = _Ctx(_group_config(residual_alarm=0.08), llm=lambda prompt, **kw: _COHORT_DIGEST)
        plugin = GroupPlugin()
        plugin.setup(ctx)
        agents = _agents()

        def contrary(agent):  # the cohort said stress +0.05; the brief says -0.3
            agent["state"]["stress"] = max(0.0, agent["state"]["stress"] - 0.3)

        self._day(plugin, ctx, agents, 1, contrary)
        first = ctx.recorder.table("group.day")[0]
        self.assertTrue(first["alarms"])
        self.assertTrue(all(change["to"] == 2 for change in first["boost_changes"]))
        self.assertEqual(set(first["audit_boost"]), set(first["alarms"]))
        self._day(plugin, ctx, agents, 2, contrary)
        second = ctx.recorder.table("group.day")[1]
        self.assertGreater(len(second["plan"]["audit"]), len(first["plan"]["audit"]))

        for handler in ctx.bus.handlers["on_simulation_end"]:
            handler({"agents": agents})
        (summary,) = ctx.recorder.table("group.summary")
        self.assertEqual(summary["days"], 2)
        self.assertTrue(summary["cohorts_boosted"])

    def test_without_brief_llm_no_cohort_calls_are_made(self):
        calls = []
        config = _group_config()
        config["long_run"]["brief_llm"] = False
        ctx = _Ctx(config, llm=lambda prompt, **kw: calls.append(1) or _COHORT_DIGEST)
        plugin = GroupPlugin()
        plugin.setup(ctx)
        self._day(plugin, ctx, _agents(), 1)
        self.assertEqual(calls, [])
        self.assertEqual(ctx.recorder.table("group.day")[0]["cohort_calls"], 0)

    def test_industry_comes_from_the_job_when_the_corpus_has_none(self):
        agents = [
            {"id": i, "age": 30, "hukou": "本地", "job": job, "state": {"stress": 0.5}}
            for i, job in enumerate(
                [
                    "程序员",
                    "算法工程师",
                    "后端研发",
                    "产品经理",
                    "外卖骑手物流",
                    "快递物流",
                    "门店店员",
                    "客服专员",
                ]
            )
        ]
        ctx = _Ctx(_group_config(cohort_axes=["industry"], min_cohort_size=2), llm=None)
        plugin = GroupPlugin()
        plugin.setup(ctx)
        cohorts = plugin._partition(agents)
        self.assertEqual({c.key for c in cohorts}, {("tech",), ("service",)})


def _has(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


@unittest.skipUnless(all(_has(m) for m in ("networkx", "matplotlib")), "needs the simulator's deps")
class GroupRunE2ETest(unittest.TestCase):
    """A 2-day group-mode fast-forward run of the real main loop, mock LLM."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shutil.copytree(os.path.join(repo_root, "data"), os.path.join(self.tmp.name, "data"))
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)

    def test_group_run(self) -> None:
        import generative_city_sim as sim
        from gaworld.settings import CONFIG

        ids = list(range(1, 13))
        patched = {
            "agent_ids": ids,
            "sim_days": 2,
            "stateful": False,
            "simulate_realtime": False,
            "seconds_per_day": 1,
            "random_seed": 7,
            "simulation_mode": "group",
            "long_run": {"enabled": True, "unit": "day", "brief_llm": True, "max_state_delta": 0.15},
            "group": {**CONFIG.get("group", {}), "materialization_budget": 3, "audit_fraction": 0.1},
        }
        for key, sub in (
            ("news", "enabled"),
            ("intervention", "enabled"),
            ("external_environment_service", "enabled"),
            ("distributed", "enabled"),
            ("visualization", "enabled"),
            ("life_events", "enabled"),
        ):
            if isinstance(CONFIG.get(key), dict):
                patched[key] = {**CONFIG[key], sub: False}
        if isinstance(CONFIG.get("news"), dict):
            patched["news"]["info_seek"] = {**CONFIG["news"].get("info_seek", {}), "enabled": False}
        if isinstance(CONFIG.get("external_rag"), dict):
            patched["external_rag"] = {
                **CONFIG["external_rag"],
                "bootstrap": {**CONFIG["external_rag"].get("bootstrap", {}), "enabled": False},
            }
        originals = {key: CONFIG[key] for key in patched if key in CONFIG}
        self.addCleanup(
            lambda: ([CONFIG.pop(k, None) for k in patched if k not in originals], CONFIG.update(originals))
        )
        CONFIG.update(patched)

        names = (
            "AGENT_IDS",
            "SIM_DAYS",
            "STATEFUL",
            "SIMULATE_REALTIME",
            "SECONDS_PER_DAY",
            "NEWS_ENABLED",
            "INTERVENTION_ENABLED",
            "HUMAN_REALISM_ENABLED",
            "VISUALIZATION_ENABLED",
            "LIFE_EVENTS_ENABLED",
            "LONG_RUN_ENABLED",
            "LONG_RUN_UNIT",
        )
        saved = {name: getattr(sim, name) for name in names if hasattr(sim, name)}
        self.addCleanup(lambda: [setattr(sim, k, v) for k, v in saved.items()])
        sim.AGENT_IDS, sim.SIM_DAYS, sim.STATEFUL = ids, 2, False
        sim.SIMULATE_REALTIME, sim.SECONDS_PER_DAY = False, 1
        sim.NEWS_ENABLED = sim.INTERVENTION_ENABLED = sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = sim.LIFE_EVENTS_ENABLED = False
        sim.LONG_RUN_ENABLED, sim.LONG_RUN_UNIT = True, "day"

        with install() as mock:
            mock.set_response("group_cohort_day", _COHORT_DIGEST)
            sim.run_simulation()

        records = os.path.join(self.tmp.name, CONFIG.get("records", {}).get("output_dir", "output/records"))
        with open(os.path.join(records, "group.day.jsonl"), encoding="utf-8") as handle:
            days = [json.loads(line) for line in handle if line.strip()]
        self.assertEqual([d["day"] for d in days], [1, 2])
        materialized = sum(d["plan"]["total"] for d in days)
        self.assertEqual(mock.call_count("fast_forward_day"), materialized)
        self.assertLess(materialized, len(ids) * 2)
        self.assertEqual(mock.call_count("group_cohort_day"), sum(d["cohorts"] for d in days))

        state_dir = os.path.join(self.tmp.name, CONFIG.get("state_output_dir", "output/state"))
        import pandas as pd

        history = pd.read_csv(os.path.join(state_dir, "agent_state_history.csv"))
        id_col = "agent_id" if "agent_id" in history.columns else history.columns[0]
        counts = history.groupby(id_col).size()
        self.assertEqual(sorted(counts.index.tolist()), ids)
        self.assertEqual(counts.nunique(), 1, counts.to_dict())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
