# Contextual Curiosity → RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let simulation agents propose context-driven search keywords from what they are currently doing/experiencing, gate web-search via a cheap heuristic budget, and store the retrieved knowledge into their RAG — reusing the existing `info_seek` web-search + vector-DB plumbing.

**Architecture:** A new focused module `gaworld/sim/_curiosity.py` holds three units: a pure context assembler, a heuristic trigger gate (no LLM, budget-aware), and an LLM keyword proposer (called only after the gate passes). The existing `gaworld/sim/_news.py` gains an optional `keywords=` parameter so proposed queries flow through unchanged web-search + RAG-write code. The main loop in `generative_city_sim.py` wires per-agent daily budgets and event-driven seeks. All new behavior is config-gated under `behavior.info_seek`, default-on, with full fallback to existing behavior when disabled.

**Tech Stack:** Python 3.10+, `unittest` + `unittest.mock.patch`, existing `gaworld.llm.providers.call_llm` (module-attribute dispatch for mockability), existing `gaworld.memory.store` (`save_agent_memory`, `vector_db_add_entry`).

**Spec:** `docs/superpowers/specs/2026-06-22-contextual-curiosity-rag-design.md`

---

## File Structure

- **Create** `gaworld/sim/_curiosity.py` — context assembly + heuristic gate + LLM keyword proposer. One responsibility: "decide to seek knowledge and what to seek." No HTTP, no vector-DB writes.
- **Create** `tests/test_curiosity_keywords.py` — unit tests for the new module.
- **Create** `tests/test_curiosity_integration.py` — one integration test: a fresh life-event triggers an extra info-seek that writes a RAG entry.
- **Modify** `gaworld/sim/_news.py` — `_choose_info_target` and `info_seek_and_store` gain optional `keywords=None`; when provided, build the query from keywords and go straight to web-search.
- **Modify** `gaworld/settings/behavior.py` — add new config keys under `behavior.info_seek`.
- **Modify** `generative_city_sim.py` — import the new module functions, add per-agent daily `curiosity_budget`, wire the gate + proposer into the tick loop, and route scheduled seeks through the proposer when `contextual_keywords` is on.

**Key conventions to follow (verified in codebase):**
- LLM is called as `_llm_providers.call_llm(prompt, task="...", agent_id=agent["id"])` via `from gaworld.llm import providers as _llm_providers` (module-attribute dispatch so tests can reassign `providers.call_llm`).
- Tests patch with `unittest.mock.patch.object(module, "name", ...)`. For sim-level wiring, tests import `generative_city_sim as sim` and patch `sim.<name>`.
- JSON arrays from the LLM are extracted with `_extract_json_array_block` (in `gaworld/sim/_schedule.py`) and sanitized with `_sanitize_extra_text` (in `gaworld/sim/_utils.py`).
- `growth_focus(profile, limit=2)` (in `gaworld/interests.py`) returns top growth-focus term names.

---

## Task 1: New module skeleton + pure context assembler

**Files:**
- Create: `gaworld/sim/_curiosity.py`
- Test: `tests/test_curiosity_keywords.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_curiosity_keywords.py`:

