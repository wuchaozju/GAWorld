"""The classic paradigms: what each one asks, and what humans did.

Every paradigm is a **contrast between two conditions** with a direction
the literature agrees on — framing flips risk preference, a high anchor
pulls estimates up, a responder who can veto gets offered more. The
verdict reads that direction only. Human levels (72 % / 22 %, "about a
quarter of the pie") are shown next to the residents' for comparison and
never decide anything: under ``benchmark/MECHANISM_PROVENANCE.md`` these
answers are grade (c) — what a model playing a resident says, not how
large a real effect is.

Each resident answers **every** condition, each in its own stateless
call, so no answer can see another. That makes the contrast paired by
person — the same resident, the gain frame and the loss frame — which a
human lab can only approximate with randomisation.

Wording is localised (a rare infectious disease in this city, West Lake,
yuan) but every one of these studies is famous, and a model may be
reciting the textbook rather than playing the person. Each paradigm says
so in its ``caveat``.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: Role instruction shared by every call. It names no experiment.
SYSTEM = (
    "你正在扮演一位真实的中国城市居民。完全以这个人的身份、性格和处境作答。"
    "只输出要求的 JSON 对象，不要任何别的文字。"
)


@dataclass(frozen=True)
class Item:
    """One stimulus inside a paradigm (anchoring has three; the rest one)."""

    id: str
    label: str
    #: Item-specific parameters the task text and the parser read.
    params: dict[str, Any]


@dataclass(frozen=True)
class Paradigm:
    id: str
    name: str
    #: The classic finding, one sentence.
    claim: str
    reference: str
    #: ``(control, treatment)``; the hypothesis is ``treatment − control > 0``.
    conditions: tuple[str, str]
    condition_labels: dict[str, str]
    measure: str
    #: Human results as reported, for comparison only: per condition, and
    #: under ``"effect"`` the contrast itself where the literature gives one.
    human: dict[str, str]
    caveat: str
    items: tuple[Item, ...]
    #: ``(item, condition) -> task text``; the runner puts the resident in front of it.
    task: Callable[[Item, str], str]
    #: ``(raw answer, item, condition) -> measure value or None``
    parse: Callable[[str, Item, str], float | None]
    #: The measure is a 0–1 share (shown as %); anchoring's log10 is not.
    percent: bool = True

    @property
    def control(self) -> str:
        return self.conditions[0]

    @property
    def treatment(self) -> str:
        return self.conditions[1]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_OBJECT = re.compile(r"\{.*?\}", re.S)


def answer_json(raw: str) -> dict[str, Any]:
    """The first JSON object in an answer, or ``{}``."""
    text = str(raw or "")
    for match in [*_FENCED.finditer(text), *_OBJECT.finditer(text)]:
        blob = match.group(1) if match.re is _FENCED else match.group(0)
        try:
            value = json.loads(blob)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else None


def _share(raw: str, key: str) -> float | None:
    """An amount out of 100 yuan, as a share; out-of-range answers are unusable."""
    amount = _number(answer_json(raw).get(key))
    if amount is None or not 0 <= amount <= 100:
        return None
    return amount / 100


# ---------------------------------------------------------------------------
# 1. Framing — Tversky & Kahneman (1981)
# ---------------------------------------------------------------------------

_FRAMING_INTRO = "假设本市正在为一种罕见传染病的暴发做准备，预计这种病会导致 600 人死亡。现有两套应对方案，科学估计的后果如下：\n"
_FRAMING = {
    "gain": "采用方案 A，200 人将获救。\n采用方案 B，有 1/3 的可能 600 人全部获救，有 2/3 的可能没有人获救。",
    "loss": "采用方案 A，400 人将死亡。\n采用方案 B，有 1/3 的可能没有人死亡，有 2/3 的可能 600 人全部死亡。",
}


def _framing_task(item: Item, condition: str) -> str:
    return (
        _FRAMING_INTRO
        + _FRAMING[condition]
        + '\n\n你支持哪一套方案？只输出一个 JSON 对象：{"choice": "A 或 B", "reason": "一句话"}'
    )


def _framing_parse(raw: str, item: Item, condition: str) -> float | None:
    """1 = the sure option (A in both frames)."""
    choice = str(answer_json(raw).get("choice") or "").replace("方案", "").strip().upper()
    if choice[:1] == "A":
        return 1.0
    if choice[:1] == "B":
        return 0.0
    return None


FRAMING = Paradigm(
    id="framing",
    name="框架效应（罕见传染病问题）",
    claim="同一组方案，说成「获救」时多数人选确定方案，说成「死亡」时多数人去赌",
    reference="Tversky & Kahneman 1981",
    conditions=("loss", "gain"),
    condition_labels={"gain": "获益框架", "loss": "损失框架"},
    measure="选确定方案（A）的比例",
    human={"gain": "72%（N=152）", "loss": "22%（N=155）"},
    caveat="这是最常被引用的心理学实验之一，模型很可能见过原题和结论；措辞已本地化，但复现仍可能是背出来的。",
    items=(Item("disease", "罕见传染病", {}),),
    task=_framing_task,
    parse=_framing_parse,
)


# ---------------------------------------------------------------------------
# 2. Anchoring — Jacowitz & Kahneman (1995), Many Labs 1
# ---------------------------------------------------------------------------

_ANCHOR_ITEMS = (
    Item("westlake", "杭州西湖的湖岸周长", {"unit": "公里", "low": 5, "high": 50}),
    Item("elephant", "一头成年雄性非洲象的体重", {"unit": "吨", "low": 2, "high": 20}),
    Item("births", "2023 年全国出生人口", {"unit": "万人", "low": 200, "high": 3000}),
)


def _anchor_task(item: Item, condition: str) -> str:
    unit = item.params["unit"]
    anchor = item.params[condition]
    return (
        f"凭你自己的印象回答，不用查资料。\n{item.label}，比 {anchor} {unit}多还是少？"
        f"然后说出你自己估计的数（单位：{unit}）。\n"
        '只输出一个 JSON 对象：{"compare": "多 或 少", "estimate": 数字}'
    )


def _anchor_parse(raw: str, item: Item, condition: str) -> float | None:
    """log10 of the estimate: anchors an order of magnitude apart need a log scale."""
    estimate = _number(answer_json(raw).get("estimate"))
    return math.log10(estimate) if estimate and estimate > 0 else None


ANCHORING = Paradigm(
    id="anchoring",
    name="锚定效应",
    claim="先问「比某个数多还是少」，之后的估计会被这个数拉过去",
    reference="Jacowitz & Kahneman 1995; Klein et al. 2014（Many Labs 1）",
    conditions=("low", "high"),
    condition_labels={"low": "低锚", "high": "高锚"},
    measure="估计值的 log10（三题平均）",
    human={"effect": "锚定指数（两组中位数之差 ÷ 两个锚之差）平均约 0.5（Jacowitz & Kahneman 1995）"},
    caveat="这几个量模型多半知道真值，锚定会因此偏小；模型也可能把锚当成题目给的提示。",
    items=_ANCHOR_ITEMS,
    task=_anchor_task,
    parse=_anchor_parse,
    percent=False,
)


# ---------------------------------------------------------------------------
# 3. Dictator vs ultimatum proposer — Forsythe et al. (1994)
# ---------------------------------------------------------------------------

_SPLIT_INTRO = (
    "假设这是一笔真钱：你拿到 100 元，要分一部分给另一位你不认识的本市居民。"
    "对方不知道你是谁，这样的事只发生这一次。\n"
)
_SPLIT_RULE = {
    "dictator": "你给多少，对方就拿多少，对方没有任何发言权。",
    "ultimatum": "对方会看到你的分法，然后决定接受还是拒绝：接受就按你的分法拿钱，拒绝的话两个人都一分钱拿不到。",
}


def _proposer_task(item: Item, condition: str) -> str:
    return (
        _SPLIT_INTRO
        + _SPLIT_RULE[condition]
        + '\n\n你给对方多少元（0–100 的整数）？只输出一个 JSON 对象：{"offer": 整数, "reason": "一句话"}'
    )


DICTATOR_ULTIMATUM = Paradigm(
    id="dictator_ultimatum",
    name="独裁者 vs 最后通牒（提议方）",
    claim="对方能否决时，提议方给得更多——公平里有一部分是怕被拒",
    reference="Forsythe et al. 1994; Engel 2011; Oosterbeek, Sloof & van de Kuilen 2004",
    conditions=("dictator", "ultimatum"),
    condition_labels={"dictator": "独裁者", "ultimatum": "最后通牒"},
    measure="分给对方的比例",
    human={
        "dictator": "平均约 28%（Engel 2011 元分析）",
        "ultimatum": "平均约 40%（Oosterbeek 等 2004 元分析）",
        "effect": "最后通牒高于独裁者（Forsythe 等 1994）",
    },
    caveat="钱是假想的，人类数字来自真实激励；模型可能按「公平是美德」作答，两种规则下都给一半。",
    items=(Item("split", "分 100 元", {}),),
    task=_proposer_task,
    parse=lambda raw, item, condition: _share(raw, "offer"),
)


# ---------------------------------------------------------------------------
# 4. Ultimatum responder — Güth et al. (1982), Camerer (2003)
# ---------------------------------------------------------------------------

_OFFERS = {"fair": 50, "low": 20}


def _responder_task(item: Item, condition: str) -> str:
    offer = _OFFERS[condition]
    return (
        "假设这是一笔真钱：另一位你不认识的本市居民拿到 100 元，由他提出怎么分给你们两个。"
        "你只能接受或拒绝：接受就按他的分法拿钱，拒绝的话两个人都一分钱拿不到。"
        "这样的事只发生这一次，你们互相不知道对方是谁。\n"
        f"他提出：给你 {offer} 元，他自己留 {100 - offer} 元。\n\n"
        '你接受吗？只输出一个 JSON 对象：{"accept": true 或 false, "reason": "一句话"}'
    )


def _responder_parse(raw: str, item: Item, condition: str) -> float | None:
    """1 = reject."""
    value = answer_json(raw).get("accept")
    if isinstance(value, bool):
        return 0.0 if value else 1.0
    text = str(value or "").strip()
    if text in ("不接受", "拒绝", "false", "否"):
        return 1.0
    if text in ("接受", "true", "是"):
        return 0.0
    return None


ULTIMATUM_RESPONDER = Paradigm(
    id="ultimatum_responder",
    name="最后通牒（回应方）",
    claim="明显不公的低报价常被拒绝，宁可两人都拿不到",
    reference="Güth, Schmittberger & Schwarze 1982; Camerer 2003",
    conditions=("fair", "low"),
    condition_labels={"fair": "给 50 元", "low": "给 20 元"},
    measure="拒绝的比例",
    human={"fair": "几乎都接受", "low": "低于两成的报价约一半被拒（Camerer 2003）；本题正好两成"},
    caveat="钱是假想的，拒绝不花真钱；模型可能把「拒绝不公」当成正确答案。",
    items=(Item("offer", "回应一个报价", {}),),
    task=_responder_task,
    parse=_responder_parse,
)


# ---------------------------------------------------------------------------
# 5. Trust game, in-group partner — Berg et al. (1995), Balliet et al. (2014)
# ---------------------------------------------------------------------------

_PARTNER = {
    "neighbor": "一位和你一样住在{residence}的居民，你们没打过交道",
    "stranger": "一位刚从外地来本市的人，你们没打过交道",
}


def _trust_task(item: Item, condition: str) -> str:
    # ``{residence}`` is filled per subject by the runner (see build_prompt).
    return (
        "假设这是一笔真钱：你拿到 100 元，可以从中转一部分给另一个人，转过去的钱到他手里会变成三倍。"
        "然后由他决定还给你多少——可以全部留下，一分不还。你们只打这一次交道，他不知道你是谁。\n"
        f"对方是{_PARTNER[condition]}。\n\n"
        '你转给他多少元（0–100 的整数）？只输出一个 JSON 对象：{"send": 整数, "reason": "一句话"}'
    )


TRUST_INGROUP = Paradigm(
    id="trust_ingroup",
    name="信任博弈（同小区 vs 外地人）",
    claim="人们把钱交给陌生人时会冒一部分险，而且更愿意信任自己群体里的人",
    reference="Berg, Dickhaut & McCabe 1995; Johnson & Mislin 2011; Balliet, Wu & De Dreu 2014",
    conditions=("stranger", "neighbor"),
    condition_labels={"stranger": "外地人", "neighbor": "同小区居民"},
    measure="转出的比例",
    human={
        "stranger": "平均约一半（对陌生人；Berg 等 1995，Johnson & Mislin 2011 元分析）",
        "effect": "对群体内的人合作更多，元分析 d≈0.3（Balliet 等 2014）",
    },
    caveat="「同一小区」也可能被读成以后还会碰面（声誉），不只是群体身份。",
    items=(Item("send", "转钱给对方", {}),),
    task=_trust_task,
    parse=lambda raw, item, condition: _share(raw, "send"),
)


# ---------------------------------------------------------------------------
# 6. Public goods, MPCR — Isaac & Walker (1988), Ledyard (1995)
# ---------------------------------------------------------------------------

_MPCR = {"low": (1.2, 0.3), "high": (3.0, 0.75)}


def _public_goods_task(item: Item, condition: str) -> str:
    multiplier, mpcr = _MPCR[condition]
    return (
        "假设这是一笔真钱：你和另外三位本市居民一组，每人各拿到 100 元，大家互不认识，只做这一次。"
        "每人私下决定往公共账户里投多少（0–100 元），没投的归自己。"
        f"公共账户里的钱会乘以 {multiplier} 再平均分给 4 个人——也就是说，你每投 1 元，组里每个人（包括你）各得 {mpcr} 元。\n\n"
        '你投多少元？只输出一个 JSON 对象：{"contribute": 整数, "reason": "一句话"}'
    )


PUBLIC_GOODS_MPCR = Paradigm(
    id="public_goods_mpcr",
    name="公共品博弈（回报率高 vs 低）",
    claim="一次性公共品博弈里人们投出约一半，而且公共账户回报率越高投得越多",
    reference="Isaac & Walker 1988; Ledyard 1995",
    conditions=("low", "high"),
    condition_labels={"low": "每投 1 元每人得 0.3", "high": "每投 1 元每人得 0.75"},
    measure="投入公共账户的比例",
    human={
        "low": "一次性 / 首轮约 40–60%（Ledyard 1995 综述）",
        "effect": "回报率越高投得越多（Isaac & Walker 1988）",
    },
    caveat="回报率写成「你每投 1 元每人各得多少」，比原实验更直白，可能放大效应。",
    items=(Item("contribute", "投入公共账户", {}),),
    task=_public_goods_task,
    parse=lambda raw, item, condition: _share(raw, "contribute"),
)


PARADIGMS: dict[str, Paradigm] = {
    p.id: p
    for p in (FRAMING, ANCHORING, DICTATOR_ULTIMATUM, ULTIMATUM_RESPONDER, TRUST_INGROUP, PUBLIC_GOODS_MPCR)
}


def subject_block(subject: Any) -> str:
    """Who is answering: the resident's own profile, the same one the simulator runs."""
    lines = [
        f"你是{subject.name}，{subject.age}岁{subject.gender}性，{subject.job_title}，"
        f"住在{subject.residence}，月收入约 {subject.monthly_income:.0f} 元。",
        subject.work_rhythm,
        subject.personality,
        subject.daily_life,
    ]
    return "\n".join(line for line in lines if line)


def build_prompt(paradigm: Paradigm, item: Item, condition: str, subject: Any) -> tuple[str, str]:
    """``(system, user)`` for one call."""
    task = paradigm.task(item, condition).replace("{residence}", subject.residence or "同一个小区")
    return SYSTEM, f"{subject_block(subject)}\n\n{task}"


__all__ = ["PARADIGMS", "SYSTEM", "Item", "Paradigm", "answer_json", "build_prompt", "subject_block"]
