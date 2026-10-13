"""Phase 4 — per-agent LLM routing via the GAWorld LLMRouter (RED tests).

Specifies the FOS → GAWorld routing contract from ``PHASE4-BRIEF.md``:

* Routing config shape (experiment-scoped ``llm`` field)::

      {
          "default": {"provider": "a", "model": "m-a"},
          "agents": {"7": {"provider": "b", "model": "m-b"}},   # exact int GAWorld IDs
          "tasks": {"actions": {"provider": "c", "model": "m-c"}},
          "failure_policy": "pause_and_ask" | "fail" | "ordered_fallback",
          "fallback_order": ["c", "d"],   # only for ordered_fallback, explicit
      }

* Precedence (deterministic, never registration/dict/env order):
  explicit per-call override > per-agent > per-task > default.

* Failure policy is enforced by the router: ``pause_and_ask`` (default) and
  ``fail`` stop on the first failure and never touch the default provider;
  ``ordered_fallback`` tries exactly the configured order and never invents
  extra attempts.

* No silent fallback ever. Provenance (original, failed attempt, fallback
  index, agent id) is recorded in ``router.last_call``.

* No credential material ever reaches a frontend-facing routing payload.

The contract under test does not exist yet — every non-guard test here must
fail with AttributeError/TypeError/AssertionError naming the missing feature,
never a syntax error.
"""

from __future__ import annotations

import unittest

import gaworld.llm.providers as llm_providers
from gaworld.llm.providers import LLMRouter


class _StubProvider:
    def __init__(self, name: str, *, fail: bool = False, reply: str | None = None):
        self.name = name
        self.fail = fail
        self.reply = reply
        self.calls = 0
        self.call_args: list[dict] = []

    def call(self, prompt: str, **overrides) -> str:
        self.calls += 1
        self.call_args.append({"prompt": prompt, **overrides})
        if self.fail:
            raise ConnectionError(f"{self.name} simulated failure")
        if self.reply is not None:
            return self.reply
        return f"hello from {self.name}"


def _make_router(routing, providers):
    router = object.__new__(LLMRouter)
    router.providers = providers
    router.routing = routing
    router.config = {}
    return router


def _feature(name):
    """Fetch a not-yet-existing attribute; fails naming the missing feature."""
    attr = getattr(llm_providers, name, None)
    assert attr is not None, (
        f"feature missing: gaworld.llm.providers.{name} is not implemented (Phase 4 RED)"
    )
    return attr


# ---------------------------------------------------------------------------
# §11a — precedence matrix
# ---------------------------------------------------------------------------


class TestPrecedenceMatrix(unittest.TestCase):
    """explicit > agent > task > default, resolved by one function."""

    ROUTING = {
        "default": {"provider": "a", "model": "m-a"},
        "tasks": {"actions": {"provider": "c", "model": "m-c"}},
        "agents": {"7": {"provider": "b", "model": "m-b"}},
    }

    def test_explicit_override_beats_agent(self):
        resolve = _feature("resolve_llm_target")
        target = resolve(self.ROUTING, agent_id=7, provider="z")
        self.assertEqual("z", target["provider"])
        self.assertEqual("explicit", target["source"])

    def test_agent_beats_task(self):
        # The current router resolves task before agent; Phase 4 fixes the
        # order so a per-agent assignment is never shadowed by a task rule.
        resolve = _feature("resolve_llm_target")
        target = resolve(self.ROUTING, task="actions", agent_id=7)
        self.assertEqual("b", target["provider"])
        self.assertEqual("agent", target["source"])

    def test_agent_beats_default(self):
        resolve = _feature("resolve_llm_target")
        target = resolve(self.ROUTING, agent_id=7)
        self.assertEqual(("b", "m-b"), (target["provider"], target["model"]))
        self.assertEqual("agent", target["source"])

    def test_task_beats_default(self):
        resolve = _feature("resolve_llm_target")
        target = resolve(self.ROUTING, task="actions")
        self.assertEqual("c", target["provider"])
        self.assertEqual("task", target["source"])

    def test_default_only(self):
        resolve = _feature("resolve_llm_target")
        target = resolve(self.ROUTING, task="other", agent_id=99)
        self.assertEqual(("a", "m-a"), (target["provider"], target["model"]))
        self.assertEqual("default", target["source"])

    def test_exact_int_agent_ids(self):
        # Keys are exact GAWorld int IDs (JSON gives strings); an int agent_id
        # of 7 must hit the "7" key — and 8 must NOT.
        resolve = _feature("resolve_llm_target")
        self.assertEqual("b", resolve(self.ROUTING, agent_id=7)["provider"])
        self.assertEqual("a", resolve(self.ROUTING, agent_id=8)["provider"])

    def test_resolution_is_deterministic(self):
        resolve = _feature("resolve_llm_target")
        first = resolve(self.ROUTING, agent_id=7)
        for _ in range(5):
            self.assertEqual(first, resolve(self.ROUTING, agent_id=7))


