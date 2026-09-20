"""Tests for the Agent Studio backend helpers in ``gaworld.apps.dashboard_server``.

These exercise the read/write paths added for the Studio UI without starting an
HTTP server: state round-trip + profile sync, agent creation, and the social
snapshot reader. All writes target temp copies so repo seed data is untouched.
"""

import json
import os
import shutil
import tempfile
import unittest

import gaworld.apps.dashboard_server as ds

REPO_ROOT = ds.REPO_ROOT
REAL_CSV = os.path.join(REPO_ROOT, "data", "hangzhou_agents_state_init.csv")
REAL_MD = os.path.join(REPO_ROOT, "data", "hangzhou_profiles_with_names.md")


class TestStateRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._csv, self._md = ds.STATE_CSV_PATH, ds.PROFILE_PATH
        ds.STATE_CSV_PATH = os.path.join(self.tmp, "state.csv")
        ds.PROFILE_PATH = os.path.join(self.tmp, "profiles.md")
        shutil.copy(REAL_CSV, ds.STATE_CSV_PATH)
        shutil.copy(REAL_MD, ds.PROFILE_PATH)

    def tearDown(self):
        ds.STATE_CSV_PATH, ds.PROFILE_PATH = self._csv, self._md
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_state_write_persists_to_csv(self):
        ds._save_agent_state(1, {"state": {"emotion": 0.123, "risk_preference": 0.9}})
        again = ds._agent_state(1)
        self.assertAlmostEqual(again["state"]["emotion"], 0.123, places=4)
        self.assertAlmostEqual(again["state"]["risk_preference"], 0.9, places=4)

    def test_state_write_syncs_profile_markdown(self):
        ds._save_agent_state(1, {"state": {"emotion": 0.11, "mobility_intent": 0.77}})
        block = ds._agent_profile(1)["text"]
        self.assertIn("emotion 0.11", block)
        self.assertIn("- mobility_intent：0.77", block)

    def test_identity_edit_persists(self):
        ds._save_agent_state(1, {"name": "测试改名", "age": 41})
        again = ds._agent_state(1)
        self.assertEqual(again["name"], "测试改名")
        self.assertEqual(again["age"], 41)

    def test_state_clamped_to_unit_interval(self):
        ds._save_agent_state(1, {"state": {"stress": 5.0, "emotion": -3}})
        again = ds._agent_state(1)
        self.assertEqual(again["state"]["stress"], 1.0)
        self.assertEqual(again["state"]["emotion"], 0.0)


class TestCreateAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._csv, self._md = ds.STATE_CSV_PATH, ds.PROFILE_PATH
        ds.STATE_CSV_PATH = os.path.join(self.tmp, "state.csv")
        ds.PROFILE_PATH = os.path.join(self.tmp, "profiles.md")
        shutil.copy(REAL_CSV, ds.STATE_CSV_PATH)
        shutil.copy(REAL_MD, ds.PROFILE_PATH)

    def tearDown(self):
        ds.STATE_CSV_PATH, ds.PROFILE_PATH = self._csv, self._md
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_appends_row_and_block(self):
        before = {a["id"] for a in ds._agents_summary()}
        res = ds._create_agent({"name": "新居民甲", "gender": "女", "age": 27, "state": {"risk_preference": 0.9}})
        self.assertNotIn(res["id"], before)
        # readable from CSV
        state = ds._agent_state(res["id"])
        self.assertEqual(state["name"], "新居民甲")
        self.assertAlmostEqual(state["state"]["risk_preference"], 0.9, places=4)
        # profile block appended
        with open(ds.PROFILE_PATH, encoding="utf-8") as f:
            self.assertIn("新居民甲", f.read())

    def test_create_preserves_bom(self):
        ds._create_agent({"name": "BOM测试"})
        with open(ds.STATE_CSV_PATH, "rb") as f:
            self.assertEqual(f.read(3), b"\xef\xbb\xbf")


class TestSocialSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root, self._cfg = ds.REPO_ROOT, ds._effective_config
        ds.REPO_ROOT = self.tmp
        ds._effective_config = lambda: {"memory_dir": "output/memory"}
        mem = os.path.join(self.tmp, "output", "memory")
        os.makedirs(mem, exist_ok=True)
        rels = {
            "42": {"kind": "agent", "role": "coworker", "dunbar_tier": "close",
                   "closeness": 0.6, "trust": 0.5, "profile": {"name": "同事小王"}},
            "g_mother": {"kind": "ghost", "role": "mother", "dunbar_tier": "inner",
                         "closeness": 0.85, "trust": 0.86, "profile": {"name": "母亲"}},
        }
        with open(os.path.join(mem, "agent_9_relationships.json"), "w", encoding="utf-8") as f:
            json.dump(rels, f, ensure_ascii=False)

    def tearDown(self):
        ds.REPO_ROOT, ds._effective_config = self._root, self._cfg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_parses_and_sorts(self):
        snap = ds._social_snapshot(9)
        self.assertEqual(snap["count"], 2)
        self.assertEqual(snap["tier_counts"]["inner"], 1)
        self.assertEqual(snap["tier_counts"]["close"], 1)
        # sorted by closeness desc → mother first
        self.assertEqual(snap["relations"][0]["name"], "母亲")
        self.assertEqual(snap["relations"][0]["kind"], "ghost")

    def test_snapshot_none_when_absent(self):
        self.assertIsNone(ds._social_snapshot(9999))


