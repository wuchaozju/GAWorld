"""State-aware candidate tags for the dashboard's 人生事件 panel.

Three things have to hold for the tag cloud to be worth having:

1. **Gating is real.** A tag that offers 离婚 to someone unmarried or 退休 to a
   25-year-old is worse than no tag at all — the whole point is that the set
   reads as *this* resident's plausible next chapter.
2. **The set moves with the state.** If the ranking ignores the state
   variables, the "candidates" are just a second, longer dropdown.
3. **A click queues a real event.** The tag posts a key; the payload the
   simulator consumes is assembled server-side and must survive
   ``normalize_life_event`` with its title, severity and effects intact.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.events import candidates as candidate_events
from gaworld.events import life as life_events

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")


def _read(*parts):
    with open(os.path.join(DASHBOARD, *parts), encoding="utf-8") as handle:
        return handle.read()


def _context(**overrides):
    """A plain, middle-of-the-road resident; tests vary one axis at a time."""
    context = {
        "age": 34,
        "hukou": "本地",
        "job": "软件工程师",
        "employment": "employed",
        "self_employed": False,
        "marital_status": "single",
        "children": 0,
        "has_parents": True,
        "balance": 20000.0,
        "debt": 0.0,
        "state": {
            "emotion": 0.5,
            "stress": 0.5,
            "econ_security": 0.5,
            "city_identity": 0.5,
            "policy_sensitivity": 0.5,
            "platform_dependence": 0.3,
            "risk_preference": 0.5,
            "voice_propensity": 0.5,
            "mobility_intent": 0.5,
        },
    }
    context.update(overrides)
    return context


def _keys(context, limit=candidate_events.MAX_CANDIDATE_LIMIT):
    return [item["key"] for item in candidate_events.rank_life_event_candidates(context, limit=limit)]


class GatingTests(unittest.TestCase):
    """``candidate_applies`` answers the gate alone — the shortlist also truncates."""

    def assertOffered(self, key, context):
        self.assertTrue(candidate_events.candidate_applies(key, context), key)

    def assertNotOffered(self, key, context):
        self.assertFalse(candidate_events.candidate_applies(key, context), key)

    def test_divorce_needs_a_marriage(self):
        self.assertNotOffered("divorce", _context(marital_status="single"))
        self.assertOffered("divorce", _context(marital_status="married"))

    def test_marriage_is_not_offered_to_the_married(self):
        self.assertOffered("marriage", _context(marital_status="single"))
        self.assertNotOffered("marriage", _context(marital_status="married"))

    def test_job_events_track_employment(self):
        employed = _context(employment="employed")
        self.assertOffered("unemployment", employed)
        self.assertNotOffered("reemployment", employed)

        jobless = _context(employment="unemployed", job="待业中")
        self.assertNotOffered("unemployment", jobless)
        self.assertNotOffered("promotion", jobless)
        self.assertOffered("reemployment", jobless)

    def test_retirement_needs_the_years(self):
        self.assertNotOffered("retirement", _context(age=25))
        self.assertOffered("retirement", _context(age=64))

    def test_child_events_need_a_child(self):
        self.assertNotOffered("child_milestone", _context(children=0))
        self.assertOffered("child_milestone", _context(children=2))

    def test_platform_shock_only_for_platform_workers(self):
        office = _context()
        office["state"]["platform_dependence"] = 0.2
        self.assertNotOffered("platform_rule_shock", office)

        rider = _context(job="外卖骑手")
        rider["state"]["platform_dependence"] = 0.9
        self.assertOffered("platform_rule_shock", rider)
        self.assertIn("platform_rule_shock", _keys(rider, limit=10))

    def test_business_failure_only_for_the_self_employed(self):
        self.assertNotOffered("business_failure", _context())
        self.assertOffered("business_failure", _context(job="自己开了家小店", self_employed=True))

    def test_unknown_key_never_applies(self):
        self.assertFalse(candidate_events.candidate_applies("no_such_event", _context()))

    def test_employment_inferred_from_job_text(self):
        self.assertEqual("employed", candidate_events.employment_from_job("外卖配送员"))
        self.assertEqual("unemployed", candidate_events.employment_from_job("待业中"))
        self.assertEqual("retired", candidate_events.employment_from_job("退休"))
        self.assertEqual("student", candidate_events.employment_from_job("学生"))
        self.assertTrue(candidate_events.is_self_employed("创业做餐饮"))
        self.assertFalse(candidate_events.is_self_employed("公司职员"))


class RankingTests(unittest.TestCase):
    def test_limit_is_clamped_to_a_tag_cloud(self):
        context = _context()
        self.assertEqual(10, len(candidate_events.rank_life_event_candidates(context, limit=1)))
        self.assertEqual(20, len(candidate_events.rank_life_event_candidates(context, limit=999)))
        self.assertEqual(
            candidate_events.DEFAULT_CANDIDATE_LIMIT,
            len(candidate_events.rank_life_event_candidates(context)),
        )

    def test_catalogue_is_big_enough_to_fill_the_cloud(self):
        """Even the most gated-out resident should still get a full set."""
        narrow = _context(age=70, employment="retired", job="退休", marital_status="widowed", children=0, has_parents=False)
        self.assertGreaterEqual(len(_keys(narrow, limit=20)), candidate_events.MIN_CANDIDATE_LIMIT)

    def test_ranking_follows_the_state(self):
        """The same person under money stress gets a different shortlist."""
        secure = _context()
        secure["state"]["econ_security"] = 0.9
        secure["state"]["stress"] = 0.2

        precarious = _context()
        precarious["state"]["econ_security"] = 0.1
        precarious["state"]["stress"] = 0.9

        # Both are employed, so 失业 is on the table either way — but it only
        # makes the shortlist for the one whose situation invites it.
        self.assertTrue(candidate_events.candidate_applies("unemployment", secure))
        self.assertIn("unemployment", _keys(precarious, limit=10))
        self.assertNotIn("unemployment", _keys(secure, limit=10))

    def test_rootless_resident_is_offered_the_exit(self):
        drifting = _context(hukou="外省")
        drifting["state"]["city_identity"] = 0.1
        drifting["state"]["mobility_intent"] = 0.9
        self.assertIn("leave_city", _keys(drifting, limit=10))

    def test_candidates_expose_no_callables(self):
        for item in candidate_events.rank_life_event_candidates(_context()):
            self.assertNotIn("gate", item)
            self.assertNotIn("weight", item)
            self.assertIn("score", item)
            self.assertTrue(item["title"])
            self.assertTrue(item["description"])

    def test_every_dropdown_template_is_also_a_candidate(self):
        catalog = {item["key"] for item in candidate_events.LIFE_EVENT_CANDIDATES}
        for template in life_events.list_life_event_templates():
            self.assertIn(template["key"], catalog)

    def test_state_effects_stay_within_the_simulator_vocabulary(self):
        for item in candidate_events.LIFE_EVENT_CANDIDATES:
            for key, value in item.get("state_effects", {}).items():
                self.assertIn(key, life_events.STATE_EFFECT_KEYS, item["key"])
                self.assertLessEqual(abs(value), 0.35, item["key"])

    def test_only_job_rewriting_events_carry_the_employment_tag(self):
        """``employment`` makes finance.py rewrite the job — retirement must not."""
        rewriting = {"job_change", "unemployment", "entrepreneurship", "business_failure", "reemployment"}
        for item in candidate_events.LIFE_EVENT_CANDIDATES:
            if "employment" in item.get("impact_tags", []):
                self.assertIn(item["key"], rewriting)


class CooldownTests(unittest.TestCase):
    """A tag you just clicked has to leave, and has to come back on its own."""

    def test_a_queued_event_hides_its_own_tag(self):
        context = _context(marital_status="married", day=100)
        self.assertIn("divorce", _keys(context))

        context["recent_events"] = [{"key": "divorce", "day": None, "pending": True}]
        self.assertNotIn("divorce", _keys(context))
        # The gate still says it applies — it is hidden, not ruled out.
        self.assertTrue(candidate_events.candidate_applies("divorce", context))

    def test_a_fired_event_returns_once_its_cooldown_expires(self):
        fired_day = 100
        cooldown = candidate_events.candidate_cooldown_days("divorce")

        def at(day):
            context = _context(marital_status="married", day=day)
            context["recent_events"] = [{"key": "divorce", "day": fired_day, "pending": False}]
            return context

        self.assertNotIn("divorce", _keys(at(fired_day)))
        self.assertNotIn("divorce", _keys(at(fired_day + cooldown - 1)))
        self.assertIn("divorce", _keys(at(fired_day + cooldown)))

    def test_cooldown_length_follows_the_event_scale(self):
        """A flu comes back around long before a divorce does."""
        self.assertLess(
            candidate_events.candidate_cooldown_days("illness"),
            candidate_events.candidate_cooldown_days("relationship_break"),
        )
        self.assertLess(
            candidate_events.candidate_cooldown_days("relationship_break"),
            candidate_events.candidate_cooldown_days("divorce"),
        )
        self.assertEqual(
            candidate_events.DEFAULT_CANDIDATE_COOLDOWN_DAYS,
            candidate_events.candidate_cooldown_days("no_such_event"),
        )

    def test_returning_tag_still_has_to_earn_its_place(self):
        """"Cooldown expired" is not "shown" — the ranking still decides."""
        context = _context(day=1000)
        context["state"]["econ_security"] = 0.9
        context["state"]["stress"] = 0.1
        context["recent_events"] = [{"key": "unemployment", "day": 100, "pending": False}]
        self.assertEqual({}, candidate_events.cooldown_keys(context))
        self.assertTrue(candidate_events.candidate_applies("unemployment", context))
        self.assertNotIn("unemployment", _keys(context, limit=10))

    def test_a_reset_run_does_not_hide_tags_for_a_future_day(self):
        context = _context(day=3)
        context["recent_events"] = [{"key": "illness", "day": 6000, "pending": False}]
        self.assertEqual({}, candidate_events.cooldown_keys(context))

    def test_other_subsystems_events_are_ignored(self):
        context = _context(day=100)
        context["recent_events"] = [
            {"key": "family_elder_visit", "day": 99, "pending": False},
            {"key": "ghost_milestone", "day": None, "pending": True},
            {"key": "", "day": 99, "pending": False},
            "not a dict",
        ]
        self.assertEqual({}, candidate_events.cooldown_keys(context))

    def test_cooldown_reports_days_remaining(self):
        context = _context(day=110)
        context["recent_events"] = [{"key": "illness", "day": 100, "pending": False}]
        self.assertEqual(
            {"illness": candidate_events.candidate_cooldown_days("illness") - 10},
            candidate_events.cooldown_keys(context),
        )

    def test_missing_history_means_no_cooldown(self):
        self.assertEqual({}, candidate_events.cooldown_keys(_context()))
        self.assertEqual({}, candidate_events.cooldown_keys(None))


class SignatureTests(unittest.TestCase):
    def test_signature_is_stable_for_the_same_situation(self):
        self.assertEqual(
            candidate_events.context_signature(_context()),
            candidate_events.context_signature(_context()),
        )

    def test_signature_moves_with_the_state(self):
        moved = _context()
        moved["state"]["stress"] = 0.9
        self.assertNotEqual(
            candidate_events.context_signature(_context()),
            candidate_events.context_signature(moved),
        )

    def test_signature_moves_when_a_tag_leaves_or_returns(self):
        """Otherwise the panel keeps a clicked tag on screen until a reload."""
        idle = _context(marital_status="married", day=100)
        clicked = dict(idle, recent_events=[{"key": "divorce", "day": 100, "pending": False}])
        expired = dict(idle, day=100 + candidate_events.candidate_cooldown_days("divorce"))
        expired["recent_events"] = clicked["recent_events"]

        self.assertNotEqual(
            candidate_events.context_signature(idle),
            candidate_events.context_signature(clicked),
        )
        self.assertEqual(
            candidate_events.context_signature(idle),
            candidate_events.context_signature(expired),
        )

    def test_signature_ignores_the_clock_between_departures(self):
        """The day advances every step; the cloud must not repaint every step."""
        day_one = _context(day=100)
        day_two = _context(day=101)
        self.assertEqual(
            candidate_events.context_signature(day_one),
            candidate_events.context_signature(day_two),
        )

    def test_signature_ignores_fourth_decimal_noise(self):
        """Otherwise the panel repaints on every poll of a live run."""
        jittered = _context()
        jittered["state"]["stress"] = 0.5001
        self.assertEqual(
            candidate_events.context_signature(_context()),
            candidate_events.context_signature(jittered),
        )


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = {
            "life_events": {
                "event_dir": os.path.join(self.tmpdir.name, "life_events"),
                "events_file": "events.json",
            }
        }

    def test_unknown_key_is_refused(self):
        with self.assertRaises(ValueError):
            candidate_events.candidate_event_payload("no_such_event")

    def test_clicked_tag_queues_a_usable_event(self):
        payload = candidate_events.candidate_event_payload("divorce", agent_ids=[7])
        event = life_events.add_life_event(payload, self.config)

        self.assertEqual("离婚", event["title"])
        self.assertEqual([7], event["agent_ids"])
        self.assertEqual("immediate", event["schedule_mode"])
        self.assertEqual("divorce", event["template_key"])
        self.assertIn("family", event["impact_tags"])
        self.assertLess(event["state_effects"]["emotion"], 0)

        due = life_events.drain_due_life_events(1, "09:00", self.config)
        self.assertEqual(1, len(due))
        self.assertEqual("离婚", due[0]["title"])

    def test_severity_can_be_overridden(self):
        payload = candidate_events.candidate_event_payload("divorce", agent_ids=[7], severity=0.2)
        self.assertEqual(0.2, life_events.add_life_event(payload, self.config)["severity"])


class DashboardWiringTests(unittest.TestCase):
    """The panel is only useful if the page actually renders and posts it."""

    def test_markup_hosts_the_tag_cloud(self):
        html = _read("index.html")
        self.assertIn('id="lifeEventCandidates"', html)
        self.assertIn('data-i18n="life_event.candidates"', html)

    def test_app_loads_ranks_and_posts(self):
        app = _read("app.js")
        self.assertIn("/api/life-events/candidates", app)
        self.assertIn("candidate_key", app)
        # Repainting only on a signature change is what keeps the 2.5s poll
        # from stomping on a click.
        self.assertIn("lifeEventCandidateKey", app)
        self.assertIn("loadLifeEventCandidates()", app)

    def test_new_strings_exist_in_both_locales(self):
        import json

        for locale in ("zh-CN", "en"):
            with open(os.path.join(DASHBOARD, "locales", f"{locale}.json"), encoding="utf-8") as handle:
                strings = json.load(handle)
            for key in (
                "life_event.candidates",
                "life_event.candidates_hint",
                "life_event.candidates_empty",
                "life_event.candidate_queued",
            ):
                self.assertIn(key, strings, locale)


class ServerTests(unittest.TestCase):
    def test_candidate_key_is_expanded_server_side(self):
        from gaworld.apps import dashboard_server as ds

        payload = ds._expand_candidate_payload({"candidate_key": "divorce", "agent_ids": "7"})
        self.assertEqual("离婚", payload["title"])
        self.assertEqual("7", payload["agent_ids"])
        self.assertNotIn("candidate_key", payload)

    def test_form_payloads_pass_through_untouched(self):
        from gaworld.apps import dashboard_server as ds

        form = {"template_key": "illness", "title": "自定义"}
        self.assertEqual(form, ds._expand_candidate_payload(form))

    def test_context_and_ranking_for_a_seeded_agent(self):
        """End to end against the repo's own data files, whatever a run left."""
        from gaworld.apps import dashboard_server as ds

        agent_id = ds._agents_summary()[0]["id"]
        payload = ds._life_event_candidates_payload(agent_id)
        self.assertEqual(agent_id, payload["agent_id"])
        self.assertTrue(payload["signature"])
        self.assertGreaterEqual(len(payload["candidates"]), candidate_events.MIN_CANDIDATE_LIMIT)
        self.assertLessEqual(len(payload["candidates"]), candidate_events.MAX_CANDIDATE_LIMIT)

    def test_unknown_agent_has_no_candidates(self):
        from gaworld.apps import dashboard_server as ds

        self.assertIsNone(ds._life_event_candidates_payload(999999))

    def test_history_flattens_events_aimed_at_this_agent(self):
        from unittest import mock

        from gaworld.apps import dashboard_server as ds

        stored = [
            {"template_key": "divorce", "agent_ids": [7], "status": "pending", "day": None},
            {"template_key": "illness", "agent_ids": [], "status": "consumed", "triggered_day": 40},
            {"template_key": "lottery", "agent_ids": [9], "status": "consumed", "triggered_day": 41},
        ]
        with mock.patch.object(ds, "list_life_events", return_value=stored):
            history = ds._life_event_history(7)

        self.assertEqual(
            [
                {"key": "divorce", "day": None, "pending": True},
                # Empty agent_ids means everyone, so it lands on 7 as well.
                {"key": "illness", "day": 40, "pending": False},
            ],
            history,
        )

    def test_current_day_falls_back_to_the_last_day_anything_fired(self):
        from unittest import mock

        from gaworld.apps import dashboard_server as ds

        history = [
            {"key": "illness", "day": 40, "pending": False},
            {"key": "divorce", "day": None, "pending": True},
        ]
        with mock.patch.object(ds, "_current_trace_frame", return_value={}):
            self.assertEqual(40, ds._life_event_current_day(history))
            self.assertEqual(0, ds._life_event_current_day([]))
        with mock.patch.object(ds, "_current_trace_frame", return_value={"day": 6007}):
            self.assertEqual(6007, ds._life_event_current_day(history))

    def test_a_queued_tag_is_gone_from_the_payload(self):
        from unittest import mock

        from gaworld.apps import dashboard_server as ds

        agent_id = ds._agents_summary()[0]["id"]
        with mock.patch.object(ds, "list_life_events", return_value=[]):
            before = [item["key"] for item in ds._life_event_candidates_payload(agent_id)["candidates"]]
        self.assertTrue(before, "the seeded agent should have candidates to begin with")

        clicked = before[0]
        queued = [{"template_key": clicked, "agent_ids": [agent_id], "status": "pending", "day": None}]
        with mock.patch.object(ds, "list_life_events", return_value=queued):
            payload = ds._life_event_candidates_payload(agent_id)

        after = [item["key"] for item in payload["candidates"]]
        self.assertNotIn(clicked, after)
        # The cloud stays full: the next-best candidate moves up into the gap.
        self.assertEqual(len(before), len(after))


if __name__ == "__main__":
    unittest.main()
