"""Policy simulation & optimisation (政策仿真与优化): a policy in, a better one out.

The researcher picks a city and writes a policy — "every household pays a
garbage-sorting fee by weight, 0.5 元/kg, 300 元 fine for mixed waste" —
optionally with a candidate alternative. A run then goes:

    policy (A) [+ candidate (B)]
      → a seeded sample of the city's residents (the same people for every
        version, so versions are compared on paired answers, not on luck)
      → every resident reacts to every version in their own persona, as a
        fixed JSON shape: support, wellbeing, finances, compliance, what they
        would actually do, their main worry, the one change they would ask for
      → code aggregates: support / opposition rates, means, who is hurt,
        the gap between the best- and worst-off group, one composite score
      → one optimiser call reads the numbers, the group breakdown and the
        residents' worries and suggestions, and proposes modifications plus a
        complete revised policy (R)
      → R is simulated on the same residents, and the version with the
        highest composite score is the recommendation

As in the duel game, **code picks the winner, not the model**: the optimiser
only argues for its revision, the second simulation decides whether the
revision actually helped. A revision that scores worse than the original is
reported as such.

Everything lives under ``output/research/policy/<id>.json``; nothing is
written back into a city bundle. This module owns no threads and no HTTP; the
dashboard delegate (:mod:`gaworld.apps.policy_sim_api`) runs it as a job.
"""

from __future__ import annotations

import json
import random
import re
import statistics
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.research.policy_sim")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_DIRNAME = "output/research/policy"

MAX_POLICY_CHARS = 4_000
DEFAULT_SAMPLE = 12
MIN_SAMPLE, MAX_SAMPLE = 3, 30
#: Residents younger than this are not asked: a policy reaction needs
#: somebody who pays, works or votes.
MIN_AGE = 16
#: Worries and suggestions quoted to the optimiser, per version.
MAX_QUOTES = 24

#: Version keys: the original, the researcher's candidate, the optimiser's revision.
KEYS = ("A", "B", "R")
LABELS = {"A": "原政策", "B": "候选政策", "R": "推荐修订版"}

#: Composite score weights; every component is first mapped onto 0..1.
SCORE_WEIGHTS = {"support": 0.35, "wellbeing": 0.30, "finance": 0.15, "compliance": 0.20}
#: Groups the breakdown is cut by: (axis id, label).
GROUP_AXES = (("age_band", "年龄段"), ("gender", "性别"), ("hukou", "户籍"))

LLMFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int = 600) -> str:
    return str(value or "").strip()[:limit]


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, int(number)))


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def parse_json(raw: Any) -> dict[str, Any]:
    from gaworld.apps.games_api import first_json_object

    return first_json_object(raw)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def sample_residents(people: list[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    """A seeded sample of adult-ish residents; the whole roster if it is small."""
    adults = [p for p in people if int(p.get("age") or 0) >= MIN_AGE] or list(people)
    if not adults:
        raise ValueError("这座城市里没有可用的居民")
    size = max(1, min(size, len(adults)))
    picked = random.Random(seed).sample(adults, size)
    return sorted(picked, key=lambda p: int(p["id"]))


def group_of(person: dict[str, Any], axis: str) -> str:
    from gaworld.group.cohort import COHORT_AXES

    return str(COHORT_AXES[axis](person))


# ---------------------------------------------------------------------------
# Resident reaction
# ---------------------------------------------------------------------------

#: Same lesson as the referendum: asked neutrally, everybody answers with the
#: balanced, agreeable middle. A policy hits people differently, and that
#: difference is the whole point of simulating it on residents.
_STAKES_RULE = (
    "先想清楚这项政策落到你头上具体意味着什么——你住哪、干什么、家里有谁、手里有多少钱。"
    "不要给面面俱到的中间答案，真实的人对一项政策是有倾向的；只有确实事不关己时才打 0。"
)

_REACTION_SCHEMA = (
    '{"support": -2 到 2 的整数（-2 强烈反对，0 无所谓，2 强烈支持）, '
    '"wellbeing": -5 到 5 的整数（实施半年后你的日子过得更差还是更好）, '
    '"finance": -5 到 5 的整数（对你家钱包的影响）, '
    '"compliance": 0-100 的整数（你会多大程度照着做）, '
    '"behavior": "你实际会怎么应对，一句话", '
    '"concern": "你最担心的一点，一句话，第一人称", '
    '"suggestion": "如果只能改一处，你希望怎么改，一句话"}'
)


def reaction_prompt(persona_text: str, policy_text: str, city_name: str) -> str:
    where = f"你所在的{city_name}" if city_name else "你所在的城市"
    return (
        f"{persona_text}\n\n"
        f"{where}准备出台下面这项政策：\n【政策】{policy_text}\n\n"
        f"{_STAKES_RULE}\n"
        f"只输出一个 JSON 对象，不要任何解释：\n{_REACTION_SCHEMA}"
    )


def parse_reaction(raw: Any) -> dict[str, Any]:
    """The resident's answer on the fixed scales; an unreadable reply is marked, not invented."""
    data = parse_json(raw)
    if not data:
        return {
            "ok": False,
            "support": 0,
            "wellbeing": 0,
            "finance": 0,
            "compliance": 50,
            "behavior": "",
            "concern": "",
            "suggestion": "",
        }
    return {
        "ok": True,
        "support": _clamp_int(data.get("support"), -2, 2, 0),
        "wellbeing": _clamp_int(data.get("wellbeing"), -5, 5, 0),
        "finance": _clamp_int(data.get("finance"), -5, 5, 0),
        "compliance": _clamp_int(data.get("compliance"), 0, 100, 50),
        "behavior": _text(data.get("behavior"), 200),
        "concern": _text(data.get("concern"), 200),
        "suggestion": _text(data.get("suggestion"), 200),
    }


# ---------------------------------------------------------------------------
# Aggregation — all by code
# ---------------------------------------------------------------------------


def composite_score(support: float, wellbeing: float, finance: float, compliance: float) -> float:
    """0..100 from the four means; weights in :data:`SCORE_WEIGHTS`."""
    parts = {
        "support": (support + 2) / 4,
        "wellbeing": (wellbeing + 5) / 10,
        "finance": (finance + 5) / 10,
        "compliance": compliance / 100,
    }
    return round(100 * sum(SCORE_WEIGHTS[k] * v for k, v in parts.items()), 1)


def metrics(reactions: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in reactions if r.get("ok")]
    n = len(valid)
    if not n:
        return {"n": 0, "failed": len(reactions), "score": 0.0}
    support = _mean([r["support"] for r in valid])
    wellbeing = _mean([r["wellbeing"] for r in valid])
    finance = _mean([r["finance"] for r in valid])
    compliance = _mean([r["compliance"] for r in valid])
    return {
        "n": n,
        "failed": len(reactions) - n,
        "support_rate": round(sum(1 for r in valid if r["support"] > 0) / n, 3),
        "oppose_rate": round(sum(1 for r in valid if r["support"] < 0) / n, 3),
        "hurt_rate": round(sum(1 for r in valid if r["wellbeing"] < 0) / n, 3),
        "mean_support": support,
        "mean_wellbeing": wellbeing,
        "mean_finance": finance,
        "mean_compliance": compliance,
        "score": composite_score(support, wellbeing, finance, compliance),
    }


def breakdown(reactions: list[dict[str, Any]], people: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Per axis, per group: size, mean support, mean wellbeing; plus the
    widest wellbeing gap between two groups of at least two people."""
    out: dict[str, Any] = {}
    widest: dict[str, Any] = {"gap": 0.0, "axis": "", "low": "", "high": ""}
    for axis, _label in GROUP_AXES:
        groups: dict[str, list[dict[str, Any]]] = {}
        for reaction in reactions:
            if not reaction.get("ok"):
                continue
            person = people.get(int(reaction["agent_id"]))
            if person is None:
                continue
            groups.setdefault(group_of(person, axis), []).append(reaction)
        rows = {
            name: {
                "n": len(members),
                "mean_support": _mean([r["support"] for r in members]),
                "mean_wellbeing": _mean([r["wellbeing"] for r in members]),
            }
            for name, members in sorted(groups.items())
        }
        out[axis] = rows
        sized = {k: v for k, v in rows.items() if v["n"] >= 2}
        if len(sized) >= 2:
            low = min(sized, key=lambda k: sized[k]["mean_wellbeing"])
            high = max(sized, key=lambda k: sized[k]["mean_wellbeing"])
            gap = round(sized[high]["mean_wellbeing"] - sized[low]["mean_wellbeing"], 2)
            if gap > widest["gap"]:
                widest = {"gap": gap, "axis": axis, "low": low, "high": high}
    out["widest_gap"] = widest
    return out


def best_version(metric_by_key: dict[str, dict[str, Any]]) -> str:
    """Highest composite score; ties go to the earlier version (A before B before R)."""
    scored = [(k, m.get("score", 0.0)) for k, m in metric_by_key.items() if m.get("n")]
    if not scored:
        return ""
    top = max(score for _, score in scored)
    return next(k for k, score in scored if score == top)


# ---------------------------------------------------------------------------
# Optimiser
# ---------------------------------------------------------------------------

_OPTIMISE_SCHEMA = """{
  "assessment": "对原政策效果的整体评价，2-4 句",
  "effects": ["仿真里看到的主要效果，每条一句"],
  "risks": ["风险、副作用或被忽视的人群，每条一句"],
  "comparison": "原政策与候选政策的对比（没有候选政策就留空）",
  "modifications": [{"change": "具体改什么", "reason": "为什么改，引用仿真结果", "addresses": "回应哪类居民的什么问题"}],
  "revised_policy": "修订后的完整政策文本，可以直接拿去再仿真一次",
  "expected": "预期修订后会改善什么、可能牺牲什么"
}"""


def _metric_line(key: str, m: dict[str, Any]) -> str:
    if not m.get("n"):
        return f"- {LABELS[key]}：没有有效回答"
    return (
        f"- {LABELS[key]}（{m['n']} 人）：支持 {m['support_rate']:.0%}、反对 {m['oppose_rate']:.0%}、"
        f"日子变差 {m['hurt_rate']:.0%}；平均支持度 {m['mean_support']}（-2~2）、"
        f"生活 {m['mean_wellbeing']}（-5~5）、钱包 {m['mean_finance']}（-5~5）、"
        f"遵从 {m['mean_compliance']}（0~100）；综合分 {m['score']}"
    )


def _breakdown_lines(groups: dict[str, Any]) -> str:
    lines = []
    for axis, label in GROUP_AXES:
        rows = groups.get(axis) or {}
        cells = "；".join(
            f"{name} {row['n']} 人 支持 {row['mean_support']} 生活 {row['mean_wellbeing']}"
            for name, row in rows.items()
        )
        if cells:
            lines.append(f"- {label}：{cells}")
    return "\n".join(lines)


def _quotes(run: dict[str, Any], key: str) -> str:
    names = {int(r["agent_id"]): r for r in run["residents"]}
    worried = sorted(
        (r for r in run["reactions"].get(key, []) if r.get("ok")),
        key=lambda r: r["support"] + r["wellbeing"] / 2.5,
    )[:MAX_QUOTES]
    lines = []
    for r in worried:
        person = names.get(int(r["agent_id"]), {})
        who = f"{person.get('name', '')}（{person.get('age', '')}岁，{person.get('job') or '职业不详'}）"
        lines.append(
            f"- {who} 支持 {r['support']} 生活 {r['wellbeing']}：担心「{r['concern']}」；"
            f"会「{r['behavior']}」；建议「{r['suggestion']}」"
        )
    return "\n".join(lines)


def optimise_prompt(run: dict[str, Any]) -> str:
    policies = {p["key"]: p["text"] for p in run["policies"]}
    parts = [
        "你是一位公共政策分析师。下面是一项政策在一座城市里对一组真实居民画像的仿真结果。"
        "居民各自按自己的处境给出了反应，数字由代码汇总。",
        f"城市：{run.get('city_name') or '默认世界'}；样本 {len(run['residents'])} 人。",
        f"【原政策 A】{policies['A']}",
    ]
    if "B" in policies:
        parts.append(f"【候选政策 B】{policies['B']}")
    parts.append("【汇总指标】\n" + "\n".join(_metric_line(k, run["metrics"][k]) for k in policies))
    for key in policies:
        parts.append(f"【{LABELS[key]} · 分组】\n{_breakdown_lines(run['groups'][key])}")
        quotes = _quotes(run, key)
        if quotes:
            parts.append(f"【{LABELS[key]} · 最不满意的居民怎么说】\n{quotes}")
    parts.append(
        "请据此评估政策效果，并提出修改。要求：\n"
        "1. 每条修改都要能追溯到上面的数字或居民的原话，不要泛泛而谈；\n"
        "2. 修订版保留原政策的目标，主要解决受损最重、反对最强的人群的问题，同时不要明显伤害现在支持的人；\n"
        "3. 有候选政策时，修订版可以吸收两者各自做得好的部分；\n"
        "4. revised_policy 写成完整、具体、可执行的政策文本（含对象、标准、金额或期限）。\n"
        f"只输出一个 JSON 对象：\n{_OPTIMISE_SCHEMA}"
    )
    return "\n\n".join(parts)


def _texts(value: Any, limit: int = 8, chars: int = 300) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [t for t in (_text(v, chars) for v in value) if t][:limit]


def parse_recommendation(raw: Any) -> dict[str, Any]:
    data = parse_json(raw)
    mods = []
    for item in data.get("modifications") or []:
        if isinstance(item, dict) and _text(item.get("change")):
            mods.append(
                {
                    "change": _text(item.get("change"), 400),
                    "reason": _text(item.get("reason"), 400),
                    "addresses": _text(item.get("addresses"), 200),
                }
            )
        elif isinstance(item, str) and item.strip():
            mods.append({"change": _text(item, 400), "reason": "", "addresses": ""})
    return {
        "assessment": _text(data.get("assessment"), 1200),
        "effects": _texts(data.get("effects")),
        "risks": _texts(data.get("risks")),
        "comparison": _text(data.get("comparison"), 1200),
        "modifications": mods[:10],
        "revised_policy": _text(data.get("revised_policy"), MAX_POLICY_CHARS),
        "expected": _text(data.get("expected"), 800),
    }


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return f"pol-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _simulate(
    run: dict[str, Any],
    key: str,
    personas: dict[int, str],
    react: LLMFn,
    progress: Callable[[float, str], None],
    span: tuple[float, float],
) -> None:
    text = next(p["text"] for p in run["policies"] if p["key"] == key)
    residents = run["residents"]
    reactions = []
    for index, person in enumerate(residents):
        start, end = span
        progress(start + (end - start) * index / len(residents), f"{LABELS[key]} · {person['name']}")
        prompt = reaction_prompt(personas[int(person["agent_id"])], text, run.get("city_name") or "")
        try:
            raw = react(prompt)
        except Exception as exc:  # pragma: no cover - provider failure
            _LOG.warning("policy reaction failed for #%s: %s", person["agent_id"], exc)
            raw = ""
        reaction = parse_reaction(raw)
        reaction["agent_id"] = int(person["agent_id"])
        reactions.append(reaction)
    run["reactions"][key] = reactions
    run["metrics"][key] = metrics(reactions)
    people = {int(p["agent_id"]): p for p in residents}
    run["groups"][key] = breakdown(reactions, people)


def run_policy_sim(
    *,
    policy: str,
    candidate: str = "",
    city: str = "",
    city_name: str = "",
    sample_size: int = DEFAULT_SAMPLE,
    seed: int | None = None,
    verify: bool = True,
    provider: str = "",
    react: LLMFn,
    optimise: LLMFn,
    population: list[dict[str, Any]] | None = None,
    persona_fn: Callable[[str, int], dict[str, Any]] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Simulate A (and B), ask for a revision, simulate R; return the run.

    *react* and *optimise* are the two model entry points; *population* and
    *persona_fn* are injected by tests so no city bundle is read.
    """
    from gaworld.apps.games_api import load_persona, persona_block

    progress = progress or (lambda p, m: None)
    policy = _text(policy, MAX_POLICY_CHARS)
    candidate = _text(candidate, MAX_POLICY_CHARS)
    if not policy:
        raise ValueError("先写一段政策描述")
    size = max(MIN_SAMPLE, min(MAX_SAMPLE, int(sample_size or DEFAULT_SAMPLE)))
    seed = int(seed) if seed is not None else random.randrange(1, 1_000_000)

    if population is None:
        from gaworld.interview.roster import load_population

        population = load_population(city)
    picked = sample_residents(population, size, seed)
    load = persona_fn or load_persona
    personas: dict[int, str] = {}
    residents = []
    for person in picked:
        card = load(city, int(person["id"]))
        personas[int(person["id"])] = persona_block(card)
        residents.append(
            {
                "agent_id": int(person["id"]),
                "name": str(card.get("name") or person.get("name") or f"#{person['id']}"),
                "age": person.get("age"),
                "gender": person.get("gender"),
                "hukou": person.get("hukou"),
                "job": str(card.get("job") or person.get("job") or ""),
            }
        )

    policies = [{"key": "A", "label": LABELS["A"], "text": policy}]
    if candidate:
        policies.append({"key": "B", "label": LABELS["B"], "text": candidate})
    run: dict[str, Any] = {
        "id": _new_id(),
        "title": _text(policy, 40),
        "city": str(city or ""),
        "city_name": city_name,
        "provider": provider,
        "seed": seed,
        "verify": bool(verify),
        "policies": policies,
        "residents": residents,
        "reactions": {},
        "metrics": {},
        "groups": {},
        "recommendation": None,
        "best": "",
        "created_at": time.time(),
    }

    # Budget the progress bar by model calls: one per resident per version, plus the optimiser.
    versions = len(policies) + (1 if verify else 0)
    calls = versions * len(residents) + 1
    per_version = len(residents) / calls
    cursor = 0.0
    for item in policies:
        _simulate(run, item["key"], personas, react, progress, (cursor, cursor + per_version))
        cursor += per_version

    progress(cursor, "正在分析结果、起草修改建议…")
    recommendation = parse_recommendation(optimise(optimise_prompt(run)))
    run["recommendation"] = recommendation
    cursor += 1 / calls

    if verify and recommendation["revised_policy"]:
        run["policies"].append({"key": "R", "label": LABELS["R"], "text": recommendation["revised_policy"]})
        _simulate(run, "R", personas, react, progress, (cursor, 0.99))

    run["best"] = best_version(run["metrics"])
    return run


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return "—"


def export_markdown(run: dict[str, Any]) -> str:
    lines = [
        f"# 政策仿真与优化 · {run.get('title') or run['id']}",
        "",
        f"- 城市：{run.get('city_name') or run.get('city') or '默认世界'}",
        f"- 样本：{len(run.get('residents') or [])} 位居民（种子 {run.get('seed')}，各版本使用同一批人）",
        f"- 推荐版本：{LABELS.get(run.get('best') or '', '—')}",
        "",
        "## 政策版本",
        "",
    ]
    for item in run.get("policies") or []:
        lines += [f"### {item['key']} · {item['label']}", "", item["text"], ""]

    lines += [
        "## 仿真结果",
        "",
        "| 版本 | 有效样本 | 支持 | 反对 | 日子变差 | 支持度 | 生活 | 钱包 | 遵从 | 综合分 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in run.get("policies") or []:
        m = (run.get("metrics") or {}).get(item["key"]) or {}
        if not m.get("n"):
            lines.append(f"| {item['label']} | 0 | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {item['label']} | {m['n']} | {_pct(m['support_rate'])} | {_pct(m['oppose_rate'])} | "
            f"{_pct(m['hurt_rate'])} | {m['mean_support']} | {m['mean_wellbeing']} | {m['mean_finance']} | "
            f"{m['mean_compliance']} | **{m['score']}** |"
        )
    weights = "、".join(f"{k} {v:.0%}" for k, v in SCORE_WEIGHTS.items())
    lines += ["", f"综合分 = 0~100，由支持度、生活、钱包、遵从各自归一化后加权（{weights}）。", ""]

    rec = run.get("recommendation") or {}
    if rec:
        lines += ["## 效果评估", "", rec.get("assessment") or "", ""]
        for title, key in (("主要效果", "effects"), ("风险与被忽视的人群", "risks")):
            if rec.get(key):
                lines += [f"### {title}", ""] + [f"- {x}" for x in rec[key]] + [""]
        if rec.get("comparison"):
            lines += ["### 原政策与候选政策对比", "", rec["comparison"], ""]
        if rec.get("modifications"):
            lines += ["## 推荐的修改", ""]
            for i, mod in enumerate(rec["modifications"], 1):
                lines.append(f"{i}. **{mod['change']}**")
                if mod.get("reason"):
                    lines.append(f"   - 理由：{mod['reason']}")
                if mod.get("addresses"):
                    lines.append(f"   - 回应：{mod['addresses']}")
            lines.append("")
        if rec.get("expected"):
            lines += ["### 预期", "", rec["expected"], ""]

    names = {int(r["agent_id"]): r for r in run.get("residents") or []}
    lines += ["## 居民反应", ""]
    for item in run.get("policies") or []:
        lines += [
            f"### {item['label']}",
            "",
            "| 居民 | 支持 | 生活 | 钱包 | 遵从 | 会怎么做 | 担心 | 建议 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in (run.get("reactions") or {}).get(item["key"]) or []:
            person = names.get(int(r["agent_id"]), {})
            if not r.get("ok"):
                lines.append(f"| {person.get('name', '')} | 无有效回答 | | | | | | |")
                continue
            lines.append(
                f"| {person.get('name', '')} | {r['support']} | {r['wellbeing']} | {r['finance']} | "
                f"{r['compliance']} | {r['behavior']} | {r['concern']} | {r['suggestion']} |"
            )
        lines.append("")
    lines.append("> 居民反应由大模型按每位居民的档案扮演生成，是对政策反应的情景推演，不是民意调查。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def policy_root() -> Path:
    return PROJECT_ROOT / POLICY_DIRNAME


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(value or "")):
        raise KeyError(value)
    return str(value)


def save_run(run: dict[str, Any]) -> None:
    path = policy_root() / f"{_safe_id(run['id'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_run(run_id: str) -> dict[str, Any] | None:
    try:
        path = policy_root() / f"{_safe_id(run_id)}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def delete_run(run_id: str) -> bool:
    try:
        path = policy_root() / f"{_safe_id(run_id)}.json"
    except KeyError:
        return False
    if not path.exists():
        return False
    path.unlink()
    return True


def list_runs() -> list[dict[str, Any]]:
    root = policy_root()
    rows = []
    for path in root.glob("*.json") if root.exists() else []:
        data = load_run(path.stem)
        if not data or not data.get("id"):
            continue
        best = data.get("best") or ""
        rows.append(
            {
                "id": data["id"],
                "title": data.get("title", ""),
                "city_name": data.get("city_name") or data.get("city") or "",
                "residents": len(data.get("residents") or []),
                "versions": [p["key"] for p in data.get("policies") or []],
                "best": best,
                "best_score": ((data.get("metrics") or {}).get(best) or {}).get("score"),
                "created_at": data.get("created_at") or 0,
                "owner_id": data.get("owner_id"),
            }
        )
    rows.sort(key=lambda r: -r["created_at"])
    return rows


__all__ = [
    "DEFAULT_SAMPLE",
    "KEYS",
    "LABELS",
    "MAX_SAMPLE",
    "MIN_SAMPLE",
    "SCORE_WEIGHTS",
    "best_version",
    "breakdown",
    "composite_score",
    "delete_run",
    "export_markdown",
    "list_runs",
    "load_run",
    "metrics",
    "optimise_prompt",
    "parse_reaction",
    "parse_recommendation",
    "policy_root",
    "reaction_prompt",
    "run_policy_sim",
    "sample_residents",
    "save_run",
]
