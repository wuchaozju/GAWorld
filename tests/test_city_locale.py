"""Per-city naming, housing and residency.

The bug these tests pin down: a city built from the ``us_suburb`` preset used
to come out statistically American and culturally Chinese — "王伟，本地户籍，
住 西古山·商品房". The contract now is that the *cultural* layer follows the
city while the profile prose stays Chinese, so the simulator's own loaders
(``parse_profile``) and the economy's Chinese job-title keyword matching keep
working untouched.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from gaworld.city.agents import add_population
from gaworld.city.create import create_city
from gaworld.city.geocode import offline_place
from gaworld.city.locale import build_locale, load_locale, research_locale
from gaworld.population.locale import (
    DEFAULT_LOCALE,
    LocaleProfile,
    compose_name,
    normalize_locale,
)
from gaworld.population.schema import normalize_spec
from gaworld.population.synth import derive_rng, synthesize_people
from gaworld.sim.agents_loader import parse_profile

US_LOCALE = {
    "code": "en-US",
    "label": "美国郊区",
    "given_mode": "whole",
    "joiner": " ",
    "given_first": True,
    "surnames": ["Smith", "Johnson", "Williams", "Garcia", "Miller", "Davis"],
    "given_male": ["Michael", "James", "Robert", "David"],
    "given_female": ["Mary", "Jennifer", "Linda", "Susan"],
    "given_neutral": [],
    "residence_suffixes": ["独栋住宅", "联排住宅", "出租公寓"],
    "residency": ["本市", "本州", "外州", "外国"],
    "suggested_overrides": {
        "demography": {"median_age": 39.0, "migrant_share": 0.14},
        "income": {"median_monthly": 5800.0},
    },
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class NormalizeLocaleTest(unittest.TestCase):
    def test_a_partial_profile_falls_back_field_by_field(self):
        # Getting the surnames right but forgetting the housing words should
        # cost Chinese housing words, not an entirely Chinese population.
        locale = normalize_locale({"surnames": ["Smith", "Johnson"], "code": "en-US"})
        self.assertEqual(("Smith", "Johnson"), locale.surnames)
        self.assertEqual(DEFAULT_LOCALE.residence_suffixes, locale.residence_suffixes)
        self.assertEqual(DEFAULT_LOCALE.residency, locale.residency)

    def test_a_character_run_is_split_into_a_pool(self):
        # Models asked for a character pool often answer with one long string.
        locale = normalize_locale({"surnames": "陈黄梁林罗"})
        self.assertEqual(("陈", "黄", "梁", "林", "罗"), locale.surnames)

    def test_a_residency_ladder_of_the_wrong_length_is_rejected(self):
        locale = normalize_locale({"residency": ["本市", "外地"]})
        self.assertEqual(DEFAULT_LOCALE.residency, locale.residency)

    def test_unknown_override_knobs_are_dropped(self):
        locale = normalize_locale(
            {"suggested_overrides": {"demography": {"median_age": 39, "favourite_colour": "red"}}}
        )
        self.assertEqual({"demography": {"median_age": 39.0}}, locale.suggested_overrides)

    def test_an_empty_payload_is_the_mainland_default(self):
        locale = normalize_locale({})
        for field in ("surnames", "given_male", "given_female", "residence_suffixes", "residency"):
            self.assertEqual(getattr(DEFAULT_LOCALE, field), getattr(locale, field), field)


class ComposeNameTest(unittest.TestCase):
    def test_western_names_are_given_first_and_space_joined(self):
        locale = normalize_locale(US_LOCALE)
        rng = derive_rng(7, "name")
        names = [compose_name(locale, i % 2 == 0, rng) for i in range(40)]
        for name in names:
            given, _, surname = name.partition(" ")
            self.assertIn(surname, US_LOCALE["surnames"], name)
            self.assertIn(given, US_LOCALE["given_male"] + US_LOCALE["given_female"], name)

    def test_the_default_locale_still_composes_two_character_names(self):
        rng = derive_rng(7, "name")
        names = [compose_name(DEFAULT_LOCALE, True, rng) for _ in range(40)]
        for name in names:
            self.assertIn(len(name), (2, 3), name)
            self.assertIn(name[0], DEFAULT_LOCALE.surnames, name)

    def test_an_empty_gendered_pool_falls_back_to_every_given_name(self):
        locale = LocaleProfile(
            surnames=("陈",), given_male=(), given_female=("兰",), given_neutral=()
        )
        self.assertEqual("陈兰", compose_name(locale, True, np.random.default_rng(0))[:2])


class SynthesizeWithLocaleTest(unittest.TestCase):
    def test_the_sampler_honours_every_layer_of_the_locale(self):
        locale = normalize_locale(US_LOCALE)
        spec = normalize_spec({"size": 120, "seed": 5, "preset": "us_suburb"})
        people, _ = synthesize_people(spec, locale=locale)

        self.assertTrue(people)
        for person in people:
            self.assertIn(person.hukou, ("本市", "本州", "外州", "外国"), person.hukou)
            self.assertIn(person.residence.split("·")[-1], US_LOCALE["residence_suffixes"])
            self.assertIn(" ", person.name)
        # Job titles are deliberately *not* localised: finance.py infers
        # industry by substring-matching Chinese words.
        self.assertTrue(any("一" <= ch <= "鿿" for ch in people[0].job))

    def test_migrants_still_lose_city_identity_under_a_foreign_ladder(self):
        # The state adjustment used to test `hukou != "本地"`, which is simply
        # never true once the ladder reads 本市/本州/外州.
        locale = normalize_locale(US_LOCALE)
        spec = normalize_spec(
            {"size": 300, "seed": 5, "demography": {"migrant_share": 0.5}}
        )
        people, _ = synthesize_people(spec, locale=locale)
        local = [p.state["city_identity"] for p in people if p.hukou == "本市"]
        migrant = [p.state["city_identity"] for p in people if p.hukou != "本市"]
        self.assertGreater(sum(local) / len(local), sum(migrant) / len(migrant))

    def test_the_report_counts_migrants_under_a_foreign_ladder(self):
        # The report used to count `hukou != "本地"`, which under a US ladder
        # made every single resident a migrant — 0.14 requested, 1.00 reported.
        from gaworld.population.generate import generate_population

        result = generate_population(
            normalize_spec({"size": 300, "seed": 5, "demography": {"migrant_share": 0.14}}),
            locale=normalize_locale(US_LOCALE),
        )
        self.assertAlmostEqual(
            0.14, result.report["achieved"]["migrant_share"]["achieved"], places=2
        )

    def test_omitting_the_locale_reproduces_the_old_population(self):
        spec = normalize_spec({"size": 80, "seed": 42})
        default, _ = synthesize_people(spec)
        explicit, _ = synthesize_people(spec, locale=DEFAULT_LOCALE)
        self.assertEqual(
            [(p.name, p.hukou, p.residence) for p in default],
            [(p.name, p.hukou, p.residence) for p in explicit],
        )


class ResearchLocaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.city = create_city("测试镇", offline=True, scale="small", root=self.root)

    def test_a_fenced_json_answer_is_parsed(self):
        def llm(_prompt: str) -> str:
            return "好的：\n```json\n" + json.dumps(US_LOCALE) + "\n```"

        locale = research_locale(offline_place("测试镇"), llm_fn=llm)
        self.assertEqual("en-US", locale.code)
        self.assertEqual("llm", locale.source)

    def test_the_prompt_carries_the_full_administrative_chain(self):
        seen: list[str] = []

        def llm(prompt: str) -> str:
            seen.append(prompt)
            return json.dumps(US_LOCALE)

        research_locale(offline_place("测试镇"), llm_fn=llm)
        self.assertIn("测试镇", seen[0])

    def test_a_failed_call_degrades_to_the_default_and_says_so(self):
        def llm(_prompt: str) -> str:
            raise RuntimeError("no model configured")

        locale = build_locale(self.city, offline_place("测试镇"), llm_fn=llm)
        self.assertEqual(DEFAULT_LOCALE.surnames, locale.surnames)
        actions = [entry.get("action") for entry in self.city.manifest.get("history", [])]
        self.assertIn("locale.default", actions)

    def test_a_cached_locale_round_trips_through_the_bundle(self):
        build_locale(self.city, offline_place("测试镇"), llm_fn=lambda _p: json.dumps(US_LOCALE))
        self.assertTrue(self.city.locale_path.exists())
        self.assertEqual("en-US", load_locale(self.city).code)

    def test_a_corrupt_cache_does_not_break_generation(self):
        self.city.locale_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(DEFAULT_LOCALE.surnames, load_locale(self.city).surnames)


class PopulateWithLocaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.city = create_city("Springfield", offline=True, scale="small", root=self.root)
        self.city.locale_path.write_text(
            json.dumps(US_LOCALE, ensure_ascii=False), encoding="utf-8"
        )

    def test_residents_are_named_and_housed_locally(self):
        add_population(self.city, size=40, seed=3)
        rows = read_rows(self.city.state_csv_path)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(" ", row["name"])
            self.assertIn(row["hukou"], ("本市", "本州", "外州", "外国"))

    def test_the_profiles_still_parse_as_the_simulator_reads_them(self):
        # The whole point of keeping profile prose Chinese: this loader is
        # regex-bound to "…岁，…户籍，居住…" and must not need changing.
        add_population(self.city, size=40, seed=3)
        text = self.city.profiles_md_path.read_text(encoding="utf-8")
        blocks = [b for b in text.split("## Profile ") if b.strip()][1:]
        self.assertTrue(blocks)
        for block in blocks:
            parsed = parse_profile("## Profile " + block)
            self.assertTrue(parsed["name"])
            self.assertGreater(parsed["age"], 0)

    def test_an_omitted_preset_takes_the_locale_demography(self):
        add_population(self.city, size=200, seed=3, replace=True)
        report = json.loads((self.city.directory / "population_manifest.json").read_text())
        self.assertAlmostEqual(0.14, report["achieved"]["migrant_share"]["target"], places=3)

    def test_an_explicit_preset_beats_the_locale_suggestion(self):
        # A caller who asked for aging_community means it.
        add_population(self.city, size=200, seed=3, preset="aging_community", replace=True)
        report = json.loads((self.city.directory / "population_manifest.json").read_text())
        self.assertAlmostEqual(0.12, report["achieved"]["migrant_share"]["target"], places=3)

    def test_explicit_overrides_still_beat_everything(self):
        add_population(
            self.city,
            size=200,
            seed=3,
            replace=True,
            overrides={"demography": {"migrant_share": 0.4}},
        )
        report = json.loads((self.city.directory / "population_manifest.json").read_text())
        self.assertAlmostEqual(0.4, report["achieved"]["migrant_share"]["target"], places=3)


if __name__ == "__main__":
    unittest.main()
