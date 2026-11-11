"""Survey / experiment fidelity (社会调查/实验拟合度): does a crowd of residents
answer the way the people in a paper did?

The researcher uploads a paper that reports a survey or an experiment on real
people, with its results. A run then goes:

    paper text
      → one extraction call reads it into an editable spec: who was asked,
        the conditions (one for a plain survey; treatment arms for an
        experiment), every stimulus as the participants saw it, the questions
        on their own scales, and the human results the paper reports — each
        number with where it came from
      → the researcher checks and corrects the spec (the numbers above all)
      → a seeded sample of a city's residents, of the size the researcher
        picks, takes the same study: randomly assigned to one condition each
        (``between``, as in the paper) or answering every condition in
        separate calls (``paired``); one call per resident per condition, a
        fixed JSON shape back
      → code compares: per question and condition the agents' mean /
        distribution against the human one (error on the item's own range,
        whether the human value sits inside the agents' 95% interval), per
        treatment the effect against the baseline (same direction? significant
        among the agents?), the correlation across cells and across effects,
        and one fidelity score

No model judges the fit. Everything lives under
``output/research/replication/<id>.json``; nothing is written back into a
city bundle. This module owns no HTTP; the dashboard delegate
(:mod:`gaworld.apps.replication_api`) runs it as a job.
"""

from __future__ import annotations

import contextvars
import json
import math
import random
import re
import statistics
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from gaworld.core.comparability import CURRENT_EPOCH
from gaworld.logging_setup import get_logger
from gaworld.population import education as education_filters
from gaworld.research import identity_checks, interaction_checks, interaction_probe, sampling_checks
from gaworld.research import replication_checks as checks
from gaworld.research import result_checks as rc

_LOG = get_logger("gaworld.research.replication")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPLICATION_DIRNAME = "output/research/replication"

MAX_PAPER_CHARS = 60_000
EXTRACT_MAX_TOKENS = 6_000
#: A cap, not a target: a thinking model spends most of it before the one-line JSON.
ANSWER_MAX_TOKENS = 2_000
MAX_CONDITIONS = 6
MAX_ITEMS = 12
MAX_GROUPS = 8
MAX_TEXT_CHARS = 3_000
DEFAULT_SAMPLE = 50
MIN_SAMPLE, MAX_SAMPLE = 5, 500
#: Without an age range from the paper, residents younger than this are not asked.
MIN_AGE = 16
WORKERS = 4
DESIGNS = ("between", "paired")
ITEM_KINDS = ("scale", "choice", "number")
#: |effect| on the item's 0–1 range below which a human contrast counts as "no difference".
NULL_EFFECT = 0.01
ALPHA = 0.05
#: A group cell with fewer agents than this is shown, but flagged as thin.
MIN_GROUP_N = 5
#: Group filters a paper's subgroups can be mapped onto: the only attributes every resident carries.
GROUP_FILTERS = ("gender", "age_min", "age_max", "hukou", "education", "student_status", "job")
HUKOU_VALUES = ("本地", "外地")
#: Fidelity score weights: central tendency, dispersion (shape) and effect direction.
#: A component that cannot be computed (the paper reported no SD, the study has no
#: treatment contrast) drops out and the rest are re-weighted to sum to 1 — so a
#: study whose dispersion cannot be judged keeps exactly the old score.
SCORE_WEIGHTS = {"level": 0.35, "spread": 0.30, "direction": 0.35}
#: Bumped whenever the score formula changes; a run records the version it was scored under.
#: 3: a collapsed 95% interval that missed the human mean is charged to level when
#:    the paper reported no SD (v2 left that collapse invisible in the score).
SCORE_VERSION = 3
#: Fewer agents than this in a cell: their SD is too noisy to compare with the humans'.
MIN_DISPERSION_N = 5
#: How much of the level term a collapsed interval costs when the paper reported no
#: SD and the spread term could not judge the collapse. A unanimous crowd is a real
#: defect of the simulation, but it is one the score has to charge somewhere.
COLLAPSE_PENALTY = 0.25
#: Words that, close to a number, mark it as a reported human result. A number next
#: to one of these in the text a resident reads is a leak: the resident is handed the
#: very answer the score will then measure.
LEAK_MARKERS = ("均值", "平均", "标准差", "得分", "分数", "显著", "比例", "占比")
#: The same markers in Latin script, matched as whole words so "sd" does not fire
#: inside "sponsored".
LEAK_MARKERS_LATIN = (r"\bmean\b", r"\bsd\b", r"\bm\s*=", r"\bp\s*[<=>]", r"\br\s*=")
#: How close a marker has to be to the number (in characters) to count as a leak.
LEAK_WINDOW = 16

VERDICTS = {
    "replicated": "方向一致且显著（不代表效应等价）",
    "same_direction": "方向一致，但不显著",
    "not_replicated": "未复现：方向不一致，也不显著",
    "reversed": "方向相反且显著",
    "no_human_effect": "文献中无差异",
}

LLMFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# What the seed controls
# ---------------------------------------------------------------------------
#
# A run's seed fixes **which** residents answer and **how their answers are
# grouped** — both reproducibly, from the seed alone. It never fixed the
# model's own sampling: each answer was an independent draw, and on a hosted
# endpoint that draw is not reproducible by construction. Re-running one study
# with one seed therefore gave three different scores, and nothing in the run
# said which part of the result the seed could speak for.
#
# So the seed's scope is now explicit: every cell derives its own seed from
# the run seed, the provider is asked for that draw again where it accepts a
# seed, and the run records what that covers. Where the provider takes no
# seed, the run says so rather than implying the answers repeat.

#: The largest seed a provider is guaranteed to take.
MAX_SEED = rc.MAX_SEED


def cell_seed(run_seed: int, agent_id: int, condition: str) -> int:
    """The seed for one cell: the run seed plus which cell this is.

    Derived from the cell's own identity, so the same cell gets the same seed
    on every run with the same run seed, and two different cells never share
    one.
    """
    return rc.derive_seed(int(run_seed), int(agent_id), condition)


def _backend_takes_seed(provenance: dict[str, Any]) -> bool:
    """Whether the provider behind this run accepts a seed.

    The Anthropic Messages API has no seed parameter, so a run on it cannot
    ask the model for the same draw twice; the OpenAI-compatible and Ollama
    backends both take one.
    """
    backend = str(provenance.get("backend_type") or "")
    return backend in {"OpenAIProvider", "OllamaProvider"}


def seed_scope(provider_supports_seed: bool) -> dict[str, Any]:
    """What this run's seed covered, and what it did not."""
    return {
        "controls": ["sampling", "assignment", "probe_order", "model_call_seeds"],
        "does_not_control": ["answers"],
        "provider_supports_seed": bool(provider_supports_seed),
        "model_sampling_reproducible": bool(provider_supports_seed),
        "note": (
            "种子固定抽哪些居民、怎么分组，并给每次模型调用派生一个格子种子；"
            "provider 接受 seed 时会据此请求同一次抽样，但托管端点不承诺逐字复现，"
            "同一种子重复运行的拟合度分仍可能有小幅差异。"
        ),
    }


def _call_with_seed(answer: Any, prompt: str, seed: int | None) -> str:
    """Call the model, passing the cell's seed when the callable takes one."""
    return rc.call_with_seed(answer, prompt, seed)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int = 600) -> str:
    return str(value or "").strip()[:limit]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip().rstrip("%").replace(",", "")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return round(number) if number is not None and number >= 0 else None


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def parse_json(raw: Any) -> dict[str, Any]:
    from gaworld.apps.games_api import first_json_object

    return first_json_object(raw)


def _p_two_sided(z: float) -> float:
    """Normal approximation: fine for the sample sizes a run uses, a bit generous below ~15."""
    return math.erfc(abs(z) / math.sqrt(2))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return round(statistics.correlation(xs, ys), 3)


# ---------------------------------------------------------------------------
# The spec: what was asked, of whom, and what the humans answered
# ---------------------------------------------------------------------------


def _normalize_item(raw: Any, index: int, used: set[str], warnings: list[str]) -> dict[str, Any] | None:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    text = _text(raw.get("text") or raw.get("question"), 600)
    if not text:
        warnings.append(f"第 {index + 1} 题没有题目内容，已丢弃")
        return None
    kind = _text(raw.get("kind") or raw.get("type"), 16).lower()
    kind = {
        "likert": "scale",
        "rating": "scale",
        "boolean": "choice",
        "yesno": "choice",
        "single": "choice",
        "numeric": "number",
        "amount": "number",
    }.get(kind, kind)
    options = [_text(o, 120) for o in raw.get("options") or [] if _text(o, 120)]
    if kind not in ITEM_KINDS:
        kind = "choice" if options else "scale"
    item: dict[str, Any] = {"id": "", "text": text, "kind": kind}
    if kind == "choice":
        if len(options) < 2:
            warnings.append(f"第 {index + 1} 题是单选题但不到两个选项，已丢弃")
            return None
        item["options"] = options[:12]
    else:
        low, high = _num(raw.get("min")), _num(raw.get("max"))
        if kind == "scale":
            low = 1 if low is None else round(low)
            high = 5 if high is None else round(high)
            if high <= low or high - low > 20:
                warnings.append(f"第 {index + 1} 题的量表范围 {low}–{high} 不可用，改成 1–5")
                low, high = 1, 5
            item["labels"] = [_text(label, 60) for label in raw.get("labels") or [] if _text(label, 60)][:21]
        elif low is not None and high is not None and high <= low:
            low = high = None
        item["min"], item["max"] = low, high
        if kind == "number":
            item["unit"] = _text(raw.get("unit"), 20)
    qid = re.sub(r"[^0-9A-Za-z_]+", "", _text(raw.get("id"), 12)).upper() or f"Q{index + 1}"
    while qid in used:
        qid += "X"
    used.add(qid)
    item["id"] = qid
    margin = _num(raw.get("equivalence_margin"))
    item["equivalence_margin"] = margin if margin is not None and margin > 0 else None
    interaction_margin = _num(raw.get("interaction_margin"))
    item["interaction_margin"] = (
        interaction_margin if interaction_margin is not None and interaction_margin > 0 else None
    )
    sampling_margin = _num(raw.get("sampling_margin"))
    item["sampling_margin"] = sampling_margin if sampling_margin is not None and sampling_margin > 0 else None
    identity_margin = _num(raw.get("identity_margin"))
    item["identity_margin"] = identity_margin if identity_margin is not None and identity_margin > 0 else None
    item["audit_wording"] = _text(raw.get("audit_wording"), 600)
    return item


