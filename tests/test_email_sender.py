"""
tests/test_email_sender.py  –  Unit tests for the email sender module.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.email_sender as sender
from src.email_sender import send_email


SUBJECT = "【AI日报】2025年03月10日 今日科技与AI精选"
HTML = "<html><body><p>test</p></body></html>"


def test_send_raises_when_no_recipients(monkeypatch):
    monkeypatch.setattr(sender, "RECIPIENTS", [])
    with pytest.raises(ValueError, match="No recipients"):
        send_email(SUBJECT, HTML)


def test_send_raises_unknown_backend(monkeypatch):
    monkeypatch.setattr(sender, "RECIPIENTS", ["test@example.com"])
    monkeypatch.setattr(sender, "EMAIL_BACKEND", "unknown_backend")
    with pytest.raises(ValueError, match="Unknown EMAIL_BACKEND"):
        send_email(SUBJECT, HTML)


@patch("src.email_sender.smtplib.SMTP_SSL")
def test_smtp_ssl_backend_called(mock_smtp_ssl, monkeypatch):
    monkeypatch.setattr(sender, "RECIPIENTS", ["a@example.com"])
    monkeypatch.setattr(sender, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", 465)
    monkeypatch.setattr(sender, "SMTP_USE_SSL", True)
    monkeypatch.setattr(sender, "SMTP_USERNAME", "user@example.com")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(sender, "EMAIL_FROM_ADDRESS", "noreply@example.com")
    monkeypatch.setattr(sender, "EMAIL_FROM_NAME", "AI日报")

    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__ = lambda s: mock_server
    mock_smtp_ssl.return_value.__exit__ = MagicMock(return_value=False)

    send_email(SUBJECT, HTML)
    mock_smtp_ssl.assert_called_once()


@patch("src.email_sender.smtplib.SMTP_SSL")
def test_smtp_with_inline_images(mock_smtp_ssl, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sender, "RECIPIENTS", ["a@example.com"])
    monkeypatch.setattr(sender, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", 465)
    monkeypatch.setattr(sender, "SMTP_USE_SSL", True)
    monkeypatch.setattr(sender, "SMTP_USERNAME", "user@example.com")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(sender, "EMAIL_FROM_ADDRESS", "noreply@example.com")
    monkeypatch.setattr(sender, "EMAIL_FROM_NAME", "AI日报")

    image_path = tmp_path / "a.jpg"
    image_path.write_bytes(b"fake-bytes")

    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__ = lambda s: mock_server
    mock_smtp_ssl.return_value.__exit__ = MagicMock(return_value=False)

    send_email(SUBJECT, HTML, inline_images={"img1": image_path})

    sent_raw = mock_server.sendmail.call_args.args[2]
    assert "Content-ID: <img1>" in sent_raw


@patch("src.email_sender.smtplib.SMTP_SSL")
def test_send_email_uses_recipients_override(mock_smtp_ssl, monkeypatch):
    monkeypatch.setattr(sender, "RECIPIENTS", ["default@example.com"])
    monkeypatch.setattr(sender, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", 465)
    monkeypatch.setattr(sender, "SMTP_USE_SSL", True)
    monkeypatch.setattr(sender, "SMTP_USERNAME", "user@example.com")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(sender, "EMAIL_FROM_ADDRESS", "noreply@example.com")
    monkeypatch.setattr(sender, "EMAIL_FROM_NAME", "AI日报")

    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__ = lambda s: mock_server
    mock_smtp_ssl.return_value.__exit__ = MagicMock(return_value=False)

    send_email(SUBJECT, HTML, recipients=["dev@example.com"])

    rcpt_arg = mock_server.sendmail.call_args.args[1]
    assert rcpt_arg == ["dev@example.com"]


@patch("src.email_sender.smtplib.SMTP")
def test_smtp_starttls_backend_called(mock_smtp, monkeypatch):
    monkeypatch.setattr(sender, "RECIPIENTS", ["a@example.com"])
    monkeypatch.setattr(sender, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", 587)
    monkeypatch.setattr(sender, "SMTP_USE_SSL", False)
    monkeypatch.setattr(sender, "SMTP_USERNAME", "user@example.com")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(sender, "EMAIL_FROM_ADDRESS", "noreply@example.com")
    monkeypatch.setattr(sender, "EMAIL_FROM_NAME", "AI日报")

    mock_server = MagicMock()
    mock_smtp.return_value.__enter__ = lambda s: mock_server
    mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

    send_email(SUBJECT, HTML)
    mock_smtp.assert_called_once()


def test_smtp_raises_without_host(monkeypatch):
    monkeypatch.setattr(sender, "RECIPIENTS", ["a@example.com"])
    monkeypatch.setattr(sender, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(sender, "SMTP_HOST", "")
    monkeypatch.setattr(sender, "EMAIL_FROM_ADDRESS", "noreply@example.com")
    with pytest.raises(ValueError, match="SMTP_HOST"):
        send_email(SUBJECT, HTML)
