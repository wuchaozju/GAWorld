"""Email delivery utilities for backend notifications."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Iterable

from ..core.config import Settings, get_settings
from fos.i18n import T


class EmailSender:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send_email(
        self,
        subject: str,
        recipients: Iterable[str],
        body_text: str,
        *,
        body_html: str | None = None,
    ) -> bool:
        if not self._settings.email_enabled:
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._settings.email_from  # type: ignore[arg-type]
        message["To"] = ", ".join(recipients)
        message.set_content(body_text)
        if body_html is not None:
            message.add_alternative(body_html, subtype="html")

        await asyncio.to_thread(self._deliver, message)
        return True

    async def send_verification_email(self, recipient: str, verification_link: str) -> bool:
        subject = "Verify your FOS account"
        body_text = (
            "Welcome to FOS!\n\n"
            "Click the link below to verify your email address:\n"
            f"{verification_link}\n\n"
            "If you did not create an account, you can ignore this message."
        )
        body_html = (
            "<p>Welcome to FOS!</p>"
            "<p>Click the link below to verify your email address:</p>"
            f"<p><a href='{verification_link}'>Verify your email</a></p>"
            "<p>If you did not create an account, you can ignore this message.</p>"
        )
        return await self.send_email(subject, [recipient], body_text, body_html=body_html)

    def _deliver(self, message: EmailMessage) -> None:
        host = self._settings.email_smtp_host
        port = self._settings.email_smtp_port
        if host is None or port is None:
            raise RuntimeError(T("api.errors.smtp_not_configured"))

        if self._settings.email_smtp_use_ssl:
            context = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            context = smtplib.SMTP(host, port, timeout=30)
            if self._settings.email_smtp_use_tls:
                context.starttls()

        try:
            username = self._settings.email_smtp_username
            password = self._settings.email_smtp_password
            if username and password:
                context.login(username, password.get_secret_value())

            context.send_message(message)
        finally:
            context.quit()
