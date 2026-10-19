"""Work finds its own skills: library search, the online market, use → attach.

Covers:
* ranking (:mod:`gaworld.skills.search`);
* the registry's extra directories (``<name>/SKILL.md``) and searchable list;
* the router picking an *unattached* library skill and recording it;
* :class:`gaworld.skills.market.SkillMarket` against a fake HTTP layer
  (no real network);
* the worker's brief hook and the ingest step attaching used skills.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from typing import Any

from gaworld.skills import Skill, SkillRegistry
from gaworld.skills.market import SkillMarket
from gaworld.skills.schemas import dump_skill_markdown
from gaworld.skills.search import score_skill, search_skills
from gaworld.work.adapters.base import make_ok
from gaworld.work.ingest import absorb_completed_for
from gaworld.work.queue import WorkQueue
from gaworld.work.router import RealWorkRouter
from gaworld.work.schemas import AgentCapabilities, MarketJob, WorkBrief
from gaworld.work.skill_lookup import SKILLS_PER_BRIEF, make_market_hook
from gaworld.work.worker import WorkerPool


def _skill(skill_id: str, name: str, *, description: str = "", triggers: list[str] | None = None) -> Skill:
    return Skill(
        skill_id=skill_id, name=name, description=description, body=f"{name} 的步骤", triggers=triggers or []
    )


def _write(directory: str, skill: Skill) -> None:
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, f"{skill.skill_id}.md"), "w", encoding="utf-8") as f:
        f.write(dump_skill_markdown(skill))


def _brief(**overrides: Any) -> WorkBrief:
    payload: dict[str, Any] = {
        "task_id": "wt_test",
        "agent_id": 2,
        "sim_day": 1,
        "sim_time": "10:00",
        "activity": "工作",
        "chosen_action": "做海报",
        "deliverable": "poster_svg",
        "adapter": "web_design",
        "brief_text": "【任务】做海报",
        "estimated_minutes": 30,
        "submitted_at": time.time(),
    }
    payload.update(overrides)
    return WorkBrief(**payload)


class FakeHttp:
    """Answers URLs from a dict; records every request."""

    def __init__(self, pages: dict[str, tuple[int, str]]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> tuple[int, str]:
        self.calls.append(url)
        for prefix, answer in self.pages.items():
            if url.startswith(prefix):
                return answer
        return 404, "404: Not Found"


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
class RankingTests(unittest.TestCase):
    def test_better_match_ranks_first_and_misses_are_dropped(self) -> None:
        poster = _skill("poster", "海报网格", triggers=["海报", "排版"])
        code = _skill("code", "代码评审", triggers=["代码"])
        layout = _skill("layout", "版式", description="做排版的小窍门")
        ranked = search_skills([layout, code, poster], "给活动做一张海报，注意排版", keywords=["排版"])
        self.assertEqual([s.skill_id for s in ranked], ["poster", "layout"])

    def test_short_ascii_keywords_are_ignored(self) -> None:
        skill = _skill("build", "build tool", description="builds things")
        self.assertEqual(score_skill(skill, "", keywords=["ui"]), 0)
        self.assertEqual(score_skill(skill, "", keywords=["build"]), 1)

    def test_ties_keep_candidate_order_and_limit_applies(self) -> None:
        a, b, c = (_skill(i, i, triggers=["海报"]) for i in ("a", "b", "c"))
        self.assertEqual([s.skill_id for s in search_skills([b, a, c], "海报", limit=2)], ["b", "a"])


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class RegistrySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.global_dir = os.path.join(self.root, "skills")
        self.extra_dir = os.path.join(self.root, "extra")
        _write(self.global_dir, _skill("poster", "海报网格", triggers=["海报"]))
        os.makedirs(os.path.join(self.extra_dir, "canvas-design"))
        with open(os.path.join(self.extra_dir, "canvas-design", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: canvas-design\ndescription: Create a poster\nlicense: MIT\n---\n\n# Canvas\n")
        _write(self.extra_dir, _skill("poster", "外部同名", triggers=["海报"]))
        self.registry = SkillRegistry(
            global_dir=self.global_dir,
            memory_dir=os.path.join(self.root, "memory"),
            extra_dirs=[(self.extra_dir, "external")],
        )

    def test_extra_dirs_load_skill_md_folders_and_global_dir_wins(self) -> None:
        by_id = {s.skill_id: s for s in self.registry.list_global()}
        self.assertEqual(by_id["canvas-design"].description, "Create a poster")
        self.assertEqual(by_id["canvas-design"].origin, "external")
        self.assertEqual(by_id["poster"].name, "海报网格")

    def test_searchable_lists_own_skills_first(self) -> None:
        self.registry.save_private(2, _skill("", "我的海报法", triggers=["海报"]))
        agent = {"id": 2, "skill_ids": ["canvas-design"]}
        ids = [s.skill_id for s in self.registry.list_searchable(agent)]
        self.assertEqual(ids[:2], ["我的海报法", "canvas-design"])
        self.assertIn("poster", ids[2:])

    def test_register_global_makes_a_skill_attachable(self) -> None:
        agent: dict[str, Any] = {"id": 2}
        self.assertFalse(self.registry.attach_to_agent(agent, "new-one"))
        self.registry.register_global(_skill("new-one", "新技能"))
        self.assertTrue(self.registry.attach_to_agent(agent, "new-one"))


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
class RouterSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        global_dir = os.path.join(self.root, "skills")
        _write(global_dir, _skill("poster-grid", "海报网格", triggers=["海报"]))
        _write(global_dir, _skill("code-review", "代码评审", triggers=["代码"]))
        _write(global_dir, _skill("brand", "品牌视觉", description="品牌色与视觉识别"))
        self.registry = SkillRegistry(
            global_dir=global_dir, memory_dir=os.path.join(self.root, "memory"), extra_dirs=[]
        )
        self.queue = WorkQueue(os.path.join(self.root, "queue.jsonl"))
        caps = AgentCapabilities(
            agent_id=2,
            job_label="ui_designer",
            skills=["排版"],
            deliverables=["poster_svg"],
            adapter_priority=["web_design"],
            notes="设计师",
        )
        self.caps = caps
        self.agent: dict[str, Any] = {"id": 2, "name": "小王", "job": "设计师", "state": {}}

    def _router(self) -> RealWorkRouter:
        return RealWorkRouter(
            queue=self.queue,
            market=None,
            capabilities={2: self.caps},
            config={"enabled": True},
            skill_registry=self.registry,
        )

    def test_unattached_library_skill_is_found_and_recorded(self) -> None:
        router = self._router()
        outcome = router.maybe_dispatch(
            self.agent, activity="工作", chosen_action="给社区活动做一张海报", sim_day=1, sim_time="10:00"
        )
        self.assertIsNotNone(outcome)
        (brief,) = list(self.queue.all_briefs())
        self.assertEqual(brief.skill_ids, ["poster-grid"])
        self.assertIn("【可用技能】", brief.brief_text)
        self.assertIn("海报网格", brief.brief_text)
        self.assertNotIn("代码评审", brief.brief_text)

    def test_market_job_required_skills_count_as_keywords(self) -> None:
        job = MarketJob(
            job_id="mj",
            title="新品发布",
            description="做一版",
            deliverable="html_landing",
            required_skills=["品牌色"],
        )
        brief = self._router()._brief_from_market_job(self.agent, self.caps, job, 1, "10:00")
        assert brief is not None
        self.assertEqual(brief.skill_ids, ["brand"])

    def test_auto_search_off_keeps_the_old_attached_only_behaviour(self) -> None:
        router = self._router()
        router._skills_auto_search = False
        router.maybe_dispatch(
            self.agent, activity="工作", chosen_action="给社区活动做一张海报", sim_day=1, sim_time="10:00"
        )
        (brief,) = list(self.queue.all_briefs())
        self.assertEqual(brief.skill_ids, [])
        self.assertNotIn("【可用技能】", brief.brief_text)


# ---------------------------------------------------------------------------
# Online market
# ---------------------------------------------------------------------------
_SEARCH_URL = "https://skills.sh/api/search?q=poster%20design"
_RAW = "https://raw.githubusercontent.com"


def _search_page(*entries: dict[str, Any]) -> tuple[int, str]:
    return 200, json.dumps({"skills": list(entries)})


class MarketTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = os.path.join(tmp.name, "market")
        self.http = FakeHttp(
            {
                _SEARCH_URL: _search_page(
                    {"source": "acme/skills", "skillId": "poster-kit", "installs": 5000},
                    {"source": "acme/skills", "skillId": "tiny", "installs": 3},
                    {"source": "../evil", "skillId": "x", "installs": 9000},
                    {"source": "big/popular", "skillId": "grill", "installs": 900000},
                ),
                f"{_RAW}/acme/skills/HEAD/skills/poster-kit/SKILL.md": (
                    200,
                    "---\nname: poster-kit\ndescription: >-\n---\n\n# Poster kit\n\nLay out a poster design fast.\n",
                ),
                f"{_RAW}/big/popular/HEAD/grill/SKILL.md": (
                    200,
                    "---\nname: grill\ndescription: Interview the user hard\n---\n\nAsk questions.\n",
                ),
            }
        )
        self.market = SkillMarket(self.cache, min_installs=100, http_get=self.http)

    def test_find_filters_unpopular_unsafe_and_irrelevant_entries(self) -> None:
        found = self.market.find("poster design", limit=3)
        self.assertEqual([s.skill_id for s in found], ["acme__skills__poster-kit"])
        skill = found[0]
        self.assertEqual(skill.origin, "market")
        self.assertEqual(skill.description, "Lay out a poster design fast.")
        self.assertFalse(any("evil" in url or "tiny" in url for url in self.http.calls))
        folder = os.path.join(self.cache, "acme__skills__poster-kit")
        self.assertTrue(os.path.isfile(os.path.join(folder, "SKILL.md")))
        with open(os.path.join(folder, "source.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["installs"], 5000)

    def test_second_run_works_from_the_cache_without_network(self) -> None:
        self.market.find("poster design")
        offline = SkillMarket(self.cache, http_get=FakeHttp({}))
        self.assertEqual(
            [s.skill_id for s in offline.find("poster design", limit=1)], ["acme__skills__poster-kit"]
        )
        self.assertEqual(offline._get.calls, [])  # type: ignore[attr-defined]

    def test_failed_search_is_not_cached(self) -> None:
        down = SkillMarket(self.cache, http_get=FakeHttp({_SEARCH_URL: (503, "")}))
        self.assertEqual(down.find("poster design"), [])
        self.assertFalse(os.path.exists(os.path.join(self.cache, "_search_cache.json")))

    def test_cached_market_skills_join_the_library(self) -> None:
        self.market.find("poster design")
        registry = SkillRegistry(
            global_dir=os.path.join(self.cache, "none"),
            memory_dir=self.cache,
            extra_dirs=[(self.cache, "market")],
        )
        self.assertIn("acme__skills__poster-kit", [s.skill_id for s in registry.list_global()])

    def test_unusual_layout_is_found_through_the_repo_tree(self) -> None:
        tree = {"tree": [{"path": "README.md"}, {"path": "guides/design/deep-kit/SKILL.md"}]}
        http = FakeHttp(
            {
                "https://api.github.com/repos/odd/repo/git/trees/HEAD": (200, json.dumps(tree)),
                f"{_RAW}/odd/repo/HEAD/guides/design/deep-kit/SKILL.md": (
                    200,
                    "---\nname: deep-kit\ndescription: Poster design, the long way\n---\n\nSteps.\n",
                ),
            }
        )
        market = SkillMarket(self.cache, http_get=http)
        skill = market.fetch({"source": "odd/repo", "skillId": "deep-kit", "installs": 500})
        assert skill is not None
        self.assertEqual(skill.description, "Poster design, the long way")
        with open(os.path.join(self.cache, "odd__repo__deep-kit", "source.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)["url"].endswith("guides/design/deep-kit/SKILL.md"))

    def test_one_shared_word_is_not_enough_and_forks_are_dropped(self) -> None:
        page = "---\nname: kit\ndescription: {}\n---\n\nSteps.\n"
        http = FakeHttp(
            {
                _SEARCH_URL: _search_page(
                    {"source": "a/r", "skillId": "kit", "installs": 900},
                    {"source": "b/r", "skillId": "kit", "installs": 800},
                    {"source": "c/r", "skillId": "kit", "installs": 700},
                ),
                f"{_RAW}/a/r/HEAD/skills/kit/SKILL.md": (200, page.format("Interior design ideas")),
                f"{_RAW}/b/r/HEAD/skills/kit/SKILL.md": (200, page.format("Poster design kit")),
                f"{_RAW}/c/r/HEAD/skills/kit/SKILL.md": (200, page.format("Poster design kit, forked")),
            }
        )
        found = SkillMarket(self.cache, http_get=http).find("poster design", limit=3)
        self.assertEqual([s.skill_id for s in found], ["b__r__kit"])


class MarketHookTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.registry = SkillRegistry(
            global_dir=os.path.join(self.root, "skills"),
            memory_dir=os.path.join(self.root, "memory"),
            extra_dirs=[],
        )
        http = FakeHttp(
            {
                _SEARCH_URL: _search_page(
                    {"source": "acme/skills", "skillId": "poster-kit", "installs": 5000}
                ),
                f"{_RAW}/acme/skills/HEAD/skills/poster-kit/SKILL.md": (
                    200,
                    "---\nname: poster-kit\ndescription: Poster design steps\n---\n\n1. Grid.\n",
                ),
            }
        )
        self.market = SkillMarket(os.path.join(self.root, "market"), http_get=http)

    def test_hook_fills_free_slots_and_registers_the_skill(self) -> None:
        hook = make_market_hook(self.market, self.registry)
        out = hook(_brief(skill_ids=["poster-grid"], brief_text="【任务】做海报\n【可用技能】\n- 海报网格"))
        self.assertEqual(out.skill_ids, ["poster-grid", "acme__skills__poster-kit"])
        self.assertEqual(out.brief_text.count("【可用技能】"), 1)
        self.assertIn("poster-kit：Poster design steps", out.brief_text)
        self.assertIsNotNone(self.registry.get("acme__skills__poster-kit"))

    def test_hook_adds_the_header_when_the_brief_had_no_skills(self) -> None:
        out = make_market_hook(self.market, self.registry)(_brief())
        self.assertIn("\n【可用技能】\n- poster-kit", out.brief_text)

    def test_full_brief_or_unknown_deliverable_skips_the_market(self) -> None:
        hook = make_market_hook(self.market, self.registry)
        full = _brief(skill_ids=[f"s{i}" for i in range(SKILLS_PER_BRIEF)])
        self.assertIs(hook(full), full)
        odd = _brief(deliverable="video")
        self.assertIs(hook(odd), odd)
        self.assertEqual(self.market._get.calls, [])  # type: ignore[attr-defined]

    def test_market_error_leaves_the_brief_alone(self) -> None:
        def boom(url: str, timeout: float) -> tuple[int, str]:
            raise ConnectionError("offline")

        hook = make_market_hook(SkillMarket(os.path.join(self.root, "m2"), http_get=boom), self.registry)
        brief = _brief()
        self.assertIs(hook(brief), brief)


# ---------------------------------------------------------------------------
# Worker + ingest
# ---------------------------------------------------------------------------
class _EchoAdapter:
    name = "web_design"
    supported_deliverables = frozenset({"poster_svg"})

    def __init__(self) -> None:
        self.seen: list[WorkBrief] = []

    def run(self, brief: WorkBrief, ctx: Any) -> Any:
        self.seen.append(brief)
        return make_ok(brief, ["poster.svg"], "完成海报", time.time())


class WorkerAndIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        global_dir = os.path.join(self.root, "skills")
        _write(global_dir, _skill("poster-grid", "海报网格", triggers=["海报"]))
        self.registry = SkillRegistry(
            global_dir=global_dir, memory_dir=os.path.join(self.root, "memory"), extra_dirs=[]
        )
        self.queue = WorkQueue(os.path.join(self.root, "queue.jsonl"))
        self.adapter = _EchoAdapter()

    def _pool(self, hook: Any) -> WorkerPool:
        return WorkerPool(
            queue=self.queue,
            adapters={"web_design": self.adapter},
            ctx_factory=lambda name: None,
            brief_hook=hook,
        )

    def test_hook_runs_before_the_adapter_and_result_keeps_skill_ids(self) -> None:
        self.queue.submit(_brief())
        pool = self._pool(lambda b: _brief(skill_ids=["poster-grid"], brief_text=b.brief_text + "!"))
        self.assertEqual(pool.drain_sync(), 1)
        self.assertTrue(self.adapter.seen[0].brief_text.endswith("!"))
        (result,) = self.queue.drain_completed_for(2)
        self.assertEqual(result.skill_ids, ["poster-grid"])

    def test_a_raising_hook_does_not_cost_the_work(self) -> None:
        def broken(brief: WorkBrief) -> WorkBrief:
            raise RuntimeError("nope")

        self.queue.submit(_brief())
        self._pool(broken).drain_sync()
        (result,) = self.queue.drain_completed_for(2)
        self.assertEqual(result.status, "ok")

    def test_successful_work_attaches_the_skill_and_notes_it_in_memory(self) -> None:
        self.queue.submit(_brief(skill_ids=["poster-grid"]))
        self._pool(None).drain_sync()
        agent: dict[str, Any] = {"id": 2, "state": {}}
        absorb_completed_for(
            agent, queue=self.queue, market=None, sim_day=1, sim_time="11:00", skill_registry=self.registry
        )
        self.assertEqual(agent["skill_ids"], ["poster-grid"])
        entry = agent["memory"][-1]
        self.assertIn("运用了技能：海报网格", entry["text"])
        self.assertEqual(entry["skill_ids"], ["poster-grid"])

    def test_failed_work_does_not_attach(self) -> None:
        from gaworld.work.adapters.base import make_failed

        brief = _brief(skill_ids=["poster-grid"])
        self.queue.submit(brief)
        self.queue.claim_next()
        self.queue.record_result(make_failed(brief, "boom", time.time()))
        agent: dict[str, Any] = {"id": 2, "state": {}}
        absorb_completed_for(
            agent, queue=self.queue, market=None, sim_day=1, sim_time="11:00", skill_registry=self.registry
        )
        self.assertNotIn("skill_ids", agent)


if __name__ == "__main__":
    unittest.main()