def _normalize_distribution(raw: Any, keys: list[str]) -> dict[str, float] | None:
    """Shares over *keys*, summing to 1; percentages are accepted. ``None`` if unusable."""
    if isinstance(raw, list) and len(raw) == len(keys):
        raw = dict(zip(keys, raw, strict=True))
    if not isinstance(raw, dict):
        return None
    shares: dict[str, float] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if name not in keys:
            # Scale keys may come as "4.0"; choice keys as a 1-based index.
            number = _num(name)
            if number is not None and str(int(number)) in keys and float(number).is_integer():
                name = str(int(number))
            elif number is not None and float(number).is_integer() and 1 <= int(number) <= len(keys):
                name = keys[int(number) - 1]
            else:
                continue
        share = _num(value)
        if share is not None and share >= 0:
            shares[name] = shares.get(name, 0.0) + share
    if not shares or sum(shares.values()) <= 0:
        return None
    if max(shares.values()) > 1:  # percentages (or counts, which the division below absorbs)
        shares = {key: value / 100 for key, value in shares.items()}
    missing = [key for key in keys if key not in shares]
    if len(missing) == 1 and sum(shares.values()) < 1:
        shares[missing[0]] = 1 - sum(shares.values())  # "62% said yes" leaves 38% for no
    total = sum(shares.values())
    return {key: round(shares.get(key, 0.0) / total, 6) for key in keys}


def item_keys(item: dict[str, Any]) -> list[str]:
    """Distribution keys: the scale points, or the options of a single choice."""
    if item["kind"] == "scale":
        return [str(v) for v in range(int(item["min"]), int(item["max"]) + 1)]
    if item["kind"] == "choice":
        return list(item["options"])
    return []


def _gender(value: Any) -> str | None:
    text = _text(value, 16).lower()
    if text in ("男", "男性", "male", "m", "men", "man"):
        return "男"
    if text in ("女", "女性", "female", "f", "women", "woman"):
        return "女"
    return None


def _hukou(value: Any) -> str | None:
    text = _text(value, 16).lower()
    if not text:
        return None
    if any(word in text for word in ("外", "非本地", "流动", "migrant", "non")):
        return "外地"
    return "本地" if "本地" in text or "local" in text else None


def _normalize_groups(raw: Any, warnings: list[str]) -> list[dict[str, Any]]:
    """Subgroups as filters on resident attributes; a group nothing can filter is dropped."""
    groups: list[dict[str, Any]] = []
    gids: set[str] = set()
    entries = raw if isinstance(raw, list) else []
    if len(entries) > MAX_GROUPS:
        warnings.append(f"最多 {MAX_GROUPS} 个分组，多出的已丢弃")
    for index, entry in enumerate(entries[:MAX_GROUPS]):
        if not isinstance(entry, dict):
            continue
        label = _text(entry.get("label") or entry.get("name"), 60)
        group: dict[str, Any] = {
            "gender": _gender(entry.get("gender")),
            "age_min": _int(entry.get("age_min")),
            "age_max": _int(entry.get("age_max")),
            "hukou": _hukou(entry.get("hukou")),
            **education_filters.normalize_filters(entry),
        }
        if (
            group["age_min"] is not None
            and group["age_max"] is not None
            and group["age_max"] < group["age_min"]
        ):
            group["age_min"], group["age_max"] = group["age_max"], group["age_min"]
        if all(group[key] is None for key in GROUP_FILTERS):
            warnings.append(f"分组「{label or index + 1}」没有可用的人口筛选条件，已丢弃")
            continue
        gid = re.sub(r"[^0-9A-Za-z_]+", "", _text(entry.get("id"), 12)).upper() or f"G{index + 1}"
        while gid in gids:
            gid += "X"
        gids.add(gid)
        groups.append({"id": gid, "label": label or gid, **group})
    return groups


def group_dimension(group: dict[str, Any]) -> str:
    """Which attribute(s) a group cuts on; gaps are only compared within one dimension."""
    parts = []
    if group.get("gender"):
        parts.append("gender")
    if group.get("age_min") is not None or group.get("age_max") is not None:
        parts.append("age")
    if group.get("hukou"):
        parts.append("hukou")
    parts.extend(key for key in education_filters.FILTER_KEYS if group.get(key))
    return "+".join(parts)


def in_group(person: dict[str, Any], group: dict[str, Any]) -> bool:
    if not education_filters.matches_filters(person, group):
        return False
    age = int(person.get("age") or 0)
    if group.get("gender") and person.get("gender") != group["gender"]:
        return False
    if group.get("age_min") is not None and age < group["age_min"]:
        return False
    if group.get("age_max") is not None and age > group["age_max"]:
        return False
    if group.get("hukou"):
        local = person.get("hukou") == "本地"
        if local != (group["hukou"] == "本地") or person.get("hukou") in (None, "", "未知"):
            return False
    return True


def normalize_spec(raw: Any) -> dict[str, Any]:
    """Validate a model-written or researcher-edited spec.

    Never invents a number: a human result the paper does not report stays
    absent. What had to be dropped or repaired is listed in ``warnings``.
    """
    data = raw if isinstance(raw, dict) else {}
    warnings: list[str] = []
    bias_settings = data.get("bias_checks")
    bias_settings = bias_settings if isinstance(bias_settings, dict) else {}

    used: set[str] = set()
    items = [
        item
        for index, entry in enumerate((data.get("items") or [])[:MAX_ITEMS])
        if (item := _normalize_item(entry, index, used, warnings)) is not None
    ]
    if len(data.get("items") or []) > MAX_ITEMS:
        warnings.append(f"最多 {MAX_ITEMS} 道题，多出的已丢弃")

    conditions: list[dict[str, Any]] = []
    cids: set[str] = set()
    for index, entry in enumerate((data.get("conditions") or [])[:MAX_CONDITIONS]):
        if isinstance(entry, str):
            entry = {"label": entry}
        if not isinstance(entry, dict):
            continue
        cid = re.sub(r"[^0-9A-Za-z_]+", "", _text(entry.get("id"), 12)).upper() or f"C{index + 1}"
        while cid in cids:
            cid += "X"
        cids.add(cid)
        conditions.append(
            {
                "id": cid,
                "label": _text(entry.get("label") or entry.get("name"), 80) or cid,
                "stimulus": _text(entry.get("stimulus") or entry.get("description"), MAX_TEXT_CHARS),
                "human_n": _int(entry.get("human_n") or entry.get("n")),
            }
        )
    if len(data.get("conditions") or []) > MAX_CONDITIONS:
        warnings.append(f"最多 {MAX_CONDITIONS} 个实验条件，多出的已丢弃")
    if not conditions:
        conditions = [
            {"id": "C1", "label": "全体受访者", "stimulus": "", "human_n": _int(data.get("human_n"))}
        ]

    groups = _normalize_groups(data.get("groups"), warnings)
    by_item = {item["id"]: item for item in items}
    by_condition = {c["id"]: c for c in conditions}
    gids = {g["id"] for g in groups}
    results = []
    seen: set[tuple[str, str, str]] = set()
    for entry in data.get("results") or []:
        if not isinstance(entry, dict):
            continue
        item = by_item.get(str(entry.get("item") or "").strip().upper())
        condition = str(entry.get("condition") or "").strip().upper()
        if condition not in by_condition and len(conditions) == 1:
            condition = conditions[0]["id"]
        group = str(entry.get("group") or "").strip().upper()
        if group and group not in gids:
            continue  # its group was dropped: no residents to compare it with
        if item is None or condition not in by_condition or (item["id"], condition, group) in seen:
            continue
        mean, sd = _num(entry.get("mean")), _num(entry.get("sd"))
        distribution = (
            _normalize_distribution(entry.get("distribution"), item_keys(item)) if item_keys(item) else None
        )
        if item["kind"] == "choice":
            mean = sd = None  # a nominal answer has no mean
        if mean is None and distribution is None:
            continue
        if sd is not None and sd < 0:
            sd = None
        seen.add((item["id"], condition, group))
        results.append(
            {
                "item": item["id"],
                "condition": condition,
                "group": group,
                "mean": mean,
                "sd": sd,
                "n": _int(entry.get("n")) or (None if group else by_condition[condition]["human_n"]),
                "distribution": distribution,
                "source": _text(entry.get("source"), 200),
            }
        )
    if items and not results:
        warnings.append("没有可用的真人结果：至少要有一个题目在一个条件下的均值或选项分布")

    age_min, age_max = _int(data.get("age_min")), _int(data.get("age_max"))
    if age_min is not None and age_max is not None and age_max < age_min:
        age_min, age_max = age_max, age_min
    kind = "experiment" if len(conditions) > 1 else _text(data.get("kind"), 16) or "survey"
    spec = {
        "sampling_probe": sampling_checks.normalize(data.get("sampling_probe")),
        "interaction_probe": interaction_checks.normalize(data.get("interaction_probe")),
        "identity_probe": identity_checks.normalize(data.get("identity_probe")),
        "human_design": data.get("human_design")
        if data.get("human_design") in ("between", "paired")
        else "unknown",
        "bias_checks": {key: bias_settings.get(key) is True for key in ("order", "wording")},
        "title": _text(data.get("title"), 160),
        "citation": _text(data.get("citation"), 400),
        "kind": kind if kind in ("survey", "experiment") else "survey",
        "population": _text(data.get("population"), 600),
        "human_n": _int(data.get("human_n")),
        "age_min": age_min,
        "age_max": age_max,
        "gender": _gender(data.get("gender")),
        "hukou": _hukou(data.get("hukou")),
        **education_filters.normalize_filters(data),
        "intro": _text(data.get("intro"), MAX_TEXT_CHARS),
        "conditions": conditions,
        "groups": groups,
        "items": items,
        "results": results,
        "notes": _text(data.get("notes"), 1200),
        "warnings": warnings,
    }
    # What the paper did not report, and what it leaked into the material the
    # residents read: both decide what the score can and cannot stand for.
    warnings.extend(coverage(spec)["warnings"])
    for leak in leak_findings(spec):
        warnings.append(
            f"材料泄漏：{leak['item']}/{leak['condition']} 的真人{leak['kind']} {leak['value']} "
            f"出现在{leak['where']}里（{leak['excerpt']}）——居民会照着答案答，这一格不计入评分"
        )
    return spec


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_EXTRACT_SCHEMA = """{
  "title": "研究标题",
  "citation": "作者（年份）. 题目. 期刊",
  "kind": "survey 或 experiment",
  "human_design": "between（独立组）或 paired（同一人重复）或 unknown（未报告）",
  "population": "真人受访者是谁：国家/地区、人群、抽样方式、年龄",
  "human_n": 总样本量（整数，未报告写 null）,
  "age_min": 受访者最小年龄（整数或 null）, "age_max": 最大年龄（整数或 null）,
  "education": "已获最高学历：小学及以下 / 初中 / 高中/中专 / 大专 / 本科 / 硕士及以上，未限定写 null",
  "student_status": "当前在读阶段：小学 / 初中 / 高中/中专 / 大专 / 本科 / 硕士 / 博士；只说大学生写大学生，只说研究生写研究生，未限定写 null",
  "gender": "限定性别：男 / 女；未限定写 null", "job": "限定职业关键词；未限定写 null",
  "intro": "所有受访者都看到的说明或情境，忠实转述",
  "conditions": [{"id": "C1", "label": "条件名（对照组放第一个）", "stimulus": "该条件下受访者看到的材料，尽量逐字转述", "human_n": 整数或 null}],
  "items": [
    {"id": "Q1", "text": "题目", "kind": "scale", "min": 1, "max": 7, "labels": ["1 的含义", "7 的含义"]},
    {"id": "Q2", "text": "题目", "kind": "choice", "options": ["选项一", "选项二"]},
    {"id": "Q3", "text": "题目", "kind": "number", "min": 0, "max": 100, "unit": "元"}
  ],
  "results": [
    {"item": "Q1", "condition": "C1", "mean": 4.2, "sd": 1.3, "n": 120, "distribution": null, "source": "表 2"},
    {"item": "Q2", "condition": "C1", "mean": null, "sd": null, "n": 120, "distribution": {"选项一": 62, "选项二": 38}, "source": "第 5 页"},
    {"item": "Q1", "condition": "C1", "group": "G1", "mean": 4.6, "sd": 1.1, "n": 61, "source": "表 3"}
  ],
  "groups": [
    {"id": "G1", "label": "女性", "gender": "女", "age_min": null, "age_max": null, "hukou": null},
    {"id": "G2", "label": "男性", "gender": "男", "age_min": null, "age_max": null, "hukou": null}
  ],
  "notes": "文献里其他研究、没能抽取的结果、需要人工核对的地方"
}"""


