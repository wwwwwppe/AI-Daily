from __future__ import annotations

from datetime import datetime, timezone

from main import (
    _MAX_DAILY_ITEMS,
    _append_translation_for_english_content,
    _filter_items_for_window,
    _get_report_window,
)


def test_filter_items_for_window_only_keeps_items_inside_range():
    start_utc = datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    items = [
        {"title": "in-range", "published_at": "2026-03-14T12:00:00Z"},
        {"title": "start-boundary", "published_at": "2026-03-14T00:00:00Z"},
        {"title": "end-boundary", "published_at": "2026-03-15T00:00:00Z"},
        {"title": "unknown", "published": ""},
    ]

    filtered = _filter_items_for_window(items, start_utc, end_utc)

    assert [item["title"] for item in filtered] == ["in-range", "start-boundary"]


def test_daily_total_limit_is_10_items():
    start_utc = datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    articles = [
        {"id": i, "published_at": f"2026-03-14T12:{i:02d}:00Z"} for i in range(12)
    ]
    tweets = [{"id": i, "published_at": f"2026-03-14T13:{i:02d}:00Z"} for i in range(5)]

    filtered_articles = _filter_items_for_window(articles, start_utc, end_utc)
    filtered_tweets = _filter_items_for_window(tweets, start_utc, end_utc)

    limited_articles = filtered_articles[:_MAX_DAILY_ITEMS]
    limited_tweets = filtered_tweets[: max(0, _MAX_DAILY_ITEMS - len(limited_articles))]

    assert len(limited_articles) + len(limited_tweets) == 10
    assert len(limited_articles) == 10
    assert len(limited_tweets) == 0


def test_report_window_defaults_to_yesterday_8_to_today_8_for_utc8():
    now_utc = datetime(2026, 3, 15, 2, 30, tzinfo=timezone.utc)  # UTC+8 = 10:30
    start_utc, end_utc = _get_report_window(now_utc, 8, 8)

    assert start_utc == datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)


def test_append_translation_for_english_content(monkeypatch):
    monkeypatch.setattr("src.translator.is_english_only", lambda text: text.startswith("Hello world"))
    monkeypatch.setattr(
        "src.translator.translate_to_chinese",
        lambda text: "" if text == "Hello world (fail)" else "你好，世界",
    )

    items = [
        {"summary": "Hello world"},
        {"summary": "你好世界"},
        {"summary": "", "title": "Hello world"},
        {"summary": "Hello world (fail)"},
    ]
    enriched = _append_translation_for_english_content(
        items, "summary", fallback_text_key="title"
    )

    assert enriched[0]["translation"] == "你好，世界"
    assert "translation" not in enriched[1]
    assert enriched[2]["translation"] == "你好，世界"
    assert enriched[3]["translation"] == "（翻译服务暂时不可用）"
