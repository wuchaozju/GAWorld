import unittest
from unittest.mock import patch

import generative_city_sim as sim


def _agent():
    return {
        "id": 1,
        "name": "测试居民",
        "age": 29,
        "living": "杭州城西",
        "residence": "杭州",
        "job": "产品经理",
        "personality": "谨慎但好奇，关注趋势",
        "daily_life": "工作日通勤稳定，周末逛书店和咖啡馆",
        "values": "重视稳定收入，也关心公共政策变化",
        "state": {
            "emotion": 0.5,
            "stress": 0.6,
            "econ_security": 0.45,
            "risk_preference": 0.5,
            "platform_dependence": 0.5,
        },
        "memory": [],
    }


class TestBootstrapExternalRag(unittest.TestCase):
    def test_bootstrap_seeds_profile_and_web_items(self):
        agent = _agent()
        bootstrap_cfg = {
            "bootstrap": {
                "enabled": True,
                "only_when_empty": True,
                "profile_items": 2,
                "web_items": 1,
                "use_web_search": True,
                "prefer_cached_news": True,
                "max_chars_per_item": 280,
            }
        }
        target = {
            "url": "https://example.com/story",
            "title": "平台就业政策变化",
            "content": "这条政策信息可能影响平台从业者的收入预期与工作安排。",
            "query": "平台就业政策 最新消息",
        }

        with patch.dict(sim.EXTERNAL_RAG_CONFIG, bootstrap_cfg, clear=True), \
             patch.object(sim, "_llm_bootstrap_external_items", return_value=["背景记忆A", "背景记忆B"]), \
             patch.object(sim, "_build_agent_preferred_sites", return_value=["example.com"]), \
             patch.object(sim, "_choose_info_target", return_value=target), \
             patch.object(sim, "_summarize_bootstrap_web_item", return_value="会长期关注平台就业政策对收入预期的影响。"), \
             patch.object(sim, "STATEFUL", False), \
             patch.object(sim, "vector_db_add_entry"), \
             patch.object(sim, "save_agent_memory"):
            inserted = sim._bootstrap_agent_external_rag(
                agent,
                news_cache=[],
                news_sources=[],
            )

        self.assertEqual(3, len(inserted))
        self.assertEqual(3, len(agent["memory"]))
        self.assertTrue(any("来源:init_seed_profile" in item for item in agent["memory"]))
        self.assertTrue(any("来源:init_seed_web:example.com" in item for item in agent["memory"]))

    def test_bootstrap_degrades_when_llm_profile_seed_raises(self):
        # LLM endpoint down: the profile-seed call raises, but bootstrap must
        # swallow it, skip the seed, and let the run continue (no exception).
        agent = _agent()
        bootstrap_cfg = {
            "bootstrap": {
                "enabled": True,
                "only_when_empty": True,
                "profile_items": 2,
                "web_items": 1,
                "use_web_search": False,
            }
        }
        with patch.dict(sim.EXTERNAL_RAG_CONFIG, bootstrap_cfg, clear=True), \
             patch.object(
                 sim, "_llm_bootstrap_external_items",
                 side_effect=ConnectionError("connection refused"),
             ), \
             patch.object(sim, "STATEFUL", False):
            inserted = sim._bootstrap_agent_external_rag(agent, news_cache=[], news_sources=[])
        self.assertEqual([], inserted)
        self.assertEqual([], agent["memory"])

    def test_bootstrap_skips_web_item_when_summarize_raises(self):
        # Profile seed succeeds; the web-summarize LLM call fails — the web item
        # is skipped, but the already-seeded profile items survive.
        agent = _agent()
        bootstrap_cfg = {
            "bootstrap": {
                "enabled": True,
                "only_when_empty": True,
                "profile_items": 2,
                "web_items": 1,
                "use_web_search": True,
            }
        }
        target = {
            "url": "https://example.com/story",
            "title": "平台就业政策变化",
            "content": "这条政策信息可能影响平台从业者的收入预期与工作安排。",
            "query": "平台就业政策 最新消息",
        }
        with patch.dict(sim.EXTERNAL_RAG_CONFIG, bootstrap_cfg, clear=True), \
             patch.object(sim, "_llm_bootstrap_external_items", return_value=["背景A", "背景B"]), \
             patch.object(sim, "_build_agent_preferred_sites", return_value=["example.com"]), \
             patch.object(sim, "_choose_info_target", return_value=target), \
             patch.object(
                 sim, "_summarize_bootstrap_web_item",
                 side_effect=ConnectionError("connection refused"),
             ), \
             patch.object(sim, "STATEFUL", False), \
             patch.object(sim, "vector_db_add_entry"), \
             patch.object(sim, "save_agent_memory"):
            inserted = sim._bootstrap_agent_external_rag(agent, news_cache=[], news_sources=[])
        self.assertEqual(2, len(inserted))  # profile seed kept, web item skipped
        self.assertTrue(all("来源:init_seed_web" not in item for item in agent["memory"]))

    def test_bootstrap_skips_when_external_info_exists(self):
        agent = _agent()
        agent["memory"] = ["[额外信息 | 来源:manual] 已有外部知识 关键词: 已有 外部 知识"]
        bootstrap_cfg = {
            "bootstrap": {
                "enabled": True,
                "only_when_empty": True,
                "profile_items": 2,
                "web_items": 1,
                "use_web_search": True,
            }
        }
        with patch.dict(sim.EXTERNAL_RAG_CONFIG, bootstrap_cfg, clear=True), \
             patch.object(sim, "_llm_bootstrap_external_items") as bootstrap_mock:
            inserted = sim._bootstrap_agent_external_rag(agent, news_cache=[], news_sources=[])
        self.assertEqual([], inserted)
        bootstrap_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
