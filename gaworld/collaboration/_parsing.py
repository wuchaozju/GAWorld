from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any


_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*\s*\n(.*?)```", re.DOTALL)


def _first_object(text: str) -> str:
    """Return the first balanced ``{...}`` span, ignoring braces in strings."""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : index + 1]
    return ""


def _candidates(text: str) -> Iterator[str]:
    yield text
    for block in _FENCE_RE.findall(text):
        block = block.strip()
        if block:
            yield block
    span = _first_object(text)
    if span:
        yield span


def extract_json(raw: Any) -> dict[str, Any]:
    """Return the first JSON object found in ``raw``, or ``{}``.

    Models routinely wrap their JSON in a ```json fence or bracket it with
    a sentence of explanation. A bare :func:`json.loads` rejects both, and
    callers then fall back to defaults that contradict what the model
    actually said — a fenced ``{"approved": true}`` silently becomes a
    rejection.
    """
    text = str(raw or "").strip()
    if not text:
        return {}
    for candidate in _candidates(text):
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}
