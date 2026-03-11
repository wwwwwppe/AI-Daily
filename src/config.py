"""
src/config.py  –  Load and expose all configuration.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env from the project root (silently skip if absent – CI uses real secrets)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env", override=False)


# ─────────────────────────────────────────────────────────────────────────────
# Email delivery
# ─────────────────────────────────────────────────────────────────────────────
EMAIL_BACKEND: str = os.getenv("EMAIL_BACKEND", "smtp").lower()

SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT") or "465")
SMTP_USE_SSL: bool = (os.getenv("SMTP_USE_SSL") or "true").lower() == "true"
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")

EMAIL_FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "AI日报")
EMAIL_FROM_ADDRESS: str = os.getenv("EMAIL_FROM_ADDRESS", "")
EMAIL_SUBJECT_TEMPLATE: str = os.getenv(
    "EMAIL_SUBJECT", "【AI日报】{date} 今日科技与AI精选"
)

# ─────────────────────────────────────────────────────────────────────────────
# Recipients
# ─────────────────────────────────────────────────────────────────────────────

def _load_recipients() -> list[str]:
    """Return deduplicated list of recipient addresses."""
    recipients: set[str] = set()

    # 1. From environment variable (comma-separated)
    env_list = os.getenv("EMAIL_RECIPIENTS", "")
    for addr in env_list.split(","):
        addr = addr.strip()
        if addr:
            recipients.add(addr)

    # 2. From config/recipients.txt
    txt_file = _ROOT / "config" / "recipients.txt"
    if txt_file.exists():
        for line in txt_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                recipients.add(line)

    return sorted(recipients)


RECIPIENTS: list[str] = _load_recipients()


# ─────────────────────────────────────────────────────────────────────────────
# News / social sources
# ─────────────────────────────────────────────────────────────────────────────

def _load_sources() -> dict:
    sources_file = _ROOT / "config" / "sources.yaml"
    with sources_file.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_sources = _load_sources()
RSS_SOURCES: list[dict] = _sources.get("rss_sources", [])
TWITTER_ACCOUNTS: list[dict] = _sources.get("twitter_accounts", [])

# ─────────────────────────────────────────────────────────────────────────────
# Twitter / X
# ─────────────────────────────────────────────────────────────────────────────
TWITTER_BEARER_TOKEN: str = os.getenv("TWITTER_BEARER_TOKEN", "")

# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────
# Optional HTTP proxy (e.g. "http://127.0.0.1:7890")
HTTP_PROXY: str = os.getenv("HTTP_PROXY", os.getenv("http_proxy", ""))
HTTPS_PROXY: str = os.getenv("HTTPS_PROXY", os.getenv("https_proxy", HTTP_PROXY))

REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT") or "15")