```python
import unittest

from gaworld.sim import _curiosity


def _agent():
    return {
        "id": 7,
        "name": "测试居民",
        "age": 31,
        "job": "外卖骑手",
        "personality": "务实，关注收入",
        "daily_life": "每天跑单，晚上看手机资讯",
        "values": "重视收入稳定",
        "state": {
            "stress": 0.7,
            "econ_security": 0.4,
            "platform_dependence": 0.6,
            "risk_preference": 0.5,
        },
        "growth_profile": {"items": [{"name": "理财", "kind": "skill", "priority": 1, "level": 0.2}]},
        "memory": [],
    }


class TestAssembleContext(unittest.TestCase):
    def test_assembles_four_signal_groups(self):
        ctx = _curiosity.assemble_curiosity_context(
            _agent(),
            scheduled_activity="跑单途中",
            recent_events=["平台调整了配送费规则"],
            day=2,
            time_str="12:30",
        )
        self.assertEqual(ctx["activity"], "跑单途中")
        self.assertIn("平台调整了配送费规则", ctx["recent_events"])
        self.assertAlmostEqual(ctx["state"]["stress"], 0.7)
        self.assertIn("理财", ctx["growth_focus"])
        self.assertEqual(ctx["day"], 2)
        self.assertEqual(ctx["time_str"], "12:30")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curiosity_keywords.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaworld.sim._curiosity'` (or `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Create `gaworld/sim/_curiosity.py`:

```python
"""Contextual curiosity / knowledge-seeking helpers.

Three concerns, isolated from the news/HTTP plumbing in ``_news.py``:

1. ``assemble_curiosity_context`` — pure: pack the agent's current
   activity, recent events, emotional state, and growth focus into a
   compact dict.
2. ``should_seek_knowledge`` — cheap heuristic gate (no LLM), budget-aware.
3. ``propose_contextual_keywords`` — LLM, called only after the gate
   passes; falls back to the existing template query builder.

LLM access uses module-attribute dispatch (``_llm_providers.call_llm``)
so the test mock installer's ``providers.call_llm = mock`` reassignment
is picked up.
"""

from __future__ import annotations

import json
import random
from typing import Any

from gaworld.llm import providers as _llm_providers
from gaworld.sim._schedule import _extract_json_array_block
from gaworld.sim._utils import _sanitize_extra_text


def assemble_curiosity_context(
    agent: dict[str, Any],
    *,
    scheduled_activity: str = "",
    recent_events: list[str] | None = None,
    day: int | None = None,
    time_str: str | None = None,
) -> dict[str, Any]:
    """Pack the four signal groups into a compact context dict (pure)."""
    state = agent.get("state", {}) if isinstance(agent, dict) else {}
    try:
        from gaworld.interests import growth_focus
        focus = growth_focus(agent.get("growth_profile"), limit=3)
    except Exception:  # pragma: no cover - defensive
        focus = []
    return {
        "activity": str(scheduled_activity or "").strip(),
        "recent_events": [str(e).strip() for e in (recent_events or []) if str(e).strip()],
        "state": {
            "stress": float(state.get("stress", 0.5)),
            "econ_security": float(state.get("econ_security", 0.5)),
        },
        "growth_focus": focus,
        "day": day,
        "time_str": time_str,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_curiosity_keywords.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gaworld/sim/_curiosity.py tests/test_curiosity_keywords.py
git commit -m "feat(curiosity): pure context assembler for knowledge-seeking"
```

---

## Task 2: Heuristic trigger gate

**Files:**
- Modify: `gaworld/sim/_curiosity.py`
- Test: `tests/test_curiosity_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_curiosity_keywords.py` (before the `if __name__` line):

```python
class TestShouldSeekKnowledge(unittest.TestCase):
    CONFIG = {
        "event_driven": {
            "enabled": True,
            "stress_threshold": 0.6,
            "curiosity_threshold": 0.6,
            "trigger_chance_on_event": 0.5,
        }
    }

    def _ctx(self, **over):
        base = {
            "activity": "跑单途中",
            "recent_events": [],
            "state": {"stress": 0.3, "econ_security": 0.5},
            "growth_focus": [],
            "day": 1,
            "time_str": "10:00",
        }
        base.update(over)
        return base

    def test_no_trigger_when_disabled(self):
        cfg = {"event_driven": {"enabled": False}}
        ok, reason = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(recent_events=["x"]), budget_left=5, config=cfg
        )
        self.assertFalse(ok)

    def test_no_trigger_when_budget_exhausted(self):
        ok, _ = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(recent_events=["x"]), budget_left=0, config=self.CONFIG
        )
        self.assertFalse(ok)

    def test_no_trigger_when_no_hard_condition(self):
        # stress low, no events, no growth focus -> no hard condition
        ok, _ = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(state={"stress": 0.1, "econ_security": 0.5}, growth_focus=[]),
            budget_left=5, config=self.CONFIG,
        )
        self.assertFalse(ok)

    def test_event_triggers_when_dice_low(self):
        random.seed(0)
        # With trigger_chance 1.0 a hard condition (fresh event) always fires.
        cfg = {"event_driven": {"enabled": True, "stress_threshold": 0.6,
                                "curiosity_threshold": 0.6, "trigger_chance_on_event": 1.0}}
        ok, reason = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(recent_events=["平台调整配送费"]), budget_left=5, config=cfg
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "event")

    def test_high_stress_is_hard_condition(self):
        cfg = {"event_driven": {"enabled": True, "stress_threshold": 0.6,
                                "curiosity_threshold": 0.6, "trigger_chance_on_event": 1.0}}
        ok, reason = _curiosity.should_seek_knowledge(
            _agent(), self._ctx(state={"stress": 0.8, "econ_security": 0.4}),
            budget_left=5, config=cfg,
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "stress")
```

Add `import random` at the top of the test file (next to `import unittest`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curiosity_keywords.py::TestShouldSeekKnowledge -v`
Expected: FAIL with `AttributeError: module 'gaworld.sim._curiosity' has no attribute 'should_seek_knowledge'`.

