import os
import tempfile
import unittest

from gaworld.twin import binding
from gaworld.twin.backend import TwinBackend
from gaworld.world.city_map import BASE_LAT, BASE_LNG, LAT_PER_KM, LNG_PER_KM


def _fake_map():
    return {
        "nodes": {
            "home": {"id": "home", "name": "home", "x_km": 0.0, "y_km": 0.0},
            "office": {"id": "office", "name": "office", "x_km": 5.0, "y_km": 0.0},
        }
    }


def _lnglat_at_km(x_km, y_km):
    return (BASE_LNG + x_km * LNG_PER_KM, BASE_LAT + y_km * LAT_PER_KM)


def _raw(report_id, x_km=0.0, ts=1000, action_tag="commute", note=""):
    lng, lat = _lnglat_at_km(x_km, 0.0)
    return {
        "report_id": report_id,
        "ts": ts,
        "tz_offset": 480,
        "loc": {"lat": lat, "lng": lng, "acc_m": 10, "source": "gps"},
        "action_tag": action_tag,
        "note": note,
    }


class TestTwinBackend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "twin")
        self.bindings = os.path.join(self._tmp.name, "twin_bindings.json")
        self.backend = TwinBackend(
            root=self.root,
            bindings_path=self.bindings,
            city_map=_fake_map(),
            snapshot_ttl_minutes=30,
            max_snap_km=3.0,
            diary_dir=os.path.join(self._tmp.name, "diaries"),
            state_dir=os.path.join(self._tmp.name, "state"),
            memory_dir=os.path.join(self._tmp.name, "memory"),
            city_places=[],
            roster_path=self._write_roster(),
            simulated_ids=(1, 2, 7),
        )

        self.code = binding.issue_code(agent_id=7, label="cw", path=self.bindings)
        self.token = binding.redeem_code(self.code, path=self.bindings)

    def _write_roster(self):
        path = os.path.join(self._tmp.name, "agents.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("id,name,age,job\n")
            handle.write("1,甲,30,工程师\n2,乙,41,教师\n3,丙,25,学生\n7,cw,33,研究员\n8,丁,50,司机\n")
        return path

    def tearDown(self):
        self._tmp.cleanup()

    def test_authenticate_exchanges_a_code_for_a_token(self):
        result = self.backend.authenticate(self.code)
        self.assertTrue(result["ok"])
        self.assertTrue(result["token"])
        self.assertEqual(result["label"], "cw")

    def test_authenticate_rejects_a_bad_code(self):
        result = self.backend.authenticate("nope")
        self.assertFalse(result["ok"])

    def test_submit_enriches_the_report_with_geo_fields(self):
        result = self.backend.submit(self.token, [_raw("a", x_km=4.8)])
        self.assertTrue(result["ok"])
        self.assertEqual(result["accepted"], 1)
        stored = self.backend.snapshot(self.token)["report"]
        self.assertEqual(stored["node_id"], "office")
        self.assertFalse(stored["out_of_map"])
        self.assertIn("grid", stored)

    def test_submit_rejects_an_invalid_token(self):
        result = self.backend.submit("nope", [_raw("a")])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 401)

    def test_a_client_cannot_write_another_agents_data(self):
        # The single most important test in this plan. agent_id must come from
        # the token, so a body claiming a different agent changes nothing.
        other_code = binding.issue_code(agent_id=8, label="other", path=self.bindings)
        other_token = binding.redeem_code(other_code, path=self.bindings)
        forged = _raw("a")
        forged["agent_id"] = 7
        self.backend.submit(other_token, [forged])

        # Agent 7 (this test's token) must still have nothing stored.
        self.assertIsNone(self.backend.snapshot(self.token)["report"])
        # And the write must have landed on agent 8 instead.
        self.assertIsNotNone(self.backend.snapshot(other_token)["report"])

    def test_out_of_map_report_keeps_the_real_coordinate(self):
        # out_of_map means "matched no map node", NOT "position unknown".
        # The true fix must survive intact for calibration and for the trail.
        lng, lat = _lnglat_at_km(40.0, 0.0)
        result = self.backend.submit(self.token, [_raw("a", x_km=40.0)])
        self.assertTrue(result["ok"])
        stored = self.backend.snapshot(self.token)["report"]
        self.assertTrue(stored["out_of_map"])
        self.assertIsNone(stored["node_id"])
        self.assertAlmostEqual(stored["loc"]["lat"], lat, places=4)
        self.assertAlmostEqual(stored["loc"]["lng"], lng, places=4)
        self.assertIsNotNone(stored["grid"])

    def test_out_of_map_report_is_given_an_offline_place_name(self):
        # Beijing: far outside the fake map, but nameable without a network call.
        beijing = {
            "report_id": "bj", "ts": 1000, "tz_offset": 480,
            "loc": {"lat": 39.90, "lng": 116.41, "acc_m": 10, "source": "gps"},
            "action_tag": "rest", "note": "",
        }
        self.backend.submit(self.token, [beijing])
        stored = self.backend.snapshot(self.token)["report"]
        self.assertTrue(stored["out_of_map"])
        self.assertEqual(stored["place"], "北京")

    def test_trail_includes_out_of_map_points(self):
        # The phone must be able to draw where you actually were, even when
        # that is nowhere near the simulated city.
        self.backend.submit(self.token, [_raw("a", x_km=40.0)])
        points = self.backend.trail(self.token)["points"]
        self.assertEqual(len(points), 1)
        self.assertTrue(points[0]["out_of_map"])
        self.assertIsNotNone(points[0]["loc"])

    def test_snapshot_reports_freshness(self):
        self.backend.submit(self.token, [_raw("a", ts=1000)])
        fresh = self.backend.snapshot(self.token, now_ts=1000 + 60)
        self.assertTrue(fresh["fresh"])
        stale = self.backend.snapshot(self.token, now_ts=1000 + 60 * 60)
        self.assertFalse(stale["fresh"])

    def test_profile_returns_an_svg_avatar(self):
        profile = self.backend.profile(self.token)
        self.assertTrue(profile["ok"])
        self.assertEqual(profile["agent_id"], 7)
        self.assertIn("<svg", profile["avatar_svg"])

    def test_trail_returns_points_within_the_window(self):
        self.backend.submit(
            self.token,
            [_raw("a", x_km=0.0, ts=1000), _raw("b", x_km=5.0, ts=2000)],
        )
        trail = self.backend.trail(self.token, since_ts=1500)
        self.assertEqual(len(trail["points"]), 1)
        self.assertEqual(trail["points"][0]["report_id"], "b")

    def test_trail_points_carry_coordinates_and_tag(self):
        self.backend.submit(self.token, [_raw("a", x_km=5.0, action_tag="work")])
        point = self.backend.trail(self.token)["points"][0]
        self.assertIn("grid", point)
        self.assertEqual(point["action_tag"], "work")
        self.assertEqual(point["node_id"], "office")

    def test_trail_keeps_real_positions_outside_simulation_map(self):
        self.backend.submit(self.token, [_raw("outside", x_km=40.0)])
        point = self.backend.trail(self.token)["points"][0]
        self.assertTrue(point["has_location"])
        self.assertTrue(point["out_of_map"])
        self.assertIsNone(point["node_id"])

    def test_activity_only_report_is_not_a_trail_position(self):
        report = _raw("activity-only")
        report["loc"] = {"lat": 0, "lng": 0, "source": "manual"}
        self.backend.submit(self.token, [report])
        point = self.backend.trail(self.token)["points"][0]
        self.assertFalse(point["has_location"])
        self.assertTrue(point["out_of_map"])
        self.assertEqual(len(self.backend.reports(self.token)["reports"]), 1)

    def test_amend_can_delete_the_callers_own_report(self):
        self.backend.submit(self.token, [_raw("a")])
        result = self.backend.amend(self.token, "a", "delete", amend_id="m1")
        self.assertTrue(result["ok"])
        self.assertEqual(self.backend.reports(self.token)["reports"], [])

    def test_amend_can_retag(self):
        self.backend.submit(self.token, [_raw("a", action_tag="work")])
        self.backend.amend(self.token, "a", "update",
                           patch={"action_tag": "meal"}, amend_id="m1")
        self.assertEqual(
            self.backend.reports(self.token)["reports"][0]["action_tag"], "meal"
        )

    def test_amend_rejects_an_unknown_target(self):
        result = self.backend.amend(self.token, "nope", "delete", amend_id="m1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 404)

    def test_amend_cannot_touch_another_agents_report(self):
        # Same class of bug as writing another agent's reports: the target
        # must be resolved within the token's own agent, never globally.
        other_code = binding.issue_code(agent_id=8, label="other", path=self.bindings)
        other_token = binding.redeem_code(other_code, path=self.bindings)
        self.backend.submit(other_token, [_raw("a")])

        result = self.backend.amend(self.token, "a", "delete", amend_id="m1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 404)
        # Agent 8's report must survive untouched.
        self.assertEqual(len(self.backend.reports(other_token)["reports"]), 1)

    def test_amend_rejects_an_unknown_op(self):
        self.backend.submit(self.token, [_raw("a")])
        result = self.backend.amend(self.token, "a", "obliterate", amend_id="m1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 400)

    def test_reports_are_newest_first(self):
        self.backend.submit(self.token, [_raw("a", ts=1000), _raw("b", ts=2000)])
        ids = [r["report_id"] for r in self.backend.reports(self.token)["reports"]]
        self.assertEqual(ids, ["b", "a"])

    def test_life_returns_empty_structures_when_nothing_exists(self):
        result = self.backend.life(self.token)
        self.assertTrue(result["ok"])
        self.assertEqual(result["diary"]["text"], "")
        self.assertEqual(result["state"], {})
        self.assertEqual(result["goals"]["life_goals"], [])

    def test_places_are_sorted_by_distance_from_a_point(self):
        places = self.backend.places(self.token)["places"]
        self.assertEqual([p["id"] for p in places], ["home", "office"])

    def test_places_can_be_filtered_by_name(self):
        places = self.backend.places(self.token, query="off")["places"]
        self.assertEqual([p["id"] for p in places], ["office"])

    def test_an_unbound_token_is_told_to_choose_rather_than_rejected(self):
        # 409, not 401: the phone should show a picker, not bounce the user
        # back to the invite-code screen.
        code = binding.issue_code(path=self.bindings)
        token = binding.redeem_code(code, path=self.bindings)
        result = self.backend.snapshot(token)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 409)

    def test_agents_lists_the_roster_with_simulated_and_taken_flags(self):
        code = binding.issue_code(path=self.bindings)
        token = binding.redeem_code(code, path=self.bindings)
        result = self.backend.agents(token)
        self.assertTrue(result["ok"])
        by_id = {a["id"]: a for a in result["agents"]}
        self.assertEqual(by_id[1]["name"], "甲")
        self.assertTrue(by_id[1]["simulated"])
        self.assertFalse(by_id[3]["simulated"])
        # Agent 7 is twinned by this test case's own token.
        self.assertTrue(by_id[7]["taken"])

    def test_agents_does_not_mark_your_own_agent_as_taken(self):
        result = self.backend.agents(self.token)
        by_id = {a["id"]: a for a in result["agents"]}
        self.assertFalse(by_id[7]["taken"])
        self.assertEqual(result["current"], 7)

    def test_bind_points_an_unbound_token_at_an_agent(self):
        code = binding.issue_code(path=self.bindings)
        token = binding.redeem_code(code, path=self.bindings)
        result = self.backend.bind(token, 3)
        self.assertTrue(result["ok"])
        self.assertFalse(result["simulated"])
        self.assertEqual(self.backend.snapshot(token)["agent_id"], 3)

    def test_bind_refuses_an_agent_another_token_already_twins(self):
        code = binding.issue_code(path=self.bindings)
        token = binding.redeem_code(code, path=self.bindings)
        result = self.backend.bind(token, 7)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 409)

    def test_bind_refuses_an_unknown_agent(self):
        result = self.backend.bind(self.token, 999)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 404)

    def test_rebinding_leaves_old_reports_with_the_old_agent(self):
        # The log is append-only, so switching agents cannot move history.
        self.backend.submit(self.token, [_raw("a")])
        self.backend.bind(self.token, 3)
        self.assertEqual(self.backend.reports(self.token)["reports"], [])
        self.backend.bind(self.token, 7)
        self.assertEqual(len(self.backend.reports(self.token)["reports"]), 1)

    def test_every_read_operation_rejects_an_invalid_token(self):
        for call in (self.backend.snapshot, self.backend.profile, self.backend.trail,
                     self.backend.life, self.backend.reports, self.backend.places):
            with self.subTest(call=call.__name__):
                result = call("nope")
                self.assertFalse(result["ok"])
                self.assertEqual(result["status"], 401)


if __name__ == "__main__":
    unittest.main()
