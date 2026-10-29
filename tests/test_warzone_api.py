"""Tests for 《这是我的战争》 (gaworld.apps.warzone_api).

What we defend:

* ``run_warzone`` runs the day-by-day loop: proposals, votes, settlement,
  and end-of-day hunger/health decay, with the day count clamped to the
  scenario's actual day list.
* The proposal/vote prompts carry the persona, the day text, the live
  stockpile, the yesterday-winning plan, and the cohort's status — and
  each resident's own vote anchors to their own proposal index, so a bare
  ``yes`` from the model counts.
* ``parse_proposal`` and ``parse_vote`` survive off-shape answers: clean
  JSON, JSON wrapped in prose, garbage, off-vocabulary resources, missing
  ``for`` — none of it kills the round.
* The aggregate (mortality / dissent rate / Gini of food / depleted-first /
  strongest proposer) is computed from the day log itself, no model call.
* ``resolve_scenario`` accepts the bank and a custom script, and rejects
  unknown ids; ``start_run`` refuses an empty roster.
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/warzone/`` branch in ``games_api``.

No LLM is reached: ``proposal_fn`` / ``vote_fn`` / ``essay_fn`` are injected
and residents are handed in directly.
"""

from __future__ import annotations

import unittest
from collections.abc import Iterator
from unittest import mock

from gaworld.apps import games_api, warzone_api


def _people(n: int = 3) -> list[warzone_api.Resident]:
    return [
        warzone_api.Resident(
            agent_id=i,
            name=f"居民{i}",
            job="教师",
            persona_text=f"你是居民{i},40岁,女。职业:教师。",
        )
        for i in range(1, n + 1)
    ]


def _scripted(*items: str) -> Iterator[str]:
    """``answer_fn`` that yields the scripted replies in order and then sticks.

    The fixture stores its calls list on ``.calls`` so prompts can be
    asserted the same way as ``test_disaster_api`` does it.
    """
    items = list(items)
    iterator = iter(items)

    def fn(prompt: str) -> str:
        try:
            value = next(iterator)
        except StopIteration:
            return items[-1]
        fn.calls.append(prompt)  # type: ignore[attr-defined]
        return value

    fn.calls = []  # type: ignore[attr-defined]
    return fn


def _proposal(author_id: int, plan: list[tuple[str, str, int]], rationale: str = "") -> str:
    rows = ",".join(f'{{"resource": "{r}", "recipient_id": "{rid}", "amount": {a}}}' for r, rid, a in plan)
    return f'{{"rationale": "{rationale or "我给病的孩子。"}", "plan": [{rows}]}}'


def _vote(choice: str, for_: int = 0, reason: str = "好.") -> str:
    target = f', "for": {for_}' if for_ else ""
    return f'{{"choice": "{choice}"{target}, "reason": "{reason}"}}'


