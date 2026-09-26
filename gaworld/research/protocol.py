"""Compile a research plan into a pre-registered, executable protocol.

A :class:`~gaworld.research.workbench.ResearchPlan` is a document: its
conditions, events and measures are prose the model wrote for a person.
The protocol is the same study written for the runner — every condition
is already a world, every hypothesis names a measure from the registry
and two conditions to contrast, and every prediction carries a direction
and a minimum effect so it can be scored without anybody's judgement
after the fact. That is pre-registration in the open-science sense, and
it is what makes an automated study honest: the prediction is fixed
before the run, and the verdict is computed rather than argued.

    plan + measure registry
      → compile prompt → LLM answers as JSON
      → :func:`protocol_from_answer` (normalise; drop what cannot run and
        say so in ``dropped``)
      → :func:`preflight` (the gate before approval)

As everywhere in this package the model emits JSON and the code decides
what survives. What does not survive is *recorded*, not silently fixed: a
hypothesis whose measure is not in the registry lands in ``dropped`` with
the reason, because the alternative — keeping it and reporting it as
"unmeasured" after an expensive run — is exactly the failure this module
exists to prevent.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from gaworld.parallel.spec import normalize_event, sanitize_world_config
from gaworld.research.measures import Measure, registry, render_registry, resolve
from gaworld.research.workbench import ResearchError

#: Study designs the compiler may emit. Surveys, prompt grids and composite
#: designs are later phases; naming them here would let a plan compile into
#: something nothing can run.
KINDS = ("parallel_worlds",)
DIRECTIONS = ("increase", "decrease")
ROLES = ("baseline", "treatment", "placebo")

#: The parallel worlds engine's own ceiling, placebo included.
MAX_CONDITIONS = 8
MAX_SEEDS = 5
MAX_HYPOTHESES = 20
DEFAULT_SEEDS: tuple[int, ...] = (42, 43)
DEFAULT_SIM_DAYS = 7
MAX_SIM_DAYS = 3650

#: A whole protocol — up to eight worlds and twenty scored predictions — is
#: a long answer; the provider default suits a single agent turn.
PROTOCOL_MAX_TOKENS = 6_000

#: Rough model calls per agent-day. The full tick-loop figure is the one
#: ``gaworld.group.driver.cost_summary`` assumes (48 ticks × ~4 calls); the
#: fast-forward figure is by construction one brief per agent per step.
CALLS_PER_AGENT_DAY = {"full": 198, "fast": 1}
DEFAULT_CALL_BUDGET = 50_000

_PLACEBO = {
    "zh-CN": ("安慰剂", "市政通告", "市政部门发布一则例行通告，不涉及任何居民的实际生活。"),
    "en": ("Placebo", "Municipal notice", "The city posts a routine notice that touches nobody's daily life."),
}
_ID_RE = re.compile(r"[^0-9a-z_-]+")
_DIRECTION_WORDS = {
    "increase": ("increase", "increas", "up", "higher", "rise", "positive", "+", "上升", "增加", "升高", "提高", "更高", "变高", "正"),
    "decrease": ("decrease", "decreas", "down", "lower", "fall", "drop", "negative", "-", "下降", "减少", "降低", "更低", "变低", "负"),
}
_LANGUAGE_LABELS = {"zh-CN": "简体中文", "en": "English"}


@dataclass
class Protocol:
    """A pre-registered study: what runs, what is measured, what is predicted."""

    title: str
    kind: str = "parallel_worlds"
    language: str = "zh-CN"
    plan_id: str = ""
    sample: dict[str, Any] = field(default_factory=dict)
    sim_days: int = DEFAULT_SIM_DAYS
    fast: bool = False
    max_parallel: int = 2
    #: Model the *simulation* runs on; blank = routed by config. Distinct from
    #: the model that compiled the protocol.
    sim_provider: str = ""
    conditions: list[dict[str, Any]] = field(default_factory=list)
    measures: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    validity: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    @property
    def baseline_id(self) -> str:
        for cond in self.conditions:
            if cond.get("role") == "baseline":
                return str(cond["id"])
        return str(self.conditions[0]["id"]) if self.conditions else ""

    @property
    def seeds(self) -> list[int]:
        return [int(seed) for seed in self.validity.get("seeds") or []]

    def condition(self, cid: str) -> dict[str, Any] | None:
        for cond in self.conditions:
            if cond.get("id") == cid:
                return cond
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Protocol:
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in (data or {}).items() if key in known})


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT = """你是 GAWorld 平台的实验方法学家。下面是一份研究方案，请把它编译成一份可以直接执行、跑完也能自动判定的**预注册协议**。协议只能用 GAWorld 的「平行世界」引擎执行：同一批居民、同一个随机种子、同样的天数，分成若干个世界，各世界只差自己的事件表（或 config 补丁）。

