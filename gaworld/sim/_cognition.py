"""Cognition primitives extracted from ``generative_city_sim.py``.

Scope of this module — the *now-unblocked* subset of the legacy
``# A. 认知模块`` and ``# 社会影响`` banners:

* ``get_social_context`` — sample today's social-partner mentions
* ``perception`` — thin LLM wrapper for per-tick perception
* ``social_influence`` — relationship-weighted emotion contagion

These were originally entangled with ``HUMAN_REALISM_ENABLED``,
``relationship_weight`` (from ``human_realism``) and ``call_llm`` (from
``llm_providers``). All three sources have now migrated into the
``gaworld`` package, so this module can import them directly.

Intentionally out of scope:

* ``planning`` / ``reflection`` — still depend on ``evoke_memory``,
  ``_current_emotion_text``, ``_parse_structured_json`` and other
  helpers that live in ``generative_city_sim.py``. They'll move when
  those helpers are also extracted.
* ``interview_agent`` — depends on ``evoke_memory``.
"""

from __future__ import annotations

import random
from typing import Any

from gaworld.cognition.realism import relationship_weight
from gaworld.llm import providers as _llm_providers
from gaworld.personality.traits import traits_of
from gaworld.settings import CONFIG

# NB: access ``call_llm`` via ``_llm_providers.call_llm`` rather than a
# ``from`` import. The mock installer in ``tests/fixtures/mock_llm.py``
# patches by *reassigning* the module attribute — a ``from`` import here
# would capture the original function reference and miss the patch.

_HUMAN_REALISM_CONFIG: dict[str, Any] = CONFIG.get("human_realism", {})
HUMAN_REALISM_ENABLED: bool = bool(_HUMAN_REALISM_CONFIG.get("enabled", False))


