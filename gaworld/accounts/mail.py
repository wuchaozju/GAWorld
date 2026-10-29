"""Explicit SMTP delivery or an opt-in local development outbox; never fake success."""

from __future__ import annotations

import json
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode, urlparse

from .store import AccountError


def send(email: str, kind: str, token: str) -> None:
    base = os.environ.get("GAWORLD_PUBLIC_URL", "").rstrip("/")
    parsed = urlparse(base)
    development = os.environ.get("GAWORLD_MAIL_MODE") == "outbox"
    if (
        parsed.scheme not in ({"http", "https"} if development else {"https"})
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise AccountError("请配置有效的 GAWORLD_PUBLIC_URL（生产环境须 HTTPS）")
    path = "/verify" if kind == "verify" else "/recover"
    link = base + path + "?" + urlencode({"code": token})
    if development:
        location = os.environ.get("GAWORLD_MAIL_OUTBOX", "")
        if not location:
            raise AccountError("开发邮件出口未配置")
        root = Path(location)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = root / (secrets.token_hex(12) + ".json")
        with target.open("x", encoding="utf-8") as handle:
            os.chmod(target, 0o600)
            json.dump({"to": email, "kind": kind, "link": link}, handle)
        return
    host, sender = os.environ.get("GAWORLD_SMTP_HOST", ""), os.environ.get("GAWORLD_MAIL_FROM", "")
    if not host or not sender:
        raise AccountError("邮件服务未配置，请联系管理员")
    message = EmailMessage()
    message["From"], message["To"] = sender, email
    message["Subject"] = "GAWorld · " + ("验证邮箱" if kind == "verify" else "重设密码")
    message.set_content("请在一小时内打开以下链接：\n" + link)
    try:
        with smtplib.SMTP(host, int(os.environ.get("GAWORLD_SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if os.environ.get("GAWORLD_SMTP_USER"):
                smtp.login(os.environ["GAWORLD_SMTP_USER"], os.environ.get("GAWORLD_SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise AccountError("邮件发送失败，请稍后重新发送") from exc
