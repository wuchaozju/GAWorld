"""City knowledge base: sourcing, the four influence channels, and the guards.

The guards matter as much as the features here. A city profile is treated as
fact by every downstream channel, so "we could not find out" must produce an
*empty* profile rather than a confident wrong one — from either the web path or
the map path.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gaworld.city import news as news_mod
from gaworld.city.context import CityContext, clear_cache, load_context
from gaworld.city.knowledge import (
    CityProfile,
    Industry,
    build_from_map,
    build_from_web,
    map_category_counts,
)

_PROFILE = {
    "name": "柯桥区",
    "summary": "纺织为核心，正培育文旅与跨境电商。",
    "industries": [
        {"name": "纺织业", "weight": 0.5, "trend": "stable", "note": "全球最大集散地"},
        {"name": "旅游业", "weight": 0.3, "trend": "growing", "note": "全域旅游"},
        {"name": "跨境电商", "weight": 0.2, "trend": "growing", "note": ""},
    ],
    "priorities": ["全域旅游", "数字贸易"],
    "labor_demand": ["导游", "跨境电商运营"],
    "source": "web",
}


def _llm_returning(payload: dict) -> object:
    return lambda prompt: json.dumps(payload, ensure_ascii=False)


def _search_returning(*items: dict) -> object:
    return lambda query: list(items)


class IndustryCategoryTests(unittest.TestCase):
    def test_free_form_names_map_onto_the_economy_taxonomy(self):
        for name, expected in [
            ("旅游业", "service"),
            ("跨境电商", "trade"),
            ("软件开发", "tech"),
            ("生物医药", "medical"),
            ("职业教育", "education"),
            ("金融服务", "finance"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(Industry(name=name).category(), expected)

    def test_specific_hints_win_over_the_broad_service_bucket(self):
        # "金融服务" contains 服务; it must still classify as finance.
        self.assertEqual(Industry(name="金融服务").category(), "finance")
        self.assertEqual(Industry(name="医疗服务").category(), "medical")

    def test_unclassifiable_industry_falls_back_rather_than_vanishing(self):
        self.assertEqual(Industry(name="采矿").category(), "service")


class WebSourcingTests(unittest.TestCase):
    def test_builds_a_profile_from_search_results(self):
        profile = build_from_web(
            "柯桥区",
            search_fn=_search_returning({"title": "柯桥纺织", "excerpt": "纺织业为主", "url": "u1"}),
            llm_fn=_llm_returning(_PROFILE),
        )
        self.assertIsNotNone(profile)
        self.assertEqual(profile.source, "web")
        self.assertEqual([i.name for i in profile.industries], ["纺织业", "旅游业", "跨境电商"])
        self.assertEqual([i.name for i in profile.growing()], ["旅游业", "跨境电商"])

    def test_prompt_forbids_filling_gaps_from_general_knowledge(self):
        seen = {}

        def capture(prompt):
            seen["prompt"] = prompt
            return json.dumps(_PROFILE, ensure_ascii=False)

        build_from_web("柯桥区", search_fn=_search_returning({"title": "t", "excerpt": "e"}), llm_fn=capture)
        self.assertIn("不要凭常识补充或推测", seen["prompt"])

    def test_no_search_results_yields_no_profile(self):
        self.assertIsNone(build_from_web("X", search_fn=lambda q: [], llm_fn=_llm_returning(_PROFILE)))

    def test_search_failure_is_not_fatal(self):
        def boom(query):
            raise OSError("no network")

        self.assertIsNone(build_from_web("X", search_fn=boom, llm_fn=_llm_returning(_PROFILE)))

    def test_llm_failure_or_garbage_yields_no_profile(self):
        search = _search_returning({"title": "t", "excerpt": "e"})

        def boom(prompt):
            raise RuntimeError("llm down")

        self.assertIsNone(build_from_web("X", search_fn=search, llm_fn=boom))
        self.assertIsNone(build_from_web("X", search_fn=search, llm_fn=lambda p: "sorry, no"))


class MapSourcingTests(unittest.TestCase):
    def test_rich_map_produces_a_profile(self):
        profile = build_from_map("X", {"industry": 18, "commerce": 12, "leisure": 9})
        self.assertEqual(profile.source, "map")
        self.assertEqual(profile.industries[0].name, "制造业")

    def test_thin_map_refuses_to_claim_an_economy(self):
        # A real bundle: 55 housing blocks + 22 schools. Counting tagged nodes
        # would call this "100% education"; that is tagging density, not work.
        profile = build_from_map("绍兴市", {"residential": 55, "education": 22})
        self.assertEqual(profile.source, "stub")
        self.assertTrue(profile.is_empty)
        self.assertEqual(profile.industry_conditions(), {})

    def test_too_few_nodes_refuses_as_well(self):
        self.assertTrue(build_from_map("X", {"education": 3, "industry": 2}).is_empty)

    def test_map_never_invents_a_trend(self):
        profile = build_from_map("X", {"industry": 18, "commerce": 12, "leisure": 9})
        self.assertEqual({i.trend for i in profile.industries}, {"stable"})

    def test_counts_only_point_features(self):
        geojson = {
            "features": [
                {"geometry": {"type": "Point"}, "properties": {"category": "industry"}},
                {"geometry": {"type": "LineString"}, "properties": {"category": "industry"}},
            ]
        }
        self.assertEqual(map_category_counts(geojson), {"industry": 1})


class IndustryConditionsTests(unittest.TestCase):
    """Channel C: the profile biases what local work pays."""

    def test_trend_separates_cities_with_identical_shares(self):
        def tech_condition(trend):
            profile = CityProfile.from_dict({
                "industries": [
                    {"name": "软件开发", "weight": 0.5, "trend": trend},
                    {"name": "零售", "weight": 0.5, "trend": "stable"},
                ]
            })
            return profile.industry_conditions()["tech"]

        self.assertGreater(tech_condition("growing"), tech_condition("stable"))
        self.assertGreater(tech_condition("stable"), tech_condition("declining"))

    def test_a_balanced_city_is_neutral(self):
        profile = CityProfile.from_dict({
            "industries": [
                {"name": "软件开发", "weight": 0.5, "trend": "stable"},
                {"name": "零售", "weight": 0.5, "trend": "stable"},
            ]
        })
        self.assertEqual(set(profile.industry_conditions().values()), {1.0})

    def test_values_stay_inside_the_economy_clip_range(self):
        for industries in (
            [{"name": "软件开发", "weight": 1.0, "trend": "growing"}],
            [{"name": "煤炭", "weight": 1.0, "trend": "declining"}],
        ):
            profile = CityProfile.from_dict({"industries": industries})
            for value in profile.industry_conditions().values():
                self.assertGreaterEqual(value, 0.5)
                self.assertLessEqual(value, 1.5)

    def test_empty_profile_yields_no_override(self):
        # Callers must keep their own defaults rather than receive a uniform
        # distribution pretending to be knowledge.
        self.assertEqual(CityProfile().industry_conditions(), {})
        self.assertEqual(CityProfile().industry_mix(), {})


class NewsClockTests(unittest.TestCase):
    """The two clocks: fetch on real time, serve on sim time."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "news.json"
        self.calls = 0
        self.t0 = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)
        self.addCleanup(self.tmp.cleanup)

    def _search(self, query):
        self.calls += 1
        return [{"title": f"{query}-{self.calls}", "excerpt": "x", "url": f"u{self.calls}"}]

    def test_a_year_of_sim_days_inside_one_window_fetches_once(self):
        for day in range(365):
            news_mod.refresh(
                self.path, "绍兴", search_fn=self._search,
                ttl_hours=6, now=self.t0 + timedelta(seconds=day),
            )
        self.assertEqual(self.calls, len(news_mod.news_queries("绍兴")))

    def test_fetches_again_once_real_time_has_passed(self):
        news_mod.refresh(self.path, "绍兴", search_fn=self._search, ttl_hours=6, now=self.t0)
        before = self.calls
        news_mod.refresh(
            self.path, "绍兴", search_fn=self._search, ttl_hours=6,
            now=self.t0 + timedelta(hours=7),
        )
        self.assertGreater(self.calls, before)

    def test_sim_days_rotate_through_the_cache(self):
        news_mod.refresh(self.path, "绍兴", search_fn=self._search, ttl_hours=6, now=self.t0)
        news_mod.refresh(
            self.path, "绍兴", search_fn=self._search, ttl_hours=0,
            now=self.t0 + timedelta(hours=1),
        )
        cache = news_mod.load(self.path)
        slices = {tuple(i.title for i in news_mod.for_sim_day(cache, d, per_day=2)) for d in range(4)}
        self.assertGreater(len(slices), 1)

    def test_dead_network_does_not_retry_every_sim_day(self):
        news_mod.refresh(self.path, "绍兴", search_fn=self._search, ttl_hours=6, now=self.t0)
        attempts = {"n": 0}

        def dead(query):
            attempts["n"] += 1
            raise OSError("down")

        for day in range(20):
            news_mod.refresh(
                self.path, "绍兴", search_fn=dead, ttl_hours=1,
                now=self.t0 + timedelta(hours=2, seconds=day),
            )
        # One window elapsed, so one attempt per query — not one per sim-day.
        self.assertLessEqual(attempts["n"], len(news_mod.news_queries("绍兴")))

    def test_corrupt_cache_is_survivable(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(news_mod.load(self.path).items, [])


class ContextChannelTests(unittest.TestCase):
    """The four read-outs agents actually consume."""

    def setUp(self):
        self.context = CityContext(
            slug="keqiao", name="柯桥区", profile=CityProfile.from_dict(_PROFILE)
        )

    def test_prompt_block_names_industries_and_marks_growth(self):
        block = self.context.prompt_block()
        self.assertIn("纺织业", block)
        self.assertIn("旅游业↑", block)

    def test_growth_hint_leads_with_what_the_city_is_short_of(self):
        hint = self.context.growth_hint()
        self.assertIn("导游", hint)
        self.assertIn("旅游业", hint)

    def test_signature_separates_cities(self):
        other = CityContext(slug="other", name="X", profile=CityProfile.from_dict(_PROFILE))
        self.assertNotEqual(self.context.signature(), other.signature())

    def test_signature_is_empty_without_knowledge(self):
        self.assertEqual(CityContext().signature(), "")

    def test_rag_chunks_are_standalone_facts(self):
        chunks = self.context.rag_chunks()
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertIn("柯桥区", chunk)

    def test_empty_context_produces_nothing_on_any_channel(self):
        empty = CityContext()
        self.assertEqual(empty.prompt_block(), "")
        self.assertEqual(empty.growth_hint(), "")
        self.assertEqual(empty.rag_chunks(), [])
        self.assertEqual(empty.industry_mix(), {})

    def test_load_context_without_a_city_is_inert(self):
        clear_cache()
        self.assertTrue(load_context({}).is_empty)

    def test_load_context_survives_a_missing_bundle(self):
        clear_cache()
        self.assertTrue(load_context({"city": "no-such-city-anywhere"}).is_empty)


class GrowthChannelTests(unittest.TestCase):
    """Channel B: the city steers what residents choose to learn."""

    AGENT = {
        "id": 1, "name": "林素", "age": 34, "job": "社区医生",
        "personality": "温和", "daily_life": "规律", "values": "务实",
    }

    def test_city_hint_reaches_the_derivation_prompt(self):
        from gaworld.interests import _build_prompt

        self.assertNotIn("所在城市：", _build_prompt(self.AGENT, 6))
        self.assertIn("所在城市：", _build_prompt(self.AGENT, 6, city_hint="本地紧缺：导游"))

    def test_signature_includes_the_city(self):
        from gaworld.interests import profile_signature

        self.assertNotEqual(profile_signature(self.AGENT), profile_signature(self.AGENT, "cityA"))
        self.assertNotEqual(
            profile_signature(self.AGENT, "cityA"), profile_signature(self.AGENT, "cityB")
        )

    def test_cached_profile_is_not_reused_across_cities(self):
        from gaworld.interests import derive_growth_profile

        calls = []

        def llm(prompt):
            calls.append(prompt)
            return '{"items":[{"name":"导游","kind":"skill"},{"name":"散步","kind":"hobby"}]}'

        cache: dict = {}
        derive_growth_profile(self.AGENT, llm=llm, cache=cache, city_signature="A")
        derive_growth_profile(self.AGENT, llm=llm, cache=cache, city_signature="A")
        self.assertEqual(len(calls), 1, "same city should hit the cache")
        derive_growth_profile(self.AGENT, llm=llm, cache=cache, city_signature="B")
        self.assertEqual(len(calls), 2, "a different city must re-derive")

    def test_opportunity_adoption_is_a_career_skill_not_a_social_hobby(self):
        from gaworld.interests import evolve_growth_profile

        profile = {"items": [{"name": "散步", "kind": "hobby", "last_practiced_day": 5}]}
        out, changes = evolve_growth_profile(
            profile, 6, opportunity_candidates=["导游"],
            config={"adopt_chance": 1.0, "opportunity_factor": 1.0},
            rng=random.Random(0),
        )
        self.assertIn("导游", changes["adopted"])
        item = next(i for i in out["items"] if i["name"] == "导游")
        self.assertEqual(item["kind"], "skill")
        self.assertEqual(item["category"], "职业")
        self.assertTrue(item["career_link"])

    def test_no_candidates_leaves_the_profile_alone(self):
        from gaworld.interests import evolve_growth_profile

        profile = {"items": [{"name": "散步", "kind": "hobby", "last_practiced_day": 6}]}
        out, changes = evolve_growth_profile(profile, 6, rng=random.Random(0))
        self.assertEqual(changes["adopted"], [])
        self.assertEqual([i["name"] for i in out["items"]], ["散步"])


if __name__ == "__main__":
    unittest.main()
