import unittest
from unittest.mock import patch

from gaworld.apps.public_smoke import check_relay


class TestPublicSmoke(unittest.TestCase):
    def test_requires_delivered_message_not_just_http_success(self):
        with patch("gaworld.apps.public_smoke.request_json", return_value={"ok": True}):
            with self.assertRaisesRegex(ValueError, "not delivered"):
                check_relay("https://example.test/agent-relay")

    def test_tests_two_agents_in_an_isolated_cluster(self):
        messages = []
        clusters = []

        def request(url, payload=None):
            if payload:
                clusters.append(payload["cluster"])
            if url.endswith("/message/send"):
                messages.append(payload["message"])
            if url.endswith("/message/poll"):
                return {"ok": True, "messages": messages}
            return {"ok": True}

        with patch("gaworld.apps.public_smoke.request_json", side_effect=request):
            result = check_relay("https://example.test/agent-relay/")
        self.assertEqual(result["poll"], "ok")
        self.assertEqual(len(set(clusters)), 1)
        self.assertTrue(clusters[0].startswith("public-smoke-"))