# ---------------------------------------------------------------------------
# §11a — launch-time validation of the experiment llm config
# ---------------------------------------------------------------------------


class TestExperimentConfigValidation(unittest.TestCase):
    """Bad experiment configs are rejected before launch, cheaply."""

    def test_unknown_agent_assignment_rejected(self):
        validate = _feature("validate_llm_routing")
        cfg = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"999": {"provider": "b", "model": "m-b"}},
        }
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, selected_agent_ids=[7, 8], known_providers=["a", "b"])
        self.assertIn("999", str(ctx.exception))

    def test_missing_default_rejected(self):
        validate = _feature("validate_llm_routing")
        cfg = {"agents": {"7": {"provider": "b", "model": "m-b"}}}
        with self.assertRaises(ValueError):
            validate(cfg, selected_agent_ids=[7], known_providers=["a", "b"])

    def test_invalid_provider_reference_rejected(self):
        validate = _feature("validate_llm_routing")
        cfg = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "ghost", "model": "m"}},
        }
        with self.assertRaises(ValueError) as ctx:
            validate(cfg, selected_agent_ids=[7], known_providers=["a"])
        self.assertIn("ghost", str(ctx.exception))

    def test_valid_config_passes(self):
        validate = _feature("validate_llm_routing")
        cfg = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        # Must not raise.
        validate(cfg, selected_agent_ids=[7, 8], known_providers=["a", "b"])


# ---------------------------------------------------------------------------
# §11b / §12 — failure policies at the router
# ---------------------------------------------------------------------------


class TestFailurePolicies(unittest.TestCase):
    def _router(self):
        a = _StubProvider("a")  # the healthy default
        b = _StubProvider("b", fail=True)  # the assigned, broken provider
        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        return _make_router(routing, {"a": a, "b": b}), a, b

    def test_pause_and_ask_stops_and_never_calls_default(self):
        router, a, b = self._router()
        with self.assertRaises(Exception):
            router.call("hi", agent_id=7, failure_policy="pause_and_ask")
        self.assertEqual(1, b.calls, "assigned provider must have been attempted")
        self.assertEqual(0, a.calls, "pause_and_ask must NOT fall back to the default")

    def test_fail_stops_and_never_calls_default(self):
        router, a, b = self._router()
        with self.assertRaises(Exception):
            router.call("hi", agent_id=7, failure_policy="fail")
        self.assertEqual(1, b.calls)
        self.assertEqual(0, a.calls, "fail must NOT fall back to the default")

    def test_ordered_fallback_tries_exact_configured_order(self):
        b = _StubProvider("b", fail=True)
        c = _StubProvider("c")
        a = _StubProvider("a")  # healthy default but NOT in the fallback list
        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        router = _make_router(routing, {"a": a, "b": b, "c": c})
        out = router.call(
            "hi",
            agent_id=7,
            failure_policy="ordered_fallback",
            fallback_order=["c"],
        )
        self.assertEqual("hello from c", out)
        self.assertEqual([1, 1, 0], [b.calls, c.calls, a.calls])

    def test_ordered_fallback_all_fail_reports_every_attempt(self):
        b = _StubProvider("b", fail=True)
        c = _StubProvider("c", fail=True)
        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        router = _make_router(routing, {"b": b, "c": c})
        with self.assertRaises(Exception):
            router.call(
                "hi",
                agent_id=7,
                failure_policy="ordered_fallback",
                fallback_order=["c"],
            )
        attempts = (router.last_call or {}).get("attempts")
        self.assertIsNotNone(attempts, "router.last_call['attempts'] missing (Phase 4)")
        self.assertEqual(
            ["b", "c"],
            [att["provider"] for att in attempts],
            "all configured fallback attempts must be reported",
        )

    def test_no_fallback_without_explicit_config(self):
        # No failure_policy / fallback_order given: a failing assignment must
        # never quietly succeed via the default provider.
        router, a, b = self._router()
        with self.assertRaises(Exception):
            router.call("hi", agent_id=7)
        self.assertEqual(0, a.calls)


class TestNoSilentFallbackRegression(unittest.TestCase):
    """Dedicated guard: agent 7 → B fails; healthy default A is never used."""

    def _scenario(self, policy):
        a = _StubProvider("a")
        b = _StubProvider("b", fail=True)
        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
            "failure_policy": policy,
        }
        router = _make_router(routing, {"a": a, "b": b})
        with self.assertRaises(Exception):
            router.call("hi", agent_id=7)
        return a, b

    def test_policy_pause_and_ask(self):
        a, b = self._scenario("pause_and_ask")
        self.assertEqual((1, 0), (b.calls, a.calls), "default A must never be called")

    def test_policy_fail(self):
        a, b = self._scenario("fail")
        self.assertEqual((1, 0), (b.calls, a.calls), "default A must never be called")


