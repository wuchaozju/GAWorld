"""Bounded, non-executing recovery of structured game replies.

Recovery accepts Python-style string quotes/trailing commas and JSON literal
names. It does not infer missing fields or execute model-produced expressions.
"""

from __future__ import annotations

import ast
import io
import json
import math
import tokenize
from typing import Any


def reply_object(raw: str) -> tuple[dict[str, Any], str]:
    """Return the first complete object and whether literal repair was needed."""
    text = str(raw or "")[:16000]
    start = text.find("{")
    for _ in range(16):
        if start < 0:
            break
        quote = ""
        escaped = False
        depth = 0
        nesting = 0
        for end in range(start, len(text)):
            char = text[end]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
            elif char in ('"', "'"):
                quote = char
            elif char == "{":
                depth += 1
                nesting += 1
                if nesting > 64:
                    return {}, "invalid"
            elif char == "[":
                nesting += 1
                if nesting > 64:
                    return {}, "invalid"
            elif char == "]":
                nesting -= 1
            elif char == "}":
                depth -= 1
                nesting -= 1
                if depth == 0:
                    candidate = text[start : end + 1]
                    try:
                        payload = json.loads(candidate)
                        if isinstance(payload, dict):
                            return payload, "ok"
                    except (ValueError, RecursionError):
                        pass
                    try:
                        tokens = tokenize.generate_tokens(io.StringIO(candidate).readline)
                        normalized = tokenize.untokenize(
                            [
                                (
                                    token.type,
                                    {"true": "True", "false": "False", "null": "None"}.get(
                                        token.string, token.string
                                    )
                                    if token.type == tokenize.NAME
                                    else token.string,
                                )
                                for token in tokens
                            ]
                        )
                        payload = ast.literal_eval(normalized)
                        if isinstance(payload, dict):
                            return payload, "repaired"
                    except (ValueError, SyntaxError, TypeError, RecursionError, tokenize.TokenError):
                        pass
                    break
        start = text.find("{", start + 1)
    return {}, "invalid"


def scale_integer(value: Any, low: int, high: int) -> int | None:
    """Only finite, integral, in-range measurements are usable."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return int(number) if math.isfinite(number) and number.is_integer() and low <= number <= high else None


def boolean_answer(value: Any) -> bool | None:
    """Read explicit boolean answers; unknown is different from false."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None
