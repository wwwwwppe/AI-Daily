"""
src/email_sender.py  –  Send the rendered HTML email to all recipients.

Supports two backends, selected via the EMAIL_BACKEND env var:
  * "smtp"      – built-in Python smtplib (SSL or STARTTLS)
  * "sendgrid"  – SendGrid Web API v3 via the official SDK
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.config import (
    EMAIL_BACKEND,
    EMAIL_FROM_ADDRESS,
    EMAIL_FROM_NAME,
    RECIPIENTS,
    SENDGRID_API_KEY,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USERNAME,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SMTP backend
# ─────────────────────────────────────────────────────────────────────────────

def _send_smtp(subject: str, html_body: str, recipients: list[str]) -> None:
    if not SMTP_HOST:
        raise ValueError("SMTP_HOST is not configured.")
    if not EMAIL_FROM_ADDRESS:
        raise ValueError("EMAIL_FROM_ADDRESS is not configured.")

    from_header = f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()

    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM_ADDRESS, recipients, msg.as_string())
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM_ADDRESS, recipients, msg.as_string())

    logger.info("Email sent via SMTP to %d recipient(s).", len(recipients))


# ─────────────────────────────────────────────────────────────────────────────
# SendGrid backend
# ─────────────────────────────────────────────────────────────────────────────

def _send_sendgrid(subject: str, html_body: str, recipients: list[str]) -> None:
    try:
        from sendgrid import SendGridAPIClient  # type: ignore[import]
        from sendgrid.helpers.mail import (  # type: ignore[import]
            Email,
            Mail,
            Personalization,
            To,
        )
    except ImportError as exc:
        raise ImportError(
            "sendgrid package is required for the sendgrid backend. "
            "Install it with: pip install sendgrid"
        ) from exc

    if not SENDGRID_API_KEY:
        raise ValueError("SENDGRID_API_KEY is not configured.")
    if not EMAIL_FROM_ADDRESS:
        raise ValueError("EMAIL_FROM_ADDRESS is not configured.")

    message = Mail(
        from_email=Email(EMAIL_FROM_ADDRESS, EMAIL_FROM_NAME),
        subject=subject,
        html_content=html_body,
    )

    personalization = Personalization()
    for addr in recipients:
        personalization.add_to(To(addr))
    message.add_personalization(personalization)

    client = SendGridAPIClient(SENDGRID_API_KEY)
    response = client.send(message)
    logger.info(
        "Email sent via SendGrid (status %s) to %d recipient(s).",
        response.status_code,
        len(recipients),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> None:
    """
    Send *html_body* to all configured recipients.

    The delivery backend is chosen by the EMAIL_BACKEND env var
    (``"smtp"`` or ``"sendgrid"``).

    Raises
    ------
    ValueError
        When required configuration is missing.
    RuntimeError
        On unexpected delivery errors.
    """
    if not RECIPIENTS:
        raise ValueError(
            "No recipients configured. "
            "Set EMAIL_RECIPIENTS in .env or add addresses to config/recipients.txt."
        )

    logger.info(
        "Sending '%s' via %s backend to %d recipient(s)…",
        subject,
        EMAIL_BACKEND,
        len(RECIPIENTS),
    )

    if EMAIL_BACKEND == "sendgrid":
        _send_sendgrid(subject, html_body, RECIPIENTS)
    elif EMAIL_BACKEND == "smtp":
        _send_smtp(subject, html_body, RECIPIENTS)
    else:
        raise ValueError(
            f"Unknown EMAIL_BACKEND '{EMAIL_BACKEND}'. Choose 'smtp' or 'sendgrid'."
        )