## 研究方案
{plan}

## 可测量指标目录（假设里的 measure 只能从这里选，写 id）
{registry}

## 规则
1. conditions 至少 2 个、最多 {max_conditions} 个（含安慰剂）。恰好一个 role 为 baseline 的基准世界，通常没有事件；处理条件 role 为 treatment；需要剂量反应就给多个 treatment。
2. 事件：day 是从 1 开始的整数，time 形如 09:00，name 简短，description 是居民当天会「看到」的那段话，写得具体。sim_days 必须大于最晚的事件日，并给效应留出显形的时间。
3. 每条假设：measure 是目录里的 id；treatment 与 control 是 conditions 里的 id；direction 只能是 increase / decrease（treatment 相对 control）；min_effect 是能算作「有效应」的最小绝对差——指标多为 0–1 归一化，量级通常在 0.01–0.10；aggregation 是 final（终值）或 mean（全程均值）。
4. 方案里测不到的东西不要硬凑成假设，写进 notes。
5. 输出语言：{language_label}。

## 输出
只输出一个 JSON 对象，不要解释：
{{
  "title": "研究标题（30 字以内）",
  "sample": {{"city": "用哪座城市或默认世界", "agent_ids": [], "note": "人口与 agent 设定的说明；agent_ids 留空 = 配置里的全部居民"}},
  "sim_days": 14,
  "fast": false,
  "conditions": [
    {{"id": "baseline", "label": "基准", "role": "baseline", "events": [], "config": {{}}}},
    {{"id": "t1", "label": "处理条件名", "role": "treatment", "events": [{{"day": 2, "time": "09:00", "name": "事件名", "description": "居民看到的描述"}}], "config": {{}}}}
  ],
  "measures": ["stress", "emotion"],
  "hypotheses": [
    {{"id": "H1", "statement": "一句话假设", "measure": "stress", "treatment": "t1", "control": "baseline", "direction": "decrease", "min_effect": 0.02, "aggregation": "final"}}
  ],
  "validity": {{"seeds": [42, 43], "placebo": true}},
  "notes": "测不到的东西、简化之处"
}}"""


def _plan_text(plan: dict[str, Any]) -> str:
    """The plan, compacted to what the compiler needs to see."""
    design = plan.get("design") or {}
    parts: list[str] = [f"标题：{plan.get('title') or ''}"]
    if plan.get("summary"):
        parts.append(f"概要：{plan['summary']}")
    for label, key in (("研究问题", "research_questions"), ("假设", "hypotheses"), ("可信度检验", "validation")):
        items = plan.get(key) or []
        if items:
            parts.append(f"{label}：\n" + "\n".join(f"- {item}" for item in items))
    for label, key in (
        ("实验设计", "name"), ("设计思路", "approach"),
        ("城市", "city"), ("人口", "population"), ("Agent 设定", "agents"), ("时间跨度", "timeline"),
    ):
        if design.get(key):
            parts.append(f"{label}：{design[key]}")
    if design.get("conditions"):
        parts.append("实验条件：\n" + "\n".join(
            f"- {item.get('name', '')}：{item.get('manipulation', '')}" for item in design["conditions"]
        ))
    if design.get("events"):
        parts.append("事件：\n" + "\n".join(f"- {item}" for item in design["events"]))
    if design.get("measures"):
        parts.append("测量指标：\n" + "\n".join(
            f"- {item.get('name', '')}：{item.get('operationalization', '')}（{item.get('source', '')}）"
            for item in design["measures"]
        ))
    if plan.get("gaps"):
        parts.append("局限：\n" + "\n".join(
            f"- {item.get('limitation', '')}（替代：{item.get('workaround', '')}）" for item in plan["gaps"]
        ))
    cost = plan.get("estimated_cost") or {}
    if cost.get("llm_calls"):
        parts.append(f"成本估算：{cost['llm_calls']}")
    return "\n\n".join(parts)


def build_compile_prompt(plan: dict[str, Any], *, registry_table: str | None = None, language: str = "zh-CN") -> str:
    return _PROMPT.format(
        plan=_plan_text(plan),
        registry=registry_table if registry_table is not None else render_registry(),
        max_conditions=MAX_CONDITIONS,
        language_label=_LANGUAGE_LABELS.get(language, "简体中文"),
    )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:limit]
    return str(value).strip()[:limit]


def _int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _bool(value: Any, default: bool = False) -> bool:
    """JSON booleans, plus the strings a model sometimes writes instead."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in ("true", "yes", "1", "on", "是"):
        return True
    if text in ("false", "no", "0", "off", "否"):
        return False
    return default


