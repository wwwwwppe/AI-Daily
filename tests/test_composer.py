"""
tests/test_composer.py  –  Unit tests for the email composer.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.composer import render_email


SAMPLE_ARTICLES = [
    {
        "title": "OpenAI Releases GPT-5",
        "url": "https://openai.com/blog/gpt-5",
        "source": "OpenAI Blog",
        "published": "2025-03-10",
        "summary": "OpenAI today announced the release of GPT-5…",
    },
    {
        "title": "Google DeepMind Achieves New Benchmark",
        "url": "https://deepmind.com/blog/benchmark",
        "source": "DeepMind Blog",
        "published": "2025-03-10",
        "summary": "",  # empty summary is valid
    },
]

SAMPLE_TWEETS = [
    {
        "author": "Sam Altman",
        "username": "sama",
        "text": "Excited to share our latest research on alignment.",
        "url": "https://twitter.com/sama/status/123456789",
        "published": "2025-03-10",
    }
]


def test_render_returns_subject_and_html():
    subject, html = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert isinstance(subject, str)
    assert isinstance(html, str)
    assert len(subject) > 0
    assert len(html) > 0


def test_subject_contains_date():
    subject, _ = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert "2025" in subject
    assert "03" in subject or "3" in subject


def test_html_contains_article_titles():
    _, html = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert "OpenAI Releases GPT-5" in html
    assert "Google DeepMind Achieves New Benchmark" in html


def test_html_contains_article_urls():
    _, html = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert "https://openai.com/blog/gpt-5" in html
    assert "https://deepmind.com/blog/benchmark" in html


def test_html_contains_tweet_text():
    _, html = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert "Excited to share our latest research" in html
    assert "https://twitter.com/sama/status/123456789" in html


def test_html_contains_sources():
    _, html = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert "OpenAI Blog" in html
    assert "DeepMind Blog" in html


def test_render_with_no_tweets():
    """Should render without errors when no tweets are available."""
    subject, html = render_email(SAMPLE_ARTICLES, [], date(2025, 3, 10))
    assert "OpenAI Releases GPT-5" in html
    # Tweet section should not appear
    assert "AI 大V 观点" not in html


def test_render_with_no_articles():
    """Should render without errors when no articles are provided."""
    subject, html = render_email([], SAMPLE_TWEETS, date(2025, 3, 10))
    assert "Sam Altman" in html
    # Article titles should not be rendered when articles list is empty
    assert "OpenAI Releases GPT-5" not in html
    assert "Google DeepMind Achieves New Benchmark" not in html


def test_html_is_valid_html_structure():
    _, html = render_email(SAMPLE_ARTICLES, SAMPLE_TWEETS, date(2025, 3, 10))
    assert html.strip().startswith("<!DOCTYPE html>")
    assert "</html>" in html
