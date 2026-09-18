"""Build one interview turn's prompt, and parse the answer back out.

The turn is the unit: one respondent, one question, one model call. Asking a
whole round in a single call would be cheaper, and is what the single-agent
interview does — but it costs the two things this feature is for. A batched
call gives the model licence to answer six questions in one flowing
paragraph, which defeats per-question choice/boolean parsing; and it collapses
the series into a single moment, when the requirement is that question 4 is
answered by someone who remembers answering question 1.

So each turn replays the respondent's own prior Q&A. That replay *is* the
continuous memory — deliberately a transcript rather than a write into the
agent's episodic store, so surveying a population never changes it.

Parsing is forgiving about form and strict about content. A model that wraps
its JSON in prose still gets read (:func:`extract_json` handles the wrapping),
but a choice answer that names something outside the declared options is
marked ``unparsed`` and left out of the tally rather than guessed at.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Reused rather than re-implemented: this is the repo's one careful
# brace-matching JSON extractor (handles ``` fences and prose-wrapped
# objects), and a second copy would drift from it.
from gaworld.collaboration._parsing import extract_json
from gaworld.interview.attachments import ResolvedMaterial
from gaworld.interview.schema import Answer, Question

#: Truthy / falsy words a boolean answer may arrive as, in either language.
_YES_WORDS = ("是", "对", "同意", "会", "有", "支持", "yes", "true", "agree")
_NO_WORDS = ("不是", "否", "不对", "不同意", "不会", "没有", "反对", "no", "false", "disagree")

#: Leading enumerators a model puts in front of an option it picked:
#: "A. 支持", "1) 支持", "选项二：支持".
_ENUMERATOR_RE = re.compile(
    r"^\s*(?:选项)?\s*[\(\[【]?\s*[A-Za-z0-9一二三四五六七八九十]{1,3}\s*[\)\]】.、:：,，]\s*"
)


def _normalize(text: Any) -> str:
    """Casefold and strip punctuation/space so labels compare by content."""
    raw = unicodedata.normalize("NFKC", str(text or "")).strip().casefold()
    return re.sub(r"[\s　·。，,、.:：;；!！?？\"'“”‘’()（）\[\]【】]+", "", raw)


def _material_block(material: ResolvedMaterial) -> str:
    if not material or not material.items:
        return ""
    lines: list[str] = []
    for index, item in enumerate(material.items, start=1):
        if item.kind == "url":
            head = f"材料{index}（网页：{item.source}）"
            body = item.text or "（无法读取正文）"
        elif item.has_image:
            # The picture itself rides on the API call, not in the text. The
            # line is here so the model is told a picture exists and which
            # numbered material it is.
            head = f"材料{index}（图片，见本次附带的图像）"
            body = item.caption or "（无额外说明）"
        else:
            head = f"材料{index}（图片，仅有文字说明）"
            body = item.text or item.caption or "（无说明）"
        lines.append(f"{head}：\n{body}")
    return "【随问题提供的材料】\n" + "\n\n".join(lines)


def _history_block(history: list[tuple[Question, Answer]]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for question, answer in history:
        said = answer.text.strip()
        if answer.choice:
            said = f"（我选了：{'、'.join(answer.choice)}）{said}".strip()
        elif answer.boolean is not None:
            said = f"（我的回答：{'是' if answer.boolean else '否'}）{said}".strip()
        lines.append(f"问：{question.text}\n我答：{said or '（当时没答上来）'}")
    return "【这次访谈里你已经说过的话】\n" + "\n\n".join(lines)


def _format_contract(question: Question) -> str:
    """What shape the answer must take, and the JSON envelope to use."""
    if question.kind == "boolean":
        return (
            "这是一道是非题。你必须先明确表态「是」或「否」，不能含糊，然后用一两句话说明理由。\n"
            '只输出 JSON：{"yes": true 或 false, "reason": "一两句话的理由"}'
        )
    if question.kind == "choice":
        listed = "\n".join(f"  - {option}" for option in question.options)
        count = "可以选多个" if question.multi else "只能选一个"
        return (
            f"这是一道选择题，{count}。你必须从下面的选项里原样挑出你的答案，不要自己造新选项：\n"
            f"{listed}\n"
            "然后用一两句话说明你为什么这么选。\n"
            '只输出 JSON：{"choice": ["原样抄写的选项"], "reason": "一两句话的理由"}'
        )
    return (
        "用 2-4 句话回答，说你自己的真实想法和经历，不要写成报告或列要点。\n"
        '只输出 JSON：{"answer": "你的回答"}'
    )


def build_turn_prompt(
    *,
    persona: str,
    context: str,
    question: Question,
    material: ResolvedMaterial | None = None,
    history: list[tuple[Question, Answer]] | None = None,
    turn_no: int = 1,
    total: int = 1,
) -> str:
    """Assemble the prompt for one respondent answering one question.

    ``persona`` is the respondent block — a resident's profile and recalled
    memories, or a cohort's statistics — supplied by the caller so this
    module stays free of any dependency on the simulator's agent objects.
    """
    blocks = [
        persona.strip(),
        f"这是一次访谈，一共 {total} 个问题，现在是第 {turn_no} 个。" if total > 1 else "这是一次访谈。",
        "回答要真实、具体，基于你自己的处境和经历，不要说教，也不要替别人代言。",
    ]
    if context.strip():
        blocks.append(f"【访谈背景】\n{context.strip()}")
    history_block = _history_block(history or [])
    if history_block:
        blocks.append(history_block)
        blocks.append("如果这个问题和你前面说过的话有关，就接着那儿讲，保持前后一致。")
    material_block = _material_block(material) if material else ""
    if material_block:
        blocks.append(material_block)
    blocks.append(f"【问题】\n{question.text}")
    blocks.append(f"【回答要求】\n{_format_contract(question)}")
    return "\n\n".join(block for block in blocks if block)


def _match_options(candidates: list[str], question: Question) -> list[str]:
    """Map whatever the model said onto the declared option labels."""
    by_norm = {_normalize(option): option for option in question.options}
    matched: list[str] = []
    for raw in candidates:
        text = _ENUMERATOR_RE.sub("", str(raw or "").strip())
        norm = _normalize(text)
        if not norm:
            continue
        hit = by_norm.get(norm)
        if hit is None:
            # Containment either way: the model may answer "我选支持" for the
            # option "支持", or abbreviate a long option to its distinctive
            # part. Longest option wins so "支持" cannot swallow "不支持".
            for option_norm, option in sorted(by_norm.items(), key=lambda kv: -len(kv[0])):
                if option_norm and (option_norm in norm or norm in option_norm):
                    hit = option
                    break
        if hit is not None and hit not in matched:
            matched.append(hit)
    if not question.multi:
        return matched[:1]
    return matched


def _parse_boolean(payload: dict[str, Any], raw: str) -> bool | None:
    for key in ("yes", "answer", "value", "boolean"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            norm = _normalize(value)
            # Check the negatives first: "不是" contains "是".
            if any(word in norm for word in (_normalize(w) for w in _NO_WORDS)):
                return False
            if any(word in norm for word in (_normalize(w) for w in _YES_WORDS)):
                return True
    norm = _normalize(raw)[:40]
    if any(_normalize(word) in norm for word in _NO_WORDS):
        return False
    if any(_normalize(word) in norm for word in _YES_WORDS):
        return True
    return None


def parse_answer(raw: Any, question: Question) -> Answer:
    """Read a model reply into an :class:`Answer` for ``question``.

    Never raises and never discards the prose: an answer that fails its
    format contract is still shown in the Markdown document (a resident did
    say something), it is only barred from the tally, and ``unparsed`` says
    so explicitly so the report can report the shortfall instead of a
    silently smaller denominator.
    """
    text = str(raw or "").strip()
    payload = extract_json(text)
    answer = Answer(question_id=question.id)
    reason = str(payload.get("reason") or "").strip()

    if question.kind == "boolean":
        answer.boolean = _parse_boolean(payload, text)
        answer.reason = reason
        answer.text = reason or _plain_text(payload, text)
        answer.unparsed = answer.boolean is None
        return answer

    if question.kind == "choice":
        raw_choice = payload.get("choice", payload.get("answer"))
        if isinstance(raw_choice, str):
            # A single string may still hold several picks for a multi-select.
            candidates = re.split(r"[、,，;；/|]+", raw_choice) if question.multi else [raw_choice]
        elif isinstance(raw_choice, (list, tuple)):
            candidates = [str(item) for item in raw_choice]
        else:
            candidates = []
        answer.choice = _match_options(candidates, question)
        if not answer.choice:
            # Last resort: the option may be named in the free prose.
            answer.choice = _match_options([text], question)
        answer.reason = reason
        answer.text = reason or _plain_text(payload, text)
        answer.unparsed = not answer.choice
        return answer

    answer.text = _plain_text(payload, text)
    answer.reason = reason
    answer.unparsed = not answer.text
    return answer


def _plain_text(payload: dict[str, Any], raw: str) -> str:
    for key in ("answer", "text", "reason", "response"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # No JSON at all: the reply itself is the answer. Strip a leading fence
    # so the document does not carry ``` noise.
    cleaned = re.sub(r"^```[A-Za-z0-9_-]*\s*|\s*```$", "", raw).strip()
    return cleaned


__all__ = ["build_turn_prompt", "parse_answer"]
