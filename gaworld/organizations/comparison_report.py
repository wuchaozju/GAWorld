"""Local file IO and readable tables for descriptive organization comparisons."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from gaworld.organizations.comparison import ComparisonError, compare_metrics

LABELS = {
    "applications": "已决策申请数",
    "eligible_applications": "合格申请数",
    "coverage_numerator": "覆盖申请数",
    "coverage_denominator": "覆盖率分母",
    "coverage": "覆盖率",
    "aid_paid_cents": "实际资助",
    "balance_cents": "剩余余额",
    "arrears_cents": "未付义务",
    "budget_utilization_denominator_cents": "累计显式拨款",
    "budget_utilization": "预算利用率",
    "vacancies": "已发布岗位总数",
    "occupied": "当前岗位占用",
    "hires": "累计录用",
    "rejections": "拒绝申请数",
    "wage_owed_cents": "累计劳动义务",
    "wage_paid_cents": "累计劳动义务实付",
    "waiting_days_sum": "累计等待天数",
    "waiting_days_denominator": "平均等待分母",
    "mean_waiting_days": "平均等待天数",
    "paid_aid_applications": "实付资助申请数",
}


def _cell(value: Any) -> str:
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for character in ("\\", "|", "`", "*", "_", "[", "]"):
        text = text.replace(character, "\\" + character)
    return text.replace("\r", " ").replace("\n", " ")


def _value(value: int | float | None, unit: str, *, difference: bool = False) -> str:
    if value is None:
        return "—（无分母）"
    sign = "+" if difference and value > 0 else ""
    if unit == "ratio":
        return f"{sign}{value * 100:.2f}" + (" 个百分点" if difference else "%")
    if unit == "cents":
        # Integer arithmetic preserves cents even for large cumulative amounts.
        whole, fraction = divmod(abs(int(value)), 100)
        return f"{'-' if value < 0 else sign}¥{whole}.{fraction:02d}"
    if unit == "days":
        return f"{sign}{value:.2f} 天"
    return f"{sign}{value}"


def _table(
    rows: list[dict[str, Any]], left_label: str, right_label: str, *, groups: bool = False
) -> list[str]:
    prefix = "群体 | " if groups else ""
    lines = [
        f"| {prefix}指标 | {_cell(left_label)} | {_cell(right_label)} | 差值（右−左） |",
        "| " + "--- | " * (5 if groups else 4),
    ]
    for row in rows:
        group_prefix = f"{_cell(row['dimension'] + '/' + row['group'])} | " if groups else ""
        title = LABELS.get(row["metric"], row["metric"])
        values = [
            _value(row[side], row["unit"], difference=side == "difference")
            for side in ("left", "right", "difference")
        ]
        lines.append(f"| {group_prefix}{_cell(title)} | {' | '.join(values)} |")
    return lines


def _markdown(report: dict[str, Any]) -> str:
    a, b = report["sources"]["left"], report["sources"]["right"]
    lines = ["# 持久组织规则对照", "", f"完成日：{a['day']}；范围：本世代累计结果。", ""]
    for source in (a, b):
        lines.extend(
            [
                f"- {_cell(source['label'])}：世代 {_cell(source['generation_id'])}",
                f"  - 输入：{_cell(source['path'])}",
                f"  - SHA-256：{source['sha256']}",
            ]
        )
    lines.extend(["", "差值按右侧减左侧计算；比例差用百分点表示。金额显示为元，JSON/CSV 保持整数分。", ""])
    for org in report["organizations"]:
        lines.extend(
            [f"## {_cell(org['organization_id'])} · {'社区' if org['kind'] == 'community' else '企业'}", ""]
        )
        for side in ("left", "right"):
            rule = org["current_rules"][side]
            lines.append(
                f"- {_cell(report['sources'][side]['label'])} 当前规则：{_cell(rule['name'])}，版本 {rule['version']}"
            )
        if any(rule["version"] > 1 for rule in org["current_rules"].values()):
            lines.extend(["", "存在规则版本变更；这些累计结果可能包含较早规则，应结合决策历史解释。"])
        lines.append("")
        lines.extend(_table(org["metrics"], a["label"], b["label"]))
        lines.extend(
            [
                "",
                "### 决策前群体分布",
                "",
                "按申请计数；显示有申请的群体及所有未知群体。完整零值分组保留在 JSON/CSV。",
                "",
            ]
        )
        visible = {
            (row["dimension"], row["group"])
            for row in org["groups"]
            if row["metric"] == "applications" and (row["left"] or row["right"] or row["group"] == "unknown")
        }
        chosen = {
            "applications",
            "coverage_numerator",
            "coverage_denominator",
            "coverage",
            "mean_waiting_days",
            "aid_paid_cents" if org["kind"] == "community" else "hires",
        }
        rows = [
            row
            for row in org["groups"]
            if (row["dimension"], row["group"]) in visible and row["metric"] in chosen
        ]
        lines.extend(_table(rows, a["label"], b["label"], groups=True))
        if org["rejection_reasons"]:
            lines.extend(["", "### 拒绝原因", ""])
            lines.extend(_table(org["rejection_reasons"], a["label"], b["label"]))
        lines.append("")
    lines.extend(["## 口径与解释", ""])
    lines.extend(f"- {_cell(text)}" for text in report["definitions"].values())
    return "\n".join(lines) + "\n"


def _csv_text(value: Any) -> Any:
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r"))
    ):
        return "'" + value
    return value


def _csv(report: dict[str, Any]) -> str:
    stream = io.StringIO(newline="")
    fields = [
        "organization_id",
        "kind",
        "section",
        "dimension",
        "group",
        "metric",
        "unit",
        "left",
        "right",
        "difference",
        "day",
        "left_label",
        "right_label",
        "left_generation",
        "right_generation",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    a, b = report["sources"]["left"], report["sources"]["right"]
    for org in report["organizations"]:
        for section in ("metrics", "groups", "rejection_reasons"):
            for row in org[section]:
                data = dict(
                    row,
                    organization_id=org["organization_id"],
                    kind=org["kind"],
                    section=section,
                    day=a["day"],
                    left_label=a["label"],
                    right_label=b["label"],
                    left_generation=a["generation_id"],
                    right_generation=b["generation_id"],
                )
                writer.writerow({key: _csv_text(value) for key, value in data.items()})
    return stream.getvalue()


def _load(path: Path) -> tuple[dict[str, Any], str]:
    def invalid_constant(value: str) -> None:
        raise ComparisonError(f"nonfinite JSON value: {value}")

    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"), parse_constant=invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"cannot read input {path}: {exc}") from exc
    return payload, hashlib.sha256(raw).hexdigest()


def _write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def compare_files(
    left_path: str | Path, right_path: str | Path, output_dir: str | Path, **options: Any
) -> dict[str, str]:
    left_file, right_file, output = (
        Path(left_path).resolve(),
        Path(right_path).resolve(),
        Path(output_dir).resolve(),
    )
    paths = {
        kind: output / name
        for kind, name in (
            ("json", "comparison.json"),
            ("csv", "comparison.csv"),
            ("markdown", "comparison.md"),
        )
    }
    if any(path.resolve() in {left_file, right_file} for path in paths.values()):
        raise ComparisonError("report output cannot replace an input file")
    left, left_hash = _load(left_file)
    right, right_hash = _load(right_file)
    report = compare_metrics(left, right, **options)
    report["sources"]["left"].update(path=str(left_file), sha256=left_hash)
    report["sources"]["right"].update(path=str(right_file), sha256=right_hash)
    outputs = {
        "json": json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        "csv": _csv(report),
        "markdown": _markdown(report),
    }
    output.mkdir(parents=True, exist_ok=True)
    for kind, content in outputs.items():
        _write(paths[kind], content)
    return {kind: str(path) for kind, path in paths.items()}
