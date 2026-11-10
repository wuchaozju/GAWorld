"""Education/enrollment vocabulary, explicit legacy evidence and recruitment filters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

EDUCATION_LEVELS = ("小学及以下", "初中", "高中/中专", "大专", "本科", "硕士及以上")
STUDENT_STATUSES = (
    "未知",
    "非在读",
    "小学",
    "初中",
    "高中/中专",
    "大专",
    "本科",
    "硕士",
    "博士",
    "大学生",
    "研究生",
    "在读",
)
UNIVERSITY_STAGES = frozenset(("大专", "本科", "大学生"))
GRADUATE_STAGES = frozenset(("硕士", "博士", "研究生"))
ENROLLED_STAGES = frozenset(STUDENT_STATUSES) - {"未知", "非在读"}
EDUCATION_MIN_AGE = {"初中": 15, "高中/中专": 18, "大专": 21, "本科": 22, "硕士及以上": 24}
STAGE_MIN_AGE = {
    "小学": 6,
    "初中": 12,
    "高中/中专": 15,
    "大专": 18,
    "本科": 18,
    "硕士": 22,
    "博士": 24,
    "大学生": 18,
    "研究生": 22,
    "在读": 6,
}
FILTER_KEYS = ("education", "student_status", "job")


def normalize_education(value: Any) -> str:
    text = str(value or "").strip()
    text = {
        "专科": "大专",
        "高中": "高中/中专",
        "中专": "高中/中专",
        "硕士": "硕士及以上",
        "博士": "硕士及以上",
        "小学": "小学及以下",
        "未上学": "小学及以下",
    }.get(text, text)
    return text if text in (*EDUCATION_LEVELS, "未知") else "未知"


def normalize_student_status(value: Any) -> str:
    text = str(value or "").strip()
    text = {
        "非学生": "非在读",
        "已毕业": "非在读",
        "专科": "大专",
        "高中": "高中/中专",
        "中专": "高中/中专",
    }.get(text, text)
    if text in STUDENT_STATUSES:
        return text
    for suffix in ("在读", "学生"):
        if text.endswith(suffix) and text not in ("大学生", "在读"):
            text = text[: -len(suffix)]
    return text if text in STUDENT_STATUSES else "未知"


def education_attributes(row: Mapping[str, Any], profile: str = "") -> dict[str, str]:
    """CSV wins; missing fields use only explicit profile statements, never age."""
    education = normalize_education(row.get("education"))
    status = normalize_student_status(row.get("student_status"))
    if not str(row.get("education") or "").strip():
        match = re.search(r"最高已获学历[：:]\s*([^；。\n]+)", profile)
        if not match:
            match = re.search(
                r"\*\*教育与收入背景\*\*[：:]\s*(小学及以下|初中|高中/中专|高中|中专|大专|专科|本科|硕士及以上|硕士|博士)学历",
                profile,
            )
        if match:
            education = normalize_education(match[1])
    if not str(row.get("student_status") or "").strip():
        match = re.search(r"当前在读阶段[：:]\s*([^；。\n]+)", profile)
        if match:
            status = normalize_student_status(match[1])
        else:
            # A job or an explicit enrollment phrase is evidence; a degree alone isn't.
            job = str(row.get("job") or "")
            job_match = re.search(r"\*\*职业与工作节奏\*\*[：:]([^\n]+)", profile)
            evidence = job or (job_match[1] if job_match else "")
            if re.search(r"辅导员|导师|教师|教务|管理员|招生|毕业|曾是|曾经|不是|并非|不再|未在读", evidence):
                evidence = ""
            education_match = re.search(r"\*\*教育与收入背景\*\*[：:]([^\n]+)", profile)
            school_text = education_match[1] if education_match else ""
            if re.search(r"不是|并非|不再|未在读", school_text):
                school_text = ""
            patterns = (
                ("博士", r"博士(?:研究生|生|在读)"),
                ("硕士", r"硕士(?:研究生|生|在读)"),
                ("本科", r"本科(?:学生|生|在读)"),
                ("大专", r"(?:大专|专科)(?:学生|生|在读)"),
                ("大学生", r"大学生"),
                ("研究生", r"研究生"),
            )
            for stage, pattern in patterns:
                enrollment = {
                    "博士": "博士在读",
                    "硕士": "硕士在读",
                    "本科": "本科在读",
                    "大专": r"(?:大专|专科)在读",
                }.get(stage)
                if re.search(pattern, evidence) or (enrollment and re.search(enrollment, school_text)):
                    status = stage
                    break
    return {"education": education, "student_status": status}


def education_line(education: str, student_status: str) -> str:
    return f"**教育背景**：最高已获学历：{education}；当前在读阶段：{student_status}。"


def sync_profile(profile: str, attributes: Mapping[str, str], job: str | None = None) -> str:
    line = education_line(attributes["education"], attributes["student_status"])
    if re.search(r"^\*\*教育背景\*\*[：:].*$", profile, re.MULTILINE):
        profile = re.sub(r"^\*\*教育背景\*\*[：:].*$", lambda _: line, profile, flags=re.MULTILINE)
    else:
        header = re.search(r"^##[^\n]*\n", profile, re.MULTILINE)
        position = header.end() if header else 0
        profile = profile[:position] + line + "\n\n" + profile[position:]
    profile = re.sub(
        r"(\*\*教育与收入背景\*\*[：:])[^，。\n]*学历",
        lambda m: m[1] + attributes["education"] + "学历",
        profile,
    )
    if job is not None:
        line = f"**职业与工作节奏**：{job}"
        if re.search(r"^\*\*职业与工作节奏\*\*[：:].*$", profile, re.MULTILINE):
            profile = re.sub(r"^\*\*职业与工作节奏\*\*[：:].*$", lambda _: line, profile, flags=re.MULTILINE)
        else:
            profile += "\n" + line + "\n"
    return profile


def validate_education(education: str, status: str, age: int) -> None:
    # Generation uses typical completion ages; editing permits shorter or
    # accelerated adult paths rather than imposing one country's duration.
    minimum = {"初中": 12, "高中/中专": 15, "大专": 17, "本科": 18, "硕士及以上": 20}
    if age < minimum.get(education, 0):
        raise ValueError("年龄与已获学历不一致")
    stage_minimum = {**STAGE_MIN_AGE, "硕士": 20, "博士": 21, "研究生": 20}
    if age < stage_minimum.get(status, 0):
        raise ValueError("年龄与在读阶段不一致")
    prerequisites = {
        "大专": {"高中/中专"},
        "本科": {"高中/中专", "大专"},
        "硕士": {"本科"},
        "博士": {"本科", "硕士及以上"},
    }
    if status in prerequisites and education != "未知" and education not in prerequisites[status]:
        raise ValueError("已获学历与在读阶段不一致")


def normalize_filters(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Invalid nonempty categories fail closed instead of widening recruitment."""
    result: dict[str, Any] = dict.fromkeys(FILTER_KEYS)
    for key, normalizer in (("education", normalize_education), ("student_status", normalize_student_status)):
        value = str(raw.get(key) or "").strip()
        if value:
            normalized = normalizer(value)
            if normalized == "未知" and value != "未知":
                raise ValueError(f"无效的 {key} 筛选条件：{value}")
            result[key] = normalized
    result["job"] = str(raw.get("job") or "").strip()[:120] or None
    return result


def matches_filters(person: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    attributes = education_attributes(person)
    if filters.get("education") and attributes["education"] != filters["education"]:
        return False
    wanted = filters.get("student_status")
    actual = attributes["student_status"]
    if wanted:
        accepted = {"大学生": UNIVERSITY_STAGES, "研究生": GRADUATE_STAGES, "在读": ENROLLED_STAGES}.get(
            wanted, {wanted}
        )
        if actual not in accepted:
            return False
    return not filters.get("job") or str(filters["job"]).casefold() in str(person.get("job") or "").casefold()
