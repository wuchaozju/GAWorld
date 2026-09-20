# 长期规划驱动的日常生活（GoalsPlugin）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为智能体新增"人生目标 → 长期目标 → 短期目标"三层目标体系，驱动每日意图与日程生成，并通过日轻量进度、周回顾与重大事件回顾持续演化。

**Architecture:** 新模块 `gaworld/goals.py`（数据模型/持久化/引导/进度/回顾/格式化）+ 微内核插件 `gaworld/goals_plugin.py`（`agents.built` 引导、`on_day_end` 回顾），完全仿照 `InterestsPlugin` 的"生命周期归插件、读侧 prompt 注入内联"的过渡耦合模式。Spec: `docs/superpowers/specs/2026-07-18-long-term-goals-design.md`。

**Tech Stack:** Python 3（无新依赖）、unittest + pytest、原生 JS dashboard。

**与 spec 的两处已确认偏差**（实现更正）：
1. spec 5.2 写 "priority=15，晚于 interests 的 10" —— 总线语义是**priority 大者先跑**（interests 用 10 抢在 config 注册的 0 之前）。GoalsPlugin 用 `priority=5`：晚于 interests(10)、早于 economy(0)。
2. spec 3.3 写周回顾"沿用 HUMAN_REALISM llm_budget"——该 per-agent budget dict 在 `on_day_end` 钩子里拿不到。改用 goals 自己的全局节流 `max_reviews_per_day`（默认 20）：当天周回顾额度用完则顺延（`last_review_day` 不更新，明天重试）；事件回顾不受此限制。

**主循环顺序确认**：日终 `consolidate_day` + `apply_goal_progress`（内联，`generative_city_sim.py` ~4169）先执行，`on_day_end` 钩子（周/事件回顾）后执行——先记进度、当晚再回顾，顺序正确。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `gaworld/goals.py` | Create | 目标数据模型、JSON 持久化、LLM 引导+启发式兜底、进度应用、周/事件回顾、prompt 格式化、salience 匹配 |
| `gaworld/goals_plugin.py` | Create | 生命周期钩子：`agents.built` 引导、`on_day_end` 回顾节奏 |
| `gaworld/settings/behavior.py` | Modify | `CONFIG["goals"]` 默认值 |
| `gaworld/plugins/__init__.py` | Modify | 注册 `GoalsPlugin` |
| `gaworld/cognition/realism.py` | Modify | `build_daily_intentions` / `consolidate_day` 注入目标上下文，后者输出 `goal_progress` |
| `generative_city_sim.py` | Modify | 常量、`_goals_hint`、日程 prompt、`goal_relevance` 真实化、日终进度应用、访谈注入、CLI 访谈加载 goals |
| `gaworld/sim/_diary.py` | Modify | 日记 prompt 注入目标 |
| `gaworld/apps/dashboard_server.py` | Modify | GET/POST `/api/agents/{id}/goals`、memory payload 附带 goals |
| `site/dashboard/index.html` + `app.js` + `locales/*.json` | Modify | 目标面板 + JSON 编辑 |
| `tests/test_goals_module.py` 等 | Create | 见各任务 |

---

### Task 1: goals.py — 持久化、规范化、启发式兜底

**Files:**
- Create: `gaworld/goals.py`
- Test: `tests/test_goals_module.py`

- [x] **Step 1: Write the failing tests**

创建 `tests/test_goals_module.py`：

```python
"""Tests for gaworld.goals — persistence, normalization, fallback."""

import json
import os
import tempfile
import unittest

from gaworld import goals as goals_mod


def _agent(job="产品经理", econ=0.6):
    return {
        "id": 3,
        "name": "测试者",
        "age": 32,
        "job": job,
        "personality": "稳重务实",
        "daily_life": "作息规律",
        "values": "重视家庭",
        "state": {"econ_security": econ},
    }


def _sample_goals():
    return {
        "life_goals": [
            {"id": "lg1", "title": "在杭州安家", "domain": "family",
             "description": "", "status": "active"},
        ],
        "long_term_goals": [
            {"id": "ltg1", "parent": "lg1", "title": "两年内攒够首付",
             "horizon_days": 700, "progress": 0.15, "status": "active",
             "created_day": 1, "updated_day": 1},
        ],
        "short_term_goals": [
            {"id": "stg1", "parent": "ltg1", "title": "这两周完成基金调仓",
             "target_day": 14, "progress": 0.4, "status": "active",
             "created_day": 1, "updated_day": 1, "recent_note": ""},
        ],
        "last_review_day": 0,
        "needs_review": False,
        "review_log": [],
    }


class TestPersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            goals_mod.save_agent_goals(3, _sample_goals(), tmp)
            loaded = goals_mod.load_agent_goals(3, tmp)
        self.assertEqual(loaded["short_term_goals"][0]["title"], "这两周完成基金调仓")

    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(goals_mod.load_agent_goals(99, tmp), {})

    def test_load_corrupt_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = goals_mod.agent_goals_path(3, tmp)
            os.makedirs(tmp, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json {{{")
            self.assertEqual(goals_mod.load_agent_goals(3, tmp), {})


class TestNormalize(unittest.TestCase):
    def test_truncates_active_to_limits(self):
        payload = _sample_goals()
        payload["short_term_goals"] = [
            {"id": f"stg{i}", "parent": "ltg1", "title": f"目标{i}",
             "progress": 0.0, "status": "active"}
            for i in range(1, 8)
        ]
        out = goals_mod.normalize_goals(payload, day=1)
        active = [g for g in out["short_term_goals"] if g["status"] == "active"]
        self.assertLessEqual(len(active), 4)

    def test_reparents_orphans(self):
        payload = _sample_goals()
        payload["short_term_goals"][0]["parent"] = "ltg_missing"
        out = goals_mod.normalize_goals(payload, day=1)
        self.assertEqual(out["short_term_goals"][0]["parent"], "ltg1")

    def test_clamps_progress_and_status(self):
        payload = _sample_goals()
        payload["long_term_goals"][0]["progress"] = 4.2
        payload["long_term_goals"][0]["status"] = "bogus"
        out = goals_mod.normalize_goals(payload, day=1)
        self.assertEqual(out["long_term_goals"][0]["progress"], 1.0)
        self.assertEqual(out["long_term_goals"][0]["status"], "active")

    def test_drops_untitled_and_empty_payload(self):
        self.assertEqual(goals_mod.normalize_goals({"life_goals": [{"title": ""}]}, day=1), {})
        self.assertEqual(goals_mod.normalize_goals("nope", day=1), {})


class TestFallbackGoals(unittest.TestCase):
    def test_worker_gets_three_tiers(self):
        goals = goals_mod._fallback_goals(_agent(), day=1)
        for tier in ("life_goals", "long_term_goals", "short_term_goals"):
            self.assertTrue(goals[tier], tier)
        self.assertEqual(goals["short_term_goals"][0]["parent"],
                         goals["long_term_goals"][0]["id"])

    def test_retiree_has_no_work_goal(self):
        goals = goals_mod._fallback_goals(_agent(job="已退休"), day=1)
        blob = json.dumps(goals, ensure_ascii=False)
        for word in ("工作", "上班", "加班"):
            self.assertNotIn(word, blob)

    def test_low_econ_prioritizes_income(self):
        goals = goals_mod._fallback_goals(_agent(econ=0.2), day=1)
        self.assertIn("收入", json.dumps(goals, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cw/dev/GAWorld && python -m pytest tests/test_goals_module.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaworld.goals'`（或 import error）。

- [x] **Step 3: Write the implementation**

创建 `gaworld/goals.py`：