def _seeds(value: Any) -> list[int]:
    if isinstance(value, str):
        value = [part for part in re.split(r"[,\s，]+", value) if part]
    elif isinstance(value, (int, float)):
        value = [value]
    out: list[int] = []
    for item in value if isinstance(value, list) else []:
        try:
            seed = int(item)
        except (TypeError, ValueError):
            continue
        if seed not in out:
            out.append(seed)
    return out[:MAX_SEEDS]


def _agent_ids(value: Any) -> list[int]:
    if isinstance(value, str):
        value = [part for part in re.split(r"[,\s，]+", value) if part]
    out: list[int] = []
    for item in value if isinstance(value, list) else []:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in out:
            out.append(number)
    return out


def _direction(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    for direction, words in _DIRECTION_WORDS.items():
        if text == direction or any(word in text for word in words):
            return direction
    return None


def _aggregation(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "mean" if text.startswith("mean") or "均值" in text or "平均" in text else "final"


def _conditions(raw: Any, dropped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    if len(items) > MAX_CONDITIONS:
        dropped.append({
            "what": "condition",
            "where": "; ".join(_text((item or {}).get("label") if isinstance(item, dict) else item, 40)
                               for item in items[MAX_CONDITIONS:]),
            "reason": f"平行世界一次最多 {MAX_CONDITIONS} 个世界，多出的条件被丢弃",
        })
        items = items[:MAX_CONDITIONS]

    out: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            item = {"label": item}
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label") or item.get("name"), 80) or f"条件 {index + 1}"
        events: list[dict[str, Any]] = []
        for raw_event in item.get("events") or []:
            try:
                events.append(normalize_event(raw_event, where=label))
            except ValueError as exc:
                dropped.append({"what": "event", "where": label, "reason": str(exc)})
        events.sort(key=lambda event: (event["day"], event["time"]))
        try:
            config = sanitize_world_config(item.get("config"), where=label)
        except ValueError as exc:
            dropped.append({"what": "config", "where": label, "reason": str(exc)})
            config = {}
        role = str(item.get("role") or "").strip().lower()
        if role not in ROLES:
            is_placebo = "安慰剂" in label or "placebo" in label.lower()
            role = "placebo" if is_placebo else ("baseline" if not events and not config else "treatment")
        out.append({
            "_raw_id": _text(item.get("id"), 32),
            "label": label,
            "role": role,
            "events": events,
            "config": config,
            "note": _text(item.get("note"), 300),
        })

    # Exactly one baseline: the first one wins, extras become treatments, and
    # a design with none promotes its first condition — "baseline" is what
    # every hypothesis defaults its control to, so there has to be one.
    seen_baseline = False
    for cond in out:
        if cond["role"] == "baseline":
            if seen_baseline:
                cond["role"] = "treatment"
            seen_baseline = True
    if out and not seen_baseline:
        out[0]["role"] = "baseline"

    used: set[str] = set()
    treatments = 0
    for cond in out:
        raw_id = _ID_RE.sub("-", cond.pop("_raw_id").lower()).strip("-")
        if cond["role"] == "treatment":
            treatments += 1
        base = raw_id or {"baseline": "baseline", "placebo": "placebo"}.get(cond["role"], f"t{treatments}")
        cid, suffix = base, 2
        while cid in used:
            cid = f"{base}-{suffix}"
            suffix += 1
        used.add(cid)
        cond["id"] = cid
        cond["aliases"] = sorted({alias for alias in (raw_id, cond["label"]) if alias})
    return out


def _add_placebo(conditions: list[dict[str, Any]], dropped: list[dict[str, Any]], language: str) -> None:
    if any(cond["role"] == "placebo" for cond in conditions):
        return
    if len(conditions) >= MAX_CONDITIONS:
        dropped.append({"what": "placebo", "where": "validity", "reason": f"已有 {MAX_CONDITIONS} 个世界，放不下安慰剂世界"})
        return
    label, name, description = _PLACEBO.get(language, _PLACEBO["zh-CN"])
    days = [event["day"] for cond in conditions if cond["role"] == "treatment" for event in cond["events"]]
    conditions.append({
        "id": "placebo" if "placebo" not in {cond["id"] for cond in conditions} else "placebo-auto",
        "label": label,
        "role": "placebo",
        "events": [{"day": min(days) if days else 2, "time": "10:00", "name": name, "description": description}],
        "config": {},
        "note": "auto",
        "aliases": [label],
    })


def _hypotheses(
    raw: Any,
    conditions: list[dict[str, Any]],
    reg: dict[str, Measure],
    dropped: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lookup: dict[str, str] = {}
    for cond in conditions:
        lookup[cond["id"]] = cond["id"]
        for alias in cond.get("aliases") or []:
            lookup.setdefault(alias, cond["id"])
            lookup.setdefault(alias.lower(), cond["id"])
    baseline = next((cond["id"] for cond in conditions if cond["role"] == "baseline"), "")

    def condition_id(value: Any) -> str:
        text = str(value or "").strip()
        return lookup.get(text) or lookup.get(text.lower()) or ""

    out: list[dict[str, Any]] = []
    used: set[str] = set()
    items = raw if isinstance(raw, list) else []
    for index, item in enumerate(items[:MAX_HYPOTHESES]):
        if not isinstance(item, dict):
            continue
        hid = _ID_RE.sub("", _text(item.get("id"), 16).lower()).upper() or f"H{index + 1}"
        while hid in used:
            hid = f"{hid}X"
        statement = _text(item.get("statement") or item.get("text") or item.get("hypothesis"), 600)
        where = f"{hid}：{statement[:40]}" if statement else hid

        measure = resolve(item.get("measure"), reg)
        if measure is None:
            dropped.append({"what": "hypothesis", "where": where, "reason": f"指标不在可测量目录里：{_text(item.get('measure'), 40)!r}"})
            continue
        treatment = condition_id(item.get("treatment"))
        if not treatment:
            dropped.append({"what": "hypothesis", "where": where, "reason": f"处理条件不存在：{_text(item.get('treatment'), 40)!r}"})
            continue
        control = condition_id(item.get("control")) or baseline
        if not control or control == treatment:
            dropped.append({"what": "hypothesis", "where": where, "reason": "对照条件缺失或与处理条件相同"})
            continue
        direction = _direction(item.get("direction"))
        if direction is None:
            dropped.append({"what": "hypothesis", "where": where, "reason": f"方向不是 increase / decrease：{_text(item.get('direction'), 20)!r}"})
            continue
        try:
            min_effect = max(0.0, float(item.get("min_effect") or 0.0))
        except (TypeError, ValueError):
            min_effect = 0.0
        used.add(hid)
        out.append({
            "id": hid,
            "statement": statement,
            "measure": measure.id,
            "treatment": treatment,
            "control": control,
            "direction": direction,
            "min_effect": round(min_effect, 6),
            "aggregation": _aggregation(item.get("aggregation")),
        })
    return out


def _measures(raw: Any, hypotheses: list[dict[str, Any]], reg: dict[str, Measure]) -> list[dict[str, Any]]:
    ids: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        measure = resolve(item.get("id") if isinstance(item, dict) else item, reg)
        if measure and measure.id not in ids:
            ids.append(measure.id)
    for hypothesis in hypotheses:
        if hypothesis["measure"] not in ids:
            ids.append(hypothesis["measure"])
    return [{"id": mid, "label": reg[mid].label, "source": reg[mid].source, "note": reg[mid].note} for mid in ids]


def protocol_from_answer(
    answer: dict[str, Any],
    plan: dict[str, Any],
    *,
    reg: dict[str, Measure] | None = None,
) -> Protocol:
    """Validate a parsed compile answer into a protocol.

    Raises :class:`ResearchError` only when there is nothing to run at all
    (no conditions). A protocol with no surviving hypotheses is returned —
    the preflight reports it, together with *why* each one was dropped, so
    the user sees what to change instead of a blank refusal.
    """
    reg = registry() if reg is None else reg
    language = str(plan.get("language") or "zh-CN")
    dropped: list[dict[str, Any]] = []

    kind = str(answer.get("kind") or "parallel_worlds").strip().lower()
    conditions = _conditions(answer.get("conditions"), dropped)
    if not conditions:
        raise ResearchError("模型没有返回任何实验条件，无法生成协议")

    validity_any = answer.get("validity")
    validity_raw: dict[str, Any] = validity_any if isinstance(validity_any, dict) else {}
    placebo = _bool(validity_raw.get("placebo"), default=True)
    if placebo:
        _add_placebo(conditions, dropped, language)
    seeds = _seeds(validity_raw.get("seeds")) or list(DEFAULT_SEEDS)

    hypotheses = _hypotheses(answer.get("hypotheses"), conditions, reg, dropped)
    sample_any = answer.get("sample")
    sample_raw: dict[str, Any] = sample_any if isinstance(sample_any, dict) else {}
    return Protocol(
        title=_text(answer.get("title"), 160) or str(plan.get("title") or "") or "研究",
        kind=kind,
        language=language,
        plan_id=str(plan.get("id") or ""),
        sample={
            "city": _text(sample_raw.get("city"), 200),
            "agent_ids": _agent_ids(sample_raw.get("agent_ids")),
            "note": _text(sample_raw.get("note"), 800),
        },
        sim_days=_int(answer.get("sim_days"), DEFAULT_SIM_DAYS, low=1, high=MAX_SIM_DAYS),
        fast=_bool(answer.get("fast")),
        conditions=conditions,
        measures=_measures(answer.get("measures"), hypotheses, reg),
        hypotheses=hypotheses,
        validity={"seeds": seeds, "placebo": placebo},
        dropped=dropped,
        notes=_text(answer.get("notes"), 2000),
    )


def apply_overrides(protocol: Protocol, payload: dict[str, Any]) -> Protocol:
    """Operator adjustments that do not need a recompile: cost and scope knobs.

    The scientific content — conditions, measures, predictions — is what was
    pre-registered and stays as compiled; what the panel may turn are the
    knobs that decide how much the study costs and which residents take part.
    """
    payload = payload if isinstance(payload, dict) else {}
    if "seeds" in payload:
        seeds = _seeds(payload.get("seeds"))
        if seeds:
            protocol.validity["seeds"] = seeds
    if payload.get("sim_days") not in (None, ""):
        protocol.sim_days = _int(payload.get("sim_days"), protocol.sim_days, low=1, high=MAX_SIM_DAYS)
    if "fast" in payload:
        protocol.fast = _bool(payload.get("fast"))
    if "agent_ids" in payload:
        protocol.sample["agent_ids"] = _agent_ids(payload.get("agent_ids"))
    if payload.get("max_parallel") not in (None, ""):
        protocol.max_parallel = _int(payload.get("max_parallel"), protocol.max_parallel, low=1, high=4)
    if "sim_provider" in payload:
        protocol.sim_provider = _text(payload.get("sim_provider"), 64)
    return protocol


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def estimate_calls(protocol: Protocol, agents: int) -> int:
    per_day = CALLS_PER_AGENT_DAY["fast" if protocol.fast else "full"]
    return int(max(1, agents) * protocol.sim_days * per_day * len(protocol.conditions) * max(1, len(protocol.seeds)))


def preflight(
    protocol: Protocol,
    *,
    default_agents: int = 5,
    call_budget: int = DEFAULT_CALL_BUDGET,
) -> dict[str, Any]:
    """The gate before approval. Errors block; warnings are for the reader.

    Also writes the budget into ``protocol.budget`` so the saved protocol
    carries the estimate the gate was judged on.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if protocol.kind not in KINDS:
        errors.append(f"阶段一只支持 {' / '.join(KINDS)}，协议的 kind 是 {protocol.kind!r}")
    if not any(cond["role"] == "treatment" for cond in protocol.conditions):
        errors.append("没有处理条件：至少要有一个 role 为 treatment 的世界")
    if not protocol.hypotheses:
        dropped = sum(1 for item in protocol.dropped if item.get("what") == "hypothesis")
        errors.append("没有一条可评估的假设" + (f"（{dropped} 条被丢弃，原因见下）" if dropped else ""))

    last_event = max((event["day"] for cond in protocol.conditions for event in cond["events"]), default=0)
    if last_event and protocol.sim_days <= last_event:
        errors.append(f"仿真天数 {protocol.sim_days} 不晚于最后一个事件日 {last_event}，事件没有时间显形")

    has_placebo = any(cond["role"] == "placebo" for cond in protocol.conditions)
    if len(protocol.seeds) < 2:
        warnings.append("只有一个种子：没有跨种子一致性，判定最高只能到 inconclusive（有安慰剂世界时除外）")
    if not has_placebo:
        warnings.append("没有安慰剂世界：没有噪声底线，效应只能对最小效应 min_effect 判定")
    for item in protocol.dropped:
        warnings.append(f"已丢弃{item.get('what', '')}「{item.get('where', '')}」：{item.get('reason', '')}")

    agents = len(protocol.sample.get("agent_ids") or []) or max(1, int(default_agents))
    calls = estimate_calls(protocol, agents)
    protocol.budget = {
        "agents": agents,
        "worlds": len(protocol.conditions),
        "seeds": len(protocol.seeds),
        "sim_days": protocol.sim_days,
        "calls_per_agent_day": CALLS_PER_AGENT_DAY["fast" if protocol.fast else "full"],
        "estimated_calls": calls,
        "limit": int(call_budget),
    }
    if calls > call_budget:
        errors.append(
            f"估算模型调用量 {calls:,} 超过上限 {call_budget:,}：减少居民、天数、种子或条件，或打开快速模式"
        )
    return {"ok": not errors, "errors": errors, "warnings": warnings, "budget": dict(protocol.budget)}


__all__ = [
    "CALLS_PER_AGENT_DAY",
    "DEFAULT_CALL_BUDGET",
    "DEFAULT_SEEDS",
    "DIRECTIONS",
    "KINDS",
    "MAX_CONDITIONS",
    "PROTOCOL_MAX_TOKENS",
    "ROLES",
    "Protocol",
    "apply_overrides",
    "build_compile_prompt",
    "estimate_calls",
    "preflight",
    "protocol_from_answer",
]
