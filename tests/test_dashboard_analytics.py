"""Tests for the Analytics readers in ``gaworld.apps.analytics``.

Each reader is exercised against a synthetic ``output/`` tree in a temp dir, so
the assertions do not depend on whatever the last real run happened to leave
behind. The empty-tree cases matter as much as the populated ones: the
dashboard renders before a simulation has ever been run.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from gaworld.apps import analytics

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "site" / "dashboard"
CONSOLE = ROOT / "site" / "console"

NAMES = {40: "邓思琦", 33: "钱福生"}


def _out(root, *parts):
    """The artifact dir a reader takes, inside a seeded temp tree."""
    return os.path.join(root, "output", *parts)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _write_json(path, payload):
    _write(path, json.dumps(payload, ensure_ascii=False))


def _seed(root):
    _write(
        os.path.join(root, "output", "state", "agent_state_history.csv"),
        "agent_id,step,metric,value\n"
        "40,0,emotion,0.60\n40,1,emotion,0.50\n40,2,emotion,0.80\n"
        "40,0,stress,0.20\n40,1,stress,0.20\n40,2,stress,0.20\n"
        "33,0,emotion,0.40\n33,1,emotion,0.30\n33,2,emotion,0.20\n",
    )
    _write(
        os.path.join(root, "output", "economy", "daily_ledger.csv"),
        "day,agent_id,income,expense,net,balance,checking,savings,investment,"
        "housing_fund,debt,wealth_drive,hourly_income,econ_security,"
        "engel_coefficient,macro_phase\n"
        "1,40,100,40,60,1000,500,300,200,0,0,0.6,20,0.5,0.38,expansion\n"
        "2,40,110,50,60,1060,540,320,200,0,0,0.6,21,0.6,0.37,expansion\n"
        "2,33,0,30,-30,500,500,0,0,0,0,0.4,10,0.3,0.44,recession\n",
    )
    _write(
        os.path.join(root, "output", "economy", "wealth_snapshot.csv"),
        "agent_id,currency,balance,checking,savings,investment,housing_fund,debt,"
        "gross_monthly_salary,net_monthly_salary,monthly_tax,monthly_si_total,"
        "engel_coefficient,savings_rate,lifetime_income,lifetime_expense,wealth_drive,"
        "base_hourly_income,hourly_income,income_target_daily,portfolio_type,"
        "investment_return_ytd,initial_labor_savings,initial_inheritance,initial_assets_total\n"
        "40,CNY,1060,540,320,200,0,0,4000,3200,300,500,0.37,0.1,210,90,0.6,20,21,150,moderate,5,900,0,900\n"
        "33,CNY,500,500,0,0,0,0,0,0,0,0,0.44,0.0,0,30,0.4,10,10,80,conservative,0,500,0,500\n",
    )
    _write(
        os.path.join(root, "output", "economy", "conservation_audit.csv"),
        "day,agents_total,firms,government,bank,system_total,drift\n"
        "1,1500,10,5,0,1515,0.0\n2,1560,10,5,0,1575,0.0\n",
    )
    _write_json(
        os.path.join(root, "output", "economy", "macro_state.json"),
        {"phase": "expansion", "inflation_rate": 0.025, "unemployment_rate": 0.052},
    )
    # Agent 40 and 33 know each other; each also carries a private ghost tie.
    _write_json(
        os.path.join(root, "output", "memory", "agent_40_relationships.json"),
        {
            "33": {"kind": "agent", "role": "friend", "closeness": 0.7, "trust": 0.6,
                   "dunbar_tier": "close", "profile": {"name": "钱福生"}},
            "g_mother": {"kind": "ghost", "role": "mother", "closeness": 0.9, "trust": 0.9,
                         "dunbar_tier": "inner", "profile": {"name": "母亲"}},
        },
    )
    _write_json(
        os.path.join(root, "output", "memory", "agent_33_relationships.json"),
        {
            "40": {"kind": "agent", "role": "friend", "closeness": 0.5, "trust": 0.8,
                   "dunbar_tier": "close", "profile": {"name": "邓思琦"}},
        },
    )
    _write_json(
        os.path.join(root, "output", "memory", "agent_40_locations.json"),
        {
            "home": "北山街道", "workplace": "西溪街道", "transport_mode": "bike",
            "frequent_places": {"西溪街道": 5, "北山街道": 2},
            "preferred_modes": {"bike": 4, "metro": 1},
        },
    )
    _write_json(
        os.path.join(root, "output", "memory", "agent_40_habits.json"),
        {
            "morning|work|通勤": {"strength": 0.4, "preferred_action": "骑车上班", "last_updated_day": 2},
            "evening|home|阅读": {"strength": 0.2, "preferred_action": "读书", "last_updated_day": 2},
        },
    )
    _write_json(
        os.path.join(root, "output", "memory", "agent_40_schedule.json"),
        [{"time": "08:30", "activity": "上班"}, {"time": "20:00", "activity": "阅读"}],
    )
    _write_json(
        os.path.join(root, "output", "visualization", "simulation_trace.json"),
        {
            "meta": {"finished": True, "generated_at": "2026-07-24T06:00:00Z",
                     "sim_meta": {"sim_days": 2}},
            "frames": [
                {"index": 0, "day": 1, "date": "2026-08-01", "policy": {},
                 "env_events": [{"id": "e1", "type": "natural", "topic": "weather",
                                 "name": "晴朗", "severity": 0.2, "scope": "city",
                                 "impact_tags": ["mobility", "emotion"]}]},
                # Same id repeated: an event spanning frames must count once.
                {"index": 1, "day": 2, "date": "2026-08-02", "policy": {},
                 "env_events": [{"id": "e1", "type": "natural", "topic": "weather",
                                 "name": "晴朗", "severity": 0.2, "scope": "city",
                                 "impact_tags": ["mobility"]},
                                {"id": "e2", "type": "policy", "topic": "transit",
                                 "name": "限行", "severity": 0.6, "scope": "city",
                                 "impact_tags": ["mobility"]}]},
            ],
        },
    )
    _write(os.path.join(root, "output", "diaries", "agent_40", "day_001.md"), "# 日记")
    _write(os.path.join(root, "output", "diaries", "agent_40", "day_002.md"), "# 日记")


class AnalyticsReadersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        _seed(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_state_history_orders_series_and_computes_deltas(self):
        payload = analytics.state_history(_out(self.root), NAMES)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["metrics"], ["emotion", "stress"])
        self.assertEqual(payload["steps"], 3)
        self.assertEqual(payload["series"]["emotion"]["40"], [0.6, 0.5, 0.8])
        stats = payload["deltas"]["emotion"]["40"]
        self.assertEqual(stats["first"], 0.6)
        self.assertEqual(stats["last"], 0.8)
        self.assertAlmostEqual(stats["delta"], 0.2, places=6)
        self.assertEqual(stats["min"], 0.5)
        self.assertEqual(stats["max"], 0.8)
        self.assertEqual(
            [agent["name"] for agent in payload["agents"]], ["钱福生", "邓思琦"]
        )

    def test_state_history_downsamples_long_series(self):
        root = tempfile.mkdtemp()
        rows = ["agent_id,step,metric,value"]
        total = analytics.MAX_SERIES_POINTS * 3
        for step in range(total):
            rows.append(f"7,{step},emotion,{step / total:.4f}")
        _write(os.path.join(root, "output", "state", "agent_state_history.csv"), "\n".join(rows))
        payload = analytics.state_history(_out(root))
        series = payload["series"]["emotion"]["7"]
        self.assertEqual(len(series), analytics.MAX_SERIES_POINTS)
        self.assertTrue(payload["sampled"])
        # The final observation survives thinning — the delta charts read it.
        self.assertAlmostEqual(series[-1], (total - 1) / total, places=4)
        # Deltas are computed on the full series, not the thinned one.
        self.assertEqual(payload["deltas"]["emotion"]["7"]["first"], 0.0)

    def test_economy_groups_by_agent_and_reads_macro(self):
        payload = analytics.economy(_out(self.root), NAMES)
        self.assertTrue(payload["available"])
        ledger = {item["id"]: item for item in payload["ledger"]}
        self.assertEqual(ledger[40]["days"], [1, 2])
        self.assertEqual(ledger[40]["balance"], [1000.0, 1060.0])
        self.assertEqual(ledger[40]["name"], "邓思琦")
        self.assertEqual(payload["macro"]["phase"], "expansion")
        self.assertEqual(payload["conservation"]["day"], 2)
        self.assertEqual(payload["conservation"]["system_total"], 1575.0)
        # Wealth is ranked richest first.
        self.assertEqual([item["id"] for item in payload["wealth"]], [40, 33])
        self.assertEqual(payload["macro_timeline"][0], {"day": 1, "phase": "expansion"})

    def test_social_collapses_reciprocal_agent_ties(self):
        payload = analytics.social(_out(self.root, "memory"), NAMES)
        self.assertTrue(payload["available"])
        edges = {(link["source"], link["target"]) for link in payload["links"]}
        self.assertIn(("33", "40"), edges)
        self.assertEqual(len(payload["links"]), 2)  # one agent tie + one ghost tie
        agent_link = next(link for link in payload["links"] if link["target"] == "40")
        # Both directions are merged, keeping the stronger reading of each field.
        self.assertEqual(agent_link["closeness"], 0.7)
        self.assertEqual(agent_link["trust"], 0.8)
        kinds = {node["id"]: node["kind"] for node in payload["nodes"]}
        self.assertEqual(kinds["40"], "agent")
        self.assertEqual(kinds["33"], "agent")
        self.assertEqual(kinds["40:g_mother"], "ghost")
        self.assertEqual(payload["tier_counts"]["close"], 2)

    def test_behavior_aggregates_places_modes_and_habits(self):
        payload = analytics.behavior(_out(self.root, "memory"), NAMES)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["places"][0], {"name": "西溪街道", "visits": 5})
        self.assertEqual({item["mode"] for item in payload["modes"]}, {"bike", "metro"})
        self.assertEqual(payload["heatmap"]["periods"], ["morning", "evening"])
        self.assertIn("work", payload["heatmap"]["contexts"])
        self.assertEqual(payload["habits"][0]["activity"], "通勤")
        self.assertEqual(payload["habits"][0]["name"], "邓思琦")
        hours = {item["hour"]: item["count"] for item in payload["schedule_hours"]}
        self.assertEqual(len(payload["schedule_hours"]), 24)
        self.assertEqual(hours[8], 1)
        self.assertEqual(hours[20], 1)
        self.assertEqual(hours[3], 0)

    def test_events_deduplicates_by_id(self):
        payload = analytics.events(_out(self.root, "visualization"))
        self.assertTrue(payload["available"])
        # "e1" spans both frames but is counted once.
        self.assertEqual(payload["type_counts"], {"natural": 1, "policy": 1})
        self.assertEqual(payload["impact_counts"]["mobility"], 2)
        self.assertEqual(len(payload["timeline"]), 2)
        self.assertEqual(payload["timeline"][1]["events"][0]["name"], "限行")

    def test_overview_summarizes_run(self):
        payload = analytics.overview(
            _out(self.root),
            _out(self.root, "memory"),
            _out(self.root, "visualization"),
            _out(self.root, "diaries"),
            NAMES,
        )
        self.assertEqual(payload["agent_count"], 2)
        self.assertEqual(payload["metric_count"], 2)
        self.assertEqual(payload["step_count"], 3)
        self.assertEqual(payload["frame_count"], 2)
        self.assertEqual(payload["day_span"], {"first": 1, "last": 2})
        self.assertEqual(payload["event_total"], 3)  # raw frame entries, not deduped
        self.assertEqual(payload["diary_count"], 2)
        self.assertEqual(payload["relationship_total"], 3)
        self.assertTrue(payload["finished"])
        movers = {item["metric"]: item["mean_delta"] for item in payload["top_movers"]}
        # emotion: agent 40 gains 0.2, agent 33 loses 0.2 → mean 0.
        self.assertAlmostEqual(movers["emotion"], 0.0, places=6)
        self.assertEqual(movers["stress"], 0.0)


class AnalyticsEmptyTreeTest(unittest.TestCase):
    """A dashboard opened before any run must not raise."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_reader_degrades_to_empty(self):
        self.assertFalse(analytics.state_history(_out(self.root))["available"])
        self.assertFalse(analytics.economy(_out(self.root))["available"])
        self.assertFalse(analytics.social(_out(self.root, "memory"))["available"])
        self.assertFalse(analytics.behavior(_out(self.root, "memory"))["available"])
        self.assertFalse(analytics.events(_out(self.root, "visualization"))["available"])
        overview = analytics.overview(
            _out(self.root),
            _out(self.root, "memory"),
            _out(self.root, "visualization"),
            _out(self.root, "diaries"),
        )
        self.assertEqual(overview["agent_count"], 0)
        self.assertIsNone(overview["day_span"])

    def test_malformed_artifacts_are_skipped(self):
        _write(
            os.path.join(self.root, "output", "state", "agent_state_history.csv"),
            "agent_id,step,metric,value\nx,0,emotion,0.5\n40,0,emotion,oops\n40,0,,0.5\n",
        )
        _write(os.path.join(self.root, "output", "visualization", "simulation_trace.json"), "{not json")
        self.assertFalse(analytics.state_history(_out(self.root))["available"])
        self.assertFalse(analytics.events(_out(self.root, "visualization"))["available"])


