"""Evidence-backed advisory ratings and bounded source-design records.

Ratings remain model advice. Code validates completeness and computes totals;
it cannot establish the scientific truth of the supplied evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

RUBRIC_VERSION = "gaworld-method-v1"
DIMENSIONS = (
    ("mechanism", 25, "机制表达", "Mechanism"),
    ("measurement", 25, "测量映射", "Measurement"),
    ("identification", 20, "对照与识别", "Identification"),
    ("constraints", 20, "原设计约束保留", "Design constraints"),
    ("validation", 10, "验证与复现安排", "Validation"),
)
ORIGINAL_FIELDS = (
    ("participants", "研究对象", "Participants"),
    ("sample", "样本与招募", "Sample and recruitment"),
    ("assignment", "组别与分配", "Conditions and assignment"),
    ("interventions", "刺激与干预", "Stimuli and interventions"),
    ("measures", "测量与量表", "Measures and scales"),
    ("timepoints", "测量时间点", "Measurement timepoints"),
    ("analysis", "分析方法", "Analysis"),
    ("results", "原文报告结果", "Reported results"),
)
PRESERVATION_STATUSES = {"preserved", "approximated", "missing", "pending"}
_UNKNOWN = {"", "未说明", "未报告", "待确认", "unknown", "not reported", "not specified"}
_PAGES = re.compile(r"\[Page\s+(\d+)\]", re.IGNORECASE)


def _text(value: Any, limit: int = 1200) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def material_source(text: str, limit: int) -> dict[str, Any]:
    """Fingerprint the actual normalized input, never a client-supplied hash."""
    used = text[:limit]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "reference": f"sha256:{digest}",
        "sha256": digest,
        "used_sha256": hashlib.sha256(used.encode("utf-8")).hexdigest(),
        "input_chars": len(text),
        "used_chars": len(used),
        "used_range": [0, len(used)],
        "truncated": len(used) < len(text),
        "coverage": "partial" if len(used) < len(text) else "provided_text",
    }


def located_material(text: str) -> str:
    """Supply actual locators without changing the stored material."""
    if _PAGES.search(text):
        return text
    return "\n\n".join(
        f"[Paragraph {index}]\n{paragraph}" for index, paragraph in enumerate(re.split(r"\n\s*\n", text), 1)
    )


def _source(value: Any, material: str) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    locator, quote = _text(value.get("locator"), 100), _text(value.get("quote"), 300)
    segment = ""
    page = re.fullmatch(r"(?:page:|\[Page\s+)(\d+)\]?", locator, re.IGNORECASE)
    paragraph = re.fullmatch(r"(?:paragraph:|\[Paragraph\s+)(\d+)\]?", locator, re.IGNORECASE)
    if page:
        pages = list(_PAGES.finditer(material))
        matches = [index for index, marker in enumerate(pages) if marker.group(1) == page.group(1)]
        if len(matches) == 1:
            index = matches[0]
            end = pages[index + 1].start() if index + 1 < len(pages) else len(material)
            segment = material[pages[index].end() : end]
    elif paragraph:
        parts = re.split(r"\n\s*\n", material)
        index = int(paragraph.group(1)) - 1
        if 0 <= index < len(parts):
            segment = parts[index]
    return {"locator": locator, "quote": quote, "verified": bool(quote and quote in segment)}


def normalize_original_design(value: Any, material: str = "", *, confirmed: bool = False) -> dict[str, Any]:
    """Keep omissions explicit; a claimed quote is rechecked at its locator."""
    if not isinstance(value, dict) or not any(key in value for key, *_ in ORIGINAL_FIELDS):
        return {}
    result = {}
    for key, *_ in ORIGINAL_FIELDS:
        item = value.get(key)
        item = item if isinstance(item, dict) else {"value": item}
        text = _text(item.get("value"), 2000)
        result[key] = {
            "value": text or "未说明",
            "status": "unknown" if text.lower() in _UNKNOWN else "reported",
            "source": _source(item.get("source"), material),
            "manual_edited": confirmed and item.get("manual_edited") is True,
        }
    return result


def normalize_preservation(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    known = {key for key, *_ in ORIGINAL_FIELDS}
    result = []
    seen = set()
    for item in value[:16]:
        if not isinstance(item, dict):
            continue
        key = _text(item.get("field"), 80)
        if key not in known or key in seen:
            continue
        seen.add(key)
        status = item.get("status")
        result.append(
            {
                "field": key,
                "status": status if status in PRESERVATION_STATUSES else "pending",
                **{name: _text(item.get(name)) for name in ("original", "proposed", "consequence")},
            }
        )
    return result


def normalize_assessment(
    value: Any, *, legacy: dict[str, Any] | None = None, missing_constraints: bool = False
) -> dict[str, Any]:
    """Unknown bands/evidence prevent totals, regardless of a model's score."""
    value = value if isinstance(value, dict) else {}
    raw = value.get("dimensions")
    if not isinstance(raw, list):
        old_score = (legacy or {}).get("score")
        if isinstance(old_score, int) and not isinstance(old_score, bool) and 0 <= old_score <= 100:
            return {
                "rubric_version": "legacy",
                "status": "legacy",
                "score": old_score,
                "dimensions": [],
                "execution_status": "pending",
                "comparable": False,
            }
        raw = []
    rows = []
    for key, weight, zh, en in DIMENSIONS:
        matches = [item for item in raw if isinstance(item, dict) and item.get("id") == key]
        item = matches[0] if len(matches) == 1 else {}
        band, evidence = item.get("band"), _text(item.get("evidence"))
        if type(band) is not int or band not in range(5) or not evidence or item.get("unknown") is True:
            band = None
        if key == "constraints" and missing_constraints:
            band = None
        rows.append(
            {
                "id": key,
                "label": zh,
                "label_en": en,
                "weight": weight,
                "band": band,
                "evidence": evidence,
                "gap": _text(item.get("gap")),
                "status": "pending" if band is None else "assessed",
            }
        )
    complete = all(item["band"] is not None for item in rows)
    score = int(sum(item["band"] * item["weight"] / 4 for item in rows) + 0.5) if complete else None
    return {
        "rubric_version": RUBRIC_VERSION,
        "status": "complete" if complete else "pending",
        "score": score,
        "dimensions": rows,
        "execution_status": "pending",
        "comparable": complete,
    }


