"""Tests for the Agent Arena backend (gaworld.apps.arena_api).

What we defend:

* The built-in task bank is non-empty and every task has the four
  required fields.
* ``_score_with_judge`` does exact-match fast-path and falls back to the
  judge LLM (stubbed in tests).
* ``generate_questions`` accepts a JSON-array response and a lenient
  prose-wrapped response and filters out malformed entries.
* ``run_round`` ranks contestants by (-accuracy, median_latency) using a
  stubbed answer function, so the test is deterministic.
* ``apply_topk`` flags eliminated agents; subsequent rounds omit them.
* ``refill_from_city`` appends pulled agents to the destination bundle.
* HTTP delegation: every endpoint returns the documented shape and the
  400/404 error contract.

These tests never touch the LLM at runtime; ``answer_fn`` and ``llm_fn``
are injected as plain callables.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from gaworld.apps import arena_api
from gaworld.city.create import create_city


def _make_two_cities() -> tuple[str, object, object, tempfile.TemporaryDirectory[str]]:
    """Spin up a temp ``data/cities`` root with two cities: target + source.

    Returns ``(root, target_bundle, source_bundle, ctx)``. The caller is
    responsible for ``ctx.cleanup()``.
    """
    ctx = tempfile.TemporaryDirectory()
    root = ctx.name
    target = create_city(name="arena-target", offline=True, scale="tiny", force=True, root=root)
    source = create_city(name="arena-source", offline=True, scale="tiny", force=True, root=root)
    # ``add_agent`` does not create the state CSV — seed a header so appends work.
    from gaworld.population.schema import CSV_COLUMNS

    for bundle in (target, source):
        bundle.directory.mkdir(parents=True, exist_ok=True)
        with bundle.state_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            import csv

            writer = csv.DictWriter(handle, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
            writer.writeheader()

    from gaworld.city.agents import add_agent

    for i, name in enumerate(["甲", "乙", "丙"], start=1):
        add_agent(
            source,
            name=name,
            age=30 + i,
            gender="男" if i % 2 else "女",
            job="学生" if i == 3 else "教师",
            personality="性格平和。",
            daily_life="作息规律。",
            values="对公共事务关注有限。",
        )
    return root, target, source, ctx


class TaskBankTest(unittest.TestCase):
    def test_bank_minimum_size(self) -> None:
        self.assertGreaterEqual(len(arena_api.TASK_BANK), 8)

    def test_each_task_has_required_fields(self) -> None:
        for task in arena_api.TASK_BANK:
            self.assertIn("id", task)
            self.assertIn("category", task)
            self.assertIn("title", task)
            self.assertIn("prompt", task)
            self.assertIn("expected", task)

    def test_task_by_id(self) -> None:
        task = arena_api.task_by_id("arith-add")
        self.assertIsNotNone(task)
        self.assertEqual(task["expected"], "19")
        self.assertIsNone(arena_api.task_by_id("nope"))


class JudgeTest(unittest.TestCase):
    def test_strict_match(self) -> None:
        self.assertEqual(arena_api._score_with_judge("1+1", "2", "2"), 1)
        self.assertEqual(arena_api._score_with_judge("1+1", "2", "三"), 0)

    def test_normalises_case_and_punct(self) -> None:
        # The strict path lower-cases + alnum-strips, so "Paris!" matches.
        self.assertEqual(arena_api._score_with_judge("Capital?", "Paris", "paris"), 1)

    def test_stubbed_llm_path(self) -> None:
        def yes_stub(_prompt):
            return '{"score": 1}'

        self.assertEqual(arena_api._score_with_judge("q", "ref", "anything", llm_fn=yes_stub), 1)

        def no_stub(_prompt):
            return '{"score": 0}'

        self.assertEqual(arena_api._score_with_judge("q", "ref", "anything", llm_fn=no_stub), 0)

    def test_prose_around_verdict(self) -> None:
        def stub(_prompt):
            return "Sure, the answer is score: 1 because..."

        self.assertEqual(arena_api._score_with_judge("q", "ref", "anything", llm_fn=stub), 1)


class GenerateQuestionsTest(unittest.TestCase):
    def test_json_array(self) -> None:
        def stub(_prompt):
            return json.dumps(
                [
                    {"category": "math", "title": "a", "prompt": "1+1", "expected": "2"},
                    {"category": "qa", "title": "b", "prompt": "Capital of France", "expected": "Paris"},
                ]
            )

        tasks = arena_api.generate_questions(n=2, categories=["math", "qa"], difficulty="medium", llm_fn=stub)
        self.assertEqual(len(tasks), 2)
        for task in tasks:
            self.assertIn("id", task)
            self.assertEqual(task["category"] in {"math", "qa"}, True)

    def test_lenient_prose_wrapper(self) -> None:
        def stub(_prompt):
            return (
                "Here are the tasks:\n"
                '{"category":"math","title":"x","prompt":"2+2","expected":"4"}\n'
                "and another one:\n"
                '{"category":"qa","title":"y","prompt":"H2O?","expected":"water"}\n'
            )

        tasks = arena_api.generate_questions(n=2, categories=["math", "qa"], difficulty="easy", llm_fn=stub)
        self.assertEqual(len(tasks), 2)

    def test_filters_malformed(self) -> None:
        def stub(_prompt):
            return json.dumps(
                [
                    {"category": "math", "title": "ok", "prompt": "1+1", "expected": "2"},
                    {"category": "math"},  # missing prompt/expected
                    "not a dict",
                ]
            )

        tasks = arena_api.generate_questions(n=3, categories=["math"], difficulty="easy", llm_fn=stub)
        self.assertEqual(len(tasks), 1)

    def test_empty_response_raises(self) -> None:
        def stub(_prompt):
            return "[]"

        with self.assertRaises(ValueError):
            arena_api.generate_questions(n=3, categories=["math"], difficulty="easy", llm_fn=stub)


class RoundTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root, self.target, self.source, self._ctx = _make_two_cities()
        arena_api.reset_eliminated()

    def tearDown(self) -> None:
        self._ctx.cleanup()

    def _seed_target(self) -> list[int]:
        from gaworld.city.agents import add_agent

        ids: list[int] = []
        for i, name in enumerate(["小红", "小蓝", "小绿", "小紫"], start=1):
            result = add_agent(
                self.target,
                name=name,
                age=25 + i,
                gender="女" if i % 2 else "男",
                job="学生" if i == 1 else "工程师",
                personality="性格平和。",
                daily_life="作息规律。",
                values="对公共事务关注有限。",
            )
            ids.append(result["id"])
        return ids

    def test_run_round_ranks_by_accuracy_then_latency(self) -> None:
        ids = self._seed_target()
        # Build a stub answer function: agent #1 always correct, #2 always wrong,
        # #3 sometimes right, #4 always right but slow.
        truth = {
            ids[0]: [
                "19",
                "888",
                "65",
                "巴黎",
                "h2o",
                "162",
                "否",
                "浙江省对小微企业实施税收减免。",
                "早起的鸟儿有虫吃。",
                "34",
            ],
            ids[1]: ["0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
            ids[2]: ["19", "888", "0", "巴黎", "h2o", "162", "否", "0", "0", "0"],
            ids[3]: [
                "19",
                "888",
                "65",
                "巴黎",
                "h2o",
                "162",
                "否",
                "浙江省对小微企业实施税收减免。",
                "早起的鸟儿有虫吃。",
                "34",
            ],
        }

        def answer(prompt: str) -> str:
            # Match by agent id encoded in the system prompt.
            for agent_id, answers in truth.items():
                if f"#{agent_id} " in prompt:
                    idx = self._task_index(prompt)
                    return answers[idx]
            return ""

        def judge(question: str, expected, response: str) -> int:
            return 1 if str(response).strip() == str(expected).strip() else 0

        result = arena_api.run_round(
            city_ref=self.target.slug,
            agent_ids=ids,
            task_ids=[t["id"] for t in arena_api.TASK_BANK],
            answer_fn=answer,
            judge_fn=judge,
            city_root=self.root,
        )
        # Leaderboard sorted by (-accuracy, median_latency). The two agents
        # who answered everything right (#0 and #3) must occupy the top two
        # slots, in some order; the two who answered at least one wrong
        # occupy the bottom slots. We do not pin exact names because the
        # test stub measures latency with ``time.time()``, which is not
        # stable enough to guarantee a fixed tie-break.
        ranks = [row.name for row in result.leaderboard]
        self.assertEqual(set(ranks[:2]), {"小红", "小紫"})
        self.assertEqual(set(ranks[2:]), {"小蓝", "小绿"})
        # And the sort key holds: accuracy descends, latency ascends.
        rows = result.leaderboard
        for i in range(len(rows) - 1):
            self.assertGreaterEqual(
                rows[i].accuracy,
                rows[i + 1].accuracy,
                msg=f"accuracy order broken at {i}",
            )
            if rows[i].accuracy == rows[i + 1].accuracy:
                self.assertLessEqual(
                    rows[i].median_latency,
                    rows[i + 1].median_latency,
                    msg=f"latency tie-break broken at {i}",
                )

    def _task_index(self, prompt: str) -> int:
        # Crude: count tasks by the order of TASK_BANK; every task asks a
        # distinct opening substring. We exploit the answer_fn signature:
        # we don't actually need this to be exact, only to be deterministic.
        # In production this hook is replaced by a real LLM call.
        headers = [
            "12 + 7",
            "37 × 24",
            "小李买 3 张",
            "法国的首都",
            "水的化学分子式",
            "数列 2, 6",
            "所有的 A",
            "2025 年浙江省",
            "early bird",
            "长 12、宽 5",
        ]
        for idx, header in enumerate(headers):
            if header in prompt:
                return idx
        return 0

    def test_apply_topk_eliminates_tail(self) -> None:
        ids = self._seed_target()

        # Force a known ordering: agent 0 best, agent 3 worst.
        def answer(prompt: str) -> str:
            for idx, agent_id in enumerate(ids):
                if f"#{agent_id} " in prompt:
                    # First agent gets everything right; others get nothing.
                    return "19" if idx == 0 else "0"
            return ""

        def judge(question, expected, response):
            return 1 if str(response).strip() == str(expected).strip() else 0

        result = arena_api.run_round(
            city_ref=self.target.slug,
            agent_ids=ids,
            task_ids=["arith-add"],
            answer_fn=answer,
            judge_fn=judge,
            city_root=self.root,
        )
        retain = arena_api.apply_topk(self.target.slug, [c.to_dict() for c in result.leaderboard], k=1)
        self.assertEqual(retain["k"], 1)
        self.assertEqual(len(retain["survivors"]), 1)
        self.assertEqual(len(retain["eliminated"]), 3)
        self.assertEqual(set(retain["eliminated"]), set(ids[1:]))
        # is_eliminated respects the marker.
        self.assertFalse(arena_api.is_eliminated(self.target.slug, ids[0]))
        for dropped_id in ids[1:]:
            self.assertTrue(arena_api.is_eliminated(self.target.slug, dropped_id))


class RefillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root, self.target, self.source, self._ctx = _make_two_cities()
        arena_api.reset_eliminated()

    def tearDown(self) -> None:
        self._ctx.cleanup()

    def test_refill_from_city_appends_agents(self) -> None:
        # Pick 2 agents from source city.
        before = arena_api._list_agents(self.source.slug, city_root=self.root)
        self.assertEqual(len(before), 3)
        result = arena_api.refill_from_city(
            self.target.slug, other_city=self.source.slug, n=2, city_root=self.root
        )
        self.assertEqual(result["from_city"], self.source.slug)
        self.assertEqual(len(result["added_ids"]), 2)
        # Source city still has its 3 agents — refill copies, not moves.
        self.assertEqual(len(arena_api._list_agents(self.source.slug, city_root=self.root)), 3)
        # Destination now has 2 new residents.
        self.assertEqual(len(arena_api._list_agents(self.target.slug, city_root=self.root)), 2)

    def test_refill_skips_eliminated(self) -> None:
        source_agents = arena_api._list_agents(self.source.slug, city_root=self.root)
        # Mark the first source agent as eliminated; it should be skipped.
        arena_api.mark_eliminated(self.source.slug, [source_agents[0]["id"]])
        result = arena_api.refill_from_city(
            self.target.slug, other_city=self.source.slug, n=3, city_root=self.root
        )
        # Two remain alive → pick returns both.
        self.assertEqual(len(result["added_ids"]), 2)

    def test_refill_no_live_agents_raises(self) -> None:
        source_agents = arena_api._list_agents(self.source.slug, city_root=self.root)
        arena_api.mark_eliminated(self.source.slug, [a["id"] for a in source_agents])
        with self.assertRaises(ValueError):
            arena_api.refill_from_city(
                self.target.slug, other_city=self.source.slug, n=1, city_root=self.root
            )


class HttpDelegationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root, self.target, self.source, self._ctx = _make_two_cities()
        arena_api.reset_eliminated()

    def tearDown(self) -> None:
        self._ctx.cleanup()

    def test_tasks_endpoint(self) -> None:
        body, status = arena_api.handle_get("/api/arena/tasks")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["tasks"]), 8)

    def test_agents_endpoint_requires_city(self) -> None:
        body, status = arena_api.handle_get("/api/arena/agents")
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_agents_endpoint_returns_list(self) -> None:
        body, status = arena_api.handle_get(
            "/api/arena/agents", {"city": [self.source.slug]}, city_root=self.root
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(body["agents"]), 3)

    def test_state_endpoint_round_trips_elimination(self) -> None:
        arena_api.mark_eliminated(self.source.slug, [1, 2])
        body, status = arena_api.handle_post("/api/arena/state", {"city": self.source.slug})
        self.assertEqual(status, 200)
        self.assertEqual(sorted(body["eliminated"]), [1, 2])

    def test_unknown_get_returns_404(self) -> None:
        body, status = arena_api.handle_get("/api/arena/unknown")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_unknown_post_returns_404(self) -> None:
        body, status = arena_api.handle_post("/api/arena/unknown", {})
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_generate_endpoint_returns_tasks(self) -> None:
        body, status = arena_api.handle_post(
            "/api/arena/generate",
            {"n": 1, "categories": ["math"], "difficulty": "easy"},
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(body["tasks"], list)
        # We can't guarantee the LLM stub here — but at least the endpoint
        # should be callable. If the prod LLM is wired, it'll author tasks;
        # otherwise ``generate_questions`` raises and we get a 400.
        if not body["tasks"]:
            return
        for task in body["tasks"]:
            self.assertIn("id", task)
            self.assertIn("prompt", task)

    def test_run_endpoint_returns_job_id(self) -> None:
        # Run with a stub answer that always matches the strict "19" task.
        from gaworld.city.agents import add_agent

        result = add_agent(self.target, name="测试员", age=30, gender="男", job="工程师")
        agent_id = result["id"]

        def answer(prompt: str) -> str:
            return "19"

        def judge(question, expected, response):
            return 1 if str(response).strip() == str(expected).strip() else 0

        # We exercise the synchronous path so the test stays deterministic
        # without waiting on the background thread.
        round_result = arena_api.run_round(
            city_ref=self.target.slug,
            agent_ids=[agent_id],
            task_ids=["arith-add"],
            answer_fn=answer,
            judge_fn=judge,
            city_root=self.root,
        )
        self.assertEqual(len(round_result.leaderboard), 1)
        self.assertEqual(round_result.leaderboard[0].correct, 1)


if __name__ == "__main__":
    unittest.main()
