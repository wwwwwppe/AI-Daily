"""
tests/test_news_fetcher.py  –  Unit tests for the RSS news fetcher.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import feedparser
import pytest

from src.fetchers.news_fetcher import _parse_date, _strip_html, _truncate, _fetch_feed


# ─────────────────────────────────────────────────────────────────────────────
# _strip_html
# ─────────────────────────────────────────────────────────────────────────────

def test_strip_html_removes_tags():
    assert _strip_html("<p>Hello <strong>world</strong>!</p>") == "Hello world !"


def test_strip_html_plain_text():
    assert _strip_html("plain text") == "plain text"


def test_strip_html_empty():
    assert _strip_html("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# _truncate
# ─────────────────────────────────────────────────────────────────────────────

def test_truncate_short_string():
    assert _truncate("short", 300) == "short"


def test_truncate_long_string():
    text = "word " * 200  # 1000 chars
    result = _truncate(text, 300)
    assert len(result) <= 301  # may include the ellipsis char
    assert result.endswith("…")


# ─────────────────────────────────────────────────────────────────────────────
# _parse_date
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_date_from_published_parsed():
    entry = MagicMock()
    entry.published_parsed = (2025, 3, 10, 12, 0, 0, 0, 0, 0)
    entry.updated_parsed = None
    entry.created_parsed = None
    assert _parse_date(entry) == "2025-03-10"


def test_parse_date_missing():
    entry = MagicMock()
    entry.published_parsed = None
    entry.updated_parsed = None
    entry.created_parsed = None
    assert _parse_date(entry) == ""


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_feed  (mocked feedparser)
# ─────────────────────────────────────────────────────────────────────────────

def _make_entry(title, link, summary, pub_parsed=None):
    e = MagicMock()
    e.title = title
    e.link = link
    e.summary = summary
    e.description = ""
    e.published_parsed = pub_parsed
    e.updated_parsed = None
    e.created_parsed = None
    return e


@patch("src.fetchers.news_fetcher.feedparser.parse")
def test_fetch_feed_returns_articles(mock_parse):
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_entry(
            "AI breakthrough",
            "https://example.com/1",
            "<p>Great news about AI.</p>",
            (2025, 3, 10, 0, 0, 0, 0, 0, 0),
        )
    ]
    mock_parse.return_value = mock_feed

    source = {"name": "Test Feed", "url": "https://example.com/feed", "max_items": 5}
    articles = _fetch_feed(source)

    assert len(articles) == 1
    assert articles[0]["title"] == "AI breakthrough"
    assert articles[0]["url"] == "https://example.com/1"
    assert articles[0]["source"] == "Test Feed"
    assert articles[0]["published"] == "2025-03-10"
    assert "Great news about AI" in articles[0]["summary"]


@patch("src.fetchers.news_fetcher.feedparser.parse")
def test_fetch_feed_respects_max_items(mock_parse):
    mock_feed = MagicMock()
    mock_feed.entries = [
        _make_entry(f"Article {i}", f"https://example.com/{i}", "summary")
        for i in range(10)
    ]
    mock_parse.return_value = mock_feed

    source = {"name": "Test Feed", "url": "https://example.com/feed", "max_items": 3}
    articles = _fetch_feed(source)
    assert len(articles) == 3


@patch("src.fetchers.news_fetcher.feedparser.parse", side_effect=Exception("network error"))
def test_fetch_feed_handles_error_gracefully(mock_parse):
    source = {"name": "Broken Feed", "url": "https://broken.example.com/feed"}
    articles = _fetch_feed(source)
    assert articles == []
