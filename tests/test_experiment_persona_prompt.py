"""RED tests — an enriched persona reaches the classic-experiment prompt.

The path under test (audit RESULT-2799 §6): profile MD →
``experiments/subjects.load_subjects`` → ``Subject.personality/.daily_life``
→ ``paradigms.subject_block`` → ``build_prompt``. Enriching a resident's
profile must change the public-goods prompt **without touching any
experiment code**, and the structural facts in the prompt must equal the
CSV row — the enriched narrative is never allowed to move them.
"""

from __future__ import annotations

import unittest

from gaworld.apps import residents
from gaworld.experiments.classics.paradigms import PUBLIC_GOODS_MPCR, build_prompt
from gaworld.experiments.subjects import load_subjects
from gaworld.sim.agents_loader import parse_profile
from tests.test_persona_generate_api import ENRICHED, BaseGenerateCase

SEED = {
    "name": "测试者",
    "gender": "女",
    "age": 38,
    "hukou": "绍兴",
    "residence": "柯桥",
    "job": "经营一家布艺店",
}


class TestEnrichedPersonaReachesThePrompt(BaseGenerateCase):
    def test_enriched_personality_and_daily_life_render_in_the_prompt(self):
        created = residents.create_agent(dict(SEED))
        agent_id = created["id"]
        record = self.run_job({"scope": "selected", "ids": [agent_id]})
        self.assertEqual("completed", record["status"], record.get("error"))

        subjects = load_subjects(csv_path=_STATE(), md_path=_MD())
        subject = next(s for s in subjects if s.id == agent_id)
        _system, user = build_prompt(PUBLIC_GOODS_MPCR, PUBLIC_GOODS_MPCR.items[0], "low", subject)
        self.assertIn(ENRICHED["personality"], user)
        self.assertIn(ENRICHED["daily_life"], user)

    def test_structural_facts_in_the_prompt_equal_the_csv_row(self):
        created = residents.create_agent(dict(SEED))
        agent_id = created["id"]
        record = self.run_job({"scope": "selected", "ids": [agent_id]})
        self.assertEqual("completed", record["status"], record.get("error"))

        subjects = load_subjects(csv_path=_STATE(), md_path=_MD())
        subject = next(s for s in subjects if s.id == agent_id)
        row = next(r for r in residents.read_state_rows()[1] if int(r["id"]) == agent_id)

        self.assertEqual(int(row["age"]), subject.age)
        self.assertEqual(row["gender"], subject.gender)
        self.assertEqual(row["residence"], subject.residence)
        self.assertEqual(row["name"], subject.name)

        _system, user = build_prompt(PUBLIC_GOODS_MPCR, PUBLIC_GOODS_MPCR.items[0], "low", subject)
        self.assertIn(row["residence"], user)
        self.assertIn(str(row["age"]) + "岁", user)

    def test_enriched_fields_are_parseable_by_the_standard_parser(self):
        created = residents.create_agent(dict(SEED))
        agent_id = created["id"]
        record = self.run_job({"scope": "selected", "ids": [agent_id]})
        self.assertEqual("completed", record["status"], record.get("error"))

        text = residents.agent_profile(agent_id)["text"]
        block = text[text.index(f"## Profile {agent_id}") :]
        block = block.split("\n## Profile ", 1)[0]
        parsed = parse_profile(block)
        self.assertEqual(ENRICHED["personality"], parsed["personality"])
        self.assertEqual(ENRICHED["daily_life"], parsed["daily_life"])
        # structural facts survive the round trip untouched
        self.assertEqual(SEED["name"], parsed["name"])
        self.assertEqual(SEED["age"], parsed["age"])


def _STATE():
    from gaworld.apps import world_paths

    return world_paths.STATE_CSV_PATH


def _MD():
    from gaworld.apps import world_paths

    return world_paths.PROFILE_PATH


if __name__ == "__main__":
    unittest.main()
