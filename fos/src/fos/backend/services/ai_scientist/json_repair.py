"""JSON parsing and repair helpers for AI Scientist model output."""

from __future__ import annotations

import json
import re
from typing import Any

from fos.i18n import T


def extract_json_block(raw_output: str) -> str:
    text = (raw_output or "").strip()
    if not text:
        raise ValueError(T("error.ai_scientist.model_empty_output"))

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(T("error.ai_scientist.model_output_no_json"))
    return text[start:end + 1]


def parse_llm_json(raw_output: str) -> dict[str, Any]:
    parsed = json.loads(extract_json_block(raw_output))
    if not isinstance(parsed, dict):
        raise ValueError(T("error.ai_scientist.model_json_not_object"))
    return parsed


def repair_llm_json(raw_output: str) -> dict[str, Any]:
    text = (raw_output or "").strip()
    if not text:
        raise ValueError(T("error.ai_scientist.model_empty_output"))

    candidates: list[str] = []
    if text:
        candidates.append(text)

    normalized = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    if normalized != text:
        candidates.append(normalized)

    start = normalized.find("{")
    end = normalized.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(normalized[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    raise ValueError(T("error.ai_scientist.model_json_repair_failed"))


__all__ = ["extract_json_block", "parse_llm_json", "repair_llm_json"]
