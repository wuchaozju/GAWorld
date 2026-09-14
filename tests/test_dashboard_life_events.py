"""The 人生事件 panel's wiring: candidate route, candidate POST, panel headings.

`gaworld.events.candidates` is covered on its own in
``test_life_event_candidates.py`` — the ranking rules, the cooldown, the
signature. This file covers the half that broke: the catalogue was complete
and tested, the dashboard fetched it, and nobody registered the route. The
panel shipped dead, and the only symptom was an error toast on every page
load.

Three failure modes, all of which have already happened here:

1. **A client URL no route claims.** ``app.js`` fetched
   ``/api/life-events/candidates``; the server answered 404 "Unknown
   endpoint". A unit test of the ranking function cannot see that, so the
   route is exercised over real HTTP.
2. **A key the POST handler does not understand.** The tag cloud posts a
   ``candidate_key`` instead of a full event body. Without expansion the
   event is queued untitled, which looks like a working click.
3. **A kicker that repeats its own heading.** Panel headers are "English
   label above localized title"; binding both to one i18n key prints the
   same words twice, in every locale, and reads as a rendering bug.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.events import candidates as candidate_events

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")

#: What the tag cloud fetches. Kept as a literal so a rename on either side
#: has to be made on both.
CANDIDATES_PATH = "/api/life-events/candidates"


def _read(*parts):
    with open(os.path.join(DASHBOARD, *parts), encoding="utf-8") as handle:
        return handle.read()


def _locale(name):
    with open(os.path.join(DASHBOARD, "locales", f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


def _first_agent_id():
    """An id that exists in the seed CSV, so the test does not hardcode one."""
    rows = ds._read_state_rows()[1]
    for row in rows:
        agent_id = ds._row_id(row)
        if agent_id is not None:
            return agent_id
    raise unittest.SkipTest("no agents in the seed CSV")


class CandidateRouteTest(unittest.TestCase):
    """Over real HTTP: a unit test of the ranking cannot catch a missing route."""

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.agent_id = _first_agent_id()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=20) as res:
                return json.loads(res.read().decode("utf-8")), res.status
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8")), exc.code

    def test_the_url_the_client_fetches_is_routed(self):
        payload, status = self._get(f"{CANDIDATES_PATH}?agent_id={self.agent_id}&limit=16")
        self.assertEqual(200, status, payload)
        self.assertNotEqual("Unknown endpoint", payload.get("error"))

    def test_payload_carries_every_field_the_panel_reads(self):
        payload, _ = self._get(f"{CANDIDATES_PATH}?agent_id={self.agent_id}")
        # app.js reads exactly these: the label, the repaint digest, the tags.
        for field in ("agent_id", "agent_name", "signature", "candidates"):
            self.assertIn(field, payload)
        self.assertEqual(self.agent_id, payload["agent_id"])

    def test_tags_carry_what_the_cloud_renders(self):
        payload, _ = self._get(f"{CANDIDATES_PATH}?agent_id={self.agent_id}")
        self.assertTrue(payload["candidates"], "a seeded agent should have candidates")
        for tag in payload["candidates"]:
            # key drives the click, title the label, severity the tint,
            # description the tooltip.
            for field in ("key", "title", "description", "severity"):
                self.assertIn(field, tag)
            self.assertNotIn("gate", tag, "rule callables must stay server-side")

    def test_limit_is_honoured_within_the_clamp(self):
        payload, _ = self._get(f"{CANDIDATES_PATH}?agent_id={self.agent_id}&limit=10")
        self.assertLessEqual(len(payload["candidates"]), 10)

    def test_a_missing_agent_id_is_a_400_not_a_stack_trace(self):
        payload, status = self._get(CANDIDATES_PATH)
        self.assertEqual(400, status)
        self.assertIn("agent_id", payload["error"])

    def test_an_unknown_agent_is_a_404(self):
        payload, status = self._get(f"{CANDIDATES_PATH}?agent_id=999999")
        self.assertEqual(404, status)
        self.assertEqual("Agent not found", payload["error"])


class CandidateContextTest(unittest.TestCase):
    """The context is read off the files on disk; the gates depend on it."""

    def test_context_reaches_the_fields_the_gates_read(self):
        context = ds._life_event_candidate_context(_first_agent_id())
        self.assertIsNotNone(context)
        # `job` lives only in the Markdown profile — the CSV has no column for
        # it — and three gates (platform / self-employed / employment) read it.
        self.assertIn("job", context)
        for field in ("age", "hukou", "state", "day", "recent_events"):
            self.assertIn(field, context)

    def test_an_unknown_agent_has_no_context(self):
        self.assertIsNone(ds._life_event_candidate_context(999999))

    def test_a_fired_event_is_reported_for_the_cooldown(self):
        """`cooldown_keys` needs {key, day, pending} per event, or it hides nothing."""
        history = ds._life_event_history(_first_agent_id())
        for item in history:
            self.assertEqual({"key", "day", "pending"}, set(item))


class CandidatePostTest(unittest.TestCase):
    """`_expand_candidate_payload` is pinned in test_life_event_candidates.py.

    What is pinned here is that the POST handler actually calls it — the panel
    was dead not because the expansion was wrong but because nothing invoked it.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Redirect the queue file: this test writes events, and the repo's own
        # output/ is a live artifact.
        config = dict(ds.CONFIG)
        config["life_events"] = {
            "enabled": True,
            "event_dir": tmp.name,
            "events_file": "events.json",
        }
        patch = mock.patch.object(ds, "CONFIG", config)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_post_handler_queues_the_catalogue_entry(self):
        entry = candidate_events.candidate_by_key("illness")
        event = ds._add_life_event(
            {"candidate_key": "illness", "agent_ids": "3", "schedule_mode": "immediate"}
        )["event"]
        self.assertEqual(entry["title"], event["title"])
        self.assertEqual(entry["severity"], event["severity"])
        self.assertEqual([3], event["agent_ids"])
        self.assertEqual("dashboard-candidate", event["created_by"])

    def test_an_unknown_candidate_key_never_queues_an_untitled_event(self):
        # ValueError is what the HTTP boundary turns into a 400 with a message.
        with self.assertRaises(ValueError):
            ds._add_life_event({"candidate_key": "no_such_event", "agent_ids": "3"})


