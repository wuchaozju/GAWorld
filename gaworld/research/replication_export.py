"""The data package of a replication run: everything behind the score.

The Markdown report tells a reader what the run found. It does not let them
check it: the individual answers are gone, the residents' attributes are
gone, the model calls are gone, and the distributions are a table of
percentages rather than something you can look at. This module assembles
the rest into one ZIP:

* ``manifest.json`` — what was run, with which model, at which parameters,
  and the sha256 of every other file in the package.
* ``summary.md`` — the Markdown report.
* ``spec.json`` — the questions, the conditions and the human results.
* ``responses.csv`` — one row per resident per condition: who they are,
  what they answered, whether the answer parsed.
* ``raw_answers.json`` — the model's own words, and the probes' words.
* ``personas.csv`` — the resident attributes and the card the model saw.
* ``model_calls.csv`` — one row per model call: stage, model, parameters,
  seed, prompt fingerprint, latency, success.
* ``checks.json`` — the result checks the score was built on.
* ``distributions.html`` — the human and the agent distributions side by
  side, as charts.

Everything is computed from the run record; the module reads nothing else
and writes nothing outside the ZIP it returns.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import zipfile
from typing import Any

from gaworld.research import replication as rp

#: How much of a model's own answer travels with the package.
RAW_ANSWER_CHARS = 4_000

#: The columns of ``responses.csv``, in order.
RESPONSE_COLUMNS = [
    "agent_id",
    "name",
    "age",
    "gender",
    "hukou",
    "job",
    "education",
    "student_status",
    "condition",
    "condition_label",
    "ok",
    "error",
    "seed",
    "prompt_hash",
    "answers",
]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    """CSV as bytes, with a BOM so Excel reads the Chinese columns right."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _condition_labels(spec: dict[str, Any]) -> dict[str, str]:
    return {str(c.get("id")): str(c.get("label") or c.get("id")) for c in spec.get("conditions") or []}