def assessment_prompt() -> str:
    example = {
        "dimensions": [
            {"id": key, "band": None, "evidence": "具体依据；资料不足留空", "gap": "缺口与替代的后果"}
            for key, *_ in DIMENSIONS
        ]
    }
    return (
        "\n## 方法建议量表（仅供研究者审阅，不能替代编译后的执行检查）\n"
        "每个设计分别填写 assessment，维度权重 mechanism=25、measurement=25、identification=20、"
        "constraints=20（原设计约束保留）、validation=10。每维 band 取 0–4 或 null；代码计算总分，不要自行报总分。\n"
        "0=已知无法满足；1=仅有构想且核心机制或测量需新增；2=可近似表达但有重要替代；"
        "3=基本满足且差异明确；4=要求逐项有据且无必要缺口。无依据必须 null，不能用低分或高分代替未知。\n"
        "论文 constraints 核对原研究设计，想法核对用户明确要求；两种材料总分不可直接比较。"
        "信息简短不代表限制不存在。分数不是成功概率、现实效度或代码可执行结论。\n"
        "assessment 格式：" + json.dumps(example, ensure_ascii=False) + "\n"
        '每个设计另填 preservation：[ {"field":"measures", "status":"preserved|approximated|missing|pending", '
        '"original":"原要求", "proposed":"拟采用方法", "consequence":"替代或缺失的后果"} ]，'
        "逐项覆盖下面 original_design 的八项；不自动省略未知项。\n"
    )


def original_design_prompt() -> str:
    example = {
        key: {
            "value": label + "；原文没有就写未说明",
            "source": {"locator": "page:1 或 paragraph:1", "quote": "该位置可核对的短原文，最多300字符"},
        }
        for key, label, _ in ORIGINAL_FIELDS
    }
    return (
        "\n## 原研究设计资料\n"
        "输出顶层 original_design，严格依据提供材料，不估计未报告的样本、题项、量表、效应或条件。"
        "使用材料中的 [Page N] 或 [Paragraph N] 引用位置；页码不存在时不得编造。"
        "quote 必须逐字来自该位置；只能核对片段是否存在，不能据此证明提炼结论正确。\n"
        + json.dumps(example, ensure_ascii=False)
        + "\n"
    )


def assessment_markdown(value: dict[str, Any], language: str = "zh-CN") -> str:
    english = language == "en"
    if value.get("status") == "legacy":
        return (
            "**Legacy model rating; no shared rubric. Not comparable with rubric v1.**\n"
            if english
            else "**旧版模型总评，无统一量表；不能与新版建议分直接比较。**\n"
        )
    title = "Method advice (rubric v1)" if english else "方法建议（量表 v1）"
    pending = "Pending confirmation" if english else "待确认"
    score = f"{value['score']}/100" if value.get("score") is not None else pending
    lines = [f"**{title}: {score}**", ""]
    lines.append(
        "Model advice, not success probability. Execution checks are pending compilation."
        if english
        else "模型方法建议，不是成功率；平台执行检查待编译后由代码确认。"
    )
    for item in value.get("dimensions") or []:
        band = f"{item['band']}/4" if item.get("band") is not None else pending
        label = item["label_en"] if english else item["label"]
        lines.append(f"- {label} ({item['weight']}%): {band} — {item.get('evidence') or pending}")
        if item.get("gap"):
            lines.append(f"  {'Gap' if english else '缺口'}: {item['gap']}")
    return "\n".join(lines) + "\n"