class TestRelationshipEditing(unittest.TestCase):
    """Studio writes back to agent_{id}_relationships.json (step 5)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root, self._cfg = ds.REPO_ROOT, ds._effective_config
        ds.REPO_ROOT = self.tmp
        ds._effective_config = lambda: {"memory_dir": "output/memory"}
        mem = os.path.join(self.tmp, "output", "memory")
        os.makedirs(mem, exist_ok=True)
        self.path = os.path.join(mem, "agent_9_relationships.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "g_mother": {
                    "kind": "ghost", "role": "mother", "dunbar_tier": "inner",
                    "closeness": 0.85, "trust": 0.86, "friction": 0.24,
                    "channels": ["call"], "profile": {"name": "母亲", "vibe": "爱唠叨"},
                },
                "c_wang": {
                    "kind": "agent", "role": "coworker", "dunbar_tier": "close",
                    "closeness": 0.6, "trust": 0.5, "profile": {"name": "同事小王"},
                },
            }, f, ensure_ascii=False)

    def tearDown(self):
        ds.REPO_ROOT, ds._effective_config = self._root, self._cfg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _raw(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_edit_updates_closeness_and_keeps_simulator_fields(self):
        ds._save_agent_relationships(9, {"relations": [
            {"id": "g_mother", "closeness": 0.42, "trust": 0.4, "tier": "close", "name": "妈妈"},
        ]})
        entry = self._raw()["g_mother"]
        self.assertAlmostEqual(entry["closeness"], 0.42)
        self.assertEqual(entry["dunbar_tier"], "close")
        self.assertEqual(entry["profile"]["name"], "妈妈")
        # untouched simulator-owned fields survive the edit
        self.assertEqual(entry["friction"], 0.24)
        self.assertEqual(entry["profile"]["vibe"], "爱唠叨")

    def test_closeness_clamped(self):
        ds._save_agent_relationships(9, {"relations": [{"id": "c_wang", "closeness": 4, "trust": -1}]})
        entry = self._raw()["c_wang"]
        self.assertEqual(entry["closeness"], 1.0)
        self.assertEqual(entry["trust"], 0.0)

    def test_add_without_id_gets_generated_key(self):
        snap = ds._save_agent_relationships(9, {"relations": [
            {"name": "新邻居", "role": "neighbor", "tier": "acquaintance", "closeness": 0.3},
        ]})
        self.assertEqual(snap["count"], 3)
        entry = self._raw()["manual_1"]
        self.assertEqual(entry["profile"]["name"], "新邻居")
        self.assertEqual(entry["role"], "neighbor")
        self.assertEqual(entry["tie_origin"], "manual")

    def test_removed_ids_are_deleted(self):
        snap = ds._save_agent_relationships(9, {"removed": ["c_wang"]})
        self.assertEqual(snap["count"], 1)
        self.assertNotIn("c_wang", self._raw())

    def test_creates_file_when_absent(self):
        ds._save_agent_relationships(11, {"relations": [{"name": "老同学", "role": "classmate"}]})
        with open(os.path.join(self.tmp, "output", "memory", "agent_11_relationships.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["manual_1"]["profile"]["name"], "老同学")


class TestManualMemory(unittest.TestCase):
    """Hand-written long-term memories and RAG snippets (step 4)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root, self._cfg = ds.REPO_ROOT, ds._effective_config
        self._index = ds._index_memory_entry
        ds.REPO_ROOT = self.tmp
        ds._effective_config = lambda: {"memory_dir": "output/memory"}
        ds._index_memory_entry = lambda *args: None  # skip the vector-DB mirror
        self.path = os.path.join(self.tmp, "output", "memory", "agent_9.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(["原有记忆"], f, ensure_ascii=False)

    def tearDown(self):
        ds.REPO_ROOT, ds._effective_config = self._root, self._cfg
        ds._index_memory_entry = self._index
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _raw(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_append_plain_memory(self):
        result = ds._append_agent_memory(9, {"kind": "memory", "text": " 上周   搬了家 "})
        self.assertEqual(result["count"], 2)
        self.assertEqual(self._raw()[-1], "上周 搬了家")

    def test_rag_gets_tagged(self):
        ds._append_agent_memory(9, {"kind": "rag", "text": "杭州地铁19号线已开通"})
        stored = self._raw()[-1]
        self.assertTrue(stored.startswith(ds.MANUAL_RAG_PREFIX))
        self.assertEqual(ds._rag_snapshot(self._raw())["count"], 1)

    def test_already_tagged_rag_not_double_prefixed(self):
        ds._append_agent_memory(9, {"kind": "rag", "text": "[额外信息 | 来源:web] 已经有前缀"})
        self.assertEqual(self._raw()[-1].count("[额外信息"), 1)

    def test_rejects_blank_and_unknown_kind(self):
        with self.assertRaises(ValueError):
            ds._append_agent_memory(9, {"kind": "memory", "text": "   "})
        with self.assertRaises(ValueError):
            ds._append_agent_memory(9, {"kind": "diary", "text": "x"})

    def test_creates_file_when_absent(self):
        ds._append_agent_memory(12, {"text": "第一条记忆"})
        with open(os.path.join(self.tmp, "output", "memory", "agent_12.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), ["第一条记忆"])


class TestMemoryDetail(unittest.TestCase):
    def test_splits_rag_and_flattens_habits(self):
        detail = ds._memory_detail({
            "memory": ["普通记忆", "[额外信息 | 来源:web] 外部知识"],
            "habits": {
                "morning|public|上午工作": {"preferred_action": "推进任务", "strength": 0.23, "last_updated_day": 4},
                "night|public|散步": {"preferred_action": "沿河走", "strength": 0.51},
            },
            "intentions": {"priorities": ["维持日常节奏"]},
            "schedule": [{"time": "08:00", "activity": "吃早饭"}],
        })
        self.assertEqual([item["rag"] for item in detail["long_term"]], [False, True])
        # habits sorted by strength desc, key split into phase / activity
        self.assertEqual(detail["habits"][0]["activity"], "散步")
        self.assertEqual(detail["habits"][1]["phase"], "morning")
        self.assertEqual(detail["intentions"]["priorities"], ["维持日常节奏"])
        self.assertEqual(detail["schedule"], [{"time": "08:00", "activity": "吃早饭"}])

    def test_tolerates_missing_and_malformed(self):
        detail = ds._memory_detail({"memory": None, "habits": ["bad"], "intentions": [], "schedule": {}})
        self.assertEqual(detail["long_term"], [])
        self.assertEqual(detail["habits"], [])
        self.assertEqual(detail["intentions"], {})
        self.assertEqual(detail["schedule"], [])


class TestFinanceEditing(unittest.TestCase):
    """Studio writes back to the live economy state (step 7)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root, self._cfg, self._snap = ds.REPO_ROOT, ds._effective_config, ds.ECONOMY_SNAPSHOT_PATH
        ds.REPO_ROOT = self.tmp
        ds._effective_config = lambda: {"memory_dir": "output/memory"}
        ds.ECONOMY_SNAPSHOT_PATH = os.path.join(self.tmp, "missing.csv")
        self.path = os.path.join(self.tmp, "output", "memory", "agent_9_economy.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "currency": "CNY", "balance": 10256.18, "debt": 0.0,
                "accounts": {"checking": 2484.57, "savings": 5521.93,
                             "investment": 2249.68, "housing_fund": 79614.86},
                "net_monthly_salary": 2971.84, "engel_coefficient": 0.48,
                "savings_rate": 0.05, "monthly_budget": {"food": 1355.16},
            }, f, ensure_ascii=False)

    def tearDown(self):
        ds.REPO_ROOT, ds._effective_config = self._root, self._cfg
        ds.ECONOMY_SNAPSHOT_PATH = self._snap
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_live_state_as_editable(self):
        fin = ds._agent_finance(9)
        self.assertTrue(fin["editable"])
        self.assertEqual(fin["source"], "state")
        self.assertEqual(fin["accounts"]["savings"], 5521.93)

    def test_deposit_edit_recomputes_liquid_balance(self):
        fin = ds._save_agent_finance(9, {"accounts": {"savings": 100000}})
        self.assertEqual(fin["accounts"]["savings"], 100000.0)
        # housing fund is excluded from the liquid balance
        self.assertEqual(fin["balance"], round(2484.57 + 100000 + 2249.68, 2))
        with open(self.path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["monthly_budget"], {"food": 1355.16})  # untouched keys survive

    def test_rates_clamped_and_amounts_floored(self):
        fin = ds._save_agent_finance(9, {"savings_rate": 3, "engel_coefficient": -1, "debt": -50})
        self.assertEqual(fin["savings_rate"], 1.0)
        self.assertEqual(fin["engel_coefficient"], 0.0)
        self.assertEqual(fin["debt"], 0.0)

    def test_refuses_when_no_live_state(self):
        self.assertIsNone(ds._agent_finance(77))
        with self.assertRaises(ValueError):
            ds._save_agent_finance(77, {"accounts": {"savings": 10}})


class TestRagSnapshot(unittest.TestCase):
    def test_filters_tagged_items(self):
        memory = ["普通记忆", "[额外信息 | 来源:web] 杭州地铁19号线已开通", {"text": "dict item"}]
        snap = ds._rag_snapshot(memory)
        self.assertEqual(snap["count"], 1)
        self.assertIn("杭州地铁", snap["items"][0])

    def test_empty_and_non_list(self):
        self.assertEqual(ds._rag_snapshot([])["count"], 0)
        self.assertEqual(ds._rag_snapshot(None)["count"], 0)


class TestOpenclawSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._relay = ds.RELAY_STATE_PATH
        ds.RELAY_STATE_PATH = os.path.join(self.tmp, "relay_state.json")
        state = {
            "directory": {
                "default": {
                    "7": {"agent_id": 7, "name": "沈嘉和", "agent_type": "native", "node_id": "n1"},
                    "1001": {"agent_id": 1001, "name": "外部助手", "agent_type": "openclaw", "node_id": "n2"},
                }
            },
            "messages": [
                {"id": 1, "from_agent": 7, "to_agent": 1001, "text": "hi"},
                {"id": 2, "from_agent": 1001, "to_agent": 7, "text": "hello"},
                {"id": 3, "from_agent": 7, "to_agent": 4, "text": "native-to-native"},
            ],
        }
        with open(ds.RELAY_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

    def tearDown(self):
        ds.RELAY_STATE_PATH = self._relay
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_native_agent_connected_via_messages(self):
        snap = ds._openclaw_snapshot(7)
        self.assertTrue(snap["registered"])
        self.assertFalse(snap["is_openclaw_agent"])
        self.assertEqual(snap["messages_sent"], 1)
        self.assertEqual(snap["messages_received"], 1)
        self.assertTrue(snap["connected"])

    def test_external_openclaw_agent(self):
        snap = ds._openclaw_snapshot(1001)
        self.assertTrue(snap["is_openclaw_agent"])
        self.assertTrue(snap["connected"])

    def test_unregistered_agent_not_connected(self):
        snap = ds._openclaw_snapshot(99)
        self.assertFalse(snap["registered"])
        self.assertFalse(snap["connected"])


class TestCognitionAndCard(unittest.TestCase):
    EMPTY_COUNTS = {"long_term": 0, "habits": 0, "intentions": 0, "schedule": 0}

    def test_cognition_floor_when_empty(self):
        snap = ds._cognition_snapshot(None, None, self.EMPTY_COUNTS, {"count": 0})
        self.assertEqual(snap["score"], 60)

    def test_cognition_ceiling(self):
        caps = {"skills": ["a"] * 6, "deliverables": ["d"] * 4}
        growth = {"items": [{"level": 1.0}]}
        counts = {"long_term": 300, "habits": 0, "intentions": 0, "schedule": 0}
        snap = ds._cognition_snapshot(caps, growth, counts, {"count": 20})
        self.assertEqual(snap["score"], 140)

    def test_agent_card_merges_sources(self):
        identity = {"id": 5, "name": "测试", "gender": "女", "age": 30, "residence": "杭州"}
        caps = {"job_label": "engineer", "skills": ["编程"], "interests": ["运动"], "deliverables": ["code"]}
        private = [{"file": "x.md", "title": "数据分析"}]
        growth = {"items": [{"name": "摄影", "kind": "hobby"}]}
        card = ds._agent_card(identity, caps, private, growth, {"connected": True})
        self.assertEqual(card["skills"], ["编程", "数据分析"])
        self.assertEqual(card["interests"], ["运动", "摄影"])
        self.assertTrue(card["openclaw_connected"])
        self.assertEqual(card["endpoints"]["detail"], "/api/agents/5/detail")


class TestPrivateSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._root, self._cfg = ds.REPO_ROOT, ds._effective_config
        ds.REPO_ROOT = self.tmp
        ds._effective_config = lambda: {"memory_dir": "output/memory"}
        skill_dir = os.path.join(self.tmp, "output", "memory", "agent_5_skills")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "photo.md"), "w", encoding="utf-8") as f:
            f.write("# 街头摄影\n从经验蒸馏。\n")

    def tearDown(self):
        ds.REPO_ROOT, ds._effective_config = self._root, self._cfg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_private_dir(self):
        skills = ds._private_skills(5)
        self.assertEqual(skills, [{"file": "photo.md", "title": "街头摄影"}])

    def test_empty_when_absent(self):
        self.assertEqual(ds._private_skills(6), [])


if __name__ == "__main__":
    unittest.main()
