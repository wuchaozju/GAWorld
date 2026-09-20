"""External-RAG helpers extracted from ``generative_city_sim.py``.

Two related concerns live here:

1. **Runtime hints** — surface stored ``[额外信息]`` memories to the
   planning prompt via :func:`_external_rag_hint`. Pure agent-dict
   access plus the vector-DB retrieval API.

2. **Init-time bootstrap helpers** — five pure (or LLM-call) helpers
   used by :func:`generative_city_sim._bootstrap_agent_external_rag`
   to seed an agent's RAG with background memories before the
   simulation starts. The bootstrap *entry point* itself stays in
   ``generative_city_sim`` because tests do
   ``patch.object(sim, "_llm_bootstrap_external_items", ...)`` /
   ``patch.object(sim, "_summarize_bootstrap_web_item", ...)`` and the
   bare-name lookups inside ``_bootstrap_agent_external_rag`` need to
   resolve to ``sim``'s globals (which works through the re-export
   pattern).

LLM access uses module-attribute dispatch (``_llm_providers.call_llm``)
rather than a ``from`` import so the test mock installer's
``llm_providers.call_llm = mock`` reassignment is picked up.
"""

from __future__ import annotations

import json
from typing import Any

from gaworld.llm import providers as _llm_providers
from gaworld.memory.store import _format_memory_hint, retrieve_relevant_memories
from gaworld.personality import personality_line
from gaworld.settings import CONFIG
from gaworld.sim._schedule import _extract_json_array_block
from gaworld.sim._utils import _sanitize_extra_text

_EXTERNAL_RAG_CONFIG: dict[str, Any] = CONFIG.get("external_rag", {})
EXTERNAL_RAG_TOP_K: int = max(1, int(_EXTERNAL_RAG_CONFIG.get("top_k", 2)))


# ---------------------------------------------------------------------------
# Runtime hint helpers.
# ---------------------------------------------------------------------------

def _agent_has_external_rag(agent: Any) -> bool:
    if not isinstance(agent, dict):
        return False
    for item in agent.get("memory", []):
        text = str(item).strip()
        if text.startswith("[额外信息"):
            return True
    return False


def _augment_query_with_growth(agent: Any, query: str) -> str:
    """Append the agent's top growth-focus terms to ``query``.

    The augmented query biases vector retrieval toward memories that
    overlap with the agent's current hobbies/skills — the D4 hook in
    the RAG enhancement plan. Gated by the ``memory.growth_boost``
    flag so it stays opt-out and a no-op when no growth profile
    is attached.
    """
    if not isinstance(agent, dict):
        return query
    mem_cfg = CONFIG.get("memory", {}) or {}
    if not mem_cfg.get("growth_boost", True):
        return query
    profile = agent.get("growth_profile")
    if not profile:
        return query
    try:
        from gaworld.interests import growth_focus
    except Exception:  # pragma: no cover
        return query
    focus = growth_focus(profile, limit=2)
    if not focus:
        return query
    return f"{query} {' '.join(focus)}".strip()


def _external_rag_hint(agent: Any, query: str, max_items: int = EXTERNAL_RAG_TOP_K) -> str:
    augmented = _augment_query_with_growth(agent, query)
    hits = retrieve_relevant_memories(
        agent,
        augmented,
        max_items=max_items,
        entry_types=["external_info"],
    )
    if hits:
        return _format_memory_hint(hits, max_chars=240)
    fallback: list[dict[str, str]] = []
    if isinstance(agent, dict):
        for item in reversed(agent.get("memory", [])):
            text = str(item).strip()
            if "[额外信息" not in text:
                continue
            fallback.append({"type": "external_info", "text": text})
            if len(fallback) >= max_items:
                break
    return _format_memory_hint(list(reversed(fallback)), max_chars=240)


# ---------------------------------------------------------------------------
# Init-time bootstrap helpers (called by gen_city_sim's
# ``_bootstrap_agent_external_rag`` orchestrator).
# ---------------------------------------------------------------------------

def _append_external_payload_to_agent(agent: dict[str, Any], payload: str) -> None:
    if not payload or not isinstance(agent, dict):
        return
    memory = agent.setdefault("memory", [])
    if payload not in memory:
        memory.append(payload)


