"""Phase 4b: the Population Studio dashboard surface.

Two things are tested that the existing dashboard tests do not cover, because
both are ways this integration could break silently:

* **the routing delegation actually fires.** The existing dashboard tests call
  helper functions directly and never start an HTTP server, so a broken
  if/elif branch in ``dashboard_server`` would go unnoticed. A few tests here
  drive the real handler.
* **the panel's knob definitions come from the backend.** The nine state
  variables are already declared twice in this repo and hand-synced; the schema
  endpoint exists so the population knobs never join them, and that only holds
  if the endpoint really serves them.

No LLM calls: every group run here is deterministic (``use_llm`` false).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import population_api


def _wait(job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = population_api.job_status(job_id)
        if record and record["status"] != "running":
            return record
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


class SchemaTests(unittest.TestCase):
    def test_schema_serves_the_knob_contract(self):
        schema = population_api.population_schema()
        for key in ("presets", "state_var_keys", "industries", "cohort_axes", "defaults", "ranges"):
            self.assertIn(key, schema)
        self.assertEqual(9, len(schema["state_var_keys"]))
        self.assertIn("cn_county_town", schema["presets"])

    def test_schema_state_keys_match_the_population_module(self):
        # The panel renders one slider per key from this list. If it drifts from
        # the generator's own definition the UI silently stops covering a
        # variable — the exact failure the endpoint exists to prevent.
        from gaworld.population.schema import STATE_VAR_KEYS

        self.assertEqual(list(STATE_VAR_KEYS), population_api.population_schema()["state_var_keys"])

    def test_schema_cohort_axes_match_the_group_module(self):
        from gaworld.group.cohort import COHORT_AXES

        self.assertEqual(sorted(COHORT_AXES), population_api.population_schema()["cohort_axes"])

    def test_schema_defaults_round_trip_through_normalize(self):
        from gaworld.population.schema import normalize_spec

        defaults = population_api.population_schema()["defaults"]
        self.assertEqual(defaults, normalize_spec(defaults).to_dict())

    def test_network_coupling_note_states_it_needs_recalibration(self):
        # A user reading only the panel must not take 0.7 as universal.
        note = population_api.population_schema()["notes"]["network_coupling"]
        self.assertIn("重新标定", note)


class PreviewTests(unittest.TestCase):
    def test_preview_reports_conflicts_without_generating(self):
        result = population_api.preview_population(
            {"household": {"share_single_person": 0.6, "mean_size": 3.2}}
        )
        self.assertTrue(result["has_errors"])
        codes = {i["code"] for i in result["issues"]}
        self.assertIn("household_mean_too_large", codes)
        self.assertNotIn("people", result)

    def test_preview_returns_reachable_bounds_for_the_ui(self):
        result = population_api.preview_population({})
        bounds = result["bounds"]
        self.assertLess(bounds["household_mean_size"]["min"], bounds["household_mean_size"]["max"])
        self.assertLess(bounds["median_age"]["min"], bounds["median_age"]["max"])

    def test_preview_of_a_clean_preset_has_no_errors(self):
        result = population_api.preview_population({"preset": "aging_community"})
        self.assertFalse(result["has_errors"], result["issues"])

    def test_preview_is_fast_enough_for_keystroke_use(self):
        start = time.time()
        for _ in range(20):
            population_api.preview_population({"size": 5000})
        self.assertLess(time.time() - start, 1.0)


class JobTests(unittest.TestCase):
    def test_generation_job_completes_and_returns_people(self):
        started = population_api.start_population_job({"spec": {"size": 120, "seed": 3}})
        record = _wait(started["job_id"])
        self.assertEqual("done", record["status"], record.get("error"))
        self.assertEqual(120, len(record["result"]["people"]))
        self.assertTrue(record["result"]["ok"])
        self.assertIn("achieved", record["result"]["report"])

    def test_group_run_needs_a_population_first(self):
        population_api._LAST_POPULATION.clear()
        result = population_api.start_group_job({"source": "last"})
        self.assertIn("error", result)

    def test_group_run_follows_the_generated_population(self):
        generated = _wait(population_api.start_population_job({"spec": {"size": 120, "seed": 3}})["job_id"])
        self.assertEqual("done", generated["status"])
        started = population_api.start_group_job(
            {"source": "last", "days": 3, "materialization_budget": 5, "use_llm": False}
        )
        record = _wait(started["job_id"])
        self.assertEqual("done", record["status"], record.get("error"))
        self.assertEqual(120, record["result"]["cost"]["population"])
        self.assertEqual(3, len(record["result"]["days"]))
        self.assertTrue(record["result"]["cohorts"])

    def test_group_run_honours_network_coupling(self):
        _wait(population_api.start_population_job({"spec": {"size": 120, "seed": 3}})["job_id"])
        record = _wait(
            population_api.start_group_job(
                {"source": "last", "days": 2, "network_coupling": 0.7, "use_llm": False}
            )["job_id"]
        )
        self.assertEqual("done", record["status"], record.get("error"))
        self.assertEqual(0.7, record["result"]["network_coupling"])

    def test_a_failing_job_is_reported_not_swallowed(self):
        job_id = population_api._new_job("test")

        def boom(_report):
            raise RuntimeError("deliberate")

        population_api._run_in_background(job_id, boom)
        record = _wait(job_id, timeout=10)
        self.assertEqual("error", record["status"])
        self.assertIn("deliberate", record["message"])
        self.assertIsNotNone(record["error"])

    def test_finished_jobs_are_evicted_but_running_ones_are_not(self):
        # A dashboard left open for a week must not accumulate every population
        # it ever generated, but evicting in-flight work would strand the UI.
        for _ in range(population_api._MAX_JOBS + 8):
            population_api._new_job("test")
        with population_api._JOBS_LOCK:
            running = [r for r in population_api._JOBS.values() if r["status"] == "running"]
        self.assertGreaterEqual(len(running), population_api._MAX_JOBS)

    def test_unknown_job_id_returns_none(self):
        self.assertIsNone(population_api.job_status("does-not-exist"))


class ExportTests(unittest.TestCase):
    """Downloading the generated agents straight from the panel.

    The three artefacts are rendered here rather than in JavaScript so the CSV
    column order and the profile template stay declared once, in
    ``gaworld.population.writer`` — a second copy in ``population.js`` would
    drift the moment either changes.
    """

    def _generate(self, size=40):
        record = _wait(population_api.start_population_job({"spec": {"size": size, "seed": 3}})["job_id"])
        self.assertEqual("done", record["status"], record.get("error"))

    def test_export_serves_the_same_three_artefacts_as_writing_to_disk(self):
        self._generate()
        csv_file = population_api.export_population("csv")
        self.assertTrue(csv_file["filename"].endswith("_state_init.csv"))
        # utf-8-sig on the reader side: without the BOM flag the downloaded CSV
        # is not a drop-in replacement for CONFIG["csv_path"].
        self.assertTrue(csv_file["bom"])
        self.assertGreater(csv_file["bytes"], 0)

        markdown = population_api.export_population("md")
        self.assertTrue(markdown["filename"].endswith("_profiles.md"))
        self.assertIn("## Profile", markdown["content"])

        manifest = json.loads(population_api.export_population("json")["content"])
        self.assertEqual(40, manifest["counts"]["people"])

    def test_exported_csv_keeps_the_writer_column_order(self):
        from gaworld.population.schema import CSV_COLUMNS

        self._generate()
        header = population_api.export_population("csv")["content"].splitlines()[0]
        self.assertEqual(list(CSV_COLUMNS), header.split(","))

    def test_export_over_the_route_returns_400_when_nothing_was_generated(self):
        population_api._LAST_POPULATION.clear()
        payload, status = population_api.handle_get("/api/population/export", {"format": ["csv"]})
        self.assertEqual(400, status)
        self.assertIn("error", payload)

    def test_unknown_export_format_is_rejected(self):
        self._generate()
        payload, status = population_api.handle_get("/api/population/export", {"format": ["exe"]})
        self.assertEqual(400, status)
        self.assertIn("error", payload)

    def test_household_type_labels_cover_every_generated_type(self):
        # The roster renders one row per resident; an unlabelled type would
        # print a raw identifier like "shared_rental" in a Chinese table.
        from gaworld.population.schema import HOUSEHOLD_TYPES

        labels = population_api.population_schema()["household_type_labels"]
        self.assertEqual(sorted(HOUSEHOLD_TYPES), sorted(labels))


class SecurityTests(unittest.TestCase):
    def test_out_dir_cannot_escape_the_repository(self):
        # The dashboard serves REPO_ROOT statically and takes this value from
        # the browser, so an unchecked path would be an arbitrary-write hole.
        with self.assertRaises(ValueError):
            population_api._output_dir({"out_dir": "../../../tmp/evil"})
        with self.assertRaises(ValueError):
            population_api._output_dir({"out_dir": "/etc"})

    def test_out_dir_accepts_a_path_inside_the_repository(self):
        resolved = population_api._output_dir({"out_dir": "output/population"})
        self.assertIn("output", resolved)

    def test_post_returns_400_for_a_bad_out_dir_rather_than_raising(self):
        body, status = population_api.handle_post(
            "/api/population/generate", {"spec": {"size": 30}, "write": True, "out_dir": "/etc"}
        )
        self.assertEqual(400, status)
        self.assertIn("error", body)


class RoutingTests(unittest.TestCase):
    def test_get_routes(self):
        payload, status = population_api.handle_get("/api/population/schema", {})
        self.assertEqual(200, status)
        self.assertIn("defaults", payload)

        payload, status = population_api.handle_get("/api/population/jobs/nope", {})
        self.assertEqual(404, status)

        payload, status = population_api.handle_get("/api/population/bogus", {})
        self.assertEqual(404, status)

    def test_post_routes(self):
        _payload, status = population_api.handle_post("/api/population/preview", {"size": 50})
        self.assertEqual(200, status)

        _payload, status = population_api.handle_post("/api/population/bogus", {})
        self.assertEqual(404, status)

    def test_post_tolerates_a_non_dict_body(self):
        _payload, status = population_api.handle_post("/api/population/preview", None)
        self.assertEqual(200, status)


class HttpIntegrationTests(unittest.TestCase):
    """Drive the real handler, so a broken route branch cannot pass unnoticed."""

    @classmethod
    def setUpClass(cls):
        from gaworld.apps import dashboard_server as ds

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def _post(self, path, body):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_schema_endpoint_is_reachable_over_http(self):
        status, payload = self._get("/api/population/schema")
        self.assertEqual(200, status)
        self.assertEqual(9, len(payload["state_var_keys"]))

    def test_preview_endpoint_is_reachable_over_http(self):
        status, payload = self._post("/api/population/preview", {"size": 60})
        self.assertEqual(200, status)
        self.assertIn("issues", payload)

    def test_generate_returns_202_and_the_job_polls_to_done(self):
        status, payload = self._post("/api/population/generate", {"spec": {"size": 60, "seed": 2}})
        self.assertEqual(202, status)
        record = _wait(payload["job_id"])
        self.assertEqual("done", record["status"], record.get("error"))
        status, polled = self._get("/api/population/jobs/" + payload["job_id"])
        self.assertEqual(200, status)
        self.assertEqual("done", polled["status"])

    def test_existing_dashboard_endpoints_still_work(self):
        # The delegation is a prefix match inserted ahead of the existing
        # chain; this guards against it swallowing unrelated routes.
        status, payload = self._get("/api/config")
        self.assertEqual(200, status)
        self.assertIsInstance(payload, dict)

    def test_static_panel_assets_are_served(self):
        for asset in (
            "/site/dashboard/population.html",
            "/site/dashboard/population.js",
            "/site/dashboard/population.css",
        ):
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{asset}", timeout=10) as res:
                self.assertEqual(200, res.status, asset)
                self.assertTrue(res.read())


class JobPayloadSerialisationTests(unittest.TestCase):
    """The browser gets whatever ``job_status`` returns, via ``json.dumps``."""

    def test_non_finite_floats_are_nulled_so_the_response_stays_valid_json(self):
        # L2 reports a ratio of two Moran's I values; when the reference signal
        # is under the noise floor that ratio is NaN. Python happily writes a
        # bare ``NaN`` token, which ``JSON.parse`` rejects — so a single such
        # key made the browser throw away the entire verdict, not just that
        # field. Anything the panel shows must survive a strict re-encode.
        population_api._JOBS["nan-probe"] = {
            "status": "done",
            "result": {"verdict": {"layers": [{"detail": {"by_key": {"emotion": {"ratio": float("nan")}}}}]}},
            "extras": [float("inf"), float("-inf"), 1.5],
        }
        try:
            record = population_api.job_status("nan-probe")
        finally:
            population_api._JOBS.pop("nan-probe", None)

        self.assertIsNotNone(record)
        json.dumps(record, allow_nan=False)  # would raise on NaN/Infinity
        layer = record["result"]["verdict"]["layers"][0]
        self.assertIsNone(layer["detail"]["by_key"]["emotion"]["ratio"])
        self.assertEqual([None, None, 1.5], record["extras"])

    def test_finite_numbers_are_left_alone(self):
        population_api._JOBS["plain-probe"] = {"a": 0.0, "b": -12.5, "c": [1, 2, 3]}
        try:
            record = population_api.job_status("plain-probe")
        finally:
            population_api._JOBS.pop("plain-probe", None)
        self.assertEqual({"a": 0.0, "b": -12.5, "c": [1, 2, 3]}, record)


class WrittenFileDescriptorTests(unittest.TestCase):
    """Written files must be openable from the page, not just named in a log."""

    def test_repo_relative_files_get_a_clickable_url_and_a_preview(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        target = os.path.join(root, "output", "population", "_descriptor_probe.csv")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("id,name\n1,张三\n2,李四\n")
        try:
            described = population_api._describe_written({"state_csv": target})
        finally:
            os.remove(target)

        self.assertEqual(1, len(described))
        entry = described[0]
        # The dashboard serves REPO_ROOT statically, so a repo-relative URL is
        # directly clickable; an absolute filesystem path is not.
        self.assertEqual("/output/population/_descriptor_probe.csv", entry["url"])
        # The path stays absolute on purpose: it is what the user pastes into
        # CONFIG["csv_path"], and that must not depend on the working directory.
        self.assertTrue(os.path.isabs(entry["path"]))
        self.assertIn("张三", entry["preview"])
        self.assertGreater(entry["bytes"], 0)
        self.assertTrue(entry["label"])
        self.assertTrue(entry["hint"])

    def test_files_outside_the_repo_are_listed_without_a_url(self):
        # Users can point the output directory anywhere; the panel must not
        # render a link that would 404.
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(tmp, "elsewhere.csv")
            with open(outside, "w", encoding="utf-8") as fh:
                fh.write("x\n")
            described = population_api._describe_written({"state_csv": outside})
        self.assertEqual(1, len(described))
        self.assertFalse(described[0]["url"])  # falsy -> the panel renders no link


class ConsoleWiringTests(unittest.TestCase):
    def test_population_tab_is_registered_in_both_shell_files(self):
        # console.js maps tab id → iframe src and index.html renders the button;
        # adding one without the other yields a dead tab.
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "site", "console", "console.js"), encoding="utf-8") as fh:
            js = fh.read()
        with open(os.path.join(root, "site", "console", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('id: "population"', js)
        self.assertIn("/site/dashboard/population.html", js)
        self.assertIn('data-tab="population"', html)


if __name__ == "__main__":
    unittest.main()