class AnalyticsRoutingTest(unittest.TestCase):
    def test_dashboard_server_dispatches_every_section(self):
        import gaworld.apps.dashboard_server as ds

        for section in ("overview", "state-history", "economy", "social", "behavior", "events"):
            with self.subTest(section=section):
                self.assertIsInstance(ds._analytics_payload(section), dict)
        self.assertIsNone(ds._analytics_payload("nope"))


class AnalyticsRunSelectionTest(unittest.TestCase):
    """Past runs are analysable, and each is read from its own artifacts."""

    def setUp(self):
        import gaworld.apps.dashboard_server as ds

        self.ds = ds
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _seed(self.root)  # the live tree
        # A scenario run with its own, different artifacts.
        self.scenario = os.path.join(self.root, "output", "comparisons", "限行", "with_event")
        _write(
            os.path.join(self.scenario, "state", "agent_state_history.csv"),
            "agent_id,step,metric,value\n33,0,emotion,0.10\n33,1,emotion,0.90\n",
        )
        _write_json(
            os.path.join(self.scenario, "visualization", "simulation_trace.json"),
            {"meta": {"finished": True}, "frames": []},
        )
        # An archived run: the visualizer copies the trace and nothing else.
        _write_json(
            os.path.join(self.root, "output", "visualization", "runs", "r1", "simulation_trace.json"),
            {"meta": {"finished": True}, "frames": []},
        )
        self._real_root = ds.REPO_ROOT
        ds.REPO_ROOT = self.root

    def tearDown(self):
        self.ds.REPO_ROOT = self._real_root
        self._tmp.cleanup()

    def _run(self, kind):
        return next(item for item in self.ds._analytics_runs() if item["kind"] == kind)

    def test_runs_are_listed_with_their_available_sections(self):
        runs = self.ds._analytics_runs()
        self.assertEqual(runs[0]["kind"], "live")  # the current run stays first
        self.assertTrue(all(run["sections"]["events"] for run in runs))
        live = self._run("live")
        self.assertTrue(live["sections"]["economy"])
        self.assertTrue(live["sections"]["social"])
        scenario = self._run("scenario")
        self.assertTrue(scenario["sections"]["state-history"])
        self.assertFalse(scenario["sections"]["economy"])  # that run had none
        # An archive holds only its trace; its siblings belong to a later run.
        archive = self._run("archive")
        self.assertEqual(
            [key for key, ok in archive["sections"].items() if ok], ["events"]
        )

    def test_a_past_run_is_read_from_its_own_tree(self):
        paths = self.ds._analytics_run_paths(self._run("scenario")["id"])
        self.assertEqual(paths["output_dir"], self.scenario)
        payload = self.ds._analytics_payload("state-history", paths)
        # The scenario's own CSV, not the live tree's.
        self.assertEqual(payload["series"]["emotion"]["33"], [0.1, 0.9])
        self.assertNotIn("40", payload["series"]["emotion"])

    def test_an_archived_run_does_not_borrow_the_live_artifacts(self):
        paths = self.ds._analytics_run_paths(self._run("archive")["id"])
        self.assertFalse(self.ds._analytics_payload("state-history", paths)["available"])
        self.assertFalse(self.ds._analytics_payload("social", paths)["available"])

    def test_no_run_id_means_the_current_run(self):
        self.assertEqual(
            self.ds._analytics_run_paths(""), self.ds._analytics_run_paths(self._run("live")["id"])
        )

    def test_an_unlisted_run_id_is_refused(self):
        self.assertIsNone(self.ds._analytics_run_paths("output/../../etc"))
        self.assertIsNone(self.ds._analytics_run_paths("output/visualization/runs/nope"))


