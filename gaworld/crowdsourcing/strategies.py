"""The coordination mechanisms a crowd can run under.

Four strategies, and the difference between them is *who gets to act in a
round* and *how the round's answer is chosen*:

``market``
    Market-based post-training (Xu et al., arXiv:2610.22322). Every agent
    bids for the right to work on the task; the market clears the highest
    bids; the outcome gives each bidder a local credit, and the credit feeds
    back into how they bid next round. No central coordinator decides who
    works — the bids do.
``vote``
    Everyone who acts answers on their own and the crowd clusters the answers
    by similarity. The majority cluster wins, and its agreement ratio is the
    crowd's confidence in the answer.
``elite``
    The strongest agents by accumulated credit keep acting and improve on
    their own previous answer. A tournament, not a conversation.
``debate``
    The best answers are shortlisted and then critique each other; a final
    pass picks the winner.

Pruning (who survives between rounds) is deliberately *not* part of a
strategy: it is an independent switch, so any mechanism can be run with or
without narrowing the pool towards the agents that did well.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """Everything the API and the UI need to describe one mechanism."""

    id: str
    name: str
    name_en: str
    summary: str
    mechanics: tuple[str, ...]
    source: str = ""
    bids: bool = False
    critique: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "name_en": self.name_en,
            "summary": self.summary,
            "mechanics": list(self.mechanics),
            "source": self.source,
            "bids": self.bids,
            "critique": self.critique,
        }


MPT_SOURCE = "https://arxiv.org/abs/2610.22322"

STRATEGIES: dict[str, StrategySpec] = {
    "market": StrategySpec(
        id="market",
        name="市场竞价",
        name_en="Market-based bidding",
        summary=(
            "智能体各自投标表达参与的意愿与把握，价格出清决定谁动手；"
            "结果再回过头给每个投标者一份局部信用，让下一轮的报价更贴近真实能力。"
            "没有中央调度者，谁干活由报价决定。"
        ),
        mechanics=("bid", "clear", "act", "credit", "evolve"),
        source=MPT_SOURCE,
        bids=True,
    ),
    "vote": StrategySpec(
        id="vote",
        name="众包投票",
        name_en="Crowd voting",
        summary=(
            "参与者各自独立作答，按答案的相似度聚类，多数簇代表群体的共识，簇的大小就是这次众包的同意度。"
        ),
        mechanics=("sample", "attempt", "cluster", "vote"),
    ),
    "elite": StrategySpec(
        id="elite",
        name="精英进化",
        name_en="Elite tournament",
        summary=("按累积信用只让最强的智能体继续，他们在上一轮自己的答案基础上改进，逐轮逼近更好的解。"),
        mechanics=("rank", "attempt", "improve", "score"),
    ),
    "debate": StrategySpec(
        id="debate",
        name="辩论评审",
        name_en="Debate and critique",
        summary=("先各自作答并评分，选出终选答案互相挑刺，最后由评审定夺。"),
        mechanics=("attempt", "score", "shortlist", "critique", "judge"),
        critique=True,
    ),
}

DEFAULT_STRATEGY = "market"


def strategy_catalog() -> list[dict[str, Any]]:
    """The strategy list the dashboard renders its picker from."""
    return [spec.to_dict() for spec in STRATEGIES.values()]


def get_strategy(strategy_id: str) -> StrategySpec:
    spec = STRATEGIES.get(str(strategy_id))
    if spec is None:
        raise ValueError(f"unknown strategy: {strategy_id}")
    return spec


# --------------------------------------------------------------------------
# Answer similarity
# --------------------------------------------------------------------------
#
# Chinese answers rarely share a long literal phrase, so token overlap misses
# almost everything. Character bigrams catch the shared wording that does
# exist ("公共空间" vs "公共 空间"), and Jaccard on them gives a usable
# "are these two answers basically the same thing" signal.


def _bigrams(text: Any) -> set[str]:
    clean = "".join(char for char in str(text or "").lower() if char.isalnum())
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[index : index + 2] for index in range(len(clean) - 1)}


def similarity(left: Any, right: Any) -> float:
    """Jaccard overlap of the two texts' character bigrams, in ``[0, 1]``."""
    first = _bigrams(left)
    second = _bigrams(right)
    if not first or not second:
        return 0.0
    intersection = len(first & second)
    union = len(first | second)
    return intersection / union if union else 0.0


def cluster_attempts(
    attempts: list[dict[str, Any]],
    *,
    threshold: float = 0.22,
) -> list[list[dict[str, Any]]]:
    """Group attempts that say roughly the same thing.

    Longer answers are treated as more representative and seed the clusters
    first, so a short one-liner that happens to share vocabulary with a
    thorough answer does not become the cluster's centre by accident.
    """
    ordered = sorted(
        attempts,
        key=lambda item: len(str(item.get("text") or "")),
        reverse=True,
    )
    clusters: list[list[dict[str, Any]]] = []
    centres: list[str] = []
    for attempt in ordered:
        text = str(attempt.get("text") or "")
        placed = False
        for index, centre in enumerate(centres):
            if similarity(text, centre) >= threshold:
                clusters[index].append(attempt)
                placed = True
                break
        if not placed:
            clusters.append([attempt])
            centres.append(text)
    return clusters