```python
"""Goal hierarchy (life / long-term / short-term) for agents.

Data model, JSON persistence, LLM bootstrap with heuristic fallback,
daily progress application, weekly/event reviews, prompt formatting and
episode-salience matching.

Lifecycle is owned by :mod:`gaworld.goals_plugin`; read-side consumers
(intention/routine/diary/interview prompts, salience) stay inline in the
sim — the same interim coupling the interests module uses (see
``gaworld/interests_plugin.py`` module docstring).

Design doc: docs/superpowers/specs/2026-07-18-long-term-goals-design.md
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.goals")

LlmFn = Callable[[str], str]

DEFAULT_GOALS_CONFIG: dict[str, Any] = {
    "enabled": True,
    "review_interval_days": 7,
    "event_review_severity": 0.7,
    "max_life_goals": 2,
    "max_long_term": 3,
    "max_short_term": 4,
    "max_daily_progress_delta": 0.34,
    "review_log_keep": 12,
    "relevance_floor": 0.2,
    "relevance_cap": 0.9,
    "max_reviews_per_day": 20,
}

VALID_STATUS = {"active", "completed", "abandoned", "paused"}
VALID_DOMAINS = {"career", "family", "health", "wealth", "social", "self"}
_TIERS = ("life_goals", "long_term_goals", "short_term_goals")
_ID_PREFIX = {"life_goals": "lg", "long_term_goals": "ltg", "short_term_goals": "stg"}
# Inactive (completed/abandoned) goals kept per tier so files stay bounded.
_MAX_INACTIVE_KEPT = 8


def goals_config(config: dict | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_GOALS_CONFIG)
    if isinstance(config, dict):
        cfg.update({k: v for k, v in config.items() if v is not None})
    return cfg


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return lo


# ---------------------------------------------------------------------
# Persistence — mirrors gaworld.memory.experience file conventions.
# ---------------------------------------------------------------------

def agent_goals_path(agent_id: Any, memory_dir: str) -> str:
    return os.path.join(memory_dir, f"agent_{int(agent_id)}_goals.json")


def load_agent_goals(agent_id: Any, memory_dir: str) -> dict[str, Any]:
    path = agent_goals_path(agent_id, memory_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        _LOG.warning("goals file unreadable for agent %s; will re-bootstrap", agent_id)
        return {}
    return payload if isinstance(payload, dict) else {}


def save_agent_goals(agent_id: Any, goals: dict[str, Any], memory_dir: str) -> None:
    if not isinstance(goals, dict):
        return
    os.makedirs(memory_dir, exist_ok=True)
    path = agent_goals_path(agent_id, memory_dir)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------
# Parsing & normalization
# ---------------------------------------------------------------------

def parse_goals_json(text: Any) -> dict[str, Any]:
    match = re.search(r"\{.*\}", str(text or ""), re.S)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _norm_goal(item: Any, tier: str, idx: int, day: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("title", "")).strip()
    if not title:
        return None
    goal: dict[str, Any] = {
        "id": str(item.get("id", "")).strip() or f"{_ID_PREFIX[tier]}{idx}",
        "title": title,
        "status": item.get("status") if item.get("status") in VALID_STATUS else "active",
    }
    if tier == "life_goals":
        goal["domain"] = item.get("domain") if item.get("domain") in VALID_DOMAINS else "self"
        goal["description"] = str(item.get("description", "")).strip()
        return goal
    goal["parent"] = str(item.get("parent", "")).strip()
    goal["progress"] = _clamp(item.get("progress", 0.0))
    try:
        goal["created_day"] = int(item.get("created_day", day) or day)
        goal["updated_day"] = int(item.get("updated_day", day) or day)
    except (TypeError, ValueError):
        goal["created_day"] = goal["updated_day"] = int(day)
    if tier == "long_term_goals":
        try:
            goal["horizon_days"] = max(30, int(item.get("horizon_days", 180) or 180))
        except (TypeError, ValueError):
            goal["horizon_days"] = 180
    else:
        try:
            goal["target_day"] = int(item.get("target_day", day + 14) or (day + 14))
        except (TypeError, ValueError):
            goal["target_day"] = int(day) + 14
        goal["recent_note"] = str(item.get("recent_note", "")).strip()
    return goal


def normalize_goals(payload: Any, *, config: dict | None = None, day: int = 0) -> dict[str, Any]:
    """Validate/clean a goals payload. Returns {} when nothing valid remains."""
    cfg = goals_config(config)
    if not isinstance(payload, dict):
        return {}
    limits = {
        "life_goals": int(cfg["max_life_goals"]),
        "long_term_goals": int(cfg["max_long_term"]),
        "short_term_goals": int(cfg["max_short_term"]),
    }
    out: dict[str, Any] = {}
    for tier in _TIERS:
        raw = payload.get(tier, [])
        cleaned = []
        for idx, item in enumerate(raw if isinstance(raw, list) else [], start=1):
            goal = _norm_goal(item, tier, idx, day)
            if goal is not None:
                cleaned.append(goal)
        active = [g for g in cleaned if g["status"] == "active"]
        inactive = [g for g in cleaned if g["status"] != "active"]
        out[tier] = active[: limits[tier]] + inactive[-_MAX_INACTIVE_KEPT:]
    if not any(out[tier] for tier in _TIERS):
        return {}
    life_ids = [g["id"] for g in out["life_goals"] if g["status"] == "active"]
    long_ids = [g["id"] for g in out["long_term_goals"] if g["status"] == "active"]
    for g in out["long_term_goals"]:
        if g.get("parent") not in life_ids and life_ids:
            g["parent"] = life_ids[0]
    for g in out["short_term_goals"]:
        if g.get("parent") not in long_ids and long_ids:
            g["parent"] = long_ids[0]
    try:
        out["last_review_day"] = int(payload.get("last_review_day", 0) or 0)
    except (TypeError, ValueError):
        out["last_review_day"] = 0
    out["needs_review"] = bool(payload.get("needs_review", False))
    log = payload.get("review_log", [])
    out["review_log"] = [
        x for x in (log if isinstance(log, list) else []) if isinstance(x, dict)
    ][-int(cfg["review_log_keep"]):]
    return out


# ---------------------------------------------------------------------
# Heuristic fallback — mirrors realism._fallback_intentions in spirit.
# ---------------------------------------------------------------------

def _fallback_goals(agent: dict, *, day: int = 0, config: dict | None = None) -> dict[str, Any]:
    job = str(agent.get("job", ""))
    state = agent.get("state", {}) if isinstance(agent.get("state"), dict) else {}
    econ = _clamp(state.get("econ_security", 0.5), 0.0, 1.0)
    if any(k in job for k in ("退休", "无业", "待业", "失业", "家庭主妇", "家庭主夫")):
        life = {"title": "健康安稳地生活，和家人朋友保持联结", "domain": "health"}
        long_term = {"title": "半年内保持规律作息和身体锻炼", "horizon_days": 180}
        short = {"title": "这两周保持每天散步或锻炼"}
    elif "学生" in job:
        life = {"title": "完成学业并找到自己热爱的方向", "domain": "self"}
        long_term = {"title": "本学期成绩稳步提升", "horizon_days": 120}
        short = {"title": "这两周跟上课程进度并按时完成作业"}
    elif econ < 0.45:
        life = {"title": "让家人过上经济安稳的生活", "domain": "wealth"}
        long_term = {"title": "一年内提高收入稳定性", "horizon_days": 365}
        short = {"title": "这两周控制开支并留意增收机会"}
    else:
        life = {"title": "在事业和生活之间找到平衡", "domain": "career"}
        long_term = {"title": "半年内在主业上有可见的进步", "horizon_days": 180}
        short = {"title": "这两周把手头的主要事务按时推进"}
    payload = {
        "life_goals": [{**life, "id": "lg1", "status": "active", "description": ""}],
        "long_term_goals": [
            {**long_term, "id": "ltg1", "parent": "lg1", "progress": 0.0, "status": "active"}
        ],
        "short_term_goals": [
            {**short, "id": "stg1", "parent": "ltg1", "progress": 0.0,
             "status": "active", "target_day": int(day) + 14}
        ],
    }
    return normalize_goals(payload, config=config, day=day)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_module.py -v`
Expected: 全部 PASS（10 个测试）。

- [x] **Step 5: Commit**

```bash
git add gaworld/goals.py tests/test_goals_module.py
git commit -m "feat(goals): add goal hierarchy data model, persistence and fallback"
```

---

### Task 2: goals.py — LLM 引导生成（bootstrap）

**Files:**
- Modify: `gaworld/goals.py`（文件末尾追加）
- Test: `tests/test_goals_module.py`（追加）

- [x] **Step 1: Write the failing tests**

在 `tests/test_goals_module.py` 追加（`_agent`、`goals_mod` 已有）：

```python
class TestBootstrap(unittest.TestCase):
    def _llm_ok(self, prompt):
        self.last_prompt = prompt
        return json.dumps({
            "life_goals": [{"title": "成为行业专家", "domain": "career", "description": "深耕产品"}],
            "long_term_goals": [{"title": "一年内主导一个大项目", "parent_index": 1, "horizon_days": 365}],
            "short_term_goals": [
                {"title": "这两周完成竞品分析", "parent_index": 1, "target_day_offset": 14},
                {"title": "本周约谈三位用户", "parent_index": 1, "target_day_offset": 7},
            ],
        }, ensure_ascii=False)

    def test_derive_goals_maps_parent_index_and_offsets(self):
        goals = goals_mod.derive_goals(_agent(), llm=self._llm_ok, day=10)
        self.assertEqual(goals["long_term_goals"][0]["parent"], "lg1")
        self.assertEqual(goals["short_term_goals"][0]["parent"], "ltg1")
        self.assertEqual(goals["short_term_goals"][0]["target_day"], 24)
        self.assertIn("产品经理", self.last_prompt)

    def test_derive_goals_llm_failure_falls_back(self):
        def boom(prompt):
            raise RuntimeError("llm down")
        goals = goals_mod.derive_goals(_agent(), llm=boom, day=1)
        self.assertTrue(goals["short_term_goals"])  # heuristic fallback

    def test_derive_goals_garbage_falls_back(self):
        goals = goals_mod.derive_goals(_agent(), llm=lambda p: "不是JSON", day=1)
        self.assertTrue(goals["life_goals"])

    def test_bootstrap_skips_existing_file_when_stateful(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            goals_mod.save_agent_goals(3, _sample_goals(), tmp)
            agent = _agent()
            goals_mod.bootstrap_goals(
                [agent], llm=lambda p: calls.append(p) or "{}",
                memory_dir=tmp, stateful=True,
            )
        self.assertEqual(calls, [])
        self.assertEqual(agent["goals"]["short_term_goals"][0]["id"], "stg1")

    def test_bootstrap_derives_and_saves_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent()
            goals_mod.bootstrap_goals(
                [agent], llm=self._llm_ok, memory_dir=tmp, stateful=True,
            )
            self.assertTrue(os.path.exists(goals_mod.agent_goals_path(3, tmp)))
        self.assertEqual(agent["goals"]["life_goals"][0]["title"], "成为行业专家")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_module.py -k Bootstrap -v`
Expected: FAIL — `AttributeError: ... has no attribute 'derive_goals'`。

- [x] **Step 3: Write the implementation**

在 `gaworld/goals.py` 末尾追加：

```python
# ---------------------------------------------------------------------
# Bootstrap (one LLM call per agent, once; heuristic fallback)
# ---------------------------------------------------------------------

def _build_bootstrap_prompt(agent: dict, cfg: dict) -> str:
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"职业：{agent.get('job', '')}",
        f"性格与情绪特征：{agent.get('personality', '')}",
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    return f"""
你是城市生活模拟器的“人生规划推导器”。请根据角色资料推导其目标体系。
角色资料：
{profile_text}
当前状态：{json.dumps(agent.get('state', {}), ensure_ascii=False)}
只输出 JSON：
{{
  "life_goals": [{{"title":"...","domain":"career|family|health|wealth|social|self","description":"一句话"}}],
  "long_term_goals": [{{"title":"...","parent_index":1,"horizon_days":365}}],
  "short_term_goals": [{{"title":"...","parent_index":1,"target_day_offset":14}}]
}}
要求：
1) life_goals 1-{cfg['max_life_goals']} 个：方向性的人生追求，符合年龄、职业与价值观。
2) long_term_goals 1-{cfg['max_long_term']} 个：数月尺度、可评估进度；parent_index 指向所属人生目标序号（从1开始）。
3) short_term_goals 2-{cfg['max_short_term']} 个：1-2 周尺度、能直接落到日常安排；parent_index 指向所属长期目标序号。
4) 目标要具体、贴近角色真实生活，不要空洞口号；全部中文短语。
5) 仅输出 JSON，不要其他文字。
"""


def _coerce_bootstrap_payload(payload: dict, *, day: int, config: dict) -> dict[str, Any]:
    life, long_term, short = [], [], []
    for idx, item in enumerate(payload.get("life_goals", []) or [], start=1):
        if isinstance(item, dict):
            life.append({**item, "id": f"lg{idx}", "status": "active"})
    for idx, item in enumerate(payload.get("long_term_goals", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        try:
            parent = int(item.get("parent_index", 1) or 1)
        except (TypeError, ValueError):
            parent = 1
        long_term.append({**item, "id": f"ltg{idx}", "parent": f"lg{parent}",
                          "progress": 0.0, "status": "active"})
    for idx, item in enumerate(payload.get("short_term_goals", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        try:
            parent = int(item.get("parent_index", 1) or 1)
        except (TypeError, ValueError):
            parent = 1
        try:
            offset = int(item.get("target_day_offset", 14) or 14)
        except (TypeError, ValueError):
            offset = 14
        short.append({**item, "id": f"stg{idx}", "parent": f"ltg{parent}",
                      "progress": 0.0, "status": "active",
                      "target_day": int(day) + max(3, offset)})
    return normalize_goals(
        {"life_goals": life, "long_term_goals": long_term, "short_term_goals": short},
        config=config,
        day=day,
    )


def derive_goals(agent: dict, *, llm: LlmFn, day: int = 0, config: dict | None = None) -> dict[str, Any]:
    cfg = goals_config(config)
    try:
        raw = llm(_build_bootstrap_prompt(agent, cfg))
    except Exception as exc:  # noqa: BLE001 - any LLM failure must fall back, never crash the sim
        _LOG.warning("goals bootstrap LLM call failed for agent %s: %s", agent.get("id"), exc)
        raw = ""
    payload = parse_goals_json(raw)
    goals = _coerce_bootstrap_payload(payload, day=day, config=cfg) if payload else {}
    if not goals or not goals.get("short_term_goals"):
        goals = _fallback_goals(agent, day=day, config=cfg)
    return goals


def bootstrap_goals(agents: list, *, llm: LlmFn, memory_dir: str,
                    stateful: bool = True, config: dict | None = None, day: int = 0) -> None:
    """Attach ``agent["goals"]`` for every agent; stored file wins over LLM."""
    cfg = goals_config(config)
    for agent in agents:
        try:
            agent_id = int(agent.get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not agent_id:
            continue
        stored = load_agent_goals(agent_id, memory_dir) if stateful else {}
        goals = normalize_goals(stored, config=cfg, day=day) if stored else {}
        if not goals:
            goals = derive_goals(agent, llm=llm, day=day, config=cfg)
            if stateful:
                save_agent_goals(agent_id, goals, memory_dir)
        agent["goals"] = goals
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_module.py -v`
Expected: 全部 PASS。

