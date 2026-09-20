"""The Studio's Big Five panel: seed round-trip and the consistency flags.

The panel edits ``data/agents_big5.csv``, which the plugin loads once at
``agents.built`` — so a change takes effect on the **next** run, exactly like
every other seed the Studio writes. All writes below target a temp copy.

The flags are the interesting part. The corpus was produced by sampling OCEAN
first and writing each resident's 人格与行为倾向 paragraph *from* those scores
(an independent scorer reads them back at r = 0.79). Editing a score therefore
puts the paragraph out of step with the rules channel — the same
self-contradiction the corpus-rewrite proposal diagnosed in §11.2 and fixed in
§11.3 by having prompts render only the new paragraph. The panel cannot rewrite
prose, so its job is to make the contradiction impossible to miss.
"""

import os
import shutil
import tempfile
import unittest

import gaworld.apps.dashboard_server as ds

REPO_ROOT = ds.REPO_ROOT
REAL_BIG5 = os.path.join(REPO_ROOT, "data", "agents_big5.csv")
REAL_MD = os.path.join(REPO_ROOT, "data", "hangzhou_profiles_with_names.md")


class _TempSeeds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._big5, self._md = ds.BIG5_CSV_PATH, ds.PROFILE_PATH
        ds.BIG5_CSV_PATH = os.path.join(self.tmp, "agents_big5.csv")
        ds.PROFILE_PATH = os.path.join(self.tmp, "profiles.md")
        shutil.copy(REAL_BIG5, ds.BIG5_CSV_PATH)
        shutil.copy(REAL_MD, ds.PROFILE_PATH)

    def tearDown(self):
        ds.BIG5_CSV_PATH, ds.PROFILE_PATH = self._big5, self._md
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestRead(_TempSeeds):
    def test_reads_the_five_scores_and_the_paragraph(self):
        data = ds._agent_big5(1)
        self.assertEqual(sorted(data["values"]), ["a", "c", "e", "n", "o"])
        self.assertEqual(data["source"], "sampled_authored")
        self.assertTrue(data["paragraph"], "the resident's authored paragraph")

    def test_untouched_scores_are_their_own_baseline(self):
        # source == sampled_authored means the values on disk *are* what the
        # paragraph was written from, so no snapshot column is needed yet.
        data = ds._agent_big5(1)
        self.assertEqual(data["authored"], data["values"])
        self.assertTrue(all(f["state"] == "ok" for f in data["consistency"].values()))

    def test_missing_agent_is_none_not_an_exception(self):
        self.assertIsNone(ds._agent_big5(9999))


class TestWrite(_TempSeeds):
    def test_scores_persist_and_are_clipped(self):
        ds._save_agent_big5(1, {"values": {"o": 0.25, "c": 99.0, "e": -99.0}})
        again = ds._agent_big5(1)
        self.assertAlmostEqual(again["values"]["o"], 0.25, places=4)
        self.assertAlmostEqual(again["values"]["c"], 2.5, places=4)
        self.assertAlmostEqual(again["values"]["e"], -2.5, places=4)

    def test_provenance_stops_claiming_the_sampler_produced_this(self):
        ds._save_agent_big5(1, {"values": {"o": 0.25}})
        self.assertEqual(ds._agent_big5(1)["source"], "hand_edited")

    def test_an_unchanged_write_does_not_relabel_the_row(self):
        before = ds._agent_big5(1)["values"]
        ds._save_agent_big5(1, {"values": before})
        self.assertEqual(ds._agent_big5(1)["source"], "sampled_authored")

    def test_the_collinearity_verdict_is_cleared_not_carried_over(self):
        # `redundant` was a gate's verdict about values that just changed.
        rows = ds._read_big5_rows()[1]
        rows[0]["redundant"] = "o|c"
        ds._save_agent_big5(1, {"values": {"o": 1.9}})
        row = next(r for r in ds._read_big5_rows()[1] if ds._row_id(r) == 1)
        self.assertEqual(row.get("redundant", ""), "")

    def test_non_numeric_input_is_refused(self):
        with self.assertRaises(ValueError):
            ds._save_agent_big5(1, {"values": {"o": "很高"}})
        with self.assertRaises(ValueError):
            ds._save_agent_big5(1, {"values": {"o": float("nan")}})


