"""
src/fetchers/news_fetcher.py  –  Fetch articles from RSS / Atom feeds.

Each article is returned as a dict::

    {
        "title":       str,
        "url":         str,   # original article link
        "source":      str,   # human-readable feed name
        "published":   str,   # ISO-8601 date string or empty
        "summary":     str,   # plain-text excerpt (≤ 300 chars)
    }
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from src.config import HTTP_PROXY, HTTPS_PROXY, REQUEST_TIMEOUT, RSS_SOURCES

logger = logging.getLogger(__name__)

_PROXIES: dict | None = (
    {"http": HTTP_PROXY, "https": HTTPS_PROXY}
    if HTTP_PROXY or HTTPS_PROXY
    else None
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = BeautifulSoup(raw, "lxml").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate(text: str, max_len: int = 300) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def _parse_date(entry) -> str:
    """Return an ISO-8601 date string from a feedparser entry, or ''."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                dt = datetime(*value[:6], tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    return ""


def _fetch_feed(source: dict) -> list[dict]:
    """Fetch a single RSS feed and return a list of article dicts."""
    name: str = source.get("name", "Unknown")
    url: str = source.get("url", "")
    max_items: int = int(source.get("max_items", 5))

    articles: list[dict] = []
    try:
        # Pass the raw URL to feedparser; use requests for proxy support if needed
        if _PROXIES:
            resp = requests.get(url, proxies=_PROXIES, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        else:
            feed = feedparser.parse(url)

        for entry in feed.entries[:max_items]:
            link = getattr(entry, "link", "")
            if not link:
                continue

            title = getattr(entry, "title", "(no title)")
            raw_summary = (
                getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or ""
            )
            summary = _truncate(_strip_html(raw_summary))
            published = _parse_date(entry)

            articles.append(
                {
                    "title": title.strip(),
                    "url": link.strip(),
                    "source": name,
                    "published": published,
                    "summary": summary,
                }
            )
    except Exception as exc:
        logger.warning("Failed to fetch feed '%s' (%s): %s", name, url, exc)

    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_news() -> list[dict]:
    """
    Fetch articles from all configured RSS sources.

    Returns a flat list of article dicts sorted by source order.
    """
    all_articles: list[dict] = []
    for source in RSS_SOURCES:
        items = _fetch_feed(source)
        logger.info("Fetched %d articles from '%s'", len(items), source.get("name"))
        all_articles.extend(items)
    return all_articles
