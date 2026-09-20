"""Agent-profile parsing helpers extracted from ``generative_city_sim.py``.

This module is the new home for the pure pieces of the legacy
``# Profile 解析`` banner — Markdown profile parsing, type-safe field
coercion, and payload normalisation used when importing agents from
external sources (social pages, files, ad-hoc text).

What's intentionally **not** here yet
-------------------------------------

The rest of the original banner — anything that touches simulator
module-level path constants (``MD_PATH``, ``CSV_PATH`` …), the CLI
``_cli_create_agent_from_social`` dispatcher, the LLM-driven
``_generate_imported_agent_seed``, and ``build_agent``/``print_agent_profiles``
(which depend on ``init_agent_locations`` from the Map & Location
section) — stays in ``generative_city_sim.py`` until the corresponding
sections are migrated. Re-exports preserve the public surface.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Markdown profile parser.
# ---------------------------------------------------------------------------

def parse_profile(block: str) -> dict[str, Any]:
    def _extract(pattern: str, default: str = "") -> str:
        match = re.search(pattern, block)
        return match.group(1) if match else default

    p: dict[str, Any] = {}
    p["name"] = _extract(r"## Profile \d+｜(.+)")
    base = _extract(r"\*\*基础信息\*\*：(.+)")
    p["age"] = int(re.search(r"(\d+)岁", base).group(1))
    p["living"] = re.search(r"居住(?:于)?(.+?)[，。]", base).group(1)
    p["job"] = _extract(r"\*\*职业与工作节奏\*\*：(.+)")
    p["personality"] = _extract(r"\*\*性格与情绪特征\*\*：(.+)")
    # Written by scripts/author_personality.py from the sampled OCEAN scores,
    # and absent from profiles that predate it — hence the empty default, which
    # is what keeps the pre-rewrite corpus rendering byte-identical prompts.
    p["behavior_tendencies"] = _extract(r"\*\*人格与行为倾向\*\*：(.+)")
    p["daily_life"] = _extract(r"\*\*日常生活与生活习惯\*\*：(.+)")
    p["values"] = _extract(r"\*\*价值观与公共事务态度\*\*：(.+)")
    p["work_style"] = p["job"]
    return p


# ---------------------------------------------------------------------------
# Type-safe field coercion helpers.
# ---------------------------------------------------------------------------

def _safe_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text if text else default


def _safe_int(value: Any, default: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clip_state_value(value: Any, default: float = 0.5) -> float:
    return float(np.clip(_safe_float(value, default), 0.0, 1.0))


# ---------------------------------------------------------------------------
# Imported-agent payload defaults & normalisation.
# ---------------------------------------------------------------------------

def _default_imported_agent_payload(
    source: dict[str, Any], override_name: str | None = None
) -> dict[str, Any]:
    source_title = _safe_text(source.get("title"), "社交媒体用户")
    name = _safe_text(override_name, source_title[:12] or "社交媒体用户")
    return {
        "name": name,
        "gender": "未知",
        "age": 28,
        "hukou": "未知",
        "residence": "杭州",
        "job": "自媒体/平台活跃用户",
        "personality": "表达欲较强，部分信息不完整，需在模拟中进一步补足。",
        "daily_life": "日常活动受线上平台内容发布、浏览和社交互动影响较大。",
        "values": "关注与个人内容、平台环境和公共讨论相关的话题。",
        "education_income": "根据社交媒体内容估计，教育与收入信息未完全公开。",
        "social_network": "线上互动关系较多，线下社交网络待进一步观察。",
        "source_summary": _safe_text(source.get("summary")) or _safe_text(source.get("content"))[:200],
        "state": {
            "emotion": 0.58,
            "stress": 0.52,
            "econ_security": 0.50,
            "city_identity": 0.55,
            "policy_sensitivity": 0.55,
            "platform_dependence": 0.72,
            "risk_preference": 0.45,
            "voice_propensity": 0.66,
            "mobility_intent": 0.50,
        },
    }


def _normalize_imported_agent_payload(
    raw: Any, source: dict[str, Any], override_name: str | None = None
) -> dict[str, Any]:
    payload = _default_imported_agent_payload(source, override_name=override_name)
    if not isinstance(raw, dict):
        return payload

    state_raw = raw.get("state", {})
    if not isinstance(state_raw, dict):
        state_raw = {}

    for key in [
        "name",
        "gender",
        "hukou",
        "residence",
        "job",
        "personality",
        "daily_life",
        "values",
        "education_income",
        "social_network",
        "source_summary",
    ]:
        payload[key] = _safe_text(raw.get(key), payload[key])
    payload["name"] = _safe_text(override_name, payload["name"])
    payload["age"] = max(16, min(80, _safe_int(raw.get("age"), payload["age"])))

    for metric, default in payload["state"].items():
        payload["state"][metric] = _clip_state_value(state_raw.get(metric), default)
    return payload


# ---------------------------------------------------------------------------
# Markdown profile block formatter (used when persisting imported agents).
# ---------------------------------------------------------------------------

def _format_imported_profile_block(agent_id: int, payload: dict[str, Any]) -> str:
    state = payload["state"]
    return (
        f"\n## Profile {agent_id:02d}｜{payload['name']}\n"
        f"**基础信息**：{payload['gender']}，{payload['age']}岁，{payload['hukou']}户籍，居住{payload['residence']}。\n\n"
        f"**教育与收入背景**：{payload['education_income']}\n\n"
        f"**职业与工作节奏**：{payload['job']}\n\n"
        f"**性格与情绪特征**：{payload['personality']}\n\n"
        f"**日常生活与生活习惯**：{payload['daily_life']}\n\n"
        f"**社交网络情况**：{payload['social_network']}\n\n"
        f"**价值观与公共事务态度**：{payload['values']}\n\n"
        f"**研究增强变量初始化**：\n"
        f"- policy_sensitivity：{state['policy_sensitivity']:.2f}\n"
        f"- platform_dependence：{state['platform_dependence']:.2f}\n"
        f"- risk_preference：{state['risk_preference']:.2f}\n"
        f"- voice_propensity：{state['voice_propensity']:.2f}\n"
        f"- mobility_intent：{state['mobility_intent']:.2f}\n\n"
        f"**核心状态变量**：emotion {state['emotion']:.2f}｜stress {state['stress']:.2f}｜"
        f"econ_security {state['econ_security']:.2f}｜city_identity {state['city_identity']:.2f}\n"
        f"\n---\n"
    )


__all__ = [
    "_clip_state_value",
    "_default_imported_agent_payload",
    "_format_imported_profile_block",
    "_normalize_imported_agent_payload",
    "_safe_float",
    "_safe_int",
    "_safe_text",
    "parse_profile",
]
