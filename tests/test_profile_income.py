"""The income a profile states is the income the ledger runs on.

Until now ``parse_profile`` never read the "月收入约 …元" line, so
``_init_agent_economy`` re-rolled a salary from the job text instead. Measured
across 326 residents the two agreed only weakly (r=0.305): the ledger paid
1.39x the stated figure at the median, up to 3.47x at p90, and flattened the
income Gini the population synthesiser had fitted (0.468 -> 0.348).
"""

from __future__ import annotations

import unittest

from gaworld.economy import finance
from gaworld.sim.agents_loader import parse_profile

BLOCK = """## Profile 07｜张三
**基础信息**：男，31岁，本地户籍，居住于滨江·老小区。

**教育与收入背景**：大专学历，月收入约 9,117 元。

**职业与工作节奏**：跨境电商经营

**性格与情绪特征**：平和。

**日常生活与生活习惯**：规律。

**价值观与公共事务态度**：关注公共事务。
"""


def _profile(income_line):
    return BLOCK.replace("**教育与收入背景**：大专学历，月收入约 9,117 元。",
                         f"**教育与收入背景**：{income_line}")


class TestIncomeParsing(unittest.TestCase):
    def test_the_synthesiser_phrasing(self):
        self.assertEqual(parse_profile(BLOCK)["monthly_income"], 9117.0)

    def test_the_hand_written_corpus_phrasing(self):
        """The older corpus writes it without a space and with a comma."""
        block = _profile("本科毕业于省内一本高校计算机专业，目前月收入约12,000元，收入稳定。")
        self.assertEqual(parse_profile(block)["monthly_income"], 12000.0)

    def test_no_stated_income_is_none_not_zero(self):
        block = _profile("重点高校计算机相关专业硕士在读，无固定收入。")
        self.assertIsNone(parse_profile(block)["monthly_income"])

    def test_a_full_width_comma_still_parses(self):
        self.assertEqual(parse_profile(_profile("月收入约 8，500 元。"))["monthly_income"], 8500.0)


def _agent(monthly_income=None, job="跨境电商经营"):
    agent = {"id": 1, "job": job, "personality": "", "daily_life": "", "values": "", "state": {}}
    if monthly_income is not None:
        agent["monthly_income"] = monthly_income
    return agent


def _salary(agent, seed=7, **overrides):
    cfg = dict(finance.DEFAULT_ECONOMY_CONFIG)
    cfg.update(overrides)
    finance._rng.seed(seed)
    target = dict(agent)
    finance._init_agent_economy(target, cfg, {})
    return target["economy"]["gross_monthly_salary"]


class TestEconomyAnchorsOnTheProfile(unittest.TestCase):
    def test_the_ledger_pays_what_the_profile_says(self):
        stated = 9117.0
        salary = _salary(_agent(stated))
        self.assertAlmostEqual(salary / stated, 1.0, delta=0.09)

    def test_jitter_zero_reproduces_the_figure_exactly(self):
        self.assertAlmostEqual(_salary(_agent(9117.0), profile_income_jitter=0.0), 9117.0, places=0)

    def test_a_high_and_a_low_earner_stay_apart(self):
        """The re-roll compressed the spread; anchoring must preserve it."""
        low = _salary(_agent(2275.0))
        high = _salary(_agent(27137.0))
        self.assertGreater(high / low, 8.0)

    def test_no_stated_income_falls_back_to_the_job_band(self):
        salary = _salary(_agent(None))
        self.assertGreater(salary, 0.0)

    def test_the_switch_restores_the_old_behaviour(self):
        stated = 9117.0
        anchored = _salary(_agent(stated))
        rerolled = _salary(_agent(stated), use_profile_income=False)
        self.assertNotAlmostEqual(anchored, rerolled, delta=1.0)
        self.assertAlmostEqual(rerolled, _salary(_agent(None)), delta=1.0)

    def test_the_minimum_wage_floor_still_applies(self):
        """A tiny stated income must not put the hourly rate below the floor."""
        cfg = dict(finance.DEFAULT_ECONOMY_CONFIG)
        floor = float(cfg["min_hourly_income"]) * float(cfg["work_hours_per_day"]) * float(cfg["work_days_per_month"])
        self.assertGreaterEqual(_salary(_agent(50.0)), floor - 1.0)


if __name__ == "__main__":
    unittest.main()
