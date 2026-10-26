"""Tests for 同居模式 (gaworld.apps.roommate_api).

What we defend:

* **Session lifecycle.** ``start_session`` validates ids, opens a session
  with a known set of residents, and is idempotent for the catalogue.
* **Tick advances state.** A tick increments ``tick_index``, advances the
  virtual clock, and adds at least one event; the deadline from
  ``max_hours`` is respected (the session stops at the boundary).
* **Interactions cost one model call, no more.** Idle ticks cost zero; only
  a co-present pair triggers ``reaction_fn``. We verify the call count.
* **Mood and relationships move deterministically.** Given a known
  ``reaction_fn`` we can assert what the dashboard will see.
* **HTTP delegation.** ``/api/games/roommate/{catalogue, sessions/<id>,
  start, tick, end}`` plus the 400/404 contract.

No LLM is reached at runtime: ``reaction_fn`` is injected, and the roster /
profile block are mocked.
"""

from __future__ import annotations

import json
import random
import unittest
from unittest import mock

from gaworld.apps import games_api, roommate_api

PEOPLE = [
    {
        "id": 1,
        "name": "闫然",
        "age": 41,
        "gender": "男",
        "job": "美发店员",
        "residence": "A小区",
        "state": {},
        "hukou": "本地",
    },
    {
        "id": 2,
        "name": "林佳",
        "age": 28,
        "gender": "女",
        "job": "小学老师",
        "residence": "A小区",
        "state": {},
        "hukou": "本地",
    },
    {
        "id": 3,
        "name": "蒋颂",
        "age": 67,
        "gender": "男",
        "job": "退休",
        "residence": "B小区",
        "state": {},
        "hukou": "本地",
    },
]


def _reply(room: str = "kitchen", mood_a: float = 0.1, mood_b: float = -0.05, rel: float = 2.0) -> str:
    return json.dumps({
        "room": room,
        "lines": [
            {"who": "闫然", "text": "嗨,早上好"},
            {"who": "林佳", "text": "早啊,睡得怎么样?"},
        ],
        "thought_a": "还好吧",
        "thought_b": "有点累",
        "mood_delta_a": mood_a,
        "mood_delta_b": mood_b,
        "rel_delta": rel,
    })


