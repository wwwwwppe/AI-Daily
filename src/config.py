"""
src/config.py  –  Load and expose all configuration.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv


def _get_base_dir() -> Path:
    """Get base directory: supports both dev and PyInstaller one-file mode."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller one-file mode: _MEIPASS is the temp dir with bundled files
        # But we also want to look for .env in the exe's directory
        return Path(sys.executable).parent
    else:
        # Dev mode: project root
        return Path(__file__).parent.parent


def _get_bundled_data_dir() -> Path:
    """Get directory where bundled data files live."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def _get_runtime_data_dir(base_dir: Path, bundled_data_dir: Path) -> Path:
    """Prefer editable external config near executable/project; fallback to bundled data."""
    external_config_dir = base_dir / "config"
    if external_config_dir.exists() and external_config_dir.is_dir():
        return base_dir
    return bundled_data_dir


def _resolve_config_file(base_dir: Path, bundled_data_dir: Path, filename: str) -> Path:
    """Resolve config file with external-first lookup and bundled fallback."""
    candidates = [
        base_dir / "config" / filename,
        bundled_data_dir / "config" / filename,
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return candidates[0]


_BASE_DIR = _get_base_dir()
_BUNDLED_DATA_DIR = _get_bundled_data_dir()
_DATA_DIR = _get_runtime_data_dir(_BASE_DIR, _BUNDLED_DATA_DIR)

# Load .env from exe directory (or project root in dev)
load_dotenv(_BASE_DIR / ".env", override=False)


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
    txt_file = _resolve_config_file(_BASE_DIR, _BUNDLED_DATA_DIR, "recipients.txt")
    if txt_file.exists():
        for line in txt_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                recipients.add(line)

    return sorted(recipients)


RECIPIENTS: list[str] = _load_recipients()


def _parse_csv_env(name: str) -> list[str]:
    values: list[str] = []
    raw = os.getenv(name, "")
    for part in raw.split(","):
        part = part.strip()
        if part:
            values.append(part)
    return values


DEVELOPER_ALERT_RECIPIENTS: list[str] = _parse_csv_env("DEVELOPER_ALERT_RECIPIENTS")


# ─────────────────────────────────────────────────────────────────────────────
# News / social sources
# ─────────────────────────────────────────────────────────────────────────────

def _load_sources() -> dict:
    sources_file = _resolve_config_file(_BASE_DIR, _BUNDLED_DATA_DIR, "sources.yaml")
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

# Report window: include content published within [yesterday HH:00, today HH:00)
REPORT_WINDOW_MODE: str = (os.getenv("REPORT_WINDOW_MODE") or "rolling").strip().lower()
REPORT_WINDOW_HOUR: int = int(os.getenv("REPORT_WINDOW_HOUR") or "8")
REPORT_WINDOW_TZ_OFFSET: int = int(os.getenv("REPORT_WINDOW_TZ_OFFSET") or "8")

# Translation
ENABLE_ENGLISH_TRANSLATION: bool = (
    (os.getenv("ENABLE_ENGLISH_TRANSLATION") or "true").lower() == "true"
)
TRANSLATE_API_URL: str = os.getenv(
    "TRANSLATE_API_URL",
    "https://translate.googleapis.com/translate_a/single",
)

# DeepSeek (optional, for my-news markdown generation)
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL: str = os.getenv(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"
)
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TIMEOUT: int = int(os.getenv("DEEPSEEK_TIMEOUT") or "60")

# my-news generation output limit (provider-specific hard caps still apply)
MY_NEWS_MAX_TOKENS: int = int(os.getenv("MY_NEWS_MAX_TOKENS") or "0")
MY_NEWS_REQUIRED_MARKER: str = os.getenv("MY_NEWS_REQUIRED_MARKER", "- 导读 -")
MY_NEWS_MAX_WAIT_SECONDS: int = int(os.getenv("MY_NEWS_MAX_WAIT_SECONDS") or "600")
MY_NEWS_RETRY_INTERVAL_SECONDS: int = int(
    os.getenv("MY_NEWS_RETRY_INTERVAL_SECONDS") or "20"
)
MY_NEWS_PRUNE_INVALID_SOURCE_ITEMS: bool = (
    (os.getenv("MY_NEWS_PRUNE_INVALID_SOURCE_ITEMS") or "false").lower() == "true"
)

