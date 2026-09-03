"""The 配置 panel: provenance, whole-tree serialization, patches, and secrets.

The panel's whole reason to exist is that this project's configuration comes
from four layers that override each other, so the failure modes worth pinning
down are the ones that make an edit *look* like it worked:

* **A single non-finite float blanks the entire panel.** The economy's top tax
  bracket is ``float("inf")`` and this payload carries the *whole* config tree,
  so it is strictly more exposed to the bare-``Infinity`` trap than the
  External Systems panel that first hit it.
* **Wrong provenance is worse than no provenance.** If a key overridden by
  ``environment_config.json`` is reported as a plain default, the user edits it
  here, the save succeeds, and nothing changes. That is the exact confusion the
  panel was built to remove, so the layering is tested against the real
  precedence in ``settings/overrides.py``.
* **Reset must delete, not write the default back.** Writing the default into
  the override file pins it, so a later change to the Python default silently
  stops taking effect — a bug that surfaces months later, in someone else's run.
* **A dashboard bound to a port must not echo API keys.** Secret-named env vars
  are reported as present/absent and masked; the test asserts the raw value is
  nowhere in the serialized payload.
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
from gaworld.apps import settings_api as api
from gaworld.settings import config_docs


class _TempRepo:
    """Point the dashboard's path constants at a scratch tree."""

    def __init__(self, dashboard_config=None, env_config=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.dashboard_config = dashboard_config
        self.env_config = env_config
        self._saved = (ds.REPO_ROOT, ds.DASHBOARD_CONFIG_PATH)
        self._saved_cwd = os.getcwd()

    def __enter__(self):
        ds.REPO_ROOT = self.root
        ds.DASHBOARD_CONFIG_PATH = os.path.join(self.root, "dashboard_config.json")
        if self.dashboard_config is not None:
            self.write(ds.DASHBOARD_CONFIG_PATH, self.dashboard_config)
        if self.env_config is not None:
            # ``load_environment_config`` resolves the relative default path
            # against the *package* root, not REPO_ROOT, so the cwd is the only
            # lever a test has over it.
            os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
            self.write(os.path.join(self.root, "data", "environment_config.json"), self.env_config)
            os.chdir(self.root)
        return self

    def __exit__(self, *exc):
        os.chdir(self._saved_cwd)
        ds.REPO_ROOT, ds.DASHBOARD_CONFIG_PATH = self._saved
        self.tmp.cleanup()
        return False

    @staticmethod
    def write(path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def config(self):
        with open(ds.DASHBOARD_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)


class OverviewTests(unittest.TestCase):
    def test_overview_survives_json_parse(self):
        # `parse_constant` fires only on Infinity/-Infinity/NaN — exactly the
        # tokens a browser's JSON.parse rejects, and rejecting one of them
        # discards the *entire* response, not just that leaf.
        with _TempRepo():
            body, status = api.handle_get("/api/settings/overview")
        self.assertEqual(200, status)
        json.loads(
            json.dumps(body, ensure_ascii=False),
            parse_constant=lambda token: self.fail(f"non-finite JSON token: {token}"),
        )

    def test_every_top_level_config_key_lands_in_exactly_one_section(self):
        # A key that belongs to no section is invisible in the panel, which is
        # the one thing a "所有配置集中在这里" claim cannot survive.
        with _TempRepo():
            payload = api.overview()
        claimed = [key for section in payload["sections"] for key in section["keys"]]
        self.assertEqual(sorted(claimed), sorted(set(claimed)), "a key is claimed twice")
        self.assertEqual(sorted(claimed), sorted(payload["tree"].keys()))

    def test_sections_carry_their_own_explanation(self):
        with _TempRepo():
            payload = api.overview()
        for section in payload["sections"]:
            self.assertTrue(section["title"], section["id"])
            self.assertTrue(section["help"], section["id"])

    def test_defaults_are_reported_alongside_the_effective_value(self):
        with _TempRepo(dashboard_config={"sim_days": 99}):
            payload = api.overview()
        self.assertEqual(99, payload["tree"]["sim_days"])
        self.assertEqual(2, payload["defaults"]["sim_days"])


class ProvenanceTests(unittest.TestCase):
    def test_dashboard_override_is_attributed_to_the_dashboard_layer(self):
        with _TempRepo(dashboard_config={"sim_days": 7, "long_run": {"randomness": 0.4}}):
            payload = api.overview()
        self.assertEqual("dashboard", payload["sources"]["sim_days"])
        self.assertEqual("dashboard", payload["sources"]["long_run.randomness"])
        # Untouched siblings must not be tarred with the same brush.
        self.assertNotIn("long_run.enabled", payload["sources"])

    def test_environment_config_wins_and_is_labelled_as_the_layer_that_wins(self):
        # apply_runtime_overrides applies environment_config.json *last*, so a
        # key it names cannot be changed from this panel. Reporting it as
        # "dashboard" or as a default would invite exactly the silent no-op
        # edit this panel exists to prevent.
        with _TempRepo(
            dashboard_config={"external_environment": {"max_events_per_tick": 9}},
            env_config={"external_environment": {"max_events_per_tick": 3}},
        ):
            payload = api.overview()
        self.assertEqual("env_file", payload["sources"]["external_environment.max_events_per_tick"])

    def test_untouched_keys_have_no_source_entry(self):
        with _TempRepo():
            payload = api.overview()
        self.assertNotIn("economy.macro.initial_inflation_rate", payload["sources"])


class SaveTests(unittest.TestCase):
    def test_patch_is_nested_and_coerced_to_the_existing_shape(self):
        with _TempRepo() as repo:
            result = api.save_config(
                {"sim_days": "5", "economy": {"macro": {"initial_inflation_rate": "0.09"}}}
            )
            saved = repo.config()
        self.assertTrue(result["saved"])
        self.assertEqual(5, saved["sim_days"])
        self.assertIsInstance(saved["sim_days"], int)
        self.assertEqual(0.09, saved["economy"]["macro"]["initial_inflation_rate"])

    def test_unknown_keys_are_dropped_rather_than_planted(self):
        # A typo that lands in the override file is a key the simulator never
        # reads and nobody ever notices. Nothing survivable means nothing
        # written at all — not an empty file.
        with _TempRepo():
            result = api.save_config({"nope": 1, "economy": {"not_a_knob": 2}})
            self.assertFalse(os.path.exists(ds.DASHBOARD_CONFIG_PATH))
        self.assertFalse(result["saved"])
        self.assertIn("nope", result["dropped"])
        self.assertIn("economy.not_a_knob", result["dropped"])

    def test_provider_credentials_are_refused_while_routing_stays_editable(self):
        # ``omlx_qwen`` is the provider that carries a literal ``api_key``, so
        # shape coercion alone would happily write it through; this is the case
        # the read-only guard exists for. A provider whose key lives in an env
        # var is refused one layer earlier, by coercion, and would not exercise
        # the guard at all.
        with _TempRepo() as repo:
            result = api.save_config(
                {
                    "llm": {
                        "providers": {"omlx_qwen": {"api_key": "sk-leak"}},
                        "routing": {"default": "minimax"},
                    }
                }
            )
            saved = repo.config()
        self.assertIn("llm.providers", result["blocked"])
        self.assertNotIn("providers", saved["llm"])
        self.assertEqual("minimax", saved["llm"]["routing"]["default"])

    def test_a_credential_only_patch_writes_nothing_at_all(self):
        with _TempRepo():
            result = api.save_config({"llm": {"providers": {"omlx_qwen": {"api_key": "sk-leak"}}}})
            self.assertFalse(os.path.exists(ds.DASHBOARD_CONFIG_PATH))
        self.assertFalse(result["saved"])
        self.assertIn("llm.providers", result["blocked"])

    def test_existing_overrides_are_merged_not_replaced(self):
        with _TempRepo(dashboard_config={"sim_days": 3, "long_run": {"enabled": True}}) as repo:
            api.save_config({"long_run": {"randomness": 0.5}})
            saved = repo.config()
        self.assertEqual(3, saved["sim_days"])
        self.assertIs(True, saved["long_run"]["enabled"])
        self.assertEqual(0.5, saved["long_run"]["randomness"])


class ResetTests(unittest.TestCase):
    def test_the_tree_is_not_a_stale_snapshot_of_import_time_config(self):
        """The panel must read the layers, not ``CONFIG``.

        ``settings/overrides.py`` merges the override files into ``CONFIG``
        at import, so ``deepcopy(CONFIG)`` is a snapshot that goes stale the
        moment the dashboard writes one. It made reset look like it had not
        worked — the override file was empty, the panel still showed the old
        value — which is precisely the "the edit looks like it worked"
        confusion this panel exists to remove, running in reverse.
        """
        with _TempRepo(dashboard_config={"sim_days": 9}):
            self.assertEqual(9, api.overview()["tree"]["sim_days"])
            # A write made *after* import has to be visible immediately.
            _TempRepo.write(ds.DASHBOARD_CONFIG_PATH, {"sim_days": 77})
            self.assertEqual(77, api.overview()["tree"]["sim_days"])
            # ...and so does its removal.
            _TempRepo.write(ds.DASHBOARD_CONFIG_PATH, {})
            payload = api.overview()
            self.assertEqual(
                payload["defaults"]["sim_days"], payload["tree"]["sim_days"],
                "with no override left, the tree is the Python default",
            )

    def test_reset_deletes_the_key_instead_of_writing_the_default_back(self):
        # Writing the default value into the override file would pin it: a
        # later change to the Python default would silently not take effect.
        with _TempRepo(dashboard_config={"sim_days": 9}) as repo:
            result = api.reset_paths({"paths": ["sim_days"]})
            saved = repo.config()
        self.assertEqual(["sim_days"], result["removed"])
        self.assertNotIn("sim_days", saved)
        self.assertEqual(2, result["tree"]["sim_days"])

    def test_reset_prunes_parents_it_leaves_empty(self):
        # An orphaned `{"economy": {"macro": {}}}` reads as "economy is
        # overridden" in every provenance view forever.
        with _TempRepo(dashboard_config={"economy": {"macro": {"initial_inflation_rate": 0.09}}}) as repo:
            api.reset_paths({"paths": ["economy.macro.initial_inflation_rate"]})
            saved = repo.config()
        self.assertEqual({}, saved)

    def test_reset_keeps_siblings_under_a_shared_parent(self):
        with _TempRepo(dashboard_config={"long_run": {"enabled": True, "randomness": 0.4}}) as repo:
            api.reset_paths({"paths": ["long_run.randomness"]})
            saved = repo.config()
        self.assertEqual({"long_run": {"enabled": True}}, saved)

    def test_resetting_a_path_that_is_not_overridden_is_a_no_op(self):
        with _TempRepo(dashboard_config={"sim_days": 9}) as repo:
            result = api.reset_paths({"paths": ["economy.macro.initial_inflation_rate"]})
            saved = repo.config()
        self.assertEqual([], result["removed"])
        self.assertEqual({"sim_days": 9}, saved)

    def test_reset_all_empties_the_override_file(self):
        with _TempRepo(dashboard_config={"sim_days": 9, "long_run": {"randomness": 0.4}}) as repo:
            result = api.reset_all()
            saved = repo.config()
        self.assertEqual({}, saved)
        self.assertEqual(["long_run.randomness", "sim_days"], sorted(result["removed"]))

    def test_non_list_paths_are_rejected(self):
        with _TempRepo():
            body, status = api.handle_post("/api/settings/reset", {"paths": 3})
        self.assertEqual(400, status)
        self.assertIn("error", body)


class LlmProviderTests(unittest.TestCase):
    """选后端 / 加后端 / 测连通性 — the three things the tree editor can't express."""

    def test_routing_paths_carry_the_provider_names_as_a_closed_set(self):
        # A free-text routing value is a typo away from a run that dies on
        # "Provider not found" after the config has already been saved.
        with _TempRepo():
            payload = api.overview()
        names = payload["choices"]["llm.routing.default"]
        self.assertIn("ollama_gemma4", names)
        self.assertEqual(sorted(payload["tree"]["llm"]["providers"]), names)
        # Per-task routing is the same closed set, not a different one.
        self.assertEqual(names, payload["choices"]["llm.routing.tasks.schedule"])

    def test_provider_rows_report_key_readiness_without_the_key(self):
        secret = "sk-must-not-travel-9876543210"
        os.environ["MINIMAX_API_KEY"] = secret
        try:
            with _TempRepo():
                payload = api.overview()
                blob = json.dumps(payload, ensure_ascii=False)
        finally:
            os.environ.pop("MINIMAX_API_KEY", None)
        row = next(item for item in payload["providers"] if item["name"] == "minimax")
        self.assertTrue(row["needs_key"])
        self.assertTrue(row["key_ready"])
        self.assertEqual(["MINIMAX_API_KEY"], row["api_key_envs"])
        self.assertNotIn(secret, blob)

    def test_inline_provider_keys_are_masked_on_the_wire(self):
        # Two local backends ship a literal api_key in the Python defaults, and
        # this payload is served to any browser that can reach the port.
        with _TempRepo():
            payload = api.overview()
        self.assertEqual("••••••", payload["tree"]["llm"]["providers"]["omlx_qwen"]["api_key"])
        self.assertEqual("••••••", payload["defaults"]["llm"]["providers"]["omlx_qwen"]["api_key"])
        # Masking is on the wire only — the real value still reaches the router.
        self.assertEqual("omlx-local", ds._effective_config()["llm"]["providers"]["omlx_qwen"]["api_key"])

    def test_added_provider_lands_in_the_override_file_and_the_choices(self):
        with _TempRepo() as repo:
            result = api.save_provider(
                {
                    "name": "my_local",
                    "config": {"type": "ollama", "url": "http://127.0.0.1:11434/api/generate",
                               "model": "qwen3.5:9b", "timeout": "600"},
                }
            )
            saved = repo.config()
        self.assertEqual(
            {"type": "ollama", "url": "http://127.0.0.1:11434/api/generate",
             "model": "qwen3.5:9b", "timeout": 600},
            saved["llm"]["providers"]["my_local"],
        )
        self.assertIsInstance(saved["llm"]["providers"]["my_local"]["timeout"], int)
        # A backend you cannot then select is not added.
        self.assertIn("my_local", result["choices"]["llm.routing.default"])
        row = next(item for item in result["providers"] if item["name"] == "my_local")
        self.assertTrue(row["editable"])

    def test_saving_a_provider_replaces_the_block_instead_of_merging_it(self):
        # Deep-merging would leave a cleared api_key_env behind, so the backend
        # keeps authenticating with a credential the user believes they removed.
        with _TempRepo(
            dashboard_config={"llm": {"providers": {"cloud": {
                "type": "openai", "base_url": "https://a/v1", "model": "m", "api_key_env": "OLD_KEY"}}}}
        ) as repo:
            api.save_provider(
                {"name": "cloud", "config": {"type": "openai", "base_url": "https://b/v1", "model": "m2"}}
            )
            saved = repo.config()
        self.assertNotIn("api_key_env", saved["llm"]["providers"]["cloud"])
        self.assertEqual("https://b/v1", saved["llm"]["providers"]["cloud"]["base_url"])

    def test_a_plaintext_key_is_refused_rather_than_written_to_a_tracked_file(self):
        with _TempRepo():
            with self.assertRaises(ValueError) as caught:
                api.save_provider(
                    {"name": "cloud", "config": {"type": "openai", "base_url": "https://a/v1",
                                                 "model": "m", "api_key": "sk-leak"}}
                )
            self.assertFalse(os.path.exists(ds.DASHBOARD_CONFIG_PATH))
        self.assertIn("密钥", str(caught.exception))

    def test_incomplete_or_unsupported_providers_are_refused(self):
        with _TempRepo():
            for bad in (
                {"name": "x", "config": {"type": "ollama", "url": "http://a"}},          # no model
                {"name": "x", "config": {"type": "ollama", "model": "m"}},               # no endpoint
                {"name": "x", "config": {"type": "telepathy", "model": "m"}},            # unknown type
                {"name": "bad name", "config": {"type": "ollama", "url": "u", "model": "m"}},
            ):
                with self.assertRaises(ValueError, msg=bad):
                    api.save_provider(bad)
            self.assertFalse(os.path.exists(ds.DASHBOARD_CONFIG_PATH))

    def test_deleting_an_added_provider_reuses_the_reset_path(self):
        # The panel's 删除 button posts to /api/settings/reset; a provider added
        # here is just another override, so removal is the same pruning.
        with _TempRepo(
            dashboard_config={"llm": {"providers": {"mine": {"type": "ollama", "url": "u", "model": "m"}}}}
        ) as repo:
            result = api.reset_paths({"paths": ["llm.providers.mine"]})
            saved = repo.config()
        self.assertEqual(["llm.providers.mine"], result["removed"])
        self.assertEqual({}, saved)
        self.assertNotIn("mine", result["choices"]["llm.routing.default"])

    def test_probe_of_an_unreachable_backend_is_a_verdict_not_an_exception(self):
        # The button must always answer. An exception here would leave the row
        # stuck on 正在调用… with no explanation.
        with _TempRepo():
            result = api.test_provider(
                {"name": "draft", "config": {"type": "ollama", "model": "nope",
                                             "url": "http://127.0.0.1:1/api/generate", "timeout": 2}}
            )
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    def test_probe_names_the_missing_env_var_instead_of_reporting_a_401(self):
        os.environ.pop("GAWORLD_TEST_ABSENT_KEY", None)
        with _TempRepo():
            result = api.test_provider(
                {"config": {"type": "openai", "model": "m", "base_url": "https://example.invalid/v1",
                            "api_key_env": "GAWORLD_TEST_ABSENT_KEY"}}
            )
        self.assertFalse(result["ok"])
        self.assertIn("GAWORLD_TEST_ABSENT_KEY", result["error"])

    def test_probing_an_unknown_saved_provider_is_a_400_not_a_crash(self):
        with _TempRepo():
            body, status = api.handle_post("/api/settings/llm/test", {"name": "ghost"})
        self.assertEqual(400, status)
        self.assertIn("ghost", body["error"])

    def test_the_probe_takes_one_shot_while_the_simulator_still_retries(self):
        # The router's three-with-backoff is right for a long run and wrong for
        # a button: it turns an unreachable endpoint into a minute of silence.
        from gaworld.llm import providers

        cfg = {"type": "ollama", "url": "http://127.0.0.1:1/api/generate", "model": "m"}
        self.assertEqual(1, providers.build_provider(cfg, attempts=1).attempts)
        self.assertEqual(3, providers.build_provider(cfg).attempts)

    def test_the_probe_builds_the_same_object_the_router_uses(self):
        # A probe with its own hand-rolled request would keep passing after the
        # router's construction drifted — the one failure it exists to catch.
        from gaworld.llm import providers

        cfg = ds._effective_config()["llm"]["providers"]["minimax"]
        built = providers.build_provider(cfg)
        self.assertIsInstance(built, type(providers.LLM_ROUTER.providers["minimax"]))
        self.assertEqual(providers.LLM_ROUTER.providers["minimax"].base_url, built.base_url)


class SecretTests(unittest.TestCase):
    def test_secret_env_values_are_masked_and_never_appear_in_the_payload(self):
        secret = "sk-do-not-echo-0123456789"
        os.environ["OPENAI_API_KEY"] = secret
        try:
            with _TempRepo() as repo:
                # The catalogue comes from the repo's own .env.example.
                with open(os.path.join(repo.root, ".env.example"), "w", encoding="utf-8") as f:
                    f.write("# ---- LLM providers ----\n# OpenAI key\nOPENAI_API_KEY=\n")
                payload = api.overview()
                blob = json.dumps(payload, ensure_ascii=False)
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        entry = next(item for item in payload["env"]["vars"] if item["name"] == "OPENAI_API_KEY")
        self.assertTrue(entry["set"])
        self.assertTrue(entry["secret"])
        self.assertNotEqual(secret, entry["value"])
        self.assertNotIn(secret, blob)

    def test_non_secret_env_values_are_shown_in_full(self):
        os.environ["GAWORLD_LOG_LEVEL"] = "DEBUG"
        try:
            with _TempRepo() as repo:
                with open(os.path.join(repo.root, ".env.example"), "w", encoding="utf-8") as f:
                    f.write("GAWORLD_LOG_LEVEL=INFO\n")
                payload = api.overview()
        finally:
            os.environ.pop("GAWORLD_LOG_LEVEL", None)
        entry = next(item for item in payload["env"]["vars"] if item["name"] == "GAWORLD_LOG_LEVEL")
        self.assertEqual("DEBUG", entry["value"])
        self.assertFalse(entry["secret"])

    def test_env_catalogue_carries_the_comments_from_env_example(self):
        with _TempRepo() as repo:
            with open(os.path.join(repo.root, ".env.example"), "w", encoding="utf-8") as f:
                f.write("# ---- LLM providers ----\n# OpenAI / OpenAI-compatible\nOPENAI_API_KEY=\n")
            payload = api.overview()
        entry = next(item for item in payload["env"]["vars"] if item["name"] == "OPENAI_API_KEY")
        self.assertEqual("LLM providers", entry["group"])
        self.assertIn("OpenAI", entry["help"])


class DocumentationTests(unittest.TestCase):
    def test_source_comments_are_extracted_from_the_settings_modules(self):
        # The extractor is what keeps ~500 leaves documented without a
        # hand-written catalogue; if the AST walk silently returns nothing, the
        # panel still renders and every tooltip quietly loses its first line.
        extracted = config_docs.source_help()
        self.assertGreater(len(extracted), 50)
        self.assertIn("fast-forward", extracted["long_run"])
        self.assertIn("time_step_minutes", extracted["time_grid_snap"])

    def test_manual_help_wins_over_the_source_comment(self):
        self.assertIn("long_run", config_docs.MANUAL_HELP)
        self.assertEqual(config_docs.MANUAL_HELP["long_run"], config_docs.help_for("long_run"))

    def test_labels_resolve_full_path_before_last_segment(self):
        # `routing` is payment routing under economy and model routing under
        # llm; resolving by last segment alone would call them the same thing.
        self.assertEqual("支付路由", config_docs.label_for("economy.routing"))
        self.assertEqual("任务路由", config_docs.label_for("llm.routing"))

    def test_unknown_paths_fall_back_to_the_raw_key_without_raising(self):
        self.assertEqual("no_such_knob", config_docs.label_for("a.b.no_such_knob"))
        self.assertEqual("", config_docs.help_for("a.b.no_such_knob"))

    def test_every_documented_path_that_is_curated_exists_in_the_config(self):
        # A manual entry for a path that no longer exists is dead text nobody
        # will ever see, and the usual sign that a knob was renamed.
        with _TempRepo():
            tree = api.overview()["tree"]
        for path in config_docs.MANUAL_HELP:
            node = tree
            for part in path.split("."):
                self.assertIsInstance(node, dict, f"{path}: not a config path")
                self.assertIn(part, node, f"{path}: no longer in CONFIG")
                node = node[part]


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
        payload, status = self._get("/api/settings/overview")
        self.assertEqual(200, status)
        self.assertIn("sections", payload)
        self.assertIn("docs", payload)

    def test_save_is_served_and_persists(self):
        payload, status = self._post("/api/settings/save", {"config": {"sim_days": 4}})
        self.assertEqual(200, status)
        self.assertTrue(payload["saved"])
        self.assertEqual(4, self.repo.config()["sim_days"])

    def test_reset_is_served(self):
        self._post("/api/settings/save", {"config": {"sim_days": 4}})
        payload, status = self._post("/api/settings/reset", {"paths": ["sim_days"]})
        self.assertEqual(200, status)
        self.assertEqual(["sim_days"], payload["removed"])

    def test_unknown_settings_endpoint_is_a_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/api/settings/nope")
        self.assertEqual(404, caught.exception.code)


class PanelWiringTests(unittest.TestCase):
    @staticmethod
    def _read(*parts):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, *parts), encoding="utf-8") as f:
            return f.read()

    def test_console_registers_the_settings_tab(self):
        html = self._read("site", "console", "index.html")
        source = self._read("site", "console", "console.js")
        self.assertIn('data-tab="settings"', html)
        self.assertIn('src: "/site/dashboard/settings.html"', source)

    def test_page_loads_the_shared_help_tooltip_script(self):
        # Every field's hover explanation is rendered by help.js; without the
        # script the data-help attributes are inert and the panel silently
        # loses the one feature it was asked for.
        html = self._read("site", "dashboard", "settings.html")
        self.assertIn("help.js", html)
        self.assertIn("settings.js", html)

    def test_panel_escapes_every_interpolation_it_renders(self):
        # Config values and env var contents land in innerHTML.
        source = self._read("site", "dashboard", "settings.js")
        self.assertIn("function esc(text)", source)
        self.assertIn("esc(helpText(path, value))", source)
        self.assertIn("esc(item.name)", source)

    def test_the_llm_panel_wires_all_three_actions(self):
        source = self._read("site", "dashboard", "settings.js")
        # Pick a backend: a closed-set <select>, fed by the backend's choices.
        self.assertIn("function choicesFor(path)", source)
        self.assertIn("function optionsHtml(options, current)", source)
        self.assertIn("<select data-kind=", source)
        # Add one, and probe one — saved or still a draft.
        self.assertIn("/api/settings/llm/provider", source)
        self.assertIn("/api/settings/llm/test", source)
        self.assertIn("function draftPayload()", source)

    def test_the_panel_never_offers_a_plaintext_key_box(self):
        # dashboard_config.json is tracked; a key typed here would land in git.
        source = self._read("site", "dashboard", "settings.js")
        self.assertIn('field("api_key_env", "密钥环境变量"', source)
        self.assertNotIn('data-draft="api_key"', source)

    def test_every_field_gets_a_tooltip_even_without_curated_text(self):
        # The fallback (path / type / default / source) is what makes the
        # "每一项都有说明" promise true for the ~400 leaves nobody has written
        # prose for.
        source = self._read("site", "dashboard", "settings.js")
        self.assertIn('lines.push("路径：" + path)', source)
        self.assertIn('lines.push("当前来自："', source)


if __name__ == "__main__":
    unittest.main()
