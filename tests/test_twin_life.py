import os
import tempfile
import unittest

from gaworld.twin import life


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class TestTwinLife(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.diary_dir = os.path.join(self.root, "diaries")
        self.state_dir = os.path.join(self.root, "state")
        self.memory_dir = os.path.join(self.root, "memory")

    def tearDown(self):
        self._tmp.cleanup()

    # -- diary ----------------------------------------------------------

    def test_latest_diary_picks_the_highest_day(self):
        _write(os.path.join(self.diary_dir, "agent_7", "day_001.md"), "第一天")
        _write(os.path.join(self.diary_dir, "agent_7", "day_012.md"), "第十二天")
        _write(os.path.join(self.diary_dir, "agent_7", "day_003.md"), "第三天")
        entry = life.latest_diary(7, diary_dir=self.diary_dir)
        self.assertEqual(entry["day"], 12)
        self.assertIn("第十二天", entry["text"])

    def test_missing_diary_returns_empty(self):
        entry = life.latest_diary(7, diary_dir=self.diary_dir)
        self.assertEqual(entry["text"], "")
        self.assertIsNone(entry["day"])

    def test_diary_ignores_non_day_files(self):
        _write(os.path.join(self.diary_dir, "agent_7", "notes.md"), "x")
        _write(os.path.join(self.diary_dir, "agent_7", "day_002.md"), "第二天")
        self.assertEqual(life.latest_diary(7, diary_dir=self.diary_dir)["day"], 2)

    # -- state ----------------------------------------------------------

    def test_state_folds_to_the_last_value_per_metric(self):
        _write(
            os.path.join(self.state_dir, "agent_state_history.csv"),
            "agent_id,step,metric,value\n"
            "7,0,emotion,0.30\n"
            "7,1,emotion,0.72\n"
            "7,0,stress,0.60\n"
            "8,9,emotion,0.11\n",
        )
        state = life.latest_state(7, state_dir=self.state_dir)
        self.assertAlmostEqual(state["emotion"], 0.72)
        self.assertAlmostEqual(state["stress"], 0.60)
        self.assertNotIn(0.11, state.values())

    def test_missing_state_file_returns_empty(self):
        self.assertEqual(life.latest_state(7, state_dir=self.state_dir), {})

    def test_corrupt_state_row_is_skipped(self):
        _write(
            os.path.join(self.state_dir, "agent_state_history.csv"),
            "agent_id,step,metric,value\n"
            "7,0,emotion,notanumber\n"
            "7,1,stress,0.5\n",
        )
        state = life.latest_state(7, state_dir=self.state_dir)
        self.assertNotIn("emotion", state)
        self.assertAlmostEqual(state["stress"], 0.5)

    # -- goals ----------------------------------------------------------

    def test_active_goals_are_returned_by_tier(self):
        _write(
            os.path.join(self.memory_dir, "agent_7_goals.json"),
            '{"life_goals": [{"id": "lg1", "title": "职业晋升", "status": "active"}],'
            ' "short_term_goals": [{"id": "s1", "title": "早睡", "status": "done"}]}',
        )
        goals = life.active_goals(7, memory_dir=self.memory_dir)
        self.assertEqual([g["title"] for g in goals["life_goals"]], ["职业晋升"])
        # Completed goals are dropped: the phone card shows what is live.
        self.assertEqual(goals["short_term_goals"], [])

    def test_missing_goals_return_empty_tiers(self):
        goals = life.active_goals(7, memory_dir=self.memory_dir)
        self.assertEqual(goals["life_goals"], [])
        self.assertEqual(goals["long_term_goals"], [])
        self.assertEqual(goals["short_term_goals"], [])

    def test_corrupt_goals_file_returns_empty_tiers(self):
        _write(os.path.join(self.memory_dir, "agent_7_goals.json"), "{not json")
        self.assertEqual(life.active_goals(7, memory_dir=self.memory_dir)["life_goals"], [])


if __name__ == "__main__":
    unittest.main()
