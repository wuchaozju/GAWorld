import os
import tempfile
import unittest

from gaworld.apps.distributed_comm_server import DistributedRelayBackend
from gaworld.distributed.comm import format_inbox_context


class TestDistributedComm(unittest.TestCase):
    def test_backend_send_and_poll(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "relay_state.json")
            backend = DistributedRelayBackend(state_path=state_path, max_messages=100)
            reg_a = backend.register_agents("demo", "node-a", [{"id": 1, "name": "A"}])
            reg_b = backend.register_agents("demo", "node-b", [{"id": 2, "name": "B"}])
            self.assertTrue(reg_a.get("ok"))
            self.assertTrue(reg_b.get("ok"))

            sent = backend.send_message(
                "demo",
                "node-a",
                {
                    "from_agent": 1,
                    "from_name": "A",
                    "to_agent": 2,
                    "kind": "agent_update",
                    "text": "今天压力有点高，但我会按计划行动。",
                    "day": 1,
                    "time": "10:00",
                    "activity": "工作",
                },
            )
            self.assertTrue(sent.get("ok"))
            msg = sent.get("message", {})
            self.assertEqual(msg.get("from_agent"), 1)
            self.assertEqual(msg.get("to_agent"), 2)

            first = backend.poll_messages("demo", recipient_ids=[2], since_map={"2": 0}, limit=10)
            self.assertTrue(first.get("ok"))
            self.assertEqual(len(first.get("messages", [])), 1)
            next_since = first.get("next_since", {})
            self.assertGreaterEqual(int(next_since.get("2", 0)), 1)

            second = backend.poll_messages("demo", recipient_ids=[2], since_map=next_since, limit=10)
            self.assertTrue(second.get("ok"))
            self.assertEqual(len(second.get("messages", [])), 0)

    def test_format_inbox_context(self):
        text = format_inbox_context(
            [
                {"from_agent": 7, "from_name": "Agent7", "text": "我刚刚完成了通勤。"},
                {"from_agent": 9, "from_name": "Agent9", "text": "今天准备减少外出。"},
            ],
            max_items=2,
        )
        self.assertIn("跨机器通信消息", text)
        self.assertIn("Agent7", text)
        self.assertIn("Agent9", text)

    def test_personal_twin_social_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = DistributedRelayBackend(
                state_path=os.path.join(tmpdir, "relay_state.json"),
                max_messages=200,
            )
            backend.register_agents(
                "cluster-a",
                "node-1",
                [
                    {
                        "id": 1,
                        "name": "Twin-1",
                        "public_profile": {"summary": "node1 twin", "tags": ["pm"]},
                    }
                ],
                agent_type="personal_twin",
            )
            backend.register_agents(
                "cluster-a",
                "node-2",
                [
                    {
                        "id": 2,
                        "name": "Twin-2",
                        "public_profile": {"summary": "node2 twin", "tags": ["design"]},
                    }
                ],
                agent_type="personal_twin",
            )
            backend.send_message(
                "cluster-a",
                "node-1",
                {
                    "from_agent": 1,
                    "from_name": "Twin-1",
                    "to_agent": 2,
                    "text": "今天在本地做了一个求职方向的 what-if。",
                    "intent": "what_if_share",
                    "social_summary": {"summary": "分享求职方向推演结果", "topic": "职业选择"},
                },
            )
            backend.send_message(
                "cluster-a",
                "node-2",
                {
                    "from_agent": 2,
                    "from_name": "Twin-2",
                    "to_agent": 1,
                    "text": "我这边更建议先做短周期验证。",
                    "intent": "advice_request",
                    "social_summary": {"summary": "建议先做短周期验证", "topic": "建议反馈"},
                },
            )

            snapshot = backend.social_snapshot("cluster-a", recent_limit=5)
            self.assertEqual(2, snapshot["stats"]["agent_count"])
            self.assertEqual(1, snapshot["stats"]["edge_count"])
            self.assertEqual(2, snapshot["stats"]["recent_message_count"])
            agents = {item["agent_id"]: item for item in snapshot["agents"]}
            self.assertEqual([2], agents[1].get("recent_partners", [])[:1])
            self.assertEqual([1], agents[2].get("recent_partners", [])[:1])
            self.assertEqual("personal_twin", agents[1].get("agent_type"))
            self.assertEqual("node-1", agents[1].get("node_id"))

    def test_social_snapshot_tracks_agents_edges_and_privacy_safe_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "relay_state.json")
            backend = DistributedRelayBackend(state_path=state_path, max_messages=100)
            reg_a = backend.register_agents(
                "demo",
                "node-a",
                [
                    {
                        "id": 1,
                        "name": "TwinA",
                        "job": "产品经理",
                        "background_summary": "长期关注工作与通勤平衡。",
                        "public_profile": {
                            "summary": "本地运行的个人孪生，公开摘要版本。",
                            "status": "今天在整理工作流",
                            "focus": "职业决策",
                            "tags": ["产品", "杭州"],
                        },
                        "private_memory": "不应进入 snapshot",
                    }
                ],
                agent_type="personal_twin",
            )
            reg_b = backend.register_agents(
                "demo",
                "node-b",
                [{"id": 2, "name": "TwinB", "job": "设计师"}],
                agent_type="openclaw",
            )
            self.assertTrue(reg_a.get("ok"))
            self.assertTrue(reg_b.get("ok"))

            sent = backend.send_message(
                "demo",
                "node-a",
                {
                    "from_agent": 1,
                    "from_name": "TwinA",
                    "to_agent": 2,
                    "kind": "agent_update",
                    "text": "我今天在本地跑了一个面试选择的反事实模拟。",
                    "intent": "what_if_share",
                    "visibility": "direct",
                    "private_level": "summary",
                    "memory_policy": "social_summary",
                    "conversation_id": "conv-1",
                    "social_summary": {
                        "summary": "分享本地 what-if 推演后的结论摘要。",
                        "topic": "职业选择",
                        "status": "准备比较两份机会",
                        "emotion": "谨慎",
                        "ask": "想听听你的看法",
                    },
                    "public_state": {
                        "emotion": 0.42,
                        "stress": 0.61,
                        "status": "在做个人决策演练",
                    },
                    "meta": {"private_memory": "这部分不该出现在 social snapshot"},
                    "day": 2,
                    "time": "21:30",
                    "activity": "个人时间",
                },
            )
            self.assertTrue(sent.get("ok"))

            snapshot = backend.social_snapshot("demo", recent_limit=10)
            self.assertTrue(snapshot.get("ok"))
            self.assertEqual(2, snapshot["stats"]["agent_count"])
            self.assertEqual(1, snapshot["stats"]["edge_count"])
            self.assertEqual(1, snapshot["stats"]["recent_message_count"])

            agents = {item["agent_id"]: item for item in snapshot.get("agents", [])}
            self.assertIn(1, agents)
            self.assertIn(2, agents)
            self.assertEqual("personal_twin", agents[1].get("agent_type"))
            self.assertEqual(
                "本地运行的个人孪生，公开摘要版本。",
                agents[1].get("public_profile", {}).get("summary"),
            )
            self.assertNotIn("private_memory", agents[1])
            self.assertEqual("在做个人决策演练", agents[1].get("public_state", {}).get("status"))

            edges = snapshot.get("edges", [])
            self.assertEqual(1, len(edges))
            self.assertEqual(1, edges[0].get("interaction_count"))
            self.assertEqual("what_if_share", edges[0].get("last_intent"))

            recent = snapshot.get("recent_messages", [])
            self.assertEqual(1, len(recent))
            self.assertEqual("分享本地 what-if 推演后的结论摘要。", recent[0].get("preview"))
            self.assertNotIn("private_memory", str(recent[0]))


if __name__ == "__main__":
    unittest.main()
