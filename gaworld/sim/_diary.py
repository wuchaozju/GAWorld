"""Long-term memory and daily-diary helpers extracted from ``generative_city_sim.py``.

Scope — the legacy ``# B. 长期记忆`` banner plus the small
``_append_memory_record`` helper that the daily-summary code path
depends on:

* ``_append_memory_record`` — write a memory line into the agent's
  in-memory list and persist it to disk + vector DB.
* ``daily_summary`` — one-line LLM summary of the day; stored as a
  ``memory`` record.
* ``_daily_diary_path`` / ``save_daily_diary`` — file path helpers
  for the per-day diary markdown.
* ``_top_day_episode_lines`` / ``_fallback_daily_diary`` /
  ``generate_daily_diary`` — produce a markdown diary for the day, with
  an LLM fast path and a deterministic fallback.

Now-unblocked dependencies (all in ``gaworld/`` already):
``gaworld.memory.store`` (persistence), ``gaworld.cognition.realism``
(intention_text), ``gaworld.sim._schedule`` (_compact_text), and the
``llm_providers`` shim for the LLM call.

LLM access uses module-attribute dispatch (``_llm_providers.call_llm``)
rather than a ``from`` import so the test mock installer's
``llm_providers.call_llm = mock`` reassignment is picked up.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from gaworld.cognition.realism import intention_text
from gaworld.goals import format_goals_context
from gaworld.llm import providers as _llm_providers
from gaworld.personality import anchor_block
from gaworld.logging_setup import get_logger
from gaworld.memory.store import save_agent_memory, vector_db_add_entry
from gaworld.settings import CONFIG
from gaworld.sim._schedule import _compact_text

_LOG = get_logger("gaworld.sim.diary")

DIARY_OUTPUT_DIR: str = CONFIG.get("diary_output_dir", "output/diaries")


def _fos_fast_mode_cfg() -> dict[str, Any]:
    cfg = CONFIG.get("fos_fast_mode", {}) if isinstance(CONFIG, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


# ---------------------------------------------------------------------------
# Memory record append (used by daily_summary and other long-term writers).
# ---------------------------------------------------------------------------

def _append_memory_record(
    agent: Any,
    text: str,
    entry_type: str = "memory",
    day: int | None = None,
    time_str: str | None = None,
) -> bool:
    payload = str(text or "").strip()
    if not payload or not isinstance(agent, dict):
        return False
    memory = agent.setdefault("memory", [])
    if payload not in memory:
        memory.append(payload)
    save_agent_memory(agent)
    vector_db_add_entry(agent["id"], entry_type, payload, sim_day=day, sim_time=time_str)
    return True


# ---------------------------------------------------------------------------
# One-line LLM daily summary, stored as a memory record.
# ---------------------------------------------------------------------------

def daily_summary(agent: dict[str, Any], logs: str, day: int | None = None) -> str:
    if bool(_fos_fast_mode_cfg().get("skip_daily_summary", False)):
        memory = _compact_text(logs, max_chars=160) or "今天整体按当前节奏推进。"
        _append_memory_record(agent, memory, entry_type="memory", day=day, time_str="end_of_day")
        return memory
    prompt = f"""
你是{agent['name']}。
这是你今天经历的关键片段：
{logs}

