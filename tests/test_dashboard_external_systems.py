"""The External Systems panel: observation payloads, config edits, interventions.

Four failure modes drive the choice of what is covered here, because each one
would otherwise be invisible until a user hit it in the browser:

* **A single non-finite float kills the whole response.** The economy config's
  top tax bracket is ``float("inf")``; ``json.dumps`` emits a bare ``Infinity``
  token and ``JSON.parse`` rejects the *entire* body, so the panel renders
  "无法加载" with a green backend. That is a serialization test, not a UI one.
* **A config patch that writes the wrong shape corrupts the simulator's input.**
  The panel edits ~150 leaves through one generic coercion path, so the
  coercion is tested directly rather than field by field.
* **Routing delegation is a branch in a 60-branch if/elif chain.** The other
  helper-level tests never start a server, so a broken branch stays green.
* **A queued intervention that the simulator does not apply is a no-op that
  looks like a feature.** Covered end to end against the real consumer in
  ``gaworld.economy.finance``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import external_systems_api as api
from gaworld.economy import finance


class _TempRepo:
    """Point the dashboard's path constants at a scratch tree."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._saved = (ds.REPO_ROOT, ds.DASHBOARD_CONFIG_PATH)

    def __enter__(self):
        ds.REPO_ROOT = self.root
        ds.DASHBOARD_CONFIG_PATH = os.path.join(self.root, "dashboard_config.json")
        os.makedirs(os.path.join(self.root, "output", "economy"), exist_ok=True)
        return self

    def __exit__(self, *exc):
        ds.REPO_ROOT, ds.DASHBOARD_CONFIG_PATH = self._saved
        self.tmp.cleanup()
        return False

    def config(self):
        with open(ds.DASHBOARD_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


class OverviewTests(unittest.TestCase):
    def test_overview_carries_config_and_runtime_for_all_three_systems(self):
        with _TempRepo():
            payload = api.overview()
        for section in ("currency", "environment", "services"):
            self.assertIn(section, payload)
            self.assertIn("config", payload[section])
            self.assertIn("runtime", payload[section])
        self.assertIn("economy", payload["currency"]["config"])
        self.assertIn("external_environment", payload["environment"]["config"])

    def test_overview_survives_json_parse(self):
        # The regression this file exists for: `float("inf")` in the tax
        # brackets makes json.dumps emit a bare `Infinity`, which the browser
        # refuses to parse — the backend looks healthy and the panel is blank.
        with _TempRepo():
            body, status = api.handle_get("/api/external-systems/overview")
        self.assertEqual(200, status)
        # `parse_constant` fires only on Infinity/-Infinity/NaN, i.e. exactly
        # the tokens a browser's JSON.parse rejects.
        json.loads(
            json.dumps(body, ensure_ascii=False),
            parse_constant=lambda token: self.fail(f"non-finite JSON token: {token}"),
        )

    def test_unbounded_tax_bracket_is_visible_rather_than_dropped(self):
        with _TempRepo():
            body, _ = api.handle_get("/api/external-systems/overview")
        brackets = body["currency"]["config"]["economy"]["tax"]["brackets"]
        self.assertEqual("Infinity", brackets[-1][0])

    def test_missing_run_artifacts_do_not_raise(self):
        # A fresh clone has no output/ at all; the panel must still render.
        with _TempRepo():
            runtime = api.currency_runtime()
            environment = api.environment_runtime()
        self.assertEqual({}, runtime["macro"])
        self.assertEqual(0, runtime["wealth"]["agents"])
        self.assertFalse(environment["available"])


class ConfigPatchTests(unittest.TestCase):
    def test_unknown_keys_are_dropped_and_reported(self):
        with _TempRepo():
            patch, dropped = api.sanitize_config_patch(
                {
                    "economy": {"macro": {"initial_inflation_rate": 0.07, "nope": 1}},
                    "agent_ids": [1, 2],
                }
            )
        self.assertEqual({"economy": {"macro": {"initial_inflation_rate": 0.07}}}, patch)
        self.assertIn("economy.macro.nope", dropped)
        self.assertIn("agent_ids", dropped)

    def test_values_are_cast_to_the_shape_already_in_the_config(self):
        with _TempRepo():
            patch, _ = api.sanitize_config_patch(
                {
                    "economy": {
                        "enabled": "false",
                        "macro": {"initial_inflation_rate": "0.09"},
                        "work_days_per_month": "21",
                    }
                }
            )
        economy = patch["economy"]
        self.assertIs(False, economy["enabled"])
        self.assertEqual(0.09, economy["macro"]["initial_inflation_rate"])
        self.assertEqual(21, economy["work_days_per_month"])
        self.assertIsInstance(economy["work_days_per_month"], int)

    def test_uncastable_values_are_dropped_not_written_through(self):
        with _TempRepo():
            patch, dropped = api.sanitize_config_patch(
                {"economy": {"macro": {"initial_inflation_rate": "很高"}}}
            )
        self.assertEqual({}, patch)
        self.assertIn("economy.macro.initial_inflation_rate", dropped)

    def test_infinity_round_trips_through_the_wire_form(self):
        # The panel hands the top bracket back as the string "Infinity"; left
        # as a string it would break the numeric comparison that reads it.
        with _TempRepo():
            patch, _ = api.sanitize_config_patch(
                {"economy": {"tax": {"brackets": [[3000, 0.03, 0], ["Infinity", 0.45, 15160]]}}}
            )
        self.assertEqual(float("inf"), patch["economy"]["tax"]["brackets"][-1][0])

    def test_llm_providers_are_not_editable(self):
        with _TempRepo():
            patch, _ = api.sanitize_config_patch(
                {"llm": {"routing": {"default": "openai_gpt"}, "providers": {"evil": {}}}}
            )
        self.assertEqual({"llm": {"routing": {"default": "openai_gpt"}}}, patch)

    def test_save_writes_a_minimal_nested_patch(self):
        with _TempRepo() as repo:
            result = api.save_config({"economy": {"macro": {"initial_unemployment_rate": 0.11}}})
            saved = repo.config()
        self.assertTrue(result["saved"])
        self.assertEqual({"economy": {"macro": {"initial_unemployment_rate": 0.11}}}, saved)


class InterventionTests(unittest.TestCase):
    def test_empty_intervention_is_rejected(self):
        with _TempRepo():
            with self.assertRaises(ValueError):
                api.queue_intervention({"note": "什么都没改"})

    def test_queued_entry_is_applied_by_the_simulator_at_the_day_boundary(self):
        with _TempRepo() as repo:
            api.queue_intervention(
                {
                    "macro": {"phase": "contraction", "inflation_rate": 0.09},
                    "sector_delta": {"government": 50000},
                    "note": "财政刺激",
                }
            )
            cfg = {"output_dir": os.path.join(repo.root, "output", "economy")}
            runtime = {
                "macro": {"enabled": True, "phase": "expansion", "inflation_rate": 0.025,
                          "unemployment_rate": 0.052, "industry_conditions": {}},
                "sectors": {"firms": 0.0, "government": 0.0, "bank": 0.0},
                "initial_system_total": 1000.0,
            }
            applied = finance._consume_interventions({}, runtime, cfg, day=3)

            self.assertEqual(1, len(applied))
            self.assertEqual("contraction", runtime["macro"]["phase"])
            self.assertEqual(0.09, runtime["macro"]["inflation_rate"])
            self.assertEqual(50000.0, runtime["sectors"]["government"])
            # An injection is deliberate, so the conservation baseline moves
            # with it — otherwise the daily audit reports it as money leaking.
            self.assertEqual(51000.0, runtime["initial_system_total"])
            self.assertEqual(50000.0, runtime["intervention_injected_total"])

            queue = api.interventions()
            self.assertEqual([], queue["pending"])
            self.assertEqual(3, queue["applied"][0]["applied_day"])

    def test_a_scheduled_entry_waits_for_its_day(self):
        with _TempRepo() as repo:
            api.queue_intervention({"macro": {"unemployment_rate": 0.15}, "day": 9})
            cfg = {"output_dir": os.path.join(repo.root, "output", "economy")}
            runtime = {"macro": {"enabled": True}, "sectors": {}, "initial_system_total": 0.0}

            self.assertEqual([], finance._consume_interventions({}, runtime, cfg, day=4))
            self.assertEqual(1, len(api.interventions()["pending"]))

            self.assertEqual(1, len(finance._consume_interventions({}, runtime, cfg, day=9)))
            self.assertEqual(0.15, runtime["macro"]["unemployment_rate"])

    def test_macro_values_are_clamped_to_the_simulator_range(self):
        with _TempRepo() as repo:
            api.queue_intervention({"macro": {"inflation_rate": 99.0, "unemployment_rate": 0.0}})
            cfg = {"output_dir": os.path.join(repo.root, "output", "economy")}
            runtime = {"macro": {"enabled": True}, "sectors": {}, "initial_system_total": 0.0}
            finance._consume_interventions({}, runtime, cfg, day=1)
        self.assertEqual(0.15, runtime["macro"]["inflation_rate"])
        self.assertEqual(0.02, runtime["macro"]["unemployment_rate"])

    def test_cancel_all_clears_the_pending_queue(self):
        with _TempRepo():
            api.queue_intervention({"sector_delta": {"bank": 10.0}})
            api.queue_intervention({"sector_delta": {"bank": 20.0}})
            result = api.cancel_intervention({"all": True})
        self.assertEqual(2, result["removed"])
        self.assertEqual([], result["interventions"]["pending"])


class RoutingTests(unittest.TestCase):
    """Drive the real handler: the if/elif branch is what these cover."""

    def setUp(self):
        self.repo = _TempRepo().__enter__()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.repo.__exit__(None, None, None)

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as res:
            return json.loads(res.read().decode("utf-8")), res.status

    def _post(self, path, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as res:
            return json.loads(res.read().decode("utf-8")), res.status

    def test_overview_is_served(self):
        payload, status = self._get("/api/external-systems/overview")
        self.assertEqual(200, status)
        self.assertIn("currency", payload)

    def test_config_post_is_served_and_persists(self):
        payload, status = self._post(
            "/api/external-systems/config",
            {"config": {"external_environment": {"max_events_per_tick": 5}}},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["saved"])
        self.assertEqual(5, self.repo.config()["external_environment"]["max_events_per_tick"])

    def test_intervention_post_is_served(self):
        payload, _ = self._post(
            "/api/external-systems/interventions", {"sector_delta": {"firms": 100}}
        )
        self.assertIn("queued", payload)
        listed, _ = self._get("/api/external-systems/interventions")
        self.assertEqual(1, len(listed["pending"]))

    def test_unknown_subpath_is_a_404_not_a_static_file(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/external-systems/nope")
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            self.assertEqual(404, exc.code)
        else:
            self.fail("expected 404")


class FrontendTests(unittest.TestCase):
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _read(self, *parts):
        with open(os.path.join(self.ROOT, *parts), "r", encoding="utf-8") as f:
            return f.read()

    def test_headless_render_suite_passes(self):
        import subprocess

        result = subprocess.run(
            [
                "node",
                os.path.join(self.ROOT, "site", "dashboard", "external.test.js"),
            ],
            cwd=self.ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_console_registers_the_external_systems_tab(self):
        html = self._read("site", "console", "index.html")
        source = self._read("site", "console", "console.js")
        self.assertIn('data-tab="external"', html)
        self.assertIn('src: "/site/dashboard/external.html"', source)

    def test_panel_escapes_every_interpolation_it_renders(self):
        # Environment event text is LLM-authored and lands in innerHTML.
        source = self._read("site", "dashboard", "external.js")
        self.assertIn("function esc(text)", source)
        self.assertIn("esc(ev.description)", source)
        self.assertIn("esc(day.summary", source)


if __name__ == "__main__":
    unittest.main()
