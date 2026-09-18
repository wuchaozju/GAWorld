"""Render a persona into the three shapes the rest of the system consumes.

``agent_payload``   → the dict ``dashboard_server._create_agent`` takes
``profile_block``   → the 思维框架 section appended to the agent's profile
``skill_markdown``  → a ``nuwa``-shaped ``SKILL.md``

Why the framework is appended to the *profile* rather than kept in the archive:
the profile Markdown is what the simulator actually reads into an agent's
prompt. A mental model that lives only in ``output/personas/`` would have no
effect on how the resident behaves, which is the entire point of distilling it.

Every renderer here is pure — a profile in, a string out — so the tests can
check the wording without touching the network, a model, or the disk.
"""

from __future__ import annotations

from gaworld.persona.distill import PersonaProfile

#: Marks the appended section so a later re-distillation can find and replace
#: it instead of stacking a second copy under the same profile.
FRAMEWORK_HEADING = "**思维框架（蒸馏自公开资料）**"


def agent_payload(profile: PersonaProfile) -> dict:
    """Identity + nine state seeds, ready for ``_create_agent``."""
    payload = profile.identity_payload()
    payload["state"] = dict(profile.state)
    return payload


def _bullets(items: list[str], indent: str = "- ") -> str:
    return "".join(f"{indent}{item}\n" for item in items if item)


def profile_block(profile: PersonaProfile) -> str:
    """The framework section for the agent's profile Markdown.

    Returns ``""`` when nothing was distilled, so a persona with no usable
    framework does not leave an empty heading in the profile file.
    """
    if not profile.has_framework and not profile.boundaries:
        return ""
    lines = [f"\n{FRAMEWORK_HEADING}\n"]
    if profile.summary:
        lines.append(f"\n{profile.summary}\n")

    if profile.mental_models:
        lines.append("\n*心智模型*：\n")
        for model in profile.mental_models:
            gist = f"：{model.gist}" if model.gist else ""
            lines.append(f"- **{model.name}**{gist}\n")
            if model.limits:
                lines.append(f"  - 失效条件：{model.limits}\n")

    if profile.heuristics:
        lines.append("\n*决策启发式*：\n")
        lines.append(_bullets([h.rule for h in profile.heuristics]))

    voice = profile.voice
    if not voice.is_empty():
        bits = [
            f"句式：{voice.sentences}" if voice.sentences else "",
            f"用词：{voice.vocabulary}" if voice.vocabulary else "",
            f"节奏：{voice.rhythm}" if voice.rhythm else "",
            f"幽默：{voice.humor}" if voice.humor else "",
            f"确定性：{voice.certainty}" if voice.certainty else "",
        ]
        lines.append("\n*表达方式*：" + "；".join(b for b in bits if b) + "\n")
        if voice.phrases:
            lines.append(f"\n*口头禅*：{'、'.join(voice.phrases)}\n")

    if profile.values_ranked:
        lines.append(f"\n*价值排序*：{' > '.join(profile.values_ranked)}\n")
    if profile.anti_patterns:
        lines.append("\n*绝不会做*：\n")
        lines.append(_bullets(profile.anti_patterns))
    if profile.tensions:
        lines.append("\n*内在张力*：\n")
        lines.append(_bullets(profile.tensions))
    if profile.boundaries:
        lines.append("\n*画像边界*：\n")
        lines.append(_bullets(profile.boundaries))
    if profile.sources:
        cited = "；".join(f"{s.get('title') or s.get('url')}" for s in profile.sources[:5])
        lines.append(f"\n*资料来源*：{cited}\n")
    return "".join(lines)


def insert_block(profile_text: str, block: str) -> str:
    """Splice *block* into a profile section, ahead of its closing rule.

    Profile blocks end with a ``---`` that separates one resident from the
    next. Appending past it would leave that rule sitting in the middle of the
    section and the file's last resident without one, so the framework goes in
    front of it instead.
    """
    text = str(profile_text or "").rstrip()
    if not block:
        return text
    if text.endswith("---"):
        return text[: -len("---")].rstrip() + "\n" + block.rstrip() + "\n\n---"
    return text + "\n" + block.rstrip()


