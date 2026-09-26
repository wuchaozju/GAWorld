"""Creating a city that does not exist, from a description or a sketch."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gaworld.city.create import CityCreationError, create_city
from gaworld.city.imagine import ImagineError, build_from_design, imagine_city
from gaworld.world.city_map import load_city_map

#: A well-formed design, as a cooperative model would return it. Deliberately
#: Chinese-named throughout: the map layer infers categories from *English*
#: keywords, so this is the case where declaring them explicitly matters.
ISLAND_DESIGN = {
    "summary": "热带火山岛上的渔业与潜水旅游小城",
    "scale": "small",
    "climate": "tropical",
    "river": {"name": "翡翠溪", "path": [[0.1, 0.7], [0.45, 0.5], [0.9, 0.45]], "width": 0.06},
    "districts": [
        {
            "name": "老港区", "category": "commerce", "x": 0.2, "y": 0.3,
            "places": ["鱼市", "妈祖庙"], "place_categories": ["commerce", "leisure"],
        },
        {
            "name": "礁石居", "category": "residential", "x": 0.45, "y": 0.25,
            "places": ["社区卫生站"], "place_categories": ["medical"],
        },
        {
            "name": "火山北麓", "category": "leisure", "x": 0.5, "y": 0.92,
            "places": ["火山口观景台"], "place_categories": ["leisure"],
        },
        {
            "name": "渔获加工区", "category": "industry", "x": 0.85, "y": 0.35,
            "places": ["冷库"], "place_categories": ["industry"],
        },
    ],
    "roads": [["老港区", "礁石居"], ["礁石居", "渔获加工区"]],
    "metro": None,
    "industries": [{"name": "潜水旅游", "weight": 0.45, "trend": "growing", "note": "旺季四个月"}],
    "priorities": ["珊瑚礁保育"],
    "labor_demand": ["潜水教练"],
}


def stub_llm(design):
    """An ``llm_fn`` that answers with *design*, fenced the way models do."""

    def call(prompt, images=None):
        return "```json\n" + json.dumps(design, ensure_ascii=False) + "\n```"

    return call


class ImagineDesignTest(unittest.TestCase):
    def test_a_design_renders_to_a_loadable_map(self):
        city = build_from_design(ISLAND_DESIGN, "翡翠屿")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(city.spec, encoding="utf-8")
            built = load_city_map(str(path))
        self.assertEqual(
            [node["name"] for node in built["nodes"].values() if node["kind"] == "hub"],
            ["老港区", "礁石居", "火山北麓", "渔获加工区"],
        )

    def test_chinese_places_keep_the_category_the_design_declared(self):
        # infer_category would file every one of these under "mixed", which
        # decides their capacity, opening hours and what agents can do there.
        city = build_from_design(ISLAND_DESIGN, "翡翠屿")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(city.spec, encoding="utf-8")
            built = load_city_map(str(path))
        categories = {node["name"]: node["category"] for node in built["nodes"].values()}
        self.assertEqual(categories["鱼市"], "commerce")
        self.assertEqual(categories["社区卫生站"], "medical")
        self.assertEqual(categories["冷库"], "industry")

    def test_a_residential_district_gets_housing_with_interiors(self):
        city = build_from_design(ISLAND_DESIGN, "翡翠屿")
        self.assertIn("- Floor:", city.spec)
        self.assertIn("- Flat:", city.spec)

    def test_relative_coordinates_preserve_the_described_compass(self):
        # y=1 is north by the prompt's convention, and the map layer's +y is
        # north too; a silent flip would put the volcano south of the harbour.
        city = build_from_design(ISLAND_DESIGN, "翡翠屿")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(city.spec, encoding="utf-8")
            built = load_city_map(str(path))
        nodes = {node["name"]: node for node in built["nodes"].values()}
        self.assertGreater(nodes["火山北麓"]["grid_y"], nodes["老港区"]["grid_y"])
        self.assertGreater(nodes["渔获加工区"]["grid_x"], nodes["老港区"]["grid_x"])

    def test_a_district_the_model_forgot_to_link_is_still_reachable(self):
        # 火山北麓 appears in no road pair, so nobody who works there could get
        # home — the graph has to be repaired, not rendered as designed.
        city = build_from_design(ISLAND_DESIGN, "翡翠屿")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(city.spec, encoding="utf-8")
            built = load_city_map(str(path))
        linked = set()
        for edge in built["edges"]:
            linked.add(edge["source"])
            linked.add(edge["target"])
        for hub in ("老港区", "礁石居", "火山北麓", "渔获加工区"):
            self.assertIn(hub, linked)

    def test_a_bogus_category_falls_back_to_mixed(self):
        design = json.loads(json.dumps(ISLAND_DESIGN))
        design["districts"][0]["category"] = "纯属瞎编"
        city = build_from_design(design, "翡翠屿")
        self.assertIn("| category=mixed |", city.spec)

    def test_out_of_range_coordinates_are_clamped_not_fatal(self):
        design = json.loads(json.dumps(ISLAND_DESIGN))
        design["districts"][0]["x"] = 47.0
        design["districts"][1]["y"] = -3.0
        city = build_from_design(design, "翡翠屿")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "citymap.md"
            path.write_text(city.spec, encoding="utf-8")
            load_city_map(str(path))  # must not raise

    def test_duplicate_district_names_are_dropped(self):
        design = json.loads(json.dumps(ISLAND_DESIGN))
        design["districts"].append(dict(design["districts"][0]))
        city = build_from_design(design, "翡翠屿")
        self.assertEqual(len(city.districts), len(set(city.districts)))

    def test_a_two_stop_metro_is_not_a_metro(self):
        design = json.loads(json.dumps(ISLAND_DESIGN))
        design["metro"] = {"name": "1号线", "stops": ["老港区", "礁石居"]}
        self.assertNotIn("@metro:", build_from_design(design, "翡翠屿").spec)

    def test_a_design_with_no_districts_is_rejected(self):
        with self.assertRaises(ImagineError):
            build_from_design({"summary": "空城"}, "翡翠屿")

    def test_unparseable_output_is_an_imagine_error(self):
        with self.assertRaises(ImagineError):
            imagine_city("翡翠屿", description="一座岛城", llm_fn=lambda p, **k: "抱歉，我做不到。")

    def test_no_description_and_no_sketch_is_an_imagine_error(self):
        with self.assertRaises(ImagineError):
            imagine_city("翡翠屿", llm_fn=stub_llm(ISLAND_DESIGN))

    def test_a_sketch_reaches_the_model_as_an_image(self):
        seen = {}

        def call(prompt, images=None):
            seen["images"] = images
            return json.dumps(ISLAND_DESIGN, ensure_ascii=False)

        city = imagine_city(
            "翡翠屿",
            images=[{"media_type": "image/png", "data": "QUJD"}],
            llm_fn=call,
        )
        self.assertEqual(seen["images"][0]["media_type"], "image/png")
        self.assertEqual(city.source, "image")

    def test_an_explicit_scale_overrides_the_designed_one(self):
        city = imagine_city(
            "翡翠屿", description="一座岛城", scale="metro", llm_fn=stub_llm(ISLAND_DESIGN)
        )
        self.assertEqual(city.scale, "metro")


class ImaginedCityBundleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def create(self, **kwargs):
        return create_city(
            "翡翠屿",
            root=self.root,
            description="热带火山岛，靠渔业和潜水旅游为生，北边是火山",
            design_llm_fn=stub_llm(ISLAND_DESIGN),
            **kwargs,
        )

    def test_the_bundle_is_complete_and_virtual(self):
        city = self.create()
        self.assertTrue(city.manifest_path.exists())
        self.assertTrue(city.virtual_map_path.exists())
        self.assertFalse(city.real_map_path.exists())
        self.assertEqual(city.map_mode, "virtual")
        self.assertEqual(city.manifest["place"]["source"], "imagined")

    def test_the_described_climate_drives_the_environment(self):
        # The whole point of routing climate through a latitude: a described
        # tropical island must get typhoons, not the default anchor's drizzle.
        environment = json.loads(self.create().environment_path.read_text(encoding="utf-8"))
        self.assertEqual(environment["climate"], "tropical")
        self.assertIn("热带火山岛上的渔业与潜水旅游小城", environment["background"])

    def test_the_economy_comes_from_the_design_not_from_a_web_search(self):
        def explode(query):
            raise AssertionError("an invented city must not be searched for")

        profile = json.loads(self.create(search_fn=explode).knowledge_path.read_text(encoding="utf-8"))
        self.assertEqual(profile["source"], "imagined")
        self.assertEqual([i["name"] for i in profile["industries"]], ["潜水旅游"])

    def test_the_brief_is_recorded_on_the_manifest(self):
        manifest = self.create().manifest
        self.assertEqual(manifest["imagined"]["source"], "description")
        self.assertIn("火山", manifest["imagined"]["description"])
        self.assertIn("map.imagined", [e["action"] for e in manifest["history"]])

    def test_a_model_that_cannot_design_fails_loudly(self):
        # Silently falling back to the name-seeded generator would hand back a
        # city that ignored the description while looking like it honoured it.
        with self.assertRaises(CityCreationError):
            create_city(
                "翡翠屿",
                root=self.root,
                description="热带火山岛",
                design_llm_fn=lambda p, **k: "对不起",
            )

    def test_no_description_still_takes_the_ordinary_offline_route(self):
        city = create_city("柳溪村", offline=True, scale="tiny", root=self.root)
        self.assertNotIn("imagined", city.manifest)
        self.assertEqual(city.manifest["place"]["source"], "offline")


if __name__ == "__main__":
    unittest.main()