- [ ] **Step 3: Write minimal implementation**

Add to `gaworld/sim/_curiosity.py` (after `assemble_curiosity_context`):

```python
def should_seek_knowledge(
    agent: dict[str, Any],
    context: dict[str, Any],
    *,
    budget_left: int,
    config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Cheap heuristic gate. Returns ``(trigger?, reason)``.

    A hard condition must hold first (fresh event / high stress / high
    estimated curiosity / salient growth focus); then a single
    ``trigger_chance_on_event`` dice roll smooths the frequency.
    """
    cfg = (config or {}).get("event_driven", {}) or {}
    if not cfg.get("enabled", True):
        return False, ""
    if budget_left <= 0:
        return False, ""

    stress_threshold = float(cfg.get("stress_threshold", 0.6))
    curiosity_threshold = float(cfg.get("curiosity_threshold", 0.6))

    reason = ""
    if context.get("recent_events"):
        reason = "event"
    elif float(context.get("state", {}).get("stress", 0.5)) >= stress_threshold:
        reason = "stress"
    elif _curiosity_score(agent) >= curiosity_threshold:
        reason = "curiosity"
    elif context.get("growth_focus"):
        reason = "growth"
    if not reason:
        return False, ""

    chance = float(cfg.get("trigger_chance_on_event", 0.5))
    if random.random() > chance:
        return False, ""
    return True, reason


def _curiosity_score(agent: dict[str, Any]) -> float:
    """Reuse the existing curiosity estimator from the news module."""
    from gaworld.sim._news import _estimate_curiosity
    return _estimate_curiosity(agent)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_curiosity_keywords.py::TestShouldSeekKnowledge -v`
Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add gaworld/sim/_curiosity.py tests/test_curiosity_keywords.py
git commit -m "feat(curiosity): heuristic budget-aware trigger gate"
```

---

## Task 3: LLM contextual keyword proposer with fallback

**Files:**
- Modify: `gaworld/sim/_curiosity.py`
- Test: `tests/test_curiosity_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_curiosity_keywords.py` (before `if __name__`):

```python
from unittest.mock import patch
from gaworld.llm import providers as _providers


class TestProposeKeywords(unittest.TestCase):
    def _ctx(self):
        return {
            "activity": "跑单途中",
            "recent_events": ["平台调整了配送费规则"],
            "state": {"stress": 0.7, "econ_security": 0.4},
            "growth_focus": ["理财"],
            "day": 2,
            "time_str": "12:30",
        }

    def test_parses_json_array(self):
        with patch.object(_providers, "call_llm",
                          return_value='["配送费规则 最新", "骑手收入 政策"]'):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config={})
        self.assertEqual(kws, ["配送费规则 最新", "骑手收入 政策"])

    def test_respects_max(self):
        cfg = {"contextual_max_keywords": 1}
        with patch.object(_providers, "call_llm",
                          return_value='["a 最新", "b 政策", "c 趋势"]'):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config=cfg)
        self.assertEqual(len(kws), 1)

    def test_garbage_falls_back_to_template(self):
        with patch.object(_providers, "call_llm", return_value="抱歉我不知道"):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config={})
        # Fallback returns a non-empty template query string list.
        self.assertTrue(kws)
        self.assertIsInstance(kws[0], str)

    def test_llm_exception_falls_back(self):
        with patch.object(_providers, "call_llm", side_effect=RuntimeError("boom")):
            kws = _curiosity.propose_contextual_keywords(_agent(), self._ctx(), config={})
        self.assertTrue(kws)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curiosity_keywords.py::TestProposeKeywords -v`
Expected: FAIL with `AttributeError: ... has no attribute 'propose_contextual_keywords'`.

- [ ] **Step 3: Write minimal implementation**

Add to `gaworld/sim/_curiosity.py`:

```python
_KEYWORD_PROMPT = """你是{name}，正在生活和工作中。请根据你当前的处境，提出你此刻最想上网查证/了解的搜索关键词。

当前活动：{activity}
最近发生的事：{events}
当前状态：压力={stress:.2f}，经济安全感={econ:.2f}
你正在发展的兴趣/技能：{growth}

要求：
1) 输出 1-{max_items} 个中文搜索关键词，每个 4-16 字，像真实搜索框里会输入的词。
2) 关键词要贴合“你当前的处境”，不要泛泛而谈。
3) 仅输出 JSON 字符串数组，不要输出其他文字。"""


