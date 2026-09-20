"""Behavioural anchor sentences — how OCEAN reaches an LLM prompt.

Also a leaf module (stdlib only), for the same reason as
:mod:`gaworld.personality.traits`.

Three rules, each of them a decision the design proposal argues for at length:

1. **Never write the number.** "尽责性 0.62" has no stable behavioural prior in
   Chinese text; models either ignore it or act out a caricature of the label.
   What transfers is a second-person sentence naming an observable behaviour
   and one concrete threshold ("独处超过两天就会觉得不对劲").
2. **Only render what is distinctive, and render it probabilistically.** A hard
   |z| > 0.8 cutoff would silently turn a continuous trait into a three-way
   classification with a discontinuity at the threshold. The render probability
   ``Phi((|z| - midpoint) / spread)`` smears the boundary: an agent at 0.8 is a
   coin flip, one at 1.6 almost always renders. The draw is deterministic per
   ``(agent, dimension)``, so a resident's description does not flicker from day
   to day.
3. **At most two dimensions per scene.** Every prompt here already carries a
   dozen context blocks; five paragraphs of personality would crowd out the
   situation, and personality that overrides the situation is exactly the
   caricature failure mode. The scene table below picks the dimensions with an
   actual claim on that decision and drops the rest.

Anchors go in as *material*, never as an instruction line. Imperatives in these
prompts carry more weight than background, and a personality that outranks the
day's events is worse than no personality at all.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from gaworld.personality.traits import prompt_knobs_of, residual, traits_of

#: ``dimension -> (label, {pole: (mild, strong)})``. ``strong`` is used past
#: ``strong_z``; both poles exist because low C and high C are different
#: people, not one person described with a negation.
ANCHORS: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
    "o": (
        "对新事物",
        {
            "high": (
                "你对新鲜事物有兴趣，愿意在熟悉的路线上试点没试过的东西。",
                "你对没见过的东西有强烈兴趣，常主动绕路去看新开的店、试没试过的做法，哪怕会打乱原计划。",
            ),
            "low": (
                "你偏好熟悉的做法，对没试过的东西会先观望一阵。",
                "你对新鲜事物基本无感，认准的做法很少改；别人推荐的新玩意你多半不会去试。",
            ),
        },
    ),
    "c": (
        "做事方式",
        {
            "high": (
                "你做事有条理，被打断之后通常会想着把落下的补上。",
                "你会提前把当天要做的事排好顺序，被打断后一定会补回来，很少让事情过夜。",
            ),
            "low": (
                "你的计划执行得比较松，事情容易往后拖一点。",
                "你常把计划排得很满然后放掉一半，deadline 前一天才动手，且不太为此内疚。",
            ),
        },
    ),
    "e": (
        "社交倾向",
        {
            "high": (
                "你不排斥social，有人约通常会去，热闹场合待着不累。",
                "你在陌生场合会主动搭话，独处超过两天就会觉得不对劲，宁可绕路也要顺道见个人。",
            ),
            "low": (
                "你更喜欢小范围相处，临时的热闹场合会让你有点累。",
                "你会主动回避临时聚会，人多的场合待一小时就想找借口离开；恢复精力靠独处。",
            ),
        },
    ),
    "a": (
        "与人相处",
        {
            "high": (
                "你倾向于把关系维持好，不太愿意把话说僵。",
                "你很难拒绝别人，遇到分歧第一反应是先让一步，事后才觉得委屈。",
            ),
            "low": (
                "你不太会为了迁就别人改变自己的做法。",
                "你说话直接，觉得对方不对就当场讲，不太在意场面是否难看。",
            ),
        },
    ),
    "n": (
        "情绪反应",
        {
            "high": (
                "你对负面消息比较敏感，心情容易受当天的事影响。",
                "你容易把小事往坏处想，一件没落定的事会让你一整天心神不宁，情绪起落也比别人大。",
            ),
            "low": (
                "你情绪比较稳定，起落不大。",
                "你情绪很稳，出了岔子也能照常吃饭睡觉，别人急你不急。",
            ),
        },
    ),
}

#: ``scene -> (channel, dimensions)``. ``voice`` is the expressive scene, kept
#: on its own channel so "the diary reads differently" and "the decisions came
#: out differently" can be attributed separately.
SCENES: dict[str, tuple[str, tuple[str, ...]]] = {
    "routine": ("prompt", ("c", "e")),
    "action": ("prompt", ("c", "n")),
    "goals": ("prompt", ("o", "c")),
    "news": ("prompt", ("o", "n")),
    "social": ("prompt", ("e", "a")),
    "diary": ("voice", ("n", "a")),
}


def _render_probability(z_abs: float, midpoint: float, spread: float) -> float:
    if spread <= 0:
        return 1.0 if z_abs >= midpoint else 0.0
    return 0.5 * (1.0 + math.erf((z_abs - midpoint) / (spread * math.sqrt(2.0))))


def anchor_lines(
    agent: Mapping[str, Any],
    dims: Sequence[str],
    *,
    channel: str = "prompt",
    midpoint: float | None = None,
    spread: float | None = None,
    strong_z: float | None = None,
    max_dims: int | None = None,
    floor_z: float | None = None,
) -> list[str]:
    """Anchor sentences for ``agent``, most distinctive dimension first.

    Every knob defaults to ``None`` and falls back to the values the plugin
    stamped on this agent's record from ``personality.prompt.*`` — not to a
    literal, and not to CONFIG, which this module is not allowed to read. An
    explicit keyword still wins, which is what the tests and the ablation
    scripts use to sweep one knob without editing the operator's settings.
    """
    traits = traits_of(agent, channel)
    if not any(traits.values()):
        return []
    knobs = prompt_knobs_of(agent)
    midpoint = knobs["midpoint"] if midpoint is None else float(midpoint)
    spread = knobs["spread"] if spread is None else float(spread)
    strong_z = knobs["strong_z"] if strong_z is None else float(strong_z)
    max_dims = int(knobs["max_dims"] if max_dims is None else max_dims)
    floor_z = knobs["floor_z"] if floor_z is None else float(floor_z)
    picked: list[tuple[float, str]] = []
    for dim in dims:
        if dim not in ANCHORS:
            continue
        z = traits.get(dim, 0.0)
        z_abs = abs(z)
        # A hard floor, unlike the soft render probability above, and for a
        # different reason: probabilistic rendering exists so the *distinctive*
        # boundary is not a cliff, but someone sitting on the population mean
        # has no pole to describe and must never be handed one.
        if z_abs < floor_z:
            continue
        # Deterministic per (agent, dim): the same resident is described the
        # same way on day 1 and day 300.
        draw = 0.5 * (1.0 + math.erf(residual(agent, f"anchor:{dim}") / math.sqrt(2.0)))
        if draw > _render_probability(z_abs, midpoint, spread):
            continue
        label, poles = ANCHORS[dim]
        mild, strong = poles["high" if z > 0 else "low"]
        picked.append((z_abs, f"{label}：{strong if z_abs >= strong_z else mild}"))
    picked.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in picked[: max(0, max_dims)]]


def anchor_block(agent: Mapping[str, Any], scene: str, **kwargs: Any) -> str:
    """One newline-joined block for ``scene``, or ``""`` when nothing renders."""
    entry = SCENES.get(scene)
    if entry is None:
        return ""
    channel, dims = entry
    lines = anchor_lines(agent, dims, channel=channel, **kwargs)
    return "\n".join(lines)


#: The exact label the profile prompts have always used. Kept verbatim so the
#: no-traits path renders byte-identical prompts to the pre-personality build.
PROFILE_LABEL = "性格与情绪特征"

#: The behaviour paragraph authored from the sampled scores, when the profile
#: has one. Absent on the pre-rewrite corpus.
TENDENCY_LABEL = "人格与行为倾向"


def personality_line(agent: Mapping[str, Any], scene: str, **kwargs: Any) -> str:
    """Render the profile's personality material for one prompt.

    Two parts:

    1. The personality description — ``人格与行为倾向`` when the corpus has been
       rewritten, otherwise the original ``性格与情绪特征`` line. **Not both**,
       see below.
    2. The scene's anchor sentences, when the ``prompt`` channel is on. These
       pick only the dimensions that bear on *this* decision, so they overlap
       with (1) by design — that overlap is what the A4 ablation measures, not
       an accident.

    Why the new paragraph *replaces* rather than joins the old line: the two
    were written from different sources — the old line by hand alongside the
    state variables, the new one from independently sampled OCEAN scores — and
    on the current corpus they contradict each other for 9 of 51 residents
    (resident 28: 「外向、对不确定性耐受度较高」 against a paragraph where a
    client's hesitation ruins her evening; resident 48: 「情绪波动与市场高度
    相关」 against one where she naps through a mid-session crash). Printing
    both puts the contradiction on two consecutive lines of every prompt.

    Which one wins is not a coin flip. The sampled scores drive the ``rules``
    channel, and the new paragraph is the description consistent with them; if
    the prompt showed the old label instead, the prompt channel and the rules
    channel would be describing different people and the A3/A4 ablation arms
    would measure nothing.

    ``agent["personality"]`` itself is untouched, so the four subsystems that
    keyword-match it — ``dynamic.py``'s archetype table and ``is_extrovert``,
    ``finance.py``'s wealth drive, ``_heuristic_schedule``'s sleep hints —
    behave exactly as before. Only the prompt stops showing a profile that
    disagrees with itself.

    With no rewritten field and no traits, the return value is the original
    line unchanged, which is the backwards-compatibility contract.
    """
    tendencies = str(agent.get("behavior_tendencies", "") or "").strip()
    if tendencies:
        parts = [f"{TENDENCY_LABEL}：{tendencies}"]
    else:
        parts = [f"{PROFILE_LABEL}：{agent.get('personality', '')}"]
    block = anchor_block(agent, scene, **kwargs)
    if block:
        parts.append(block)
    return "\n".join(parts)