class RunTest(unittest.TestCase):
    def test_full_seven_day_round_plays_each_day(self) -> None:
        # 3 voters × 7 days = 21 proposal slots + 21 vote slots (no deaths here).
        # Each voter proposes "feed #1 one food unit"; every voter votes yes
        # backing the first proposal. Stock decreases monotonically (or at
        # least never goes negative).
        proposal_call_count = 0

        def proposal_fn(_prompt: str) -> str:
            nonlocal proposal_call_count
            proposal_call_count += 1
            return _proposal(1, [("食物", "#1", 1)])

        def vote_fn(_prompt: str) -> str:
            return _vote("yes", for_=1)

        run = warzone_api.run_warzone(
            city="wuzhen",
            agent_ids=[],
            scenario_id="siege",
            days=7,
            residents=_people(3),
            proposal_fn=proposal_fn,
            vote_fn=vote_fn,
            essay_fn=lambda p: "战士们走了。",
        )
        self.assertEqual(len(run["days"]), 7)
        self.assertEqual(len(run["log"]), 7)
        self.assertEqual(proposal_call_count, 21)
        self.assertEqual(run["essay"], "战士们走了。")
        self.assertEqual(run["scenario"]["name"], "围城战")
        # Stock should never go negative (the runner refuses overdraw silently)
        for day in run["log"]:
            for resource, amount in day["stock_after"].items():
                self.assertGreaterEqual(amount, 0, f"{resource} should not be < 0")

    def test_day_count_is_clamped(self) -> None:
        full = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="urban",
            days=99,
            residents=_people(2),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 1)]),
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        self.assertEqual(len(full["log"]), warzone_api.DEFAULT_DAYS)

        short = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            custom={"name": "二天剧本", "days": "第一天。\n第二天。"},
            days=4,
            residents=_people(1),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 1)]),
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        self.assertEqual(len(short["log"]), 2)
        self.assertEqual(short["scenario"]["name"], "二天剧本")

    def test_proposal_prompt_has_persona_stock_and_yesterday_winner(self) -> None:
        proposal_calls: list[str] = []

        def proposal_fn(prompt: str) -> str:
            proposal_calls.append(prompt)
            return _proposal(1, [("食物", "#1", 1)])

        warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="village",
            days=2,
            residents=_people(2),
            proposal_fn=proposal_fn,
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        self.assertGreaterEqual(len(proposal_calls), 3)
        first = proposal_calls[0]
        self.assertIn("你是居民1", first)
        self.assertIn("公共仓库剩", first)
        # Day 2 proposal calls should reference yesterday's winning plan
        self.assertIn("昨天", proposal_calls[len(proposal_calls) // 2])

    def test_vote_prompt_lists_each_proposal_in_compact_form(self) -> None:
        vote_calls: list[str] = []

        def proposal_fn(_prompt: str) -> str:
            return _proposal(1, [("食物", "#1", 1)])

        def vote_fn(prompt: str) -> str:
            vote_calls.append(prompt)
            return _vote("yes", for_=1)

        warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="exodus",
            days=1,
            residents=_people(3),
            proposal_fn=proposal_fn,
            vote_fn=vote_fn,
            essay_fn=lambda p: "",
        )
        self.assertEqual(len(vote_calls), 3)
        for prompt in vote_calls:
            self.assertIn("方案1", prompt)
            self.assertIn("方案2", prompt)
            self.assertIn("方案3", prompt)

    def test_a_bare_yes_counts_as_self_approval(self) -> None:
        # voter 1 has proposal index 0 (theirs); voter 2 has proposal index 1.
        # voter 1 votes "yes" without "for"; the runner must count it for
        # their own proposal (index 0). voter 2 backs proposal 1 (theirs).
        votes = [
            _vote("yes"),  # voter 1 — bare yes → counts for #0
            _vote("yes", for_=1),  # voter 2 — backs proposal 2 = index 1
        ]
        idx = {"i": 0}

        def vote_fn(_prompt: str) -> str:
            value = votes[idx["i"]]
            idx["i"] += 1
            return value

        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=1,
            residents=_people(2),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 1)]),
            vote_fn=vote_fn,
            essay_fn=lambda p: "",
        )
        day = run["log"][0]
        # voter 1 → tally[0] += 1 (bare yes → own proposal at index 0).
        # voter 2 → tally[1] += 1 (for=1 in vote means 1-based proposal index → tally[0]).
        # Wait: vote["for"]: 1 means 1-based proposal index 1 → 0-based tally[0].
        # So both land on tally[0].
        self.assertEqual(day["tally"][0], 2)
        self.assertEqual(day["tally"][1], 0)
        self.assertEqual(day["winning_proposal"]["author_id"], 1)

    def test_a_garbage_proposal_degrades_one_row_without_killing_the_round(self) -> None:
        proposal = _scripted(
            "完全不是 JSON",
            _proposal(2, [("食物", "#2", 1)]),
        )

        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=1,
            residents=_people(2),
            proposal_fn=proposal,
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        proposals_list = run["log"][0]["proposals"]
        self.assertEqual(proposals_list[0]["plan"], [])
        self.assertEqual(proposals_list[1]["plan"], [{"resource": "食物", "recipient_id": "#2", "amount": 1}])

    def test_essay_failure_does_not_fail_the_round(self) -> None:
        def boom(_prompt: str) -> str:
            raise RuntimeError("provider down")

        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="urban",
            days=1,
            residents=_people(1),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 1)]),
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=boom,
        )
        self.assertEqual(run["essay"], "")
        self.assertEqual(len(run["log"]), 1)

    def test_no_agents_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            warzone_api.run_warzone(city="", agent_ids=[], scenario_id="siege")

    def test_stock_before_and_stock_after_capture_pre_and_post_settlement(self) -> None:
        # Three residents, 3-day siege. Each proposes "give #1 one food";
        # everyone votes yes for plan 1. Food should decrease by 1 per day.
        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=3,
            residents=_people(3),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 1)]),
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        initial_food = run["scenario"]["stock_initial"]["食物"]
        self.assertGreater(initial_food, 0)
        # Day 1: stock_before is the initial stockpile.
        self.assertEqual(run["log"][0]["stock_before"]["食物"], initial_food)
        # Day 1: stock_after is initial minus the day's distribution.
        self.assertEqual(run["log"][0]["stock_after"]["食物"], initial_food - 1)
        # Day 2: stock_before is Day 1's stock_after (continuity).
        self.assertEqual(
            run["log"][1]["stock_before"]["食物"],
            run["log"][0]["stock_after"]["食物"],
        )

    def test_daily_cap_prevents_one_day_draining(self) -> None:
        # The whole point of the cap: a wildly generous proposal must not
        # be allowed to wipe the stockpile in a single day. With siege
        # initial food = 120 and 4 days, the per-day cap on Day 1 is
        # 120 // 3 = 40 — even if every resident proposes 9999 food,
        # Day 1 consumes at most 40 units, so Days 2 and 3 still have
        # real amounts to argue over.
        def generous(_p: str) -> str:
            return '{"rationale":"全给","plan":[{"resource":"食物","recipient_id":"#1","amount":9999}]}'

        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=4,
            residents=_people(4),
            proposal_fn=generous,
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        day1_consumed = run["log"][0]["stock_before"]["食物"] - run["log"][0]["stock_after"]["食物"]
        # Day 1 cap = floor(120 / 3) = 40.
        self.assertEqual(day1_consumed, 40)
        # Days 2 and 3 must still have something — the cap leaves at
        # least one day's worth of room for Day 4.
        self.assertGreater(run["log"][1]["stock_before"]["食物"], 0)
        self.assertGreater(run["log"][2]["stock_before"]["食物"], 0)

    def test_proposal_prompt_announces_the_daily_cap(self) -> None:
        prompt_calls: list[str] = []

        def proposal_fn(prompt: str) -> str:
            prompt_calls.append(prompt)
            return _proposal(1, [("食物", "#1", 1)])

        warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=3,
            residents=_people(2),
            proposal_fn=proposal_fn,
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        first = prompt_calls[0]
        self.assertIn("今天各种资源的支出上限", first)
        # Cap = floor(120 / 2) = 60 (days_left - 1 = 3 - 1 = 2).
        self.assertIn("≤60", first)