def extract_prompt(paper: str, title: str = "") -> str:
    return (
        "你是一位社会科学方法学家。下面是一篇报告了真人社会调查或实验及其结果的文献。"
        "请把它的研究设计和真人结果抽取成一份可以原样交给另一批受访者重做的规格。\n\n"
        "要求：\n"
        "1. 只抽取文献里确实报告的数字，原样照抄；文献没报告的写 null，绝不估算或编造。每个结果在 source 里写出处（表号、图号或页码）。\n"
        "2. 文献有多个研究时，选结果报告最完整的一个，其他写进 notes。\n"
        "3. 实验：每个组间条件是一个 condition，对照组放第一个，stimulus 写受访者在该条件下看到的情境材料；"
        "调查：只有一个 condition。组内设计的不同情境也拆成不同 condition。\n"
        "   题目和选项对所有条件通用：每个选项在每个条件下都必须是一个合理的回答。"
        "选项措辞随条件变化时（如收益框架的方案 A/B、损失框架的方案 C/D），选项写成与条件无关的说法"
        "（如「确定的方案」「有风险的方案」），各条件下的具体措辞写进该条件的 stimulus。\n"
        "4. 题目类型：李克特等有序量表用 scale（写 min / max，labels 写端点含义）；"
        '单选、是非题用 choice（是非题的 options 写 ["是", "否"]）；金额、分配数、概率等数值用 number。\n'
        "5. scale 题有均值就写 mean（和 sd）；有各分值的比例就写 distribution（键为分值）。"
        "choice 题写 distribution（键为选项原文，值为百分比或比例）。\n"
        "6. 文献按人群分组报告了结果时，把分组写进 groups，分组结果在 results 里带上 group（全体结果不写 group）。"
        "分组可以按性别（gender：男 / 女）、年龄范围（age_min / age_max）或户籍（hukou：本地 / 外地）划分，"
        "可以组合（如「30 岁以下女性」）；同一维度的分组放在一起，参照组放第一个。"
        "学历（education，已获学历）、在读阶段（student_status）和职业关键词（job）也可作为分组或整体入选条件。"
        "大学生不等于已本科毕业，未报告的学历、年龄或阶段不能猜测。收入、种族、党派等分组写入 notes。\n"
        "7. 题目、选项和材料一律译成中文，保持原意和选项顺序。最多 "
        f"{MAX_CONDITIONS} 个条件、{MAX_ITEMS} 道题、{MAX_GROUPS} 个分组，挑文献的核心结果。\n"
        "8. 题目文字、选项、说明和 stimulus 里不要出现真人结果（均值、标准差、各选项比例、显著性、效应量）。"
        "居民读到的就是当年受访者读到的；把结果带进材料等于把答案发给居民。"
        "文献里结果和题干写在一起时，题干只保留受访者当时看到的那部分，结果放进 results。\n\n"
        + (f"标题：{title}\n" if title else "")
        + f"【文献】\n{paper[:MAX_PAPER_CHARS]}\n\n"
        f"只输出一个 JSON 对象：\n{_EXTRACT_SCHEMA}"
    )


def extract_spec(paper: str, *, title: str = "", llm: LLMFn) -> dict[str, Any]:
    paper = str(paper or "").strip()
    if len(paper) < 200:
        raise ValueError("文献内容太短：请上传或粘贴包含方法和结果的正文")
    spec = normalize_spec(parse_json(llm(extract_prompt(paper, title))))
    if not spec["items"]:
        raise ValueError("没能从文献里抽取出题目，请检查文献是否包含调查/实验的问题和结果")
    if not spec["title"]:
        spec["title"] = _text(title, 160)
    spec["truncated"] = len(paper) > MAX_PAPER_CHARS
    return spec


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------

_RESPONDENT_RULE = (
    "请完全以你自己的身份、处境和真实想法作答，像一位真实的受访者那样：不必迎合研究者，"
    "不要给面面俱到的中间答案，也不要解释。"
)


def _item_line(item: dict[str, Any]) -> str:
    if item["kind"] == "scale":
        labels = item.get("labels") or []
        hint = f"{item['min']} 到 {item['max']} 的整数"
        if len(labels) >= 2:
            hint += f"，{item['min']} = {labels[0]}，{item['max']} = {labels[-1]}"
        return f"{item['id']}. {item['text']}（{hint}）"
    if item["kind"] == "choice":
        options = "；".join(f"{i}. {o}" for i, o in enumerate(item["options"], 1))
        return f"{item['id']}. {item['text']}（单选，填选项编号：{options}）"
    bounds = ""
    if item.get("min") is not None and item.get("max") is not None:
        bounds = f"，{item['min']} 到 {item['max']}"
    unit = f"，单位：{item['unit']}" if item.get("unit") else ""
    return f"{item['id']}. {item['text']}（填一个数字{bounds}{unit}）"