class AnalyticsFrontendTest(unittest.TestCase):
    def test_page_mounts_its_assets(self):
        html = (DASHBOARD / "analytics.html").read_text(encoding="utf-8")
        self.assertIn("analytics.css", html)
        self.assertIn("analytics.js", html)
        # Every element the script writes into must exist in the markup.
        script = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")
        for target in sorted(set(re.findall(r'\$\("(an[A-Za-z]+)"\)', script))):
            self.assertIn('id="' + target + '"', html, f"missing #{target} in analytics.html")

    def test_page_offers_the_run_picker(self):
        html = (DASHBOARD / "analytics.html").read_text(encoding="utf-8")
        script = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")
        self.assertIn('<select id="anRunSelect">', html)
        self.assertIn("/api/analytics/runs", script)
        # Every section has to follow the picked run, not just the first one.
        self.assertIn('api("/api/analytics/" + name, state.runId ? { run: state.runId } : null)', script)
        for name in ("overview", "state-history", "economy", "social", "behavior", "events"):
            self.assertIn('section("' + name + '")', script)

    def test_rendered_text_is_escaped(self):
        # Agent names, place names and event titles are model-authored, so every
        # interpolation into innerHTML has to run through esc().
        script = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")
        self.assertIn("function esc(text)", script)
        for label in ("item.label", "node.label", "event.name", "habit.activity"):
            self.assertIn("esc(" + label, script)

    def test_export_menu_offers_every_format(self):
        html = (DASHBOARD / "analytics.html").read_text(encoding="utf-8")
        script = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")
        self.assertIn("analytics-export.js", html)
        # The loader has to run before analytics.js reads the global off window.
        self.assertLess(
            html.index("analytics-export.js"), html.index('src="/site/dashboard/analytics.js')
        )
        for kind in ("html", "json", "csv", "md"):
            self.assertIn(f'data-export="{kind}"', html)
        self.assertIn("window.GAWorldAnalyticsExport", script)
        # The report snapshots the live DOM, so the interactive chrome has to
        # be stripped or the exported file ships dead buttons.
        self.assertIn(".hero-status, .an-pickers, .help-tip, .an-export", script)

    def test_export_builders_node_suite(self):
        result = subprocess.run(
            ["node", "--test", str(DASHBOARD / "analytics-export.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_console_registers_the_analytics_tab(self):
        console_js = (CONSOLE / "console.js").read_text(encoding="utf-8")
        console_html = (CONSOLE / "index.html").read_text(encoding="utf-8")
        self.assertIn('{ id: "analytics", src: "/site/dashboard/analytics.html" }', console_js)
        self.assertIn('data-tab="analytics"', console_html)


if __name__ == "__main__":
    unittest.main()