请总结今天最重要的一条经验或感受。
"""
    memory = _llm_providers.call_llm(prompt, task="summary", agent_id=agent["id"])
    _append_memory_record(agent, memory, entry_type="memory", day=day, time_str="end_of_day")
    return memory


# ---------------------------------------------------------------------------
# Daily diary (markdown, per agent per day).
# ---------------------------------------------------------------------------

def _daily_diary_path(agent_id: int, day: int, output_dir: str | None = None) -> str:
    base_dir = output_dir or DIARY_OUTPUT_DIR
    return os.path.join(base_dir, f"agent_{int(agent_id)}", f"day_{int(day):03d}.md")


def _top_day_episode_lines(agent: dict[str, Any], day: int, max_items: int = 4) -> list[str]:
    episodes = [
        ep for ep in agent.get("episodes", [])
        if int(ep.get("day", ep.get("created_at_day", 0)) or 0) == int(day)
    ]
    episodes = sorted(
        episodes,
        key=lambda e: float(e.get("decayed_salience", e.get("salience", 0.0))),
        reverse=True,
    )[:max(1, int(max_items))]
    lines: list[str] = []
    for ep in episodes:
        piece = (
            f"{ep.get('time', '')}，{ep.get('final_activity', '')}，做了{ep.get('action', '')}。"
            f" 当时觉得：{ep.get('reflection', '')}"
        ).strip()
        lines.append(_compact_text(piece, max_chars=140))
    return lines


def _fallback_daily_diary(
    agent: dict[str, Any],
    day: int,
    day_context: dict[str, Any] | None = None,
    day_memory: str = "",
    consolidation_text: str = "",
    intentions: Any = None,
) -> str:
    diary_date = ""
    if isinstance(day_context, dict):
        diary_date = " ".join(
            str(day_context.get(key, "")).strip()
            for key in ("sim_date", "weekday_zh", "day_type_zh")
            if str(day_context.get(key, "")).strip()
        ).strip()
    episode_lines = _top_day_episode_lines(agent, day, max_items=3)
    major = "今天整体比较平稳。" if not episode_lines else "；".join(episode_lines)
    feelings = _compact_text(
        consolidation_text or day_memory or "今天的起伏让我更清楚自己在意什么。",
        max_chars=120,
    )
    plan_text = intention_text(intentions or agent.get("intentions", {}))
    return (
        f"# {agent.get('name', 'Agent')} 的 Day {int(day)} 日记\n\n"
        f"{diary_date}\n\n"
        "## 今天主要发生的事情\n"
        f"{major}\n\n"
        "## 今天的感想\n"
        f"{feelings}\n\n"
        "## 明天的计划\n"
        f"{plan_text}\n"
    )


def generate_daily_diary(
    agent: dict[str, Any],
    day: int,
    logs: str,
    day_context: dict[str, Any] | None = None,
    day_memory: str = "",
    consolidation_text: str = "",
    intentions: Any = None,
) -> str:
    if bool(_fos_fast_mode_cfg().get("skip_daily_diary", False)):
        return _fallback_daily_diary(
            agent,
            day,
            day_context=day_context,
            day_memory=day_memory,
            consolidation_text=consolidation_text,
            intentions=intentions,
        )
    episode_lines = _top_day_episode_lines(agent, day, max_items=4)
    intent_hint = intention_text(intentions or agent.get("intentions", {}))
    goals_hint = format_goals_context(agent.get("goals"))
    diary_date = ""
    if isinstance(day_context, dict):
        diary_date = " ".join(
            str(day_context.get(key, "")).strip()
            for key in ("sim_date", "weekday_zh", "day_type_zh")
            if str(day_context.get(key, "")).strip()
        ).strip()
    log_excerpt = _compact_text(logs, max_chars=1600)
    # The diary is the one place personality is allowed to shape *voice*
    # rather than choices, which is why it sits on its own `voice` channel: an
    # experiment can turn the prose difference on and the decision difference
    # off, and tell the two apart. Empty for an agent with no traits, and the
    # surrounding prompt is then byte-identical to the pre-personality build.
    voice_hint = anchor_block(agent, "diary")
    voice_block = f"\n我平时的样子：\n{voice_hint}\n" if voice_hint else ""
    prompt = f"""
你是{agent.get('name', '某位居民')}，请以第一人称写一篇日记。

日期：Day {int(day)} {diary_date}
今天的重要经历：
{json.dumps(episode_lines, ensure_ascii=False, indent=2)}

今天的详细日志摘录：
{log_excerpt}

今天形成的长期记忆：{day_memory}
今天的经验整合：{consolidation_text}
明天的行为意图：{intent_hint}
我的目标与追求：{goals_hint}
{voice_block}
要求：
1) 输出 markdown。
2) 必须包含且只包含这三个二级标题：`## 今天主要发生的事情`、`## 今天的感想`、`## 明天的计划`。
3) 语气像这个 agent 自己写的日记，聚焦今天最重要的几件事、真实感受、以及明天的打算。
4) 若“我的目标与追求”不为“无”，感想或计划中可自然流露与目标的关系（推进的踏实、落后的焦虑），但不要罗列目标本身。
5) 不要写成流水账，也不要输出 JSON。
"""
    try:
        response = _llm_providers.call_llm(
            prompt, task="daily_diary", agent_id=agent["id"]
        ).strip()
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        _LOG.warning("daily_diary LLM call failed for agent %s: %s", agent.get("id"), exc)
        response = ""
    if (
        not response
        or "## 今天主要发生的事情" not in response
        or "## 今天的感想" not in response
        or "## 明天的计划" not in response
    ):
        return _fallback_daily_diary(
            agent,
            day,
            day_context=day_context,
            day_memory=day_memory,
            consolidation_text=consolidation_text,
            intentions=intentions,
        )
    title = f"# {agent.get('name', 'Agent')} 的 Day {int(day)} 日记"
    if not response.lstrip().startswith("#"):
        response = f"{title}\n\n{response}"
    return response


def save_daily_diary(
    agent: dict[str, Any], day: int, diary_text: str, output_dir: str | None = None
) -> str:
    path = _daily_diary_path(agent["id"], day, output_dir=output_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(diary_text or "").strip() + "\n")
    return path


__all__ = [
    "DIARY_OUTPUT_DIR",
    "_append_memory_record",
    "_fallback_daily_diary",
    "_top_day_episode_lines",
    "daily_summary",
    "generate_daily_diary",
    "save_daily_diary",
]
