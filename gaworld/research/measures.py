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

Every measure also carries a **provenance grade** — the weakest grade among
the mechanisms that produce it, on the scale of
``benchmark/MECHANISM_PROVENANCE.md`` — and a one-line ``basis`` saying what
those mechanisms are. A (c) measure is driven by numbers we chose rather than
calibrated, so a study may read its *direction* but not its *size*: the
evaluator and the report say so next to every effect on one. Today every
measure in the catalogue is (c); the grade is there so that stays visible,
and so a ledger-derived (b) measure, when one arrives, is told apart.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gaworld.parallel.analysis import METRIC_LABELS

#: How a per-step series is reduced to one number per world.
AGGREGATIONS = ("final", "mean")

STATE_SOURCE = "state/agent_state_history.csv"

#: Grades of ``benchmark/MECHANISM_PROVENANCE.md``, and what each lets a study say.
GRADES: dict[str, str] = {
    "a": "从真实数据校准：可以单独立论",
    "b": "文献中的标准机制、参数有公开区间：可以单独立论，须注明出处",
    "c": "自定的合理猜测或按目标标定的旋钮：不得单独立论，只读方向，效应大小不作数",
}

#: Grades whose effects may be read for direction only.
DIRECTION_ONLY = frozenset({"c"})

_CORE = "九维状态之一，0–1 归一化"
_INTERVENTION = "PolicySim 干预插件记录，0–1；需要 CONFIG[intervention][enabled]"
_NEEDS = "生理 / 需求状态，0–1"

#: What drives the nine core states, for every one of them. The first clause
#: is the one a reader most needs: an event moves these states by a delta one
#: model call proposes for it, so the direction of an event's effect is the
#: model's own judgement of that event, carried forward by hand-set dynamics.
_CORE_BASIS = (
    "事件与政策对它的影响由一次模型调用直接给出（每件事 ±0.2 以内，`infer_event_effect`）——效应方向就是模型对这件事的判断；"
    "之后按手写的均值回归公式（目标值与系数都是定的，`update_state`）每步拉回；"
    "人生事件与家庭事件另带固定增量（数值是定的）"
)
_EXTRA_BASIS: dict[str, str] = {
    "emotion": "；另受社交情绪传染、动态行为心情增量、记忆唤起影响（系数都是定的）",
    "stress": "；另受记忆唤起、当日消费被截断（+0.02）、家庭单职工负担影响（系数都是定的）",
    "econ_security": "；另每天按账本资产 / 三个月开销平滑更新（权重 0.85 / 0.15 是定的）",
}
_INTERVENTION_BASIS = (
    "干预插件对信息流与居民所写文字做关键词匹配后打分（关键词表与权重都是定的），文字由模型生成"
)
_NEEDS_BASIS = "人类真实感模块的手写规则（目标值与回归速率都是定的）；人生事件与家庭事件另带固定增量"

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
    "stance_score": "PolicySim 干预插件记录，取值 −1–1（正面关键词减负面关键词，按 0.8 平滑）；需要 CONFIG[intervention][enabled]",
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
    #: Weakest provenance grade among the mechanisms behind it (``GRADES``).
    grade: str = "c"
    #: What those mechanisms are, in a sentence a reader can check.
    basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _basis(metric: str) -> str:
    if _NOTES.get(metric) == _CORE:
        return _CORE_BASIS + _EXTRA_BASIS.get(metric, "")
    if metric == "stance_score" or _NOTES.get(metric) == _INTERVENTION:
        return _INTERVENTION_BASIS
    if _NOTES.get(metric) == _NEEDS:
        return _NEEDS_BASIS
    return ""


def registry() -> dict[str, Measure]:
    """Every measurable outcome, keyed by id, in a stable order."""
    return {
        metric: Measure(
            id=metric, label=label, source=STATE_SOURCE, family="state", note=_NOTES.get(metric, ""),
            grade="c", basis=_basis(metric),
        )
        for metric, label in METRIC_LABELS.items()
    }


def direction_only(grade: Any) -> bool:
    """Whether an effect on a measure of this grade is read for direction only.

    An unknown grade (a protocol saved before grades existed, a measure from
    nowhere) counts as (c): the cautious reading is the default one.
    """
    value = str(grade or "").strip().lower()
    return value not in GRADES or value in DIRECTION_ONLY


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
    lines = ["| id | 名称 | 来源 | 等级 | 说明 |", "|---|---|---|---|---|"]
    lines += [f"| {m.id} | {m.label} | {m.source} | ({m.grade}) | {m.note} |" for m in reg.values()]
    return "\n".join(lines)


__all__ = [
    "AGGREGATIONS",
    "DIRECTION_ONLY",
    "GRADES",
    "STATE_SOURCE",
    "Measure",
    "direction_only",
    "registry",
    "render_registry",
    "resolve",
]