def answer_prompt(persona_text: str, spec: dict[str, Any], condition: dict[str, Any]) -> str:
    kind = "一项实验" if spec.get("kind") == "experiment" else "一项问卷调查"
    parts = [persona_text, f"你正在参加{kind}。{_RESPONDENT_RULE}"]
    if spec.get("intro"):
        parts.append(f"【说明】{spec['intro']}")
    if condition.get("stimulus"):
        parts.append(f"【你看到的材料】{condition['stimulus']}")
    parts.append("【问题】\n" + "\n".join(_item_line(item) for item in spec["items"]))
    shape = ", ".join(
        f'"{item["id"]}": {"数字" if item["kind"] == "number" else "整数"}' for item in spec["items"]
    )
    parts.append(f"只输出一个 JSON 对象：{{{shape}}}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Leak detection — did the residents get handed the answer?
# ---------------------------------------------------------------------------


def _resident_text(
    spec: dict[str, Any], item: dict[str, Any], condition: dict[str, Any]
) -> list[tuple[str, str]]:
    """The text a resident reads for one question, and where each piece came from."""
    pieces: list[tuple[str, str]] = []
    if spec.get("intro"):
        pieces.append(("说明", str(spec["intro"])))
    if condition.get("stimulus"):
        pieces.append(("材料", str(condition["stimulus"])))
    pieces.append(("题目", str(item.get("text") or "")))
    for label in item.get("labels") or []:
        pieces.append(("量表标签", str(label)))
    for option in item.get("options") or []:
        pieces.append(("选项", str(option)))
    return [(where, text) for where, text in pieces if text.strip()]


def _number_forms(value: float) -> list[str]:
    """How a number may be written in prose: 15, 15.0, 15.00 — but never 2.8 for 2.83."""
    number = float(value)
    forms = {
        f"{number:.{digits}f}"
        for digits in (0, 1, 2, 3)
        if abs(float(f"{number:.{digits}f}") - number) < 1e-9
    }
    forms.add(f"{number:g}")
    return sorted(forms, key=len, reverse=True)


def _find_number(text: str, form: str) -> list[re.Match[str]]:
    """Where ``form`` appears as a whole number (not inside 12.83 or 15.0)."""
    return list(re.compile(r"(?<![\d.])" + re.escape(form) + r"(?![\d.])").finditer(text))


def _marker_in(window: str) -> str | None:
    """The result marker inside ``window``, if there is one."""
    lowered = window.lower()
    for marker in LEAK_MARKERS:
        if marker in lowered:
            return marker
    for pattern in LEAK_MARKERS_LATIN:
        match = re.search(pattern, lowered)
        if match:
            return match.group(0)
    return None


def leak_findings(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Where a reported human result turns up in the text the residents read.

    The answering prompt never carries the paper's numbers by itself, but the item
    text, the stimulus and the intro are transcribed from the paper — and a
    transcription that keeps the result ("原文均值 15 分", "72% 的人选择了 A")
    hands the resident the answer the score is about to measure. Such a cell
    measures nothing, so it must not count for or against the residents.
    """
    humans = {(r["item"], r["condition"]): r for r in (spec.get("results") or []) if not r.get("group")}
    conditions = {c["id"]: c for c in (spec.get("conditions") or [])}
    findings: list[dict[str, Any]] = []
    for item in spec.get("items") or []:
        for cid, condition in conditions.items():
            human = humans.get((item["id"], cid))
            if not human:
                continue
            numbers: list[tuple[str, str]] = []
            if human.get("mean") is not None:
                numbers += [("均值", form) for form in _number_forms(human["mean"])]
            if human.get("sd"):
                numbers += [("标准差", form) for form in _number_forms(human["sd"])]
            for key, share in (human.get("distribution") or {}).items():
                numbers.append((f"占比（{key}）", f"{float(share) * 100:g}%"))
            for where, text in _resident_text(spec, item, condition):
                for label, form in numbers:
                    for match in _find_number(text, form):
                        window = text[max(0, match.start() - LEAK_WINDOW) : match.end() + LEAK_WINDOW]
                        marker = _marker_in(window)
                        if not marker:
                            continue
                        findings.append(
                            {
                                "item": item["id"],
                                "condition": cid,
                                "kind": label,
                                "value": form,
                                "marker": marker,
                                "where": where,
                                "excerpt": text[max(0, match.start() - 24) : match.end() + 24].strip(),
                            }
                        )
    return findings


def coverage(spec: dict[str, Any]) -> dict[str, Any]:
    """How much of the study the paper actually reported, and what it left out.

    A fidelity score is only about the cells the paper reported; the rest never
    enters it. Saying how big that part is keeps the number honest — a study whose
    paper reported one question out of two cannot be scored on two.
    """
    items = spec.get("items") or []
    conditions = spec.get("conditions") or []
    item_ids = [i["id"] for i in items]
    condition_ids = [c["id"] for c in conditions]
    pairs = {
        (r["item"], r["condition"])
        for r in (spec.get("results") or [])
        if not r.get("group") and r["item"] in item_ids and r["condition"] in condition_ids
    }
    covered_items = [i for i in item_ids if any(item == i for item, _ in pairs)]
    covered_conditions = [c for c in condition_ids if any(cond == c for _, cond in pairs)]
    missing_items = [i for i in item_ids if i not in covered_items]
    missing_conditions = [c for c in condition_ids if c not in covered_conditions]
    possible = len(item_ids) * len(condition_ids)
    warnings: list[str] = []
    if missing_items:
        warnings.append(f"题目 {', '.join(missing_items)} 没有真人参照，不参与评分")
    if missing_conditions:
        warnings.append(f"条件 {', '.join(missing_conditions)} 没有真人参照，不参与评分")
    if possible and len(pairs) < possible:
        warnings.append(
            f"文献只报告了 {len(pairs)}/{possible} 个（题目×条件）的真人结果；"
            "拟合度分只覆盖这一部分，不能代表整项研究"
        )
    if (spec.get("groups") or []) and not any(r.get("group") for r in (spec.get("results") or [])):
        warnings.append("文献没有按分组报告结果，分组对照不参与")
    return {
        "cells_possible": possible,
        "cells_with_human": len(pairs),
        "human_coverage": _r(len(pairs) / possible, 3) if possible else None,
        "items_covered": len(covered_items),
        "items_total": len(item_ids),
        "conditions_covered": len(covered_conditions),
        "conditions_total": len(condition_ids),
        "missing_items": missing_items,
        "missing_conditions": missing_conditions,
        "warnings": warnings,
    }


def parse_answer(item: dict[str, Any], value: Any) -> float | None:
    """The counted answer, or ``None``. Out-of-range answers are invalid, not clamped."""
    if item["kind"] == "choice":
        options = item["options"]
        number = _num(value)
        if number is not None and float(number).is_integer() and 1 <= int(number) <= len(options):
            return float(int(number) - 1)
        text = _text(value, 200)
        if text in options:
            return float(options.index(text))
        hits = [i for i, option in enumerate(options) if text and (option in text or text in option)]
        return float(hits[0]) if len(hits) == 1 else None
    number = _num(value)
    if number is None:
        return None
    low, high = item.get("min"), item.get("max")
    if item["kind"] == "scale":
        number = float(round(number))
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def parse_answers(spec: dict[str, Any], raw: Any) -> dict[str, Any]:
    data = parse_json(raw)
    values = {item["id"]: parse_answer(item, data.get(item["id"])) for item in spec["items"]}
    return {"ok": any(v is not None for v in values.values()), "answers": values}


# ---------------------------------------------------------------------------
# Sampling and assignment
# ---------------------------------------------------------------------------


def eligible_residents(people: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    low: int = spec["age_min"] if spec.get("age_min") is not None else MIN_AGE
    high: int | None = spec.get("age_max")
    return [
        p
        for p in people
        if int(p.get("age") or 0) >= low
        and (high is None or int(p.get("age") or 0) <= high)
        and in_group(p, spec)
    ]


def assign(
    residents: list[dict[str, Any]], conditions: list[dict[str, Any]], design: str, seed: int
) -> list[tuple[int, str]]:
    """``(agent id, condition id)`` pairs: balanced random assignment, or everyone × every condition."""
    ids = [int(p["id"]) for p in residents]
    cids = [c["id"] for c in conditions]
    if design == "paired":
        return [(agent_id, cid) for agent_id in ids for cid in cids]
    shuffled = list(ids)
    random.Random(seed + 1).shuffle(shuffled)
    return sorted((agent_id, cids[index % len(cids)]) for index, agent_id in enumerate(shuffled))


# ---------------------------------------------------------------------------
# Comparison — all by code
# ---------------------------------------------------------------------------


def _span(item: dict[str, Any], human: dict[str, Any] | None = None) -> float | None:
    """The width an error is measured against: the item's range, else ±2 human SD."""
    if item["kind"] == "choice":
        return 1.0
    if item.get("min") is not None and item.get("max") is not None:
        return float(item["max"] - item["min"])
    if human and human.get("sd"):
        return 4.0 * float(human["sd"])
    return None


def _human_mean(item: dict[str, Any], human: dict[str, Any]) -> float | None:
    if human.get("mean") is not None:
        return float(human["mean"])
    if item["kind"] == "scale" and human.get("distribution"):
        return sum(float(k) * v for k, v in human["distribution"].items())
    return None


def _shares(item: dict[str, Any], values: list[float]) -> dict[str, float]:
    keys = item_keys(item)
    if item["kind"] == "scale":
        counts = {key: sum(1 for v in values if str(int(v)) == key) for key in keys}
    else:
        counts = {key: sum(1 for v in values if int(v) == index) for index, key in enumerate(keys)}
    return {key: round(count / len(values), 4) for key, count in counts.items()} if values else {}


def _tvd(a: dict[str, float], b: dict[str, float]) -> float:
    return round(0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b)), 4)


def _overlap(a: dict[str, float], b: dict[str, float]) -> float:
    """How much two distributions share: 1 = identical shares, 0 = no overlap."""
    return sum(min(a.get(k, 0.0), b.get(k, 0.0)) for k in set(a) | set(b))


def _spread_error(
    item: dict[str, Any], human: dict[str, Any] | None, agent: dict[str, Any] | None
) -> float | None:
    """How far the agents' spread is from the humans', on 0–1. None when the paper
    reported no dispersion and none can be derived.

    A choice question's error already *is* the whole distribution difference (the
    total variation distance), so it gets no separate spread term. A scale question
    is judged on the ratio of the two standard deviations: agents agreeing far more
    (or far less) than the people did is a mismatch of the population, not of the
    mean, and a mean-only score cannot see it.
    """
    if not human or not agent:
        return None
    if item["kind"] == "choice":
        return None
    if int(agent.get("n") or 0) < MIN_DISPERSION_N:
        return None
    h_sd, a_sd = human.get("sd"), agent.get("sd")
    if h_sd and a_sd is not None:
        if h_sd <= 0:
            return None  # the humans reported no variation: nothing to compare against
        if a_sd <= 0:
            return 1.0  # every agent answered the same: no spread at all
        ratio = a_sd / h_sd
        return _r(1 - min(ratio, 1 / ratio), 4)
    h_dist, a_dist = human.get("distribution"), agent.get("distribution")
    if h_dist and a_dist:
        return _r(1 - _overlap(h_dist, a_dist), 4)
    return None


