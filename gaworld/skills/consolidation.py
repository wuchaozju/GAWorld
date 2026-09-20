"""Experience → Skill: distill an agent's recent episodes into a private Skill.

Pattern mirrors :mod:`gaworld.memory.consolidation`:

* Read the agent's recent episodic memories (via the same fetcher).
* Ask the LLM to extract a single transferable pattern as YAML+MD.
* Parse, validate, save under ``output/memory/agent_{id}_skills/``.

Failure modes (no episodes, LLM error, parse error, duplicate) all
return ``None`` — the caller treats skill creation as a *best-effort*
bonus, not a required side effect.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.memory.consolidation import fetch_recent_episodes
from gaworld.settings import CONFIG
from gaworld.skills.registry import SkillRegistry, get_default_registry
from gaworld.skills.schemas import Skill, slugify_skill_id

_LOG = get_logger("gaworld.skills.consolidation")

LlmFn = Callable[[str], str]


_PROMPT = """你是城市仿真器的"技能提炼器"。下面是角色 {name}（{job}）最近 {n_episodes} 条
日常记录。请判断这些经历里是否反复出现一个**可复用的做事方法**——也就是这个
角色已经"掌握并能再次施展"的小技能。

如果存在，输出一个 JSON 对象：
{{
  "name": "<≤16 字的技能名>",
  "description": "<≤40 字，说明什么场景下用、能做什么>",
  "triggers": ["≤4 个可触发该技能的关键词或活动短语"],
  "body": "<80-220 字，第二人称写法的操作指南，告诉这个角色未来再遇到时怎么做>"
}}

如果**没有**清晰、可复用的模式（比如经历过于零碎、彼此无关），请输出：
{{ "skip": true, "reason": "<≤20 字>" }}

只输出 JSON，不要解释，不要 Markdown 围栏。

最近经历：
{episodes}
"""


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)


def _skill_consolidation_config() -> dict[str, Any]:
    mem = CONFIG.get("memory", {}) if isinstance(CONFIG, dict) else {}
    return (mem.get("skill_consolidation", {}) or {}) if isinstance(mem, dict) else {}


def _parse_llm_payload(text: str) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJ_RE.search(cleaned)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _coerce_triggers(value: Any, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def summarize_experience_to_skill(
    agent: dict[str, Any],
    *,
    llm: LlmFn,
    registry: SkillRegistry | None = None,
    today: int | None = None,
    lookback_days: int | None = None,
    min_episodes: int = 4,
) -> Skill | None:
    """Try to derive one new private Skill from the agent's recent episodes.

    Returns the saved :class:`Skill` on success, or ``None`` if no
    pattern was extracted. Idempotent on the slug: a returned LLM
    payload whose name slugifies to an existing private skill id is
    silently overwritten (the LLM is allowed to refine the same skill
    over time).
    """
    if not isinstance(agent, dict):
        return None
    agent_id = int(agent.get("id", 0) or 0)
    if not agent_id:
        return None

    reg = registry or get_default_registry()
    cfg = _skill_consolidation_config()
    lookback = int(lookback_days if lookback_days is not None else cfg.get("lookback_days", 5))
    fetch_max = max(min_episodes * 3, 12)
    episodes = fetch_recent_episodes(agent_id, lookback_days=lookback, today=today, max_rows=fetch_max)
    if len(episodes) < int(min_episodes):
        return None

    bullets: list[str] = []
    for ep in episodes:
        sim_day = ep.get("sim_day")
        sim_time_str = ep.get("sim_time") or ""
        prefix = f"(D{sim_day} {sim_time_str})" if sim_day is not None else f"({sim_time_str})"
        bullets.append(f"- {prefix} {ep['text']}")
    prompt = _PROMPT.format(
        name=agent.get("name", ""),
        job=agent.get("job", ""),
        n_episodes=len(bullets),
        episodes="\n".join(bullets),
    )

    try:
        raw = llm(prompt)
    except Exception as exc:
        _LOG.warning("skill consolidation LLM call failed for agent %s: %s", agent_id, exc)
        return None

    payload = _parse_llm_payload(raw)
    if not payload:
        return None
    if payload.get("skip"):
        return None

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    body = str(payload.get("body") or "").strip()
    triggers = _coerce_triggers(payload.get("triggers"))
    if not name or not body:
        return None

    skill_id = slugify_skill_id(name, fallback=f"agent{agent_id}-skill")
    skill = Skill(
        skill_id=skill_id,
        name=name[:32],
        description=description[:80],
        body=body[:1200],
        triggers=triggers,
        source="private",
        owner_agent_id=agent_id,
        origin="consolidation",
        created_day=today,
    )
    saved = reg.save_private(agent_id, skill)
    _LOG.info(
        "summarised new private skill %r for agent %s from %d episodes",
        saved.skill_id,
        agent_id,
        len(episodes),
    )
    return saved


def run_skill_consolidation(
    agent: dict[str, Any],
    *,
    llm: LlmFn,
    today: int | None = None,
    registry: SkillRegistry | None = None,
) -> Skill | None:
    """Lifecycle entrypoint: gated by config, otherwise calls into
    :func:`summarize_experience_to_skill`.

    Kept as a thin shim so :mod:`gaworld.memory.lifecycle` can call us
    without re-reading the config block itself.
    """
    cfg = _skill_consolidation_config()
    if not cfg.get("enabled", False):
        return None
    return summarize_experience_to_skill(
        agent,
        llm=llm,
        registry=registry,
        today=today,
        lookback_days=cfg.get("lookback_days"),
        min_episodes=int(cfg.get("min_episodes", 4)),
    )


__all__ = [
    "run_skill_consolidation",
    "summarize_experience_to_skill",
]