class TestConsistencyFlags(_TempSeeds):
    """Flags are arithmetic on the scores against the authoring floor.

    Deliberately not keyword matching against the paragraph: a keyword probe on
    this corpus already misled once — the personality proposal records an E
    probe reading -0.13 because the word list used topic nouns (约/聚/局) that
    appear at both poles. A confident-but-wrong indicator here is worse than
    none, because the operator would trust it instead of reading the paragraph.
    """

    def _flag(self, dim):
        return ds._agent_big5(1)["consistency"][dim]

    def test_flipping_a_dimension_the_paragraph_describes_is_the_loud_case(self):
        was = ds._agent_big5(1)["values"]["n"]
        self.assertGreaterEqual(abs(was), ds.BIG5_AUTHORING_FLOOR, "n is written")
        ds._save_agent_big5(1, {"values": {"n": -was}})
        flag = self._flag("n")
        self.assertEqual(flag["state"], "rewrite")
        self.assertEqual(flag["severity"], "flip")

    def test_a_large_same_sign_move_is_flagged_as_drift_not_a_flip(self):
        ds._save_agent_big5(1, {"values": {"n": 0.6}})  # was ~+1.90, still positive
        flag = self._flag("n")
        self.assertEqual(flag["state"], "rewrite")
        self.assertEqual(flag["severity"], "drift")

    def test_making_an_unwritten_dimension_distinctive_says_the_text_lacks_it(self):
        data = ds._agent_big5(1)
        self.assertLess(abs(data["values"]["o"]), ds.BIG5_AUTHORING_FLOOR, "o is unwritten")
        ds._save_agent_big5(1, {"values": {"o": -1.8}})
        self.assertEqual(self._flag("o")["state"], "now_missing")

    def test_flattening_a_written_dimension_says_the_text_over_describes(self):
        ds._save_agent_big5(1, {"values": {"n": 0.1}})
        self.assertEqual(self._flag("n")["state"], "now_moot")

    def test_a_small_move_inside_the_same_pole_is_not_flagged(self):
        was = ds._agent_big5(1)["values"]["n"]
        ds._save_agent_big5(1, {"values": {"n": round(was - 0.2, 4)}})
        self.assertEqual(self._flag("n")["state"], "ok")

    def test_the_baseline_survives_a_reload(self):
        """Without the snapshot the contradiction disappears on refresh.

        The first edit destroys the only record of what the paragraph was
        written from, so a panel that compares against "the current CSV" would
        show the warning once and then go quiet — the exact failure the panel
        exists to prevent.
        """
        was = ds._agent_big5(1)["values"]["n"]
        ds._save_agent_big5(1, {"values": {"n": -was}})
        ds._save_agent_big5(1, {"values": {"c": 0.3}})  # a second, unrelated edit
        flag = self._flag("n")
        self.assertEqual(flag["severity"], "flip")
        self.assertAlmostEqual(flag["authored"], was, places=4)


class TestPluginStillReadsWhatThePanelWrites(_TempSeeds):
    """The panel adds a column; the loader must not care."""

    def test_the_new_column_does_not_break_the_plugin_loader(self):
        from gaworld.personality.plugin import load_profiles

        ds._save_agent_big5(1, {"values": {"o": 1.25}})
        profiles = load_profiles(ds.BIG5_CSV_PATH)
        self.assertIn(1, profiles)
        self.assertAlmostEqual(profiles[1]["values"]["o"], 1.25, places=4)
        self.assertEqual(len(profiles), 51)


if __name__ == "__main__":
    unittest.main()