- [x] **Step 5: Commit**

```bash
git add gaworld/goals.py tests/test_goals_module.py
git commit -m "feat(goals): LLM bootstrap with heuristic fallback and stateful reuse"
```

---

### Task 3: goals.py — prompt 格式化与 salience 匹配

**Files:**
- Modify: `gaworld/goals.py`（末尾追加）
- Test: `tests/test_goals_module.py`（追加）

- [x] **Step 1: Write the failing tests**

```python
class TestFormatAndRelevance(unittest.TestCase):
    def test_format_goals_context_lists_three_tiers_with_ids(self):
        text = goals_mod.format_goals_context(_sample_goals())
        self.assertIn("人生方向", text)
        self.assertIn("[ltg1]", text)
        self.assertIn("[stg1]", text)
        self.assertIn("40%", text)

    def test_format_goals_context_empty(self):
        self.assertEqual(goals_mod.format_goals_context({}), "无")
        self.assertEqual(goals_mod.format_goals_context(None), "无")

    def test_format_skips_inactive(self):
        goals = _sample_goals()
        goals["short_term_goals"][0]["status"] = "completed"
        self.assertNotIn("[stg1]", goals_mod.format_goals_context(goals))

    def test_relevance_floor_when_unrelated_or_empty(self):
        self.assertEqual(goals_mod.match_goal_relevance({}, "跑步"), 0.2)
        self.assertEqual(
            goals_mod.match_goal_relevance(_sample_goals(), "下午在西湖边散步"), 0.2)

    def test_relevance_high_on_short_term_match(self):
        score = goals_mod.match_goal_relevance(
            _sample_goals(), "上午研究基金调仓方案", "认真比较了收益")
        self.assertGreater(score, 0.5)
        self.assertLessEqual(score, 0.9)

    def test_relevance_ignores_inactive_goals(self):
        goals = _sample_goals()
        goals["short_term_goals"][0]["status"] = "abandoned"
        goals["long_term_goals"][0]["status"] = "abandoned"
        score = goals_mod.match_goal_relevance(goals, "基金调仓 攒首付")
        self.assertEqual(score, 0.2)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_module.py -k FormatAndRelevance -v`
Expected: FAIL — `no attribute 'format_goals_context'`。

- [x] **Step 3: Write the implementation**

在 `gaworld/goals.py` 末尾追加：

```python
# ---------------------------------------------------------------------
# Prompt formatting & episode-salience matching (read side, no LLM)
# ---------------------------------------------------------------------

def format_goals_context(goals: Any, *, max_items: int = 8) -> str:
    """Compact goals block for prompts. Short-term/long-term goals carry
    ``[id]`` markers so consolidate_day's ``goal_progress`` can reference them."""
    if not isinstance(goals, dict) or not any(goals.get(t) for t in _TIERS):
        return "无"
    lines: list[str] = []
    life = [g for g in goals.get("life_goals", []) if g.get("status") == "active"]
    if life:
        lines.append("人生方向：" + "；".join(str(g.get("title", "")) for g in life))
    for g in goals.get("long_term_goals", []):
        if g.get("status") != "active":
            continue
        lines.append(
            f"- 长期[{g.get('id')}]：{g.get('title')}（进度 {_clamp(g.get('progress', 0.0)):.0%}）"
        )
    for g in goals.get("short_term_goals", []):
        if g.get("status") != "active":
            continue
        note = f"；最近：{g['recent_note']}" if g.get("recent_note") else ""
        lines.append(
            f"- 短期[{g.get('id')}]：{g.get('title')}"
            f"（进度 {_clamp(g.get('progress', 0.0)):.0%}，目标 Day {g.get('target_day', '?')}{note}）"
        )
    return "\n".join(lines[: max(1, max_items)]) if lines else "无"


def _goal_terms(text: Any) -> list[str]:
    return [t for t in re.split(r"[，。；、！？\s/（）()\[\]]+", str(text or "")) if len(t) >= 2]


def match_goal_relevance(goals: Any, *texts: Any, config: dict | None = None) -> float:
    """Keyword overlap between active goals and episode text → salience input.

    Returns ``relevance_floor`` (unrelated) .. ``relevance_cap`` (strong
    short-term match). No LLM — same spirit as interests.match_growth_items.
    """
    cfg = goals_config(config)
    floor = float(cfg["relevance_floor"])
    cap = float(cfg["relevance_cap"])
    if not isinstance(goals, dict):
        return floor
    blob = " ".join(str(t or "") for t in texts)
    if not blob.strip():
        return floor
    best = floor
    for tier, weight in (("short_term_goals", 1.0), ("long_term_goals", 0.75), ("life_goals", 0.55)):
        for g in goals.get(tier, []):
            if g.get("status") != "active":
                continue
            terms = _goal_terms(g.get("title")) + _goal_terms(g.get("recent_note"))
            hits = sum(1 for t in terms if t and t in blob)
            if not hits:
                continue
            ratio = min(1.0, hits / max(1, min(len(terms), 3)))
            best = max(best, floor + (cap - floor) * weight * ratio)
    return min(cap, best)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_module.py -v`
Expected: 全部 PASS。

- [x] **Step 5: Commit**

```bash
git add gaworld/goals.py tests/test_goals_module.py
git commit -m "feat(goals): prompt context formatting and goal-relevance matching"
```

---

### Task 4: goals.py — 日终进度应用 `apply_goal_progress`

**Files:**
- Modify: `gaworld/goals.py`（末尾追加）
- Test: `tests/test_goals_module.py`（追加）

- [x] **Step 1: Write the failing tests**

```python
class TestApplyGoalProgress(unittest.TestCase):
    def test_applies_progress_and_note(self):
        goals, notes = goals_mod.apply_goal_progress(
            _sample_goals(),
            [{"id": "stg1", "progress": 0.6, "note": "完成了方案比较"}],
            day=5,
        )
        g = goals["short_term_goals"][0]
        self.assertEqual(g["progress"], 0.6)
        self.assertEqual(g["recent_note"], "完成了方案比较")
        self.assertEqual(g["updated_day"], 5)
        self.assertTrue(notes)

    def test_caps_daily_delta(self):
        goals, _ = goals_mod.apply_goal_progress(
            _sample_goals(), [{"id": "stg1", "progress": 1.0}], day=5,
            config={"max_daily_progress_delta": 0.1},
        )
        self.assertAlmostEqual(goals["short_term_goals"][0]["progress"], 0.5)

    def test_daily_pass_never_regresses(self):
        goals, _ = goals_mod.apply_goal_progress(
            _sample_goals(), [{"id": "stg1", "progress": 0.1}], day=5)
        self.assertEqual(goals["short_term_goals"][0]["progress"], 0.4)

    def test_full_progress_completes_short_term(self):
        base = _sample_goals()
        base["short_term_goals"][0]["progress"] = 0.9
        goals, notes = goals_mod.apply_goal_progress(
            base, [{"id": "stg1", "progress": 1.0}], day=5)
        self.assertEqual(goals["short_term_goals"][0]["status"], "completed")
        self.assertIn("完成", "".join(notes))

    def test_unknown_id_and_bad_items_skipped(self):
        goals, notes = goals_mod.apply_goal_progress(
            _sample_goals(),
            [{"id": "nope", "progress": 0.9}, "garbage", {"progress": 0.5}],
            day=5,
        )
        self.assertEqual(goals["short_term_goals"][0]["progress"], 0.4)
        self.assertEqual(notes, [])
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_module.py -k ApplyGoalProgress -v`
Expected: FAIL — `no attribute 'apply_goal_progress'`。

- [x] **Step 3: Write the implementation**

在 `gaworld/goals.py` 末尾追加：

```python
# ---------------------------------------------------------------------
# Day-end light progress (piggybacks on consolidate_day's LLM call)
# ---------------------------------------------------------------------

def apply_goal_progress(goals: Any, goal_progress: Any, day: int,
                        *, config: dict | None = None) -> tuple[Any, list[str]]:
    """Apply consolidate_day's ``goal_progress`` items. Daily pass only moves
    progress forward (setbacks are the weekly review's job) and clamps the
    per-day gain to ``max_daily_progress_delta``. Returns (goals, notes)."""
    if not isinstance(goals, dict) or not isinstance(goal_progress, list):
        return goals, []
    cfg = goals_config(config)
    max_delta = float(cfg["max_daily_progress_delta"])
    by_id: dict[str, tuple[str, dict]] = {}
    for tier in ("long_term_goals", "short_term_goals"):
        for g in goals.get(tier, []):
            by_id[str(g.get("id"))] = (tier, g)
    notes: list[str] = []
    for item in goal_progress:
        if not isinstance(item, dict):
            continue
        entry = by_id.get(str(item.get("id", "")).strip())
        if entry is None:
            continue
        tier, goal = entry
        if goal.get("status") != "active":
            continue
        old = _clamp(goal.get("progress", 0.0))
        new = _clamp(item.get("progress", old))
        new = min(new, old + max_delta)
        new = max(new, old)
        goal["progress"] = round(new, 3)
        goal["updated_day"] = int(day)
        note = str(item.get("note", "")).strip()
        if note and tier == "short_term_goals":
            goal["recent_note"] = note[:60]
        if tier == "short_term_goals" and goal["progress"] >= 1.0:
            goal["status"] = "completed"
            notes.append(f"完成短期目标：{goal.get('title')}")
        elif new > old:
            notes.append(f"{goal.get('title')} 进度 {old:.0%}→{new:.0%}")
    return goals, notes
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_module.py -v`
Expected: 全部 PASS。

- [x] **Step 5: Commit**

```bash
git add gaworld/goals.py tests/test_goals_module.py
git commit -m "feat(goals): day-end goal progress application with delta cap"
```

---

### Task 5: goals.py — 周回顾与事件回顾 `run_goal_review`

**Files:**
- Modify: `gaworld/goals.py`（末尾追加）
- Test: `tests/test_goals_module.py`（追加）

- [x] **Step 1: Write the failing tests**

