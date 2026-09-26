"""What a study is allowed to measure.

The catalogue of outcomes, and nothing else: a hypothesis that names a
measure outside this table is dropped at compile time rather than carried
into a run it can never be scored on. It plays the same role for the
protocol compiler that ``docs/FEATURES.md`` plays for the workbench — the
one list the model may cite — with the difference that this one is code,
because the evaluator has to read the very column the prompt promised.

Phase one registers the state metrics only: the per-agent, per-step values
in ``state/agent_state_history.csv``, which are exactly what the parallel
worlds report already compares across worlds. Economy ledger columns,
network statistics and interview tallies arrive with the backends that
produce them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gaworld.parallel.analysis import METRIC_LABELS

#: How a per-step series is reduced to one number per world.
AGGREGATIONS = ("final", "mean")

STATE_SOURCE = "state/agent_state_history.csv"

_CORE = "九维状态之一，0–1 归一化"
_INTERVENTION = "PolicySim 干预插件记录，0–1；需要 CONFIG[intervention][enabled]"
_NEEDS = "生理 / 需求状态，0–1"

#: A note per metric keeps the model from predicting a 0.5 shift on a
#: variable whose whole range is 0–1, and from picking an intervention
#: metric on a run where the plugin is off.
_NOTES: dict[str, str] = {
    "emotion": _CORE,
    "stress": _CORE,
    "econ_security": _CORE,
    "city_identity": _CORE,
    "policy_sensitivity": _CORE,
    "platform_dependence": _CORE,
    "risk_preference": _CORE,
    "voice_propensity": _CORE,
    "mobility_intent": _CORE,
    "stance_score": _INTERVENTION,
    "toxicity_score": _INTERVENTION,
    "misinformation_risk": _INTERVENTION,
    "cross_viewpoint_exposure": _INTERVENTION,
    "intervention_reward": _INTERVENTION,
    "energy": _NEEDS,
    "hunger": _NEEDS,
    "fatigue_debt": _NEEDS,
    "self_control": _NEEDS,
    "social_need": _NEEDS,
    "time_pressure": _NEEDS,
}


@dataclass(frozen=True)
class Measure:
    """One column a study may score a hypothesis on."""

    id: str
    label: str
    source: str
    family: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def registry() -> dict[str, Measure]:
    """Every measurable outcome, keyed by id, in a stable order."""
    return {
        metric: Measure(id=metric, label=label, source=STATE_SOURCE, family="state", note=_NOTES.get(metric, ""))
        for metric, label in METRIC_LABELS.items()
    }


def resolve(name: Any, reg: dict[str, Measure] | None = None) -> Measure | None:
    """Match a model-given name by id or display label.

    Models answer in the language of the prompt, so ``"压力"`` has to find
    ``stress``; ids are matched case-insensitively for the same reason.
    """
    reg = registry() if reg is None else reg
    text = str(name or "").strip()
    if not text:
        return None
    if text in reg:
        return reg[text]
    lowered = text.lower()
    for measure in reg.values():
        if measure.id.lower() == lowered or measure.label == text:
            return measure
    return None


def render_registry(reg: dict[str, Measure] | None = None) -> str:
    """The table the compile prompt shows the model."""
    reg = registry() if reg is None else reg
    lines = ["| id | 名称 | 来源 | 说明 |", "|---|---|---|---|"]
    lines += [f"| {m.id} | {m.label} | {m.source} | {m.note} |" for m in reg.values()]
    return "\n".join(lines)


__all__ = ["AGGREGATIONS", "STATE_SOURCE", "Measure", "registry", "render_registry", "resolve"]