def _agent_cell(item: dict[str, Any], values: list[float]) -> dict[str, Any]:
    n = len(values)
    cell: dict[str, Any] = {"n": n}
    if item["kind"] == "choice":
        cell["distribution"] = _shares(item, values)
        return cell
    if not n:
        return cell
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    cell.update({"mean": _r(mean), "sd": _r(sd), "ci": [_r(mean - half), _r(mean + half)]})
    if item["kind"] == "scale":
        cell["distribution"] = _shares(item, values)
    return cell


def compare_cell(item: dict[str, Any], human: dict[str, Any] | None, agent: dict[str, Any]) -> dict[str, Any]:
    """One question in one condition: agents against humans, as an error on 0–1."""
    out: dict[str, Any] = {"item": item["id"], "agent": agent, "human": human, "error": None}
    if not human or not agent.get("n"):
        return out
    out["spread_error"] = _spread_error(item, human, agent)
    if item["kind"] == "choice":
        if human.get("distribution") and agent.get("distribution"):
            hd, ad = human["distribution"], agent["distribution"]
            out["tvd"] = _tvd(hd, ad)
            out["modal_match"] = max(hd, key=hd.get) == max(ad, key=ad.get)
            out["error"] = out["tvd"]
        return out
    h_mean = _human_mean(item, human)
    if h_mean is not None and agent.get("mean") is not None:
        diff = agent["mean"] - h_mean
        out["human_mean"] = _r(h_mean)
        out["diff"] = _r(diff)
        low, high = agent["ci"]
        out["within_ci"] = low <= h_mean <= high
        # A unanimous crowd has no spread: its 95% interval collapses to a point
        # and the human mean can never fall inside it. That is a defect of the
        # simulation, not a statistical fact about the humans, so it is flagged
        # rather than read as "the humans were outside the range".
        out["ci_degenerate"] = low >= high
        if human.get("sd") and agent.get("sd") is not None:
            out["sd_ratio"] = _r(agent["sd"] / human["sd"], 3)  # < 1: agents agree more than people do
        span = _span(item, human)
        if span:
            out["error"] = _r(min(1.0, abs(diff) / span))
        elif h_mean:
            out["error"] = _r(min(1.0, abs(diff) / abs(h_mean)))  # no range, no SD: relative error
    if item["kind"] == "scale" and human.get("distribution") and agent.get("distribution"):
        out["tvd"] = _tvd(human["distribution"], agent["distribution"])
        if out["error"] is None:
            out["error"] = out["tvd"]
    return out


def _level_points(item: dict[str, Any], cell: dict[str, Any]) -> list[tuple[float, float]]:
    """``(human, agent)`` on 0–1, for the correlation across cells."""
    if cell.get("error") is None:
        return []
    if item["kind"] == "choice":
        hd, ad = cell["human"]["distribution"], cell["agent"]["distribution"]
        return [(hd[k], ad.get(k, 0.0)) for k in hd]
    if item.get("min") is None or item.get("max") is None or "human_mean" not in cell:
        return []
    span = float(item["max"] - item["min"])
    return [((cell["human_mean"] - item["min"]) / span, (cell["agent"]["mean"] - item["min"]) / span)]