def _fos_fast_mode_cfg() -> dict[str, Any]:
    cfg = CONFIG.get("fos_fast_mode", {}) if isinstance(CONFIG, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _deterministic_cognition_enabled() -> bool:
    return bool(_fos_fast_mode_cfg().get("deterministic_cognition", False))


# ---------------------------------------------------------------------------
# Social context sampling (per-day "who did you think about" fragments).
# ---------------------------------------------------------------------------

def get_social_context(agent: dict[str, Any], agents_by_id: dict[Any, dict[str, Any]]) -> str:
    neighbors = agent["social_neighbors"]
    agent["_recent_social_partners"] = []
    if not neighbors:
        return "今天几乎没有与熟人互动。"
    k = min(3, len(neighbors))
    if HUMAN_REALISM_ENABLED:
        sampled: list[Any] = []
        pool = list(neighbors)
        for _ in range(k):
            weights = [max(0.01, relationship_weight(agent, n)) for n in pool]
            pick = random.choices(pool, weights=weights, k=1)[0]
            sampled.append(pick)
            pool = [n for n in pool if n != pick]
            if not pool:
                break
    else:
        sampled = random.sample(neighbors, k)
    agent["_recent_social_partners"] = sampled
    fragments: list[str] = []
    relationships = agent.get("relationships", {})
    for neighbor_id in sampled:
        name = agents_by_id.get(neighbor_id, {}).get("name", str(neighbor_id))
        rel = relationships.get(str(neighbor_id), {}) if isinstance(relationships, dict) else {}
        closeness = float(rel.get("closeness", 0.5))
        obligation = float(rel.get("obligation", 0.5))
        friction = float(rel.get("friction", 0.5))
        if friction > 0.62:
            fragments.append(f"{name}最近让你有些顾虑，想到对方时会有一点摩擦感")
        elif obligation > 0.65:
            fragments.append(f"{name}最近可能等你回应或配合，这会带来一点责任压力")
        elif closeness > 0.65:
            fragments.append(f"{name}会给你支持感，你更容易想到和对方保持联系")
        else:
            fragments.append(f"{name}的近况会偶尔分散你的注意力")
    return "；".join(fragments) if fragments else "今天几乎没有与熟人互动。"


# ---------------------------------------------------------------------------
# Perception (thin LLM wrapper).
# ---------------------------------------------------------------------------

def perception(
    agent: dict[str, Any],
    time_str: str,
    social_context: str,
    env_context: str,
    policy_event: str,
    extra_sections: list[str] | None = None,
) -> str:
    """Perceive the current situation via LLM.

    ``extra_sections`` are plugin contributions collected on the
    ``perception.sections`` event (e.g. the Skill library block); they
    render at the position the inline skill suffix used to occupy.
    """
    if _deterministic_cognition_enabled():
        social_text = str(social_context or "").strip() or "周围的人没有太多新变化"
        env_text = str(env_context or "").strip() or "环境整体比较平稳"
        policy_text = str(policy_event or "").strip()
        if policy_text:
            return f"我注意到{env_text}，也感到{social_text}，政策上的变化让我会顺手多留意一下。"
        return f"我注意到{env_text}，也感到{social_text}，所以更想先按当前节奏把这段时间过稳。"
    sections = [str(s).strip() for s in (extra_sections or []) if str(s).strip()]
    skill_suffix = "\n" + "\n".join(sections) + "\n" if sections else ""
    prompt = f"""
你是{agent['name']}。
现在是 {time_str}。
你感知到的社交环境是：{social_context}
自然与社会环境：{env_context if env_context else "无特殊变化"}
政策环境：{policy_event if policy_event else "无特殊变化"}
{skill_suffix}
请描述你此刻对环境、他人和制度的感知。（1-2句）
"""
    return _llm_providers.call_llm(prompt, task="perception", agent_id=agent["id"])


# ---------------------------------------------------------------------------
# Social influence (relationship-weighted emotion contagion).
# ---------------------------------------------------------------------------

def _emotion_baseline_cfg() -> dict[str, Any]:
    personality = CONFIG.get("personality", {}) or {}
    if not personality.get("enabled", True):
        return {}
    cfg = personality.get("emotion_baseline", {}) or {}
    return cfg if cfg.get("enabled", True) else {}


def _emotion_setpoint(agent: dict[str, Any], traits: dict[str, float], cfg: dict[str, Any]) -> float:
    """The emotion this agent drifts back to when nothing is happening.

    Anchored on the agent's *own* starting emotion rather than a population
    constant, because the initial values carry real heterogeneity from
    ``data/hangzhou_agents_state_init.csv``; replacing them with one number
    would swap the flattening this function is meant to fix for a different
    one. Captured on first use and cached, so it is a trait-like constant
    rather than something that chases the state it is supposed to anchor.
    """
    record = agent.setdefault("ext", {}).setdefault("big_five", {})
    cached = record.get("emotion_setpoint")
    if cached is not None:
        return float(cached)
    base = float(agent["state"]["emotion"])
    # Neuroticism lowers the set point, extraversion raises it — the two
    # best-replicated trait/affect links there are.
    setpoint = base - float(cfg.get("n_baseline_slope", 0.12)) * traits["n"]
    setpoint += float(cfg.get("e_baseline_slope", 0.04)) * traits["e"]
    setpoint = max(0.15, min(0.85, setpoint))
    record["emotion_setpoint"] = round(setpoint, 4)
    return setpoint


def social_influence(agent: dict[str, Any], agents_by_id: dict[Any, dict[str, Any]]) -> None:
    neighbors = agent["social_neighbors"]
    if not neighbors:
        return
    if HUMAN_REALISM_ENABLED:
        weights = [max(0.01, relationship_weight(agent, n)) for n in neighbors]
        total = sum(weights)
        if total <= 0:
            avg_emotion = sum(agents_by_id[n]["state"]["emotion"] for n in neighbors) / len(neighbors)
        else:
            avg_emotion = sum(
                agents_by_id[n]["state"]["emotion"] * w for n, w in zip(neighbors, weights)
            ) / total
    else:
        avg_emotion = sum(agents_by_id[n]["state"]["emotion"] for n in neighbors) / len(neighbors)
    # Contagion alone is a pure averaging operator: repeated often enough it
    # drives every connected agent onto one emotion, erasing exactly the
    # individual differences the Big Five is supposed to introduce. Pairing it
    # with a pull back towards a personal set point is what makes the
    # neuroticism -> affect link survive more than a few steps. The two forces
    # act at the same cadence because they act on the same variable; the
    # weights are configurable under `personality.emotion_baseline`.
    cfg = _emotion_baseline_cfg()
    traits = traits_of(agent, "rules") if cfg else {}
    if not cfg or not any(traits.values()):
        agent["state"]["emotion"] += 0.1 * (avg_emotion - agent["state"]["emotion"])
        return
    emotion = float(agent["state"]["emotion"])
    setpoint = _emotion_setpoint(agent, traits, cfg)
    # High neuroticism recovers more slowly, so a shock lasts longer and the
    # emotion series has a wider spread — the observable signature of N.
    recovery = float(cfg.get("recovery_rate", 0.08)) / (
        1.0 + float(cfg.get("n_recovery_slope", 0.30)) * traits["n"]
    )
    emotion += float(cfg.get("contagion_weight", 0.06)) * (avg_emotion - emotion)
    emotion += max(0.0, recovery) * (setpoint - emotion)
    agent["state"]["emotion"] = max(0.0, min(1.0, emotion))


__all__ = [
    "HUMAN_REALISM_ENABLED",
    "get_social_context",
    "perception",
    "social_influence",
]
