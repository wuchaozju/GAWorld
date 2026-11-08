"""地区档案 —— 让城市与居民长得像那个地方。

背景：城市原来只有三层调研（地理编码、产业知识库、居民命名），环境只按
「纬度带 + 规模」生成天气，居民的日常则是一句全国通用的模板。于是杭州和
临安都是"亚热带、梅雨持续"，居民的档案里也写着同一句"作息规律，日常以工作、
家务和少量社交为主"。

这里钉住的是第四层（``gaworld.city.region``）的行为：

* 调研拿不到证据时不编，档案保持为空（降级而不是假装有）；
* 档案里的灾害与节律**替换**掉纬度带的事件池——山里的城市不该播报台风；
* 档案进入每一步认知看到的城市背景与每位居民的检索记忆；
* 档案里的习惯、饮食、出行写进居民档案的日常那一句；
* 本地产业决定居民的职业分布，但不会把其它行业清零。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gaworld.city.agents import add_population, rewrite_daily_life
from gaworld.city.config import city_overrides
from gaworld.city.context import clear_cache, load_context
from gaworld.city.create import create_city, refresh_environment
from gaworld.city.environment import build_environment
from gaworld.city.geocode import offline_place
from gaworld.city.region import (
    RegionProfile,
    build_region,
    load_region,
    normalize_region,
    research_region,
    search_queries,
)
from gaworld.sim.agents_loader import parse_profile

#: A dossier for a mountain town in Zhejiang — deliberately *not* what a
#: latitude band would produce for it.
LINAN = {
    "code": "CN-ZJ-HZ-LA",
    "label": "浙江·杭州·临安",
    "summary": "西北山地的县域，竹木与山核桃当家，外出务工的人多。",
    "terrain": "西北高、东南低，境内多山丘，天目山横亘西北部",
    "water": "苕溪自西向东穿城而过，汇入富春江",
    "climate": "亚热带季风气候，年均温16.4℃，降水集中在3—6月梅雨期",
    "hazards": ["梅雨集中，山区局部山洪风险上升", "冬季极端低温可达零下8℃"],
    "seasons": ["3—6月梅雨不断，山区易起雾", "7—8月高温，电负荷升高"],
    "culture": ["山民世代采竹，经营竹制品", "宗族观念强，婚丧讲究老规矩"],
    "dialect": "临安话",
    "diet": ["山核桃", "笋干"],
    "commuting": ["电动车", "城乡公交"],
    "festivals": ["端午龙舟赛，江边聚集大量观赛人群"],
    "landmarks": ["天目山", "苕溪"],
    "services": ["县人民医院", "临安中学"],
    "livelihood": "竹林种植与外出务工",
    "habits": ["晚饭吃笋干面", "清晨去菜场挑山核桃"],
    "work_habits": ["骑电动车上下班", "清晨进山采竹"],
    "suggested_overrides": {
        "demography": {"median_age": 41.0, "migrant_share": 0.12, "share_over_65": 0.18},
        "education_work": {"tertiary_rate": 0.18, "employment_rate": 0.62},
        "income": {"median_monthly": 5800.0, "gini": 0.34},
    },
}


def stub_search(hits: list[dict[str, str]]):
    def search(_query: str) -> list[dict[str, str]]:
        return list(hits)

    return search


def stub_llm(payload: dict):
    def llm(_prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    return llm


class NormalizeRegionTest(unittest.TestCase):
    def test_unknown_override_knobs_are_dropped(self):
        region = normalize_region(
            {"suggested_overrides": {"demography": {"median_age": 41, "favourite_colour": "red"}}}
        )
        self.assertEqual({"demography": {"median_age": 41.0}}, region.suggested_overrides)

    def test_a_string_run_becomes_a_pool(self):
        region = normalize_region({"hazards": "山洪风险上升；路面结冰"})
        self.assertEqual(("山洪风险上升", "路面结冰"), region.hazards)

    def test_an_empty_dossier_is_empty(self):
        self.assertTrue(RegionProfile().is_empty)
        self.assertEqual("", RegionProfile().prompt_block())


class ResearchRegionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_the_search_covers_every_facet(self):
        queries = search_queries("临安")
        self.assertEqual(6, len(queries))
        self.assertTrue(all("临安" in q for q in queries))

    def test_search_results_and_a_model_answer_become_a_dossier(self):
        hits = [{"title": "临安气候", "excerpt": "年均温16.4℃", "url": "https://example.cn/a"}]
        region = research_region(
            offline_place("临安"),
            search_fn=stub_search(hits),
            llm_fn=stub_llm(LINAN),
        )
        self.assertIsNotNone(region)
        assert region is not None
        self.assertEqual("web", region.source)
        self.assertEqual("苕溪自西向东穿城而过，汇入富春江", region.water)
        self.assertIn("山洪", region.hazards[0])
        self.assertEqual("https://example.cn/a", region.sources[0]["url"])

    def test_no_search_results_means_no_dossier(self):
        # Better an empty profile than a confident invention about a real place.
        self.assertIsNone(
            research_region(offline_place("临安"), search_fn=stub_search([]), llm_fn=stub_llm(LINAN))
        )

    def test_a_failed_model_call_means_no_dossier(self):
        def llm(_prompt: str) -> str:
            raise RuntimeError("no model configured")

        self.assertIsNone(
            research_region(
                offline_place("临安"),
                search_fn=stub_search([{"title": "x", "excerpt": "y"}]),
                llm_fn=llm,
            )
        )

    def test_a_failed_research_leaves_the_bundle_without_a_dossier(self):
        city = create_city("测试镇", offline=True, scale="small", root=self.root)
        region = build_region(
            city,
            offline_place("测试镇"),
            search_fn=stub_search([]),
            llm_fn=stub_llm(LINAN),
        )
        self.assertTrue(region.is_empty)
        actions = [entry.get("action") for entry in city.manifest.get("history", [])]
        self.assertIn("region.empty", actions)


class EnvironmentFromRegionTest(unittest.TestCase):
    def setUp(self):
        self.region = normalize_region(LINAN)
        self.place = offline_place("临安")

    def test_the_regions_hazards_replace_the_latitude_band(self):
        env = build_environment(self.place, region=self.region)
        natural = env["environment"]["natural_events"]
        # 临安 is a mountain town: a typhoon warning from the latitude band
        # would simply be wrong here.
        self.assertNotIn("台风外围环流影响，风力加大", natural)
        self.assertTrue(any("山洪" in item for item in natural))

    def test_without_a_dossier_the_band_behaviour_is_unchanged(self):
        env = build_environment(self.place)
        self.assertIn("梅雨持续，空气潮湿", env["environment"]["natural_events"])

    def test_the_generator_context_carries_the_terrain_and_the_hazards(self):
        env = build_environment(self.place, region=self.region)
        description = env["external_environment"]["generator"]["description"]
        self.assertIn("苕溪", description)
        self.assertIn("山洪", description)


class CityBackgroundTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.city = create_city("测试镇", offline=True, scale="small", root=self.root)
        build_region(
            self.city,
            offline_place("测试镇"),
            search_fn=stub_search([{"title": "x", "excerpt": "y", "url": "https://example.cn"}]),
            llm_fn=stub_llm(LINAN),
        )
        self.city.save()

    def test_the_region_paragraph_reaches_the_background_prompt(self):
        # Every cognition prompt starts with this string, so it is the one
        # place a resident can learn what their town is like.
        patch = city_overrides(self.city.slug, self.root)
        background = patch.get("background", "")
        self.assertIn("苕溪", background)
        self.assertIn("方言为临安话", background)

    def test_the_region_reaches_the_prompt_block_and_the_rag(self):
        clear_cache()
        context = load_context({"city": self.city.slug}, root=self.root)
        self.assertIn("苕溪", context.prompt_block())
        self.assertTrue(any("本地地理" in chunk for chunk in context.rag_chunks()))

    def test_rebuilding_the_environment_picks_up_the_new_dossier(self):
        refresh_environment(self.city, region=normalize_region(LINAN))
        payload = json.loads(self.city.environment_path.read_text(encoding="utf-8"))
        self.assertTrue(any("山洪" in item for item in payload["environment"]["natural_events"]))


class ResidentFromRegionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.city = create_city("测试镇", offline=True, scale="small", root=self.root)
        build_region(
            self.city,
            offline_place("测试镇"),
            search_fn=stub_search([{"title": "x", "excerpt": "y"}]),
            llm_fn=stub_llm(LINAN),
        )
        self.city.save()

    def test_the_dossier_demography_reaches_the_sampler(self):
        # The region's numbers are only suggestions, and only when the caller
        # did not ask for a specific preset.
        add_population(self.city, size=120, seed=3)
        manifest = json.loads((self.city.directory / "population_manifest.json").read_text(encoding="utf-8"))
        spec = manifest["spec"]
        self.assertEqual(41.0, spec["demography"]["median_age"])
        self.assertEqual(5800.0, spec["income"]["median_monthly"])

    def test_residents_describe_their_days_in_local_terms(self):
        add_population(self.city, size=60, seed=3)
        text = self.city.profiles_md_path.read_text(encoding="utf-8")
        self.assertIn("笋干面", text)
        # …and the profile still parses: the daily-life line is prose, but
        # the 基础信息 contract must not have moved.
        block = text.split("## Profile ")[1]
        parsed = parse_profile("## Profile " + block)
        self.assertIn("日常", parsed["daily_life"])

    def test_a_work_habit_never_lands_on_a_child(self):
        # "骑电动车上下班" on an eight-year-old is the kind of detail that
        # makes a whole simulation look fabricated.
        add_population(self.city, size=200, seed=3)
        text = self.city.profiles_md_path.read_text(encoding="utf-8")
        for block in text.split("## Profile ")[1:]:
            lines = {line.split("**")[1]: line for line in block.splitlines() if line.startswith("**")}
            age = int(lines["基础信息"].split("，")[1].replace("岁", ""))
            daily = lines["日常生活与生活习惯"]
            if age < 18:
                self.assertNotIn("上下班", daily)
                self.assertNotIn("进山采竹", daily)

    def test_the_local_customs_reach_the_values_line(self):
        add_population(self.city, size=40, seed=3)
        text = self.city.profiles_md_path.read_text(encoding="utf-8")
        # The first entry of the dossier's customs, not just any of them.
        self.assertIn(LINAN["culture"][0], text)

    def test_the_local_industry_mix_shifts_the_jobs_without_zeroing_them(self):
        profile = {
            "name": "测试镇",
            "source": "web",
            "industries": [
                {"name": "竹制品加工", "weight": 0.6, "trend": "stable"},
                {"name": "旅游", "weight": 0.4, "trend": "growing"},
            ],
        }
        self.city.knowledge_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        add_population(self.city, size=200, seed=3)
        manifest = json.loads((self.city.directory / "population_manifest.json").read_text(encoding="utf-8"))
        mix = manifest["spec"]["education_work"]["industry_mix"]
        # The local industries carry the weight …
        self.assertGreater(mix["service"], mix["tech"])
        # … but a town with no schools is not what a town without a tech
        # sector looks like.
        self.assertGreater(mix["education"], 0.0)

    def test_a_map_derived_profile_does_not_reshape_the_job_mix(self):
        # The map fallback folds every unknown category into "service", which
        # would put the whole town in one sector.
        profile = {
            "name": "测试镇",
            "source": "map",
            "industries": [{"name": "制造业", "weight": 1.0, "trend": "stable"}],
        }
        self.city.knowledge_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        add_population(self.city, size=120, seed=3)
        manifest = json.loads((self.city.directory / "population_manifest.json").read_text(encoding="utf-8"))
        mix = manifest["spec"]["education_work"]["industry_mix"]
        self.assertGreater(mix["tech"], 0.0)
        self.assertGreater(mix["education"], 0.0)


class MigratedResidentTest(unittest.TestCase):
    def test_the_old_citys_daily_life_is_replaced(self):
        block = (
            "\n## Profile 07｜王伟\n"
            "**基础信息**：男，34岁，本地户籍，居住于余杭·商品房。\n\n"
            "**日常生活与生活习惯**：工作日节奏规律，通勤与工作占据主要时段；"
            "周末用于补觉、家务和少量社交。\n\n"
            "**社交网络情况**：当前在模拟内共有 3 条社会关系。\n\n"
        )
        updated = rewrite_daily_life(block, "骑电动车上下班，晚饭吃笋干面")
        self.assertIn("笋干面", updated)
        # The person's own routine survives; only the local half is added.
        self.assertIn("通勤与工作占据主要时段", updated)


class RegionApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.city = create_city("测试镇", offline=True, scale="small", root=self.root)
        build_region(
            self.city,
            offline_place("测试镇"),
            search_fn=stub_search([{"title": "x", "excerpt": "y"}]),
            llm_fn=stub_llm(LINAN),
        )
        self.city.save()

    def test_the_panel_endpoint_returns_the_dossier_and_its_channels(self):
        from gaworld.apps.city_api import region as region_endpoint

        # The panel resolves cities against the project root, so a bundle
        # outside it is addressed by its directory.
        payload = region_endpoint(str(self.city.directory))
        self.assertFalse(payload["empty"])
        self.assertIn("苕溪", payload["channels"]["background"])
        self.assertTrue(payload["channels"]["events"]["natural"])

    def test_the_dossier_round_trips_through_the_bundle(self):
        self.assertTrue(self.city.region_path.exists())
        reloaded = load_region(self.city)
        self.assertEqual("浙江·杭州·临安", reloaded.label)
        self.assertEqual(2, len(reloaded.hazards))


if __name__ == "__main__":
    unittest.main()