```python
def _review_agent():
    agent = _agent()
    agent["goals"] = _sample_goals()
    agent["episodes"] = [
        {"day": 3, "time": "10:00", "final_activity": "研究基金", "action": "比较收益",
         "reflection": "有进展", "salience": 0.8},
    ]
    return agent


class TestGoalReview(unittest.TestCase):
    def _llm(self, payload):
        return lambda prompt: json.dumps(payload, ensure_ascii=False)

    def test_weekly_review_applies_actions_and_logs(self):
        agent = _review_agent()
        goals, summary = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly",
            llm=self._llm({
                "short_term_updates": [{"id": "stg1", "action": "complete"}],
                "new_short_term_goals": [
                    {"title": "下两周研究学区政策", "parent": "ltg1", "target_day_offset": 14}
                ],
                "long_term_updates": [{"id": "ltg1", "action": "keep", "progress": 0.2}],
                "new_long_term_goals": [],
                "life_goal_change": None,
                "summary": "这周把调仓做完了",
            }),
        )
        self.assertEqual(summary, "这周把调仓做完了")
        by_id = {g["id"]: g for g in goals["short_term_goals"]}
        self.assertEqual(by_id["stg1"]["status"], "completed")
        titles = [g["title"] for g in goals["short_term_goals"] if g["status"] == "active"]
        self.assertIn("下两周研究学区政策", titles)
        self.assertEqual(goals["long_term_goals"][0]["progress"], 0.2)
        self.assertEqual(goals["last_review_day"], 7)
        self.assertEqual(goals["review_log"][-1]["type"], "weekly")

    def test_weekly_review_cannot_touch_life_goals(self):
        agent = _review_agent()
        goals, _ = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly",
            llm=self._llm({
                "short_term_updates": [], "new_short_term_goals": [],
                "long_term_updates": [], "new_long_term_goals": [],
                "life_goal_change": {"id": "lg1", "title": "环游世界"},
                "summary": "想换个活法",
            }),
        )
        self.assertEqual(goals["life_goals"][0]["title"], "在杭州安家")

    def test_event_review_may_change_one_life_goal(self):
        agent = _review_agent()
        goals, _ = goals_mod.run_goal_review(
            agent, day=9, trigger="event",
            trigger_event={"title": "突发失业", "severity": 0.9, "description": "被裁员"},
            llm=self._llm({
                "short_term_updates": [{"id": "stg1", "action": "abandon"}],
                "new_short_term_goals": [
                    {"title": "这两周整理简历投递", "parent": "ltg1", "target_day_offset": 10}
                ],
                "long_term_updates": [], "new_long_term_goals": [],
                "life_goal_change": {"id": "lg1", "title": "先稳住生活再谈安家"},
                "summary": "失业了，先求稳",
            }),
        )
        self.assertEqual(goals["life_goals"][0]["title"], "先稳住生活再谈安家")
        self.assertFalse(goals["needs_review"])
        self.assertEqual(goals["review_log"][-1]["type"], "event")

    def test_unparseable_review_keeps_goals_and_review_day(self):
        agent = _review_agent()
        goals, summary = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly", llm=lambda p: "上周还行",
        )
        self.assertEqual(summary, "")
        self.assertEqual(goals["last_review_day"], 0)

    def test_new_goals_respect_active_caps(self):
        agent = _review_agent()
        goals, _ = goals_mod.run_goal_review(
            agent, day=7, trigger="weekly",
            llm=self._llm({
                "short_term_updates": [],
                "new_short_term_goals": [
                    {"title": f"新目标{i}", "parent": "ltg1", "target_day_offset": 14}
                    for i in range(8)
                ],
                "long_term_updates": [], "new_long_term_goals": [],
                "life_goal_change": None, "summary": "加了一堆",
            }),
        )
        active = [g for g in goals["short_term_goals"] if g["status"] == "active"]
        self.assertLessEqual(len(active), 4)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_module.py -k GoalReview -v`
Expected: FAIL — `no attribute 'run_goal_review'`。

- [x] **Step 3: Write the implementation**

在 `gaworld/goals.py` 末尾追加：

```python
# ---------------------------------------------------------------------
# Weekly / event-triggered reviews (one LLM call per review)
# ---------------------------------------------------------------------

def _recent_episode_lines(agent: dict, day: int, *, since_day: int = 0,
                          max_items: int = 8) -> list[str]:
    eps = [
        ep for ep in agent.get("episodes", [])
        if isinstance(ep, dict) and since_day < int(ep.get("day", 0) or 0) <= int(day)
    ]
    eps.sort(key=lambda e: float(e.get("decayed_salience", e.get("salience", 0.0))), reverse=True)
    return [
        f"Day {e.get('day')} {e.get('time', '')} {e.get('final_activity', '')} -> "
        f"{e.get('action', '')}（{str(e.get('reflection', ''))[:40]}）"
        for e in eps[:max_items]
    ]


def _review_prompt(agent: dict, goals: dict, *, day: int, trigger: str,
                   episode_lines: list[str], trigger_event: dict | None, cfg: dict) -> str:
    goals_text = json.dumps({t: goals.get(t, []) for t in _TIERS}, ensure_ascii=False, indent=2)
    event_text = ""
    if trigger == "event" and isinstance(trigger_event, dict):
        event_text = (
            f"\n触发本次回顾的重大事件：{trigger_event.get('title', '')}"
            f"（严重度 {_clamp(trigger_event.get('severity', 0.0)):.2f}）："
            f"{str(trigger_event.get('description', ''))[:100]}\n"
        )
    life_rule = (
        "5) 本次为重大事件回顾：若事件确实动摇了人生方向，最多在 life_goal_change 修改 1 条人生目标，否则给 null。"
        if trigger == "event"
        else "5) 不要改动人生目标，life_goal_change 恒为 null。"
    )
    kind = "因重大变故引发的" if trigger == "event" else "每周的"
    return f"""
你是{agent.get('name', '')}，正在进行一次{kind}个人目标回顾（今天是 Day {int(day)}）。
你的角色：{agent.get('job', '')}，{agent.get('personality', '')}
当前状态：{json.dumps(agent.get('state', {}), ensure_ascii=False)}
{event_text}
当前目标体系：
{goals_text}
自上次回顾以来的重要经历：
{json.dumps(episode_lines, ensure_ascii=False, indent=2)}

只输出 JSON：
{{
  "short_term_updates": [{{"id":"stg1","action":"keep|complete|adjust|abandon","title":"仅 adjust 时给新标题","progress":0.6}}],
  "new_short_term_goals": [{{"title":"...","parent":"ltg1","target_day_offset":14}}],
  "long_term_updates": [{{"id":"ltg1","action":"keep|complete|abandon","progress":0.3}}],
  "new_long_term_goals": [{{"title":"...","parent":"lg1","horizon_days":365}}],
  "life_goal_change": null,
  "summary": "一段中文回顾小结（50字内）"
}}
要求：
1) 已实际完成的短期目标标 complete；不再合适的标 abandon；方向对但内容要变的用 adjust。
2) 保持 active 短期目标 2-{cfg['max_short_term']} 个（不够就在 new_short_term_goals 里补，须挂在 active 长期目标下）。
3) 长期目标进度按真实经历修订，可升可降；完成或放弃后可在 new_long_term_goals 补充。
4) 目标要具体、符合近期经历，不要空洞口号。
{life_rule}
6) 仅输出 JSON，不要其他文字。
"""


def _next_goal_id(items: list, prefix: str) -> str:
    existing = {str(g.get("id")) for g in items}
    n = 1
    while f"{prefix}{n}" in existing:
        n += 1
    return f"{prefix}{n}"


def _apply_review(goals: dict, payload: dict, *, day: int, trigger: str, cfg: dict) -> dict:
    short_by_id = {str(g.get("id")): g for g in goals.get("short_term_goals", [])}
    for upd in payload.get("short_term_updates", []) or []:
        if not isinstance(upd, dict):
            continue
        g = short_by_id.get(str(upd.get("id", "")).strip())
        if g is None or g.get("status") != "active":
            continue
        action = str(upd.get("action", "keep")).strip()
        if action == "complete":
            g["status"] = "completed"
            g["progress"] = 1.0
        elif action == "abandon":
            g["status"] = "abandoned"
        elif action == "adjust":
            title = str(upd.get("title", "")).strip()
            if title:
                g["title"] = title
            g["progress"] = _clamp(upd.get("progress", g.get("progress", 0.0)))
        elif "progress" in upd:
            g["progress"] = _clamp(upd.get("progress", g.get("progress", 0.0)))
        g["updated_day"] = int(day)
    long_by_id = {str(g.get("id")): g for g in goals.get("long_term_goals", [])}
    for upd in payload.get("long_term_updates", []) or []:
        if not isinstance(upd, dict):
            continue
        g = long_by_id.get(str(upd.get("id", "")).strip())
        if g is None or g.get("status") != "active":
            continue
        action = str(upd.get("action", "keep")).strip()
        if action == "complete":
            g["status"] = "completed"
            g["progress"] = 1.0
        elif action == "abandon":
            g["status"] = "abandoned"
        elif "progress" in upd:
            g["progress"] = _clamp(upd.get("progress", g.get("progress", 0.0)))
        g["updated_day"] = int(day)
    for item in payload.get("new_long_term_goals", []) or []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        active = [g for g in goals["long_term_goals"] if g.get("status") == "active"]
        if len(active) >= int(cfg["max_long_term"]):
            break
        try:
            horizon = max(30, int(item.get("horizon_days", 180) or 180))
        except (TypeError, ValueError):
            horizon = 180
        goals["long_term_goals"].append({
            "id": _next_goal_id(goals["long_term_goals"], "ltg"),
            "parent": str(item.get("parent", "")).strip(),
            "title": str(item["title"]).strip(),
            "horizon_days": horizon,
            "progress": 0.0, "status": "active",
            "created_day": int(day), "updated_day": int(day),
        })
    for item in payload.get("new_short_term_goals", []) or []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        active = [g for g in goals["short_term_goals"] if g.get("status") == "active"]
        if len(active) >= int(cfg["max_short_term"]):
            break
        try:
            offset = max(3, int(item.get("target_day_offset", 14) or 14))
        except (TypeError, ValueError):
            offset = 14
        goals["short_term_goals"].append({
            "id": _next_goal_id(goals["short_term_goals"], "stg"),
            "parent": str(item.get("parent", "")).strip(),
            "title": str(item["title"]).strip(),
            "target_day": int(day) + offset,
            "progress": 0.0, "status": "active", "recent_note": "",
            "created_day": int(day), "updated_day": int(day),
        })
    if trigger == "event":
        change = payload.get("life_goal_change")
        if isinstance(change, dict) and str(change.get("id", "")).strip():
            for g in goals.get("life_goals", []):
                if str(g.get("id")) == str(change.get("id")).strip():
                    title = str(change.get("title", "")).strip()
                    if title:
                        g["title"] = title
                    desc = str(change.get("description", "")).strip()
                    if desc:
                        g["description"] = desc
                    break
    return normalize_goals(goals, config=cfg, day=day)


def run_goal_review(agent: dict, *, llm: LlmFn, day: int, trigger: str = "weekly",
                    trigger_event: dict | None = None,
                    episode_lines: list[str] | None = None,
                    config: dict | None = None) -> tuple[Any, str]:
    """One review pass. On any LLM/parse failure the goals are returned
    unchanged (``last_review_day``/``needs_review`` untouched → retried later)."""
    cfg = goals_config(config)
    goals = agent.get("goals")
    if not isinstance(goals, dict) or not any(goals.get(t) for t in _TIERS):
        return goals, ""
    lines = episode_lines if isinstance(episode_lines, list) else _recent_episode_lines(
        agent, day, since_day=int(goals.get("last_review_day", 0) or 0))
    prompt = _review_prompt(agent, goals, day=day, trigger=trigger,
                            episode_lines=lines, trigger_event=trigger_event, cfg=cfg)
    try:
        raw = llm(prompt)
    except Exception as exc:  # noqa: BLE001 - review failure must not stop the day-end flow
        _LOG.warning("goals review LLM call failed for agent %s: %s", agent.get("id"), exc)
        return goals, ""
    payload = parse_goals_json(raw)
    if not payload:
        _LOG.warning("goals review unparseable for agent %s; keeping goals unchanged", agent.get("id"))
        return goals, ""
    goals = _apply_review(goals, payload, day=day, trigger=trigger, cfg=cfg)
    summary = str(payload.get("summary", "")).strip()
    goals["last_review_day"] = int(day)
    goals["needs_review"] = False
    goals.setdefault("review_log", []).append(
        {"day": int(day), "type": trigger, "summary": summary[:120]})
    goals["review_log"] = goals["review_log"][-int(cfg["review_log_keep"]):]
    agent["goals"] = goals
    return goals, summary
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_module.py -v`
Expected: 全部 PASS。

