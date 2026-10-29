"""Frozen execution policy and conservative response recovery, with no model calls."""

from __future__ import annotations

import json
import re
import time

from gaworld.llm.run_state import retry_delay

POLICY = {
    "min_interval_seconds": 10,
    "on_429": "pause_manual_resume",
    "rate_limit_floor_seconds": 60,
    "token_plan_floor_seconds": 300,
    "json_recovery": "complete_message_escaping_v1",
    "automatic_retries": 0,
}


def wait_for_slot(last, interval, checkpoint, set_waiting, wait, *, clock=time.monotonic):
    if last is None:
        checkpoint()
        return clock()
    try:
        if last + interval > clock():
            set_waiting(True)
        while last + interval > clock():
            checkpoint()
            wait(min(0.2, last + interval - clock()))
        checkpoint()
        return clock()
    finally:
        set_waiting(False)


def rate_limit(exc, *, now=None):
    response = getattr(exc, "response", None)
    if response is None or response.status_code != 429:
        return None
    quota = "2062" in response.text
    floor = POLICY["token_plan_floor_seconds"] if quota else POLICY["rate_limit_floor_seconds"]
    delay = max(floor, retry_delay(exc, now=now))
    return {
        "kind": "token_plan_2062" if quota else "rate_limit",
        "retry_at": (time.time() if now is None else now) + delay,
        "message": "MiniMax Token Plan 已限流（2062），请等待配额恢复或检查套餐。"
        if quota
        else "模型服务限流（HTTP 429），请等待后再续跑。",
        "hint": "最早重试时间仅为本地退避下限，不代表服务商承诺的配额恢复时间。",
    }


def escape_message(text):
    """Only a closed choice+message object; never infer fields or repair truncation."""
    match = re.fullmatch(r'\s*\{\s*"choice"\s*:\s*([0-3])\s*,\s*"message"\s*:\s*"(.*)"\s*\}\s*', text, re.S)
    if not match:
        raise ValueError("不是完整的 choice/message 对象")
    body = match[2]
    # A quote followed by JSON structural punctuation could close a field.
    # Reject that ambiguous case rather than swallowing additional fields.
    escaped, pending = [], False
    for index, char in enumerate(body):
        if pending:
            escaped.append(char)
            pending = False
        elif char == "\\":
            escaped.append(char)
            pending = True
        elif char == '"':
            if body[index + 1 :].lstrip().startswith((",", "}", ":", "]")):
                raise ValueError("message 边界不明确，不进行修复")
            escaped.append('\\"')
        elif char in "\n\r\t":
            escaped.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}[char])
        else:
            escaped.append(char)
    return json.loads('{"choice":' + match[1] + ',"message":"' + "".join(escaped) + '"}')
