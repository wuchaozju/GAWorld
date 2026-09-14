"""Adding agents to a city: bulk synthesis, single append, migration.

The binding contract these tests defend: whatever lands in a bundle must be
readable by the simulator's own loaders, so every case round-trips through
``gaworld.sim.agents_loader.parse_profile`` rather than trusting the writer.
"""

from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gaworld.city.agents import (
    AgentError,
    add_agent,
    add_population,
    city_districts,
    migrate_agent,
    rewrite_residence,
)
from gaworld.city.create import create_city
from gaworld.sim.agents_loader import parse_profile

PROFILE_SPLIT = re.compile(r"(?=^## Profile )", re.M)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [b for b in PROFILE_SPLIT.split(text) if b.lstrip().startswith("## Profile")]


class ResidenceRewriteTest(unittest.TestCase):
    """Both corpus styles have to be rewritable, or migration silently lies."""

    def test_rewrites_the_generated_style(self):
        block, previous = rewrite_residence("**基础信息**：女，34岁，本地户籍，居住于余杭·商品房。", "A·B")
        self.assertEqual(previous, "余杭·商品房")
        self.assertIn("居住于A·B。", block)

    def test_rewrites_the_hand_authored_style(self):
        # data/hangzhou_profiles_with_names.md omits the 于 and uses a bare
        # district — a literal string replace against the CSV value misses it.
        block, previous = rewrite_residence("**基础信息**：男，63岁，本地户籍，居住西湖区。", "Lake Block·自住房")
        self.assertEqual(previous, "西湖区")
        self.assertIn("居住Lake Block·自住房。", block)

    def test_block_without_a_residence_clause_is_untouched(self):
        block, previous = rewrite_residence("## Profile 01｜甲", "X")
        self.assertEqual(previous, "")
        self.assertEqual(block, "## Profile 01｜甲")


class CityAgentsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.city = create_city("测试镇", offline=True, scale="small", root=self.root)

    # -- helpers ----------------------------------------------------------

    def assert_corpus_is_loadable(self):
        """Every row pairs with a parseable block that agrees with it."""
        rows = read_rows(self.city.state_csv_path)
        blocks = read_blocks(self.city.profiles_md_path)
        self.assertEqual(len(rows), len(blocks))
        self.assertEqual(
            [int(r["id"]) for r in rows], list(range(1, len(rows) + 1)), "ids must be contiguous"
        )
        districts = set(city_districts(self.city))
        for row, block in zip(rows, blocks):
            profile = parse_profile(block)
            self.assertEqual(profile["name"], row["name"])
            self.assertEqual(str(profile["age"]), row["age"])
            self.assertEqual(profile["living"], row["residence"])
            self.assertIn(
                profile["living"].split("·")[0], districts, "residence must name a real district"
            )
        return rows

    # -- bulk synthesis ---------------------------------------------------

    def test_add_population_writes_a_loadable_corpus(self):
        result = add_population(self.city, size=25, seed=3)
        self.assertEqual(result["added"], 25)
        self.assertEqual(result["total"], 25)
        self.assertEqual(len(self.assert_corpus_is_loadable()), 25)
        self.assertEqual(self.city.population_count, 25)

    def test_second_batch_appends_and_renumbers(self):
        add_population(self.city, size=20, seed=1)
        result = add_population(self.city, size=24, seed=2)
        self.assertEqual(result["added"], 24)
        self.assertEqual(result["total"], 44)
        self.assert_corpus_is_loadable()

    def test_replace_discards_the_previous_batch(self):
        add_population(self.city, size=30, seed=1)
        result = add_population(self.city, size=22, seed=2, replace=True)
        self.assertEqual(result["total"], 22)
        self.assertEqual(len(self.assert_corpus_is_loadable()), 22)

    def test_size_below_the_samplers_floor_is_reported_not_hidden(self):
        # normalize_spec clamps to >= 20 so the IPF stays well-conditioned; a
        # caller asking for 5 must be able to see it actually got 20.
        result = add_population(self.city, size=5, seed=1)
        self.assertEqual(result["requested"], 5)
        self.assertEqual(result["added"], 20)
        self.assertEqual(result["total"], 20)

    def test_residents_live_in_districts_this_city_actually_has(self):
        add_population(self.city, size=30, seed=5)
        districts = set(city_districts(self.city))
        residences = {r["residence"].split("·")[0] for r in read_rows(self.city.state_csv_path)}
        self.assertTrue(residences <= districts, residences - districts)

    # -- single agent -----------------------------------------------------

    def test_add_agent_appends_to_an_empty_city(self):
        result = add_agent(self.city, name="林素", age=34, job="社区医生")
        self.assertEqual(result["id"], 1)
        rows = self.assert_corpus_is_loadable()
        self.assertEqual(rows[0]["name"], "林素")
        self.assertEqual(parse_profile(read_blocks(self.city.profiles_md_path)[0])["job"], "社区医生")

    def test_add_agent_continues_the_existing_numbering(self):
        add_population(self.city, size=20, seed=4)
        result = add_agent(self.city, name="马建国", age=47, gender="男")
        self.assertEqual(result["id"], 21)
        self.assertEqual(result["total"], 21)
        self.assert_corpus_is_loadable()

    def test_explicit_residence_is_honoured(self):
        result = add_agent(self.city, name="甲", age=30, residence="自定义区·自建房")
        self.assertEqual(result["residence"], "自定义区·自建房")

    def test_blank_name_is_rejected(self):
        with self.assertRaises(AgentError):
            add_agent(self.city, name="  ", age=30)

    # -- migration --------------------------------------------------------

    def test_migrate_from_another_city_rehomes_the_agent(self):
        source = create_city("来源市", offline=True, scale="small", root=self.root)
        add_population(source, size=20, seed=9)
        add_population(self.city, size=20, seed=8)

        source_rows = read_rows(source.state_csv_path)
        result = migrate_agent(
            self.city,
            2,
            source_csv=source.state_csv_path,
            source_md=source.profiles_md_path,
        )
        self.assertEqual(result["id"], 21)
        self.assertEqual(result["name"], source_rows[1]["name"])
        # The whole point: the profile must not still claim the source city.
        self.assert_corpus_is_loadable()

    def test_migrate_can_keep_the_original_residence(self):
        source = create_city("来源市2", offline=True, scale="small", root=self.root)
        add_population(source, size=20, seed=11)
        original = read_rows(source.state_csv_path)[0]["residence"]

        migrate_agent(
            self.city,
            1,
            source_csv=source.state_csv_path,
            source_md=source.profiles_md_path,
            rehome=False,
        )
        self.assertEqual(read_rows(self.city.state_csv_path)[0]["residence"], original)

    def test_migrating_from_the_default_corpus_rewrites_its_bare_district(self):
        """The shipped corpus writes '居住西湖区。', a different shape entirely."""
        csv_path = Path("data/hangzhou_agents_state_init.csv")
        md_path = Path("data/hangzhou_profiles_with_names.md")
        if not csv_path.exists() or not md_path.exists():
            self.skipTest("default corpus not present")

        migrate_agent(self.city, 31, source_csv=csv_path, source_md=md_path)
        rows = self.assert_corpus_is_loadable()
        self.assertNotIn("西湖", rows[0]["residence"])

    def test_missing_agent_raises(self):
        source = create_city("来源市3", offline=True, scale="small", root=self.root)
        add_population(source, size=20, seed=12)
        with self.assertRaises(AgentError):
            migrate_agent(
                self.city,
                999,
                source_csv=source.state_csv_path,
                source_md=source.profiles_md_path,
            )


if __name__ == "__main__":
    unittest.main()