def propose_contextual_keywords(
    agent: dict[str, Any],
    context: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """LLM-propose contextual search keywords; fall back to the template builder."""
    cfg = config or {}
    max_items = max(1, int(cfg.get("contextual_max_keywords", 3)))
    prompt = _KEYWORD_PROMPT.format(
        name=agent.get("name", "该居民"),
        activity=context.get("activity") or "日常活动",
        events="；".join(context.get("recent_events", [])) or "无特别事件",
        stress=float(context.get("state", {}).get("stress", 0.5)),
        econ=float(context.get("state", {}).get("econ_security", 0.5)),
        growth="、".join(context.get("growth_focus", [])) or "无",
        max_items=max_items,
    )
    try:
        response = _llm_providers.call_llm(
            prompt, task="curiosity_keywords", agent_id=agent.get("id")
        )
    except Exception:  # pragma: no cover - defensive; fall back to template
        response = ""

    keywords = _parse_keywords(response, max_items=max_items)
    if keywords:
        return keywords
    return _fallback_keywords(agent, max_items=max_items)


def _parse_keywords(text: str, *, max_items: int) -> list[str]:
    blob = _extract_json_array_block(text or "")
    if not blob:
        return []
    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        cleaned = _sanitize_extra_text(str(item), max_chars=32)
        if cleaned and cleaned not in out:
            out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


def _fallback_keywords(agent: dict[str, Any], *, max_items: int) -> list[str]:
    from gaworld.sim._news import _build_search_query
    query = _build_search_query(agent)
    return [query] if query else []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_curiosity_keywords.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: Commit**

```bash
git add gaworld/sim/_curiosity.py tests/test_curiosity_keywords.py
git commit -m "feat(curiosity): LLM contextual keyword proposer with template fallback"
```

---

## Task 4: `_news.py` accepts proposed keywords

**Files:**
- Modify: `gaworld/sim/_news.py` (`_choose_info_target` ~L367, `info_seek_and_store` ~L487)
- Test: `tests/test_curiosity_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_curiosity_keywords.py` (before `if __name__`):

```python
from gaworld.sim import _news


class TestNewsKeywordsParam(unittest.TestCase):
    def test_choose_info_target_uses_keywords_for_web_search(self):
        captured = {}

        def fake_web_search(query, config=None):
            captured["query"] = query
            return "google", [{"url": "https://ex.com/a", "title": "标题", "snippet": "片段内容"}]

        def fake_excerpt(url, **kw):
            return "这是抓取到的正文内容，足够长用于记忆。"

        with patch.object(_news, "web_search", side_effect=fake_web_search), \
             patch.object(_news, "fetch_news_excerpt", side_effect=fake_excerpt):
            target = _news._choose_info_target(
                agent=_agent(),
                news_cache=[],
                news_sources=[],
                preferred_sites=[],
                keywords=["配送费规则 最新", "骑手收入 政策"],
            )
        self.assertEqual(target["mode"], "web_search")
        self.assertEqual(captured["query"], "配送费规则 最新 骑手收入 政策")
        self.assertEqual(target["url"], "https://ex.com/a")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curiosity_keywords.py::TestNewsKeywordsParam -v`
Expected: FAIL with `TypeError: _choose_info_target() got an unexpected keyword argument 'keywords'`.

- [ ] **Step 3: Write minimal implementation**

In `gaworld/sim/_news.py`, change the `_choose_info_target` signature (currently ends with `config: dict[str, Any] | None = None,`) to add the new parameter:

```python
def _choose_info_target(
    agent: dict[str, Any],
    news_cache: list[dict[str, Any]],
    news_sources: list[str],
    preferred_sites: list[str],
    seen_urls: set[str] | None = None,
    used_queries: set[str] | None = None,
    config: dict[str, Any] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any] | None:
```

Then, immediately after the existing line `interests = _extract_interest_keywords(agent)` near the top of the function body, insert a short-circuit that skips the cached/source-preference branches and goes straight to web-search when keywords are provided:

```python
    if keywords:
        query = " ".join(str(k).strip() for k in keywords if str(k).strip())
        if query:
            return _web_search_target(
                agent=agent,
                query=query,
                interests=interests,
                preferred_sites=preferred_sites,
                seen_urls=seen_urls,
                config=config,
            )
```

Refactor the existing web-search tail of `_choose_info_target` into a reusable helper. The current tail looks like:

```python
    query = _build_search_query(agent, used_queries=used_queries)
    if preferred_sites and random.random() < 0.85:
        query = f"{query} site:{random.choice(preferred_sites)}"
    engine, results = web_search(query, config=config)
    if not results:
        return None
    ranked = []
    ...
    return {
        "mode": "web_search",
        "query": query,
        ...
    }
```

Extract everything from `engine, results = web_search(...)` through the final `return {...}` into a new module-level helper, and have both the keyword path and the template path call it:

```python
def _web_search_target(
    *,
    agent: dict[str, Any],
    query: str,
    interests: list[str],
    preferred_sites: list[str],
    seen_urls: set[str] | None,
    config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    config = config or {}
    seen_urls = seen_urls or set()
    engine, results = web_search(query, config=config)
    if not results:
        return None
    ranked = []
    timeout = int(config.get("content_timeout", config.get("timeout", 8)))
    max_chars = int(config.get("content_max_chars", 2000))
    user_agent = str(config.get("user_agent", "GAWorld/1.0"))
    for item in results:
        url = str(item.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        title = str(item.get("title", "")).strip()
        snippet = str(item.get("snippet", "")).strip()
        excerpt = fetch_news_excerpt(url, timeout=timeout, max_chars=max_chars, user_agent=user_agent)
        content = excerpt or snippet
        if not content:
            continue
        score, matched = _score_news_relevance(url, title, content, interests)
        if preferred_sites and _domain_from_url(url) in preferred_sites:
            score += 0.9
        ranked.append((score + random.random() * 0.03, matched, url, title, content))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    score, matched, url, title, content = ranked[0]
    return {
        "mode": "web_search",
        "query": query,
        "engine": engine,
        "url": url,
        "title": title,
        "content": content,
        "score": score,
        "matched": matched,
    }
```

Then replace the template tail of `_choose_info_target` with:

```python
    query = _build_search_query(agent, used_queries=used_queries)
    if preferred_sites and random.random() < 0.85:
        query = f"{query} site:{random.choice(preferred_sites)}"
    return _web_search_target(
        agent=agent,
        query=query,
        interests=interests,
        preferred_sites=preferred_sites,
        seen_urls=seen_urls,
        config=config,
    )
```

Finally, thread `keywords` through `info_seek_and_store`. Change its signature to add `keywords: list[str] | None = None,` before `config`, and pass it into the `_choose_info_target` call:

```python
    target = _choose_info_target(
        agent=agent,
        news_cache=news_cache or [],
        news_sources=news_sources or [],
        preferred_sites=preferred_sites or [],
        seen_urls=seen_urls or set(),
        used_queries=used_queries or set(),
        config=config,
        keywords=keywords,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_curiosity_keywords.py -v`
Expected: PASS.

Also run the existing news/RAG tests to confirm no regression from the refactor:

Run: `python -m pytest tests/test_bootstrap_external_rag.py -v`
Expected: PASS (the extracted helper preserves behavior).

- [ ] **Step 5: Commit**

```bash
git add gaworld/sim/_news.py tests/test_curiosity_keywords.py
git commit -m "feat(news): info_seek accepts proposed keywords via _web_search_target helper"
```

---

## Task 5: Config keys

**Files:**
- Modify: `gaworld/settings/behavior.py` (`info_seek` block ~L22-43)
- Test: `tests/test_curiosity_keywords.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_curiosity_keywords.py` (before `if __name__`):

```python
from gaworld.settings import behavior as _behavior_settings


class TestConfigDefaults(unittest.TestCase):
    def test_info_seek_has_curiosity_keys(self):
        cfg = _behavior_settings.news_settings()["news"]["info_seek"]
        self.assertTrue(cfg["contextual_keywords"])
        self.assertEqual(cfg["contextual_max_keywords"], 3)
        ev = cfg["event_driven"]
        self.assertTrue(ev["enabled"])
        self.assertEqual(ev["max_extra_seeks_per_day"], 2)
        self.assertAlmostEqual(ev["stress_threshold"], 0.6)
        self.assertAlmostEqual(ev["curiosity_threshold"], 0.6)
        self.assertAlmostEqual(ev["trigger_chance_on_event"], 0.5)
```

Note (verified): the block lives at `news_settings()["news"]["info_seek"]` in `gaworld/settings/behavior.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curiosity_keywords.py::TestConfigDefaults -v`
Expected: FAIL with `KeyError: 'contextual_keywords'`.

- [ ] **Step 3: Write minimal implementation**

In `gaworld/settings/behavior.py`, inside the `"info_seek": { ... }` dict, after the existing `"user_agent": "GAWorld/1.0",` line and before the closing `},`, add:

```python
                "contextual_keywords": True,
                "contextual_max_keywords": 3,
                "event_driven": {
                    "enabled": True,
                    "max_extra_seeks_per_day": 2,
                    "stress_threshold": 0.6,
                    "curiosity_threshold": 0.6,
                    "trigger_chance_on_event": 0.5,
                },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_curiosity_keywords.py::TestConfigDefaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gaworld/settings/behavior.py tests/test_curiosity_keywords.py
git commit -m "feat(settings): contextual_keywords + event_driven config for info_seek"
```

---

## Task 6: Wire into the simulation loop

**Files:**
- Modify: `generative_city_sim.py` (imports ~L272-287; schedule build ~L2971-2994; tick loop ~L3104-3124)
- Test: `tests/test_curiosity_integration.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_curiosity_integration.py`:

```python
import unittest
from unittest.mock import patch

import generative_city_sim as sim


def _agent():
    return {
        "id": 3,
        "name": "测试居民",
        "age": 31,
        "job": "外卖骑手",
        "personality": "务实，关注收入",
        "daily_life": "每天跑单",
        "values": "重视收入稳定",
        "state": {"stress": 0.8, "econ_security": 0.4,
                  "platform_dependence": 0.6, "risk_preference": 0.5},
        "growth_profile": {"items": []},
        "memory": [],
    }


class TestCuriosityTickTrigger(unittest.TestCase):
    def test_fresh_event_triggers_seek_and_writes_rag(self):
        agent = _agent()
        cfg = {
            "contextual_keywords": True,
            "contextual_max_keywords": 2,
            "memory_excerpt_chars": 200,
            "event_driven": {
                "enabled": True,
                "max_extra_seeks_per_day": 2,
                "stress_threshold": 0.6,
                "curiosity_threshold": 0.6,
                "trigger_chance_on_event": 1.0,
            },
        }

        # The seek itself returns a fake memory + log so we only assert wiring.
        def fake_seek(agent, **kw):
            self.assertEqual(kw["keywords"], ["配送费规则 最新", "骑手收入 政策"])
            return "MEM", "LOGLINE\n", "https://ex.com/a", "配送费规则 最新"

        budget = {3: 2}
        with patch.object(sim, "propose_contextual_keywords",
                          return_value=["配送费规则 最新", "骑手收入 政策"]), \
             patch.object(sim, "info_seek_and_store", side_effect=fake_seek):
            triggered = sim._maybe_curiosity_seek(
                agent,
                day=1,
                time_str="12:30",
                scheduled_activity="跑单途中",
                recent_events=["平台调整了配送费规则"],
                news_cache=[],
                news_sources=[],
                preferred_sites=[],
                seen_urls=set(),
                used_queries=set(),
                curiosity_budget=budget,
                config=cfg,
            )

        self.assertTrue(triggered)
        self.assertEqual(budget[3], 1)  # budget decremented


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_curiosity_integration.py -v`
Expected: FAIL with `AttributeError: module 'generative_city_sim' has no attribute '_maybe_curiosity_seek'`.

- [ ] **Step 3: Write minimal implementation**

In `generative_city_sim.py`, extend the existing import block from `gaworld.sim._news` / add a new import. Near the other `from gaworld.sim...` imports (around L272-287), add:

```python
from gaworld.sim._curiosity import (
    assemble_curiosity_context,
    should_seek_knowledge,
    propose_contextual_keywords,
)
```

Then add a module-level orchestrator function (place it near the other info-seek helpers, e.g. just after the `INFO_SEEK_*` constants around L604):

```python
def _maybe_curiosity_seek(
    agent,
    *,
    day,
    time_str,
    scheduled_activity,
    recent_events,
    news_cache,
    news_sources,
    preferred_sites,
    seen_urls,
    used_queries,
    curiosity_budget,
    config,
):
    """Event-driven contextual seek. Returns True if a seek fired.

    Writes nothing itself beyond delegating to ``info_seek_and_store``;
    decrements the per-agent daily budget on a real fire.
    """
    if not config.get("contextual_keywords", True):
        return False
    agent_id = agent["id"]
    budget_left = int(curiosity_budget.get(agent_id, 0))
    context = assemble_curiosity_context(
        agent,
        scheduled_activity=scheduled_activity or "",
        recent_events=recent_events or [],
        day=day,
        time_str=time_str,
    )
    trigger, _reason = should_seek_knowledge(
        agent, context, budget_left=budget_left, config=config
    )
    if not trigger:
        return False
    keywords = propose_contextual_keywords(agent, context, config=config)
    if not keywords:
        return False
    memory_entry, info_log, result_url, query = info_seek_and_store(
        agent,
        day=day,
        time_str=time_str,
        news_cache=news_cache,
        news_sources=news_sources,
        preferred_sites=preferred_sites,
        seen_urls=seen_urls,
        used_queries=used_queries,
        keywords=keywords,
        config=config,
    )
    if query:
        used_queries.add(query)
    if result_url:
        seen_urls.add(result_url)
    if not memory_entry:
        return False
    curiosity_budget[agent_id] = budget_left - 1
    if info_log:
        print(info_log)
        daily_logs = globals().get("_NOOP_DAILY_LOGS")  # placeholder, see Step 3 note
    return True
```

**Step 3 note — logging:** the helper above must write the log line into the caller's `daily_logs[agent_id]` and `append_agent_log(agent, info_log)` exactly like the scheduled path at L3119-3122. Since `daily_logs` and `append_agent_log` are loop-local/module-level respectively, pass `daily_logs` in as a parameter rather than using the placeholder. Update the signature to add `daily_logs=None` and replace the trailing `if info_log:` block with:

```python
    if info_log:
        print(info_log)
        if daily_logs is not None:
            daily_logs[agent_id] += info_log
        append_agent_log(agent, info_log)
    return True
```

(Then drop the placeholder line. The integration test passes `daily_logs` implicitly as `None`, which is fine — it only asserts the trigger + budget.)

Now build the daily budget alongside `info_schedule`. In the schedule-build block (~L2971-2994), after `info_schedule = {}` add:

```python
        curiosity_budget = {}
```

and inside the `for agent in agents:` loop that builds `info_schedule`, after computing `curiosity = _estimate_curiosity(agent)`, add:

```python
                ev_cfg = INFO_SEEK_CONFIG.get("event_driven", {})
                curiosity_budget[agent["id"]] = int(ev_cfg.get("max_extra_seeks_per_day", 2))
```

Finally, call the orchestrator in the tick loop. Immediately after the existing scheduled `if time_str in info_schedule.get(agent_id, set()):` block (ends ~L3124, after the `append_agent_log(agent, info_log)` for that block), add:

```python
                _maybe_curiosity_seek(
                    agent,
                    day=day,
                    time_str=time_str,
                    scheduled_activity=get_activity_for_time(schedule_map[agent_id], time_str),
                    recent_events=[
                        _format_external_env_event(ev) for ev in (env_events or [])
                    ],
                    news_cache=news_cache,
                    news_sources=news_sources,
                    preferred_sites=preferred_sites_map.get(agent_id, []),
                    seen_urls=daily_info_seen[agent_id],
                    used_queries=daily_query_seen[agent_id],
                    curiosity_budget=curiosity_budget,
                    config=INFO_SEEK_CONFIG,
                    daily_logs=daily_logs,
                )
```

(`get_activity_for_time`, `schedule_map`, `_format_external_env_event`, `env_events`, `preferred_sites_map`, `daily_info_seen`, `daily_query_seen`, `news_cache`, `news_sources` are all already in scope at that point in the loop — verified against L3104-3145.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_curiosity_integration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add generative_city_sim.py tests/test_curiosity_integration.py
git commit -m "feat(sim): wire event-driven contextual curiosity seek into tick loop"
```

---

## Task 7: Route scheduled seeks through the proposer + full regression

**Files:**
- Modify: `generative_city_sim.py` (scheduled seek call ~L3104-3115)
- Test: full suite

- [ ] **Step 1: Make scheduled seeks contextual**

In the existing scheduled block (`if time_str in info_schedule.get(agent_id, set()):`), when `contextual_keywords` is enabled, propose keywords first and pass them in. Replace the current `info_seek_and_store(...)` call with:

```python
                if time_str in info_schedule.get(agent_id, set()):
                    scheduled_keywords = None
                    if INFO_SEEK_CONFIG.get("contextual_keywords", True):
                        _ctx = assemble_curiosity_context(
                            agent,
                            scheduled_activity=get_activity_for_time(schedule_map[agent_id], time_str),
                            recent_events=[
                                _format_external_env_event(ev) for ev in (env_events or [])
                            ],
                            day=day,
                            time_str=time_str,
                        )
                        scheduled_keywords = propose_contextual_keywords(
                            agent, _ctx, config=INFO_SEEK_CONFIG
                        ) or None
                    _, info_log, result_url, query = info_seek_and_store(
                        agent,
                        day=day,
                        time_str=time_str,
                        news_cache=news_cache,
                        news_sources=news_sources,
                        preferred_sites=preferred_sites_map.get(agent_id, []),
                        seen_urls=daily_info_seen[agent_id],
                        used_queries=daily_query_seen[agent_id],
                        keywords=scheduled_keywords,
                        config=INFO_SEEK_CONFIG,
                    )
                    if query:
                        daily_query_seen[agent_id].add(query)
                    if result_url:
                        daily_info_seen[agent_id].add(result_url)
                    if info_log:
                        print(info_log)
                        daily_logs[agent_id] += info_log
                        append_agent_log(agent, info_log)
```

(This preserves the existing keyword-args; `keywords=None` when the flag is off means behavior is identical to before.)

- [ ] **Step 2: Run the new module + integration tests**

Run: `python -m pytest tests/test_curiosity_keywords.py tests/test_curiosity_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Run the focused regression set**

Run: `python -m pytest tests/test_bootstrap_external_rag.py tests/test_gaworld_settings.py tests/test_e2e_smoke.py -v`
Expected: PASS. (The e2e smoke test uses the mock LLM; the new `curiosity_keywords` task will hit the mock — confirm the mock returns a parseable-or-garbage string and the fallback keeps it green.)

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (no regressions). If `test_e2e_smoke.py` fails because the mock LLM has no `curiosity_keywords` task response, add a default in `tests/fixtures/mock_llm.py` returning a JSON array (e.g. `'["本地新闻 最新"]'`) for that task; commit that as part of this task.

- [ ] **Step 5: Commit**

```bash
git add generative_city_sim.py tests/fixtures/mock_llm.py
git commit -m "feat(sim): scheduled info-seek uses contextual keyword proposer"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** Task 1 = `assemble_curiosity_context` (signal groups); Task 2 = `should_seek_knowledge` (heuristic gate + budget + enabled); Task 3 = `propose_contextual_keywords` (LLM + fallback); Task 4 = `_news.py` `keywords=` reuse of web-search + RAG write; Task 5 = config; Task 6 = event-driven wiring + budget; Task 7 = scheduled path made contextual + regression. Storage/decay/consolidation need no change (existing `info_seek` type already covered) — verified, no task required.
- **Naming consistency:** function names are identical across tasks — `assemble_curiosity_context`, `should_seek_knowledge`, `propose_contextual_keywords`, `_web_search_target`, `_maybe_curiosity_seek`, `info_seek_and_store(..., keywords=...)`.
- **Verify-before-edit reminders:** line numbers in `generative_city_sim.py` may drift — search by the anchor strings quoted, not raw line numbers. (`behavior.py` accessor confirmed: `news_settings()["news"]["info_seek"]`.)
