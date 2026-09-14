"""The 家庭 card: its backend, its wiring, and the config section behind it.

Three failure modes worth pinning, all of which have already happened once in
this repo's history for other subsystems:

1. **A config fragment that no panel section claims.** ``CONFIG["family"]`` is
   composed by ``build_default_config``, but the 配置 panel is generated from
   the ``SECTIONS`` registry in ``config_docs``. Adding the fragment without
   registering it leaves the whole subsystem un-tunable from the browser while
   looking fine from Python — exactly the gap this file exists to close.
2. **A panel that renders before there is any data.** The card reads recorder
   output; a fresh checkout has none, and "no run yet" must be an empty card,
   not a stack trace.
3. **Escaping.** Resident names come from a Markdown profile an operator can
   edit, so they reach the DOM as untrusted text.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import family_api

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")


def _read(*parts):
    with open(os.path.join(DASHBOARD, *parts), encoding="utf-8") as handle:
        return handle.read()


class ConfigSectionTests(unittest.TestCase):
    def test_every_config_fragment_has_a_panel_section(self):
        """The regression guard: a fragment nobody claims is invisible."""
        from gaworld.settings import build_default_config
        from gaworld.settings.config_docs import SECTION_EXTRA_KEYS, section_index

        index = section_index()
        claimed = set(index) | {k for keys in SECTION_EXTRA_KEYS.values() for k in keys}
        unclaimed = sorted(set(build_default_config()) - claimed)
        self.assertEqual(unclaimed, [], f"config keys with no 配置 panel section: {unclaimed}")

    def test_family_is_its_own_section(self):
        from gaworld.settings.config_docs import section_index, section_meta

        self.assertEqual(section_index().get("family"), "family")
        meta = {item["id"]: item for item in section_meta()}
        self.assertIn("family", meta)
        self.assertTrue(meta["family"]["title"])
        self.assertTrue(meta["family"]["help"])

    def test_the_knobs_an_operator_reaches_for_are_documented_in_chinese(self):
        from gaworld.settings.config_docs import help_for, label_for

        for path in (
            "family.pairing.in_sim_pair_share",
            "family.fertility.p_any_child",
            "family.events.contagion_weight",
            "family.finance.child_cost_monthly",
            "family.marital_status_bands",
        ):
            with self.subTest(path=path):
                self.assertTrue(label_for(path) != path.rsplit(".", 1)[-1], "needs a label")
                text = help_for(path)
                self.assertTrue(text, "needs help text")
                self.assertRegex(text, r"[一-鿿]", "help text should be Chinese")

    def test_no_family_tooltip_is_left_in_english(self):
        """Every other section's tooltips are Chinese; a half-translated
        section reads like a bug to the operator."""
        from gaworld.settings.config_docs import MANUAL_HELP, source_help

        english = [
            key
            for key, value in source_help().items()
            if key.startswith("family")
            and value
            and key not in MANUAL_HELP
            and not re.search(r"[一-鿿]", value)
        ]
        self.assertEqual(english, [])

    def test_the_panel_can_actually_save_a_family_patch(self):
        """Registering the section only puts the knobs on screen; the save
        path coerces every patch against the effective config and silently
        drops what it does not recognise, so the round trip needs its own
        check — including the nested list-of-dicts knobs."""
        from gaworld.apps.external_systems_api import _coerce_like
        from gaworld.settings import build_default_config

        family = build_default_config()["family"]
        dropped: list[str] = []
        patch = _coerce_like(
            family,
            {
                "pairing": {"in_sim_pair_share": 0.2},
                "events": {"contagion_weight": 0.0},
                "fertility": {"p_any_child": [{"age": [0, 200], "p": 0.1}]},
            },
            "family",
            dropped,
        )
        self.assertEqual(dropped, [])
        self.assertEqual(patch["pairing"]["in_sim_pair_share"], 0.2)
        self.assertEqual(patch["events"]["contagion_weight"], 0.0)
        self.assertEqual(patch["fertility"]["p_any_child"][0]["p"], 0.1)

    def test_the_pairing_share_tooltip_states_it_is_a_modelling_choice(self):
        """This knob is the one place the model knowingly departs from
        demography; a tooltip that hides that invites it being read as a
        measured rate."""
        from gaworld.settings.config_docs import help_for

        text = help_for("family.pairing.in_sim_pair_share")
        self.assertIn("0", text)
        self.assertTrue(
            any(word in text for word in ("取舍", "不是人口学事实", "建模")),
            "the tooltip must say this is a modelling choice",
        )


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        original = ds.RECORDS_DIR
        self.addCleanup(lambda: setattr(ds, "RECORDS_DIR", original))
        ds.RECORDS_DIR = self.tmp.name

    def _write(self, table, rows):
        with open(os.path.join(self.tmp.name, f"{table}.jsonl"), "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_no_run_yet_is_an_empty_payload_not_an_error(self):
        payload, status = family_api.handle_get("/api/family/overview", {})
        self.assertEqual(status, 200)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["agents"], [])

    def test_overview_reads_the_recorded_run(self):
        self._write("family.summary", [{"agents": 2, "households": 1, "in_sim_couples": 1}])
        self._write("family.household", [{"id": "hh_001", "type": "nuclear", "agent_ids": [1, 2]}])
        self._write(
            "family.agent",
            [
                {"agent_id": 1, "name": "甲", "household_id": "hh_001",
                 "household_type": "nuclear", "marital_status": "married", "members": []},
                {"agent_id": 2, "name": "乙", "household_id": "hh_001",
                 "household_type": "nuclear", "marital_status": "married", "members": []},
            ],
        )
        payload, status = family_api.handle_get("/api/family/overview", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["summary"]["in_sim_couples"], 1)
        self.assertEqual([a["agent_id"] for a in payload["agents"]], [1, 2])

    def test_a_rerun_appends_and_the_latest_row_wins(self):
        """The recorder appends; two runs in one output dir must not show the
        same household twice, or every count doubles."""
        self._write(
            "family.agent",
            [
                {"agent_id": 1, "name": "甲", "household_type": "single", "marital_status": "never"},
                {"agent_id": 1, "name": "甲", "household_type": "couple", "marital_status": "married"},
            ],
        )
        payload, _ = family_api.handle_get("/api/family/overview", {})
        self.assertEqual(len(payload["agents"]), 1)
        self.assertEqual(payload["agents"][0]["household_type"], "couple")

    def test_summary_is_derived_when_only_agent_rows_exist(self):
        self._write(
            "family.agent",
            [
                {"agent_id": 1, "household_type": "single", "marital_status": "never"},
                {"agent_id": 2, "household_type": "couple", "marital_status": "married"},
            ],
        )
        payload, _ = family_api.handle_get("/api/family/overview", {})
        self.assertEqual(payload["summary"]["marital_statuses"], {"never": 1, "married": 1})

    def test_finance_is_totalled_per_household(self):
        self._write("family.agent", [{"agent_id": 1, "household_id": "hh_001"}])
        self._write(
            "family.finance",
            [
                {"household": "hh_001", "dependant_cost": 10.0, "partner_transfer": 0.0},
                {"household": "hh_001", "dependant_cost": 5.5, "partner_transfer": 2.0},
            ],
        )
        payload, _ = family_api.handle_get("/api/family/overview", {})
        self.assertAlmostEqual(payload["finance"]["hh_001"]["dependant_cost"], 15.5)
        self.assertAlmostEqual(payload["finance"]["hh_001"]["partner_transfer"], 2.0)
        self.assertEqual(payload["finance"]["hh_001"]["days"], 2)

    def test_single_agent_lookup(self):
        self._write("family.agent", [{"agent_id": 7, "name": "丙"}])
        payload, status = family_api.handle_get("/api/family/agent", {"agent_id": ["7"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "丙")
        _, status = family_api.handle_get("/api/family/agent", {"agent_id": ["999"]})
        self.assertEqual(status, 404)
        _, status = family_api.handle_get("/api/family/agent", {})
        self.assertEqual(status, 400)

    def test_unknown_endpoint_is_a_404(self):
        _, status = family_api.handle_get("/api/family/nope", {})
        self.assertEqual(status, 404)

    def test_a_corrupt_line_does_not_take_the_panel_down(self):
        with open(os.path.join(self.tmp.name, "family.agent.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"agent_id": 1, "name": "甲"}\n')
            fh.write("not json at all\n")
            fh.write('{"agent_id": 2, "name": "乙"}\n')
        payload, status = family_api.handle_get("/api/family/overview", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["agents"]), 2)


class StudioEditorApiTests(unittest.TestCase):
    """The Studio editor's endpoints. Unlike the card, these deliberately
    re-derive the assignment: the question is what happens *next* run."""

    def setUp(self):
        from gaworld.settings import CONFIG

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        original = CONFIG.get("family")
        self.addCleanup(lambda: CONFIG.__setitem__("family", original))
        CONFIG["family"] = dict(original)
        CONFIG["family"]["overrides_path"] = os.path.join(self.tmp.name, "overrides.json")

    def test_preview_returns_a_family_for_every_agent(self):
        payload, status = family_api.handle_get("/api/family/preview", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["agents"])
        for row in payload["agents"]:
            self.assertTrue(row["household_type"])
            self.assertTrue(row["marital_status"])

    def test_preview_for_one_agent_carries_the_editor_payload(self):
        payload, status = family_api.handle_get("/api/family/preview", {"agent_id": ["13"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["selected"]["agent_id"], 13)
        self.assertIn("weekday", payload["duties"])
        self.assertTrue(payload["candidates"])
        self.assertNotIn(13, [c["agent_id"] for c in payload["candidates"]])

    def test_a_bad_agent_id_is_a_400(self):
        _, status = family_api.handle_get("/api/family/preview", {"agent_id": ["abc"]})
        self.assertEqual(status, 400)

    def test_saving_an_override_changes_the_preview_and_marks_it_pinned(self):
        body = {
            "agent_id": 13,
            "override": {
                "marital_status": "married",
                "children": [
                    {"name": "测试小满", "gender": "女", "age": 4, "coresident": True}
                ],
            },
        }
        payload, status = family_api.handle_post("/api/family/override", body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["saved"])
        self.assertTrue(payload["selected"]["pinned"])
        self.assertIn("测试小满", payload["selected"]["brief"])
        self.assertTrue(os.path.exists(payload["path"]))

    def test_pinning_a_partner_changes_both_sides(self):
        body = {
            "agent_id": 13,
            "override": {
                "marital_status": "married",
                "partner": {"kind": "agent", "agent_id": 16, "role": "spouse"},
            },
        }
        payload, status = family_api.handle_post("/api/family/override", body)
        self.assertEqual(status, 200)
        rows = {row["agent_id"]: row for row in payload["agents"]}
        self.assertEqual(rows[13]["household_id"], rows[16]["household_id"])

    def test_invalid_edits_are_rejected_with_a_readable_message(self):
        payload, status = family_api.handle_post(
            "/api/family/override",
            {"agent_id": 13, "override": {"children": [{"name": "", "age": 3}]}},
        )
        self.assertEqual(status, 400)
        self.assertIn("姓名", payload["error"])

    def test_clearing_removes_the_pin(self):
        family_api.handle_post(
            "/api/family/override",
            {"agent_id": 13, "override": {"marital_status": "widowed"}},
        )
        payload, status = family_api.handle_post(
            "/api/family/override", {"agent_id": 13, "clear": True}
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["selected"]["pinned"])

    def test_saving_an_empty_edit_unpins_rather_than_storing_a_no_op(self):
        family_api.handle_post(
            "/api/family/override",
            {"agent_id": 13, "override": {"marital_status": "widowed"}},
        )
        payload, _ = family_api.handle_post(
            "/api/family/override", {"agent_id": 13, "override": {}}
        )
        self.assertFalse(payload["selected"]["pinned"])

    def test_missing_agent_id_is_a_400(self):
        _, status = family_api.handle_post("/api/family/override", {"override": {}})
        self.assertEqual(status, 400)

    def test_unknown_post_endpoint_is_a_404(self):
        _, status = family_api.handle_post("/api/family/nope", {})
        self.assertEqual(status, 404)

    def test_the_dashboard_server_forwards_both_verbs(self):
        path = os.path.join(REPO_ROOT, "gaworld", "apps", "dashboard_server.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertEqual(source.count('path.startswith("/api/family")'), 2)


class FrontendWiringTests(unittest.TestCase):
    def test_the_dashboard_hosts_the_card(self):
        html = _read("index.html")
        self.assertIn('id="familyOverview"', html)
        self.assertIn('id="familyDetail"', html)
        self.assertIn('data-i18n="family.title"', html)

    def test_the_card_is_loaded_and_refreshed(self):
        app = _read("app.js")
        self.assertIn("/api/family/overview", app)
        self.assertIn("loadFamily", app)
        # Switching residents must re-render the detail, or the card keeps
        # showing the previous person's family.
        self.assertIn("renderFamilyDetail()", app)

    def test_every_interpolation_is_escaped(self):
        """Resident and family-member names come from an operator-editable
        profile, so they are untrusted text by the time they reach innerHTML."""
        app = _read("app.js")
        start = app.index("function familyMemberChip")
        end = app.index("\n}", app.index("function renderFamilyDetail"))
        block = app[start:end]
        raw = re.findall(r"\$\{(?!escapeHtml|Number|`)([^}]+)\}", block)
        offenders = [
            expr.strip()
            for expr in raw
            # Numeric/boolean expressions and nested template calls are fine;
            # anything reading a `.name` / `.role` string is not.
            if re.search(r"\.(name|role|brief|household_id)\b", expr)
        ]
        self.assertEqual(offenders, [], f"unescaped interpolations: {offenders}")

    def test_the_studio_hosts_the_family_editor(self):
        studio = _read("studio.js")
        self.assertIn("familyCard", studio)
        self.assertIn("/api/family/override", studio)
        self.assertIn("/api/family/preview", studio)
        # The editor must live in step 5 (社交 · 关系), where the user asked
        # for it — not as a floating card somewhere else.
        social = studio[studio.index("function stepSocial()"):]
        self.assertIn("${familyCard()}", social[: social.index("\nasync function saveRelations")])

    def test_the_editor_explains_that_edits_apply_to_the_next_run(self):
        """Households are re-derived every run; an editor that does not say so
        invites the operator to expect a live change and conclude it is broken.

        The copy itself lives in the locale files now, so this checks the card
        renders that note *and* that neither language has lost the point of it.
        """
        studio = _read("studio.js")
        block = studio[studio.index("function familyCard()"):studio.index("async function saveFamilyOverride")]
        self.assertIn("sd.family_note", block)
        self.assertIn("family_overrides.json", block)

        locales = {}
        for name in ("zh-CN", "en"):
            with open(os.path.join(DASHBOARD, "locales", f"{name}.json"), encoding="utf-8") as fh:
                locales[name] = json.load(fh)["sd.family_note"]
        self.assertIn("每次运行开始时", locales["zh-CN"])
        self.assertIn("every run", locales["en"])
        for text in locales.values():
            # The note interpolates the file name, so the placeholder is what
            # has to survive here.
            self.assertIn("{file}", text)

    def test_the_design_doc_is_listed_in_the_docs_panel(self):
        docs = _read("docs.js")
        self.assertIn("/docs/FAMILY_DESIGN.md", docs)

    def test_both_locales_carry_the_card_keys(self):
        with open(os.path.join(DASHBOARD, "locales", "zh-CN.json"), encoding="utf-8") as fh:
            zh = json.load(fh)
        with open(os.path.join(DASHBOARD, "locales", "en.json"), encoding="utf-8") as fh:
            en = json.load(fh)
        for key in ("family.title", "family.empty", "family.coresident", "family.stat.single"):
            self.assertIn(key, zh)
            self.assertIn(key, en)

    def test_headless_render_suite_passes(self):
        """The Python tests can read app.js but cannot run it; this suite
        renders the card against a stubbed DOM and checks the output."""
        result = subprocess.run(
            ["node", "--test", os.path.join(DASHBOARD, "family-card.test.js")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_studio_editor_headless_suite_passes(self):
        result = subprocess.run(
            ["node", "--test", os.path.join(DASHBOARD, "studio-family.test.js")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_card_has_styles(self):
        css = _read("styles.css")
        for selector in (".family-stats", ".family-member", ".family-bar"):
            self.assertIn(selector, css)


if __name__ == "__main__":
    unittest.main()