class StatsTest(unittest.TestCase):
    def test_aggregate_includes_yes_no_and_abstain(self) -> None:
        # 3 voters; voter 1 votes yes+for=1, voter 2 votes no, voter 3 votes yes+for=1
        votes = [
            _vote("yes", for_=1),
            _vote("no"),
            _vote("yes", for_=1),
        ]
        idx = {"i": 0}

        def vote_fn(_prompt: str) -> str:
            value = votes[idx["i"]]
            idx["i"] += 1
            return value

        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=1,
            residents=_people(3),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 1)]),
            vote_fn=vote_fn,
            essay_fn=lambda p: "",
        )
        agg = run["log"][0]["aggregate"]
        self.assertEqual(agg["yes"], 2)
        self.assertEqual(agg["no"], 1)
        self.assertEqual(agg["abstain"], 0)
        self.assertGreaterEqual(agg["dissent_rate"], 0.0)

    def test_overall_stats_cover_the_run(self) -> None:
        # Three participants; every voter backs proposal 0; everything goes
        # to #1, so food_gini is high but mortality stays 0 (stock > deaths).
        run = warzone_api.run_warzone(
            city="",
            agent_ids=[],
            scenario_id="siege",
            days=1,
            residents=_people(3),
            proposal_fn=lambda _p: _proposal(1, [("食物", "#1", 5)]),
            vote_fn=lambda _p: _vote("yes", for_=1),
            essay_fn=lambda p: "",
        )
        stats = run["stats"]
        for key in (
            "mortality",
            "dissent_rate",
            "food_gini",
            "avg_moral_distress",
            "depleted_first",
            "strongest_id",
            "most_excluded_id",
        ):
            self.assertIn(key, stats)


class ParseTest(unittest.TestCase):
    def test_proposal_clean_json(self) -> None:
        got = warzone_api.parse_proposal(_proposal(1, [("食物", "#1", 2), ("药品", "#2", 1)], "先给病人"))
        self.assertEqual(got["rationale"], "先给病人")
        self.assertEqual(len(got["plan"]), 2)
        self.assertEqual(got["plan"][0]["resource"], "食物")

    def test_proposal_off_resource_is_dropped(self) -> None:
        raw = '{"rationale": "什么都有", "plan": [{"resource": "时光机", "recipient_id": "#1", "amount": 1}, {"resource": "食物", "recipient_id": "#1", "amount": 2}]}'
        got = warzone_api.parse_proposal(raw)
        self.assertEqual(len(got["plan"]), 1)
        self.assertEqual(got["plan"][0]["resource"], "食物")

    def test_proposal_off_amount_is_dropped(self) -> None:
        raw = '{"plan": [{"resource": "食物", "recipient_id": "#1", "amount": 0}, {"resource": "食物", "recipient_id": "#2", "amount": 3}]}'
        got = warzone_api.parse_proposal(raw)
        self.assertEqual(len(got["plan"]), 1)

    def test_proposal_wrapped_in_prose(self) -> None:
        got = warzone_api.parse_proposal(
            '好的。\n{"plan": [{"resource": "药品", "recipient_id": "#2", "amount": 1}]}\n就这样'
        )
        self.assertEqual(len(got["plan"]), 1)

    def test_garbage_proposal_yields_empty_plan_with_fallback(self) -> None:
        got = warzone_api.parse_proposal("完全不是 JSON")
        self.assertEqual(got["plan"], [])
        self.assertTrue(got["rationale"])

    def test_vote_clean(self) -> None:
        got = warzone_api.parse_vote(_vote("yes", for_=2, reason="好."))
        self.assertEqual(got["choice"], "yes")
        self.assertEqual(got["for"], 2)
        self.assertEqual(got["reason"], "好.")

    def test_vote_abstain_from_garbage(self) -> None:
        got = warzone_api.parse_vote("模型忘记格式")
        self.assertEqual(got["choice"], "abstain")
        self.assertIsNone(got["for"])

    def test_vote_negative_index_normalised(self) -> None:
        got = warzone_api.parse_vote('{"choice": "yes", "for": -1}')
        self.assertIsNone(got["for"])