- [x] **Step 5: Commit**

```bash
git add gaworld/goals.py tests/test_goals_module.py
git commit -m "feat(goals): weekly and event-triggered goal reviews"
```

---

### Task 6: 配置默认值 + GoalsPlugin + 注册

**Files:**
- Modify: `gaworld/settings/behavior.py`（`human_realism_settings()` 里 `"interests"` 块之后）
- Create: `gaworld/goals_plugin.py`
- Modify: `gaworld/plugins/__init__.py`
- Test: `tests/test_goals_plugin.py`

- [x] **Step 1: Write the failing tests**

创建 `tests/test_goals_plugin.py`（`_make_ctx` 仿 `tests/test_interests_plugin.py` 顶部的同名 helper——先阅读该文件 1-45 行照抄其 kernel 构建方式，把 `"interests"` 换成 `"goals"` 配置键）：

```python
"""Tests for gaworld.goals_plugin.GoalsPlugin."""

import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.goals_plugin import GoalsPlugin
from gaworld.kernel import build_kernel


def _make_ctx(goals_cfg, stateful=False, tmpdir="output/memory"):
    config = {
        "goals": goals_cfg,
        "stateful": stateful,
        "memory_dir": tmpdir,
    }
    ctx = build_kernel(config, load_entry_points=False)
    ctx.llm = lambda prompt, task=None, agent_id=None: "{}"
    return ctx


class TestGoalsPluginBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def test_disabled_seeds_empty_goals_and_skips_day_end(self):
        ctx = _make_ctx({"enabled": False})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agents = [{"id": 1, "name": "甲"}]
        ctx.bus.emit("agents.built", agents=agents, config=ctx.config)
        self.assertEqual(agents[0]["goals"], {})

    def test_enabled_bootstrap_invokes_impl(self):
        ctx = _make_ctx({"enabled": True}, stateful=True)
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agents = [{"id": 1, "name": "甲"}]
        calls = {}

        def fake_bootstrap(agents_arg, *, llm, memory_dir, stateful, config, day):
            calls.update(agents=agents_arg, memory_dir=memory_dir,
                         stateful=stateful, day=day)
            for a in agents_arg:
                a["goals"] = {"short_term_goals": []}

        with patch("gaworld.goals.bootstrap_goals", fake_bootstrap), \
             patch("gaworld.goals.format_goals_context", lambda g, max_items=8: "无"):
            ctx.bus.emit("agents.built", agents=agents, config=ctx.config)

        self.assertIs(calls["agents"], agents)
        self.assertTrue(calls["stateful"])
        self.assertEqual(calls["day"], 0)


class TestGoalsPluginDayEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def _agent(self, last_review_day=0, needs_review=False):
        return {
            "id": 1, "name": "甲", "episodes": [],
            "goals": {
                "life_goals": [{"id": "lg1", "title": "安家", "domain": "family",
                                "description": "", "status": "active"}],
                "long_term_goals": [], "short_term_goals": [],
                "last_review_day": last_review_day,
                "needs_review": needs_review, "review_log": [],
            },
        }

    def test_weekly_review_fires_on_interval(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=0)
        reviews = []

        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: reviews.append(kw["trigger"]) or (a["goals"], "小结")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(reviews, ["weekly"])

    def test_no_review_before_interval(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=3)
        reviews = []
        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: reviews.append(1) or (a["goals"], "")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(reviews, [])

    def test_weekly_budget_defers_review(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7,
                         "max_reviews_per_day": 0})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=0)
        reviews = []
        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: reviews.append(1) or (a["goals"], "")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(reviews, [])
        self.assertEqual(agent["goals"]["last_review_day"], 0)

    def test_severe_event_triggers_event_review_and_sets_flag(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 7})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=6)  # weekly not due on day 7? 7-6<7 → yes
        triggers = []

        def fake_review(a, **kw):
            triggers.append((kw["trigger"], kw.get("trigger_event", {}).get("title")))
            a["goals"]["needs_review"] = False
            return a["goals"], "重估"

        with patch("gaworld.goals.run_goal_review", fake_review), \
             patch.object(plugin, "_severe_event_today",
                          lambda a, d: {"title": "失业", "severity": 0.9}):
            ctx.bus.emit("on_day_end", day=7, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(triggers, [("event", "失业")])

    def test_needs_review_flag_retries_event_review(self):
        ctx = _make_ctx({"enabled": True, "review_interval_days": 30})
        plugin = GoalsPlugin()
        plugin.setup(ctx)
        agent = self._agent(last_review_day=0, needs_review=True)
        triggers = []
        with patch("gaworld.goals.run_goal_review",
                   lambda a, **kw: triggers.append(kw["trigger"]) or (a["goals"], "")), \
             patch.object(plugin, "_severe_event_today", lambda a, d: None):
            ctx.bus.emit("on_day_end", day=3, agents=[agent],
                         agents_by_id={1: agent}, config=ctx.config)
        self.assertEqual(triggers, ["event"])


class TestBuiltinRegistration(unittest.TestCase):
    def test_goals_plugin_in_builtin_list(self):
        from gaworld.plugins import builtin_plugins

        ids = [p.id for p in builtin_plugins()]
        self.assertIn("goals", ids)


if __name__ == "__main__":
    unittest.main()
```

注意：若照抄 `tests/test_interests_plugin.py` 的 `_make_ctx` 时发现其 kernel 构建方式与上面不同（例如 `build_kernel` 参数名不同），以 interests 测试文件的真实写法为准调整本测试与插件代码。

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_plugin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gaworld.goals_plugin'`。

- [x] **Step 3: Add config defaults**

`gaworld/settings/behavior.py`，`human_realism_settings()` 返回 dict 中 `"interests"` 块（约 104-128 行）之后、`"human_realism"` 之前插入：

```python
        # Goal hierarchy (life / long-term / short-term) driving daily plans.
        # Design doc: docs/superpowers/specs/2026-07-18-long-term-goals-design.md
        "goals": {
            "enabled": True,
            "review_interval_days": 7,
            "event_review_severity": 0.7,
            "max_life_goals": 2,
            "max_long_term": 3,
            "max_short_term": 4,
            "max_daily_progress_delta": 0.34,
            "review_log_keep": 12,
            "relevance_floor": 0.2,
            "relevance_cap": 0.9,
            # Global throttle for weekly reviews per sim-day (event reviews
            # are exempt); deferred agents retry the next day.
            "max_reviews_per_day": 20,
        },
```

- [x] **Step 4: Write the plugin**

创建 `gaworld/goals_plugin.py`：

```python
"""GoalsPlugin — goal-hierarchy lifecycle as a kernel plugin.

Owns bootstrap (``agents.built``) and the day-end review cadence
(``on_day_end``): weekly reviews every ``review_interval_days`` days plus
event-triggered reviews after severe life events. Daily goal-progress
application stays inline next to ``consolidate_day`` in the run loop —
the same interim coupling the interests read-side consumers use.

Interim coupling, by design: goals live at ``agent["goals"]`` (not
``agent["ext"]``) because the read-side consumers (intention/routine/
diary/interview prompts, episode salience) are still inline.
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.goals_plugin")


class GoalsPlugin(Plugin):
    id = "goals"

    def setup(self, ctx):
        from gaworld import goals as impl
        from gaworld.memory.store import append_agent_log

        self._impl = impl
        self._append_agent_log = append_agent_log
        self._cfg = impl.goals_config(ctx.config.get("goals", {}) or {})
        self._enabled = bool(self._cfg.get("enabled", True))
        ctx.bus.on("agents.built", self._bootstrap)
        if not self._enabled:
            return
        # priority=5: after the interests day-end pass (10), before the
        # economy's config-registered settlement (0).
        ctx.bus.on("on_day_end", self._day_end_reviews, priority=5)

    # -- hooks ---------------------------------------------------------------

    def _bootstrap(self, hook_ctx):
        sim = hook_ctx["sim"]
        agents = hook_ctx.get("agents", [])
        if not self._enabled:
            for agent in agents:
                agent["goals"] = {}
            return
        self._impl.bootstrap_goals(
            agents,
            llm=lambda prompt: sim.llm(prompt, task="goals_bootstrap", agent_id=None),
            memory_dir=sim.config.get("memory_dir", "output/memory"),
            stateful=bool(sim.config.get("stateful", False)),
            config=self._cfg,
            day=0,
        )
        for agent in agents:
            context = self._impl.format_goals_context(agent.get("goals"))
            line = f"[Goals] {agent.get('name', agent['id'])}\n{context}\n"
            print(line.strip())
            self._append_agent_log(agent, line)

    def _day_end_reviews(self, hook_ctx):
        sim = hook_ctx["sim"]
        day = int(hook_ctx.get("day", 0) or 0)
        agents = hook_ctx.get("agents", [])
        stateful = bool(sim.config.get("stateful", False))
        memory_dir = sim.config.get("memory_dir", "output/memory")
        interval = int(self._cfg.get("review_interval_days", 7))
        weekly_budget = int(self._cfg.get("max_reviews_per_day", 20))
        for agent in agents:
            goals = agent.get("goals")
            if not isinstance(goals, dict) or not goals:
                continue
            trigger = None
            trigger_event = self._severe_event_today(agent, day)
            if trigger_event is not None or goals.get("needs_review"):
                trigger = "event"
                # Mark before the LLM call: a failed review keeps the flag
                # set, so the event review retries tomorrow.
                goals["needs_review"] = True
            elif day - int(goals.get("last_review_day", 0) or 0) >= interval:
                if weekly_budget <= 0:
                    continue  # deferred: last_review_day untouched, retries tomorrow
                trigger = "weekly"
                weekly_budget -= 1
            if trigger is None:
                continue
            _goals, summary = self._impl.run_goal_review(
                agent,
                llm=lambda prompt: sim.llm(
                    prompt, task="goals_review", agent_id=agent["id"]),
                day=day,
                trigger=trigger,
                trigger_event=trigger_event,
                config=self._cfg,
            )
            if stateful:
                self._impl.save_agent_goals(agent["id"], agent.get("goals", {}), memory_dir)
            if summary:
                label = "目标周回顾" if trigger == "weekly" else "目标重估"
                line = f"🎯 {agent.get('name', agent['id'])} 的{label}：{summary}\n"
                print(line.strip())
                self._append_agent_log(agent, line)

    # -- helpers -------------------------------------------------------------

    def _severe_event_today(self, agent, day):
        """Highest-severity consumed life event for this agent today at or
        above ``event_review_severity``, else None."""
        from gaworld.events.life import list_life_events

        threshold = float(self._cfg.get("event_review_severity", 0.7))
        try:
            events = list_life_events(include_consumed=True)
        except (OSError, TypeError, ValueError):
            return None
        try:
            agent_id = int(agent.get("id", 0) or 0)
        except (TypeError, ValueError):
            return None
        best, best_sev = None, -1.0
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            try:
                if int(ev.get("triggered_day", -1) or -1) != day:
                    continue
                sev = float(ev.get("severity", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if sev < threshold:
                continue
            ids = ev.get("agent_ids") or []
            if ids:
                try:
                    if agent_id not in [int(x) for x in ids]:
                        continue
                except (TypeError, ValueError):
                    continue
            if sev > best_sev:
                best, best_sev = ev, sev
        return best
```

