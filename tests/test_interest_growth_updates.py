import unittest

from gaworld.interests import growth_focus, update_growth_from_episode


def _profile():
    return {
        "agent_id": 3,
        "source_hash": "abc",
        "items": [
            {
                "name": "阅读",
                "kind": "hobby",
                "category": "阅读",
                "motivation": "放松",
                "level": 0.2,
                "priority": 0.9,
                "weekly_target_minutes": 120,
                "preferred_time_blocks": ["evening"],
                "activity_templates": ["阅读", "看书"],
                "career_link": False,
                "sociality": 0.1,
                "last_practiced_day": 0,
                "total_minutes": 0,
                "streak_days": 0,
            },
            {
                "name": "编程技能",
                "kind": "skill",
                "category": "技术",
                "motivation": "职业成长",
                "level": 0.1,
                "priority": 0.8,
                "weekly_target_minutes": 240,
                "preferred_time_blocks": ["evening"],
                "activity_templates": ["练习编程", "做小项目"],
                "career_link": True,
                "sociality": 0.2,
                "last_practiced_day": 0,
                "total_minutes": 0,
                "streak_days": 0,
            },
        ],
    }


class TestInterestGrowthUpdates(unittest.TestCase):
    def test_matching_activity_accumulates_minutes_and_level(self):
        profile = _profile()
        updated, progress = update_growth_from_episode(
            profile,
            {
                "day": 1,
                "final_activity": "晚上阅读",
                "action": "阅读专业书并做笔记",
                "reflection": "感觉有收获",
            },
            step_minutes=45,
        )

        reading = updated["items"][0]
        self.assertEqual(["阅读"], progress["matches"])
        self.assertEqual(45, progress["minutes"])
        self.assertEqual(45, reading["total_minutes"])
        self.assertGreater(reading["level"], 0.2)
        self.assertEqual(1, reading["streak_days"])

    def test_non_matching_activity_does_not_change_progress(self):
        profile = _profile()
        updated, progress = update_growth_from_episode(
            profile,
            {
                "day": 1,
                "final_activity": "午饭",
                "action": "吃饭",
                "reflection": "普通一餐",
            },
            step_minutes=30,
        )

        self.assertEqual([], progress["matches"])
        self.assertEqual(0, updated["items"][0]["total_minutes"])
        self.assertEqual(0.2, updated["items"][0]["level"])

    def test_high_priority_items_surface_as_growth_focus(self):
        focus = growth_focus(_profile(), limit=2)

        self.assertEqual(["阅读", "编程技能"], focus)


if __name__ == "__main__":
    unittest.main()
