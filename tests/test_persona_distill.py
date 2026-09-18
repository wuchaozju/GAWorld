"""Tests for the persona layer — research, distillation, renderers, archive.

No network and no model: ``research`` and ``distill`` both take their callables
as parameters, so every path here runs against fakes. What is checked is the
part that decides whether a distilled resident is trustworthy — that only
sourced material reaches the profile, that numbers are clamped to the ranges
the seed files accept, and that the honest-boundary lines cannot be dropped by
a confident model.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from gaworld.persona import distill as distill_mod
from gaworld.persona import render as render_mod
from gaworld.persona import research as research_mod
from gaworld.persona import store as store_mod
from gaworld.persona.distill import DistillError, PersonaProfile


def fake_search(results_by_query=None, default=None):
    calls: list[str] = []

    def search(query: str):
        calls.append(query)
        if results_by_query and query in results_by_query:
            return results_by_query[query]
        return default if default is not None else [
            {"url": f"https://example.com/{len(calls)}", "title": f"命中{len(calls)}", "snippet": "一段摘要"}
        ]

    search.calls = calls  # type: ignore[attr-defined]
    return search


def fake_fetch(pages=None):
    def fetch(url: str):
        if pages and url in pages:
            return pages[url]
        return (f"标题 {url}", f"正文 {url}")

    return fetch


FACTS = {
    "off_topic": False,
    "name": "李某",
    "summary": "一位做纺织外贸的经营者",
    "gender": "男",
    "age": "47",
    "hukou": "绍兴",
    "residence": "柯桥",
    "job": "经营一家面料出口公司",
    "education_income": "",
    "daily_life": "早七点到厂",
    "personality": "谨慎，话少",
    "social_network": "同业商会",
    "values": "务实",
    "unknown_fields": ["education_income"],
}

FRAMEWORK = {
    "mental_models": [
        {"name": "订单即信号", "gist": "从订单结构反推行业周期", "evidence": ["2023年他据此提前减产"], "limits": "只在自有渠道成立"},
        {"name": "不加杠杆", "gist": "现金流优先于扩张", "evidence": ["拒绝了一笔并购"], "limits": ""},
    ],
    "heuristics": [{"rule": "如果账期超过90天，则不接单", "example": "2022年拒绝一家大客户"}],
    "voice": {"sentences": "短句", "vocabulary": "行业术语多", "rhythm": "先结论", "humor": "不幽默",
              "certainty": "「我不确定」型", "phrases": ["先看单子"]},
    "values_ranked": ["稳", "信用", "家里人"],
    "anti_patterns": ["赊账扩张"],
    "tensions": ["想做品牌又不肯投钱"],
    "lineage": ["同代温商"],
    "boundaries": ["只覆盖公开报道"],
    "state": {"emotion": 0.6, "stress": 2.0, "econ_security": -1, "risk_preference": 0.2},
    "big5": {"o": 0.3, "c": 9.0, "e": -0.4, "a": 0.1, "n": -5},
}


def scripted_llm(*answers):
    queue = list(answers)
    seen: list[str] = []

    def call(prompt: str) -> str:
        seen.append(prompt)
        return queue.pop(0) if queue else "{}"

    call.prompts = seen  # type: ignore[attr-defined]
    return call


def build_profile() -> PersonaProfile:
    dossier = research_mod.research(
        "李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_queries=2, max_pages=2
    )
    return distill_mod.distill(
        dossier,
        llm_fn=scripted_llm(json.dumps(FACTS), json.dumps(FRAMEWORK)),
        slugify_fn=lambda name: "li-mou",
    )


class TestResearch(unittest.TestCase):
    def test_name_mode_runs_one_query_per_facet(self):
        search = fake_search()
        dossier = research_mod.research("李某", search_fn=search, fetch_fn=fake_fetch(), max_queries=3, max_pages=0)
        self.assertEqual(3, len(search.calls))
        self.assertTrue(all("李某" in q for q in search.calls))
        self.assertEqual("name", dossier.mode)

    def test_url_mode_reads_the_page_and_derives_the_name(self):
        pages = {"https://example.com/who": ("张三 - 个人主页", "他长期研究城市交通")}
        dossier = research_mod.research(
            "https://example.com/who",
            search_fn=fake_search(),
            fetch_fn=fake_fetch(pages),
            max_queries=1,
            max_pages=1,
        )
        self.assertEqual("url", dossier.mode)
        self.assertEqual("张三", dossier.name)
        self.assertIn("城市交通", dossier.brief())

    def test_pages_are_read_in_full_and_marked(self):
        dossier = research_mod.research(
            "李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_queries=2, max_pages=2
        )
        self.assertEqual(2, dossier.page_count)
        self.assertTrue(all(doc.text for doc in dossier.documents if doc.kind == "page"))

    def test_a_failing_search_does_not_end_the_run(self):
        def exploding(query: str):
            raise RuntimeError("engine down")

        dossier = research_mod.research("李某", search_fn=exploding, fetch_fn=fake_fetch(), max_pages=0)
        self.assertTrue(dossier.is_empty)
        self.assertEqual([], dossier.queries)

    def test_duplicate_urls_are_collected_once(self):
        same = [{"url": "https://example.com/a", "title": "同一页", "snippet": "x"}]
        dossier = research_mod.research(
            "李某", search_fn=fake_search(default=same), fetch_fn=fake_fetch(), max_queries=3, max_pages=0
        )
        self.assertEqual(1, len(dossier.documents))

    def test_empty_subject_is_rejected(self):
        with self.assertRaises(ValueError):
            research_mod.research("  ", search_fn=fake_search(), fetch_fn=fake_fetch())


class TestDistill(unittest.TestCase):
    def test_profile_carries_identity_and_framework(self):
        profile = build_profile()
        self.assertEqual("李某", profile.name)
        self.assertEqual(47, profile.age)
        self.assertEqual("柯桥", profile.residence)
        self.assertEqual(2, len(profile.mental_models))
        self.assertEqual("订单即信号", profile.mental_models[0].name)
        self.assertEqual(1, len(profile.heuristics))
        self.assertEqual("短句", profile.voice.sentences)

    def test_state_is_clamped_and_complete(self):
        profile = build_profile()
        self.assertEqual(set(distill_mod.STATE_VAR_KEYS), set(profile.state))
        self.assertEqual(1.0, profile.state["stress"])          # 2.0 in the answer
        self.assertEqual(0.0, profile.state["econ_security"])   # -1 in the answer
        self.assertEqual(0.5, profile.state["city_identity"])   # absent from the answer

    def test_big5_is_clamped_to_the_slider_range(self):
        profile = build_profile()
        self.assertEqual(distill_mod.BIG5_LIMIT, profile.big5["c"])
        self.assertEqual(-distill_mod.BIG5_LIMIT, profile.big5["n"])

    def test_sources_are_recorded(self):
        profile = build_profile()
        self.assertTrue(profile.sources)
        self.assertTrue(all(s["url"] for s in profile.sources))

    def test_boundaries_always_state_the_two_fixed_limits(self):
        profile = build_profile()
        joined = " ".join(profile.boundaries)
        self.assertIn("公开材料", joined)
        self.assertIn("信息截止", joined)
        self.assertIn("只覆盖公开报道", joined)  # the model's own line survives

    def test_low_evidence_is_flagged_in_the_boundaries(self):
        dossier = research_mod.Dossier(subject="李某", name="李某")
        dossier.documents.append(research_mod.Document(title="t", url="u", text="一点点", kind="snippet"))
        profile = distill_mod.distill(
            dossier,
            llm_fn=scripted_llm(json.dumps(FACTS), json.dumps(FRAMEWORK)),
            slugify_fn=lambda n: "x",
        )
        self.assertEqual("low", profile.confidence)
        self.assertTrue(any("人工复核" in b for b in profile.boundaries))

    def test_empty_dossier_raises(self):
        with self.assertRaises(DistillError):
            distill_mod.distill(research_mod.Dossier(subject="李某", name="李某"), llm_fn=scripted_llm("{}"))

    def test_off_topic_material_raises_instead_of_inventing(self):
        dossier = research_mod.research("李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_pages=1)
        with self.assertRaises(DistillError) as ctx:
            distill_mod.distill(dossier, llm_fn=scripted_llm(json.dumps({**FACTS, "off_topic": True})))
        self.assertIn("无关", str(ctx.exception))

    def test_unparseable_facts_raise(self):
        dossier = research_mod.research("李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_pages=1)
        with self.assertRaises(DistillError):
            distill_mod.distill(dossier, llm_fn=scripted_llm("抱歉，我无法回答。"))

    def test_a_missing_framework_still_yields_a_persona(self):
        dossier = research_mod.research("李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_pages=1)
        profile = distill_mod.distill(dossier, llm_fn=scripted_llm(json.dumps(FACTS), "模型跑偏了"))
        self.assertEqual("李某", profile.name)
        self.assertEqual([], profile.mental_models)
        self.assertTrue(profile.boundaries)

    def test_prompts_forbid_filling_gaps_from_general_knowledge(self):
        llm = scripted_llm(json.dumps(FACTS), json.dumps(FRAMEWORK))
        dossier = research_mod.research("李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_pages=1)
        distill_mod.distill(dossier, llm_fn=llm)
        self.assertIn("只使用材料中出现的信息", llm.prompts[0])
        self.assertIn("不要凭常识", llm.prompts[0])

    def test_fenced_json_is_parsed(self):
        self.assertEqual({"a": 1}, distill_mod.parse_json_object('前言\n```json\n{"a": 1}\n```'))

    def test_round_trip_through_dict(self):
        profile = build_profile()
        again = PersonaProfile.from_dict(profile.to_dict())
        self.assertEqual(profile.name, again.name)
        self.assertEqual(profile.state, again.state)
        self.assertEqual([m.name for m in profile.mental_models], [m.name for m in again.mental_models])
        self.assertEqual(profile.voice.phrases, again.voice.phrases)


class TestRenderers(unittest.TestCase):
    def setUp(self):
        self.profile = build_profile()

    def test_agent_payload_matches_the_create_agent_shape(self):
        payload = render_mod.agent_payload(self.profile)
        for key in ("name", "gender", "age", "hukou", "residence", "job", "personality",
                    "daily_life", "values", "education_income", "social_network", "state"):
            self.assertIn(key, payload)
        self.assertEqual(9, len(payload["state"]))

    def test_blank_fields_fall_back_rather_than_writing_empty(self):
        self.profile.education_income = ""
        self.assertEqual("待补充", render_mod.agent_payload(self.profile)["education_income"])

    def test_profile_block_carries_the_framework(self):
        block = render_mod.profile_block(self.profile)
        self.assertIn(render_mod.FRAMEWORK_HEADING, block)
        self.assertIn("订单即信号", block)
        self.assertIn("如果账期超过90天", block)
        self.assertIn("画像边界", block)

    def test_profile_block_is_empty_without_a_framework(self):
        bare = PersonaProfile(name="无名")
        self.assertEqual("", render_mod.profile_block(bare))

    def test_insert_block_goes_ahead_of_the_closing_rule(self):
        section = "## Profile 61｜李某\n\n**基础信息**：男\n\n---"
        merged = render_mod.insert_block(section, "\n**思维框架**\n\n- 订单即信号\n")
        self.assertTrue(merged.endswith("---"), "the separator between residents was lost")
        self.assertLess(merged.index("思维框架"), merged.rindex("---"))

    def test_insert_block_appends_when_there_is_no_rule(self):
        merged = render_mod.insert_block("## Profile 61｜李某", "**思维框架**")
        self.assertTrue(merged.endswith("**思维框架**"))

    def test_insert_block_leaves_the_text_alone_when_there_is_nothing_to_add(self):
        self.assertEqual("## Profile 61", render_mod.insert_block("## Profile 61\n", ""))

    def test_skill_markdown_has_front_matter_and_nuwa_sections(self):
        text = render_mod.skill_markdown(self.profile)
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: li-mou-perspective", text)
        for heading in ("## 心智模型", "## 决策启发式", "## 表达 DNA", "## 诚实边界", "## 资料来源"):
            self.assertIn(heading, text)

    def test_skill_markdown_says_so_when_nothing_was_distilled(self):
        bare = PersonaProfile(name="无名", slug="wu-ming", boundaries=["资料不足"])
        text = render_mod.skill_markdown(bare)
        self.assertIn("材料不足以支撑", text)
        self.assertIn("资料不足", text)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("GAWORLD_PERSONA_DIR")
        os.environ["GAWORLD_PERSONA_DIR"] = self.tmp
        self.profile = build_profile()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("GAWORLD_PERSONA_DIR", None)
        else:
            os.environ["GAWORLD_PERSONA_DIR"] = self._prev

    def test_save_writes_three_files(self):
        dossier = research_mod.research("李某", search_fn=fake_search(), fetch_fn=fake_fetch(), max_pages=1)
        target = store_mod.save(self.profile, dossier)
        for name in ("persona.json", "SKILL.md", "research.md"):
            self.assertTrue((target / name).exists(), name)
        self.assertIn("https://", (target / "research.md").read_text(encoding="utf-8"))

    def test_load_round_trips(self):
        store_mod.save(self.profile)
        again = store_mod.load("li-mou")
        self.assertIsNotNone(again)
        self.assertEqual("李某", again.name)
        self.assertEqual(2, len(again.mental_models))

    def test_list_reports_the_archive(self):
        store_mod.save(self.profile)
        rows = store_mod.list_personas()
        self.assertEqual(1, len(rows))
        self.assertEqual("li-mou", rows[0]["slug"])
        self.assertEqual(2, rows[0]["mental_models"])

    def test_unknown_slug_loads_as_none(self):
        self.assertIsNone(store_mod.load("nobody"))

    def test_path_traversal_is_rejected(self):
        for bad in ("../evil", "a/b", ""):
            with self.assertRaises(ValueError):
                store_mod.persona_dir(bad)

    def test_install_skill_refuses_to_overwrite_silently(self):
        skills = os.path.join(self.tmp, "skills")
        os.environ["GAWORLD_SKILLS_DIR"] = skills
        try:
            store_mod.save(self.profile)
            first = store_mod.install_skill("li-mou")
            self.assertTrue(first["installed"])
            self.assertTrue(os.path.exists(first["path"]))
            second = store_mod.install_skill("li-mou")
            self.assertFalse(second["installed"])
            self.assertEqual("exists", second["reason"])
            self.assertTrue(store_mod.install_skill("li-mou", overwrite=True)["installed"])
        finally:
            os.environ.pop("GAWORLD_SKILLS_DIR", None)


if __name__ == "__main__":
    unittest.main()
