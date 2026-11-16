"""RED tests — honest labelling of synthetic / LLM-authored profiles.

From ``SPEC-persona-generate.md``:

* LLM-authored profile blocks carry a provenance banner (mentioning
  "Synthetic demographic profile") rendered OUTSIDE the regex-parsed
  ``**…**：`` headings.
* ``agents_loader.parse_profile`` output must be byte-identical with and
  without the banner — the banner is prose, never parsed data.
* ``scope="fast"`` (the default, zero LLM calls) produces the existing
  templated demographic profiles, labelled honestly as synthetic.
"""

from __future__ import annotations

import unittest

from gaworld.sim.agents_loader import parse_profile
from tests.test_persona_generate_api import ENRICHED, BaseGenerateCase

BLOCK = """## Profile 999｜测试者
**基础信息**：男，42岁，绍兴人，居住于柯桥，
**职业与工作节奏**：经营一家小面馆，早市到午后。
**性格与情绪特征**：精打细算，遇事冷静。
**日常生活与生活习惯**：清晨备料，午后休息。
**价值观与公共事务态度**：踏实过日子。
"""


class TestBannerIsOutsideParsedHeadings(unittest.TestCase):
    def test_banner_changes_nothing_parse_profile_reads(self):
        banner = (
            "> 合成人口画像（Synthetic demographic profile）：结构字段来自人口合成器，"
            "叙述字段由 LLM 撰写（persona_author, 2026-10-22）。"
        )
        with_banner = f"{banner}\n{BLOCK}"
        self.assertEqual(parse_profile(BLOCK), parse_profile(with_banner))

    def test_banner_is_not_eaten_by_a_heading_regex(self):
        # The banner must not be shaped like a parsed heading: prepending it
        # must not let any extractor start matching mid-banner.
        banner = "> Synthetic demographic profile：LLM-authored narrative."
        parsed = parse_profile(f"{banner}\n{BLOCK}")
        self.assertEqual("精打细算，遇事冷静。", parsed["personality"])


class TestGeneratedProfilesCarryTheBanner(BaseGenerateCase):
    def test_llm_enriched_profile_carries_the_banner(self):
        record = self.run_job({"scope": "selected", "ids": [1]})
        self.assertEqual("completed", record["status"], record.get("error"))
        text = residents_profile_text(1)
        self.assertIn("Synthetic demographic profile", text)
        self.assertIn(ENRICHED["personality"], text)

    def test_fast_scope_labels_templated_profiles_honestly(self):
        record = self.run_job({"scope": "fast", "seed": {"name": "测试者", "age": 42, "gender": "男"}})
        self.assertEqual("completed", record["status"], record.get("error"))
        agent_id = (record.get("result") or {}).get("agent_id") or (record.get("result") or {}).get("id")
        self.assertIsNotNone(agent_id, f"fast generation must return the new resident: {record}")
        text = residents_profile_text(agent_id)
        self.assertIn("Synthetic demographic profile", text)
        # fast is the zero-LLM path
        self.assertEqual([], self.fake_llm.calls)

    def test_fast_scope_makes_zero_llm_calls(self):
        self.run_job({"scope": "fast", "seed": {"name": "测试者", "age": 42, "gender": "男"}})
        self.assertEqual([], self.fake_llm.calls)


def residents_profile_text(agent_id):
    from gaworld.apps import residents

    return residents.agent_profile(agent_id)["text"]


if __name__ == "__main__":
    unittest.main()