class RoommateApiTests(unittest.TestCase):
    def setUp(self):
        roommate_api.reset_sessions()
        # Mock roster/profile_block so no real city is needed.
        self._roster_patch = mock.patch(
            "gaworld.interview.roster.load_population", return_value=PEOPLE
        )
        self._profile_patch = mock.patch(
            "gaworld.interview.roster.profile_block", return_value="档案:一个普通居民"
        )
        self._roster_patch.start()
        self._profile_patch.start()

    def tearDown(self):
        self._roster_patch.stop()
        self._profile_patch.stop()

    # -- catalogue --------------------------------------------------------
    def test_catalogue_has_rooms_and_limits(self):
        body, status = roommate_api.handle_get("/api/games/roommate/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(body["max_agents"], 6)
        self.assertEqual(body["min_agents"], 2)
        self.assertGreaterEqual(len(body["rooms"]), 8)
        # The floor plan always has a kitchen and a balcony; the player can
        # rely on these ids to render the SVG.
        room_ids = {r["id"] for r in body["rooms"]}
        self.assertIn("kitchen", room_ids)
        self.assertIn("balcony", room_ids)

    # -- session start ----------------------------------------------------
    def test_start_session_validates_min_agents(self):
        with self.assertRaises(ValueError):
            roommate_api.start_session(city="wuzhen", agent_ids=[1])

    def test_start_session_validates_max_agents(self):
        with self.assertRaises(ValueError):
            roommate_api.start_session(city="wuzhen", agent_ids=[1, 2, 3, 1, 2, 3, 3])

    def test_start_session_returns_residents_and_clock(self):
        s = roommate_api.start_session(
            city="wuzhen",
            agent_ids=[1, 2, 3],
            vibe="三个朋友合租",
            reaction_fn=lambda p: _reply(),
        )
        self.assertEqual(len(s["residents"]), 3)
        names = [r["name"] for r in s["residents"]]
        self.assertEqual(names, ["闫然", "林佳", "蒋颂"])
        # First picked is the eldest resident by id order in our seed data;
        # they get the master bedroom, the rest get the second bedroom.
        self.assertEqual(s["residents"][0]["bedroom"], "master")
        self.assertEqual(s["residents"][1]["bedroom"], "second")
        self.assertTrue(s["virtual_clock"].endswith(":00"))
        self.assertEqual(s["tick_index"], 0)
        self.assertFalse(s["finished"])

    # -- tick advances state ---------------------------------------------
    def test_tick_increments_clock_and_index(self):
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2, 3], reaction_fn=lambda p: _reply(),
        )
        after = roommate_api.tick(s["id"], steps=2)
        self.assertEqual(after["tick_index"], 2)
        # 2 ticks * 5 minutes = 10 minutes past 08:00 -> 08:10.
        self.assertEqual(after["virtual_clock"], "08:10")

    def test_tick_at_deadline_finishes_session(self):
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2, 3],
            tick_minutes=5, max_hours=1,
            reaction_fn=lambda p: _reply(),
        )
        # 1 hour = 60 min = 12 ticks of 5 minutes. The session opens at
        # 08:00 and the deadline is 09:00; one tick call caps at
        # ``MAX_TICKS_PER_REQUEST``, so we walk in two batches.
        after = roommate_api.tick(s["id"], steps=6)
        after = roommate_api.tick(s["id"], steps=6)
        self.assertFalse(after["running"])
        self.assertTrue(after["finished"])
        # A second tick call after finish is a no-op.
        after2 = roommate_api.tick(s["id"], steps=1)
        self.assertEqual(after2["tick_index"], after["tick_index"])

    def test_idle_ticks_cost_no_model_calls(self):
        """Two residents who are always in different rooms never share a
        room, so no interaction fires and no model call is made — only the
        ``mood_decay`` and ``relationship_decay`` housekeeping runs."""
        calls = {"n": 0}

        def reaction_fn(prompt: str) -> str:
            calls["n"] += 1
            return _reply()

        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2],
            reaction_fn=reaction_fn,
            rng=random.Random(0),
        )
        sess = roommate_api._require(s["id"])
        # "看窗外" is a private activity, and the room follows the activity:
        # each resident ends the tick in their own bedroom, so the two never
        # share a room and an interaction is impossible rather than unlikely.
        # A shared-room activity would not do — "看书" and "练琴" both map to
        # the study, which parked the two residents together and left the
        # call count to an 8% coin flip (both busy → prob 0.55 x 0.15).
        with mock.patch(
            "gaworld.apps.roommate_api._activity_for_hour",
            return_value="看窗外",
        ):
            roommate_api.tick(s["id"], steps=2)
        self.assertNotEqual(
            sess.residents[0].room,
            sess.residents[1].room,
            "the two residents must stay in different rooms",
        )
        self.assertEqual(calls["n"], 0, "no interactions => zero LLM calls")

    def test_interaction_calls_model_and_updates_state(self):
        calls = {"n": 0}

        def reaction_fn(prompt: str) -> str:
            calls["n"] += 1
            return _reply(mood_a=0.2, mood_b=-0.1, rel=3.0)

        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2, 3], reaction_fn=reaction_fn,
            rng=random.Random(0),
        )
        sess = roommate_api._require(s["id"])
        # Force everyone into the kitchen with non-solo activities so the
        # interaction probability is high.
        for resident in sess.residents:
            resident.room = "kitchen"
            resident.activity = "吃午餐"
        # Skip the per-resident activity / room shuffle so the test
        # exercises ``_co_present_pairs`` + the reaction call directly.
        with mock.patch(
            "gaworld.apps.roommate_api._step_resident", return_value=None
        ):
            after = roommate_api.tick(s["id"], steps=1)
        # 3-person kitchen => 3 pairs, each can fire.
        self.assertGreaterEqual(calls["n"], 1)
        self.assertLessEqual(calls["n"], 3)
        self.assertGreaterEqual(len(after["events"]), 1)
        interact = next((e for e in after["events"] if e["kind"] == "interact"), None)
        self.assertIsNotNone(interact)
        self.assertIn("嗨", interact["dialogue"])
        moods = {r["agent_id"]: r["mood"] for r in after["residents"]}
        self.assertNotEqual(moods[1], 0)

    def test_relationship_matrix_is_symmetric(self):
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2, 3],
            reaction_fn=lambda p: _reply(rel=5.0),
        )
        sess = roommate_api._require(s["id"])
        for resident in sess.residents:
            resident.room = "kitchen"
            resident.activity = "吃午餐"
        with mock.patch(
            "gaworld.apps.roommate_api._step_resident", return_value=None
        ):
            after = roommate_api.tick(s["id"], steps=2)
        rels = after["relationships"]
        for a_id, pairs in rels.items():
            for b_id, value in pairs.items():
                mirror = rels.get(b_id, {}).get(a_id)
                self.assertEqual(value, mirror, "relationship scores must mirror")

    def test_relationship_record_has_three_dimensions_and_stage(self):
        # New shape: every pair has affinity / trust / closeness + a
        # derived ``stage`` label, not a bare scalar.
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], reaction_fn=lambda p: _reply(),
        )
        sess = roommate_api._require(s["id"])
        for r in sess.residents:
            r.room = "kitchen"
            r.activity = "吃午餐"
        with mock.patch("gaworld.apps.roommate_api._step_resident", return_value=None):
            after = roommate_api.tick(s["id"], steps=4)
        # Walk the matrix and ensure every cell is the new shape.
        rels = after["relationships"]
        for a_id, pairs in rels.items():
            for b_id, rec in pairs.items():
                if a_id == b_id:
                    continue
                self.assertIsInstance(rec, dict)
                self.assertIn("affinity", rec)
                self.assertIn("trust", rec)
                self.assertIn("closeness", rec)
                self.assertIn("stage", rec)
                self.assertIn(rec["stage"], roommate_api.REL_STAGES)
                # The legacy scalar compatibility stays — ``rec`` is
                # always reachable, never a bare float.
                self.assertIsInstance(rec["affinity"], (int, float))

    def test_relationship_stage_advances_on_positive_deltas(self):
        # Repeated positive deltas move two residents from "陌生人" up
        # the stage ladder. Use the synchronous ``_trigger_interaction``
        # path so the test does not race the worker pool — by the time
        # the function returns the event and the 3-dim relationship
        # record are both written.
        def reaction_fn(prompt: str) -> str:
            return json.dumps({
                "lines": [{"who": "a", "text": "hi"}, {"who": "b", "text": "hi"}],
                "thought_a": "ok", "thought_b": "ok",
                "mood_delta_a": 0.0, "mood_delta_b": 0.0,
                "rel_deltas": {"affinity": 12.0, "trust": 6.0, "closeness": 4.0},
            })
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], reaction_fn=reaction_fn,
        )
        sess = roommate_api._require(s["id"])
        a, b = sess.residents[0], sess.residents[1]
        for _ in range(4):
            roommate_api._trigger_interaction(
                sess, a, b, "kitchen", reaction_fn=reaction_fn,
            )
        rec = sess.relationships[a.agent_id][b.agent_id]
        # 4 interactions × (12, 6, 4) = (48, 24, 16). The heuristic
        # crosses the "朋友" boundary (>=25 affinity + 15 trust) at
        # the second interaction; by the fourth it is firmly there.
        self.assertGreaterEqual(rec["affinity"], 25)
        self.assertIn(rec["stage"], {"朋友", "好友", "亲密", "恋人"})

    def test_relationship_stage_can_drop_to_hostile(self):
        def reaction_fn(prompt: str) -> str:
            return json.dumps({
                "lines": [{"who": "a", "text": "x"}, {"who": "b", "text": "x"}],
                "thought_a": "", "thought_b": "",
                "mood_delta_a": 0.0, "mood_delta_b": 0.0,
                "rel_deltas": {"affinity": -8.0, "trust": -3.0, "closeness": -2.0},
            })
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], reaction_fn=reaction_fn,
        )
        sess = roommate_api._require(s["id"])
        a, b = sess.residents[0], sess.residents[1]
        for _ in range(6):
            roommate_api._trigger_interaction(
                sess, a, b, "kitchen", reaction_fn=reaction_fn,
            )
        rec = sess.relationships[a.agent_id][b.agent_id]
        # Six × (–8, –3, –2) = (–48, –18, –12) — firmly in 敌对.
        self.assertEqual(rec["stage"], "敌对")

    def test_parse_interaction_accepts_legacy_rel_delta(self):
        # Old models / fixtures return a single ``rel_delta`` scalar;
        # the parser must fold that into the new 3-dim shape so
        # nothing silently breaks.
        parsed = roommate_api._parse_interaction(
            json.dumps({"mood_delta_a": 0.1, "rel_delta": 2.0}),
            default_room="kitchen",
        )
        self.assertEqual(parsed["rel_deltas"]["affinity"], 2.0)
        self.assertEqual(parsed["rel_deltas"]["trust"], 0.0)
        self.assertEqual(parsed["rel_deltas"]["closeness"], 0.0)
        # Backwards-compat scalar still surfaces for older consumers.
        self.assertEqual(parsed["rel_delta"], 2.0)

    def test_parse_interaction_clamps_each_dim(self):
        # A model that returns trust=99 (should be -10..10) is clamped
        # on the per-dim range, not propagated.
        parsed = roommate_api._parse_interaction(
            json.dumps({
                "rel_deltas": {"affinity": 99, "trust": 99, "closeness": -99}
            }),
            default_room="living",
        )
        self.assertEqual(parsed["rel_deltas"]["affinity"], 15.0)
        self.assertEqual(parsed["rel_deltas"]["trust"], 10.0)
        self.assertEqual(parsed["rel_deltas"]["closeness"], -10.0)

    # -- bedroom assignment (bug 1) -------------------------------------
    def test_bedrooms_assign_unique_rooms_to_each_resident(self):
        # The wuzhen roster has 3 personas; the back-end assigns each
        # to a different bedroom, capped at the SLEEP_ROOMS tuple size.
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2, 3])
        bedrooms = [r["bedroom"] for r in s["residents"]]
        self.assertEqual(len(set(bedrooms)), 3,
                         "every resident should have a unique bedroom")

    def test_assign_bedrooms_handles_overflow_by_reusing_last_slot(self):
        # With only 3 personas in the wuzhen roster we cannot directly
        # check the 6-resident overflow, but the back-end helper is
        # exposed: passing more residents than ``SLEEP_ROOMS`` reuses
        # the last slot (the apartment physically only has 5 rooms).
        # The 5-room ceiling is what this test pins.
        residents = [roommate_api.Resident(agent_id=i, name=f"#{i}", age=30, gender="",
                                           job="", profile_md="") for i in range(7)]
        roommate_api._assign_bedrooms(residents)
        # First five all unique.
        self.assertEqual(len({r.bedroom for r in residents[:5]}), 5)
        # The 6th and 7th share the last bedroom.
        self.assertEqual(residents[5].bedroom, residents[6].bedroom)

    # -- time-of-day mood nudge (bug 3) ---------------------------------
    def test_mood_nudge_for_activity_changes_mood(self):
        # Eating dinner nudges mood up; a string of "发呆" ticks
        # brings it down. The session is set up so the call goes
        # through ``_mood_nudge_for_activity`` directly — bypassing
        # ``_step_resident`` so the activity does not get re-picked
        # by the hour-of-day pool.
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], rng=random.Random(0),
        )
        sess = roommate_api._require(s["id"])
        target = sess.residents[0]
        # Reset mood so the test only measures the nudge.
        target.mood = 0.0
        # Dinner (+0.10) plus co-presence bonus (~+0.015): two
        # consecutive ticks land above zero.
        roommate_api._mood_nudge_for_activity(
            target, "吃晚餐", is_night=False, session=sess,
        )
        roommate_api._mood_nudge_for_activity(
            target, "吃晚餐", is_night=False, session=sess,
        )
        self.assertGreater(target.mood, 0.0,
                            "晚饭+co-presence should lift mood")
        # A long stretch of 发呆 (-0.04 each) should drag the bar down
        # past the prior level.
        baseline = target.mood
        for _ in range(15):
            roommate_api._mood_nudge_for_activity(
                target, "发呆", is_night=False, session=sess,
            )
        self.assertLess(target.mood, baseline,
                         "a streak of 发呆 should drag mood below its prior level")

    def test_mood_decay_is_gentle_after_redesign(self):
        # The original 0.05/tick decay was strong enough that one good
        # interaction could not move the bar visibly. The new 0.02 is
        # still a pull-to-zero so neighbours do not freeze at +1, but
        # the rate is low enough that activity-driven nudges dominate.
        self.assertEqual(roommate_api.MOOD_DECAY_PER_TICK, 0.02)

    # -- time-aware prompt (bug 2) ---------------------------------------
    def test_interact_prompt_includes_clock_and_day_phase(self):
        # A session at 22:30 should produce a prompt that says "夜晚"
        # and the formatted clock — so the LLM knows it is late at
        # night and does not write "good morning".
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        sess = roommate_api._require(s["id"])
        sess.virtual_clock_minutes = 22 * 60 + 30  # 22:30
        a, b = sess.residents[0], sess.residents[1]
        prompt = roommate_api._interact_prompt(a, b, "living", "", sess)
        self.assertIn("22:30", prompt)
        self.assertIn("夜晚", prompt)
        # Hard rule: the prompt should explicitly forbid cross-time-of-
        # day content so a 22:30 prompt never yields a "good morning"
        # reply.
        self.assertIn("早上好", prompt)
        # 6 am is morning — the opposite phase should be elsewhere.
        sess.virtual_clock_minutes = 6 * 60 + 30
        prompt2 = roommate_api._interact_prompt(a, b, "kitchen", "", sess)
        self.assertIn("06:30", prompt2)
        self.assertIn("清晨", prompt2)

    # -- parsing ----------------------------------------------------------
    def test_parse_interaction_handles_missing_lines(self):
        # A model reply that is missing some fields must not crash.
        parsed = roommate_api._parse_interaction(
            json.dumps({"thought_a": "ok", "thought_b": "ok"}), default_room="living"
        )
        self.assertEqual(parsed["lines"], [])
        self.assertEqual(parsed["thought_a"], "ok")
        self.assertEqual(parsed["room"], "living")
        self.assertEqual(parsed["mood_delta_a"], 0.0)
        self.assertEqual(parsed["rel_delta"], 0.0)

    def test_parse_interaction_clamps_out_of_range_numbers(self):
        # A model that returns mood_delta = 99 (should be -1..1) and
        # rel_delta = 999 (should be -15..15) is clamped, not propagated.
        parsed = roommate_api._parse_interaction(
            json.dumps({"mood_delta_a": 99, "rel_delta": 999}), default_room="kitchen"
        )
        self.assertEqual(parsed["mood_delta_a"], 1.0)
        self.assertEqual(parsed["rel_delta"], 15.0)

    # -- HTTP delegation --------------------------------------------------
    def test_handle_get_sessions_lists_open_ones(self):
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], reaction_fn=lambda p: _reply(),
        )
        body, status = roommate_api.handle_get("/api/games/roommate/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["sessions"]), 1)
        self.assertEqual(body["sessions"][0]["id"], s["id"])

    def test_handle_get_session_404_for_unknown(self):
        _body, status = roommate_api.handle_get("/api/games/roommate/sessions/nope")
        self.assertEqual(status, 404)

    def test_handle_post_start_validates(self):
        body, status = roommate_api.handle_post(
            "/api/games/roommate/start",
            {"city": "wuzhen", "agent_ids": [1]},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_handle_post_tick_roundtrip(self):
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2, 3], reaction_fn=lambda p: _reply(),
        )
        body, status = roommate_api.handle_post(
            "/api/games/roommate/tick",
            {"session_id": s["id"], "steps": 1},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["tick_index"], 1)

    def test_handle_post_tick_404_for_unknown_session(self):
        _body, status = roommate_api.handle_post(
            "/api/games/roommate/tick", {"session_id": "nope", "steps": 1},
        )
        self.assertEqual(status, 404)

    def test_handle_post_end_marks_finished(self):
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2, 3], reaction_fn=lambda p: _reply(),
        )
        body, status = roommate_api.handle_post(
            "/api/games/roommate/end", {"session_id": s["id"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["finished"])
        self.assertFalse(body["running"])

    def test_games_api_routes_roommate_through(self):
        # The games_api dispatcher should hand off /api/games/roommate/*.
        body, status = games_api.handle_get("/api/games/roommate/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("rooms", body)

    def test_dashboard_openapi_lists_roommate_endpoints(self):
        from gaworld.apps import openapi
        paths = openapi.spec().get("paths", {})
        self.assertIn("/api/games/roommate/catalogue", paths)
        self.assertIn("/api/games/roommate/start", paths)
        self.assertIn("/api/games/roommate/tick", paths)
        self.assertIn("/api/games/roommate/end", paths)
        self.assertIn("/api/games/roommate/sessions", paths)
        self.assertIn("/api/games/roommate/sessions/{session_id}/direct", paths)

    # -- turns (feature 3) -------------------------------------------------
    def test_interaction_event_has_ordered_turns(self):
        # The model now returns a turn list; the Event must keep it in
        # order so the front-end can cycle the speech bubble through it.
        # We drive ``_trigger_interaction`` directly (sync path) to
        # avoid the worker-pool dance — that's covered separately by
        # ``test_interaction_calls_model_and_updates_state``.
        def reaction_fn(prompt: str) -> str:
            return json.dumps({
                "lines": [
                    {"who": "闫然", "text": "早啊"},
                    {"who": "王彬", "text": "早"},
                    {"who": "闫然", "text": "今天吃啥"},
                ],
                "thought_a": "累", "thought_b": "嗯",
                "mood_delta_a": 0.05, "mood_delta_b": 0.05, "rel_delta": 1.5,
            })
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], reaction_fn=reaction_fn,
            rng=random.Random(0),
        )
        sess = roommate_api._require(s["id"])
        roommate_api._trigger_interaction(
            sess, sess.residents[0], sess.residents[1], "kitchen",
            reaction_fn=reaction_fn,
        )
        after = roommate_api.get_session(s["id"])
        interact = next((e for e in after["events"] if e["kind"] == "interact"), None)
        self.assertIsNotNone(interact)
        # Order matters — the front-end animates them in this sequence.
        self.assertEqual(
            [t["who"] for t in interact["turns"]],
            ["闫然", "王彬", "闫然"],
        )
        self.assertEqual(interact["turns"][2]["text"], "今天吃啥")
        # Backwards-compat: ``dialogue`` is still a packed string.
        self.assertIn("闫然:早啊", interact["dialogue"])
        # Sanity: the line that just spoke (3rd turn) reflects who said it.
        self.assertEqual(interact["turns"][2]["who"], "闫然")

    # -- direct_resident (feature 4) --------------------------------------
    def test_direct_resident_moves_them_and_appends_event(self):
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        before = roommate_api.get_session(s["id"])
        # Person 1 starts in living; ask them to do 午睡 in the master bedroom.
        target_agent = before["residents"][0]["agent_id"]
        target_bedroom = before["residents"][0]["bedroom"]
        after = roommate_api.direct_resident(
            s["id"],
            agent_id=target_agent,
            activity="午睡",
        )
        self.assertIsNotNone(after)
        moved = next((r for r in after["residents"] if r["agent_id"] == target_agent), None)
        self.assertEqual(moved["activity"], "午睡")
        self.assertEqual(moved["room"], target_bedroom)
        # The event tail must include a move (room change) followed by a
        # direct event with the speaker's one-liner.
        kinds = [e["kind"] for e in after["events"][-2:]]
        self.assertEqual(kinds, ["move", "direct"])
        direct = after["events"][-1]
        self.assertEqual(direct["kind"], "direct")
        self.assertEqual(direct["actor_ids"], [target_agent])
        # Without an injected reaction_fn, the bubble falls back to a
        # deterministic note-based line.
        self.assertTrue(direct["turns"])
        self.assertEqual(direct["turns"][0]["who"], moved["name"])
        self.assertIn(moved["name"], direct["turns"][0]["text"])

    def test_direct_resident_with_injected_reaction(self):
        def reaction_fn(prompt: str) -> str:
            return json.dumps({"say": "好嘞,这就过去", "think": "被叫去干活有点烦"})
        s = roommate_api.start_session(
            city="wuzhen", agent_ids=[1, 2], reaction_fn=reaction_fn,
        )
        target = s["residents"][0]["agent_id"]
        after = roommate_api.direct_resident(
            s["id"], agent_id=target, activity="做早餐", note="让小明做饭"
        )
        direct = after["events"][-1]
        self.assertEqual(direct["turns"][0]["text"], "好嘞,这就过去")
        self.assertEqual(direct["thought"].split(":", 1)[1].strip(), "被叫去干活有点烦")
        self.assertEqual(direct["note"], "让小明做饭")

    def test_direct_resident_rejects_unknown_agent(self):
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        with self.assertRaises(ValueError) as cm:
            roommate_api.direct_resident(s["id"], agent_id=9999, activity="做早餐")
        self.assertIn("9999", str(cm.exception))

    def test_direct_resident_rejects_bad_activity(self):
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        with self.assertRaises(ValueError):
            roommate_api.direct_resident(s["id"], agent_id=1, activity="开飞机")

    def test_direct_resident_rejects_bad_room(self):
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        with self.assertRaises(ValueError) as cm:
            roommate_api.direct_resident(s["id"], agent_id=1, activity="做早餐", room="木屋")
        self.assertIn("木屋", str(cm.exception))

    def test_direct_resident_rejects_after_end(self):
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        roommate_api.end_session(s["id"])
        with self.assertRaises(ValueError):
            roommate_api.direct_resident(s["id"], agent_id=1, activity="做早餐")

    def test_direct_resident_keeps_current_room_for_bed_in_bedroom(self):
        # Clicking "午睡" with no explicit room must keep the resident in
        # their bedroom (we have no separate bed_room override). The
        # default activity → room mapping drives the fallback.
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        after = roommate_api.direct_resident(
            s["id"], agent_id=s["residents"][0]["agent_id"], activity="午睡",
        )
        moved = next((r for r in after["residents"] if r["agent_id"] == s["residents"][0]["agent_id"]), None)
        # ACTIVITY_ROOM maps 午睡 → master, but the resident's bedroom
        # might be "second" — we don't override room based on activity,
        # we just trust whatever the activity's natural room is.
        self.assertIn(moved["room"], {"master", "second"})
        # Direct event must mention the activity name.
        direct = after["events"][-1]
        self.assertIn("午睡", direct["note"])

    def test_handle_post_direct_routes_through(self):
        # The HTTP layer should hand /sessions/{id}/direct to the
        # roommate backend and return the session dict (200) or 400/404.
        s = roommate_api.start_session(city="wuzhen", agent_ids=[1, 2])
        body, status = roommate_api.handle_post(
            f"/api/games/roommate/sessions/{s['id']}/direct",
            {"agent_id": s["residents"][0]["agent_id"], "activity": "做早餐"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["events"][-1]["kind"], "direct")
        # Bad activity surfaces as a 400 from the HTTP layer.
        body, status = roommate_api.handle_post(
            f"/api/games/roommate/sessions/{s['id']}/direct",
            {"agent_id": s["residents"][0]["agent_id"], "activity": "开飞机"},
        )
        self.assertEqual(status, 400)
        self.assertIn("开飞机", body["error"])
        # Unknown session id surfaces as 404.
        body, status = roommate_api.handle_post(
            "/api/games/roommate/sessions/nope/direct",
            {"agent_id": 1, "activity": "做早餐"},
        )
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