def skill_markdown(profile: PersonaProfile) -> str:
    """A ``nuwa``-shaped perspective skill for this person.

    Same section order as the skill ``nuwa`` writes — 心智模型 / 决策启发式 /
    表达DNA / 反模式 / 诚实边界 — so a reader who knows one knows the other.
    The front matter is YAML because that is what the skill loader reads; the
    description doubles as the trigger line.
    """
    name = profile.name or profile.subject
    trigger = f"「{name}」「{name}会怎么看」「{name}的思维方式」"
    head = (
        "---\n"
        f"name: {profile.slug or name}-perspective\n"
        "description: |\n"
        f"  蒸馏 {name} 的思维框架：{profile.summary or '基于公开资料的认知画像'}。\n"
        f"  核心心智模型：{len(profile.mental_models)}个｜决策启发式：{len(profile.heuristics)}条\n"
        f"  触发词：{trigger}\n"
        "---\n\n"
        f"# {name} · 思维框架\n\n"
        "> 由 GAWorld 智能体工作台从公开资料蒸馏生成。捕捉的是 HOW they think，不是 WHAT they said。\n\n"
    )

    body = [f"## 这是谁\n\n{profile.summary or '（资料不足）'}\n\n"]
    if profile.job:
        body.append(f"- 职业：{profile.job}\n")
    if profile.residence:
        body.append(f"- 所在：{profile.residence}\n")
    if profile.lineage:
        body.append(f"- 智识谱系：{'、'.join(profile.lineage)}\n")
    body.append("\n")

    body.append("## 心智模型\n\n")
    if profile.mental_models:
        for index, model in enumerate(profile.mental_models, start=1):
            body.append(f"### {index}. {model.name}\n\n{model.gist}\n\n")
            if model.evidence:
                body.append("**证据**：\n" + _bullets(model.evidence) + "\n")
            if model.limits:
                body.append(f"**局限**：{model.limits}\n\n")
    else:
        body.append("（材料不足以支撑任何跨领域复现的心智模型。）\n\n")

    body.append("## 决策启发式\n\n")
    if profile.heuristics:
        for item in profile.heuristics:
            example = f"　*例*：{item.example}" if item.example else ""
            body.append(f"- {item.rule}{example}\n")
        body.append("\n")
    else:
        body.append("（未提炼出可复用的决策规则。）\n\n")

    voice = profile.voice
    body.append("## 表达 DNA\n\n")
    if voice.is_empty():
        body.append("（材料不足。）\n\n")
    else:
        body.append("| 维度 | 特征 |\n|------|------|\n")
        for label, value in (
            ("句式偏好", voice.sentences),
            ("词汇特征", voice.vocabulary),
            ("节奏感", voice.rhythm),
            ("幽默方式", voice.humor),
            ("确定性表达", voice.certainty),
        ):
            if value:
                body.append(f"| {label} | {value} |\n")
        body.append("\n")
        if voice.phrases:
            body.append(f"**标志性短语**：{'、'.join(voice.phrases)}\n\n")

    if profile.values_ranked:
        body.append("## 价值排序\n\n" + _bullets(profile.values_ranked) + "\n")
    if profile.anti_patterns:
        body.append("## 反模式（绝不做的事）\n\n" + _bullets(profile.anti_patterns) + "\n")
    if profile.tensions:
        body.append("## 内在张力\n\n" + _bullets(profile.tensions) + "\n")

    body.append("## 诚实边界\n\n" + _bullets(profile.boundaries or ["未记录。"]) + "\n")

    if profile.sources:
        body.append("## 资料来源\n\n")
        for source in profile.sources:
            title = source.get("title") or source.get("url", "")
            body.append(f"- [{title}]({source.get('url', '')})\n")
        body.append("\n")

    return head + "".join(body)
