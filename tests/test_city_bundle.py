"""City bundle layout, manifest round-trip, registry and config wiring."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gaworld.city.bundle import (
    CityBundle,
    CityNotFoundError,
    city_root,
    delete_city,
    list_cities,
    load_bundle,
    new_manifest,
    resolve_city,
    slugify,
)
from gaworld.city.geocode import offline_place


class SlugifyTest(unittest.TestCase):
    def test_ascii_names_are_lowercased_and_hyphenated(self):
        self.assertEqual(slugify("Hangzhou Riverside"), "hangzhou-riverside")
        self.assertEqual(slugify("  Old   Town  "), "old-town")

    def test_non_ascii_names_keep_their_characters(self):
        # There is no dependency-free transliteration for these, and a hash
        # would make data/cities/ unreadable.
        self.assertEqual(slugify("绍兴柯桥"), "绍兴柯桥")
        self.assertEqual(slugify("柳溪 村"), "柳溪-村")

    def test_path_separators_are_stripped(self):
        self.assertEqual(slugify("a/b:c*d"), "abcd")

    def test_name_with_no_usable_characters_is_rejected(self):
        for bad in ("", "   ", "///"):
            with self.assertRaises(ValueError):
                slugify(bad)


class BundleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _make(self, slug="test-city", scale="small"):
        directory = city_root(self.root) / slug
        bundle = CityBundle(
            directory=directory,
            manifest=new_manifest(
                slug=slug,
                name=slug,
                display_name=slug,
                place=offline_place(slug, scale=scale).to_dict(),
                scale=scale,
            ),
        )
        bundle.save()
        return bundle

    def test_manifest_round_trips(self):
        bundle = self._make()
        bundle.record("create", offline=True)
        bundle.save()

        reloaded = load_bundle(bundle.directory)
        self.assertEqual(reloaded.slug, "test-city")
        self.assertEqual(reloaded.map_mode, "virtual")
        self.assertEqual(reloaded.population_count, 0)
        self.assertEqual(reloaded.manifest["history"][-1]["action"], "create")

    def test_map_mode_falls_back_when_the_real_bundle_is_missing(self):
        bundle = self._make()
        bundle.manifest["map"] = {"mode": "real", "real": "map.geojson"}
        # Declared real but no file on disk: the bundle must not claim to be
        # real, or load_real_city_map would raise at simulation start.
        self.assertEqual(bundle.map_mode, "virtual")

        bundle.real_map_path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        self.assertEqual(bundle.map_mode, "real")

    def test_paths_for_config_only_lists_files_that_exist(self):
        bundle = self._make()
        bundle.virtual_map_path.write_text("# City Map\n", encoding="utf-8")
        paths = bundle.paths_for_config()
        self.assertIn("map_path", paths)
        self.assertNotIn("csv_path", paths)

        bundle.state_csv_path.write_text("id\n", encoding="utf-8-sig")
        bundle.profiles_md_path.write_text("# x\n", encoding="utf-8")
        paths = bundle.paths_for_config()
        self.assertTrue(paths["csv_path"].endswith("agents.csv"))
        self.assertTrue(paths["md_path"].endswith("profiles.md"))

    def test_registry_lists_and_resolves(self):
        self._make("alpha")
        self._make("beta")
        self.assertEqual([b.slug for b in list_cities(self.root)], ["alpha", "beta"])
        self.assertEqual(resolve_city("alpha", self.root).slug, "alpha")
        with self.assertRaises(CityNotFoundError):
            resolve_city("gamma", self.root)

    def test_registry_skips_a_corrupt_bundle_instead_of_failing(self):
        self._make("good")
        broken = city_root(self.root) / "broken"
        broken.mkdir(parents=True)
        (broken / "city.json").write_text("{not json", encoding="utf-8")
        self.assertEqual([b.slug for b in list_cities(self.root)], ["good"])

    def test_delete_refuses_paths_outside_the_registry(self):
        outside = self.root / "elsewhere"
        outside.mkdir()
        (outside / "city.json").write_text(json.dumps({"slug": "x"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            delete_city(str(outside), self.root)
        self.assertTrue(outside.exists())

    def test_delete_removes_a_registered_bundle(self):
        bundle = self._make("doomed")
        delete_city("doomed", self.root)
        self.assertFalse(bundle.directory.exists())


class CityConfigTest(unittest.TestCase):
    """``config["city"]`` swaps the simulator's map, environment and background."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_overrides_carry_paths_environment_and_background(self):
        from gaworld.city.config import city_overrides

        directory = city_root(self.root) / "somewhere"
        bundle = CityBundle(
            directory=directory,
            manifest=new_manifest(
                slug="somewhere",
                name="Somewhere",
                display_name="Somewhere",
                place=offline_place("Somewhere").to_dict(),
                scale="small",
            ),
        )
        bundle.save()
        bundle.virtual_map_path.write_text("# City Map\n", encoding="utf-8")
        bundle.environment_path.write_text(
            json.dumps(
                {
                    "background": "A different place entirely.",
                    "environment": {"natural_events": ["blizzard"]},
                    "not_allowed": {"nope": 1},
                }
            ),
            encoding="utf-8",
        )

        patch = city_overrides("somewhere", self.root)
        self.assertEqual(patch["city"], "somewhere")
        self.assertEqual(patch["background"], "A different place entirely.")
        self.assertEqual(patch["environment"]["natural_events"], ["blizzard"])
        self.assertTrue(patch["map_path"].endswith("citymap.md"))
        # Only the allowlisted environment blocks come through.
        self.assertNotIn("not_allowed", patch)
        # Inputs keyed by agent id belong to this city's residents, not to the
        # default population's #1, #2, … under data/.
        self.assertTrue(patch["personality"]["profile_path"].endswith("somewhere/agents_big5.csv"))
        self.assertTrue(patch["family"]["overrides_path"].endswith("somewhere/family_overrides.json"))
        self.assertTrue(patch["moltbook"]["accounts_path"].endswith("somewhere/moltbook_accounts.json"))
        # …while the run outputs of the same sections still move under the run root.
        self.assertEqual(patch["personality"]["output_dir"], "output/cities/somewhere/traits")

    def test_unknown_city_degrades_to_an_empty_patch(self):
        from gaworld.city.config import city_overrides

        # A config naming a deleted city must not make the simulator unstartable.
        self.assertEqual(city_overrides("ghost-town", self.root), {})
        self.assertEqual(city_overrides("", self.root), {})