def _heuristic_bootstrap_external_items(
    agent: dict[str, Any], max_items: int = 3, max_chars: int = 280,
) -> list[str]:
    if not isinstance(agent, dict):
        return []
    state = agent.get("state", {})
    items: list[str] = []
    living = str(agent.get("living") or agent.get("residence") or agent.get("residence", "")).strip()
    job = str(agent.get("job", "")).strip()
    personality = str(agent.get("personality", "")).strip()
    daily_life = str(agent.get("daily_life", "")).strip()
    values = str(agent.get("values", "")).strip()
    if living:
        items.append(f"长期生活在{living}一带，熟悉周边通勤路径、生活服务与大致消费水平。")
    if job:
        items.append(f"对“{job}”相关的工作节奏、收入波动和行业机会有持续关注，会据此调整自己的日常安排。")
    if daily_life:
        items.append(f"平时的生活习惯是：{_sanitize_extra_text(daily_life, max_chars=max_chars)}")
    stress = float(state.get("stress", 0.5))
    econ_security = float(state.get("econ_security", 0.5))
    if stress >= 0.6 or econ_security <= 0.45:
        items.append("最近会更留意收入稳定性、生活成本和能否节省开支。")
    else:
        items.append("通常会平衡工作、休息和消费，不会完全被短期经济波动牵着走。")
    if personality:
        items.append(f"熟人对其的稳定印象通常是：{_sanitize_extra_text(personality, max_chars=max_chars)}")
    if values:
        items.append(f"在公共事务和人生选择上，长期倾向于：{_sanitize_extra_text(values, max_chars=max_chars)}")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _sanitize_extra_text(item, max_chars=max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= max(1, int(max_items)):
            break
    return cleaned


def _parse_bootstrap_external_items(text: str, max_items: int = 3) -> list[str]:
    blob = _extract_json_array_block(text)
    if not blob:
        return []
    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    parsed: list[str] = []
    for item in raw:
        if isinstance(item, str):
            cleaned = _sanitize_extra_text(item, max_chars=280)
        elif isinstance(item, dict):
            cleaned = ""
            for key in ("text", "memory", "knowledge", "content"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned = _sanitize_extra_text(value, max_chars=280)
                    break
        else:
            cleaned = _sanitize_extra_text(str(item), max_chars=280)
        if cleaned:
            parsed.append(cleaned)
        if len(parsed) >= max(1, int(max_items)):
            break
    return parsed


def _llm_bootstrap_external_items(
    agent: dict[str, Any], max_items: int = 3, max_chars: int = 280,
) -> list[str]:
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"年龄：{agent.get('age', '')}",
        f"居住情况：{agent.get('living', agent.get('residence', ''))}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "news"),
        f"日常生活与习惯：{agent.get('daily_life', '')}",
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    prompt = f"""
你是城市模拟器的初始化器。请为一个智能体生成 {max_items} 条“可放入 RAG 的背景记忆/知识”。

角色资料：
{profile_text}

要求：
1) 内容应当是“合理、模糊但有帮助”的长期背景信息，可被后续计划/访谈/决策引用。
2) 不要写极端具体、不可验证的重大事件；更像长期经验、偏好、熟悉领域、持续关注主题。
3) 每条 20-80 字，中文。
4) 仅输出 JSON 数组，每项是字符串，不能输出其他文字。
"""
    response = _llm_providers.call_llm(prompt, task="external_rag_bootstrap", agent_id=agent["id"])
    items = _parse_bootstrap_external_items(response, max_items=max_items)
    if items:
        return [_sanitize_extra_text(item, max_chars=max_chars) for item in items]
    return _heuristic_bootstrap_external_items(agent, max_items=max_items, max_chars=max_chars)


def _summarize_bootstrap_web_item(
    agent: dict[str, Any], title: str, content: str, url: str, max_chars: int = 280,
) -> str:
    profile_text = "\n".join([
        f"姓名：{agent.get('name', '')}",
        f"职业：{agent.get('job', '')}",
        personality_line(agent, "news"),
        f"价值观与公共事务态度：{agent.get('values', '')}",
    ])
    prompt = f"""
你是城市模拟器的初始化器。请把下面一条外部信息转写成适合放入角色 RAG 的“长期背景知识”。

角色资料：
{profile_text}

标题：{title or "N/A"}
链接：{url}
内容摘要：
{content}

要求：
1) 输出 1 句中文，20-80 字。
2) 要体现“这条信息为什么会长期影响/被该角色持续关注”。
3) 不要出现“根据新闻”“网页显示”等措辞。
4) 只输出这一句。
"""
    response = _llm_providers.call_llm(prompt, task="external_rag_bootstrap", agent_id=agent["id"]).strip()
    cleaned = _sanitize_extra_text(response, max_chars=max_chars)
    if cleaned:
        return cleaned
    title_text = _sanitize_extra_text(title, max_chars=80)
    excerpt = _sanitize_extra_text(content, max_chars=max_chars)
    if title_text:
        return f"持续关注“{title_text}”这类信息，因为它可能影响自己的工作机会、生活成本或公共环境判断。 {excerpt}"
    return excerpt


__all__ = [
    "EXTERNAL_RAG_TOP_K",
    "_agent_has_external_rag",
    "_append_external_payload_to_agent",
    "_external_rag_hint",
    "_heuristic_bootstrap_external_items",
    "_llm_bootstrap_external_items",
    "_parse_bootstrap_external_items",
    "_summarize_bootstrap_web_item",
]
