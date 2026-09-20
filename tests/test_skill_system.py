"""Unit tests for the Skill subsystem.

Covers:
* Markdown ↔ Skill round-trip (frontmatter parser + dumper).
* Registry: global library, private per-agent skills, attach/detach.
* Experience → Skill consolidation with a mocked LLM.
* Prompt helpers (cognition block + work-router brief integration).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from gaworld.settings import CONFIG
from gaworld.skills import (
    Skill,
    SkillRegistry,
    render_agent_skills,
    summarize_experience_to_skill,
)
from gaworld.skills.consolidation import run_skill_consolidation
from gaworld.skills.prompt_helpers import relevant_skills_for_text
from gaworld.skills.schemas import (
    dump_skill_markdown,
    parse_skill_markdown,
    slugify_skill_id,
)


def _seed_global_skill(directory: str, skill_id: str, *, name: str, triggers: list[str]) -> str:
    os.makedirs(directory, exist_ok=True)
    skill = Skill(
        skill_id=skill_id,
        name=name,
        description=f"{name} 的简短描述",
        body=f"{name} 的执行步骤说明，至少有一行可读文本。",
        triggers=triggers,
        source="global",
        origin="seed",
    )
    path = os.path.join(directory, f"{skill_id}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump_skill_markdown(skill))
    return path


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------
class SkillSchemaTests(unittest.TestCase):
    def test_dump_then_parse_preserves_fields(self) -> None:
        original = Skill(
            skill_id="quick-debug",
            name="快速排错",
            description="先复现，再二分",
            body="1. 复现 bug。\n2. 二分定位。\n3. 写一条 regression test。",
            triggers=["bug", "排错", "debug"],
            source="private",
            owner_agent_id=7,
            origin="consolidation",
            created_day=12,
        )
        text = dump_skill_markdown(original)
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: 快速排错", text)
        self.assertIn("triggers: [bug, 排错, debug]", text)

        parsed = parse_skill_markdown("quick-debug", text)
        self.assertEqual(parsed.name, original.name)
        self.assertEqual(parsed.description, original.description)
        self.assertEqual(parsed.triggers, original.triggers)
        self.assertEqual(parsed.body.split("\n")[0], "1. 复现 bug。")
        self.assertEqual(parsed.source, "private")
        self.assertEqual(parsed.owner_agent_id, 7)
        self.assertEqual(parsed.created_day, 12)

    def test_parser_tolerates_missing_frontmatter(self) -> None:
        skill = parse_skill_markdown("legacy", "Free-form skill\nWith some body text.")
        self.assertEqual(skill.name, "Free-form skill")
        self.assertIn("body text", skill.body)
        self.assertEqual(skill.triggers, [])

    def test_slugify_handles_cjk_and_punctuation(self) -> None:
        self.assertEqual(slugify_skill_id("快速排错!@#"), "快速排错")
        self.assertEqual(slugify_skill_id("  ", fallback="x"), "x")
        self.assertEqual(slugify_skill_id("Code Review v2"), "Code-Review-v2")

    def test_skill_matches_trigger_substrings(self) -> None:
        skill = Skill(skill_id="x", name="排版指南", triggers=["海报", "Layout"])
        self.assertTrue(skill.matches("今天要做一张海报"))
        self.assertTrue(skill.matches("set up the LAYOUT"))
        self.assertFalse(skill.matches("写一段代码"))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.global_dir = os.path.join(self._tmp.name, "data", "skills")
        self.memory_dir = os.path.join(self._tmp.name, "output", "memory")
        _seed_global_skill(self.global_dir, "code-review", name="代码评审", triggers=["代码", "评审"])
        _seed_global_skill(self.global_dir, "poster-grid", name="海报网格", triggers=["海报", "排版"])
        self.registry = SkillRegistry(global_dir=self.global_dir, memory_dir=self.memory_dir)

    def test_lists_only_attached_global_skills_for_agent(self) -> None:
        agent: dict[str, Any] = {"id": 11, "skill_ids": ["code-review"]}
        skills = self.registry.list_for_agent(agent)
        self.assertEqual([s.skill_id for s in skills], ["code-review"])

    def test_attach_refuses_unknown_skill(self) -> None:
        agent: dict[str, Any] = {"id": 11}
        self.assertFalse(self.registry.attach_to_agent(agent, "nonexistent"))
        self.assertEqual(agent.get("skill_ids", []), [])

    def test_attach_and_detach_global_skill(self) -> None:
        agent: dict[str, Any] = {"id": 11}
        self.assertTrue(self.registry.attach_to_agent(agent, "poster-grid"))
        self.assertFalse(self.registry.attach_to_agent(agent, "poster-grid"))  # idempotent
        self.assertIn("poster-grid", agent["skill_ids"])
        self.assertTrue(self.registry.detach_from_agent(agent, "poster-grid"))
        self.assertEqual(agent["skill_ids"], [])

    def test_save_private_persists_and_reloads(self) -> None:
        skill = Skill(
            skill_id="",  # let registry slugify
            name="自创小招",
            description="自总结技能",
            body="先做 A，再做 B，最后回顾 C。",
            triggers=["自创"],
            source="private",
        )
        saved = self.registry.save_private(agent_id=11, skill=skill)
        self.assertEqual(saved.source, "private")
        self.assertEqual(saved.owner_agent_id, 11)

        # New registry instance hits the same dir — saved file should appear.
        fresh = SkillRegistry(global_dir=self.global_dir, memory_dir=self.memory_dir)
        listed = fresh.list_private(11)
        self.assertEqual([s.skill_id for s in listed], [saved.skill_id])

    def test_private_skill_outranks_global_with_same_id(self) -> None:
        # Save a private skill with the same id as a global one.
        clash = Skill(skill_id="code-review", name="我的代码评审", body="私有版本")
        self.registry.save_private(agent_id=11, skill=clash)
        agent = {"id": 11, "skill_ids": ["code-review"]}
        skills = self.registry.list_for_agent(agent)
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "我的代码评审")
        self.assertEqual(skills[0].source, "private")


# ---------------------------------------------------------------------------
# Experience → Skill
# ---------------------------------------------------------------------------
class SkillConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.memory_dir = os.path.join(self._tmp.name, "memory")
        self.global_dir = os.path.join(self._tmp.name, "skills")
        os.makedirs(self.global_dir, exist_ok=True)
        self.registry = SkillRegistry(global_dir=self.global_dir, memory_dir=self.memory_dir)

    def _fake_episodes(self, n: int) -> list[dict[str, Any]]:
        return [
            {
                "id": i,
                "entry_type": "memory",
                "text": f"今天在工作中又用三栏网格搞定了海报 #{i}",
                "sim_day": 10 + i,
                "sim_time": "14:00",
                "salience": 0.7,
                "recall_count": 0,
            }
            for i in range(n)
        ]

    def test_returns_none_when_too_few_episodes(self) -> None:
        with patch(
            "gaworld.skills.consolidation.fetch_recent_episodes",
            return_value=self._fake_episodes(2),
        ):
            result = summarize_experience_to_skill(
                {"id": 7, "name": "测试人"},
                llm=lambda _p: "shouldnt be called",
                registry=self.registry,
                today=20,
                min_episodes=4,
            )
        self.assertIsNone(result)

    def test_skip_payload_returns_none(self) -> None:
        with patch(
            "gaworld.skills.consolidation.fetch_recent_episodes",
            return_value=self._fake_episodes(5),
        ):
            result = summarize_experience_to_skill(
                {"id": 7, "name": "测试人"},
                llm=lambda _p: json.dumps({"skip": True, "reason": "无模式"}),
                registry=self.registry,
                today=20,
                min_episodes=4,
            )
        self.assertIsNone(result)
        self.assertEqual(self.registry.list_private(7), [])

    def test_valid_payload_persists_private_skill(self) -> None:
        payload = {
            "name": "海报三栏法",
            "description": "用三栏网格快速搭海报",
            "triggers": ["海报", "排版"],
            "body": "先定主色，再切三栏，最后调字号 4:2:1。",
        }
        with patch(
            "gaworld.skills.consolidation.fetch_recent_episodes",
            return_value=self._fake_episodes(5),
        ):
            saved = summarize_experience_to_skill(
                {"id": 7, "name": "测试人", "job": "设计师"},
                llm=lambda _p: json.dumps(payload),
                registry=self.registry,
                today=20,
                min_episodes=4,
            )
        assert saved is not None
        self.assertEqual(saved.name, "海报三栏法")
        self.assertEqual(saved.source, "private")
        self.assertEqual(saved.owner_agent_id, 7)
        self.assertEqual(saved.created_day, 20)
        # Persisted file is readable by a fresh registry.
        fresh = SkillRegistry(global_dir=self.global_dir, memory_dir=self.memory_dir)
        self.assertEqual(len(fresh.list_private(7)), 1)

    def test_run_skill_consolidation_respects_config_flag(self) -> None:
        # Test is self-contained: it explicitly patches the config flag in
        # both directions rather than relying on the runtime default (which
        # the project may flip ON in production).
        cfg = CONFIG.get("memory", {}).setdefault("skill_consolidation", {})

        # enabled=False → should no-op even with good data.
        with patch.dict(cfg, {"enabled": False}, clear=False):
            with patch(
                "gaworld.skills.consolidation.fetch_recent_episodes",
                return_value=self._fake_episodes(5),
            ):
                result = run_skill_consolidation(
                    {"id": 7, "name": "测试人"},
                    llm=lambda _p: json.dumps({"name": "x", "body": "y"}),
                    registry=self.registry,
                    today=20,
                )
        self.assertIsNone(result)

        # enabled=True → should actually run.
        with patch.dict(
            cfg,
            {"enabled": True, "min_episodes": 4, "lookback_days": 5},
            clear=False,
        ):
            with patch(
                "gaworld.skills.consolidation.fetch_recent_episodes",
                return_value=self._fake_episodes(5),
            ):
                result = run_skill_consolidation(
                    {"id": 7, "name": "测试人"},
                    llm=lambda _p: json.dumps({"name": "测试技能", "body": "做事步骤", "description": "x"}),
                    registry=self.registry,
                    today=20,
                )
        assert result is not None
        self.assertEqual(result.name, "测试技能")


# ---------------------------------------------------------------------------
# Prompt rendering + relevance
# ---------------------------------------------------------------------------
class SkillPromptTests(unittest.TestCase):
    def test_render_truncates_to_max(self) -> None:
        skills = [Skill(skill_id=f"s{i}", name=f"skill-{i}") for i in range(10)]
        rendered = render_agent_skills(skills, max_skills=3)
        self.assertEqual(rendered.count("\n") + 1, 3)
        self.assertIn("skill-0", rendered)
        self.assertNotIn("skill-5", rendered)

    def test_render_empty_returns_empty(self) -> None:
        self.assertEqual(render_agent_skills([]), "")

    def test_relevant_skills_filters_by_trigger(self) -> None:
        a = Skill(skill_id="a", name="海报排版", triggers=["海报"])
        b = Skill(skill_id="b", name="代码评审", triggers=["代码"])
        result = relevant_skills_for_text([a, b], "今天要给活动做一张海报")
        self.assertEqual([s.skill_id for s in result], ["a"])


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------
class SkillRouterIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.global_dir = os.path.join(self._tmp.name, "skills")
        self.memory_dir = os.path.join(self._tmp.name, "memory")
        _seed_global_skill(
            self.global_dir,
            "poster-grid",
            name="海报网格",
            triggers=["海报", "排版"],
        )
        self.registry = SkillRegistry(global_dir=self.global_dir, memory_dir=self.memory_dir)

    def test_self_driven_brief_includes_relevant_skill(self) -> None:
        # Imports here to keep the schema tests independent of router wiring.
        from gaworld.work.queue import WorkQueue
        from gaworld.work.router import RealWorkRouter
        from gaworld.work.schemas import AgentCapabilities

        queue_path = os.path.join(self._tmp.name, "queue.jsonl")
        queue = WorkQueue(queue_path)
        caps = AgentCapabilities(
            agent_id=2,
            job_label="ui_designer",
            skills=["排版"],
            interests=[],
            deliverables=["poster_svg"],
            adapter_priority=["web_design"],
            notes="设计师",
        )
        agent: dict[str, Any] = {
            "id": 2,
            "name": "测试设计师",
            "job": "UI 设计师",
            "skill_ids": ["poster-grid"],
            "state": {},
        }
        router = RealWorkRouter(
            queue=queue,
            market=None,
            capabilities={2: caps},
            config={"enabled": True},
            skill_registry=self.registry,
        )
        outcome = router.maybe_dispatch(
            agent,
            activity="工作",
            chosen_action="给社区活动做一张海报",
            sim_day=3,
            sim_time="10:00",
        )
        self.assertIsNotNone(outcome)
        # Pull the brief back out of the queue.
        briefs = list(queue.all_briefs())
        self.assertEqual(len(briefs), 1)
        brief = briefs[0]
        self.assertIn("【可用技能】", brief.brief_text)
        self.assertIn("海报网格", brief.brief_text)


if __name__ == "__main__":
    unittest.main()