实现前先读 `gaworld/events/life.py` 里 `list_life_events` 的真实签名与事件字段（`include_consumed`、`triggered_day`、`agent_ids` 为推断名）：若字段不同，按真实字段调整 `_severe_event_today` 与对应测试（测试里该函数整体被 patch，不受影响；只影响真实实现的字段名）。

- [x] **Step 5: Register the plugin**

`gaworld/plugins/__init__.py` 的 `builtin_plugins()`：

```python
    from gaworld.goals_plugin import GoalsPlugin
```

（加在 `from gaworld.interests_plugin import InterestsPlugin` 之后），返回列表中 `InterestsPlugin(),` 之后插入 `GoalsPlugin(),`。

- [x] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_plugin.py tests/test_goals_module.py -v`
Expected: 全部 PASS。再跑 `python -m pytest tests/test_interests_plugin.py tests/test_extension_hooks_resolve.py -v` 确认无回归。

- [x] **Step 7: Commit**

```bash
git add gaworld/goals_plugin.py gaworld/plugins/__init__.py gaworld/settings/behavior.py tests/test_goals_plugin.py
git commit -m "feat(goals): GoalsPlugin lifecycle + config defaults + builtin registration"
```

---

### Task 7: realism.py — 意图与日终整合注入目标

**Files:**
- Modify: `gaworld/cognition/realism.py:328`（`build_daily_intentions`）、`gaworld/cognition/realism.py:434`（`consolidate_day`）
- Test: `tests/test_goals_prompt_injection.py`

- [x] **Step 1: Write the failing tests**

创建 `tests/test_goals_prompt_injection.py`：

```python
"""Goals context must reach the intention/consolidation prompts."""

import json
import unittest
from unittest.mock import patch

from gaworld.cognition import realism


def _agent():
    return {
        "id": 5, "name": "测试者", "job": "教师", "personality": "耐心",
        "state": {"stress": 0.3}, "growth_profile": {}, "episodes": [],
    }


def _episode():
    return {"day": 1, "final_activity": "备课", "action": "整理教案",
            "salience": 0.7, "tags": [], "reflection": "还算顺利"}


class TestIntentionPromptInjection(unittest.TestCase):
    def test_goals_context_in_prompt(self):
        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return json.dumps({"priorities": ["推进课题"], "avoidances": ["拖延"],
                               "target_social": "", "target_recovery": "",
                               "growth_focus": []}, ensure_ascii=False)

        with patch.object(realism, "call_llm", fake_llm):
            realism.build_daily_intentions(
                _agent(), [_episode()], {}, {"remaining": 2},
                goals_context="- 短期[stg1]：完成课题申报（进度 20%）",
            )
        self.assertIn("当前人生与阶段目标", prompts[0])
        self.assertIn("完成课题申报", prompts[0])

    def test_default_goals_context_keeps_signature_optional(self):
        result = realism.build_daily_intentions(_agent(), [], {}, {"remaining": 0})
        self.assertIn("priorities", result)


class TestConsolidationGoalProgress(unittest.TestCase):
    def test_prompt_contains_goals_and_result_carries_goal_progress(self):
        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return json.dumps({
                "summary": "有推进", "priorities": ["继续"], "avoidances": [],
                "target_social": "", "target_recovery": "", "growth_focus": [],
                "goal_progress": [{"id": "stg1", "progress": 0.5, "note": "写了一半"}],
            }, ensure_ascii=False)

        with patch.object(realism, "call_llm", fake_llm):
            result = realism.consolidate_day(
                _agent(), 3, [_episode()], {}, {"remaining": 2},
                goals_context="- 短期[stg1]：完成课题申报（进度 20%）",
            )
        self.assertIn("当前人生与阶段目标", prompts[0])
        self.assertEqual(result["goal_progress"][0]["id"], "stg1")

    def test_no_llm_budget_returns_empty_goal_progress(self):
        result = realism.consolidate_day(_agent(), 3, [_episode()], {}, {"remaining": 0})
        self.assertEqual(result["goal_progress"], [])

    def test_no_episodes_returns_empty_goal_progress(self):
        result = realism.consolidate_day(_agent(), 3, [], {}, {"remaining": 2})
        self.assertEqual(result["goal_progress"], [])

    def test_malformed_goal_progress_becomes_empty_list(self):
        def fake_llm(prompt, task=None, agent_id=None):
            return json.dumps({"summary": "ok", "priorities": [], "avoidances": [],
                               "target_social": "", "target_recovery": "",
                               "growth_focus": [], "goal_progress": "不是列表"},
                              ensure_ascii=False)

        with patch.object(realism, "call_llm", fake_llm):
            result = realism.consolidate_day(
                _agent(), 3, [_episode()], {}, {"remaining": 2}, goals_context="x")
        self.assertEqual(result["goal_progress"], [])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_prompt_injection.py -v`
Expected: FAIL — `build_daily_intentions() got an unexpected keyword argument 'goals_context'`（以及 `KeyError: 'goal_progress'`）。

- [x] **Step 3: Modify `build_daily_intentions`**

`gaworld/cognition/realism.py:328` 签名改为：

```python
def build_daily_intentions(agent, recent_episodes, cfg, llm_budget_ctx, goals_context="无"):
```

prompt 中 `近期经历：\n{eps_text}` 之后、`只输出 JSON` 之前插入：

```
当前人生与阶段目标：
{goals_context}
```

要求列表把原 `4) 不要输出其他文字。` 改为：

```
4) 若“当前人生与阶段目标”不为“无”，priorities 中自然包含 0-2 项与短期目标相关的事项；状态不佳时可为恢复让位。
5) 不要输出其他文字。
```

- [x] **Step 4: Modify `consolidate_day`**

`gaworld/cognition/realism.py:434` 签名改为：

```python
def consolidate_day(agent, day, episodes, cfg, llm_budget_ctx, goals_context="无"):
```

三处 result dict 都补 `"goal_progress": []`：
1. `if not selected:` 的提前返回 dict（约 444-449 行）加一行 `"goal_progress": [],`；
2. 主 `result = {...}`（约 467-471 行）加 `"goal_progress": [],`；

prompt（约 473-489 行）在 `经历：\n{json.dumps(...)}` 之后插入：

```
当前人生与阶段目标（长期/短期目标带[编号]）：
{goals_context}
```

输出 JSON 模板 `"growth_focus": ["..."]` 后加：

```
  "goal_progress": [{{"id":"stg1","progress":0.55,"note":"15字内的推进说明"}}]
```

`仅输出 JSON。` 前加一行说明：

```
goal_progress 仅包含今天确有推进或明确受挫的目标；id 必须使用目标里的[编号]；没有则给 []。
```

解析块（`if parsed:` 内，约 501-511 行之后）追加：

```python
            parsed_goal_progress = parsed.get("goal_progress", [])
            result["goal_progress"] = (
                parsed_goal_progress if isinstance(parsed_goal_progress, list) else []
            )
```

- [x] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_prompt_injection.py tests/test_goals_module.py -v`
Expected: 全部 PASS。再跑 `python -m pytest tests/ -k "realism or intention or consolidation" -v` 查回归。

- [x] **Step 6: Commit**

```bash
git add gaworld/cognition/realism.py tests/test_goals_prompt_injection.py
git commit -m "feat(goals): inject goals context into daily intentions and day consolidation"
```

---

### Task 8: 主循环接线（generative_city_sim.py）

**Files:**
- Modify: `generative_city_sim.py`（常量区 ~425、`generate_daily_routine` 1513、`interview_agent` 2296、goal_relevance ~3508、意图调用 ~3868、日终 ~4169、`_cli_interview_agent` 4588）
- Test: `tests/test_goals_prompt_injection.py`（追加）

- [x] **Step 1: Write the failing tests**

在 `tests/test_goals_prompt_injection.py` 追加：

```python
class TestMainSimGoalsWiring(unittest.TestCase):
    def _agent(self):
        return {
            "id": 5, "name": "测试者", "age": 30, "job": "教师",
            "personality": "耐心", "daily_life": "规律", "values": "务实",
            "state": {}, "growth_profile": {}, "episodes": [], "intentions": {},
            "goals": {
                "life_goals": [{"id": "lg1", "title": "教书育人", "domain": "career",
                                "description": "", "status": "active"}],
                "long_term_goals": [],
                "short_term_goals": [{"id": "stg1", "parent": "", "title": "完成课题申报",
                                      "target_day": 14, "progress": 0.2,
                                      "status": "active", "recent_note": "",
                                      "created_day": 1, "updated_day": 1}],
                "last_review_day": 0, "needs_review": False, "review_log": [],
            },
        }

    def test_goals_hint_formats_and_respects_disabled(self):
        import generative_city_sim as sim

        agent = self._agent()
        with patch.object(sim, "GOALS_ENABLED", True):
            self.assertIn("完成课题申报", sim._goals_hint(agent))
        with patch.object(sim, "GOALS_ENABLED", False):
            self.assertEqual(sim._goals_hint(agent), "无")

    def test_daily_routine_prompt_contains_goals(self):
        import generative_city_sim as sim

        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return "[]"

        agent = self._agent()
        with patch.object(sim, "call_llm", fake_llm), \
             patch.object(sim, "GOALS_ENABLED", True), \
             patch.object(sim, "retrieve_relevant_memories", lambda *a, **k: []):
            sim.generate_daily_routine(agent, [("08:00", "起床")], day=2)
        self.assertTrue(prompts)
        self.assertIn("当前人生与阶段目标", prompts[0])
        self.assertIn("完成课题申报", prompts[0])

    def test_interview_prompt_contains_goals(self):
        import generative_city_sim as sim

        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return json.dumps([{"question": "q", "answer": "a"}], ensure_ascii=False)

        agent = self._agent()
        with patch.object(sim, "call_llm", fake_llm), \
             patch.object(sim, "GOALS_ENABLED", True), \
             patch.object(sim, "evoke_memory",
                          lambda *a, **k: {"hint": "无", "recollection": ""}):
            sim.interview_agent(agent, ["你最近在忙什么？"])
        self.assertIn("完成课题申报", prompts[0])
```

