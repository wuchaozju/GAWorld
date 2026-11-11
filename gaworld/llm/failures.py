"""Safe public diagnostics for provider failures; never serialize request secrets."""

from __future__ import annotations

import re
import time

from gaworld.llm.run_state import retry_delay


def describe(exc, *, now=None):
    now = time.time() if now is None else now
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    body = getattr(response, "text", "") if response is not None else ""
    match = re.search(r"\b(2062|2067)\b", body) if status == 429 else None
    code = match[1] if match else None
    kind, message = "unknown", "模型请求中断，已保留完成的回答；请查看服务状态后继续。"
    retry_at = None
    if status == 429:
        floor = 300 if code else 60
        retry_at = now + max(floor, retry_delay(exc, now=now))
        if code == "2062":
            kind, message = (
                "token_plan_rate_limit",
                "MiniMax Token Plan 达到速率限制（HTTP 429，2062），已暂停并保留进度。",
            )
        elif code == "2067":
            kind, message = (
                "token_plan_quota",
                "MiniMax Token Plan 可用用量已达上限（HTTP 429，2067），已暂停并保留进度。请检查套餐用量。",
            )
        else:
            kind, message = "rate_limit", "模型服务限流（HTTP 429），已暂停并保留进度。"
    elif status in (401, 403):
        kind, message = "authentication", f"模型服务拒绝访问（HTTP {status}），请检查该模型的凭证或权限。"
    elif status is not None:
        kind, message = "http_error", f"模型服务返回 HTTP {status}，已保留进度；请检查模型服务后继续。"
    elif "Connection" in type(exc).__name__ or "Timeout" in type(exc).__name__:
        kind, message = "network", "连接模型服务失败或请求超时，已保留进度，可稍后继续。"
    return {
        "kind": kind,
        "exception": type(exc).__name__,
        "http_status": status,
        "provider_code": code,
        "message": message,
        "retry_at": retry_at,
        "hint": "重试时间是本地等待下限，不代表服务商承诺的额度恢复时间。" if retry_at else "",
    }
