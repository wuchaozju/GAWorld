import json
import tempfile
import unittest

from gaworld.interests import (
    derive_growth_profile,
    load_growth_cache,
    save_growth_cache,
)


def _agent(**overrides):
    base = {
        "id": 7,
        "name": "测试居民",
        "age": 31,
        "job": "软件工程师，平时需要写代码和沟通需求。",
        "personality": "谨慎但有好奇心。",
        "daily_life": "晚上会阅读，也想恢复运动。",
        "values": "重视稳定和持续成长。",
    }
    base.update(overrides)
    return base


class TestInterestGrowthProfile(unittest.TestCase):
    def test_llm_json_is_parsed_and_normalized(self):
        payload = {
            "items": [
                {
                    "name": "跑步",
                    "kind": "hobby",
                    "category": "健康",
                    "motivation": "保持精力",
                    "level": 0.4,
                    "priority": 0.7,
                    "weekly_target_minutes": 180,
                    "preferred_time_blocks": ["morning"],
                    "activity_templates": ["跑步训练"],
                    "career_link": False,
                    "sociality": 0.2,
                },
                {
                    "name": "编程技能",
                    "kind": "skill",
                    "category": "技术",
                    "motivation": "提升职业机会",
                    "level": 0.3,
                    "priority": 0.8,
                    "weekly_target_minutes": 240,
                    "preferred_time_blocks": ["evening"],
                    "activity_templates": ["练习编程"],
                    "career_link": True,
                    "sociality": 0.3,
                },
            ],
            "notes": "适合稳定成长。",
        }

        profile = derive_growth_profile(_agent(), llm=lambda _: json.dumps(payload, ensure_ascii=False))

        self.assertEqual(7, profile.agent_id)
        self.assertEqual(["跑步", "编程技能"], [item.name for item in profile.items])
        self.assertEqual("skill", profile.items[1].kind)
        self.assertTrue(profile.items[1].career_link)
        self.assertTrue(profile.source_hash)

    def test_llm_failure_falls_back_to_hobby_and_skill(self):
        def failing_llm(_prompt):
            raise RuntimeError("boom")

        profile = derive_growth_profile(_agent(), llm=failing_llm)

        kinds = {item.kind for item in profile.items}
        self.assertIn("hobby", kinds)
        self.assertIn("skill", kinds)
        self.assertGreaterEqual(len(profile.items), 2)

    def test_cache_reused_until_profile_hash_changes(self):
        calls = {"count": 0}

        def llm(_prompt):
            calls["count"] += 1
            return json.dumps(
                {
                    "items": [
                        {"name": "阅读", "kind": "hobby", "activity_templates": ["阅读"]},
                        {"name": "编程技能", "kind": "skill", "activity_templates": ["练习编程"]},
                    ]
                },
                ensure_ascii=False,
            )

        cache = {}
        first = derive_growth_profile(_agent(), llm=llm, cache=cache)
        second = derive_growth_profile(_agent(), llm=llm, cache=cache)
        changed = derive_growth_profile(_agent(job="教师，关注课程设计。"), llm=llm, cache=cache)

        self.assertEqual(2, calls["count"])
        self.assertEqual(first.source_hash, second.source_hash)
        self.assertNotEqual(second.source_hash, changed.source_hash)

    def test_cache_roundtrip(self):
        profile = derive_growth_profile(_agent(), llm=lambda _: "{}")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = f"{tmpdir}/growth_profiles.json"
            save_growth_cache(path, {profile.agent_id: profile})
            loaded = load_growth_cache(path)
        self.assertIn(profile.agent_id, loaded)
        self.assertEqual(profile.items[0].name, loaded[profile.agent_id].items[0].name)


if __name__ == "__main__":
    unittest.main()
