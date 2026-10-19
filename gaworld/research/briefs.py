"""Bounded recovery of structured research briefs, without placeholder data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.research.briefs")


def parse_brief(response: str, state_keys: set[str]) -> tuple[dict[str, Any] | None, str]:
    raw = str(response or "").strip()
    while re.match(r"\A<think>", raw, flags=re.I):
        closing = re.search(r"</think>", raw, flags=re.I)
        if closing is None:
            return None, "truncated_thinking"
        raw = raw[closing.end() :].strip()
    if not raw:
        return None, "empty_response"
    decoder = json.JSONDecoder(strict=False)
    found = []
    cursor = 0
    while (start := raw.find("{", cursor)) >= 0:
        try:
            payload, end = decoder.raw_decode(raw, start)
        except ValueError as exc:
            # Never salvage a nested object from an incomplete outer JSON.
            return None, f"invalid_json: {exc}"
        cursor = end
        if isinstance(payload, dict) and "brief" in payload:
            found.append(payload)
    if len(found) != 1:
        return None, "missing_brief_object" if not found else "ambiguous_brief_objects"
    payload = found[0]
    if not isinstance(payload["brief"], str) or not payload["brief"].strip():
        return None, "brief_must_be_nonempty_text"
    changes = payload.get("state_changes")
    if not isinstance(changes, dict):
        return None, "state_changes_must_be_object"
    if set(changes) - state_keys:
        return None, "unknown_state_key"
    for value in changes.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "state_delta_must_be_numeric"
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            return None, "state_delta_must_be_finite"
    return payload, ""


def request_brief(
    llm_fn: Any, *, prompt: str, task: str, agent_id: Any, ledger: Any, state_keys: set[str]
) -> dict[str, Any]:
    failure = ""
    for attempt in (1, 2):
        ledger.check()
        if attempt == 2:
            ledger.brief_event("repair")
        instruction = (
            prompt
            if attempt == 1
            else (
                prompt + "\n上次响应未满足 JSON 简报格式（" + failure + "）。"
                "请重新按原始资料输出一个完整 JSON 对象，不要解释、代码围栏或思考过程。"
                "brief 必须是文字，state_changes 必须是数值增量对象；无变化时明确给 {}。"
            )
        )
        try:
            response = llm_fn(
                instruction, task=task, agent_id=agent_id, **({"max_tokens": 4096} if attempt == 2 else {})
            )
        except Exception as exc:
            # Provider errors have their own retry/cooldown budget. They are
            # never counted as malformed model output or retried here.
            raise RuntimeError(f"研究简报调用失败（{type(exc).__name__}）；不使用占位数据") from exc
        payload, failure = parse_brief(response, state_keys)
        if payload is not None:
            ledger.brief_event("valid")
            if attempt == 2:
                ledger.brief_event("recovered")
            return payload
        raw = str(response or "")
        diagnostic = {
            "task": task,
            "agent_id": agent_id,
            "attempt": attempt,
            "category": failure,
            "response_chars": len(raw),
            "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        }
        day = re.search(r"\bDay\s+(\d+)", prompt)
        if day:
            diagnostic["day"] = int(day.group(1))
        ledger.brief_event("parse_failed", diagnostic)
        _LOG.warning(
            "研究简报格式错误 agent=%s task=%s attempt=%s category=%s chars=%s sha256=%s",
            agent_id,
            task,
            attempt,
            failure,
            len(raw),
            diagnostic["response_sha256"][:12],
        )
    ledger.invalid_brief()
    raise RuntimeError(f"研究简报两次响应均不可用：{failure}；不使用占位数据")