def _human_results(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """The human results of the paper, keyed by (item, condition)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in spec.get("results") or []:
        key = (str(row.get("item")), str(row.get("condition")))
        out[key] = row
    return out


def _agent_values(
    responses: list[dict[str, Any]],
    condition: str,
    item_id: str,
) -> list[float]:
    """What the agents answered one question in one condition."""
    values = []
    for response in responses:
        if str(response.get("condition")) != condition:
            continue
        value = (response.get("answers") or {}).get(item_id)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _option_label(item: dict[str, Any], value: float) -> str:
    options = item.get("options") or []
    index = int(value)
    if 0 <= index < len(options):
        return str(options[index])
    return str(value)


def _shares(values: list[float], labels: list[str]) -> dict[str, float]:
    if not values:
        return {}
    counts: dict[str, float] = {}
    for value in values:
        key = labels[int(value)] if 0 <= int(value) < len(labels) else str(value)
        counts[key] = counts.get(key, 0.0) + 1
    total = float(len(values))
    return {key: count / total for key, count in counts.items()}


def _human_distribution(human: dict[str, Any] | None) -> dict[str, float]:
    if not human:
        return {}
    raw = human.get("distribution") or {}
    out: dict[str, float] = {}
    for key, share in raw.items():
        try:
            value = float(share)
        except (TypeError, ValueError):
            continue
        out[str(key)] = value if value <= 1.0 else value / 100.0
    return out


def _histogram(
    values: list[float], low: float, high: float, bins: int = 12
) -> list[tuple[float, float, int]]:
    """``(bin low, bin high, count)`` over a fixed range."""
    if not values:
        return []
    if high <= low:
        high = low + 1.0
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = int((value - low) / width)
        if index >= bins:
            index = bins - 1
        if index < 0:
            index = 0
        counts[index] += 1
    return [(low + i * width, low + (i + 1) * width, counts[i]) for i in range(bins)]


def _svg_chart(title: str, subtitle: str, body: str, width: int = 620, height: int = 220) -> str:
    """One chart, as an inline SVG string.

    The chart keeps its natural width: an SVG stretched to the width of the
    page scales its labels up with it, and a 12px label becomes a poster.
    """
    return (
        f'<figure class="chart"><figcaption><strong>{html.escape(title)}</strong>'
        f"<span>{html.escape(subtitle)}</span></figcaption>"
        f'<svg viewBox="0 0 {width} {height}" width="{width}" role="img" '
        f'aria-label="{html.escape(title)}">{body}</svg></figure>'
    )


def _choice_chart(title: str, human: dict[str, float], agent: dict[str, float]) -> str:
    """Two share bars per option: the humans above, the agents below."""
    options = list(dict.fromkeys([*human.keys(), *agent.keys()]))
    if not options:
        return ""
    left, right, top = 150, 96, 26  # the right margin holds the share label
    width, height = 620, 26 + len(options) * 46 + 18
    parts = []
    for index, option in enumerate(options):
        y = top + index * 46
        h_share = human.get(option, 0.0)
        a_share = agent.get(option, 0.0)
        h_w = (width - left - right) * max(0.0, min(1.0, h_share))
        a_w = (width - left - right) * max(0.0, min(1.0, a_share))
        parts.append(
            f'<text x="0" y="{y + 12}" font-size="12" fill="currentColor">{html.escape(option[:18])}</text>'
            f'<rect x="{left}" y="{y}" width="{h_w:.1f}" height="15" fill="#16324F" opacity="0.85"/>'
            f'<text x="{left + h_w + 6:.1f}" y="{y + 12}" font-size="11" fill="currentColor">'
            f"真人 {h_share * 100:.0f}%</text>"
            f'<rect x="{left}" y="{y + 19}" width="{a_w:.1f}" height="15" fill="#B23A2E" opacity="0.85"/>'
            f'<text x="{left + a_w + 6:.1f}" y="{y + 31}" font-size="11" fill="currentColor">'
            f"智能体 {a_share * 100:.0f}%</text>"
        )
    legend = (
        f'<g font-size="11" fill="currentColor">'
        f'<rect x="{left}" y="{height - 16}" width="10" height="10" fill="#16324F" opacity="0.85"/>'
        f'<text x="{left + 15}" y="{height - 7}">真人</text>'
        f'<rect x="{left + 60}" y="{height - 16}" width="10" height="10" fill="#B23A2E" opacity="0.85"/>'
        f'<text x="{left + 75}" y="{height - 7}">智能体</text></g>'
    )
    return _svg_chart(title, "深色＝真人，红色＝智能体", "".join(parts) + legend, width, height)


def _numeric_chart(
    title: str,
    values: list[float],
    human_mean: float | None,
    human_sd: float | None,
    agent_mean: float | None,
    low: float,
    high: float,
) -> str:
    """A histogram of the agents' answers, with the human mean and spread on top.

    The value axis is horizontal, so the humans' mean and spread are drawn
    vertically: a solid line at their mean, a shaded band from one standard
    deviation below it to one above. The labels sit above the plot, where
    they cannot land on a bar.
    """
    left, right, top, bottom = 46, 20, 40, 40
    width, height = 620, 230
    plot_w = width - left - right
    plot_h = height - top - bottom
    bins = _histogram(values, low, high)
    peak = max([count for _, _, count in bins] or [1])
    span = (high - low) or 1.0

    def x_of(value: float) -> float:
        return left + plot_w * (value - low) / span

    parts = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="currentColor" opacity="0.25"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="currentColor" opacity="0.25"/>',
    ]
    if human_sd and human_mean is not None:
        band_left = x_of(human_mean - human_sd)
        band_right = x_of(human_mean + human_sd)
        parts.append(
            f'<rect x="{band_left:.1f}" y="{top}" width="{max(1.0, band_right - band_left):.1f}" '
            f'height="{plot_h}" fill="#16324F" opacity="0.12"/>'
        )
    for index, (_bin_low, _bin_high, count) in enumerate(bins):
        if not count:
            continue
        bar_w = plot_w / len(bins)
        bar_h = plot_h * count / peak
        x = left + index * bar_w
        y = top + plot_h - bar_h
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{y:.1f}" width="{max(1.0, bar_w - 2):.1f}" height="{bar_h:.1f}" '
            f'fill="#B23A2E" opacity="0.7"/>'
        )
    legend = '<g font-size="11" fill="currentColor">'
    legend += f'<text x="0" y="{top - 16}">横轴＝答案值（{low:g}–{high:g}），纵轴＝人数</text>'
    if human_mean is not None:
        legend += (
            f'<line x1="0" y1="{top - 4}" x2="16" y2="{top - 4}" stroke="#16324F" stroke-width="2"/>'
            f'<text x="21" y="{top}">真人均值 {human_mean:g}</text>'
        )
    if agent_mean is not None:
        legend += (
            f'<line x1="130" y1="{top - 4}" x2="146" y2="{top - 4}" stroke="#B23A2E" stroke-width="2" '
            f'stroke-dasharray="4 3"/>'
            f'<text x="151" y="{top}">智能体均值 {agent_mean:g}</text>'
        )
    legend += "</g>"
    axis = '<g font-size="11" fill="currentColor" opacity="0.75">'
    axis += f'<text x="0" y="{top + 10}">{peak}</text>'
    axis += f'<text x="{left}" y="{height - 12}">居民回答（n={len(values)}）</text>'
    axis += f'<text x="{left + plot_w}" y="{height - 12}" text-anchor="end">{high:g}</text>'
    axis += "</g>"
    if human_mean is not None:
        x = x_of(human_mean)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#16324F" stroke-width="2"/>'
        )
    if agent_mean is not None:
        x = x_of(agent_mean)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#B23A2E" '
            f'stroke-width="2" stroke-dasharray="4 3"/>'
        )
    subtitle = "竖线＝真人均值，阴影＝真人 ±1 个标准差，虚线＝智能体均值"
    return _svg_chart(title, subtitle, "".join(parts) + legend + axis, width, height)


def _distributions_html(run: dict[str, Any]) -> str:
    """The human and agent distributions of every question, as charts."""
    spec = run["spec"]
    responses = run.get("responses") or []
    human_rows = _human_results(spec)
    labels = _condition_labels(spec)
    charts: list[str] = []
    for item in spec.get("items") or []:
        item_id = str(item.get("id"))
        for condition in spec.get("conditions") or []:
            condition_id = str(condition.get("id"))
            human = human_rows.get((item_id, condition_id)) or {}
            values = _agent_values(responses, condition_id, item_id)
            title = (
                f"{item_id} · {labels.get(condition_id, condition_id)} · {str(item.get('text') or '')[:40]}"
            )
            if item.get("kind") == "choice":
                options = [str(o) for o in item.get("options") or []]
                agent_shares = _shares(values, options)
                human_shares = _human_distribution(human)
                charts.append(_choice_chart(title, human_shares, agent_shares))
            else:
                agent_mean = sum(values) / len(values) if values else None
                human_mean = human.get("mean")
                human_sd = human.get("sd")
                low = float(item.get("min") if item.get("min") is not None else 0)
                high = float(item.get("max") if item.get("max") is not None else 0)
                if human_mean is not None:
                    low = min(low, float(human_mean) - (float(human_sd or 0) or 1))
                    high = max(high, float(human_mean) + (float(human_sd or 0) or 1))
                if values:
                    low = min(low, min(values))
                    high = max(high, max(values))
                if high <= low:
                    high = low + 1
                charts.append(_numeric_chart(title, values, human_mean, human_sd, agent_mean, low, high))
    body = "".join(charts) or "<p>这个运行没有可画的分布。</p>"
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>拟合度分布对照</title>"
        "<style>"
        "body{font:14px/1.6 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#16324F;"
        "background:#FBFAF6;margin:0;padding:32px}"
        "h1{font-size:22px;margin:0 0 4px}p.lead{color:#5A6B7B;margin:0 0 24px}"
        ".chart{margin:0 0 28px;padding:16px 18px;border:1px solid #E2DED4;background:#FFFDF8;"
        "border-radius:6px;break-inside:avoid}"
        ".chart figcaption{display:flex;justify-content:space-between;gap:16px;margin-bottom:10px}"
        ".chart figcaption span{color:#5A6B7B;font-size:12px}"
        "svg{display:block;color:#16324F;max-width:100%;height:auto}"
        "</style></head><body>"
        f"<h1>{html.escape(str(run.get('title') or run.get('id')))} · 分布对照</h1>"
        '<p class="lead">每一格是一道题在一个条件下的分布：深色是文献里的真人，红色是智能体。'
        "图里的数字由代码算出，与 <code>summary.md</code> 中的分数同源。</p>"
        f"{body}</body></html>"
    )


def _responses_rows(run: dict[str, Any]) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """The per-response rows and the raw answers."""
    spec = run["spec"]
    labels = _condition_labels(spec)
    residents = {int(r.get("agent_id")): r for r in run.get("residents") or []}
    items = [str(i.get("id")) for i in spec.get("items") or []]
    rows: list[list[Any]] = []
    raw: list[dict[str, Any]] = []
    for response in run.get("responses") or []:
        agent_id = int(response.get("agent_id") or 0)
        person = residents.get(agent_id, {})
        answers = response.get("answers") or {}
        condition = str(response.get("condition") or "")
        rows.append(
            [
                agent_id,
                person.get("name", ""),
                person.get("age", ""),
                person.get("gender", ""),
                person.get("hukou", ""),
                person.get("job", ""),
                person.get("education", ""),
                person.get("student_status", ""),
                condition,
                labels.get(condition, condition),
                "是" if response.get("ok") else "否",
                response.get("error", ""),
                response.get("seed", ""),
                response.get("prompt_hash", ""),
                json.dumps(
                    {item_id: answers.get(item_id) for item_id in items if answers.get(item_id) is not None},
                    ensure_ascii=False,
                ),
            ]
        )
        raw.append(
            {
                "agent_id": agent_id,
                "condition": condition,
                "ok": bool(response.get("ok")),
                "error": response.get("error", ""),
                "seed": response.get("seed"),
                "prompt_hash": response.get("prompt_hash", ""),
                "raw": str(response.get("raw") or "")[:RAW_ANSWER_CHARS],
                "probes": {
                    name: {
                        "ok": bool((probe or {}).get("ok")),
                        "answers": (probe or {}).get("answers", {}),
                        "prompt_hash": (probe or {}).get("prompt_hash", ""),
                        "raw": str((probe or {}).get("raw") or "")[:RAW_ANSWER_CHARS],
                    }
                    for name, probe in (response.get("probes") or {}).items()
                    if isinstance(probe, dict)
                },
            }
        )
    return rows, raw


def _persona_rows(run: dict[str, Any]) -> list[list[Any]]:
    """One row per resident: who they are and what card the model was given."""
    personas = run.get("personas") or {}
    rows = []
    for person in run.get("residents") or []:
        agent_id = int(person.get("agent_id") or 0)
        rows.append(
            [
                agent_id,
                person.get("name", ""),
                person.get("age", ""),
                person.get("gender", ""),
                person.get("hukou", ""),
                person.get("job", ""),
                person.get("education", ""),
                person.get("student_status", ""),
                str(personas.get(agent_id) or personas.get(str(agent_id)) or ""),
            ]
        )
    return rows


def _model_call_rows(run: dict[str, Any]) -> list[list[Any]]:
    """One row per model call."""
    rows = []
    for entry in run.get("model_calls") or []:
        rows.append(
            [
                entry.get("seq", ""),
                entry.get("task", ""),
                entry.get("provider", ""),
                entry.get("model", ""),
                entry.get("temperature", ""),
                entry.get("max_tokens", ""),
                entry.get("seed", ""),
                entry.get("agent_id", ""),
                entry.get("condition", ""),
                entry.get("variant", ""),
                entry.get("prompt_hash", ""),
                entry.get("latency_ms", ""),
                "是" if entry.get("ok") else "否",
                entry.get("error", ""),
                entry.get("chars", ""),
            ]
        )
    return rows


def _manifest(run: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    """What was run, and what is in the package."""
    summary = ((run.get("comparison") or {}).get("summary")) or {}
    cover = summary.get("coverage") or rp.coverage(run["spec"])
    model = run.get("model") or ((run.get("check_protocol") or {}).get("model")) or {}
    manifest = {
        "schema": 1,
        "kind": "replication_run",
        "id": run.get("id"),
        "title": run.get("title"),
        "created_at": run.get("created_at"),
        "city": run.get("city"),
        "city_name": run.get("city_name"),
        "design": run.get("design"),
        "seed": run.get("seed"),
        "seed_scope": run.get("seed_scope"),
        "requested_sample": run.get("requested_sample"),
        "eligible": run.get("eligible"),
        "failed": run.get("failed"),
        "comparability_epoch": run.get("comparability_epoch"),
        "score": {
            "score": summary.get("score"),
            "score_version": summary.get("score_version"),
            "score_weights": summary.get("score_weights"),
            "score_scope": summary.get("score_scope"),
            "coverage": {
                "cells_possible": cover.get("cells_possible"),
                "cells_with_human": cover.get("cells_with_human"),
                "items_covered": cover.get("items_covered"),
                "items_total": cover.get("items_total"),
                "conditions_covered": cover.get("conditions_covered"),
                "conditions_total": cover.get("conditions_total"),
                "warnings": cover.get("warnings") or [],
            },
            "leaks": summary.get("leak_findings") or [],
        },
        "model": {
            "provider": model.get("provider"),
            "model": model.get("model"),
            "backend_type": model.get("backend_type"),
            "endpoint_hash": model.get("endpoint_hash"),
            "config_hash": model.get("config_hash"),
            "generation_settings": model.get("generation_settings") or {},
            "allow_fallback": model.get("allow_fallback"),
        },
        # The model that read the paper may differ from the one that played
        # the residents; the package says both.
        "extraction_model": run.get("extraction_model") or {},
        "generation": run.get("generation") or {},
        "check_protocol": run.get("check_protocol") or {},
        "counts": {
            "residents": len(run.get("residents") or []),
            "responses": len(run.get("responses") or []),
            "items": len(run["spec"].get("items") or []),
            "conditions": len(run["spec"].get("conditions") or []),
            "model_calls": len(run.get("model_calls") or []),
        },
        "files": [
            {"name": name, "bytes": len(data), "sha256": _sha256(data)}
            for name, data in sorted(files.items())
        ],
    }
    manifest["integrity"] = _sha256(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    )
    return manifest


def _readme(run: dict[str, Any], manifest: dict[str, Any]) -> str:
    counts = manifest["counts"]
    score = manifest["score"]
    model = manifest["model"]
    generation = manifest["generation"]
    lines = [
        f"# 拟合度数据包 · {run.get('title') or run.get('id')}",
        "",
        "这个压缩包是这个运行的**原始材料**，不是一个重新算过的结果。",
        "分数、图表、判定都由代码算出，模型只负责扮演居民作答。",
        "",
        "## 里面有什么",
        "",
        "| 文件 | 内容 |",
        "|---|---|",
        "| `manifest.json` | 这次运行的元信息：模型版本、生成参数、评分口径、每个文件的 sha256 |",
        "| `summary.md` | 报告：拟合度分、逐题对照、处理效应、检查结论 |",
        "| `spec.json` | 题目、条件、材料与文献里的真人结果 |",
        "| `responses.csv` | 每位居民每个条件一行：属性、逐题作答、是否解析成功 |",
        "| `raw_answers.json` | 模型原话（截断到 4000 字）与各探针的回答 |",
        "| `personas.csv` | 居民属性，以及作答时给模型的档案卡 |",
        "| `model_calls.csv` | 每一次模型调用：阶段、模型、参数、种子、提示词指纹、耗时 |",
        "| `checks.json` | 分数所依据的结果检查 |",
        "| `distributions.html` | 真人与智能体的分布对照图（浏览器打开） |",
        "",
        "## 这次运行",
        "",
        f"- 拟合度分：**{score.get('score')}**（口径：{score.get('score_scope') or '—'}）",
        f"- 覆盖：{score.get('coverage', {}).get('cells_with_human')} / "
        f"{score.get('coverage', {}).get('cells_possible')} 个单元格",
        f"- 模型：{model.get('provider') or '—'} / {model.get('model') or '—'}"
        f"（后端 {model.get('backend_type') or '—'}，端点指纹 {model.get('endpoint_hash') or '—'}）",
        f"- 生成参数：{json.dumps(generation, ensure_ascii=False)}",
        f"- 规模：{counts['responses']} 份回答、{counts['model_calls']} 次模型调用、"
        f"{counts['residents']} 位居民",
        "",
        "## 怎么核对",
        "",
        "1. `manifest.json` 里的 `files[].sha256` 是每个文件的校验值——文件被改过就能发现。",
        "2. `model_calls.csv` 的 `prompt_hash` 与 `responses.csv` 的 `prompt_hash` 对得上，"
        "说明某一行回答确实是那一次调用产生的。",
        "3. `responses.csv` 的逐题作答与 `summary.md` 的逐题对照是同一份数据的两种呈现，"
        "两边的格子数应当一致。",
        "",
        "## 两点提醒",
        "",
        "- 智能体回答由大模型按居民档案生成，拟合度衡量的是这批居民与文献中真人的接近程度，"
        "不等于真人在本城市会怎样作答。",
        "- 种子固定了抽样与分组；托管端点不承诺逐字复现，"
        "同一种子重复运行，分数可能有小幅差异（见 `manifest.json` 的 `seed_scope`）。",
    ]
    return "\n".join(lines) + "\n"


def export_bundle(run: dict[str, Any]) -> bytes:
    """The whole run as a ZIP, ready to be downloaded."""
    spec = run["spec"]
    response_rows, raw = _responses_rows(run)
    files: dict[str, bytes] = {
        "summary.md": rp.export_markdown(run).encode("utf-8"),
        "spec.json": json.dumps(spec, ensure_ascii=False, indent=2).encode("utf-8"),
        "responses.csv": _csv_bytes(RESPONSE_COLUMNS, response_rows),
        "raw_answers.json": json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8"),
        "personas.csv": _csv_bytes(
            [
                "agent_id",
                "name",
                "age",
                "gender",
                "hukou",
                "job",
                "education",
                "student_status",
                "persona_card",
            ],
            _persona_rows(run),
        ),
        "model_calls.csv": _csv_bytes(
            [
                "seq",
                "task",
                "provider",
                "model",
                "temperature",
                "max_tokens",
                "seed",
                "agent_id",
                "condition",
                "variant",
                "prompt_hash",
                "latency_ms",
                "ok",
                "error",
                "chars",
            ],
            _model_call_rows(run),
        ),
        "checks.json": json.dumps(
            {
                "summary_checks": (run.get("comparison") or {}).get("result_checks"),
                "cells": [
                    {
                        "item": cell.get("item"),
                        "condition": cell.get("condition"),
                        "result_checks": cell.get("result_checks"),
                    }
                    for cell in (run.get("comparison") or {}).get("cells") or []
                ],
                "effects": [
                    {
                        "item": effect.get("item"),
                        "condition": effect.get("condition"),
                        "result_checks": effect.get("result_checks"),
                    }
                    for effect in (run.get("comparison") or {}).get("effects") or []
                ],
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8"),
        "distributions.html": _distributions_html(run).encode("utf-8"),
    }
    manifest = _manifest(run, files)
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    readme = _readme(run, manifest)
    files["README.md"] = readme.encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return buffer.getvalue()


def bundle_filename(run: dict[str, Any]) -> str:
    """``<id>-data.zip`` — the name the download is offered under."""
    return f"{run.get('id')}-data.zip"


__all__ = ["RAW_ANSWER_CHARS", "RESPONSE_COLUMNS", "bundle_filename", "export_bundle"]