注：导入 `generative_city_sim` 会触发模块级初始化，属重量级导入——项目里已有同类测试（如 `tests/test_interest_daily_routine_prompt.py`）这样做，照其导入/patch 方式对齐（若它用了额外的环境准备 fixture，先照抄）。

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_prompt_injection.py -k MainSimGoalsWiring -v`
Expected: FAIL — `module 'generative_city_sim' has no attribute '_goals_hint'` / 无 `GOALS_ENABLED`。

- [x] **Step 3: Add imports and constants**

`generative_city_sim.py` 在 `from gaworld.events.life import list_life_events`（约 105 行）之后加：

```python
from gaworld.goals import (
    apply_goal_progress,
    format_goals_context,
    load_agent_goals,
    match_goal_relevance,
    save_agent_goals,
)
```

常量区在 `INTERESTS_WEEKEND_BOOST = ...`（约 425 行）之后加：

```python
GOALS_CONFIG = CONFIG.get("goals", {})
GOALS_ENABLED = bool(GOALS_CONFIG.get("enabled", True))
```

- [x] **Step 4: Add `_goals_hint` and inject into the routine prompt**

`generate_daily_routine`（1513 行）定义之前加：

```python
def _goals_hint(agent):
    """Goals block for prompts; '无' when the goals layer is disabled."""
    if not GOALS_ENABLED:
        return "无"
    return format_goals_context(agent.get("goals"))
```

`generate_daily_routine` 内 `intent_hint = ...`（1556 行）之后加：

```python
    goals_hint = _goals_hint(agent)
```

prompt 中 `今日行为意图：{intent_hint}` 之后插入：

```
当前人生与阶段目标：
{goals_hint}
```

要求列表把原 `12) 仅输出 JSON，不要其他文字。` 改为：

```
12) 若“当前人生与阶段目标”不为“无”，日程应自然服务于当前短期目标（每天推进 0-2 个即可，不要堆砌）；疲惫、突发事件或周末休整时目标推进可让位。
13) 仅输出 JSON，不要其他文字。
```

- [x] **Step 5: Wire the daily-intention call**

约 3868 行的调用改为：

```python
                intentions = build_daily_intentions(
                    agent,
                    episodes,
                    HUMAN_REALISM_CONFIG,
                    budget,
                    goals_context=_goals_hint(agent),
                )
```

- [x] **Step 6: Real goal_relevance**

约 3508-3513 行：

```python
            priorities = agent.get("intentions", {}).get("priorities", [])
            goal_relevance = 0.2
            for p in priorities:
                if p and (p in effective_activity or p in plan_text or p in refl_text):
                    goal_relevance = 0.8
                    break
```

之后追加：

```python
            if GOALS_ENABLED:
                goal_relevance = max(
                    goal_relevance,
                    match_goal_relevance(
                        agent.get("goals"),
                        effective_activity,
                        plan_text,
                        refl_text,
                        config=GOALS_CONFIG,
                    ),
                )
```

- [x] **Step 7: Day-end progress application**

约 4169-4177 行，`consolidate_day` 调用加 `goals_context` 参数：

```python
                consolidated = consolidate_day(
                    agent,
                    day,
                    day_eps,
                    HUMAN_REALISM_CONFIG,
                    budget,
                    goals_context=_goals_hint(agent),
                )
                agent["intentions"] = consolidated.get("intentions", agent.get("intentions", {}))
```

紧随其后（`decay_relationships` 之前）插入：

```python
                if GOALS_ENABLED and isinstance(agent.get("goals"), dict) and agent["goals"]:
                    agent["goals"], goal_notes = apply_goal_progress(
                        agent["goals"],
                        consolidated.get("goal_progress", []),
                        day,
                        config=GOALS_CONFIG,
                    )
                    if goal_notes:
                        print(f"🎯 {agent['name']} 的目标推进：{'；'.join(goal_notes)}")
                    if STATEFUL:
                        save_agent_goals(
                            agent_id, agent["goals"], CONFIG.get("memory_dir", "output/memory")
                        )
```

- [x] **Step 8: Interview injection + CLI goals loading**

`interview_agent`（2296 行）内 `recollection = ...` 之后加：

```python
    goals_hint = _goals_hint(agent)
```

prompt 中 `你的近期经验：{memory_hint}` 之后插入一行：

```
你的目标与追求：{goals_hint}
```

`_cli_interview_agent`（4588 行）：先阅读该函数，找到其加载记忆/状态的位置，追加：

```python
    agent["goals"] = (
        load_agent_goals(agent["id"], CONFIG.get("memory_dir", "output/memory"))
        if (STATEFUL and GOALS_ENABLED)
        else {}
    )
```

- [x] **Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_prompt_injection.py tests/test_interest_daily_routine_prompt.py tests/test_schedule_anchor_threshold.py -v`
Expected: 全部 PASS。

- [x] **Step 10: Commit**

```bash
git add generative_city_sim.py tests/test_goals_prompt_injection.py
git commit -m "feat(goals): wire goals into routine prompt, salience, day-end progress and interviews"
```

---

### Task 9: 日记注入（gaworld/sim/_diary.py）

**Files:**
- Modify: `gaworld/sim/_diary.py`（`generate_daily_diary`，158-230 行）
- Test: `tests/test_goals_prompt_injection.py`（追加）

- [x] **Step 1: Write the failing test**

```python
class TestDiaryGoalsInjection(unittest.TestCase):
    def test_diary_prompt_contains_goals(self):
        from gaworld.sim import _diary

        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return ("## 今天主要发生的事情\nx\n## 今天的感想\ny\n## 明天的计划\nz")

        agent = {
            "id": 5, "name": "测试者", "episodes": [], "intentions": {},
            "goals": {
                "life_goals": [], "long_term_goals": [],
                "short_term_goals": [{"id": "stg1", "parent": "", "title": "完成课题申报",
                                      "target_day": 14, "progress": 0.2,
                                      "status": "active", "recent_note": "",
                                      "created_day": 1, "updated_day": 1}],
                "last_review_day": 0, "needs_review": False, "review_log": [],
            },
        }
        with patch.object(_diary._llm_providers, "call_llm", fake_llm):
            _diary.generate_daily_diary(agent, 3, "今天的日志")
        self.assertIn("我的目标与追求", prompts[0])
        self.assertIn("完成课题申报", prompts[0])
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_goals_prompt_injection.py -k Diary -v`
Expected: FAIL — `AssertionError: '我的目标与追求' not found ...`。

- [x] **Step 3: Implement**

`gaworld/sim/_diary.py` 顶部 import 区加：

```python
from gaworld.goals import format_goals_context
```

`generate_daily_diary` 内 `intent_hint = ...`（177 行）之后加：

```python
    goals_hint = format_goals_context(agent.get("goals"))
```

prompt 中 `明天的行为意图：{intent_hint}` 之后插入一行：

```
我的目标与追求：{goals_hint}
```

要求列表 `4) 不要写成流水账，也不要输出 JSON。` 改为：

```
4) 若“我的目标与追求”不为“无”，感想或计划中可自然流露与目标的关系（推进的踏实、落后的焦虑），但不要罗列目标本身。
5) 不要写成流水账，也不要输出 JSON。
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_prompt_injection.py -v`
Expected: 全部 PASS。

- [x] **Step 5: Commit**

```bash
git add gaworld/sim/_diary.py tests/test_goals_prompt_injection.py
git commit -m "feat(goals): diary prompt reflects goal progress feelings"
```

---

### Task 10: Dashboard 服务端 goals 端点

**Files:**
- Modify: `gaworld/apps/dashboard_server.py`（payload 函数区 ~660、GET 路由 866-899、POST 路由 903-923）
- Test: `tests/test_goals_dashboard.py`

- [x] **Step 1: Write the failing tests**

创建 `tests/test_goals_dashboard.py`：

```python
"""Dashboard goals endpoints: payload read + validated write."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.apps import dashboard_server as ds


def _valid_payload():
    return {
        "life_goals": [{"id": "lg1", "title": "安家", "domain": "family",
                        "description": "", "status": "active"}],
        "long_term_goals": [{"id": "ltg1", "parent": "lg1", "title": "攒首付",
                             "horizon_days": 700, "progress": 0.1, "status": "active",
                             "created_day": 1, "updated_day": 1}],
        "short_term_goals": [{"id": "stg1", "parent": "ltg1", "title": "调仓",
                              "target_day": 14, "progress": 0.4, "status": "active",
                              "recent_note": "", "created_day": 1, "updated_day": 1}],
        "last_review_day": 0, "needs_review": False, "review_log": [],
    }


class TestGoalsPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher_root = patch.object(ds, "REPO_ROOT", self.tmp.name)
        patcher_cfg = patch.object(
            ds, "_effective_config", lambda: {"memory_dir": "memory"})
        patcher_root.start()
        self.addCleanup(patcher_root.stop)
        patcher_cfg.start()
        self.addCleanup(patcher_cfg.stop)
        os.makedirs(os.path.join(self.tmp.name, "memory"), exist_ok=True)

    def test_read_missing_returns_empty(self):
        self.assertEqual(ds._agent_goals_payload(9), {})

    def test_save_then_read_roundtrip(self):
        saved = ds._save_agent_goals_payload(9, _valid_payload())
        self.assertEqual(saved["short_term_goals"][0]["title"], "调仓")
        loaded = ds._agent_goals_payload(9)
        self.assertEqual(loaded["long_term_goals"][0]["id"], "ltg1")

    def test_save_rejects_non_dict_and_empty(self):
        with self.assertRaises(ValueError):
            ds._save_agent_goals_payload(9, ["not", "a", "dict"])
        with self.assertRaises(ValueError):
            ds._save_agent_goals_payload(9, {"life_goals": [{"title": ""}]})

    def test_save_normalizes_bad_status(self):
        payload = _valid_payload()
        payload["short_term_goals"][0]["status"] = "bogus"
        saved = ds._save_agent_goals_payload(9, payload)
        self.assertEqual(saved["short_term_goals"][0]["status"], "active")


if __name__ == "__main__":
    unittest.main()
```

注：先确认 `dashboard_server.py` 里根目录常量的真实名称（本计划按 `REPO_ROOT` 与 `_effective_config` 书写，407-410 行的 growth-profile 端点即用此模式读 memory_dir）；若名称不同，按真实名称调整测试与实现。

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goals_dashboard.py -v`
Expected: FAIL — `module ... has no attribute '_agent_goals_payload'`。

- [x] **Step 3: Implement payload helpers**

在 `dashboard_server.py` 的 `_memory_payload`（约 660 行）附近加：

```python
def _agent_goals_payload(agent_id):
    memory_dir = _effective_config().get("memory_dir", "output/memory")
    base = os.path.join(REPO_ROOT, memory_dir)
    return _read_json_file(os.path.join(base, f"agent_{int(agent_id)}_goals.json"), {})


def _save_agent_goals_payload(agent_id, payload):
    from gaworld.goals import normalize_goals

    if not isinstance(payload, dict):
        raise ValueError("goals payload must be a JSON object")
    normalized = normalize_goals(payload, day=int(payload.get("last_review_day", 0) or 0))
    if not normalized:
        raise ValueError("goals payload has no valid goals")
    memory_dir = _effective_config().get("memory_dir", "output/memory")
    base = os.path.join(REPO_ROOT, memory_dir)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"agent_{int(agent_id)}_goals.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return normalized
```

`_memory_payload`（663-670 行）里 `intentions = ...` 之后加：

```python
    goals = _read_json_file(os.path.join(base, f"agent_{agent_id}_goals.json"), {})
```

返回 dict 中 `"intentions": intentions,` 之后加 `"goals": goals,`。

- [x] **Step 4: Add routes**

GET 分发（866-899 行），`path.endswith("/memory")` 分支之后加：

```python
        if path.startswith("/api/agents/") and path.endswith("/goals"):
            agent_id = path.split("/")[3]
            return self._json_response(_agent_goals_payload(agent_id))
