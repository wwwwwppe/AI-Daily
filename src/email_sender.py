"""
src/email_sender.py  –  Send the rendered HTML email to all recipients.

Supports two backends, selected via the EMAIL_BACKEND env var:
  * "smtp"      – built-in Python smtplib (SSL or STARTTLS)
  * "sendgrid"  – SendGrid Web API v3 via the official SDK
"""
from __future__ import annotations

import logging
import mimetypes
import smtplib
import ssl
from pathlib import Path
from email.mime.image import MIMEImage
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

def _build_smtp_message(
    subject: str,
    html_body: str,
    recipients: list[str],
    inline_images: dict[str, Path] | None = None,
) -> MIMEMultipart:
    from_header = f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>"

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = from_header
    msg["To"] = ", ".join(recipients)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alternative)

    for cid, image_path in (inline_images or {}).items():
        try:
            data = image_path.read_bytes()
        except Exception as exc:
            logger.warning("Failed to read inline image '%s': %s", image_path, exc)
            continue

        mime_type, _ = mimetypes.guess_type(str(image_path))
        subtype = "jpeg"
        if mime_type and "/" in mime_type:
            subtype = mime_type.split("/", 1)[1]
        image_part = MIMEImage(data, _subtype=subtype)
        image_part.add_header("Content-ID", f"<{cid}>")
        image_part.add_header("Content-Disposition", "inline", filename=image_path.name)
        msg.attach(image_part)

    return msg


def _send_smtp(
    subject: str,
    html_body: str,
    recipients: list[str],
    inline_images: dict[str, Path] | None = None,
) -> None:
    if not SMTP_HOST:
        raise ValueError("SMTP_HOST is not configured.")
    if not EMAIL_FROM_ADDRESS:
        raise ValueError("EMAIL_FROM_ADDRESS is not configured.")

    msg = _build_smtp_message(subject, html_body, recipients, inline_images=inline_images)

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

def _send_sendgrid(
    subject: str,
    html_body: str,
    recipients: list[str],
    inline_images: dict[str, Path] | None = None,
) -> None:
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

    if inline_images:
        logger.warning("SendGrid backend currently ignores inline_images attachments.")

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

def send_email(
    subject: str,
    html_body: str,
    inline_images: dict[str, Path] | None = None,
    recipients: list[str] | None = None,
) -> None:
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
    target_recipients = recipients if recipients is not None else RECIPIENTS
    if not target_recipients:
        raise ValueError(
            "No recipients configured. "
            "Set EMAIL_RECIPIENTS in .env or add addresses to config/recipients.txt."
        )

    logger.info(
        "Sending '%s' via %s backend to %d recipient(s)…",
        subject,
        EMAIL_BACKEND,
        len(target_recipients),
    )

    if EMAIL_BACKEND == "sendgrid":
        _send_sendgrid(subject, html_body, target_recipients, inline_images=inline_images)
    elif EMAIL_BACKEND == "smtp":
        _send_smtp(subject, html_body, target_recipients, inline_images=inline_images)
    else:
        raise ValueError(
            f"Unknown EMAIL_BACKEND '{EMAIL_BACKEND}'. Choose 'smtp' or 'sendgrid'."
        )
