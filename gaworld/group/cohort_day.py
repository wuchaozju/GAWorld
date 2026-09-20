"""One cohort's day, in one LLM call.

Structurally this is ``gaworld.sim._fastforward.simulate_agent_day`` with the
subject changed from a person to a group — which is why the group tier is
affordable at all: that function already collapses a day into a single call,
so the cost of a cohort-day equals the cost of an agent-day, and there are
20-40 cohorts instead of 500 agents.

Two things are deliberately different from the individual digest:

* **the prompt asks for a distribution, not a person.** It states the group's
  spread and asks how the day went "for most of them / for a minority", and
  the response carries a ``divergence`` field naming the sub-group that had a
  different day. A cohort prompt written in the first person singular would
  reintroduce exactly the representative-agent error the tier exists to avoid.
* **deltas are group deltas.** They are applied as a common shift to every
  member (see ``apply_cohort_state_changes``), so the mean moves and the
  within-cohort spread survives.

The deterministic fallback matters more here than in the individual case: a
failed cohort call silently mis-simulates 20-50 people at once, so the
fallback must produce something usable rather than a blank day.

LLM access goes through ``gaworld.llm.providers`` by module attribute (not a
``from`` import) so test mock installers that reassign ``call_llm`` are
honoured — same convention as ``gaworld/sim/_fastforward.py`` and
``gaworld/sim/_diary.py``.
"""

from __future__ import annotations

import json
import random as _random
import re
from collections.abc import Callable
from typing import Any

from gaworld.group.cohort import Cohort, cohort_summary
from gaworld.logging_setup import get_logger
from gaworld.population.schema import STATE_VAR_KEYS

_LOG = get_logger("gaworld.group.cohort_day")

#: State keys a cohort digest may move. Wider than the individual
#: fast-forward's ``LONG_RUN_STATE_KEYS`` (which omits ``risk_preference`` and
#: ``voice_propensity``) because group mode exists partly to study
#: polarisation and collective voice — freezing ``voice_propensity`` would
#: make the tier unable to represent the phenomenon it was built for.
COHORT_STATE_KEYS: tuple[str, ...] = STATE_VAR_KEYS

_DEFAULT_MAX_DELTA = 0.12
_DEFAULT_BRIEF_MAX_CHARS = 200

