"""Prompt arms for the demand-estimation experiment.

Five arms, crossing *who answers* with *what they are told about the
experiment*:

===================  ==========================  ================================
arm                  subject                     blinding
===================  ==========================  ================================
``blind``            none (paper Prompt 5 + 1/2)  blinded
``covariate``        synthetic demographics       blinded, covariates in the text
``unblinded``        none (paper Prompt 6)        design revealed
``agent``            GAWorld resident + world     blinded
``agent_unblinded``  GAWorld resident + world     design revealed
===================  ==========================  ================================

``blind``/``covariate``/``unblinded`` reproduce Gui & Toubia (2025) in
Chinese. The two ``agent`` arms are the contribution: the pre-treatment
covariates reach the decision through the resident's own situation
rather than through an enumerated list of factors to weigh. That matters
because the paper's Figure 4 shows the enumerated version buys
unconfoundedness at the cost of ecological validity — the simulated
customer degenerates into "buy iff price <= competitor price". Handing
the same information over as lived background (a remembered price, a
budget that feels tight) is an attempt to control the covariate without
making it salient.

Two questions run on the same grid:

``elicit``
    The paper's Prompt 1 (and appendix Prompts 7/8) — ask for the
    unspecified variables and see whether they move with the treatment.
    A diagnostic: the correct slope is zero. The elicited fields are
    deliberately *withheld* from the prompt in every arm, including the
    agent arms, or the question would be circular.

``purchase``
    The paper's Prompt 2 — the estimand.
"""

from __future__ import annotations

from dataclasses import dataclass

from gaworld.experiments.stimulus import Treatment
from gaworld.experiments.subjects import Subject, WorldContext

#: Elicited variables, in the order they appear in the CSV answer.
ELICIT_FIELDS: tuple[str, ...] = ("last_price", "competitor_price", "shelf_life_days")

_ELICIT_LINES = {
    "last_price": "你上一次购买这个商品时，它的价格是 ¥____ [最多两位小数的数字]。",
    "competitor_price": "同一货架上，竞品{competitor}当时的价格是 ¥____ [最多两位小数的数字]。",
    "shelf_life_days": "这件商品距离保质期到期还有 ____ 天 [整数]。",
}
_ELICIT_EXAMPLES = {"last_price": "12.34", "competitor_price": "11.20", "shelf_life_days": "180"}

_BLIND_SYSTEM = "你，AI，是一位顾客。你的任务是填空 ___。只返回补全后的内容，不要输出任何多余文字。"

_AGENT_SYSTEM = (
    "你，AI，正在扮演一位真实的中国城市居民。"
    "完全以这个人的身份、按他/她自己的生活习惯和处境作答，不要做市场分析。"
    "你的任务是填空 ___。只返回补全后的内容，不要输出任何多余文字。"
)

_UNBLINDED_SYSTEM = (
    "你，AI，是预测顾客行为的专家。现有一项关于{category}类商品「{product}」购买决策的调查："
    "该商品的价格是在 {min_price} 元到 {max_price} 元之间均匀随机抽取的，"
    "顾客只会看到其中一个价格，且对这一随机化设计并不知情。"
    "顾客拿到的调查如下。你的任务是填空 ___。只返回补全后的内容，不要输出任何多余文字。"
)


@dataclass(frozen=True)
class PromptSpec:
    """One model call: a system message and a user message."""

    system: str
    user: str


@dataclass(frozen=True)
class Arm:
    id: str
    needs_subject: bool
    unblinded: bool
    grounded: bool
    note: str


ARMS: dict[str, Arm] = {
    "blind": Arm("blind", False, False, False, "论文基线：盲化、无协变量"),
    "covariate": Arm("covariate", True, False, False, "论文 §3：把人口学与竞品价写进提示词"),
    "unblinded": Arm("unblinded", False, True, False, "论文 Prompt 6：公开随机化设计"),
    "agent": Arm("agent", True, False, True, "GAWorld 居民 + 世界状态，盲化"),
    "agent_unblinded": Arm("agent_unblinded", True, True, True, "GAWorld 居民 + 世界状态，非盲"),
}


def _price_support(treatment: Treatment, grid: tuple[float, ...]) -> tuple[float, float]:
    regular = treatment.product.regular_price
    return round(regular * min(grid), 2), round(regular * max(grid), 2)


