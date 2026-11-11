"""What the seed of a replication run actually controls.

A researcher pins a seed, runs the same study twice, and gets 91.9, 92.0 and
93.3. The seed was not broken: it controls **which residents answer and how
their answers are grouped**, and it has always done so reproducibly. What it
never controlled was the model's own sampling — every answer was an
independent draw at temperature 0.9 — and on a hosted endpoint that draw is
not reproducible by construction.

So the seed's scope has to be stated, not assumed:

* the same seed picks the same residents and the same condition assignment;
* the same seed derives the same per-cell seed for every model call;
* a provider that accepts a seed is asked for the same draw again;
* the run records what the seed covered, so a reader knows which parts of the
  result the seed can speak for.

These tests pin that contract.
"""

from __future__ import annotations

import unittest
from unittest import mock

from gaworld.apps import replication_api
from gaworld.llm import providers
from gaworld.research import replication as rp

PEOPLE = [
    {
        "id": i,
        "name": f"居民{i}",
        "age": 25 + i,
        "gender": "女" if i % 2 else "男",
        "hukou": "本地",
        "job": "职员",
    }
    for i in range(1, 13)
]

SPEC = {
    "title": "框架效应",
    "kind": "experiment",
    "conditions": [
        {"id": "C1", "label": "收益框架", "stimulus": "可以救 200 人"},
        {"id": "C2", "label": "损失框架", "stimulus": "会死 400 人"},
    ],
    "items": [{"id": "Q1", "text": "你支持方案 A 吗", "kind": "scale", "min": 1, "max": 7}],
    "results": [{"item": "Q1", "condition": "C1", "mean": 5.0, "sd": 1.0, "n": 50, "source": "表1"}],
}


class SeedScopeTest(unittest.TestCase):
    def _run(self, seed: int, **overrides: object) -> dict:
        seen: list[dict] = []

        def answer(prompt: str, **kwargs: object) -> str:
            seen.append(kwargs)
            return '{"Q1": 5}'

        kwargs: dict = {
            "spec": SPEC,
            "sample_size": 6,
            "seed": seed,
            "answer": answer,
            "population": PEOPLE,
            "profile_fn": lambda city, agent_id: "",
            "workers": 1,
        }
        kwargs.update(overrides)
        run = rp.run_replication(**kwargs)
        run["_seen"] = seen
        return run

    def test_the_same_seed_picks_the_same_residents(self) -> None:
        first = self._run(146)
        second = self._run(146)
        self.assertEqual(
            [r["agent_id"] for r in first["residents"]], [r["agent_id"] for r in second["residents"]]
        )

    def test_the_same_seed_assigns_the_same_conditions(self) -> None:
        first = self._run(146)
        second = self._run(146)
        self.assertEqual(
            [(r["agent_id"], r["condition"]) for r in first["responses"]],
            [(r["agent_id"], r["condition"]) for r in second["responses"]],
        )

    def test_a_different_seed_picks_a_different_sample(self) -> None:
        first = self._run(146)
        second = self._run(999)
        self.assertNotEqual(
            [r["agent_id"] for r in first["residents"]], [r["agent_id"] for r in second["residents"]]
        )

    def test_every_model_call_carries_a_cell_seed(self) -> None:
        run = self._run(146)
        self.assertTrue(run["_seen"])
        for kwargs in run["_seen"]:
            self.assertIn("seed", kwargs)
            self.assertIsInstance(kwargs["seed"], int)

    def test_the_cell_seed_is_the_same_across_runs_with_the_same_seed(self) -> None:
        first = self._run(146)
        second = self._run(146)
        self.assertEqual(
            [kwargs["seed"] for kwargs in first["_seen"]],
            [kwargs["seed"] for kwargs in second["_seen"]],
        )

    def test_the_cell_seed_differs_between_residents(self) -> None:
        run = self._run(146)
        seeds = [kwargs["seed"] for kwargs in run["_seen"]]
        self.assertEqual(len(seeds), len(set(seeds)), "每个格子要有自己的种子")

    def test_the_run_records_what_the_seed_controls(self) -> None:
        run = self._run(146)
        scope = run["seed_scope"]
        self.assertIn("sampling", scope["controls"])
        self.assertIn("assignment", scope["controls"])
        # The seed is not a claim that the model's answers repeat.
        self.assertIn("answers", scope["does_not_control"])
        self.assertTrue(scope["model_sampling_reproducible"] is False or scope["provider_supports_seed"])

    def test_a_provider_that_takes_only_a_prompt_still_works(self) -> None:
        """An injected answer callable with the old one-argument signature must
        not break: the seed is an extra, not a requirement."""

        def answer(prompt: str) -> str:
            return '{"Q1": 5}'

        run = rp.run_replication(
            spec=SPEC,
            sample_size=6,
            seed=146,
            answer=answer,
            population=PEOPLE,
            profile_fn=lambda city, agent_id: "",
            workers=1,
        )
        self.assertEqual(len(run["responses"]), 6)

    def test_the_seed_scope_reaches_the_check_protocol(self) -> None:
        run = self._run(146)
        self.assertIn("seed_scope", run["check_protocol"])

    def test_the_export_says_what_the_seed_covered(self) -> None:
        run = self._run(146)
        markdown = rp.export_markdown(run)
        self.assertIn("种子范围", markdown)
        self.assertIn("接口不接受 seed", markdown)

    def test_the_export_says_the_provider_takes_a_seed(self) -> None:
        run = self._run(146)
        run["seed_scope"] = rp.seed_scope(True)
        markdown = rp.export_markdown(run)
        self.assertIn("接受 seed", markdown)
        self.assertNotIn("接口不接受 seed", markdown)