class PanelHeadingTest(unittest.TestCase):
    """Kicker = English label, h2 = localized title. Never the same key."""

    def setUp(self):
        self.page = _read("index.html")
        # <p class="kicker" data-i18n="X">…</p> … <h2 data-i18n="Y">
        self.pairs = re.findall(
            r'<p class="kicker" data-i18n="([^"]+)">.*?<h2[^>]*data-i18n="([^"]+)"',
            self.page,
            re.S,
        )

    def test_the_page_still_has_panel_headers(self):
        self.assertGreaterEqual(len(self.pairs), 9, "header regex stopped matching")

    def test_no_kicker_shares_its_key_with_its_heading(self):
        same = [k for k, h2 in self.pairs if k == h2]
        self.assertEqual([], same, f"kicker and h2 bound to one key: {same}")

    def test_no_kicker_renders_as_its_own_heading(self):
        """Distinct keys are not enough — the values have to differ too."""
        for name in ("en", "zh-CN"):
            messages = _locale(name)
            for kicker, title in self.pairs:
                with self.subTest(locale=name, kicker=kicker):
                    self.assertNotEqual(
                        messages.get(kicker, kicker),
                        messages.get(title, title),
                        f"{name}: {kicker} and {title} render the same text",
                    )

    def test_every_heading_key_is_translated(self):
        en, zh = _locale("en"), _locale("zh-CN")
        for kicker, title in self.pairs:
            for key in (kicker, title):
                with self.subTest(key=key):
                    self.assertIn(key, en)
                    self.assertIn(key, zh)


class MobileWidthTest(unittest.TestCase):
    """The dashboard scrolled ~1100px sideways on a phone. Three causes."""

    def setUp(self):
        self.css = _read("styles.css")

    def test_single_column_grids_are_floored_at_zero(self):
        """A bare `1fr` floors the column at min-content, which one wide
        memory card then pushes onto the whole page."""
        mobile = self.css.split("@media (max-width: 720px)")[-1]
        for rule in re.findall(r"grid-template-columns:\s*([^;]+);", mobile):
            with self.subTest(rule=rule):
                self.assertNotRegex(
                    rule.strip(),
                    r"^1fr$",
                    "use minmax(0, 1fr): a bare 1fr cannot shrink below min-content",
                )

    def test_the_action_row_can_shrink(self):
        """Its max-content is ~1000px; flex-shrink: 0 pinned the page to that."""
        rule = re.search(r"\.toolbar-actions\s*\{([^}]*)\}", self.css).group(1)
        self.assertNotRegex(rule, r"flex:\s*0\s+0\s")
        self.assertIn("min-width: 0", rule)

    def test_memory_text_can_break_mid_token(self):
        """Memory lines quote URLs verbatim; one unbroken link widened the page."""
        rule = re.search(r"\.memory-view\s*\{([^}]*)\}", self.css).group(1)
        self.assertIn("overflow-wrap: anywhere", rule)


if __name__ == "__main__":
    unittest.main()