class TestFallbackProvenance(unittest.TestCase):
    """§10 — fallbacks are recorded, never presented as the original model."""

    def test_provenance_fields_recorded(self):
        b = _StubProvider("b", fail=True)
        c = _StubProvider("c")
        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        router = _make_router(routing, {"b": b, "c": c})
        router.call("hi", agent_id=7, failure_policy="ordered_fallback", fallback_order=["c"])

        meta = router.last_call
        self.assertIsNotNone(meta, "router.last_call provenance missing (Phase 4)")
        self.assertEqual(7, meta["agent_id"])
        self.assertEqual("b", meta["resolved"]["provider"], "original assignment recorded")
        self.assertEqual(
            "b", meta["attempts"][0]["provider"], "failed attempt recorded"
        )
        success = meta["attempts"][-1]
        self.assertEqual("c", success["provider"])
        self.assertEqual(1, success["fallback_index"], "fallback index recorded")

    def test_first_try_success_has_zero_fallback_index(self):
        b = _StubProvider("b")
        routing = {
            "default": {"provider": "a", "model": "m-a"},
            "agents": {"7": {"provider": "b", "model": "m-b"}},
        }
        router = _make_router(routing, {"b": b})
        router.call("hi", agent_id=7)
        meta = router.last_call
        self.assertEqual("b", meta["attempts"][-1]["provider"])
        self.assertEqual(0, meta["attempts"][-1]["fallback_index"])


# ---------------------------------------------------------------------------
# §7 — secrets absence in frontend-facing routing payloads
# ---------------------------------------------------------------------------


class TestSecretsAbsence(unittest.TestCase):
    def test_routing_status_leaks_no_credentials(self):
        status = _feature("llm_routing_status")
        routing = {
            "default": {
                "provider": "a",
                "model": "m-a",
                "api_key": "sk-super-secret-123",
            },
            "agents": {
                "7": {"provider": "b", "model": "m-b", "api_key": "sk-other-secret"}
            },
        }
        payload = status(routing)
        blob = repr(payload)
        for secret in ("sk-super-secret-123", "sk-other-secret", "api_key"):
            self.assertNotIn(secret, blob, f"routing status leaked {secret!r}")
        # IDs and model names are fine — and required.
        self.assertEqual("m-a", payload["default"]["model"])


# ---------------------------------------------------------------------------
# §11 backward-compat guard (expected GREEN before Phase 4 lands)
# ---------------------------------------------------------------------------


class TestBackwardCompatGuards(unittest.TestCase):
    """No routing config → existing behaviour. Guards, not RED tests."""

    def test_no_routing_config_uses_first_provider(self):
        x = _StubProvider("x")
        y = _StubProvider("y")
        router = _make_router({}, {"x": x, "y": y})
        self.assertEqual("hello from x", router.call("hi"))

    def test_legacy_string_routing_still_works(self):
        a = _StubProvider("a")
        b = _StubProvider("b")
        router = _make_router(
            {"default": "a", "tasks": {"plan": "b"}}, {"a": a, "b": b}
        )
        self.assertEqual("hello from b", router.call("hi", task="plan"))
        self.assertEqual("hello from a", router.call("hi"))

    def test_legacy_global_fallback_list_still_works(self):
        a = _StubProvider("a", fail=True)
        b = _StubProvider("b")
        router = _make_router({"default": "a", "fallback": ["b"]}, {"a": a, "b": b})
        self.assertEqual("hello from b", router.call("hi"))


# ---------------------------------------------------------------------------
# §12 — mapping test: FOS experiment config → resolved route
# ---------------------------------------------------------------------------


class TestFosExperimentMapping(unittest.TestCase):
    """A FOS experiment's ``llm`` field resolves to the route each agent hits."""

    EXPERIMENT_LLM = {
        "default": {"provider": "deepseek", "model": "deepseek-chat"},
        "agents": {"7": {"provider": "qwen-local", "model": "qwen3-4b-instruct"}},
        "failure_policy": "pause_and_ask",
    }

    def test_agent_7_maps_to_override(self):
        resolve = _feature("resolve_llm_target")
        target = resolve(self.EXPERIMENT_LLM, agent_id=7, task="actions")
        self.assertEqual("qwen-local", target["provider"])
        self.assertEqual("qwen3-4b-instruct", target["model"])

    def test_other_agent_maps_to_default(self):
        resolve = _feature("resolve_llm_target")
        target = resolve(self.EXPERIMENT_LLM, agent_id=31)
        self.assertEqual(("deepseek", "deepseek-chat"), (target["provider"], target["model"]))

    def test_mapping_provenance_end_to_end(self):
        # Config says agent 7 → qwen-local AND the router actually called it.
        deepseek = _StubProvider("deepseek")
        qwen = _StubProvider("qwen-local")
        router = _make_router(dict(self.EXPERIMENT_LLM), {"deepseek": deepseek, "qwen-local": qwen})
        router.call("hi", task="actions", agent_id=7)
        self.assertEqual((0, 1), (deepseek.calls, qwen.calls))


if __name__ == "__main__":
    unittest.main()
