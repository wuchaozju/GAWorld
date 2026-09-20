"""Profile → AgentCapabilities via LLM, with on-disk hash cache.

The cache is a single JSON file mapping ``str(agent_id)`` to the
serialised :class:`AgentCapabilities`. We re-derive only when the
profile fields that feed the prompt change (detected via md5 hash).

Calling code path::

    caps = bootstrap_all_agents(agents, cache_path, llm=call_llm)
    caps_for_agent = caps[agent_id]   # AgentCapabilities

The LLM call is mocked out in tests by passing a callable that
returns a JSON string.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Callable, Iterable, Optional

from gaworld.logging_setup import get_logger
from gaworld.work.schemas import (
    ADAPTERS,
    DELIVERABLES,
    JOB_LABELS,
    AgentCapabilities,
)

_LOG = get_logger("gaworld.work.capabilities")


_PROMPT_TEMPLATE = """你是一个仿真社会的能力建模助手。读取下面这个虚构居民的 profile，输出一个 JSON：

{{
  "job_label": "<从枚举里选: {job_labels}>",
  "skills":   [≤6 个具体可操作的中文技能词],
  "interests":[≤6 个兴趣词],
  "deliverables": [可交付物枚举的子集: {deliverables}],
  "adapter_priority": [按可能性排序的 adapter 名: {adapters}],
  "notes": "<≤80 字解释>"
}}

不在枚举里的 deliverables 不要输出。退休/无业/学龄前儿童 等无产出能力的人，
deliverables 可以为空数组。

profile:
姓名：{name}
职业：{job}
性格：{personality}
日常生活：{daily_life}
价值观：{values}

只输出 JSON，不要解释。"""


def _profile_signature(agent: dict[str, Any]) -> str:
    """md5 of the profile fields that drive the prompt."""

    parts = [
        str(agent.get("job", "")),
        str(agent.get("personality", "")),
        str(agent.get("daily_life", "")),
        str(agent.get("values", "")),
    ]
    blob = "".join(parts).encode("utf-8")
    return hashlib.md5(blob).hexdigest()


def _build_prompt(agent: dict[str, Any]) -> str:
    return _PROMPT_TEMPLATE.format(
        job_labels=" | ".join(JOB_LABELS),
        deliverables=", ".join(DELIVERABLES),
        adapters=" / ".join(ADAPTERS),
        name=agent.get("name", ""),
        job=agent.get("job", ""),
        personality=agent.get("personality", ""),
        daily_life=agent.get("daily_life", ""),
        values=agent.get("values", ""),
    )


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


def _parse_llm_response(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        return {}
    text = text.strip()
    # Try direct parse first; fall back to greedy {...} extract.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _coerce_list(value: Any, allowed: Optional[set[str]] = None, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        s = str(item).strip()
        if not s or s in seen:
            continue
        if allowed is not None and s not in allowed:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _coerce_capabilities(
    agent_id: int,
    payload: dict[str, Any],
    source_hash: str,
) -> AgentCapabilities:
    job_label = str(payload.get("job_label", "other"))
    if job_label not in JOB_LABELS:
        job_label = "other"
    return AgentCapabilities(
        agent_id=int(agent_id),
        job_label=job_label,
        skills=_coerce_list(payload.get("skills"), limit=6),
        interests=_coerce_list(payload.get("interests"), limit=6),
        deliverables=_coerce_list(payload.get("deliverables"), allowed=set(DELIVERABLES), limit=6),
        adapter_priority=_coerce_list(payload.get("adapter_priority"), allowed=set(ADAPTERS), limit=4),
        notes=str(payload.get("notes", ""))[:200],
        source_hash=source_hash,
    )


def _merge_growth_surface(agent: dict[str, Any], caps: AgentCapabilities) -> AgentCapabilities:
    """Blend planned growth interests/skills into the work surface.

    The public AgentCapabilities schema stays unchanged; we only enrich the
    existing skills/interests lists when the simulator has already derived a
    growth profile for this agent.
    """
    caps = AgentCapabilities.from_dict(caps.to_dict())
    profile = agent.get("growth_profile", {}) if isinstance(agent, dict) else {}
    raw_items = profile.get("items", []) if isinstance(profile, dict) else []
    if not isinstance(raw_items, list):
        return caps

    def _append_unique(base: list[str], values: list[str], limit: int = 8) -> list[str]:
        out = []
        seen = set()
        for value in [*base, *values]:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
            if len(out) >= limit:
                break
        return out

    growth_skills = []
    growth_interests = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        if item.get("kind") == "skill" or bool(item.get("career_link", False)):
            growth_skills.append(name)
        else:
            growth_interests.append(name)
        if name not in growth_interests:
            growth_interests.append(name)

    caps.skills = _append_unique(caps.skills, growth_skills)
    caps.interests = _append_unique(caps.interests, growth_interests)
    return caps


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def load_cache(path: str) -> dict[int, AgentCapabilities]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        _LOG.warning("capabilities cache unreadable, ignoring: %s", path)
        return {}
    out: dict[int, AgentCapabilities] = {}
    if not isinstance(payload, dict):
        return out
    for k, v in payload.items():
        try:
            agent_id = int(k)
        except (TypeError, ValueError):
            continue
        if not isinstance(v, dict):
            continue
        out[agent_id] = AgentCapabilities.from_dict({**v, "agent_id": agent_id})
    return out


def save_cache(path: str, caps: dict[int, AgentCapabilities]) -> None:
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = {str(k): v.to_dict() for k, v in caps.items()}
    # Process-unique tmp: parallel compare-event scenarios may write the same
    # global cache path; a shared "{path}.tmp" races on os.replace.
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

LlmFn = Callable[[str], str]


def derive_one(
    agent: dict[str, Any],
    *,
    llm: LlmFn,
    cache: Optional[dict[int, AgentCapabilities]] = None,
) -> AgentCapabilities:
    """Compute capabilities for one agent, using cache if hash matches."""

    agent_id = int(agent.get("id", 0))
    source_hash = _profile_signature(agent)
    if cache is not None:
        cached = cache.get(agent_id)
        if cached is not None and cached.source_hash == source_hash:
            return _merge_growth_surface(agent, cached)
    prompt = _build_prompt(agent)
    try:
        raw = llm(prompt)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _LOG.warning("capability LLM call failed for agent %s: %s", agent_id, exc)
        raw = ""
    payload = _parse_llm_response(raw)
    return _merge_growth_surface(agent, _coerce_capabilities(agent_id, payload, source_hash))


def bootstrap_all_agents(
    agents: Iterable[dict[str, Any]],
    cache_path: str,
    *,
    llm: LlmFn,
) -> dict[int, AgentCapabilities]:
    """Compute capabilities for every agent, persisting the cache."""

    cache = load_cache(cache_path)
    derived: dict[int, AgentCapabilities] = {}
    for agent in agents:
        agent_id = int(agent.get("id", 0))
        if not agent_id:
            continue
        caps = derive_one(agent, llm=llm, cache=cache)
        derived[agent_id] = caps
        cache[agent_id] = caps
    save_cache(cache_path, cache)
    return derived


__all__ = [
    "AgentCapabilities",
    "bootstrap_all_agents",
    "derive_one",
    "load_cache",
    "save_cache",
]
