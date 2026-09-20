"""Big Five (OCEAN) traits — the single read-side entry point.

Leaf module by design: it imports nothing from ``gaworld``, so any subsystem
may depend on it the way it depends on ``math``. Traits live as z scores in
``agent["ext"]["big_five"]``; :class:`~gaworld.personality.plugin.BigFivePlugin`
seeds them once at ``agents.built`` and nothing writes them again — personality
is a trait, not a state, and the real timescale of OCEAN change is years while
a run is days.

Three channels, gated by the record itself (``record["channels"]``) rather
than by a CONFIG read at every call site — that is what keeps this module a
leaf and makes the ablation arms in the design proposal implementable:

``rules``
    Deterministic modulation: ``choose_action``'s ``trait_style_fit``
    component, the small base rates in ``behavior/dynamic.py``, the economy's
    wealth drive, the emotion baseline. Zero tokens, fully reproducible.
``prompt``
    Behavioural anchor sentences injected into *decision* prompts (routine,
    goals, news, activity adjustment).
``voice``
    The same anchors in *expressive* prompts only (the diary), so "the writing
    changed" can be separated from "the decisions changed".

Two modulation shapes, deliberately different:

* :func:`style_fit` is **additive**, sized like the existing ``components``
  entries in ``choose_action`` (``growth_drive``=0.6, ``habit``~0.9). Additive
  because the analytic ceiling of a multiplicative +-25% modifier on a single
  weight is |r| ~ 0.15, below what n=51 can detect.
* :func:`trait_modifier` is **multiplicative** and bounded to +-``band``, for
  the small per-tick base rates in ``dynamic.py`` where a wider band compounds
  and runs away.

Tuning knobs (``strength``, ``band``, ``amplitude``, ``residual_ratio``) are
written onto the record by the plugin at seed time rather than read from CONFIG
here. That keeps this module a leaf, makes every call site a one-liner, and
means ``output/traits/agent_traits.csv`` records exactly the settings that were
in force — a run cannot silently disagree with the config it claims to use.

Both carry a deterministic per-agent residual. Without it the trait ->
propensity map is exact, and the observed trait/behaviour correlation grows
towards 1.0 as the observation window lengthens (~0.14 at 1 day, ~0.61 at 30,
~1.0 asymptotically) — which would make any effect-size acceptance criterion a
measure of the window rather than of personality. The residual is derived from
a hash of the agent id, not from ``random``, so it is stable across runs and
does not perturb the determinism gate.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Mapping
from typing import Any

#: Canonical dimension order. ``n`` is neuroticism (not emotional stability):
#: high ``n`` means more reactive.
DIMENSIONS: tuple[str, ...] = ("o", "c", "e", "a", "n")

DIMENSION_NAMES_ZH: dict[str, str] = {
    "o": "开放性",
    "c": "尽责性",
    "e": "外向性",
    "a": "宜人性",
    "n": "神经质",
}

#: All three channels on. Used when a record predates the ``channels`` key.
ALL_CHANNELS: tuple[str, ...] = ("rules", "prompt", "voice")

#: z scores beyond this are clipped. +-2.5 SD covers ~99% of a normal
#: population; past it the anchor sentences stop being describable anyway.
Z_CLIP = 2.5

_NEUTRAL: dict[str, float] = dict.fromkeys(DIMENSIONS, 0.0)

BigFive = dict[str, float]


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def record_of(agent: Mapping[str, Any]) -> dict[str, Any]:
    """Raw ``big_five`` record, or ``{}`` when the plugin never seeded one."""
    ext = agent.get("ext") if isinstance(agent, Mapping) else None
    if not isinstance(ext, Mapping):
        return {}
    record = ext.get("big_five")
    return dict(record) if isinstance(record, Mapping) else {}


def traits_of(agent: Mapping[str, Any], channel: str | None = None) -> BigFive:
    """z scores for one agent, neutral (all zero) when absent or gated off.

    ``channel`` is the ablation gate: asking for a channel the record does not
    list yields neutral traits, which makes every downstream modulation the
    identity. That is also the backwards-compatibility contract — an agent
    with no record behaves exactly as it did before this subsystem existed.
    """
    record = record_of(agent)
    if not record:
        return dict(_NEUTRAL)
    if channel is not None:
        channels = record.get("channels")
        allowed = tuple(channels) if isinstance(channels, (list, tuple)) else ALL_CHANNELS
        if channel not in allowed:
            return dict(_NEUTRAL)
    return {k: _clip(_f(record.get(k)), -Z_CLIP, Z_CLIP) for k in DIMENSIONS}


#: Fallbacks for records written before a knob existed, and for the neutral
#: path. Overridden per-agent by ``record["tuning"]``.
TUNING_DEFAULTS: dict[str, float] = {
    "strength": 1.0,
    "amplitude": 0.6,
    "band": 0.25,
    "residual_ratio": 0.6,
}


def tuning_of(agent: Mapping[str, Any]) -> dict[str, float]:
    """Modulation knobs in force for this agent."""
    values = dict(TUNING_DEFAULTS)
    raw = record_of(agent).get("tuning")
    if isinstance(raw, Mapping):
        for key in TUNING_DEFAULTS:
            if key in raw:
                values[key] = _f(raw[key], TUNING_DEFAULTS[key])
    return values


#: Anchor-rendering knobs, same arrangement and for the same reason as
#: :data:`TUNING_DEFAULTS`: ``anchors.py`` is a stdlib-only leaf and must not
#: reach into CONFIG, so the plugin copies the operator's settings onto each
#: agent record at seed time and the read side takes them from there. Without
#: this the ``personality.prompt.*`` block is documented but inert, and an
#: ablation that turns a knob would silently measure nothing.
PROMPT_DEFAULTS: dict[str, float] = {
    "midpoint": 0.5,
    "spread": 0.4,
    "strong_z": 1.5,
    "max_dims": 2.0,
    "floor_z": 0.25,
}


def prompt_knobs_of(agent: Mapping[str, Any]) -> dict[str, float]:
    """Anchor-rendering knobs in force for this agent."""
    values = dict(PROMPT_DEFAULTS)
    raw = record_of(agent).get("prompt")
    if isinstance(raw, Mapping):
        for key in PROMPT_DEFAULTS:
            if key in raw:
                values[key] = _f(raw[key], PROMPT_DEFAULTS[key])
    return values


# ---------------------------------------------------------------------------
# Deterministic per-agent residual
# ---------------------------------------------------------------------------

def residual(agent: Mapping[str, Any], name: str) -> float:
    """Stable standard-normal draw keyed on ``(agent id, name)``.

    ``hashlib`` rather than :func:`hash` because the builtin is salted per
    process, which would make two runs of the same seed diverge.
    """
    key = f"{agent.get('id', 'x')}|{name}".encode()
    seed = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
    return random.Random(seed).gauss(0.0, 1.0)


# ---------------------------------------------------------------------------
# Channel 1a — additive fit against ``_action_style_tags``
# ---------------------------------------------------------------------------

#: ``style tag -> trait -> loading``. The tags are exactly the ones
#: ``gaworld.sim._action._action_style_tags`` already produces, so this table
#: projects OCEAN onto a vocabulary the decision loop speaks natively instead
#: of inventing a second one. Signs follow the strongest of the personality
#: literature: C predicts follow-through, E predicts social initiation, N
#: predicts withdrawal and recovery-seeking, O predicts novelty.
STYLE_LOADINGS: dict[str, dict[str, float]] = {
    "social": {"e": 1.00, "a": 0.30},
    "progress": {"c": 1.00, "o": 0.30},
    "avoidant": {"c": -0.80, "n": 0.50},
    "restorative": {"n": 0.60, "e": -0.30},
    "quick": {"c": -0.50},
    "maintain": {"c": 0.40, "o": -0.30},
}

#: Divisor inside ``tanh``. A single dominant tag gives raw ~ 1.0 * z, so
#: ``tanh(z/2)`` is close to linear over the bulk of the distribution and
#: saturates instead of clipping at the tails.
_FIT_SOFTNESS = 2.0


def style_fit(
    agent: Mapping[str, Any],
    styles: Iterable[str],
    *,
    amplitude: float | None = None,
    residual_ratio: float | None = None,
    channel: str = "rules",
) -> float:
    """Additive score for one candidate action, bounded to ~+-``amplitude``.

    Returns ``0.0`` for a neutral or gated-off agent, which is what makes the
    "no traits ⇒ bit-identical behaviour" contract hold.
    """
    traits = traits_of(agent, channel)
    if not any(traits.values()):
        return 0.0
    tags = [t for t in styles if t in STYLE_LOADINGS]
    if not tags:
        return 0.0
    knobs = tuning_of(agent)
    amplitude = knobs["amplitude"] if amplitude is None else amplitude
    residual_ratio = knobs["residual_ratio"] if residual_ratio is None else residual_ratio
    raw = sum(w * traits[dim] for tag in tags for dim, w in STYLE_LOADINGS[tag].items())
    signature = "style:" + ",".join(sorted(tags))
    noise = residual(agent, signature) * residual_ratio
    return amplitude * knobs["strength"] * math.tanh((raw + noise) / _FIT_SOFTNESS)


# ---------------------------------------------------------------------------
# Channel 1b — multiplicative modifiers
# ---------------------------------------------------------------------------

#: ``name -> trait -> slope``. Entries are added only when a real consumer
#: exists; there is no registration API and no extension hook, because the
#: moment this table can be extended from outside it stops being auditable.
MODIFIERS: dict[str, dict[str, float]] = {
    # gaworld/behavior/dynamic.py — how hard it is to derail the current activity
    "interrupt_threshold": {"c": 0.30, "n": -0.15},
    # gaworld/behavior/dynamic.py — base rate of spontaneous urges
    "spontaneity_chance": {"c": -0.25, "o": 0.20},
    # gaworld/behavior/dynamic.py — chance a co-located pair actually interacts
    "social_encounter": {"e": 0.35, "a": 0.10},
    # gaworld/sim/_action.py — width of the multiplicative weight jitter
    "decision_noise": {"o": 0.20},
    # gaworld/sim/_action.py — chance the weighted draw is bypassed entirely
    "impulse_gate": {"c": -0.25},
    # gaworld/economy/finance.py — savings/consumption tilt
    "wealth_drive": {"c": 0.20, "n": 0.10},
}


def trait_modifier(
    agent: Mapping[str, Any],
    name: str,
    *,
    strength: float | None = None,
    band: float | None = None,
    residual_ratio: float | None = None,
    channel: str = "rules",
) -> float:
    """Multiplier in ``[1-band, 1+band]``; exactly ``1.0`` when neutral.

    ``tanh`` rather than a hard clip so the tails compress smoothly — a hard
    clip would pile every strongly-scoring agent onto the same value and
    manufacture a ceiling group.
    """
    loadings = MODIFIERS.get(name)
    if not loadings:
        return 1.0
    traits = traits_of(agent, channel)
    if not any(traits.values()):
        return 1.0
    knobs = tuning_of(agent)
    strength = knobs["strength"] if strength is None else strength
    band = knobs["band"] if band is None else band
    residual_ratio = knobs["residual_ratio"] if residual_ratio is None else residual_ratio
    raw = sum(w * traits[dim] for dim, w in loadings.items())
    noise = residual(agent, f"mod:{name}") * residual_ratio
    return 1.0 + band * strength * math.tanh(raw + noise)
