"""
src/translator.py  –  Lightweight helpers for English detection and translation.
"""
from __future__ import annotations

import logging
import re

import requests

from src.config import REQUEST_TIMEOUT, TRANSLATE_API_URL

logger = logging.getLogger(__name__)

_ENGLISH_ONLY_RE = re.compile(r"^[A-Za-z0-9\s\.,;:!?\-_'\"()\[\]/&%+#@*$^`~|<>…]+$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def is_english_only(text: str) -> bool:
    """Return True when text looks like plain English content."""
    if not text:
        return False
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return False
    if _CJK_RE.search(normalized):
        return False
    if not re.search(r"[A-Za-z]", normalized):
        return False
    return bool(_ENGLISH_ONLY_RE.fullmatch(normalized))


def translate_to_chinese(text: str) -> str:
    """
    Translate English text to Simplified Chinese.

    Returns an empty string when translation is unavailable.
    """
    if not text:
        return ""
    try:
        resp = requests.get(
            TRANSLATE_API_URL,
            params={
                "client": "gtx",
                "sl": "en",
                "tl": "zh-CN",
                "dt": "t",
                "q": text,
            },
            timeout=min(REQUEST_TIMEOUT, 8),
        )
        resp.raise_for_status()
        payload = resp.json()
        parts = payload[0] if isinstance(payload, list) and payload else []
        translated = "".join(
            part[0] for part in parts if isinstance(part, list) and part and part[0]
        ).strip()
        return translated
    except Exception as exc:
        logger.warning("Translation failed: %s", exc)
        return ""