class CityRunRootTest(unittest.TestCase):
    """Selecting a city moves the whole run tree under ``output/cities/<slug>/``.

    Memory, logs and the vector store are keyed by agent id alone and
    ``sim_state.json`` holds one world clock, so sharing a run tree means two
    cities' ``#1`` share one set of files and one calendar.
    """

    def test_every_runtime_path_moves_under_the_city(self):
        from gaworld.city.config import RUN_PATHS, run_overrides

        patch = run_overrides("wuzhen")
        self.assertEqual(patch["run_output_dir"], "output/cities/wuzhen")
        self.assertEqual(patch["memory_dir"], "output/cities/wuzhen/memory")
        self.assertEqual(patch["log_dir"], "output/cities/wuzhen/logs")
        self.assertEqual(
            patch["vector_db_path"], "output/cities/wuzhen/memory/vector_db.sqlite"
        )
        # Nested sections are patched in place, not flattened.
        self.assertEqual(patch["economy"]["output_dir"], "output/cities/wuzhen/economy")
        self.assertEqual(
            patch["visualization"]["output_dir"], "output/cities/wuzhen/visualization"
        )
        self.assertEqual(
            patch["collaboration"]["sessions_dir"],
            "output/cities/wuzhen/collaboration/sessions",
        )
        # Nothing in the table is silently dropped on the way into the patch.
        leaves = 0
        for value in patch.values():
            leaves += len(value) if isinstance(value, dict) else 1
        self.assertEqual(leaves, len(RUN_PATHS))

    def test_two_cities_never_share_a_path(self):
        from gaworld.city.config import run_overrides

        a, b = run_overrides("wuzhen"), run_overrides("绍兴柯桥")
        self.assertEqual(set(a), set(b))
        for key, value in a.items():
            if isinstance(value, dict):
                for leaf, path in value.items():
                    self.assertNotEqual(path, b[key][leaf])
            else:
                self.assertNotEqual(value, b[key])

    def test_no_city_selected_keeps_the_default_output_tree(self):
        from gaworld.city.config import city_overrides

        with TemporaryDirectory() as tmp:
            self.assertEqual(city_overrides("", Path(tmp)), {})

    def test_the_run_layout_mirrors_the_default_output_tree(self):
        # Analytics joins `state/` and `economy/` onto a run root, and
        # replay_runs globs `output/*/visualization` for traces. Both read the
        # *names* below, so a city's tree has to be laid out exactly like the
        # default one — renaming a leaf here breaks them without any error.
        from gaworld.city.config import RUN_PATHS

        for path, leaf in RUN_PATHS.items():
            if not leaf:
                continue
            default = self._default_for(path)
            self.assertEqual(
                default,
                f"output/{leaf}",
                f"{path}: run-root layout has drifted from the default tree",
            )

    def _default_for(self, path):
        """The stock (no city selected) value of a dotted config path."""
        import inspect

        from gaworld.kernel import remote
        from gaworld.kernel.recorder import Recorder
        from gaworld.settings import build_default_config

        # Two defaults live in code, next to the only code that writes them.
        in_code = {
            "records.output_dir": inspect.signature(Recorder).parameters["base_dir"].default,
            "kernel.interventions_path": remote.DEFAULT_PATH,
        }
        if path in in_code:
            return in_code[path]
        node = build_default_config()
        for part in path.split("."):
            self.assertIsInstance(node, dict, f"{path}: not a config path")
            self.assertIn(part, node, f"{path}: no longer in the defaults")
            node = node[part]
        return node