```

POST 分发（903-923 行），`path.endswith("/state")` 分支之后加（对照相邻 POST 分支拿 body 的真实写法——若它们用 `payload` 参数或 `self._read_json_body()`，照抄同一模式）：

```python
        if path.startswith("/api/agents/") and path.endswith("/goals"):
            agent_id = path.split("/")[3]
            try:
                saved = _save_agent_goals_payload(agent_id, payload)
            except ValueError as exc:
                return self._json_response({"error": str(exc)}, status=400)
            return self._json_response(saved)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_goals_dashboard.py tests/test_dashboard_studio.py -v`
Expected: 全部 PASS。

- [x] **Step 6: Commit**

```bash
git add gaworld/apps/dashboard_server.py tests/test_goals_dashboard.py
git commit -m "feat(goals): dashboard GET/POST goals endpoints and memory payload"
```

---

### Task 11: Dashboard 前端目标面板

**⚠️ STOP（执行前必读）**：`site/dashboard/app.js` 有用户未提交的本地修改（会话开始时 git status 为 M）。开工前先 `git status site/dashboard/app.js`——若仍有未提交修改，**询问用户**是先提交/暂存他们的改动，还是直接在其上追加。不要覆盖或还原用户的修改。

**Files:**
- Modify: `site/dashboard/index.html`（memory-grid，约 203-208 行）
- Modify: `site/dashboard/app.js`（els 声明 ~43、loadMemory、监听器区 968-1006）
- Modify: `site/dashboard/locales/en.json`、`site/dashboard/locales/zh-CN.json`

- [x] **Step 1: index.html 加目标卡片**

`memory-grid` 内（`<article><h3 data-i18n="memory.agent_log">` 之后）加：

```html
          <article>
            <h3 data-i18n="goals.title">目标</h3>
            <div id="goalsPanel" class="goals-panel"></div>
            <div>
              <button id="goalsEditBtn" class="button small" data-i18n="goals.edit">编辑目标</button>
              <button id="goalsSaveBtn" class="button small" style="display:none" data-i18n="goals.save">保存目标</button>
            </div>
            <textarea id="goalsEditor" class="codebox" rows="14" style="display:none;width:100%"></textarea>
          </article>
```

- [x] **Step 2: locales 加词条**

`site/dashboard/locales/zh-CN.json`（`"memory.agent_log"` 词条之后，保持字母序或原文件顺序风格）：

```json
  "goals.title": "目标",
  "goals.life": "人生方向",
  "goals.long": "长期目标",
  "goals.short": "短期目标",
  "goals.empty": "暂无目标",
  "goals.edit": "编辑目标",
  "goals.save": "保存目标",
  "goals.saved": "目标已保存",
  "goals.invalid_json": "JSON 格式错误",
```

`site/dashboard/locales/en.json` 对应：

```json
  "goals.title": "Goals",
  "goals.life": "Life Direction",
  "goals.long": "Long-term Goals",
  "goals.short": "Short-term Goals",
  "goals.empty": "No goals yet",
  "goals.edit": "Edit Goals",
  "goals.save": "Save Goals",
  "goals.saved": "Goals saved",
  "goals.invalid_json": "Invalid JSON",
```

注意补逗号使 JSON 合法；用 `python -m json.tool site/dashboard/locales/zh-CN.json > /dev/null` 验证两个文件。

- [x] **Step 3: app.js — els、渲染、保存**

els 对象（约 43 行区域）加：

```javascript
  goalsPanel: document.getElementById("goalsPanel"),
  goalsEditor: document.getElementById("goalsEditor"),
  goalsEditBtn: document.getElementById("goalsEditBtn"),
  goalsSaveBtn: document.getElementById("goalsSaveBtn"),
```

新增函数（放在 loadMemory 相关函数附近；`t(...)` 为 app.js 现有的 i18n 取词函数——先确认真实函数名，i18n.js 导出什么就用什么）：

```javascript
function escapeGoalsHtml(text) {
  const div = document.createElement("div");
  div.textContent = String(text == null ? "" : text);
  return div.innerHTML;
}

function renderGoals(goals) {
  if (!els.goalsPanel) return;
  const tiers = [
    ["life_goals", t("goals.life")],
    ["long_term_goals", t("goals.long")],
    ["short_term_goals", t("goals.short")],
  ];
  const hasAny = goals && tiers.some(([k]) => Array.isArray(goals[k]) && goals[k].length);
  if (!hasAny) {
    els.goalsPanel.textContent = t("goals.empty");
    return;
  }
  const parts = [];
  for (const [key, label] of tiers) {
    const items = (goals[key] || []).filter(Boolean);
    if (!items.length) continue;
    const rows = items.map((g) => {
      const progress = typeof g.progress === "number"
        ? ` <progress max="1" value="${g.progress}"></progress> ${Math.round(g.progress * 100)}%`
        : "";
      const status = g.status && g.status !== "active"
        ? ` <em>[${escapeGoalsHtml(g.status)}]</em>` : "";
      return `<li>${escapeGoalsHtml(g.title)}${progress}${status}</li>`;
    }).join("");
    parts.push(`<h4>${escapeGoalsHtml(label)}</h4><ul>${rows}</ul>`);
  }
  const lastReview = (goals.review_log || []).slice(-1)[0];
  if (lastReview) {
    parts.push(`<p>Day ${Number(lastReview.day) || 0}: ${escapeGoalsHtml(lastReview.summary)}</p>`);
  }
  els.goalsPanel.innerHTML = parts.join("");
}

async function loadGoals() {
  if (!state.selectedAgentId) return;
  const goals = await api(`/api/agents/${state.selectedAgentId}/goals`);
  renderGoals(goals || {});
  if (els.goalsEditor) {
    els.goalsEditor.value = JSON.stringify(goals || {}, null, 2);
  }
}

async function saveGoals() {
  if (!state.selectedAgentId) return;
  let payload;
  try {
    payload = JSON.parse(els.goalsEditor.value);
  } catch (e) {
    message(t("goals.invalid_json"), "error");
    return;
  }
  await api(`/api/agents/${state.selectedAgentId}/goals`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await loadGoals();
  message(t("goals.saved"));
}
```

实施时先核对：`state.selectedAgentId` 是否为 app.js 中当前选中 agent 的真实字段名（查看 loadMemory/interview 如何取当前 agent id，用同一来源）；`api()`/`message()` 的真实签名（152/164 行）；toast 的 tone 参数值。以现有代码为准调整。

- [x] **Step 4: 挂载调用与监听器**

在现有 `loadMemory()` 被调用的地方（agent 切换、刷新记忆按钮回调）追加 `await loadGoals();`（跟随现有调用风格）。监听器区（968-1006 行）加：

```javascript
  if (els.goalsEditBtn) els.goalsEditBtn.addEventListener("click", () => {
    const show = els.goalsEditor.style.display === "none";
    els.goalsEditor.style.display = show ? "block" : "none";
    els.goalsSaveBtn.style.display = show ? "inline-block" : "none";
  });
  if (els.goalsSaveBtn) els.goalsSaveBtn.addEventListener("click", withBusy(els.goalsSaveBtn, saveGoals));
```

- [x] **Step 5: 手动验证**

启动 dashboard（按 `docs/TUTORIAL.md` 的启动方式，通常 `python -m gaworld.apps.dashboard_server`；先查该文件 `__main__` 块确认命令），浏览器打开后：
1. 选一个有 `output/memory/agent_N_goals.json` 的 agent（没有就手工造一个合法文件）→ 目标面板显示三层目标与进度条；
2. 点"编辑目标"→ 改 JSON → 保存 → 面板刷新且文件更新；
3. 提交非法 JSON → toast 报错、文件不变；
4. 中英文切换词条正常。

- [x] **Step 6: Commit**

```bash
git add site/dashboard/index.html site/dashboard/app.js site/dashboard/locales/en.json site/dashboard/locales/zh-CN.json
git commit -m "feat(goals): dashboard goals panel with JSON editing"
```

---

### Task 12: 回归、CHANGELOG 与收尾

**Files:**
- Modify: `CHANGELOG.md`

- [x] **Step 1: Full test run**

Run: `python -m pytest tests/ -x -q`
Expected: 新增测试全部 PASS；既有失败（如有）须与主分支基线一致——先 `git stash && python -m pytest tests/ -q` 摸基线再对比，不引入新失败。

- [x] **Step 2: Smoke run（可选但推荐）**

若 `dashboard_config.json` 配了可用 LLM，跑最小仿真（按 `docs/TUTORIAL.md` 的最短命令，1-2 天、少量 agent），确认：
1. 启动日志出现 `[Goals] <名字>` 引导输出；
2. `output/memory/agent_N_goals.json` 生成且结构合法；
3. Day 7（或把 `review_interval_days` 临时调成 1）出现 `🎯 ... 目标周回顾`。

- [x] **Step 3: CHANGELOG**

`CHANGELOG.md` 的 `## [Unreleased]` 节 `### Added` 下追加：

```markdown
- Goal-driven daily life: three-tier goal hierarchy (life / long-term / short-term) per agent, bootstrapped from profiles by LLM with heuristic fallback and persisted to `output/memory/agent_N_goals.json`. Goals drive daily intentions and routine prompts, real `goal_relevance` in episode salience, diary/interview context; day-end progress piggybacks on consolidation, weekly + severe-life-event reviews evolve the hierarchy (`GoalsPlugin`, `CONFIG["goals"]`). Dashboard goals panel with JSON editing (`GET/POST /api/agents/{id}/goals`). Design doc: `docs/superpowers/specs/2026-07-18-long-term-goals-design.md`.
```

- [x] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for goal-driven daily life"
```

---

## Self-Review 记录

- **Spec 覆盖**：数据模型/持久化（T1）、引导+可编辑（T2/T10/T11）、日轻量（T4/T7/T8）、周回顾+事件回顾（T5/T6）、意图/日程驱动（T7/T8）、goal_relevance（T3/T8）、日记/访谈（T8/T9）、dashboard（T10/T11）、配置（T6）、错误处理（各 task 的兜底路径 + 测试）、测试计划（T1-T10）、YAGNI 边界未越界。spec 3.3 "记忆记录"由插件 summary 写入 agent log 承担（`_append_memory_record` 需要 sim 侧参数较多，改用 `append_agent_log`+review_log 已满足可检索性最低要求；若执行中发现 `_append_memory_record` 可从插件安全调用，可加回）。
- **占位符**：无 TBD/TODO；三处"先核对真实名称再对齐"（interests 测试 `_make_ctx`、`list_life_events` 字段、app.js `t()`/`state.selectedAgentId`）是对既有代码的核对指令并给出了默认写法，非空缺。
- **类型一致性**：`format_goals_context(goals, *, max_items=8)`、`match_goal_relevance(goals, *texts, config=None)`、`apply_goal_progress(goals, goal_progress, day, *, config=None) -> (goals, notes)`、`run_goal_review(agent, *, llm, day, trigger, trigger_event, episode_lines, config) -> (goals, summary)`、`bootstrap_goals(agents, *, llm, memory_dir, stateful, config, day)` 在定义与全部调用点一致。