def _system_prompt(arm: Arm, treatment: Treatment, grid: tuple[float, ...]) -> str:
    if arm.unblinded:
        low, high = _price_support(treatment, grid)
        return _UNBLINDED_SYSTEM.format(
            category=treatment.product.category,
            product=treatment.product.label,
            min_price=f"{low:.2f}",
            max_price=f"{high:.2f}",
        )
    return _AGENT_SYSTEM if arm.grounded else _BLIND_SYSTEM


def _budget_phrase(context: WorldContext) -> str:
    """Qualitative, on purpose.

    A number here would invite the model to do arithmetic against the
    price — which is the focalism failure the agent arms exist to avoid.
    """
    if context.budget_left_ratio >= 0.6:
        return "这个月的日常开销还宽裕。"
    if context.budget_left_ratio >= 0.35:
        return "这个月的日常开销还算正常。"
    return "这个月手头有点紧，买东西比平时更留意价格。"


def _scene(arm: Arm, treatment: Treatment, subject: Subject | None, context: WorldContext | None) -> str:
    product = treatment.product
    if not arm.grounded:
        return (
            f"请考虑以下商品类别：{product.category}。\n\n"
            f"假设你正在一家超市，看到该类别下的这个商品：{product.label}。\n"
        )
    assert subject is not None and context is not None
    return (
        f"你是{subject.name}，{subject.age}岁{subject.gender}性，"
        f"{subject.job_title}，住在{subject.residence}。\n"
        f"{subject.work_rhythm}\n"
        f"{subject.personality}\n"
        f"{subject.daily_life}\n\n"
        f"你在{context.store}，看到货架上的{product.label}。\n"
    )


def _covariate_block(treatment: Treatment, subject: Subject, context: WorldContext) -> str:
    """The paper's §3 control block: covariates stated as explicit facts."""
    return (
        f"你的基本情况：{subject.demographics}。\n"
        f"同一货架上，竞品{treatment.product.competitor}的价格是 {context.competitor_price:.2f} 元。\n"
        f"你上一次购买该商品的价格是 {context.last_paid:.2f} 元。\n"
    )


def _grounding_block(treatment: Treatment, context: WorldContext) -> str:
    """The agent arms' control block: the same facts, as lived background."""
    return (
        f"你记得上次在这里买它花了 {context.last_paid:.2f} 元。"
        f"旁边的{treatment.product.competitor}标着 {context.competitor_price:.2f} 元。"
        f"{_budget_phrase(context)}\n"
    )


def _elicit_body(treatment: Treatment, fields: tuple[str, ...]) -> str:
    lines = [_ELICIT_LINES[name].format(competitor=treatment.product.competitor) for name in fields]
    example = ",".join(_ELICIT_EXAMPLES[name] for name in fields)
    return (
        "\n".join(lines)
        + f"\n\n该商品当前的价格是：{treatment.price:.2f} 元。\n\n返回示例：{example}"
    )


def _purchase_body(treatment: Treatment) -> str:
    return (
        f"该商品当前的价格是 {treatment.price:.2f} 元。你会不会购买这个商品？\n"
        '____ ["购买" 或 "不购买"]\n\n返回示例：购买'
    )


def build_prompt(
    arm_id: str,
    question: str,
    treatment: Treatment,
    *,
    subject: Subject | None = None,
    context: WorldContext | None = None,
    grid: tuple[float, ...] = (0.0, 2.0),
    elicit_fields: tuple[str, ...] = ELICIT_FIELDS,
) -> PromptSpec:
    """Assemble the system/user pair for one cell of the design."""
    arm = ARMS.get(arm_id)
    if arm is None:
        raise ValueError(f"Unknown arm '{arm_id}'. Known: {', '.join(sorted(ARMS))}")
    if question not in {"elicit", "purchase"}:
        raise ValueError(f"Unknown question '{question}'. Known: elicit, purchase")
    if arm.needs_subject and (subject is None or context is None):
        raise ValueError(f"Arm '{arm_id}' requires a subject and its world context.")

    parts = [_scene(arm, treatment, subject, context)]

    # Covariates are withheld from the elicitation question in every arm:
    # asking a model to report a number we just handed it measures nothing.
    if question == "purchase" and subject is not None and context is not None:
        if arm_id == "covariate":
            parts.append(_covariate_block(treatment, subject, context))
        elif arm.grounded:
            parts.append(_grounding_block(treatment, context))
    elif question == "elicit" and arm.grounded and context is not None:
        parts.append(_budget_phrase(context) + "\n")

    parts.append(
        _elicit_body(treatment, elicit_fields) if question == "elicit" else _purchase_body(treatment)
    )
    return PromptSpec(system=_system_prompt(arm, treatment, grid), user="\n".join(parts))
