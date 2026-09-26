"""Domain tests for the home_environment module.

The procedural home generator is deterministic and side-effect-free, so it
gets its own suite — the plugin wiring is pinned separately in
``test_home_environment_plugin.py``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gaworld.world import home_environment as he


def _agent(agent_id=1, income=10000, home="H1"):
    return {
        "id": agent_id,
        "name": f"a{agent_id}",
        "age": 30,
        "monthly_income": income,
        "locations": {"home": home, "current": home},
        "marital_status": "single",
    }


class TestDesignHome(unittest.TestCase):
    def test_returns_full_schema(self):
        home = he.design_home(_agent(income=12000), seed=42)
        self.assertEqual(home["home_id"], "agent_1")
        self.assertEqual(home["home_node"], "H1")
        self.assertIn("vibe", home)
        self.assertIn("ambiance_quality", home)
        # Each room has name, size, furniture, ambiance_bias
        self.assertGreater(len(home["rooms"]), 0)
        for room in home["rooms"].values():
            self.assertIn("name", room)
            self.assertIn("furniture", room)
            self.assertGreater(len(room["furniture"]), 0)

    def test_deterministic_for_same_seed(self):
        a = he.design_home(_agent(agent_id=1), seed=42)
        b = he.design_home(_agent(agent_id=1), seed=42)
        # Rooms and furniture must match exactly.
        self.assertEqual(
            sorted(a["rooms"]),
            sorted(b["rooms"]),
        )
        for key in a["rooms"]:
            self.assertEqual(a["rooms"][key]["furniture"], b["rooms"][key]["furniture"])

    def test_income_tier_changes_rooms(self):
        # Very low income should not get a study or balcony by default.
        low = he.design_home(_agent(income=1500), seed=42)
        self.assertNotIn("study", low["rooms"])
        # Top tier includes a balcony (and possibly a second bedroom).
        rich = he.design_home(_agent(income=60000), seed=42)
        self.assertIn("balcony", rich["rooms"])

    def test_at_home_activities_covers_rooms(self):
        home = he.design_home(_agent(income=12000), seed=42)
        # Every room must carry a non-empty activity list — that's what the
        # observation side filters against.
        for key, room in home["rooms"].items():
            activities = home["at_home_activities"][key]
            self.assertGreater(len(activities), 0, f"room {key} ({room['name']}) has no activities")

    def test_default_ambiance_present(self):
        home = he.design_home(_agent(), seed=42)
        self.assertIn("ambient_state", home)
        for dim in he.AMBIANCE_DIMS:
            self.assertIn(dim, home["ambient_state"])


class TestPickRoomForActivity(unittest.TestCase):
    def test_known_activity_maps_to_correct_room(self):
        home = he.design_home(_agent(income=12000), seed=42)
        self.assertEqual(he.pick_room_for_activity(home, "做饭", "12:00")[0], "kitchen")
        self.assertEqual(he.pick_room_for_activity(home, "睡觉", "23:00")[0], "bedroom")

    def test_unknown_activity_falls_back_by_time(self):
        home = he.design_home(_agent(income=12000), seed=42)
        # Late evening unknown activity → bedroom.
        self.assertEqual(he.pick_room_for_activity(home, "休息", "23:00")[0], "bedroom")
        # Mid-morning → kitchen (breakfast default).
        self.assertEqual(he.pick_room_for_activity(home, "休息", "07:30")[0], "kitchen")
        # Afternoon → living room.
        self.assertEqual(he.pick_room_for_activity(home, "休息", "15:00")[0], "living_room")


class TestAmbianceEvolution(unittest.TestCase):
    def test_lighting_varies_by_hour(self):
        home = he.design_home(_agent(), seed=42)
        # 02:00 → 夜灯昏暗; 12:00 → 自然光; 22:00 → 台灯+落地灯
        he.update_ambiance(home, time_str="02:00", weather_state="clear", activity="")
        self.assertEqual(home["ambient_state"]["lighting"], "夜灯昏暗")
        he.update_ambiance(home, time_str="12:00", weather_state="clear", activity="")
        self.assertEqual(home["ambient_state"]["lighting"], "自然光")
        he.update_ambiance(home, time_str="22:00", weather_state="clear", activity="")
        self.assertEqual(home["ambient_state"]["lighting"], "台灯+落地灯")

    def test_rainy_weather_darkens_lighting(self):
        home = he.design_home(_agent(), seed=42)
        he.update_ambiance(home, time_str="12:00", weather_state="rain", activity="")
        self.assertIn("阴沉", home["ambient_state"]["lighting"])

    def test_cooking_pollutes_then_tidying_recovers(self):
        home = he.design_home(_agent(), seed=42)
        # Start clean.
        home["ambient_state"]["tidiness"] = "基本整洁"
        he.update_ambiance(home, time_str="18:00", weather_state="clear", activity="做饭")
        self.assertEqual(home["ambient_state"]["tidiness"], "有点乱")
        he.update_ambiance(home, time_str="18:30", weather_state="clear", activity="整理桌面")
        # Clean-up recovers one step, not all the way back (deliberate so the
        # signal of a busy kitchen lingers for one tick).
        self.assertEqual(home["ambient_state"]["tidiness"], "基本整洁")

    def test_sound_label_matches_activity(self):
        home = he.design_home(_agent(), seed=42)
        he.update_ambiance(home, time_str="19:00", weather_state="clear", activity="做饭")
        self.assertIn("厨房", home["ambient_state"]["sound"])


class TestObservation(unittest.TestCase):
    def test_returns_is_at_home_true_when_home_exists(self):
        home = he.design_home(_agent(), seed=42)
        obs = he.home_observation(_agent(), home, activity="看电视", time_str="20:00")
        self.assertTrue(obs["is_at_home"])
        self.assertEqual(obs["home_node"], "H1")
        self.assertEqual(obs["current_room"]["name"], "客厅")

    def test_returns_is_at_home_false_for_empty_home(self):
        obs = he.home_observation(_agent(), {}, activity="看电视", time_str="20:00")
        self.assertFalse(obs["is_at_home"])

    def test_prompt_lines_empty_when_not_at_home(self):
        self.assertEqual(he.home_prompt_lines({"is_at_home": False}), [])

    def test_prompt_lines_cover_room_and_ambiance(self):
        home = he.design_home(_agent(), seed=42)
        he.update_ambiance(home, time_str="12:00", weather_state="clear", activity="做饭")
        obs = he.home_observation(_agent(), home, activity="做饭", time_str="12:00")
        lines = he.home_prompt_lines(obs)
        # 1) room line, 2) ambiance line, 3) vibe line.
        self.assertEqual(len(lines), 3)
        self.assertTrue(any("厨房" in line for line in lines))
        self.assertTrue(any("氛围" in line for line in lines))
        self.assertTrue(any("气质" in line for line in lines))


class TestPersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = he.design_home(_agent(), seed=42)
            he.save_home(home["home_id"], home, tmp)
            loaded = he.load_home(home["home_id"], tmp)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["home_id"], home["home_id"])
            self.assertEqual(loaded["rooms"], home["rooms"])

    def test_load_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(he.load_home("agent_9999", tmp))

    def test_append_observation_creates_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            he.append_observation(
                tmp,
                agent_id=1,
                day=1,
                time_str="10:00",
                obs={"is_at_home": True, "home_node": "H1"},
            )
            path = Path(tmp) / "agent_1.jsonl"
            self.assertTrue(path.exists())
            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["day"], 1)
            self.assertEqual(row["home_node"], "H1")


class TestLLMPolish(unittest.TestCase):
    def test_polish_updates_furniture_and_vibe(self):
        home = he.design_home(_agent(income=12000), seed=42)
        with patch(
            "gaworld.llm.providers.call_llm",
            return_value=json.dumps(
                {
                    "living_room": {"furniture": ["Linen sofa", "Brass floor lamp"]},
                    "vibe": "warm minimal",
                },
                ensure_ascii=False,
            ),
        ):
            polished = he.polish_home_with_llm(
                dict(home),
                call_llm=lambda *a, **kw: json.dumps(
                    {
                        "living_room": {"furniture": ["Linen sofa", "Brass floor lamp"]},
                        "vibe": "warm minimal",
                    },
                    ensure_ascii=False,
                ),
                agent=_agent(),
            )
        self.assertEqual(polished["rooms"]["living_room"]["furniture"], ["Linen sofa", "Brass floor lamp"])
        self.assertEqual(polished["vibe"], "warm minimal")

    def test_polish_keeps_home_on_bad_response(self):
        home = he.design_home(_agent(), seed=42)
        original_vibe = home["vibe"]
        out = he.polish_home_with_llm(
            dict(home),
            call_llm=lambda *a, **kw: "this is not json",
            agent=_agent(),
        )
        self.assertEqual(out["vibe"], original_vibe)


if __name__ == "__main__":
    unittest.main()