_COHORT_PROMPT = """你是生成式城市模拟中的“群体单日整合器”。下面是一个**人群**（不是单个人），请把这一群人的一整天压缩成一份群体简报，并给出这一天的群体近似变化。

群体：{label}
规模：{size} 人
群体画像：{profile}
今天：Day {day} {day_desc}
群体当前状态（均值与离散度）：{state_summary}
群体近期共同记忆：{memory}
外部环境／事件：{env}
{event_hint}
注意：这是一个**有内部差异**的人群，不要当成一个"平均人"来写。请区分"大多数人"和"其中一部分人"。

请只输出 JSON（不要额外解释）：
{{
  "brief": "≤{brief_chars}字，这一天这群人整体上过得怎样：主要在做什么、共同的处境与情绪",
  "divergence": "≤40字，其中哪一部分人的这一天明显不同（说明是哪类人、怎么不同）；若确实高度一致则填\\"\\"",
  "memory": "≤30字，今天这群人共同会记住的一件事",
  "state_changes": {{"emotion": 0.0, "stress": 0.0}},
  "share_affected": 0.8
}}

要求：
- state_changes 是这群人**平均**的当日增量，取值在 -{max_delta}~{max_delta} 之间，只填确有变化的键；键只能取 {state_keys}。
- share_affected 是受今天影响的人口比例（0~1），用于折算群体平均变化。
- 克制，不要编造夸张的大事；没有外部事件时这一天就应该是平淡的。仅输出 JSON。
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _extract_json_object(text: Any) -> dict[str, Any]:
    """Pull the first JSON object out of a possibly fenced LLM response.

    Defensive about the input type: a mocked ``call_llm`` that returns a
    ``MagicMock`` would otherwise raise deep inside ``re``, turning a test
    setup mistake into a confusing traceback.
    """
    if not isinstance(text, str):
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.S)
        candidate = brace.group(0) if brace else None
    if not candidate:
        return {}
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact(text: Any, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    return cleaned[:max_chars]


def normalize_cohort_digest(
    parsed: dict[str, Any], *, max_delta: float, brief_max_chars: int
) -> dict[str, Any]:
    """Coerce a raw LLM object into the cohort digest contract."""
    changes: dict[str, float] = {}
    raw_changes = parsed.get("state_changes")
    if isinstance(raw_changes, dict):
        for key, value in raw_changes.items():
            if key not in COHORT_STATE_KEYS:
                continue
            try:
                delta = float(value)
            except (TypeError, ValueError):
                continue
            if delta == 0.0:
                continue
            changes[key] = max(-max_delta, min(max_delta, delta))

    try:
        share = float(parsed.get("share_affected", 1.0))
    except (TypeError, ValueError):
        share = 1.0
    share = max(0.0, min(1.0, share))

    return {
        "brief": _compact(parsed.get("brief"), brief_max_chars),
        "divergence": _compact(parsed.get("divergence"), 60),
        "memory": _compact(parsed.get("memory"), 40),
        "state_changes": changes,
        "share_affected": share,
    }


def fallback_cohort_digest(
    cohort: Cohort, *, day: int, brief_max_chars: int = _DEFAULT_BRIEF_MAX_CHARS
) -> dict[str, Any]:
    """Deterministic digest for when the LLM is off or the call fails.

    Non-empty on purpose. A blank cohort day is not a neutral outcome — it
    silently freezes 20-50 residents for a day, and doing that without leaving
    a trace in the log is the kind of bug that only shows up as an
    inexplicable flat line weeks later.
    """
    return {
        "brief": _compact(f"{cohort.label()} 这一天按常规节奏度过，群体层面没有明显波动。", brief_max_chars),
        "divergence": "",
        "memory": f"[Day {day}] 平稳的一天。",
        "state_changes": {},
        "share_affected": 1.0,
        "fallback": True,
    }


# ---------------------------------------------------------------------------
# Public: one call per cohort per day
# ---------------------------------------------------------------------------


def cohort_profile_text(cohort: Cohort) -> str:
    """Static描述 of who is in this cohort, from its partition key."""
    return "，".join(f"{axis}={value}" for axis, value in zip(cohort.axes, cohort.key, strict=True))


def simulate_cohort_day(
    cohort: Cohort,
    *,
    day: int,
    day_desc: str = "",
    env_context: str = "",
    event_hint: str = "",
    max_delta: float = _DEFAULT_MAX_DELTA,
    brief_max_chars: int = _DEFAULT_BRIEF_MAX_CHARS,
    use_llm: bool = True,
    llm_fn: Callable[..., str] | None = None,
    rng: _random.Random | None = None,
) -> dict[str, Any]:
    """Compress one day for one cohort into a normalized digest.

    Returns ``brief``, ``divergence``, ``memory``, ``state_changes`` (clamped),
    ``share_affected``, and ``fallback`` when the deterministic path was taken.
    Never raises: a cohort day that throws would take out a whole
    sub-population, so LLM failures degrade to the fallback and are logged.
    """
    del rng  # reserved for burst behaviour, kept for signature parity
    if not use_llm or llm_fn is None:
        return fallback_cohort_digest(cohort, day=day, brief_max_chars=brief_max_chars)

    prompt = _COHORT_PROMPT.format(
        label=cohort.label(),
        size=cohort.size,
        profile=cohort_profile_text(cohort),
        day=int(day),
        day_desc=str(day_desc or "").strip(),
        state_summary=cohort_summary(cohort),
        memory=("；".join(cohort.memory[-3:]) if cohort.memory else "无"),
        env=(str(env_context).strip() or "无特别事件"),
        event_hint=str(event_hint or ""),
        brief_chars=brief_max_chars,
        max_delta=max_delta,
        state_keys="、".join(COHORT_STATE_KEYS),
    )
    try:
        response = llm_fn(prompt, task="group_cohort_day", agent_id=cohort.id)
    except Exception as exc:
        _LOG.warning("cohort day LLM call failed for %s: %s", cohort.id, exc)
        response = ""

    parsed = _extract_json_object(response)
    if not parsed or not str(parsed.get("brief", "")).strip():
        return fallback_cohort_digest(cohort, day=day, brief_max_chars=brief_max_chars)

    digest = normalize_cohort_digest(parsed, max_delta=max_delta, brief_max_chars=brief_max_chars)
    digest["fallback"] = False
    return digest


def effective_state_changes(digest: dict[str, Any]) -> dict[str, float]:
    """Scale a digest's deltas by the share of the cohort actually affected.

    If the model says a shock hit 40% of the group, the *group mean* moves by
    0.4× the per-person effect. Applying the raw delta to everyone would
    overstate the impact by 2.5×, and that error compounds every day.
    """
    share = float(digest.get("share_affected", 1.0))
    changes = digest.get("state_changes")
    if not isinstance(changes, dict):
        return {}
    return {key: float(value) * share for key, value in changes.items()}


def render_cohort_brief_block(cohort: Cohort, day: int, digest: dict[str, Any]) -> str:
    """Log/console block for one cohort-day."""
    lines = [f"── Day {day}｜{cohort.label()}"]
    if digest.get("fallback"):
        lines[0] += "  [fallback]"
    lines.append(f"   {digest.get('brief', '')}")
    divergence = str(digest.get("divergence") or "").strip()
    if divergence:
        lines.append(f"   ↳ 分化：{divergence}")
    changes = digest.get("state_changes") or {}
    if changes:
        rendered = "，".join(f"{key}{value:+.3f}" for key, value in sorted(changes.items()))
        share = float(digest.get("share_affected", 1.0))
        lines.append(f"   ↳ 群体变化（覆盖{share:.0%}）：{rendered}")
    return "\n".join(lines)


__all__ = [
    "COHORT_STATE_KEYS",
    "cohort_profile_text",
    "effective_state_changes",
    "fallback_cohort_digest",
    "normalize_cohort_digest",
    "render_cohort_brief_block",
    "simulate_cohort_day",
]