def _welch_p(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    diff = statistics.fmean(a) - statistics.fmean(b)
    if se == 0:
        return 1.0 if diff == 0 else 0.0
    return _p_two_sided(diff / se)


def _paired_p(diffs: list[float]) -> float | None:
    if len(diffs) < 2:
        return None
    sd = statistics.stdev(diffs)
    mean = statistics.fmean(diffs)
    if sd == 0:
        return 1.0 if mean == 0 else 0.0
    return _p_two_sided(mean / (sd / math.sqrt(len(diffs))))


def _human_p(
    item: dict[str, Any], base: dict[str, Any], other: dict[str, Any], option: str | None
) -> float | None:
    """The human contrast's p-value, when the paper gave enough to compute one."""
    n1, n2 = base.get("n"), other.get("n")
    if not n1 or not n2:
        return None
    if option is not None:
        p1, p2 = base["distribution"][option], other["distribution"][option]
        pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        return None if se == 0 else _p_two_sided((p2 - p1) / se)
    if not base.get("sd") or not other.get("sd"):
        return None
    m_base, m_other = _human_mean(item, base), _human_mean(item, other)
    if m_base is None or m_other is None:
        return None
    se = math.sqrt(base["sd"] ** 2 / n1 + other["sd"] ** 2 / n2)
    return _p_two_sided((m_other - m_base) / se)


def verdict(human_effect: float, agent_effect: float, agent_p: float | None) -> str:
    if abs(human_effect) < NULL_EFFECT:
        return "no_human_effect"
    same = agent_effect != 0 and (agent_effect > 0) == (human_effect > 0)
    significant = agent_p is not None and agent_p < ALPHA
    if same:
        return "replicated" if significant else "same_direction"
    return "reversed" if significant else "not_replicated"


def contrast(
    item: dict[str, Any],
    h_base: dict[str, Any] | None,
    h_other: dict[str, Any] | None,
    a_base: dict[int, float],
    a_other: dict[int, float],
    paired: bool,
) -> dict[str, Any] | None:
    """One difference — a treatment against the control, or one group against another — on one question.

    ``a_*`` map agent id → counted answer. Effects are on the item's 0–1 range
    so they compare across questions; a single choice is compared on the
    option whose share moved most among the humans. ``paired`` uses the agents
    present on both sides as their own controls.
    """
    if not h_base or not h_other:
        return None
    option = None
    if item["kind"] == "choice":
        if not h_base.get("distribution") or not h_other.get("distribution"):
            return None
        option = max(
            item["options"], key=lambda o: abs(h_other["distribution"][o] - h_base["distribution"][o])
        )
        index = item["options"].index(option)
        a_base = {k: 1.0 if v == index else 0.0 for k, v in a_base.items()}
        a_other = {k: 1.0 if v == index else 0.0 for k, v in a_other.items()}
        span = 1.0
        human_effect = h_other["distribution"][option] - h_base["distribution"][option]
    else:
        m_base, m_other = _human_mean(item, h_base), _human_mean(item, h_other)
        if m_base is None or m_other is None:
            return None
        # Without a range or an SD the effect is relative to the baseline mean.
        span = _span(item, h_base) or abs(m_base) or 1.0
        human_effect = (m_other - m_base) / span
    if not a_base or not a_other:
        return None
    agent_effect = (statistics.fmean(a_other.values()) - statistics.fmean(a_base.values())) / span
    if paired:
        shared = sorted(set(a_base) & set(a_other))
        if not shared:
            return None
        diffs = [a_other[k] - a_base[k] for k in shared]
        agent_effect = statistics.fmean(diffs) / span
        agent_p = _paired_p(diffs)
    else:
        agent_p = _welch_p(list(a_other.values()), list(a_base.values()))
    return {
        "option": option,
        "human_effect": _r(human_effect),
        "agent_effect": _r(agent_effect),
        "ratio": _r(agent_effect / human_effect, 3) if abs(human_effect) >= NULL_EFFECT else None,
        "human_p": _r(_human_p(item, h_base, h_other, option)),
        "agent_p": _r(agent_p),
        "agent_n": [len(a_base), len(a_other)],
        "verdict": verdict(human_effect, agent_effect, agent_p),
    }


def _direction_rate(rows: list[dict[str, Any]]) -> float | None:
    judged = [r for r in rows if r["verdict"] != "no_human_effect"]
    if not judged:
        return None
    return sum(1 for r in judged if r["verdict"] in ("replicated", "same_direction")) / len(judged)


def _group_rows(
    spec: dict[str, Any],
    item: dict[str, Any],
    values: dict[str, dict[int, float]],
    members: dict[str, set[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group cells (on the residents in each group) and group gaps (within one dimension)."""
    human = {
        (r["condition"], r["group"]): r for r in spec["results"] if r["item"] == item["id"] and r["group"]
    }
    cells: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for condition in spec["conditions"]:
        cid = condition["id"]
        firsts: dict[str, dict[str, Any]] = {}
        for group in spec["groups"]:
            result = human.get((cid, group["id"]))
            if result is None and not (spec.get("identity_probe") or {}).get("enabled"):
                continue
            answers = {k: v for k, v in values.get(cid, {}).items() if k in members[group["id"]]}
            cell = compare_cell(item, result, _agent_cell(item, list(answers.values())))
            cell.update(condition=cid, group=group["id"], ref=f"{item['id']}/{cid}/{group['id']}")
            cell["thin"] = cell["agent"]["n"] < MIN_GROUP_N
            cells.append(cell)
            if result is None:
                # Identity pairs need no human reference. They must not change
                # the reference group of the legacy human-gap comparisons.
                continue
            dimension = group_dimension(group)
            base = firsts.setdefault(dimension, {"group": group, "human": result, "answers": answers})
            if base["group"] is group:
                continue
            gap = contrast(item, base["human"], result, base["answers"], answers, paired=False)
            if gap:
                gid, bid = group["id"], base["group"]["id"]
                gap.update(
                    item=item["id"],
                    condition=cid,
                    base_group=bid,
                    group=gid,
                    dimension=dimension,
                    ref=f"{item['id']}/{cid}/{gid}-{bid}",
                )
                gaps.append(gap)
    return cells, gaps


def compare(
    spec: dict[str, Any],
    responses: list[dict[str, Any]],
    design: str,
    residents: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cells, effects, group cells, group gaps and the summary for a finished run.

    Every row carries a ``ref`` (``Q1/C1``, ``Q1/C2-C1``, ``Q1/C1/G1``,
    ``Q1/C1/G2-G1``) — the handle a model's reading must cite.
    """
    human = {(r["item"], r["condition"]): r for r in spec["results"] if not r.get("group")}
    members = {
        g["id"]: {int(p["agent_id"]) for p in residents or [] if in_group(p, g)}
        for g in spec.get("groups") or []
    }
    cells, effects, points, group_cells, group_gaps = [], [], [], [], []
    leaks = leak_findings(spec)
    leak_map = {(f["item"], f["condition"]): f for f in leaks}
    for item in spec["items"]:
        values: dict[str, dict[int, float]] = {}
        for response in responses:
            value = (response.get("answers") or {}).get(item["id"])
            if value is not None:
                values.setdefault(response["condition"], {})[int(response["agent_id"])] = float(value)
        row = []
        for condition in spec["conditions"]:
            agent = _agent_cell(item, list(values.get(condition["id"], {}).values()))
            cell = compare_cell(item, human.get((item["id"], condition["id"])), agent)
            cell.update(condition=condition["id"], ref=f"{item['id']}/{condition['id']}")
            leak = leak_map.get((item["id"], condition["id"]))
            if leak:
                # The residents were handed this cell's answer: whatever they say back
                # says nothing about them, so the cell is shown but not scored.
                cell["leak"] = leak
            row.append(cell)
            if not leak:
                points += _level_points(item, cell)
        cells += row
        base_id = row[0]["condition"]
        for other in row[1:]:
            cid = other["condition"]
            effect = contrast(
                item,
                row[0]["human"],
                other["human"],
                values.get(base_id, {}),
                values.get(cid, {}),
                paired=design == "paired",
            )
            if effect:
                effect.update(
                    item=item["id"], base=base_id, condition=cid, ref=f"{item['id']}/{cid}-{base_id}"
                )
                effects.append(effect)
        if members:
            more_cells, more_gaps = _group_rows(spec, item, values, members)
            group_cells += more_cells
            group_gaps += more_gaps

    scored = [c for c in cells if not c.get("leak")]
    errors = [c["error"] for c in scored if c.get("error") is not None]
    judged = [e for e in effects if e["verdict"] != "no_human_effect"]
    direction = _direction_rate(effects)
    spread_errors = [c["spread_error"] for c in scored if c.get("spread_error") is not None]
    spread = 1 - statistics.fmean(spread_errors) if spread_errors else None
    # Cells whose 95% interval collapsed to a point *and* did not cover the human
    # mean: every resident answered the same thing, and that common answer missed
    # what the humans said. The "human value inside the agents' 95% interval" rate
    # then reads 0% for a reason that has nothing to do with the humans. When the
    # paper reported an SD the spread term already charges the collapse (a
    # unanimous crowd scores spread_error 1.0); when it did not, that term drops
    # out of the score and the collapse would otherwise be invisible.
    #
    # A collapsed interval that *does* cover the human mean is not charged here:
    # the group got it right, and the level term already says so.
    degenerate = [c for c in scored if c.get("ci_degenerate") and c.get("within_ci") is False]
    degenerate_rate = len(degenerate) / len(scored) if scored else None
    level = 1 - statistics.fmean(errors) if errors else None
    if level is not None and degenerate and spread is None:
        level = level * (1 - COLLAPSE_PENALTY * (degenerate_rate or 0.0))
    if level is None:
        score = None
        parts: dict[str, float] = {}
    else:
        parts = {"level": level, "spread": spread, "direction": direction}
        parts = {key: value for key, value in parts.items() if value is not None}
        weight = sum(SCORE_WEIGHTS[key] for key in parts)
        score = round(100 * sum(SCORE_WEIGHTS[key] * value for key, value in parts.items()) / weight, 1)
    with_ci = [c for c in scored if "within_ci" in c]
    group_errors = [c["error"] for c in group_cells if c.get("error") is not None]
    group_spread_errors = [c["spread_error"] for c in group_cells if c.get("spread_error") is not None]
    ratios = [c["sd_ratio"] for c in scored if c.get("sd_ratio") is not None]
    cover = coverage(spec)
    summary = {
        "score": score,
        "score_version": SCORE_VERSION,
        "score_components": {key: _r(value, 3) for key, value in parts.items()},
        "score_weights": {
            key: _r(SCORE_WEIGHTS[key] / sum(SCORE_WEIGHTS[k] for k in parts), 3) for key in parts
        }
        if parts
        else {},
        "level_accuracy": _r(level, 3),
        "spread_accuracy": _r(spread, 3),
        "spread_cells_compared": len(spread_errors),
        "cells_compared": len(errors),
        "coverage": cover,
        "coverage_warnings": cover["warnings"],
        "score_scope": f"{len(errors)}/{cover['cells_possible']} 个单元格",
        "leaked_cells": sum(1 for c in cells if c.get("leak")),
        "leak_findings": leaks,
        "within_ci_rate": _r(sum(1 for c in with_ci if c["within_ci"]) / len(with_ci), 3)
        if with_ci
        else None,
        "degenerate_ci_cells": len(degenerate),
        "degenerate_ci_rate": _r(degenerate_rate, 3),
        "collapsed_ci_cells": sum(1 for c in scored if c.get("ci_degenerate")),
        "level_r": _pearson([h for h, _ in points], [a for _, a in points]),
        "mean_sd_ratio": _r(statistics.fmean(ratios), 3) if ratios else None,
        "effects_judged": len(judged),
        "direction_rate": _r(direction, 3),
        "replication_rate": _r(sum(1 for e in judged if e["verdict"] == "replicated") / len(judged), 3)
        if judged
        else None,
        "effect_r": _pearson([e["human_effect"] for e in judged], [e["agent_effect"] for e in judged]),
        "verdicts": {key: sum(1 for e in effects if e["verdict"] == key) for key in VERDICTS},
        "group_cells_compared": len(group_errors),
        "group_level_accuracy": _r(1 - statistics.fmean(group_errors), 3) if group_errors else None,
        "group_spread_accuracy": _r(1 - statistics.fmean(group_spread_errors), 3)
        if group_spread_errors
        else None,
        "group_spread_cells_compared": len(group_spread_errors),
        "thin_group_cells": sum(1 for c in group_cells if c["thin"]),
        "group_gaps_judged": sum(1 for g in group_gaps if g["verdict"] != "no_human_effect"),
        "group_direction_rate": _r(_direction_rate(group_gaps), 3),
    }
    return checks.attach(
        spec,
        responses,
        design,
        residents or [],
        {
            "cells": cells,
            "effects": effects,
            "group_cells": group_cells,
            "group_gaps": group_gaps,
            "summary": summary,
        },
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return f"rep-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def run_replication(
    *,
    spec: dict[str, Any],
    city: str = "",
    city_name: str = "",
    sample_size: int = DEFAULT_SAMPLE,
    seed: int | None = None,
    design: str = "between",
    provider: str = "",
    answer: LLMFn,
    population: list[dict[str, Any]] | None = None,
    profile_fn: Callable[[str, int], str] | None = None,
    progress: Callable[[float, str], None] | None = None,
    workers: int = WORKERS,
) -> dict[str, Any]:
    """Have a sample of residents take the study; return the compared run.

    *answer* is the model entry point; *population* and *profile_fn* are
    injected by tests so no city bundle is read.
    """
    from gaworld.apps.games_api import persona_block

    progress = progress or (lambda p, m: None)
    spec = normalize_spec(spec)
    if not spec["items"]:
        raise ValueError("规格里没有题目")
    if not spec["results"]:
        raise ValueError("规格里没有真人结果，无法比较")
    design = design if design in DESIGNS else "between"
    size = max(MIN_SAMPLE, min(MAX_SAMPLE, int(sample_size or DEFAULT_SAMPLE)))
    seed = int(seed) if seed is not None else random.randrange(1, 1_000_000)

    if population is None:
        from gaworld.interview.roster import recruitment_population

        population = recruitment_population(city)
    pool = eligible_residents(population, spec)
    if not pool:
        raise ValueError("这座城市里没有符合年龄、教育、在读阶段等条件的居民，请调整条件或补充样本")
    picked = sorted(random.Random(seed).sample(pool, min(size, len(pool))), key=lambda p: int(p["id"]))
    if profile_fn is None:
        from gaworld.interview.roster import recruitment_profile

        profile_fn = recruitment_profile
    personas, residents = {}, []
    for person in picked:
        agent_id = int(person["id"])
        card = {**person, "profile_md": profile_fn(city, agent_id)}
        personas[agent_id] = persona_block(card)
        residents.append(
            {
                key: person.get(key)
                for key in ("name", "age", "gender", "hukou", "job", "education", "student_status")
            }
            | {"agent_id": agent_id}
        )

    pairs = assign(picked, spec["conditions"], design, seed)
    interaction_groups = interaction_checks.partition(pairs, spec["interaction_probe"], seed)
    conditions = {c["id"]: c for c in spec["conditions"]}
    done = [0]
    variants = checks.variants(spec)
    identity_orders = identity_checks.orders(pairs, seed) if spec["identity_probe"]["enabled"] else {}
    sampling_extra = spec["sampling_probe"]["repeats"] if spec["sampling_probe"]["enabled"] else 0
    model_provenance = getattr(answer, "provenance", {"kind": "unknown", "provider": provider})
    scope = seed_scope(_backend_takes_seed(model_provenance))
    check_protocol = {
        "version": rc.VERSION,
        "spec_hash": rc.fingerprint(spec),
        "personas_hash": rc.fingerprint(personas),
        "model": model_provenance,
        "seed": seed,
        "seed_scope": scope,
        "design": design,
        "variants": list(variants),
        "planned_calls": len(pairs)
        * (
            (1 + len(variants)) * (1 + sampling_extra)
            + (4 * spec["interaction_probe"]["rounds"] if interaction_groups else 0)
        ),
        "unit": "resident",
        "independent_worlds": 1,
        "note": "额外检查独立提问，不将回答写入主实验或居民记忆；模型标识不保证服务端权重不变",
    }
    check_protocol["sampling_probe"] = spec["sampling_probe"]
    if interaction_groups:
        check_protocol["interaction_probe"] = {
            **spec["interaction_probe"],
            "groups": interaction_groups,
            "unit": "group",
            "contrasts": {key: formula for key, (_, _, formula) in interaction_checks.CONTRASTS.items()},
            "scope": interaction_checks.SCOPE,
        }
    if identity_orders:
        check_protocol["identity_probe"] = {
            **spec["identity_probe"],
            "contrast": "B - A",
            "scope": identity_checks.SCOPE,
            "order": "seeded counterbalance within each condition; main answer first",
        }

    def ask(pair: tuple[int, str]) -> dict[str, Any]:
        agent_id, cid = pair
        error = ""
        prompt = answer_prompt(personas[agent_id], spec, conditions[cid])
        # Every cell draws from its own seed, so the same cell is asked the
        # same question the same way on every run with the same run seed.
        this_seed = cell_seed(seed, agent_id, cid)
        try:
            raw = _call_with_seed(answer, prompt, this_seed)
        except Exception as exc:
            _LOG.warning("replication answer failed for #%s: %s", agent_id, exc)
            raw, error = "", f"{type(exc).__name__}: {exc}"
        parsed = parse_answers(spec, raw)
        parsed["raw"] = str(raw)[:12000]
        parsed["prompt_hash"] = rc.fingerprint(prompt)
        parsed["seed"] = this_seed
        parsed["probes"] = {}
        probe_order = [name for name in variants if not name.startswith("identity_")]
        probe_order += identity_orders.get(pair, [])
        parsed["probe_order"] = probe_order
        for name in probe_order:
            variant = variants[name]
            probe_prompt = answer_prompt(personas[agent_id], variant, conditions[cid])
            try:
                probe_raw = _call_with_seed(answer, probe_prompt, cell_seed(this_seed, agent_id, name))
                probe = checks.canonical(parse_answers(variant, probe_raw), variant, spec)
                probe["raw"] = str(probe_raw)[:12000]
            except Exception as exc:
                probe = {"ok": False, "answers": {}, "error": f"{type(exc).__name__}: {exc}"}
            parsed["probes"][name] = {**probe, "prompt_hash": rc.fingerprint(probe_prompt)}
        if sampling_extra:
            parsed["sampling"] = sampling_checks.execute(
                spec,
                variants,
                answer,
                answer_prompt,
                parse_answers,
                checks.canonical,
                personas[agent_id],
                conditions[cid],
                seed,
                agent_id,
            )
        if not parsed["ok"]:
            parsed["error"] = error or f"读不出回答：{_text(raw, 200)}"
        done[0] += 1
        progress(
            0.02 + (0.48 if interaction_groups else 0.96) * done[0] / len(pairs),
            f"已作答 {done[0]}/{len(pairs)}",
        )
        return {"agent_id": agent_id, "condition": cid, **parsed}

    # Worker threads start with an empty context; each call carries the
    # caller's, so the asking user and world stay attached to the model calls.
    caller_context = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="replication") as executor:
        responses = list(executor.map(lambda pair: caller_context.copy().run(ask, pair), pairs))
    # Preserve all-failed attempts as evidence; never replace them with a successful sample.
    comparison = compare(spec, responses, design, residents, provenance=check_protocol)
    sampling_checks.attach(comparison, spec, responses)
    interaction_run = None
    if interaction_groups:
        interaction_run = interaction_probe.execute(
            spec=spec,
            groups=interaction_groups,
            baseline=responses,
            personas=personas,
            answer=answer,
            prompt_fn=answer_prompt,
            parse_fn=parse_answers,
            seed=seed,
            workers=workers,
            progress=progress,
        )
        interaction_checks.attach(comparison, spec, responses, interaction_run)

    return {
        "id": _new_id(),
        "title": spec["title"] or "未命名研究",
        "comparability_epoch": CURRENT_EPOCH,
        "city": str(city or ""),
        "city_name": city_name,
        "provider": provider,
        "seed": seed,
        "seed_scope": scope,
        "design": design,
        "check_protocol": check_protocol,
        "requested_sample": size,
        "eligible": len(pool),
        "spec": spec,
        "residents": residents,
        # The card every resident was given, so an exported package can show
        # what the model actually saw, not only the attributes.
        "personas": personas,
        "responses": responses,
        "failed": sum(1 for r in responses if not r["ok"]),
        "comparison": comparison,
        "interaction_run": interaction_run,
        "created_at": time.time(),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _fmt(value: Any, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def _p(value: float | None) -> str:
    return "<0.001" if value is not None and value < 0.001 else _fmt(value, 3)


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.0%}"


def _score_formula_text(summary: dict[str, Any]) -> str:
    """One line saying how this run's score was put together."""
    if (summary.get("score_version") or 1) < 2:
        return (
            "拟合度分 = 100 ×（有处理效应时：50% 水平准确度 + 50% 效应方向一致率；只有调查时：水平准确度）"
            "——本记录按旧公式计分，没有计入离散度。"
        )
    weights = summary.get("score_weights") or {}
    names = {"level": "水平准确度", "spread": "离散度准确度", "direction": "效应方向一致率"}
    parts = " + ".join(
        f"{round(weights[key] * 100)}% {names[key]}"
        for key in ("level", "spread", "direction")
        if key in weights
    )
    text = (
        f"拟合度分 = 100 ×（{parts}）；"
        "算不出的分量（文献未报离散度、或没有处理效应）不计入，剩下的权重按比例重新分配。"
    )
    if (summary.get("score_version") or 1) >= 3 and summary.get("degenerate_ci_cells"):
        text += (
            f"其中 {summary['degenerate_ci_cells']} 个单元格的居民 95% 区间退化成一个点"
            "（全员同答）且没有覆盖真人均值；文献未报离散度时，这一项按 "
            f"{int(COLLAPSE_PENALTY * 100)}% 计入水平准确度。"
        )
    return text


def _dist(distribution: dict[str, float] | None) -> str:
    return " / ".join(f"{k} {v:.0%}" for k, v in (distribution or {}).items()) or "—"


def group_text(group: dict[str, Any]) -> str:
    """``女 · 30–49 岁 · 外地户籍``: how a group filters residents."""
    parts = [group["gender"]] if group.get("gender") else []
    low, high = group.get("age_min"), group.get("age_max")
    if low is not None or high is not None:
        parts.append(
            f"{low}–{high} 岁"
            if low is not None and high is not None
            else f"{low or high} 岁{'以上' if low else '以下'}"
        )
    if group.get("hukou"):
        parts.append(f"{group['hukou']}户籍")
    for key, label in (("education", "已获学历"), ("student_status", "在读阶段"), ("job", "职业")):
        if group.get(key):
            parts.append(f"{label}：{group[key]}")
    return " · ".join(parts)


def _seed_scope_text(scope: dict[str, Any] | None) -> str:
    """One line saying what this run's seed covered.

    A reader has to be able to tell which parts of the result the seed can
    speak for. It always fixed the sampling and the grouping; whether the
    model's own draw repeats depends on the provider, and that has to be said
    rather than assumed.
    """
    if not scope:
        return "未记录（本次运行早于种子范围的记录）"
    if scope.get("provider_supports_seed"):
        return (
            "固定了抽哪些居民、怎么分组，并给每次模型调用派了格子种子；"
            "本次模型的接口接受 seed，已据此请求同一次抽样，"
            "但托管端点不承诺逐字复现，同一种子重复运行的拟合度分仍可能有小幅差异"
        )
    return (
        "固定了抽哪些居民、怎么分组，并给每次模型调用派了格子种子；"
        "本次模型的接口不接受 seed，作答本身无法复现，"
        "同一种子重复运行的拟合度分可能不同"
    )


def _cell_values(item: dict[str, Any], cell: dict[str, Any]) -> tuple[str, str]:
    human, agent = cell.get("human") or {}, cell["agent"]
    if item["kind"] == "choice":
        return (_dist(human.get("distribution")) if human else "未报告"), _dist(agent.get("distribution"))
    return (
        _fmt(cell.get("human_mean")) if human else "未报告"
    ), f"{_fmt(agent.get('mean'))} (n={agent['n']})"


def export_markdown(run: dict[str, Any]) -> str:
    spec = run["spec"]
    summary = run["comparison"]["summary"]
    cover = summary.get("coverage") or coverage(spec)
    labels = {c["id"]: c["label"] for c in spec["conditions"]}
    items = {i["id"]: i for i in spec["items"]}
    design = (
        "组间随机分配（每人一个条件）" if run.get("design") == "between" else "配对（每人分别作答每个条件）"
    )
    lines = [
        f"# 社会调查/实验拟合度 · {run.get('title') or run['id']}",
        "",
        f"- 文献：{spec.get('citation') or '—'}",
        f"- 真人样本：{spec.get('population') or '—'}（N = {spec.get('human_n') or '未报告'}）",
        f"- 智能体：{run.get('city_name') or run.get('city') or '默认世界'}，{len(run['residents'])} 位居民"
        f"（请求 {run.get('requested_sample')}，符合条件 {run.get('eligible')}，种子 {run.get('seed')}），{design}",
        f"- 无效回答：{run.get('failed', 0)} / {len(run['responses'])}",
        f"- 种子范围：{_seed_scope_text(run.get('seed_scope'))}",
        "",
        "## 拟合度",
        "",
        f"- **拟合度分：{_fmt(summary['score'], 1)}** / 100",
        f"- 水平准确度（1 − 平均误差）：{_fmt(summary['level_accuracy'], 3)}（{summary['cells_compared']} 个单元格）",
        f"- 离散度准确度（1 − 平均离散度误差）：{_fmt(summary.get('spread_accuracy'), 3)}"
        f"（{summary.get('spread_cells_compared', 0)} 个单元格）",
        f"- 真人数值落在智能体 95% 区间内的比例：{_pct(summary['within_ci_rate'])}",
        f"- 95% 区间退化成一点（居民全员同答）的单元格：{summary.get('collapsed_ci_cells', 0)}"
        f"（其中未覆盖真人均值的 {summary.get('degenerate_ci_cells', 0)} 个）",
        f"- 单元格水平相关 r：{_fmt(summary['level_r'], 3)}",
        f"- 效应方向一致率：{_pct(summary['direction_rate'])}；方向一致且显著比例：{_pct(summary['replication_rate'])}"
        f"（{summary['effects_judged']} 个效应）；效应相关 r：{_fmt(summary['effect_r'], 3)}",
        "",
        f"{_score_formula_text(summary)}",
        "误差按题目自身量程归一到 0–1（单选题为分布的总变差距离）；"
        "离散度误差按两个标准差之比算（比值取小的一边，误差 = 1 − 比值）。",
        "",
        "### 这个分数覆盖了多少",
        "",
        f"- 评分口径：{summary.get('score_scope', '—')}"
        f"（研究共 {cover['items_total']} 道题 × {cover['conditions_total']} 个条件 = "
        f"{cover['cells_possible']} 个单元格，文献报告了真人结果的有 {cover['cells_with_human']} 个）",
        f"- 题目覆盖：{cover['items_covered']}/{cover['items_total']}；条件覆盖："
        f"{cover['conditions_covered']}/{cover['conditions_total']}",
        *(
            [f"- ⚠ {text}" for text in cover["warnings"]]
            or ["- 覆盖完整：文献报告的真人结果覆盖了全部题目与条件"]
        ),
        *(
            [
                f"- ⚠ 材料泄漏：{leak['item']}/{leak['condition']} 的真人{leak['kind']} {leak['value']} "
                f"出现在{leak['where']}里（{leak['excerpt']}）——这一格不计入评分"
                for leak in summary.get("leak_findings") or []
            ]
        ),
        "",
        "## 逐题对照",
        "",
        "| 题目 | 条件 | 真人 | 智能体 | 差值 | 误差 | 离散度误差 | SD 比 | 在 95% 区间内 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cell in run["comparison"]["cells"]:
        item = items[cell["item"]]
        h, a = _cell_values(item, cell)
        inside = "—" if "within_ci" not in cell else ("是" if cell["within_ci"] else "否")
        leak = cell.get("leak")
        mark = "（材料含真人结果，不计入评分）" if leak else ""
        lines.append(
            f"| {item['id']} {item['text'][:30]} | {labels[cell['condition']]} | {h} | {a} | "
            f"{_fmt(cell.get('diff'))} | {_fmt(cell.get('error'), 3)}{mark} | "
            f"{_fmt(cell.get('spread_error'), 3)} | {_fmt(cell.get('sd_ratio'), 2)} | {inside} |"
        )
    if run["comparison"]["effects"]:
        lines += [
            "",
            "## 处理效应（相对对照组，按量程归一）",
            "",
            "| 题目 | 条件 | 真人效应 | 智能体效应 | 智能体 p | 真人 p | 判定 |",
            "|---|---|---|---|---|---|---|",
        ]
        for effect in run["comparison"]["effects"]:
            option = f"（「{effect['option']}」占比）" if effect.get("option") else ""
            lines.append(
                f"| {effect['item']}{option} | {labels[effect['condition']]} vs {labels[effect['base']]} | "
                f"{_fmt(effect['human_effect'], 3)} | {_fmt(effect['agent_effect'], 3)} | {_p(effect['agent_p'])} | "
                f"{_p(effect['human_p'])} | {VERDICTS[effect['verdict']]} |"
            )
    groups = {g["id"]: g for g in spec.get("groups") or []}
    group_cells = run["comparison"].get("group_cells") or []
    if group_cells:
        lines += [
            "",
            "## 分组对照",
            "",
            f"- 分组水平准确度：{_fmt(summary.get('group_level_accuracy'), 3)}（{summary.get('group_cells_compared')} 个单元格，"
            f"其中 {summary.get('thin_group_cells')} 个居民不足 {MIN_GROUP_N} 人）",
            f"- 分组离散度准确度：{_fmt(summary.get('group_spread_accuracy'), 3)}"
            f"（{summary.get('group_spread_cells_compared', 0)} 个单元格）",
            f"- 分组差异方向一致率：{_pct(summary.get('group_direction_rate'))}（{summary.get('group_gaps_judged')} 个差异）",
            "",
            "| 题目 | 条件 | 分组 | 真人 | 智能体 | 误差 |",
            "|---|---|---|---|---|---|",
        ]
        for cell in group_cells:
            group = groups[cell["group"]]
            h, a = _cell_values(items[cell["item"]], cell)
            thin = "（样本少）" if cell.get("thin") else ""
            lines.append(
                f"| {cell['item']} | {labels[cell['condition']]} | {group['label']}（{group_text(group)}） | {h} | "
                f"{a}{thin} | {_fmt(cell.get('error'), 3)} |"
            )
    if run["comparison"].get("group_gaps"):
        lines += [
            "",
            "| 题目 | 条件 | 分组差异 | 真人差异 | 智能体差异 | 智能体 p | 判定 |",
            "|---|---|---|---|---|---|---|",
        ]
        for gap in run["comparison"]["group_gaps"]:
            option = f"（「{gap['option']}」占比）" if gap.get("option") else ""
            lines.append(
                f"| {gap['item']}{option} | {labels[gap['condition']]} | {groups[gap['group']]['label']} − "
                f"{groups[gap['base_group']]['label']} | {_fmt(gap['human_effect'], 3)} | {_fmt(gap['agent_effect'], 3)} | "
                f"{_p(gap['agent_p'])} | {VERDICTS[gap['verdict']]} |"
            )
    interpretation = run.get("interpretation") or {}
    if interpretation.get("summary") or interpretation.get("findings"):
        from gaworld.research.replication_interpret import interpretation_markdown

        lines += ["", *interpretation_markdown(interpretation)]
    lines += ["", "## 研究设计", ""]
    if spec.get("intro"):
        lines += [f"**说明**：{spec['intro']}", ""]
    for condition in spec["conditions"]:
        lines += [
            f"- **{condition['id']} · {condition['label']}**：{condition['stimulus'] or '（无额外材料）'}"
        ]
    lines.append("")
    for item in spec["items"]:
        lines.append(f"- {_item_line(item)}")
    lines += [
        "",
        "> 智能体回答由大模型按每位居民的档案扮演生成；p 值为正态近似。"
        "拟合度衡量的是这批居民与文献中真人的接近程度，不等于真人在本城市会怎样作答。",
    ]
    comparison = run["comparison"]
    lines.append(rc.markdown(comparison.get("result_checks")))
    for row in (
        comparison["cells"]
        + comparison["effects"]
        + comparison.get("group_cells", [])
        + comparison.get("group_gaps", [])
    ):
        lines.append(rc.markdown(row.get("result_checks")))
    if run.get("check_protocol"):
        lines += [
            "",
            "## 检查设置与追溯信息",
            "",
            "```json",
            json.dumps(run["check_protocol"], ensure_ascii=False, indent=2),
            "```",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def replication_root() -> Path:
    return PROJECT_ROOT / REPLICATION_DIRNAME


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(value or "")):
        raise KeyError(value)
    return str(value)


def save_run(run: dict[str, Any]) -> None:
    path = replication_root() / f"{_safe_id(run['id'])}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_run(run_id: str) -> dict[str, Any] | None:
    try:
        path = replication_root() / f"{_safe_id(run_id)}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def delete_run(run_id: str) -> bool:
    try:
        path = replication_root() / f"{_safe_id(run_id)}.json"
    except KeyError:
        return False
    if not path.exists():
        return False
    path.unlink()
    return True


def list_runs() -> list[dict[str, Any]]:
    root = replication_root()
    rows = []
    for path in root.glob("*.json") if root.exists() else []:
        data = load_run(path.stem)
        if not data or not data.get("id"):
            continue
        rows.append(
            {
                "id": data["id"],
                "title": data.get("title", ""),
                "city_name": data.get("city_name") or data.get("city") or "",
                "residents": len(data.get("residents") or []),
                "design": data.get("design", ""),
                "score": ((data.get("comparison") or {}).get("summary") or {}).get("score"),
                "created_at": data.get("created_at") or 0,
                "owner_id": data.get("owner_id"),
            }
        )
    rows.sort(key=lambda r: -r["created_at"])
    return rows


__all__ = [
    "ANSWER_MAX_TOKENS",
    "DEFAULT_SAMPLE",
    "DESIGNS",
    "MAX_SAMPLE",
    "MIN_SAMPLE",
    "VERDICTS",
    "answer_prompt",
    "assign",
    "compare",
    "compare_cell",
    "contrast",
    "delete_run",
    "eligible_residents",
    "export_markdown",
    "extract_prompt",
    "extract_spec",
    "group_dimension",
    "group_text",
    "in_group",
    "list_runs",
    "load_run",
    "normalize_spec",
    "parse_answer",
    "parse_answers",
    "replication_root",
    "run_replication",
    "save_run",
    "verdict",
]