#: Paths in the default config that deliberately stay shared by every city and
#: world, with the reason. Everything else under ``output/`` or ``data/`` must be
#: a per-run output (RUN_PATHS) or a per-population input (AGENT_FILES).
SHARED_PATHS = {
    # The population and its map: a city bundle or a world's seed/ sets them.
    "csv_path": "population",
    "md_path": "population",
    "map_path": "population",
    "real_map_path": "population",
    "environment_config_path": "a city's environment.json layers over it",
    "skills.global_dir": "the skill library every resident draws on",
    # Standalone services with their own deployment, not part of a run.
    "distributed.server.state_path": "relay service",
    "environment_server.state_path": "environment service",
    "twin.bindings_path": "twin service",
    # The real world's news is the same for every simulated one.
    "news.sources_path": "real-world news",
    "news.cache_path": "real-world news",
    "news.sources.registry_path": "real-world news",
    "news.sources.feed_cache_path": "real-world news",
}


class PathClassificationTest(unittest.TestCase):
    """A path missing from these tables silently stays shared: two worlds (or
    two cities) then write one file, or a city reads the default population's
    agent-keyed data. A new path has to be classified here to pass."""

    def test_every_output_and_data_path_is_classified(self):
        from gaworld.city.config import AGENT_FILES, RUN_PATHS
        from gaworld.settings import build_default_config

        def walk(node, prefix=""):
            for key, value in node.items():
                path = f"{prefix}{key}"
                if isinstance(value, dict):
                    yield from walk(value, f"{path}.")
                elif isinstance(value, str) and value.startswith(("output", "data/")):
                    yield path

        for path in walk(build_default_config()):
            with self.subTest(path=path):
                self.assertIn(path, {*RUN_PATHS, *AGENT_FILES, *SHARED_PATHS})

    def test_the_tables_do_not_overlap(self):
        from gaworld.city.config import AGENT_FILES, RUN_PATHS

        self.assertFalse(set(RUN_PATHS) & set(AGENT_FILES))
        self.assertFalse(set(RUN_PATHS) & set(SHARED_PATHS))
        self.assertFalse(set(AGENT_FILES) & set(SHARED_PATHS))


class DeleteTakesRunStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _make(self, slug):
        bundle = CityBundle(
            directory=city_root(self.root) / slug,
            manifest=new_manifest(
                slug=slug,
                name=slug,
                display_name=slug,
                place=offline_place(slug).to_dict(),
                scale="small",
            ),
        )
        bundle.save()
        return bundle

    def test_deleting_a_city_also_drops_its_run_state(self):
        from gaworld.city.bundle import runs_root

        bundle = self._make("doomed")
        run_dir = runs_root(self.root) / "doomed"
        (run_dir / "memory").mkdir(parents=True)
        (run_dir / "memory" / "sim_state.json").write_text("{}", encoding="utf-8")

        delete_city("doomed", self.root)

        self.assertFalse(bundle.directory.exists())
        # Left behind, a city recreated under the same name would inherit the
        # deleted one's memory and world clock.
        self.assertFalse(run_dir.exists())

    def test_a_city_with_no_run_state_yet_deletes_cleanly(self):
        bundle = self._make("unrun")
        delete_city("unrun", self.root)
        self.assertFalse(bundle.directory.exists())

    def test_a_refused_delete_leaves_run_state_alone(self):
        from gaworld.city.bundle import runs_root

        outside = self.root / "elsewhere"
        outside.mkdir()
        (outside / "city.json").write_text(json.dumps({"slug": "x"}), encoding="utf-8")
        run_dir = runs_root(self.root) / "x"
        run_dir.mkdir(parents=True)
        with self.assertRaises(ValueError):
            delete_city(str(outside), self.root)
        self.assertTrue(run_dir.exists())


if __name__ == "__main__":
    unittest.main()