class CatalogueTest(unittest.TestCase):
    def test_bank_entries_are_seven_days_long(self) -> None:
        for scenario in warzone_api.list_scenarios():
            self.assertTrue(scenario["name"])
            self.assertEqual(len(scenario["days"]), warzone_api.DEFAULT_DAYS)
            self.assertEqual(set(scenario["stock"]), set(warzone_api.RESOURCES))

    def test_custom_splits_text_into_days(self) -> None:
        got = warzone_api.resolve_scenario("", {"name": "矿井坍塌", "days": "第一天\n\n第二天"})
        self.assertEqual(got["name"], "矿井坍塌")
        self.assertEqual(got["days"], ["第一天", "第二天"])

    def test_empty_custom_and_unknown_id_are_value_errors(self) -> None:
        with self.assertRaises(ValueError):
            warzone_api.resolve_scenario("", {"name": "x", "days": "   "})
        with self.assertRaises(ValueError):
            warzone_api.resolve_scenario("phantom")

    def test_custom_stock_with_zero_values_falls_back(self) -> None:
        got = warzone_api.resolve_scenario(
            "",
            {"name": "化工厂", "days": "第一天", "stock": {"食物": 0, "药品": 0, "燃料": 0, "守卫时间": 0}},
        )
        self.assertTrue(any(got["stock"].values()))


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        warzone_api.reset_jobs()

    def test_catalogue_endpoint(self) -> None:
        body, status = warzone_api.handle_get("/api/games/warzone/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["scenarios"]), len(warzone_api.WARZONE_BANK))
        self.assertEqual(body["max_agents"], warzone_api.MAX_AGENTS)
        self.assertIn("食物", body["resources"])

    def test_runs_endpoint_starts_empty(self) -> None:
        body, status = warzone_api.handle_get("/api/games/warzone/runs")
        self.assertEqual(status, 200)
        self.assertEqual(body["runs"], [])

    def test_run_without_agents_is_400(self) -> None:
        body, status = warzone_api.handle_post(
            "/api/games/warzone/run", {"city": "wuzhen", "scenario_id": "siege"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_with_unknown_scenario_is_400(self) -> None:
        body, status = warzone_api.handle_post(
            "/api/games/warzone/run", {"agent_ids": [1], "scenario_id": "phantom"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_opens_a_job_and_finishes(self) -> None:
        fake = {
            "run_id": "abc",
            "created_at": 1.0,
            "residents": [],
            "days": [],
            "log": [],
            "stats": {},
            "scenario": {"name": "X", "emoji": "🏰"},
            "essay": "",
        }
        with mock.patch("gaworld.apps.warzone_api.run_warzone", return_value=fake):
            body, status = warzone_api.handle_post(
                "/api/games/warzone/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "scenario_id": "siege"},
            )
            self.assertEqual(status, 202)
            job_id = body["job_id"]
            import time

            for _ in range(200):
                record = warzone_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)
        record, status = warzone_api.handle_get(f"/api/games/warzone/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["run_id"], "abc")

    def test_unknown_job_is_404(self) -> None:
        self.assertEqual(warzone_api.handle_get("/api/games/warzone/jobs/nope")[1], 404)

    def test_unknown_endpoints_are_404(self) -> None:
        self.assertEqual(warzone_api.handle_get("/api/games/warzone/nope")[1], 404)
        self.assertEqual(warzone_api.handle_post("/api/games/warzone/nope", {})[1], 404)

    def test_games_api_forwards_the_warzone_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/warzone/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("scenarios", body)

        body, status = games_api.handle_post("/api/games/warzone/run", {})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
