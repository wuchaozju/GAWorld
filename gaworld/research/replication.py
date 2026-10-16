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

from gaworld.logging_setup import get_logger

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
GROUP_FILTERS = ("gender", "age_min", "age_max", "hukou")
HUKOU_VALUES = ("本地", "外地")
#: Fidelity score weights when the study has treatment contrasts.
SCORE_WEIGHTS = {"level": 0.5, "direction": 0.5}

VERDICTS = {
    "replicated": "复现：方向一致且显著",
    "same_direction": "方向一致，但不显著",
    "not_replicated": "未复现：方向不一致，也不显著",
    "reversed": "方向相反且显著",
    "no_human_effect": "文献中无差异",
}

LLMFn = Callable[[str], str]


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
        }
        if (
            group["age_min"] is not None
            and group["age_max"] is not None
            and group["age_max"] < group["age_min"]
        ):
            group["age_min"], group["age_max"] = group["age_max"], group["age_min"]
        if all(group[key] is None for key in GROUP_FILTERS):
            warnings.append(f"分组「{label or index + 1}」不是按性别、年龄或户籍划分的，居民无法对应，已丢弃")
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
    return "+".join(parts)


def in_group(person: dict[str, Any], group: dict[str, Any]) -> bool:
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
        if sd is not None and sd <= 0:
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
    return {
        "title": _text(data.get("title"), 160),
        "citation": _text(data.get("citation"), 400),
        "kind": kind if kind in ("survey", "experiment") else "survey",
        "population": _text(data.get("population"), 600),
        "human_n": _int(data.get("human_n")),
        "age_min": age_min,
        "age_max": age_max,
        "intro": _text(data.get("intro"), MAX_TEXT_CHARS),
        "conditions": conditions,
        "groups": groups,
        "items": items,
        "results": results,
        "notes": _text(data.get("notes"), 1200),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_EXTRACT_SCHEMA = """{
  "title": "研究标题",
  "citation": "作者（年份）. 题目. 期刊",
  "kind": "survey 或 experiment",
  "population": "真人受访者是谁：国家/地区、人群、抽样方式、年龄",
  "human_n": 总样本量（整数，未报告写 null）,
  "age_min": 受访者最小年龄（整数或 null）, "age_max": 最大年龄（整数或 null）,
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
        "分组只能按性别（gender：男 / 女）、年龄范围（age_min / age_max）或户籍（hukou：本地 / 外地）划分，"
        "可以组合（如「30 岁以下女性」）；同一维度的分组放在一起，参照组放第一个。"
        "按学历、收入、种族、党派等其他属性的分组无法对应，写进 notes，不要写进 groups。\n"
        "7. 题目、选项和材料一律译成中文，保持原意和选项顺序。最多 "
        f"{MAX_CONDITIONS} 个条件、{MAX_ITEMS} 道题、{MAX_GROUPS} 个分组，挑文献的核心结果。\n\n"
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
        if int(p.get("age") or 0) >= low and (high is None or int(p.get("age") or 0) <= high)
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
        agent_p = _paired_p([a_other[k] - a_base[k] for k in shared])
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
            if result is None:
                continue
            answers = {k: v for k, v in values.get(cid, {}).items() if k in members[group["id"]]}
            cell = compare_cell(item, result, _agent_cell(item, list(answers.values())))
            cell.update(condition=cid, group=group["id"], ref=f"{item['id']}/{cid}/{group['id']}")
            cell["thin"] = cell["agent"]["n"] < MIN_GROUP_N
            cells.append(cell)
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
            row.append(cell)
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

    errors = [c["error"] for c in cells if c.get("error") is not None]
    judged = [e for e in effects if e["verdict"] != "no_human_effect"]
    level = 1 - statistics.fmean(errors) if errors else None
    direction = _direction_rate(effects)
    if level is None:
        score = None
    elif direction is None:
        score = round(100 * level, 1)
    else:
        score = round(100 * (SCORE_WEIGHTS["level"] * level + SCORE_WEIGHTS["direction"] * direction), 1)
    with_ci = [c for c in cells if "within_ci" in c]
    group_errors = [c["error"] for c in group_cells if c.get("error") is not None]
    ratios = [c["sd_ratio"] for c in cells if c.get("sd_ratio") is not None]
    summary = {
        "score": score,
        "level_accuracy": _r(level, 3),
        "cells_compared": len(errors),
        "within_ci_rate": _r(sum(1 for c in with_ci if c["within_ci"]) / len(with_ci), 3)
        if with_ci
        else None,
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
        "thin_group_cells": sum(1 for c in group_cells if c["thin"]),
        "group_gaps_judged": sum(1 for g in group_gaps if g["verdict"] != "no_human_effect"),
        "group_direction_rate": _r(_direction_rate(group_gaps), 3),
    }
    return {
        "cells": cells,
        "effects": effects,
        "group_cells": group_cells,
        "group_gaps": group_gaps,
        "summary": summary,
    }


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
        from gaworld.interview.roster import load_population

        population = load_population(city)
    pool = eligible_residents(population, spec)
    if not pool:
        raise ValueError("这座城市里没有符合文献年龄范围的居民")
    picked = sorted(random.Random(seed).sample(pool, min(size, len(pool))), key=lambda p: int(p["id"]))
    if profile_fn is None:
        from gaworld.interview.roster import profile_block

        profile_fn = profile_block
    personas, residents = {}, []
    for person in picked:
        agent_id = int(person["id"])
        card = {**person, "profile_md": profile_fn(city, agent_id)}
        personas[agent_id] = persona_block(card)
        residents.append(
            {key: person.get(key) for key in ("name", "age", "gender", "hukou", "job")}
            | {"agent_id": agent_id}
        )

    pairs = assign(picked, spec["conditions"], design, seed)
    conditions = {c["id"]: c for c in spec["conditions"]}
    done = [0]

    def ask(pair: tuple[int, str]) -> dict[str, Any]:
        agent_id, cid = pair
        error = ""
        try:
            raw = answer(answer_prompt(personas[agent_id], spec, conditions[cid]))
        except Exception as exc:
            _LOG.warning("replication answer failed for #%s: %s", agent_id, exc)
            raw, error = "", f"{type(exc).__name__}: {exc}"
        parsed = parse_answers(spec, raw)
        if not parsed["ok"]:
            parsed["error"] = error or f"读不出回答：{_text(raw, 200)}"
        done[0] += 1
        progress(0.02 + 0.96 * done[0] / len(pairs), f"已作答 {done[0]}/{len(pairs)}")
        return {"agent_id": agent_id, "condition": cid, **parsed}

    # Worker threads start with an empty context; each call carries the
    # caller's, so the asking user and world stay attached to the model calls.
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="replication") as executor:
        responses = list(executor.map(lambda pair: contextvars.copy_context().run(ask, pair), pairs))
    if not any(r["ok"] for r in responses):
        raise RuntimeError(f"{len(responses)} 份回答全部无效，例如：{responses[0]['error']}")

    return {
        "id": _new_id(),
        "title": spec["title"] or "未命名研究",
        "city": str(city or ""),
        "city_name": city_name,
        "provider": provider,
        "seed": seed,
        "design": design,
        "requested_sample": size,
        "eligible": len(pool),
        "spec": spec,
        "residents": residents,
        "responses": responses,
        "failed": sum(1 for r in responses if not r["ok"]),
        "comparison": compare(spec, responses, design, residents),
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
    return " · ".join(parts)


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
        "",
        "## 拟合度",
        "",
        f"- **拟合度分：{_fmt(summary['score'], 1)}** / 100",
        f"- 水平准确度（1 − 平均误差）：{_fmt(summary['level_accuracy'], 3)}（{summary['cells_compared']} 个单元格）",
        f"- 真人数值落在智能体 95% 区间内的比例：{_pct(summary['within_ci_rate'])}",
        f"- 单元格水平相关 r：{_fmt(summary['level_r'], 3)}",
        f"- 效应方向一致率：{_pct(summary['direction_rate'])}；显著复现率：{_pct(summary['replication_rate'])}"
        f"（{summary['effects_judged']} 个效应）；效应相关 r：{_fmt(summary['effect_r'], 3)}",
        "",
        "拟合度分 = 100 ×（有处理效应时：50% 水平准确度 + 50% 效应方向一致率；只有调查时：水平准确度）。"
        "误差按题目自身量程归一到 0–1（单选题为分布的总变差距离）。",
        "",
        "## 逐题对照",
        "",
        "| 题目 | 条件 | 真人 | 智能体 | 差值 | 误差 | 在 95% 区间内 |",
        "|---|---|---|---|---|---|---|",
    ]
    for cell in run["comparison"]["cells"]:
        item = items[cell["item"]]
        h, a = _cell_values(item, cell)
        inside = "—" if "within_ci" not in cell else ("是" if cell["within_ci"] else "否")
        lines.append(
            f"| {item['id']} {item['text'][:30]} | {labels[cell['condition']]} | {h} | {a} | "
            f"{_fmt(cell.get('diff'))} | {_fmt(cell.get('error'), 3)} | {inside} |"
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
