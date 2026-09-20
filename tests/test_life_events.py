import os
import tempfile
import unittest

from gaworld.events import life as life_events


class TestLifeEvents(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = {
            "life_events": {
                "event_dir": os.path.join(self.tmpdir.name, "life_events"),
                "events_file": "events.json",
            }
        }

    def test_immediate_event_drains_once(self):
        event = life_events.add_life_event(
            {
                "template_key": "illness",
                "agent_ids": "4,5",
            },
            self.config,
        )

        self.assertEqual("pending", event["status"])
        self.assertEqual([4, 5], event["agent_ids"])

        due = life_events.drain_due_life_events(1, "09:00", self.config)
        self.assertEqual(1, len(due))
        self.assertEqual("consumed", due[0]["status"])
        self.assertEqual(1, due[0]["triggered_day"])
        self.assertEqual("09:00", due[0]["triggered_time"])

        self.assertEqual([], life_events.drain_due_life_events(1, "10:00", self.config))

    def test_scheduled_event_waits_until_time(self):
        life_events.add_life_event(
            {
                "title": "测试事件",
                "description": "等到下午才触发",
                "schedule_mode": "scheduled",
                "day": 2,
                "time": "15:30",
            },
            self.config,
        )

        self.assertEqual([], life_events.drain_due_life_events(2, "15:00", self.config))
        due = life_events.drain_due_life_events(2, "15:30", self.config)

        self.assertEqual(1, len(due))
        self.assertEqual("测试事件", due[0]["title"])

    def test_life_events_for_agent_empty_target_means_all_agents(self):
        all_event = {"title": "全体事件", "agent_ids": []}
        targeted = {"title": "定向事件", "agent_ids": [7]}
        picked = life_events.life_events_for_agent([all_event, targeted], 7)

        self.assertEqual(["全体事件", "定向事件"], [item["title"] for item in picked])
        self.assertEqual(["全体事件"], [item["title"] for item in life_events.life_events_for_agent([all_event, targeted], 8)])


if __name__ == "__main__":
    unittest.main()
