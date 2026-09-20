import os
import tempfile
import unittest

from gaworld.twin import binding


class TestTwinBinding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "twin_bindings.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_issue_code_then_redeem_returns_a_token(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        self.assertTrue(token)
        self.assertEqual(binding.resolve_token(token, path=self.path), 7)

    def test_the_plaintext_code_is_never_persisted(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        with open(self.path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn(code, raw)

    def test_the_plaintext_token_is_never_persisted(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        with open(self.path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn(token, raw)

    def test_unknown_code_is_rejected(self):
        self.assertIsNone(binding.redeem_code("nope", path=self.path))

    def test_unknown_token_resolves_to_none(self):
        self.assertIsNone(binding.resolve_token("nope", path=self.path))

    def test_a_code_can_be_redeemed_more_than_once(self):
        # The user may reinstall the PWA or clear site data. Each redemption
        # issues a fresh token; both remain valid until revoked.
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        first = binding.redeem_code(code, path=self.path)
        second = binding.redeem_code(code, path=self.path)
        self.assertNotEqual(first, second)
        self.assertEqual(binding.resolve_token(first, path=self.path), 7)
        self.assertEqual(binding.resolve_token(second, path=self.path), 7)

    def test_revoked_code_stops_issuing_tokens(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        binding.revoke_code(code, path=self.path)
        self.assertIsNone(binding.redeem_code(code, path=self.path))

    def test_revoking_a_code_invalidates_tokens_already_issued_from_it(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        binding.revoke_code(code, path=self.path)
        self.assertIsNone(binding.resolve_token(token, path=self.path))

    def test_two_agents_get_distinct_bindings(self):
        code_a = binding.issue_code(agent_id=7, label="a", path=self.path)
        code_b = binding.issue_code(agent_id=8, label="b", path=self.path)
        token_a = binding.redeem_code(code_a, path=self.path)
        token_b = binding.redeem_code(code_b, path=self.path)
        self.assertEqual(binding.resolve_token(token_a, path=self.path), 7)
        self.assertEqual(binding.resolve_token(token_b, path=self.path), 8)

    def test_an_unbound_code_yields_a_token_with_no_agent(self):
        code = binding.issue_code(path=self.path)
        token = binding.redeem_code(code, path=self.path)
        status = binding.token_status(token, path=self.path)
        self.assertTrue(status["valid"])
        self.assertIsNone(status["agent_id"])

    def test_token_status_tells_invalid_apart_from_unbound(self):
        # The caller must distinguish a 401 from a prompt-to-choose.
        self.assertEqual(
            binding.token_status("nope", path=self.path),
            {"valid": False, "agent_id": None},
        )

    def test_binding_a_token_points_it_at_an_agent(self):
        code = binding.issue_code(path=self.path)
        token = binding.redeem_code(code, path=self.path)
        self.assertTrue(binding.bind_token(token, 12, path=self.path))
        self.assertEqual(binding.resolve_token(token, path=self.path), 12)

    def test_binding_can_be_changed(self):
        code = binding.issue_code(path=self.path)
        token = binding.redeem_code(code, path=self.path)
        binding.bind_token(token, 12, path=self.path)
        binding.bind_token(token, 13, path=self.path)
        self.assertEqual(binding.resolve_token(token, path=self.path), 13)

    def test_binding_an_invalid_token_fails(self):
        self.assertFalse(binding.bind_token("nope", 12, path=self.path))

    def test_claimed_agent_ids_lists_taken_agents(self):
        code = binding.issue_code(path=self.path)
        token = binding.redeem_code(code, path=self.path)
        binding.bind_token(token, 12, path=self.path)
        self.assertEqual(binding.claimed_agent_ids(path=self.path), {12})

    def test_claimed_agent_ids_can_exclude_the_asking_token(self):
        # Otherwise the picker would hide the agent you are already twinning.
        code = binding.issue_code(path=self.path)
        token = binding.redeem_code(code, path=self.path)
        binding.bind_token(token, 12, path=self.path)
        self.assertEqual(
            binding.claimed_agent_ids(path=self.path, exclude_token=token), set()
        )

    def test_revoked_codes_release_their_claim(self):
        code = binding.issue_code(path=self.path)
        token = binding.redeem_code(code, path=self.path)
        binding.bind_token(token, 12, path=self.path)
        binding.revoke_code(code, path=self.path)
        self.assertEqual(binding.claimed_agent_ids(path=self.path), set())

    def test_label_for_token(self):
        code = binding.issue_code(agent_id=7, label="cw", path=self.path)
        token = binding.redeem_code(code, path=self.path)
        self.assertEqual(binding.label_for_token(token, path=self.path), "cw")


if __name__ == "__main__":
    unittest.main()