class CellSeedTest(unittest.TestCase):
    def test_the_cell_seed_is_derived_from_the_run_seed_and_the_cell(self) -> None:
        first = rp.cell_seed(146, 7, "C1")
        second = rp.cell_seed(146, 7, "C1")
        self.assertEqual(first, second)
        self.assertNotEqual(first, rp.cell_seed(146, 8, "C1"))
        self.assertNotEqual(first, rp.cell_seed(146, 7, "C2"))
        self.assertNotEqual(first, rp.cell_seed(999, 7, "C1"))

    def test_the_cell_seed_is_a_valid_seed(self) -> None:
        value = rp.cell_seed(146, 7, "C1")
        self.assertIsInstance(value, int)
        self.assertGreaterEqual(value, 0)
        self.assertLess(value, 2**31 - 1)


class ProviderScopeTest(unittest.TestCase):
    """Which providers can be asked for the same draw again."""

    def test_the_openai_compatible_backend_takes_a_seed(self) -> None:
        self.assertTrue(rp._backend_takes_seed({"backend_type": "OpenAIProvider"}))

    def test_ollama_takes_a_seed(self) -> None:
        self.assertTrue(rp._backend_takes_seed({"backend_type": "OllamaProvider"}))

    def test_the_anthropic_backend_has_no_seed_to_send(self) -> None:
        """The Anthropic Messages API accepts no seed parameter."""
        self.assertFalse(rp._backend_takes_seed({"backend_type": "AnthropicProvider"}))

    def test_an_unknown_backend_is_treated_as_not_taking_one(self) -> None:
        self.assertFalse(rp._backend_takes_seed({}))

    def test_the_scope_says_the_answers_are_not_covered(self) -> None:
        for supports in (True, False):
            scope = rp.seed_scope(supports)
            self.assertIn("answers", scope["does_not_control"])
            self.assertIn("sampling", scope["controls"])


class ApiSeedTest(unittest.TestCase):
    """The run's answer callable forwards the cell's seed to the provider."""

    def _llm_with_backend(self, backend: object, captured: list[dict]) -> object:
        router = providers.LLM_ROUTER
        original_chain = router._resolve_chain
        original_config = router.config

        class _Router:
            pass

        def _resolve_chain(**kwargs):
            return [name]

        name = "seed_probe"
        router.providers[name] = backend
        router._resolve_chain = _resolve_chain
        router.config = {"llm": {"providers": {name: {}}}}
        self.addCleanup(lambda: router.providers.pop(name, None))
        self.addCleanup(setattr, router, "_resolve_chain", original_chain)
        self.addCleanup(setattr, router, "config", original_config)
        return replication_api._llm(name, "answer", 0.9, 2000)

    def test_an_openai_compatible_run_sends_the_seed(self) -> None:
        captured: list[dict] = []

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

            @property
            def text(self):
                return '{"choices":[{"message":{"content":"ok"}}]}'

        def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
            captured.append(json)
            return _Resp()

        backend = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
        with mock.patch.object(providers, "http_post", fake_post):
            llm = self._llm_with_backend(backend, captured)
            llm("问题", seed=4242)
        self.assertEqual(captured[0].get("seed"), 4242)

    def test_the_run_records_that_its_provider_takes_a_seed(self) -> None:
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "ok"}}]}

            @property
            def text(self):
                return '{"choices":[{"message":{"content":"ok"}}]}'

        def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
            return _Resp()

        backend = providers.OpenAIProvider("http://x/v1", "gpt-4o", api_key="k", attempts=1)
        with mock.patch.object(providers, "http_post", fake_post):
            llm = self._llm_with_backend(backend, [])
        self.assertTrue(rp._backend_takes_seed(llm.provenance))
        self.assertTrue(rp.seed_scope(rp._backend_takes_seed(llm.provenance))["provider_supports_seed"])


if __name__ == "__main__":
    unittest.main()
