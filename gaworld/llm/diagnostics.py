"""Safe, actionable fault categories for task APIs and research ledgers.

Only static messages and bounded caller-supplied identifiers leave this module.
Upstream exception text and response bodies are used for classification, never
copied into a browser-facing result.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
from collections.abc import Iterable
from typing import Any

import requests

_MESSAGES = {
    "no_comparable_data": (
        "没有可用于判定假设的数据；请查看执行记录和运行日志。",
        "检查失败世界与缺失指标，修复后创建新的尝试。",
        False,
    ),
    "configuration_missing": (
        "模型配置或密钥缺失。",
        "检查当前任务实际路由、模型名称及当前账号密钥。",
        False,
    ),
    "authentication_failed": (
        "模型服务拒绝认证或授权。",
        "检查密钥、接口地址和模型访问权限后重新测试。",
        False,
    ),
    "model_not_found": ("模型或生成接口不存在。", "核对模型名称及生成接口；本地模型需先安装。", False),
    "dns_failed": ("无法解析模型服务地址。", "检查服务地址、DNS 和网络后重新测试。", True),
    "connection_failed": ("无法连接模型服务。", "检查服务是否运行、网络及代理设置；稍后重试。", True),
    "rate_limited": ("模型服务暂时限流。", "遵循服务商等待时间；降低并发后重试。", True),
    "quota_exhausted": (
        "模型服务配额或套餐额度已耗尽。",
        "检查服务商配额和套餐，恢复后创建新的运行尝试。",
        False,
    ),
    "request_timeout": ("模型请求等待超时。", "检查模型负载与请求等待设置；先查看已保存任务状态。", True),
    "upstream_unavailable": ("模型服务暂时不可用。", "查看服务商状态；有限重试失败后稍后再试。", True),
    "output_format": (
        "模型输出缺少正文或不符合要求的格式。",
        "检查输出长度、思考模式和解析诊断；已有产物保留。",
        False,
    ),
    "process_exit": ("仿真子进程异常退出。", "查看该世界最后日志和退出码，排查后创建新的尝试。", False),
    "process_signal": ("仿真子进程被信号终止。", "查看退出信号及系统日志；仅凭信号无法确定终止原因。", False),
    "service_restarted": (
        "服务重启或进程退出，任务已中断。",
        "查看保留产物，重新检查后创建新的尝试。",
        False,
    ),
    "user_stopped": ("任务已由用户停止。", "查看已完成产物；需要重跑时创建新的尝试。", False),
    "budget_exhausted": (
        "实际模型请求已达到批准的硬预算。",
        "查看已完成产物，修订规模或预算后重新批准。",
        False,
    ),
    "provider_wait_exhausted": (
        "模型服务等待时间已达到本次运行上限。",
        "检查限流与 Retry-After；恢复后创建新的尝试。",
        False,
    ),
    "provider_failures_exhausted": (
        "模型连续失败已达到本次运行上限。",
        "查看最近模型故障类别，修复后创建新的尝试。",
        False,
    ),
    "task_failed": ("任务执行失败。", "使用任务标识查看对应阶段日志，排查后再重试。", False),
}


def _chain(exc: BaseException | None) -> list[BaseException]:
    items: list[BaseException] = []
    while exc is not None and len(items) < 8 and all(exc is not prior for prior in items):
        items.append(exc)
        exc = exc.__cause__ or exc.__context__
    return items


def is_quota_error(exc: BaseException) -> bool:
    """Recognize explicit provider quota codes; ordinary 429s remain retryable."""
    for error in _chain(exc):
        response = getattr(error, "response", None)
        if response is None or getattr(response, "status_code", None) not in {402, 403, 429}:
            continue
        # Access only an already-buffered body. Response.content can itself
        # perform network reads, including on a failed streaming request.
        raw = getattr(response, "_content", b"")
        body = raw[:16384].decode("utf-8", errors="replace").lower() if isinstance(raw, bytes) else ""
        if any(marker in body for marker in ("insufficient_quota", "billing_hard_limit", "quota_exceeded")):
            return True
        if response.status_code == 429 and "2062" in body and "token plan" in body:
            return True
    return False


def _identifier(value: Any, secrets: Iterable[str]) -> str:
    text = str(value or "")[:240]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    if re.search(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+|authorization\s*[:=])", text):
        return "[REDACTED]"
    # Identifiers are not addresses: never expose URL credentials or queries.
    if "://" in text or "?" in text or "@" in text:
        return "[REDACTED]"
    return re.sub(r"[\x00-\x1f\x7f]", "", text)[:160]


def classify_error(
    exc: BaseException | None = None,
    *,
    stage: str = "",
    provider: str = "",
    model: str = "",
    attempts: int | None = None,
    exit_code: int | None = None,
    reason_code: str = "",
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Classify a wrapped exception or explicit lifecycle reason without echoing it."""
    errors = _chain(exc)
    statuses = [getattr(getattr(error, "response", None), "status_code", None) for error in reversed(errors)]
    status = next((item for item in statuses if isinstance(item, int)), None)
    code = reason_code if reason_code in _MESSAGES else ""
    for error in errors:
        if not code and getattr(error, "reason_code", "") in _MESSAGES:
            code = getattr(error, "reason_code", "")
        if exit_code is None and isinstance(error, subprocess.CalledProcessError):
            exit_code = error.returncode
    text = " ".join(str(error)[:8000] for error in errors).lower()
    if not code:
        if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
            code = "process_signal" if exit_code < 0 else "process_exit"
        elif exc is not None and is_quota_error(exc):
            code = "quota_exhausted"
        elif status in {401, 403}:
            code = "authentication_failed"
        elif status == 404:
            code = "model_not_found"
        elif status is not None and 300 <= status < 400:
            code = "configuration_missing"
        elif status == 429:
            code = "rate_limited"
        elif status in {408, 504}:
            code = "request_timeout"
        elif status in {425, 500, 502, 503}:
            code = "upstream_unavailable"
        elif any(isinstance(error, socket.gaierror) for error in errors) or any(
            term in text
            for term in (
                "name resolution",
                "nameresolutionerror",
                "getaddrinfo failed",
                "nodename nor servname",
            )
        ):
            code = "dns_failed"
        elif any(isinstance(error, (requests.Timeout, TimeoutError)) for error in errors) or any(
            type(error).__name__ == "ModelWaitTimeout" for error in errors
        ):
            code = "request_timeout"
        elif any(isinstance(error, requests.ConnectionError) for error in errors):
            code = "connection_failed"
        elif (
            any(isinstance(error, json.JSONDecodeError) for error in errors)
            or any(type(error).__name__ == "EmptyCompletionError" for error in errors)
            or any(
                term in text for term in ("可解析的 json", "解析失败", "简报失败预算", "格式修复后仍不可用")
            )
        ):
            code = "output_format"
        elif "没有可用于判定假设的数据" in text:
            code = "no_comparable_data"
        elif "budget_exhausted" in text:
            code = "budget_exhausted"
        elif "等待预算" in text:
            code = "provider_wait_exhausted"
        elif "连续失败预算" in text:
            code = "provider_failures_exhausted"
        elif "服务重启" in text or "任务已中断" in text:
            code = "service_restarted"
        elif text.strip() == "已停止":
            code = "user_stopped"
        elif any(isinstance(error, KeyError) for error in errors) or any(
            term in text
            for term in ("没有拿到密钥", "尚未配置", "not found in config", "没有填 model", "没有填 type")
        ):
            code = "configuration_missing"
        else:
            code = "task_failed"
    message, action, retryable = _MESSAGES[code]
    if any(type(error).__name__ == "ModelWaitTimeout" for error in errors):
        retryable = False
    secret_list = tuple(secrets)
    result: dict[str, Any] = {
        "code": code,
        "stage": _identifier(stage, secret_list),
        "message": message,
        "retryable": retryable,
        "next_action": action,
        "provider": _identifier(provider, secret_list),
        "model": _identifier(model, secret_list),
        "http_status": status,
    }
    if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 0:
        result["attempts"] = attempts
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        result["exit_code"] = exit_code
        if exit_code < 0:
            result["signal"] = -exit_code
    return result
